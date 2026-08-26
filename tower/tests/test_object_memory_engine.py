"""Turning detections into observations, with a substitute detector.

`FixedDetector` rather than the real weights, for the same reason
Document Memory's `--ocr none` exists: a default suite that downloaded a
model would fail on a train, and these cases are about the record the
producer writes, not about whether torchvision can find a laptop.
"""

import json

import cv2
import numpy as np
import pytest

from tower.object_memory.detector import Detection, FixedDetector
from tower.object_memory.engine import ObjectMemoryEngine
from tower.object_memory.records import Confidence
from tower.object_memory.relevance import RelevancePolicy
from tower.object_memory.store import OBSERVATIONS_FILENAME, ObservationStore

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
    assert observation.privacy_tags == ("derived-only", "frame-referenced")
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


# --- REVIEW FINDING 3: spatial_ref must be null in the BYTES that reach disk ---


def test_spatial_ref_is_null_in_the_line_the_store_actually_writes(tmp_path):
    # Asserting on a read-back observation cannot catch this: the read
    # path nulls spatial_ref unconditionally, and prune's raw-dict rewrite
    # preserves unknown keys by design -- so a box written here would
    # reach disk, survive retention and be invisible to every read. This
    # slice knows no position in a room, and the file has to say so.
    store, engine = _engine(tmp_path, [[_detection()]], session_id="cap-1")

    engine.observe(_frame(), received_at=900.0, source_seq=7)

    raw = json.loads(
        (tmp_path / OBSERVATIONS_FILENAME).read_text(encoding="utf-8").strip()
    )
    assert raw["spatial_ref"] is None
    assert raw["external_refs"] == []


# --- REVIEW FINDING 4: confidence is DERIVED from the score, never asserted ---


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.45, Confidence.LOW),
        (0.60, Confidence.MEDIUM),
        (0.95, Confidence.HIGH),
    ],
)
def test_the_recorded_confidence_follows_the_detector_score(
    tmp_path, score, expected
):
    # min_score is lowered so all three scores are actually persisted;
    # the point is the mapping, not the threshold.
    store, engine = _engine(
        tmp_path, [[_detection(score=score)]], policy=RelevancePolicy(min_score=0.1)
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)

    (observation,) = store.all_observations()
    assert observation.confidence is expected


# --- REVIEW FINDING 5: the tags must describe the record's REACH, not just
# its content ---


def test_the_tags_admit_the_record_points_back_at_a_stored_frame(tmp_path):
    # `derived-only` is true of the CONTENT -- no pixels, no crop. It was
    # false about reach: session_id + frame_seq is an exact pointer into
    # data/captures/<id>/frames/, which Object Memory's retention does not
    # govern. Purging every record here leaves that JPEG where it is.
    store, engine = _engine(tmp_path, [[_detection()]], session_id="cap-1")

    engine.observe(_frame(), received_at=900.0, source_seq=7)

    (observation,) = store.all_observations()
    assert observation.privacy_tags == ("derived-only", "frame-referenced")


def test_a_record_that_points_at_no_frame_does_not_claim_it_does(tmp_path):
    store, engine = _engine(tmp_path, [[_detection()]], session_id=None)

    engine.observe(_frame(), received_at=900.0, source_seq=None)

    (observation,) = store.all_observations()
    assert observation.privacy_tags == ("derived-only",)


# --- REVIEW FINDING 6: write on first sighting, then upgrade in-window ---
#
# The filter records the FIRST detection after each gap, so the persisted
# laptop median was 0.601 against a population median of 0.910 -- the
# memory was pessimistic about sightings it had seen clearly seconds
# later. The write still happens immediately (a killed session loses
# nothing) and observed_at still means "when it came into view"; the
# stronger look is carried alongside as best_score.


def test_the_first_sighting_is_written_at_once_and_is_its_own_best(tmp_path):
    store, engine = _engine(tmp_path, [[_detection(score=0.60)]])

    engine.observe(_frame(), received_at=900.0, source_seq=0)

    (observation,) = store.all_observations()
    assert observation.detector_score == pytest.approx(0.60)
    assert observation.best_score == pytest.approx(0.60)


def test_a_stronger_look_inside_the_window_upgrades_best_score_in_place(tmp_path):
    store, engine = _engine(
        tmp_path,
        [[_detection(score=0.60)], [_detection(score=0.97)]],
        policy=RelevancePolicy(resample_seconds=30.0),
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)
    engine.observe(_frame(), received_at=905.0, source_seq=1)

    (observation,) = store.all_observations()
    assert observation.best_score == pytest.approx(0.97)
    assert engine.best_score_upgrades == 1
    # Still one record, still counted as suppressed, and the first
    # sighting's own numbers are untouched.
    assert engine.observations_recorded == 1
    assert engine.dropped["resampled"] == 1
    assert observation.detector_score == pytest.approx(0.60)
    assert observation.observed_at == 900.0
    assert observation.frame_seq == 0


def test_a_weaker_look_inside_the_window_does_not_lower_the_best(tmp_path):
    store, engine = _engine(
        tmp_path,
        [[_detection(score=0.97)], [_detection(score=0.60)]],
        policy=RelevancePolicy(resample_seconds=30.0),
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)
    engine.observe(_frame(), received_at=905.0, source_seq=1)

    (observation,) = store.all_observations()
    assert observation.best_score == pytest.approx(0.97)
    assert engine.best_score_upgrades == 0


def test_a_sighting_after_the_window_starts_a_record_with_its_own_best(tmp_path):
    store, engine = _engine(
        tmp_path,
        [[_detection(score=0.60)], [_detection(score=0.97)]],
        policy=RelevancePolicy(resample_seconds=30.0),
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)
    engine.observe(_frame(), received_at=1000.0, source_seq=1)

    bests = [o.best_score for o in store.all_observations()]
    assert bests == [pytest.approx(0.60), pytest.approx(0.97)]
    assert engine.best_score_upgrades == 0


def test_an_upgrade_that_fails_to_reach_disk_is_counted_not_swallowed(tmp_path):
    class FailingUpgradeStore:
        def __init__(self):
            self.appended = []

        def append(self, observation):
            self.appended.append(observation)

        def update_best_score(self, object_class, observed_at, score):
            raise OSError("disk full")

    store = FailingUpgradeStore()
    engine = ObjectMemoryEngine(
        store,
        FixedDetector([[_detection(score=0.60)], [_detection(score=0.97)]]),
        policy=RelevancePolicy(resample_seconds=30.0),
        clock=lambda: 1000.0,
    )
    engine.load()

    engine.observe(_frame(), received_at=900.0, source_seq=0)
    engine.observe(_frame(), received_at=905.0, source_seq=1)

    assert engine.best_score_upgrades == 0
    assert engine.upgrade_failures == 1
    # The record itself is still there: an upgrade is an improvement on
    # an honest record, never a precondition for having one.
    assert len(store.appended) == 1


def test_the_upgrade_reinterprets_confidence_from_the_best_look(tmp_path):
    # confidence is derived in TWO places now -- at the first write from
    # the sighting that created the record, and again on every in-window
    # upgrade -- so it needs pinning in both. Leaving it on
    # detector_score here makes the memory report "medium" about a
    # laptop it saw at 0.97 five seconds later.
    store, engine = _engine(
        tmp_path,
        [[_detection(score=0.60)], [_detection(score=0.97)]],
        policy=RelevancePolicy(resample_seconds=30.0),
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)
    engine.observe(_frame(), received_at=905.0, source_seq=1)

    (observation,) = store.all_observations()
    assert observation.confidence is Confidence.HIGH
    # Both raw scores survive, so the record stays auditable: it was
    # first seen at 0.60 and best seen at 0.97.
    assert observation.detector_score == pytest.approx(0.60)
    assert observation.best_score == pytest.approx(0.97)


def test_a_weak_sighting_that_never_improves_stays_weak(tmp_path):
    # The label follows the evidence, so it is not a tautology: a
    # sighting the detector never saw clearly keeps its honest label.
    store, engine = _engine(
        tmp_path,
        [[_detection(score=0.55)], [_detection(score=0.58)]],
        policy=RelevancePolicy(resample_seconds=30.0),
    )

    engine.observe(_frame(), received_at=900.0, source_seq=0)
    engine.observe(_frame(), received_at=905.0, source_seq=1)

    (observation,) = store.all_observations()
    assert observation.confidence is Confidence.MEDIUM
