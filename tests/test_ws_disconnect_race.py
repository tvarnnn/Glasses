import base64
import io
import logging

from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocket, WebSocketDisconnect

from tower.main import create_app


def _make_jpeg_base64(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(60, 60, 60)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_disconnect_during_in_flight_frame_is_handled_gracefully(caplog, monkeypatch):
    """Simulates the client disconnecting between the server receiving a
    frame and the server sending back frame_result -- reproduced for real
    against a live server during investigation (abrupt TCP transport.abort()
    while the server was mid-processing). This test forces the same failure
    deterministically by making send_json raise WebSocketDisconnect for the
    frame_result reply specifically.
    """
    caplog.set_level(logging.INFO, logger="tower.routes.ws")

    original_send_json = WebSocket.send_json

    async def send_json_that_fails_for_frame_result(self, data, mode="text"):
        if data.get("type") == "frame_result":
            raise WebSocketDisconnect(code=1006)
        return await original_send_json(self, data, mode=mode)

    monkeypatch.setattr(WebSocket, "send_json", send_json_that_fails_for_frame_result)

    app = create_app()
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        websocket.send_json(
            {
                "type": "frame",
                "seq": 5,
                "width": 8,
                "height": 8,
                "format": "jpeg",
                "data": _make_jpeg_base64(8, 8),
            }
        )
        # Do not attempt to receive a response -- the server-side send is
        # patched to fail exactly as it would for a genuinely disconnected
        # peer, so no frame_result will ever arrive.

    messages = [record.getMessage() for record in caplog.records]

    assert any(
        "#5" in m and "disconnect" in m.lower() and "could not" in m.lower()
        for m in messages
    ), messages
    assert any("[Tower][Session] final summary:" in m for m in messages), messages
    assert app.state.session.is_client_connected() is False
