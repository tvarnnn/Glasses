import time
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class FrameProcessingResult:
    mean_intensity: float
    processing_ms: float


def process_frame(raw_bytes: bytes) -> FrameProcessingResult:
    start = time.perf_counter()

    array = np.frombuffer(raw_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean_intensity = float(gray.mean())

    processing_ms = (time.perf_counter() - start) * 1000

    return FrameProcessingResult(
        mean_intensity=mean_intensity,
        processing_ms=processing_ms,
    )
