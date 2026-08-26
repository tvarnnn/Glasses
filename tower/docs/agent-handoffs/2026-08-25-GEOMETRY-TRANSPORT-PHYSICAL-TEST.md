# Geometry transport — physical test

**Date:** 2026-08-25
**Branch:** `integration/world-builder-lifecycle-v1`
**Tower:** 1218 passed / 32 skipped / 0 failed, run on the Windows box
**iOS:** written on Windows, **never compiled**

This is the first build in which reconstructed geometry can reach the phone.
Nothing below has met the glasses.

---

## 0. The gate: build the iOS app first

There is no Swift toolchain on the Tower machine — `xcodebuild`, `swift` and
`swiftc` are all absent. Every iOS commit on this branch says **BUILD
UNVERIFIED** and means it. Six Swift files are new or heavily changed:

```
ios/Glasses/Workspaces/WorldBuilder/WorldGeometry.swift          (new)
ios/Glasses/Workspaces/WorldBuilder/WorldGeometryClient.swift    (new)
ios/Glasses/Workspaces/WorldBuilder/WorldFragmentsView.swift     (new)
ios/Glasses/Workspaces/WorldBuilder/WorldBuilderClient.swift     (changed)
ios/Glasses/Workspaces/WorldBuilder/WorldCanvasView.swift        (changed)
ios/GlassesTests/WorldGeometryTests.swift                        (new, 20 tests)
```

On the Mac:

```bash
git pull
xcodebuild -scheme Glasses -destination 'platform=iOS Simulator,name=iPhone 15' build
xcodebuild -scheme Glasses -destination 'platform=iOS Simulator,name=iPhone 15' test
```

**Paste any compiler error back and it gets fixed.** Expect one or two rounds —
this is Swift that no compiler has seen. The likeliest failures, in order:

1. A `[String: Any]` cast that Swift infers differently than predicted.
2. `WorldGeometryTests.swift` not in the test target. It was added to
   `project.pbxproj` by hand (build file `4E8D7950967282CF51E8CBE3`, file ref
   `0EBE6B82C2538A025B0E3C4C`); if Xcode disagrees, re-add it through the UI.
3. An actor-isolation complaint around `WorldGeometryStore`.

Do not run the walk until this builds. A failed build looks exactly like a
Tower problem from the phone side.

---

## 1. Start the Tower

```powershell
powershell -NoProfile -File scripts\start_tower.ps1
```

`.env` already sets `TOWER_CAPTURE_ROOT=data` and
`TOWER_WORLD_ROOT=data/world_builder`. A calibration for the streamed
resolution already exists at `data/world_builder/intrinsics/360x640.json`
(`self_calibrated`, 511 views, 0.289 px RMS), so this run should reach
`classical-sfm` rather than downgrading.

**Confirm the new route is alive before walking** — one command, and it saves a
whole walk if it fails:

```powershell
curl.exe http://localhost:8000/health
```

---

## 2. The walk — keep the first one to about 60 seconds

Open World Builder on the phone, press **Start**, walk, press **Stop**.

Walk the way the reconstruction wants, which is not how people naturally walk:
**translate, don't pan.** On the 2026-08-25 walk the dominant refusal reason was
`low_parallax` (164 of 312), which means turning on the spot. Sidestep along a
wall. Keep the far wall in view. Turn your body, not just your head.

---

## 3. What to watch, in order of importance

**1. Fragments appear DURING the walk.** This is the entire claim of this
branch. Previously the phone showed counters only. If tiles appear only after
Stop, see failure signature B.

**2. The headline reads "N fragments, not yet connected."** Not "1 world". On
the last real walk the Tower produced 51 segments of which 19 had geometry, so
expect a number in that range — and expect it to be *ugly*. That is the honest
rendering. Nineteen disconnected tiles is what the reconstruction actually is.

**3. A note saying the world is still building.** While the derived tree is
behind the live journal, the manifest carries `current: false` and the UI says
so. It should appear during the walk and disappear shortly after Stop.

**4. "N areas were seen but could not be reconstructed."** Expect roughly 30.
This is the third truthfulness state and it is deliberately not drawn as
space — we know reconstruction failed, not where.

**5. Segment count.** 51 on a 154-second walk was one break every 3 seconds.
Note what a 60-second walk gives.

---

## 4. Failure signatures

| Signature | Meaning | First check |
|---|---|---|
| **A.** No tiles at all, ever | Manifest 404 | `curl.exe "http://localhost:8000/worlds/<world_id>/geometry/manifest?session_id=<sid>"`. Get the ids from `data/world_builder/worlds/` |
| **B.** Tiles only after Stop | The `current: false` path is not working; the route is still hiding behind-the-journal geometry | Same curl **during** a walk — it must return 200 with `"current": false`, not 404 |
| **C.** Phone says "update the app" | Contract mismatch | The Tower emits `world_builder.status/2026-08-25`; the app must pin the same string |
| **D.** One tile holding everything | Segments merged | Would be a **Tower** bug today — nothing registers segments. Check `segments` in the derived manifest |
| **E.** Tiles look like a plausible room | **Suspicious, not good** | Segments share no frame and disagree in scale by up to ~87x. A room-like picture means something composited them. Report it |
| **F.** Tile count disagrees with the geometry counter | Decode error | Compare the tile count against `geometry.element_count` in the status payload |
| **G.** `poses 0, points 0, calibration uncalibrated` | The calibration was not found | Confirm the stream really is 360x640; the store is keyed by observed frame size |

Signature **E** is the one worth staring at. Every other failure is visible as
absence. That one is visible as success.

---

## 5. What to send back

Small and specific:

1. Roughly when the first tile appeared — during the walk, or after Stop.
2. The headline text, verbatim.
3. The `derived/manifest.json` from the new world (13 numbers, tiny).
4. A photo of the screen mid-walk if a tile ever appeared.
5. Any Xcode error from §0.

Not needed: full logs, the point cloud, or keyframe imagery — imagery never
leaves the Tower by design.

---

## 6. Known-unknown

Whether 360x640 supports reconstruction well enough to be *useful* is still
open. The 2026-08-25 walk solved 94 poses out of 457 keyframes — real, but 64%
of keyframes resolved to nothing. This test measures whether the transport and
the viewer work. It does not measure whether the world is good, and a
disappointing map is not a failure of this branch.

The likeliest next lever is capture resolution: DAT offers 720x1280, the app
currently streams 360x640, and frames are ~20.8 KB JPEG at ~2 Mbps — so there
is headroom. That is a separate piece of work.
