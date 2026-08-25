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
from tower.world_builder.store import WorldStoreError

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


def _read(store, world_id: str, session_id: str):
    """Return `(world, derived, grouped)` or `None` if anything is absent.

    `read_derived` verifies the input digest, so a stale tree comes back as
    absent -- which is the honest outcome, since both mean "rebuild".
    """
    try:
        world: World = store.read_world(world_id)
    except WorldStoreError:
        return None
    derived = store.read_derived(world_id, session_id)
    if derived is None:
        return None
    return world, derived, _grouped(derived)


def build_manifest(store, world_id: str, session_id: str) -> dict | None:
    read = _read(store, world_id, session_id)
    if read is None:
        return None
    world, _, grouped = read

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
    _, _, grouped = read
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
