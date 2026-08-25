"""The geometry adapter: grouping, hashing, manifest and chunks."""

import pytest

from tower.results.world_builder_geometry import (
    GEOMETRY_CONTRACT,
    build_manifest,
    segment_content_hash,
)


def test_the_contract_identifier_is_exact():
    assert GEOMETRY_CONTRACT == "world_builder.geometry/2026-08-25"


def test_the_manifest_reports_every_segment_including_empty_ones(derived_world):
    """32 of 51 segments on the real walk resolved to nothing.

    Dropping them would erase the observed-but-unresolved state, which is
    the difference between "we did not look" and "we looked and failed".
    """
    store, world_id, session_id = derived_world
    manifest = build_manifest(store, world_id, session_id)

    assert manifest["segment_count"] == 2
    assert [s["segment_index"] for s in manifest["segments"]] == [0, 1]


def test_a_segment_with_no_points_is_unresolved_with_null_bounds(derived_world):
    store, world_id, session_id = derived_world
    manifest = build_manifest(store, world_id, session_id)
    empty = manifest["segments"][1]

    assert empty["point_count"] == 0
    assert empty["resolution_state"] == "unresolved"
    assert empty["bounds"] is None
    assert empty["dominant_degeneracy"] == "low_parallax"


def test_a_resolved_segment_reports_bounds_over_its_own_points(derived_world):
    store, world_id, session_id = derived_world
    manifest = build_manifest(store, world_id, session_id)
    resolved = manifest["segments"][0]

    assert resolved["resolution_state"] == "resolved"
    assert resolved["point_count"] == 2
    assert resolved["solved_count"] == 1
    assert resolved["keyframe_count"] == 2
    assert resolved["bounds"] == {"min": [-1.0, 0.0, 3.0], "max": [1.0, 2.0, 5.0]}


def test_no_segment_claims_registration(derived_world):
    """Nothing registers segments yet. Claiming otherwise fabricates a world."""
    store, world_id, session_id = derived_world
    manifest = build_manifest(store, world_id, session_id)

    for segment in manifest["segments"]:
        assert segment["registered"] is False
        assert segment["transform_to_world"] is None
        assert segment["frame_id"] == f"segment:{segment['segment_index']}"


def test_the_manifest_carries_the_pose_convention_verbatim(derived_world):
    """iOS refuses to render on any mismatch, so all nine keys must travel."""
    store, world_id, session_id = derived_world
    manifest = build_manifest(store, world_id, session_id)

    assert set(manifest["pose_convention"]) == {
        "pose_type", "quaternion_order", "handedness", "camera_axes",
        "translation_units", "world_axes_origin", "up_axis",
        "pose_dtype", "point_dtype",
    }
    assert manifest["pose_convention"]["quaternion_order"] == "wxyz"
    assert manifest["pose_convention"]["up_axis"] == "unknown"


def test_a_content_hash_is_stable_for_identical_content():
    poses = [{"keyframe_id": "a", "segment_index": 0, "status": "anchor",
              "degeneracy": "", "rotation": [1.0, 0.0, 0.0, 0.0],
              "translation": [0.0, 0.0, 0.0]}]
    points = [{"segment_index": 0, "xyz": [1.0, 2.0, 3.0]}]

    assert segment_content_hash(poses, points) == segment_content_hash(poses, points)


def test_a_content_hash_changes_when_a_point_moves():
    poses = []
    a = [{"segment_index": 0, "xyz": [1.0, 2.0, 3.0]}]
    b = [{"segment_index": 0, "xyz": [1.0, 2.0, 3.5]}]

    assert segment_content_hash(poses, a) != segment_content_hash(poses, b)


def test_a_frozen_segment_keeps_its_hash_when_a_later_segment_is_added(
    derived_world, keyframe_factory
):
    """The property the whole cache design rests on.

    engine.py:767 freezes a segment when tracking is lost, so segment 0 must
    not churn because segment 1 grew.
    """
    from tower.world_builder.store import compute_input_digest

    store, world_id, session_id = derived_world
    before = build_manifest(store, world_id, session_id)["segments"][0]["content_hash"]

    derived = store.read_derived(world_id, session_id)
    poses = derived["poses"] + [
        {"keyframe_id": f"{session_id}:00000005", "segment_index": 1,
         "status": "solved", "degeneracy": "",
         "rotation": [1.0, 0.0, 0.0, 0.0], "translation": [9.0, 9.0, 9.0]}
    ]
    points = derived["points"] + [{"segment_index": 1, "xyz": [9.0, 9.0, 9.0]}]

    store.append_keyframe(world_id, keyframe_factory(session_id, 5, 1))
    manifest = store.read_derived_manifest(world_id)
    manifest["input_digest"] = compute_input_digest(
        store.read_keyframes(world_id, session_id)
    )
    store.write_derived(world_id, session_id, poses=poses, points=points,
                        manifest=manifest)

    after = build_manifest(store, world_id, session_id)["segments"][0]["content_hash"]
    assert after == before


def test_a_missing_world_yields_none(derived_world):
    store, _, session_id = derived_world
    assert build_manifest(store, "nope", session_id) is None
