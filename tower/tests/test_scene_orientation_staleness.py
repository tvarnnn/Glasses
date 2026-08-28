"""A facing estimate whose cost depends on the device must carry its age.

Orientation runs at a cadence rather than per frame, and the estimates it
produces are stale by construction. The original reason -- "it costs 23x
the detector on this CPU" -- was measured on CPU with synthetic input and
is now known to be wrong in both directions: 43.4 ms on CUDA (1.43x the
detector) and 956.4 ms on CPU (29.1x), against a delivered frame interval
of 83.5 ms rather than the ~300 ms the docs assumed.

The age field survives that correction because CPU is still the default
device at 11.5x the frame interval, and because `age_estimate`'s clamp
guards a clock bug no GPU touches. A consumer that cannot see how stale
an estimate is being told something false with a true-looking shape.

These tests use `FixedPoseEstimator`, so the keypoint visibility pattern
-- and therefore the correct facing state -- is chosen here rather than
read back from a model.
"""

import numpy as np
import pytest

from tower.confidence import Confidence
from tower.scene.detect import FixedDetector
from tower.scene.engine import (
    DELIVERED_FRAME_INTERVAL_S,
    ORIENTATION_FRAME_STRIDE,
    ORIENTATION_INTERVAL_S,
    SceneEngine,
)
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
        """Explicitly at the old 2.0 s interval, not the default.

        Pinned here so this test keeps testing the cadence MECHANISM
        rather than whatever the cadence constant currently is.
        """
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


class TestAgeIsPerTrackNotPerRun:
    """A run that fails to find someone must not refresh THEIR estimate.

    Found by re-reading the design rather than by a failing test, which is
    why it is worth spelling out: the age was computed from the last
    orientation RUN, not from when this track was last estimated. Those
    diverge exactly when staleness matters most -- the pose model runs,
    does not find this person because they turned away, and the track
    keeps its old reading.

    Measured before the fix: an estimate made at t=0 still reported
    `age=1.0` and `toward_wearer` at **t=11**, because every run reset it.
    The expiry that exists to catch precisely this never fired.
    """

    @staticmethod
    def _engine_that_sees_once():
        # The pose estimator finds the person on its first call and
        # nothing on every call after -- a person who turned away.
        pose = FixedPoseEstimator([[(BoundingBox(*PERSON_BOX), FACING)], [], [], []])
        engine = SceneEngine(
            FixedDetector([_person()] * 200),
            POLICY,
            clock=lambda: 0.0,
            pose_estimator=pose,
            orientation_interval_s=2.0,
        )
        engine.load()
        return engine, pose

    def test_a_stale_estimate_keeps_ageing_across_later_runs(self):
        engine, pose = self._engine_that_sees_once()

        ages = []
        at = 0.0
        for _ in range(16):
            state = engine.observe(FRAME, received_at=at)
            if state.of_class("person"):
                ages.append(state.of_class("person")[0].facing.age_seconds)
            at += 0.5

        assert pose.calls >= 3, "later runs must actually have happened"
        assert ages == sorted(ages), f"the age reset: {ages}"
        assert ages[-1] > 5.0, f"final age {ages[-1]} -- it was being reset"

    def test_a_stale_estimate_eventually_expires_to_unknown(self):
        """The expiry only works if the age is honest."""
        engine, _ = self._engine_that_sees_once()

        state = None
        at = 0.0
        while at <= MAX_ESTIMATE_AGE_S + 3.0:
            state = engine.observe(FRAME, received_at=at)
            at += 0.5

        person = state.of_class("person")[0]
        assert person.facing.state == FACING_UNKNOWN
        assert person.facing.age_seconds > MAX_ESTIMATE_AGE_S

    def test_a_track_that_was_never_estimated_reports_unknown(self):
        """And not the previous occupant's reading."""
        pose = FixedPoseEstimator([[]])
        engine = SceneEngine(
            FixedDetector([_person()] * 20),
            POLICY,
            clock=lambda: 0.0,
            pose_estimator=pose,
        )
        engine.load()

        state = None
        for index in range(8):
            state = engine.observe(FRAME, received_at=index * 0.3)

        person = state.of_class("person")[0]
        assert person.facing.state == FACING_UNKNOWN
        assert person.facing_estimated_at is None


class TestTheCadenceIsDerivedNotGuessed:
    """The cadence constant must show its arithmetic.

    `ORIENTATION_INTERVAL_S` was 2.0 s, justified by a 744 ms per-call
    cost against a "~300 ms" delivered frame interval. Measurement on 754
    real corpus frames disproved both numbers: the call is 43.4 ms on
    CUDA (956.4 ms on CPU) and the corpus's own `frames.jsonl` puts the
    delivered interval at 83.5 ms, not 300 ms.

    So these tests pin the cadence to the frame interval it is derived
    FROM, not to a literal. A successor who changes one of the two must
    change the other deliberately, and a successor who restores 2.0 s
    finds out here why that was never a free choice.
    """

    def test_the_delivered_frame_interval_is_the_measured_one(self):
        """83.5 ms == 12.0 fps, from the corpus receipt timestamps."""
        assert DELIVERED_FRAME_INTERVAL_S == pytest.approx(0.0835)
        assert 1.0 / DELIVERED_FRAME_INTERVAL_S == pytest.approx(12.0, abs=0.05)

    def test_the_cadence_is_a_whole_number_of_delivered_frames(self):
        """Not a round-looking literal -- a stride times the interval."""
        assert ORIENTATION_FRAME_STRIDE == int(ORIENTATION_FRAME_STRIDE)
        assert ORIENTATION_INTERVAL_S == pytest.approx(
            ORIENTATION_FRAME_STRIDE * DELIVERED_FRAME_INTERVAL_S
        )

    def test_the_stride_is_one_tracker_confirmation_window(self):
        """The reason the stride is 3 and not some other small number.

        `TrackerPolicy.min_hits` is how many consecutive frames a track
        must be seen before it is confirmed at all. Estimating facing
        more often than a track can be confirmed buys nothing; estimating
        it less often means a track can be confirmed, reported and
        dropped without its facing ever being measured once.
        """
        assert ORIENTATION_FRAME_STRIDE == TrackerPolicy.min_hits

    def test_the_two_second_cadence_would_fail_this_derivation(self):
        """The constant this replaced, checked rather than described.

        2.0 s is 24 delivered frames -- eight confirmation windows, and
        four times the 6.0 s expiry away from a fresh reading. It is not
        a stride the derivation can produce.
        """
        old_stride = 2.0 / DELIVERED_FRAME_INTERVAL_S

        assert old_stride > TrackerPolicy.min_hits
        assert ORIENTATION_INTERVAL_S != pytest.approx(2.0)
        assert ORIENTATION_INTERVAL_S < MAX_ESTIMATE_AGE_S / 10

    def test_the_measured_call_fits_inside_the_cadence_on_cuda(self):
        """43.4 ms median, 50.6 ms p95, into a ~250 ms window.

        Orientation's share of wall clock drops from 52% if it ran per
        frame to under a fifth at this cadence, which is what leaves the
        detector's own 30.4 ms room inside the 83.5 ms budget.
        """
        cuda_p95_s = 0.0506

        assert cuda_p95_s < ORIENTATION_INTERVAL_S / 4
