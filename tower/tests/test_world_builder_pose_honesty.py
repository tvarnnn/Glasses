"""An anchor is not a camera pose, and the wire must not say it is.

On 2026-08-24 a physical walk put "Camera poses: 36" on the phone. The
manifest that number came from says:

    {"backend_id": "unposed", "keyframes": 155, "poses_solved": 0,
     "poses_refused": 119, "points": 0, "segments": 36}

`poses_solved` is zero. The 36 were `POSE_STATUS_ANCHOR` rows -- one per
tracking segment, every one of them an identity rotation at the origin,
all 36 at the same point. `backends/unposed.py` says in a comment that
the ANCHOR status exists precisely so "a downstream consumer [cannot]
count it as evidence". The result channel counted it, via

    pose_count = keyframes - poses_refused        # 155 - 119 = 36

That formula is right for the classical backend, where an anchor sits at
the origin of a chain that genuinely resolved, and wrong for a backend
that solved nothing. The distinction is not cosmetic: it is the
difference between "the Tower reconstructed 36 camera positions" and
"the Tower reconstructed nothing and broke your walk into 36 pieces".
"""

import pytest

from tower.results.world_builder import _pose_count


def _manifest(**overrides):
    manifest = {
        "input_digest": "d",
        "session_id": "s",
        "keyframes": 155,
        "points": 0,
        "poses_solved": 0,
        "poses_refused": 119,
        "segments": 36,
    }
    manifest.update(overrides)
    return manifest


def test_anchors_alone_are_not_reported_as_poses():
    """The exact manifest from the 2026-08-24 walk."""
    assert _pose_count(_manifest(poses_positioned=0)) == 0


def test_a_solved_chain_still_counts_its_own_anchor():
    """An anchor at the origin of a chain that resolved IS a real position.

    Dropping it would under-report every segment by one, which is the
    opposite error and just as wrong. One segment, ten keyframes, nine
    solved plus the anchor they were solved against: ten positions.
    """
    manifest = _manifest(
        keyframes=10, poses_solved=9, poses_refused=0, segments=1,
        poses_positioned=10,
    )
    assert _pose_count(manifest) == 10


def test_an_unsolved_segments_anchor_is_not_counted():
    """Two segments, only one of which resolved.

    Segment A: 5 keyframes, anchor + 4 solved -> 5 positions.
    Segment B: 3 keyframes, anchor only, nothing solved -> 0 positions.
    The bare anchor of B is a definitional origin, not a measurement.
    """
    manifest = _manifest(
        keyframes=8, poses_solved=4, poses_refused=2, segments=2,
        poses_positioned=5,
    )
    assert _pose_count(manifest) == 5


def test_an_old_manifest_without_the_breakdown_reports_absent():
    """Worlds built before poses_positioned existed do not get a guess.

    This test used to assert that falling back to keyframes - poses_refused
    was "the honest choice" for a manifest that cannot answer the better
    question. It was not: that is the exact arithmetic that put "Camera
    poses: 36" on the phone from a manifest reading poses_solved: 0. An
    anchor is definitional (identity rotation, zero translation), and the
    fallback silently promoted every one of them to a measured position.
    A manifest missing poses_positioned predates the fix that can tell
    the difference, and absent is the only honest answer for it now.
    """
    manifest = _manifest(keyframes=10, poses_solved=9, poses_refused=0)
    assert _pose_count(manifest) is None


def test_a_manifest_with_nonsense_counts_reports_nothing():
    assert _pose_count(_manifest(keyframes=None)) is None
    assert _pose_count(_manifest(poses_positioned="lots")) is None


# -- end to end, through a real build ---------------------------------


@pytest.fixture
def built(tmp_path):
    """A real engine, a real store, a real (unposed) build."""
    import base64  # noqa: F401  -- kept for parity with sibling fixtures

    import cv2
    import numpy as np

    from tower.world_builder.engine import WorldBuilderEngine
    from tower.world_builder.store import WorldStore

    store = WorldStore(tmp_path)
    engine = WorldBuilderEngine(store)
    world_id = engine.create_world()
    session_id = engine.start_session(world_id, frame_source="test")

    rng = np.random.default_rng(0)
    for index in range(6):
        # Textured noise, shifted, so tracking survives and keyframes are
        # accepted. Content does not matter here: the unposed backend
        # refuses every pose regardless.
        image = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)
        ok, buffer = cv2.imencode(".jpg", image)
        assert ok
        engine.observe(buffer.tobytes(), source_seq=index + 1)
    engine.stop_session()
    result = engine.build(world_id, session_id)
    return store, world_id, session_id, result


def test_an_uncalibrated_build_reports_zero_positioned_poses(built):
    """The whole point, asserted against a real build.

    The unposed backend withholds every pose by construction, so whatever
    else this world contains, it contains no trajectory.
    """
    store, world_id, session_id, result = built

    assert result.backend_id == "unposed"
    assert result.poses_solved == 0
    manifest = store.read_derived_manifest(world_id)
    assert manifest["poses_positioned"] == 0
    assert _pose_count(manifest) == 0


def test_the_manifest_records_how_many_anchors_there_were(built):
    """The anchors are still reported -- as anchors.

    Suppressing them entirely would replace one misleading number with a
    missing one. A reader should be able to see that the build produced
    36 segment origins and no trajectory, because that is a precise
    description of what happened.
    """
    store, world_id, _, result = built

    manifest = store.read_derived_manifest(world_id)
    assert manifest["poses_anchor"] == manifest["segments"]
    assert manifest["poses_anchor"] > 0


# -- the downgrade is loud once, not once per rebuild ------------------


def test_the_backend_downgrade_is_announced_exactly_once_per_session(
    tmp_path, caplog
):
    """Loud once is the point; loud sixty times is what hides it.

    Selection stopped being a once-per-session event when `build()`
    became a flush that runs on every rebuild, and the Tower now attaches
    a follower rebuilding every four keyframes. A 260-keyframe walk --
    which is what the current keyframe policy produces on the 2026-08-24
    footage -- would emit sixty-six identical warnings, and the operator
    reading a log for "why is there no geometry?" would be scrolling past
    the answer.

    The SELECTION is unchanged either way. `downgraded_from` and
    `downgrade_reason` are still recorded on the session, which is where
    a machine reads them; the log line is for a person, once.
    """
    import cv2
    import numpy as np

    from tower.world_builder.engine import WorldBuilderEngine
    from tower.world_builder.store import WorldStore

    store = WorldStore(tmp_path)
    engine = WorldBuilderEngine(store)
    world_id = engine.create_world()

    rng = np.random.default_rng(3)
    with caplog.at_level("WARNING"):
        session_id = engine.start_session(world_id, frame_source="test")
        rebuilds = 0
        for index in range(12):
            image = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)
            ok, buffer = cv2.imencode(".jpg", image)
            assert ok
            engine.observe(buffer.tobytes(), source_seq=index + 1)
            if (index + 1) % 2 == 0:
                engine.build(world_id, session_id)
                rebuilds += 1
        engine.stop_session()
        engine.build(world_id, session_id)

    assert rebuilds >= 3, "this test needs several rebuilds to mean anything"
    announcements = [
        record
        for record in caplog.records
        if "backend selected unposed" in record.getMessage()
    ]
    assert len(announcements) == 1, (
        f"{len(announcements)} identical downgrade warnings across "
        f"{rebuilds} rebuilds; it should be announced once, at session start"
    )

    # And the machine-readable record is untouched by the quieting.
    session = store.read_session(world_id, session_id)
    assert session.backend_downgraded_from == "classical"
    assert "intrinsics" in session.backend_downgrade_reason
