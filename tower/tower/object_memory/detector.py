"""Seeing objects, behind a seam.

**This does not import the Experimental CV Lab**, for the reason
`tower/scene/detect.py` already wrote down and a boundary test already
enforces there: the Lab's `ExperimentResult` is a scalar plus a
`name -> number` bag and cannot carry a box. `experiments/object_detection.py`
loads these exact weights and measured them (38.6 ms median on CUDA
across the real 9,199-frame corpus), which is what `EXPERIMENTAL-CV.md`'s
promotion path is for -- but it reports COUNTS, and a memory needs the
individual detection. Reusing it would also put a sandbox that may be
thrown away upstream of a persistent store.

The seam exists for the same second reason Document Memory's OCR has
one: the real detector costs a model download that a default test suite
must not pay for, and it lets the pipeline be tested against detections a
test wrote down rather than against whatever torchvision happened to
find.

Everything here is **model inference, not measured fact**
(`07-PLATFORM-CONSTRAINTS.md` Core Principle 2). A detection is evidence
that something scored above a threshold, and nothing more.
"""

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Below this a COCO detection from a mobile-class detector is noise more
# often than not. The relevance filter applies its own, higher, min_score
# on top; this one only decides what is worth returning at all.
SCORE_THRESHOLD = 0.4


@dataclass(frozen=True)
class Detection:
    """One detection, in FRAME PIXELS.

    Pixels here and fractions in the persisted record, deliberately: a
    detector reports what it saw in the image it was given, and only the
    thing that writes a durable record has to care that a stored box must
    still mean something at a different capture resolution.
    """

    label: str
    score: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2


@runtime_checkable
class Detector(Protocol):
    """Anything that can find objects in a decoded frame."""

    name: str

    def load(self) -> None: ...

    def detect(self, frame_bgr) -> list[Detection]: ...

    def release(self) -> None: ...


class FixedDetector:
    """Returns detections the caller chose. The default suite's detector.

    Not a mock of torchvision's behaviour -- a substitute for it, so the
    producer's tests assert against INDEPENDENT truth: the boxes are ones
    the test wrote down, so the correct record is known without asking
    the code.
    """

    name = "fixed"

    def __init__(self, frames=None) -> None:
        # One list of Detection per frame; the last is repeated once
        # exhausted, so a test can supply a short script and keep feeding.
        self._frames = [list(frame) for frame in (frames or [])]
        self.calls = 0

    def load(self) -> None:
        return None

    def detect(self, frame_bgr) -> list[Detection]:
        self.calls += 1
        if not self._frames:
            return []
        index = min(self.calls - 1, len(self._frames) - 1)
        return list(self._frames[index])

    def release(self) -> None:
        return None


class TorchvisionDetector:
    """`ssdlite320_mobilenet_v3_large`, COCO weights.

    torchvision, not ultralytics/YOLO: torchvision is already installed
    via the `ml` extra, so this adds no dependency and no AGPL
    obligation. 13.4 MB of weights, measured at 38.6 ms median per frame
    on this host's GPU over the real corpus.

    Its resolution-independence is a design constraint rather than
    trivia: the model resizes to 320 internally, so a larger frame costs
    decode time and buys nothing.
    """

    name = "ssdlite320"

    def __init__(
        self,
        score_threshold: float = SCORE_THRESHOLD,
        device: str = "cpu",
    ) -> None:
        self._score_threshold = score_threshold
        self._device = device
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
            "[Tower][ObjectMemory] detector loaded on %s (torch %s)",
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

        boxes = prediction["boxes"].detach().cpu().numpy()
        scores = prediction["scores"].detach().cpu().numpy()
        labels = prediction["labels"].detach().cpu().numpy()

        detections = []
        for box, score, label_index in zip(boxes, scores, labels):
            if score < self._score_threshold:
                continue
            detections.append(
                Detection(
                    label=self._categories[int(label_index)],
                    score=float(score),
                    box=tuple(float(value) for value in box),
                )
            )
        return detections

    def release(self) -> None:
        # Safe after a partial load, and after no load at all: a producer
        # that fails half way through loading still runs its finally.
        was_cuda = self._device.startswith("cuda")
        self._model = None
        self._transform = None
        self._categories = None
        self._torch_device = None
        if was_cuda:
            import torch

            torch.cuda.empty_cache()
