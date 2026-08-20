import io
import os

import pytest
from PIL import Image

from tower.experiments.depth import DepthEstimation
from tower.modules.depth_cv import _resolve_device

pytestmark = pytest.mark.skipif(
    os.environ.get("TOWER_RUN_MODEL_TESTS") != "1",
    reason="opt-in: requires a real torch install and a MiDaS weight "
    "download on first run; set TOWER_RUN_MODEL_TESTS=1 to run",
)


def _jpeg_bytes(width: int, height: int, color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_run_on_real_image_produces_expected_result_shape():
    experiment = DepthEstimation()
    experiment.load("cpu")
    try:
        result = experiment.run(_jpeg_bytes(64, 64, (120, 130, 140)))
    finally:
        experiment.release()

    assert result.result_label == "mean_relative_depth"
    assert isinstance(result.result_value, float)
    assert set(result.stage_ms) == {"decode", "preprocess", "inference", "postprocess"}
    assert result.mean_intensity is None


def test_resolve_device_auto_prefers_cuda_when_available():
    import torch

    resolved = _resolve_device("auto")
    assert resolved == ("cuda" if torch.cuda.is_available() else "cpu")


def test_resolve_device_cuda_raises_when_unavailable():
    import torch

    if torch.cuda.is_available():
        pytest.skip("only meaningful on a machine without CUDA")
    with pytest.raises(RuntimeError):
        _resolve_device("cuda")
