# iOS → Tower send-window investigation — cross-machine handoff

**Status:** implementation complete. **Compiler- and test-validated on the Mac
(Debug + Release build clean, 89/89 tests passing). NOT yet validated on
hardware — no FPS measurement has been taken, so the actual fix is still
unproven.**

This work was produced on Windows, where there is no Xcode, no Swift compiler,
no Simulator, no iPhone and no Meta DAT hardware. Every claim written there was
either a statement about source, a piece of arithmetic, or an explicitly
labelled hypothesis. The Mac was the authoritative validation gate for
*correctness*; §11.2 records what it cleared.

**The performance claim remains a hypothesis.** §15's predicted 10–12 fps has
not been observed. The build-and-test gate says the change is safe to run, not
that it is faster. §14 is the outstanding work and §16 must not be settled
without it.

---

## 1. Mission

Find and fix the **second** iOS → Tower FPS bottleneck.

The first bottleneck (a 1-in-30 logging stride that accidentally gated
transmission, capping delivery at ~0.8 fps) was fixed in `8e80942`. After that
fix a physical run still delivered only ~3.4 fps against a 12 fps target. This
task is that remaining shortfall.

Explicitly in scope: investigate **and implement**. Explicitly out of scope:
raising the 12 fps selection target, World Builder, Object Memory, UI redesign,
cartridge architecture, Tower behaviour changes, unrelated cleanup.

**The invariant that governs every decision here: freshness beats completeness.**
No unbounded queues, no unlimited in-flight sends, no silently growing latency.
If the link cannot carry every selected frame, frames are dropped — never
queued.

---

## 2. Known-good base

| | |
|---|---|
| Base branch | `ui/product-shell` |
| Base commit | `d9e513d` "Surface the sender pipeline metrics in the product shell" |
| Feature branch | `ios/send-window-investigation` |

`d9e513d` had previously passed, on real hardware: 56/56 Xcode tests, Debug
build, Release build, physical iPhone deployment, Meta DAT hardware testing,
live Ray-Ban viewfinder, and real remote Tower streaming. **If this branch turns
out to be wrong, `d9e513d` is the known-good state to return to.**

`main` and `ui/product-shell` were not modified.

---

## 3. Physical baseline being explained

One ~5-minute physical run, Ray-Ban Meta glasses → iPhone → remote Tower over
Tailscale.

### iOS sender

| Stage | Count | Rate |
|---|---|---|
| DAT capture | 7273 | 23.9 fps |
| Selected by 12 fps gate | 3631 | 11.9 fps |
| Send attempts | 1030 | 3.4 fps |
| Successful sends | 1028 | 3.4 fps |
| Tower replies | 984 | 3.2 fps |
| **Send-window drops** | **2601** | |

Encode ~1.57 ms avg / ~2.30 ms max. Decode failures 0. Encode failures 0. Send
failures 0. Backlog 0. Sequence 1:1 yes.

### Tower

```
session_duration_s        309.623
frames_received           1030
effective_fps             3.33
source_fps_estimate       20.09
backpressure_drops        0
frame_processing_errors   0
frames_rejected           0
receive_to_result_ms_avg  229.28
receive_to_result_ms_max  52121.091     <-- 52 seconds
cv_processing_ms_avg      0.817
process_cpu_percent       ~0.99
```

### The arithmetic that localises the bottleneck

```
3631 selected − 2601 send-window drops = 1030 send attempts
Tower received exactly                   1030 frames
```

The pipeline is **exact**. Nothing is lost in transit, nothing is lost on the
Tower, nothing fails. Every missing frame was **deliberately dropped by the iOS
send window**. The bottleneck is precisely between *selected* (11.9 fps) and
*admitted* (3.4 fps), and nowhere else.

### The degradation over time (the most important clue)

At ~85 s into the same run:

| Stage | Rate at 85 s | Rate over full 309 s |
|---|---|---|
| Capture | ~24.1 fps | 23.9 fps |
| Selected | ~12.0 fps | 11.9 fps |
| Send attempts | ~7.0 fps | 3.4 fps |
| Sent | ~7.0 fps | 3.4 fps |
| Tower replies | ~6.7 fps | 3.2 fps |
| Send-window drops | 426 | 2601 |

Capture and selection held perfectly flat. **Only the send stage decayed** —
roughly halving. Deriving the back half: ~595 frames in the first 85 s, so ~435
frames across the remaining ~224 s ≈ **1.9 fps** by the end.

---

## 4. Recovery of the interrupted session

The previous session was interrupted for an authentication/billing change. Its
state was recovered before any new work began.

**Finding: the interrupted session produced no durable work.** Specifically:

- `git status`: clean. No staged, unstaged, or untracked changes.
- `git stash list`: empty.
- Reflog: `clone` → `checkout main` → `checkout -b ios/send-window-investigation`.
  The branch was created at `d9e513d` and **no commit was ever made on it**.
- No `docs/`, no plan, no notes, no instrumentation, no tests.
- Its transcript shows it invoked the systematic-debugging skill, then read
  `TowerClient`, `FrameRateGate`, `SenderMetrics`, `StreamManager`,
  `GlassesConnection`, `ProjectManager`, the roadmap, the development rules, the
  tests and `DeveloperToolsView` — and was interrupted before producing any
  analysis.
- One subagent artifact survived on disk. It is a verbatim dump of
  `GlassesConnection.swift`, not a finding.

So: nothing was discarded, because nothing existed. The branch pointer was kept
and the investigation was done fresh. **Reconnaissance only — no conclusions
from that session were inherited or relied upon.**

---

## 5. Root cause

### 5.1 PROVEN (by source reading and arithmetic)

**The bounded send window is not a memory guard. It is the pipeline's rate
limiter, and it was sized about three times too small for the measured link.**

In `TowerClient.sendFrame`, a frame is admitted only if a window slot is free. A
slot is held from `framesInFlight += 1` until the `URLSessionWebSocketTask.send`
completion handler hops back to the main actor and decrements. In steady state
that makes the achievable rate exactly:

```
admittedFPS = capacity / averageSlotLifetime
```

With the shipped `capacity = 2`, this reproduces the observed numbers exactly:

| Slot lifetime | capacity 2 | Observed |
|---|---|---|
| ~290 ms | 6.9 fps | ~7.0 fps at 85 s |
| ~590 ms | 3.4 fps | 3.4 fps over the run |

The gate selecting 11.9 fps is irrelevant when the window can only admit 6.9.
The 2601 "send-window drops" are not a symptom of a fault — they are the window
**working exactly as designed**, at a design point that was wrong. There is no
bug to fix in the mechanism; there is a sizing decision to correct and a stall
to detect.

This is why `maxFramesInFlight = 2` was defensible when written and wrong in
practice: its doc comment reasoned that "a send completing in well under one
frame interval never blocks the next frame". On a LAN that holds. On a remote
Tailscale path where a send takes 290–590 ms — 3.5 to 7 frame intervals — it
does not, and nothing in the code or the metrics said so, because **slot
lifetime was never measured**.

### 5.2 CONFIRMED by Apple's own documentation

Researched during this task (iOS 26.5 SDK header + Apple docs):

- `send`'s completion handler fires when the message has been **written to the
  kernel socket buffer** — not enqueued, and *not* acknowledged by the peer.
  Verbatim: *"invocation of the completion handler does not guarantee that the
  remote side has received all the bytes, only that they have been written to
  the kernel."* Therefore the completion **is** gated by TCP send-buffer
  pressure, and a peer that stops reading stalls it. A multi-second stall is
  documented behaviour, not a malfunction.
- The completion runs on the session's `delegateQueue`; with `delegateQueue: nil`
  URLSession creates a **serial** background queue. Never the main thread.
- **There is no way to cancel or time out an individual outstanding `send`.**
  The class surface has no such API, and `timeoutIntervalForRequest` is
  community-reported not to apply. The only lever is tearing down the task.
  *This is why stall recovery here is necessarily at connection granularity.*
- Send-**completion** ordering is **not** documented as FIFO (only `sendPing`
  ordering is guaranteed). Code must not assume it.
- One send error fails **all** outstanding work on the task and ends it.
- `didCloseWith` fires only on a real close **frame**. TCP resets, dropped links
  and NAT timeouts produce no callback at all. Multiple Apple DTS threads report
  send completions succeeding for ~40 s after a disconnect, and failures
  surfacing only after 60 s–3 min.
- Apple's TN3151 now recommends Network framework over `URLSessionWebSocketTask`
  for new WebSocket code. See §12.

### 5.3 HYPOTHESIS (not proven — this is what the next run must settle)

Why slot lifetime **doubled** from ~290 ms to ~590 ms over five minutes. Three
candidates, not mutually exclusive:

- **H1 — peer/link stalls.** Tower's `receive_to_result_ms_max` of **52 s**
  against a 0.817 ms mean CV time means the Tower's read loop stopped for 52
  seconds. During that, its TCP receive window closes, iOS's writes cannot
  complete, and both slots are held. 52 s at 12 fps is ~624 frames not sent. One
  such event plus a few smaller ones accounts for most of the decay. **This is
  the leading hypothesis** and it is corroborated by a detail in the final
  snapshot: `sendAttempts − sendSuccesses = 1030 − 1028 = 2`, exactly the full
  window — i.e. at capture time **both slots were occupied by sends that had not
  completed**. The socket was stalled at the moment the run ended.
- **H2 — thermal throttling.** The user physically felt the glasses heating. If
  the iPhone also throttled, the main actor slows, the completion's hop to the
  main actor lengthens, and slot lifetime grows — with no network change at all.
  *Evidence against it being dominant:* a main actor backed up by hundreds of
  milliseconds would make the UI visibly unresponsive, which was not reported;
  and capture held at 23.9 fps throughout.
- **H3 — genuine uplink degradation** (bufferbloat, Wi-Fi/cellular quality,
  Tailscale path change).

**These were previously indistinguishable, because nothing measured them.** That
is the single biggest gap this change closes — see §7.

### 5.4 UNKNOWN / not determined

- Which of H1/H2/H3 dominates. Requires the next physical run.
- What the Tower was doing during its 52 s stall. Tower-side; not investigated,
  and deliberately not changed.
- Actual wire bytes per frame on the physical run. `wireBytesPerSecond` is
  already recorded but was not captured in the baseline. **Capture it this
  time** — it decides whether the link is latency-bound (a bigger window helps)
  or bandwidth-bound (only a smaller payload helps).

---

## 6. Slot lifetime semantics (the precise mechanism)

A window slot is held for:

```
reserve ──► [ URLSession writes to kernel buffer ] ──► completion handler
                                                       (serial bg queue)
                                                            │
                                                            ▼
                                                  Task { @MainActor }  hop
                                                            │
                                                            ▼
                                                        release
```

Both spans are now measured separately:

- **`sendLatency`** — reserve → completion handler entry, sampled *inside* the
  completion handler before the hop. This is the transport.
- **`slotLifetime`** — reserve → slot actually returned on the main actor. This
  is the true rate denominator.
- **hop** = the difference. Large hop ⇒ main-actor congestion (H2). Large
  `sendLatency` with a small hop ⇒ network/peer (H1/H3).

**A stalled send holds its slot for the entire stall and is still transmitted
when it finally flushes.** In the baseline that means the Tower could receive a
frame ~52 seconds stale. That is the freshness violation, and it is what the
stall detector exists to bound.

---

## 7. Selected design

Four changes, each justified separately.

### 7.1 Extract `SendWindow` as a pure value type — `Glasses/SendWindow.swift`

The window was three loose fields inside `TowerClient` (`maxFramesInFlight`,
`framesInFlight`, and an implicit reset in teardown). It is now a value type with
reservation tokens, so slot lifetime, exhaustion and stall detection are unit
testable with synthetic time — no socket, no timer, no real elapsed time. Same
shape as `FrameRateGate`, which the codebase already tests this way.

Tokens are **never reused, including across `reset()`**. That closes a real
hazard: a completion handler for a torn-down socket arriving after the next
connection has started sending must not credit a slot it does not own. Because
the token counter is not rewound, such a late release returns `nil` and is
accounted as abandoned.

The window also tracks the *genuinely oldest* reservation rather than assuming
FIFO completion, because §5.2 establishes that FIFO completion is not guaranteed.

### 7.2 Capacity derived from a latency budget: 2 → 4

```
capacity = round(targetFPS × outboundLatencyBudget)
         = round(12 × 1/3) = 4
```

**This is deliberately not "turn the number up until it goes faster".** The
brief warned against exactly that, and the reasoning matters:

- The window's job is to bound the *local outbound backlog*. Expressed in
  frames, "2" is meaningless without a latency; expressed as a latency budget,
  it is a reviewable real-time decision: *how stale may a frame be by the time it
  is written?* One third of a second, at 12 fps, is 4 frames.
- On a **latency-dominated** link (spare bandwidth, slow round trip — the
  Tailscale case) a larger window recovers throughput that was being thrown away.
- On a **bandwidth-dominated** link it changes nothing: slot lifetime grows in
  proportion and the delivered rate is unchanged. The window still sheds load
  rather than queueing it. **This is the important property — the fix cannot
  turn into an unbounded queue on a saturated link.**
- It is deliberately not larger. At 12 fps each extra slot is another ~83 ms a
  frame may be stale before it is even written.

### 7.3 Stall detection → connection replacement

If the window is **full** *and* the oldest outstanding send has been outstanding
for ≥ 2 s, the socket is treated as wedged: teardown, then reconnect.

- Requires **full** as well as old. An aged send on a window that still has room
  is a slow send on a connection that is nonetheless admitting frames; tearing
  that down would cost more than it recovered.
- 2 s is deliberately reluctant — long enough to ride out congestion, a cellular
  handover or a Tailscale path change; short enough to cut the 52 s stall to ~4%
  of its cost. A frame written 2 s after capture is not a real-time frame, so
  nothing of value is abandoned.
- Checked on the send path rather than from a timer: it runs at the selection
  rate exactly when a stall costs something, and with no frames arriving there is
  no throughput to lose.
- **This is what makes 7.2 safe.** A larger window is only defensible if a
  wedged socket cannot sit on every slot indefinitely.

**The false-positive guard (`mainActorGapAllowance`) — added after review.** A
slot is held until the completion handler's hop *back to the main actor* has
run, so a slot's age is transport time **plus** main-actor time. Keying a
teardown off that age alone would let a busy main thread be misdiagnosed as a
wedged socket — inverting the very distinction §7.6's instrumentation exists to
draw, and potentially feeding a loop of congestion → spurious teardown →
reconnect → congestion.

The guard is that `sendFrame` is itself the main actor's pulse: it runs at the
selection rate (~83 ms apart), so a gap far larger than that *is* a main-actor
stall, observable at exactly the point the verdict is reached. When the gap
exceeds 1 s the stall verdict is skipped for one frame — by which time the
completion hops queued during the hitch have drained and returned their slots. A
genuine transport stall is still caught on the very next frame.

The alternative — having the completion handler stamp transport progress into a
lock-protected timestamp — is strictly more precise and is the right answer if
this guard proves insufficient. It was not taken here because it puts shared
mutable state on the send path for a failure mode that is, so far, hypothetical.
Both new tests in §9 pin the two directions of this behaviour.

### 7.4 Automatic reconnect with bounded backoff

**Pre-existing defect found during this work, independent of the FPS bug:**
nothing in the app ever reconnected. `fail()` set `.failed` and stopped. The only
`connect()` call site is a button in `SessionView`. So *any* transient drop —
the expected case on a remote Tailscale path — permanently ended Tower delivery
until a human noticed and tapped Connect. `ProjectManager` already contained
wiring to reopen the stream bracket "after the Tower connection is replaced" —
written for a reconnect that could not happen.

Backoff `0.5, 1, 2, 4, 8` s, then stop at a visible `.failed` (a Tower that is
simply not running must not retry forever behind a pill that never settles).
Because each attempt also carries up to the 6 s pong timeout, giving up against
a dead endpoint takes up to ~45 s.

**The budget refills only for a connection that actually held — corrected after
review.** Resetting the counter the moment a socket reaches `.online` sounds
right and is wrong: reaching `.online` proves only that the socket opened and
the Tower answered one ping. A Tower that accepts a connection and then
immediately wedges would reset the counter every lap and reconnect *forever* —
the exact unbounded loop the schedule exists to prevent. The budget is therefore
refilled on the way **down**, and only if the connection survived 30 s. A
flapping endpoint always exhausts the schedule and stops; a session that runs
for minutes and then drops is treated as the isolated blip it is. Tapping
Connect also refills it, because that is the user explicitly asking to retry.

**Opt-in, defaulting to off**, with `ProjectManager` passing `true`. This is not
timidity: reconnect makes `status` a *sequence* rather than a settled value, and
several existing tests assert that a dropped connection *settles* at `.failed`.
Defaulting it on would have made those tests race. See §10.

### 7.5 Designs considered and rejected

- **Just raise `maxFramesInFlight`.** Rejected as a standalone fix: without
  §7.3 a wedged socket still holds every slot for 52 s, and a bigger window
  simply means more stale frames in that queue. Adopted only as §7.2, derived
  and paired with stall detection.
- **Keep a replaceable "latest pending frame" to send when a slot frees.**
  Rejected on analysis. If slots free *faster* than the gate produces frames,
  the gate is the limit and the buffer is never used. If slots free *slower*, the
  window is the limit and a pending buffer adds **no throughput at all** — it
  only means the frame sent is up to one gate interval older. It costs
  staleness and buys nothing. Rejected.
- **Release the slot off the main actor** (lock-protected counter decremented
  synchronously in the completion handler), removing main-actor congestion from
  the rate-limiting loop. **Deferred, not rejected.** It is a real decoupling,
  but H2 is unproven, and it would make
  `testSendWindowDropsFramesWhileEarlierSendsAreStillInFlight` racy — that test's
  determinism depends on the decrement hopping through `Task { @MainActor }`.
  Measure first (§7.6), restructure only if the hop is shown to be significant.
  **Do not do this until `Main-actor hop ms` says it matters.**
- **Per-send timeout.** Impossible: no such API exists (§5.2).
- **Move the JPEG encode off the main actor.** Not done. Encode measured 1.57 ms
  avg / 2.30 ms max — ~2% of the main thread at 12 fps. Not currently a
  constraint; revisit only if the new hop measurement implicates the main actor.
- **Reduce JPEG quality / payload size.** Not done, because whether the link is
  bandwidth-bound is still unknown. Gated on the `Uplink KB/s` reading from the
  next run.

### 7.6 Instrumentation added

The decisive addition. New rows on the developer surface:

| Row | Meaning |
|---|---|
| `Send ms` | transport write time (avg / max) |
| `Slot ms` | full slot lifetime (avg / max) |
| `Main-actor hop ms` | derived mean difference of the two |
| `Window limit` | `capacity ÷ slot ms` — the ceiling on `Sent OK` |
| `Stall recoveries` | connections replaced due to a wedged window |

`Window limit` is the diagnosis in one number: **`Sent OK` can never exceed it**,
however many frames the gate selects. There is deliberately no "max hop": the
two maxima can come from different frames, so subtracting them would fabricate a
measurement.

---

## 8. Device health (secondary task)

The user physically felt the glasses heating. Investigated what telemetry
**actually exists**; nothing is fabricated (Development Rule 3: unknown values
remain unavailable).

### Meta DAT 0.9.0 — glasses

**Thermal IS exposed.** `WearablesInterface.deviceStateStream(for:)` yields
`DeviceState`, whose *only* property is `thermalLevel: ThermalLevel`
(`unknown, none, light, moderate, severe, critical, emergency, shutdown`). An
ordinal, not a temperature. `AsyncStream` only — no listener variant.

**Battery is NOT exposed in 0.9.0.** It existed in 0.2, was removed, and Meta has
said it returns in a later release. **Glasses battery is therefore absent from
the UI rather than estimated.**

Also absent: any numeric temperature, `HingeState`, firmware version, storage,
signal strength, worn/don-doff state, and any `DeviceStatus`/`Health*`/
`Telemetry*` type.

Reactive-only signals, arriving as the stream is already dying:
`DeviceSessionError` and `StreamError` carry `thermalCritical`,
`thermalEmergency`, `peakPowerShutdown`, `batteryCritical`; `StreamError` adds
`hingesClosed`.

**`MockDeviceKit` cannot simulate thermal or battery**, so the glasses thermal
path has **no automated test coverage and cannot be given any** — it is
physical-device-only.

Full detail recorded in `Glasses/Project_Overview_Steps/docs/05-DAT-INTEGRATION.md`
per Development Rule 4.

### Apple — iPhone

`ProcessInfo.thermalState` (+ its did-change notification; note the documented
requirement to read the property once *before* observing, which `DeviceHealth.init`
does), `ProcessInfo.isLowPowerModeEnabled` (+ `.NSProcessInfoPowerStateDidChange`
— the name lives on `NSNotification.Name`, **not** on `ProcessInfo`), and
`UIDevice` battery level/state (requires `isBatteryMonitoringEnabled = true`;
level is `-1` otherwise, translated to `nil` here; fires at most once a minute,
hence the explicit `refresh()` at session start).

This matters to the primary task: if `iPhone thermal` reads Serious or above
while the send rate decays, H2 moves from hypothesis toward cause.

---

## 9. Files changed

| File | Change |
|---|---|
| `Glasses/SendWindow.swift` | **New.** Pure value type: reservation tokens, slot lifetime, stall detection, latency-budgeted capacity. |
| `Glasses/DeviceHealth.swift` | **New.** iPhone thermal / Low Power Mode / battery. No DAT. |
| `Glasses/TowerClient.swift` | Window replaced by `SendWindow`; capacity derived; stall detection; auto-reconnect with backoff; slot timings sampled either side of the main-actor hop. |
| `Glasses/SenderMetrics.swift` | `slotSamples`, send-latency and slot-lifetime totals/maxima, `stallRecoveries`, derived `completionHopMsAverage` and `windowLimitedFPS(capacity:)`. Corrected the `successfulSendFPS` doc to the true kernel-buffer semantics. |
| `Glasses/GlassesConnection.swift` | Observes `deviceStateStream(for:)` for the active device; publishes `glassesThermalLevel`. |
| `Glasses/ProjectManager.swift` | Owns `DeviceHealth`; enables `autoReconnect`; refreshes health at session start. |
| `Glasses/ContentView.swift` | Passes `deviceHealth` to the developer sheet. |
| `Glasses/Views/DeveloperToolsView.swift` | Slot-timing / window-limit rows; new Device Health section. |
| `Glasses/Views/SessionView.swift` | "Tower replies" tile now reads `senderMetrics.frameResults` (per camera session) instead of `tower.frameResultCount` (per stream bracket) — see below. |
| `GlassesTests/SenderPipelineTests.swift` | **Appended** `SendWindowTests` (16) and `SlotTimingMetricsTests` (8). |
| `GlassesTests/TowerClientTests.swift` | **Appended** 9: window sizing, slot instrumentation, reconnect, and both directions of stall detection. |
| `Glasses/Project_Overview_Steps/docs/05-DAT-INTEGRATION.md` | Recorded the 0.9.0 device-health surface. |

**Why no new test files:** `Glasses/` is an Xcode filesystem-synchronized group,
so new app sources are picked up automatically. **`GlassesTests/` is not** — its
four files are listed explicitly in `project.pbxproj`. Adding a test file would
require hand-editing the pbxproj with fabricated 24-hex object IDs, blind, with
no way to verify. Tests were appended to the existing files instead.
`project.pbxproj` was **not modified**.

---

## 10. Invariants preserved

- **Bounded memory / no queue growth.** The window still refuses rather than
  queues. On a bandwidth-bound link the larger capacity changes nothing.
- **Bounded latency.** Now bounded in *time* (2 s stall ceiling), not just in
  frame count — strictly stronger than before, where a slot could be held
  indefinitely.
- **Fresh-frame semantics.** The newest frame is still dropped when the window
  is full; nothing is buffered for later. WebSocket streams cannot be reordered,
  so declining to add is the only backpressure available.
- **Truthful metrics.** `framesUnaccounted` accounting is unchanged and the new
  counters do not feed it. Abandoned sends contribute no timing sample (a
  teardown-length "slot lifetime" would poison the average the window is sized
  against). `stallRecoveries` is incremented only after the teardown it
  describes.
- **No slot leak or over-credit across teardown**, now enforced by
  non-reused tokens rather than by zeroing a counter.
- **Clean Stop / clean disconnect.** `disconnect()` clears the reconnect target
  *before* teardown, so a failure observed on the way down cannot resurrect a
  connection the user just closed.
- **DAT boundary (Rule 1).** `DeviceHealth` contains no DAT code; glasses
  thermal is observed inside `GlassesConnection`.
- **Rule 3.** Glasses battery is absent, not estimated. `batteryLevel = -1` is
  translated to `nil`.
- **12 fps target unchanged.** `FrameRateGate.towerTargetFPS` was not touched.
- **On-screen counters cannot reset mid-session.** `TowerClient.frameResultCount`
  is scoped to one *stream bracket*. Once a dropped connection reconnects on its
  own, a bracket no longer coincides with a camera session, so the main screen's
  "Tower replies" tile would have visibly reset to zero after any blip while the
  "Sent to Tower" tile beside it kept counting. That tile now reads
  `senderMetrics.frameResults`, so both come from the same per-session source.
  `TowerClient.frameResultCount` and its per-bracket semantics are unchanged, as
  is the test that pins them.

---

## 11. Verification performed

### 11.1 On Windows (implementation machine)

**Performed:**

- Source-level self-review of the complete diff.
- Independent adversarial source review by a separate agent. It found no
  definite compile error, and raised three MAJOR issues, **all of which were
  real and all of which are fixed**:
  1. Stall detection keyed off *slot* age, which includes the main-actor hop —
     so a main-thread hitch could have torn down a healthy socket. Fixed with
     `mainActorGapAllowance` (§7.3).
  2. The reconnect budget reset on every `.online`, so a Tower that accepted a
     socket and then wedged would have reconnected forever. Fixed by refilling
     the budget only for a connection that survived 30 s (§7.4).
  3. The `TowerClient` stall path had no test at all, despite the `stallTimeout`
     seam having been added for exactly that. Fixed with two new tests covering
     both directions.
  Also fixed from that review: a retain cycle in `observeDeviceState` (a
  `guard let self` promoted a weak capture to strong for the unbounded life of
  the stream, so the `deinit` that cancels the task could never run),
  `reconnectURL` being set after an early return, five stale or now-false doc
  comments, and one piece of dead code.
- Self-review during implementation caught, before that: two new tests that
  could pass without exercising anything (they polled for a post-drop state
  before the drop had landed), a `framesUnaccounted` leak of one frame per
  stall, and a main-screen counter that auto-reconnect would have reset
  mid-session.
- Git invariants: branched from `d9e513d`; `main` and `ui/product-shell`
  untouched.
- Confirmed `Glasses/` is a filesystem-synchronized group, so the two new app
  files need no pbxproj edit; confirmed `GlassesTests/` is not, and added no
  test files.
- Checked every changed call site of every changed signature.
- API semantics for `URLSessionWebSocketTask` and DAT 0.9.0 verified against
  primary documentation (iOS 26.5 SDK header; Meta's versioned 0.9 API
  reference), not from memory.

**NOT performed on Windows — no facility existed on that machine:**

- ❌ Xcode compilation (Debug or Release)
- ❌ XCTest execution — every test was unrun when this document was written
- ❌ SwiftUI validation / previews
- ❌ Swift concurrency and actor-isolation checking by the compiler
- ❌ Simulator
- ❌ iPhone deployment
- ❌ Meta DAT runtime validation
- ❌ Physical Ray-Ban behaviour
- ❌ Any FPS measurement whatsoever

### 11.2 On the Mac — compile and test gate CLEARED

Xcode 26.6 (build 17F113), iOS Simulator 26.5 SDK, simulator **iPhone 17 Pro**
(the iPhone 16 Pro simulator named in §13 is not installed on this machine).
Branch `ios/send-window-investigation` @ `7508db1`, working tree clean, no source
changes were required to make any of this pass.

**Now performed — these items are closed:**

- ✅ **Package resolution.** `MetaWearablesDAT` resolves to **exactly 0.9.0**.
- ✅ **Debug build: BUILD SUCCEEDED**, on the first attempt, with no edits. The
  §13 note that compile errors were "the anticipated outcome" did not
  materialise.
- ✅ **Release build: BUILD SUCCEEDED** (`generic/platform=iOS`).
- ✅ **XCTest execution: 89/89 pass, 0 failures.** Exactly the predicted count —
  56 pre-existing + 33 new. Verified against the base: `d9e513d` has 56 test
  methods, `7508db1` has 89. `SenderPipelineTests` 27 → 51 (+16 `SendWindowTests`,
  +8 `SlotTimingMetricsTests`); `TowerClientTests` 19 → 28 (+9). **All 56
  pre-existing tests still pass** — no regression.
- ✅ **Six consecutive green runs.** The full suite was run 6 times end to end:
  89/89 every time, zero flakes. This specifically clears **§12.4** (the
  reconnect tests that use real wall-clock timing against a loopback server) and
  the two deliberately main-actor-blocking stall tests
  (`testAWedgedSendWindowReplacesTheConnection`,
  `testAStalledMainActorIsNotMistakenForAWedgedSocket`). No timeout loosening was
  needed.
- ✅ **Swift concurrency / actor-isolation checking by the compiler.** The
  project's `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` accepted the
  `nonisolated` `SendWindow`, its tuple-array reservations, and the in-body
  initialiser defaults. **§12.2 and §12.3 clear** — no Sendable warnings from
  `DeviceHealth`'s notification observation.
- ✅ **Meta DAT 0.9.0 thermal API validated at compile time.** The
  highest-ranked risk in §12.1 is resolved: `WearablesInterface.deviceStateStream(for:)`
  and `DeviceState.thermalLevel` both exist and compile against the real 0.9.0
  package. The contingency in §12.1 and §16 — "delete just the DAT thermal code
  and ship the sender work" — is **not needed**.
- ✅ **New files are in the target automatically.** `SendWindow.o` and
  `DeviceHealth.o` are produced by the synchronized group. `project.pbxproj`
  remains unmodified; no test files were added.
- ✅ **Simulator** — used as the XCTest host. Note this means the test *host*
  ran; the app UI was not manually exercised there (see below).

**Build warnings: 5, all pre-existing, none introduced by this branch.**

A clean (non-incremental) Debug build emits five warnings in project sources,
two of them "this is an error in the Swift 6 language mode". They were checked
against the base rather than assumed: `d9e513d` was built in a scratch worktree
under both configurations and emits the **identical five** — same kinds, same
files, only the line numbers shifted by the new code above them.

| Warning | At `d9e513d` | At `7508db1` |
|---|---|---|
| `FrameRateGate` — main actor-isolated static `tolerance` from nonisolated context | :104 | :104 |
| `GlassesConnection` — `'as' test is always true` | :360 | :384 |
| `TowerClient` — main actor-isolated static `webSocketURL` from nonisolated context | :114 | :247 |
| `TowerClient` — captured var `self` in concurrently-executing code | :216 | :495 |
| `TowerClient` — captured var `self` in concurrently-executing code | :305 | :596 |

So this branch adds **zero** new warnings. They are worth fixing eventually —
two are future Swift 6 errors — but they are not this change's defect and were
deliberately not touched here.

*Method note:* an incremental build recompiles nothing and therefore reports no
warnings. Every warning count above comes from a clean build with a dedicated
`-derivedDataPath`. A "no warnings" reading from an incremental build is not
evidence.

**Design constants verified to match this document:**
`outboundLatencyBudget = 1.0/3.0`, capacity = `round(12 × 1/3)` = **4**,
`sendStallTimeout = 2.0`, `mainActorGapAllowance = 1.0`, reconnect backoff
`[0.5, 1, 2, 4, 8]`. `FrameRateGate.towerTargetFPS` is still `12` and the file is
untouched by the diff. `project.pbxproj` untouched. §10's invariants hold at
source level.

### 11.3 STILL NOT performed — physical validation is outstanding

**The compile-and-test gate proves the change is sound and safe to run. It says
nothing whatsoever about whether it is faster.** Everything below is still open,
and §15's expected result remains a *hypothesis, not a measurement*.

- ❌ **Any FPS measurement whatsoever.** The 3.4 fps → 10–12 fps prediction is
  unmeasured.
- ❌ **iPhone deployment.** The physical iPhone 16 Pro is paired but was not
  connected during this session.
- ❌ **Meta DAT runtime validation.** The thermal symbols compile; they have
  never been *run* against hardware, and `MockDeviceKit` cannot simulate thermal
  (§8), so `glassesThermalLevel` remains physical-device-only and untested.
- ❌ **Physical Ray-Ban behaviour.**
- ❌ **Live Tower streaming over Tailscale**, and therefore no reading for
  `Send ms`, `Slot ms`, `Main-actor hop ms`, `Window limit`, `Stall recoveries`
  or `Uplink KB/s`.
- ❌ **H1 / H2 / H3 remain unresolved** (§5.3). Nothing measured on the Mac
  distinguishes them.
- ⚠️ **SwiftUI previews / manual UI validation — partly done since.** The app
  has now been launched in the Simulator on `ios/integration-candidate`: it
  renders, `GlassesConnection` is created exactly once, Tower auto-connect is
  attempted, and the camera stays off. But the shell it renders is the
  cartridge-driven one, not the `SessionView` this document describes — that
  file was deleted by `319a23b`. The **Developer sheet rows remain unexercised
  visually**, and nothing that needs a live camera or a reachable Tower can be
  driven in the Simulator, so every sender row is still unread.
- ❌ **§16 merge criteria are NOT met.** The build and test criteria are
  satisfied; the 5-minute ≥ 10 fps sustained-rate criterion, backlog stability,
  clean Stop and sequence 1:1 on hardware are all still unverified. **Do not
  merge on the strength of §11.2 alone.**

---

## 12. Highest-risk items for the Mac session

Ranked. Check these first.

1. **`GlassesConnection.observeDeviceState(for:)` uses two DAT symbols this
   machine could not compile against:** `WearablesInterface.deviceStateStream(for:)`
   and `DeviceState.thermalLevel`. Sourced from Meta's versioned 0.9 API
   reference, but unverified by a compiler. If either is wrong, the fix is
   contained to that one function plus the `glassesThermalLevel` property — it is
   deliberately isolated. **This is unrelated to the FPS fix; if it fights you,
   delete it and ship the sender work.**
2. **Actor isolation.** The project builds with
   `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`. `SendWindow` is `nonisolated`
   throughout for that reason. The `TowerClient` initialiser resolves its
   defaults *in the body* rather than as default arguments, because default
   arguments are evaluated outside the type's actor — the same trap
   `GlassesConnection.init` already documents.
3. **`DeviceHealth`'s notification observation** — `for await _ in
   NotificationCenter.default.notifications(named:)` inside
   `Task { [weak self] in … }`, one task per signal. Written in the same shape
   `GlassesConnection` already uses for its DAT streams, deliberately, so no
   closure crosses an isolation boundary and the non-`Sendable` `Notification`
   is discarded rather than moved. May still produce Sendable warnings under
   stricter checking; the properties are re-read rather than taken from the
   notification, so the warnings are cosmetic if they appear.

   Two other compile risks were pre-emptively removed for the same reason and
   are worth knowing about if you refactor: `SendWindow` stores its
   reservations as a **tuple array rather than a nested struct** (an
   unannotated nested type would be main-actor isolated under
   `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` and unusable from the
   `nonisolated` methods), and `SendWindow`'s members are individually
   `nonisolated` in the same style as `FrameRateGate`, which is the pattern
   already proven to compile in this project.
4. **New reconnect tests use real timing** against a loopback server and sleep
   past the 0.5 s first backoff step. If they prove flaky on the Mac, prefer
   loosening timeouts over deleting the assertions.
5. Apple's TN3151 now recommends Network framework over
   `URLSessionWebSocketTask` for new WebSocket code, and DTS threads document
   poor/slow failure surfacing in the Foundation implementation. **Not acted on
   here** — it is a transport rewrite, far outside this task. Worth recording as
   a future decision.

---

## 13. Mac validation sequence

> **Status: steps 1–5 COMPLETE and green. Step 6 (device) is outstanding.**
> Results recorded in §11.2. Nothing below needed fixing; no source change was
> made on the Mac. Re-run this sequence only if the branch moves.

Run in this order. Do not skip to the device.

```bash
git fetch origin
git checkout ios/send-window-investigation
git log --oneline -3          # expect the send-window commit on top of d9e513d
```

Substitute the simulator you actually have. This machine has no iPhone 16 Pro
simulator; validation was done on **iPhone 17 Pro** (Xcode 26.6, build 17F113,
iOS Simulator 26.5 SDK). Check with `xcrun simctl list devices available`.

1. ✅ **Resolve packages.** Confirm meta-wearables-dat-ios pins to exactly 0.9.0.
   — **Done: resolves to exactly 0.9.0.**
2. ✅ **Debug build.**
   ```bash
   xcodebuild -project Glasses.xcodeproj -scheme Glasses \
     -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
   ```
   The original note here said to expect compile errors, and that fixing them
   was the anticipated outcome. **That did not happen: BUILD SUCCEEDED on the
   first attempt with no edits**, including the §12.1 DAT thermal symbols. The
   warning about where errors were most likely (§12) is retained only as history.

   Use a dedicated `-derivedDataPath` when you care about the warning output — an
   incremental build recompiles nothing and reports no warnings, which is not
   the same as being clean.
3. ✅ **Confirm the two new files are in the target.** `SendWindow.swift` and
   `DeviceHealth.swift` should be compiled automatically via the synchronized
   group. If they are not, add them — but do **not** add new *test* files.
   — **Done: both produce object files via the synchronized group;
   `project.pbxproj` unmodified.**
4. ✅ **Run the tests.**
   ```bash
   xcodebuild -project Glasses.xcodeproj -scheme Glasses \
     -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
   ```
   — **Done: 89/89 pass, 0 failures.** Run 6 times consecutively, green every
   time.
   - Expect **89** test methods total: the 56 pre-existing ones plus 33 added
     here (`SendWindowTests` 16, `SlotTimingMetricsTests` 8, and 9 appended to
     `TowerClientTests`). **Confirmed exactly.**
   - The 56 pre-existing tests **must all still pass**. Any regression there is a
     defect in this change, not a test to update. **They all pass.**
   - ~~Every one of the 33 new tests is unrun.~~ **All 33 have now run and
     pass.** The caution that a failure among them was as likely a bad test as a
     bad implementation no longer applies to this commit.
   - Two of them (`testAWedgedSendWindowReplacesTheConnection`,
     `testAStalledMainActorIsNotMistakenForAWedgedSocket`) deliberately
     **busy-wait to block the main actor** for 0.2 s and 1.1 s respectively.
     That is not sloppiness: `Task.sleep` would yield the actor, the queued send
     completion would run, the slot would come back, and there would be no stall
     left to detect. Blocking is the only way to hold a window open against a
     loopback server that answers instantly, and it makes both tests
     deterministic rather than timing-dependent. **Both pass, and were stable
     across all 6 runs — §12.4's flakiness concern did not materialise and no
     timeouts were loosened.**
5. ✅ **Release build**, to catch anything `#if DEBUG` hid.
   ```bash
   xcodebuild -project Glasses.xcodeproj -scheme Glasses \
     -destination 'generic/platform=iOS' -configuration Release \
     build CODE_SIGNING_ALLOWED=NO
   ```
   — **Done: BUILD SUCCEEDED.** Nothing was hidden by `#if DEBUG`.
6. ⬜ **Deploy to the physical iPhone.** — **OUTSTANDING.** This is where
   validation currently stops. Proceed to §14; that procedure is entirely
   unperformed and is what §16's merge criteria actually turn on.

---

## 14. Physical test procedure

Ray-Ban Meta glasses + iPhone + the real remote Tower over Tailscale, matching
the baseline conditions as closely as possible.

1. Start the Tower. Confirm it is reachable.
2. Launch the app, connect to the Tower, wait for the pill to go green.
3. Start the camera session. Confirm the live viewfinder.
4. **Run for a full 5 minutes.** The bug is a *decay*; a 60-second run will look
   fine and prove nothing. Match the baseline duration.
5. Open the Developer sheet at **~85 s** and record every Sender Pipeline row —
   this is the direct comparison point against the baseline's 7.0 fps.
6. Record every row again at **~5 minutes**, plus the Device Health section.
7. Record the Tower's own session summary.
8. Tap **Stop**. Confirm counters freeze, the stream bracket closes, and no
   frames are sent afterwards.

**Capture these specifically — they are what the next decision depends on:**

- `Sent OK` fps at 85 s **and** at 5 min (is the decay gone, or merely smaller?)
- `Send ms` avg/max and `Slot ms` avg/max
- **`Main-actor hop ms`** — settles H2. If it is small, the main actor is
  exonerated and §7.5's deferred restructuring stays deferred.
- **`Window limit`** — if this sits at or above 12 fps, the window is no longer
  the constraint.
- **`Uplink KB/s`** — settles bandwidth-bound vs latency-bound. **Not captured in
  the baseline; capture it this time.**
- **`Stall recoveries`** — if > 0, H1 is confirmed and the stall detector fired.
- `Backlog` must stay small and must **not climb**.
- `Glasses thermal`, `iPhone thermal`, `Low Power Mode`, `iPhone battery` at both
  timestamps — and note whether the glasses feel hot again.
- Tower `receive_to_result_ms_max` — did the 52 s outlier recur?

---

## 15. Expected result — **HYPOTHESIS, NOT A MEASUREMENT**

> **The following has not been observed. It is a prediction derived from
> arithmetic, and it may be wrong.**

If the link is latency-dominated at ~290 ms and stalls are the decay mechanism:

- Successful sends **~10–12 fps** (from 3.4)
- Tower `effective_fps` tracking within ~0.5 fps of it
- Send-window drops falling sharply (the window stops being the binding
  constraint; the gate does)
- `Window limit` ≥ 12 fps
- Worst-case staleness bounded at ~2 s instead of 52 s
- `Stall recoveries` small but possibly non-zero

**What would mean the diagnosis is wrong:**

- `Sent OK` stays ~3.4 fps **and** `Slot ms` scales up with the bigger window
  (e.g. ~1.2 s at capacity 4) ⇒ the link is **bandwidth-bound**, not
  latency-bound. The window is then correctly shedding load and the real fix is a
  smaller payload (JPEG quality, resolution, or a binary frame instead of
  base64-in-JSON, which costs ~33% on the wire). Check `Uplink KB/s`.
- `Main-actor hop ms` is large ⇒ H2. Implement the deferred off-main slot
  release from §7.5.
- `Stall recoveries` climbing continuously ⇒ the 2 s threshold is too aggressive
  for this link, or the Tower stalls chronically. Raise `sendStallTimeout` before
  concluding the mechanism is wrong.

---

## 16. Merge / revise / revert criteria

**Merge to `ui/product-shell` when all of:**

- Debug **and** Release build clean
- All 56 pre-existing tests pass, plus the new ones
- A 5-minute physical run sustains **≥ 10 fps** successful sends with no decay
  between the 85 s and 5 min readings
- `Backlog` stays small and does not climb; memory is stable
- Stop is clean; a deliberate disconnect is not undone by a reconnect
- Sequence 1:1 still holds

**Revise (keep the branch, change the design) if:**

- Sends improve but land in 6–9 fps ⇒ tune `outboundLatencyBudget`, or act on the
  `Uplink KB/s` reading
- `Main-actor hop ms` is significant ⇒ implement the deferred off-main release
- Stall recoveries thrash ⇒ raise `sendStallTimeout`
- Only the DAT thermal code fails to compile ⇒ **delete just that** and ship the
  sender work; it is independent

**Revert to `d9e513d` if:**

- Any pre-existing test fails and the cause is this change
- The physical run is **worse** than 3.4 fps, or memory/latency grows unbounded
- Reconnect proves unstable on the real network (thrashing, or overriding the
  user)

Revert is cheap and clean: `ui/product-shell @ d9e513d` is untouched, and this
branch is a strict addition on top of it.

---

## 17. Open questions for the next session

- Latency-bound or bandwidth-bound? (`Uplink KB/s`)
- What caused the Tower's 52 s read stall? Tower-side; not investigated here.
- Should the wire format drop base64-in-JSON for binary WebSocket frames? ~33%
  saving, only worth it if bandwidth-bound.
- Should the transport move to Network framework, per Apple's own current
  recommendation? Large, and out of scope for this task.
- Should `ThermalLevel` drive a user-facing warning, or throttle the send rate?
  Deliberately not done — the level is only *displayed* today.

---

## 18. Final Git state

- Branch: `ios/send-window-investigation`
- Implementation commit: `76d3810` "Size the Tower send window to a latency budget and detect stalls"
- Base: `ui/product-shell` @ `d9e513d` (unmodified)
- `main` unmodified
- `project.pbxproj` unmodified
- Working tree clean; branch pushed

**Validation state:** implementation was produced on Windows without Xcode, then
compiler- and test-validated on the Mac at `7508db1` — Debug and Release builds
clean, 89/89 tests passing across 6 consecutive runs, zero new warnings versus
`d9e513d`. **No source change was required on the Mac; this branch's runtime
behaviour is byte-identical to what Windows produced.**

**It has NOT been device-validated.** No deployment to the physical iPhone, no
Ray-Ban run, no Tower streaming, and no FPS measurement of any kind. See §11.3
for the full outstanding list and §14 for the procedure that closes it.
