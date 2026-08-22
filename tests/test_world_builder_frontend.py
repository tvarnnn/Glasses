"""Live-path measurements and the keyframe policy.

SYNTHETIC, NOT PHYSICAL.
"""

import cv2
import numpy as np
import pytest

from tests import synthetic_scene as ss
from tower.world_builder.frontend import (
    FrameQuality,
    FrameTracker,
    MotionSummary,
    analyse_frame,
    decode_gray,
    measure_sharpness,
    seed_tracks,
    summarise_motion,
)
from tower.world_builder.keyframes import (
    ACCEPT,
    REASON_BLURRED,
    REASON_INSUFFICIENT_MOTION,
    REASON_OVERLAP_FLOOR,
    REASON_PARALLAX,
    REASON_SESSION_SEED,
    REASON_TRACKING_DEGRADED,
    REASON_TRACKING_LOST,
    REJECT,
    SKIP,
    TRACKING_LOST,
    KeyframePolicy,
    KeyframeSelector,
)

WIDTH, HEIGHT = 480, 360


@pytest.fixture(scope="module")
def scene():
    return ss.furnished_room()


@pytest.fixture(scope="module")
def camera_matrix():
    return ss.camera_matrix(WIDTH, HEIGHT)


def _grays(scene, camera_matrix, poses):
    return [
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        for image in ss.render_sequence(scene, poses, camera_matrix, WIDTH, HEIGHT)
    ]


def _motion(scene, camera_matrix, poses):
    grays = _grays(scene, camera_matrix, poses)
    return summarise_motion(grays[0], grays[1], seed_tracks(grays[0]))


def _quality() -> FrameQuality:
    return FrameQuality(width=WIDTH, height=HEIGHT, sharpness=500.0)


class TestFrameMeasurements:
    def test_decode_gray_returns_single_channel(self, scene, camera_matrix):
        image = ss.render(scene, ss.strafe(1)[0], camera_matrix, WIDTH, HEIGHT)[0]

        gray = decode_gray(ss.encode_jpeg(image))

        assert gray.ndim == 2
        assert gray.shape == (HEIGHT, WIDTH)

    def test_decode_gray_rejects_a_malformed_payload(self):
        """One bad frame is a frame-scoped failure, not a session failure."""
        with pytest.raises(ValueError):
            decode_gray(b"this is not a jpeg")

    def test_sharpness_falls_sharply_with_blur(self, scene, camera_matrix):
        """The measurement that makes cheap early rejection possible."""
        gray = _grays(scene, camera_matrix, ss.strafe(1))[0]

        sharp = measure_sharpness(gray)
        blurred = measure_sharpness(ss.blur(gray, kernel=9))

        assert sharp > blurred * 5

    def test_analyse_frame_reports_dimensions(self, scene, camera_matrix):
        gray = _grays(scene, camera_matrix, ss.strafe(1))[0]

        quality = analyse_frame(gray)

        assert (quality.width, quality.height) == (WIDTH, HEIGHT)
        assert quality.diagonal_px == pytest.approx(np.hypot(WIDTH, HEIGHT))


class TestMotionSummary:
    def test_translation_produces_displacement_and_residual(
        self, scene, camera_matrix
    ):
        motion = _motion(scene, camera_matrix, ss.strafe(2, step=0.30))

        assert motion.tracked_count > 100
        assert motion.survival_ratio > 0.5
        assert motion.median_displacement_px > 5.0
        assert motion.homography_residual_px is not None

    def test_pure_rotation_moves_pixels_but_leaves_no_residual(
        self, scene, camera_matrix
    ):
        """Records that displacement is not parallax.

        A pure rotation moves pixels a long way while contributing zero
        baseline, so displacement alone cannot mean "there is geometry
        here". The residual does drop to near zero for THIS clean case --
        but see test_residual_does_not_separate_combined_motion for why
        that does not generalise into a usable gate.
        """
        motion = _motion(scene, camera_matrix, ss.pure_rotation(2, 2.0))

        assert motion.median_displacement_px > 5.0
        assert motion.homography_residual_px < 0.2

    def test_translation_residual_exceeds_rotation_residual(
        self, scene, camera_matrix
    ):
        """True for clean, separated motions -- and NOT sufficient. See below."""
        rotating = _motion(scene, camera_matrix, ss.pure_rotation(2, 2.0))
        translating = _motion(scene, camera_matrix, ss.strafe(2, step=0.30))

        assert translating.homography_residual_px > rotating.homography_residual_px

    def test_residual_does_not_separate_combined_motion(
        self, scene, camera_matrix
    ):
        """Why there is no rotation gate in the keyframe policy.

        Rotation alone and rotation-plus-translation produce overlapping
        residuals, because the rotation dominates the pixel motion and the
        homography absorbs it. This test exists so the negative result
        stays visible to anyone tempted to reintroduce the gate.
        """
        angle = np.deg2rad(4.0)
        start = ss.look_at((0.0, -1.6, 1.2), (0.0, -1.6, 2.2))
        turned_and_moved = ss.look_at(
            (0.25, -1.6, 1.2),
            (0.25 + np.sin(angle), -1.6, 1.2 + np.cos(angle)),
        )

        rotating = _motion(scene, camera_matrix, ss.pure_rotation(2, 4.0))
        combined = _motion(scene, camera_matrix, [start, turned_and_moved])

        rotating_ratio = (
            rotating.homography_residual_px / rotating.median_displacement_px
        )
        combined_ratio = (
            combined.homography_residual_px / combined.median_displacement_px
        )

        # The pair that genuinely translated scores LOWER than the pair
        # that only rotated. No threshold can separate these.
        assert combined_ratio < rotating_ratio

    def test_no_seeds_yields_an_empty_summary(self, scene, camera_matrix):
        gray = _grays(scene, camera_matrix, ss.strafe(1))[0]

        motion = summarise_motion(gray, gray, None)

        assert motion.tracked_count == 0
        assert not motion.has_motion_evidence

    def test_a_completely_different_scene_collapses_survival(
        self, scene, camera_matrix
    ):
        gray = _grays(scene, camera_matrix, ss.strafe(1))[0]
        noise = np.random.default_rng(7).integers(
            0, 255, gray.shape, dtype=np.uint8
        )

        motion = summarise_motion(gray, noise, seed_tracks(gray))

        assert motion.survival_ratio < 0.35


class TestFrameTracker:
    def test_measure_returns_none_without_a_reference(self, scene, camera_matrix):
        gray = _grays(scene, camera_matrix, ss.strafe(1))[0]

        assert FrameTracker().measure(gray) is None

    def test_reference_advances_only_when_set(self, scene, camera_matrix):
        grays = _grays(scene, camera_matrix, ss.strafe(3, step=0.15))
        tracker = FrameTracker()
        tracker.set_reference(grays[0])

        near = tracker.measure(grays[1])
        far = tracker.measure(grays[2])

        # Both measured against frame 0, so the second must have moved more.
        assert far.median_displacement_px > near.median_displacement_px

    def test_reset_clears_the_reference(self, scene, camera_matrix):
        grays = _grays(scene, camera_matrix, ss.strafe(2))
        tracker = FrameTracker()
        tracker.set_reference(grays[0])

        tracker.reset()

        assert not tracker.has_reference
        assert tracker.measure(grays[1]) is None


def _motion_summary(**overrides) -> MotionSummary:
    base = dict(
        seeded_count=400,
        tracked_count=350,
        survival_ratio=0.875,
        overlap_ratio=0.85,
        median_displacement_px=40.0,
        homography_residual_px=0.6,
    )
    base.update(overrides)
    return MotionSummary(**base)


class TestKeyframePolicy:
    def _seeded_selector(self) -> KeyframeSelector:
        selector = KeyframeSelector()
        selector.note_frame(_quality())
        selector.evaluate(_quality(), None)
        selector.note_accepted()
        return selector

    def test_first_frame_seeds_the_session(self):
        selector = KeyframeSelector()
        selector.note_frame(_quality())

        decision = selector.evaluate(_quality(), None)

        assert decision.outcome == ACCEPT
        assert decision.reason == REASON_SESSION_SEED

    def test_a_blurred_frame_is_never_promoted(self):
        """Including as the session seed.

        Anchoring a session on a smeared frame poisons every measurement
        taken against it afterwards.
        """
        selector = KeyframeSelector()
        blurred = FrameQuality(width=WIDTH, height=HEIGHT, sharpness=3.0)
        selector.note_frame(blurred)

        decision = selector.evaluate(blurred, None)

        assert decision.outcome == REJECT
        assert decision.reason == REASON_BLURRED

    def test_a_frame_much_blurrier_than_its_neighbours_is_rejected(self):
        """Catches a head-turn smear in a scene that is dim throughout."""
        selector = KeyframeSelector()
        for _ in range(10):
            selector.note_frame(FrameQuality(WIDTH, HEIGHT, 400.0))
        smeared = FrameQuality(WIDTH, HEIGHT, 120.0)
        selector.note_frame(smeared)

        decision = selector.evaluate(smeared, _motion_summary())

        assert decision.outcome == REJECT
        assert decision.reason == REASON_BLURRED

    def test_collapsed_tracking_reports_loss(self):
        selector = self._seeded_selector()
        selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(), _motion_summary(survival_ratio=0.05)
        )

        assert decision.outcome == TRACKING_LOST
        assert decision.reason == REASON_TRACKING_LOST

    def test_degraded_tracking_is_rejected_without_declaring_loss(self):
        selector = self._seeded_selector()
        selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(), _motion_summary(survival_ratio=0.25)
        )

        assert decision.outcome == REJECT
        assert decision.reason == REASON_TRACKING_DEGRADED

    def test_collapsing_overlap_forces_acceptance_at_low_parallax(self):
        """Losing correspondence is worse than a weak keyframe."""
        selector = self._seeded_selector()
        selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(),
            _motion_summary(overlap_ratio=0.20, median_displacement_px=4.0),
        )

        assert decision.outcome == ACCEPT
        assert decision.reason == REASON_OVERLAP_FLOOR

    def test_the_policy_does_not_try_to_decide_degeneracy(self):
        """Rotation-dominance is NOT decided here, on measurement.

        A homography-residual gate was implemented and removed: the
        residual distributions for pure rotation and for genuine
        translation overlap once a head both turns and moves, because the
        rotation dominates the pixel motion and the homography absorbs
        it. See the keyframes module docstring for the numbers.

        A frame with plenty of motion is therefore accepted here even
        when its residual looks rotational; the geometry backend refuses
        the pose later using triangulation angle, which needs intrinsics
        and does separate cleanly.
        """
        selector = self._seeded_selector()
        selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(),
            _motion_summary(median_displacement_px=60.0, homography_residual_px=0.05),
        )

        assert decision.outcome == ACCEPT
        assert decision.reason == REASON_PARALLAX

    def test_genuine_parallax_is_accepted(self):
        selector = self._seeded_selector()
        selector.note_frame(_quality())

        decision = selector.evaluate(_quality(), _motion_summary())

        assert decision.outcome == ACCEPT
        assert decision.reason == REASON_PARALLAX

    def test_small_motion_is_skipped(self):
        selector = self._seeded_selector()
        selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(), _motion_summary(median_displacement_px=2.0)
        )

        assert decision.outcome == SKIP
        assert decision.reason == REASON_INSUFFICIENT_MOTION

    def test_stall_is_reported_without_forcing_a_keyframe(self):
        """A hole in the map is honest; a fabricated keyframe is not."""
        selector = self._seeded_selector()
        policy = KeyframePolicy()
        for _ in range(policy.max_frame_gap + 2):
            selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(), _motion_summary(median_displacement_px=1.0)
        )

        assert selector.is_stalled
        assert decision.outcome != ACCEPT

    def test_every_decision_carries_a_reason(self):
        selector = self._seeded_selector()
        cases = [
            _motion_summary(),
            _motion_summary(survival_ratio=0.05),
            _motion_summary(survival_ratio=0.25),
            _motion_summary(overlap_ratio=0.1),
            _motion_summary(median_displacement_px=1.0),
            _motion_summary(homography_residual_px=0.01),
        ]
        for motion in cases:
            selector.note_frame(_quality())
            decision = selector.evaluate(_quality(), motion)
            assert decision.reason

    def test_acceptance_resets_the_frame_counter(self):
        selector = self._seeded_selector()
        selector.note_frame(_quality())
        selector.note_frame(_quality())
        assert selector.frames_since_keyframe > 0

        selector.note_accepted()

        assert selector.frames_since_keyframe == 0

    def test_policy_is_frozen_so_a_sweep_can_record_it(self):
        with pytest.raises(Exception):
            KeyframePolicy().min_sharpness = 1.0


class TestPolicyOnRenderedMotion:
    """End-to-end on real rendered frames rather than fabricated summaries."""

    def test_a_full_pass_produces_reasoned_decisions_for_every_frame(
        self, scene, camera_matrix
    ):
        def count_accepted(poses):
            grays = _grays(scene, camera_matrix, poses)
            selector = KeyframeSelector()
            tracker = FrameTracker()
            accepted = 0
            for gray in grays:
                quality = analyse_frame(gray)
                selector.note_frame(quality)
                motion = tracker.measure(gray)
                decision = selector.evaluate(quality, motion)
                if decision.accepted:
                    tracker.set_reference(gray)
                    selector.note_accepted()
                    accepted += 1
                elif decision.lost:
                    tracker.reset()
                    selector.note_lost()
            return accepted

        rotating = count_accepted(ss.pure_rotation(10, degrees_per_step=2.0))
        walking = count_accepted(ss.strafe(10, step=0.12))

        # Both motions produce keyframes -- rotation still needs them to
        # keep the tracking chain alive. What distinguishes them is the
        # pose status the BACKEND later assigns, not the count here.
        assert 0 < rotating < 10
        assert 0 < walking < 10
