import dataclasses

import pytest

from tower.object_memory.records import (
    DERIVED_ONLY,
    FRAME_REFERENCED,
    Confidence,
    ObjectObservation,
    object_observation_from_json_dict,
    privacy_tags_for,
)


def _observation(**overrides) -> ObjectObservation:
    defaults = dict(
        object_class="keys",
        detector_score=0.91,
        confidence=Confidence.HIGH,
        observed_at=1000.0,
        time_basis="tower-receipt",
        recorded_at=1000.5,
        source="glasses-camera",
        module_id="object-memory",
        session_id="session-1",
        frame_seq=42,
        bounding_box=(1.0, 2.0, 3.0, 4.0),
        retention_tag="default",
        privacy_tags=("derived-only",),
        spatial_ref=None,
        external_refs=(),
    )
    defaults.update(overrides)
    return ObjectObservation(**defaults)


def test_confidence_from_score_buckets_by_threshold():
    assert Confidence.from_score(None) is Confidence.UNKNOWN
    assert Confidence.from_score(0.30) is Confidence.LOW
    assert Confidence.from_score(0.60) is Confidence.MEDIUM
    assert Confidence.from_score(0.95) is Confidence.HIGH


def test_confidence_from_score_boundaries_are_inclusive_on_the_upper_bucket():
    # Pins the exact boundary comparisons: flipping either `<` to `<=`
    # in Confidence.from_score passes every other test in the suite.
    assert Confidence.from_score(0.5) is Confidence.MEDIUM
    assert Confidence.from_score(0.8) is Confidence.HIGH


def test_observation_round_trips_through_json_dict():
    original = _observation()

    restored = object_observation_from_json_dict(original.to_json_dict())

    assert restored == original


def test_observed_at_and_recorded_at_are_distinct_fields():
    # Rule 16: capture time and record time must not be conflated.
    observation = _observation(observed_at=10.0, recorded_at=99.0)

    data = observation.to_json_dict()

    assert data["observed_at"] == 10.0
    assert data["recorded_at"] == 99.0


def test_time_basis_is_recorded_so_observed_at_cannot_be_misread():
    # No capture timestamp exists on the wire; observed_at is tower
    # receipt time and the record must say so (Rule 16).
    data = _observation(time_basis="tower-receipt").to_json_dict()

    assert data["time_basis"] == "tower-receipt"


def test_confidence_survives_serialization_as_a_label_not_a_number():
    # Rule 16: confidence must survive persistence.
    data = _observation(confidence=Confidence.UNKNOWN).to_json_dict()

    assert data["confidence"] == "unknown"


def test_observation_is_immutable():
    observation = _observation()

    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.object_class = "mutated"


def test_best_score_round_trips_beside_the_first_sighting_score():
    data = _observation(detector_score=0.60, best_score=0.97).to_json_dict()

    assert data["detector_score"] == 0.60
    assert data["best_score"] == 0.97
    assert object_observation_from_json_dict(data).best_score == 0.97


def test_a_record_written_before_best_score_existed_still_parses():
    # Read with .get(), not [], on purpose: the 55 records already on
    # disk have no best_score, and a required key would make
    # _parse_observations skip every one of them as a schema mismatch --
    # silently deleting the wearer's memory to add a field.
    data = _observation().to_json_dict()
    del data["best_score"]

    restored = object_observation_from_json_dict(data)

    assert restored.best_score is None
    assert restored.object_class == "keys"


def test_privacy_tags_admit_a_record_that_points_back_at_a_stored_frame():
    # `derived-only` describes the CONTENT (no pixels, no crop). It says
    # nothing about reach, and session_id + frame_seq is an exact pointer
    # into data/captures/<id>/frames/, whose retention this cartridge
    # does not govern.
    assert privacy_tags_for("cap-1", 7) == (DERIVED_ONLY, FRAME_REFERENCED)


def test_privacy_tags_do_not_claim_a_frame_pointer_that_is_not_there():
    assert privacy_tags_for(None, None) == (DERIVED_ONLY,)


def test_a_half_present_frame_pointer_still_counts_as_a_pointer():
    # A session id alone narrows the imagery to one capture directory,
    # which is a reach claim worth making.
    assert privacy_tags_for("cap-1", None) == (DERIVED_ONLY, FRAME_REFERENCED)
    assert privacy_tags_for(None, 7) == (DERIVED_ONLY, FRAME_REFERENCED)
