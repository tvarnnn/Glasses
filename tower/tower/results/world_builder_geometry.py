"""Geometry transport adapter for World Builder.

The third file permitted to import `world_builder`, and named after its
cartridge for the same reason `tower/results/world_builder.py` is: an
adapter named after one cartridge cannot leak that cartridge's
assumptions into the next, because the next one gets its own file.

Why geometry does not travel on the result channel: `tower/routes/ws.py`
gives the result sender and the frame path a single `asyncio.Lock`, and
one real session's `points.json` is 1.07 MB against a 3,884-byte status
snapshot. Bulk data there would starve `frame_result`.

Why the segment is the unit: `engine.py:767` freezes a segment when
tracking is lost, so a closed segment is fetched once and cached for the
life of the world. Only the open segment churns.
"""

import hashlib
import json
from collections import Counter

from tower.world_builder.records import World
from tower.world_builder.schema import POSE_CONVENTION
from tower.world_builder.store import (
    WorldStore,
    WorldStoreError,
    compute_input_digest,
)

GEOMETRY_CONTRACT = "world_builder.geometry/2026-08-25"

# Statuses that are neither measured evidence nor a segment origin. Their
# degeneracy is the only place the reason for a refusal survives.
_REFUSED = ("unavailable", "rotation_only")


def segment_content_hash(poses: list[dict], points: list[dict]) -> str:
    """A stable, opaque identity for one segment's geometry.

    Truncated to 16 hex characters, matching `compute_revision`. This is a
    change detector, not a security primitive: the client compares it for
    equality and nothing else.
    """
    canonical = json.dumps(
        {"poses": poses, "points": points}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _bounds(points: list[dict]) -> dict | None:
    if not points:
        return None
    xyz = [p["xyz"] for p in points]
    return {
        "min": [min(v[i] for v in xyz) for i in range(3)],
        "max": [max(v[i] for v in xyz) for i in range(3)],
    }


def _dominant_degeneracy(poses: list[dict]) -> str | None:
    reasons = Counter(
        p["degeneracy"] for p in poses
        if p.get("status") in _REFUSED and p.get("degeneracy")
    )
    if not reasons:
        return None
    return reasons.most_common(1)[0][0]


def _grouped(derived: dict) -> dict[int, dict]:
    """Split the session's derived rows into per-segment buckets.

    Both files already carry `segment_index`, because segments share
    neither a coordinate frame nor a unit and an untagged row could not be
    placed.
    """
    segments: dict[int, dict] = {}
    for pose in derived["poses"]:
        segments.setdefault(
            pose["segment_index"], {"poses": [], "points": []}
        )["poses"].append(pose)
    for point in derived["points"]:
        segments.setdefault(
            point["segment_index"], {"poses": [], "points": []}
        )["points"].append(point)
    return segments


def _revision_over(hashes: list[str]) -> str:
    """A rollup identity for the whole session's geometry.

    Separate from `segment_content_hash` on purpose: that function's input
    IS a segment, and reusing it here would hash fabricated rows and claim
    they were geometry.
    """
    canonical = json.dumps(hashes, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def store_from_root(root) -> WorldStore:
    """Construct a `WorldStore` for a configured world root.

    Lives here, not in `tower/routes/geometry.py`, so the route imports
    only this adapter and never reaches `tower.world_builder` directly --
    the same rule that keeps `tower/results/world_builder.py` as the sole
    place outside this file that knows a `WorldStore` exists.
    """
    return WorldStore(root)


def _is_current(store, world_id: str, session_id: str) -> bool:
    """Whether the derived tree reflects every keyframe accepted so far.

    False is NORMAL during a walk: the digest moves with every keyframe, so
    a build finishes and the next keyframe puts it behind.
    """
    try:
        digest = compute_input_digest(store.read_keyframes(world_id, session_id))
    except (WorldStoreError, KeyError, ValueError, OSError):
        return False
    return store.derived_is_current(world_id, digest)


def _read(store, world_id: str, session_id: str):
    """Return `(world, derived, grouped, current)` or `None` if absent.

    The digest is deliberately NOT verified on the read, and currency is
    computed alongside instead. `read_derived`'s default treats a tree that
    no longer matches the journal as absent, and on this channel that was
    the wrong trade: during a live walk the digest moves with every
    keyframe, so every manifest request answered 404 and the fragment
    gallery stayed empty until the session ended -- while real geometry sat
    on disk the whole time.

    `tower/results/world_builder.py:1058` already made this decision for
    the status channel, for exactly the same reason and in the same words:
    a build over the first N keyframes is not wrong, it is a correct answer
    to an older question. Hiding it discards true information; serving it
    unflagged would let a viewer mistake it for the finished world. The
    `current` flag is the whole difference, and it rides on the manifest
    AND on every chunk, so a client holding only a chunk still knows.

    Absent stays distinguishable from behind: a tree with no poses.json is
    still `None`, and the routes still answer 404 for it.
    """
    try:
        world: World = store.read_world(world_id)
    except WorldStoreError:
        return None
    derived = store.read_derived(world_id, session_id, verify=False)
    if derived is None:
        return None
    current = _is_current(store, world_id, session_id)
    return world, derived, _grouped(derived), current


def build_manifest(store, world_id: str, session_id: str) -> dict | None:
    read = _read(store, world_id, session_id)
    if read is None:
        return None
    world, _, grouped, current = read

    segments = []
    for index in sorted(grouped):
        poses = grouped[index]["poses"]
        points = grouped[index]["points"]
        segments.append({
            "segment_index": index,
            "content_hash": segment_content_hash(poses, points),
            "frame_id": f"segment:{index}",
            # Nothing registers segments yet. When it does, this flips and
            # `transform_to_world` carries a Sim3 -- and because the
            # segment's own geometry does not move, every cached
            # content_hash stays valid across that change.
            "registered": False,
            "transform_to_world": None,
            "resolution_state": "resolved" if points else "unresolved",
            "dominant_degeneracy": _dominant_degeneracy(poses),
            "keyframe_count": len(poses),
            "solved_count": sum(1 for p in poses if p.get("status") == "solved"),
            "point_count": len(points),
            "bounds": _bounds(points),
        })

    return {
        "contract": GEOMETRY_CONTRACT,
        "world_id": world_id,
        "session_id": session_id,
        # Additive, and deliberately not a contract bump: CARTRIDGE-RESULTS
        # section 12 says a field an older decoder ignores is not grounds
        # for one. False means "this geometry is real, and behind the
        # newest keyframes" -- the normal state during a walk.
        "current": current,
        "geometry_revision": _revision_over([s["content_hash"] for s in segments]),
        "pose_convention": dict(world.pose_convention or POSE_CONVENTION),
        "scale": {
            "state": world.scale.state,
            "meters_per_unit": world.scale.meters_per_unit,
        },
        "segment_count": len(segments),
        "segments": segments,
    }


def build_segment(
    store, world_id: str, session_id: str, segment_index: int,
    max_points: int | None = None,
) -> dict | None:
    """One segment's geometry, in its own frame.

    `max_points` exists so a budget lever is available without a contract
    change. It defaults to unlimited: the largest segment on the real walk
    is 3,033 points, and because a closed segment is fetched exactly once
    that is a one-time cost rather than a per-revision one.
    """
    read = _read(store, world_id, session_id)
    if read is None:
        return None
    _, _, grouped, current = read
    if segment_index not in grouped:
        return None

    poses = grouped[segment_index]["poses"]
    points = grouped[segment_index]["points"]
    # Hash the WHOLE segment before sampling: the hash identifies the
    # segment, not this transfer, so a client that sampled once and
    # refetches in full must not see a changed identity.
    content_hash = segment_content_hash(poses, points)

    total = len(points)
    sampling = "none"
    sent = points
    if max_points is not None:
        if max_points < 1:
            raise ValueError("max_points must be at least 1")
        if total > max_points:
            # Evenly spaced across the WHOLE cloud, never a prefix: a prefix
            # is one corner of the room and would read as a smaller world
            # rather than a coarser one.
            #
            # An INTEGER stride cannot do this. `total // max_points`
            # collapses to 1 whenever max_points > total/2 -- so capping
            # 3,033 points at 2,000 would return points[0:2000], which is
            # exactly the truncation this comment claims to avoid.
            step = total / max_points
            sent = [points[int(i * step)] for i in range(max_points)]
            sampling = "stride"

    return {
        "contract": GEOMETRY_CONTRACT,
        # Repeated from the manifest on purpose: a client that fetched one
        # chunk from cache and never re-read the manifest would otherwise
        # have no way to know the geometry in its hand is behind.
        "current": current,
        "segment_index": segment_index,
        "content_hash": content_hash,
        "frame_id": f"segment:{segment_index}",
        "registered": False,
        "transform_to_world": None,
        "poses": [
            {
                "keyframe_id": p["keyframe_id"],
                "status": p["status"],
                "degeneracy": p["degeneracy"],
                "rotation": p["rotation"],
                "translation": p["translation"],
            }
            for p in poses
        ],
        "points": [p["xyz"] for p in sent],
        "points_sent": len(sent),
        "points_total": total,
        "point_sampling": sampling,
    }
