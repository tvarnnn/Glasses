import pytest

from tower.experiments.depth import DepthEstimation
from tower.modules.base import FrameProcessingError


def test_undecodable_frame_raises_frame_processing_error_without_loading_a_model():
    experiment = DepthEstimation()  # never loaded -- no model, no torch import

    with pytest.raises(FrameProcessingError):
        experiment.run(b"not a jpeg")


def test_depth_array_capture_is_off_by_default():
    experiment = DepthEstimation()

    assert experiment.capture_depth_array is False
    assert experiment.last_depth_array is None


def test_depth_array_capture_is_opt_in_via_constructor():
    experiment = DepthEstimation(capture_depth_array=True)

    assert experiment.capture_depth_array is True
    assert experiment.last_depth_array is None  # nothing captured until run()
