import logging
import time

import cv2
import numpy as np

from tower.experiments import ExperimentResult
from tower.instrumentation import StageTimer
from tower.modules.base import FrameProcessingError

logger = logging.getLogger(__name__)


class DepthEstimation:
    """Stateful monocular depth estimation (MiDaS-small).

    Deliberately NOT registered in tower/experiments/__init__.py's
    EXPERIMENTS dict -- that registry is for pure stateless functions.
    This holds a loaded model across frames, so DepthEstimationModule
    owns an instance directly instead.

    Output is relative (inverse) depth, not metric distance -- MiDaS-
    small does not produce metric output. result_label says "relative"
    explicitly; treat as model inference, not measurement, per
    07-PLATFORM-CONSTRAINTS.md Limitation 1 / Core Principle 2.
    """

    def __init__(self) -> None:
        self._model = None
        self._transform = None
        self._device = None

    def load(self, device: str) -> None:
        import torch  # local import: torch is an optional [ml] extra;
        # nothing outside a depth-selected module may require it.

        start = time.perf_counter()
        self._device = torch.device(device)
        self._model = torch.hub.load("intel-isl/MiDaS", "MiDaS_small")
        self._model.to(self._device)
        self._model.eval()
        self._transform = torch.hub.load(
            "intel-isl/MiDaS", "transforms"
        ).small_transform
        load_ms = (time.perf_counter() - start) * 1000

        if self._device.type == "cuda":
            allocated_mb = torch.cuda.memory_allocated() / (1024 * 1024)
            logger.info(
                "[Tower][Module] depth model loaded on %s in %.1fms "
                "(torch %s, cuda runtime %s, %.1fMB allocated)",
                self._device,
                load_ms,
                torch.__version__,
                torch.version.cuda,
                allocated_mb,
            )
        else:
            logger.info(
                "[Tower][Module] depth model loaded on %s in %.1fms (torch %s)",
                self._device,
                load_ms,
                torch.__version__,
            )

    def release(self) -> None:
        if self._device is not None and self._device.type == "cuda":
            import torch

            peak_mb = torch.cuda.max_memory_allocated() / (1024 * 1024)
            logger.info(
                "[Tower][Module] depth experiment released; peak cuda allocation %.1fMB",
                peak_mb,
            )
            torch.cuda.empty_cache()
        self._model = None
        self._transform = None
        self._device = None

    def run(self, raw_bytes: bytes) -> ExperimentResult:
        timer = StageTimer()

        with timer.stage("decode"):
            array = np.frombuffer(raw_bytes, dtype=np.uint8)
            image = cv2.imdecode(array, cv2.IMREAD_COLOR)
            if image is None:
                raise FrameProcessingError("undecodable frame")
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        import torch  # deferred: only the stages below need it, so an
        # undecodable frame never requires torch to be installed at all.

        with timer.stage("preprocess"):
            input_tensor = self._transform(image_rgb).to(self._device)

        with timer.stage("inference"):
            with torch.inference_mode():
                prediction = self._model(input_tensor)

        with timer.stage("postprocess"):
            depth = prediction.squeeze().detach().cpu().numpy()
            mean_relative_depth = float(depth.mean())

        return ExperimentResult(
            result_value=mean_relative_depth,
            result_label="mean_relative_depth",
            processing_ms=timer.total_ms,
            stage_ms=timer.snapshot(),
        )
