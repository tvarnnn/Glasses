"""The WS layer must feed the capture index into the rate estimates.

tower/routes/ws.py passes `source_seq` (not `seq`) into
SessionMetrics.record_frame, so that a post-split sender -- one whose
`seq`/`tx_seq` is a dense transmit counter and whose capture index lives
in `source_seq` -- still gets a truthful sampling stride. These tests
cover that wiring end to end through the real endpoint.
"""
import base64
import io
import logging

from fastapi.testclient import TestClient
from PIL import Image

from tower.main import create_app


def _make_jpeg_base64(width: int = 16, height: int = 16) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(70, 70, 70)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _send_frame(websocket, seq: int, **extra) -> dict:
    message = {
        "type": "frame",
        "seq": seq,
        "width": 16,
        "height": 16,
        "format": "jpeg",
        "data": _make_jpeg_base64(),
    }
    message.update(extra)
    websocket.send_json(message)
    result = websocket.receive_json()
    assert result["type"] == "frame_result", result
    return result


def _final_summary(caplog) -> str:
    summaries = [
        record.getMessage()
        for record in caplog.records
        if "final summary:" in record.getMessage()
    ]
    assert len(summaries) == 1, summaries
    return summaries[0]


def test_final_summary_reports_the_sampling_stride_for_a_legacy_sender(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        for seq in (1, 31, 61, 91):
            _send_frame(websocket, seq)
        websocket.send_json({"type": "stream_stop"})

    summary = _final_summary(caplog)
    assert "'sampling_stride_avg': 30.0" in summary
    assert "'source_seq_span': 90" in summary


def test_stride_comes_from_source_seq_not_the_dense_transmit_counter(caplog):
    """A post-split sender forwarding 1-in-30 sends seq/tx_seq 1,2,3,4 and
    source_seq 1,31,61,91. Reading the stride off `seq` would report 1.0 --
    "forwarding every frame" -- which is exactly the wrong diagnosis.
    """
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        for index, source_seq in enumerate([1, 31, 61, 91], start=1):
            _send_frame(websocket, index, source_seq=source_seq, tx_seq=index)
        websocket.send_json({"type": "stream_stop"})

    summary = _final_summary(caplog)
    assert "'sampling_stride_avg': 30.0" in summary
    # Dense transmit counter with no gaps: nothing was lost in transit.
    assert "'tx_seq_gap_total': 0" in summary


def test_summary_reports_unavailable_stride_for_a_single_frame_window(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "stream_start"})
        _send_frame(websocket, 1)
        websocket.send_json({"type": "stream_stop"})

    summary = _final_summary(caplog)
    assert "'sampling_stride_avg': None" in summary
    assert "'source_fps_estimate': None" in summary
