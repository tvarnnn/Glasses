from tower.object_memory.relevance import RelevanceFilter, RelevancePolicy
from tower.object_memory.records import Confidence


def _filter(**overrides) -> RelevanceFilter:
    return RelevanceFilter(RelevancePolicy(**overrides))


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
