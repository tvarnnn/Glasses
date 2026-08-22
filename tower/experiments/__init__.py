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

from dataclasses import dataclass, field
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


@runtime_checkable
class Experiment(Protocol):
    """One CV experiment, stateful or not.

    `load()` may allocate. `release()` must free whatever it allocated and
    must be safe to call twice, and safe after a partial load -- it runs
    on the FAILED transition, which can be reached from anywhere.
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

# name -> zero-argument factory. A FACTORY, not an instance: constructing
# a detector at import time would load model weights in any process that
# so much as imports this module, including every unrelated test.
EXPERIMENTS: dict[str, Callable[[], Experiment]] = {
    "baseline": lambda: StatelessExperiment("baseline", baseline.run),
    "edge_detection": lambda: StatelessExperiment(
        "edge_detection", edge_detection.run
    ),
    "frame_quality": lambda: StatelessExperiment("frame_quality", frame_quality.run),
    "feature_detection": lambda: StatelessExperiment(
        "feature_detection", feature_detection.run
    ),
    "redaction_impact": lambda: StatelessExperiment(
        "redaction_impact", redaction_impact.run
    ),
    "optical_flow": optical_flow.OpticalFlowExperiment,
    "object_detection": object_detection.ObjectDetectionExperiment,
    "depth": depth.DepthEstimation,
}
