import asyncio
import base64
import io
import logging

from fastapi.testclient import TestClient
from PIL import Image

from tower.main import create_app
from tower.modules.base import FrameProcessingError, Module, ModuleDataBehavior, ModuleDescriptor, ModuleState
from tower.modules.container import ModuleContainer


def _make_jpeg_base64(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class _FrameProcessingErrorModule(Module):
    descriptor = ModuleDescriptor(
        id="frame-processing-error",
        name="frame-processing-error",
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
        return None

    async def _do_start(self) -> None:
        return None

    def _do_process(self, observation):
        raise FrameProcessingError("undecodable frame")

    async def _do_stop(self) -> None:
        return None

    async def _do_unload(self) -> None:
        return None


def test_frame_processing_error_drops_frame_keeps_module_active_and_counts_metric(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")

    app = create_app()
    container = ModuleContainer(_FrameProcessingErrorModule())
    asyncio.run(container.load_and_start())
    assert container.state == ModuleState.ACTIVE
    app.state.module_container = container

    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
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
        # No frame_result was queued for the bad frame -- a frame_error
        # message arrives instead, and the module is still ACTIVE afterward.
        error = websocket.receive_json()
        assert error == {
            "type": "frame_error",
            "seq": 1,
            "reason": "frame_skipped",
            "message": "module frame-processing-error could not process this frame",
        }
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}
        websocket.send_json({"type": "stream_stop"})

    assert container.state == ModuleState.ACTIVE

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "'frame_processing_errors': 1" in m for m in messages
    ), messages
