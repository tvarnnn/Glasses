import io

from PIL import Image

from tower.experiments import edge_detection


def _uniform_jpeg_bytes(width: int, height: int, color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _hard_edge_jpeg_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(0, 0, 0))
    right_half = Image.new("RGB", (width // 2, height), color=(255, 255, 255))
    image.paste(right_half, (width // 2, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_hard_edge_image_has_higher_edge_density_than_uniform_image():
    uniform_result = edge_detection.run(_uniform_jpeg_bytes(64, 64, (128, 128, 128)))
    edge_result = edge_detection.run(_hard_edge_jpeg_bytes(64, 64))

    assert edge_result.result_value > uniform_result.result_value


def test_result_label_and_mean_intensity():
    result = edge_detection.run(_hard_edge_jpeg_bytes(64, 64))

    assert result.result_label == "edge_density"
    assert result.mean_intensity is None


def test_stage_ms_has_all_four_expected_stages():
    result = edge_detection.run(_hard_edge_jpeg_bytes(32, 32))

    assert set(result.stage_ms) == {"decode", "blur", "canny", "summarize"}
    assert result.processing_ms == sum(result.stage_ms.values())
