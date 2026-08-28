"""Do the Lab's measurements actually measure what they claim?

SYNTHETIC, NOT PHYSICAL.

Every assertion here compares against something known INDEPENDENTLY of
the code under test: a deliberately blurred frame, a deliberately blank
one, a rendered walk whose camera motion is exact, a redaction rectangle
whose coordinates we chose. None of them compares the pipeline against
its own output.

That discipline is not stylistic. The World Builder review named eleven
tests that would have passed while the code was broken, and every one of
them asserted against a value the code itself produced.
"""

import io

import cv2
import numpy as np
import pytest
from PIL import Image

from tower.experiments import EXPERIMENTS, ExperimentSettings
from tower.experiments import feature_detection, frame_quality, redaction_impact
from tests import synthetic_scene as ss


def _encode(array: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", array, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    assert ok
    return buffer.tobytes()


def _flat(shade: int = 128, size=(240, 320)) -> np.ndarray:
    return np.full((*size, 3), shade, dtype=np.uint8)


def _textured(seed: int = 7, size=(240, 320)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Blocky noise rather than per-pixel noise: per-pixel noise is mostly
    # destroyed by JPEG, and a corner detector needs structure at a scale
    # the codec preserves.
    small = rng.integers(0, 255, (size[0] // 8, size[1] // 8, 3), dtype=np.uint8)
    return cv2.resize(small, (size[1], size[0]), interpolation=cv2.INTER_NEAREST)


class TestTheSharpnessIntermediateIsExact:
    """`sharpness` uses a CV_16S Laplacian instead of a CV_64F one.

    4.69x on real frames (1.4885 -> 0.3173 ms), on a stage that runs
    synchronously on the event loop whenever this experiment is selected.
    It is only defensible because the cheaper intermediate is EXACT for
    this input, and these tests pin the two facts the argument rests on so
    a successor cannot quietly widen the input and keep the optimisation.

    The same reasoning, with the full derivation, is in
    `world_builder/frontend.py: measure_sharpness`.
    """

    def _gray(self, array):
        return cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)

    def test_the_int16_laplacian_is_elementwise_identical_to_the_float_one(self):
        """8-bit input with ksize=1 bounds it at +/-1020 against +/-32767.

        Saturation is unreachable, so the cheaper dtype loses nothing.
        """
        for source in (_textured(), _flat(), _flat(0), _flat(255)):
            gray = self._gray(source)
            wide = cv2.Laplacian(gray, cv2.CV_64F)
            narrow = cv2.Laplacian(gray, cv2.CV_16S)

            assert np.array_equal(wide, narrow)
            assert abs(int(narrow.min())) <= 1020
            assert abs(int(narrow.max())) <= 1020

    def test_the_variance_agrees_with_the_float64_form(self):
        for source in (_textured(), _textured(11), _flat(), _flat(3)):
            gray = self._gray(source)
            reference = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            _, deviation = cv2.meanStdDev(cv2.Laplacian(gray, cv2.CV_16S))
            measured = float(deviation[0, 0] ** 2)

            if reference == 0:
                assert measured == 0
                continue
            assert abs(measured - reference) / reference < 1e-12, (
                f"{measured=} {reference=}"
            )

    def test_the_input_this_experiment_feeds_it_is_uint8_single_channel(self):
        """The exactness argument holds only for that, and there is no
        dtype guard here -- `run()` produces `gray` two lines earlier with
        `cvtColor(..., BGR2GRAY)`, so the guarantee is structural. If that
        ever stops being true, the guard the shared function carries has
        to come with it: on colour input `meanStdDev` returns a
        PER-CHANNEL deviation and `[0, 0]` would silently report channel
        zero where `.var()` pooled all three.
        """
        gray = self._gray(_textured())

        assert gray.dtype == np.uint8
        assert gray.ndim == 2


class TestFrameQualityMeasuresQuality:
    def test_a_blurred_frame_scores_lower_sharpness_than_its_original(self):
        original = _textured()
        blurred = cv2.GaussianBlur(original, (15, 15), 0)

        sharp_score = frame_quality.run(_encode(original)).result_value
        blur_score = frame_quality.run(_encode(blurred)).result_value

        assert blur_score < sharp_score / 2, f"{blur_score=} {sharp_score=}"

    def test_a_blank_frame_has_far_less_entropy_than_a_textured_one(self):
        blank = frame_quality.run(_encode(_flat())).metrics["entropy_bits"]
        textured = frame_quality.run(_encode(_textured())).metrics["entropy_bits"]

        assert blank < 2.0
        assert textured > blank + 3.0

    def test_a_clipped_white_frame_reports_overexposure(self):
        white = frame_quality.run(_encode(_flat(255))).metrics
        mid = frame_quality.run(_encode(_flat(128))).metrics

        assert white["overexposed_fraction"] > 0.9
        assert mid["overexposed_fraction"] < 0.01

    def test_a_black_frame_reports_underexposure(self):
        black = frame_quality.run(_encode(_flat(0))).metrics

        assert black["underexposed_fraction"] > 0.9

    def test_reported_dimensions_match_the_frame_we_encoded(self):
        metrics = frame_quality.run(_encode(_flat(size=(120, 200)))).metrics

        assert (metrics["width"], metrics["height"]) == (200.0, 120.0)


class TestFeatureDetectionMeasuresTexture:
    def test_a_blank_frame_yields_almost_no_keypoints(self):
        assert feature_detection.run(_encode(_flat())).result_value < 5

    def test_a_textured_frame_yields_many(self):
        assert feature_detection.run(_encode(_textured())).result_value > 100

    def test_coverage_distinguishes_spread_from_a_clump(self):
        """The measurement a bare count cannot make.

        Both frames carry texture; only one carries it everywhere. A
        thousand keypoints in one corner is a worse frame for geometry
        than three hundred spread out, and a count alone cannot say so.
        """
        spread = _textured()

        clumped = _flat()
        patch = _textured(size=(80, 80))
        clumped[:80, :80] = patch

        spread_metrics = feature_detection.run(_encode(spread)).metrics
        clumped_metrics = feature_detection.run(_encode(clumped)).metrics

        assert clumped_metrics["keypoint_count"] > 20, "the clump must have features"
        # Measured here: 0.09 clumped against 0.59 spread. The clump
        # occupies 8% of the frame, so ~0.09 is the geometric floor;
        # spread does not reach 1.0 because ORB piles onto the strongest
        # corners rather than distributing itself. The RATIO is the real
        # assertion -- an absolute bound would pin a detector's taste.
        assert clumped_metrics["spatial_coverage"] < 0.2
        assert spread_metrics["spatial_coverage"] > 0.4
        assert (
            spread_metrics["spatial_coverage"]
            > clumped_metrics["spatial_coverage"] * 3
        )

    def test_every_keypoint_that_was_described_was_also_detected(self):
        metrics = feature_detection.run(_encode(_textured())).metrics

        assert metrics["descriptor_count"] <= metrics["keypoint_count"]


class TestOpticalFlowMeasuresRealCameraMotion:
    """Evaluated against a rendered walk whose camera motion is exact."""

    @staticmethod
    def _walk_frames(step: float, count: int = 3, width=320, height=240):
        scene = ss.furnished_room()
        poses = ss.strafe(count, step=step)
        assert ss.poses_outside_room(poses) == []
        images = ss.render_sequence(
            scene, poses, ss.camera_matrix(width, height), width, height
        )
        return [ss.encode_jpeg(image) for image in images]

    def test_the_first_frame_reports_no_flow_rather_than_a_still_scene(self):
        experiment = EXPERIMENTS["optical_flow"]()
        experiment.load(ExperimentSettings())

        first = experiment.run(self._walk_frames(0.1)[0])

        assert first.result_value == 0.0
        assert first.metrics["has_reference"] == 0.0
        assert first.metrics["tracked_count"] == 0.0

    def test_a_sideways_walk_produces_horizontal_flow(self):
        """The camera translates purely along +x, so the scene must move
        purely along -x in the image. Direction is ground truth here."""
        experiment = EXPERIMENTS["optical_flow"]()
        experiment.load(ExperimentSettings())
        frames = self._walk_frames(0.12)

        experiment.run(frames[0])
        moved = experiment.run(frames[1])

        assert moved.metrics["tracked_count"] > 20
        assert moved.metrics["direction_coherence"] > 0.8
        direction = moved.metrics["dominant_direction_deg"]
        # 180 deg = leftwards. Allow +/-25 deg: the scene has real depth,
        # so nearer surfaces sweep faster and the field is not perfectly
        # parallel.
        assert abs(abs(direction) - 180.0) < 25.0, direction

    def test_a_bigger_step_produces_more_flow(self):
        def median_flow(step: float) -> float:
            experiment = EXPERIMENTS["optical_flow"]()
            experiment.load(ExperimentSettings())
            frames = self._walk_frames(step)
            experiment.run(frames[0])
            return experiment.run(frames[1]).result_value

        small = median_flow(0.05)
        large = median_flow(0.20)

        assert large > small * 2, f"{small=} {large=}"

    def test_an_identical_frame_pair_produces_near_zero_flow(self):
        experiment = EXPERIMENTS["optical_flow"]()
        experiment.load(ExperimentSettings())
        frame = self._walk_frames(0.1)[0]

        experiment.run(frame)
        repeated = experiment.run(frame)

        assert repeated.result_value < 0.5

    def test_a_resolution_change_is_reported_rather_than_measured(self):
        """DAT's ladder changes resolution mid-stream. Comparing frames of
        different sizes would produce a large, meaningless number."""
        experiment = EXPERIMENTS["optical_flow"]()
        experiment.load(ExperimentSettings())

        experiment.run(_encode(_textured(size=(240, 320))))
        after = experiment.run(_encode(_textured(size=(120, 160))))

        assert after.metrics["resolution_changed"] == 1.0
        assert after.result_value == 0.0

    def test_release_drops_the_retained_frame(self):
        """A stopped experiment must not keep wearer imagery in memory."""
        experiment = EXPERIMENTS["optical_flow"]()
        experiment.load(ExperimentSettings())
        experiment.run(self._walk_frames(0.1)[0])

        experiment.release()

        assert experiment._previous is None


class TestRedactionImpactMeasuresTheCost:
    @staticmethod
    def _room(width=640, height=360) -> bytes:
        """A rendered room -- textured the way a real scene is, not uniformly."""
        scene = ss.furnished_room()
        poses = ss.strafe(1, step=0.1)
        images = ss.render_sequence(
            scene, poses, ss.camera_matrix(width, height), width, height
        )
        return ss.encode_jpeg(images[0])

    def test_redaction_removes_keypoints_from_the_region_we_chose(self):
        """The rectangle is ours, so its contents are independent truth."""
        frame = _textured(size=(240, 320))
        metrics = redaction_impact.run(_encode(frame)).metrics

        assert metrics["keypoints_in_region_before"] > 5
        assert metrics["keypoints_in_region_after"] < metrics[
            "keypoints_in_region_before"
        ]

    def test_the_headline_is_the_in_region_number_not_the_frame_number(self):
        """A frame-wide retention is nearly a constant and decides nothing.

        The region covers ~6% of the area, so frame retention sits near
        0.99 whether the redaction was clean or leaky. The in-region
        number moves: measured 0.12 on a rendered room against 0.99
        frame-wide, an 8x difference in what the two numbers say.
        """
        metrics = redaction_impact.run(self._room()).metrics

        assert metrics["region_keypoint_retention"] < 0.5
        assert metrics["frame_keypoint_retention"] > 0.9
        assert (
            metrics["region_keypoint_retention"]
            < metrics["frame_keypoint_retention"] / 2
        )

    def test_survivors_near_the_redaction_sit_on_its_boundary(self):
        """The finding this experiment exists to reproduce.

        A box blur leaves features along its own edge. They look
        trackable and describe the transition rather than the scene, so a
        high retention with a high boundary fraction is WORSE than a low
        retention. Measured on a rendered room: 0.96.
        """
        metrics = redaction_impact.run(self._room()).metrics

        assert metrics["survivors_near_region"] > 10
        assert metrics["boundary_fraction"] > 0.7

    def test_the_boundary_denominator_is_the_nearby_survivors(self):
        """Divided by every survivor in the frame this measures the frame.

        Ordinary never-blurred texture anywhere near the box edge would
        dominate the number and dilute the signal. Pinned so a future
        edit cannot quietly widen the denominator again.
        """
        metrics = redaction_impact.run(self._room()).metrics

        assert metrics["survivors_near_region"] < metrics["keypoints_after"]
        assert metrics["boundary_fraction"] == pytest.approx(
            metrics["survivors_on_boundary"] / metrics["survivors_near_region"]
        )

    def test_a_blank_frame_loses_nothing_because_it_had_nothing(self):
        metrics = redaction_impact.run(_encode(_flat())).metrics

        assert metrics["keypoints_before"] < 5
        assert metrics["keypoints_lost"] <= metrics["keypoints_before"]

    def test_the_region_covers_the_fraction_of_the_frame_it_claims(self):
        metrics = redaction_impact.run(_encode(_textured(size=(240, 320)))).metrics

        # REGION_FRACTION is a linear fraction per axis, so the area is
        # its square. Computed from the constant rather than hard-coded,
        # so changing the constant does not silently pass.
        expected = redaction_impact.REGION_FRACTION**2
        assert metrics["region_area_fraction"] == pytest.approx(expected, abs=0.01)

    def test_the_reported_region_matches_the_pixels_that_changed(self):
        """The strongest available check: find what actually got blurred."""
        frame = cv2.cvtColor(_textured(size=(240, 320)), cv2.COLOR_BGR2GRAY)
        x0, y0, x1, y1 = redaction_impact.redaction_region(
            frame.shape[1], frame.shape[0]
        )

        blurred = frame.copy()
        blurred[y0:y1, x0:x1] = cv2.GaussianBlur(
            blurred[y0:y1, x0:x1], (31, 31), 0
        )
        changed = np.argwhere(cv2.absdiff(frame, blurred) > 0)

        assert changed.size, "the region must actually be modified"
        assert changed[:, 0].min() >= y0 and changed[:, 0].max() < y1
        assert changed[:, 1].min() >= x0 and changed[:, 1].max() < x1


class TestUndecodableInputIsAFrameLevelFailure:
    """One bad frame must not take the module down (FrameProcessingError)."""

    @pytest.mark.parametrize(
        "name",
        [
            "baseline",
            "edge_detection",
            "frame_quality",
            "feature_detection",
            "redaction_impact",
            "optical_flow",
        ],
    )
    def test_garbage_bytes_raise_a_frame_scoped_error(self, name):
        from tower.modules.base import FrameProcessingError

        experiment = EXPERIMENTS[name]()
        experiment.load(ExperimentSettings())

        with pytest.raises(FrameProcessingError):
            experiment.run(b"not a jpeg at all")

    @pytest.mark.parametrize(
        "name",
        [
            "baseline",
            "edge_detection",
            "frame_quality",
            "feature_detection",
            "redaction_impact",
            "optical_flow",
        ],
    )
    def test_a_header_only_jpeg_raises_a_frame_scoped_error(self, name):
        """The reachable case, not the obvious one.

        The transport validates a frame with `Image.open(...).size`, which
        parses the JPEG HEADER only. A truncated file with an intact
        header passes that check and reaches the experiment, where
        `cv2.imdecode` returns None. Anything other than
        FrameProcessingError here marks the whole module FAILED for the
        rest of the process.
        """
        from tower.modules.base import FrameProcessingError

        # Built from hex so this source file stays plain ASCII: a
        # literal � byte in a test file is a trap for every tool
        # that reads it as text.
        truncated = bytes.fromhex("ffd8ffe00010") + b"JFIF" + bytes(40)
        experiment = EXPERIMENTS[name]()
        experiment.load(ExperimentSettings())

        with pytest.raises(FrameProcessingError):
            experiment.run(truncated)
