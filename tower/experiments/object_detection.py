"""What objects are in view, as a measurement rather than a product.

This exists for one concrete reason: a Scene Understanding cartridge
needs to choose a detector, and the module doc's promotion path says
measure in the Lab before promoting. COCO gives `person`, `chair` and
`dining table` -- literally the example questions that cartridge is meant
to answer -- so this is the measurement that decision needs.

`ssdlite320_mobilenet_v3_large` from torchvision, which is already an
installed dependency: 13.4 MB of weights, ~31 ms per frame on this CPU at
640x360. No new dependency earns its cost here.

**Output is model inference, not measured fact** (Rule 16, Core Principle
2). A detection is evidence that something scored above a threshold, and
the score is reported alongside the count so a consumer can see how thin
the evidence is. Nothing here establishes identity, and nothing persists.
"""

import cv2
import numpy as np

from tower.experiments import ExperimentResult, ExperimentSettings
from tower.instrumentation import StageTimer
from tower.modules.base import FrameProcessingError

# Below this a COCO detection from a mobile-class detector is noise more
# often than not. Reported as a metric so the choice stays visible, and
# raw counts at 0.0 are reported too so the threshold can be re-chosen
# from data instead of from this comment.
SCORE_THRESHOLD = 0.4

# Reported individually because a Scene Understanding cartridge asks about
# them by name. Everything else is folded into `detections`.
TRACKED_CLASSES = ("person", "chair", "couch", "dining table", "tv", "laptop")


class ObjectDetectionExperiment:
    name = "object_detection"

    def __init__(self) -> None:
        self._model = None
        self._transform = None
        self._device = None
        self._categories = None

    def load(self, settings: ExperimentSettings | None = None) -> None:
        # Local imports: torch/torchvision are an optional [ml] extra, and
        # nothing outside a detection-selected module may require them.
        import torch
        from torchvision.models.detection import (
            SSDLite320_MobileNet_V3_Large_Weights,
            ssdlite320_mobilenet_v3_large,
        )

        from tower.experiments.depth import resolve_device

        device = resolve_device("auto" if settings is None else settings.device)
        weights = SSDLite320_MobileNet_V3_Large_Weights.COCO_V1
        model = ssdlite320_mobilenet_v3_large(weights=weights)
        model.eval()
        self._device = torch.device(device)
        model.to(self._device)
        self._model = model
        self._transform = weights.transforms()
        self._categories = list(weights.meta["categories"])

    def release(self) -> None:
        was_cuda = self._device is not None and self._device.type == "cuda"
        self._model = None
        self._transform = None
        self._categories = None
        self._device = None
        if was_cuda:
            import torch

            torch.cuda.empty_cache()

    def run(self, raw_bytes: bytes) -> ExperimentResult:
        timer = StageTimer()

        with timer.stage("decode"):
            array = np.frombuffer(raw_bytes, dtype=np.uint8)
            image = cv2.imdecode(array, cv2.IMREAD_COLOR)
            if image is None:
                raise FrameProcessingError("undecodable frame")
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        import torch

        with timer.stage("preprocess"):
            tensor = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1)
            batch = [self._transform(tensor).to(self._device)]

        with timer.stage("inference"):
            with torch.inference_mode():
                outputs = self._model(batch)

        with timer.stage("summarize"):
            prediction = outputs[0]
            scores = prediction["scores"].detach().cpu().numpy()
            labels = prediction["labels"].detach().cpu().numpy()

            kept = scores >= SCORE_THRESHOLD
            kept_scores = scores[kept]
            kept_labels = labels[kept]

            metrics = {
                "detections": float(kept.sum()),
                "raw_detections": float(len(scores)),
                "score_threshold": SCORE_THRESHOLD,
                "mean_score": float(kept_scores.mean()) if kept.any() else 0.0,
                "max_score": float(scores.max()) if len(scores) else 0.0,
            }
            for name in TRACKED_CLASSES:
                index = self._categories.index(name)
                metrics[f"count_{name.replace(' ', '_')}"] = float(
                    (kept_labels == index).sum()
                )

        return ExperimentResult(
            result_value=metrics["detections"],
            result_label="detections",
            processing_ms=timer.total_ms,
            stage_ms=timer.snapshot(),
            metrics=metrics,
        )
