"""Regressions found by the two shared-runtime reviewers of the 2026-08-27 unification.

Both defects existed on a lane branch and neither was reachable there,
because each needed something the OTHER lane brought: a second worker spec
to contend the supervisor's lock, and a live cartridge that follows the
stream while a wearer can pause it. Merging four lanes is what made them
real, so the tests that pin them live with the integration rather than in
any one lane's file.

Each test was proven RED against the pre-fix code before being kept.
"""

import asyncio
import threading
import time

import pytest

from tower.live_session import STATE_PAUSED, STATE_RUNNING, STATE_STOPPED


class _StubEngine:
    """Loads instantly and observes nothing. The LIFECYCLE is under test,
    not the model, so this deliberately carries no torch."""

    def load(self):
        return None

    def observe(self, frame, received_at, source_seq):
        return None

    def release(self):
        return None


def _session():
    """A real `SceneLive` -- the cartridge that actually has this bug --
    over a stub engine.

    `SceneLive` rather than the `LiveSession` base because the base is not
    constructible on its own, and because Scene Understanding is the
    cartridge whose `follow_stream` defaults ON and which detects PEOPLE.
    Testing the base class would prove the mechanism and miss the product.
    """
    from tower.scene.live import SceneLive

    return SceneLive(_StubEngine, decode=lambda raw: raw, follow_stream=True)


# -- Reviewer A, finding 4 ---------------------------------------------


def test_a_new_stream_does_not_resume_a_session_the_wearer_paused():
    """A socket connecting is not a person pressing a button.

    `start()` promotes PAUSED -> RUNNING on the stated grounds of "an
    operator pressing a button twice". `stream_opened` used to call it
    unconditionally, so a wearer who paused Scene Understanding -- which
    detects PEOPLE, and follows the stream by default -- had that pause
    undone by any new connection: a reconnect, a second phone, or a Mac
    running a physical test. Nobody asked, and nothing said so.

    Object Memory reaches the right answer by construction: its gate is
    re-asked at every `capture_opened`, so a paused session stays paused
    across any number of new captures. This makes the two agree.
    """
    session = _session()
    try:
        session.stream_opened(owner="phone-a")
        assert session.status()["state"] in (STATE_RUNNING, "starting")

        session.pause()
        assert session.status()["state"] == STATE_PAUSED

        # A third connection arrives. The wearer has not touched anything.
        session.stream_opened(owner="phone-c")
        assert session.status()["state"] == STATE_PAUSED, (
            "a stream_start resumed a session the wearer paused"
        )
    finally:
        session.stop()


def test_an_operator_pressing_start_still_resumes_a_paused_session():
    """The other half, so the fix above cannot be 'never resume'.

    An explicit Start is a person's decision and must still work, or
    Pause becomes a one-way door out of which only Stop leads.
    """
    session = _session()
    try:
        session.start()
        session.pause()
        assert session.status()["state"] == STATE_PAUSED

        session.start()
        assert session.status()["state"] in (STATE_RUNNING, "starting")
    finally:
        session.stop()


def test_a_stream_start_still_starts_a_stopped_session():
    """And the fix must not break the reason `stream_opened` exists.

    Nothing on the wire could start a session before this hook: opening a
    cartridge on the phone sends nothing, and a test asserts the wire
    stays silent. Withholding only the PAUSED promotion must leave that
    intact.
    """
    session = _session()
    try:
        assert session.status()["state"] == STATE_STOPPED
        session.stream_opened(owner="phone-a")
        assert session.status()["state"] in (STATE_RUNNING, "starting")
    finally:
        session.stop()


# -- Reviewer A, finding 1 ---------------------------------------------


class _StubSupervisor:
    """A supervisor whose `capture_opened` blocks, the way a real one does
    while `detach` holds its lock across a terminate-and-wait."""

    def __init__(self, block_seconds: float) -> None:
        self._block = block_seconds
        self.calls = 0

    def capture_opened(self, capture_id, capture_dir, continues=None):
        self.calls += 1
        time.sleep(self._block)


class _StubObserver:
    """The dataset recorder's shape, reduced to what `_start_capture` uses."""

    is_recording = False

    def resumable_capture(self):
        return None

    def start(self, owner=None, continues=None):
        return "cap-1"

    def capture_dir(self, capture_id):
        return f"/tmp/{capture_id}"


class _StubState:
    def __init__(self, supervisor):
        self.capture_workers = supervisor
        self.frame_observers = [_StubObserver()]
        self.frame_consumers = []
        self.live_cartridges = None


class _StubApp:
    def __init__(self, supervisor):
        self.state = _StubState(supervisor)


class _StubWebSocket:
    def __init__(self, supervisor):
        self.app = _StubApp(supervisor)


def test_starting_a_capture_does_not_block_the_event_loop():
    """`capture_opened` is the one supervisor call that ran ON THE LOOP.

    Since the supervisor became multi-spec its lock is contended by Pause
    and Stop, whose `detach` holds it across a `terminate()` and a bounded
    `process.wait()`. A producer that ignores SIGTERM therefore blocked
    `stream_start` for up to the terminate timeout PER SPEC -- and on the
    event loop that is the whole Tower: no frames, no pings, no /health,
    on every connection. Reviewer A measured 1.95 s with one stubborn
    worker.

    This drives the REAL `_start_capture`, not a hand-rolled `to_thread`
    around the inner helper -- a test that does its own offloading would
    pass against the very code it is meant to catch. It asserts the
    property that matters: while a capture is being attached, the loop
    still runs other work. Against the pre-fix code the heartbeat scores
    0.
    """
    from tower.routes import ws as ws_module

    supervisor = _StubSupervisor(block_seconds=0.5)
    websocket = _StubWebSocket(supervisor)
    ticks = 0

    async def scenario():
        nonlocal ticks

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        await ws_module._start_capture(websocket, owner="conn-1")
        beat.cancel()

    asyncio.run(scenario())

    assert supervisor.calls == 1, "the supervisor was never told a capture opened"
    # 0.5 s of blocking against a 10 ms heartbeat. A frozen loop scores 0;
    # a healthy one scores tens. The bar sits far below the ideal so this
    # cannot flake on a loaded box.
    assert ticks >= 5, (
        f"the event loop advanced only {ticks} times while a capture was "
        "attaching; the attach is blocking the loop"
    )


def test_a_supervisor_that_raises_does_not_end_the_stream():
    """Attaching a worker is a side errand and must stay one.

    Unchanged by the fix, and pinned here because moving the call
    off-thread is exactly the kind of change that loses an except.
    """
    from tower.routes.ws import _offer_capture_opened

    class _Angry:
        def capture_opened(self, *args, **kwargs):
            raise RuntimeError("no")

    # Must not raise.
    _offer_capture_opened(_Angry(), "cap-1", "/tmp/cap-1", None)


def test_offering_a_capture_to_no_supervisor_is_a_no_op():
    from tower.routes.ws import _offer_capture_opened

    _offer_capture_opened(None, "cap-1", "/tmp/cap-1", None)


# -- Reviewer B, finding 1 (CRITICAL) ----------------------------------


def _client_with_lab(monkeypatch, tmp_path):
    """A real app with a capture root, so the recorder actually writes."""
    from fastapi.testclient import TestClient

    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "captures"))
    monkeypatch.delenv("TOWER_WORLD_ROOT", raising=False)
    client = TestClient(create_app())
    client.__enter__()
    return client


def _jpeg_message(seq: int) -> dict:
    import base64
    import io as _io

    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(seq)
    array = rng.integers(0, 255, size=(360, 640, 3), dtype=np.uint8)
    buffer = _io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG", quality=60)
    return {
        "type": "frame",
        "seq": seq,
        "width": 640,
        "height": 360,
        "format": "jpeg",
        "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }


def _frames_written(client) -> int:
    """How many frames actually reached disk.

    `frames_written` lives on `CaptureStatus`, not on the recorder --
    `status` is a PROPERTY and is None when nothing is recording, which is
    itself a failure worth catching here.
    """
    status = client.app.state.frame_observers[0].status
    assert status is not None, "the recorder is not recording at all"
    return status.frames_written


def test_a_paused_cv_lab_does_not_stop_the_dataset_recorder(monkeypatch, tmp_path):
    """One experimental sandbox must not gate the frame bus.

    `cv_lab_pause` is an ordinary, client-reachable command that any
    connection may send. It used to stop frames reaching the DATASET
    RECORDER, Scene Understanding and Document Memory -- while every one
    of them went on reporting itself healthy. `/health` said `capture:
    armed`, the recorder said `is_recording` with an open capture id, and
    zero bytes were written. The walk was lost and nothing said so.

    A frame that arrived and decoded is a real frame. What the CV module
    thought of it is the CV module's business.
    """
    client = _client_with_lab(monkeypatch, tmp_path)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "stream_start"})
            for seq in range(1, 4):
                ws.send_json(_jpeg_message(seq))
                ws.receive_json()
            before = _frames_written(client)

            ws.send_json({"type": "cv_lab_pause"})
            # Drain until the Lab acknowledges the pause.
            for _ in range(20):
                if ws.receive_json().get("type") == "cv_lab_status":
                    break

            refusals = 0
            for seq in range(10, 20):
                ws.send_json(_jpeg_message(seq))
                reply = ws.receive_json()
                if reply.get("reason") == "cv_lab_paused":
                    refusals += 1
            after = _frames_written(client)

        assert refusals == 10, "the Lab did not actually refuse these frames"
        assert after - before == 10, (
            f"the recorder wrote {after - before} of 10 frames the Lab refused; "
            "a paused CV Lab is starving the dataset recorder"
        )
    finally:
        client.__exit__(None, None, None)


def test_an_unavailable_cv_module_does_not_stop_the_dataset_recorder(
    monkeypatch, tmp_path
):
    """The terminal case, which is worse than the pause.

    `mark_failed()` is terminal, so a typo in TOWER_CV_EXPERIMENT or one
    load timeout made the Tower record nothing and feed no cartridge for
    the LIFE OF THE PROCESS.
    """
    from tower.modules.container import ModuleUnavailableError

    client = _client_with_lab(monkeypatch, tmp_path)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "stream_start"})
            ws.send_json(_jpeg_message(1))
            ws.receive_json()
            before = _frames_written(client)

            def _dead(_raw):
                raise ModuleUnavailableError("module is FAILED")

            monkeypatch.setattr(
                client.app.state.module_container, "process", _dead
            )

            for seq in range(10, 16):
                ws.send_json(_jpeg_message(seq))
                reply = ws.receive_json()
                assert reply["reason"] == "module_unavailable"
            after = _frames_written(client)

        assert after - before == 6, (
            f"the recorder wrote {after - before} of 6 frames a FAILED module "
            "refused; a dead CV module is starving the dataset recorder"
        )
    finally:
        client.__exit__(None, None, None)
