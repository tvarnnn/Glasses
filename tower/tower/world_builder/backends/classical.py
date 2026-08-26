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
    Extension,
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

# Rows of PointBlock.support_views: [frame index, feature index, landmark
# index]. int32, not int64: ORB is capped at a few thousand features per
# frame and a segment holds tens of thousands of landmarks, so every
# column is bounded three orders of magnitude below the type, and this is
# the one piece of solve state that is never pruned -- half the width is
# half the resident cost for the whole walk.
SUPPORT_DTYPE = np.int32


def _support_block(rows) -> np.ndarray:
    """(m, 3) int32 from an iterable of (frame, feature, landmark)."""
    flat = np.fromiter(
        (value for row in rows for value in row), dtype=SUPPORT_DTYPE
    )
    return flat.reshape(-1, 3)


def _support_table(blocks: list) -> np.ndarray:
    """A solve's per-keyframe blocks concatenated, in creation order."""
    if not blocks:
        return np.zeros((0, 3), dtype=SUPPORT_DTYPE)
    return np.concatenate(blocks, axis=0)


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
        self._chain: _Chain | None = None

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
        self._chain = None

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
        # The same association, accumulated rather than derived. `observed`
        # is a LOOKUP -- one landmark per (frame, feature) key, last writer
        # wins -- and the live path prunes it (see _Chain.forget_before), so
        # neither its contents nor its lifetime can stand in for the record
        # of what was triangulated. Rows are appended where landmarks are
        # created, in both this method and extend(), and nowhere else.
        support: list[np.ndarray] = []
        seed: list[tuple[int, int, int]] = []
        for offset, (index_a, index_b) in enumerate(pair.inlier_index_pairs):
            observed[(0, index_a)] = offset
            observed[(1, index_b)] = offset
            # Emitted regardless of whether the dict write above collided:
            # match_indices guarantees one entry per query index, not per
            # train index, so two of frame 0's features can name the same
            # feature of frame 1. Both statements are true about the solve,
            # and dropping one would leave a landmark with a single view --
            # which is not a thing that can be triangulated.
            seed.append((0, index_a, offset))
            seed.append((1, index_b, offset))
        support.append(_support_block(seed))

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
            support.append(
                _support_block(
                    (frame, feature, landmark)
                    for (frame, feature), landmark in reobserved.items()
                )
            )
            base = len(landmarks)
            landmarks.extend(new_points)
            for key, offset in new_observed.items():
                observed[key] = base + offset
            support.append(
                _support_block(
                    (frame, feature, base + offset)
                    for (frame, feature), offset in new_observed.items()
                )
            )

        block = (
            PointBlock(
                xyz=np.asarray(landmarks, dtype=np.float32),
                support_views=_support_table(support),
            )
            if landmarks
            else None
        )
        return GeometryEstimate(poses=tuple(poses), points=block)

    # -- the incremental seam -------------------------------------------
    #
    # estimate_window() above is already strictly forward-only: frame i is
    # solved by _extend() against features[i-1] and the accumulated
    # landmarks, and never looks forward. There is no bundle adjustment
    # and no loop closure -- BA was implemented and measured at 0.00%
    # drift improvement at 16, 32 and 104 keyframes, because the
    # observation graph is a chain whose median covisibility span is 1
    # (docs/agent-handoffs/WORLD-BUILDER.md section 10).
    #
    # So `absolute`, `landmarks` and `observed` really are the entire
    # carried state, and the only reason a rebuild re-paid for all of it
    # was that they were local variables. _Chain is those three promoted
    # to instance state, and nothing else.
    #
    # The methods below reuse the SAME _estimate_pair and _extend helpers
    # estimate_window uses, so the two paths cannot drift in their
    # geometry. What they deliberately do NOT share is the orchestration:
    # an oracle that delegates to the thing it is checking checks
    # nothing, and tests/test_world_builder_incremental.py checks this
    # one bit-for-bit.

    def begin(self, intrinsics: CameraIntrinsics) -> None:
        self.prepare(intrinsics)
        self.reset()

    def reset(self) -> None:
        self._chain = _Chain()

    def extend(self, frame: KeyframeInput) -> Extension:
        if self._camera_matrix is None:
            raise RuntimeError("begin() must be called before extend()")
        if self._chain is None:
            self._chain = _Chain()
        chain = self._chain
        index = chain.count

        if chain.broken is not None:
            # estimate_window() stops chaining at the first refusal and
            # marks every later frame unavailable carrying THAT frame's
            # degeneracy. Latched here for the same reason and with the
            # same value. It skips detection too: estimate_window
            # computes those descriptors up front and then never reads
            # them, so not computing them changes no output.
            pose = PoseEstimate(
                keyframe_id=frame.keyframe_id,
                status=POSE_STATUS_UNAVAILABLE,
                degeneracy=chain.broken,
            )
            chain.poses.append(pose)
            chain.count += 1
            return Extension(pose=pose)

        features = detect_and_describe(frame.image_gray)
        new_points: list = []
        # Rows for THIS keyframe's delta block, landmark indices local to
        # it. The chain's own copy carries the same rows shifted into the
        # accumulated map.
        delta_support: list[tuple[int, int, int]] = []

        if index == 0:
            pose = PoseEstimate(
                keyframe_id=frame.keyframe_id, status=POSE_STATUS_ANCHOR
            )
            # World frame == first keyframe's camera frame.
            chain.absolute[0] = (np.eye(3), np.zeros(3))
        elif index == 1:
            pair = self._estimate_pair(
                chain.previous_features, features, frame.keyframe_id
            )
            pose = pair.estimate
            if pose.status != POSE_STATUS_SOLVED:
                chain.broken = pose.degeneracy
            else:
                chain.absolute[1] = (pose.rotation, pose.translation)
                chain.landmarks.extend(pair.points)
                new_points = pair.points
                for offset, (index_a, index_b) in enumerate(
                    pair.inlier_index_pairs
                ):
                    chain.observed[(0, index_a)] = offset
                    chain.observed[(1, index_b)] = offset
                    delta_support.append((0, index_a, offset))
                    delta_support.append((1, index_b, offset))
                # The seed block IS the whole map so far, so delta-local
                # and map-relative indices coincide here and only here.
                chain.support.append(_support_block(delta_support))
        else:
            pose, triangulated, new_observed, reobserved = self._extend(
                chain.previous_features,
                features,
                index - 1,
                index,
                chain.absolute,
                chain.landmarks,
                chain.observed,
                frame.keyframe_id,
            )
            if pose.status != POSE_STATUS_SOLVED:
                chain.broken = pose.degeneracy
            else:
                chain.absolute[index] = (pose.rotation, pose.translation)
                chain.observed.update(reobserved)
                chain.support.append(
                    _support_block(
                        (frame, feature, landmark)
                        for (frame, feature), landmark in reobserved.items()
                    )
                )
                base = len(chain.landmarks)
                chain.landmarks.extend(triangulated)
                new_points = triangulated
                for key, offset in new_observed.items():
                    chain.observed[key] = base + offset
                    delta_support.append((key[0], key[1], offset))
                chain.support.append(
                    _support_block(
                        (frame, feature, base + landmark)
                        for frame, feature, landmark in delta_support
                    )
                )
                # A re-observation names a landmark this delta does not
                # carry, so it is not expressible in the delta's own index
                # space. It reaches a consumer through snapshot(), which is
                # the authoritative view anyway.

        chain.poses.append(pose)
        chain.count += 1
        chain.previous_features = features
        if chain.broken is None:
            chain.forget_before(index)
        return Extension(
            pose=pose,
            new_points=(
                PointBlock(
                    xyz=np.asarray(new_points, dtype=np.float32),
                    support_views=_support_block(delta_support),
                )
                if new_points
                else None
            ),
        )

    def snapshot(self) -> GeometryEstimate:
        chain = self._chain
        if chain is None or chain.count == 0:
            return GeometryEstimate(poses=())
        block = (
            PointBlock(
                xyz=np.asarray(chain.landmarks, dtype=np.float32),
                support_views=_support_table(chain.support),
            )
            if chain.landmarks
            else None
        )
        return GeometryEstimate(poses=tuple(chain.poses), points=block)

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

        # recoverPose takes `mask` as BOTH input and output: it narrows it
        # in place with a cheirality test bounded by an undocumented
        # `distanceThresh` default of 50 baselines. Reading `mask` after
        # the call therefore does NOT give the epipolar inlier count, and
        # the field persisted as `inlier_ratio` was measuring cheirality.
        # Measured, one scene, ORB matches at 640x360:
        #
        #   baseline   matches   epipolar inliers   ratio AFTER recoverPose
        #     0.02 m      1160     1134  (0.978)              0.001
        #     0.04 m      1145     1103  (0.963)              0.004
        #     0.06 m      1154     1120  (0.971)              0.098
        #     0.08 m      1137     1116  (0.982)              0.941
        #     0.30 m       987      958  (0.971)              0.971
        #
        # At short baselines nearly every correspondence is a genuine
        # epipolar inlier and the reported "inlier ratio" is three orders
        # of magnitude smaller. It was a measurement of baseline over
        # depth wearing another field's name -- which also explains two
        # historical results recorded as facts about geometry.
        epipolar_mask = mask.copy()
        cheirality, rotation, translation, _ = cv2.recoverPose(
            essential, points_a, points_b, camera_matrix, mask=mask
        )
        epipolar_kept = epipolar_mask.ravel() > 0
        epipolar_inliers = int(epipolar_kept.sum())
        inlier_ratio = epipolar_inliers / matches if matches else 0.0

        kept = mask.ravel() > 0
        inliers = int(kept.sum())
        # What the gate below has always actually used, now carried in the
        # field that was already declared for it. `KeyframeEdge`'s own
        # comment describes `cheirality_fraction` as "the fraction of
        # correspondences passing recoverPose's cheirality check" -- which
        # is exactly this, and which the code was instead putting into
        # `inlier_ratio` while filling this field with something else.
        cheirality_ratio = inliers / matches if matches else 0.0
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
            "inliers": epipolar_inliers,
            "inlier_ratio": inlier_ratio,
            "median_triangulation_deg": angle,
            "median_displacement_px": displacement,
            "cheirality_fraction": cheirality_ratio,
            "r_h": homography_ratio(points_a, points_b),
        }

        # Rotation survives degeneracy; translation does not. Under a pure
        # rotation recoverPose still returns a confident translation whose
        # direction is meaningless -- measured 62 and 106 degrees of error
        # on pairs that reported no other complaint.
        # Gated on the CHEIRALITY ratio, which is what this condition has
        # always used -- the constant is simply named for the wrong thing.
        # Deliberately unchanged: correcting the reporting is a separate
        # act from changing which poses are accepted, and the second needs
        # a sweep this did not have. Note the consequence, measured: a real
        # sideways strafe at a 4-6 cm baseline recovers direction to within
        # 2 degrees and is still refused here.
        degenerate = (
            inliers < MIN_INLIERS
            or cheirality_ratio < MIN_INLIER_RATIO
            or angle is None
            or angle < MIN_TRIANGULATION_ANGLE_DEG
        )
        if degenerate:
            # "pure_rotation" overstates what was observed: a low
            # cheirality ratio means few points are in front of both
            # cameras within 50 baselines, which a genuine short-baseline
            # translation also produces. Kept for now because the label is
            # persisted and consumers switch on it.
            reason = (
                DEGENERACY_PURE_ROTATION
                if cheirality_ratio < MIN_INLIER_RATIO
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


class _Chain:
    """The carried state of one forward-only solve, and nothing else.

    Exactly the four locals estimate_window() builds -- `absolute`,
    `landmarks`, `observed`, `support` -- plus the poses emitted so far
    and the latch recording where the chain stopped. If anything else
    ever has to live here, this backend has stopped being forward-only,
    and the equivalence test is the thing that will say so.
    """

    __slots__ = (
        "absolute",
        "broken",
        "count",
        "landmarks",
        "observed",
        "poses",
        "previous_features",
        "support",
    )

    def __init__(self) -> None:
        self.count = 0
        self.previous_features = None
        self.absolute: dict[int, tuple] = {}
        self.landmarks: list = []
        # (frame index, feature index) -> landmark index. PRUNED.
        self.observed: dict[tuple[int, int], int] = {}
        # The support table, one (m, 3) int32 block per keyframe that
        # added something, concatenated by snapshot(). NOT pruned, and it
        # is the only thing here that is not: `observed` can be dropped
        # because nothing will ever look up an old frame again, whereas
        # this IS the output. A list of small arrays rather than one
        # grown array so appending stays O(m) with no reallocation, and
        # rather than a list of tuples so the cost is 12 bytes a row
        # instead of the ~200 a dict entry cost before the prune.
        self.support: list = []
        self.poses: list[PoseEstimate] = []
        # Degeneracy of the first frame that refused, or None.
        self.broken: str | None = None

    def forget_before(self, index: int) -> None:
        """Drop observations no later step can reach.

        _extend() reads exactly one key shape, `observed[(previous, f)]`,
        so once frame `index` is solved nothing will ever look up a frame
        older than it. estimate_window() keeps them all because it is
        over in one call. A live solve is not over, and unpruned this
        dict grows by roughly two entries per ORB match per keyframe.

        `support` is deliberately NOT pruned here. It holds the same
        association and is the reason this backend records anything at
        all about 2-D/3-D linkage, so pruning it would silently give the
        live path one frame's worth of a field the rebuild path fills
        completely. It is affordable precisely because it is not this
        dict: 12 bytes a row against ~200 bytes an entry, so the 26.1 MB
        below is ~1.3 MB, and the 142.9 MB is ~8 MB.

        Measured, 480x360 synthetic walk, retained `observed` unpruned
        against pruned: 26.1 MB vs 0.15 MB at 155 keyframes, 142.9 MB vs
        0.15 MB at 1000. Pruned it is flat, because what survives is one
        frame's features. It changes no output -- which is a claim the
        equivalence test exists to check, not one it is asked to
        tolerate.
        """
        self.observed = {
            key: value for key, value in self.observed.items() if key[0] == index
        }
