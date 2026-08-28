# World Builder — status and outstanding validation

**Date:** 2026-08-26
**Branch:** `integration/world-builder-lifecycle-v1`
**Status:** **IMPLEMENTATION COMPLETE — MAC VALIDATION AND PHYSICAL VALIDATION PENDING**

Not "done". Two whole classes of verification have not happened, and this
document exists so the broader cartridge program can proceed without either
forgetting them or waiting on them.

Companion documents:
- `docs/agent-handoffs/WORLD-BUILDER-MAC-HANDOFF.md` — how to compile, test and
  physically validate. The operational doc.
- `docs/contracts/WORLD-BUILDER-GEOMETRY.md` — the wire contract.
- `tower/docs/superpowers/plans/2026-08-25-geometry-transport-followups.md` — 21
  deferred findings, each triaged.

---

## 1. What is implemented and verified here

**Tower: 1307 passed, 32 skipped, 0 failed**, run on this machine.

| Capability | State |
|---|---|
| Geometry transport (manifest + per-segment chunks over HTTP) | done, tested |
| Content-hash caching, O(1) live wire cost | done, tested |
| Behind-the-journal geometry served with `current: false` | done, tested |
| Three-state truthfulness model | done, tested |
| Tracking continuity | done, measured on five real captures |
| Cross-segment registration | done, gate verified under adversarial attack |
| Landmark association (`support.json`) | done, 0.435× the size of `points.json` |
| Contract versioning, absent-vs-zero, reconnect | done, tested |
| iOS decoder, HTTP client, cache, fragments renderer | **written, never compiled** |

### The two measured results worth carrying forward

**Tracking was losing reach, not losing the image.** Of 50 declared segment
breaks on the real walk, 47 still had survival above the floor against the
previous frame. The reference advances only on an accept, so a run of blurred
frames froze it while the camera kept moving — up to 89 frames stale. Two
constants (`LK_MAX_LEVEL` 3→4, forward-backward 1.0→3.0) took five real
captures from 151→114 segments while *raising* solved poses 211→**265** and
points 27,406→**42,100**.

**Registration merges only what two independent solves agree on.** On the real
world: 51 segments, 19 with geometry, **3 registered (4, 5, 32) carrying 31.1%
of all points.** It refuses (30,50) and (5,6) — both of which fit well.

---

## 2. Physical validation requirements — the full list

None of the following has been done. Each states what would settle it.

### 2.1 Blocking the product claim

| # | Requirement | Settled by | Why it cannot be settled here |
|---|---|---|---|
| P1 | **The iOS half compiles** | `xcodebuild build` on a Mac | No Swift toolchain on this machine — `xcodebuild`, `swift`, `swiftc` all absent |
| P2 | **The 66 iOS tests pass** | `xcodebuild test` | Same. They are written and have never been executed by anything |
| P3 | **Fragments appear DURING a walk** | One ~60 s walk, watching the phone | This is the entire claim of the geometry transport and only hardware exercises it |
| P4 | **The geometry route is reachable from the phone** | The walk, or `curl` from the phone's network | Tailscale address is hardcoded; nothing has fetched geometry over a real link |

### 2.2 Correctness the tests cannot reach

| # | Requirement | Settled by |
|---|---|---|
| P5 | **`current: false` clears after Stop** | Observing the note disappear once the final build lands |
| P6 | **A mid-walk WiFi drop still yields one world** | Deliberately breaking the link mid-walk; expect the capture to chain and **no second worker** |
| P7 | **Redaction fires on real bystanders at real distances** | Footage containing an actual second person. **Not available**: measured on the current corpus, the "people" are the wearer's own torso (median box bottom edge 0.981, 59% touching the frame edge) |
| P8 | **The tracking change holds on a fresh walk** | A new capture. Per-capture variance is large and bidirectional — one capture went 27→111 poses, another 94→61 — so a single walk can neither confirm nor refute it |

### 2.3 Registration, which is newest and least exercised

| # | Requirement | Settled by |
|---|---|---|
| P9 | **A registered pair is actually correct** | Walking a loop that revisits a place, then checking the merged fragments line up with the room. **Nothing automated can catch a wrong Sim3** — pair (30,50) fits at 1.62 px with 88% of points under 3 px while being 3.2× wrong on scale |
| P10 | **Cycle consistency** | A capture whose link graph contains a cycle. The current graph is a 3-node path, so composition has **no independent check**. This is the first thing to add when a cycle appears |
| P11 | **Deliberate translation raises the registrable fraction** | A walk where the wearer sidesteps rather than pans. 16 of 19 segments are refused for `span/depth` — the wearer stood still, so scale is unobservable. This is the single highest-leverage physical experiment available |

### 2.4 Settled — recorded so they are not re-run

| Question | Answer | Evidence |
|---|---|---|
| Is calibration the blocker? | **No.** Solved | `intrinsics/360x640.json`, self-calibrated, 511 views, 0.289 px RMS |
| Would 720p help tracking? | **No — it would hurt** | Halving resolution *improved* survival 0.874→0.930; displacement-limited, not feature-starved. And `min_sharpness = 25.0` is absolute: at 720p **73.3%** of frames fall below it and are rejected as blurred |
| Is 1080p available? | **No** | DAT offers 720×1280 / 504×896 / 360×640, all 9:16. No landscape mode at any resolution |
| Is the iOS client missing? | **No** | It was on `origin/ios/world-builder-integration` the whole time; a prior handoff searched only the wrong remote |

---

## 3. What is NOT implemented, deliberately

- **Interaction.** Fragment tiles are static — no pinch, drag or selection.
- **Saved-world reopen / replay.** The Tower serves any world by id today; iOS
  has no picker. `WorldInspectionMode` is modelled and permanently `.live`.
- **Registration in the production path.** It exists as
  `tower/scripts/world_registration.py`, an offline analysis tool. It does not
  yet write `registered` / `transform_to_world` into the served contract. That
  wiring is a deliberate next decision, informed by the fact that only 3 of 19
  segments currently qualify.
- **Metric scale.** Unreachable on monocular hardware by any route in V1.
- **Performance instrumentation** beyond `observe_ms_per_frame` and
  `build_seconds`.

---

## 4. The honest summary

The transport works and is tested. Tracking is measurably better on the numbers
that matter — and the one time this session optimised segment count without
checking solved poses, it shipped a change that cost a third of the
reconstruction, which is recorded in `keyframes.py` so it is not repeated.
Registration produces its first merged geometry and refuses more than it
admits, which is the correct ratio for a system that must never fabricate a
room.

What stands between this and a finished product is not more Tower code. It is a
Mac compiler, a wearer who walks sideways, and a loop closure that gives
composition something to check itself against.
