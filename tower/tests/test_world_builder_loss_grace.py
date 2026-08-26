"""One bad hop is not a lost track.

Declaring a segment break was a SINGLE-FRAME verdict: one frame whose
survival fell below the floor ended the segment, and everything after it
lived in a new coordinate frame that shares nothing with the old one.

Replaying the 2026-08-25 walk says that verdict is usually wrong. Of the
50 declared losses, **47 still had survival above the 0.05 floor measured
against the previous frame** and 40 were above 0.20. Only 3 were genuine.
The rest were a stale reference being asked to cross a gap in one hop --
and the very next frame would have tracked fine.

So a break now requires N consecutive loss verdicts. Genuine loss still
breaks, three frames later; a single bad hop does not.

The cost is bounded and worth stating: while in grace the reference does
not advance, so staleness grows for up to N frames. That is acceptable
because the alternative is a segment boundary, and a boundary is
permanent while staleness is not.
"""

import pytest

from tower.world_builder.frontend import FrameQuality, MotionSummary
from tower.world_builder.keyframes import (
    REASON_TRACKING_HELD,
    REASON_TRACKING_LOST,
    TRACKING_LOST,
    KeyframePolicy,
    KeyframeSelector,
)


def _sharp() -> FrameQuality:
    return FrameQuality(sharpness=500.0, width=360, height=640)


def _motion(survival: float, *, overlap: float = 0.9) -> MotionSummary:
    return MotionSummary(
        seeded_count=200,
        tracked_count=int(200 * survival),
        survival_ratio=survival,
        overlap_ratio=overlap,
        median_displacement_px=4.0,
        homography_residual_px=1.0,
    )


@pytest.fixture
def selector():
    sel = KeyframeSelector()
    sel.note_frame(_sharp())
    sel.evaluate(_sharp(), None)      # session seed
    sel.note_accepted()
    return sel


def _feed(selector, survival, count):
    """Run `count` frames at a given survival and return the decisions."""
    out = []
    for _ in range(count):
        selector.note_frame(_sharp())
        out.append(selector.evaluate(_sharp(), _motion(survival)))
    return out


class TestGraceWindow:
    def test_a_single_bad_hop_does_not_break_the_segment(self, selector):
        """The 47-of-50 case. One frame below the floor is not a lost track."""
        [decision] = _feed(selector, 0.01, 1)

        assert decision.outcome != TRACKING_LOST
        assert decision.reason == REASON_TRACKING_HELD
        assert not decision.lost

    def test_a_sustained_loss_still_breaks(self, selector):
        """The 3-of-50 case. Grace delays a real break, it does not prevent it."""
        decisions = _feed(selector, 0.01, KeyframePolicy().loss_grace_frames)

        assert decisions[-1].outcome == TRACKING_LOST
        assert decisions[-1].reason == REASON_TRACKING_LOST
        assert decisions[-1].lost

    def test_the_break_arrives_exactly_at_the_grace_bound(self, selector):
        """Not earlier, not later -- an off-by-one here is a silent policy change."""
        grace = KeyframePolicy().loss_grace_frames
        decisions = _feed(selector, 0.01, grace)

        assert [d.lost for d in decisions] == [False] * (grace - 1) + [True]

    def test_one_good_frame_resets_the_grace_count(self, selector):
        """Otherwise grace becomes a budget spent slowly across a whole walk.

        Two bad hops far apart are two recoveries, not two thirds of a
        break. Without a reset, an unrelated bad frame minutes later would
        inherit the earlier one's credit.
        """
        grace = KeyframePolicy().loss_grace_frames
        _feed(selector, 0.01, grace - 1)
        _feed(selector, 0.90, 1)            # recovered
        decisions = _feed(selector, 0.01, grace - 1)

        assert not any(d.lost for d in decisions)

    def test_a_declared_loss_clears_the_count_for_the_next_segment(self, selector):
        """A fresh segment starts with a full grace window, not a spent one."""
        grace = KeyframePolicy().loss_grace_frames
        _feed(selector, 0.01, grace)        # breaks
        selector.note_lost()

        selector.note_frame(_sharp())
        selector.evaluate(_sharp(), None)   # segment seed
        selector.note_accepted()
        [decision] = _feed(selector, 0.01, 1)

        assert not decision.lost


class TestGraceDoesNotWidenTheLossDefinition:
    def test_a_degraded_but_not_lost_frame_is_unaffected(self, selector):
        """Grace applies only below the loss floor.

        A frame between `loss_survival_ratio` and `min_survival_ratio` was
        already a plain reject and must stay one -- otherwise grace would
        quietly convert degradation into loss-with-a-countdown.
        """
        policy = KeyframePolicy()
        between = (policy.loss_survival_ratio + policy.min_survival_ratio) / 2
        [decision] = _feed(selector, between, 1)

        assert not decision.lost
        assert decision.reason != REASON_TRACKING_HELD

    def test_held_frames_are_never_accepted_as_keyframes(self, selector):
        """A frame the tracker could not follow must not become geometry."""
        decisions = _feed(selector, 0.01, KeyframePolicy().loss_grace_frames - 1)

        assert all(not d.accepted for d in decisions)


class TestGraceIsConfigurableAndAuditable:
    def test_grace_of_one_restores_the_single_frame_verdict(self):
        """The old behaviour must remain expressible, for A/B measurement."""
        sel = KeyframeSelector(KeyframePolicy(loss_grace_frames=1))
        sel.note_frame(_sharp())
        sel.evaluate(_sharp(), None)
        sel.note_accepted()

        [decision] = _feed(sel, 0.01, 1)

        assert decision.lost

    def test_held_frames_are_counted_under_their_own_reason(self, selector):
        """The rejection histogram is the only tuning instrument there is.

        Folding held frames into `tracking_degraded` would hide how often
        grace fires, which is exactly the number needed to tell whether it
        is set right.
        """
        [decision] = _feed(selector, 0.01, 1)
        assert decision.reason == REASON_TRACKING_HELD
