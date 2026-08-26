# iOS execution plan — the single current handoff

> **The Mac lane has now answered §3.1 and §3.2.** Results, the one
> defect found, and where physical validation actually stopped:
> **[`MAC-BUILD-VERIFICATION.md`](MAC-BUILD-VERIFICATION.md)**.
> The Swift compiles; 388 tests pass; the phone needs one tap.

**START HERE.** This is the one document Mac Claude needs. Everything else
iOS-facing is either a contract it points to, or reference material
classified in §7. Where another document disagrees with this one, **this
one wins** and the other is stale.

**Ownership, as of 2026-08-26:** `ios/` belongs to Mac Claude exclusively.
The Tower lane does not modify it. When Tower work creates an iOS
requirement, it is written here instead of implemented.

**Tower lane:** `integration/world-builder-lifecycle-v1`.
**Tower suite:** 1547 passed, 30 skipped, 0 failed.
**Tower host:** Windows, no Apple toolchain — `swiftc`, `swift` and
`xcodebuild` are all absent, so **no Swift has ever been compiled in the
Tower lane.** (As of 2026-08-26 the Mac lane has begun compiling on
`ios/world-builder-integration` and has the app running on a phone. Where
this document's §3.1 and §4 disagree with an actual `xcodebuild` result,
**the compiler wins** — those sections were written without one.)

---

## 0. How to use this

```bash
git fetch origin
git log --oneline <your-last-read>..origin/integration/world-builder-lifecycle-v1
```

Then read §1 (what changed), work §3 (REQUIRED NOW), and check §5 before
building anything speculative — it lists claims the Tower has **measured
and refused**, which no iOS work should anticipate.

Each entry below carries: context, the Tower decision and its evidence,
required iOS behaviour, likely Swift components, steps, contract detail,
tests, expected runtime behaviour, failure signatures, and acceptance
criteria. You should not need git history or prior chat to execute.

---

## 1. What changed on the Tower this run, and whether iOS cares

| Tower change | iOS consequence |
|---|---|
| **Object Memory got its first HTTP route** (5th router) | **NEW WORK — §3.2.** Two endpoints, new contract |
| **Object Memory iOS surface written** (5 files, uncompiled) | **REQUIRED NOW — §3.1.** Compile, test, run |
| **`in_front_of`/`behind` measured and refused** | **DO NOT BUILD — §5.1.** Was already unimplemented; now it is a measured refusal, not a pending feature |
| **Scene Understanding tracker constants re-derived** | **None today.** It has no wire path (§5.3) |
| **Scene Understanding orientation cadence 2.0 s → 0.2505 s** | **None today**, same reason. Matters when transport lands — §6.4 |
| **Document Memory glyph gate re-derived (FP 6 → 0)** | **None.** No wire contract exists for it |
| **Build settings read directly** | **Resolves two open iOS questions — §4** |
| **Your capture-clock measurement, corroborated Tower-side** | **NEW FOLLOW-UP — §6.5.** Tower confirms ~24 fps capture vs ~12 fps delivery from `source_seq` stepping by 2 |
| **One certain Swift compile error fixed** | Already applied; see §4.1 |
| `timm` installed, tracker/gate work, corpus measurement | None |

---

## 2. The Tower surface iOS talks to

Five routers registered in `tower/tower/main.py`:

| Method | Path | Contract |
|---|---|---|
| GET | `/health` | — |
| GET | `/cartridges` | — |
| GET | `/worlds/{world_id}/geometry/manifest?session_id=` | `world_builder.geometry/2026-08-25` |
| GET | `/worlds/{world_id}/geometry/segment/{segment_index}?session_id=`&`max_points=` | `world_builder.geometry/2026-08-25` |
| GET | `/object-memory/observations?object_class=&retention_days=` | `object_memory.observations/2026-08-26` |
| GET | `/object-memory/last-seen/{object_class}?retention_days=` | `object_memory.observations/2026-08-26` |
| WS | `/ws` | `cartridge_results.envelope/2026-08-23`, `world_builder.status/2026-08-25` |

Contract identifiers are **opaque and compared for equality only** —
never parsed, never ordered, never range-checked.

---

## 3. REQUIRED NOW

### 3.1 Compile and test everything. This is the whole gate.

**Context.** Over 4,383 lines of Swift across 18+ files, plus Object
Memory's 5 new files, have never been compiled. This is the largest
unverified surface in the program and it gates every user-visible claim.

**Steps.**
1. `xcodebuild build` — app target, then test target.
2. `xcodebuild test`. 66 World Builder tests + the Object Memory suite,
   none ever executed.
3. Fix compile errors. **You may fix mechanical errors freely.** If a fix
   requires changing behaviour or a contract, stop and document it —
   §4 lists what has already been ruled out so you do not re-derive it.

**Failure signatures to expect first.** §4 retires the two that were most
suspected. What remains genuinely unknown is everything a static reader
cannot check: generic inference, SwiftUI body type-checking timeouts,
protocol conformance, and any API whose signature differs from
assumption.

**Acceptance.** `xcodebuild build` clean; `xcodebuild test` green; the
count of executed tests reported (a suite that "passes" with 0 executed
is the failure mode that already bit this repo once — `WorldGeometryTests`
was absent from the target and passed by not existing).

---

### 3.2 Object Memory — verify the screen against the live route

**Context.** The cartridge went from a data layer with no producer to a
producer (55 real observations from 9,199 real frames), an enforced
retention promise, and an HTTP read surface. The iOS surface consuming it
is written and uncompiled.

**Tower decision and evidence.** This cartridge **does not know where
anything is**. `spatial_ref` is `null`, always — reserved, never
populated, actively nulled on read. "Where" is a *frame reference*
(session, frame_seq, camera): a pointer back into a recording, not a
place. A record means a **category** was visible **once** — not that it is
still there, and not that it is *yours*.

**Contract detail — `GET /object-memory/last-seen/{object_class}`.**

```json
{"contract":"object_memory.observations/2026-08-26",
 "claim":"category-was-visible-once",
 "identity":"category-not-instance",
 "absence_means":"not-observed-by-this-cartridge",
 "spatial_ref":null,
 "recorded_classes":["laptop","cell phone"],
 "retention":{"requested_days":null,"effective_days":30.0,"clamped":false,
              "policy":"min(persisted, requested): a reader may narrow this window and can never widen it"},
 "object_class":"laptop","recordable":true,"observed":true,
 "observation":{"confidence":"high","detector_score":0.512,"best_score":0.985,
                "observed_at":1787695274.32,"time_basis":"tower-receipt",
                "recorded_at":1787730238.16,"module_id":"object-memory",
                "retention_tag":"default","privacy_tags":["derived-only","frame-referenced"]},
 "where":{"kind":"frame-reference","spatial_ref":null,
          "session_id":"22e9d428…","frame_seq":3214,"camera":"glasses-camera",
          "bounding_box_normalized":[0.112,0.652,0.441,0.902],
          "imagery_retention":"capture-side"}}
```

`GET /object-memory/observations` returns the same envelope plus
`observation_count` and an `observations` array of the per-record shape
(each carrying its own `claim`, `identity`, and `where`).

**THE THREE BRANCHES — all return HTTP 200.** Absence is **not** a 404,
and treating it as an error is the most likely functional bug here:

| `recordable` | `observed` | `observation` | Meaning |
|---|---|---|---|
| `true` | `true` | populated | Seen, within the retention window |
| `true` | `false` | **`null`** | Recordable class, nothing in the window |
| `false` | `false` | **`null`** | **Never looked for** — not in the whitelist |

The third is semantically distinct and must read differently to a user:
its absence carries **no information at all**, whereas the second is a
real statement about what the camera captured.

**Required iOS behaviour.**
- Never say "your laptop". Indefinite article, past tense.
- Never render `where` as a location, on a map, or as a place name.
- Never imply present tense or that the object is still there.
- Absence of a record is never absence of the object.
- `spatial_ref` is `null` — carry it explicitly rather than omitting it,
  so a future consumer sees the field exists and is empty.
- `retention.clamped == true` means the request was **narrowed**; a client
  can narrow the window and can never widen it. Do not present a clamped
  window as if the request were honoured.

**Likely Swift components.** `ios/Glasses/Workspaces/ObjectMemory/`
(`ObjectMemoryModel`, `ObjectMemoryCopy`, `ObjectMemoryClient`,
`ObjectMemoryWorkspaceView`), `ObjectMemoryTests.swift`, plus the
catalog / `CartridgeWorkspace` / `CartridgeClients` / `ContentView` wiring.

**How the no-overclaim rule is enforced** (verify this survives your
fixes): the view contains **no user-facing string literal** — the only
literal is an SF Symbol name. All copy lives in `ObjectMemoryCopy`, and
the tests sweep that same source. If you add a literal to the view, you
have silently left the test's reach.

**Tests to run.** The `ObjectMemoryTests` suite. Confirm the no-overclaim
sweep asserts a **non-empty** string set before scanning — a sweep over
zero strings passes trivially.

**Run the Tower locally to exercise it:**
```bash
cd tower
TOWER_OBSERVATION_ROOT=data/object_memory ./.venv/Scripts/python.exe -m uvicorn tower.main:create_app --factory --host 0.0.0.0 --port 8000
curl "http://<tower>:8000/object-memory/last-seen/laptop"
```
The corpus holds 55 observations: 29 `laptop`, 26 `cell phone`, and
**zero `person`**.

**Acceptance.** Builds; tests green; the screen renders all three
branches correctly against the live route; no string asserts possession,
location, or present tense.

---

## 4. Settled — do not re-investigate

Each was flagged as a risk and then resolved by direct evidence. Recorded
so you do not spend a cycle on it.

**4.1 One certain compile error, FIXED.** `"points": []` inside a
`[String: Any]` literal — `Any` is not `ExpressibleByArrayLiteral`, so
the element type is unresolved. Fixed to `[[Double]]()` /
`[[String: Any]]()` in `WorldGeometryTests.swift:131,145`. The empty
literals on `main` are all in **typed** slots, which is why the construct
looked precedented and was not.

**4.2 `@MainActor` on test classes — NOT needed.** Read from
`project.pbxproj`: the app target sets
`SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`; the **test target sets
nothing**. It does not inherit the app's isolation.
**If `xcodebuild` nonetheless raises isolation errors**, the fix is one
`@MainActor` per class at `WorldGeometryTests.swift:7,155,198,330,380` —
but do not apply it pre-emptively.

**4.3 `URLProtocol` stubs' mutable `static var` — not an error here.**
It would be one under Swift 6 ("nonisolated global shared mutable
state"), but **both targets are `SWIFT_VERSION = 5.0`** and
`SWIFT_STRICT_CONCURRENCY` is not set anywhere, so checking is `minimal`.
Applies to both `StubbedGeometryProtocol` and `ObjectMemoryStubProtocol`.
Three separate sources named this the likeliest first failure; it is not.

**4.4 The geometry wire contract matches field for field**, verified
against the Tower **producer**, not just the contract doc. No nullable
wire field feeds a non-optional Swift property.

**4.5 `WorldPose.degeneracy` mapping `null → ""` is benign.**
`records.py:557` types it `degeneracy: str = DEGENERACY_NONE` and
`schema.py:67` sets `DEGENERACY_NONE = ""`. Tower never emits `null`, and
the sentinel for "none" *is* the empty string. `dominant_degeneracy` is
separately and correctly optional on both sides.

---

## 5. Refusals — measured. Do not build UI anticipating these.

**5.1 `in_front_of` / `behind` will not be emitted.**

*Old reason (withdrawn):* MiDaS flickers 6–8%, so ordering would invert.
That figure came from EPIC-KITCHENS at 128×256.

*What was actually measured*, on 9,199 real frames, 2,700 object-pair
observations across 13 captures:
- Per-object depth flicker is **4.8%** — the old figure was about right
  **in magnitude**, and the inference from it was still wrong. Flicker
  only breaks an ordering when it exceeds the **separation**, and both
  objects' depths move together.
- Flip rate is **3.8%** overall and **strongly predicted by separation**:
  15.7% below 0.02 separation, **0.0% above 0.40** (n=331). So the
  ordering genuinely carries information, unlike the parallax route that
  was rejected for being *flat* against separation.
- **Motion is what kills it.** At *matched* separation 0.10–0.20, the same
  pairs go **0.0% (n=124) → 11.5% (n=52)** from the most static frames to
  the top motion decile. A 0.05 separation gate goes **0.00% (n=507) →
  4.85% (n=206)**.
- The corpus's median inter-frame box motion is **4.2 px of a 734.8 px
  diagonal**, p99 56 px: **it contains no walking.** The regime this
  relation would actually be used in is unsampled, and the trend across
  the bins that exist points the wrong way.

*Cost was never the obstacle* — depth is 5.73 ms on CUDA, 18.29 ms on
CPU, against an 83.4 ms delivered frame interval.

**Revisit only when** footage containing an actual walking wearer exists.
Until then this is a measured refusal, not a backlog item.
Detail: `tower/docs/superpowers/research/2026-08-26-depth-ordering-on-real-frames.md`.

**5.2 Metric scale is unreachable** on monocular hardware by any V1
route. World Builder geometry is relative. Never present a distance in
metres.

**5.3 Scene Understanding has no wire path at all**, and its status
wording elsewhere blames persistence, which points at the wrong fix. The
real chain: it has **no store by design** (enforced against 17 write
primitives — its strongest privacy property), so it cannot use the
journal-follower pattern that gave Object Memory a route. It must deliver
live, which needs the in-process module route, which is blocked on a
**pending human ruling** about the lifecycle execution model. **Build no
Scene Understanding UI until that lands.**

---

## 6. FOLLOW-UP (real, not required for a first green build)

Triaged in full at
`tower/docs/superpowers/plans/2026-08-25-geometry-transport-followups.md`
items 7–21. The ones worth doing:

**6.1 Fetching every segment, including the empty ones.** *(Efficiency —
the clearest win on the list.)* `WorldBuilderClient` fetches every segment
the manifest names. On the real world that is **51 round trips where 19
are usable**; ~32 resolved to nothing and are never drawn.
*Acceptance:* fetch only segments the manifest marks as carrying
geometry; segment count fetched ≤ resolved count. *Measure the product
outcome* — latency and battery on a live walk — not just the request count.

**6.2 A blank tile beside a "N points" label.** *(Correctness of
appearance.)* A chunk that has not arrived renders an empty tile next to
a populated count, so the label and the tile disagree. **More visible
now** that behind-the-journal geometry is served *during* a walk rather
than after Stop. *Acceptance:* a not-yet-arrived chunk reads as loading,
never as an empty world.

**6.3 Error fidelity.** Non-404 statuses (a 500, or a 422 from a missing
`session_id`) decode their `{"detail": …}` body and then surface as
`.undecodable`; a `JSONSerialization` throw is labelled `.transport`; a
`CancellationError` is swallowed into `.transport`. Diagnostics quality
only — but on a live walk these are the messages you will be reading.

**6.4 Orientation, when transport lands.** Cadence is now
`ORIENTATION_INTERVAL_S = 0.2505 s` (stride 3 × the measured 83.5 ms
interval, where stride 3 = `TrackerPolicy.min_hits`). It costs **43.4 ms
on CUDA and 956.4 ms on CPU, and CPU is the default device** — 29.1× the
detector. Every estimate carries its age and iOS must respect that age
rather than treating an estimate as current.

---

**6.5 Transport DAT's capture timestamp — a contract addition, both halves
together.** *(FOLLOW-UP. Originated in your lane; the Tower consequences are
worked out in `tower/docs/superpowers/research/2026-08-26-two-clocks-capture-vs-receipt.md`.)*

**Context.** Your `f77b623` established that DAT's frame timestamps are a
**capture clock**, not a receipt time — and the jitter argument is what makes
it stick (`residual_sd/d_host_sd = 1.003`, `d_pts_sd/d_host_sd = 0.141`; a
1/24 s grid against arrivals scattering from 2.5 ms bursts to 120 ms stalls).

**The Tower-side shadow, which corroborates it independently.** Tower's
journal carries **no capture timestamp at all** — only `received_at` with
`time_basis: "tower-receipt"`. And Tower's `source_seq` steps by **2**
(48 of 74 sampled) against a measured **83.5 ms** delivered interval. Set
beside your 1/24 s grid: **the camera captures ~24 fps and Tower is
delivered ~12 fps.** Roughly every other captured frame never arrives. Two
lanes, two methods, same conclusion — and it explains a step-by-2 quirk the
depth study had recorded as an unexplained trap.

**Required behaviour.** Send DAT's capture timestamp alongside each frame,
as an **optional, additive** field. Tower will persist it beside
`received_at` and distinguish the two via `time_basis`.

**Contract rules (binding).** `null` when unavailable — **never zero, and
never silently substituted with a phone-side arrival stamp**, which would
destroy the only property that makes this worth doing. The unit and epoch
must be stated explicitly on the wire, since DAT's epoch is a
mach-timescale value, not Unix time.

**What it buys, as decisions it changes:** Object Memory could report when
the shutter fired instead of when the Tower received the frame — strictly
more truthful for the question that cartridge exists to answer, and it would
let its UI drop the receipt-time caveat. Tower could also distinguish "the
camera slowed" from "the network stalled", which are currently identical in
`received_at`.

**Blocking prerequisite, and it is yours to settle.** Your own commit
records that **whether the epoch survives a reconnect is untested** — a
two-minute test. This matters more to Tower than to iOS: World Builder's
capture lineage chains across a mid-walk reconnect, and splicing two
different epochs into one timeline would be worse than having no capture
clock. **Until that test exists, a transported capture clock is valid only
within a single uninterrupted connection**, and Tower will treat it that way.

**Acceptance.** The field arrives as `null` when DAT gives nothing; a real
capture stamp round-trips with its epoch intact; the reconnect behaviour is
either proven or explicitly documented as unproven at the boundary.

**Do not start this before §3.1 is green.** A first clean build matters more.

---

## 7. Document map

| Document | Status |
|---|---|
| **This file** | **CURRENT — the entry point** |
| `docs/contracts/WORLD-BUILDER-GEOMETRY.md` | **CURRENT** — geometry wire truth |
| `docs/contracts/OBJECT-MEMORY.md` | **CURRENT** — observations wire truth |
| `docs/contracts/WORLD-BUILDER-IOS.md` | **CURRENT** — the reconciled seam |
| `docs/agent-handoffs/WORLD-BUILDER-MAC-HANDOFF.md` | **REFERENCE** — deep detail on the geometry viewer; its §7–9 compile notes are superseded by §4 here |
| `docs/agent-handoffs/OBJECT-MEMORY-MAC-HANDOFF.md` | **REFERENCE** — deep detail on the Object Memory screen |
| `docs/agent-handoffs/IOS-STATIC-REVIEW.md` | **REFERENCE** — the findings §4 summarises |
| `docs/agent-handoffs/WORLD-BUILDER-STATUS.md` | **CURRENT** for P1–P11 physical gates |
| `docs/agent-handoffs/CARTRIDGE-ROADMAP.md` | **CURRENT** — program-level blockers |
| `tower/docs/contracts/IOS-TO-TOWER-RECONCILIATION.md` | **REFERENCE** — requirement-by-requirement classification |
| `tower/docs/agent-handoffs/IOS-WORLD-BUILDER-INTEGRATION.md` | **SUPERSEDED** by this file and the contracts above |
| `tower/docs/agent-handoffs/TOWER-TO-IOS.md` | **PARTLY SUPERSEDED** — predates the result channel; its own header says which sections were updated |
| `docs/agent-handoffs/WORLD-BUILDER-INTEGRATION.md` | **REFERENCE**, and note it describes branch `ios/world-builder-integration` |

---

## 8. Physical validation — P1–P11

Enumerated in `WORLD-BUILDER-STATUS.md` §2. **Nothing below has happened.**
The three that matter most, in value order:

- **P11 — the highest-leverage experiment available.** A walk where the
  wearer **sidesteps rather than pans**. 16 of 19 segments are refused
  because the wearer stood still, so scale is unobservable. This **tests a
  prediction** rather than gathering data.
- **P3** — do fragments appear *during* a walk. The entire product claim.
- **P9/P10** — a loop closure, so registration composition finally has an
  independent check. **Nothing automated can catch a wrong Sim3:** pair
  (30,50) fits at 1.62 px with 88% of points under 3 px while being
  **3.2× wrong on scale**.

**P7 is unanswerable with the current corpus** — its "people" are the
wearer's own torso (median box bottom edge 0.981, 59% touching the frame
edge). Redaction on real bystanders cannot be validated here at all.

---

## 9. Changelog

**2026-08-26 (b)** — Added §6.5: the capture-clock contract addition, after
the iOS lane's `f77b623` was corroborated Tower-side. Records that "the frame
rate" is now ambiguous — capture ~24 fps and regular, delivery ~12 fps and
bursty — and that every existing Tower constant correctly uses the delivery
rate, so nothing measured so far is invalidated.

**2026-08-26** — First edition. Covers: Object Memory route + iOS surface,
the measured `in_front_of`/`behind` refusal, build-settings findings
retiring two suspected compile risks, one fixed compile error, and the
Scene Understanding wire-path chain.
