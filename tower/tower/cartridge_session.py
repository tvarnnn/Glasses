"""Start, Pause and Stop for a cartridge that produces out of process.

**Why this is shared code rather than one cartridge's.** Every producer
in this repository runs in its own process and tails a capture journal --
World Builder, Scene, Document Memory and Object Memory all do. None of
them had a way for a wearer to say "start remembering" or "stop", because
the only thing that ever started a producer was a human typing a command.
The first cartridge to need the button would have built it privately, and
the second would have built it again slightly differently. So the state
machine lives here, knows no cartridge, and is handed a worker NAME.

**What a session is not.**

  * Not a capture. The capture id is minted by the phone's
    `stream_start` and is shared by everything watching the camera; a
    session says what one cartridge DOES about it.
  * Not persisted. A Tower that restarts comes back `stopped`. Resuming
    a memory of what a camera sees, without anybody asking again, is the
    wrong direction to fail in -- and the alternative, a state file,
    would be a promise this process could not keep across a crash.
  * Not the producer. It starts and stops one. Whether a process is
    actually alive is the supervisor's answer, and `snapshot()` reports
    that separately from the state, because "the wearer asked for this"
    and "it is happening" are different claims and the gap between them
    is exactly the failure worth showing.

**Three states, and the reason there is no fourth.** `stopped`, `active`,
`paused`. There is no `starting`: attaching is a `Popen` and a dict
update, and a transient state that no client can ever observe is a state
that only exists to be got wrong.

**SERIALISED, because the transport is concurrent.** The routes are sync
`def` so a five-second detach stays off the event loop, which means
FastAPI runs them in its threadpool and two actions can be in flight at
once. Unserialised, a Stop arriving while a Start was between "set
ACTIVE" and "attach" left the session `stopped` with a producer running
-- and `stop()` from `stopped` returned early without detaching, so a
second Stop could not recover it. The one control a wearer has over being
remembered failed OPEN. A reviewer reproduced it: `state=stopped`,
`following=['cap-1']`, live pid.

Every action holds the lock for its whole duration, including the
attach and the detach. That makes a Pause take as long as stopping a
process takes and makes a concurrent Start wait for it, which is correct:
these are a person pressing buttons, not a hot path.
"""

import logging
import threading
import uuid

logger = logging.getLogger(__name__)

STOPPED = "stopped"
ACTIVE = "active"
PAUSED = "paused"

STATES = (STOPPED, ACTIVE, PAUSED)

START = "start"
PAUSE = "pause"
RESUME = "resume"
STOP = "stop"

ACTIONS = (START, PAUSE, RESUME, STOP)

# How long a producer gets to exit on its own before Pause or Stop
# terminates it.
#
# ZERO, and the five seconds it used to be were worse than useless.
# Nothing SIGNALS the producer: it is a follower tailing a journal that
# is still being written, so it has no reason to stop and never does.
# The wait measured 5.01 seconds every single time, and then the process
# was terminated anyway -- so the grace bought exactly nothing and cost a
# wearer five seconds of a control whose whole purpose is to stop
# recording NOW. Worse, a Start arriving inside that window used to
# return 200 `active` and then find itself paused.
#
# What the grace was supposed to protect is a half-written JSONL line.
# The store already tolerates one: `_read_raw_records` skips a line that
# is not valid JSON, and `prune_expired` rewrites it out. Losing at most
# the record being appended at the instant of a Pause is the right trade
# against a Pause that takes five seconds to be obeyed.
#
# `shutdown` keeps its own, longer grace, because there the capture has
# CLOSED and the follower really will finish and exit by itself.
DETACH_GRACE_SECONDS = 0.0


class SessionRefused(Exception):
    """An action this session cannot honour from the state it is in.

    Carries a `reason` short enough to be a wire value and a `message`
    long enough to be read by a person, because the transport has to
    serve both and inventing the split at the route would put half the
    vocabulary somewhere no test looks.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class CartridgeSession:
    """One cartridge's Start/Pause/Stop, over a capture it does not own.

    `open_capture` is a callable returning `(capture_id, capture_dir)` for
    whatever is recording right now, or None. Injected rather than
    reached for, because the recorder lives behind `app.state` and this
    class must stay testable without an app -- and because a session that
    imported the recorder would make the recorder's absence an
    AttributeError on the wearer's Start button.
    """

    def __init__(
        self,
        *,
        cartridge: str,
        worker: str,
        supervisor,
        open_capture,
        clock,
        detach_grace_seconds: float = DETACH_GRACE_SECONDS,
    ) -> None:
        self._cartridge = cartridge
        self._worker = worker
        self._supervisor = supervisor
        self._open_capture = open_capture
        self._clock = clock
        self._detach_grace_seconds = detach_grace_seconds

        # Held for the whole of every action, attach and detach
        # included. See the module docstring: the transport is concurrent
        # and the failure was open.
        self._lock = threading.RLock()
        self._state = STOPPED
        self._session_id: str | None = None
        self._started_at: float | None = None
        self._changed_at: float | None = None
        # Every capture this session's worker has been seen following, in
        # the order they were first seen. Accumulated rather than
        # declared: a session started before the walk attaches nothing
        # itself -- the capture opens later and the supervisor consults
        # the gate -- so the only honest source is what the supervisor
        # says it is actually following.
        self._captures: list[str] = []

    # -- what the gate asks -------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def is_active(self) -> bool:
        """The predicate handed to the worker spec as its gate.

        A plain bool and nothing else. `capture_opened` runs on the
        connection that just received `stream_start`, so this is on the
        frame path's critical section and must not read a file, take a
        lock, or raise.
        """
        return self._state == ACTIVE

    @property
    def supported(self) -> bool:
        """Whether this Tower has a producer to start at all.

        False on a Tower where the cartridge is switched off. Reported
        rather than hidden: a Start button that silently does nothing is
        worse than one that says why it cannot.
        """
        try:
            return self._worker in self._supervisor.worker_names()
        except Exception:
            logger.exception(
                "[Tower][Session] could not ask the supervisor about worker %r",
                self._worker,
            )
            return False

    # -- actions -------------------------------------------------------

    def apply(self, action: str) -> dict:
        """Run a named action. The one entry point a transport needs."""
        if action == START:
            return self.start()
        if action == PAUSE:
            return self.pause()
        if action == RESUME:
            return self.resume()
        if action == STOP:
            return self.stop()
        raise SessionRefused(
            "unknown-action",
            f"{action!r} is not an action; expected one of {', '.join(ACTIONS)}",
        )

    def start(self) -> dict:
        """Begin remembering. From `stopped` or `paused`, and idempotent.

        `start` is deliberately accepted from `paused` as well as from
        `stopped`, while `resume` is not accepted from `stopped`. The
        asymmetry is on purpose: Start is what a wearer presses, and it
        should mean "be running" whatever the app thought the state was,
        whereas Resume is a claim about continuing something and should
        not quietly invent a session that was never started.
        """
        with self._lock:
            self._require_supported()
            if self._state == ACTIVE:
                return self._result(changed=False)
            if self._state == STOPPED:
                self._session_id = uuid.uuid4().hex
                self._started_at = self._clock()
                self._captures = []
            return self._go_active()

    def resume(self) -> dict:
        with self._lock:
            self._require_supported()
            if self._state == ACTIVE:
                return self._result(changed=False)
            if self._state != PAUSED:
                raise SessionRefused(
                    "not-paused",
                    "there is no paused session to resume; this cartridge is "
                    f"{self._state}",
                )
            return self._go_active()

    def pause(self) -> dict:
        """Stop remembering, keep the session.

        Pausing DETACHES the producer rather than signalling it to idle.
        The alternative was a control file the producer polls, and it was
        rejected: it would give the web process a write into the
        cartridge's own directory, add a second source of truth for
        whether the cartridge is running, and leave a stale "active" file
        behind after a crash. Stopping the process makes the pause
        observable in the process table, costs one model load to undo,
        and cannot go stale.

        It is also PROMPT. See DETACH_GRACE_SECONDS: the producer is not
        signalled and has no reason to exit on its own, so waiting for it
        bought nothing and cost a wearer five seconds of a control whose
        whole purpose is to stop recording now.

        What that costs is the producer's in-memory state -- which track
        was open, which class was last recorded. Losing it errs towards
        one extra honest observation after a resume, never towards a
        suppressed real one, which is the direction this cartridge
        already errs on restart.
        """
        with self._lock:
            self._require_supported()
            if self._state == PAUSED:
                return self._result(changed=False)
            if self._state != ACTIVE:
                raise SessionRefused(
                    "not-active",
                    f"there is nothing to pause; this cartridge is {self._state}",
                )
            self._detach()
            self._state = PAUSED
            self._changed_at = self._clock()
            return self._result(changed=True)

    def stop(self) -> dict:
        """End the session. Never refused, from any state.

        Whatever a confused client believes, "stop" is a request to end
        up stopped, and it can always be honoured. Refusing it would
        leave the only way out of a bad state being a Tower restart.

        Observations already written are untouched. Stopping ends the
        producing, not the memory.

        IT ALWAYS DETACHES, EVEN FROM `stopped`. This used to return
        early when the state was already `stopped`, on the reasonable
        view that there was nothing to do -- and that made the one
        recoverable state unrecoverable. Stop means "end up with nothing
        recording", and the only way to keep that promise is to check.
        Detaching when nothing is attached costs a dictionary lookup.
        """
        with self._lock:
            already_stopped = self._state == STOPPED
            self._detach()
            self._state = STOPPED
            self._session_id = None
            self._started_at = None
            if already_stopped:
                return self._result(changed=False)
            self._changed_at = self._clock()
            return self._result(changed=True)

    # -- reporting -----------------------------------------------------

    def snapshot(self) -> dict:
        """Everything a client needs to draw the cartridge honestly.

        Accumulating `captures` here means a read has a side effect, and
        that is the lesser evil. The alternative is a callback from the
        supervisor into every session, which would put a cartridge's
        bookkeeping on the connection that handles `stream_start`; this
        way the frame path stays untouched and the list is refreshed
        exactly when somebody is looking.
        """
        following = self._following()
        for capture_id in following:
            if capture_id not in self._captures:
                self._captures.append(capture_id)
        return {
            "cartridge": self._cartridge,
            "worker": self._worker,
            "supported": self.supported,
            "state": self._state,
            "session_id": self._session_id,
            "started_at": self._started_at,
            "changed_at": self._changed_at,
            # What the wearer asked for is `state`. What is actually
            # happening is this. An ACTIVE session with an empty
            # `following` while a capture is recording is a producer that
            # died, and the phone should be able to say so.
            "following": following,
            "captures": list(self._captures),
        }

    # -- internals -----------------------------------------------------

    def _require_supported(self) -> None:
        if not self.supported:
            raise SessionRefused(
                "unsupported",
                f"this Tower has no {self._cartridge} producer configured, so "
                "there is nothing to start",
            )

    def _go_active(self) -> dict:
        self._state = ACTIVE
        self._changed_at = self._clock()
        attached = self._attach()
        result = self._result(changed=True)
        result["attached_capture_id"] = attached
        return result

    def _attach(self) -> str | None:
        """Attach to whatever is recording NOW, if anything.

        Deliberately re-asked on every start and resume rather than
        remembered. A pause long enough to matter is long enough for the
        phone to have reconnected, and a session that re-attached to the
        capture it remembered would follow a directory nothing is writing
        to any more.
        """
        try:
            current = self._open_capture()
        except Exception:
            logger.exception(
                "[Tower][Session] could not find out what is recording; %s is "
                "%s and will attach when the next capture opens",
                self._cartridge,
                self._state,
            )
            return None
        if current is None:
            return None
        capture_id, capture_dir = current
        try:
            started = self._supervisor.attach(self._worker, capture_id, capture_dir)
        except Exception:
            logger.exception(
                "[Tower][Session] could not attach the %s worker to capture %s",
                self._worker,
                capture_id,
            )
            return None
        if not started:
            # Either one was already following -- which is fine and
            # common, a Start pressed twice -- or the spawn failed, which
            # the supervisor has already logged loudly. Neither is a
            # reason to refuse the wearer's Start, and `following` in the
            # snapshot tells the two apart.
            return None
        return capture_id

    def _detach(self) -> None:
        try:
            self._supervisor.detach(
                self._worker, grace_seconds=self._detach_grace_seconds
            )
        except Exception:
            # The state change goes ahead regardless. Closing the gate is
            # what stops the NEXT capture being followed, and a session
            # that refused to move because a terminate failed would keep
            # attaching a producer to every future capture.
            logger.exception(
                "[Tower][Session] could not stop the %s worker; the gate is "
                "closed and no new capture will be followed",
                self._worker,
            )

    def _following(self) -> list[str]:
        try:
            return list(self._supervisor.following(self._worker))
        except Exception:
            logger.exception(
                "[Tower][Session] could not ask the supervisor what worker %r "
                "is following",
                self._worker,
            )
            return []

    def _result(self, *, changed: bool) -> dict:
        result = self.snapshot()
        result["changed"] = changed
        result.setdefault("attached_capture_id", None)
        return result
