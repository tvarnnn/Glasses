"""Calibrated two-view geometry, with degeneracy refused rather than fudged.

Runs today, on CPU, with no dependency beyond the OpenCV already required
by the Tower. It needs intrinsics and says so: prepare() raises rather
than substituting a plausible focal length, because a wrong focal length
does not produce slightly-wrong geometry, it produces a confidently wrong
trajectory.

Scale is arbitrary by construction. recoverPose returns a unit
translation, so the reconstruction is internally consistent with a unit
fixed by whatever the first solved baseline happened to be. That is
"relative", not metric, and nothing here pretends otherwise.
"""

from collections.abc import Sequence

import cv2
import numpy as np

from tower.world_builder.backend import (
    BackendCapabilities,
    GeometryBackend,
    GeometryEstimate,
    KeyframeInput,
    PointBlock,
    PoseEstimate,
)
from tower.world_builder.geometry import (
    MIN_INLIER_RATIO,
    MIN_INLIERS,
    MIN_TRIANGULATION_ANGLE_DEG,
    RANSAC_CONFIDENCE,
    RANSAC_THRESHOLD_PX,
    detect_and_describe,
    homography_ratio,
    match_descriptors,
    median_triangulation_angle_deg,
    triangulate_points,
)
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.schema import (
    DEGENERACY_LOW_PARALLAX,
    DEGENERACY_NO_CORRESPONDENCE,
    DEGENERACY_NONE,
    DEGENERACY_PURE_ROTATION,
    POSE_STATUS_ANCHOR,
    POSE_STATUS_ROTATION_ONLY,
    POSE_STATUS_SOLVED,
    POSE_STATUS_UNAVAILABLE,
)

CAPABILITIES = BackendCapabilities(
    backend_id="classical-two-view",
    version="1",
    requires_intrinsics=True,
    estimates_intrinsics=False,
    produces_dense_geometry=False,
    produces_metric_scale=False,
    preferred_window=2,
    device="cpu",
)


class ClassicalTwoViewBackend(GeometryBackend):
    capabilities = CAPABILITIES

    def __init__(self) -> None:
        self._camera_matrix: np.ndarray | None = None

    def prepare(self, intrinsics: CameraIntrinsics) -> None:
        camera_matrix = intrinsics.camera_matrix()
        if camera_matrix is None:
            raise ValueError(
                "ClassicalTwoViewBackend requires known intrinsics; got "
                f"source={intrinsics.source!r}. Refusing to substitute a "
                "guessed focal length -- a wrong one yields a plausible and "
                "entirely wrong trajectory."
            )
        self._camera_matrix = camera_matrix

    def release(self) -> None:
        self._camera_matrix = None

    def estimate_window(
        self, window: Sequence[KeyframeInput]
    ) -> GeometryEstimate:
        if self._camera_matrix is None:
            raise RuntimeError("prepare() must be called before estimate_window()")
        if not window:
            return GeometryEstimate(poses=())

        poses = [
            PoseEstimate(keyframe_id=window[0].keyframe_id, status=POSE_STATUS_ANCHOR)
        ]
        all_points: list[np.ndarray] = []

        previous = window[0]
        previous_features = detect_and_describe(previous.image_gray)

        for current in window[1:]:
            current_features = detect_and_describe(current.image_gray)
            estimate, points = self._estimate_pair(
                previous_features, current_features, current.keyframe_id
            )
            poses.append(estimate)
            if points is not None and len(points):
                all_points.append(points)
            previous, previous_features = current, current_features

        block = (
            PointBlock(xyz=np.concatenate(all_points).astype(np.float32))
            if all_points
            else None
        )
        return GeometryEstimate(poses=tuple(poses), points=block)

    def _estimate_pair(self, features_a, features_b, keyframe_id):
        points_a, points_b = match_descriptors(*features_a, *features_b)
        matches = len(points_a)

        if matches < MIN_INLIERS:
            return (
                PoseEstimate(
                    keyframe_id=keyframe_id,
                    status=POSE_STATUS_UNAVAILABLE,
                    degeneracy=DEGENERACY_NO_CORRESPONDENCE,
                    matches=matches,
                ),
                None,
            )

        camera_matrix = self._camera_matrix
        essential, mask = cv2.findEssentialMat(
            points_a,
            points_b,
            camera_matrix,
            method=cv2.USAC_MAGSAC,
            prob=RANSAC_CONFIDENCE,
            threshold=RANSAC_THRESHOLD_PX,
        )
        if essential is None or essential.shape != (3, 3):
            return (
                PoseEstimate(
                    keyframe_id=keyframe_id,
                    status=POSE_STATUS_UNAVAILABLE,
                    degeneracy=DEGENERACY_NO_CORRESPONDENCE,
                    matches=matches,
                ),
                None,
            )

        cheirality, rotation, translation, _ = cv2.recoverPose(
            essential, points_a, points_b, camera_matrix, mask=mask
        )
        kept = mask.ravel() > 0
        inliers = int(kept.sum())
        inlier_ratio = inliers / matches if matches else 0.0
        translation = np.asarray(translation, dtype=np.float64).reshape(3)

        inlier_a, inlier_b = points_a[kept], points_b[kept]
        displacement = (
            float(np.median(np.linalg.norm(inlier_a - inlier_b, axis=1)))
            if inliers
            else None
        )
        triangulation_angle = median_triangulation_angle_deg(
            inlier_a, inlier_b, rotation, translation, camera_matrix
        )
        measured = {
            "matches": matches,
            "inliers": inliers,
            "inlier_ratio": inlier_ratio,
            "median_triangulation_deg": triangulation_angle,
            "median_displacement_px": displacement,
            "cheirality_fraction": (
                cheirality / inliers if inliers else None
            ),
            "r_h": homography_ratio(points_a, points_b),
        }

        # Rotation survives degeneracy; translation does not. Under a pure
        # rotation recoverPose still returns a confident translation, and
        # its direction is meaningless -- measured errors of 62 and 106
        # degrees on pairs it reported no other complaint about. So the
        # rotation is kept and the translation is withheld.
        if inliers < MIN_INLIERS or inlier_ratio < MIN_INLIER_RATIO:
            return (
                PoseEstimate(
                    keyframe_id=keyframe_id,
                    status=POSE_STATUS_ROTATION_ONLY,
                    rotation=rotation,
                    translation=None,
                    degeneracy=DEGENERACY_PURE_ROTATION,
                    **measured,
                ),
                None,
            )

        if (
            triangulation_angle is None
            or triangulation_angle < MIN_TRIANGULATION_ANGLE_DEG
        ):
            return (
                PoseEstimate(
                    keyframe_id=keyframe_id,
                    status=POSE_STATUS_ROTATION_ONLY,
                    rotation=rotation,
                    translation=None,
                    degeneracy=DEGENERACY_LOW_PARALLAX,
                    **measured,
                ),
                None,
            )

        points = triangulate_points(
            inlier_a, inlier_b, rotation, translation, camera_matrix
        )
        return (
            PoseEstimate(
                keyframe_id=keyframe_id,
                status=POSE_STATUS_SOLVED,
                rotation=rotation,
                translation=translation,
                degeneracy=DEGENERACY_NONE,
                **measured,
            ),
            points,
        )
