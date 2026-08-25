"""The on-disk shape of the derived reconstruction.

These files are about to become a wire contract. Nothing pinned their key
sets, their dtypes, the wxyz quaternion order, or the difference between
null and zero -- so a rename would have been invisible until a phone
rendered it wrong.
"""

import json

import pytest

from tower.world_builder.records import Keyframe, Session, World
from tower.world_builder.store import WorldStore, compute_input_digest


def _keyframe(session_id: str, seq: int, segment_index: int) -> Keyframe:
    return Keyframe(
        keyframe_id=f"{session_id}:{seq:08d}",
        session_id=session_id,
        source_seq=seq,
        received_at=1000.0 + seq,
        image_relpath=f"images/{seq:08d}.jpg",
        width=360,
        height=640,
        byte_count=1234,
        segment_index=segment_index,
    )


@pytest.fixture
def derived_world(tmp_path):
    """A two-segment world with a derived tree that verifies.

    Segment 0 resolves (an anchor plus a solved pose, with points).
    Segment 1 does not (an anchor plus a refused pose, no points) -- the
    32-of-51 case on the real walk.
    """
    store = WorldStore(tmp_path)
    world_id = "w0"
    session_id = "s0"
    store.write_world(World(world_id=world_id, created_at=1.0, updated_at=2.0,
                            session_ids=(session_id,)))
    store.write_session(Session(session_id=session_id, world_id=world_id,
                                started_at=1.0, ended_at=2.0))

    layout = [(1, 0), (2, 0), (3, 1), (4, 1)]
    for seq, segment_index in layout:
        store.append_keyframe(world_id, _keyframe(session_id, seq, segment_index))

    poses = [
        {"keyframe_id": f"{session_id}:00000001", "segment_index": 0,
         "status": "anchor", "degeneracy": "",
         "rotation": [1.0, 0.0, 0.0, 0.0], "translation": [0.0, 0.0, 0.0]},
        {"keyframe_id": f"{session_id}:00000002", "segment_index": 0,
         "status": "solved", "degeneracy": "",
         "rotation": [0.0, 1.0, 0.0, 0.0], "translation": [1.0, 2.0, 3.0]},
        {"keyframe_id": f"{session_id}:00000003", "segment_index": 1,
         "status": "anchor", "degeneracy": "",
         "rotation": [1.0, 0.0, 0.0, 0.0], "translation": [0.0, 0.0, 0.0]},
        {"keyframe_id": f"{session_id}:00000004", "segment_index": 1,
         "status": "unavailable", "degeneracy": "low_parallax",
         "rotation": None, "translation": None},
    ]
    points = [
        {"segment_index": 0, "xyz": [1.0, 2.0, 3.0]},
        {"segment_index": 0, "xyz": [-1.0, 0.0, 5.0]},
    ]
    digest = compute_input_digest(store.read_keyframes(world_id, session_id))
    manifest = {
        "schema_version": 1, "input_digest": digest, "built_at": 3.0,
        "backend_id": "classical-sfm", "session_id": session_id,
        "keyframes": 4, "poses_solved": 1, "poses_refused": 1,
        "poses_anchor": 2, "poses_positioned": 2, "points": 2,
        "segments": 2, "scale_state": "unknown",
    }
    store.write_derived(world_id, session_id, poses=poses, points=points,
                        manifest=manifest)
    return store, world_id, session_id


def test_poses_json_has_exactly_the_documented_keys(derived_world):
    store, world_id, session_id = derived_world
    path = store.derived_dir(world_id) / session_id / "poses.json"
    data = json.loads(path.read_text())

    assert set(data) == {"poses"}
    for row in data["poses"]:
        assert set(row) == {
            "keyframe_id", "segment_index", "status", "degeneracy",
            "rotation", "translation",
        }


def test_a_refused_pose_keeps_null_and_not_zero(derived_world):
    """null means refused. A zero translation is a claim about the world."""
    store, world_id, session_id = derived_world
    path = store.derived_dir(world_id) / session_id / "poses.json"
    rows = json.loads(path.read_text())["poses"]

    refused = [r for r in rows if r["status"] == "unavailable"]
    assert refused, "fixture must contain a refused pose"
    for row in refused:
        assert row["translation"] is None
        assert row["rotation"] is None


def test_an_anchor_is_identity_and_origin_exactly(derived_world):
    """Anchors are definitional, not measured. Every segment starts at one."""
    store, world_id, session_id = derived_world
    path = store.derived_dir(world_id) / session_id / "poses.json"
    rows = json.loads(path.read_text())["poses"]

    anchors = [r for r in rows if r["status"] == "anchor"]
    assert len(anchors) == 2
    for row in anchors:
        assert row["rotation"] == [1.0, 0.0, 0.0, 0.0]
        assert row["translation"] == [0.0, 0.0, 0.0]


def test_points_json_rows_carry_their_segment(derived_world):
    """Segments share no frame, so an untagged point cannot be placed."""
    store, world_id, session_id = derived_world
    path = store.derived_dir(world_id) / session_id / "points.json"
    data = json.loads(path.read_text())

    assert set(data) == {"points"}
    for row in data["points"]:
        assert set(row) == {"segment_index", "xyz"}
        assert len(row["xyz"]) == 3


def test_derived_manifest_has_exactly_the_documented_keys(derived_world):
    store, world_id, _ = derived_world
    manifest = store.read_derived_manifest(world_id)

    assert set(manifest) == {
        "schema_version", "input_digest", "built_at", "backend_id",
        "session_id", "keyframes", "poses_solved", "poses_refused",
        "poses_anchor", "poses_positioned", "points", "segments",
        "scale_state",
    }


def test_the_fixture_survives_digest_verification(derived_world):
    """If this fails every later geometry test is reading a stale tree."""
    store, world_id, session_id = derived_world
    assert store.read_derived(world_id, session_id) is not None
