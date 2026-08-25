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


from tower.results.world_builder_geometry import build_segment


def test_a_chunk_carries_poses_in_file_order(derived_world):
    store, world_id, session_id = derived_world
    chunk = build_segment(store, world_id, session_id, 0)

    assert [p["status"] for p in chunk["poses"]] == ["anchor", "solved"]
    assert chunk["segment_index"] == 0
    assert chunk["registered"] is False


def test_a_refused_pose_reaches_the_chunk_as_null(derived_world):
    """The viewer must draw a break, not a line through a gap."""
    store, world_id, session_id = derived_world
    chunk = build_segment(store, world_id, session_id, 1)

    refused = [p for p in chunk["poses"] if p["status"] == "unavailable"]
    assert refused[0]["translation"] is None
    assert refused[0]["degeneracy"] == "low_parallax"


def test_points_are_bare_triples_not_tagged_rows(derived_world):
    """The chunk already names its segment, so per-row tagging is redundant."""
    store, world_id, session_id = derived_world
    chunk = build_segment(store, world_id, session_id, 0)

    assert chunk["points"] == [[1.0, 2.0, 3.0], [-1.0, 0.0, 5.0]]


def test_an_unsampled_chunk_says_so(derived_world):
    store, world_id, session_id = derived_world
    chunk = build_segment(store, world_id, session_id, 0)

    assert chunk["points_sent"] == 2
    assert chunk["points_total"] == 2
    assert chunk["point_sampling"] == "none"


def test_sampling_never_lets_a_partial_cloud_look_whole(derived_world):
    store, world_id, session_id = derived_world
    chunk = build_segment(store, world_id, session_id, 0, max_points=1)

    assert chunk["points_sent"] == 1
    assert chunk["points_total"] == 2
    assert chunk["point_sampling"] == "stride"
    assert len(chunk["points"]) == 1


def test_a_chunks_hash_matches_the_manifests_hash(derived_world):
    """Otherwise the client's cache key never matches what it fetched."""
    store, world_id, session_id = derived_world
    manifest = build_manifest(store, world_id, session_id)
    chunk = build_segment(store, world_id, session_id, 0)

    assert chunk["content_hash"] == manifest["segments"][0]["content_hash"]


def test_a_sampled_chunk_keeps_the_unsampled_hash(derived_world):
    """The hash identifies the SEGMENT, not the transfer."""
    store, world_id, session_id = derived_world
    full = build_segment(store, world_id, session_id, 0)
    sampled = build_segment(store, world_id, session_id, 0, max_points=1)

    assert sampled["content_hash"] == full["content_hash"]


def test_an_unknown_segment_yields_none(derived_world):
    store, world_id, session_id = derived_world
    assert build_segment(store, world_id, session_id, 99) is None
