# Mac/iOS integration — canonical status

**This is the Mac lane's entry point.** It supersedes the Mac-facing status
sections of `MAC-BUILD-VERIFICATION.md` (which remains accurate as the record
of the first compile) and corrects `CARTRIDGE-ROADMAP.md`, whose headline
blocker was resolved two hours after it was written.

**Lane:** Mac/iOS. **Branch:** `ios/world-builder-integration`.
**Upstream consumed:** `integration/world-builder-lifecycle-v1` @ `25eb794`,
fully merged — `git merge-base --is-ancestor` confirms nothing is outstanding.
**World Builder specialist branch:** `world-builder/next-generation`
**does not exist on `origin`.** Nothing to consume; nothing is blocked on it.
**Toolchain:** Xcode 26.6, Swift 6.3.3, iOS SDK 26.5. Simulator iPhone 17 Pro,
physical iPhone 16 Pro (`iPhone17,1`).

---

## 1. Build and test — re-verified on this Mac, not inherited

Every row below was produced from a clean `derivedDataPath` in this session.

| Gate | Result |
|---|---|
| Debug (Simulator) | **0 errors, 0 warnings** |
| Release (Simulator) | **0 errors, 0 warnings** |
| Signed device build | **0 errors, 0 warnings** — `Apple Development: tv.lloyd@icloud.com` |
| XCTest | **392 passed, 0 failed** (was 388; four added this wave) |
| Install on physical iPhone 16 Pro | **done** — `com.tristanvarner.Glasses` |

**The `warning:` lines from `appintentsmetadataprocessor` are not compiler
warnings.** They are a tool notice that the target declares no
`AppIntents.framework` dependency. Grepping build logs for `warning:` without
anchoring on ` warning:` will pick them up and report a clean build as dirty.

### 1.1 What "Release builds clean" does and does not mean

**It means less than it looks.** `GlassesConnection.swift` puts the entire
camera path inside `#if DEBUG` — lines 12–17, 26–37, 46–139 and **398–832**,
over half the file — and `ProjectManager.swift:118-174` likewise. There is no
`#else`. The file says so itself: *"Camera session (proof-of-path milestone;
DEBUG-only for now)"*.

So a Release build contains no `CapturedFrame`, no camera session, no
`startCameraSession`/`beginCameraStream`, and **sends no frames to the Tower**.
Verified against the binaries rather than the source: `nm` finds `FrameRateGate`
in the Release binary and finds none of the camera-session symbols.

This is a deliberate staging decision, not a defect. It is recorded here
because "Release builds, 0 errors" is being used as a readiness signal, and
Release currently compiles cleanly *partly because it excludes half the app*.
**Do not treat the Release gate as evidence of product function until the
camera path leaves `#if DEBUG`.**

---

## 2. Live Tower evidence

The Tower at `100.110.156.55:8000` was **running during this session** and was
probed directly. This is wire truth, not a reading of Tower source.

```
/health    module_state: "active"   module_id: "experimental-cv"
           capture: armed=true, recording=false, frames_written=256
/cartridges
   offers:      world_builder / status / world_builder.status/2026-08-25
                available=true, snapshot_only=true
   envelope:    cartridge_results.envelope/2026-08-23
   not_offered: experimental_cv, document_memory, scene_understanding
/object-memory/*        404 {"detail":"no object memory root is configured"}
/worlds/{id}/geometry/manifest (no session_id)   422
```

Only six HTTP routes exist: `/health`, `/cartridges`,
`/object-memory/{observations,last-seen}`, and the two geometry routes.

**`ios/scripts/contract-drift-check.py`** was added this wave and automates
this comparison. It reads the contract identifiers out of the Swift source and
asks a live Tower what it serves. Every fixture in `GlassesTests` was captured
by hand and nothing re-checked them; this is that check.

---

## 3. Cartridge matrix

Status vocabulary is kept separate on purpose. **IMPLEMENTED** ≠ **TESTED** ≠
**DEVICE-VALIDATED** ≠ **PHYSICALLY VALIDATED**.

| Cartridge | iOS surface | Compiles | XCTest | Tower wire | State |
|---|---|---|---|---|---|
| **World Builder** | full (canvas, fragments, geometry) | yes | yes, incl. real-Tower fixtures | `world_builder.status/2026-08-25` offered + geometry over HTTP | **TESTED**; transport proven live. **PHYSICAL VALIDATION PENDING** — P3 needs a walk |
| **Object Memory** | full, live HTTP client | yes | yes, incl. real-Tower fixtures | HTTP only, **not in `/cartridges` at all** | **TESTED**. Live Tower currently returns 404 (no root configured); iOS renders that as its own state, correctly and by test |
| **Experimental CV Lab** | workspace + stub client | yes | model-level only, **no decode tests** | `not_offered`; results arrive on `frame_result` | **IMPLEMENTED**, and see §4.1 — its results were being dropped |
| **Scene Understanding** | workspace + stub client | yes | model-level only | `not_offered`, and **no Tower route exists** (test-enforced) | **IMPLEMENTED** placeholder. Blocked on the Tower lifecycle ruling |
| **Document Memory** | workspace + stub client | yes | 37 cases, model-level | `not_offered`; Tower engine is CLI-only | **IMPLEMENTED** placeholder. See §5 |
| **Visual Q&A** | catalog row only | — | — | no Tower code at all | NOT IMPLEMENTED, correctly |
| **Accessibility** | catalog row only | — | — | no Tower code at all | NOT IMPLEMENTED, correctly |
| **Environmental Memory** | catalog row only | — | — | no Tower code at all | NOT IMPLEMENTED; its own design says do not begin |
| **Translator** | **no catalog row** | — | — | no Tower code at all | NOT IMPLEMENTED. See §6 |

Nine cartridges in the docs, eight rows in the iOS catalog, four ids in Tower's
`contracts.py`, one offered on the wire. All four counts are correct for what
they describe; they are not the same list.

---

## 4. Defects found and fixed this wave

All four are covered by tests that were **proven to fail without the fix** —
each guard was neutralised and the suite re-run before being restored.

### 4.1 The Tower's per-frame result was being decoded at half its width

`tower/tower/routes/ws.py:148-155` sends **five keys unconditionally** —
`seq`, `processing_ms`, `result_value`, `result_label`, `stage_ms` — plus
`mean_intensity` and `metrics` when present. `TowerFrameResult` modelled three
and dropped the rest, and its doc comment asserted that three *was* the whole
vocabulary and that the Tower "has no module runtime". Both halves were false;
the live `/health` above says `module_state: active`.

`result_label` and `result_value` are the running experiment's own answer.
They were arriving on every frame and being discarded — while the Experimental
CV Lab workspace told the wearer the Tower *"cannot run experiments yet"* and
that *"the module container it would run inside does not exist."*

Fixed: the struct carries the full vocabulary, the decoder reads it, and the
workspace copy now describes the real limitation (one experiment, chosen at
Tower startup, with no way to list or request another).

### 4.2 A frame result outlived the socket that carried it

`teardownConnection` clears everything else scoped to one connection — the send
window, `lastSendFrameAt`, `isStreamingToTower`, of which it says leaving it set
"would be a lie". It did not clear `latestFrameResult`, which
`HomeWorkspaceView` renders under the caption **"latest Tower reply"**. A socket
dropping mid-capture left the dead connection's reading on screen for the whole
outage, and permanently once the reconnect budget was spent. Now cleared.

### 4.3 A partial result would have silently blanked the world

The envelope's `snapshot` field exists so a future delta mode cannot be mistaken
for a complete state. It was decoded and never read. The failure mode without a
guard is not a missing error — it is a **wrong answer that looks right**: a
payload with `model_state: "receiving"` and no `world_snapshot` decodes cleanly
to `.awaitingFirstUpdate`, collapsing a populated world into a spinner with no
error and no log. The characterisation test drives exactly that shape after a
17-keyframe world is on screen; without the guard it reports
`expected a refusal, got awaitingFirstUpdate`.

### 4.4 Two prose claims the live Tower contradicts

The drawer footer said *"the Tower has no module runtime yet"* and the home
screen said *"no module runs there yet"*. Both false against a Tower reporting
`module_state: active`. Corrected to describe the real constraint — the Tower
chooses what it runs at startup and this app cannot ask it for anything else.

---

## 5. Reviewed and deliberately NOT changed

Recorded so the next lane does not re-litigate them. Each was proposed, argued
against by an independent adversarial reviewer, and refused on evidence.

- **`seq` gap detection.** Refused. `tower/tower/results/envelope.py:56-63`
  states it directly: *"because every result is a complete snapshot, a client
  never needs to detect a gap to know whether it missed information — it did
  not."* Tower increments `seq` only after a successful send, so it cannot skip
  one; WebSocket over TCP cannot manufacture a gap. A correct detector would
  need five reset points (per-connection identity, every ack, unsubscribe,
  `consumer_too_slow`, `channel_failed`) and a naive one false-alarms on every
  reconnect, where `subscription_id` restarts at `sub-1`. A debug log line is
  the most this justifies.
- **`envelope_contract` equality gating.** Deferred, not refused outright. It
  has no defined user state, no repo precedent at the transport layer, and the
  largest possible blast radius — one string comparison would fail every
  cartridge at once. The case that *does* have a defined state, a cartridge
  contract this build does not implement, is already enforced. Note also that
  the field is **absent** from three Tower→client messages today, so any
  "absent ⇒ mismatch" rule would fire against a conforming Tower.
- **`not_offered` decoding.** Correctly not decoded. The contract states
  presence there must never be read as an offer, and a test pins it.
- **Raising `FrameRateGate.towerTargetFPS`** from 12. Untouched. Requires a
  device measurement and coordination with the World Builder lane.

---

## 6. Backend follow-up required (Windows lanes)

Found from the Mac side, verified in Tower source, **not fixed here** —
`tower/` was not modified.

1. **`tower/docs/contracts/CARTRIDGE-RESULTS.md:326`** — *"Every `result_error`
   also carries `envelope_contract`"* is false. `publisher.py:356-362`
   (`channel_failed`), `publisher.py:397-407` (`consumer_too_slow`) and
   `results_ws.py:258-260` (`result_unsubscribed`) all omit it. This matters
   because it is exactly the sentence a client would lean on when implementing
   an envelope-version gate.
2. **Same document, `:355-356`** — the bounds table gives send timeout and lock
   wait as **2 s** each. `publisher.py:74,79` set both to **1.0**.
3. **Object Memory is absent from `/cartridges` entirely**, not even under
   `not_offered`. It is the one cartridge whose Tower half actually answers, and
   the capability declaration a phone caches does not mention it. iOS works
   around this with a probe-on-ask model; that asymmetry should be a decision
   rather than an accident.

---

## 7. Physical validation

**DONE, and this session moved the line.** App built, signed, installed and
launched on the physical iPhone 16 Pro against the live Tower. Clean run, no
crash. Full console, in order:

```
[Glasses][Init] GlassesConnection created                    <- exactly one
[Glasses][Tower] connection attempt: ws://100.110.156.55:8000/ws
[Glasses][Registration] state changed: RegistrationState(rawValue: 3)
[Glasses][Devices] devicesStream changed: count=0 ids=[]
[Glasses][CameraPermission] check failed: No wearable devices ... discovered
[Glasses][Devices] devicesStream changed: count=1 ids=["5161af8f...ec"]
[Glasses][Tower] ping sent / pong validated                  <- pong still first
[Glasses][Tower] receive loop started
[Glasses][Tower] cartridges sent                             <- after the pong
[Glasses][Tower] cartridges declared: world_builder/status available=true
[Glasses][Tower] result_subscribe(world_builder) sent
[Glasses][Tower] result_subscribed: sub-1 world_builder/status
[Glasses][Tower] cartridge_result: ... seq=1 revision=a124493a48ee4b29 coalesced=0
[Glasses][WorldBuilder] finalized keyframes=2 tracking=Good scale=Relative
                        calibration=Calibrated geometry=95 poses=2 anchors=1
                        segments=1 binding=none
[Glasses][Camera] activeDeviceStream changed: Optional("5161af8f...ec")
                        (hasActiveDevice=true)
[Glasses][CameraPermission] checkPermissionStatus -> granted
```

**Two things here are new, and both matter.**

- **The glasses are powered on and the camera is authorised.** Every earlier
  handoff recorded them as "discovered, powered off"; the state machine ran all
  the way through `count=0` → `count=1` → `hasActiveDevice=true` →
  `PermissionStatus.granted`. The console also shows iOS attaching
  `Ray-Ban Meta (Gen 2) - 37418056` as an ExternalAccessory before DAT reports
  the device, so the two layers agree.
- **The phone received a real world, not `idle`.** `finalized`, 2 keyframes,
  tracking Good, **calibration Calibrated**, 95 geometry elements. The status
  path end-to-end — declare, subscribe, decode, render — ran on hardware
  against a Tower serving real data.

The Tower is armed and not recording (`capture.armed: true,
recording: false`), so nothing is mid-session and a walk can start clean.

**This is the closest the program has been to P3.** Everything upstream of a
wearer is now confirmed working on the actual device.

**PENDING, and every one needs a wearer:**

| | What it needs |
|---|---|
| **P3 — do fragments appear during a walk** | glasses powered on, then a walk. The entire product claim |
| **P11 — the sidestep experiment** | walk *laterally* rather than panning. Highest-leverage: it tests a prediction |
| P9/P10 — loop closure | a walk that returns to its start |
| Sender FPS against the physical baseline | a live stream, to measure encode/backlog headroom |
| Frames from the real camera reaching the Tower | glasses powered on |

**The single next physical action is no longer "power on the glasses" — they
are on.** It is: open the app, press Start, and walk. See §9.

---

## 8. Known gaps, ranked, not yet addressed

1. **Subscribe ack has no timeout.** `subscribeIfPossible` sets
   `.awaitingFirstUpdate` before sending, and `sendResultMessage` deliberately
   does not escalate a failed send. A subscribe that never lands on a socket
   that stays up leaves a spinner forever. `CartridgeFailure.Kind.timedOut`
   exists for exactly this and is never constructed.
2. **`noContract` and `unsupportedContract` render identically** — same
   headline, same glyph — while calling for opposite user actions ("wait for
   the Tower" vs "update the app").
3. **Three retain cycles defeat `GlassesConnection.isolated deinit`**
   (`:190, :210, :220`): `Task { [weak self] in guard let self else … }` over an
   unbounded DAT stream promotes the capture to strong. The correct pattern is
   in the same file at `:807-822`. Blast radius is currently limited — multiple
   scenes are not enabled — but it is unmitigated.
4. **`towerCartridgeNames` has one row.** If Tower promotes `experimental_cv`,
   `document_memory` or `scene_understanding` out of `not_offered`, iOS cannot
   see it — silently, with no test failing.
5. **`cartridgeDeclaration` is not invalidated on endpoint change**, so a
   retarget can race a stale contract into the first subscribe.
6. **The iOS docs tree is a stale fork.**
   `ios/Glasses/Project_Overview_Steps/docs/modules/` is missing
   `TRANSLATOR.md` and its status lines predate every blocker finding. It is the
   mechanical cause of the 8-vs-9 cartridge discrepancy, because
   `Cartridge.swift` cites paths that resolve into it.

---

## 9. Exact next actions for a successor Mac lane

1. Run `ios/scripts/contract-drift-check.py` first. It answers in seconds
   whether the Tower has moved under this build.
2. Fix §8.1 (subscribe-ack timeout) — it has a user-visible symptom, an unused
   failure kind built for it, and a bounded fix.
3. Fix §8.2 (availability states rendering identically).
4. When a wearer is available, run P11 before P3: it tests a prediction rather
   than gathering data.
5. Do not re-open §5. Those were argued and refused on evidence.
