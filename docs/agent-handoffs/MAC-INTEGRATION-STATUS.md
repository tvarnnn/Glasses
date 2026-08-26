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
| XCTest | **396 passed, 0 failed** (was 388 at the start of this lane's session) |
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

## 4.5 Second wave — the walk's findings

### 4.5.1 The subscribe wait was unbounded

`subscribeIfPossible` shows a spinner *before* sending, and
`sendResultMessage` deliberately swallows a send failure so the result channel
can never take down the frame path. Both are right alone. Together they left a
`result_subscribe` that never reached the wire, on a socket that then stayed
up, waiting with nothing to end it. `CartridgeFailure.Kind.timedOut` existed
for exactly this — Rule 15 — and was never constructed anywhere in the app.
Now bounded at 10 s, disarmed on the ack, on an inbound error, and on the
connection going away, with an attempt counter so a stale bound cannot fire
into a later attempt.

### 4.5.2 `noContract` and `unsupportedContract` rendered identically

Same headline ("Nothing yet"), same glyph, **opposite remedies**: one is "this
Tower may never do this" and there is nothing to be done; the other is "the
Tower already does this and the app is behind", which a person fixes in a
minute. A new `CartridgePhase.needsUpdate` now carries it — "Update needed",
`arrow.down.circle`. This is the same argument the codebase already made once
when it split `.disconnected` out of `.unsupported`, applied one level up. The
suite's own tripwire — *"a phase was added without a decision here"* — caught
the addition and was answered rather than silenced.

### 4.5.3 A connect that never completes never ended — and `withTimeout` could not fix it

The handshake's `receive` was bounded at 6 s; the `send` beside it, which
cannot return until TCP connect and the HTTP Upgrade are done, had **no
deadline at all**. A peer that accepts TCP and never upgrades parked the client
in `.connecting` permanently: `fail(_:task:)` was never reached, the reconnect
schedule never advanced, the attempt budget was never spent, and nothing said
so.

**The first fix did not work, and finding that out is the valuable part.**
Wrapping the `send` in the existing `withTimeout` helper is useless here: a
throwing task group must await its remaining child before it can propagate the
sleeper's error, and that child is the stuck call. Measured, not reasoned —
against a listener that accepts TCP and never upgrades, a one-second
`withTimeout` left the client `.connecting` for the full twelve seconds the
test would wait.

The bound therefore had to act on the socket, which *is* cancellable, rather
than on the await. A watchdog now tears the connection down if a whole attempt
has not resolved. **The same caveat applies to the pong's existing 6 s
`withTimeout`** — it bounds the ordinary case, it is not a guarantee — and that
is now written where the next reader will find it.

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
- **Raising `sendStallTimeout` from 2.0 s** after it cost ~9 s of a walk.
  Investigated and **refused**, which was not the expected outcome. It would
  not have saved that walk: the replacement connection needed ~8.5 s to
  handshake, so any threshold below that fires anyway and merely lengthens the
  hole. The mechanism it protects is severe — there is no API to time out an
  individual `send`, `didCloseWith` fires only on a real close frame, and send
  completions have been observed succeeding for ~40 s after a disconnect, so
  the stall detector is the *only* observer of a dead socket. `SendWindow`
  capacity 4 is measured (and since confirmed at 11.97 fps over 9,199 frames),
  not a guess. The repo pre-registered the condition for raising the threshold
  — "stall recoveries climbing continuously" — and n=1 does not meet it. It is
  also a published cross-lane invariant. **Instrumented instead**: each
  handshake leg is timed separately and every stall verdict now prints the
  slot-lifetime max, send-latency max and prior recovery count, so the next
  walk distinguishes the three competing hypotheses instead of guessing.

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

### 7.1 The walk happened — P3 result: PARTIAL, and P11 still not performed

A full walk was performed and the Tower finalized session
`8ad340d01e0d477599d701bbcaf9ed29` / world `3d49a7711f6f4329a00c23dd395c95e8`:
520 frames observed, 141 keyframes, 14 segments, 30 solved poses, 97 refused,
3,732 points, `classical-sfm`, `scale_state=unknown`. **The room was not
coherently reconstructed.** Phone-side evidence: 482 console lines captured.

**What the iOS half got right, on hardware, for the first time:**

- The **whole lifecycle** ran: `awaitingFirstUpdate` → `FOREIGN(be4c8ead…)` →
  `bound(8e1875ed…)` → 83 `receiving` updates → `binding=none` → `finalized`.
- **The foreign-capture gate fired correctly.** At launch the Tower had another
  capture open and the phone reported `FOREIGN` rather than claiming it.
- **A mid-capture reconnect was survived.** The socket dropped, the client
  re-handshook, re-subscribed, re-sent `stream_start`, and re-bound to the same
  session — all logged, all truthful.
- **Nothing was overstated.** `scale=Unknown` was never dressed up as relative
  across the entire run, and the phone's counts matched the Tower's final
  summary exactly on keyframes, segments and points.

**Two findings came out of it, both recorded in
`WORLD-BUILDER-WALK-EVIDENCE-2026-08-26.md` for the World Builder lane:**

1. **The Tower lost ~9 seconds of the walk and cannot see that it did.** A send
   stall (4 slots outstanding for 2.0 s) replaced the connection; DAT ordinals
   #747–#963 (216 frames ≈ 9.0 s at 24.04 fps) never reached the Tower while
   the camera kept delivering. Reconstruction yield collapsed **~14×** across
   that boundary — 48.5 points/keyframe before, 3.5 after — and never
   recovered. Stated to that lane as a hypothesis with a mechanism, not a
   cause; it cannot rule out the wearer entering a lower-texture area.
2. **`trajectory.pose_count` reads 37 where the Tower solved 30**, with
   keyframes, segments and points matching to the digit. That is the one field
   with a history of meaning two things — it is why the `2026-08-25` contract
   exists. Reported, not "fixed": the phone renders what the payload says, and
   which number is right is the Tower lane's to confirm.

**P3 — "do fragments appear during a walk" — came back UNANSWERABLE, and that
was our fault.** The geometry pull had **no logging whatsoever**. 482 lines
across seven subsystems and not one said whether the manifest was ever fetched.
The status channel logs what the Tower *said*; nothing logged what the phone
then went and *got*. Fixed this session: `[Glasses][Geometry]` now reports, per
manifest, the segment count, how many carry points, fetched vs cached chunks,
and total points drawn — plus explicit lines for a failed manifest and for a
pose-convention refusal. **A walk is expensive to repeat and this one could not
answer the question it was run for.**

**PENDING, and every one needs a wearer:**

| | What it needs |
|---|---|
| **P3 — do fragments appear during a walk** | **re-run.** The walk happened; the phone could not report the answer. Now instrumented — see §7.1 |
| **P11 — the sidestep experiment** | walk *laterally* rather than panning. Highest-leverage: it tests a prediction |
| P9/P10 — loop closure | a walk that returns to its start |
| Sender FPS against the physical baseline | a live stream, to measure encode/backlog headroom |
| Frames from the real camera reaching the Tower | glasses powered on |

**The single next physical action is no longer "power on the glasses" — they
are on.** It is: open the app, press Start, and walk. See §9.

---

## 8. Known gaps, ranked, not yet addressed

1. ~~Subscribe ack has no timeout.~~ **FIXED — §4.5.1.**
2. ~~`noContract` and `unsupportedContract` render identically.~~ **FIXED — §4.5.2.**
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
2. **The next walk is instrumented — read its `[Glasses][Geometry]` and
   handshake-leg lines before changing anything.** They answer P3 and they
   settle which of the three reconnect hypotheses is real. Do not tune a
   transport constant before those numbers exist.
3. Fix §8.3 (the three retain cycles) — it is the largest remaining correctness
   item that does not need a wearer.
4. When a wearer is available, run P11 before P3: it tests a prediction rather
   than gathering data.
5. Do not re-open §5. Those were argued and refused on evidence, and one of
   them — the send-stall threshold — is a published cross-lane invariant.
