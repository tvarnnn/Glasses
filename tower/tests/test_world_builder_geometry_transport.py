"""The geometry adapter: grouping, hashing, manifest and chunks."""

import json
import os

import pytest

from tower.results.world_builder_geometry import (
    GEOMETRY_CONTRACT,
    build_manifest,
    segment_content_hash,
)
from tower.world_builder.records import Session, World


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


def test_sampling_spans_the_whole_cloud_and_is_not_a_prefix(tmp_path, keyframe_factory):
    """The regression that mattered: an integer stride became truncation.

    3,033 points capped at 2,000 must reach past index 1999, or the viewer is
    shown one corner of the room and told it is the world.

    This calls build_segment. A test that recomputes the sampling arithmetic
    proves only that the arithmetic equals itself.
    """
    from tower.world_builder.records import Session, World
    from tower.world_builder.store import WorldStore, compute_input_digest

    store = WorldStore(tmp_path)
    world_id, session_id = "wbig", "sbig"
    store.write_world(World(world_id=world_id, created_at=1.0, updated_at=2.0,
                            session_ids=(session_id,)))
    store.write_session(Session(session_id=session_id, world_id=world_id,
                                started_at=1.0, ended_at=2.0))
    store.append_keyframe(world_id, keyframe_factory(session_id, 1, 0))

    poses = [{"keyframe_id": f"{session_id}:00000001", "segment_index": 0,
              "status": "anchor", "degeneracy": "",
              "rotation": [1.0, 0.0, 0.0, 0.0], "translation": [0.0, 0.0, 0.0]}]
    points = [{"segment_index": 0, "xyz": [float(i), 0.0, 0.0]} for i in range(3033)]
    manifest = {
        "schema_version": 1,
        "input_digest": compute_input_digest(store.read_keyframes(world_id, session_id)),
        "built_at": 3.0, "backend_id": "classical-sfm", "session_id": session_id,
        "keyframes": 1, "poses_solved": 0, "poses_refused": 0, "poses_anchor": 1,
        "poses_positioned": 0, "points": 3033, "segments": 1,
        "scale_state": "unknown",
    }
    store.write_derived(world_id, session_id, poses=poses, points=points,
                        manifest=manifest)

    chunk = build_segment(store, world_id, session_id, 0, max_points=2000)

    assert chunk["points_sent"] == 2000
    assert chunk["points_total"] == 3033
    assert chunk["point_sampling"] == "stride"
    # The load-bearing assertion. An integer stride returned points[0:2000],
    # whose last x is 1999.0. Spanning the cloud must reach well past that.
    assert chunk["points"][-1][0] > 1999.0
    assert len({tuple(p) for p in chunk["points"]}) == 2000, "sampling produced duplicates"


def test_max_points_at_or_above_the_total_does_not_sample(derived_world):
    store, world_id, session_id = derived_world
    chunk = build_segment(store, world_id, session_id, 0, max_points=99)

    assert chunk["point_sampling"] == "none"
    assert chunk["points_sent"] == chunk["points_total"]


def test_max_points_below_one_is_refused_rather_than_dividing_by_zero(derived_world):
    store, world_id, session_id = derived_world
    with pytest.raises(ValueError):
        build_segment(store, world_id, session_id, 0, max_points=0)


from fastapi import FastAPI
from fastapi.testclient import TestClient

from tower.routes import geometry as geometry_routes


def _client(store) -> TestClient:
    app = FastAPI()
    app.include_router(geometry_routes.router)
    app.state.world_root = store.root
    return TestClient(app)


def test_the_manifest_route_serves_the_adapters_output(derived_world):
    store, world_id, session_id = derived_world
    response = _client(store).get(
        f"/worlds/{world_id}/geometry/manifest", params={"session_id": session_id}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract"] == "world_builder.geometry/2026-08-25"
    assert body["segment_count"] == 2


def test_the_segment_route_serves_one_chunk(derived_world):
    store, world_id, session_id = derived_world
    response = _client(store).get(
        f"/worlds/{world_id}/geometry/segment/0", params={"session_id": session_id}
    )

    assert response.status_code == 200
    assert response.json()["segment_index"] == 0


def test_max_points_reaches_the_adapter(derived_world):
    store, world_id, session_id = derived_world
    response = _client(store).get(
        f"/worlds/{world_id}/geometry/segment/0",
        params={"session_id": session_id, "max_points": 1},
    )

    body = response.json()
    assert body["points_sent"] == 1
    assert body["points_total"] == 2


def test_an_unknown_world_is_404_and_not_an_empty_world(derived_world):
    store, _, session_id = derived_world
    response = _client(store).get(
        "/worlds/nope/geometry/manifest", params={"session_id": session_id}
    )

    assert response.status_code == 404


def test_an_unknown_segment_is_404(derived_world):
    store, world_id, session_id = derived_world
    response = _client(store).get(
        f"/worlds/{world_id}/geometry/segment/99", params={"session_id": session_id}
    )

    assert response.status_code == 404


def test_max_points_below_one_is_rejected_by_the_api(derived_world):
    """422 at the edge, not a 500 from the adapter's ValueError."""
    store, world_id, session_id = derived_world
    response = _client(store).get(
        f"/worlds/{world_id}/geometry/segment/0",
        params={"session_id": session_id, "max_points": 0},
    )
    assert response.status_code == 422


def test_the_routes_are_sync_so_fastapi_runs_them_off_the_event_loop():
    """A 1 MB read plus a hash must never block the frame path.

    A `def` endpoint is run in FastAPI's threadpool; an `async def` one is
    not. This is the whole mechanism, so it is pinned.
    """
    import inspect

    assert not inspect.iscoroutinefunction(geometry_routes.geometry_manifest)
    assert not inspect.iscoroutinefunction(geometry_routes.geometry_segment)


def test_a_manifest_without_poses_positioned_reports_absent_not_arithmetic():
    """The fallback promoted every segment anchor to a camera pose.

    That is what produced 'Camera poses: 36' from a world with zero solved
    poses. An absent figure is the honest answer; a plausible wrong one is
    the failure the contract bump exists to prevent.
    """
    from tower.results.world_builder import _pose_count

    manifest = {"keyframes": 457, "poses_refused": 312, "segments": 51}
    assert _pose_count(manifest) is None

    manifest["poses_positioned"] = 113
    assert _pose_count(manifest) == 113


# --- currency: geometry that is real but BEHIND ---------------------------
#
# The defect these pin: `read_derived` verifies the input digest by default,
# and during a walk that digest moves with EVERY keyframe. So the adapter got
# None, the route answered 404 for the whole capture, and the fragment gallery
# stayed empty until the session ended -- while real geometry sat on disk.
# `tower/results/world_builder.py:1058` had already made the opposite call on
# the status channel for the same reason; these mirror it.


def _put_the_derived_tree_behind(store, world_id, session_id, keyframe_factory):
    """Append a keyframe AFTER the build, so the digest no longer matches.

    This is the live-walk shape exactly: nothing about the derived tree
    changes, and it becomes stale purely because the journal grew.
    """
    store.append_keyframe(world_id, keyframe_factory(session_id, 9, 1))


def test_a_current_derived_tree_says_so_in_the_manifest_and_the_chunk(derived_world):
    store, world_id, session_id = derived_world

    assert build_manifest(store, world_id, session_id)["current"] is True
    assert build_segment(store, world_id, session_id, 0)["current"] is True


def test_geometry_behind_the_journal_is_served_and_flagged_not_hidden(
    derived_world, keyframe_factory
):
    """The regression test for the headline defect.

    Against the old `verify=True` read both of these were None, and the
    route was a 404 -- for the entire duration of a live walk.
    """
    store, world_id, session_id = derived_world
    _put_the_derived_tree_behind(store, world_id, session_id, keyframe_factory)

    manifest = build_manifest(store, world_id, session_id)
    assert manifest is not None, "behind is not absent; it must still be served"
    assert manifest["current"] is False
    # The geometry itself is unchanged -- it is the same real answer to a
    # slightly older question.
    assert manifest["segment_count"] == 2

    chunk = build_segment(store, world_id, session_id, 0)
    assert chunk is not None
    assert chunk["current"] is False
    assert chunk["points"] == [[1.0, 2.0, 3.0], [-1.0, 0.0, 5.0]]


def test_the_manifest_route_serves_behind_geometry_with_200(
    derived_world, keyframe_factory
):
    store, world_id, session_id = derived_world
    _put_the_derived_tree_behind(store, world_id, session_id, keyframe_factory)

    response = _client(store).get(
        f"/worlds/{world_id}/geometry/manifest", params={"session_id": session_id}
    )

    assert response.status_code == 200
    assert response.json()["current"] is False


def test_the_segment_route_serves_behind_geometry_with_200(
    derived_world, keyframe_factory
):
    """A client that fetches only a chunk must still learn it is behind."""
    store, world_id, session_id = derived_world
    _put_the_derived_tree_behind(store, world_id, session_id, keyframe_factory)

    response = _client(store).get(
        f"/worlds/{world_id}/geometry/segment/0", params={"session_id": session_id}
    )

    assert response.status_code == 200
    assert response.json()["current"] is False


def test_an_absent_derived_tree_is_still_absent_and_still_404(derived_world):
    """Absent and behind must not collapse into one answer.

    Serving behind-but-real geometry is only defensible while "nothing was
    ever built" remains a 404.
    """
    store, world_id, session_id = derived_world
    (store.derived_dir(world_id) / session_id / "poses.json").unlink()

    assert build_manifest(store, world_id, session_id) is None
    assert build_segment(store, world_id, session_id, 0) is None

    response = _client(store).get(
        f"/worlds/{world_id}/geometry/manifest", params={"session_id": session_id}
    )
    assert response.status_code == 404


# -- Containment -----------------------------------------------------------
#
# `session_id` is declared as a bare `str` on both geometry routes, so FastAPI
# binds it as a QUERY parameter -- and unlike a path parameter it is NOT
# restricted to `[^/]+`. It arrives at `WorldStore.read_derived` as
# `self.derived_dir(world_id) / session_id`, which is an unguarded join.
#
# The check these tests demand is not novel. `results/world_builder.py:283-300`
# already whitelists these exact two identifiers against the store's own
# listings before serving the status channel, and `object_memory/imagery.py`
# resolves both sides for the same reason. This route family is the one place
# that skipped it.
#
# Reproduced BEFORE the fix: both cases answered 200 and served a
# `geometry_revision` computed over the PLANTED file rather than the world's.


def _plant_derived_tree(directory):
    """A readable derived tree, deliberately outside any world root."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "poses.json").write_text(
        json.dumps({"poses": [{
            "keyframe_id": "planted:00000001", "segment_index": 0,
            "status": "anchor", "degeneracy": "",
            "rotation": [1.0, 0.0, 0.0, 0.0],
            "translation": [111.0, 222.0, 333.0],
        }]}),
        encoding="utf-8",
    )
    (directory / "points.json").write_text(
        json.dumps({"points": [{"segment_index": 0, "xyz": [9.9, 9.9, 9.9]}]}),
        encoding="utf-8",
    )


@pytest.mark.parametrize("route", ["manifest", "segment/0"])
def test_a_traversing_session_id_cannot_escape_the_world_root(
    derived_world, tmp_path, route
):
    store, world_id, _ = derived_world
    planted = tmp_path / "outside" / "planted"
    _plant_derived_tree(planted)
    escape = os.path.relpath(planted, store.derived_dir(world_id))

    response = _client(store).get(
        f"/worlds/{world_id}/geometry/{route}", params={"session_id": escape}
    )

    assert response.status_code == 404


@pytest.mark.parametrize("route", ["manifest", "segment/0"])
def test_an_absolute_session_id_cannot_replace_the_world_root(
    derived_world, tmp_path, route
):
    """An absolute path does not traverse out of a base -- it REPLACES it.

    `Path("/a/b") / "C:/elsewhere"` is `C:/elsewhere`, so a guard that only
    looks for `..` would pass this and still read the wrong tree.
    """
    store, world_id, _ = derived_world
    planted = tmp_path / "outside" / "planted"
    _plant_derived_tree(planted)

    response = _client(store).get(
        f"/worlds/{world_id}/geometry/{route}", params={"session_id": str(planted)}
    )

    assert response.status_code == 404


def _make_world_in(root, world_id, session_id):
    """A second, complete world, deliberately under a DIFFERENT root."""
    from tower.world_builder.store import WorldStore, compute_input_digest
    from tower.world_builder.records import Keyframe

    store = WorldStore(root)
    store.write_world(World(world_id=world_id, created_at=1.0, updated_at=2.0,
                            session_ids=(session_id,)))
    store.write_session(Session(session_id=session_id, world_id=world_id,
                                started_at=1.0, ended_at=2.0))
    for seq in (1, 2):
        store.append_keyframe(world_id, Keyframe(
            keyframe_id=f"{session_id}:{seq:08d}", session_id=session_id,
            source_seq=seq, received_at=1000.0 + seq,
            image_relpath=f"images/{seq:08d}.jpg", width=360, height=640,
            byte_count=1234, segment_index=0))
    _plant_derived_tree(store.derived_dir(world_id) / session_id)
    (store.derived_dir(world_id) / session_id / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "input_digest": compute_input_digest(
                store.read_keyframes(world_id, session_id)
            ),
            "built_at": 3.0, "backend_id": "classical-sfm",
            "session_id": session_id, "keyframes": 2, "poses_solved": 0,
            "poses_refused": 0, "poses_anchor": 1, "poses_positioned": 1,
            "points": 1, "segments": 1, "scale_state": "unknown",
        }),
        encoding="utf-8",
    )
    return store


@pytest.mark.parametrize("form", ["relative", "percent_encoded", "absolute"])
def test_a_traversing_world_id_cannot_escape_the_configured_root(
    derived_world, tmp_path, form
):
    """`world_id` is the OTHER half, and the session guard cannot see it.

    Containment for `session_id` is anchored on `derived_dir(world_id)`.
    An escaped `world_id` moves that anchor, so `parent == base` still
    holds relative to the escaped base and the check passes -- the first
    version of this fix closed one hole and left its twin open.

    `world_id` is a PATH parameter, so Starlette's `[^/]+` stops a forward
    slash. On Windows a BACKSLASH is also a separator and is not excluded,
    and `%5C` is decoded before routing, so both reach the store. (`%2F`
    does not match the route and is not a vector.) Windows is the only
    platform this Tower ships on.

    REPRODUCED before the fix: all three forms answered 200 and served a
    complete world planted outside the configured root.
    """
    store, _, _ = derived_world
    outside = tmp_path / "outside"
    _make_world_in(outside, "victim", "vs")

    escape = os.path.relpath(outside / "worlds" / "victim",
                             store.root / "worlds")
    if form == "percent_encoded":
        escape = escape.replace("\\", "%5C")
    elif form == "absolute":
        escape = str(outside / "worlds" / "victim")

    response = _client(store).get(
        f"/worlds/{escape}/geometry/manifest", params={"session_id": "vs"}
    )

    assert response.status_code == 404, response.text[:200]


def test_a_non_canonical_world_id_is_answered_under_its_real_name(
    derived_world,
):
    """Contained is not the same as canonical.

    `junk\\..\\<real>` names a world inside the root, so the containment
    rule admits it -- correctly. But the reply must not echo the caller's
    spelling, or two requests for one world answer with two different
    identities, and the caller chooses how long that identity is.

    Asserted at the ADAPTER, not over HTTP. An earlier version of this
    test used `/worlds/junk/../<id>/...` and passed vacuously, because
    httpx normalises `/../` out of a URL path before the request is ever
    sent -- the route saw the plain id and the bug was untouched. A
    BACKSLASH is what actually reaches the store on Windows, and the
    adapter is where both builders assemble the payload.
    """
    from tower.results.world_builder_geometry import build_manifest, build_segment

    store, world_id, session_id = derived_world

    for spelling in (f"junk\\..\\{world_id}", f"junk/../{world_id}"):
        manifest = build_manifest(store, spelling, session_id)
        assert manifest is not None, spelling
        assert manifest["world_id"] == world_id, spelling

        # A chunk carries no `world_id` of its own -- it is addressed by
        # the manifest that named it -- so the assertion here is only that
        # the non-canonical spelling still RESOLVES to the same geometry.
        chunk = build_segment(store, spelling, session_id, 0)
        assert chunk is not None, spelling
        assert chunk["content_hash"] == (
            build_segment(store, world_id, session_id, 0)["content_hash"]
        ), spelling


def test_a_session_directory_that_is_a_junction_is_still_served(
    derived_world, tmp_path
):
    """Containment must not refuse a legitimate reparse point.

    `resolve()` resolves the LEAF too, so a session directory that is a
    junction resolved to its target and compared unequal against the
    derived root -- refusing real geometry. Resolving the PARENT keeps the
    guard exactly as tight (an escaping value still moves the parent)
    without following the last component.
    """
    import subprocess

    store, world_id, session_id = derived_world
    real = tmp_path / "elsewhere" / "linked_session"
    _plant_derived_tree(real)
    link = store.derived_dir(world_id) / "junctioned"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:  # pragma: no cover - needs the privilege
        pytest.skip(f"could not create a junction: {result.stderr.strip()}")

    from tower.results.world_builder_geometry import _read

    assert _read(store, world_id, "junctioned") is not None, (
        "a junctioned session directory was refused as if it had escaped"
    )


def test_one_worlds_geometry_cannot_be_served_under_another_worlds_identity(
    derived_world,
):
    """Containment alone is not enough: the session must be THIS world's.

    This value never leaves the world root, so a guard that only checked
    containment would pass it -- and the reply would carry the SECOND
    world's poses and points under the FIRST world's `world_id`, which is a
    correctness defect as much as a disclosure one.
    """
    store, world_id, session_id = derived_world

    # A second world, inside the same root, with its own derived tree.
    other_id = "w_other"
    store.write_world(World(world_id=other_id, created_at=1.0, updated_at=2.0,
                            session_ids=(session_id,)))
    store.write_session(Session(session_id=session_id, world_id=other_id,
                                started_at=1.0, ended_at=2.0))
    _plant_derived_tree(store.derived_dir(other_id) / session_id)

    escape = os.path.relpath(
        store.derived_dir(other_id) / session_id, store.derived_dir(world_id)
    )
    response = _client(store).get(
        f"/worlds/{world_id}/geometry/manifest", params={"session_id": escape}
    )

    assert response.status_code == 404
