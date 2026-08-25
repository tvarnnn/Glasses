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


class TestCalibrationRefusesDegenerateViewpoints:
    """View COUNT is not evidence, and reprojection RMS is not either.

    Measured before this guard existed: ten byte-identical views recovered
    fx with 287% error, ten fronto-parallel views with 3787% error, and
    BOTH scored a better reprojection RMS than a correct calibration --
    because RMS measures fit to the views supplied, and degenerate views
    are trivially easy to fit. The module docstring told the operator to
    check RMS; on this failure mode RMS endorses the wrong answer.
    """

    def _posed_views(self, count, rotation_scale, z_jitter, xy_jitter, seed=3):
        board = make_board()
        board_image = board.generateImage((700, 500))
        source = np.float32(
            [[0, 0], [699, 0], [699, 499], [0, 499]]
        )
        camera_matrix = _camera_matrix()
        corners = np.array(
            [
                [-0.14, -0.10, 0.0],
                [0.14, -0.10, 0.0],
                [0.14, 0.10, 0.0],
                [-0.14, 0.10, 0.0],
            ]
        )
        rng = np.random.default_rng(seed)
        views = []
        for _ in range(count):
            rotation, _ = cv2.Rodrigues(
                rng.uniform(-rotation_scale, rotation_scale, 3)
            )
            translation = np.array(
                [
                    rng.uniform(-xy_jitter, xy_jitter),
                    rng.uniform(-xy_jitter, xy_jitter),
                    0.6 + rng.uniform(-z_jitter, z_jitter),
                ]
            )
            projected = (rotation @ corners.T).T + translation
            uv = projected @ camera_matrix.T
            uv = np.float32(uv[:, :2] / uv[:, 2:3])
            homography = cv2.getPerspectiveTransform(source, uv)
            views.append(
                cv2.warpPerspective(
                    board_image,
                    homography,
                    (WIDTH, HEIGHT),
                    borderValue=(255, 255, 255),
                )
            )
        return views

    def test_identical_views_are_refused_however_many_there_are(self):
        views = self._posed_views(1, 0.4, 0.0, 0.0) * 10

        with pytest.raises(ValueError, match="distinct viewpoints"):
            calibrate(views)

    def test_fronto_parallel_views_are_refused(self):
        """A board held square to the sensor cannot pin down focal length.

        Perspective foreshortening is what separates focal length from
        distance; without tilt the views are nearly affine and fx is
        almost unidentifiable no matter how many are collected.
        """
        views = self._posed_views(10, 0.0, 0.0, 0.06)

        with pytest.raises(ValueError, match="perspective"):
            calibrate(views)

    def test_varied_poses_still_calibrate_accurately(self):
        """The guard must not reject a genuinely good capture."""
        views = self._posed_views(12, 0.45, 0.12, 0.06)

        result = calibrate(views)

        assert result.fx == pytest.approx(TRUE_FX, rel=0.02)


class TestIntrinsicsMustBePhysical:
    """is_known gates the calibrated backend, so it must mean something.

    A bare presence check let fx=0, fx=-500 and fx=NaN through to a
    backend that then produced a confident reconstruction from an
    impossible camera.
    """

    @pytest.mark.parametrize("focal", [0.0, -500.0, float("nan")])
    def test_non_physical_focal_lengths_are_not_known(self, focal):
        from tower.world_builder.records import CameraIntrinsics

        intrinsics = CameraIntrinsics(
            source=INTRINSICS_SOURCE_SELF_CALIBRATED,
            fx=focal,
            fy=300.0,
            cx=180.0,
            cy=320.0,
        )

        assert not intrinsics.is_known
        assert intrinsics.camera_matrix() is None

    def test_a_principal_point_outside_the_image_is_still_valid(self):
        """It can legitimately sit off-frame on a cropped sensor."""
        from tower.world_builder.records import CameraIntrinsics

        intrinsics = CameraIntrinsics(
            source=INTRINSICS_SOURCE_SELF_CALIBRATED,
            fx=300.0,
            fy=300.0,
            cx=-40.0,
            cy=900.0,
        )

        assert intrinsics.is_known


class TestTheResultLandsWhereTheBuilderLooks:
    """The loop between calibrating and building, closed.

    Before this, `--out` had no default and `--intrinsics` had no
    discovery, so the one working path required an operator to remember a
    flag at both ends. Forgetting either produced a silently pose-free
    world -- which is what 2026-08-24 produced.
    """

    @pytest.fixture
    def board_frames_dir(self, tmp_path, board_views):
        directory = tmp_path / "board"
        directory.mkdir()
        for index, view in enumerate(board_views[:16]):
            cv2.imwrite(str(directory / f"{index:04d}.jpg"), view)
        return directory

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/calibrate_charuco.py", *args],
            capture_output=True,
            text=True,
        )

    def test_a_calibration_lands_in_the_store_with_no_out_flag(
        self, board_frames_dir, tmp_path
    ):
        root = tmp_path / "world_root"

        result = self._run(
            "--frames", str(board_frames_dir), "--root", str(root)
        )

        assert result.returncode == 0, result.stderr
        assert (root / "intrinsics" / f"{WIDTH}x{HEIGHT}.json").exists()

    def test_the_stored_file_is_what_the_store_reads_back(
        self, board_frames_dir, tmp_path
    ):
        from tower.world_builder.intrinsics_store import IntrinsicsStore

        root = tmp_path / "world_root"
        self._run("--frames", str(board_frames_dir), "--root", str(root))

        found = IntrinsicsStore(root).lookup(WIDTH, HEIGHT)

        assert found.is_known
        assert found.fx == pytest.approx(TRUE_FX, rel=0.03)

    def test_the_stored_calibration_selects_the_classical_backend(
        self, board_frames_dir, tmp_path
    ):
        from tower.world_builder.backends import (
            BACKEND_AUTO,
            ClassicalTwoViewBackend,
            select_backend,
        )
        from tower.world_builder.intrinsics_store import IntrinsicsStore

        root = tmp_path / "world_root"
        self._run("--frames", str(board_frames_dir), "--root", str(root))

        selection = select_backend(
            BACKEND_AUTO, IntrinsicsStore(root).lookup(WIDTH, HEIGHT)
        )

        assert isinstance(selection.backend, ClassicalTwoViewBackend)

    def test_success_output_names_the_resolution_it_is_valid_for(
        self, board_frames_dir, tmp_path
    ):
        result = self._run(
            "--frames",
            str(board_frames_dir),
            "--root",
            str(tmp_path / "world_root"),
        )

        assert f"VALID ONLY FOR {WIDTH}x{HEIGHT}" in result.stdout
        assert "NEXT:" in result.stdout
        assert "world_build_session.py" in result.stdout

    def test_success_output_warns_that_a_low_rms_is_not_proof(
        self, board_frames_dir, tmp_path
    ):
        """RMS endorses the degenerate answer; the operator must be told."""
        result = self._run(
            "--frames",
            str(board_frames_dir),
            "--root",
            str(tmp_path / "world_root"),
        )

        assert "LOW RMS IS NOT PROOF" in result.stdout
        assert "docs/CALIBRATION.md" in result.stdout

    def test_an_explicit_out_still_wins_and_says_it_is_undiscoverable(
        self, board_frames_dir, tmp_path
    ):
        root = tmp_path / "world_root"
        out = tmp_path / "elsewhere" / "intrinsics.json"

        result = self._run(
            "--frames",
            str(board_frames_dir),
            "--root",
            str(root),
            "--out",
            str(out),
        )

        assert result.returncode == 0, result.stderr
        assert out.exists()
        assert not (root / "intrinsics").exists()
        assert "OUTSIDE the store" in result.stdout

    def test_a_refused_calibration_writes_nothing_into_the_store(self, tmp_path):
        """Refusal must not leave a half-answer where the builder looks."""
        directory = tmp_path / "blank"
        directory.mkdir()
        for index in range(12):
            cv2.imwrite(
                str(directory / f"{index:04d}.jpg"),
                np.full((HEIGHT, WIDTH), 255, np.uint8),
            )
        root = tmp_path / "world_root"

        result = self._run("--frames", str(directory), "--root", str(root))

        assert result.returncode != 0
        assert "calibration refused" in result.stderr
        assert not (root / "intrinsics").exists()


class TestSplitHalfDiagnostic:
    """The quality check reprojection RMS cannot be.

    RMS says the solver fitted the views it was given. Agreement between
    two disjoint halves says those views actually CONSTRAIN the camera --
    the thing that view count and RMS both miss.
    """

    def test_well_varied_views_agree_between_halves(self, board_views):
        from scripts.calibrate_charuco import split_half_report

        first, second, spread = split_half_report(board_views[:24])

        assert spread < 0.05
        assert first.fx == pytest.approx(TRUE_FX, rel=0.05)
        assert second.fx == pytest.approx(TRUE_FX, rel=0.05)

    def test_the_diagnostic_writes_nothing(self, tmp_path, board_views):
        directory = tmp_path / "board"
        directory.mkdir()
        for index, view in enumerate(board_views[:24]):
            cv2.imwrite(str(directory / f"{index:04d}.jpg"), view)
        root = tmp_path / "world_root"

        result = subprocess.run(
            [
                sys.executable,
                "scripts/calibrate_charuco.py",
                "--frames",
                str(directory),
                "--root",
                str(root),
                "--split-half",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "fx disagreement between halves" in result.stdout
        assert "Nothing was written" in result.stdout
        assert not (root / "intrinsics").exists()

    def test_a_half_that_cannot_be_calibrated_reports_that(self, tmp_path):
        directory = tmp_path / "blank"
        directory.mkdir()
        for index in range(24):
            cv2.imwrite(
                str(directory / f"{index:04d}.jpg"),
                np.full((HEIGHT, WIDTH), 255, np.uint8),
            )

        result = subprocess.run(
            [
                sys.executable,
                "scripts/calibrate_charuco.py",
                "--frames",
                str(directory),
                "--split-half",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "split-half refused" in result.stderr
