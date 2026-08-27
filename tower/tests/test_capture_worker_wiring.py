"""A capture starts a worker without anybody typing a UUID.

This is the product claim of the whole workstream: press Start on the
phone, walk, press Stop, and a world exists. On 2026-08-24 the same flow
required opening a second terminal, listing `data/captures` by mtime,
copying a hex id, and running `world_build_session.py --follow-capture`
by hand -- and doing it once, for one of the ten captures that walk
produced.

These tests drive the real ASGI app over a real WebSocket and assert on
what the supervisor was asked to do. The worker itself is faked: a real
follower would need a real capture to tail, and what is under test here
is the WIRING, not the follower.
"""

import base64

import numpy as np
import pytest

from tower.main import WORLD_BUILD_WORKER


def _jpeg() -> str:
    import cv2

    ok, buffer = cv2.imencode(".jpg", np.full((640, 360, 3), 128, dtype=np.uint8))
    assert ok
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def _frame(seq: int, data: str) -> dict:
    return {
        "type": "frame",
        "seq": seq,
        "width": 360,
        "height": 640,
        "format": "jpeg",
        "data": data,
    }


class RecordingSupervisor:
    """Stands in for CaptureWorkerSupervisor, remembering the calls."""

    def __init__(self):
        self.opened = []
        self.closed = []
        self.shutdowns = 0
        self.enabled = True

    def capture_opened(self, capture_id, capture_dir, *, continues=None):
        self.opened.append((capture_id, str(capture_dir), continues))

    def capture_closed(self, capture_id):
        self.closed.append(capture_id)

    def shutdown(self, grace_seconds=None):
        self.shutdowns += 1

    def reap(self):
        pass

    def status(self):
        return []


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("TOWER_WORLD_ROOT", str(tmp_path / "world"))
    app = create_app()
    app.state.capture_workers = RecordingSupervisor()
    return TestClient(app)


def test_a_stream_start_attaches_a_worker_to_the_capture_it_just_minted(client):
    """The capture id is minted inside the web process at stream_start.

    That is the structural reason it had to be copied by hand: it does
    not exist until the phone connects, so no script could be launched in
    advance with the right argument. The process that mints it is the one
    that now hands it over.
    """
    supervisor = client.app.state.capture_workers
    recorder = client.app.state.frame_observers[0]

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "stream_start"})
        ws.send_json(_frame(1, _jpeg()))
        ws.receive_json()
        capture_id = recorder.status.capture_id

    assert [row[0] for row in supervisor.opened] == [capture_id]
    assert supervisor.opened[0][1] == str(recorder.capture_dir(capture_id))
    assert supervisor.opened[0][2] is None


def test_a_stream_stop_tells_the_supervisor_which_capture_ended(client):
    supervisor = client.app.state.capture_workers
    recorder = client.app.state.frame_observers[0]

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "stream_start"})
        ws.send_json(_frame(1, _jpeg()))
        ws.receive_json()
        capture_id = recorder.status.capture_id
        ws.send_json({"type": "stream_stop"})
        ws.send_json({"type": "ping"})
        ws.receive_json()

    assert supervisor.closed[0] == capture_id


def test_a_reconnect_hands_over_the_lineage_it_was_given(client):
    """`continues` must reach the supervisor, or it cannot suppress.

    The recorder decides lineage and writes it into the manifest. If the
    supervisor is not told, it sees two unrelated captures and starts two
    workers on one walk.
    """
    supervisor = client.app.state.capture_workers
    recorder = client.app.state.frame_observers[0]
    data = _jpeg()

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "stream_start"})
        ws.send_json(_frame(1, data))
        ws.receive_json()
        first = recorder.status.capture_id

    # The socket dropped: the capture ended by disconnect, so the next
    # stream_start within the grace window declares itself a successor.
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "stream_start"})
        ws.send_json(_frame(2, data))
        ws.receive_json()
        second = recorder.status.capture_id

    assert second != first
    assert supervisor.opened[1][0] == second
    assert supervisor.opened[1][2] == first, (
        "the successor did not carry its predecessor to the supervisor"
    )


def test_a_capture_that_never_starts_attaches_no_worker(client):
    """No stream_start, no capture, no worker.

    Arming is not recording, and supervising is not recording either.
    """
    supervisor = client.app.state.capture_workers

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "ping"})
        ws.receive_json()

    assert supervisor.opened == []


def test_a_tower_with_no_capture_root_supervises_nothing(monkeypatch, tmp_path):
    """Unset TOWER_CAPTURE_ROOT means no recorder, so nothing to follow."""
    from fastapi.testclient import TestClient

    from tower.main import create_app

    monkeypatch.delenv("TOWER_CAPTURE_ROOT", raising=False)
    monkeypatch.setenv("TOWER_WORLD_ROOT", str(tmp_path / "world"))
    app = create_app()
    supervisor = RecordingSupervisor()
    app.state.capture_workers = supervisor
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "stream_start"})
        ws.send_json({"type": "ping"})
        ws.receive_json()

    assert supervisor.opened == []


def test_a_failing_supervisor_never_costs_the_stream_its_capture(client, caplog):
    """World building is a side errand; the frame path is the product.

    A supervisor that raises must not take down the connection that is
    successfully answering frames, and must not stop the recording.
    """
    class Exploding(RecordingSupervisor):
        def capture_opened(self, *args, **kwargs):
            raise RuntimeError("no")

    client.app.state.capture_workers = Exploding()
    recorder = client.app.state.frame_observers[0]

    with caplog.at_level("ERROR"):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "stream_start"})
            ws.send_json(_frame(1, _jpeg()))
            reply = ws.receive_json()

    assert reply["type"] == "frame_result"
    assert recorder.read_frames(recorder.status.capture_id), (
        "the frame was not recorded because the supervisor failed"
    )


# -- what the app actually builds --------------------------------------


def test_a_world_root_builds_a_supervisor_that_will_follow(monkeypatch, tmp_path):
    """Configuration alone must produce a supervisor that CAN start something.

    The failure this guards is silent and was the whole of 2026-08-24:
    an app that reports a capture root, reports a world root, records
    frames, and starts nothing.
    """
    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("TOWER_WORLD_ROOT", str(tmp_path / "world"))
    app = create_app()

    supervisor = app.state.capture_workers
    assert WORLD_BUILD_WORKER in supervisor.worker_names()
    argv = " ".join(supervisor.spec_for(WORLD_BUILD_WORKER).argv)
    assert "world_build_session.py" in argv
    assert "--follow-capture" in argv
    assert "{capture_dir}" in argv
    assert str(tmp_path / "world") in argv


def test_no_world_root_means_the_supervisor_is_honestly_disabled(
    monkeypatch, tmp_path
):
    """A Tower with nowhere to put a world must not start a builder.

    `enabled == False` is a different claim from "a worker was started
    and died", and /health keeps them apart.
    """
    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "capture"))
    monkeypatch.delenv("TOWER_WORLD_ROOT", raising=False)
    app = create_app()

    # Named, not `enabled`: the supervisor can hold a spec for another
    # cartridge, so "nothing at all is configured" stopped being the same
    # claim as "no builder is configured" the moment a second worker
    # existed.
    assert WORLD_BUILD_WORKER not in app.state.capture_workers.worker_names()


def test_autobuild_can_be_turned_off_without_giving_up_the_result_channel(
    monkeypatch, tmp_path
):
    """A world root still reports worlds; it just stops building new ones.

    Needed for offline reprocessing of a recorded capture, and as the
    escape hatch if auto-attach ever misbehaves in the field.
    """
    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("TOWER_WORLD_ROOT", str(tmp_path / "world"))
    monkeypatch.setenv("TOWER_WORLD_AUTOBUILD", "false")
    app = create_app()

    assert WORLD_BUILD_WORKER not in app.state.capture_workers.worker_names()
    assert app.state.world_root == str(tmp_path / "world")


def test_the_rebuild_cadence_reaches_the_worker(monkeypatch, tmp_path):
    """`--rebuild-every 0` means "build once, at the end".

    That default is why the 2026-08-24 walk showed a climbing keyframe
    count and no geometry at all until the capture closed. A Tower that
    attaches a follower automatically must not attach it in batch mode.
    """
    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("TOWER_WORLD_ROOT", str(tmp_path / "world"))
    monkeypatch.setenv("TOWER_WORLD_REBUILD_EVERY", "7")
    app = create_app()

    argv = list(app.state.capture_workers.spec_for(WORLD_BUILD_WORKER).argv)
    assert argv[argv.index("--rebuild-every") + 1] == "7"


def test_the_default_rebuild_cadence_is_live_not_batch(monkeypatch, tmp_path):
    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("TOWER_WORLD_ROOT", str(tmp_path / "world"))
    monkeypatch.delenv("TOWER_WORLD_REBUILD_EVERY", raising=False)
    app = create_app()

    argv = list(app.state.capture_workers.spec_for(WORLD_BUILD_WORKER).argv)
    cadence = int(argv[argv.index("--rebuild-every") + 1])
    assert cadence > 0, (
        "the Tower attached a follower in build-once-at-the-end mode, so "
        "nothing would appear on the phone during the walk"
    )


def test_health_reports_whether_anything_is_building(monkeypatch, tmp_path):
    """"Why isn't World Builder changing?" should be answerable remotely.

    The Tower is normally operated from another machine over Tailscale,
    where a server-side log line is invisible.
    """
    from fastapi.testclient import TestClient

    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("TOWER_WORLD_ROOT", str(tmp_path / "world"))
    client = TestClient(create_app())

    body = client.get("/health").json()

    assert body["capture_workers"]["enabled"] is True
    assert WORLD_BUILD_WORKER in body["capture_workers"]["configured"]
    # Nothing is following a capture between walks, which is the correct
    # answer here and the wrong one during one.
    assert body["capture_workers"]["workers"] == []
