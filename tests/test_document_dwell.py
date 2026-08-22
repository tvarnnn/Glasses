"""When is a page in view long enough to be worth 1.2 seconds of OCR?

SYNTHETIC, NOT PHYSICAL.

The dwell tracker is the stingy gate that makes the expensive stage rare.
Its failure modes are asymmetric and both bad: too permissive and every
glance at a poster costs a second of OCR and a stored record; too strict
and the wearer reads a document the system never noticed.

None of this measures attention. `07-PLATFORM-CONSTRAINTS.md` Limitation 8
is explicit that the camera cannot establish that anyone looked at, read
or understood anything, and no threshold here changes that. The tests use
the word `observed` for the same reason the code does.
"""

import numpy as np
import pytest

from tower.document_memory.detect import PageCandidate
from tower.document_memory.dwell import DwellPolicy, DwellTracker
from tower.document_memory.records import (
    END_REASON_LOST,
    END_REASON_MAX_DURATION,
    END_REASON_STOPPED,
)

FRAME_DIAGONAL = 800.0


def _candidate(centre=(320.0, 240.0), area=0.5, sharpness=500.0, squareness=0.95):
    half = 100.0
    x, y = centre
    corners = np.array(
        [
            [x - half, y - half],
            [x + half, y - half],
            [x + half, y + half],
            [x - half, y + half],
        ],
        dtype=np.float32,
    )
    return PageCandidate(
        corners=corners,
        area_fraction=area,
        aspect=1.0,
        solidity=0.99,
        text_row_fraction=0.3,
        ink_fraction=0.1,
        row_transitions=60.0,
        sharpness=sharpness,
        squareness=squareness,
    )


def _gray():
    return np.full((240, 320), 200, np.uint8)


def _feed(tracker, count, *, start=0.0, step=0.3, candidate=None, gray=True):
    finished = []
    at = start
    for index in range(count):
        result = tracker.observe(
            candidate if candidate is not None else _candidate(),
            at=at,
            gray=_gray() if gray else None,
            source_seq=index,
            frame_diagonal=FRAME_DIAGONAL,
        )
        if result is not None:
            finished.append(result)
        at += step
    return finished, at


class TestAGlanceIsNotAReadingEvent:
    def test_one_frame_produces_nothing(self):
        tracker = DwellTracker()
        _feed(tracker, 1)

        assert tracker.flush() is None

    def test_too_few_frames_produces_nothing_even_after_enough_time(self):
        """Both gates must pass. Frames alone are not enough."""
        tracker = DwellTracker(DwellPolicy(min_frames=6, min_seconds=1.0))
        _feed(tracker, 3, step=2.0)  # 4+ seconds, only 3 frames

        assert tracker.flush() is None

    def test_too_little_time_produces_nothing_even_with_enough_frames(self):
        """And time alone is not enough either.

        This is the case a frames-only policy gets wrong: at 12 fps, six
        frames is half a second, which is a glance.
        """
        tracker = DwellTracker(DwellPolicy(min_frames=4, min_seconds=1.0))
        _feed(tracker, 8, step=0.05)  # 8 frames in 0.4 s

        assert tracker.flush() is None

    def test_enough_frames_and_enough_time_qualifies(self):
        tracker = DwellTracker(DwellPolicy(min_frames=4, min_seconds=1.0))
        _feed(tracker, 6, step=0.3)

        dwell = tracker.flush()

        assert dwell is not None
        assert dwell.frames_seen == 6
        assert dwell.seconds == pytest.approx(1.5)
        assert dwell.end_reason == END_REASON_STOPPED


class TestItSurvivesOrdinaryInterruption:
    def test_a_brief_loss_does_not_end_the_dwell(self):
        """A blink of occlusion or one bad frame is not a page turn."""
        tracker = DwellTracker(DwellPolicy(max_missing_frames=3))
        _feed(tracker, 6)

        for _ in range(3):
            assert tracker.observe(None, at=2.0) is None

        assert tracker.in_dwell

    def test_a_sustained_loss_ends_it(self):
        tracker = DwellTracker(DwellPolicy(max_missing_frames=3))
        _feed(tracker, 6)

        finished = [tracker.observe(None, at=2.0 + i) for i in range(5)]

        assert any(dwell is not None for dwell in finished)
        assert not tracker.in_dwell
        completed = next(dwell for dwell in finished if dwell is not None)
        assert completed.end_reason == END_REASON_LOST

    def test_a_missing_frame_still_counts_as_considered(self):
        """frames_considered is the honest denominator for a dwell."""
        tracker = DwellTracker(DwellPolicy(max_missing_frames=3))
        _feed(tracker, 6)
        tracker.observe(None, at=2.0)

        dwell = tracker.flush()

        assert dwell.frames_seen == 6
        assert dwell.frames_considered == 7


class TestItSeparatesDocuments:
    def test_a_region_that_jumps_across_the_frame_starts_a_new_dwell(self):
        """Turning from one document to another is two documents.

        Without this the two would merge into one record with interleaved
        text, which would be a document that never existed.
        """
        tracker = DwellTracker(DwellPolicy(min_frames=2, min_seconds=0.2))
        _feed(tracker, 4, candidate=_candidate(centre=(150.0, 240.0)))

        finished = tracker.observe(
            _candidate(centre=(600.0, 240.0)),
            at=2.0,
            gray=_gray(),
            frame_diagonal=FRAME_DIAGONAL,
        )

        assert finished is not None, "the first document must be completed"
        assert tracker.in_dwell, "and the second must have started"

    def test_a_region_that_changes_size_dramatically_starts_a_new_dwell(self):
        tracker = DwellTracker(DwellPolicy(min_frames=2, min_seconds=0.2))
        _feed(tracker, 4, candidate=_candidate(area=0.6))

        finished = tracker.observe(
            _candidate(area=0.1),
            at=2.0,
            gray=_gray(),
            frame_diagonal=FRAME_DIAGONAL,
        )

        assert finished is not None

    def test_small_hand_motion_does_not_split_a_document(self):
        """A person holding a page is not a tripod.

        The drift here is cumulative and ends far from where it started,
        which is why the tracker compares against the LATEST accepted
        region rather than the first.
        """
        tracker = DwellTracker(DwellPolicy(min_frames=2, min_seconds=0.2))
        at = 0.0
        for index in range(20):
            finished = tracker.observe(
                _candidate(centre=(300.0 + index * 6.0, 240.0 + index * 3.0)),
                at=at,
                gray=_gray(),
                frame_diagonal=FRAME_DIAGONAL,
            )
            assert finished is None, f"split at frame {index}"
            at += 0.3

        assert tracker.in_dwell


class TestItIsBounded:
    def test_a_page_left_in_view_forever_becomes_one_bounded_observation(self):
        """Rule 15: nothing unbounded. A document on a desk all afternoon
        must not accumulate into an ever-growing record."""
        tracker = DwellTracker(DwellPolicy(max_seconds=5.0, min_frames=2))
        finished, _ = _feed(tracker, 40, step=0.3)

        assert finished, "the dwell must have been closed by the bound"
        assert finished[0].end_reason == END_REASON_MAX_DURATION

    def test_only_the_frames_that_will_be_ocred_are_retained(self):
        """Bounded memory, and bounded imagery.

        A long dwell must not accumulate wearer imagery -- only the
        handful of frames that will actually be read.
        """
        tracker = DwellTracker(DwellPolicy(best_frames=2, min_frames=2))
        _feed(tracker, 50)

        dwell = tracker.flush()

        assert len(dwell.best) == 2


class TestBestFrameSelection:
    def test_the_sharpest_frame_wins(self):
        tracker = DwellTracker(DwellPolicy(best_frames=1, min_frames=2, min_seconds=0.1))
        at = 0.0
        for sharpness in (100.0, 900.0, 200.0):
            tracker.observe(
                _candidate(sharpness=sharpness),
                at=at,
                gray=_gray(),
                frame_diagonal=FRAME_DIAGONAL,
            )
            at += 0.3

        dwell = tracker.flush()

        assert dwell.best[0].candidate.sharpness == 900.0

    def test_squareness_breaks_a_tie_between_equally_sharp_frames(self):
        """A razor-sharp page seen at 60 degrees warps into a poor read."""
        tracker = DwellTracker(DwellPolicy(best_frames=1, min_frames=2, min_seconds=0.1))
        at = 0.0
        for squareness in (0.3, 0.95):
            tracker.observe(
                _candidate(sharpness=500.0, squareness=squareness),
                at=at,
                gray=_gray(),
                frame_diagonal=FRAME_DIAGONAL,
            )
            at += 0.3

        dwell = tracker.flush()

        assert dwell.best[0].candidate.squareness == 0.95

    def test_a_dwell_of_only_blurry_frames_does_not_qualify(self):
        """Better no record than a record of unreadable text."""
        tracker = DwellTracker(DwellPolicy(min_sharpness=100.0, min_frames=2))
        _feed(tracker, 8, candidate=_candidate(sharpness=10.0))

        assert tracker.flush() is None
