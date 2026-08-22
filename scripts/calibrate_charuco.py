#!/usr/bin/env python
"""Recover camera intrinsics from ChArUco board views.

This is the switch that moves World Builder from "no poses, and it says
so" to "poses". Nothing else in the system changes what the product is by
as much.

ChArUco rather than a plain checkerboard because the wearer cannot see the
frame: ChArUco identifies each corner individually, so a partially visible
or partly occluded board still contributes, where a plain checkerboard
needs the whole grid.

    # print this, mount it flat and rigid
    .venv\\Scripts\\python.exe scripts/calibrate_charuco.py --generate-board board.png

    # then calibrate from frames captured THROUGH THE REAL PIPELINE
    .venv\\Scripts\\python.exe scripts/calibrate_charuco.py \\
        --frames data/world_builder/captures/<id>/frames --out intrinsics.json

WHAT THIS HAS AND HAS NOT BEEN VALIDATED AGAINST
------------------------------------------------
The code path is unit-tested against synthetically rendered board views
and recovers a known focal length to within ~0.3%. That validates the
wiring -- which genuinely matters, because `calibrateCameraCharuco` does
NOT exist in OpenCV 5 and the working sequence is CharucoDetector ->
matchImagePoints -> calibrateCamera.

It has NOT been validated against:

- any real lens. The synthetic input is a perfect pinhole with zero
  distortion, so the distortion-model choice -- the parameter most likely
  to be wrong on a ~100-degree wearable lens -- is completely unexercised.
- real JPEG compression, motion blur, rolling shutter, or auto-exposure.
- DAT's adaptive resolution ladder, which switches mid-stream.

Even noise-free, the principal point came back ~2.5 px off truth. It is
the weakly-constrained parameter before any real-world effect is added.
Treat a first real calibration as provisional and check its reprojection
RMS and view count before trusting it.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.world_builder.records import CameraIntrinsics  # noqa: E402
from tower.world_builder.schema import (  # noqa: E402
    INTRINSICS_SOURCE_SELF_CALIBRATED,
)

# Board geometry. Square/marker lengths are in metres and must match the
# printed board, because they set the scale of everything downstream.
SQUARES_X = 7
SQUARES_Y = 5
SQUARE_LENGTH_M = 0.040
MARKER_LENGTH_M = 0.030
DICTIONARY = cv2.aruco.DICT_4X4_50

# Refuse below this many usable views rather than emitting a shaky
# calibration. A calibration nobody can tell is bad is worse than none:
# every downstream pose inherits its error and nothing reports it.
MIN_VIEWS = 8
# Corners per view below which the view carries too little constraint.
MIN_CORNERS_PER_VIEW = 8


def make_board():
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARY)
    return cv2.aruco.CharucoBoard(
        (SQUARES_X, SQUARES_Y), SQUARE_LENGTH_M, MARKER_LENGTH_M, dictionary
    )


def generate_board_image(path: Path, pixels_per_square: int = 120) -> None:
    board = make_board()
    size = (SQUARES_X * pixels_per_square, SQUARES_Y * pixels_per_square)
    cv2.imwrite(str(path), board.generateImage(size))


def detect_views(images, board):
    """Detect ChArUco corners in each image.

    Returns (object_points, image_points, size, per_view_corner_counts).
    """
    detector = cv2.aruco.CharucoDetector(board)
    object_points, image_points, corner_counts = [], [], []
    size = None

    for image in images:
        gray = (
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        )
        size = (gray.shape[1], gray.shape[0])
        corners, ids, _, _ = detector.detectBoard(gray)
        if corners is None or ids is None or len(ids) < MIN_CORNERS_PER_VIEW:
            corner_counts.append(0 if ids is None else int(len(ids)))
            continue
        object_view, image_view = board.matchImagePoints(corners, ids)
        if object_view is None or len(object_view) < MIN_CORNERS_PER_VIEW:
            corner_counts.append(0)
            continue
        object_points.append(object_view)
        image_points.append(image_view)
        corner_counts.append(int(len(object_view)))

    return object_points, image_points, size, corner_counts


def calibrate(images) -> CameraIntrinsics:
    """Solve intrinsics, or raise if the evidence is too thin.

    Raises ValueError rather than returning a low-confidence result: an
    under-constrained calibration is silently wrong everywhere it is
    later used, and there is no downstream check that would catch it.
    """
    board = make_board()
    object_points, image_points, size, corner_counts = detect_views(images, board)

    if len(object_points) < MIN_VIEWS:
        raise ValueError(
            f"only {len(object_points)} usable views of the board "
            f"(need {MIN_VIEWS}); per-view corner counts {corner_counts}. "
            "Refusing to emit intrinsics from insufficient evidence."
        )

    rms, camera_matrix, dist_coeffs, _, _ = cv2.calibrateCamera(
        object_points, image_points, size, None, None
    )
    return CameraIntrinsics(
        source=INTRINSICS_SOURCE_SELF_CALIBRATED,
        model="pinhole_radtan",
        fx=float(camera_matrix[0, 0]),
        fy=float(camera_matrix[1, 1]),
        cx=float(camera_matrix[0, 2]),
        cy=float(camera_matrix[1, 2]),
        dist_coeffs=tuple(float(v) for v in np.asarray(dist_coeffs).ravel()),
        calibrated_width=size[0],
        calibrated_height=size[1],
        reprojection_rms_px=float(rms),
        view_count=len(object_points),
        calibrated_at=time.time(),
        # Left None deliberately. Whether DAT resizes or crops between its
        # three resolutions has never been established, and asserting
        # linearity would let intrinsics be silently rescaled by a wrong
        # factor. Establish it by calibrating at two resolutions.
        scales_linearly_across_resolutions=None,
    )


def load_images(directory: Path):
    paths = sorted(directory.glob("*.jpg")) + sorted(directory.glob("*.png"))
    if not paths:
        raise SystemExit(f"no .jpg/.png frames found under {directory}")
    return [cv2.imread(str(path)) for path in paths]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Recover camera intrinsics from ChArUco board views."
    )
    parser.add_argument(
        "--generate-board",
        type=Path,
        help="Write a printable board image and exit.",
    )
    parser.add_argument("--frames", type=Path, help="Directory of board views.")
    parser.add_argument("--out", type=Path, help="Write intrinsics JSON here.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    if args.generate_board:
        generate_board_image(args.generate_board)
        print(f"board written to {args.generate_board}")
        print(
            f"squares {SQUARES_X}x{SQUARES_Y}  square {SQUARE_LENGTH_M} m  "
            f"marker {MARKER_LENGTH_M} m"
        )
        print(
            "Print at a known scale, mount flat and rigid, and MEASURE the "
            "printed square size -- the metres above must match reality."
        )
        return 0

    if not args.frames:
        parser.error("--frames is required unless --generate-board is given")

    try:
        intrinsics = calibrate(load_images(args.frames))
    except ValueError as exc:
        print(f"calibration refused: {exc}", file=sys.stderr)
        return 1

    payload = intrinsics.to_json_dict()
    if args.out:
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(f"source            {intrinsics.source}")
        print(f"resolution        {intrinsics.calibrated_width}x{intrinsics.calibrated_height}")
        print(f"fx, fy            {intrinsics.fx:.2f}, {intrinsics.fy:.2f}")
        print(f"cx, cy            {intrinsics.cx:.2f}, {intrinsics.cy:.2f}")
        print(f"reprojection RMS  {intrinsics.reprojection_rms_px:.4f} px")
        print(f"views used        {intrinsics.view_count}")
        print(
            "\nscales_linearly_across_resolutions is null: calibrate again at "
            "another DAT resolution to establish it. Until then intrinsics "
            "will refuse to rescale."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
