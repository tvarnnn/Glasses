import logging
import time

import cv2
import numpy as np

from tower.experiments import ExperimentResult, ExperimentSettings, decode_color
from tower.instrumentation import StageTimer
from tower.modules.base import FrameProcessingError

logger = logging.getLogger(__name__)


def resolve_device(requested: str) -> str:
    """Turn a requested device into one that actually exists.

    "auto" means CUDA if it is genuinely usable, else CPU. Asking for
    "cuda" on a machine without it is an error rather than a silent
    downgrade -- an unnoticed downgrade turns a GPU benchmark into a CPU
    benchmark with a GPU label on it, which is worse than a failure.
    """
    if requested == "cpu":
        return "cpu"

    import torch

    available = torch.cuda.is_available()
    if requested == "auto":
        return "cuda" if available else "cpu"
    if requested == "cuda" and not available:
        raise RuntimeError("cuda requested but torch reports it is unavailable")
    return requested


class DepthEstimation:
    """Stateful monocular depth estimation (MiDaS-small).

    Output is relative (inverse) depth, not metric distance -- MiDaS-
    small does not produce metric output. result_label says "relative"
    explicitly; treat as model inference, not measurement, per
    07-PLATFORM-CONSTRAINTS.md Limitation 1 / Core Principle 2.
    """

    name = "depth"

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

    def load(self, settings: ExperimentSettings | None = None) -> None:
        device = resolve_device(
            "auto" if settings is None else settings.device
        )
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
            image_rgb = cv2.cvtColor(decode_color(raw_bytes), cv2.COLOR_BGR2RGB)

        import torch  # deferred: only the stages below need it, so an
        # undecodable frame never requires torch to be installed at all.

        with timer.stage("preprocess"):
            try:
                input_tensor = self._transform(image_rgb).to(self._device)
            except cv2.error as exc:
                # MiDaS's transform resizes, and its internal cv2.resize
                # asserts on a non-positive scale for an extreme aspect
                # ratio (measured: 1x1000 and 1000x1 both fail; 1x1 and
                # 16x16 are fine, so this is about the RATIO, not size).
                # Without this the bare cv2.error marks the whole module
                # FAILED, terminally, for the life of the process.
                raise FrameProcessingError(
                    f"frame {image_rgb.shape[1]}x{image_rgb.shape[0]} could "
                    f"not be prepared for the depth model: {exc}"
                ) from exc

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
            metrics={
                "mean_relative_depth": mean_relative_depth,
                "min_relative_depth": float(depth.min()),
                "max_relative_depth": float(depth.max()),
                "std_relative_depth": float(depth.std()),
            },
        )
