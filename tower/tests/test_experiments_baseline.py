import io

from PIL import Image

from tower.experiments import baseline
from tower.frame_processing import process_frame


def _jpeg_bytes(width: int, height: int, color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_run_matches_process_frame_directly():
    raw_bytes = _jpeg_bytes(32, 32, (255, 255, 255))

    result = baseline.run(raw_bytes)
    direct = process_frame(raw_bytes)

    assert result.result_value == direct.mean_intensity
    assert result.mean_intensity == direct.mean_intensity
    assert result.result_label == "mean_intensity"
    assert result.processing_ms >= 0


def test_stage_ms_has_a_single_total_entry():
    raw_bytes = _jpeg_bytes(16, 16, (0, 0, 0))

    result = baseline.run(raw_bytes)

    assert set(result.stage_ms) == {"total"}
    assert result.stage_ms["total"] == result.processing_ms
