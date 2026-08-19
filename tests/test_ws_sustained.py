import base64
import io
import logging

from PIL import Image

from fastapi.testclient import TestClient

from tower.main import create_app


def _make_jpeg_base64(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(80, 80, 80)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _send_frame(websocket, seq: int) -> dict:
    websocket.send_json(
        {
            "type": "frame",
            "seq": seq,
            "width": 16,
            "height": 16,
            "format": "jpeg",
            "data": _make_jpeg_base64(16, 16),
        }
    )
    message = websocket.receive_json()
    assert message["type"] == "frame_result"
    return message


def test_sustained_frames_are_each_still_acknowledged():
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        for seq in range(1, 6):
            result = _send_frame(websocket, seq)
            assert result["seq"] == seq


def test_session_summary_is_logged_at_the_configured_frame_interval(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    monkeypatch.setattr("tower.metrics.SessionMetrics.SUMMARY_LOG_FRAME_INTERVAL", 3)
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        for seq in range(1, 4):
            _send_frame(websocket, seq)

    messages = [record.getMessage() for record in caplog.records]
    assert any("[Tower][Session] summary:" in m for m in messages)


def test_final_session_summary_is_logged_on_disconnect(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        _send_frame(websocket, 1)

    messages = [record.getMessage() for record in caplog.records]
    assert any("[Tower][Session] final summary:" in m for m in messages)


def test_seq_gap_total_is_reflected_in_final_summary_when_a_frame_is_skipped(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        _send_frame(websocket, 1)
        _send_frame(websocket, 3)  # seq 2 never sent

    messages = [record.getMessage() for record in caplog.records]
    final_summary_lines = [m for m in messages if "final summary:" in m]
    assert final_summary_lines
    assert "'seq_gap_total': 1" in final_summary_lines[-1]
    assert "'backpressure_drops': 0" in final_summary_lines[-1]


def test_metrics_reset_across_reconnects(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        _send_frame(websocket, 1)
        _send_frame(websocket, 2)

    caplog.clear()

    with client.websocket_connect("/ws") as websocket:
        _send_frame(websocket, 1)

    messages = [record.getMessage() for record in caplog.records]
    final_summary_lines = [m for m in messages if "final summary:" in m]
    assert final_summary_lines
    assert "'frames_received': 1" in final_summary_lines[-1]
    assert "'seq_gap_total': 0" in final_summary_lines[-1]
