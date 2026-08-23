"""Counting must use tracking, and this is where that is proven.

The brief singles this out: *person counting must use tracking rather
than naively summing detections*. Two failure modes make it
non-negotiable, and they pull in opposite directions:

- a detector that misses someone on one frame in five reports a count
  flickering between 2 and 3 while nothing in the room changed;
- a detector that fires twice on one person reports two people.

Every assertion here is against a detection script this file wrote, so
the correct count is known independently of the tracker.
"""

import pytest

from tower.scene.records import BoundingBox, Detection
from tower.scene.tracking import Tracker, TrackerPolicy, detections_from_boxes

POLICY = TrackerPolicy(min_iou=0.25, min_hits=3, max_misses=5)


def _person(box, score=0.9) -> Detection:
    return Detection(label="person", score=score, box=BoundingBox(*box))


def _feed(tracker, frames, start=0.0, step=0.3):
    at = start
    for detections in frames:
        tracker.update(detections, at=at)
        at += step
    return tracker


class TestOneThingIsCountedOnce:
    def test_a_person_standing_still_is_one_track(self):
        tracker = Tracker(POLICY)
        _feed(tracker, [[_person((100, 100, 200, 400))]] * 10)

        assert tracker.count("person") == 1

    def test_a_person_walking_across_the_view_stays_one_track(self):
        """Association must survive real motion.

        At the ~3.3 fps the glasses deliver, a walking person moves a long
        way between frames -- which is why the IoU floor is permissive.
        """
        tracker = Tracker(POLICY)
        frames = [[_person((x, 100, x + 100, 400))] for x in range(0, 300, 30)]
        _feed(tracker, frames)

        assert tracker.count("person") == 1

    def test_two_people_are_two_tracks(self):
        tracker = Tracker(POLICY)
        frames = [
            [_person((50, 100, 150, 400)), _person((400, 100, 500, 400))]
        ] * 8
        _feed(tracker, frames)

        assert tracker.count("person") == 2


class TestADetectorDropoutDoesNotChangeTheCount:
    """The headline requirement, stated as a test.

    A count that flickers with the detector is worse than useless: it
    makes the wearer distrust every answer.
    """

    def test_a_missed_frame_does_not_drop_the_count(self):
        tracker = Tracker(POLICY)
        boxes = [_person((100, 100, 200, 400)), _person((400, 100, 500, 400))]

        # Establish, then lose ONE person for a single frame, then recover.
        _feed(tracker, [boxes] * 5)
        before = tracker.count("person")
        tracker.update([boxes[0]], at=2.0)
        during = tracker.count("person")
        tracker.update(boxes, at=2.3)
        after = tracker.count("person")

        assert (before, during, after) == (2, 2, 2)

    def test_a_sustained_dropout_of_one_in_five_frames_holds_the_count(self):
        tracker = Tracker(POLICY)
        both = [_person((100, 100, 200, 400)), _person((400, 100, 500, 400))]

        counts = []
        at = 0.0
        for index in range(30):
            detections = [both[0]] if index % 5 == 4 else both
            tracker.update(detections, at=at)
            at += 0.3
            if index >= 3:
                counts.append(tracker.count("person"))

        assert set(counts) == {2}, f"count flickered: {sorted(set(counts))}"

    def test_someone_who_leaves_stops_being_counted(self):
        """The other direction: a track that is truly gone must expire."""
        tracker = Tracker(TrackerPolicy(min_hits=3, max_misses=3))
        both = [_person((100, 100, 200, 400)), _person((400, 100, 500, 400))]
        _feed(tracker, [both] * 6)
        assert tracker.count("person") == 2

        for index in range(6):
            tracker.update([both[0]], at=3.0 + index * 0.3)

        assert tracker.count("person") == 1


class TestAFlickerIsNotAPerson:
    def test_a_single_detection_is_not_counted(self):
        """One frame is a flicker, not a person."""
        tracker = Tracker(POLICY)
        tracker.update([_person((100, 100, 200, 400))], at=0.0)

        assert tracker.count("person") == 0
        assert len(tracker.tracks) == 1, "it is tracked, just not confirmed"

    def test_confirmation_needs_the_full_hit_streak(self):
        tracker = Tracker(TrackerPolicy(min_hits=3))
        counts = []
        for index in range(4):
            tracker.update([_person((100, 100, 200, 400))], at=index * 0.3)
            counts.append(tracker.count("person"))

        assert counts == [0, 0, 1, 1]

    def test_a_one_frame_false_positive_never_reaches_the_count(self):
        tracker = Tracker(POLICY)
        real = _person((100, 100, 200, 400))
        ghost = _person((500, 50, 560, 120))

        for index in range(6):
            detections = [real, ghost] if index == 2 else [real]
            tracker.update(detections, at=index * 0.3)

        assert tracker.count("person") == 1


class TestAssociationRules:
    def test_a_chair_never_becomes_a_person(self):
        """Association is within a class.

        Cross-class association would let one label flip rewrite a
        track's identity, so a chair briefly detected as a person would
        merge the two.
        """
        tracker = Tracker(POLICY)
        box = (100, 100, 200, 400)
        _feed(tracker, [detections_from_boxes("chair", [box])] * 6)
        tracker.update(detections_from_boxes("person", [box]), at=3.0)

        assert tracker.count("chair") == 1
        assert tracker.count("person") == 0
        assert len(tracker.tracks) == 2

    def test_two_boxes_that_barely_overlap_are_two_things(self):
        tracker = Tracker(TrackerPolicy(min_iou=0.5, min_hits=1))
        tracker.update([_person((0, 0, 100, 100))], at=0.0)
        tracker.update([_person((90, 90, 190, 190))], at=0.3)

        assert tracker.count("person") == 2

    def test_one_detection_cannot_be_claimed_by_two_tracks(self):
        """Greedy association must not double-assign."""
        tracker = Tracker(TrackerPolicy(min_iou=0.1, min_hits=1))
        tracker.update(
            [_person((0, 0, 100, 100)), _person((50, 0, 150, 100))], at=0.0
        )
        assert len(tracker.tracks) == 2

        tracker.update([_person((25, 0, 125, 100))], at=0.3)

        matched = [track for track in tracker.tracks if track.misses == 0]
        assert len(matched) == 1, "one detection updated two tracks"


class TestTracksCarryNoIdentity:
    def test_ids_do_not_survive_a_reset(self):
        """A track id means "the same blob as last frame", nothing more.

        If ids survived a reset they would begin to mean "the same person
        as before", which is the identity this cartridge must never have.
        """
        tracker = Tracker(POLICY)
        _feed(tracker, [[_person((100, 100, 200, 400))]] * 5)
        first_ids = [track.track_id for track in tracker.tracks]

        tracker.reset()
        _feed(tracker, [[_person((100, 100, 200, 400))]] * 5)
        second_ids = [track.track_id for track in tracker.tracks]

        assert first_ids == second_ids == [1], (
            "ids restart, so nothing can be matched across sessions"
        )

    def test_a_person_who_leaves_and_returns_is_a_new_track(self):
        """Re-identification is deliberately absent.

        Recognising someone as "the same person as five minutes ago" needs
        appearance matching, which is the first step toward identity.
        """
        tracker = Tracker(TrackerPolicy(min_hits=2, max_misses=2))
        box = (100, 100, 200, 400)
        _feed(tracker, [detections_from_boxes("person", [box])] * 4)
        original = tracker.tracks[0].track_id

        for index in range(5):
            tracker.update([], at=3.0 + index * 0.3)
        _feed(tracker, [detections_from_boxes("person", [box])] * 4, start=10.0)

        assert tracker.tracks[0].track_id != original


class TestBoundingBoxGeometry:
    def test_iou_of_a_box_with_itself_is_one(self):
        box = BoundingBox(10, 20, 110, 220)
        assert box.iou(box) == pytest.approx(1.0)

    def test_disjoint_boxes_have_zero_iou(self):
        assert BoundingBox(0, 0, 10, 10).iou(BoundingBox(50, 50, 60, 60)) == 0.0

    def test_iou_matches_a_hand_computed_overlap(self):
        """Two 100x100 boxes offset by 50 in x: overlap 50x100 = 5000,
        union 10000 + 10000 - 5000 = 15000, so 1/3."""
        left = BoundingBox(0, 0, 100, 100)
        right = BoundingBox(50, 0, 150, 100)

        assert left.iou(right) == pytest.approx(1 / 3)

    def test_a_degenerate_box_does_not_divide_by_zero(self):
        assert BoundingBox(5, 5, 5, 5).iou(BoundingBox(0, 0, 10, 10)) == 0.0
