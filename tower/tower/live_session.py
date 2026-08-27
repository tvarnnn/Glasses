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
        load_overdue_s: float = LOAD_OVERDUE_S,
        stop_join_timeout_s: float = STOP_JOIN_TIMEOUT_S,
    ) -> None:
        self._clock = clock
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

    def start(self) -> dict:
        """Begin a session. Returns immediately; the engine loads off-thread.

        Idempotent in the direction the callers mean it. Both plausible
        ones -- an operator pressing a button twice, a client
        reconnecting -- mean "make sure this is on".

        Starting a PAUSED session resumes it, for the same reason.
        Starting a FAILED one begins a fresh session, because a failure
        that can only be cleared by a stop nobody thought to call is a
        Tower that needs restarting.
        """
        with self._condition:
            if self._state in (STATE_RUNNING, STATE_STARTING):
                return self._status_locked()
            if self._state == STATE_PAUSED:
                self._state = STATE_RUNNING
                self._condition.notify_all()
                return self._status_locked()
            self._begin_session_locked()
            return self._status_locked()

    def pause(self) -> dict:
        """Stop consuming frames; keep the engine loaded.

        The engine stays loaded: pausing to release a model would make
        Pause cost more than Stop, which is backwards.
        """
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

        Counters are kept until the next `start()`, so an operator can
        still read what the session did after it ended. What a subclass
        does with its RESULT is its own decision and the two cartridges
        differ: a scene expires the moment nobody is looking, a document
        memory does not.
        """
        with self._condition:
            engine = self._engine
            was_active = self._state in (STATE_RUNNING, STATE_STARTING)

        if was_active and engine is not None:
            # Before the state flips, and outside the lock: this is where
            # a subclass finishes work that would otherwise be lost, and
            # it may take as long as one unit of work.
            self._safely(self._on_pause, engine, what="stop")

        with self._condition:
            thread = self._thread
            invalidation = self._invalidation
            self._stopping = True
            self._state = STATE_STOPPED
            self._pending = None
            self._thread = None
            self._on_stop_locked()
            self._condition.notify_all()

        if invalidation is not None:
            # Closed OUTSIDE the condition: `invalidate` takes its own
            # lock and runs a teardown under it, and nesting two locks in
            # opposite orders in two threads is the deadlock this
            # repository has already paid for once -- see the note on
            # reentrancy in `tower/loading.py`.
            invalidation.invalidate(self._release_engine)

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._stop_join_timeout_s)
            if thread.is_alive():
                # It is inside a model load, which cannot be interrupted.
                # The latch above guarantees it installs nothing and
                # releases what it built, so this is a delay in
                # reclaiming memory rather than a leak. Said out loud
                # because a silent one would be indistinguishable.
                logger.warning(
                    "[Tower][%s] the session worker did not exit within "
                    "%.1fs; it is inside a model load and has been "
                    "abandoned. It will release its own engine.",
                    self.name,
                    self._stop_join_timeout_s,
                )

        with self._condition:
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
                if self._session_id != session_id or self._stopping:
                    return
                # A result produced while the session was paused is
                # discarded rather than published: it was in flight when
                # the operator said stop looking.
                if self._state != STATE_RUNNING:
                    continue
                self._frames_observed += 1
                self._publish(result, received_at, now)
