"""How usable is this frame, before anything expensive looks at it.

Every cartridge has some version of this question and World Builder
already answers a private one. The Lab's job is to make the signals
measurable side by side so a threshold gets chosen from a distribution
rather than from taste -- and to make the cost of asking visible, since a
gate that costs more than the work it skips is not a gate.

All six measurements are computed from one decode and one grayscale
conversion. Sharpness is the headline because it is the one that
separates most sharply: a Laplacian variance falls roughly 17x between a
sharp frame and a blurred one, which is a far bigger margin than any of
the others offer.
"""

import cv2
import numpy as np

from tower.experiments import ExperimentResult, decode_color
from tower.instrumentation import StageTimer

# 8-bit imagery, so these are absolute levels rather than fractions.
# Chosen at the ends of the range: a pixel at 250+ has almost certainly
# clipped and a pixel at 5 or below carries no recoverable detail.
OVEREXPOSED_LEVEL = 250
UNDEREXPOSED_LEVEL = 5


def run(raw_bytes: bytes) -> ExperimentResult:
    timer = StageTimer()

    with timer.stage("decode"):
        gray = cv2.cvtColor(decode_color(raw_bytes), cv2.COLOR_BGR2GRAY)

    with timer.stage("sharpness"):
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    with timer.stage("gradient"):
        # Scharr rather than a 3x3 Sobel: same cost, better rotational
        # symmetry, so the number does not depend on which way an edge
        # happens to run.
        dx = cv2.Scharr(gray, cv2.CV_32F, 1, 0)
        dy = cv2.Scharr(gray, cv2.CV_32F, 0, 1)
        gradient_energy = float(np.mean(np.sqrt(dx * dx + dy * dy)))

    with timer.stage("exposure"):
        histogram = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
        total = float(gray.size)
        overexposed = float(histogram[OVEREXPOSED_LEVEL:].sum()) / total
        underexposed = float(histogram[: UNDEREXPOSED_LEVEL + 1].sum()) / total
        mean_intensity = float(gray.mean())
        contrast = float(gray.std())

        # Shannon entropy of the intensity histogram, in bits. A frame of
        # flat wall and a frame of textured room can share a mean and a
        # standard deviation; they do not share an entropy.
        probabilities = histogram / total
        nonzero = probabilities[probabilities > 0]
        entropy = float(-(nonzero * np.log2(nonzero)).sum())

    with timer.stage("edges"):
        edges = cv2.Canny(gray, 100, 200)
        edge_density = float(np.count_nonzero(edges)) / edges.size

    return ExperimentResult(
        result_value=sharpness,
        result_label="sharpness_laplacian_var",
        processing_ms=timer.total_ms,
        stage_ms=timer.snapshot(),
        mean_intensity=mean_intensity,
        metrics={
            "sharpness_laplacian_var": sharpness,
            "gradient_energy": gradient_energy,
            "entropy_bits": entropy,
            "contrast_std": contrast,
            "edge_density": edge_density,
            "overexposed_fraction": overexposed,
            "underexposed_fraction": underexposed,
            "width": float(gray.shape[1]),
            "height": float(gray.shape[0]),
        },
    )
