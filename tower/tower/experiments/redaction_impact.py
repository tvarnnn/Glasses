"""What blurring a region costs the geometry that runs after it.

The platform's privacy direction is raw frame -> ephemeral perception ->
privacy filtering -> persistence. A fair objection is that filtering
destroys exactly the high-frequency texture tracking needs, and the World
Builder review found informally that after a box blur, essentially every
surviving keypoint near the redacted area sat on the blur BOUNDARY --
consistent-looking features that describe an artefact rather than the
scene. This makes that reproducible and gives it a number.

It deliberately does **not** detect a face. This OpenCV 5 build has no
`CascadeClassifier`, `FaceDetectorYN` ships no model, and there is no
face imagery anywhere to validate against. Detecting nothing and blurring
a fixed central rectangle measures the consequence honestly; pretending
to find a face would not.

The headline is retention **inside the redacted region**, not across the
frame. A frame-wide retention number is nearly a constant -- the region
covers ~6% of the area, so global retention sits near 0.97 whether the
redaction was clean or leaky, and nobody would gate a decision on 0.96
versus 0.97. The in-region number is the one that moves.

`boundary_fraction` is measured over survivors **near the region**, for
the same reason. Divided by every survivor in the frame it is dominated
by ordinary never-blurred texture that happens to lie near the box edge,
which dilutes the signal by roughly 2.5x and reports a property of the
frame rather than of the redaction.
"""

import cv2
import numpy as np

from tower.experiments import (
    ORB_MIN_DIMENSION,
    ExperimentResult,
    MetricKind,
    decode_gray,
)
from tower.instrumentation import StageTimer

# Every `keypoints_*` and `survivors_*` number is a tally of keypoints in
# one frame and adds up across the corpus. The retentions and fractions
# are ratios and do not. `blur_kernel` is the configured kernel size.
METRIC_KINDS: dict[str, MetricKind] = {
    "region_keypoint_retention": MetricKind.RATE,
    "frame_keypoint_retention": MetricKind.RATE,
    "keypoints_before": MetricKind.COUNT,
    "keypoints_after": MetricKind.COUNT,
    "keypoints_lost": MetricKind.COUNT,
    "keypoints_in_region_before": MetricKind.COUNT,
    "keypoints_in_region_after": MetricKind.COUNT,
    "survivors_near_region": MetricKind.COUNT,
    "survivors_on_boundary": MetricKind.COUNT,
    "boundary_fraction": MetricKind.RATE,
    "region_area_fraction": MetricKind.RATE,
    "blur_kernel": MetricKind.CONSTANT,
}

ORB_FEATURES = 1000
# A centred rectangle covering a quarter of each dimension -- roughly the
# size and placement of a face at conversational distance.
REGION_FRACTION = 0.25
BLUR_KERNEL = 31
# A keypoint within this many pixels of the rectangle's edge is counted as
# a boundary feature. ORB's default patch is 31 px, so a keypoint whose
# patch straddles the edge is describing the transition, not the scene.
BOUNDARY_MARGIN_PX = 16


def redaction_region(width: int, height: int) -> tuple[int, int, int, int]:
    """The rectangle this experiment blurs, as (x0, y0, x1, y1)."""
    half_w = int(width * REGION_FRACTION / 2)
    half_h = int(height * REGION_FRACTION / 2)
    cx, cy = width // 2, height // 2
    return (
        max(cx - half_w, 0),
        max(cy - half_h, 0),
        min(cx + half_w, width),
        min(cy + half_h, height),
    )


def _keypoints(gray: np.ndarray):
    return cv2.ORB_create(nfeatures=ORB_FEATURES).detect(gray, None)


def run(raw_bytes: bytes) -> ExperimentResult:
    timer = StageTimer()

    with timer.stage("decode"):
        gray = decode_gray(raw_bytes, min_dimension=ORB_MIN_DIMENSION)

    height, width = gray.shape[:2]
    x0, y0, x1, y1 = redaction_region(width, height)

    with timer.stage("detect_original"):
        original = _keypoints(gray)

    with timer.stage("redact"):
        redacted = gray.copy()
        region = redacted[y0:y1, x0:x1]
        if region.size:
            # An odd kernel no larger than the region, or GaussianBlur
            # raises on a small frame.
            kernel = min(BLUR_KERNEL, (min(region.shape) // 2) * 2 - 1)
            if kernel >= 3:
                redacted[y0:y1, x0:x1] = cv2.GaussianBlur(region, (kernel, kernel), 0)
            else:
                redacted[y0:y1, x0:x1] = int(region.mean())

    with timer.stage("detect_redacted"):
        survivors = _keypoints(redacted)

    with timer.stage("summarize"):
        original_count = len(original)
        survivor_count = len(survivors)

        def inside(point) -> bool:
            x, y = point
            return x0 <= x <= x1 and y0 <= y <= y1

        def on_boundary(point) -> bool:
            x, y = point
            near_vertical = (
                abs(x - x0) <= BOUNDARY_MARGIN_PX or abs(x - x1) <= BOUNDARY_MARGIN_PX
            ) and (y0 - BOUNDARY_MARGIN_PX <= y <= y1 + BOUNDARY_MARGIN_PX)
            near_horizontal = (
                abs(y - y0) <= BOUNDARY_MARGIN_PX or abs(y - y1) <= BOUNDARY_MARGIN_PX
            ) and (x0 - BOUNDARY_MARGIN_PX <= x <= x1 + BOUNDARY_MARGIN_PX)
            return near_vertical or near_horizontal

        original_inside = sum(1 for kp in original if inside(kp.pt))
        survivors_inside = sum(1 for kp in survivors if inside(kp.pt))
        survivors_on_boundary = sum(1 for kp in survivors if on_boundary(kp.pt))
        # Survivors the redaction could plausibly have affected: inside it
        # or within the boundary band. This is boundary_fraction's honest
        # denominator -- dividing by every survivor in the frame answers a
        # question about the frame, not about the redaction.
        survivors_near = sum(
            1 for kp in survivors if inside(kp.pt) or on_boundary(kp.pt)
        )

        region_retention = (
            survivors_inside / original_inside if original_inside else 0.0
        )
        frame_retention = survivor_count / original_count if original_count else 0.0
        boundary_fraction = (
            survivors_on_boundary / survivors_near if survivors_near else 0.0
        )
        region_area_fraction = ((x1 - x0) * (y1 - y0)) / float(gray.size)

    return ExperimentResult(
        result_value=region_retention,
        result_label="region_keypoint_retention",
        processing_ms=timer.total_ms,
        stage_ms=timer.snapshot(),
        metrics={
            "region_keypoint_retention": region_retention,
            "frame_keypoint_retention": frame_retention,
            "keypoints_before": float(original_count),
            "keypoints_after": float(survivor_count),
            "keypoints_lost": float(original_count - survivor_count),
            "keypoints_in_region_before": float(original_inside),
            "keypoints_in_region_after": float(survivors_inside),
            "survivors_near_region": float(survivors_near),
            "survivors_on_boundary": float(survivors_on_boundary),
            "boundary_fraction": boundary_fraction,
            "region_area_fraction": region_area_fraction,
            "blur_kernel": float(BLUR_KERNEL),
        },
    )
