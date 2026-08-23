import cv2
import numpy as np

from tower.experiments import ExperimentResult, decode_color
from tower.instrumentation import StageTimer


def run(raw_bytes: bytes) -> ExperimentResult:
    timer = StageTimer()

    with timer.stage("decode"):
        image = decode_color(raw_bytes)

    with timer.stage("blur"):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    with timer.stage("canny"):
        edges = cv2.Canny(blurred, 100, 200)

    with timer.stage("summarize"):
        edge_density = float(np.count_nonzero(edges)) / edges.size

    return ExperimentResult(
        result_value=edge_density,
        result_label="edge_density",
        processing_ms=timer.total_ms,
        stage_ms=timer.snapshot(),
    )
