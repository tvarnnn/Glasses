import dataclasses

import pytest

from tower.object_memory.records import (
    Confidence,
    ObjectObservation,
    object_observation_from_json_dict,
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
