"""Every metric an experiment emits must say how it combines.

The corpus harness used to classify metrics with an ALLOWLIST of names
and sum anything not on it. Eight of the eleven names were dead -- no
experiment had ever emitted them -- and fifteen genuinely rate-like
metrics were being summed, including `tracked_fraction`, which reported
~768 over the real corpus for a quantity that cannot exceed 1. The list
had been checked against the producers once and never again.

So this test does the checking, every run, by RUNNING each registered
experiment and comparing the keys it actually emits against the keys it
declares. Two directions matter and both are asserted:

* a metric emitted but not declared is the defect itself, and
* a metric declared but never emitted is the eight dead names.

The frames below are chosen to reach every branch that builds a metrics
dict -- optical flow alone has four, and three of them are the ones a
single-frame test never sees. A test that collected nothing would pass
vacuously, which is how this class of bug survives, so each experiment
also asserts that it collected something.
"""

import cv2
import numpy as np
import pytest

from tower.experiments import (
    EXPERIMENTS,
    ExperimentSettings,
    MetricKind,
    UnclassifiedMetricError,
    classify_metric,
    metric_kinds,
)
from tower.experiments.object_detection import TRACKED_CLASSES

# The two experiments whose headline is their whole result. Named here
# rather than derived from their declarations: deriving would make the
# "collected something" assertion below agree with whatever the code
# says, which is the shape of test this repository has shipped twice and
# does not want a third time.
METRICLESS = {"baseline", "edge_detection"}


def _encode(array: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", array, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    assert ok
    return buffer.tobytes()


def _textured(seed: int = 5, size=(240, 320), shift: int = 0) -> np.ndarray:
    """Blocky noise, optionally rolled -- JPEG destroys per-pixel noise,
    and a corner tracker needs structure the codec keeps."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (size[0] // 8, size[1] // 8, 3), dtype=np.uint8)
    image = cv2.resize(small, (size[1], size[0]), interpolation=cv2.INTER_NEAREST)
    return np.roll(image, shift, axis=1) if shift else image


def _flat(shade: int = 128, size=(240, 320)) -> np.ndarray:
    return np.full((*size, 3), shade, dtype=np.uint8)


def _jpeg_frames() -> list[bytes]:
    """A frame that measures well, a degenerate one, and a clipped one."""
    return [_encode(_textured()), _encode(_flat()), _encode(_flat(255))]


def _run_frames(name: str, frames: list[bytes]) -> tuple[set[str], int]:
    experiment = EXPERIMENTS[name]()
    experiment.load(ExperimentSettings(device="cpu"))
    emitted: set[str] = set()
    ran = 0
    try:
        for raw in frames:
            emitted |= set(experiment.run(raw).metrics)
            ran += 1
    finally:
        experiment.release()
    return emitted, ran


def _exercise_stateless(name: str) -> tuple[set[str], int]:
    return _run_frames(name, _jpeg_frames())


def _exercise_optical_flow(_name: str) -> tuple[set[str], int]:
    """Four metrics dicts, four situations.

    No reference at all; a reference with no corners to seed from; a
    reference whose resolution changed mid-stream; and a real tracked
    pair. Only the last one emits `mean_flow_px`, `max_flow_px`,
    `direction_coherence` and `rejected_by_forward_backward`.
    """
    frames = [
        _encode(_textured()),                       # first frame: no reference
        _encode(_textured(shift=4)),                # tracked pair
        _encode(_flat()),                           # nothing to seed from
        _encode(_flat()),                           # seeds None again
        _encode(_textured(size=(120, 160))),        # resolution changed
        _encode(_textured(size=(120, 160), shift=3)),  # tracked again
    ]
    return _run_frames("optical_flow", frames)


class _FakeTransform:
    """Stands in for the model's preprocessing. Identity, on purpose: the
    question here is which metric NAMES come out, and a real transform
    would only add a weight download to the answer."""

    def __call__(self, tensor):
        return tensor


def _exercise_object_detection(_name: str) -> tuple[set[str], int]:
    """The real `run()`, with the 13.4 MB of COCO weights replaced.

    The default suite must not reach the network, and the metric names
    are built by `run()` from `TRACKED_CLASSES` regardless of what the
    model says -- so a fake detector answers exactly the question this
    file asks, and the opt-in integration test covers the rest.
    """
    torch = pytest.importorskip("torch")

    class _FakeDetector:
        def __call__(self, batch):
            return [{
                "scores": torch.tensor([0.91, 0.62, 0.11]),
                "labels": torch.tensor([1, 2, 3]),
            }]

    experiment = EXPERIMENTS["object_detection"]()
    experiment._model = _FakeDetector()
    experiment._transform = _FakeTransform()
    experiment._device = torch.device("cpu")
    experiment._categories = ["__background__", *TRACKED_CLASSES, "spoon"]

    emitted: set[str] = set()
    ran = 0
    for raw in _jpeg_frames():
        emitted |= set(experiment.run(raw).metrics)
        ran += 1
    # No release(): nothing was loaded, and release() on a never-loaded
    # detector would be testing the loader, not the classification.
    return emitted, ran


def _exercise_depth(_name: str) -> tuple[set[str], int]:
    """The real `run()`, with MiDaS replaced. Same reasoning as above."""
    torch = pytest.importorskip("torch")

    class _FakeMidas:
        def __call__(self, tensor):
            return tensor

    experiment = EXPERIMENTS["depth"]()
    experiment._model = _FakeMidas()
    experiment._transform = lambda array: torch.from_numpy(
        np.ascontiguousarray(array).astype("float32")
    )
    experiment._device = torch.device("cpu")

    emitted: set[str] = set()
    ran = 0
    for raw in _jpeg_frames():
        emitted |= set(experiment.run(raw).metrics)
        ran += 1
    return emitted, ran


EXERCISERS = {
    "baseline": _exercise_stateless,
    "edge_detection": _exercise_stateless,
    "frame_quality": _exercise_stateless,
    "feature_detection": _exercise_stateless,
    "redaction_impact": _exercise_stateless,
    "optical_flow": _exercise_optical_flow,
    "object_detection": _exercise_object_detection,
    "depth": _exercise_depth,
}


def test_every_registered_experiment_is_actually_exercised_here():
    """A new experiment must not slip past this file by not being listed.

    Without this, adding an experiment to the registry would leave its
    metrics unchecked and the suite would stay green -- the same silence
    the allowlist offered.
    """
    assert set(EXERCISERS) == set(EXPERIMENTS)


@pytest.mark.parametrize("name", sorted(EXPERIMENTS))
def test_every_metric_the_experiment_emits_is_classified(name):
    emitted, ran = EXERCISERS[name](name)

    assert ran > 0, f"{name} ran on no frames; this test proved nothing"
    if name in METRICLESS:
        assert emitted == set(), f"{name} grew metrics; classify them"
    else:
        assert emitted, f"{name} emitted no metrics; this test proved nothing"

    unclassified = []
    for metric in sorted(emitted):
        try:
            kind = classify_metric(name, metric)
        except UnclassifiedMetricError:
            unclassified.append(metric)
            continue
        assert isinstance(kind, MetricKind)

    assert unclassified == [], (
        f"{name} emits {unclassified} without saying how they combine; "
        "add them to METRIC_KINDS"
    )


@pytest.mark.parametrize("name", sorted(EXPERIMENTS))
def test_no_experiment_classifies_a_metric_it_never_emits(name):
    """The other half of the defect: eight of eleven allowlist entries
    named metrics nothing produced, which is how nobody noticed the
    entries that were missing."""
    emitted, _ran = EXERCISERS[name](name)
    declared = set(metric_kinds(name))

    assert declared - emitted == set(), (
        f"{name} classifies metrics it never emits: {sorted(declared - emitted)}"
    )


def test_an_unclassified_metric_raises_rather_than_defaulting():
    with pytest.raises(UnclassifiedMetricError) as excinfo:
        classify_metric("frame_quality", "brand_new_fraction")

    # The message has to name the experiment and the metric, or the
    # failure costs a debugging session to interpret.
    assert "frame_quality" in str(excinfo.value)
    assert "brand_new_fraction" in str(excinfo.value)


def test_an_unknown_experiment_is_a_different_failure_from_an_unknown_metric():
    """Conflating them would send someone hunting a missing METRIC_KINDS
    entry when the real problem is a name typed wrong."""
    with pytest.raises(KeyError):
        metric_kinds("no_such_experiment")


def test_the_three_aggregations_and_the_refusal_are_all_in_use():
    """Each kind must be earning its place in a real declaration.

    `width` and `height` are the constants the harness used to SUM over
    9,199 frames; `dominant_direction_deg` is circular and has no mean.
    """
    in_use = {
        kind
        for name in EXPERIMENTS
        for kind in metric_kinds(name).values()
    }
    assert in_use == set(MetricKind)


def test_image_dimensions_are_constants_not_counts_or_rates():
    kinds = metric_kinds("frame_quality")
    assert kinds["width"] is MetricKind.CONSTANT
    assert kinds["height"] is MetricKind.CONSTANT


def test_the_metrics_that_were_being_summed_are_declared_rates():
    """The concrete list from the defect report, pinned.

    Not a restatement of the declarations: these are the names the old
    allowlist missed, and each one is a fraction, a magnitude or a mean.
    """
    assert metric_kinds("frame_quality")["sharpness_laplacian_var"] is MetricKind.RATE
    assert metric_kinds("frame_quality")["overexposed_fraction"] is MetricKind.RATE
    assert metric_kinds("optical_flow")["tracked_fraction"] is MetricKind.RATE
    assert metric_kinds("optical_flow")["direction_coherence"] is MetricKind.RATE
    assert metric_kinds("depth")["mean_relative_depth"] is MetricKind.RATE
    assert metric_kinds("object_detection")["score_threshold"] is MetricKind.CONSTANT
