"""How much trackable texture does this frame actually contain.

A count alone is misleading. A thousand keypoints piled into one corner
of the image is a worse frame for geometry than three hundred spread
evenly, because a solver needs constraints from across the view, not a
dense clump in one place. So the headline is the count and the number
that qualifies it is `spatial_coverage` -- the fraction of an 8x8 grid
that contains at least one keypoint.

This is the measurement that says whether a real indoor scene gives us
anything to work with. Today the answer is synthetic-only.

ORB is used rather than SIFT because it is what the platform already
depends on and what World Builder's geometry uses; measuring a detector
the rest of the system does not use would tell us about the wrong thing.
Deliberately implemented here with cv2 directly rather than by importing
World Builder's helper -- the Lab must not depend on a cartridge, and a
test enforces that.
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

# Counts of keypoints are counts; the response and size statistics are
# already per-frame means and must be averaged again, not added.
# `requested_features` is ORB_FEATURES, the same number on every frame.
METRIC_KINDS: dict[str, MetricKind] = {
    "keypoint_count": MetricKind.COUNT,
    "descriptor_count": MetricKind.COUNT,
    "spatial_coverage": MetricKind.RATE,
    "mean_response": MetricKind.RATE,
    "mean_keypoint_size": MetricKind.RATE,
    "requested_features": MetricKind.CONSTANT,
}

ORB_FEATURES = 1000
COVERAGE_GRID = 8


def run(raw_bytes: bytes) -> ExperimentResult:
    timer = StageTimer()

    with timer.stage("decode"):
        image = decode_gray(raw_bytes, min_dimension=ORB_MIN_DIMENSION)

    with timer.stage("detect"):
        orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
        keypoints = orb.detect(image, None)

    with timer.stage("describe"):
        keypoints, descriptors = orb.compute(image, keypoints)

    with timer.stage("summarize"):
        count = len(keypoints)
        height, width = image.shape[:2]
        if count:
            responses = np.asarray([kp.response for kp in keypoints], dtype=np.float64)
            sizes = np.asarray([kp.size for kp in keypoints], dtype=np.float64)
            xs = np.asarray([kp.pt[0] for kp in keypoints])
            ys = np.asarray([kp.pt[1] for kp in keypoints])
            cells = {
                (
                    min(int(x * COVERAGE_GRID / width), COVERAGE_GRID - 1),
                    min(int(y * COVERAGE_GRID / height), COVERAGE_GRID - 1),
                )
                for x, y in zip(xs, ys)
            }
            coverage = len(cells) / (COVERAGE_GRID * COVERAGE_GRID)
            mean_response = float(responses.mean())
            mean_size = float(sizes.mean())
        else:
            coverage = 0.0
            mean_response = 0.0
            mean_size = 0.0

        described = 0 if descriptors is None else int(len(descriptors))

    return ExperimentResult(
        result_value=float(count),
        result_label="keypoint_count",
        processing_ms=timer.total_ms,
        stage_ms=timer.snapshot(),
        metrics={
            "keypoint_count": float(count),
            "descriptor_count": float(described),
            "spatial_coverage": coverage,
            "mean_response": mean_response,
            "mean_keypoint_size": mean_size,
            "requested_features": float(ORB_FEATURES),
        },
    )
