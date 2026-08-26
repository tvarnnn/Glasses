"""One frame in, zero or more observations out.

The producer's whole logic, deliberately separate from the script that
drives it. `scripts/object_memory_session.py` chooses where frames come
from and prints a report; everything that decides what gets REMEMBERED
lives here, where it can be tested against detections a test wrote down.

Nothing here is a `Module`. Object Memory produces out of process, by
tailing a capture journal, exactly as World Builder, Scene and Document
Memory do -- so it needs no module lifecycle, no `_do_load` timeout and
no second module slot, and the unresolved lifecycle-versus-model-load
question does not stand in its way.
"""

import logging
import time

import cv2
import numpy as np

from tower.object_memory.records import Confidence, ObjectObservation
from tower.object_memory.relevance import (
    RECORD,
    RelevanceFilter,
    RelevancePolicy,
)

logger = logging.getLogger(__name__)

MODULE_ID = "object-memory"

# Rule 16. There is no on-glasses capture timestamp anywhere on this
# wire -- `tower/frames.py`'s REQUIRED_FIELDS carries no time field -- so
# every record this slice writes is stamped with the clock it can
# actually know. If a capture timestamp is ever threaded through, new
# records say "capture" and these stay correctly labelled.
TIME_BASIS = "tower-receipt"

DROP_REASONS = ("not-whitelisted", "below-min-score", "resampled")


class ObjectMemoryEngine:
    """Detect, filter, persist. Counts everything it refused, and why."""

    def __init__(
        self,
        store,
        detector,
        *,
        policy: RelevancePolicy | None = None,
        source: str = "glasses-camera",
        session_id: str | None = None,
        clock=time.time,
    ) -> None:
        self._store = store
        self._detector = detector
        self._relevance = RelevanceFilter(policy or RelevancePolicy())
        self._source = source
        self._session_id = session_id
        self._clock = clock

        self.frames_observed = 0
        self.frames_undecodable = 0
        self.detections_seen = 0
        self.observations_recorded = 0
        self.write_failures = 0
        self.recorded_by_class: dict[str, int] = {}
        # Why detections did NOT become observations. Reported rather
        # than discarded: "the producer wrote 11 records" means nothing
        # without "and declined 4,000, mostly for being off the
        # whitelist".
        self.dropped: dict[str, int] = {reason: 0 for reason in DROP_REASONS}

    def load(self) -> None:
        self._detector.load()

    def release(self) -> None:
        self._detector.release()

    def observe(
        self,
        raw_bytes: bytes,
        *,
        received_at: float | None = None,
        source_seq: int | None = None,
    ) -> list[ObjectObservation]:
        frame = self._decode(raw_bytes)
        if frame is None:
            self.frames_undecodable += 1
            return []
        self.frames_observed += 1

        height, width = frame.shape[:2]
        # received_at is the capture journal's receipt time, which is the
        # same clock TIME_BASIS names. A source with no timestamps -- a
        # directory of loose jpegs -- gets the processing clock instead;
        # inventing an interval to make it look like a real one would
        # fabricate a clock (Rule 3).
        observed_at = self._clock() if received_at is None else received_at

        recorded = []
        for detection in self._detector.detect(frame):
            self.detections_seen += 1
            verdict = self._relevance.decide(
                detection.label, detection.score, observed_at
            )
            if verdict != RECORD:
                self.dropped[verdict] = self.dropped.get(verdict, 0) + 1
                continue
            observation = self._observation(
                detection, width, height, observed_at, source_seq
            )
            try:
                self._store.append(observation)
            except OSError:
                # note_recorded is deliberately NOT called: the filter
                # must not believe it recorded a sighting that never
                # reached disk, or the next frame suppresses the retry
                # and the observation is lost in silence.
                self.write_failures += 1
                logger.warning(
                    "[Tower][ObjectMemory] failed to persist a %s observation",
                    detection.label,
                )
                continue
            self._relevance.note_recorded(detection.label, observed_at)
            self.observations_recorded += 1
            self.recorded_by_class[detection.label] = (
                self.recorded_by_class.get(detection.label, 0) + 1
            )
            recorded.append(observation)
        return recorded

    def _observation(
        self,
        detection,
        width: int,
        height: int,
        observed_at: float,
        source_seq: int | None,
    ) -> ObjectObservation:
        x1, y1, x2, y2 = detection.box
        return ObjectObservation(
            object_class=detection.label,
            detector_score=detection.score,
            confidence=Confidence.from_score(detection.score),
            observed_at=observed_at,
            time_basis=TIME_BASIS,
            recorded_at=self._clock(),
            source=self._source,
            module_id=MODULE_ID,
            session_id=self._session_id,
            frame_seq=source_seq,
            # Stored as a fraction of the frame, not in pixels. The
            # record carries no resolution, so a pixel box would mean
            # different things in different captures and nothing would
            # say which. This is still a box in an IMAGE -- it is not a
            # position in a room, and spatial_ref stays None.
            bounding_box=(x1 / width, y1 / height, x2 / width, y2 / height),
            retention_tag="default",
            privacy_tags=("derived-only",),
            spatial_ref=None,
            external_refs=(),
        )

    @staticmethod
    def _decode(raw_bytes: bytes):
        """Decode, or return None. A bad frame must not end a session.

        The corpus benchmark decoded all 9,199 real frames without a
        failure, so this is not a hot path -- but a producer that dies on
        one truncated JPEG loses the rest of the walk.
        """
        if not raw_bytes:
            return None
        array = np.frombuffer(raw_bytes, dtype=np.uint8)
        try:
            return cv2.imdecode(array, cv2.IMREAD_COLOR)
        except cv2.error:
            return None
