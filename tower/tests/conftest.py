import os

import pytest

from tower.world_builder.records import Keyframe, Session, World
from tower.world_builder.store import WorldStore, compute_input_digest

# Module-scope clear, in addition to the autouse fixture below: pytest
# imports conftest.py before any test module, but an ambient
# TOWER_CV_EXPERIMENT=depth in the operator's shell (e.g. left over from
# manually testing the depth experiment per the README) would otherwise
# still be set when tower.main is first imported during test collection.
# tower/main.py's last line is a module-level `app = create_app()` that
# runs at import time -- before any fixture, even an autouse one, gets a
# chance to run, since fixtures only wrap test *execution*, not import.
# Left uncleared, that import-time create_app() would build a real
# DepthEstimationModule and attempt a real torch import / MiDaS network
# fetch during collection, regardless of which tests are selected.
os.environ.pop("TOWER_CV_EXPERIMENT", None)
os.environ.pop("TOWER_CV_DEVICE", None)


@pytest.fixture(autouse=True)
def _clear_cv_experiment_env(monkeypatch):
    monkeypatch.delenv("TOWER_CV_EXPERIMENT", raising=False)
    monkeypatch.delenv("TOWER_CV_DEVICE", raising=False)


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
def keyframe_factory():
    """`_keyframe` as a fixture, because conftest is not an importable module."""
    return _keyframe


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
