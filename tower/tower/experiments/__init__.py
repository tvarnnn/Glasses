"""The Experimental CV Lab's own types: a result, a protocol, a registry.

Two shapes matter here.

`ExperimentResult` carries a MANDATORY headline (`result_value` +
`result_label`) and an OPTIONAL bag of `metrics`. The headline is a
discipline, not a limitation: an experiment that cannot name its single
most important number has not decided what it is measuring. The bag is
what makes the Lab useful at all -- frame quality has six things to say,
optical flow four, detection a count and a distribution, and a single
scalar threw all of that away.

`Experiment` is a protocol with `load`/`run`/`release` rather than a bare
callable. Before this, a stateful experiment cost a whole `Module`
subclass -- there were two of them sharing one descriptor id, purely
because the depth experiment holds a model across frames. Two of the five
experiments added in V1 are also stateful, so the callable-only registry
would have meant four more near-identical Module classes.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol, runtime_checkable

import cv2
import numpy as np

from tower.modules.base import FrameProcessingError


# ORB builds an image pyramid, and its internal resize asserts on a
# non-positive scale when either dimension is exactly 1. Measured across
# every (h, w) in 1..32: ORB fails if and only if a dimension is 1, and
# succeeds at 2xN and Nx2 including 2x1000. So the floor is 2, chosen
# from the measurement rather than from caution.
ORB_MIN_DIMENSION = 2


def _decode(raw_bytes: bytes, flag: int, min_dimension: int):
    """Decode a frame, or fail at FRAME scope -- never at module scope.

    Three distinct failure modes, all of which reach here and all of which
    would otherwise raise a bare `cv2.error`:

    1. `cv2.imdecode` returns **None** for a truncated file. Passing that
       to `cvtColor` raises.
    2. `cv2.imdecode` **raises** `!buf.empty()` for an empty buffer -- the
       `is None` check never sees it.
    3. A perfectly valid image with a **1-pixel dimension** decodes fine
       and then kills ORB.

    Why this matters more than it looks: `ModuleContainer.process` treats
    any exception that is not a `FrameProcessingError` as a MODULE
    failure, `mark_failed()` is terminal (FAILED can never return to
    UNLOADED), and the container is built once at process start with no
    swap path. So a single bad frame would end CV processing for every
    subsequent frame of every subsequent session, for the life of the
    server.

    All three are reachable from the wire. `tower/frames.py` validates a
    frame with `Image.open(...).size`, which parses the JPEG **header**
    only -- a truncated file passes it, and a 1x64 JPEG is not malformed
    at all, merely useless.
    """
    if not raw_bytes:
        raise FrameProcessingError("empty frame payload")
    array = np.frombuffer(raw_bytes, dtype=np.uint8)
    try:
        image = cv2.imdecode(array, flag)
    except cv2.error as exc:
        raise FrameProcessingError(f"undecodable frame: {exc}") from exc
    if image is None:
        raise FrameProcessingError("undecodable frame")
    height, width = image.shape[:2]
    if min(width, height) < min_dimension:
        raise FrameProcessingError(
            f"frame {width}x{height} is below the {min_dimension}px minimum "
            "this experiment can process"
        )
    return image


def decode_color(raw_bytes: bytes, *, min_dimension: int = 1):
    """Decode to BGR, or raise FrameProcessingError. See `_decode`."""
    return _decode(raw_bytes, cv2.IMREAD_COLOR, min_dimension)


def decode_gray(raw_bytes: bytes, *, min_dimension: int = 1):
    """Decode to grayscale, or raise FrameProcessingError. See `_decode`."""
    return _decode(raw_bytes, cv2.IMREAD_GRAYSCALE, min_dimension)


@dataclass(frozen=True)
class ExperimentSettings:
    """What an experiment may be told at load time.

    Deliberately tiny. Rule 4's prohibition on designing a generalised
    negotiation protocol before the real constraints are known applies
    here too: this grows a field when an experiment actually needs one.
    """

    device: str = "auto"


@dataclass(frozen=True)
class ExperimentResult:
    result_value: float
    result_label: str
    processing_ms: float
    stage_ms: dict[str, float]
    mean_intensity: float | None = None
    # Additional measurements, name -> number. Empty for an experiment
    # whose headline says everything. Floats only, on purpose: this is a
    # measurement channel, not a general result channel. A structured
    # result type is V1.0 work and is blocked.
    metrics: dict[str, float] = field(default_factory=dict)


class MetricKind(Enum):
    """How a per-frame metric may be combined across many frames.

    Only the EXPERIMENT knows this. A corpus harness looking at the name
    `tracked_fraction` can guess, and a harness that guesses wrong sums a
    fraction to 768 over 9,199 frames and prints it as though it meant
    something. So the producer declares it, next to the line that
    produces it, and a consumer that meets an undeclared metric raises.

    RATE      a per-frame quantity -- a fraction, a score, a mean, a
              magnitude. The corpus summary is its MEAN. Summing is
              nonsense.
    COUNT     a per-frame tally, including a 0/1 flag whose sum is "how
              many frames". The corpus summary is its SUM. Averaging
              throws away the total.
    CONSTANT  the same number every frame by construction -- an image
              dimension, a configured threshold. BOTH summing and
              averaging are meaningless; it is reported as the value (or
              values) observed, with how many frames carried each.
    UNAGGREGATED
              a per-frame number with no meaningful corpus aggregate at
              all. `dominant_direction_deg` is circular: the mean of 179
              and -179 degrees is 0, which is the direction neither frame
              was moving. The fourth kind exists because the alternative
              is to call such a metric a RATE and publish that 0 -- which
              is the exact defect the other three kinds were added to
              kill. Reported as a frame count and nothing else.
    """

    RATE = "rate"
    COUNT = "count"
    CONSTANT = "constant"
    UNAGGREGATED = "unaggregated"


class UnclassifiedMetricError(LookupError):
    """An experiment emitted a metric it never classified.

    Deliberately an ERROR rather than a default. The predecessor of this
    module classified by allowlist and SUMMED anything it did not
    recognise, so eight dead names and fifteen mis-summed rates went
    unnoticed for as long as nobody happened to read the totals. A
    silent default is what made that invisible; the loud failure is the
    fix.
    """


# What a value on the wire is: a thing this Tower measured, or a thing a
# model inferred. EXPERIMENTAL-CV.md is explicit that experiment output
# "is model inference, not a measured sensor fact, unless the experiment
# specifically validates against a ground-truth reference", and iOS makes
# provenance a REQUIRED field on every metric rather than an optional one
# -- so the party that decodes a reply has to answer it. There is no
# third value and no default: an experiment declares one or it cannot be
# registered.
PROVENANCE_MEASURED = "measured"
PROVENANCE_INFERRED = "inferred"


@dataclass(frozen=True)
class ExperimentMetadata:
    """What the Lab can say about an experiment before it runs a frame.

    Presentation, not internals. `METRIC_KINDS` lives beside the code that
    produces the numbers because only that code knows how they combine;
    this lives beside the registration because it is the WIRE surface --
    the name a person reads, the unit a figure is rendered with, and
    whether the figure was measured or inferred. Keeping it here is what
    lets one test assert that every registered experiment has it.

    `metric_units` is deliberately partial. `IOS-to-Tower.md` 0.5: iOS
    "renders a figure with the unit the Tower names and BARE when it names
    none -- a bare number being the honest rendering of an unlabelled
    quantity". An ORB response and a relative inverse depth have no unit,
    and inventing one for them would be worse than the bare number.

    `annotation_metric` names the metric that is an annotation COUNT, if
    the experiment produces one. Only `object_detection` does. A keypoint
    is not an annotation and a fraction is not one either; naming one
    would put a number in a field iOS renders as "things found in this
    frame".
    """

    name: str
    summary: str
    provenance: str
    stateful: bool
    requires_model: bool
    # The `result_label` this experiment will emit. Declared rather than
    # discovered so the Lab can say what an experiment measures BEFORE
    # anyone starts it, and pinned against the real thing by
    # `test_the_declared_headline_is_the_one_the_experiment_emits`.
    headline_label: str
    # What actually does the work. `opencv` or `torch` today. Declared,
    # not derived from `requires_model`: the two coincide for all eight
    # registered experiments and there is no reason a future one could
    # not be a model-free torch kernel or a model-backed OpenCV DNN.
    backend: str
    headline_unit: str | None = None
    metric_units: Mapping[str, str] = field(default_factory=dict)
    annotation_metric: str | None = None

    def __post_init__(self) -> None:
        if self.provenance not in (PROVENANCE_MEASURED, PROVENANCE_INFERRED):
            raise ValueError(
                f"provenance must be {PROVENANCE_MEASURED!r} or "
                f"{PROVENANCE_INFERRED!r}, got {self.provenance!r}"
            )


@runtime_checkable
class Experiment(Protocol):
    """One CV experiment, stateful or not.

    `load()` may allocate. `release()` must free whatever it allocated and
    must be safe to call twice, and safe after a partial load -- it runs
    on the FAILED transition, which can be reached from anywhere.

    There is a fourth method, `describe() -> dict`, which is **optional**
    and deliberately not declared here. An experiment that holds a model
    implements it to report what it actually loaded -- the resolved
    device, the weights, the threshold -- because `TOWER_CV_DEVICE=auto`
    is a request and `resolve_device` decides the answer, so a run
    labelled "auto" has not said whether it used the GPU. An experiment
    that holds nothing has nothing to describe, and the Lab reports
    nothing rather than inventing a device it does not have. Adding it to
    the protocol would make six experiments implement a method returning
    an empty dict.
    """

    name: str

    def load(self, settings: ExperimentSettings) -> None: ...

    def run(self, raw_bytes: bytes) -> ExperimentResult: ...

    def release(self) -> None: ...


class StatelessExperiment:
    """Adapts a plain `bytes -> ExperimentResult` function to the protocol.

    Keeps a stateless experiment costing exactly one function to write.
    """

    def __init__(self, name: str, run: Callable[[bytes], ExperimentResult]) -> None:
        self.name = name
        self._run = run

    def load(self, settings: ExperimentSettings) -> None:
        return None

    def run(self, raw_bytes: bytes) -> ExperimentResult:
        return self._run(raw_bytes)

    def release(self) -> None:
        return None


# Import order here is deliberate, not incidental: the types above must be
# defined before the submodules that import them. By the time this runs,
# this (partially-initialized) module already has them set as attributes,
# so the circular import resolves. Moving these imports above the
# definitions breaks every submodule at import time.
from tower.experiments import (  # noqa: E402
    baseline,
    depth,
    edge_detection,
    feature_detection,
    frame_quality,
    object_detection,
    optical_flow,
    redaction_impact,
)

# `depth.py` is under review in another lane and cannot be edited in this
# change, so its declaration sits here rather than beside the metrics it
# describes, where the other seven live. It belongs in `depth.py` and
# moves there the moment that file is writable again. Nothing depends on
# the location: `_REGISTRY` below cannot hold a factory without a
# declaration either way.
_DEPTH_METRIC_KINDS: dict[str, MetricKind] = {
    "mean_relative_depth": MetricKind.RATE,
    "min_relative_depth": MetricKind.RATE,
    "max_relative_depth": MetricKind.RATE,
    "std_relative_depth": MetricKind.RATE,
}


@dataclass(frozen=True)
class ExperimentRegistration:
    """A factory and, inseparably, what its numbers mean and are called.

    One record rather than three parallel dicts, so that registering an
    experiment without classifying its metrics -- or without saying what
    a person should call it and whether it measured or inferred -- is not
    a thing that can be done and then forgotten. It is a missing
    positional argument.

    `metadata` joined `metric_kinds` when the Lab stopped being selected
    by an environment variable. An experiment nobody can name is fine
    when the only way to pick one is to type its registry key into a
    shell; it is not fine when a phone lists them.
    """

    factory: Callable[[], Experiment]
    metric_kinds: Mapping[str, MetricKind]
    metadata: ExperimentMetadata


# name -> registration. A FACTORY, not an instance: constructing a
# detector at import time would load model weights in any process that so
# much as imports this module, including every unrelated test.
# Units, stated once each. Named rather than repeated so that two
# experiments reporting the same kind of quantity cannot drift into
# calling it two different things on the wire.
_FRACTION = "fraction"
_PIXELS = "px"
_LEVEL = "level"
_KEYPOINTS = "keypoints"
_SECONDS = "s"
_DEGREES = "deg"

_REGISTRY: dict[str, ExperimentRegistration] = {
    "baseline": ExperimentRegistration(
        lambda: StatelessExperiment("baseline", baseline.run),
        baseline.METRIC_KINDS,
        ExperimentMetadata(
            name="Baseline",
            headline_label="mean_intensity",
            backend="opencv",
            summary=(
                "Mean grayscale intensity of the frame. The cheapest thing "
                "that proves the whole glasses -> phone -> Tower -> CV path "
                "is alive."
            ),
            provenance=PROVENANCE_MEASURED,
            stateful=False,
            requires_model=False,
            # 8-bit intensity level, 0-255, not a fraction. It is
            # `gray.mean()` and nothing normalises it.
            headline_unit=_LEVEL,
        ),
    ),
    "edge_detection": ExperimentRegistration(
        lambda: StatelessExperiment("edge_detection", edge_detection.run),
        edge_detection.METRIC_KINDS,
        ExperimentMetadata(
            name="Edge detection",
            headline_label="edge_density",
            backend="opencv",
            summary=(
                "Fraction of pixels Canny calls an edge, after a Gaussian "
                "blur. Moves visibly between a blank wall and a cluttered "
                "desk."
            ),
            provenance=PROVENANCE_MEASURED,
            stateful=False,
            requires_model=False,
            headline_unit=_FRACTION,
        ),
    ),
    "frame_quality": ExperimentRegistration(
        lambda: StatelessExperiment("frame_quality", frame_quality.run),
        frame_quality.METRIC_KINDS,
        ExperimentMetadata(
            name="Frame quality",
            headline_label="sharpness_laplacian_var",
            backend="opencv",
            summary=(
                "Six usability signals from one decode -- sharpness, "
                "gradient energy, entropy, contrast, edge density and "
                "clipping -- so a threshold gets chosen from a "
                "distribution rather than from taste."
            ),
            provenance=PROVENANCE_MEASURED,
            stateful=False,
            requires_model=False,
            # Variance of a Laplacian over 8-bit levels. Squared levels is
            # what it is; a nicer word would name a quantity nobody could
            # reproduce.
            headline_unit="level^2",
            metric_units={
                "sharpness_laplacian_var": "level^2",
                "gradient_energy": _LEVEL,
                "entropy_bits": "bits",
                "contrast_std": _LEVEL,
                "edge_density": _FRACTION,
                "overexposed_fraction": _FRACTION,
                "underexposed_fraction": _FRACTION,
                "width": _PIXELS,
                "height": _PIXELS,
            },
        ),
    ),
    "feature_detection": ExperimentRegistration(
        lambda: StatelessExperiment("feature_detection", feature_detection.run),
        feature_detection.METRIC_KINDS,
        ExperimentMetadata(
            name="Feature detection",
            headline_label="keypoint_count",
            backend="opencv",
            summary=(
                "How much trackable ORB texture a frame contains, and how "
                "evenly it is spread. A thousand keypoints in one corner is "
                "worse for geometry than three hundred across the view."
            ),
            provenance=PROVENANCE_MEASURED,
            stateful=False,
            requires_model=False,
            headline_unit=_KEYPOINTS,
            metric_units={
                "keypoint_count": _KEYPOINTS,
                "descriptor_count": "descriptors",
                "spatial_coverage": _FRACTION,
                # `mean_response` is deliberately absent: ORB's response
                # is a corner score on an arbitrary scale, and a bare
                # number is the honest rendering of it.
                "mean_keypoint_size": _PIXELS,
                "requested_features": _KEYPOINTS,
            },
        ),
    ),
    "redaction_impact": ExperimentRegistration(
        lambda: StatelessExperiment("redaction_impact", redaction_impact.run),
        redaction_impact.METRIC_KINDS,
        ExperimentMetadata(
            name="Redaction impact",
            headline_label="region_keypoint_retention",
            backend="opencv",
            summary=(
                "What blurring a region costs the geometry that runs after "
                "it: how many keypoints survive inside the blur, and how "
                "many survivors sit on its boundary rather than on the "
                "scene."
            ),
            provenance=PROVENANCE_MEASURED,
            stateful=False,
            requires_model=False,
            headline_unit=_FRACTION,
            metric_units={
                "region_keypoint_retention": _FRACTION,
                "frame_keypoint_retention": _FRACTION,
                "keypoints_before": _KEYPOINTS,
                "keypoints_after": _KEYPOINTS,
                "keypoints_lost": _KEYPOINTS,
                "keypoints_in_region_before": _KEYPOINTS,
                "keypoints_in_region_after": _KEYPOINTS,
                "survivors_near_region": _KEYPOINTS,
                "survivors_on_boundary": _KEYPOINTS,
                "boundary_fraction": _FRACTION,
                "region_area_fraction": _FRACTION,
                "blur_kernel": _PIXELS,
            },
        ),
    ),
    "optical_flow": ExperimentRegistration(
        optical_flow.OpticalFlowExperiment,
        optical_flow.METRIC_KINDS,
        ExperimentMetadata(
            name="Optical flow",
            headline_label="median_flow_px",
            backend="opencv",
            summary=(
                "How much the scene is moving and how coherently, from "
                "sparse Lucas-Kanade with a forward-backward check. The "
                "first frame of a session has no answer and says so."
            ),
            provenance=PROVENANCE_MEASURED,
            stateful=True,
            requires_model=False,
            headline_unit=_PIXELS,
            metric_units={
                "median_flow_px": _PIXELS,
                "mean_flow_px": _PIXELS,
                "max_flow_px": _PIXELS,
                "tracked_fraction": _FRACTION,
                "tracked_count": _KEYPOINTS,
                "seeded_count": _KEYPOINTS,
                "median_forward_backward_px": _PIXELS,
                "rejected_by_forward_backward": _KEYPOINTS,
                "direction_coherence": _FRACTION,
                "dominant_direction_deg": _DEGREES,
                # The three flags are 0/1 per frame and COUNT-kind, so
                # their corpus total is a number of frames.
                "has_reference": "frames",
                "resolution_changed": "frames",
                "reference_stale": "frames",
                "seconds_since_reference": _SECONDS,
            },
        ),
    ),
    "object_detection": ExperimentRegistration(
        object_detection.ObjectDetectionExperiment,
        object_detection.METRIC_KINDS,
        ExperimentMetadata(
            name="Object detection",
            headline_label="detections",
            backend="torch",
            summary=(
                "COCO classes from SSDLite/MobileNetV3, reported with the "
                "score they cleared. Evidence that something scored above a "
                "threshold -- not a statement that an object is there."
            ),
            # Model inference. object_detection.py's own header says so in
            # as many words, and Rule 16 / Core Principle 2 require that to
            # travel with the number rather than sit in a docstring.
            provenance=PROVENANCE_INFERRED,
            stateful=True,
            requires_model=True,
            headline_unit="detections",
            metric_units={
                "detections": "detections",
                "raw_detections": "detections",
                "score_threshold": "score",
                "mean_score": "score",
                "max_score": "score",
                **{
                    "count_" + name.replace(" ", "_"): "detections"
                    for name in object_detection.TRACKED_CLASSES
                },
            },
            annotation_metric="detections",
        ),
    ),
    "depth": ExperimentRegistration(
        depth.DepthEstimation,
        _DEPTH_METRIC_KINDS,
        ExperimentMetadata(
            name="Monocular depth",
            headline_label="mean_relative_depth",
            backend="torch",
            summary=(
                "Relative inverse depth from MiDaS-small. NOT metric "
                "distance: the model does not produce one, and no figure "
                "here may be read as metres."
            ),
            provenance=PROVENANCE_INFERRED,
            stateful=True,
            requires_model=True,
            # Deliberately unitless. IOS-to-Tower.md 0.5: "metric is not
            # metres". MiDaS-small emits relative inverse depth on an
            # arbitrary scale, so a bare number is the honest rendering
            # and any unit string here would be a claim about scale.
            headline_unit=None,
        ),
    ),
}

# The long-standing public shape, derived rather than duplicated: every
# caller that only wants "name -> factory" keeps working, and the two
# cannot drift apart because there is only one list.
EXPERIMENTS: dict[str, Callable[[], Experiment]] = {
    name: registration.factory for name, registration in _REGISTRY.items()
}


def experiment_metadata(experiment_name: str) -> ExperimentMetadata:
    """What to call this experiment and what its numbers are. Or KeyError.

    Separate from `metric_kinds` because the two answer different
    questions and a caller usually wants one of them, but they come from
    the same record and therefore cannot disagree about which experiments
    exist.
    """
    return _REGISTRY[experiment_name].metadata


def metric_kinds(experiment_name: str) -> Mapping[str, MetricKind]:
    """What every metric this experiment emits means. KeyError names a
    registry miss, which is a different bug from an unclassified metric
    and is therefore a different exception."""
    return _REGISTRY[experiment_name].metric_kinds


def classify_metric(experiment_name: str, metric_name: str) -> MetricKind:
    """How to combine one metric across frames, or raise.

    There is no default. See `UnclassifiedMetricError`.
    """
    kinds = metric_kinds(experiment_name)
    try:
        return kinds[metric_name]
    except KeyError:
        raise UnclassifiedMetricError(
            f"{experiment_name} emitted {metric_name!r}, which it never "
            f"classified. Add it to METRIC_KINDS in the experiment as one "
            f"of {', '.join(k.name for k in MetricKind)} -- the experiment "
            f"is the only thing that knows which. Classified: "
            f"{sorted(kinds)}"
        ) from None
