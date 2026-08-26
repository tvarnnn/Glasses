# World Builder — Mac validation handoff

**Cartridge:** World Builder
**Windows branch:** `integration/world-builder-lifecycle-v1`
**Range:** `3998e5a..HEAD` (36 commits)
**Written:** 2026-08-26, on Windows, with no Apple toolchain
**Supersedes:** `tower/docs/agent-handoffs/2026-08-25-GEOMETRY-TRANSPORT-PHYSICAL-TEST.md`
(absorbed whole — that file is now redundant)

This is the single current World Builder handoff. If a later wave changes the
contract, update this file rather than adding another.

---

## 0. The four states, kept apart deliberately

| State | What it means here |
|---|---|
| **DESIGN / CONTRACT INTENT** | §1-3. Agreed, reviewed, and the authority for repair decisions |
| **WINDOWS IMPLEMENTATION** | §4-6. Written and statically reviewed on Windows. Tower is tested; Swift is not |
| **MAC VALIDATION PENDING** | §7-9. Nothing in the Swift half has been compiled or run by anything |
| **PHYSICAL VALIDATION PENDING** | §10. Nothing here has met the glasses |

**Tower:** 1218 passed, 32 skipped, 0 failed — run on the Windows box.
**iOS:** 66 tests written across two files, **0 executed**.

---

# DESIGN / CONTRACT INTENT

## 1. What this cartridge now does, and the fact that shapes it

World Builder reconstructs geometry from the glasses' camera. Until this wave
that geometry reached nothing — `WorldCanvasView` said outright that the build
could not draw the Tower's world.

**The fact everything follows from:** the Tower reconstructs in *segments*, and
segments share **no coordinate frame**. Measured on the 2026-08-25 walk — 51
segments, every anchor at exactly `[0,0,0]` with identity rotation, only 19 with
any points, and per-segment scale disagreeing by up to **~87×** (camera spans
1.000 to 86.74 world units).

Drawing them together would superimpose 19 independent reconstructions:
plausible-looking, meaningless geometry. `guidelines/docs/modules/WORLD-BUILD.md:238`
forbids exactly that — an unknown region must render "as unknown, never as
blank-as-if-absent and never as fabricated."

**So the viewer draws separate fragments, not a map.** That is not a placeholder
awaiting a nicer design. It is the honest rendering of what the reconstruction
currently is, and it is why the UI says "N fragments, not yet connected."

## 2. The transport, and why it is HTTP

Two contracts, versioned independently:

| Contract | Transport | Carries |
|---|---|---|
| `world_builder.status/2026-08-25` | WebSocket, existing | counts, states, revisions |
| `world_builder.geometry/2026-08-25` | **HTTP, new** | poses and points |

**Geometry is not on the WebSocket, and this is not a preference.**
`tower/tower/routes/ws.py:38` gives the result sender and the frame path a single
shared `asyncio.Lock`. One session's `points.json` is **1,095,028 bytes** against
a **3,884-byte** status snapshot. Bulk data there would hold that lock and starve
`frame_result` — violating the result channel's own rule that it must never
affect the frame path.

**The segment is the unit of everything** — coordinate frame, cache key, delta
unit, LOD unit, progressive-appearance unit. `tower/tower/world_builder/engine.py:767`
freezes a segment when tracking is lost, so a closed segment never changes again:
it is fetched exactly once and cached for the life of the world. Live wire cost
is therefore **O(1) in walk length**, not O(N).

Full field tables: `docs/contracts/WORLD-BUILDER-GEOMETRY.md`.

## 3. The five rules a client may not break

1. **Pose-convention mismatch refuses the render.** Inverting `T_world_camera`
   still draws a plausible map — that was a real shipped bug once.
2. **`translation: null` survives to the renderer**, which draws a *break* in the
   camera path, not a line through the gap. A refused pose is not a measurement.
3. **`registered: false` forbids two segments sharing a coordinate space.**
4. **`points_sent` / `points_total` always travel**, so a sampled cloud can never
   read as the whole one.
5. **No imagery, ever.** `image_relpath` and every keyframe byte stay Tower-side.

---

# WINDOWS IMPLEMENTATION

## 4. Commits

**iOS-bearing** (newest first; the last three came from the merged branch and
were Mac-built previously):

| Commit | What |
|---|---|
| `4ac2bc0` | say when fragments on screen are behind the newest frames |
| `dd6212f` | a refused segment fetch must not blank a fragment forever |
| `61eaa20` | adopt `world_builder.status/2026-08-25`, show the world |
| `6b525b0` | **merge** `origin/ios/world-builder-integration` |
| `035eda0` | keep the fragments view constructible; prove its scale guarantee |
| `69d0063` | draw fragments, not a world that does not exist |
| `aa52708` | fetch geometry over HTTP, cached by content hash |
| `3390a30` | wire geometry tests into the target; correct a doc comment |
| `c3d9079` | decode the geometry contract |

**Tower commits defining the contract iOS consumes:**
`7f4053b` (segment grouping + hashing) → `1636b7b` (chunks + sampling) →
`b61a057` (sampling spans the cloud) → `7f9171a` (HTTP routes) →
`f312cd6` (boundary predicate) → `3a2840a` (**serve behind-the-journal geometry
with `current`**).

## 5. Swift files, and why each exists

**New:**

| File | Why |
|---|---|
| `WorldGeometry.swift` (272) | Types + decoder for the geometry contract. Pure, no networking — the one fully unit-testable piece |
| `WorldGeometryClient.swift` (95) | `URLSession` fetch + `WorldGeometryStore`, an actor caching chunks **by content hash, never by segment index** — a re-solved segment keeps its index and changes contents, so an index key would serve stale geometry |
| `WorldFragmentsView.swift` (196) | `WorldFragmentsModel` (pure layout, testable without rendering) + the small-multiples `Canvas` renderer |

**Changed:**

| File | Why |
|---|---|
| `WorldBuilderClient.swift` (+248) | `WorldBuilderViewModel` gains `geometryDidChange`, the fetch orchestration, and a `geometry:` DI seam for tests |
| `WorldCanvasView.swift` (+85) | Renders the fragment gallery below the existing summary rows, in the three snapshot-bearing states only |
| `TowerWorldBuilderClient.swift` (+635) | Contract bump to `/2026-08-25`; adds `WorldGeometryCoordinates` + `geometryUpdates` |
| `TowerConfiguration.swift` (+5) | `httpBaseURL` beside `webSocketURL` |
| `WorldBuilderWorkspaceView.swift`, `WorldModel.swift`, `CartridgeClient.swift`, `CartridgeAvailability.swift`, `ProjectManager.swift`, `TowerClient.swift`, `CartridgeResultChannel.swift` | From the merge — result-channel plumbing |

**Tests:** `WorldGeometryTests.swift` (689 lines, **36 tests**, new) and
`WorldBuilderIntegrationTests.swift` (1022, **30 tests**, from the merge).

## 6. Behaviour, precisely

**Data flow.** Status arrives on the WebSocket → `geometryCoordinates(from:)`
reads `session.session_id` + `geometry.revision` + `world_snapshot.world_id` →
if the revision changed, fetch the manifest → compare each segment's
`content_hash` against the cache → fetch only the missing ones → publish.

**Why the session id comes from the payload's top-level `session` block:**
`world_snapshot` does not carry one, and the Tower's manifest route requires
`session_id` as a non-defaulted query parameter (`tower/tower/routes/geometry.py:34`)
— a world id alone returns 422. Widening `WorldSnapshot` would have broken its
field-for-field promise and its `Equatable`.

**Refetch is gated on revision change, never on arrival.** The status channel
heartbeats an unchanged snapshot roughly every 2 s; keying on arrival would
refetch ~1 MB twice a second for a world that is not changing.

**Absent / null / zero.** `null` means absent, never zero, at every layer. A
refused pose keeps `nil` translation. An unresolved segment keeps `nil` bounds —
never a zero-size box. `pose_count: 0` with `keyframe_count: 155` is "no
trajectory", not "missing value".

**Caching.** By content hash. Closed segments are immutable, so each transfers
once and is kept for the world's life. `retainOnly` drops entries the current
manifest no longer names, so a long walk does not accumulate superseded chunks.

**Reconnect.** Inherited from the status channel: resubscribe, receive a
complete snapshot, compare hashes, fetch what is missing. There is no delta
stream, therefore no gap, therefore a cursor cannot lose data.

**A failed fetch is not sticky.** If any segment fetch fails, `lastGeometryRevision`
is cleared after publishing, under the same staleness guard — so the next
heartbeat retries. Without this, a transient blip would blank a fragment
*forever* on a finalized world, whose revision never moves again.

**Persistence.** None on iOS. The cache is in-memory and per-session.

**Privacy.** No imagery crosses the wire. The client has no code path that could
request an image.

**Expected UI states:**

| Situation | Screen |
|---|---|
| Nothing mapped | "The glasses have not mapped anything here yet." Not an empty canvas — that reads as an empty room |
| Fragments exist | "N fragments, not yet connected" + one auto-framed tile each |
| Geometry behind the journal | a note that the world is still building |
| Segments seen but unreconstructed | "N areas were seen but could not be reconstructed" — **counted, never drawn**, because we know reconstruction failed but not *where* |
| Sampled cloud | "showing X of Y" |

**Interaction:** none yet. Tiles are static. Pinch/drag and saved-world reopen
are not implemented — see §11.

---

# MAC VALIDATION PENDING

## 7. Nothing here has been compiled

There is no Swift toolchain on the Windows box — `xcodebuild`, `swift` and
`swiftc` are all absent. Every iOS commit says **BUILD UNVERIFIED** and means it
literally. 66 tests are written; **0 have run**.

```bash
git checkout integration/world-builder-lifecycle-v1
xcodebuild -scheme Glasses -destination 'platform=iOS Simulator,name=iPhone 15' build
xcodebuild -scheme Glasses -destination 'platform=iOS Simulator,name=iPhone 15' test
```

## 8. Compiler-sensitive areas — check these first

Ranked by how likely they are to be wrong, with the reasoning that was applied
statically so you can tell whether it held:

1. **`[String: Any]` cast behaviour in the decoder.** Test fixtures build nested
   literals; the decoder casts with `as? [Double]`, `as? Int`, `as? Bool`. The
   static argument was that these are native Swift values boxed in `Any` rather
   than `NSDictionary` bridges, so the casts succeed. **If that is wrong, every
   decoder test fails identically** — that signature means this, not 36 separate
   bugs.
2. **Memberwise initialisers.** `WorldPoseConvention`, `WorldSegmentSummary` and
   `WorldPose` declare `init?(json:)` in **extensions**, deliberately — an `init`
   in the struct body suppresses the memberwise init that the tests use. If you
   see "extra argument" or "missing argument" errors constructing these in
   tests, that is the cause. **Do not fix it by rewriting the tests.**
3. **`Swift.min` / `Swift.max` in `WorldFragmentsModel.projector`.** `WorldBounds`
   has stored properties named `min` and `max`; without the `Swift.` prefix these
   resolve to the properties and fail. Three call sites.
4. **Actor hops.** `WorldGeometryStore` is an `actor`; the app target sets
   `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`, the test target does not. Static
   analysis said strict concurrency is **not** in force (`SWIFT_VERSION = 5.0`,
   no `SWIFT_STRICT_CONCURRENCY` key anywhere) — verify that.
5. **`WorldGeometryTests.swift` target membership.** Added to `project.pbxproj`
   **by hand** — build file `4E8D7950967282CF51E8CBE3`, file ref
   `0EBE6B82C2538A025B0E3C4C`. `GlassesTests` is a plain `PBXGroup` with an
   explicit children list, not a synchronized group. If Xcode disagrees, re-add
   through the UI. **A missing test file looks exactly like a passing suite.**
6. **`URLProtocol` stub** in the retry tests uses lock-guarded static state, and
   `protocolClasses` relies on array-literal coercion to `[AnyClass]`.

**Types whose exact Swift spelling could not be verified here:** every SwiftUI
API in `WorldFragmentsView.swift` — `Canvas { context, size in }`,
`GraphicsContext.fill/stroke`, `Path(ellipseIn:)`, `LazyVGrid`,
`GridItem(.adaptive(minimum:))`, `.clipShape`, `.foregroundStyle`. These were
written from knowledge, not from a compiler.

## 9. What you may fix without asking

**Fix freely** — implementation-level mistakes that preserve the design:
syntax, imports, cast forms, actor/`await` placement, target membership,
API spellings, test scaffolding, anything the compiler simply rejects.

**Do not change without evidence** — these are the design, and several are
load-bearing against defects that already happened once:

- geometry over HTTP rather than the WebSocket (§2)
- cache keyed by content hash, never segment index
- the five rules in §3
- fragments never composited into one canvas
- unresolved segments counted but never *placed*
- refetch gated on revision change, not arrival
- `current: false` served rather than 404'd

If the compiler or runtime reveals a genuine architectural flaw in any of those,
document the evidence and revise the contract deliberately — do not work around
it silently.

**Expected results if it compiles:** 66 tests pass. The load-bearing negatives
worth confirming by name are
`testUnregisteredSegmentsAreNeverCompositedIntoOneCanvas`,
`testEachFragmentIsScaledToItsOwnBoundsAndNeverToASharedOne`,
`testARefusedPoseDecodesAsNilTranslationNotZero`,
`testAnUnresolvedSegmentIsCountedButNeverGivenAFragment`,
`testAMalformedSegmentRowDropsTheWholeManifest` and
`testARefusedSegmentIsRetriedUnderTheSameRevision`.

---

# PHYSICAL VALIDATION PENDING

## 10. The walk

Build first. A build failure is indistinguishable from a Tower problem when
viewed from the phone.

```powershell
powershell -NoProfile -File scripts\start_tower.ps1
curl.exe http://localhost:8000/health
```

`.env` already sets `TOWER_CAPTURE_ROOT` and `TOWER_WORLD_ROOT`, and a
calibration for 360×640 exists (`self_calibrated`, 511 views, 0.289 px RMS), so
this should reach `classical-sfm` rather than downgrading.

Open World Builder → **Start** → walk ~60 s → **Stop**.

**Walk the way the reconstruction wants, which is not how people walk.**
Translate, don't pan: the dominant refusal on the last walk was `low_parallax`
(164 of 312), which is turning on the spot. Sidestep along a wall, keep the far
wall in view, turn your body rather than your head.

**Watch, in order:**

1. **Fragments appear DURING the walk.** This is the entire claim. Previously the
   phone showed counters only.
2. Headline reads **"N fragments, not yet connected"** — not "1 world". Expect a
   number near 19, and expect it to look *ugly*. That is honest.
3. A note that the world is still building, which should clear shortly after Stop.
4. "N areas were seen but could not be reconstructed" — expect roughly 30.

**Failure signatures:**

| Signature | Meaning | First check |
|---|---|---|
| No tiles ever | manifest 404 | `curl.exe "http://localhost:8000/worlds/<wid>/geometry/manifest?session_id=<sid>"` |
| Tiles only after Stop | the `current: false` path is not working | same curl **during** a walk — must be 200 with `"current": false` |
| "Update the app" | contract mismatch | Tower emits `/2026-08-25`; app must pin the same |
| One tile holding everything | segments merged | would be a **Tower** bug — nothing registers segments |
| **Tiles look like a plausible room** | **something composited them** | **Report it.** Segments disagree in scale by ~87× |
| Tile count ≠ geometry counter | decode error | compare against `geometry.element_count` |
| `poses 0, points 0, uncalibrated` | calibration not found | confirm the stream really is 360×640 |

Every failure except the fifth is visible as absence. That one is visible as
success, which is why it is the one to stare at.

**Send back:** when the first tile appeared (during, or after Stop); the headline
verbatim; the new world's `derived/manifest.json` (13 numbers); a photo mid-walk
if a tile appeared; any Xcode error. **Not** full logs or imagery.

---

## 11. Known limitations — deliberate, not oversights

- **No interaction.** Tiles are static; no pinch, drag or selection.
- **No saved-world reopen or replay.** The Tower can serve any world by id; iOS
  has no picker. `WorldInspectionMode` is modelled and permanently `.live`.
- **No registration.** Segments are never merged, so the gallery stays a gallery
  until cross-segment registration exists. This is the largest remaining gap and
  it is Tower-side.
- **Fetches all segments**, including the ~32 of 51 that resolved to nothing and
  are never drawn.
- 21 further deferred findings, each triaged:
  `tower/docs/superpowers/plans/2026-08-25-geometry-transport-followups.md`.

Whether 360×640 supports *useful* reconstruction is still open. The last walk
solved 94 poses from 457 keyframes — real, but 64% of keyframes resolved to
nothing. **This test measures whether the transport and viewer work. It does not
measure whether the world is good, and a disappointing map is not a failure of
this wave.**
