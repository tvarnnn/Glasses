# World Builder Geometry Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move World Builder's reconstructed geometry from the Tower's disk to a
truthful iOS viewer, without ever placing two unregistered segments in one
coordinate space.

**Architecture:** The status WebSocket keeps carrying only its existing
`geometry.revision` as a change signal. Geometry itself is fetched over new HTTP
routes, chunked one-per-segment and content-hashed, so frozen segments transfer
exactly once and live cost is O(1) in walk length. iOS renders each unregistered
segment as its own framed fragment.

**Tech Stack:** Python 3 / FastAPI / pytest on the Tower; Swift 5 / SwiftUI /
XCTest on iOS. No new dependencies on either side.

**Spec:** `tower/docs/superpowers/specs/2026-08-25-world-builder-geometry-transport-design.md`

## Global Constraints

- **Contract identifier, exact:** `world_builder.geometry/2026-08-25`
- **Geometry never travels on the WebSocket.** `tower/routes/ws.py:38` shares one
  `asyncio.Lock` with the frame path.
- **The status payload gains no field.** It is bounded by
  `test_result_channel_protocol.py:142-153` (`len(node) <= 16`).
- **`null` means absent, never zero.** Applies on the wire and all the way to the
  screen.
- **`translation: null` must survive to the renderer**, which draws a break.
- **`registered: false` forbids compositing two segments into one space.**
- **No new Python dependencies.** Only `cv2` 5.0.0 and `numpy` 2.5.2 are
  installed. `torch`, `scipy`, `sklearn`, `pycolmap`, `onnxruntime` are all
  absent.
- **No imagery crosses the wire, ever.** `image_relpath` and keyframe bytes stay
  Tower-side.
- **Tower commands run from `tower/`**, using `./.venv/Scripts/python.exe -m pytest`.
  Do **not** pass `--timeout`; `pytest-timeout` is not installed and the
  unrecognised argument aborts collection before any test runs.
- **iOS is BUILD UNVERIFIED.** There is no Swift toolchain on this machine
  (`xcodebuild`, `swift`, `swiftc` all absent). Every iOS commit message and any
  report must say so. Never write "tests pass" for iOS work done here.
- **Paths in this plan are repo-root-relative** (`C:\Users\tvllo\Projects\Glasses`).
  The Python package is at `tower/tower/`; its tests are at `tower/tests/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `tower/tower/results/world_builder_geometry.py` | **New.** The geometry adapter — the third named file permitted to import `world_builder`. Groups derived rows by segment, computes content hashes, assembles manifest and chunk payloads. Pure functions over a `WorldStore`; knows nothing about HTTP. |
| `tower/tower/routes/geometry.py` | **New.** Thin FastAPI route. Imports the adapter only. Declared with `def` (not `async def`) so FastAPI runs it in a threadpool, keeping disk reads and hashing off the event loop. |
| `tower/tower/main.py` | **Modify.** Register the new router. |
| `tower/tests/test_world_builder_derived_schema.py` | **New.** Pins the on-disk shape of `poses.json`, `points.json` and `derived/manifest.json` before they become a wire contract. |
| `tower/tests/test_world_builder_geometry_transport.py` | **New.** The adapter and route behaviour. |
| `tower/tests/test_architecture_boundaries.py` | **Modify.** Add the adapter to `_RESULT_CHANNEL_ADAPTERS`, deliberately and under review. |
| `tower/tower/results/world_builder.py` | **Modify.** Remove the repudiated `pose_count` fallback (`:1459-1468`). |
| `ios/Glasses/Workspaces/WorldBuilder/WorldGeometry.swift` | **New.** Contract types + decoder. Pure, no networking. |
| `ios/Glasses/Workspaces/WorldBuilder/WorldGeometryClient.swift` | **New.** `URLSession` fetch + content-hash cache. |
| `ios/Glasses/Workspaces/WorldBuilder/WorldFragmentsView.swift` | **New.** The small-multiples `Canvas` renderer and the three-state presentation. |
| `ios/Glasses/Workspaces/WorldBuilder/TowerWorldBuilderClient.swift` | **Modify.** Bump the pinned status contract to `/2026-08-25`. |
| `ios/GlassesTests/WorldGeometryTests.swift` | **New.** Decoder, cache and truthfulness tests. |

---

## Task 1: Pin the derived artifact schemas

These three files are about to become a wire contract and currently have **zero**
test coverage — no test in the repository names `poses.json` or `points.json`.
Pin them first so the transport is built on a fixed shape.

**Files:**
- Test: `tower/tests/test_world_builder_derived_schema.py` (create)

**Interfaces:**
- Consumes: `WorldStore` from `tower.world_builder.store`; `World`, `Session`,
  `Keyframe` from `tower.world_builder.records`.
- Produces: `derived_world(tmp_path)` fixture reused by Task 2 and Task 3, which
  returns `(store, world_id, session_id)` for a two-segment world whose derived
  tree passes `read_derived`'s digest verification.

- [ ] **Step 1: Write the failing test**

Create `tower/tests/test_world_builder_derived_schema.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

```
cd tower
./.venv/Scripts/python.exe -m pytest tests/test_world_builder_derived_schema.py -v
```

Expected: collection succeeds and tests fail or error — most likely
`ImportError` on `compute_input_digest` if it is not exported at module level, or
a fixture error. **Read the actual failure before changing anything.** If every
test passes on the first run, the fixture is wrong: confirm
`test_the_fixture_survives_digest_verification` is genuinely exercising
`read_derived`'s verification and not short-circuiting.

- [ ] **Step 3: Fix only the fixture, not the production code**

This task adds no production code. If an import fails, correct the import to
match what `tower/tower/world_builder/store.py` actually exports (check with
`grep -n "^def compute_input_digest\|^from\|^import" tower/world_builder/store.py`).
If the digest does not verify, the cause is the order or content of
`append_keyframe` calls versus `compute_input_digest` — align them; do not pass
`verify=False` to make the test green, because that would defeat the point.

- [ ] **Step 4: Run the tests to verify they pass**

```
cd tower
./.venv/Scripts/python.exe -m pytest tests/test_world_builder_derived_schema.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tower/tests/test_world_builder_derived_schema.py
git commit -m "test: pin the derived artifacts before they become a wire contract

poses.json and points.json had no test naming them. Their key sets, the
wxyz order, the dtypes and the difference between null and zero were all
unpinned -- and a phone is about to render them."
```

---

## Task 2: Segment grouping, content hashes and the manifest

**Files:**
- Create: `tower/tower/results/world_builder_geometry.py`
- Test: `tower/tests/test_world_builder_geometry_transport.py` (create)

**Interfaces:**
- Consumes: `derived_world` fixture from Task 1 (import it via a shared
  `conftest.py` or redefine locally — see Step 1).
- Produces:
  - `GEOMETRY_CONTRACT: str = "world_builder.geometry/2026-08-25"`
  - `segment_content_hash(poses: list[dict], points: list[dict]) -> str`
  - `build_manifest(store, world_id: str, session_id: str) -> dict | None`

- [ ] **Step 1: Write the failing test**

Create `tower/tests/test_world_builder_geometry_transport.py`. It reuses Task 1's
fixture, so move that fixture into `tower/tests/conftest.py` first: cut
`_keyframe` and `derived_world` from the Task 1 file into `conftest.py` (keeping
the same imports), and add a fixture that exposes the keyframe builder, since a
`conftest.py` helper cannot be imported by name from a test module:

```python
@pytest.fixture
def keyframe_factory():
    """`_keyframe` as a fixture, because conftest is not an importable module."""
    return _keyframe
```

Then delete the now-duplicated `derived_world` and `_keyframe` definitions from
`test_world_builder_derived_schema.py` and re-run that file to confirm pytest
still injects the fixture (6 passed).

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

```
cd tower
./.venv/Scripts/python.exe -m pytest tests/test_world_builder_geometry_transport.py -v
```

Expected: `ModuleNotFoundError: No module named 'tower.results.world_builder_geometry'`.

- [ ] **Step 3: Write the adapter**

Create `tower/tower/results/world_builder_geometry.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```
cd tower
./.venv/Scripts/python.exe -m pytest tests/test_world_builder_geometry_transport.py -v
```

Expected: 10 passed. If `world.scale.state` raises, check `ScaleState`'s actual
attribute names in `tower/tower/world_builder/records.py:39` and use those.

- [ ] **Step 5: Commit**

```bash
git add tower/tower/results/world_builder_geometry.py \
        tower/tests/test_world_builder_geometry_transport.py \
        tower/tests/conftest.py tower/tests/test_world_builder_derived_schema.py
git commit -m "feat: group geometry by segment, and hash each one

The segment is already the coordinate-frame boundary, so it is also the
cache unit: engine.py:767 freezes one when tracking is lost, which makes
a closed segment fetchable exactly once.

Empty segments are reported rather than dropped. On the real walk 32 of
51 resolved to nothing, and that is the difference between 'we did not
look' and 'we looked and failed'."
```

---

## Task 3: Segment chunks and point sampling

**Files:**
- Modify: `tower/tower/results/world_builder_geometry.py`
- Test: `tower/tests/test_world_builder_geometry_transport.py` (append)

**Interfaces:**
- Consumes: `_read`, `segment_content_hash` from Task 2.
- Produces: `build_segment(store, world_id, session_id, segment_index, max_points=None) -> dict | None`

- [ ] **Step 1: Write the failing test**

Append to `tower/tests/test_world_builder_geometry_transport.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

```
cd tower
./.venv/Scripts/python.exe -m pytest tests/test_world_builder_geometry_transport.py -k chunk -v
```

Expected: `ImportError: cannot import name 'build_segment'`.

- [ ] **Step 3: Add `build_segment`**

Append to `tower/tower/results/world_builder_geometry.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```
cd tower
./.venv/Scripts/python.exe -m pytest tests/test_world_builder_geometry_transport.py -v
```

Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add tower/tower/results/world_builder_geometry.py \
        tower/tests/test_world_builder_geometry_transport.py
git commit -m "feat: per-segment geometry chunks, with sampling that admits itself

Sampling strides rather than truncates: a prefix of a point cloud is one
corner of the room and would read as a smaller world rather than a
coarser one. points_sent and points_total always travel, so a partial
cloud can never be mistaken for the whole one."
```

---

## Task 4: The HTTP routes

**Files:**
- Create: `tower/tower/routes/geometry.py`
- Modify: `tower/tower/main.py` (import and `include_router`)
- Modify: `tower/tests/test_architecture_boundaries.py:71-76` (`_RESULT_CHANNEL_ADAPTERS`)
- Test: `tower/tests/test_world_builder_geometry_transport.py` (append)

**Interfaces:**
- Consumes: `build_manifest`, `build_segment` from Tasks 2–3.
- Produces: `GET /worlds/{world_id}/geometry/manifest?session_id=…` and
  `GET /worlds/{world_id}/geometry/segment/{segment_index}?session_id=…&max_points=…`

- [ ] **Step 1: Write the failing test**

Append to `tower/tests/test_world_builder_geometry_transport.py`:

```python
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


def test_the_routes_are_sync_so_fastapi_runs_them_off_the_event_loop():
    """A 1 MB read plus a hash must never block the frame path.

    A `def` endpoint is run in FastAPI's threadpool; an `async def` one is
    not. This is the whole mechanism, so it is pinned.
    """
    import inspect

    assert not inspect.iscoroutinefunction(geometry_routes.geometry_manifest)
    assert not inspect.iscoroutinefunction(geometry_routes.geometry_segment)
```

- [ ] **Step 2: Run the test to verify it fails**

```
cd tower
./.venv/Scripts/python.exe -m pytest tests/test_world_builder_geometry_transport.py -k route -v
```

Expected: `ImportError: cannot import name 'geometry' from 'tower.routes'`.

- [ ] **Step 3: Write the route**

Create `tower/tower/routes/geometry.py`:

```python
"""World Builder geometry, over HTTP.

HTTP and not the WebSocket, for a reason that is in the code rather than
in taste: `tower/routes/ws.py` gives the result sender and the frame path
one shared `asyncio.Lock`. One session's `points.json` is 1.07 MB against
a 3,884-byte status snapshot, so pushing geometry down that socket would
hold the lock and starve `frame_result` -- the exact thing
`CARTRIDGE-RESULTS.md` forbids in Tower responsibility #3.

Both handlers are declared `def` rather than `async def` on purpose.
FastAPI runs a sync endpoint in its threadpool, which keeps the disk read
and the hash off the event loop with no executor of our own.
"""

from fastapi import APIRouter, HTTPException, Request

from tower.results.world_builder_geometry import build_manifest, build_segment
from tower.world_builder.store import WorldStore

router = APIRouter()


def _store(request: Request) -> WorldStore:
    root = getattr(request.app.state, "world_root", None)
    if root is None:
        raise HTTPException(status_code=404, detail="no world root is configured")
    return WorldStore(root)


@router.get("/worlds/{world_id}/geometry/manifest")
def geometry_manifest(world_id: str, session_id: str, request: Request) -> dict:
    manifest = build_manifest(_store(request), world_id, session_id)
    if manifest is None:
        # Absent and stale are deliberately the same answer: both mean
        # "there is nothing here you may render".
        raise HTTPException(status_code=404, detail="no current geometry")
    return manifest


@router.get("/worlds/{world_id}/geometry/segment/{segment_index}")
def geometry_segment(
    world_id: str, segment_index: int, session_id: str, request: Request,
    max_points: int | None = None,
) -> dict:
    chunk = build_segment(
        _store(request), world_id, session_id, segment_index, max_points=max_points
    )
    if chunk is None:
        raise HTTPException(status_code=404, detail="no such segment")
    return chunk
```

- [ ] **Step 4: Register the router**

In `tower/tower/main.py`, change the routes import (currently line 18):

```python
from tower.routes import cartridges, geometry, health, ws
```

and add its registration beside the other `include_router` calls:

```python
app.include_router(geometry.router)
```

Find the existing calls with
`grep -n "include_router" tower/tower/main.py` and add the new line next to them.

- [ ] **Step 5: Widen the architecture boundary, deliberately**

In `tower/tests/test_architecture_boundaries.py`, extend the comment block above
`_RESULT_CHANNEL_ADAPTERS` (currently ending at line 70) with a third entry, and
add the path:

```python
#   tower/results/world_builder_geometry.py
#                                    the geometry adapter for that same
#                                    cartridge. Separate from the status
#                                    adapter because it answers a different
#                                    question over a different transport --
#                                    HTTP, because the status socket shares
#                                    its send lock with the frame path.
_RESULT_CHANNEL_ADAPTERS = frozenset(
    {
        TOWER / "results" / "world_builder.py",
        TOWER / "results" / "world_builder_geometry.py",
        TOWER / "results" / "__init__.py",
    }
)
```

Note `tower/routes/geometry.py` is **not** exempted and must not be: it imports
the adapter, never `world_builder` records. If
`test_shared_code_does_not_import_a_cartridge` fails pointing at the route, the
route has reached past its adapter — fix the route, not the test.

- [ ] **Step 6: Run the full suite**

```
cd tower
./.venv/Scripts/python.exe -m pytest -q
```

Expected: **1208 passed, 32 skipped** (1178 baseline + 6 from Task 1 + 10 from
Task 2 + 8 from Task 3 + 6 from Task 4). Zero failures. Treat the total as an
expectation, not a gate: assert zero failures and record the actual number. If `test_the_result_channel_core_is_cartridge_blind`
fails, read which file it names before touching anything.

- [ ] **Step 7: Commit**

```bash
git add tower/tower/routes/geometry.py tower/tower/main.py \
        tower/tests/test_architecture_boundaries.py \
        tower/tests/test_world_builder_geometry_transport.py
git commit -m "feat: geometry over HTTP, off the socket that carries frames

ws.py hands the result sender and the frame path one asyncio.Lock. A
1.07 MB point cloud there would starve frame_result, so geometry gets its
own transport and the status channel keeps carrying only the revision
that says something moved.

Both handlers are sync on purpose: FastAPI runs those in a threadpool, so
the read and the hash stay off the event loop without an executor."
```

---

## Task 5: Retire the repudiated pose_count fallback

`tower/tower/results/world_builder.py:1459-1468` falls back to
`max(0, keyframes - poses_refused)` when a manifest lacks `poses_positioned` —
the exact arithmetic that put "Camera poses: 36" on the phone and that the
2026-08-25 contract bump exists to repudiate. It still serves under the new
identifier. On the real world the two differ by 32 (113 vs 145).

**Files:**
- Modify: `tower/tower/results/world_builder.py:1459-1468`
- Test: `tower/tests/test_world_builder_geometry_transport.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: no signature change; `pose_count` becomes `None` where it was a guess.

- [ ] **Step 1: Write the failing test**

```python
def test_a_manifest_without_poses_positioned_reports_absent_not_arithmetic(
    derived_world,
):
    """The fallback promoted every segment anchor to a camera pose.

    That is what produced 'Camera poses: 36' from a world with zero solved
    poses. An absent figure is the honest answer; a plausible wrong one is
    the failure the contract bump exists to prevent.
    """
    from tower.results.world_builder import _trajectory_pose_count

    manifest = {"keyframes": 457, "poses_refused": 312, "segments": 51}
    assert _trajectory_pose_count(manifest) is None

    manifest["poses_positioned"] = 113
    assert _trajectory_pose_count(manifest) == 113
```

- [ ] **Step 2: Run the test to verify it fails**

```
cd tower
./.venv/Scripts/python.exe -m pytest tests/test_world_builder_geometry_transport.py -k poses_positioned -v
```

Expected: failure. The helper may not be named `_trajectory_pose_count` — read
`tower/tower/results/world_builder.py:1455-1470` and use the real name, updating
the test to match before proceeding.

- [ ] **Step 3: Remove the fallback**

Replace the fallback branch so a missing `poses_positioned` yields `None` rather
than recomputed arithmetic, with the reason recorded in place:

```python
    # No fallback. The old arithmetic -- keyframes - poses_refused --
    # counted a segment ANCHOR as a camera position, and an anchor is
    # definitional: identity rotation, zero translation, one per segment.
    # That is where "Camera poses: 36" came from on a world whose manifest
    # read poses_solved: 0. A manifest without poses_positioned predates
    # the fix, and absent is the only honest answer for it.
    return manifest.get("poses_positioned")
```

- [ ] **Step 4: Run the full suite**

```
cd tower
./.venv/Scripts/python.exe -m pytest -q
```

Expected: 1209 passed, 32 skipped. If a result-channel truthfulness test fails,
read it — several assert on `pose_count` and one may have encoded the fallback.
If a test asserted the old arithmetic, that test was wrong and should be updated
with a comment saying why.

- [ ] **Step 5: Commit**

```bash
git add tower/tower/results/world_builder.py \
        tower/tests/test_world_builder_geometry_transport.py
git commit -m "fix: stop serving the arithmetic the contract bump repudiated

A manifest without poses_positioned silently fell back to
keyframes - poses_refused, which counts a segment anchor as a camera
position. That is the formula behind 'Camera poses: 36' on a world with
zero solved poses, and it was still being served under the identifier
minted to retire it. Absent is the honest answer."
```

---

## Task 6: iOS geometry contract types and decoder

**BUILD UNVERIFIED.** No Swift toolchain exists here. Write the code and the
tests; do not claim either compiles.

**Files:**
- Create: `ios/Glasses/Workspaces/WorldBuilder/WorldGeometry.swift`
- Test: `ios/GlassesTests/WorldGeometryTests.swift` (create)

**Interfaces:**
- Consumes: nothing from earlier iOS code.
- Produces: `WorldGeometryContract.identifier`, `WorldPoseConvention`,
  `WorldSegmentSummary`, `WorldGeometryManifest`, `WorldSegmentChunk`,
  `WorldGeometryDecoder.manifest(from:)`, `WorldGeometryDecoder.chunk(from:)`

- [ ] **Step 1: Write the failing test**

Create `ios/GlassesTests/WorldGeometryTests.swift`:

```swift
import XCTest
@testable import Glasses

final class WorldGeometryDecoderTests: XCTestCase {

    private func manifestJSON(upAxis: String = "unknown") -> [String: Any] {
        [
            "contract": "world_builder.geometry/2026-08-25",
            "world_id": "w0", "session_id": "s0",
            "geometry_revision": "abc123",
            "pose_convention": [
                "pose_type": "T_world_camera", "quaternion_order": "wxyz",
                "handedness": "right",
                "camera_axes": "opencv_x_right_y_down_z_forward",
                "translation_units": "world",
                "world_axes_origin": "first_keyframe_camera",
                "up_axis": upAxis, "pose_dtype": "float64",
                "point_dtype": "float32",
            ],
            "scale": ["state": "unknown", "meters_per_unit": NSNull()],
            "segment_count": 2,
            "segments": [
                ["segment_index": 0, "content_hash": "h0", "frame_id": "segment:0",
                 "registered": false, "transform_to_world": NSNull(),
                 "resolution_state": "resolved", "dominant_degeneracy": NSNull(),
                 "keyframe_count": 2, "solved_count": 1, "point_count": 2,
                 "bounds": ["min": [-1.0, 0.0, 3.0], "max": [1.0, 2.0, 5.0]]],
                ["segment_index": 1, "content_hash": "h1", "frame_id": "segment:1",
                 "registered": false, "transform_to_world": NSNull(),
                 "resolution_state": "unresolved",
                 "dominant_degeneracy": "low_parallax",
                 "keyframe_count": 2, "solved_count": 0, "point_count": 0,
                 "bounds": NSNull()],
            ],
        ]
    }

    func testAManifestDecodesFieldForField() {
        let manifest = WorldGeometryDecoder.manifest(from: manifestJSON())
        XCTAssertEqual(manifest?.segments.count, 2)
        XCTAssertEqual(manifest?.segments[0].contentHash, "h0")
        XCTAssertEqual(manifest?.segments[0].pointCount, 2)
    }

    func testAnUnresolvedSegmentKeepsNilBoundsRatherThanAZeroBox() {
        let manifest = WorldGeometryDecoder.manifest(from: manifestJSON())
        let unresolved = manifest?.segments[1]
        XCTAssertNil(unresolved?.bounds)
        XCTAssertEqual(unresolved?.resolutionState, .unresolved)
        XCTAssertEqual(unresolved?.dominantDegeneracy, "low_parallax")
    }

    func testAPoseConventionMismatchIsRefused() {
        // Inverting T_world_camera still draws a plausible map. That was a
        // real shipped bug, so any mismatch refuses rather than renders.
        var json = manifestJSON()
        var convention = json["pose_convention"] as! [String: Any]
        convention["quaternion_order"] = "xyzw"
        json["pose_convention"] = convention

        let manifest = WorldGeometryDecoder.manifest(from: json)
        XCTAssertNotNil(manifest, "a mismatch decodes; it is the RENDER that refuses")
        XCTAssertFalse(manifest!.poseConvention.matchesThisBuild)
    }

    func testTheExpectedConventionIsAcceptedIncludingUnknownUpAxis() {
        let manifest = WorldGeometryDecoder.manifest(from: manifestJSON())
        XCTAssertTrue(manifest!.poseConvention.matchesThisBuild)
    }

    func testAWrongContractIdentifierIsRefused() {
        var json = manifestJSON()
        json["contract"] = "world_builder.geometry/2027-01-01"
        XCTAssertNil(WorldGeometryDecoder.manifest(from: json))
    }

    func testARefusedPoseDecodesAsNilTranslationNotZero() {
        let json: [String: Any] = [
            "contract": "world_builder.geometry/2026-08-25",
            "segment_index": 1, "content_hash": "h1", "frame_id": "segment:1",
            "registered": false, "transform_to_world": NSNull(),
            "poses": [
                ["keyframe_id": "s0:1", "status": "anchor", "degeneracy": "",
                 "rotation": [1.0, 0.0, 0.0, 0.0], "translation": [0.0, 0.0, 0.0]],
                ["keyframe_id": "s0:2", "status": "unavailable",
                 "degeneracy": "low_parallax",
                 "rotation": NSNull(), "translation": NSNull()],
            ],
            "points": [], "points_sent": 0, "points_total": 0,
            "point_sampling": "none",
        ]

        let chunk = WorldGeometryDecoder.chunk(from: json)
        XCTAssertNil(chunk?.poses[1].translation)
        XCTAssertNotNil(chunk?.poses[0].translation)
    }

    func testASampledChunkKnowsItIsPartial() {
        let json: [String: Any] = [
            "contract": "world_builder.geometry/2026-08-25",
            "segment_index": 0, "content_hash": "h0", "frame_id": "segment:0",
            "registered": false, "transform_to_world": NSNull(),
            "poses": [], "points": [[1.0, 2.0, 3.0]],
            "points_sent": 1, "points_total": 3000, "point_sampling": "stride",
        ]

        let chunk = WorldGeometryDecoder.chunk(from: json)
        XCTAssertTrue(chunk!.isSampled)
        XCTAssertEqual(chunk?.pointsTotal, 3000)
    }
}
```

- [ ] **Step 2: Note that this cannot be run here**

Do **not** run a test command. There is no Swift toolchain on this machine.
Record in the commit that the file is unbuilt.

- [ ] **Step 3: Write the types and decoder**

Create `ios/Glasses/Workspaces/WorldBuilder/WorldGeometry.swift`:

```swift
//
//  WorldGeometry.swift
//  Glasses
//

import Foundation

/// The geometry agreement this build implements. Separate from the status
/// contract so either may move without the other, and opaque: compared for
/// equality only.
enum WorldGeometryContract {
    static let identifier = "world_builder.geometry/2026-08-25"
}

/// The nine keys that decide what a pose means.
///
/// Every one of them renders plausibly and wrongly if guessed — inverting
/// `T_world_camera` still produces a map that looks like a map, and that was a
/// real shipped bug. So the convention travels on the wire and this build
/// compares all nine before drawing anything.
struct WorldPoseConvention: Equatable, Sendable {
    let poseType: String
    let quaternionOrder: String
    let handedness: String
    let cameraAxes: String
    let translationUnits: String
    let worldAxesOrigin: String
    /// `"unknown"` today. It becomes a real axis when a floor plane exists,
    /// which is the signal a 3D renderer needs to stop guessing which way is up.
    let upAxis: String
    let poseDtype: String
    let pointDtype: String

    /// What this build knows how to draw. `upAxis` is deliberately absent:
    /// the 2D top-down view does not depend on it, so an unknown up-axis is
    /// not a mismatch.
    var matchesThisBuild: Bool {
        poseType == "T_world_camera"
            && quaternionOrder == "wxyz"
            && handedness == "right"
            && cameraAxes == "opencv_x_right_y_down_z_forward"
            && translationUnits == "world"
    }
}

// In an extension so the memberwise initialiser survives, as above.
extension WorldPoseConvention {
    init?(json: [String: Any]) {
        guard
            let poseType = json["pose_type"] as? String,
            let quaternionOrder = json["quaternion_order"] as? String,
            let handedness = json["handedness"] as? String,
            let cameraAxes = json["camera_axes"] as? String,
            let translationUnits = json["translation_units"] as? String,
            let worldAxesOrigin = json["world_axes_origin"] as? String,
            let upAxis = json["up_axis"] as? String,
            let poseDtype = json["pose_dtype"] as? String,
            let pointDtype = json["point_dtype"] as? String
        else { return nil }
        self.poseType = poseType
        self.quaternionOrder = quaternionOrder
        self.handedness = handedness
        self.cameraAxes = cameraAxes
        self.translationUnits = translationUnits
        self.worldAxesOrigin = worldAxesOrigin
        self.upAxis = upAxis
        self.poseDtype = poseDtype
        self.pointDtype = pointDtype
    }
}

/// Whether a segment produced geometry, or produced nothing while looking.
enum WorldSegmentResolution: String, Equatable, Sendable {
    case resolved
    case unresolved
}

struct WorldBounds: Equatable, Sendable {
    let min: [Double]
    let max: [Double]

    init?(json: Any?) {
        guard
            let dict = json as? [String: Any],
            let min = dict["min"] as? [Double], min.count == 3,
            let max = dict["max"] as? [Double], max.count == 3
        else { return nil }
        self.min = min
        self.max = max
    }
}

struct WorldSegmentSummary: Equatable, Sendable {
    let segmentIndex: Int
    let contentHash: String
    let frameID: String
    /// False for every segment today. Two unregistered segments may never be
    /// drawn in one space — they share no coordinate frame and their scales
    /// disagree by up to ~87x on a real walk.
    let registered: Bool
    let resolutionState: WorldSegmentResolution
    /// Why this segment's refused poses were refused. Genuinely actionable:
    /// `low_parallax` means move sideways rather than turning on the spot.
    let dominantDegeneracy: String?
    let keyframeCount: Int
    let solvedCount: Int
    let pointCount: Int
    /// `nil` when the segment resolved to nothing. Never a zero-size box —
    /// absent and empty are different claims.
    let bounds: WorldBounds?
}

// The JSON initialiser lives in an extension ON PURPOSE. Declaring an `init`
// inside the struct body suppresses Swift's memberwise initialiser, and the
// tests build these values directly rather than from JSON.
extension WorldSegmentSummary {
    init?(json: [String: Any]) {
        guard
            let segmentIndex = json["segment_index"] as? Int,
            let contentHash = json["content_hash"] as? String,
            let frameID = json["frame_id"] as? String,
            let registered = json["registered"] as? Bool,
            let stateWord = json["resolution_state"] as? String,
            let state = WorldSegmentResolution(rawValue: stateWord),
            let keyframeCount = json["keyframe_count"] as? Int,
            let solvedCount = json["solved_count"] as? Int,
            let pointCount = json["point_count"] as? Int
        else { return nil }
        self.segmentIndex = segmentIndex
        self.contentHash = contentHash
        self.frameID = frameID
        self.registered = registered
        self.resolutionState = state
        self.dominantDegeneracy = json["dominant_degeneracy"] as? String
        self.keyframeCount = keyframeCount
        self.solvedCount = solvedCount
        self.pointCount = pointCount
        self.bounds = WorldBounds(json: json["bounds"])
    }
}

struct WorldGeometryManifest: Equatable, Sendable {
    let worldID: String
    let sessionID: String
    let geometryRevision: String
    let poseConvention: WorldPoseConvention
    let segments: [WorldSegmentSummary]

    var resolvedSegments: [WorldSegmentSummary] {
        segments.filter { $0.resolutionState == .resolved }
    }

    /// Segments that hold keyframes and recovered nothing. On the real walk
    /// this was 32 of 51. They are counted, never placed: we know
    /// reconstruction failed, not where it failed.
    var unresolvedSegments: [WorldSegmentSummary] {
        segments.filter { $0.resolutionState == .unresolved }
    }
}

struct WorldPose: Equatable, Sendable {
    let keyframeID: String
    let status: String
    let degeneracy: String
    let rotation: [Double]?
    /// `nil` means the pose was refused. The renderer draws a break here, not
    /// a line through the gap, and never substitutes zero.
    let translation: [Double]?
}

// In an extension so the memberwise initialiser survives, as above.
extension WorldPose {
    init?(json: [String: Any]) {
        guard
            let keyframeID = json["keyframe_id"] as? String,
            let status = json["status"] as? String
        else { return nil }
        self.keyframeID = keyframeID
        self.status = status
        self.degeneracy = json["degeneracy"] as? String ?? ""
        self.rotation = json["rotation"] as? [Double]
        self.translation = json["translation"] as? [Double]
    }
}

struct WorldSegmentChunk: Equatable, Sendable {
    let segmentIndex: Int
    let contentHash: String
    let registered: Bool
    let poses: [WorldPose]
    let points: [[Double]]
    let pointsSent: Int
    let pointsTotal: Int
    let pointSampling: String

    /// True when the cloud on screen is not the whole cloud. The UI must say
    /// so rather than let a coarse world read as a complete one.
    var isSampled: Bool { pointsSent < pointsTotal }
}

enum WorldGeometryDecoder {

    static func manifest(from json: [String: Any]) -> WorldGeometryManifest? {
        guard
            json["contract"] as? String == WorldGeometryContract.identifier,
            let worldID = json["world_id"] as? String,
            let sessionID = json["session_id"] as? String,
            let revision = json["geometry_revision"] as? String,
            let conventionJSON = json["pose_convention"] as? [String: Any],
            let convention = WorldPoseConvention(json: conventionJSON),
            let rawSegments = json["segments"] as? [[String: Any]]
        else { return nil }

        // A row that will not decode drops the whole manifest rather than
        // silently shrinking the world.
        var segments: [WorldSegmentSummary] = []
        for raw in rawSegments {
            guard let segment = WorldSegmentSummary(json: raw) else { return nil }
            segments.append(segment)
        }

        return WorldGeometryManifest(
            worldID: worldID, sessionID: sessionID, geometryRevision: revision,
            poseConvention: convention, segments: segments
        )
    }

    static func chunk(from json: [String: Any]) -> WorldSegmentChunk? {
        guard
            json["contract"] as? String == WorldGeometryContract.identifier,
            let segmentIndex = json["segment_index"] as? Int,
            let contentHash = json["content_hash"] as? String,
            let registered = json["registered"] as? Bool,
            let rawPoses = json["poses"] as? [[String: Any]],
            let points = json["points"] as? [[Double]],
            let sent = json["points_sent"] as? Int,
            let total = json["points_total"] as? Int,
            let sampling = json["point_sampling"] as? String
        else { return nil }

        var poses: [WorldPose] = []
        for raw in rawPoses {
            guard let pose = WorldPose(json: raw) else { return nil }
            poses.append(pose)
        }

        return WorldSegmentChunk(
            segmentIndex: segmentIndex, contentHash: contentHash,
            registered: registered, poses: poses, points: points,
            pointsSent: sent, pointsTotal: total, pointSampling: sampling
        )
    }
}
```

- [ ] **Step 4: Commit, labelled unbuilt**

```bash
git add ios/Glasses/Workspaces/WorldBuilder/WorldGeometry.swift \
        ios/GlassesTests/WorldGeometryTests.swift
git commit -m "feat(ios): decode the geometry contract [BUILD UNVERIFIED]

Written on Windows with no Swift toolchain. Not compiled, not run.

The decoder refuses a wrong contract identifier outright and reports a
pose-convention mismatch rather than hiding it, because inverting
T_world_camera still draws a plausible map. Absent stays absent: a
refused pose keeps a nil translation, and an unresolved segment keeps nil
bounds rather than a zero-size box."
```

---

## Task 7: iOS geometry client with a content-hash cache

**BUILD UNVERIFIED.**

**Files:**
- Create: `ios/Glasses/Workspaces/WorldBuilder/WorldGeometryClient.swift`
- Modify: `ios/Glasses/TowerConfiguration.swift` (add the HTTP base URL)
- Test: `ios/GlassesTests/WorldGeometryTests.swift` (append)

**Interfaces:**
- Consumes: Task 6's types.
- Produces: `WorldGeometryStore` (an actor holding cached chunks by
  `contentHash`), `WorldGeometryClient.manifest(worldID:sessionID:)`,
  `WorldGeometryClient.segment(worldID:sessionID:index:)`

- [ ] **Step 1: Write the failing test**

Append to `ios/GlassesTests/WorldGeometryTests.swift`:

```swift
final class WorldGeometryStoreTests: XCTestCase {

    private func chunk(index: Int, hash: String) -> WorldSegmentChunk {
        WorldSegmentChunk(
            segmentIndex: index, contentHash: hash, registered: false,
            poses: [], points: [[0, 0, 0]], pointsSent: 1, pointsTotal: 1,
            pointSampling: "none"
        )
    }

    func testACachedSegmentIsNotRefetched() async {
        // The property the whole design rests on: a closed segment is frozen,
        // so it crosses the wire exactly once.
        let store = WorldGeometryStore()
        await store.insert(chunk(index: 0, hash: "h0"))

        let needed = await store.hashesMissing(from: ["h0", "h1"])
        XCTAssertEqual(needed, ["h1"])
    }

    func testAChangedHashIsRefetched() async {
        let store = WorldGeometryStore()
        await store.insert(chunk(index: 0, hash: "h0"))

        let needed = await store.hashesMissing(from: ["h0-moved"])
        XCTAssertEqual(needed, ["h0-moved"])
    }

    func testTheCacheIsKeyedByHashNotBySegmentIndex() async {
        // A re-solved segment keeps its index and changes its content. Keying
        // on the index would serve stale geometry under a fresh revision.
        let store = WorldGeometryStore()
        await store.insert(chunk(index: 0, hash: "old"))
        await store.insert(chunk(index: 0, hash: "new"))

        let old = await store.chunk(forHash: "old")
        let new = await store.chunk(forHash: "new")
        XCTAssertNotNil(old)
        XCTAssertNotNil(new)
        XCTAssertEqual(new?.contentHash, "new")
    }
}
```

- [ ] **Step 2: Add the HTTP base URL**

In `ios/Glasses/TowerConfiguration.swift`, add beside `webSocketURL`:

```swift
    /// The same Tower, over HTTP. Geometry is fetched here rather than over the
    /// socket because the Tower gives its result sender and its frame path one
    /// shared lock, and a megabyte of points there would starve the frames.
    static let httpBaseURL = URL(string: "http://100.110.156.55:8000")!
```

- [ ] **Step 3: Write the store and client**

Create `ios/Glasses/Workspaces/WorldBuilder/WorldGeometryClient.swift`:

```swift
//
//  WorldGeometryClient.swift
//  Glasses
//

import Foundation

/// Cached segment geometry, keyed by content hash.
///
/// Keyed by hash rather than by segment index on purpose: a re-solved segment
/// keeps its index and changes its contents, so an index key would serve stale
/// geometry under a fresh revision. A hash key cannot.
///
/// Because the Tower freezes a segment when tracking is lost, a closed
/// segment's hash never changes again — so it is fetched exactly once and kept
/// for the life of the world, and only the open segment churns.
actor WorldGeometryStore {
    private var chunks: [String: WorldSegmentChunk] = [:]

    func insert(_ chunk: WorldSegmentChunk) {
        chunks[chunk.contentHash] = chunk
    }

    func chunk(forHash hash: String) -> WorldSegmentChunk? {
        chunks[hash]
    }

    func hashesMissing(from wanted: [String]) -> [String] {
        wanted.filter { chunks[$0] == nil }
    }

    /// Drop everything not named by the current manifest. Called after a
    /// manifest arrives so a long walk does not accumulate superseded
    /// segments forever.
    func retainOnly(_ wanted: Set<String>) {
        chunks = chunks.filter { wanted.contains($0.key) }
    }
}

enum WorldGeometryFetchError: Error, Equatable {
    case notFound
    case undecodable
    case transport(String)
}

/// Fetches geometry over HTTP. Deliberately not on the WebSocket.
struct WorldGeometryClient {
    var baseURL: URL = TowerConfiguration.httpBaseURL
    var session: URLSession = .shared

    func manifest(worldID: String, sessionID: String) async throws -> WorldGeometryManifest {
        let url = baseURL
            .appendingPathComponent("worlds/\(worldID)/geometry/manifest")
        let json = try await get(url, query: [URLQueryItem(name: "session_id", value: sessionID)])
        guard let manifest = WorldGeometryDecoder.manifest(from: json) else {
            throw WorldGeometryFetchError.undecodable
        }
        return manifest
    }

    func segment(
        worldID: String, sessionID: String, index: Int, maxPoints: Int? = nil
    ) async throws -> WorldSegmentChunk {
        let url = baseURL
            .appendingPathComponent("worlds/\(worldID)/geometry/segment/\(index)")
        var query = [URLQueryItem(name: "session_id", value: sessionID)]
        if let maxPoints {
            query.append(URLQueryItem(name: "max_points", value: String(maxPoints)))
        }
        let json = try await get(url, query: query)
        guard let chunk = WorldGeometryDecoder.chunk(from: json) else {
            throw WorldGeometryFetchError.undecodable
        }
        return chunk
    }

    private func get(_ url: URL, query: [URLQueryItem]) async throws -> [String: Any] {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        components.queryItems = query
        do {
            let (data, response) = try await session.data(from: components.url!)
            if let http = response as? HTTPURLResponse, http.statusCode == 404 {
                throw WorldGeometryFetchError.notFound
            }
            guard
                let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { throw WorldGeometryFetchError.undecodable }
            return json
        } catch let error as WorldGeometryFetchError {
            throw error
        } catch {
            throw WorldGeometryFetchError.transport(error.localizedDescription)
        }
    }
}
```

- [ ] **Step 4: Commit, labelled unbuilt**

```bash
git add ios/Glasses/Workspaces/WorldBuilder/WorldGeometryClient.swift \
        ios/Glasses/TowerConfiguration.swift \
        ios/GlassesTests/WorldGeometryTests.swift
git commit -m "feat(ios): fetch geometry over HTTP, cached by content hash [BUILD UNVERIFIED]

Written on Windows with no Swift toolchain. Not compiled, not run.

Keyed by hash and not by segment index: a re-solved segment keeps its
index and changes its contents, so an index key would serve stale
geometry under a fresh revision."
```

---

## Task 8: The three-state fragments view

**BUILD UNVERIFIED.** This is the task that carries the truthfulness
requirements, so its tests are assertions about what may *not* be drawn.

**Files:**
- Create: `ios/Glasses/Workspaces/WorldBuilder/WorldFragmentsView.swift`
- Test: `ios/GlassesTests/WorldGeometryTests.swift` (append)

**Interfaces:**
- Consumes: Tasks 6–7.
- Produces: `WorldFragmentsModel` (pure layout logic, testable without a view)
  and `WorldFragmentsView` (SwiftUI).

- [ ] **Step 1: Write the failing test**

Append to `ios/GlassesTests/WorldGeometryTests.swift`:

```swift
final class WorldFragmentsModelTests: XCTestCase {

    private func summary(
        index: Int, points: Int, state: WorldSegmentResolution,
        bounds: WorldBounds? = nil
    ) -> WorldSegmentSummary {
        WorldSegmentSummary(
            segmentIndex: index, contentHash: "h\(index)",
            frameID: "segment:\(index)", registered: false,
            resolutionState: state, dominantDegeneracy: "low_parallax",
            keyframeCount: 10, solvedCount: points > 0 ? 5 : 0,
            pointCount: points, bounds: bounds
        )
    }

    private let box = WorldBounds(json: ["min": [-1.0, 0.0, -1.0],
                                         "max": [1.0, 2.0, 1.0]])!

    func testUnregisteredSegmentsAreNeverCompositedIntoOneCanvas() {
        // The load-bearing negative. Segment anchors all sit at the origin and
        // per-segment scale disagrees by up to ~87x on a real walk, so one
        // shared canvas would superimpose independent reconstructions.
        let model = WorldFragmentsModel(segments: [
            summary(index: 0, points: 100, state: .resolved, bounds: box),
            summary(index: 1, points: 200, state: .resolved, bounds: box),
        ])

        XCTAssertEqual(model.fragments.count, 2)
        XCTAssertFalse(model.hasSharedFrame)
    }

    func testAnUnresolvedSegmentIsCountedButNeverGivenAFragment() {
        // We know reconstruction failed. We do not know where. Drawing it as a
        // region would invent a location.
        let model = WorldFragmentsModel(segments: [
            summary(index: 0, points: 100, state: .resolved, bounds: box),
            summary(index: 1, points: 0, state: .unresolved),
            summary(index: 2, points: 0, state: .unresolved),
        ])

        XCTAssertEqual(model.fragments.count, 1)
        XCTAssertEqual(model.unresolvedCount, 2)
    }

    func testTheHeadlineCountsFragmentsNotSegments() {
        let model = WorldFragmentsModel(segments: [
            summary(index: 0, points: 100, state: .resolved, bounds: box),
            summary(index: 1, points: 0, state: .unresolved),
        ])

        XCTAssertEqual(model.headline, "1 fragment, not yet connected")
    }

    func testAnEmptyWorldSaysNothingIsMappedRatherThanShowingAnEmptyCanvas() {
        let model = WorldFragmentsModel(segments: [])
        XCTAssertTrue(model.fragments.isEmpty)
        XCTAssertEqual(model.headline, "Nothing mapped yet")
    }

    func testAResolvedSegmentWithoutBoundsIsNotDrawn() {
        // bounds nil with points > 0 is incoherent; refuse rather than guess
        // a frame for it.
        let model = WorldFragmentsModel(segments: [
            summary(index: 0, points: 100, state: .resolved, bounds: nil),
        ])
        XCTAssertTrue(model.fragments.isEmpty)
    }

    func testRegisteredSegmentsWouldShareAFrame() {
        // Forward compatibility: when registration lands, the renderer does
        // not change -- the fragments merge.
        let registered = WorldSegmentSummary(
            segmentIndex: 0, contentHash: "h0", frameID: "world",
            registered: true, resolutionState: .resolved,
            dominantDegeneracy: nil, keyframeCount: 10, solvedCount: 5,
            pointCount: 100, bounds: box
        )
        let model = WorldFragmentsModel(segments: [registered, registered])
        XCTAssertTrue(model.hasSharedFrame)
    }
}
```

- [ ] **Step 2: Write the model and view**

Create `ios/Glasses/Workspaces/WorldBuilder/WorldFragmentsView.swift`:

```swift
//
//  WorldFragmentsView.swift
//  Glasses
//

import SwiftUI

/// Layout decisions for the fragment gallery, kept out of the view so they can
/// be tested without rendering.
///
/// ## Why fragments and not a map
///
/// Every segment anchor the Tower produces sits at exactly the origin with
/// identity rotation, and per-segment scale disagrees by up to ~87x on a real
/// walk. Drawing them in one space would superimpose independent
/// reconstructions — geometry that looks like a room and means nothing.
/// `docs/modules/WORLD-BUILD.md` forbids exactly that.
///
/// So each fragment gets its own frame, its own scale, and its own box. When
/// the Tower learns to register segments, `registered` flips, they share a
/// frame, and this model merges them without the view changing.
struct WorldFragmentsModel: Equatable {
    let segments: [WorldSegmentSummary]

    /// Only resolved segments with real bounds can be drawn. A resolved
    /// segment with no bounds is incoherent and is refused rather than framed
    /// by guess.
    var fragments: [WorldSegmentSummary] {
        segments.filter { $0.resolutionState == .resolved && $0.bounds != nil }
    }

    /// Segments that hold keyframes and recovered nothing. Counted, never
    /// placed: we know reconstruction failed, not where.
    var unresolvedCount: Int {
        segments.filter { $0.resolutionState == .unresolved }.count
    }

    /// True once the Tower registers segments into one frame. False today.
    var hasSharedFrame: Bool {
        !segments.isEmpty && segments.allSatisfy(\.registered)
    }

    var headline: String {
        let count = fragments.count
        if count == 0 { return "Nothing mapped yet" }
        if hasSharedFrame { return "1 world" }
        return count == 1
            ? "1 fragment, not yet connected"
            : "\(count) fragments, not yet connected"
    }
}

/// One fragment, drawn top-down in its own frame.
///
/// Top-down `(x, z)` and not 3D because `up_axis` is `"unknown"` — a 3D view
/// would have to guess which way is up. SceneKit earns its weight once a floor
/// plane exists; until then this is both cheaper and more honest.
struct FragmentCanvas: View {
    let summary: WorldSegmentSummary
    let chunk: WorldSegmentChunk?

    var body: some View {
        Canvas { context, size in
            guard let chunk, let bounds = summary.bounds else { return }
            let project = projector(bounds: bounds, size: size)

            for point in chunk.points where point.count == 3 {
                let p = project(point[0], point[2])
                context.fill(
                    Path(ellipseIn: CGRect(x: p.x - 1, y: p.y - 1, width: 2, height: 2)),
                    with: .color(.secondary)
                )
            }

            // The camera path, broken wherever a pose was refused. A line
            // through the gap would assert motion that was never measured.
            var path = Path()
            var pendingMove = true
            for pose in chunk.poses {
                guard let t = pose.translation, t.count == 3 else {
                    pendingMove = true
                    continue
                }
                let p = project(t[0], t[2])
                if pendingMove {
                    path.move(to: p)
                    pendingMove = false
                } else {
                    path.addLine(to: p)
                }
            }
            context.stroke(path, with: .color(.accentColor), lineWidth: 1.5)
        }
        .background(Color.secondary.opacity(0.08))
    }

    /// Each fragment is framed to its OWN bounds. Fragments share no scale,
    /// and pretending otherwise is the fabrication this view exists to avoid.
    private func projector(
        bounds: WorldBounds, size: CGSize
    ) -> (Double, Double) -> CGPoint {
        let spanX = Swift.max(bounds.max[0] - bounds.min[0], 1e-6)
        let spanZ = Swift.max(bounds.max[2] - bounds.min[2], 1e-6)
        let scale = Swift.min(size.width / spanX, size.height / spanZ) * 0.9
        let offsetX = (size.width - spanX * scale) / 2
        let offsetZ = (size.height - spanZ * scale) / 2
        return { x, z in
            CGPoint(
                x: offsetX + (x - bounds.min[0]) * scale,
                y: offsetZ + (z - bounds.min[2]) * scale
            )
        }
    }
}

/// The gallery: known-but-unregistered fragments, plus honest accounts of the
/// two states that have no geometry to draw.
struct WorldFragmentsView: View {
    let model: WorldFragmentsModel
    let chunks: [String: WorldSegmentChunk]

    private let columns = [GridItem(.adaptive(minimum: 140), spacing: 12)]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.headline)
                .font(.headline)

            if model.fragments.isEmpty {
                // UNKNOWN: nothing has been mapped. Not an empty canvas,
                // which would read as an empty room.
                Text("The glasses have not mapped anything here yet.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(model.fragments, id: \.segmentIndex) { segment in
                        VStack(alignment: .leading, spacing: 4) {
                            FragmentCanvas(
                                summary: segment,
                                chunk: chunks[segment.contentHash]
                            )
                            .frame(height: 120)
                            .clipShape(RoundedRectangle(cornerRadius: 8))

                            Text("\(segment.pointCount) points")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            if let chunk = chunks[segment.contentHash], chunk.isSampled {
                                Text("showing \(chunk.pointsSent) of \(chunk.pointsTotal)")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            if model.unresolvedCount > 0 {
                // OBSERVED BUT UNRESOLVED. Deliberately not drawn: we know
                // reconstruction failed, not where it failed, and a region
                // would invent a location.
                Text("\(model.unresolvedCount) areas were seen but could not be reconstructed.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
```

- [ ] **Step 3: Commit, labelled unbuilt**

```bash
git add ios/Glasses/Workspaces/WorldBuilder/WorldFragmentsView.swift \
        ios/GlassesTests/WorldGeometryTests.swift
git commit -m "feat(ios): draw fragments, not a world that does not exist [BUILD UNVERIFIED]

Written on Windows with no Swift toolchain. Not compiled, not run.

Every segment anchor sits at the origin and per-segment scale disagrees
by up to ~87x, so one shared canvas would superimpose 19 independent
reconstructions. Each fragment gets its own frame and its own scale.

Three states, because the data has three: unmapped space says so, areas
that were seen but did not reconstruct are counted without being placed,
and only real geometry is drawn. The camera path breaks wherever a pose
was refused rather than running a line through the gap."
```

---

## Task 9: Adopt the new status contract and wire the viewer in

**BUILD UNVERIFIED.**

**Files:**
- Modify: `ios/Glasses/Workspaces/WorldBuilder/TowerWorldBuilderClient.swift:24`
- Modify: `ios/Glasses/Workspaces/WorldBuilder/WorldCanvasView.swift`
- Test: `ios/GlassesTests/WorldGeometryTests.swift` (append)

**Interfaces:**
- Consumes: Tasks 6–8.
- Produces: no new types.

> **Ordering note.** This task edits files that live on
> `origin/ios/world-builder-integration`, not on this branch. Merge that branch
> first (see the Integration section below) or this task has nothing to edit.

- [ ] **Step 1: Write the failing test**

```swift
final class WorldBuilderContractAdoptionTests: XCTestCase {

    func testTheStatusContractIsTheOneThisTowerServes() {
        // Moved from /2026-08-23 because trajectory.pose_count changed
        // MEANING: it used to be keyframes - poses_refused, which counted a
        // segment anchor as a camera position and produced "Camera poses: 36"
        // on a world whose manifest read poses_solved: 0.
        XCTAssertEqual(
            WorldBuilderResultContract.identifier,
            "world_builder.status/2026-08-25"
        )
    }

    func testTheGeometryContractIsSeparateFromTheStatusContract() {
        XCTAssertNotEqual(
            WorldGeometryContract.identifier,
            WorldBuilderResultContract.identifier
        )
    }
}
```

- [ ] **Step 2: Bump the identifier**

In `ios/Glasses/Workspaces/WorldBuilder/TowerWorldBuilderClient.swift:24`:

```swift
    static let identifier = "world_builder.status/2026-08-25"
```

- [ ] **Step 3: Render fragments in the world panel**

In `WorldCanvasView.swift`, replace the line that reads
`"This build cannot draw the Tower's world representation yet."` with the
fragments view, keeping every existing summary row above it:

```swift
            WorldFragmentsView(model: fragmentsModel, chunks: geometryChunks)
```

Add these to `WorldBuilderViewModel` in `WorldBuilderClient.swift`, beside the
existing `@Published private(set) var state`:

```swift
    @Published private(set) var fragmentsModel = WorldFragmentsModel(segments: [])
    @Published private(set) var geometryChunks: [String: WorldSegmentChunk] = [:]

    private let geometry = WorldGeometryClient()
    private let geometryStore = WorldGeometryStore()
    private var lastGeometryRevision: String?

    /// Refetch only when the Tower says geometry moved.
    ///
    /// The status channel heartbeats an unchanged snapshot about every 2 s, so
    /// keying on arrival rather than on the revision would refetch a megabyte
    /// twice a second for a world that is not changing.
    func geometryDidChange(worldID: String?, sessionID: String?, revision: String?) async {
        guard
            let worldID, let sessionID, let revision,
            revision != lastGeometryRevision
        else { return }
        lastGeometryRevision = revision

        guard let manifest = try? await geometry.manifest(
            worldID: worldID, sessionID: sessionID
        ) else { return }

        // A convention this build does not implement renders plausibly and
        // wrongly, so it renders not at all.
        guard manifest.poseConvention.matchesThisBuild else {
            fragmentsModel = WorldFragmentsModel(segments: [])
            return
        }

        let wanted = manifest.segments.map(\.contentHash)
        await geometryStore.retainOnly(Set(wanted))
        for hash in await geometryStore.hashesMissing(from: wanted) {
            guard let summary = manifest.segments.first(where: { $0.contentHash == hash }),
                  let chunk = try? await geometry.segment(
                      worldID: worldID, sessionID: sessionID,
                      index: summary.segmentIndex
                  )
            else { continue }
            await geometryStore.insert(chunk)
            geometryChunks[chunk.contentHash] = chunk
        }
        fragmentsModel = WorldFragmentsModel(segments: manifest.segments)
    }
```

Call `geometryDidChange` from wherever the view model already handles a new
`WorldModelState`, passing `snapshot.worldID`, the session id from the payload,
and `snapshot.revision`.

- [ ] **Step 4: Expect and accept one designed failure**

`ProductShellTests.testTheTowerDeclaresNoCartridgeContracts` asserts
`TowerCapabilities.declared.isEmpty`. It will fail the moment World Builder is
declared. That failure is the designed review trigger, not a defect: update the
test to assert the *specific* declared contract rather than emptiness, and note
in the commit that the review happened.

- [ ] **Step 5: Commit, labelled unbuilt**

```bash
git add ios/Glasses/Workspaces/WorldBuilder/ ios/GlassesTests/
git commit -m "feat(ios): adopt world_builder.status/2026-08-25 and show the world [BUILD UNVERIFIED]

Written on Windows with no Swift toolchain. Not compiled, not run.

The identifier moved because pose_count changed meaning, so this is a
deliberate adoption rather than a version bump. testTheTowerDeclares-
NoCartridgeContracts fails by design here and has been updated to pin the
contract that is now declared."
```

---

## Integration

The Tower work (Tasks 1–5) is on `integration/world-builder-lifecycle-v1`. The
iOS client lives on `origin/ios/world-builder-integration`, which forked from
`main` at `35214a1` and touches a disjoint file set. Tasks 6–8 create new files
and can land on either; Task 9 edits that branch's files and requires the merge.

Before Task 9:

```bash
git merge origin/ios/world-builder-integration
```

Expect no content conflicts — the branches touch disjoint files. Expect the two
designed test failures named above.

**Do not merge anything to `main`.** Integration happens on
`integration/world-builder-lifecycle-v1`.

---

## Verification and handoff

After Task 5:

```
cd tower
./.venv/Scripts/python.exe -m pytest -q
```

Expected: **1209 passed, 32 skipped, 0 failed**, against a 1178-passing baseline.

After Task 9, the honest status is:

> **IMPLEMENTATION COMPLETE — BUILD AND PHYSICAL VALIDATION PENDING.**
> Tower: N passed on this machine. iOS: written, never compiled. Nothing in
> this plan has met the glasses.

The physical test is a walk with the phone showing fragments appearing during
capture. Its first-run failure signatures are: fragments never appearing (the
manifest 404s — check `TOWER_WORLD_ROOT`); one fragment holding everything
(segments merged, which would be a Tower bug today); and a fragment whose points
form a plausible room while the count disagrees with `geometry.element_count`
(a decode error).

---

## Out of scope

Segment registration, covisibility, loop closure, bundle adjustment, metric
scale, tracking continuity, higher-resolution capture and imagery transport are
all subsequent World Builder work, per the spec's §4.2. None is abandoned. The
contract is built so none of them requires a wire redesign: registration flips
`registered` and fills `transform_to_world`, leaving every cached
`content_hash` valid.
