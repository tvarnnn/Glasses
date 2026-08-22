"""Calibrated incremental structure-from-motion, degeneracy refused.

Runs today, on CPU, with no dependency beyond the OpenCV the Tower
already requires. It needs intrinsics and says so: prepare() raises rather
than substituting a plausible focal length, because a wrong focal length
does not produce slightly-wrong geometry, it produces a confidently wrong
trajectory.

For a two-frame window this is essential matrix + recoverPose. For longer
windows it chains properly: triangulate from the initial pair, then solve
each subsequent camera by PnP against the accumulated landmarks. Chaining
matters -- returning per-pair relative poses for a long window would give
a set of poses that are each individually correct and collectively
meaningless, because two-view translations are unit-length and carry no
common scale.

Scale is arbitrary by construction. The initial pair's baseline is
declared to be one unit, and everything after is consistent with that
choice. That is "relative", not metric, and nothing here pretends
otherwise.
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
    match_indices,
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

# Minimum 3-D/2-D correspondences before PnP is attempted. Six is the
# theoretical minimum for DLT; requiring more keeps RANSAC meaningful.
MIN_PNP_CORRESPONDENCES = 12
PNP_REPROJECTION_ERROR_PX = 3.0

CAPABILITIES = BackendCapabilities(
    backend_id="classical-sfm",
    version="2",
    requires_intrinsics=True,
    estimates_intrinsics=False,
    produces_dense_geometry=False,
    produces_metric_scale=False,
    preferred_window=8,
    device="cpu",
)


class ClassicalTwoViewBackend(GeometryBackend):
    """Incremental SfM over a window. Name kept for interface stability."""

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

        features = [detect_and_describe(frame.image_gray) for frame in window]
        poses: list[PoseEstimate] = [
            PoseEstimate(keyframe_id=window[0].keyframe_id, status=POSE_STATUS_ANCHOR)
        ]
        if len(window) == 1:
            return GeometryEstimate(poses=tuple(poses))

        # -- initialise from the first pair -----------------------------
        pair = self._estimate_pair(features[0], features[1], window[1].keyframe_id)
        poses.append(pair.estimate)
        if pair.estimate.status != POSE_STATUS_SOLVED:
            # Cannot start a chain. Everything after is unavailable rather
            # than silently measured against an anchor that never resolved.
            poses.extend(
                PoseEstimate(
                    keyframe_id=frame.keyframe_id,
                    status=POSE_STATUS_UNAVAILABLE,
                    degeneracy=pair.estimate.degeneracy,
                )
                for frame in window[2:]
            )
            return GeometryEstimate(poses=tuple(poses))

        # World frame == first keyframe's camera frame.
        absolute = {
            0: (np.eye(3), np.zeros(3)),
            1: (pair.estimate.rotation, pair.estimate.translation),
        }
        landmarks = list(pair.points)
        # (frame index, feature index) -> landmark index, so a later frame
        # can find 3-D correspondences for the features it matched.
        observed: dict[tuple[int, int], int] = {}
        for offset, (index_a, index_b) in enumerate(pair.inlier_index_pairs):
            observed[(0, index_a)] = offset
            observed[(1, index_b)] = offset

        # -- extend by PnP ----------------------------------------------
        for current in range(2, len(window)):
            previous = current - 1
            estimate, new_points, new_observed, reobserved = self._extend(
                features[previous],
                features[current],
                previous,
                current,
                absolute,
                landmarks,
                observed,
                window[current].keyframe_id,
            )
            poses.append(estimate)
            if estimate.status != POSE_STATUS_SOLVED:
                # Stop chaining. Remaining frames are honestly unavailable;
                # the engine turns this into a new segment.
                poses.extend(
                    PoseEstimate(
                        keyframe_id=frame.keyframe_id,
                        status=POSE_STATUS_UNAVAILABLE,
                        degeneracy=estimate.degeneracy,
                    )
                    for frame in window[current + 1 :]
                )
                break
            absolute[current] = (estimate.rotation, estimate.translation)
            observed.update(reobserved)
            base = len(landmarks)
            landmarks.extend(new_points)
            for key, offset in new_observed.items():
                observed[key] = base + offset

        block = (
            PointBlock(xyz=np.asarray(landmarks, dtype=np.float32))
            if landmarks
            else None
        )
        return GeometryEstimate(poses=tuple(poses), points=block)

    # -- helpers --------------------------------------------------------

    class _PairResult:
        __slots__ = ("estimate", "points", "inlier_index_pairs")

        def __init__(self, estimate, points, inlier_index_pairs):
            self.estimate = estimate
            self.points = points
            self.inlier_index_pairs = inlier_index_pairs

    def _estimate_pair(self, features_a, features_b, keyframe_id):
        keypoints_a, descriptors_a = features_a
        keypoints_b, descriptors_b = features_b
        index_pairs = match_indices(descriptors_a, descriptors_b)
        matches = len(index_pairs)

        def refuse(degeneracy, **extra):
            return self._PairResult(
                PoseEstimate(
                    keyframe_id=keyframe_id,
                    status=POSE_STATUS_UNAVAILABLE,
                    degeneracy=degeneracy,
                    matches=matches,
                    **extra,
                ),
                [],
                [],
            )

        if matches < MIN_INLIERS:
            return refuse(DEGENERACY_NO_CORRESPONDENCE)

        points_a = np.float32([keypoints_a[i].pt for i, _ in index_pairs])
        points_b = np.float32([keypoints_b[j].pt for _, j in index_pairs])

        camera_matrix = self._camera_matrix
        essential, mask = cv2.findEssentialMat(
            points_a, points_b, camera_matrix,
            method=cv2.USAC_MAGSAC,
            prob=RANSAC_CONFIDENCE,
            threshold=RANSAC_THRESHOLD_PX,
        )
        if essential is None or essential.shape != (3, 3):
            return refuse(DEGENERACY_NO_CORRESPONDENCE)

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
        angle = median_triangulation_angle_deg(
            inlier_a, inlier_b, rotation, translation, camera_matrix
        )
        measured = {
            "matches": matches,
            "inliers": inliers,
            "inlier_ratio": inlier_ratio,
            "median_triangulation_deg": angle,
            "median_displacement_px": displacement,
            "cheirality_fraction": cheirality / inliers if inliers else None,
            "r_h": homography_ratio(points_a, points_b),
        }

        # Rotation survives degeneracy; translation does not. Under a pure
        # rotation recoverPose still returns a confident translation whose
        # direction is meaningless -- measured 62 and 106 degrees of error
        # on pairs that reported no other complaint.
        degenerate = (
            inliers < MIN_INLIERS
            or inlier_ratio < MIN_INLIER_RATIO
            or angle is None
            or angle < MIN_TRIANGULATION_ANGLE_DEG
        )
        if degenerate:
            reason = (
                DEGENERACY_PURE_ROTATION
                if inlier_ratio < MIN_INLIER_RATIO
                else DEGENERACY_LOW_PARALLAX
            )
            return self._PairResult(
                PoseEstimate(
                    keyframe_id=keyframe_id,
                    status=POSE_STATUS_ROTATION_ONLY,
                    rotation=rotation,
                    translation=None,
                    degeneracy=reason,
                    **measured,
                ),
                [],
                [],
            )

        points, keep_mask = triangulate_points(
            inlier_a, inlier_b, rotation, translation, camera_matrix,
            return_mask=True,
        )
        surviving_pairs = [
            pair for pair, keep in zip(
                [p for p, k in zip(index_pairs, kept) if k], keep_mask
            ) if keep
        ]
        return self._PairResult(
            PoseEstimate(
                keyframe_id=keyframe_id,
                status=POSE_STATUS_SOLVED,
                rotation=rotation,
                translation=translation,
                degeneracy=DEGENERACY_NONE,
                **measured,
            ),
            list(points),
            surviving_pairs,
        )

    def _extend(
        self,
        features_previous,
        features_current,
        previous_index,
        current_index,
        absolute,
        landmarks,
        observed,
        keyframe_id,
    ):
        keypoints_previous, descriptors_previous = features_previous
        keypoints_current, descriptors_current = features_current
        index_pairs = match_indices(descriptors_previous, descriptors_current)
        matches = len(index_pairs)

        object_points, image_points, matched_pairs = [], [], []
        # A feature in the current frame can be named by more than one
        # match (knnMatch guarantees one entry per queryIdx, not per
        # trainIdx), so the last writer would otherwise win and silently
        # bind a landmark to the wrong feature. Keep the first claim.
        claimed: set[int] = set()
        reobserved: dict[tuple[int, int], int] = {}
        for index_previous, index_current in index_pairs:
            if index_current in claimed:
                continue
            claimed.add(index_current)
            landmark = observed.get((previous_index, index_previous))
            if landmark is None:
                matched_pairs.append((index_previous, index_current))
                continue
            object_points.append(landmarks[landmark])
            image_points.append(keypoints_current[index_current].pt)
            # THE propagation. Without this the map is write-only: a
            # landmark seen in frame N-1 and re-seen in frame N cannot be
            # found from frame N, so step N->N+1 re-triangulates the same
            # physical structure instead of reusing it, roughly doubling
            # the point count with duplicates of the same structure and
            # badly degrading the trajectory.
            #
            # Deliberately no percentage here. The figures this comment
            # used to carry were single-run measurements, and
            # findEssentialMat(USAC_MAGSAC)/solvePnPRansac(SQPNP) are not
            # seeded -- a committed test's own docstring claims 1.32%
            # where the same test now measures 1.62% on a different
            # OpenCV build. Point at the report, which can carry the
            # conditions; a bare number in a comment cannot.
            # See reports/2026-08-22-world-builder-closeout.md 5.2.
            reobserved[(current_index, index_current)] = landmark

        if len(object_points) < MIN_PNP_CORRESPONDENCES:
            return (
                PoseEstimate(
                    keyframe_id=keyframe_id,
                    status=POSE_STATUS_UNAVAILABLE,
                    degeneracy=DEGENERACY_NO_CORRESPONDENCE,
                    matches=matches,
                ),
                [],
                {},
                {},
            )

        ok, rotation_vector, translation, inlier_indices = cv2.solvePnPRansac(
            np.asarray(object_points, dtype=np.float64),
            np.asarray(image_points, dtype=np.float64),
            self._camera_matrix,
            None,
            reprojectionError=PNP_REPROJECTION_ERROR_PX,
            confidence=RANSAC_CONFIDENCE,
            flags=cv2.SOLVEPNP_SQPNP,
        )
        if not ok or inlier_indices is None or len(inlier_indices) < MIN_PNP_CORRESPONDENCES:
            return (
                PoseEstimate(
                    keyframe_id=keyframe_id,
                    status=POSE_STATUS_UNAVAILABLE,
                    degeneracy=DEGENERACY_LOW_PARALLAX,
                    matches=matches,
                    inliers=0 if inlier_indices is None else int(len(inlier_indices)),
                ),
                [],
                {},
                {},
            )

        rotation, _ = cv2.Rodrigues(rotation_vector)
        translation = np.asarray(translation, dtype=np.float64).reshape(3)

        # Triangulate the features that had no landmark yet, using the two
        # absolute poses, so new structure lands directly in world frame.
        new_points, new_observed = self._triangulate_new(
            keypoints_previous,
            keypoints_current,
            matched_pairs,
            absolute[previous_index],
            (rotation, translation),
            previous_index,
            current_index,
        )

        # Re-observations index into the EXISTING landmark list, so they
        # must not be shifted by the caller's `base` offset the way newly
        # triangulated points are. Returned separately for that reason.
        return (
            PoseEstimate(
                keyframe_id=keyframe_id,
                status=POSE_STATUS_SOLVED,
                rotation=rotation,
                translation=translation,
                degeneracy=DEGENERACY_NONE,
                matches=matches,
                inliers=int(len(inlier_indices)),
                inlier_ratio=len(inlier_indices) / matches if matches else None,
            ),
            new_points,
            new_observed,
            reobserved,
        )

    def _triangulate_new(
        self,
        keypoints_previous,
        keypoints_current,
        matched_pairs,
        pose_previous,
        pose_current,
        previous_index,
        current_index,
    ):
        if not matched_pairs:
            return [], {}

        rotation_p, translation_p = pose_previous
        rotation_c, translation_c = pose_current
        projection_p = self._camera_matrix @ np.hstack(
            [rotation_p, translation_p.reshape(3, 1)]
        )
        projection_c = self._camera_matrix @ np.hstack(
            [rotation_c, translation_c.reshape(3, 1)]
        )

        points_p = np.float32([keypoints_previous[i].pt for i, _ in matched_pairs]).T
        points_c = np.float32([keypoints_current[j].pt for _, j in matched_pairs]).T
        homogeneous = cv2.triangulatePoints(
            projection_p, projection_c, points_p, points_c
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            xyz = (homogeneous[:3] / homogeneous[3]).T

        new_points, new_observed = [], {}
        for offset, ((index_p, index_c), point) in enumerate(
            zip(matched_pairs, xyz)
        ):
            if not np.isfinite(point).all():
                continue
            depth_p = (rotation_p @ point + translation_p)[2]
            depth_c = (rotation_c @ point + translation_c)[2]
            if depth_p <= 0 or depth_c <= 0:
                continue
            landmark = len(new_points)
            new_points.append(point)
            new_observed[(previous_index, index_p)] = landmark
            new_observed[(current_index, index_c)] = landmark
        return new_points, new_observed
