"""Session cleanup must survive a failure while finalizing measurement.

`_finalize_stream_measurement` runs from the endpoint's `finally` block,
immediately before `session.client_disconnected()`. If snapshotting raises,
the cleanup call is skipped and the tracker believes a client is still
connected forever -- truthful-state violation (Rule 3) plus a lifecycle
leak (Rule 15). Measurement is diagnostics; connection bookkeeping is
correctness, and diagnostics must never take correctness down with it.
"""
import base64
import io
import logging

from fastapi.testclient import TestClient
from PIL import Image

from tower.main import create_app
from tower.metrics import SessionMetrics


def _jpeg_base64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _frame(seq: int, **extra) -> dict:
    message = {
        "type": "frame",
        "seq": seq,
        "width": 8,
        "height": 8,
        "format": "jpeg",
        "data": _jpeg_base64(),
    }
    message.update(extra)
    return message


def test_client_disconnected_still_runs_when_snapshot_raises(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")
    app = create_app()
    client = TestClient(app)

    def exploding_snapshot(self):
        raise RuntimeError("snapshot blew up")

    monkeypatch.setattr(SessionMetrics, "snapshot", exploding_snapshot)

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        websocket.send_json(_frame(1))
        assert websocket.receive_json()["type"] == "frame_result"

    # The leak this guards against: a tracker stuck at "connected".
    assert app.state.session.is_client_connected() is False
    messages = [record.getMessage() for record in caplog.records]
    assert any("could not finalize" in m for m in messages), messages


def test_string_source_seq_is_a_frame_error_not_a_dropped_session(caplog):
    """Finding 1's end-to-end shape: a stringified sequence field used to
    parse cleanly, then explode in snapshot() from the finally block. It
    must instead be rejected at the boundary, leaving the session healthy
    and the final summary intact.
    """
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    app = create_app()
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})

        websocket.send_json(_frame(1, source_seq="31"))
        error = websocket.receive_json()
        assert error["type"] == "frame_error"
        assert error["reason"] == "invalid_frame"

        # Connection stays fully usable afterwards.
        websocket.send_json(_frame(2))
        assert websocket.receive_json()["type"] == "frame_result"
        websocket.send_json({"type": "stream_stop"})

    assert app.state.session.is_client_connected() is False
    summaries = [
        record.getMessage()
        for record in caplog.records
        if "final summary:" in record.getMessage()
    ]
    assert len(summaries) == 1, summaries
    assert "'frames_received': 1" in summaries[0]
    assert "'frames_rejected': 1" in summaries[0]


def test_all_three_rejection_reasons_increment_frames_rejected(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})

        # invalid_frame: missing a required field.
        websocket.send_json({"type": "frame", "seq": 1})
        assert websocket.receive_json()["reason"] == "invalid_frame"

        # invalid_frame: undecodable payload.
        websocket.send_json(_frame(2, data="bm90IGEganBlZw=="))
        assert websocket.receive_json()["reason"] == "invalid_frame"

        websocket.send_json(_frame(3))
        assert websocket.receive_json()["type"] == "frame_result"
        websocket.send_json({"type": "stream_stop"})

    summaries = [
        record.getMessage()
        for record in caplog.records
        if "final summary:" in record.getMessage()
    ]
    assert "'frames_rejected': 2" in summaries[0]
    assert "'frames_received': 1" in summaries[0]
