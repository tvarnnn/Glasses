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


class TestAutoResolvesToTheFasterDeviceForThisModel:
    """`auto` means CPU here, and CUDA for `depth`. Measured, not assumed.

    `resolve_device("auto")` prefers CUDA wherever it exists, which is
    right for `depth` and wrong for this model. At the delivered 360x640,
    interleaved A/B with warm-up excluded: object_detection is 29.41 ms on
    CPU against 38.17 ms on CUDA, losing every one of eight blocks; depth
    is 20.03 against 10.41 the other way. Flipping `auto` globally would
    fix one experiment by making the other about twice as slow, so the
    preference belongs per experiment.

    It matters more than the milliseconds suggest: the CV Lab's
    `process()` runs synchronously on the event loop, so this is loop time
    every connection shares. It also stops reserving 196 MB of VRAM to be
    slower.
    """

    def test_auto_loads_this_model_onto_the_cpu(self):
        experiment = EXPERIMENTS["object_detection"]()
        experiment.load(ExperimentSettings(device="auto"))
        try:
            assert experiment._device.type == "cpu"
        finally:
            experiment.release()

    def test_the_request_is_still_reported_as_auto(self):
        """Provenance must say what was ASKED, not what was chosen.

        A status that reported `cpu` as the request would hide the fact
        that this Tower made a choice on the caller's behalf.
        """
        experiment = EXPERIMENTS["object_detection"]()
        experiment.load(ExperimentSettings(device="auto"))
        try:
            assert experiment._requested_device == "auto"
        finally:
            experiment.release()

    def test_an_explicit_cuda_request_is_still_honoured(self):
        """This changes what `auto` means, not what is reachable."""
        import torch

        if not torch.cuda.is_available():
            pytest.skip("no CUDA on this host")

        experiment = EXPERIMENTS["object_detection"]()
        experiment.load(ExperimentSettings(device="cuda"))
        try:
            assert experiment._device.type == "cuda"
        finally:
            experiment.release()

    def test_the_shared_resolver_is_unchanged(self):
        """The override is local. `depth` must still get CUDA from `auto`."""
        import torch

        from tower.experiments.depth import resolve_device

        expected = "cuda" if torch.cuda.is_available() else "cpu"
        assert resolve_device("auto") == expected


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
