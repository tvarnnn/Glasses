import time
from dataclasses import dataclass

import cv2
import numpy as np

from tower.modules.base import FrameProcessingError


@dataclass(frozen=True)
class FrameProcessingResult:
    mean_intensity: float
    processing_ms: float


def process_frame(raw_bytes: bytes) -> FrameProcessingResult:
    start = time.perf_counter()

    # Three failure modes, all of which would otherwise raise a bare
    # cv2.error -- which ModuleContainer treats as a MODULE failure, not a
    # frame failure. mark_failed() is terminal and the container is built
    # once at process start, so one bad frame would end CV processing for
    # the life of the server.
    #
    # Reachable from the wire: tower/frames.py validates with
    # Image.open(...).size, which parses the JPEG header. A real JPEG
    # truncated to 800 bytes passes that and still decodes to None here.
    #
    # Guarded inline rather than by calling tower.experiments.decode_color:
    # this module is shared infrastructure and must not import a cartridge.
    if not raw_bytes:
        raise FrameProcessingError("empty frame payload")
    array = np.frombuffer(raw_bytes, dtype=np.uint8)
    try:
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise FrameProcessingError(f"undecodable frame: {exc}") from exc
    if image is None:
        raise FrameProcessingError("undecodable frame")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean_intensity = float(gray.mean())

    processing_ms = (time.perf_counter() - start) * 1000

    return FrameProcessingResult(
        mean_intensity=mean_intensity,
        processing_ms=processing_ms,
    )
