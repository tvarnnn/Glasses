import base64
import io
import logging

from fastapi.testclient import TestClient
from PIL import Image

from tower.experiments import ExperimentResult
from tower.main import create_app
from tower.modules.base import Module, ModuleDataBehavior, ModuleDescriptor, ModuleState
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
        # No frame_result will ever arrive for this frame -- a frame_error
        # message arrives instead, then the connection is still alive and
        # usable via ping/pong.
        error = websocket.receive_json()
        assert error == {
            "type": "frame_error",
            "seq": 1,
            "reason": "module_unavailable",
            "message": "module broken is failed, not ACTIVE",
        }
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "#1" in m and "module unavailable" in m.lower() for m in messages
    ), messages


class _FailsAfterFirstCall(Module):
    """Loads/starts successfully, processes the first observation, then
    raises on every subsequent call -- simulating a module that goes bad
    mid-stream rather than one that never came up in the first place."""

    descriptor = ModuleDescriptor(
        id="fails-after-first",
        name="fails-after-first",
        version="0.0.1",
        data_behavior=ModuleDataBehavior(
            persists_data=False,
            retains_raw_imagery=False,
            retention="none",
            supports_purge=False,
            transmits_externally=False,
        ),
    )

    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    async def _do_load(self) -> None:
        return None

    async def _do_start(self) -> None:
        return None

    def _do_process(self, observation):
        self.call_count += 1
        if self.call_count > 1:
            raise RuntimeError("module went bad mid-stream")
        return ExperimentResult(
            result_value=1.0,
            result_label="mean_intensity",
            processing_ms=1.0,
            stage_ms={"total": 1.0},
            mean_intensity=1.0,
        )

    async def _do_stop(self) -> None:
        return None

    async def _do_unload(self) -> None:
        return None


def test_module_that_fails_mid_stream_is_marked_failed_and_subsequent_frames_are_dropped(
    caplog,
):
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")

    app = create_app()
    module = _FailsAfterFirstCall()
    container = ModuleContainer(module)
    import asyncio

    asyncio.run(container.load_and_start())
    assert container.state == ModuleState.ACTIVE
    app.state.module_container = container

    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        for seq in (1, 2, 3):
            websocket.send_json(
                {
                    "type": "frame",
                    "seq": seq,
                    "width": 8,
                    "height": 8,
                    "format": "jpeg",
                    "data": _make_jpeg_base64(8, 8),
                }
            )
        websocket.send_json({"type": "ping"})

        # Exactly one frame_result should arrive (for seq 1). The message
        # immediately after it must be the pong -- proving no frame_result
        # was queued up for seq 2 or seq 3; they were silently dropped.
        first = websocket.receive_json()
        assert first == {
            "type": "frame_result",
            "seq": 1,
            "processing_ms": 1.0,
            "result_value": 1.0,
            "result_label": "mean_intensity",
            "stage_ms": {"total": 1.0},
            "mean_intensity": 1.0,
        }

        second = websocket.receive_json()
        assert second == {
            "type": "frame_error",
            "seq": 2,
            "reason": "module_unavailable",
            "message": "module fails-after-first failed while processing",
        }

        third = websocket.receive_json()
        assert third == {
            "type": "frame_error",
            "seq": 3,
            "reason": "module_unavailable",
            "message": "module fails-after-first is failed, not ACTIVE",
        }

        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    # The module's own process() was called exactly twice: once
    # successfully for frame 1, once failingly for frame 2. Frame 3 never
    # reached _do_process at all -- it was dropped by the container's
    # ACTIVE-state short-circuit before the module was touched again.
    assert module.call_count == 2

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "#2" in m and "module unavailable" in m.lower() for m in messages
    ), messages
    assert any(
        "#3" in m and "module unavailable" in m.lower() for m in messages
    ), messages
