"""The platform's object-detection surface.

Promoted out of the cartridges once a THIRD consumer wanted the same
thing, exactly as `tower/confidence.py` was promoted once a second module
wanted the same four labels. Until then the duplication was the honest
answer and two boundary tests said so in their own docstrings; this file
is the outcome those docstrings named.

**What was duplicated, measured.** `tower/scene/detect.py` and
`tower/object_memory/detector.py` shared 130 of 190 lines verbatim: the
same `Detector` protocol, the same scripted fake, the same 0.4 threshold,
and the same twenty lines of load/infer/release around
`ssdlite320_mobilenet_v3_large`. Two copies of a threshold drift apart
silently; a `release()` that forgets `empty_cache()` in one copy leaks
GPU memory on one side only, and nothing says so.

**This promotes CODE, not model residency.** Every caller still
constructs its own detector and loads its own weights. SSDLite320 is
13.4 MB; three copies are noise, and no measurement in this repo shows
GPU contention. There is deliberately no registry, no cache and no
eviction policy here -- a model manager is a separate wave that needs its
own evidence, and `test_the_module_holds_no_mutable_global` is the
tripwire for one appearing by accident.

**It cannot become a central point of failure**, which is the property
that made the promotion defensible at all:

  * it holds no shared state, so one caller's detector cannot be emptied,
    poisoned or evicted by another's;
  * torch and torchvision are imported inside methods, never at module
    load, so a machine without the optional `[ml]` extra still starts --
    the blast radius of a module-level import here is wider than in a
    cartridge, because more things import shared code;
  * a detector that fails to load raises to the caller that asked for it,
    and nothing else. A cartridge that refuses to answer because it could
    not see keeps refusing HONESTLY, in its own words.

**It does not import a cartridge, and does not import the Lab.**
`experiments/object_detection.py` loads these same weights and measured
them, and stays separate on purpose: its `ExperimentResult` is scalars
and a `name -> number` bag, so it cannot carry a box. That is a different
question asked of the same model, not a third copy of this one -- and a
sandbox that may be thrown away must never sit upstream of a persistent
store.

**What a caller still owns.** The detection type it reports, the classes
it cares about, and the device it runs on. One consumer keeps every COCO
class because a memory of what was around cannot pre-judge what mattered;
another keeps thirteen because a live state cluttered with all ninety-one
buries the answer. Those are cartridge decisions and they stay in the
cartridges.

Everything here is **model inference, not measured fact**
(`07-PLATFORM-CONSTRAINTS.md` Core Principle 2). A detection is evidence
that something scored above a threshold, and nothing more.
"""

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Below this a COCO detection from a mobile-class detector is noise more
# often than not. One number, in one place: the version where each
# cartridge kept its own copy had them equal by coincidence rather than
# by construction. A consumer wanting a stricter bar applies its own on
# top -- Object Memory's relevance filter does -- rather than editing
# this one.
SCORE_THRESHOLD = 0.4


@dataclass(frozen=True)
class Detection:
    """One detection, in FRAME PIXELS.

    Pixels here and fractions in any persisted record, deliberately: a
    detector reports what it saw in the image it was given, and only the
    thing that writes a durable record has to care that a stored box must
    still mean something at a different capture resolution.

    A plain 4-tuple rather than a geometry type, because this is the
    narrowest shape that carries a box. A cartridge with richer geometry
    of its own -- Scene Understanding has a box type with IoU on it --
    converts at its own edge and keeps that type out of shared code.
    """

    label: str
    score: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2


@runtime_checkable
class Detector(Protocol):
    """Anything that can find objects in a decoded frame.

    `detect` is annotated as a plain list, not `list[Detection]`: a
    caller may report its own detection type, and this protocol describes
    the LIFECYCLE they share -- load, detect, release -- which is the
    part that was actually duplicated.
    """

    name: str

    def load(self) -> None: ...

    def detect(self, frame_bgr) -> list: ...

    def release(self) -> None: ...


class FixedDetector:
    """Returns detections the caller chose. The default suite's detector.

    Not a mock of torchvision's behaviour -- a substitute for it. It is
    what lets a pipeline test assert against INDEPENDENT truth: the boxes
    are ones the test wrote down, so the correct answer is known without
    asking the code. It is also why the default suite neither downloads
    weights nor pays ~32 ms a frame.

    Detection-type agnostic on purpose: it replays whatever it was
    handed, so a caller with its own detection type gets the same fake
    for free.
    """

    name = "fixed"

    def __init__(self, frames=None) -> None:
        # One list of detections per frame; the last is repeated once
        # exhausted, so a test can supply a short script and keep feeding.
        # Copied on the way in and on the way out, so a test that mutates
        # its own fixture cannot retune the detector, and a caller that
        # mutates a result cannot retune the script.
        self._frames = [list(frame) for frame in (frames or [])]
        self.calls = 0

    def load(self) -> None:
        return None

    def detect(self, frame_bgr) -> list:
        self.calls += 1
        if not self._frames:
            return []
        index = min(self.calls - 1, len(self._frames) - 1)
        return list(self._frames[index])

    def release(self) -> None:
        return None


def detections_from_prediction(
    boxes,
    scores,
    labels,
    categories,
    score_threshold: float = SCORE_THRESHOLD,
    classes=None,
) -> list[Detection]:
    """A torchvision prediction, reduced to detections.

    A free function rather than a method because it is the only part of
    the shared code with a DECISION in it -- a threshold and an optional
    class filter -- and a free function can be tested against three lists
    instead of against 13.4 MB of weights. That is most of what makes
    this module independently testable.

    `classes=None` means "every class the model knows", which is not the
    same as an empty filter and must not collapse into one.
    """
    keep = set(classes) if classes else None
    detections: list[Detection] = []
    for box, score, label_index in zip(boxes, scores, labels):
        if score < score_threshold:
            continue
        label = categories[int(label_index)]
        if keep is not None and label not in keep:
            continue
        detections.append(
            Detection(
                label=label,
                # float() on both, deliberately: a numpy scalar reaching a
                # persisted record makes its JSON depend on which numpy
                # is installed.
                score=float(score),
                box=tuple(float(value) for value in box),
            )
        )
    return detections


class SSDLite320Detector:
    """`ssdlite320_mobilenet_v3_large`, COCO weights, loaded lazily.

    torchvision, not ultralytics/YOLO: torchvision was already in the
    optional `ml` extra, so this adds no dependency and no AGPL
    obligation. 13.4 MB of weights, ~32 ms per frame on this CPU and
    38.6 ms median on this host's GPU over the real 9,199-frame corpus.

    Its resolution-independence is a design constraint rather than
    trivia: the model resizes to 320 internally, so sending a larger
    frame costs decode time and buys nothing.

    One instance owns one model. Constructing two loads the weights
    twice, and that is the intended behaviour -- see the module docstring
    on why residency was not promoted along with the code.
    """

    name = "ssdlite320"

    def __init__(
        self,
        score_threshold: float = SCORE_THRESHOLD,
        classes=None,
        device: str = "cpu",
        owner: str = "Tower",
    ) -> None:
        self._score_threshold = score_threshold
        self._classes = set(classes) if classes else None
        self._device = device
        # Whose log line this is. A shared detector logging under one
        # caller's name would make the other's logs lie about which
        # subsystem paid for the load.
        self._owner = owner
        self._model = None
        self._transform = None
        self._categories = None
        self._torch_device = None

    def load(self) -> None:
        # Local imports: torch/torchvision are an optional [ml] extra and
        # nothing outside a detection path may require them.
        import torch
        from torchvision.models.detection import (
            SSDLite320_MobileNet_V3_Large_Weights,
            ssdlite320_mobilenet_v3_large,
        )

        # Pinned by direct enum reference, not a string alias resolved at
        # runtime: a floating weights selection is a reproducibility risk
        # for any measured result, and a direct reference fails at import
        # rather than at load.
        weights = SSDLite320_MobileNet_V3_Large_Weights.COCO_V1
        model = ssdlite320_mobilenet_v3_large(weights=weights)
        model.eval()
        self._torch_device = torch.device(self._device)
        model.to(self._torch_device)
        self._model = model
        self._transform = weights.transforms()
        self._categories = list(weights.meta["categories"])
        logger.info(
            "[Tower][%s] detector loaded on %s (torch %s)",
            self._owner,
            self._torch_device,
            torch.__version__,
        )

    def detect(self, frame_bgr) -> list[Detection]:
        import numpy as np
        import torch

        if self._model is None:
            self.load()

        rgb = frame_bgr[:, :, ::-1]
        tensor = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1)
        batch = [self._transform(tensor).to(self._torch_device)]
        with torch.inference_mode():
            prediction = self._model(batch)[0]

        return detections_from_prediction(
            boxes=prediction["boxes"].detach().cpu().numpy(),
            scores=prediction["scores"].detach().cpu().numpy(),
            labels=prediction["labels"].detach().cpu().numpy(),
            categories=self._categories,
            score_threshold=self._score_threshold,
            classes=self._classes,
        )

    def release(self) -> None:
        # Safe after a partial load, and after no load at all: a caller
        # that fails half way through loading still runs its finally.
        was_cuda = self._device.startswith("cuda")
        self._model = None
        self._transform = None
        self._categories = None
        self._torch_device = None
        if was_cuda:
            import torch

            torch.cuda.empty_cache()
