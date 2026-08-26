# World Builder — the Tower↔iOS boundary, reconciled

> **iOS ENTRY POINT IS `docs/agent-handoffs/IOS-EXECUTION-PLAN.md`.**
> This file is **REFERENCE**: deeper detail, still accurate except where
> the plan says otherwise. Read the plan first — it says what to do now,
> what is already settled, and what the Tower has measured and refused.
> Where the two disagree, the plan wins.

**Living document.** It describes the boundary as it exists now.

**Status:** implemented on both sides and exercised end to end over a real
socket. Not yet exercised against the Ray-Ban camera — see
`docs/agent-handoffs/WORLD-BUILDER-INTEGRATION.md` for exactly what has and
has not met hardware.

**The wire itself** is `tower/docs/contracts/CARTRIDGE-RESULTS.md`, which is
the Tower's document and the authority on message shapes. This document is the
part neither side owns alone: **which Tower field becomes which Swift value,
and what happens where the two vocabularies do not line up.**

Contracts in play:

| | |
|---|---|
| Envelope | `cartridge_results.envelope/2026-08-23` |
| World Builder payload | `world_builder.status/2026-08-25` |
| World Builder geometry | `world_builder.geometry/2026-08-25` — **its own document: [`WORLD-BUILDER-GEOMETRY.md`](WORLD-BUILDER-GEOMETRY.md)**. Different transport (HTTP), versioned independently |
| Tower cartridge name | `world_builder` |
| iOS catalog id | `world-build` |

Those last two are **different strings for the same cartridge**, and the
mapping lives in exactly one place: `TowerCapabilities.towerCartridgeNames`.

---

## 1. The shape of the seam

```
 Tower web process ──ws://…/ws──┐
                                │  one socket, six inbound message types
                                ▼
                        TowerClient            decodes the envelope.
                                │              Knows no cartridge.
                                │ cartridgeResults / $cartridgeDeclaration
                                ▼
                    TowerWorldBuilderClient    owns the contract, the
                                │              subscription, and the mapping.
                                │              Built by ProjectManager, so it
                                │              outlives every workspace switch.
                                │              ALSO drives the geometry pull
                                │              below, off geometry.revision.
                                │ stateUpdates
                                ▼
                    WorldBuilderViewModel      republishes into SwiftUI.
                                │
                                ▼
                      WorldCanvasView          renders facts.

 Tower web process ──http://…/worlds/{id}/geometry/{manifest,segment/{i}}──┐
                                │  world_builder.geometry/2026-08-25       │
                                │  PULLED, not pushed. Contract, tables    │
                                │  and rules: WORLD-BUILDER-GEOMETRY.md    │
                                ▼                                          │
                    WorldGeometryClient ── WorldGeometryStore ── WorldFragmentsView
```

**No second socket, no second connection, no view-owned transport** for status.
Discovery, subscription and results share the socket the camera already streams
over. `frame_result` is field-for-field unchanged and pinned by a test.

**Geometry is the one thing that does not travel that way**, and the reason is
in the code: `tower/tower/routes/ws.py:38` gives the result sender and the
frame path a single `asyncio.Lock`, and one session's `points.json` is 1.07 MB
against a 3,884-byte status snapshot. Sending it there would hold that lock and
starve `frame_result`. It is an ordinary HTTP `GET` instead, pulled when the
status payload's `geometry.revision` moves. See
[`WORLD-BUILDER-GEOMETRY.md`](WORLD-BUILDER-GEOMETRY.md).

---

## 2. Reconciliation matrix

Verdicts: **CLEAN** (1:1), **ADAPTER** (small mapping, no duplicated state),
**IOS-ONLY** (no Tower field; the phone is the only machine that can know),
**UNREACHABLE** (modelled on one side, no code path on the other),
**HARDWARE** (correctness depends on something only a physical run settles).

### 2.1 Lifecycle

| Tower `model_state` | Swift `WorldModelState` | Verdict | Notes |
|---|---|---|---|
| `unsupported` | `.unsupported(reason:)` | CLEAN | `model_state_reason` verbatim; a fallback sentence when null |
| `idle` | `.idle` | CLEAN | Tower's reason is dropped — `.idle` carries none. Its prose ("no worlds exist under this Tower's world root") is diagnostic, not actionable |
| `receiving` | `.receiving(snapshot)` | ADAPTER | With `world_snapshot: null` → `.awaitingFirstUpdate`. Unreachable in practice; a live session implies a world |
| `finalizing` | `.finalizing(snapshot)` | ADAPTER | **Read the caveat in §3.** |
| `finalized` | `.finalized(snapshot)` | CLEAN | |
| `failed` | `.failed(.towerReportedFailure)` | CLEAN | Attribution matters: the Tower reported it, so it is not `.transport` and not `.notSupported` |
| *(never sent)* | `.awaitingFirstUpdate` | IOS-ONLY | Subscribed, not yet answered. Only the phone can know this, which is why Tower does not send it |
| unknown word | `.failed(.undecodableResponse)` | ADAPTER | A disagreement discovered on arrival, not an empty world |

### 2.2 `world_snapshot` → `WorldSnapshot`

Every field below is optional on both sides, and **null means absent, never
zero**.

| Tower | Swift | Verdict |
|---|---|---|
| `name` | `name` | CLEAN — null means unnamed; no name is derived |
| `world_id` | `worldID` | CLEAN |
| `keyframe_count` | `keyframeCount` | CLEAN |
| `revision` | `revision` | CLEAN — opaque, equality only. Same string as the envelope's |
| `tracking` (`good`/`lost`/`unavailable`) | `WorldTrackingQuality` | CLEAN. `limited` is mapped but **never sent** — it needs a threshold nobody has defined |
| `scale` | `WorldScaleSemantics` | CLEAN — **Tower sends iOS's vocabulary**, not its own. See §4 |
| `mapping_seconds` | `mappingSeconds` | CLEAN — **the Tower's clock.** Never derived from a phone timer. Nothing renders it today |
| `calibration` (`unknown`/`uncalibrated`/`calibrated`) | `WorldCalibrationState` | CLEAN. `calibrating` mapped but **never sent** — calibration is an offline procedure |
| `geometry.representation` | `geometry.representation` | CLEAN — opaque label, displayed verbatim, never parsed |
| `geometry.element_count` | `geometry.elementCount` | CLEAN — shown only beside the label, never alone |
| `geometry.is_incremental` | `geometry.isIncremental` | CLEAN — always `false`; a build replaces the whole tree |
| `trajectory.pose_count` | `trajectory.poseCount` | CLEAN |
| `trajectory.path_length` / `_unit` / `scale` | `WorldTrajectoryReport` | ADAPTER — see §4 |
| `persistence.state` / `revision` | `WorldPersistenceState` | CLEAN — `saved` is the only reachable state; `session` is unreachable by construction |

### 2.3 Availability

| Tower | Swift | Verdict |
|---|---|---|
| cartridge absent, or in `not_offered` | `.noContract` | CLEAN. `not_offered` is **not decoded** — both readings mean "the Tower has declared nothing" |
| declared, contract we do not implement | `.unsupportedContract` | CLEAN — tells a person to update the app, not to reconnect |
| declared, `available: false` | `.available` + `.unsupported(reason:)` | ADAPTER — see §5 |
| declared, `available: true`, socket up | `.available` | CLEAN |
| declared, socket down | `.towerUnreachable` | ADAPTER — the cached declaration deliberately survives a drop |

### 2.4 Not consumed, and deliberately

The payload's other ten blocks — `world`, `session`, `lifecycle`, `progress`,
`tracking`, `calibration`, `scale`, `geometry`, `trajectory`, `persistence`,
`artifacts` — are **Tower-native evidence** for the two halves above. iOS reads
none of them. A reader looking for where they are consumed will correctly find
that they are not.

| Not consumed | Why |
|---|---|
| pose arrays, point clouds | Not on **this** channel, and deliberately: they are bulk, and this socket shares its send lock with the frame path. They travel over HTTP under `world_builder.geometry/2026-08-25` instead — see [`WORLD-BUILDER-GEOMETRY.md`](WORLD-BUILDER-GEOMETRY.md) |
| keyframe images | **The Tower does not send them, on any channel.** `retains_raw_imagery` stays true Tower-side; no byte of imagery crosses to iOS, redacted or not |
| `progress.frames_observed` | Null while live and genuinely unknowable — an ordinary rejected frame writes no journal event |
| `lifecycle.build_in_progress` | `null` in every stopped state, and null means **unobservable**, not `false` |
| `artifacts.*`, `session.retains_raw_imagery` | Real and honest, but no iOS surface asks the question yet. See §6 |

---

## 3. `finalizing` means something narrower than it looks

Tower has **no** `finalizing` lifecycle state, deliberately: a build rewrites
several files before its manifest lands, and those writes are indistinguishable
from a build that made them and then died. The writer lock is already released,
so nothing on disk says "a process is working right now".

`model_state: "finalizing"` is projected from `lifecycle: stopped_unbuilt`, and
means **"the stored figures are not the final figures"** — not "a process is
working". iOS renders `.finalizing` with a progress indicator and the sentence
"Capture has ended. The Tower is still working, so these figures may still
change." The second half of that sentence is the claim the Tower can support;
the spinner is the part to revisit if this ever misleads.

---

## 4. Scale — the load-bearing refusal

**Reachable states in V1 are `unknown` and `relative`. That is all.**
`inferredMetric` and `measuredMetric` have no code path that produces them on
monocular hardware. Both are still mapped rather than discarded, so that one
arriving later is not silently downgraded.

- `relative` = internally consistent with an arbitrary unit fixed by whatever
  baseline the first solved pair happened to have. **Not metric.**
- `unknown` = **no unit at all**, a strictly weaker claim. Never mapped to
  `.relative`.

Two gates in `WorldTrajectoryReport`, and they answer different questions:

| | Asks | Tower answer today |
|---|---|---|
| `distanceDisplayable` | may this be shown as a **physical distance**? | always false |
| `labelledFigureDisplayable` | may this be shown as **the labelled figure it is**? | true when a unit is present |

The second is new. Refusing on scale alone meant the panel would never show a
path length at all, because `relative` is the best this hardware reaches — and
"6.6 world units", with the Tower's own unit attached and
"Shape and layout only. No real-world distances are claimed." beneath it, is
not a distance claim. **The gate is the unit, not the scale**: a bare number is
what a reader silently reads as metres.

---

## 5. `available: false` is an offer, not silence

A Tower that declares World Builder and cannot serve it right now — no world
root configured, typically — is saying something quite different from a Tower
that has never heard of it, and the two call for opposite responses.

iOS therefore resolves the contract to `.available` (this Tower speaks an
agreement we implement, and we can reach it) and carries the unserveability in
the **domain state**, as `.unsupported(reason:)` with the Tower's prose
verbatim. It does not subscribe. Collapsing the offer to `.noContract` would
render "no world root is configured" as "this Tower will never do this".

The cached declaration also **survives a disconnect**, for the same reason: what
a Tower can do is a property of its build, not of the socket. Clearing it would
turn every WiFi blip into "this will never work" when the truthful reading is
"not reachable".

---

## 6. What iOS does not implement yet

| Missing | What exists Tower-side | What iOS needs |
|---|---|---|
| **World picker / reopen a saved world** | `result_subscribe` with `world_id` pins the channel to a stored world — the Tower half of `WorldInspectionMode.inspecting(worldID:)` | A list of worlds and a way to choose one. `WorldInspectionMode` is modelled and always `.live` |
| **Replay** | `WorldView.trajectory(session_id)` returns per keyframe: pose, segment, pose status, and `image_relpath` — a recorded camera path with a real first-person view at each point. `world_inspect.py --trajectory` renders it today | The poses and points now cross the wire (geometry contract) and iOS draws them 2D, per segment. What is still missing is the **first-person view**: `image_relpath` and every keyframe byte stay Tower-side, and a 3D view needs a floor plane that does not exist (`up_axis: "unknown"`) |
| **Privacy disclosure** | `retains_raw_imagery: true` and the redaction process claim are on every session record | A surface that states what the Tower keeps. See §7 |
| **Calibration status/action** | `calibration` state is on the wire and rendered | Nothing invites or explains calibration, and without it there is no geometry at all (§7) |

---

## 7. Two facts a reader will otherwise get wrong

**Starting capture is not starting a build.** The Tower web process writes
frames to a capture and answers `frame_result`. Reconstruction runs in a
**separate process** (`scripts/world_build_session.py --follow-capture`) reading
that capture from disk. Nothing on the phone starts it and nothing on the phone
can see whether it is running. Every string in the World Builder workspace was
rewritten to stop implying otherwise.

**Without intrinsics there is no geometry.** `select_backend` downgrades to
`UnposedBackend` when intrinsics are unknown, and no flag invents a focal
length. A real walk with no calibration produces keyframes, `tracking: good`,
`scale: unknown`, `poses_solved: 0` and `points: 0` — truthful, and empty.
Calibration is `scripts/calibrate_charuco.py` against a **printed, physically
measured** board, and the intrinsics must be calibrated at the **delivered
resolution**: `_require_matching_resolution` refuses to apply a 480×360
calibration to 640×360 frames rather than silently scaling the world by the
ratio.

**Redaction is a process claim, never an outcome claim.** The recorded value is
`faces-detected-and-filled/yunet-2023mar@0.30`. Never "redacted", "anonymised"
or "privacy-safe" — YuNet has measured false negatives on faces occluded past
~60% and rotated ~90°, and `retains_raw_imagery` stays **true**: bodies,
clothing, room contents and any undetected face are still in the image. No
imagery crosses to iOS, before or after redaction.
