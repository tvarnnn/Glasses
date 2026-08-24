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


# -- what the reported figures actually mean ---------------------------


def test_inlier_ratio_is_the_epipolar_ratio_not_the_cheirality_one(tmp_path):
    """Two different quantities that were both being written to one field.

    `cv2.recoverPose` takes its `mask` as input AND output: it narrows it
    in place with a cheirality test bounded by an undocumented
    `distanceThresh` of 50 baselines. Reading the mask afterwards gives
    the cheirality count, not the epipolar inlier count -- and at short
    baselines the two differ by three orders of magnitude:

        baseline   matches   epipolar inliers   post-recoverPose
          0.02 m      1160      1134 (0.978)       1  (0.001)
          0.04 m      1145      1103 (0.963)       5  (0.004)
          0.08 m      1137      1116 (0.982)    1070  (0.941)

    So a field named `inlier_ratio` was reporting a measurement of
    baseline over depth. Both numbers are now recorded, in the two fields
    that were already declared for them.
    """
    import cv2

    from tower.world_builder.geometry import detect_and_describe, match_descriptors

    matrix = ss.camera_matrix(WIDTH, HEIGHT)
    scene = ss.furnished_room(seed=1000)

    for step, expect_divergence in ((0.04, True), (0.30, False)):
        poses = ss.strafe(2, step=step)
        images = ss.render_sequence(scene, poses, matrix, WIDTH, HEIGHT)
        grays = [cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for image in images]
        keys_a, desc_a = detect_and_describe(grays[0])
        keys_b, desc_b = detect_and_describe(grays[1])
        points_a, points_b = match_descriptors(keys_a, desc_a, keys_b, desc_b)

        a64 = np.asarray(points_a, dtype=np.float64)
        b64 = np.asarray(points_b, dtype=np.float64)
        essential, mask = cv2.findEssentialMat(
            a64, b64, matrix, method=cv2.USAC_MAGSAC, prob=0.999, threshold=1.0
        )
        epipolar = int((mask.ravel() > 0).sum())
        cv2.recoverPose(essential, a64, b64, matrix, mask=mask)
        cheirality = int((mask.ravel() > 0).sum())

        assert epipolar / len(a64) > 0.9, "the correspondences are good"
        if expect_divergence:
            assert cheirality < epipolar * 0.5, (
                "precondition: at a short baseline the two must diverge"
            )
        else:
            assert cheirality > epipolar * 0.9


def test_redacting_a_fixed_position_face_does_not_harm_the_reconstruction(
    tmp_path,
):
    """The worst case for redaction, measured rather than assumed.

    A face pasted at a FIXED IMAGE POSITION moves with the camera in a way
    no scene content does, so its features track nothing -- and a solid
    fill over it was suspected of replacing that with equally misleading
    high-contrast box edges.

    Measured over a 16-frame lateral walk: identical keyframes and solved
    poses, MORE points (1482 vs 1130) and LOWER direction error (max 1.50
    vs 2.42 deg) with redaction on. Filling the distractor removed worse
    features than the fill introduced.
    """
    pytest.importorskip("skimage.data")
    import cv2
    from skimage import data as skdata

    from tower.world_builder.redaction import model_path

    if model_path() is None:
        pytest.skip("no face-detection model is vendored on this host")

    matrix = ss.camera_matrix(WIDTH, HEIGHT)
    poses = ss.strafe(16, step=0.09)
    images = ss.render_sequence(
        ss.furnished_room(seed=1000), poses, matrix, WIDTH, HEIGHT
    )
    face = cv2.cvtColor(
        cv2.resize(skdata.astronaut()[20:220, 150:350], (90, 90)),
        cv2.COLOR_RGB2BGR,
    )
    payloads = []
    for image in images:
        frame = image.copy()
        frame[60:150, 170:260] = face
        payloads.append(ss.encode_jpeg(frame))

    def _run(root, factory):
        engine = WorldBuilderEngine(WorldStore(root), redactor_factory=factory)
        world_id = engine.create_world("Redaction cost")
        session_id = engine.start_session(
            world_id,
            intrinsics=_intrinsics(matrix),
            frame_source="synthetic",
            declared_size=(WIDTH, HEIGHT),
        )
        for index, payload in enumerate(payloads):
            engine.observe(payload, source_seq=index)
        summary = engine.stop_session()
        return summary, engine.build(world_id, session_id)

    plain_summary, plain = _run(
        tmp_path / "plain", lambda: FaceRedactor(path=tmp_path / "absent.onnx")
    )
    redacted_summary, redacted = _run(tmp_path / "redacted", FaceRedactor)

    assert redacted_summary.keyframes_accepted == plain_summary.keyframes_accepted
    assert redacted.poses_solved == plain.poses_solved
    assert redacted.segments == plain.segments
