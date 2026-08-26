from tower.object_memory.relevance import (
    PERSISTED_CLASSES,
    RelevanceFilter,
    RelevancePolicy,
)
from tower.object_memory.records import Confidence


def _filter(**overrides) -> RelevanceFilter:
    # These cases predate the class policy and are about the SCORE and
    # RESAMPLE rules, so they name their own allowed classes rather than
    # being rewritten around the whitelist. They must not be the reason
    # the default whitelist stays wide.
    defaults = {"allowed_classes": ("keys", "backpack", "item")}
    defaults.update(overrides)
    return RelevanceFilter(RelevancePolicy(**defaults))


def test_detection_below_min_score_is_not_recorded():
    relevance = _filter(min_score=0.5)

    assert relevance.should_record("keys", score=0.49, now=100.0) is False


def test_first_confident_sighting_of_a_class_is_recorded():
    relevance = _filter(min_score=0.5)

    assert relevance.should_record("keys", score=0.80, now=100.0) is True


def test_repeat_sighting_within_resample_window_is_suppressed():
    relevance = _filter(min_score=0.5, resample_seconds=30.0)
    relevance.note_recorded("keys", now=100.0)

    assert relevance.should_record("keys", score=0.99, now=120.0) is False


def test_repeat_sighting_after_resample_window_is_recorded_again():
    relevance = _filter(min_score=0.5, resample_seconds=30.0)
    relevance.note_recorded("keys", now=100.0)

    assert relevance.should_record("keys", score=0.80, now=131.0) is True


def test_suppression_is_per_class_not_global():
    relevance = _filter(min_score=0.5, resample_seconds=30.0)
    relevance.note_recorded("keys", now=100.0)

    assert relevance.should_record("backpack", score=0.80, now=101.0) is True


def test_repeat_sighting_exactly_at_resample_boundary_is_recorded():
    # elapsed == resample_seconds is treated as due, not suppressed --
    # pins the >= in should_record against an off-by-boundary flip.
    relevance = _filter(min_score=0.5, resample_seconds=30.0)
    relevance.note_recorded("keys", now=100.0)

    assert relevance.should_record("keys", score=0.80, now=130.0) is True


def test_default_min_score_means_persisted_confidence_is_never_low():
    # The default min_score (0.5) is exactly equal to LOW_CONFIDENCE_MAX (0.5).
    # This means every detection that passes this filter buckets to MEDIUM or HIGH.
    # Confidence.LOW can never appear on a persisted record using the default policy.
    # This coupling test pins both halves: the filter comparison is score < min_score,
    # so 0.5 is accepted; and Confidence.from_score(0.5) is MEDIUM, not LOW.
    relevance = _filter()  # default min_score=0.5

    assert relevance.should_record("item", score=0.5, now=100.0) is True
    assert Confidence.from_score(0.5) is Confidence.MEDIUM


# --- The class whitelist: what this slice will persist, and why ---


def test_person_is_never_recorded_however_confident_the_detector_is():
    # The unresolved ruling about persisting a record per detected
    # bystander is not settled by anything here, and this slice must not
    # depend on it being settled. Excluding `person` is what makes that
    # true. See PERSISTED_CLASSES for the reasoning.
    relevance = RelevanceFilter(RelevancePolicy())

    assert relevance.should_record("person", score=0.99, now=100.0) is False


def test_the_default_whitelist_is_the_two_measured_reliable_classes():
    assert PERSISTED_CLASSES == ("laptop", "cell phone")


def test_the_whitelisted_classes_are_recorded():
    relevance = RelevanceFilter(RelevancePolicy())

    assert relevance.should_record("laptop", score=0.81, now=100.0) is True
    assert relevance.should_record("cell phone", score=0.84, now=100.0) is True


def test_a_class_outside_the_whitelist_is_not_recorded():
    # `dining table` appears once in 9,199 real frames and `couch` sits
    # at 0.496 -- near-absent or near-noise, either way not memory.
    relevance = RelevanceFilter(RelevancePolicy())

    assert relevance.should_record("dining table", score=0.95, now=100.0) is False
    assert relevance.should_record("couch", score=0.95, now=100.0) is False


def test_the_class_check_runs_before_the_score_and_resample_checks():
    # An excluded class must not be able to reach note_recorded and take
    # up a slot in the resample table.
    relevance = RelevanceFilter(RelevancePolicy())

    assert relevance.decide("person", score=0.99, now=100.0) == "not-whitelisted"


def test_decide_names_the_reason_a_detection_was_dropped():
    # The producer reports these counts, which is the only way the
    # filter's real behaviour on real footage becomes measurable.
    relevance = _filter(min_score=0.5, resample_seconds=30.0)

    assert relevance.decide("keys", score=0.80, now=100.0) == "record"
    assert relevance.decide("keys", score=0.10, now=100.0) == "below-min-score"
    relevance.note_recorded("keys", now=100.0)
    assert relevance.decide("keys", score=0.80, now=110.0) == "resampled"
