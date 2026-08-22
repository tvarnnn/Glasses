"""Two-view geometry primitives, and the degeneracy criterion.

Separated from the backends so the criterion is testable on its own and so
both backends measure identically -- the uncalibrated one still reports
what it can, it just cannot turn those measurements into a pose.

The thresholds here were measured on synthetic scenes with exact ground
truth (tests/synthetic_scene.py). They are documented starting points, not
tuned constants, and the measurements that produced them are recorded in
tests/test_world_builder_geometry.py so a successor can see why these
numbers and not others.
"""

import cv2
import numpy as np

# Minimum median triangulation angle for translation to be trustworthy.
#
# This is the textbook conditioning criterion -- the angle each 3-D point
# subtends between the two viewing rays -- and it is used here in
# preference to pixel displacement, which is actively misleading: a pure
# rotation produces LARGE pixel motion (measured 18.4 px) with zero
# baseline, so a displacement-based gate passes exactly the case it exists
# to catch.
#
# Measured separation on synthetic ground truth: pairs whose recovered
# translation direction was wrong by 62-106 degrees had median
# triangulation angles of 0.11-0.42 deg, while every pair that recovered
# direction to within ~1 deg measured 0.54 deg or more.
MIN_TRIANGULATION_ANGLE_DEG = 0.5

# Secondary guard. An essential-matrix fit that retains almost no
# correspondences has not found a consistent geometry, whatever angle the
# few survivors happen to subtend. Measured: degenerate pairs kept
# 0.1-2.5% of matches, usable pairs kept 7.7-95.8%.
MIN_INLIER_RATIO = 0.05

# Below this there is not enough evidence to fit anything at all.
MIN_INLIERS = 15

ORB_FEATURES = 1500
LOWE_RATIO = 0.75
RANSAC_THRESHOLD_PX = 1.0
RANSAC_CONFIDENCE = 0.999


def detect_and_describe(gray: np.ndarray, nfeatures: int = ORB_FEATURES):
    orb = cv2.ORB_create(nfeatures=nfeatures)
    return orb.detectAndCompute(gray, None)


def match_descriptors(
    keypoints_a, descriptors_a, keypoints_b, descriptors_b, ratio: float = LOWE_RATIO
) -> tuple[np.ndarray, np.ndarray]:
    """Lowe ratio-test correspondences.

    Ratio test rather than crossCheck: on repetitive indoor texture
    crossCheck was measured to collapse the essential-matrix inlier ratio
    to 0.256 where the ratio test reached 0.941 on the same pair. Same
    0.75 threshold scripts/feature_trackability.py already uses.
    """
    empty = (np.empty((0, 2), np.float32), np.empty((0, 2), np.float32))
    if descriptors_a is None or descriptors_b is None:
        return empty
    if len(descriptors_a) < 2 or len(descriptors_b) < 2:
        return empty

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    good = [
        pair[0]
        for pair in matcher.knnMatch(descriptors_a, descriptors_b, k=2)
        if len(pair) == 2 and pair[0].distance < ratio * pair[1].distance
    ]
    if not good:
        return empty
    points_a = np.float32([keypoints_a[m.queryIdx].pt for m in good]).reshape(-1, 2)
    points_b = np.float32([keypoints_b[m.trainIdx].pt for m in good]).reshape(-1, 2)
    return points_a, points_b


def homography_ratio(points_a: np.ndarray, points_b: np.ndarray) -> float | None:
    """ORB-SLAM's r_H = H_inliers / (H_inliers + F_inliers).

    Recorded for continuity with V0.9.3, which measured it, and NOT used
    as a gate. Measured on synthetic indoor scenes it saturates at
    0.471-0.499 across the full range from total degeneracy to healthy
    parallax, so the conventional 0.45 threshold classifies every pair as
    rotation-dominant and separates nothing.

    That is not a defect in r_H; it is r_H answering its actual question.
    A homography suffices whenever the scene is EITHER purely rotating OR
    dominated by a plane -- and a room is nothing but planes. In a
    plane-dominated environment r_H cannot isolate rotation, which is
    precisely the thing we need isolated.
    """
    if len(points_a) < 8:
        return None
    _, h_mask = cv2.findHomography(points_a, points_b, cv2.RANSAC, 3.0)
    _, f_mask = cv2.findFundamentalMat(
        points_a, points_b, cv2.FM_RANSAC, 3.0, 0.99
    )
    h_inliers = int(h_mask.sum()) if h_mask is not None else 0
    f_inliers = int(f_mask.sum()) if f_mask is not None else 0
    total = h_inliers + f_inliers
    if total == 0:
        return None
    return h_inliers / total


def median_triangulation_angle_deg(
    points_a: np.ndarray,
    points_b: np.ndarray,
    rotation: np.ndarray,
    translation: np.ndarray,
    camera_matrix: np.ndarray,
) -> float | None:
    """Median angle subtended at each triangulated point by the two rays.

    Small angle means the two views are nearly the same viewpoint, so
    depth is poorly constrained no matter how many correspondences agree.
    """
    if len(points_a) < 2:
        return None
    projection_a = camera_matrix @ np.hstack([np.eye(3), np.zeros((3, 1))])
    projection_b = camera_matrix @ np.hstack(
        [rotation, translation.reshape(3, 1)]
    )
    homogeneous = cv2.triangulatePoints(
        projection_a, projection_b, points_a.T, points_b.T
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        xyz = (homogeneous[:3] / homogeneous[3]).T
    finite = np.isfinite(xyz).all(axis=1)
    xyz = xyz[finite]
    if len(xyz) < 2:
        return None

    centre_b = (-rotation.T @ translation.reshape(3)).ravel()
    ray_a = xyz
    ray_b = xyz - centre_b
    norm_a = np.linalg.norm(ray_a, axis=1, keepdims=True)
    norm_b = np.linalg.norm(ray_b, axis=1, keepdims=True)
    usable = (norm_a[:, 0] > 1e-9) & (norm_b[:, 0] > 1e-9)
    if usable.sum() < 2:
        return None
    cosines = ((ray_a[usable] / norm_a[usable]) * (ray_b[usable] / norm_b[usable])).sum(
        axis=1
    )
    angles = np.degrees(np.arccos(np.clip(cosines, -1.0, 1.0)))
    return float(np.median(angles))


def motion_direction(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    """Camera motion direction in the FIRST camera's frame.

    cv2.recoverPose returns [R|t] mapping points from camera 1 into camera
    2, so `t` is camera 1's position in camera 2's frame -- not the
    direction the camera travelled. The motion, in camera 1's frame, is
    -R.T @ t.

    Isolated in one function because getting it wrong is silent: an early
    probe reported a 179 deg translation error that was entirely this
    conversion, while the underlying geometry was already correct to
    0.075 deg.
    """
    direction = -rotation.T @ np.asarray(translation, dtype=np.float64).reshape(3)
    norm = np.linalg.norm(direction)
    return direction / norm if norm > 1e-12 else direction


def triangulate_points(
    points_a: np.ndarray,
    points_b: np.ndarray,
    rotation: np.ndarray,
    translation: np.ndarray,
    camera_matrix: np.ndarray,
) -> np.ndarray:
    """Triangulate into the FIRST camera's frame, dropping bad points.

    Points behind either camera, or non-finite, are removed rather than
    returned with a flag: a point the geometry says is behind the camera
    is not a low-confidence point, it is not a point.
    """
    projection_a = camera_matrix @ np.hstack([np.eye(3), np.zeros((3, 1))])
    projection_b = camera_matrix @ np.hstack([rotation, translation.reshape(3, 1)])
    homogeneous = cv2.triangulatePoints(
        projection_a, projection_b, points_a.T, points_b.T
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        xyz = (homogeneous[:3] / homogeneous[3]).T

    in_front_a = xyz[:, 2] > 0
    xyz_b = (rotation @ xyz.T).T + translation.reshape(3)
    in_front_b = xyz_b[:, 2] > 0
    keep = np.isfinite(xyz).all(axis=1) & in_front_a & in_front_b
    return xyz[keep]
