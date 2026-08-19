import base64
import io
import logging

from fastapi.testclient import TestClient
from PIL import Image

from tower.main import create_app


def _make_jpeg_base64(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(70, 70, 70)).save(buffer, format="JPEG")
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


def _final_summary_lines(caplog):
    messages = [record.getMessage() for record in caplog.records]
    return [m for m in messages if "final summary:" in m]


def test_stream_start_opens_a_measurement_window_and_logs_it(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        # give the server a beat to process by round-tripping a ping
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "[Tower][Session] stream_start: measurement window opened" in m
        for m in messages
    ), messages


def test_frame_with_no_active_window_is_still_processed_and_not_counted(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        # Sent before any stream_start -- must still be fully processed.
        result = _send_frame(websocket, 1)
        assert result["seq"] == 1

        websocket.send_json({"type": "stream_start"})
        _send_frame(websocket, 2)
        websocket.send_json({"type": "stream_stop"})

    final_summaries = _final_summary_lines(caplog)
    assert len(final_summaries) == 1
    assert "'frames_received': 1" in final_summaries[0]
    assert "'end_reason': 'stream_stop'" in final_summaries[0]


def test_stream_stop_finalizes_with_stream_stop_reason_and_correct_counts(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        _send_frame(websocket, 1)
        _send_frame(websocket, 2)
        websocket.send_json({"type": "stream_stop"})

        # connection must stay usable after stream_stop
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    final_summaries = _final_summary_lines(caplog)
    assert len(final_summaries) == 1
    assert "'frames_received': 2" in final_summaries[0]
    assert "'end_reason': 'stream_stop'" in final_summaries[0]


def test_disconnect_while_stream_active_finalizes_with_disconnect_reason(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        _send_frame(websocket, 1)

    final_summaries = _final_summary_lines(caplog)
    assert len(final_summaries) == 1
    assert "'frames_received': 1" in final_summaries[0]
    assert "'end_reason': 'disconnect'" in final_summaries[0]


def test_stream_stop_with_no_active_window_logs_warning_and_stays_usable(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_stop"})

        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "stream_stop received with no active measurement window" in m
        for m in messages
    ), messages
    assert not _final_summary_lines(caplog)


def test_stream_start_while_already_active_finalizes_previous_window_first(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        _send_frame(websocket, 1)
        _send_frame(websocket, 2)

        websocket.send_json({"type": "stream_start"})  # no stream_stop first
        _send_frame(websocket, 1)

        websocket.send_json({"type": "stream_stop"})

    final_summaries = _final_summary_lines(caplog)
    assert len(final_summaries) == 2
    assert "'frames_received': 2" in final_summaries[0]
    assert "'end_reason': 'superseded_by_stream_start'" in final_summaries[0]
    assert "'frames_received': 1" in final_summaries[1]
    assert "'end_reason': 'stream_stop'" in final_summaries[1]


def test_multiple_stream_start_stop_cycles_on_one_connection(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        _send_frame(websocket, 1)
        websocket.send_json({"type": "stream_stop"})

        websocket.send_json({"type": "stream_start"})
        _send_frame(websocket, 1)
        _send_frame(websocket, 2)
        websocket.send_json({"type": "stream_stop"})

    final_summaries = _final_summary_lines(caplog)
    assert len(final_summaries) == 2
    assert "'frames_received': 1" in final_summaries[0]
    assert "'end_reason': 'stream_stop'" in final_summaries[0]
    assert "'frames_received': 2" in final_summaries[1]
    assert "'end_reason': 'stream_stop'" in final_summaries[1]


def test_ping_pong_unaffected_by_active_stream_window():
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})

        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

        _send_frame(websocket, 1)

        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

        websocket.send_json({"type": "stream_stop"})
