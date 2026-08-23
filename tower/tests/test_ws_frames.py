import base64
import io
import logging

from PIL import Image

from fastapi.testclient import TestClient

from tower.main import create_app


def _make_jpeg_base64(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 45, 200)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _assert_connection_still_alive(websocket) -> None:
    websocket.send_json({"type": "ping"})
    assert websocket.receive_json() == {"type": "pong"}


def _receive_frame_error(websocket, seq) -> dict:
    message = websocket.receive_json()
    assert message["type"] == "frame_error"
    assert message["seq"] == seq
    assert message["reason"] == "invalid_frame"
    return message


def _receive_frame_result(websocket) -> dict:
    message = websocket.receive_json()
    assert message["type"] == "frame_result"
    return message


def test_valid_frame_is_accepted_and_dimensions_verified(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            {
                "type": "frame",
                "seq": 30,
                "width": 48,
                "height": 64,
                "format": "jpeg",
                "data": _make_jpeg_base64(48, 64),
            }
        )
        result = _receive_frame_result(websocket)
        _assert_connection_still_alive(websocket)

    assert result["seq"] == 30
    assert "mean_intensity" in result

    messages = [record.getMessage() for record in caplog.records]
    assert any("#30 received" in m for m in messages)
    assert any("#30 decoded: 48x64" in m for m in messages)
    assert any("#30 verified" in m for m in messages)


def test_frame_dimension_mismatch_is_logged_and_not_marked_verified(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            {
                "type": "frame",
                "seq": 31,
                "width": 999,
                "height": 999,
                "format": "jpeg",
                "data": _make_jpeg_base64(48, 64),
            }
        )
        _receive_frame_result(websocket)
        _assert_connection_still_alive(websocket)

    messages = [record.getMessage() for record in caplog.records]
    assert any("#31 decoded: 48x64" in m for m in messages)
    assert not any("#31 verified" in m for m in messages)
    assert any(
        "mismatch" in m and "999" in m and "48x64" in m for m in messages
    )


def test_invalid_base64_frame_does_not_crash_socket(caplog):
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            {
                "type": "frame",
                "seq": 32,
                "width": 48,
                "height": 64,
                "format": "jpeg",
                "data": "%%%not-valid-base64%%%",
            }
        )
        error = _receive_frame_error(websocket, seq=32)
        assert "base64" in error["message"].lower()
        _assert_connection_still_alive(websocket)

    messages = [record.getMessage() for record in caplog.records]
    assert any("#32" in m and "base64" in m.lower() for m in messages)


def test_unsupported_frame_format_is_rejected_cleanly(caplog):
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            {
                "type": "frame",
                "seq": 33,
                "width": 48,
                "height": 64,
                "format": "png",
                "data": _make_jpeg_base64(48, 64),
            }
        )
        error = _receive_frame_error(websocket, seq=33)
        assert "format" in error["message"].lower()
        _assert_connection_still_alive(websocket)

    messages = [record.getMessage() for record in caplog.records]
    assert any("#33" in m and "format" in m.lower() for m in messages)


def test_malformed_frame_message_missing_fields_does_not_crash(caplog):
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "frame", "seq": 34, "width": 48})
        error = _receive_frame_error(websocket, seq=34)
        assert "missing" in error["message"].lower()
        _assert_connection_still_alive(websocket)

    messages = [record.getMessage() for record in caplog.records]
    assert any("malformed" in m.lower() for m in messages)


def test_frame_error_reports_null_seq_when_the_message_has_no_seq(caplog):
    # A frame message can fail validation before seq is even known. The
    # client still needs to be told -- with seq null rather than a
    # fabricated value (Rule 3: unknown stays unknown).
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "frame", "width": 48, "height": 64})
        error = websocket.receive_json()
        _assert_connection_still_alive(websocket)

    assert error["type"] == "frame_error"
    assert error["seq"] is None
    assert error["reason"] == "invalid_frame"


def test_ping_still_works_interleaved_with_frame_messages():
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

        websocket.send_json(
            {
                "type": "frame",
                "seq": 1,
                "width": 10,
                "height": 10,
                "format": "jpeg",
                "data": _make_jpeg_base64(10, 10),
            }
        )
        _receive_frame_result(websocket)

        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}
