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

    def __init__(self, capture_depth_array: bool = False) -> None:
        self._model = None
        self._transform = None
        self._device = None
        # Opt-in, bounded observability hook for offline research analysis
        # (World Builder Experiment 1, depth_temporal_consistency): the wire
        # protocol only carries the scalar mean, but temporal-stability
        # analysis needs the full per-frame array. Off by default so the
        # serving path is unchanged; holds only the most recent frame, never
        # a growing list, so enabling it cannot grow without bound.
        self.capture_depth_array = capture_depth_array
        self.last_depth_array = None

    def load(self, device: str) -> None:
        import torch  # local import: torch is an optional [ml] extra;
        # nothing outside a depth-selected module may require it.

        start = time.perf_counter()
        self._device = torch.device(device)
        # Pinned: floating on the default branch is a reproducibility risk
        # for a measured baseline, not theoretical -- see the spec's
        # 2026-08-20 Amendment for how this was discovered.
        midas_ref = "intel-isl/MiDaS:454597711a62eabcbf7d1e89f3fb9f569051ac9b"
        self._model = torch.hub.load(midas_ref, "MiDaS_small", trust_repo=True)
        self._model.to(self._device)
        self._model.eval()
        self._transform = torch.hub.load(
            midas_ref, "transforms", trust_repo=True
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
        is_cuda = self._device is not None and self._device.type == "cuda"
        if is_cuda:
            import torch

            peak_mb = torch.cuda.max_memory_allocated() / (1024 * 1024)

        self._model = None
        self._transform = None
        self._device = None
        self.last_depth_array = None

        if is_cuda:
            torch.cuda.empty_cache()
            logger.info(
                "[Tower][Module] depth experiment released; peak cuda allocation %.1fMB",
                peak_mb,
            )

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
            if self.capture_depth_array:
                self.last_depth_array = depth

        return ExperimentResult(
            result_value=mean_relative_depth,
            result_label="mean_relative_depth",
            processing_ms=timer.total_ms,
            stage_ms=timer.snapshot(),
        )
