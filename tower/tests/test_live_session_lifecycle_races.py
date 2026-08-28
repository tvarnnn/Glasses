"""Lifecycle races in the shared live-session base, each reproduced first.

These are integration findings 13 and 15, carried open since the
2026-08-27 unification and deferred by the runtime-fitness lane because
fixing them meant touching `stop()`, whose docstring calls its four-step
ordering "the whole correctness of this method" and records what both
previous inversions cost.

The shape they share is the one the unification's final reviewer named:
every falsifiable NUMBER in that lane held, and every claim that failed
was about **lifecycle ownership or session scope** -- written from design
intent rather than read off a running object. So these tests drive two
threads at a real session and read what actually happened.

`_on_pause` is the window in both. It is what `stop()` runs at step 2,
off the lock, and for Document Memory it is `engine.flush()` -- an OCR
pass measured at 1.19 s a page, up to two pages. So this window is
SECONDS wide in the product, not microseconds. Blocking it on an event
here is not an artificial widening; it is the ordinary case held still.
"""

import threading
import time

import pytest

from tower.live_session import STATE_RUNNING, STATE_STOPPED
from tower.scene.live import SceneLive


class _Engine:
    """Loads instantly, carries no torch, and records its own release.

    The LIFECYCLE is under test, not the model -- the same reason
    `tests/test_unified_lifecycle_regressions.py` uses a stub engine.
    Identity matters here in a way it does not there, so each instance
    is numbered and remembers whether it was released.
    """

    _made = 0

    def __init__(self) -> None:
        _Engine._made += 1
        self.ident = _Engine._made
        self.released = False

    def load(self):
        return None

    def observe(self, frame, received_at, source_seq):
        return None

    def release(self):
        self.released = True


class _BlockingFlush(SceneLive):
    """Scene, but its stop-time flush is held open on an event."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.flush_entered = threading.Event()
        self.release_flush = threading.Event()

    def _on_pause(self, engine):
        self.flush_entered.set()
        assert self.release_flush.wait(15), "the test never released the flush"


def _await_state(session, want, timeout=10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.state == want:
            return True
        time.sleep(0.005)
    return False


def _session(cls=SceneLive):
    return cls(_Engine, decode=lambda raw: raw, follow_stream=True)


class TestAStopStillFlushing:
    """Integration finding 13, reproduced.

    `stop()` holds `_lifecycle` for all four of its steps. `start()`
    takes only `_condition`. Step 1 sets STOPPED under `_condition` and
    RELEASES it; steps 2 (flush), 3 (join) and 4 (release) run outside
    it. A `start()` landing in that window sees STOPPED and stands up a
    second session -- and step 4 then reached for `self._engine`, which
    by then is the SECOND session's.
    """

    def test_a_stop_releases_the_engine_it_captured_not_the_current_one(self):
        session = _session(_BlockingFlush)

        session.start()
        assert _await_state(session, STATE_RUNNING)
        engine1 = session._engine

        stopper = threading.Thread(target=session.stop, name="http-stop")
        stopper.start()
        assert session.flush_entered.wait(10), "stop() never reached its flush"

        # A wearer pressing Start, or a phone reconnecting. The state is
        # already STOPPED, so nothing refuses this.
        session.start()
        assert _await_state(session, STATE_RUNNING)
        engine2 = session._engine
        assert engine2 is not engine1, "session 2 must build its own engine"

        session.release_flush.set()
        stopper.join(15)
        assert not stopper.is_alive()

        assert engine1.released, (
            "the stopping session's own engine was never released: it "
            "leaked, and the model it holds is never returned"
        )
        assert not engine2.released, (
            "the stop released the NEXT session's engine. That session is "
            "still running and now has no model behind it"
        )
        assert session._engine is engine2, (
            "the running session lost its engine reference; every frame "
            "it is offered now fails inside _consume and is swallowed by "
            "'a frame failed; the session continues', while status() "
            "still reports running and carries no field that says so"
        )
        assert session.state == STATE_RUNNING


class TestStopThenStart:
    """Integration finding 15, reproduced.

    `stop()` clears `_stream_owners` ("a manual stop disowns the
    stream") and `_begin_session_locked` clears it again ("a fresh
    session owns nothing until a stream claims it"). Neither re-adopts a
    stream that is STILL OPEN, so after Stop -> Start on the HTTP routes
    the session is owned by nobody.

    This is a privacy defect and not only a resource one. Scene
    Understanding's whole subject is detecting PEOPLE, and "keeps
    observing after the wearer's phone disconnects, and cannot be
    stopped by disconnecting" is a claim about the product, not about
    the process table.

    XFAIL, STRICT, AND DELIBERATELY NOT FIXED HERE.

    The reproduction is kept in the suite rather than in a scratch
    directory because it is real and because the next person to touch
    this should inherit it running, not a paragraph describing it.
    `strict=True` means this turns into a FAILURE the moment somebody
    fixes the defect, which is the prompt to delete the marker.

    It is not fixed here because the mechanical fix is not obviously the
    right one, and this is a hardening lane. `stop()` clearing
    `_stream_owners` is DELIBERATE and is itself a fix: the comment on
    `_stream_owners` records that a surviving flag meant "an operator's
    hand-started session was killed by the next phone that dropped --
    verbatim the failure `stream_closed` claims to prevent". So the two
    defects are opposite ends of one decision:

        adopt too eagerly -> a passing connection stops a session an
                             operator started by hand
        adopt not at all  -> a stream-started session, once restarted
                             over HTTP, can never be stopped by the
                             stream again

    Choosing between them means deciding whether an HTTP `start()` while
    a stream is open should be owned by that stream. That is a product
    decision about iOS-facing lifecycle semantics, it needs the set of
    OPEN streams tracked separately from the set of OWNING ones, and it
    is not a decision an optimization pass gets to make on its own.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "integration finding 15, reproduced and open: after Stop -> "
            "Start on the HTTP routes the session is owned by nobody, so "
            "the stream closing cannot stop it. Fixing it needs open "
            "streams tracked apart from owning ones, which is a product "
            "decision -- see this class's docstring"
        ),
    )
    def test_a_restarted_session_is_still_stopped_by_its_stream_closing(self):
        token = "connection-token-A"
        session = _session()

        session.stream_opened(owner=token)
        assert _await_state(session, STATE_RUNNING), (
            "Scene follows the stream, so a phone connecting starts it"
        )

        session.stop()
        session.start()
        assert _await_state(session, STATE_RUNNING)

        # The SAME phone -- never disconnected -- now drops.
        session.stream_closed(owner=token)

        assert _await_state(session, STATE_STOPPED, timeout=5.0), (
            "the stream that started this session closed and the session "
            "is still running: it is owned by nobody, keeps consuming "
            "frames and holding its model, and no disconnect can stop it. "
            "Only an explicit HTTP Stop can -- which is exactly the state "
            "a wearer cannot reach by putting the glasses down"
        )
