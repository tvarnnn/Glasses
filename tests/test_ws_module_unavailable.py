import base64
import io
import logging

from fastapi.testclient import TestClient
from PIL import Image

from tower.main import create_app
from tower.modules.base import Module, ModuleDataBehavior, ModuleDescriptor
from tower.modules.container import ModuleContainer


def _make_jpeg_base64(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class _AlwaysFailsToLoad(Module):
    descriptor = ModuleDescriptor(
        id="broken",
        name="broken",
        version="0.0.1",
        data_behavior=ModuleDataBehavior(
            persists_data=False,
            retains_raw_imagery=False,
            retention="none",
            supports_purge=False,
            transmits_externally=False,
        ),
    )

    async def _do_load(self) -> None:
        raise RuntimeError("boom")

    async def _do_start(self) -> None:
        return None

    def _do_process(self, observation):
        return observation

    async def _do_stop(self) -> None:
        return None

    async def _do_unload(self) -> None:
        return None


def test_frame_is_dropped_and_connection_stays_alive_when_module_unavailable(caplog):
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")

    app = create_app()
    broken_container = ModuleContainer(_AlwaysFailsToLoad())
    import asyncio

    asyncio.run(broken_container.load_and_start())  # ends FAILED
    app.state.module_container = broken_container

    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            {
                "type": "frame",
                "seq": 1,
                "width": 8,
                "height": 8,
                "format": "jpeg",
                "data": _make_jpeg_base64(8, 8),
            }
        )
        # No frame_result will ever arrive for this frame -- confirm the
        # connection is still alive and usable via ping/pong instead of
        # trying to receive a frame_result that will never come.
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "#1" in m and "module unavailable" in m.lower() for m in messages
    ), messages
