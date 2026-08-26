"""Turning detections into observations, with a substitute detector.

`FixedDetector` rather than the real weights, for the same reason
Document Memory's `--ocr none` exists: a default suite that downloaded a
model would fail on a train, and these cases are about the record the
producer writes, not about whether torchvision can find a laptop.
"""

import cv2
import numpy as np
import pytest

from tower.object_memory.detector import Detection, FixedDetector
from tower.object_memory.engine import ObjectMemoryEngine
from tower.object_memory.records import Confidence
from tower.object_memory.relevance import RelevancePolicy
from tower.object_memory.store import ObservationStore

WIDTH, HEIGHT = 360, 640


def _frame() -> bytes:
    image = np.full((HEIGHT, WIDTH, 3), 120, np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


def _detection(label="laptop", score=0.81, box=(36.0, 64.0, 180.0, 320.0)):
    return Detection(label=label, score=score, box=box)


def _engine(tmp_path, frames, *, policy=None, clock=None, **kwargs):
    store = ObservationStore(tmp_path, retention_seconds=None)
    engine = ObjectMemoryEngine(
        store,
        FixedDetector(frames),
        policy=policy or RelevancePolicy(),
        clock=clock or (lambda: 1000.0),
        **kwargs,
    )
    engine.load()
    return store, engine


def test_a_whitelisted_detection_becomes_a_persisted_observation(tmp_path):
    store, engine = _engine(tmp_path, [[_detection()]], session_id="cap-1")

    engine.observe(_frame(), received_at=900.0, source_seq=7)

    (observation,) = store.all_observations()
    assert observation.object_class == "laptop"
    assert observation.detector_score == pytest.approx(0.81)
    assert observation.confidence is Confidence.HIGH
    assert observation.session_id == "cap-1"
    assert observation.frame_seq == 7
    assert observation.privacy_tags == ("derived-only",)
    assert observation.spatial_ref is None


def test_a_person_detection_is_never_persisted(tmp_path):
    # The detector still reports it; the producer refuses to write it.
    # See relevance.PERSISTED_CLASSES for why that is not squeamishness.
    store, engine = _engine(
        tmp_path, [[_detection(label="person", score=0.99), _detection()]]
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)

    assert [o.object_class for o in store.all_observations()] == ["laptop"]
    assert engine.dropped["not-whitelisted"] == 1


def test_the_box_is_stored_as_a_fraction_of_the_frame(tmp_path):
    # Pixels would silently mean different things at different capture
    # resolutions, and nothing in the record says which one it was.
    store, engine = _engine(
        tmp_path, [[_detection(box=(36.0, 64.0, 180.0, 320.0))]]
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)

    (observation,) = store.all_observations()
    assert observation.bounding_box == pytest.approx((0.1, 0.1, 0.5, 0.5))


def test_observed_at_is_the_capture_receipt_time_and_says_so(tmp_path):
    # Rule 16: there is no on-glasses capture timestamp anywhere on this
    # wire, so the record must not imply one.
    store, engine = _engine(tmp_path, [[_detection()]])

    engine.observe(_frame(), received_at=900.0, source_seq=0)

    (observation,) = store.all_observations()
    assert observation.observed_at == 900.0
    assert observation.time_basis == "tower-receipt"
    assert observation.recorded_at == 1000.0


def test_a_source_with_no_timestamp_gets_the_processing_clock(tmp_path):
    # A directory of loose jpegs has no receipt time. Stamping the
    # processing clock is honest; inventing an interval would not be.
    store, engine = _engine(tmp_path, [[_detection()]])

    engine.observe(_frame(), received_at=None, source_seq=0)

    (observation,) = store.all_observations()
    assert observation.observed_at == 1000.0
    assert observation.time_basis == "tower-receipt"


def test_a_repeat_sighting_inside_the_resample_window_is_suppressed(tmp_path):
    store, engine = _engine(
        tmp_path,
        [[_detection()], [_detection()]],
        policy=RelevancePolicy(resample_seconds=30.0),
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)
    engine.observe(_frame(), received_at=905.0, source_seq=1)

    assert len(store.all_observations()) == 1
    assert engine.dropped["resampled"] == 1


def test_a_weak_detection_is_dropped_and_counted_separately(tmp_path):
    store, engine = _engine(tmp_path, [[_detection(score=0.41)]])

    engine.observe(_frame(), received_at=900.0, source_seq=0)

    assert store.all_observations() == []
    assert engine.dropped["below-min-score"] == 1


def test_an_undecodable_frame_is_skipped_rather_than_ending_the_session(tmp_path):
    store, engine = _engine(tmp_path, [[_detection()]])

    assert engine.observe(b"not a jpeg", received_at=900.0, source_seq=0) == []

    assert engine.frames_undecodable == 1
    assert engine.frames_observed == 0
    assert store.all_observations() == []


def test_a_failed_store_write_does_not_count_as_recorded(tmp_path):
    # The relevance filter must not believe it already recorded a
    # sighting that never reached disk, or the next frame suppresses the
    # retry and the observation is lost silently.
    class FailingStore:
        def append(self, observation):
            raise OSError("disk full")

    engine = ObjectMemoryEngine(
        FailingStore(),
        FixedDetector([[_detection()], [_detection()]]),
        policy=RelevancePolicy(resample_seconds=30.0),
        clock=lambda: 1000.0,
    )
    engine.load()

    engine.observe(_frame(), received_at=900.0, source_seq=0)
    engine.observe(_frame(), received_at=901.0, source_seq=1)

    assert engine.observations_recorded == 0
    assert engine.write_failures == 2
    assert engine.dropped["resampled"] == 0


def test_counts_by_class_report_what_was_actually_remembered(tmp_path):
    store, engine = _engine(
        tmp_path,
        [[_detection(), _detection(label="cell phone", score=0.84)]],
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)

    assert engine.recorded_by_class == {"laptop": 1, "cell phone": 1}
    assert engine.detections_seen == 2
    assert len(store.all_observations()) == 2
