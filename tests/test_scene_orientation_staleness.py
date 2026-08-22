"""A facing estimate that costs 744 ms must carry its age.

The whole reason orientation runs at a cadence rather than per frame is
that it costs 23x the detector on this CPU. That makes every estimate
stale by construction, and a consumer that cannot see how stale is being
told something false with a true-looking shape.

These tests use `FixedPoseEstimator`, so the keypoint visibility pattern
-- and therefore the correct facing state -- is chosen here rather than
read back from a model.
"""

import numpy as np
import pytest

from tower.confidence import Confidence
from tower.scene.detect import FixedDetector
from tower.scene.engine import SceneEngine
from tower.scene.orientation import (
    MAX_ESTIMATE_AGE_S,
    FixedPoseEstimator,
    age_estimate,
    facing_from_keypoints,
)
from tower.scene.records import (
    FACING_TOWARD,
    FACING_UNKNOWN,
    BoundingBox,
    Detection,
    FacingEstimate,
)
from tower.scene.tracking import TrackerPolicy

FRAME = np.zeros((360, 640, 3), np.uint8)
POLICY = TrackerPolicy(min_iou=0.25, min_hits=2, max_misses=5)
PERSON_BOX = (100, 80, 220, 320)
FACING = {"nose": 9.0, "left_eye": 8.0, "right_eye": 8.0, "left_ear": 6.0}


def _person():
    return [Detection(label="person", score=0.9, box=BoundingBox(*PERSON_BOX))]


def _engine(pose, interval=2.0):
    engine = SceneEngine(
        FixedDetector([_person()] * 200),
        POLICY,
        clock=lambda: 0.0,
        pose_estimator=pose,
        orientation_interval_s=interval,
    )
    engine.load()
    return engine


class TestTheEstimateIsRunAtACadence:
    def test_it_does_not_run_on_every_frame(self):
        """744 ms per frame is 2.5x the interval the glasses deliver."""
        pose = FixedPoseEstimator([[(BoundingBox(*PERSON_BOX), FACING)]])
        engine = _engine(pose, interval=2.0)

        for index in range(20):
            engine.observe(FRAME, received_at=index * 0.3)

        # 20 frames over 5.7 s at a 2 s cadence: 4 calls at most.
        assert pose.calls <= 4, f"pose ran {pose.calls} times in 20 frames"

    def test_it_runs_at_least_once(self):
        pose = FixedPoseEstimator([[(BoundingBox(*PERSON_BOX), FACING)]])
        engine = _engine(pose)

        for index in range(6):
            engine.observe(FRAME, received_at=index * 0.3)

        assert pose.calls >= 1

    def test_it_never_runs_when_orientation_is_disabled(self):
        engine = SceneEngine(
            FixedDetector([_person()] * 20), POLICY, clock=lambda: 0.0
        )
        engine.load()

        state = None
        for index in range(10):
            state = engine.observe(FRAME, received_at=index * 0.3)

        assert engine.orientation_enabled is False
        assert all(
            track.facing.state == FACING_UNKNOWN for track in state.tracks
        )


class TestEveryEstimateCarriesItsAge:
    def test_a_fresh_estimate_reports_a_small_age(self):
        pose = FixedPoseEstimator([[(BoundingBox(*PERSON_BOX), FACING)]])
        engine = _engine(pose, interval=100.0)

        state = None
        for index in range(4):
            state = engine.observe(FRAME, received_at=index * 0.3)

        person = state.of_class("person")[0]
        assert person.facing.state == FACING_TOWARD
        assert person.facing.age_seconds == pytest.approx(0.9, abs=0.01)

    def test_the_age_grows_between_estimates(self):
        pose = FixedPoseEstimator([[(BoundingBox(*PERSON_BOX), FACING)]])
        engine = _engine(pose, interval=100.0)

        ages = []
        for index in range(8):
            state = engine.observe(FRAME, received_at=index * 0.5)
            if state.of_class("person"):
                ages.append(state.of_class("person")[0].facing.age_seconds)

        assert ages == sorted(ages)
        assert ages[-1] > ages[0]

    def test_an_estimate_older_than_the_limit_becomes_unknown(self):
        """Not silently kept, and not deleted either.

        Deleting it would leave a consumer reading a missing field as
        "not facing", which is the same observation-gap error in a
        different costume.
        """
        pose = FixedPoseEstimator([[(BoundingBox(*PERSON_BOX), FACING)]])
        engine = _engine(pose, interval=1000.0)

        state = None
        at = 0.0
        while at <= MAX_ESTIMATE_AGE_S + 2.0:
            state = engine.observe(FRAME, received_at=at)
            at += 0.5

        person = state.of_class("person")[0]
        assert person.facing.state == FACING_UNKNOWN
        assert person.facing.age_seconds > MAX_ESTIMATE_AGE_S

    def test_ageing_an_estimate_preserves_its_evidence_until_it_expires(self):
        estimate = FacingEstimate(
            state=FACING_TOWARD,
            confidence=Confidence.MEDIUM,
            visible_eyes=2,
            visible_ears=1,
        )

        fresh = age_estimate(estimate, 1.0)
        expired = age_estimate(estimate, MAX_ESTIMATE_AGE_S + 1.0)

        assert fresh.state == FACING_TOWARD
        assert fresh.visible_eyes == 2
        assert expired.state == FACING_UNKNOWN
        assert expired.confidence is Confidence.UNKNOWN


class TestPoseAssociation:
    def test_a_pose_that_matches_no_track_is_discarded(self):
        """The detector decides what exists.

        Two models disagreeing about whether someone is there must not
        produce a phantom person.
        """
        pose = FixedPoseEstimator(
            [[(BoundingBox(500, 20, 560, 90), FACING)]]  # nowhere near the person
        )
        engine = _engine(pose)

        state = None
        for index in range(6):
            state = engine.observe(FRAME, received_at=index * 0.3)

        assert state.count("person") == 1
        assert state.of_class("person")[0].facing.state == FACING_UNKNOWN

    def test_a_failing_pose_estimator_does_not_end_the_session(self):
        """One model failure must not cost the whole scene."""

        class _Exploding:
            name = "exploding"

            def load(self):
                return None

            def estimate(self, frame_bgr):
                raise RuntimeError("model OOM")

            def release(self):
                return None

        engine = _engine(_Exploding())

        state = None
        for index in range(8):
            state = engine.observe(FRAME, received_at=index * 0.3)

        assert state.count("person") == 1
        assert engine.frames_observed == 8


class TestAFailingDetectorDoesNotEndTheSession:
    def test_detection_failure_is_an_empty_frame_not_a_crash(self):
        class _Exploding:
            name = "exploding"

            def load(self):
                return None

            def detect(self, frame_bgr):
                raise RuntimeError("model OOM")

            def release(self):
                return None

        engine = SceneEngine(_Exploding(), POLICY, clock=lambda: 0.0)
        engine.load()

        state = None
        for index in range(6):
            state = engine.observe(FRAME, received_at=index * 0.3)

        assert engine.frames_observed == 6
        assert state.counts == {}


class TestKeypointThreshold:
    def test_the_visibility_threshold_is_what_makes_this_evidence(self):
        """A keypoint model emits a coordinate for every joint.

        Without a score threshold, "visible" would mean "predicted", every
        person would appear to face the camera, and the whole signal would
        be a constant.
        """
        confident = facing_from_keypoints(
            {"left_eye": 9.0, "right_eye": 9.0, "left_ear": 9.0}
        )
        unconfident = facing_from_keypoints(
            {"left_eye": 0.1, "right_eye": 0.1, "left_ear": 0.1}
        )

        assert confident.state == FACING_TOWARD
        assert unconfident.state == FACING_UNKNOWN
