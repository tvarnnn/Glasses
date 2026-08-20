import pytest

from tower.experiments.depth import DepthEstimation
from tower.modules.base import FrameProcessingError


def test_undecodable_frame_raises_frame_processing_error_without_loading_a_model():
    experiment = DepthEstimation()  # never loaded -- no model, no torch import

    with pytest.raises(FrameProcessingError):
        experiment.run(b"not a jpeg")
