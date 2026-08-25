# World Builder geometry transport — design

**Date:** 2026-08-25
**Status:** APPROVED (brainstorming gate passed; sections 1–3 approved with two
added requirements, recorded in §7)
**Branch:** `integration/world-builder-lifecycle-v1`
**Baseline:** Tower 1178 passed / 32 skipped / 0 failed (177.75 s), verified
before any design work.

---

## 1. Why this exists

The Tower crossed the pose boundary for the first time on 2026-08-25. World
`3dd986b1c2364d4b85de97152f2e39f4`, session `dd5d13a2381e430db9b27c7da2cf2928`:

```json
{"backend_id": "classical-sfm", "backend_downgraded_from": null,
 "keyframes": 457, "poses_solved": 94, "poses_refused": 312,
 "poses_anchor": 51, "poses_positioned": 113, "points": 12023,
 "segments": 51, "scale_state": "unknown"}
```

That geometry reaches nothing. `WorldCanvasView.swift:227` says outright:
"This build cannot draw the Tower's world representation yet." No poses, no
points and no paths cross the wire today.

### 1.1 The finding that shapes the whole design

Measured directly from `derived/<session>/poses.json` and `points.json`:

- All **51 segment anchors** carry `translation == [0,0,0]` and
  `rotation == [1,0,0,0]`, exactly. Segments share **no coordinate frame**.
- Only **19 of 51** segments produced any points. **32 produced nothing**
  despite holding keyframes (segment 20: 31 keyframes, 0 solved).
- Per-segment scale is arbitrary — the two-view baseline is normalised to 1.0.
  Camera span ranges **1.000 to 86.74** across segments: an ~87x disagreement.
- Pose status over 457 keyframes: `unavailable` 294, `solved` 94,
  `anchor` 51, `rotation_only` 18.

`engine.py:767` states the invariant deliberately:

> "A segment gets exactly one solve, and it never crosses a `tracking_lost`:
> segments do not share a coordinate frame or a unit, they are independent
> windows today, and they must stay so. Closing a segment freezes its estimate
> and resets the backend."

**Consequence.** Plotting all 12,023 points in one space superimposes 19
independent reconstructions at a common origin with ~87x scale disagreement.
That is fabricated geometry, and `guidelines/docs/modules/WORLD-BUILD.md:238`
forbids it by name: an unknown region must render "as unknown, never as
blank-as-if-absent and never as fabricated."

So the gap between "geometry exists" and "World Builder is finished" is
**segment registration**, not the viewer. This design ships the transport and a
truthful viewer now, shaped so registration later changes nothing on the wire
and nothing in the renderer.

### 1.2 Why geometry must not ride the status channel

`tower/routes/ws.py:38-42` — the result sender and **the frame path share one
`asyncio.Lock`**. The docstring says so: "The frame path takes this lock too."

`points.json` is **1,095,028 bytes** for 12,023 points; `poses.json` is
**94,881 bytes** for 457 keyframes. The status payload measures **3,884 bytes**
against a poll interval of 0.5 s. Pushing geometry over that socket would hold
the shared lock and starve `frame_result`, violating the contract's own Tower
responsibility #3: "Never let the result channel affect the frame path."

`test_result_channel_protocol.py:142-153` independently asserts the snapshot
carries no unbounded list (`len(node) <= 16`). A segment manifest is unbounded.

**Therefore: signal on the WebSocket, fetch over HTTP.** The Tower already runs
FastAPI with `GET /cartridges` and `GET /health` (`tower/routes/`), so a new
route touches neither the frame path nor the send lock.

### 1.3 Why the segment is the unit of everything

Rows in both `poses.json` and `points.json` already carry `segment_index`. A
segment is simultaneously:

| Role | Why |
|---|---|
| coordinate-frame unit | each has its own origin — the truthfulness boundary |
| cache unit | closed segments are frozen (`engine.py:767`) |
| delta unit | per-segment content hash |
| LOD unit | sample within a segment |
| progressive unit | a new segment appears as you walk |

Because closed segments never change, each is fetched **exactly once** and
cached for the life of the world; only the single open segment churns. Live
wire cost is therefore **O(1) in walk length**, not O(N).

This resolves a real tension in the existing docs. `WORLD-BUILD.md:243` prefers
"incremental world-state updates/deltas"; `CARTRIDGE-RESULTS.md:6` calls "there
is no delta stream, therefore there is no gap, therefore a cursor cannot lose
data" the single most important property of the design. Per-segment content
hashes satisfy both: the client fetches only what changed, and reconnect stays
"compare hashes, fetch what's missing" — no gap semantics anywhere.

Supporting evidence that hashing is the *safe* delta unit rather than merely a
convenient one — `backend.py:114-127`:

> "`new_points` is only the structure this keyframe created, never the whole
> map, so a live viewer can append instead of re-reading. Both are
> conveniences: `snapshot()` stays authoritative, because a backend that
> re-solves cannot promise the earlier poses it already returned are still
> current, and this type deliberately does not claim they are."

A naive append-only wire protocol would drift out of sync with the
authoritative solve. A content hash cannot: a re-solved segment changes hash
and is refetched.

Tested invariants this rests on: `test_a_live_build_equals_a_cold_build_of_the_same_keyframes:690`,
`test_rebuilding_mid_walk_does_not_change_the_final_result:720`,
`test_a_lost_track_leaks_nothing_across_the_boundary:757`.

---

## 2. The three-state truthfulness model

The requirement is that the UI distinguish **unknown space** from
**known-but-unregistered geometry**. The data supports a third state, and
omitting it would itself be a small lie — 32 of 51 segments fall in it.

| State | Meaning | Evidence | Rendered as |
|---|---|---|---|
| **UNKNOWN** | never observed | outside every fragment's bounds | fog / explicit unknown |
| **OBSERVED, UNRESOLVED** | keyframes exist; geometry could not be recovered | segment with keyframes, `point_count == 0` | counted and named, **never drawn as space** |
| **KNOWN, UNREGISTERED** | real geometry, no place in a shared frame | segment with `point_count > 0`, `registered: false` | its own framed fragment |
| *(future)* **KNOWN, REGISTERED** | geometry with a known `T_world_segment` | `registered: true` | merged into one canvas |

**The unresolved state must not be drawn positionally.** We know the wearer
looked somewhere and that reconstruction failed; we do **not** know where that
somewhere is. Drawing it as a region would invent a location. It is reported as
a count with its dominant `degeneracy`, which is genuinely informative — on the
real world, `low_parallax` 164 and `no_correspondence` 87 tell the wearer to
move sideways rather than turn on the spot.

---

## 3. The contract

New identifier, separate from `status` so each versions independently and a
client may implement status alone:

```
world_builder.geometry/2026-08-25
```

The status payload is **unchanged**. Its existing `geometry.revision`
(`world_builder.py:1106-1115`) is already an opaque content hash over
`{digest, built_at, points, solved, segments, scale}` and serves as the "refetch
the manifest" signal. No new field is added to it.

### 3.1 `GET /worlds/{world_id}/geometry/manifest?session_id=…`

```json
{
  "contract": "world_builder.geometry/2026-08-25",
  "world_id": "3dd986b1c2364d4b85de97152f2e39f4",
  "session_id": "dd5d13a2381e430db9b27c7da2cf2928",
  "geometry_revision": "…",
  "pose_convention": {
    "pose_type": "T_world_camera", "quaternion_order": "wxyz",
    "handedness": "right", "camera_axes": "opencv_x_right_y_down_z_forward",
    "translation_units": "world", "world_axes_origin": "first_keyframe_camera",
    "up_axis": "unknown", "pose_dtype": "float64", "point_dtype": "float32"
  },
  "scale": {"state": "unknown", "meters_per_unit": null},
  "segment_count": 51,
  "segments": [
    {
      "segment_index": 19,
      "content_hash": "…",
      "frame_id": "segment:19",
      "registered": false,
      "transform_to_world": null,
      "resolution_state": "resolved",
      "dominant_degeneracy": "low_parallax",
      "keyframe_count": 32,
      "solved_count": 22,
      "point_count": 3033,
      "bounds": {"min": [x,y,z], "max": [x,y,z]}
    }
  ]
}
```

Field semantics, stated so none is ambiguous:

- `keyframe_count` — pose rows for this segment. There is exactly one pose row
  per keyframe, so this is also the length of the segment's `poses` array.
  (`pose_count` and `anchor_count` are deliberately **not** carried: the former
  would duplicate this field, and the latter is always exactly 1 per segment.)
- `solved_count` — rows with `status == "solved"`. This is the only count that
  is evidence of measured camera motion.
- `resolution_state` — `resolved` when `point_count > 0`, otherwise
  `unresolved`.
- `dominant_degeneracy` — the most frequent non-empty `degeneracy` among this
  segment's refused rows, or `null` when no row was refused. Present on
  resolved segments too, since a segment can solve some poses and refuse
  others.
- `bounds` — **3D**, over this segment's points, in the segment's own frame.
  `null` when `point_count == 0`.

### 3.2 `GET /worlds/{world_id}/geometry/segment/{index}?session_id=…&max_points=N`

```json
{
  "contract": "world_builder.geometry/2026-08-25",
  "segment_index": 19,
  "content_hash": "…",
  "frame_id": "segment:19",
  "registered": false,
  "transform_to_world": null,
  "poses": [
    {"keyframe_id": "…:00000227", "status": "solved", "degeneracy": "",
     "rotation": [w,x,y,z], "translation": [x,y,z]},
    {"keyframe_id": "…:00000231", "status": "unavailable",
     "degeneracy": "low_parallax", "rotation": null, "translation": null}
  ],
  "points": [[x,y,z], …],
  "points_sent": 3033, "points_total": 3033, "point_sampling": "none"
}
```

Rows preserve `poses.json` order, which is index-aligned to `keyframes.jsonl`
(verified 457/457 on the real world).

### 3.3 Rules that are not negotiable

1. **`pose_convention` is compared key-by-key and any mismatch refuses the
   render.** Inverting `T_world_camera` still produces a plausible-looking map,
   and that was a real shipped bug (`test_world_builder_engine.py:472`).
2. **`translation: null` survives to the viewer**, which draws a break rather
   than a line through a gap. `null` means refused, never zero.
3. **`registered: false` forbids placing two segments in one space.** A
   renderer that ignores this fabricates geometry.
4. **`points_sent` / `points_total` are always present**, so a sampled cloud can
   never be read as the whole one.
5. **No imagery.** `image_relpath` and every keyframe byte stay Tower-side.
   `retains_raw_imagery` remains permanently `true`; redaction is a process
   claim, not an outcome claim.

### 3.4 Forward compatibility — the contract is fully 3D

Per the added requirement: the 2D renderer is a **V1 presentation choice**, not
a property of the wire. The contract carries complete 3D information —
`rotation` quaternions, 3D `translation`, 3D `points`, 3D `bounds`, and the
full `pose_convention` including `camera_axes` and `handedness`. A future 3D
renderer consumes the same payload with **no wire change**.

Two hooks make registration additive rather than breaking:

- `registered` flips to `true` and `transform_to_world` carries a Sim3
  (`{rotation_wxyz, translation, scale}`) placing that segment in a shared
  frame. Segment-local geometry is **unchanged** — so every cached
  `content_hash` stays valid across a registration pass.
- `up_axis` is `"unknown"` today. When a floor plane is established it becomes
  a real axis, which is the signal a 3D renderer needs to stop guessing.

This is why registration is designed as a layer **above** frozen segments:
geometry immutable, placements mutable. Loop closure moves placements, not
points, and caches survive it.

---

## 4. Tower implementation

`tests/test_architecture_boundaries.py` enforces that shared code imports no
cartridge, with two named adapter exemptions. This adds a third, deliberately
and under review:

- **`tower/results/world_builder_geometry.py`** — the adapter. The only new file
  permitted to import `world_builder`. Reads the store, computes per-segment
  content hashes, assembles manifest and chunks.
- **`tower/routes/geometry.py`** — thin HTTP route; imports the adapter only.

Both reads and hashing run in a **worker thread**, never on the event loop —
matching how snapshot computation already behaves. Hashes cache on
`(input_digest, built_at, segment_index)`, bounded like the existing
`_FileCache` (`MAX_ENTRIES = 64`).

`content_hash` covers that segment's pose rows and points, and nothing else, so
it is stable exactly when the segment is.

### 4.1 Two defects fixed because they land on this contract

1. **The repudiated arithmetic is still live.** `world_builder.py:1459-1468`
   silently falls back to `max(0, keyframes - poses_refused)` when a manifest
   lacks `poses_positioned` — the exact formula the 2026-08-25 contract bump
   exists to repudiate — while still serving under the new identifier. On the
   real world it differs by 32 (113 vs 145). Fix: refuse or report absent.
2. **`poses.json` / `points.json` have zero schema coverage.** No test names
   either file; key sets, `wxyz` order, dtypes and the manifest's 13 keys are
   unpinned. They are about to become a wire contract, so they get pinned
   first.

### 4.2 Explicitly out of scope here

Segment registration, covisibility, loop closure, bundle adjustment, metric
scale, higher-resolution capture, and imagery transport. Each is tracked
separately. The repo's own guidance stands: BA measured 0.00% drift improvement
because the observation graph is a chain, so **covisibility comes before BA**.

---

## 5. iOS implementation

- **`WorldGeometryClient`** — `URLSession`-based (the app has no HTTP client
  today), cache keyed by `content_hash`, driven by `geometry.revision` changes
  arriving on the existing status subscription.
- **Renderer: SwiftUI `Canvas`, 2D top-down (x, z).** Deployment target is
  iOS 26.5, so SceneKit/RealityKit/Metal are all available unconditionally —
  the choice is deliberate, not forced. `up_axis` is `"unknown"`, so a 3D view
  would have to guess which way is up. SceneKit earns its weight once a floor
  plane exists.
- **Small multiples.** Each resolved segment renders in its own mini-canvas,
  auto-framed to its own `bounds`, with its own scale. No shared space is
  implied because none exists. Camera trajectory draws within the fragment,
  breaking wherever `translation` is `null`.
- **The three states are visually distinct** (§2): fog for unknown, framed
  fragments for known-but-unregistered, and a non-positional summary for
  observed-but-unresolved.
- **The headline sentence is literal**, e.g. "19 fragments, not yet connected."

The existing client on `origin/ios/world-builder-integration` pins
`world_builder.status/2026-08-23` (`TowerWorldBuilderClient.swift:24`) and must
adopt `…/2026-08-25` — a deliberate one-line change, because `pose_count`
changed meaning. `ProductShellTests.testTheTowerDeclaresNoCartridgeContracts`
is expected to fail the moment World Builder is declared; that failure is the
designed review trigger.

**Verification constraint.** There is no Swift toolchain on the development
machine (`xcodebuild`, `swift`, `swiftc` all absent — it is Windows). All iOS
code and tests are written here and marked **BUILD UNVERIFIED** until compiled
on the Mac. No iOS claim in any report may say "passing" until that happens.

---

## 6. Test plan

**Tower (runs here, must be green before handoff)**

- Schema pins for `poses.json`, `points.json`, `derived/manifest.json` — key
  sets, dtypes, `wxyz` order, null semantics.
- `content_hash` is stable across a rebuild that changes nothing; changes when
  a segment's geometry changes; is independent per segment.
- A closed segment's hash does not change when a later segment is added.
- Manifest arithmetic matches the derived manifest exactly (51 segments,
  19 resolved, 32 unresolved on the real fixture).
- `max_points` sampling reports `points_sent < points_total` and never silently
  truncates.
- Route returns 404 for unknown world/session/segment; never a partial body.
- The adapter is the only new module importing `world_builder`
  (boundary test updated deliberately).
- Reading and hashing never run on the event loop.
- The repudiated `pose_count` fallback no longer fires.

**iOS (written here, BUILD UNVERIFIED)**

- A `pose_convention` mismatch on any of the nine keys refuses the render.
- `translation: null` draws a break, not a line through a gap.
- Two unregistered segments are never composited into one space.
- A sampled cloud is labelled as sampled.
- `point_count: 0` renders as observed-but-unresolved, not as empty space.
- Cached segments are not refetched when `geometry.revision` changes but that
  segment's `content_hash` does not.

---

## 7. Requirements added at the approval gate

1. **The UI must distinguish unknown/unmapped space from known-but-unregistered
   fragments.** Implemented as the three-state model in §2, which also
   surfaces the observed-but-unresolved case covering 32 of 51 segments.
2. **The 2D small-multiples renderer is a V1 presentation layer, not a
   limitation of the contract.** Implemented in §3.4: the wire is fully 3D and
   a future 3D renderer consumes it unchanged.

---

## 8. Status

**DESIGN APPROVED — NOT IMPLEMENTED.** No code has been written. Physical
validation of anything below remains pending and cannot be claimed from this
machine.
