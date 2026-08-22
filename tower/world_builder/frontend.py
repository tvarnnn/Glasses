"""The cheap per-frame path: decode, score quality, track, summarise motion.

Runs on every delivered frame. Measured at roughly 5 ms per frame at
360x640 against a ~300 ms delivered interval, so it is not a compute
problem and nothing here is optimised for speed at the cost of clarity.

Two disciplines govern this module:

**Nothing here reads a clock.** Frame spacing is variable, the sender
decimates frames, and there is no capture timestamp anywhere on the wire.
Every threshold is in pixels or ratios. A time-based rule would silently
mean something different at 3 fps than at 12 fps, and would confuse "the
user turned quickly" with "the network stalled".

**Nothing here needs intrinsics.** Everything measured is image-space, so
the same measurements are available whether or not the camera has ever
been calibrated -- which is what lets the uncalibrated backend still
report real evidence instead of nothing.
"""

from dataclasses import dataclass

import cv2
import numpy as np

# Feature seeding for tracking. Shi-Tomasi rather than ORB here: this is
# a tracking seed, not a matching problem, and goodFeaturesToTrack gives
# better-conditioned corners for Lucas-Kanade than ORB's FAST keypoints.
MAX_TRACK_POINTS = 600
TRACK_QUALITY_LEVEL = 0.01
TRACK_MIN_DISTANCE = 7
LK_WINDOW = (21, 21)
LK_MAX_LEVEL = 3

# Forward-backward consistency threshold in pixels. A track that does not
# land back where it started under the reverse flow is not a track, it is
# a coincidence.
FORWARD_BACKWARD_MAX_PX = 1.0

# Below this many surviving tracks nothing downstream is meaningful.
MIN_TRACKS_FOR_MOTION = 12

HOMOGRAPHY_RANSAC_PX = 3.0


@dataclass(frozen=True)
class FrameQuality:
    """Per-frame measurements that need no reference frame."""

    width: int
    height: int
    sharpness: float

    @property
    def diagonal_px(self) -> float:
        return float(np.hypot(self.width, self.height))


@dataclass(frozen=True)
class MotionSummary:
    """How the camera moved relative to the current reference keyframe.

    `homography_residual_px` is the load-bearing field and deserves its
    own explanation. It is the median distance between where a homography
    fitted to the tracks predicts each point should land and where it
    actually landed.

    A homography exactly explains any motion that is pure rotation about
    the camera centre, whatever the scene. So residual near zero means
    "this motion carries no baseline" -- which is the one thing a keyframe
    policy most needs to know and cannot get from displacement.

    Measured separation: 0.107 and 0.120 px for genuinely zero-baseline
    pairs, versus 0.305 to 0.765 px once the camera actually translated.
    Meanwhile raw displacement measured 12.4 px under that SAME pure
    rotation -- larger than the 4.3 px measured for a real 5 cm sideways
    step. Displacement alone would promote exactly the frames that carry
    no geometry.

    It is a rotation DETECTOR, not a parallax magnitude: it is not
    monotonic in baseline, because at wide baselines the surviving tracks
    concentrate on whatever plane dominates the view. Use it to reject,
    not to rank.
    """

    seeded_count: int
    tracked_count: int
    survival_ratio: float
    overlap_ratio: float
    median_displacement_px: float | None
    homography_residual_px: float | None

    @property
    def has_motion_evidence(self) -> bool:
        return (
            self.tracked_count >= MIN_TRACKS_FOR_MOTION
            and self.median_displacement_px is not None
        )


def decode_gray(raw_bytes: bytes) -> np.ndarray:
    """Decode a JPEG straight to grayscale.

    Raises ValueError on an undecodable payload so the caller can drop one
    frame rather than take the session down -- a malformed frame is a
    frame-scoped failure, matching how the existing Tower frame path
    already distinguishes the two.
    """
    array = np.frombuffer(raw_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("frame did not decode as an image")
    return image


def measure_sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian: high for crisp, low for blurred.

    Measured on identical content at increasing blur: 662.5 sharp, 38.0
    at a 5-px kernel, 10.1 at 9 px, 3.5 at 15 px. A 17x separation at the
    first step, for well under a millisecond, which is why blur is
    rejected here rather than discovered later by an expensive stage.

    The absolute value is scene-dependent, so callers compare against a
    rolling median of recent frames as well as an absolute floor.
    """
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def analyse_frame(gray: np.ndarray) -> FrameQuality:
    height, width = gray.shape[:2]
    return FrameQuality(
        width=width, height=height, sharpness=measure_sharpness(gray)
    )


def seed_tracks(gray: np.ndarray) -> np.ndarray | None:
    return cv2.goodFeaturesToTrack(
        gray,
        maxCorners=MAX_TRACK_POINTS,
        qualityLevel=TRACK_QUALITY_LEVEL,
        minDistance=TRACK_MIN_DISTANCE,
    )


def track_forward_backward(
    reference_gray: np.ndarray, current_gray: np.ndarray, seeds: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Track seeds and keep only forward-backward consistent survivors."""
    forward, status_f, _ = cv2.calcOpticalFlowPyrLK(
        reference_gray, current_gray, seeds, None,
        winSize=LK_WINDOW, maxLevel=LK_MAX_LEVEL,
    )
    if forward is None:
        return np.empty((0, 2), np.float32), np.empty((0, 2), np.float32)

    backward, status_b, _ = cv2.calcOpticalFlowPyrLK(
        current_gray, reference_gray, forward, None,
        winSize=LK_WINDOW, maxLevel=LK_MAX_LEVEL,
    )
    if backward is None:
        return np.empty((0, 2), np.float32), np.empty((0, 2), np.float32)

    round_trip = np.linalg.norm(seeds - backward, axis=2).ravel()
    keep = (
        (status_f.ravel() == 1)
        & (status_b.ravel() == 1)
        & (round_trip < FORWARD_BACKWARD_MAX_PX)
    )
    return seeds[keep].reshape(-1, 2), forward[keep].reshape(-1, 2)


def summarise_motion(
    reference_gray: np.ndarray,
    current_gray: np.ndarray,
    seeds: np.ndarray | None,
) -> MotionSummary:
    height, width = current_gray.shape[:2]

    if seeds is None or len(seeds) == 0:
        return MotionSummary(0, 0, 0.0, 0.0, None, None)

    seeded_count = int(len(seeds))
    origin, moved = track_forward_backward(reference_gray, current_gray, seeds)
    tracked_count = int(len(moved))
    survival_ratio = tracked_count / seeded_count

    if tracked_count == 0:
        return MotionSummary(seeded_count, 0, 0.0, 0.0, None, None)

    inside = (
        (moved[:, 0] >= 0)
        & (moved[:, 0] < width)
        & (moved[:, 1] >= 0)
        & (moved[:, 1] < height)
    )
    overlap_ratio = float(inside.sum()) / seeded_count
    displacement = float(np.median(np.linalg.norm(origin - moved, axis=1)))

    residual = None
    if tracked_count >= MIN_TRACKS_FOR_MOTION:
        homography, _ = cv2.findHomography(
            origin, moved, cv2.RANSAC, HOMOGRAPHY_RANSAC_PX
        )
        if homography is not None:
            predicted = cv2.perspectiveTransform(
                origin.reshape(-1, 1, 2), homography
            ).reshape(-1, 2)
            residual = float(
                np.median(np.linalg.norm(predicted - moved, axis=1))
            )

    return MotionSummary(
        seeded_count=seeded_count,
        tracked_count=tracked_count,
        survival_ratio=survival_ratio,
        overlap_ratio=overlap_ratio,
        median_displacement_px=displacement,
        homography_residual_px=residual,
    )


class FrameTracker:
    """Holds the reference frame that motion is measured against.

    The reference advances only when a keyframe is accepted, so motion is
    always measured against the last thing actually persisted rather than
    against the previous frame. That is what makes the measurements
    directly comparable to the keyframe decision they inform.
    """

    def __init__(self) -> None:
        self._reference_gray: np.ndarray | None = None
        self._seeds: np.ndarray | None = None

    @property
    def has_reference(self) -> bool:
        return self._reference_gray is not None

    @property
    def seed_count(self) -> int:
        return 0 if self._seeds is None else int(len(self._seeds))

    def set_reference(self, gray: np.ndarray) -> None:
        self._reference_gray = gray.copy()
        self._seeds = seed_tracks(self._reference_gray)

    def reset(self) -> None:
        """Forget the reference. Used on tracking loss, where continuing to
        measure against a frame we can no longer see would be meaningless."""
        self._reference_gray = None
        self._seeds = None

    def measure(self, gray: np.ndarray) -> MotionSummary | None:
        if self._reference_gray is None:
            return None
        return summarise_motion(self._reference_gray, gray, self._seeds)
