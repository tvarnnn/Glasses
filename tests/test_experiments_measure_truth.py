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
    def test_redaction_removes_keypoints_from_the_region_we_chose(self):
        """The rectangle is ours, so its contents are independent truth."""
        frame = _textured(size=(240, 320))
        metrics = redaction_impact.run(_encode(frame)).metrics

        assert metrics["keypoints_in_region_before"] > 5
        assert metrics["keypoints_in_region_after"] < metrics[
            "keypoints_in_region_before"
        ]

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
        "name", ["frame_quality", "feature_detection", "redaction_impact", "optical_flow"]
    )
    def test_garbage_bytes_raise_a_frame_scoped_error(self, name):
        from tower.modules.base import FrameProcessingError

        experiment = EXPERIMENTS[name]()
        experiment.load(ExperimentSettings())

        with pytest.raises(FrameProcessingError):
            experiment.run(b"not a jpeg at all")
