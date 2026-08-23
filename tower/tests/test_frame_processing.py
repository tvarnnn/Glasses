import io

from PIL import Image

from tower.frame_processing import process_frame


def _jpeg_bytes(width: int, height: int, color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_process_frame_reports_high_mean_intensity_for_white_image():
    result = process_frame(_jpeg_bytes(32, 32, (255, 255, 255)))

    assert result.mean_intensity > 250


def test_process_frame_reports_low_mean_intensity_for_black_image():
    result = process_frame(_jpeg_bytes(32, 32, (0, 0, 0)))

    assert result.mean_intensity < 5


def test_process_frame_reports_nonnegative_processing_time():
    result = process_frame(_jpeg_bytes(32, 32, (120, 45, 200)))

    assert result.processing_ms >= 0
