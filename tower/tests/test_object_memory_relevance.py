"""Which detections may be remembered, and which may not, and why.

The policy these test used to describe was a two-name whitelist and a
30-second resample window. Both were replaced by measurement over all
18,821 real frames -- see `tower/object_memory/classes.py` for the
per-class evidence and `sightings.py` for what replaced the window.

The tests that mattered most in the old file survive here unchanged in
substance, because the properties they protect did not change: `person`
is never written, a class outside the policy is never written, and the
class check runs before the score check.
"""

import pytest

from tower.object_memory.classes import (
    CLASS_EVIDENCE,
    CONTEXT,
    EXCLUDED_CLASSES,
    IGNORED,
    PERSISTABLE_CLASSES,
    REMEMBERED,
    VERIFY,
    classes_in,
    tier_of,
    wholes_of,
)
from tower.object_memory.relevance import (
    ALREADY_RECORDED,
    BELOW_MIN_SCORE,
    CONTEXT_ONLY,
    EXCLUDED,
    NOT_WHITELISTED,
    PART_OF_ANOTHER,
    RECORD,
    TOO_BRIEF,
    UNVERIFIED,
    RelevanceFilter,
    RelevancePolicy,
    recordable_classes,
)
from tower.object_memory.sightings import Look, Sighting


def _filter(**kwargs):
    return RelevanceFilter(RelevancePolicy(**kwargs))


def _look(score=0.9, at=100.0):
    return Look(score=score, box=(0.1, 0.1, 0.4, 0.4), at=at, frame_seq=1)


def _sighting(object_class="laptop", *, score=0.9, frames=5, verdict=None):
    look = _look(score)
    sighting = Sighting(
        object_class=object_class, first=look, best=look, last=look
    )
    sighting.frame_count = frames
    sighting.verdict = verdict
    return sighting


# -- the privacy gate, which is the one that may never move ------------


class TestExclusion:
    def test_person_is_refused_however_confident_the_detector_is(self):
        assert _filter().decide("person", 0.999) == EXCLUDED

    def test_the_exclusion_is_checked_before_everything_else(self):
        """Order, not just outcome.

        An excluded class refused for being off the whitelist would be
        counted under the wrong reason, and a reader of the report would
        see a policy decision where a privacy decision was made.
        """
        verdict = _filter(min_score=0.99, allowed_classes=()).decide("person", 0.1)

        assert verdict == EXCLUDED

    def test_person_is_not_in_any_tier(self):
        for tier in (REMEMBERED, VERIFY, CONTEXT):
            assert "person" not in classes_in(tier)

    def test_person_can_never_be_persisted_by_any_configuration(self):
        assert "person" not in PERSISTABLE_CLASSES
        assert "person" not in recordable_classes(True)
        assert "person" not in recordable_classes(False)

    def test_a_verifier_cannot_widen_the_policy(self):
        """The tripwire the whole tier design exists to arm.

        A verifier is consulted at gate 4, for classes gates 1-3 have
        already admitted. A verdict agreeing enthusiastically about
        `person` -- or about any class the tables never allowed -- must
        change nothing.
        """
        agreed = {"agrees": True, "label": "person", "model": "hostile"}
        for object_class in ("person", "car", "banana"):
            sighting = _sighting(object_class, verdict=agreed)
            assert _filter().decide_sighting(sighting) != RECORD


# -- the tier gate -----------------------------------------------------


class TestTiers:
    def test_the_measured_reliable_classes_are_remembered_outright(self):
        assert classes_in(REMEMBERED) == ("laptop", "cell phone")

    def test_a_context_class_is_refused_with_its_own_reason(self):
        """"Detected reliably and not worth a memory" is not "unknown".

        `bed` was correct in 20 of 24 inspected crops. Reporting it as
        off-the-whitelist would hide that this is a product decision --
        nobody looks for their bed -- rather than a detector limitation.
        """
        assert _filter().decide("bed", 0.95) == CONTEXT_ONLY

    def test_a_class_with_no_evidence_is_refused(self):
        assert _filter().decide("giraffe", 0.99) == NOT_WHITELISTED

    def test_the_ceiling_fan_classes_are_ignored(self):
        """`airplane` at 0.99 and `scissors` at 0.93 were the same fan.

        `scissors` stays in the verify tier because scissors are a real
        thing to look for; `airplane` does not, because an aeroplane
        indoors is only ever a mistake.
        """
        assert tier_of("airplane") == IGNORED
        assert _filter().decide("airplane", 0.99) == NOT_WHITELISTED

    def test_the_class_check_runs_before_the_score_check(self):
        assert _filter(min_score=0.99).decide("giraffe", 0.1) == NOT_WHITELISTED

    def test_a_weak_detection_of_an_allowed_class_is_refused_for_its_score(self):
        assert _filter().decide("laptop", 0.2) == BELOW_MIN_SCORE

    @pytest.mark.parametrize("object_class", classes_in(REMEMBERED))
    def test_every_remembered_class_passes_the_detection_gates(self, object_class):
        assert _filter().decide(object_class, 0.9) == RECORD


# -- the maturity and verification gates -------------------------------


class TestSightingGate:
    def test_a_sighting_too_short_to_be_real_is_not_written(self):
        assert _filter().decide_sighting(_sighting(frames=2)) == TOO_BRIEF

    def test_three_frames_is_enough(self):
        assert _filter().decide_sighting(_sighting(frames=3)) == RECORD

    def test_a_verify_class_with_no_verdict_is_refused(self):
        assert _filter().decide_sighting(_sighting("remote")) == UNVERIFIED

    def test_a_verify_class_a_verifier_disagreed_with_is_refused(self):
        sighting = _sighting("remote", verdict={"agrees": False, "model": "x"})

        assert _filter().decide_sighting(sighting) == UNVERIFIED

    def test_a_verify_class_a_verifier_agreed_with_is_written(self):
        sighting = _sighting("remote", verdict={"agrees": True, "model": "x"})

        assert _filter().decide_sighting(sighting) == RECORD

    def test_a_remembered_class_needs_no_verdict(self):
        assert _filter().decide_sighting(_sighting("laptop")) == RECORD

    def test_a_sighting_already_on_disk_says_so_rather_than_being_refused(self):
        sighting = _sighting()
        sighting.recorded = True

        assert _filter().decide_sighting(sighting) == ALREADY_RECORDED

    def test_the_gate_reads_the_best_look_not_the_first(self):
        """A sighting that started weak and got strong is worth writing.

        The first look is provenance; the best look is the evidence for
        the claim the record makes.
        """
        weak = _look(0.2, at=100.0)
        strong = _look(0.9, at=101.0)
        sighting = Sighting(object_class="laptop", first=weak, best=strong, last=strong)
        sighting.frame_count = 5

        assert _filter().decide_sighting(sighting) == RECORD


# -- what the wire is told ---------------------------------------------


class TestRecordableClasses:
    def test_without_a_verifier_the_answer_is_what_shipped(self):
        assert recordable_classes(False) == ("laptop", "cell phone")

    def test_the_order_the_shipped_client_was_written_against_is_preserved(self):
        """`recorded_classes` reaches an iOS decoder that already exists.

        Sorting this list alphabetically would reorder it for no reason
        but tidiness.
        """
        assert list(recordable_classes(False)) == ["laptop", "cell phone"]

    def test_a_verifier_widens_it_and_only_to_the_verify_tier(self):
        widened = recordable_classes(True)

        assert set(widened) == set(classes_in(REMEMBERED)) | set(classes_in(VERIFY))
        assert not set(widened) & set(classes_in(CONTEXT))

    def test_the_store_bound_is_never_narrower_than_what_may_be_written(self):
        """`PERSISTABLE_CLASSES` is the outer bound the store enforces.

        A class the producer may write that the store would reject is a
        cartridge that fails at the last step, loudly, in the field.
        """
        assert set(recordable_classes(True)) <= set(PERSISTABLE_CLASSES)


# -- the evidence table itself -----------------------------------------


class TestClassEvidence:
    def test_every_entry_carries_the_count_behind_its_tier(self):
        for name, evidence in CLASS_EVIDENCE.items():
            assert evidence.correct <= evidence.inspected, name
            assert evidence.note.strip(), name

    def test_an_uninspected_class_reports_unknown_precision_not_zero(self):
        """0.0 would read as "always wrong", which is a much stronger claim."""
        assert CLASS_EVIDENCE["tv"].precision is None

    def test_the_classes_that_were_all_wrong_are_not_remembered_outright(self):
        for name, evidence in CLASS_EVIDENCE.items():
            if evidence.inspected and evidence.correct == 0:
                assert evidence.tier != REMEMBERED, name

    def test_the_excluded_set_is_not_silently_empty(self):
        """A guard that guards nothing passes for the wrong reason."""
        assert EXCLUDED_CLASSES


# -- parts and wholes --------------------------------------------------


class TestPartOfAnother:
    """A laptop's keyboard is not a second memory of the laptop.

    Measured: `keyboard` produced 24 sightings across 12 captures, every
    one of them in a capture that also had a laptop in view. A verified
    replay of the validated capture wrote two `keyboard` records and one
    of them was the keyboard of a laptop that already had its own.
    """

    def test_a_part_is_suppressed_while_its_whole_is_in_view(self):
        sighting = _sighting("keyboard", verdict={"agrees": True})

        verdict = _filter().decide_sighting(sighting, open_classes={"laptop"})

        assert verdict == PART_OF_ANOTHER

    def test_a_part_on_its_own_is_still_a_memory(self):
        """The other record in that replay is a lit mechanical keyboard at
        a desk with no laptop near it. A blanket rule would lose it."""
        sighting = _sighting("keyboard", verdict={"agrees": True})

        verdict = _filter().decide_sighting(sighting, open_classes={"cell phone"})

        assert verdict == RECORD

    def test_a_whole_is_never_suppressed_by_its_part(self):
        sighting = _sighting("laptop")

        verdict = _filter().decide_sighting(sighting, open_classes={"keyboard"})

        assert verdict == RECORD

    def test_the_table_is_not_silently_empty(self):
        assert wholes_of("keyboard") == ("laptop",)
        assert wholes_of("laptop") == ()
