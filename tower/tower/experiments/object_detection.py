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

import logging

import cv2
import numpy as np

from tower.experiments import ExperimentResult, ExperimentSettings, MetricKind
from tower.instrumentation import StageTimer
from tower.loading import LoadInvalidation
from tower.modules.base import FrameProcessingError

logger = logging.getLogger(__name__)

# Below this a COCO detection from a mobile-class detector is noise more
# often than not. Reported as a metric so the choice stays visible, and
# raw counts at 0.0 are reported too so the threshold can be re-chosen
# from data instead of from this comment.
SCORE_THRESHOLD = 0.4

# Reported individually because a Scene Understanding cartridge asks about
# them by name. Everything else is folded into `detections`.
TRACKED_CLASSES = ("person", "chair", "couch", "dining table", "tv", "laptop")

# `score_threshold` is SCORE_THRESHOLD echoed back on every frame: a
# constant, and the old harness AVERAGED it, which happened to give the
# right number for the wrong reason. The per-class entries are derived
# from TRACKED_CLASSES rather than typed out, so a class added above
# cannot arrive unclassified.
METRIC_KINDS: dict[str, MetricKind] = {
    "detections": MetricKind.COUNT,
    "raw_detections": MetricKind.COUNT,
    "score_threshold": MetricKind.CONSTANT,
    "mean_score": MetricKind.RATE,
    "max_score": MetricKind.RATE,
    **{
        f"count_{name.replace(' ', '_')}": MetricKind.COUNT
        for name in TRACKED_CLASSES
    },
}


class ObjectDetectionExperiment:
    name = "object_detection"

    def __init__(self) -> None:
        self._model = None
        self._transform = None
        self._device = None
        self._categories = None
        # What was ASKED for, kept beside what was resolved.
        # `auto` resolving to `cpu` on a machine with no CUDA is a
        # correct outcome; `cuda` resolving to `cpu` would be a
        # silent downgrade, and only both numbers together can
        # tell the two apart after the fact.
        self._requested_device = None
        # Guards the handover from a load that may have been abandoned by
        # the module's load timeout. See tower/loading.py.
        self._invalidation = LoadInvalidation()

    def _install(self, model, transform, categories, device) -> None:
        """Hand the loaded model to `self`. Runs under the token's lock."""
        self._model = model
        self._transform = transform
        self._categories = categories
        self._device = device

    def load(self, settings: ExperimentSettings | None = None) -> None:
        # Local imports: torch/torchvision are an optional [ml] extra, and
        # nothing outside a detection-selected module may require them.
        import torch
        from torchvision.models.detection import (
            SSDLite320_MobileNet_V3_Large_Weights,
            ssdlite320_mobilenet_v3_large,
        )

        from tower.experiments.depth import resolve_device

        requested = "auto" if settings is None else settings.device
        self._requested_device = requested
        # "auto" resolves to CPU for THIS experiment, and only this one.
        #
        # `resolve_device("auto")` prefers CUDA whenever it exists, which
        # is right for `depth` and wrong here. Measured at the delivered
        # 360x640, same-process interleaved A/B, 480 timed frames per
        # device, 30 warm-up frames each so CUDA context creation is
        # excluded, block order alternated:
        #
        #     object_detection   cpu 29.41 ms   cuda 38.17 ms   CPU faster
        #     depth              cpu 20.03 ms   cuda 10.41 ms   CUDA faster
        #
        # CUDA lost every one of eight blocks for object_detection and won
        # every one for depth, so flipping `auto` globally would fix one
        # experiment by making the other roughly twice as slow. The choice
        # belongs per experiment. Confirmed in separate processes at 1,000
        # frames per cell (cpu 26.91 vs cuda 34.78), and an independent
        # audit measured the same direction and magnitude (28.39 vs
        # 35.85).
        #
        # It also returns VRAM: this model reserved 196 MB of peak GPU
        # memory to be slower.
        #
        # WHY: `config.py`'s `scene_device` comment explains it for the
        # same model -- MobileNetV3 at an internal 320 px is bound by
        # kernel-launch overhead, not arithmetic -- and it is worth more
        # here than there, because the CV Lab's `process()` runs
        # SYNCHRONOUSLY ON THE EVENT LOOP.
        #
        # AND IT CONTRADICTS THAT COMMENT'S NUMBERS, which say ssdlite320
        # is 30.4 ms on CUDA against 32.9 ms on CPU -- CUDA faster by 8%.
        # Two independent measurements now disagree with it in the same
        # direction and by a larger margin. That older figure is left
        # standing rather than edited, because it was taken on a different
        # harness and this lane did not re-run ITS harness; a successor
        # re-measuring `scene_device` should know both exist.
        #
        # An explicit `TOWER_CV_DEVICE=cuda` still forces CUDA. This
        # changes what "auto" means, not what is reachable.
        if requested == "auto":
            requested = "cpu"
        device = resolve_device(requested)
        weights = SSDLite320_MobileNet_V3_Large_Weights.COCO_V1
        model = ssdlite320_mobilenet_v3_large(weights=weights)
        model.eval()
        # Locals until the very last line, then installed through the
        # invalidation token. This runs on a worker thread so that the
        # module's load timeout can actually bound the weight download --
        # and a timeout ABANDONS this thread rather than stopping it, so
        # `release()` may already have run by the time we get here.
        # Assigning `self._model` directly would hand a live model, and on
        # CUDA resident GPU memory, to a FAILED module that will never be
        # released again.
        torch_device = torch.device(device)
        try:
            model.to(torch_device)
            # Built out here rather than inside the publish lambda: they
            # can raise, and raising inside `install` would do so while
            # the token's lock is held, with the model already resident
            # and nothing covering it. The token guards the publish, not
            # the build, so the build guards itself.
            transform = weights.transforms()
            categories = list(weights.meta["categories"])
        except BaseException:
            # This frame owns the model and nothing installed it, so this
            # frame frees it -- before the traceback that would otherwise
            # pin it escapes to the container's `except` block, which
            # calls `release()` while the traceback is still live.
            del model
            if torch_device.type == "cuda":
                torch.cuda.empty_cache()
            raise
        if not self._invalidation.publish(
            lambda: self._install(model, transform, categories, torch_device)
        ):
            del model
            if torch_device.type == "cuda":
                torch.cuda.empty_cache()
            logger.warning(
                "[Tower][Module] object detection weights finished loading "
                "after the module was released; discarded"
            )

    def _clear(self) -> None:
        """Forget everything the load installed. Runs under the token's lock."""
        self._model = None
        self._transform = None
        self._categories = None
        self._device = None

    def release(self) -> None:
        # The device is read INSIDE the teardown so that one lock covers
        # both the question and the answer. Reading it before invalidating
        # -- as this used to -- is a TOCTOU: an abandoned loader that
        # publishes in between makes `publish()` return True, so the
        # loader skips its own `empty_cache()`, `_clear` drops the CUDA
        # model, and the stale False here means `empty_cache()` runs
        # nowhere at all. Same shape as depth.py's `release()`.
        was_cuda: list[bool] = []

        def _teardown() -> None:
            # Runs under the token's lock, and must not touch the token.
            if self._device is not None and self._device.type == "cuda":
                was_cuda.append(True)
            self._clear()

        # Invalidate and clear as one critical section: clearing first
        # would leave a window in which an abandoned loader installs into
        # a slot that has just been emptied.
        self._invalidation.invalidate(_teardown)
        if was_cuda:
            import torch

            torch.cuda.empty_cache()

    def describe(self) -> dict:
        """Runtime facts about what is actually loaded. Never raises.

        OPTIONAL on the `Experiment` protocol, and the Lab treats a
        missing `describe()` as "this experiment holds nothing worth
        reporting" rather than as an error. It exists because
        `TOWER_CV_DEVICE=auto` is a REQUEST and `resolve_device` decides
        the answer: a run that says "auto" has not told anyone whether it
        used the GPU, and a CPU figure with a GPU label on it is the
        specific failure `resolve_device` was written to prevent.

        Read outside the invalidation lock on purpose. This is a
        diagnostic, and taking the lock that guards a model handover in
        order to print a device name would let a status read contend with
        a load. A single attribute read is atomic; the worst case is a
        `null` device on a run that was mid-load a microsecond ago.
        """
        device = self._device
        return {
            "backend": "torch",
            "device": "unknown" if device is None else str(device),
            "device_requested": self._requested_device or "auto",
            "model": "ssdlite320_mobilenet_v3_large",
            "weights": "COCO_V1",
            "score_threshold": SCORE_THRESHOLD,
        }

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
