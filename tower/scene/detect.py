"""Seeing objects, behind a seam.

A seam for the same two reasons Document Memory's OCR has one: the real
detector costs ~32 ms and a model download, which a default test suite
should pay neither of; and the choice should follow measurement rather
than be welded into the pipeline.

**This does not import the Experimental CV Lab**, and a test enforces it.
The Lab measured this exact model -- 35.3 ms at 640x360, and notably
resolution-independent because it resizes to 320 internally -- which is
what `EXPERIMENTAL-CV.md`'s promotion path is for. But the Lab's
`ExperimentResult` is scalars and a `name -> number` bag; it cannot carry
a box. The two want different things from the same weights: the Lab wants
swappable models with timings, this wants stable structured output.

Everything here is **model inference, not measured fact**
(`07-PLATFORM-CONSTRAINTS.md` Core Principle 2). A detection is evidence
that something scored above a threshold.
"""

import logging
from typing import Protocol, runtime_checkable

from tower.scene.records import BoundingBox, Detection

logger = logging.getLogger(__name__)

# Below this a COCO detection from a mobile-class detector is noise more
# often than not. Reported alongside every scene state so the number is
# visible rather than buried, and so it can be re-chosen from data once
# real footage exists.
SCORE_THRESHOLD = 0.4

# The classes this cartridge reports. Not all 91: the brief's questions
# are about people and furniture, and a scene state cluttered with every
# COCO class would bury them. Adding one is a one-line change.
CLASSES_OF_INTEREST = (
    "person",
    "chair",
    "couch",
    "bed",
    "dining table",
    "tv",
    "laptop",
    "book",
    "bottle",
    "cup",
    "keyboard",
    "mouse",
    "cell phone",
)


@runtime_checkable
class Detector(Protocol):
    """Anything that can find objects in a frame."""

    name: str

    def load(self) -> None: ...

    def detect(self, frame_bgr) -> list[Detection]: ...

    def release(self) -> None: ...


class FixedDetector:
    """Returns detections the caller chose. The default suite's detector.

    Not a mock of torchvision's behaviour -- a substitute for it. It is
    what makes the pipeline tests assert against INDEPENDENT truth: the
    boxes are ones the test wrote down, so the correct count and the
    correct left/right relation are known without asking the code.
    """

    name = "fixed"

    def __init__(self, frames=None) -> None:
        # One list of Detection per frame; the last is repeated once
        # exhausted, so a test can supply a short script and keep feeding.
        self._frames = list(frames or [])
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
    """`ssdlite320_mobilenet_v3_large`, COCO weights, loaded lazily.

    Chosen because the Lab already measured it and because it costs **no
    new dependency** -- torchvision was already in the `ml` extra. 13.4 MB
    of weights, ~32 ms per frame on this CPU.

    Its resolution-independence is a design constraint, not trivia: the
    model resizes to 320 internally, so sending a larger frame costs
    decode time and buys nothing.
    """

    name = "ssdlite320"

    def __init__(
        self,
        score_threshold: float = SCORE_THRESHOLD,
        classes=CLASSES_OF_INTEREST,
        device: str = "cpu",
    ) -> None:
        self._score_threshold = score_threshold
        self._classes = set(classes) if classes else None
        self._device = device
        self._model = None
        self._transform = None
        self._categories = None

    def load(self) -> None:
        # Local imports: torch/torchvision are an optional [ml] extra and
        # nothing outside a detection path may require them.
        import torch
        from torchvision.models.detection import (
            SSDLite320_MobileNet_V3_Large_Weights,
            ssdlite320_mobilenet_v3_large,
        )

        weights = SSDLite320_MobileNet_V3_Large_Weights.COCO_V1
        model = ssdlite320_mobilenet_v3_large(weights=weights)
        model.eval()
        self._torch_device = torch.device(self._device)
        model.to(self._torch_device)
        self._model = model
        self._transform = weights.transforms()
        self._categories = list(weights.meta["categories"])

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
            label = self._categories[int(label_index)]
            if self._classes is not None and label not in self._classes:
                continue
            detections.append(
                Detection(
                    label=label,
                    score=float(score),
                    box=BoundingBox(*(float(value) for value in box)),
                )
            )
        return detections

    def release(self) -> None:
        was_cuda = self._device.startswith("cuda")
        self._model = None
        self._transform = None
        self._categories = None
        if was_cuda:
            import torch

            torch.cuda.empty_cache()
