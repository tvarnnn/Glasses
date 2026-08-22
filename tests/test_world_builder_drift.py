"""How trajectory error actually behaves along a chain.

SYNTHETIC, NOT PHYSICAL.

This file exists because a single drift percentage was misread. 21.6% at
16 keyframes was recorded as "unbounded drift"; the dominant cause was
that the walk producing it left the room at that exact keyframe. With the
walk kept inside the scene, error accumulates *smoothly* and no cliff
exists at 16 at all.

Bounds here are deliberately loose. `findEssentialMat(USAC_MAGSAC)` and
`solvePnPRansac(SQPNP)` are unseeded, and a committed test's own docstring
claims 1.32% where the same test measures 1.62% on this OpenCV build. A
tight bound would pin a build, not a behaviour. What is asserted is the
SHAPE of the error: bounded over a short chain, and larger over a long
one.
"""

import cv2
import numpy as np
import pytest

from tower.world_builder.backend import KeyframeInput
from tower.world_builder.backends.classical import ClassicalTwoViewBackend
from tower.world_builder.records import CameraIntrinsics
from tests import synthetic_scene as ss

WIDTH, HEIGHT = 480, 360


@pytest.fixture(scope="module")
def rig():
    camera_matrix = ss.camera_matrix(WIDTH, HEIGHT)
    intrinsics = CameraIntrinsics(
        source="self_calibrated",
        model="pinhole",
        fx=float(camera_matrix[0, 0]),
        fy=float(camera_matrix[1, 1]),
        cx=float(camera_matrix[0, 2]),
        cy=float(camera_matrix[1, 2]),
        calibrated_width=WIDTH,
        calibrated_height=HEIGHT,
    )
    return ss.furnished_room(), camera_matrix, intrinsics


def _in_room_walk(count: int):
    """A walk whose step shrinks so the whole chain stays inside the room."""
    usable_half_width = ss.ROOM_WIDTH_M / 2 - 0.5
    step = min(0.20, usable_half_width / max(count - 1, 1))
    poses = ss.strafe(count, step=step)
    assert ss.poses_outside_room(poses) == [], (
        "this test measures drift, not what happens when the camera walks "
        "into a wall -- the walk must stay inside the scene"
    )
    return poses


def _max_drift_fraction(rig, poses) -> float:
    scene, camera_matrix, intrinsics = rig
    images = ss.render_sequence(scene, poses, camera_matrix, WIDTH, HEIGHT)
    grays = [
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        for image in images
    ]
    backend = ClassicalTwoViewBackend()
    backend.prepare(intrinsics)
    estimate = backend.estimate_window(
        [KeyframeInput(f"k{index}", gray) for index, gray in enumerate(grays)]
    )

    centres, kept = [], []
    for index, pose in enumerate(estimate.poses):
        if pose.status == "anchor":
            centres.append(np.zeros(3))
            kept.append(index)
        elif pose.translation is not None:
            centres.append(-pose.rotation.T @ pose.translation)
            kept.append(index)

    assert len(kept) >= len(poses) - 1, "too many poses refused to measure drift"

    centres = np.asarray(centres)
    truth = np.asarray([poses[index].position for index in kept])
    scale, rotation, translation = ss.umeyama_similarity(centres, truth)
    aligned = (scale * (rotation @ centres.T).T) + translation

    residual = np.linalg.norm(aligned - truth, axis=1)
    full_truth = np.asarray([pose.position for pose in poses])
    path_length = float(np.linalg.norm(np.diff(full_truth, axis=0), axis=1).sum())
    return float(residual.max() / path_length)


class TestDriftShape:
    def test_a_short_in_room_chain_tracks_truth_closely(self, rig):
        """Eight keyframes: measured 0.83% here, bounded at 5%."""
        assert _max_drift_fraction(rig, _in_room_walk(8)) < 0.05

    def test_sixteen_keyframes_is_not_a_cliff(self, rig):
        """The whole point.

        This is the count that produced 21.6% and a diagnosis of
        "unbounded drift". Kept inside the room it measures ~1%, which
        means the earlier figure was mostly a fact about the scene.
        """
        assert _max_drift_fraction(rig, _in_room_walk(16)) < 0.05

    def test_a_long_chain_drifts_further_than_a_short_one(self, rig):
        """Accumulation is real, and this is the bundle-adjustment trigger.

        Asserted as a comparison rather than a threshold: the ratio
        survives an OpenCV upgrade, an absolute percentage does not.
        """
        short = _max_drift_fraction(rig, _in_room_walk(8))
        long = _max_drift_fraction(rig, _in_room_walk(24))

        assert long > short * 3, f"short={short:.4f} long={long:.4f}"


class TestInlierRatioIsNotADegeneracySignal:
    """A measured negative result, kept so the fix is not re-proposed.

    The obvious response to degrading geometry is to gate PnP on inlier
    ratio, mirroring the initial pair's gate. Measurement says that would
    be backwards: the walk that stays safely inside the room reports
    LOWER inlier ratios than the one heading into a wall, because a large
    healthy match set with plenty of far-field structure has proportionally
    more outliers than a shrinking one. A ratio floor would refuse the good
    configuration and admit the bad one.
    """

    def test_the_good_walk_does_not_report_a_higher_inlier_ratio(self, rig):
        scene, camera_matrix, intrinsics = rig

        def ratios(poses):
            images = ss.render_sequence(scene, poses, camera_matrix, WIDTH, HEIGHT)
            grays = [
                cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
                for image in images
            ]
            backend = ClassicalTwoViewBackend()
            backend.prepare(intrinsics)
            estimate = backend.estimate_window(
                [KeyframeInput(f"k{i}", gray) for i, gray in enumerate(grays)]
            )
            return [
                pose.inlier_ratio
                for pose in estimate.poses
                if pose.inlier_ratio is not None
            ]

        interior = ratios(ss.strafe(16, step=0.09))
        toward_the_wall = ratios(ss.strafe(16, step=0.20))

        assert float(np.median(interior[4:])) < float(
            np.median(toward_the_wall[4:])
        ), (
            "if the interior walk ever reports the higher ratio, an "
            "inlier-ratio gate becomes worth reconsidering"
        )
