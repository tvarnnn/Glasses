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


# ---------------------------------------------------------------------------
# Task 2: the gate helper itself.
# ---------------------------------------------------------------------------


def test_gate_rejects_near_parallel_landmark():
    from tower.world_builder.geometry import landmark_gate

    pose_b = (np.eye(3), np.array([-0.001, 0.0, 0.0]))
    world = np.array([[0.0, 0.0, 1000.0]])
    keep, counts = landmark_gate(
        world,
        _project(world, IDENTITY_POSE),
        _project(world, pose_b),
        IDENTITY_POSE,
        pose_b,
        CAMERA,
    )
    assert not keep[0]
    assert counts["low_parallax"] == 1
    assert counts["high_reprojection"] == 0


def test_gate_keeps_distant_but_well_triangulated_landmark():
    """ADVERSARIAL, REQUIRED.

    A gate that discards everything satisfies every other test in this
    file. Distance alone is not the defect -- an unconstrained ray is.
    Baseline 30 at depth 1000 subtends ~1.7 deg, comfortably above the
    0.5 deg bar, and MUST survive. If this test ever fails, the gate has
    become a truncation and the reconstruction is being thrown away.
    """
    from tower.world_builder.geometry import landmark_gate

    pose_b = (np.eye(3), np.array([-30.0, 0.0, 0.0]))
    world = np.array([[0.0, 0.0, 1000.0]])
    keep, counts = landmark_gate(
        world,
        _project(world, IDENTITY_POSE),
        _project(world, pose_b),
        IDENTITY_POSE,
        pose_b,
        CAMERA,
    )
    assert keep[0], "a genuinely distant, well-triangulated point must survive"
    assert counts == {"low_parallax": 0, "high_reprojection": 0}


def test_gate_rejects_high_reprojection_landmark():
    from tower.world_builder.geometry import landmark_gate

    pose_b = (np.eye(3), np.array([-1.0, 0.0, 0.0]))
    world = np.array([[0.0, 0.0, 10.0]])
    good_a = _project(world, IDENTITY_POSE)
    bad_b = _project(world, pose_b) + np.array([[40.0, 0.0]])
    keep, counts = landmark_gate(
        world, good_a, bad_b, IDENTITY_POSE, pose_b, CAMERA
    )
    assert not keep[0]
    assert counts["high_reprojection"] == 1
    assert counts["low_parallax"] == 0


def test_gate_handles_coincident_camera_centres_without_raising():
    """Degenerate pair: zero baseline. The angle is undefined, and the
    honest answer is that this is not geometry. Must not raise, divide by
    zero, or emit a non-finite angle that silently compares False."""
    from tower.world_builder.geometry import landmark_gate

    pose_b = (np.eye(3), np.zeros(3))
    world = np.array([[0.0, 0.0, 10.0]])
    keep, counts = landmark_gate(
        world,
        _project(world, IDENTITY_POSE),
        _project(world, pose_b),
        IDENTITY_POSE,
        pose_b,
        CAMERA,
    )
    assert not keep[0]
    assert counts["low_parallax"] == 1


def test_gate_counts_are_mutually_exclusive_and_total_correctly():
    """Accounting: kept + low_parallax + high_reprojection == produced.

    A point failing both gates is counted once, under low_parallax,
    because gate 1 is evaluated first.
    """
    from tower.world_builder.geometry import landmark_gate

    pose_b = (np.eye(3), np.array([-1.0, 0.0, 0.0]))
    world = np.array(
        [[0.0, 0.0, 10.0], [0.0, 0.0, 100000.0], [1.0, 0.0, 10.0]]
    )
    pa = _project(world, IDENTITY_POSE)
    pb = _project(world, pose_b)
    pb[2] = pb[2] + np.array([50.0, 0.0])
    keep, counts = landmark_gate(world, pa, pb, IDENTITY_POSE, pose_b, CAMERA)
    assert (
        int(keep.sum()) + counts["low_parallax"] + counts["high_reprojection"]
        == 3
    )
    assert set(counts) == {"low_parallax", "high_reprojection"}


def test_gate_on_empty_input_returns_empty_mask_and_zero_counts():
    from tower.world_builder.geometry import landmark_gate

    keep, counts = landmark_gate(
        np.zeros((0, 3)),
        np.zeros((0, 2)),
        np.zeros((0, 2)),
        IDENTITY_POSE,
        (np.eye(3), np.array([-1.0, 0.0, 0.0])),
        CAMERA,
    )
    assert keep.shape == (0,)
    assert counts == {"low_parallax": 0, "high_reprojection": 0}


def test_gate_threshold_is_derived_not_invented():
    """The gate bar is DERIVED from existing constants and the actual
    calibration, not chosen.

    For a two-view triangulation, sigma_d/d = sigma_px / (f * theta).
    Setting that to 1.0 -- an error bar as wide as the measurement --
    gives theta_min = sigma_px / f, with sigma_px the pipeline's own
    RANSAC_THRESHOLD_PX. Nothing here is tunable by taste.
    """
    import math

    from tower.world_builder import geometry

    derived = geometry.min_parallax_deg(CAMERA)
    focal = 0.5 * (CAMERA[0][0] + CAMERA[1][1])
    assert derived == math.degrees(geometry.RANSAC_THRESHOLD_PX / focal)
    assert abs(derived - 0.1308) < 1e-3
    # And the depth error at that angle really is ~100%.
    assert (
        abs(
            geometry.RANSAC_THRESHOLD_PX / (focal * math.radians(derived))
            - 1.0
        )
        < 1e-9
    )


def test_gate_bar_scales_with_focal_length():
    """A pixel-denominated bar that did not scale would silently change
    meaning if the delivered resolution ever moved. This one scales."""
    from tower.world_builder import geometry

    doubled = np.array(
        [[2 * 438.23, 0.0, 349.76], [0.0, 2 * 437.78, 646.76], [0.0, 0.0, 1.0]]
    )
    assert geometry.min_parallax_deg(doubled) < geometry.min_parallax_deg(CAMERA)
    assert abs(
        geometry.min_parallax_deg(doubled) * 2 - geometry.min_parallax_deg(CAMERA)
    ) < 1e-9


def test_gate_bar_is_not_the_pair_level_constant():
    """Guards the distinction the corpus measurement forced.

    MIN_TRIANGULATION_ANGLE_DEG answers "is this PAIR good enough to trust
    a pose from" (0.5 deg, a 26% depth error). Gating LANDMARKS there
    discards 37-44% of a real world. These are different questions and
    must not be re-conflated by a well-meaning cleanup.
    """
    from tower.world_builder import geometry

    assert geometry.min_parallax_deg(CAMERA) < geometry.MIN_TRIANGULATION_ANGLE_DEG


def test_gate_falls_back_rather_than_admitting_everything_without_calibration():
    """A zero/garbage camera matrix must not yield a zero bar that admits
    every unconstrained ray."""
    from tower.world_builder import geometry

    assert geometry.min_parallax_deg(np.zeros((3, 3))) == (
        geometry.MIN_TRIANGULATION_ANGLE_DEG
    )
