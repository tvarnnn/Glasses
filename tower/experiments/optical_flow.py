"""How much is the scene moving, and how coherently.

Sparse Lucas-Kanade rather than dense Farneback. Measured on this host at
640x360: 2.9 ms against 25.4 ms for the same headline number. The dense
field is a better picture and an 8.8x worse deal, and the benchmark keeps
the comparison so the choice stays evidence rather than habit.

Stateful, because flow is a statement about a PAIR of frames. The first
frame of a session therefore has no answer, and this reports that
honestly -- zero tracked, magnitude zero, `has_reference` 0 -- rather
than inventing a still scene.

Forward-backward error is measured, not assumed: a track is kept only if
following it back lands near where it started. Without that check, flow
in a textureless region returns confident nonsense.
"""

import cv2
import numpy as np

from tower.experiments import ExperimentResult, ExperimentSettings
from tower.instrumentation import StageTimer
from tower.modules.base import FrameProcessingError

MAX_CORNERS = 300
CORNER_QUALITY = 0.01
MIN_CORNER_DISTANCE = 8
# A track that does not return to within this many pixels of its origin
# after being followed forward and then back is not a track.
MAX_FORWARD_BACKWARD_PX = 1.0
LK_PARAMS = dict(
    winSize=(21, 21),
    maxLevel=3,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
)


class OpticalFlowExperiment:
    name = "optical_flow"

    def __init__(self) -> None:
        self._previous = None

    def load(self, settings: ExperimentSettings | None = None) -> None:
        return None

    def release(self) -> None:
        # Holds one grayscale frame, not a model. Dropping it is the whole
        # of teardown -- but it must still happen, or a stopped experiment
        # keeps a frame of wearer imagery alive in memory.
        self._previous = None

    def run(self, raw_bytes: bytes) -> ExperimentResult:
        timer = StageTimer()

        with timer.stage("decode"):
            array = np.frombuffer(raw_bytes, dtype=np.uint8)
            gray = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
            if gray is None:
                raise FrameProcessingError("undecodable frame")

        previous = self._previous
        self._previous = gray

        if previous is None or previous.shape != gray.shape:
            # A resolution change also lands here. DAT's adaptive ladder
            # can change resolution mid-stream, and comparing frames of
            # different sizes would produce a large, meaningless flow.
            reason = 0.0 if previous is None else 1.0
            return ExperimentResult(
                result_value=0.0,
                result_label="median_flow_px",
                processing_ms=timer.total_ms,
                stage_ms=timer.snapshot(),
                metrics={
                    "median_flow_px": 0.0,
                    "tracked_fraction": 0.0,
                    "seeded_count": 0.0,
                    "tracked_count": 0.0,
                    "has_reference": 0.0,
                    "resolution_changed": reason,
                },
            )

        with timer.stage("seed"):
            seeds = cv2.goodFeaturesToTrack(
                previous,
                maxCorners=MAX_CORNERS,
                qualityLevel=CORNER_QUALITY,
                minDistance=MIN_CORNER_DISTANCE,
            )

        if seeds is None or len(seeds) == 0:
            return ExperimentResult(
                result_value=0.0,
                result_label="median_flow_px",
                processing_ms=timer.total_ms,
                stage_ms=timer.snapshot(),
                metrics={
                    "median_flow_px": 0.0,
                    "tracked_fraction": 0.0,
                    "seeded_count": 0.0,
                    "tracked_count": 0.0,
                    "has_reference": 1.0,
                    "resolution_changed": 0.0,
                },
            )

        with timer.stage("track"):
            forward, status_forward, _ = cv2.calcOpticalFlowPyrLK(
                previous, gray, seeds, None, **LK_PARAMS
            )
            backward, status_backward, _ = cv2.calcOpticalFlowPyrLK(
                gray, previous, forward, None, **LK_PARAMS
            )

        with timer.stage("summarize"):
            seeded = seeds.reshape(-1, 2)
            forward_points = forward.reshape(-1, 2)
            backward_points = backward.reshape(-1, 2)
            ok = (
                status_forward.reshape(-1).astype(bool)
                & status_backward.reshape(-1).astype(bool)
            )
            fb_error = np.linalg.norm(backward_points - seeded, axis=1)
            kept = ok & (fb_error <= MAX_FORWARD_BACKWARD_PX)

            tracked_count = int(kept.sum())
            seeded_count = int(len(seeded))
            if tracked_count == 0:
                metrics = {
                    "median_flow_px": 0.0,
                    "tracked_fraction": 0.0,
                    "seeded_count": float(seeded_count),
                    "tracked_count": 0.0,
                    "has_reference": 1.0,
                    "resolution_changed": 0.0,
                }
                return ExperimentResult(
                    result_value=0.0,
                    result_label="median_flow_px",
                    processing_ms=timer.total_ms,
                    stage_ms=timer.snapshot(),
                    metrics=metrics,
                )

            displacement = forward_points[kept] - seeded[kept]
            magnitudes = np.linalg.norm(displacement, axis=1)
            median_magnitude = float(np.median(magnitudes))

            # Direction coherence via the mean resultant length of the
            # displacement angles: 1.0 means every track agrees, 0.0 means
            # they cancel out. A mean of raw angles would be wrong -- the
            # average of 179 and -179 degrees is not 0.
            angles = np.arctan2(displacement[:, 1], displacement[:, 0])
            resultant = float(
                np.hypot(np.mean(np.cos(angles)), np.mean(np.sin(angles)))
            )
            dominant_direction_deg = float(
                np.degrees(
                    np.arctan2(np.mean(np.sin(angles)), np.mean(np.cos(angles)))
                )
            )

        return ExperimentResult(
            result_value=median_magnitude,
            result_label="median_flow_px",
            processing_ms=timer.total_ms,
            stage_ms=timer.snapshot(),
            metrics={
                "median_flow_px": median_magnitude,
                "mean_flow_px": float(magnitudes.mean()),
                "max_flow_px": float(magnitudes.max()),
                "tracked_fraction": tracked_count / seeded_count,
                "tracked_count": float(tracked_count),
                "seeded_count": float(seeded_count),
                "median_forward_backward_px": float(np.median(fb_error[kept])),
                "direction_coherence": resultant,
                "dominant_direction_deg": dominant_direction_deg,
                "has_reference": 1.0,
                "resolution_changed": 0.0,
            },
        )
