"""The detector, against real weights.

Opt-in, like the depth integration test: it downloads ~13.4 MB of COCO
weights on first run. Set TOWER_RUN_MODEL_TESTS=1.

Kept out of the default suite deliberately. A default suite that reaches
the network is a suite that fails on a train.
"""

import io
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tower.experiments import EXPERIMENTS, ExperimentSettings
from tower.experiments.object_detection import SCORE_THRESHOLD, TRACKED_CLASSES

pytestmark = pytest.mark.skipif(
    os.environ.get("TOWER_RUN_MODEL_TESTS") != "1",
    reason="opt-in: downloads torchvision COCO weights on first run; "
    "set TOWER_RUN_MODEL_TESTS=1 to run",
)


@pytest.fixture(scope="module")
def detector():
    experiment = EXPERIMENTS["object_detection"]()
    experiment.load(ExperimentSettings(device="cpu"))
    yield experiment
    experiment.release()


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def _blank(width=320, height=240, shade=(120, 120, 120)) -> bytes:
    return _jpeg(Image.new("RGB", (width, height), shade))


def _noise(width=320, height=240, seed=3) -> bytes:
    rng = np.random.default_rng(seed)
    array = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    return _jpeg(Image.fromarray(array))


def _shapes(width=320, height=240) -> bytes:
    """Structured but not object-like. Nothing here is a COCO class."""
    image = Image.new("RGB", (width, height), (30, 30, 30))
    draw = ImageDraw.Draw(image)
    for index in range(6):
        offset = index * 40
        draw.rectangle([offset, offset, offset + 30, offset + 30], fill=(200, 40, 40))
    return _jpeg(image)


class TestResultShape:
    def test_the_headline_is_the_detection_count(self, detector):
        result = detector.run(_blank())

        assert result.result_label == "detections"
        assert result.result_value == result.metrics["detections"]

    def test_every_tracked_class_gets_a_count_even_when_zero(self, detector):
        """Absence of a detection must be reported as zero, not as a
        missing key. A consumer cannot distinguish "none seen" from "not
        measured" if the key simply vanishes (Core Principle 3)."""
        metrics = detector.run(_blank()).metrics

        for name in TRACKED_CLASSES:
            assert f"count_{name.replace(' ', '_')}" in metrics

    def test_the_threshold_is_reported_alongside_the_count(self, detector):
        """A count is meaningless without the threshold that produced it."""
        metrics = detector.run(_blank()).metrics

        assert metrics["score_threshold"] == SCORE_THRESHOLD
        assert metrics["raw_detections"] >= metrics["detections"]

    def test_stage_timings_separate_inference_from_decode(self, detector):
        result = detector.run(_blank())

        assert set(result.stage_ms) == {
            "decode",
            "preprocess",
            "inference",
            "summarize",
        }
        assert result.stage_ms["inference"] > 0


class TestItDoesNotHallucinate:
    """Independent truth: these frames contain no COCO object."""

    @pytest.mark.parametrize("frame", ["blank", "noise", "shapes"])
    def test_a_frame_with_no_objects_yields_no_confident_detections(
        self, detector, frame
    ):
        payload = {"blank": _blank, "noise": _noise, "shapes": _shapes}[frame]()

        metrics = detector.run(payload).metrics

        assert metrics["detections"] == 0.0, (
            f"{frame} contains nothing from COCO; a confident detection "
            "here is a hallucination, not a finding"
        )

    def test_person_count_is_zero_on_a_frame_with_no_person(self, detector):
        assert detector.run(_shapes()).metrics["count_person"] == 0.0


class TestLifecycle:
    def test_release_frees_the_model_and_is_idempotent(self):
        experiment = EXPERIMENTS["object_detection"]()
        experiment.load(ExperimentSettings(device="cpu"))
        experiment.run(_blank())

        experiment.release()
        experiment.release()

        assert experiment._model is None

    def test_an_undecodable_frame_is_a_frame_level_failure(self, detector):
        from tower.modules.base import FrameProcessingError

        with pytest.raises(FrameProcessingError):
            detector.run(b"not a jpeg")
