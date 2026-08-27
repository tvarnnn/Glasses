# CV Lab → iOS: exactly what to build

**Audience:** whoever owns `ios/`. Written to be followed literally.
**Tower side:** done and on `cv-lab/productization-v1`. Nothing below is
speculative about the Tower — every message, field and error named here
exists and has a test.
**Contract:** `tower/docs/contracts/EXPERIMENTAL-CV-LAB.md`. Read §3, §4,
§8 and §9 of that before writing code; this document says what to do with
it, not what it says.

This lane does not own `ios/` and made **no Swift changes**. Everything
here is a change for that lane to make.

---

## 0. The one-paragraph version

The Tower now enumerates its eight CV experiments, lets a client select
and start one at runtime with no restart, reports lifecycle with legible
refusals, and stamps every per-frame result with the run and experiment
that produced it. `ExperimentalCVWorkspaceView` and every type behind it
were written for exactly this and are currently unreachable because
`UnavailableExperimentalCVClient` is wired in. The work is: add one
contract identifier, add one name mapping, write one Tower-backed client,
add one enum case, add one gated Start control. **No view changes.**

---

## 1. The five-step reconciliation, applied

`ios/docs/agent-handoffs/IOS-TO-TOWER.md` §8 gives the shape. Here it is
filled in.

### Step 1 — declare the contract

`Glasses/Cartridges/Integration/CartridgeClient.swift`:

```swift
enum ExperimentalCVResultContract {
    static let towerCartridge = "experimental_cv"
    static let resultType = "status"
    static let identifier = "experimental_cv.status/2026-08-27"
    // Only needed if you send commands. A Release build that cannot
    // stream should implement the read-only half and never send one.
    static let controlIdentifier = "experimental_cv.control/2026-08-27"
    static let frameResultIdentifier = "experimental_cv.frame_result/2026-08-27"
}

static let supported: Set<String> = [
    WorldBuilderResultContract.identifier,
    ExperimentalCVResultContract.identifier,
]

static let towerCartridgeNames: [String: String] = [
    "world-build": WorldBuilderResultContract.towerCartridge,
    "experimental-cv": ExperimentalCVResultContract.towerCartridge,   // NEW
]
```

**Without the `towerCartridgeNames` entry nothing else works.**
`TowerCapabilities.declaredContract(for:in:)` returns `nil` for
Experimental CV regardless of what the Tower declares, the workspace
resolves to `.noContract`, and the screen shows "Nothing yet" — with the
Tower on the other end offering the contract.

**Tests that will fail, and should:**

| Test | Why it fails | What to do |
|---|---|---|
| `ProductShellTests.testTheTowerDeclaresOnlyTheWorldBuilderContract` | `supported` now has two | update it; the failure is the intended review signal |
| `ProductShellTests.testNoClientProducesTowerData` | `experimental-cv` is no longer permanently `.unsupported` | narrow it to the three cartridges that still have no client |
| `ProductShellTests.testTheTowerDeclaresNoCartridgeContracts` | ditto | ditto |

`Cartridge.catalog`'s `"experimental-cv": .next` status is a roadmap
label, not a capability check. Change it when the screen works, not
before.

### Step 2 — write `TowerExperimentalCVClient`

Model it on `TowerWorldBuilderClient` exactly: `handle(_ event:)`
filtering every arm on `envelope.cartridge ==
ExperimentalCVResultContract.towerCartridge`, a hand-written
`[String: Any]` decoder, `isOurs(_:)` for error attribution, and
`CartridgeFailure(kind: .undecodableResponse)` rather than a partially
populated snapshot.

Subscribe exactly as World Builder does:

```json
{"type": "result_subscribe",
 "cartridge": "experimental_cv",
 "result_type": "status",
 "contract": "experimental_cv.status/2026-08-27"}
```

Sending `contract` is optional but do it: a mismatch is then refused with
`result_error` / `contract_mismatch` carrying `offered_contract`, instead
of the Tower serving a payload you would decode under different rules.

### Step 3 — construct it in `CartridgeClients`

Owned by `ProjectManager`, **not** in the workspace view — that
`@StateObject` is destroyed on every cartridge switch, and a client
holding a subscription and a live run must outlive it. This is why
`ExperimentalCVViewModel.init(client:)` has no default argument.

### Step 4 — no view changes

`ExperimentalCVWorkspaceView` already renders `.idle`, `.starting`,
`.running`, `.completed`, `.failed`, metric rows with an "Estimate"
badge, Tower processing ms, annotation count, and a withheld-artifact
reason. One enum case is missing; see §4.

### Step 5 — decode tests, including the negative ones

Fixtures are in §7.

---

## 2. Mapping the payload onto types that already exist

`status.lifecycle.state` → `ExperimentalCVState`:

| Tower | iOS |
|---|---|
| `unavailable` | `.unsupported(reason: status.lifecycle.reason ?? <generic>)` |
| `idle` | `.idle(available: <catalog>)` |
| `starting` | `.starting(<the experiment in status.run.experiment>)` |
| `running` | `.running(<run>)` |
| `paused` | **`.paused(<run>)` — new case, §4** |
| `stopped` | `.completed(<run>)` |
| `failed` | `.failed(CartridgeFailure(kind: .towerError, message: status.lifecycle.reason))` |

An **unrecognised** `state` string must produce
`CartridgeFailure(kind: .undecodableResponse)` — not a guess, and not
`.idle`. A future Tower adding a state is exactly the case where a guess
puts a wrong screen in front of somebody.

`status.available[]` → `[CVExperiment]`:

```swift
CVExperiment(id: entry["id"], name: entry["name"], summary: entry["summary"])
```

Read those three and ignore the rest, or use them: `requires_model` is
worth a badge (a start may take a hundred times longer),
`available: false` with `unavailable_reason` should disable the row rather
than hide it — "this Tower cannot run depth because torch is not
installed" is a useful thing for a person to know.

`status.run` → `CVExperimentRun`:

| iOS | from |
|---|---|
| `experiment` | `run.experiment` (same shape as a catalog entry) |
| `metrics` | `run.metrics[]`, §3 |
| `annotation.count` | `run.annotation.count` — **`nil` and `0` are different**, see §3 |
| — | `run.experiment` has **exactly the same keys** as an `available[]` entry, including `available` and `unavailable_reason`. One `CVExperiment` decoder for both |
| `annotation.artifact` | always `.absent`. `run.annotation.artifact` is always `null` and `artifact_unavailable_reason` says why |
| `timings.processingMs` | `run.timings.processing_ms` |
| `timings.time.observedAt` | `run.timings.observed_at` — **only this**. Never `Date()` at decode |
| `framesProcessed` | `run.frames_processed` |

`run.timings.observed_at` may be `null` (a run that has processed no
frames). `ObservationTime` already renders that as "time unknown"; do not
substitute `receivedAt`.

**On a run that has processed no frame — which is every Release build —
`metrics` is empty and every number under `timings` and `throughput` is
`null`**: `processing_ms`, `processing_ms_max`, `observed_at`,
`capacity_fps`, `processed_fps` and `offered_fps`. Not zero — `null`. A
rate over a zero-length window is undefined, and `time.time()` on Windows
has ~15.6 ms granularity, so **the reply to your very first
`cv_lab_start` will almost always carry `processed_fps: null`** (measured
at 11 of 12). Type them all optional; the Tower exercises every one of
them on the first message you receive.

**A STOPPED run is frozen.** Every field under `run` stops moving at the
stop, including the frame counters. Frames that keep arriving afterwards
are refused and counted by `source`, which belongs to the Tower rather
than to a run that ended. So `.completed(run)` renders numbers that will
never change again — which is what makes it worth rendering.

---

## 3. Metrics — the parts that are easy to get subtly wrong

```json
{"label": "edge_density", "value": 0.0413, "unit": "fraction",
 "aggregation": "rate", "frames": 6, "provenance": "measured",
 "confidence": null, "headline": true, "varied": false,
 "baseline": null, "higher_is_better": null}
```

```swift
CVMetric(label: row["label"], value: row["value"],
         unit: row["unit"],
         provenance: provenance(from: row),
         baseline: row["baseline"],
         higherIsBetter: row["higher_is_better"])
```

1. **`value` may be `null`, and `null` is not zero.** It means the metric
   has no meaningful aggregate — an `unaggregated` circular quantity, or a
   `constant` that stopped being constant (`varied: true`). `CVMetric.value`
   is non-optional `Double`, so either skip such a row or give
   `CVMetric` an optional value. **Do not coerce to 0.** A direction of
   0° that nothing was moving in is exactly the number `MetricKind`
   exists to stop being published.
2. **`provenance` is always present** and is `"measured"` or
   `"inferred"`. Map to `.measured` / `.inferred(confidence: nil)`. A row
   missing it, or carrying a third value, is `.undecodableResponse` — not
   `.unknown`. The Tower promises this field; a Tower that broke the
   promise is a Tower you are not talking to correctly.
3. **`confidence` is always `null`.** The Tower has no calibrated
   confidence for any of these. Do not invent one.
4. **`baseline` and `higher_is_better` are always `null`,** so
   `CVMetric.comparison` is always `nil` and no better/worse verdict is
   ever rendered. That is correct and deliberate: the Lab holds no
   reference run, and a comparison against nothing is the
   "declaring an approach 'better' without a measurement" the module doc
   rules out. Offline corpus comparison is `scripts/cv_lab_benchmark.py`
   on the Tower and is not this channel.
5. **`unit` may be `null`** and then the figure is rendered **bare**.
   `depth` is the case: relative inverse depth on an arbitrary scale.
   `CVMetric.unit` already takes this position; keep it.
6. **`headline: true` marks one row**, always first. Worth rendering
   larger — it is the experiment's own statement of what it measures.
7. **`aggregation`** (`rate` / `count` / `constant` / `unaggregated`) is
   how the number was combined across frames. Worth a caption ("mean over
   612 frames" from `aggregation` + `frames`) and worth NOT hiding: a
   sum and a mean look identical on screen.

**Annotations.** `run.annotation.count` is `null` for every experiment
except `object_detection`, and for that one `0` is a real result meaning
"found nothing". `CVAnnotationReport.count` is already `Int?` for this
reason. `run.annotation.artifact` is always `null`: the Tower serves no
imagery for CV Lab results, because iOS withholds any image whose
redaction treatment is unstated and no artifact-fetch contract exists on
either side. Render `.absent` with `artifact_unavailable_reason` as the
explanation; do not build a fetch.

---

## 4. The one type change: `.paused`

`ExperimentalCVState` has no case for a Lab that is armed and
deliberately not processing. Mapping it to `.running` would claim live
figures that are not moving; mapping it to `.completed` would claim a run
that ended. Add:

```swift
case paused(CVExperimentRun)
```

with `phase == .settled`, `isRunning == false`, and `run` returning the
associated value. `.settled` because the figures are final *for now*,
which is what the existing `.settled` rendering already says.

The Tower distinguishes `paused` from `stopped` because the difference is
real: a paused run keeps its experiment **loaded**, so resuming a `depth`
run is instant while restarting a stopped one pays the model load again.
That difference is worth surfacing — "Resume" versus "Start" is not the
same button.

---

## 5. Commands, and stale-result invalidation

### The five messages

```json
{"type": "cv_lab_status",  "request_id": "req-1"}
{"type": "cv_lab_start",   "experiment_id": "edge_detection", "request_id": "req-2"}
{"type": "cv_lab_pause",   "run_id": "<current>", "request_id": "req-3"}
{"type": "cv_lab_resume",  "run_id": "<current>", "request_id": "req-4"}
{"type": "cv_lab_stop",    "run_id": "<current>", "request_id": "req-5"}
```

Send them through `sendResultMessage`-style fire-and-forget: a failed send
must never tear down the socket the camera streams over.

**Always send `run_id`** on pause/resume/stop, taken from the status you
drew the button against. Without it the Tower applies the command to
whatever run is current, and if somebody else switched experiments in the
meantime you stopped the wrong run. With it you get `cv_lab_error` /
`stale_run` carrying `current_run_id`.

**Always send `request_id`.** It is echoed back and it is how you match a
reply to the button when two commands are in flight and one is refused.
Without it, `lastRequestFailure` cannot be attributed to a specific
action. **Keep it to 64 characters**: a longer one is silently dropped —
the command still applies, the reply simply carries no `request_id`, and
you have lost the only thing that field was for.

### The two replies

`cv_lab_status` — carries the whole document. `accepted_command` is
present **only** when it is a reply to a command; a pushed status has no
such key, which is how you tell an answer from an update.

`cv_lab_error` — a refusal. **Every one of them means the request did not
take effect.** Map to `lastRequestFailure` (which is deliberately separate
from `state`, so a refusal does not erase what is on screen) and update
`state` from the `status` the error also carries.

| `reason` | Say |
|---|---|
| `unknown_experiment` | "This Tower does not have that experiment." Refresh the catalog from `available` in the error |
| `experiment_unavailable` | Use `message` verbatim — it names the missing extra |
| `lab_busy` | "Another start is still in progress." Do not retry automatically |
| `invalid_state` | A UI bug: you offered a button the state does not allow. Log it |
| `stale_run` | "Somebody else changed the experiment." Redraw from the `status` in the error |
| `lab_unavailable` | The Tower cannot run experiments; treat as `.unsupported` |
| `malformed_request` | A client bug. Log it |
| `internal_error` | The Tower failed while answering. **Transient — retrying is reasonable**, unlike `lab_unavailable`, which is terminal |

**There is no `start_failed`, and you must not wait for one.** An arm is
asynchronous, so by the time a load fails the Tower has already answered
your `cv_lab_start` with `accepted`. The failure arrives as **state** —
`lifecycle.state: "failed"` with a `reason` — through the result-channel
subscription or a `cv_lab_status` poll. **A client that sends commands and
does not also read status will sit on `.starting` forever when a start
fails.** Subscribe first, then send commands.

Every `cv_lab_error` carries `status`, including the `lab_unavailable`
refusal from a Tower with no Lab at all — that one carries a hollow
document with the real contract identifiers in it, so one decoder handles
every case.

### Stale-result invalidation — the rule

> **Discard any `frame_result` whose `cv_lab.run_id` is not the run you
> are currently watching.**

Hold the run id from the last status you applied. On every `frame_result`,
compare. This is one comparison and it is the whole mechanism.

The Tower makes it structural on its side — a new experiment is a new run
and the old experiment is released before the new run id is published, so
it cannot emit a misattributed result. The client-side check covers the
case the Tower cannot: **a reconnect to a restarted Tower**, which starts
counting runs again. `tower_instance_id` is baked into every run id
(`"<instance>-<n>"`) precisely so that comparing `run_id` alone is
sufficient — you do not need a second comparison.

Also clear the run id on `sendStreamStop()` and on teardown, next to the
existing `latestFrameResult = nil`. Same reasoning as the comment already
there: after a stop there is no current reply, and leaving the last one on
screen dates it silently.

### Frames during a switch

While the Lab is arming, frames are answered with `frame_error`, not
silence:

```json
{"type": "frame_error", "seq": 30, "reason": "cv_lab_starting",
 "message": "the CV Lab is arming an experiment; frames are refused until it is ready..."}
```

`reason` is one of `cv_lab_idle`, `cv_lab_starting`, `cv_lab_paused`,
`cv_lab_stopped`, `cv_lab_failed`, `cv_lab_unavailable`, alongside the
transport's existing `invalid_frame`, `frame_skipped`,
`module_unavailable`. **`TowerClient.handleInboundMessage` has no
`frame_error` case today** — it falls to `default:` and logs. Add one:
these are not errors to alarm anybody with, they are the honest answer to
"why did that frame produce nothing", and the `message` says what to send.

---

## 6. Debug, Release, and not claiming what cannot arrive

The camera path is `#if DEBUG` — `GlassesConnection`'s DAT imports,
`CapturedFrame` itself, `startCameraSession()`, `ProjectManager`'s
frames→Tower bridge, and `TowerClient.sendFrame/sendStreamStart/
sendStreamStop`. **A Release build has no camera, sends no frame, and
receives no `frame_result`.**

The split that makes this workable:

| Half | Gated? | Reachable in Release? |
|---|---|---|
| capability declaration, `result_subscribe`, `cartridge_result`, the status document | **no** | **yes** |
| `cv_lab_status` / `cv_lab_start` / … | your choice | yes, but pointless without a stream |
| `frame_result` and its `cv_lab` block | downstream of the DEBUG camera path | **no** |

Rules for the iOS lane:

1. **Do not gate the client, the subscription or the state rendering.**
   A Release build is entitled to a truthful answer about what the Tower
   can do — the same reasoning already written on
   `requestCartridgeDeclaration()`.
2. **`.running` may be shown as LIVE only when this build is itself
   streaming AND `status.source.receiving_frames` is `true`.** Both halves.
   `source` is **Tower-wide, not per connection** — one Tower has one Lab
   and one run, and the Lab is handed bytes rather than a connection
   identity — so on a Tower with a second phone attached,
   `receiving_frames` is `true` for a Release build that has no camera at
   all. Your own streaming state is the half that catches that.
   `source.frames_offered_total` and `source.last_frame_at` inform the
   decision; `source.clients_connected > 1` says somebody else is on this
   Tower too, and is worth showing.
3. **The Start control is `#if DEBUG`**, because `startCameraSession()`
   does not exist in Release. In Release, say the build has no camera —
   the Home workspace already has the sentence for it ("Capture is not
   available in this build.").
4. **Never render a control whose effect you cannot deliver.** A Start
   button in Release, or a "live" badge with `receiving_frames: false`,
   converts a limitation into a false assurance.

### The Start control, concretely

`ContentView.swift:171` currently passes the CV workspace no `glasses`,
and `ExperimentalCVWorkspaceView`'s header comment explains why: there was
nothing for a session to feed, and every additional `startCameraSession()`
call site is another place the "the app never starts the camera on its
own" invariant must be re-verified. That comment ends with an explicit
invitation — *"When the Tower can run an experiment, the control that
starts one belongs here."*

It can now. Pass `glasses: project.glassesConnection` into the
`.experimentalCV` arm and add one gated control, modelled on
`WorldBuilderWorkspaceView`'s. Two things to preserve:

- **Still no `.onAppear` start.** The invariant is that a person presses a
  button; keep it structural.
- **The Lab's Start and the camera's Start are different things.** Pressing
  Start in the CV Lab should (a) `cv_lab_start` the chosen experiment and
  (b) `startCameraSession()` if `isCaptureEngaged` is false. Doing only
  (a) is the "Start that sends no frames" the Tower now reports; doing only
  (b) is today's behaviour. The user-visible promise is one button, and
  that is the whole point of the workflow this replaces.
- Leaving the workspace does **not** stop capture (Product Shell V2 §8).
  A Stop in the Lab should stop the run; whether it also stops the camera
  is a product call — say which one the button does.

---

## 7. Fixtures

Copy real bytes rather than inventing them. Against a running Tower:

```powershell
curl http://localhost:8000/cv-lab > cv-lab-status.json
curl http://localhost:8000/cartridges > cartridges.json
```

The `status` object inside `cv-lab-status.json` is **byte-identical** to
the `payload` of a `cartridge_result` for `experimental_cv`/`status` and
to the `status` of a `cv_lab_status` reply. A Tower test asserts all
three. So one capture is a fixture for all three surfaces.

Negative fixtures worth having, all of which the Tower can produce:

| Fixture | How to get it |
|---|---|
| a refusal | send `{"type":"cv_lab_start","experiment_id":"nope"}` |
| a stale-run refusal | start twice, then stop with the first `run_id` |
| a frame refused while arming | start `depth` and send a frame |
| a metric with `value: null` | run `optical_flow`; `dominant_direction_deg` is `unaggregated` |
| a `constant` that varied | run `frame_quality` at two resolutions in one run |
| a refusal with a hollow status | any command against a Tower whose Lab failed to load |
| a run with every timing `null` | read the status of a fresh Tower before sending a frame |
| an unavailable experiment | run a Tower without the `[ml]` extra; `depth` gets `available: false` |
| `receiving_frames: false` | read the status more than 5 s after the last frame |
| the Lab unavailable | `GET /cv-lab` on a Tower with no Lab returns **503**, not 404 |

**Decoder tests that must exist** (the negative ones are the point):

- an unrecognised `lifecycle.state` → `.undecodableResponse`
- a metric row with no `provenance` → `.undecodableResponse`
- a metric row with `value: null` → not rendered as `0`
- `annotation.count: 0` → renders "0 found", not "not reported"
- `annotation.count: null` → renders "not reported", not "0"
- `unit: null` → bare number
- a `frame_result` whose `cv_lab.run_id` differs from the watched run →
  discarded, and `latestFrameResult` unchanged
- a `cv_lab_error` → `lastRequestFailure` set, `state` NOT cleared

---

## 8. What the Tower will not do, so do not wait for it

1. **No imagery.** `annotation.artifact` is always `null`. Enabling it
   needs, in order: a shared redaction-state vocabulary, an artifact
   fetch contract, and a per-experiment declaration of whether a visual
   contains source pixels (an edge map is derived; a detection overlay is
   the original frame with boxes on it). None exist.
2. **No baseline and no direction**, so no better/worse verdict. §3.
3. **No end-to-end latency.** It would span two clocks whose relationship
   is an open question, and iOS asked for none.
4. **No per-connection Lab, and no per-connection `source`.** One Tower,
   one Lab, one experiment. Two phones share a run — and for
   `optical_flow` that means frames from two sources diffed against each
   other. `source.clients_connected` makes it visible; closing it needs a
   session-boundary hook the module contract does not have.
7. **An experiment that raises the wrong exception type mid-frame takes
   the Lab down until the Tower restarts.** `ModuleContainer` treats
   anything that is not a `FrameProcessingError` as a module failure, and
   that is terminal by design. The Lab then reports `unavailable`, which
   iOS renders as `.unsupported` — correct, and not something a retry
   fixes. Every registered experiment routes its recoverable failures
   through `FrameProcessingError` to stay out of this case.
5. **No progress during an arm.** `torch.hub` does not report download
   progress. `starting` is all there is, bounded at 120 s.
6. **No HTTP start/pause/stop.** Only the socket. §2.2 of the contract
   says why.

---

## 9. Order of work

1. `towerCartridgeNames` + `supported` + the contract enum. Watch three
   `ProductShellTests` go red — that is the signal, not a nuisance.
2. `TowerExperimentalCVClient` with subscribe + decode + the negative
   tests. At this point the screen shows real experiments and a real run
   in **both** Debug and Release, with `receiving_frames: false` in
   Release. That alone is worth shipping.
3. The `.paused` case.
4. Commands: `cv_lab_start` from an experiment row, plus `stop` / `pause`
   / `resume`. Still no camera involvement — a Debug build with the Home
   Start already pressed will now switch experiments live, which is the
   workflow this replaces, minus one screen.
5. The gated Start control in the CV workspace, doing both halves. This is
   the step that removes the last trip to Home.
6. `frame_error` handling and the run-id discard rule.
