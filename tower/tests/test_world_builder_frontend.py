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
    def _seeded_selector(self, policy=None) -> KeyframeSelector:
        selector = KeyframeSelector(policy)
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
        """Survival is under `loss_survival_ratio`, which is 0.05.

        The floor moved down from 0.15 on the 2026-08-24 measurement, so
        "collapsed" now means very nearly nothing survived rather than
        one track in seven. A frame at 0.05 exactly is NOT lost -- the
        comparison is strict -- which is why this uses 0.01.

        `loss_grace_frames=1` deliberately: this test is about WHERE the
        floor is, not how much sustained evidence a break needs. The grace
        window has its own tests in test_world_builder_loss_grace.py, and
        mixing the two here would leave neither pinned clearly.
        """
        selector = self._seeded_selector(KeyframePolicy(loss_grace_frames=1))
        selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(), _motion_summary(survival_ratio=0.01)
        )

        assert decision.outcome == TRACKING_LOST
        assert decision.reason == REASON_TRACKING_LOST

    def test_degraded_tracking_is_rejected_without_declaring_loss(self):
        """The band [loss_survival_ratio, min_survival_ratio) = [0.05, 0.20).

        Both floors moved down on the 2026-08-24 measurement, so the
        reject band is narrower and sits lower than the old
        [0.15, 0.35): a frame at 0.25 survival is now healthy enough to
        be rescued by the overlap floor instead of discarded, which is
        the whole point of the change. 0.10 is the new middle of the
        band.
        """
        selector = self._seeded_selector()
        selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(), _motion_summary(survival_ratio=0.10)
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


class TestRescueWindow:
    """The gap between the survival reject and the overlap floor.

    Measured on the 2026-08-24 physical walk: `overlap_ratio` and
    `survival_ratio` are equal in 1283 of 1358 frames (max gap 0.029),
    because real tracks die rather than leave frame. The overlap floor
    can therefore only rescue a frame whose survival sits in
    [min_survival_ratio, min_overlap_ratio). Everything in this class
    protects the existence and the width of that band; the class exists
    because the band was 0.10 wide, fired on 36 of 1395 frames, and the
    walk broke into 36 segments.
    """

    def _seeded_selector(self, policy=None) -> KeyframeSelector:
        selector = KeyframeSelector(policy)
        selector.note_frame(_quality())
        selector.evaluate(_quality(), None)
        selector.note_accepted()
        return selector

    def test_the_floors_are_ordered_so_a_rescue_window_exists(self):
        """A policy where these cross is incoherent, not merely tuned badly.

        If `loss` rose above `min_survival` the degraded-tracking reject
        would be unreachable; if `min_survival` rose above `min_overlap`
        the overlap floor would be unreachable and every decaying chain
        would run straight to `tracking_lost`.
        """
        policy = KeyframePolicy()

        assert policy.loss_survival_ratio < policy.min_survival_ratio
        assert policy.min_survival_ratio < policy.min_overlap_ratio

    def test_the_rescue_window_is_materially_wide(self):
        """A narrow window is exactly the defect being fixed.

        At the shipped-until-2026-08-24 values the band was
        [0.35, 0.45), 0.10 wide, and on real footage that admitted 36
        frames out of 1395 -- 28 of which were already being accepted
        for parallax. The gate was very nearly dead. This asserts the
        band is wide enough to be a real gate rather than rounding
        noise; it is deliberately not an equality on 0.55, because the
        point is the width and not the particular numbers.
        """
        policy = KeyframePolicy()

        width = policy.min_overlap_ratio - policy.min_survival_ratio

        assert width >= 0.40

    def test_a_decaying_chain_is_rescued_before_it_is_declared_lost(self):
        """The actual invariant, and it FAILED under the old constants.

        A real walk does not lose tracking in one step; survival decays
        over a run of frames. The policy's promise is that somewhere in
        that decay a keyframe is taken, so the chain is extended rather
        than cut. Under 0.45/0.35/0.15 this sequence produced only
        `tracking_degraded` rejections and then `tracking_lost` -- no
        keyframe at all -- because overlap tracks survival on real
        footage and both were already under the reject floor by the time
        the overlap floor could see them.

        Displacement is held below `min_displacement_frac` throughout so
        that nothing here can be accepted for parallax: any ACCEPT is
        the overlap floor doing its job.
        """
        selector = self._seeded_selector()
        outcomes = []
        for survival in (0.90, 0.70, 0.50, 0.30, 0.10, 0.02):
            selector.note_frame(_quality())
            decision = selector.evaluate(
                _quality(),
                # overlap == survival, as measured on real footage.
                _motion_summary(
                    survival_ratio=survival,
                    overlap_ratio=survival,
                    median_displacement_px=2.0,
                ),
            )
            outcomes.append((survival, decision))
            if decision.accepted:
                selector.note_accepted()
            elif decision.lost:
                selector.note_lost()

        reasons = [(s, d.outcome, d.reason) for s, d in outcomes]
        accepted_before_loss = [
            survival
            for survival, decision in outcomes[
                : next(i for i, (_, d) in enumerate(outcomes) if d.lost)
            ]
            if decision.accepted
        ]

        assert any(d.lost for _, d in outcomes), reasons
        assert accepted_before_loss, reasons
        assert all(
            decision.reason == REASON_OVERLAP_FLOOR
            for _, decision in outcomes
            if decision.accepted
        ), reasons

    def test_survival_above_the_overlap_floor_still_waits_for_parallax(self):
        """The rescue must not swallow the parallax path entirely.

        Healthy tracking with too little motion is still a SKIP. If this
        ever turns into an ACCEPT the policy has stopped selecting
        keyframes and started taking every frame.
        """
        selector = self._seeded_selector()
        selector.note_frame(_quality())

        decision = selector.evaluate(
            _quality(),
            _motion_summary(
                survival_ratio=0.95, overlap_ratio=0.95, median_displacement_px=2.0
            ),
        )

        assert decision.outcome == SKIP
        assert decision.reason == REASON_INSUFFICIENT_MOTION

    def test_blur_is_still_the_first_gate_and_still_on_the_absolute_floor(self):
        """Guards the two things the 2026-08-24 measurement said NOT to change.

        Loosening the blur gate makes segmentation monotonically worse
        (`min_sharpness_ratio` 0.45 -> 43 segments, off -> 49), and
        reordering the survival/overlap gates ahead of blur -> 40, versus
        a 36-segment baseline. 77% of blur rejections happen when
        survival is already below 0.15, so blur was masking losses that
        had already occurred rather than causing them.

        The frame here is both unusably blurred and completely untracked.
        Blur must win, which is only true if it is evaluated first.
        """
        policy = KeyframePolicy()
        assert policy.min_sharpness == 25.0
        assert policy.min_sharpness_ratio == 0.55

        selector = self._seeded_selector()
        blurred = FrameQuality(width=WIDTH, height=HEIGHT, sharpness=3.0)
        selector.note_frame(blurred)

        decision = selector.evaluate(blurred, _motion_summary(survival_ratio=0.0))

        assert decision.outcome == REJECT
        assert decision.reason == REASON_BLURRED


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


class TestSharpnessUsesAnExactIntermediate:
    """`measure_sharpness` computes the Laplacian at CV_16S, not CV_64F.

    That is a 7.40x saving on every delivered frame (1.429 ms -> 0.193 ms,
    measured on 120 real Ray-Ban frames), and it is only legitimate
    because the narrower type is EXACT here rather than merely adequate.

    The argument, which these tests pin rather than restate: the input is
    8-bit and `ksize` defaults to 1, so the kernel is
    [[0,1,0],[1,-4,1],[0,1,0]] and the output cannot leave +/-4*255 =
    +/-1020, against int16's +/-32767. Saturation is unreachable, so the
    int16 Laplacian equals the float64 one bit for bit and only the
    variance reduction differs, in the last bits of a float64.

    If someone later widens the kernel, raises `ksize`, or feeds 16-bit
    input, that argument collapses and `test_the_maximum_is_exactly_1020_squared`
    is the test that should notice.
    """

    @staticmethod
    def _reference(gray):
        """The pre-optimisation implementation."""
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def test_the_int16_laplacian_is_bit_identical_to_float64(self):
        rng = np.random.default_rng(3)
        gray = rng.integers(0, 256, (640, 360), dtype=np.uint8)
        wide = cv2.Laplacian(gray, cv2.CV_64F)
        narrow = cv2.Laplacian(gray, cv2.CV_16S)
        assert np.array_equal(wide, narrow.astype(np.float64)), (
            "CV_16S diverged from CV_64F -- the saturation argument has failed"
        )

    def test_the_maximum_is_exactly_1020_squared(self):
        """A checkerboard is the worst case: every pixel is a full-swing
        extremum. If this exceeds int16 the optimisation is unsound."""
        checker = (np.indices((64, 64)).sum(0) % 2 * 255).astype(np.uint8)
        narrow = cv2.Laplacian(checker, cv2.CV_16S)
        assert int(np.abs(narrow).max()) == 1020, (
            f"expected the +/-1020 bound, saw {int(np.abs(narrow).max())}"
        )
        assert measure_sharpness(checker) == pytest.approx(1020.0 ** 2)

    @pytest.mark.parametrize(
        "name,gray",
        [
            ("uniform black", np.zeros((64, 64), np.uint8)),
            ("uniform white", np.full((64, 64), 255, np.uint8)),
            ("single pixel", np.array([[128]], np.uint8)),
            ("one row", np.arange(64, dtype=np.uint8).reshape(1, 64)),
            ("one column", np.arange(64, dtype=np.uint8).reshape(64, 1)),
            ("real size noise",
             np.random.default_rng(0).integers(0, 256, (640, 360), dtype=np.uint8)),
        ],
    )
    def test_it_matches_the_reference_on_degenerate_shapes(self, name, gray):
        """Degenerate shapes are where a narrower dtype or a different
        reduction most easily diverges, and none of them raise."""
        got = measure_sharpness(gray)
        expected = self._reference(gray)
        assert got == pytest.approx(expected, rel=1e-12, abs=1e-12), name

    def test_a_flat_image_is_exactly_zero_not_nearly_zero(self):
        """The absolute floor compares against 25.0; a flat frame must
        land at zero rather than at some small positive epsilon."""
        assert measure_sharpness(np.full((64, 64), 77, np.uint8)) == 0.0
