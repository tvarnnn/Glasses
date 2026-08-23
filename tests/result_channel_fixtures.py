"""Shared setup for the cartridge result channel tests.

Two things live here because both are easy to get subtly wrong and a wrong
version would make every test that used it meaningless.

**A real world, built by the real engine.** No stubbed store, no
hand-written JSON. The point of these tests is that the wire tells the
truth about what World Builder actually persisted, so anything that
fabricated the on-disk state would be testing the fabrication.

**A deterministic way to drive the poll loop.** No `sleep` anywhere in
these tests. The hub exposes `poll_once()`, and `pump()` runs it on the
app's own event loop through the TestClient portal and does not return
until the pass has completed -- so by the time a test looks, there is
nothing left in flight to wait for.
"""

import numpy as np
import pytest

from tests import synthetic_scene as ss
from tower.world_builder.engine import WorldBuilderEngine
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.store import WorldStore

WIDTH, HEIGHT = 480, 360


def build_world(root, *, frames: int = 10, name: str | None = "Test Room"):
    """Observe, stop, build. Returns (world_id, session_id).

    Uses ground-truth intrinsics so poses actually solve; a world with no
    solved pose exercises a different and also-tested path.
    """
    world_id, session_id, engine = _observe(root, frames=frames, name=name)
    engine.stop_session()
    engine.build(world_id, session_id)
    return world_id, session_id


def start_live_world(root, *, frames: int = 6, name: str | None = "Live Room"):
    """A session that is STILL OPEN: lock held, no session_stopped event.

    Returns (world_id, session_id, engine). The caller owns stopping it.
    This is the state in which session.json still holds the zeros written
    at start_session, which several tests depend on.
    """
    return _observe(root, frames=frames, name=name)


def _observe(root, *, frames: int, name):
    camera_matrix = ss.camera_matrix(WIDTH, HEIGHT)
    scene = ss.furnished_room()
    poses = ss.strafe(frames, step=0.09)
    images = ss.render_sequence(scene, poses, camera_matrix, WIDTH, HEIGHT)
    intrinsics = CameraIntrinsics(
        source="self_calibrated",
        model="pinhole",
        fx=float(camera_matrix[0, 0]),
        fy=float(camera_matrix[1, 1]),
        cx=float(camera_matrix[0, 2]),
        cy=float(camera_matrix[1, 2]),
        calibrated_width=WIDTH,
        calibrated_height=HEIGHT,
    )
    engine = WorldBuilderEngine(WorldStore(root))
    world_id = engine.create_world(name)
    session_id = engine.start_session(
        world_id,
        intrinsics=intrinsics,
        frame_source="synthetic",
        declared_size=(WIDTH, HEIGHT),
    )
    for index, image in enumerate(images):
        engine.observe(ss.encode_jpeg(image), source_seq=index, wire_seq=index)
    return world_id, session_id, engine


_OPEN_CLIENTS: list = []


@pytest.fixture(autouse=True)
def _close_result_channel_clients():
    """Close every client a test opened, in reverse order.

    `make_client` ENTERS the TestClient, because entering is what creates
    the anyio portal -- and the portal is the only correct way to touch
    the app's event loop from a test thread. Entering also runs lifespan,
    which is how the hub's shutdown path gets exercised on every test
    rather than only in the one that asks for it.
    """
    yield
    while _OPEN_CLIENTS:
        _OPEN_CLIENTS.pop().__exit__(None, None, None)


def make_client(monkeypatch, world_root):
    """An ENTERED TestClient over the real app, pointed at `world_root`.

    `create_app()` reads settings at construction, so the environment has
    to be set before it is called -- not after.
    """
    from fastapi.testclient import TestClient

    from tower.main import create_app

    if world_root is None:
        monkeypatch.delenv("TOWER_WORLD_ROOT", raising=False)
    else:
        monkeypatch.setenv("TOWER_WORLD_ROOT", str(world_root))
    client = TestClient(create_app())
    client.__enter__()
    _OPEN_CLIENTS.append(client)
    # The hub's own timer is disabled so tests drive every poll through
    # pump(). A background task polling on its own schedule would make
    # sequence and coalescing assertions depend on wall-clock luck --
    # exactly the flakiness these tests exist to avoid.
    client.app.state.result_hub._poll_seconds = 3600.0
    return client


def pump(client, times: int = 1, *, heartbeat: float = 0.0) -> None:
    """Run `times` complete poll passes on the app's event loop.

    Returns only once every pass has finished offering to every
    subscriber, which is what removes the need for a sleep. Driving all
    `times` passes inside ONE portal call matters for the coalescing
    tests: it guarantees the sender task cannot run between them.

    `heartbeat` defaults to 0 so a pass always delivers. Otherwise a test
    that pumps an unchanged world would deliver nothing -- correct
    behaviour, and an indefinite block for a test waiting on a message.
    Tests that care about the heartbeat set it explicitly.
    """
    hub = client.app.state.result_hub
    previous = hub._heartbeat_seconds
    hub._heartbeat_seconds = heartbeat

    async def _run():
        for _ in range(times):
            await hub.poll_once()

    try:
        client.portal.call(_run)
    finally:
        hub._heartbeat_seconds = previous


def drain(ws, *, expect: str, limit: int = 12):
    """Next message of type `expect`, skipping up to `limit` others.

    Blocks if nothing arrives -- deliberately, because every caller here
    has already done the thing that guarantees a message. A timeout would
    turn "the channel published nothing" into a slow pass instead of a
    failure.
    """
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") == expect:
            return message
    raise AssertionError(f"no {expect!r} within {limit} messages")


def subscribe(ws, **overrides):
    request = {
        "type": "result_subscribe",
        "cartridge": "world_builder",
        "result_type": "status",
    }
    request.update(overrides)
    ws.send_json(request)
    return ws.receive_json()


def jpeg_frame(width: int = 640, height: int = 360) -> str:
    import base64

    import cv2

    ok, buffer = cv2.imencode(
        ".jpg", np.full((height, width, 3), 128, dtype=np.uint8)
    )
    assert ok
    return base64.b64encode(buffer.tobytes()).decode("ascii")
