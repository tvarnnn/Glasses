"""Segment placements: registration results, persisted and served.

Registration has existed as an offline script that "reads a world and
writes nothing into it". The served contract carried `registered: false`
and `transform_to_world: null` as literals, so a world with a genuine
registered cluster looked identical on the wire to one with none.

That mattered once the cluster became real: on capture `2e6cffa2`
registration places 3 of 29 segments carrying 1,917 of 4,317 points (44%),
and on `e1c52b9f` 3 of 10 carrying 5,603 of 22,520 (25%). None of it was
visible to anything downstream.

THE CACHE TRAP THIS ALSO CLOSES. `content_hash` deliberately covers only
poses and points, and the geometry-revision rollup is a hash of content
hashes. So a segment that gains a placement without its points changing
keeps its hash, and a client holding a cached chunk would never refetch --
drawing an unplaced version of a segment the world now knows how to place.
`placement_hash` exists so that state is expressible; a client keys its
cache on the pair.
"""

import pytest

from tower.world_builder.records import SegmentPlacement
from tower.world_builder.store import WorldStore


def _placement(**over):
    base = dict(
        segment_index=0,
        state="registered",
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        translation=(0.0, 0.0, 0.0),
        scale=1.0,
        reference_segment=0,
        refusal_reason=None,
        evidence={"reciprocity": 0.97},
    )
    base.update(over)
    return SegmentPlacement(**base)


def test_placements_round_trip(tmp_path):
    store = WorldStore(tmp_path)
    world_id, session_id = "w" * 32, "s" * 32
    rows = [
        _placement(segment_index=0),
        _placement(
            segment_index=1,
            state="refused",
            rotation_wxyz=None,
            translation=None,
            scale=None,
            reference_segment=None,
            refusal_reason="the wearer stood still",
            evidence={"span_over_depth": 0.02},
        ),
    ]
    store.write_placements(world_id, session_id, rows)
    read = store.read_placements(world_id, session_id)

    assert read is not None
    assert [r.segment_index for r in read] == [0, 1]
    assert read[0].state == "registered"
    assert read[0].scale == 1.0
    assert read[1].state == "refused"
    assert read[1].scale is None
    assert read[1].refusal_reason == "the wearer stood still"


def test_absent_placements_are_absent_not_an_error(tmp_path):
    """Every world built before this existed has no placements file, and
    a reconstruction is complete without one. Absent must never be an
    error, and never a reason to refuse poses and points."""
    store = WorldStore(tmp_path)
    assert store.read_placements("w" * 32, "s" * 32) is None


def test_unreadable_placements_are_treated_as_absent(tmp_path):
    """Same rule support.json follows. A truncated index beside the
    reconstruction does not make the reconstruction wrong, and refusing
    the world over it would turn an optional file into a hard dependency
    through the back door."""
    store = WorldStore(tmp_path)
    world_id, session_id = "w" * 32, "s" * 32
    store.write_placements(world_id, session_id, [_placement()])
    path = store.derived_dir(world_id) / session_id / "placements.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert store.read_placements(world_id, session_id) is None


def test_a_refused_placement_cannot_carry_a_transform():
    """A refusal that shipped a transform would be drawn. The record
    refuses to represent that state at all."""
    with pytest.raises(ValueError, match="refused"):
        SegmentPlacement(
            segment_index=0,
            state="refused",
            rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
            translation=(0.0, 0.0, 0.0),
            scale=1.0,
            reference_segment=0,
            refusal_reason="whatever",
            evidence={},
        )


def test_a_registered_placement_must_carry_a_complete_transform():
    """Half a Sim3 is not a placement. A missing scale would default to
    something somewhere, and that somewhere would be wrong."""
    with pytest.raises(ValueError, match="registered"):
        SegmentPlacement(
            segment_index=0,
            state="registered",
            rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
            translation=(0.0, 0.0, 0.0),
            scale=None,
            reference_segment=0,
            refusal_reason=None,
            evidence={},
        )


def test_state_vocabulary_is_closed():
    """Consumers switch on it, so an unknown state must not reach disk."""
    with pytest.raises(ValueError, match="state"):
        SegmentPlacement(
            segment_index=0,
            state="probably",
            rotation_wxyz=None,
            translation=None,
            scale=None,
            reference_segment=None,
            refusal_reason=None,
            evidence={},
        )


def test_scale_must_be_positive_and_finite():
    """A zero scale collapses a segment to a dot at another's origin --
    the failure the registration research calls out as invisible in every
    aggregate metric. It must not be storable."""
    for bad in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="scale"):
            SegmentPlacement(
                segment_index=0,
                state="registered",
                rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
                translation=(0.0, 0.0, 0.0),
                scale=bad,
                reference_segment=0,
                refusal_reason=None,
                evidence={},
            )


# ---------------------------------------------------------------------------
# The served contract.
# ---------------------------------------------------------------------------


def _tiny_world(store, world_id="w" * 32, session_id="s" * 32):
    """A two-segment derived tree, written directly."""
    from tower.world_builder.records import CameraIntrinsics, ScaleState, World

    world = World(
        world_id=world_id,
        created_at=0.0,
        updated_at=0.0,
        display_name=None,
        scale=ScaleState(state="unknown"),
        session_ids=(session_id,),
    )
    store.write_world(world)
    poses = [
        {"keyframe_id": "k0", "segment_index": 0, "status": "anchor",
         "degeneracy": "", "rotation": None, "translation": None},
        {"keyframe_id": "k1", "segment_index": 1, "status": "anchor",
         "degeneracy": "", "rotation": None, "translation": None},
    ]
    points = [
        {"segment_index": 0, "xyz": [0.0, 0.0, 1.0]},
        {"segment_index": 1, "xyz": [1.0, 0.0, 1.0]},
    ]
    store.write_derived(
        world_id, session_id, poses=poses, points=points,
        manifest={"session_id": session_id, "input_digest": "x"},
    )
    return world_id, session_id


def test_an_unplaced_segment_is_distinguishable_from_a_refused_one(tmp_path):
    """`registered: false` alone conflated 'we tried and the two solves
    disagreed' with 'nobody looked'. On the real corpus the refusal is
    usually 'the wearer stood still', which is a message about how to
    walk -- losing it loses the only actionable part."""
    from tower.results import world_builder_geometry as adapter

    store = WorldStore(tmp_path)
    world_id, session_id = _tiny_world(store)

    manifest = adapter.build_manifest(store, world_id, session_id)
    assert manifest["segments"][0]["registration_state"] == "unplaced"

    store.write_placements(world_id, session_id, [
        _placement(
            segment_index=0, state="refused", rotation_wxyz=None,
            translation=None, scale=None, reference_segment=None,
            refusal_reason="the wearer stood still", evidence={},
        ),
    ])
    manifest = adapter.build_manifest(store, world_id, session_id)
    row = manifest["segments"][0]
    assert row["registration_state"] == "refused"
    assert row["registered"] is False
    assert row["registration_refusal_reason"] == "the wearer stood still"


def test_a_registered_segment_serves_its_transform(tmp_path):
    from tower.results import world_builder_geometry as adapter

    store = WorldStore(tmp_path)
    world_id, session_id = _tiny_world(store)
    store.write_placements(world_id, session_id, [
        _placement(segment_index=0, scale=2.5, reference_segment=1),
    ])

    row = adapter.build_manifest(store, world_id, session_id)["segments"][0]
    assert row["registered"] is True
    assert row["registration_state"] == "registered"
    assert row["transform_to_world"]["scale"] == 2.5
    assert row["transform_to_world"]["reference_segment"] == 1

    chunk = adapter.build_segment(store, world_id, session_id, 0)
    assert chunk["registered"] is True
    assert chunk["transform_to_world"]["scale"] == 2.5


def test_a_placement_change_invalidates_the_cache(tmp_path):
    """THE TRAP THIS CLOSES.

    `content_hash` covers poses and points only, so a segment that gains
    a placement keeps its content hash -- by design, so cached geometry
    stays valid. That is safe ONLY because placement_hash changes
    instead. Without it a client would hold a cached chunk forever and
    draw an unplaced version of a segment the world knows how to place,
    and the old test suite could not catch it because the fields it
    checked were literals.
    """
    from tower.results import world_builder_geometry as adapter

    store = WorldStore(tmp_path)
    world_id, session_id = _tiny_world(store)

    before = adapter.build_manifest(store, world_id, session_id)
    store.write_placements(world_id, session_id, [
        _placement(segment_index=0, scale=2.5),
    ])
    after = adapter.build_manifest(store, world_id, session_id)

    row_before, row_after = before["segments"][0], after["segments"][0]
    assert row_before["content_hash"] == row_after["content_hash"], (
        "the geometry did not move, so its content hash must not"
    )
    assert row_before["placement_hash"] != row_after["placement_hash"], (
        "the placement DID move, so a client must be told"
    )
    assert before["geometry_revision"] != after["geometry_revision"], (
        "a placement-only change must move the rollup, or nothing "
        "downstream ever refetches"
    )


def test_the_rollup_still_moves_when_only_geometry_changes(tmp_path):
    """The other direction, so the rollup is not merely placement-sensitive."""
    from tower.results import world_builder_geometry as adapter

    store = WorldStore(tmp_path)
    world_id, session_id = _tiny_world(store)
    before = adapter.build_manifest(store, world_id, session_id)

    store.write_derived(
        world_id, session_id,
        poses=[{"keyframe_id": "k0", "segment_index": 0, "status": "anchor",
                "degeneracy": "", "rotation": None, "translation": None}],
        points=[{"segment_index": 0, "xyz": [9.0, 9.0, 9.0]}],
        manifest={"session_id": session_id, "input_digest": "x"},
    )
    after = adapter.build_manifest(store, world_id, session_id)
    assert before["geometry_revision"] != after["geometry_revision"]
