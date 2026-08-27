"""One live cartridge session: a worker thread, one slot, and a lifecycle.

Shared, and shared deliberately. Two cartridges now need the same three
properties around an engine that is synchronous, blocking and expensive,
and the properties are subtle enough that two implementations would
diverge in ways nobody would notice until a physical test:

**1. Nothing expensive on the event loop.** The connection handler calls
`offer_frame` inline, per frame, on the loop. All it may do is replace a
slot and signal. Every millisecond of model work happens on the worker.

**2. A dropped frame must be visible.** There is ONE slot, and a frame
offered while the worker is busy replaces the one waiting rather than
queueing behind it -- a backlog answers "what is around me now" with the
past, and `tower/results/publisher.py` reaches the same conclusion about
its own single slot: "a newer one answers the same question better". The
displaced frame increments `frames_skipped`, which is on the wire,
because a silently dropped frame is indistinguishable from a quiet room.

**3. A load that is abandoned must not install itself.** `stop()` during
a model load cannot kill the loading thread; nothing in Python can. It
closes a `LoadInvalidation` latch and the worker checks it before
publishing what it built, so a load that finishes after its session
stopped releases its own model instead of installing it into a session
nobody is watching. That is the module container's guard, reused rather
than reinvented.

WHAT THIS BASE MUST NEVER DO

Write anything, of any kind. Document Memory's session legitimately
persists -- through its own engine, in its own package, which is where
its retention and purge surface already lives. Scene Understanding's must
not, and `test_scene_understanding_persists_nothing` scans this file
along with the rest of that cartridge's wire path. So the rule here is
absolute regardless of which subclass is running: this file counts,
schedules and hands over. It does not open, write, or name a path.

WHAT A SUBCLASS PROVIDES

    _create()                 build and LOAD the engine. Blocking, on the
                              worker thread, and allowed to take seconds.
    _consume(engine, raw, at, seq)
                              one frame. Blocking. Whatever it returns is
                              handed to `_publish`.
    _publish(result, at, now) record what `_consume` produced, under the
                              session lock. Keep it to assignments.
    _teardown(engine)         release. Must not raise; if it does, it is
                              logged and swallowed.
    _extra_status()           cartridge-specific counters, under the
                              session lock, merged into `status()`.
    _on_pause(engine)         optional. Runs OFF the lock when a running
                              session is paused or stopped, for work that
                              must not be lost -- Document Memory flushes
                              an open dwell here.
"""

import logging
import threading
import time

from tower.loading import LoadInvalidation

logger = logging.getLogger(__name__)

# Lifecycle states. Strings, not an enum, because they cross a wire and a
# consumer compares them for equality -- the same reason contract
# identifiers are opaque strings in `tower/results/contracts.py`.
#
# `starting` is separate from `running` because a model load takes
# seconds and a client that cannot tell "loading" from "running and
# seeing nothing" renders an empty room during startup.
STATE_STOPPED = "stopped"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_FAILED = "failed"

LIFECYCLE_STATES = (
    STATE_STOPPED,
    STATE_STARTING,
    STATE_RUNNING,
    STATE_PAUSED,
    STATE_FAILED,
)

# How long a load may take before the session says so. NOT a kill: the
# thread keeps loading and may still succeed. This is the point at which
# `starting` stops being reassuring and becomes reportable, so an
# operator can tell a slow first-run weight download from a wedge.
#
# 120 s matches `tower/modules/container.py: LOAD_TIMEOUT_S` and matches
# it deliberately: a first-run weight download is the same work whichever
# cartridge pays for it, and two different answers to "how long is too
# long" would be two different answers to one question.
LOAD_OVERDUE_S = 120.0

# How long `stop()` waits for the worker to notice. A worker is either
# idle on the condition (immediate) or inside one unit of work (33 ms for
# a detection, ~1.2 s for a page of OCR), so this is generous. It is a
# bound rather than an unbounded join because `stop()` is reachable from
# an HTTP handler, and a handler that can hang is a Tower that can hang.
STOP_JOIN_TIMEOUT_S = 5.0


def decode_frame(raw_bytes):
    """JPEG bytes to a BGR array, or None. Used by whoever wants pixels.

    Imported inside the function for the reason `tower/detection.py`
    gives for torch: a heavy dependency at module import time makes every
    consumer of this module pay for it.

    Returns None rather than raising. A malformed frame is an ordinary
    event on a wireless link, and losing a session over one would be the
    same defect both engines already refuse to have.
    """
    import cv2
    import numpy as np

    if not raw_bytes:
        return None
    try:
        buffer = np.frombuffer(raw_bytes, dtype=np.uint8)
        return cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except Exception:
        logger.exception("live session: a frame could not be decoded; dropping it")
        return None


class LiveSession:
    """The lifecycle. Subclasses supply the work.

    Thread model: one `threading.Condition` guards every mutable field.
    Producers -- `offer_frame` and the lifecycle verbs -- hold it briefly.
    The worker holds it only to take work and to publish a result, never
    across `_consume`. Nothing here blocks a caller for longer than a
    dictionary update.
    """

    #: Prefix for the worker thread's name, so a stack dump says which
    #: cartridge is inside a model load.
    name = "live"

    def __init__(
        self,
        *,
        clock=time.time,
        follow_stream: bool = False,
        load_overdue_s: float = LOAD_OVERDUE_S,
        stop_join_timeout_s: float = STOP_JOIN_TIMEOUT_S,
    ) -> None:
        self._clock = clock
        self._follow_stream = bool(follow_stream)
        # WHICH connections started this session by streaming.
        #
        # A set, not a flag, and it took a second review to get here. A
        # bool was wrong in both directions: it stayed True across a
        # manual stop, so an operator's hand-started session was killed
        # by the next phone that dropped -- verbatim the failure
        # `stream_closed` claims to prevent -- and it carried no identity,
        # so with two phones streaming, the first to disconnect stopped
        # the session out from under the second.
        #
        # `ws.py` already carries a `connection_token` and hands it to
        # `_stop_capture` as `owner=` for exactly this reason. The
        # cartridge hooks now take the same token.
        self._stream_owners: set = set()
        # True while a lifecycle caller is on its way to releasing the
        # engine. The WORKER reads it: without it, `_loop` returns the
        # instant `_stopping` is set, and its `finally` released the
        # engine while `stop()`'s flush was still inside it -- the same
        # torn-down-under-a-live-call defect as before, arriving from the
        # other thread. Found by the test written for the first version.
        self._teardown_pending = False
        # Serialises the lifecycle verbs against each other. SEPARATE
        # from `_condition`, and deliberately: a flush may take a page of
        # OCR and must not be run holding the lock `offer_frame` takes on
        # the event loop -- but two callers must still not be inside
        # teardown at once. Without this, a `pause()` whose flush was in
        # flight and a concurrent `stop()` released the engine underneath
        # it, because the second caller saw a state that was no longer
        # RUNNING, skipped the flush and the join, and went straight to
        # the release.
        self._lifecycle = threading.Lock()
        self._load_overdue_s = load_overdue_s
        self._stop_join_timeout_s = stop_join_timeout_s

        self._condition = threading.Condition(threading.Lock())
        self._state = STATE_STOPPED
        self._failure_reason: str | None = None
        self._session_id: int = 0
        self._started_at: float | None = None
        self._load_started_at: float | None = None
        self._ready_at: float | None = None

        self._engine = None
        self._thread: threading.Thread | None = None
        self._invalidation: LoadInvalidation | None = None
        # The single slot. `(raw_bytes, received_at, source_seq)`, or None.
        self._pending = None
        self._stopping = False

        self._frames_offered = 0
        self._frames_observed = 0
        self._frames_skipped = 0
        self._frames_dropped_not_running = 0

    # -- lifecycle -----------------------------------------------------

    def start(self, *, resume_paused: bool = True) -> dict:
        """Begin a session. Returns immediately; the engine loads off-thread.

        Idempotent in the direction the callers mean it. Both plausible
        ones -- an operator pressing a button twice, a client
        reconnecting -- mean "make sure this is on".

        Starting a PAUSED session resumes it, for the same reason.
        Starting a FAILED one begins a fresh session, because a failure
        that can only be cleared by a stop nobody thought to call is a
        Tower that needs restarting.

        `resume_paused=False` withholds ONLY the PAUSED -> RUNNING
        promotion, and exists because one caller is not a person. See
        `stream_opened`: a socket connecting must not undo a Pause a
        wearer asked for. It is a keyword argument rather than a separate
        method so the decision is made inside this lock -- a caller that
        checked the state first and then called `start()` would have a
        window in which a Pause landing between the two is silently
        resumed, which is the bug in a smaller form.
        """
        with self._condition:
            if self._state in (STATE_RUNNING, STATE_STARTING):
                return self._status_locked()
            if self._state == STATE_PAUSED:
                if not resume_paused:
                    return self._status_locked()
                self._state = STATE_RUNNING
                self._condition.notify_all()
                return self._status_locked()
            self._begin_session_locked()
            return self._status_locked()

    def follows_stream(self) -> bool:
        return self._follow_stream

    def pause(self) -> dict:
        """Stop consuming frames; keep the engine loaded.

        The engine stays loaded: pausing to release a model would make
        Pause cost more than Stop, which is backwards.

        Serialised against `stop()` by `_lifecycle`, so a `stop()` cannot
        release the engine while this one's flush is still inside it.
        """
        with self._lifecycle:
            return self._pause_locked()

    def _pause_locked(self) -> dict:
        with self._condition:
            engine = self._engine
            was_running = self._state in (STATE_RUNNING, STATE_STARTING)
            if was_running:
                self._state = STATE_PAUSED
                self._pending = None
        if was_running and engine is not None:
            self._safely(self._on_pause, engine, what="pause")
        with self._condition:
            return self._status_locked()

    def resume(self) -> dict:
        with self._condition:
            if self._state == STATE_PAUSED:
                self._state = STATE_RUNNING
                self._condition.notify_all()
            return self._status_locked()

    def stop(self) -> dict:
        """End the session.

        THE ORDER OF THE FOUR STEPS BELOW IS THE WHOLE CORRECTNESS OF
        THIS METHOD, and it was wrong once in a way worth recording.

        1. **Close the door.** `_stopping`, `STOPPED` and an empty slot,
           under the lock, FIRST.
        2. **Then flush**, off the lock.
        3. **Then join the worker.**
        4. **Then release the engine.**

        Steps 1 and 2 used to be the other way round -- flush first,
        state second -- and an adversarial review measured what that
        costs. `_on_pause` for Document Memory is `engine.flush()`, which
        runs OCR: 1.19 s a page, up to two pages. For that entire window
        the state was still `running`, so `offer_frame` kept accepting
        frames and the worker kept calling `engine.observe()` on the SAME
        engine the flushing thread was inside. Two threads, one
        `DwellTracker`, no lock. Traced, with a real stop against a live
        stream:

            http-stop   flush   ENTER
            worker      observe ENTER     <- inside flush
            worker      observe ENTER     <- inside flush
            http-stop   flush   EXIT

        The visible damage was not a crash. It was TWO document memories
        of one page, with overlapping observation windows and no field
        linking them, because `_find_duplicate` only dedupes within a
        dwell and the race produced two.

        Steps 3 and 4 were also inverted. `LoadInvalidation` covers a
        worker stuck in `_create()`; it does nothing for a worker inside
        `_consume()`, so releasing before joining tore the model down
        underneath a live forward pass -- `torch.cuda.empty_cache()`
        racing an allocation on CUDA, and `EasyOcrRecogniser._reader =
        None` mid-`read()`. Joining first means the worker is out of
        `_consume` before anything is released, and the latch still
        covers the case where the join times out.

        Counters are kept until the next `start()`, so an operator can
        still read what the session did after it ended. What a subclass
        does with its RESULT is its own decision, and the two cartridges
        differ: a scene expires the moment nobody is looking, a document
        memory does not.

        Held under `_lifecycle` for its whole duration, so a concurrent
        `pause()` or `stop()` waits rather than releasing the engine that
        this one's flush is still inside.
        """
        with self._lifecycle:
            return self._stop_locked()

    def _stop_locked(self) -> dict:
        with self._condition:
            engine = self._engine
            thread = self._thread
            invalidation = self._invalidation
            was_active = self._state in (STATE_RUNNING, STATE_STARTING)
            # Step 1. Nothing new enters the engine after this line.
            self._stopping = True
            self._state = STATE_STOPPED
            self._pending = None
            self._thread = None
            # Claimed BEFORE the flush, so the worker's own teardown
            # stands down and lets this caller release after the join.
            self._teardown_pending = True
            # A manual stop disowns the stream. Without this the flag
            # survived into the NEXT session -- one an operator started
            # by hand -- and the next disconnect stopped it.
            self._stream_owners.clear()
            self._on_stop_locked()
            self._condition.notify_all()

        if was_active and engine is not None:
            # Step 2. Off the lock, because a flush may cost a page of
            # OCR, and the session lock is taken by `offer_frame` on the
            # event loop.
            self._safely(self._on_pause, engine, what="stop")

        if thread is not None and thread is not threading.current_thread():
            # Step 3. Before the release, so nothing is torn down under a
            # forward pass that is still running.
            thread.join(timeout=self._stop_join_timeout_s)
            if thread.is_alive():
                # It is inside a model load, which cannot be interrupted.
                # The latch below guarantees it installs nothing and
                # releases what it built, so this is a delay in
                # reclaiming memory rather than a leak. Said out loud
                # because a silent one would be indistinguishable.
                logger.warning(
                    "[Tower][%s] the session worker did not exit within "
                    "%.1fs; it is inside a model load or a frame, and has "
                    "been abandoned. It will release its own engine, and "
                    "anything it commits after this point is attributed "
                    "to no session.",
                    self.name,
                    self._stop_join_timeout_s,
                )

        if invalidation is not None:
            # Step 4. Closed OUTSIDE the condition: `invalidate` takes
            # its own lock and runs a teardown under it, and nesting two
            # locks in opposite orders in two threads is the deadlock
            # this repository has already paid for once -- see the note
            # on reentrancy in `tower/loading.py`.
            invalidation.invalidate(self._release_engine)

        with self._condition:
            self._teardown_pending = False
            return self._status_locked()

    # -- the frame path ------------------------------------------------

    def offer_frame(
        self,
        raw_bytes,
        *,
        received_at: float | None = None,
        source_seq: int | None = None,
    ) -> None:
        """Hand the session one frame. Never blocks, never raises.

        Called from the connection handler, on the event loop, once per
        delivered frame.

        NEWEST WINS. When the worker is busy the frame already waiting is
        discarded, not this one.

        `source_seq` is the sender's own sequence number and is carried
        so a cartridge that records something can say WHICH FRAME it read
        it from. Scene Understanding ignores it -- a per-frame pointer
        into a recording is exactly the joinable handle it refuses to
        publish -- and Document Memory puts it on every page it stores,
        because a memory with no provenance cannot be checked.
        """
        with self._condition:
            self._frames_offered += 1
            if self._state != STATE_RUNNING:
                self._frames_dropped_not_running += 1
                return
            if self._pending is not None:
                self._frames_skipped += 1
            at = self._clock() if received_at is None else received_at
            self._pending = (raw_bytes, at, source_seq)
            self._condition.notify()

    def stream_opened(self, owner=None) -> None:
        """The glasses began streaming. Start, if this session follows.

        The reason this hook exists is a defect an adversarial review
        found: nothing on the wire could start a session.
        `IOS-to-Tower.md` 6.2 is explicit that opening a cartridge on the
        phone sends NOTHING -- "a test asserts the wire stays silent" --
        so a session only an HTTP POST could start was a contract offered
        as `available: true` that a phone could subscribe to and would
        watch report "not observing" forever.

        `stream_start` is the right signal and not merely an available
        one. It is the moment a feed exists, and a cartridge whose whole
        claim is "what is around me now" has nothing to say before it.
        `ws.py` already treats the same pair as the session boundary for
        the dataset recorder.

        Starting an already-running session is a no-op, so a second
        `stream_start` does not restart anything -- but it does mark the
        session as the stream's, which is correct: from here on the
        stream is what keeps it alive.

        A PAUSED SESSION IS NOT RESUMED HERE, and that is the one place
        this hook departs from `start()`. `start()` promotes PAUSED ->
        RUNNING on the stated grounds of "an operator pressing a button
        twice" -- a deliberate human act. A `stream_start` is not that; it
        is a socket connecting, and it can arrive from a reconnect, a
        second phone, or a Mac running a physical test. Scene
        Understanding detects people in a room and is on by default, so
        the old behaviour meant a wearer who paused it had that pause
        undone by any new connection, with nobody asking.

        Object Memory reaches the same answer by construction: its gate is
        re-asked at every `capture_opened`, so a paused session stays
        paused across any number of new captures. This makes the two
        cartridges agree.

        Ownership is still recorded, so a later `stream_stop` is scoped
        correctly whether or not this call started anything.
        """
        if not self._follow_stream:
            return
        self.start(resume_paused=False)
        with self._condition:
            self._stream_owners.add(owner)

    def stream_closed(self, owner=None) -> None:
        """The stream ended. Stop, but ONLY what the stream started.

        The symmetry matters more than the start: a session started by a
        stream and never stopped by one would hold a model and park a
        worker for as long as the Tower ran, and -- for Scene
        Understanding -- keep serving a scene of a room whose wearer
        walked out of range.

        The ownership check matters just as much in the other direction,
        and in two ways. `ws.py` tears the stream down on ANY exit,
        including a disconnect from a client that never sent
        `stream_start` at all -- so an unconditional stop would let any
        passing connection end a session an operator started by hand for
        a physical test. And with two phones streaming, the first to
        disconnect must not stop the session out from under the second,
        which is why this is a SET of owners and stops only when the last
        one leaves.
        """
        with self._condition:
            was_owner = owner in self._stream_owners
            self._stream_owners.discard(owner)
            last_one_out = was_owner and not self._stream_owners
        if self._follow_stream and last_one_out:
            self.stop()

    def capture_started(self, capture_id) -> None:
        """A dataset capture opened, and this is its id.

        Called from the connection handler on `stream_start`, and only
        when a recorder is armed. It is how a cartridge that records
        something learns the lineage of the frames it is about to see:
        the capture id does not exist until a phone connects, so nothing
        can be told it in advance.

        A no-op by default. Scene Understanding has no use for it --
        there is nothing for a capture id to be provenance FOR when
        nothing is written.
        """

    def capture_stopped(self, capture_id) -> None:
        """That capture closed. Later frames belong to no recording."""

    # -- reading -------------------------------------------------------

    def status(self) -> dict:
        with self._condition:
            return self._status_locked()

    @property
    def state(self) -> str:
        with self._condition:
            return self._state

    # -- hooks ---------------------------------------------------------

    def _create(self):
        raise NotImplementedError

    def _consume(self, engine, raw_bytes, received_at, source_seq):
        raise NotImplementedError

    def _publish(self, result, received_at: float, now: float) -> None:
        """Record what `_consume` produced. Called under the lock."""

    #: Whether `_consume` may already have had an effect the session
    #: cannot take back -- a row appended to a store, most obviously.
    #:
    #: False for Scene Understanding: a `SceneState` that arrives after a
    #: Pause describes a moment nobody asked about and is correctly
    #: thrown away.
    #:
    #: True for Document Memory, and the difference is not a preference.
    #: `engine.observe()` has ALREADY written the document by the time
    #: this loop reaches its publish guard, so declining to publish does
    #: not discard it -- it only hides it. A review measured exactly
    #: that: two documents on disk, `documents_recorded: 1`.
    commits_during_consume = False

    def _teardown(self, engine) -> None:
        release = getattr(engine, "release", None)
        if release is not None:
            release()

    def _extra_status(self) -> dict:
        """Cartridge-specific counters. Called under the lock."""
        return {}

    def _on_pause(self, engine) -> None:
        """Work that must not be lost when observation stops."""

    def _on_start_locked(self) -> None:
        """Reset cartridge-specific counters. Called under the lock."""

    def _on_stop_locked(self) -> None:
        """Discard, or keep, whatever the subclass holds. Under the lock."""

    def _engine_name(self, engine) -> str | None:
        return None

    # -- internals -----------------------------------------------------

    def _safely(self, function, *args, what: str) -> None:
        try:
            function(*args)
        except Exception:
            logger.exception("[Tower][%s] %s hook failed", self.name, what)

    def _begin_session_locked(self) -> None:
        self._session_id += 1
        self._state = STATE_STARTING
        self._failure_reason = None
        self._started_at = self._clock()
        self._load_started_at = self._started_at
        self._ready_at = None
        self._stopping = False
        self._pending = None
        self._frames_offered = 0
        self._frames_observed = 0
        self._frames_skipped = 0
        self._frames_dropped_not_running = 0
        self._engine_label = None
        # A fresh session owns nothing until a stream claims it.
        self._stream_owners.clear()
        self._on_start_locked()
        self._invalidation = LoadInvalidation()
        self._thread = threading.Thread(
            target=self._run,
            args=(self._session_id, self._invalidation),
            name=f"tower-{self.name}-session-{self._session_id}",
            daemon=True,
        )
        self._thread.start()

    def _status_locked(self) -> dict:
        now = self._clock()
        loading_for = (
            None
            if self._load_started_at is None or self._ready_at is not None
            else max(now - self._load_started_at, 0.0)
        )
        status = {
            "state": self._state,
            "states": list(LIFECYCLE_STATES),
            "session_id": self._session_id,
            "failure_reason": self._failure_reason,
            "started_at": self._started_at,
            "ready_at": self._ready_at,
            "loading_seconds": loading_for,
            # True only while STARTING. A load that has already succeeded
            # is not overdue however long it took.
            "load_overdue": bool(
                self._state == STATE_STARTING
                and loading_for is not None
                and loading_for > self._load_overdue_s
            ),
            "load_overdue_after_seconds": self._load_overdue_s,
            "engine": getattr(self, "_engine_label", None),
            "frames_offered": self._frames_offered,
            "frames_observed": self._frames_observed,
            "frames_skipped": self._frames_skipped,
            "frames_dropped_not_running": self._frames_dropped_not_running,
        }
        status.update(self._extra_status())
        return status

    def _release_engine(self) -> None:
        """Release whatever is installed. Runs under the latch's lock.

        Must not touch this object's condition: `LoadInvalidation` calls
        this while holding its own non-reentrant lock, and reaching back
        into the session lock from here is a lock-order inversion against
        `_run`, which takes the session lock and then publishes through
        the latch.
        """
        engine, self._engine = self._engine, None
        if engine is None:
            return
        try:
            self._teardown(engine)
        except Exception:
            logger.exception("[Tower][%s] an engine failed to release", self.name)

    def _run(self, session_id: int, invalidation: LoadInvalidation) -> None:
        engine = None
        try:
            engine = self._create()
        except Exception as exc:
            reason = f"the engine could not be loaded: {type(exc).__name__}: {exc}"
            logger.exception("[Tower][%s] %s", self.name, reason)
            if engine is not None:
                try:
                    self._teardown(engine)
                except Exception:
                    logger.exception(
                        "[Tower][%s] a failed engine also failed to release",
                        self.name,
                    )
            with self._condition:
                if self._session_id == session_id:
                    self._state = STATE_FAILED
                    self._failure_reason = reason
                    self._thread = None
            return

        if not invalidation.publish(lambda: setattr(self, "_engine", engine)):
            # Stopped while loading. We hold the only reference, so we own
            # the release -- the stop that would have done it has already
            # run. `tower/loading.py: publish` states this contract.
            try:
                self._teardown(engine)
            except Exception:
                logger.exception(
                    "[Tower][%s] an abandoned engine failed to release", self.name
                )
            return

        with self._condition:
            if self._session_id == session_id and not self._stopping:
                self._engine_label = self._engine_name(engine)
                self._ready_at = self._clock()
                if self._state == STATE_STARTING:
                    self._state = STATE_RUNNING

        try:
            self._loop(session_id, engine)
        finally:
            with self._condition:
                # A `stop()` that has already claimed the teardown will
                # release after it has joined this thread. Releasing here
                # would tear the engine down underneath the flush that
                # stop is still running.
                stop_will_release = self._teardown_pending
            if not stop_will_release:
                invalidation.invalidate(self._release_engine)
            with self._condition:
                if self._session_id == session_id and self._thread is not None:
                    self._thread = None

    def _loop(self, session_id: int, engine) -> None:
        while True:
            with self._condition:
                while (
                    not self._stopping
                    and self._session_id == session_id
                    and self._pending is None
                ):
                    self._condition.wait()
                if self._stopping or self._session_id != session_id:
                    return
                work, self._pending = self._pending, None

            raw_bytes, received_at, source_seq = work
            try:
                # Outside the lock, deliberately. This is the expensive
                # call, and holding the session lock across it would make
                # `offer_frame` -- which runs on the event loop -- wait
                # for it.
                result = self._consume(
                    engine, raw_bytes, received_at, source_seq
                )
            except Exception:
                logger.exception(
                    "[Tower][%s] a frame failed; the session continues",
                    self.name,
                )
                continue

            now = self._clock()
            with self._condition:
                stale = self._session_id != session_id or self._stopping
                paused = self._state != STATE_RUNNING
                if (stale or paused) and not self.commits_during_consume:
                    # A result produced while the session was paused
                    # describes a moment nobody asked about, and is
                    # discarded rather than published.
                    if stale:
                        return
                    continue
                if self._session_id != session_id:
                    # An ABANDONED worker from a previous session. It has
                    # already written something, and there is nowhere
                    # honest to put that: publishing into the session
                    # that is current now would credit session 2 with a
                    # document session 1 recorded, and would produce a
                    # status where `frames_observed` exceeds
                    # `frames_offered` -- reproduced, in exactly that
                    # shape. The divergence between the disk and the
                    # counters is real either way; a log line is where it
                    # belongs, not in another session's numbers.
                    logger.warning(
                        "[Tower][%s] an abandoned worker from session %s "
                        "committed after session %s began; what it wrote "
                        "is on disk and is counted by neither",
                        self.name,
                        session_id,
                        self._session_id,
                    )
                    return
                # `commits_during_consume` reaches here having ALREADY
                # written something. Not publishing would not unwrite it;
                # it would only make the counters disagree with the disk,
                # which is the one outcome nobody could debug.
                self._frames_observed += 1
                self._publish(result, received_at, now)
                if stale:
                    return
