"""Point-quality gates on triangulated landmarks.

The pipeline declares MIN_TRIANGULATION_ANGLE_DEG = 0.5 as its standard for
real geometry (geometry.py), then applies it once to the MEDIAN angle of the
seed pair and not at all to chain extension. Landmarks violating it by orders
of magnitude survive: measured up to 33,363 baselines out on real captures,
which is what destroys the bounding box the phone renders against.

Task 1 of the plan pins today's behaviour. Task 3 inverts the
characterisation test deliberately -- it is not deleted, it is flipped.
"""

import numpy as np

from tower.world_builder.geometry import triangulate_points

# The real self-calibrated 360x640 intrinsics: fx 438.23, fy 437.78,
# cx 174.88, cy 323.38, reprojection RMS 0.2893 px over 511 views.
CAMERA = np.array(
    [
        [438.23, 0.0, 174.88],
        [0.0, 437.78, 323.38],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)

IDENTITY_POSE = (np.eye(3), np.zeros(3))


def _project(world, pose, camera=CAMERA):
    """Pixel coordinates of world points under a world->camera pose."""
    rotation, translation = pose
    cam = (rotation @ np.asarray(world, dtype=np.float64).T).T + np.asarray(
        translation, dtype=np.float64
    ).reshape(3)
    uv = (camera @ cam.T).T
    return (uv[:, :2] / uv[:, 2:3]).astype(np.float64)


def _near_parallel_pair():
    """A tiny baseline viewing a very distant point.

    Baseline 0.001 units, point at depth 1000, so the inter-ray angle is
    ~0.00006 deg -- four orders of magnitude below the declared 0.5 deg
    bar. The two rays are parallel to within numerical noise and their
    intersection is arbitrary. This is not distant geometry; it is an
    unconstrained ray, and it is exactly what the gate must reject.
    """
    rotation = np.eye(3)
    translation = np.array([-0.001, 0.0, 0.0])
    world = np.array([[0.0, 0.0, 1000.0]])
    pa = _project(world, IDENTITY_POSE).astype(np.float32)
    pb = _project(world, (rotation, translation)).astype(np.float32)
    return pa, pb, rotation, translation


def test_characterisation_near_parallel_point_survives_today():
    """CHARACTERISATION -- pins current behaviour. Task 3 inverts this.

    Do not delete this test when the gate lands. Flip the assertion, so
    the history records that the behaviour changed deliberately.
    """
    pa, pb, rotation, translation = _near_parallel_pair()
    points = triangulate_points(pa, pb, rotation, translation, CAMERA)
    assert len(points) == 1, (
        "Today triangulate_points keeps a near-parallel pair: cheirality "
        "and finiteness are its only filters. If this fails, the gate has "
        "already landed -- flip to the Task 3 assertion rather than "
        "loosening anything."
    )


def test_characterisation_well_conditioned_geometry_survives_today():
    """The control for the above: a healthy pair is kept today, and must
    still be kept after the gate lands. Without this, a gate that simply
    empties the cloud would look like a success."""
    rotation = np.eye(3)
    translation = np.array([-1.0, 0.0, 0.0])
    world = np.array([[0.0, 0.0, 10.0], [1.0, 0.5, 12.0], [-1.0, -0.5, 9.0]])
    pa = _project(world, IDENTITY_POSE).astype(np.float32)
    pb = _project(world, (rotation, translation)).astype(np.float32)
    points = triangulate_points(pa, pb, rotation, translation, CAMERA)
    assert len(points) == 3
