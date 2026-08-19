import base64
import io

from fastapi.testclient import TestClient
from PIL import Image

from tower.main import create_app


def _make_jpeg_base64(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(90, 90, 90)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_baseline_frame_result_has_additive_fields_and_backward_compatible_mean_intensity():
    client = TestClient(create_app())  # default config: baseline experiment

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            {
                "type": "frame",
                "seq": 1,
                "width": 16,
                "height": 16,
                "format": "jpeg",
                "data": _make_jpeg_base64(16, 16),
            }
        )
        result = websocket.receive_json()

    assert result["type"] == "frame_result"
    assert result["seq"] == 1
    assert "mean_intensity" in result  # unchanged from V0.7/V0.8
    assert "processing_ms" in result  # unchanged from V0.7/V0.8
    assert result["result_label"] == "mean_intensity"
    assert result["result_value"] == result["mean_intensity"]
    assert result["stage_ms"] == {"total": result["processing_ms"]}


def test_edge_detection_frame_result_omits_mean_intensity(monkeypatch):
    monkeypatch.setenv("TOWER_CV_EXPERIMENT", "edge_detection")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            {
                "type": "frame",
                "seq": 1,
                "width": 16,
                "height": 16,
                "format": "jpeg",
                "data": _make_jpeg_base64(16, 16),
            }
        )
        result = websocket.receive_json()

    assert result["result_label"] == "edge_density"
    assert "mean_intensity" not in result
    assert set(result["stage_ms"]) == {"decode", "blur", "canny", "summarize"}
