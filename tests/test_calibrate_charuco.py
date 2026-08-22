"""ChArUco calibration: round-trip against a known focal length, and refusal.

SYNTHETIC, NOT PHYSICAL. Board views are warps of a rendered board image
through a perfect pinhole with zero distortion. That exercises the code
path -- which matters, because `calibrateCameraCharuco` does not exist in
OpenCV 5 -- but it says nothing about a real lens, and in particular
leaves the distortion model completely unexercised.
"""

import subprocess
import sys

import cv2
import numpy as np
import pytest

from scripts.calibrate_charuco import (
    MIN_VIEWS,
    calibrate,
    generate_board_image,
    make_board,
)
from tower.world_builder.schema import INTRINSICS_SOURCE_SELF_CALIBRATED

WIDTH, HEIGHT = 360, 640
TRUE_FX = TRUE_FY = 300.0
TRUE_CX, TRUE_CY = WIDTH / 2 - 1.0, HEIGHT / 2 - 1.0


def _camera_matrix():
    return np.array(
        [[TRUE_FX, 0.0, TRUE_CX], [0.0, TRUE_FY, TRUE_CY], [0.0, 0.0, 1.0]]
    )


def _render_board_views(count: int, seed: int = 11):
    """Warp a board image through known random poses.

    Simpler than a scene renderer and sufficient: the board is planar, so
    its image under any pose is exactly a homography of the board image.
    """
    board = make_board()
    board_pixels = board.generateImage((700, 500))
    squares_x, squares_y = 7, 5
    square = 0.040
    width_m, height_m = squares_x * square, squares_y * square

    # Board corners in 3-D, centred on the origin at z = 0.
    object_corners = np.array(
        [
            [-width_m / 2, -height_m / 2, 0.0],
            [width_m / 2, -height_m / 2, 0.0],
            [width_m / 2, height_m / 2, 0.0],
            [-width_m / 2, height_m / 2, 0.0],
        ]
    )
    source_corners = np.float32(
        [
            [0, 0],
            [board_pixels.shape[1] - 1, 0],
            [board_pixels.shape[1] - 1, board_pixels.shape[0] - 1],
            [0, board_pixels.shape[0] - 1],
        ]
    )

    rng = np.random.default_rng(seed)
    camera_matrix = _camera_matrix()
    views = []
    for _ in range(count):
        angles = rng.uniform(-0.45, 0.45, size=3)
        rotation, _ = cv2.Rodrigues(angles)
        translation = np.array(
            [
                rng.uniform(-0.05, 0.05),
                rng.uniform(-0.05, 0.05),
                rng.uniform(0.35, 0.60),
            ]
        )
        projected = (rotation @ object_corners.T).T + translation
        image_corners = (projected @ camera_matrix.T)
        image_corners = np.float32(
            image_corners[:, :2] / image_corners[:, 2:3]
        )
        homography = cv2.getPerspectiveTransform(source_corners, image_corners)
        views.append(
            cv2.warpPerspective(
                board_pixels,
                homography,
                (WIDTH, HEIGHT),
                borderValue=(255, 255, 255),
            )
        )
    return views


@pytest.fixture(scope="module")
def board_views():
    return _render_board_views(40)


class TestCalibrationRoundTrip:
    def test_a_known_focal_length_is_recovered(self, board_views):
        intrinsics = calibrate(board_views)

        assert intrinsics.fx == pytest.approx(TRUE_FX, rel=0.03)
        assert intrinsics.fy == pytest.approx(TRUE_FY, rel=0.03)

    def test_the_principal_point_is_recovered_less_tightly(self, board_views):
        """Recorded rather than hidden.

        Even on noise-free synthetic input the principal point lands a
        couple of pixels off. It is the weakly-constrained parameter
        before any real-world effect is added, and a tight bound here
        would be a fiction that fails on real footage.
        """
        intrinsics = calibrate(board_views)

        assert intrinsics.cx == pytest.approx(TRUE_CX, abs=12.0)
        assert intrinsics.cy == pytest.approx(TRUE_CY, abs=12.0)

    def test_the_result_records_its_own_provenance(self, board_views):
        intrinsics = calibrate(board_views)

        assert intrinsics.source == INTRINSICS_SOURCE_SELF_CALIBRATED
        assert intrinsics.is_known
        assert intrinsics.calibrated_width == WIDTH
        assert intrinsics.calibrated_height == HEIGHT
        assert intrinsics.view_count >= MIN_VIEWS
        assert intrinsics.reprojection_rms_px < 2.0

    def test_resolution_linearity_is_left_unestablished(self, board_views):
        """Asserting linearity would let intrinsics be rescaled wrongly.

        Whether DAT resizes or crops between its three resolutions has
        never been established, and the adaptive ladder switches
        mid-stream.
        """
        intrinsics = calibrate(board_views)

        assert intrinsics.scales_linearly_across_resolutions is None
        with pytest.raises(ValueError, match="scales_linearly"):
            intrinsics.scaled_to(720, 1280)

    def test_calibrated_intrinsics_unlock_the_classical_backend(
        self, board_views
    ):
        """The whole point: this is the switch from no-poses to poses."""
        from tower.world_builder.backends import (
            BACKEND_AUTO,
            ClassicalTwoViewBackend,
            select_backend,
        )

        selection = select_backend(BACKEND_AUTO, calibrate(board_views))

        assert isinstance(selection.backend, ClassicalTwoViewBackend)


class TestCalibrationRefuses:
    def test_too_few_views_refuses_rather_than_emitting_intrinsics(self):
        """An under-constrained calibration is silently wrong everywhere."""
        with pytest.raises(ValueError, match="usable views"):
            calibrate(_render_board_views(3))

    def test_blank_frames_refuse(self):
        blank = [np.full((HEIGHT, WIDTH), 255, np.uint8) for _ in range(20)]

        with pytest.raises(ValueError, match="usable views"):
            calibrate(blank)


class TestBoardGeneration:
    def test_a_printable_board_is_written(self, tmp_path):
        path = tmp_path / "board.png"

        generate_board_image(path)

        assert path.exists()
        assert cv2.imread(str(path)) is not None


class TestCli:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/calibrate_charuco.py", *args],
            capture_output=True,
            text=True,
        )

    def test_help_exits_zero(self):
        assert self._run("--help").returncode == 0

    def test_missing_frames_is_refused(self):
        result = self._run()

        assert result.returncode != 0
        assert "--frames" in result.stderr

    def test_generate_board_writes_a_file(self, tmp_path):
        path = tmp_path / "board.png"

        result = self._run("--generate-board", str(path))

        assert result.returncode == 0
        assert path.exists()
        assert "MEASURE" in result.stdout

    def test_an_empty_frame_directory_exits_nonzero(self, tmp_path):
        result = self._run("--frames", str(tmp_path))

        assert result.returncode != 0
