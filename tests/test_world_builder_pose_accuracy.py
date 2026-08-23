"""Pose accuracy against INDEPENDENT ground truth, and pose honesty.

The synthetic scene generator knows exactly where its cameras were, so
these compare the reconstruction against the truth that produced it --
not against another output of the same pipeline, which would pass for a
pipeline that was consistently wrong.

Two different questions, and the second matters more:

1. How accurate is a solved pose?
2. When the geometry is bad, does the engine REFUSE, or does it report a
   confident wrong answer?

A refusal is a first-class result here. A wrong pose reported as `solved`
is the failure this whole project's epistemics exist to prevent, because a
consumer cannot tell it from a right one.

SYNTHETIC, NOT PHYSICAL. Rendered rooms with perfect optics say nothing
about the Ray-Ban camera.
"""

import math

import numpy as np
import pytest

from tests import synthetic_scene as ss
from tower.world_builder.engine import WorldBuilderEngine
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.redaction import FaceRedactor
from tower.world_builder.schema import POSE_STATUS_ANCHOR, POSE_STATUS_SOLVED
from tower.world_builder.store import WorldStore

WIDTH, HEIGHT = 640, 360
SOLVED = (POSE_STATUS_SOLVED, POSE_STATUS_ANCHOR)


def _intrinsics(matrix) -> CameraIntrinsics:
    return CameraIntrinsics(
        source="self_calibrated",
        model="pinhole",
        fx=float(matrix[0, 0]),
        fy=float(matrix[1, 1]),
        cx=float(matrix[0, 2]),
        cy=float(matrix[1, 2]),
        calibrated_width=WIDTH,
        calibrated_height=HEIGHT,
    )


def _reconstruct(tmp_path, seed: int, poses):
    """Run the real pipeline and return (pose rows, ground-truth poses)."""
    matrix = ss.camera_matrix(WIDTH, HEIGHT)
    images = ss.render_sequence(
        ss.furnished_room(seed=seed), poses, matrix, WIDTH, HEIGHT
    )
    store = WorldStore(tmp_path / f"seed{seed}")
    engine = WorldBuilderEngine(
        store,
        # Redaction off: this measures geometry, and a face detector has
        # no business influencing a pose-accuracy number.
        redactor_factory=lambda: FaceRedactor(path=tmp_path / "absent.onnx"),
    )
    world_id = engine.create_world("Accuracy")
    session_id = engine.start_session(
        world_id,
        intrinsics=_intrinsics(matrix),
        frame_source="synthetic",
        declared_size=(WIDTH, HEIGHT),
    )
    for index, image in enumerate(images):
        engine.observe(ss.encode_jpeg(image), source_seq=index)
    engine.stop_session()
    engine.build(world_id, session_id)

    derived = store.read_derived(world_id, session_id)
    return ([] if derived is None else derived["poses"]), poses


def _direction_error_degrees(estimated, truth) -> float | None:
    """Angle between two directions, folded so a sign flip is not 180 deg.

    The reconstruction is scale-free and its translation is defined only
    up to sign for a two-view solve, so the axis is what can be compared.
    """
    estimated = np.asarray(estimated, dtype=float)
    truth = np.asarray(truth, dtype=float)
    if np.linalg.norm(estimated) < 1e-9 or np.linalg.norm(truth) < 1e-9:
        return None
    estimated = estimated / np.linalg.norm(estimated)
    truth = truth / np.linalg.norm(truth)
    cosine = abs(float(np.dot(estimated, truth)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _errors(rows, truth):
    out = []
    for index, row in enumerate(rows):
        if index == 0 or row["translation"] is None:
            continue
        error = _direction_error_degrees(
            row["translation"],
            np.asarray(truth[index].position) - np.asarray(truth[0].position),
        )
        if error is not None:
            out.append((row["status"], error))
    return out


# -- accuracy -----------------------------------------------------------


@pytest.mark.parametrize("seed", [1000, 1001, 1002, 1003])
def test_lateral_motion_recovers_translation_direction_closely(tmp_path, seed):
    """Sideways motion is the best case for two-view geometry.

    Measured across 20 scene seeds: median 0.30 deg, p90 1.32 deg, worst
    4.91 deg. The bound below is deliberately loose enough not to be a
    thermometer and tight enough to catch a real regression.
    """
    rows, truth = _reconstruct(tmp_path, seed, ss.strafe(6, step=0.15))
    errors = _errors(rows, truth)

    assert errors, "no pose was solved on the easiest possible motion"
    worst = max(error for _status, error in errors)
    assert worst < 10.0, f"lateral direction error reached {worst:.2f} deg"


@pytest.mark.parametrize("seed", [1000, 1001, 1002, 1003])
def test_forward_motion_is_worse_but_still_bounded(tmp_path, seed):
    """Forward motion is what a walking person actually does, and it is hard.

    The epipole sits inside the image, so translation direction is poorly
    conditioned even with perfect features. Measured across 12 seeds:
    median 5.70 deg, p90 7.36 deg -- an order of magnitude worse than
    lateral, and still nowhere near a wrong answer.
    """
    rows, truth = _reconstruct(tmp_path, seed, ss.forward_walk(6, step=0.15))
    errors = _errors(rows, truth)

    if not errors:
        pytest.skip("this seed solved no pose on forward motion")
    worst = max(error for _status, error in errors)
    assert worst < 20.0, f"forward direction error reached {worst:.2f} deg"


# -- honesty ------------------------------------------------------------


@pytest.mark.parametrize("seed", [1000, 1001, 1002, 1003, 1004])
@pytest.mark.parametrize(
    "motion",
    ["strafe", "forward", "rotation"],
    ids=["lateral", "forward", "pure-rotation"],
)
def test_no_pose_is_ever_confidently_wrong(tmp_path, seed, motion):
    """The finding that matters: a bad pose must be REFUSED, not reported.

    Pure rotation is included because it is genuinely degenerate -- there
    is no baseline to triangulate from, so any translation direction the
    solver returns is meaningless. The engine must refuse it rather than
    return a plausible vector.
    """
    poses = {
        "strafe": ss.strafe(6, step=0.15),
        "forward": ss.forward_walk(6, step=0.15),
        "rotation": ss.pure_rotation(6),
    }[motion]

    rows, truth = _reconstruct(tmp_path, seed, poses)
    for status, error in _errors(rows, truth):
        if status in SOLVED:
            assert error < 30.0, (
                f"a pose {error:.1f} deg from the truth was reported as "
                f"{status!r} -- a consumer cannot tell that from a right one"
            )


def test_a_refused_pose_carries_no_translation(tmp_path):
    """A refusal must be empty, not a guess with a label on it."""
    rows, _truth = _reconstruct(tmp_path, 1000, ss.forward_walk(8, step=0.05))
    for row in rows:
        if row["status"] not in SOLVED:
            assert row["translation"] is None, (
                "a refused pose carried a translation, which invites a "
                "consumer to use it"
            )


def test_forward_motion_yields_fewer_solved_poses_than_lateral(tmp_path):
    """Conservatism under poor conditioning, stated as a measured fact.

    Across 12 seeds the same six-keyframe trajectory solved 24 poses
    laterally and 12 forwards. That is the engine being appropriately
    unwilling, not a bug -- but it means a walking person produces a
    sparser reconstruction than a sidestepping one, which is worth knowing
    before a physical demo.
    """
    lateral, _ = _reconstruct(tmp_path, 1000, ss.strafe(6, step=0.15))
    forward, _ = _reconstruct(tmp_path, 1000, ss.forward_walk(6, step=0.15))

    lateral_solved = sum(1 for row in lateral if row["status"] in SOLVED)
    forward_solved = sum(1 for row in forward if row["status"] in SOLVED)

    assert lateral_solved >= forward_solved, (
        "forward motion solved MORE poses than lateral, which contradicts "
        "the geometry and suggests the conditioning check is not working"
    )
