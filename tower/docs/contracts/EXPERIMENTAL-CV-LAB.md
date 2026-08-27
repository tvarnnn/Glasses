# Experimental CV Lab — the Tower ↔ iOS contract

**Status:** implemented on Tower, offered on the wire.
**Contracts:**

| What | Identifier |
|---|---|
| Status document | `experimental_cv.status/2026-08-27` |
| Control vocabulary | `experimental_cv.control/2026-08-27` |
| `frame_result` provenance block | `experimental_cv.frame_result/2026-08-27` |
| Envelope (shared) | `cartridge_results.envelope/2026-08-23` |

Cartridge name on the wire: `experimental_cv`. Result type: `status`.
Every timestamp: `tower-receipt`.

All four identifiers are **opaque and compared for equality only**. Do not
parse them, order them, or range over them. Three of them because the CV
Lab has three surfaces that version independently — a client may implement
the read-only half and never send a command, which is exactly what a
Release iOS build with no camera should do.

---

## 0. What this replaces

Choosing an experiment used to mean: edit `TOWER_CV_EXPERIMENT`, restart
the Tower, go to the Home screen, press a generic Start, and read an
unlabelled number off a debug panel. Every step of that follows from one
fact — the experiment was decided at process start and nothing on the wire
said which one it was.

Now:

- the Tower **enumerates** its experiments, with stable ids and metadata;
- a client **selects and starts** one with no restart;
- **pause, resume and stop** are requests with legible refusals;
- **every result names the run, the experiment and the configuration that
  produced it**, so a result from a previous experiment cannot be read as
  a result from the current one;
- the Tower reports **whether frames are actually arriving**, which is
  what "I pressed Start and nothing happened" is really asking.

`TOWER_CV_EXPERIMENT` still exists. It is now the **startup default** and
nothing more: what this Tower arms at boot so that a client which knows
nothing about the CV Lab still gets a `frame_result` for every frame,
exactly as before.

---

## 1. The three surfaces

| Surface | Direction | Carries |
|---|---|---|
| `frame_result` (existing) | Tower → client | the per-frame answer, plus a `cv_lab` provenance block |
| `cv_lab_*` messages | both | the control plane: status, start, pause, resume, stop |
| `cartridge_result` on the result channel | Tower → client | the same status document, pushed |

**The per-frame path is unchanged and was deliberately not replaced.** It
is the live path, it is already latency-measured, and duplicating it would
have meant two answers to "what did the Tower see in that frame". What
changed is that the answer now says who produced it.

**Commands never travel on the result channel.** `tower/results/` is a
read-only reporting surface; putting a mutation on it would make the next
cartridge's producer a place where somebody looks for one.

---

## 2. Discovery

### 2.1 Is the cartridge offered?

`experimental_cv` now appears in the capability declaration
(`GET /cartridges`, and `{"type": "cartridges"}` on the socket) alongside
`world_builder`:

```json
{
  "cartridge": "experimental_cv",
  "result_type": "status",
  "contract": "experimental_cv.status/2026-08-27",
  "available": true,
  "unavailable_reason": null,
  "snapshot_only": true
}
```

`available: false` with a reason means this build speaks the contract but
cannot serve it — the Lab module failed, or this Tower runs without one.
That is iOS's third state ("offered, implemented, unreachable → connect"),
never its first ("the Tower says nothing → not built yet").

### 2.2 What experiments exist?

Three surfaces, one document, byte-identical:

```
GET /cv-lab                          → {"contract", "control_contract", "status"}
{"type": "cv_lab_status"}            → {"type": "cv_lab_status", ..., "status"}
result_subscribe experimental_cv/status → cartridge_result.payload == the same "status"
```

A test asserts the three agree. `GET /cv-lab` exists for the operator with
a terminal; the Tower is normally driven over Tailscale where a
server-side log line is invisible.

There is **no HTTP surface for start, pause or stop**. A command needs the
connection it was issued on to still be there when the outcome arrives — a
start may take two minutes to arm a model — and a request/response route
would have to either block for that or lie about having finished.

---

## 3. The status document

One document answers every question about the Lab. It is a **complete
snapshot**; there are no deltas to merge.

```json
{
  "contract": "experimental_cv.status/2026-08-27",
  "control_contract": "experimental_cv.control/2026-08-27",
  "frame_result_contract": "experimental_cv.frame_result/2026-08-27",
  "tower_instance_id": "2a5b04b1b77c",
  "time_basis": "tower-receipt",
  "lifecycle": {"state": "running", "reason": null,
                "since": 1787810078.29, "run_id": "2a5b04b1b77c-1"},
  "available": [ /* the catalog, §3.2 */ ],
  "selected": "edge_detection",
  "default_experiment": "baseline",
  "device_requested": "auto",
  "run": { /* §3.3 */ },
  "source": { /* §3.5 */ }
}
```

### 3.1 `lifecycle.state` — seven values, and how iOS renders them

| Tower state | Means | iOS `ExperimentalCVState` |
|---|---|---|
| `unavailable` | this Tower cannot run experiments at all | `.unsupported(reason:)` |
| `idle` | nothing armed; a start would be accepted | `.idle(available:)` |
| `starting` | a start was accepted, the experiment is loading | `.starting(experiment)` |
| `running` | processing frames | `.running(run)` |
| `paused` | armed and deliberately not processing | **`.paused(run)` — a new case, see §8** |
| `stopped` | the last run ended; its figures are final | `.completed(run)` |
| `failed` | the last start failed; another may be sent | `.failed(CartridgeFailure)` |

`stopped` rather than `completed` on the wire, deliberately. A bench run
does not complete; it is stopped by a person. The Tower says what happened
and iOS renders it with the case its state machine has.

`paused` and `stopped` are different states because the difference is
real: a paused run keeps the experiment **loaded**, so resuming a `depth`
run costs nothing, while a stopped one pays the model load again.

`lifecycle.reason` is prose for a person, present only when the state
needs explaining. `null` is not "no reason" — it is "the state speaks for
itself".

`lifecycle.since` is when the Lab entered this state.

`lifecycle.run_id` is the current run, or `null`.

### 3.2 `available` — the catalog

One entry per registered experiment, sorted by `id`. **iOS holds no list
of its own**: `docs/modules/EXPERIMENTAL-CV.md` calls its candidate list
"intentionally broad", so any subset hard-coded on the phone would be the
app asserting that those experiments exist.

```json
{
  "id": "edge_detection",
  "name": "Edge detection",
  "summary": "Fraction of pixels Canny calls an edge, after a Gaussian blur. ...",
  "provenance": "measured",
  "headline_label": "edge_density",
  "headline_unit": "fraction",
  "stateful": false,
  "requires_model": false,
  "backend": "opencv",
  "annotation_metric": null,
  "available": true,
  "unavailable_reason": null
}
```

`id`, `name` and `summary` are the three iOS reads. Everything else is
additive; a client that ignores all of it still has a working picker.

- `provenance` — `measured` or `inferred`. Not a hint. See §4.
- `headline_label` / `headline_unit` — what this will measure, and in
  what. A `null` unit means the quantity genuinely has none and is
  rendered **bare** (`IOS-to-Tower.md` 0.5: metric is not metres). Depth
  is the case: MiDaS-small emits relative inverse depth on an arbitrary
  scale.
- `stateful` — carries state across frames, so its first frame is not
  like its hundredth.
- `requires_model` — needs the optional `[ml]` extra. A start may take a
  hundred times longer than a cheap experiment's.
- `backend` — `opencv` or `torch`.
- `annotation_metric` — the metric that is a count of things found in a
  frame, or `null`. Only `object_detection` has one.
- `available` / `unavailable_reason` — false when `requires_model` and
  torch is not installed on this Tower. Starting it is refused, in
  advance, with a reason.

The eight registered today: `baseline`, `depth`, `edge_detection`,
`feature_detection`, `frame_quality`, `object_detection`, `optical_flow`,
`redaction_impact`.

### 3.3 `run` — what the current or last run measured

`null` when no run exists. Otherwise:

```json
{
  "run_id": "2a5b04b1b77c-2",
  "experiment": { /* the same shape as an `available` entry */ },
  "origin": "client_request",
  "started_at": 1787810180.1, "ended_at": null, "elapsed_s": 14.2,
  "runtime": {"backend": "torch", "device": "cuda:0",
              "device_requested": "auto", "model": "MiDaS_small"},
  "frames_offered": 12, "frames_processed": 12,
  "frames_refused": 0, "frames_failed": 0,
  "metrics": [ /* §4 */ ], "metrics_omitted": 0,
  "unclassified_metrics": [],
  "annotation": { /* §5 */ },
  "timings": { /* §6 */ },
  "throughput": { /* §6 */ }
}
```

`origin` is `client_request` or `startup_default`. **`startup_default`
means nobody asked for this run** — the Tower armed it at boot. Reported
so that "the Lab is running" never reads as "somebody chose this".

`runtime` is what the experiment says it actually loaded, and is empty for
an experiment that holds nothing. Its keys are the experiment's own; do
not switch on them. It exists because `TOWER_CV_DEVICE=auto` is a
**request** and the Tower decides the answer — a run labelled "auto" has
not said whether it used the GPU, and a CPU figure with a GPU label on it
is a real failure this closes.

**The four frame counters are disjoint and sum to `frames_offered`.** That
is what makes a dead start diagnosable:

| Reading | Means |
|---|---|
| `frames_offered == 0` | nothing is reaching the Lab. The stream is not running, or this Tower is not receiving it |
| `frames_offered > 0`, `frames_processed == 0` | frames are arriving and the Lab is refusing them. Check `lifecycle.state` |
| `frames_failed > 0` | the experiment raised on a frame. It stays armed; those frames produced nothing |

Frames rejected by wire validation before they ever reach the Lab are
**not** counted here — they never reached it. They appear in the Tower's
own session summary as `frames_rejected`.

`metrics_omitted` is how many aggregate metrics did not fit the 16-row
bound. Reported rather than silently truncated.

`unclassified_metrics` names any metric an experiment emitted without
declaring how it combines across frames. Empty is the only correct value
and a test enforces it for every registered experiment; this is what the
wire says if one ever reaches production anyway.

### 3.4 Switching discards the previous run

Starting a different experiment mints a **new** run and the previous run's
figures leave the document. That is the point: a run is the unit of
provenance, and keeping an old summary beside a new one is how a number
from the wrong experiment ends up on a screen. Press **Stop** to keep a
run's figures readable; they stay until the next start.

### 3.5 `source` — is anything feeding this Lab

```json
{"clients_connected": 1, "receiving_frames": true,
 "last_frame_at": 1787810180.83, "frames_offered_total": 7,
 "idle_after_s": 5.0}
```

`receiving_frames` is `last_frame_at` within `idle_after_s`. Five seconds,
because the current iOS sender forwards roughly one frame in thirty of a
~24 fps capture — about 0.8 frames per second observed — so five seconds
is about four missed frames: long enough never to flicker during normal
streaming, short enough to show up while a person is still standing there.

`clients_connected` is `null` when this Tower cannot report it.

**This is the field that keeps a Release build honest.** See §7.

---

## 4. Metrics, and provenance on every one

```json
{"label": "edge_density", "value": 0.0413, "unit": "fraction",
 "aggregation": "rate", "frames": 6, "provenance": "measured",
 "confidence": null, "headline": true, "varied": false,
 "baseline": null, "higher_is_better": null}
```

- `label` — the Tower's word, displayed verbatim. **iOS matches on no
  metric name, ever.**
- `value` — `null` is a real answer meaning "this metric has no meaningful
  aggregate", never "zero". See `aggregation`.
- `unit` — `null` means the quantity has no unit and is rendered bare.
- `provenance` — **required, never omitted.** `measured` or `inferred`.
  `EXPERIMENTAL-CV.md` requires that experiment output be distinguished
  from measured sensor fact, and iOS makes this a non-optional field so
  that whoever decodes the reply has to answer it. A `constant`-kind
  metric is always `measured` even when the experiment as a whole infers:
  a configured threshold or an image dimension is a fact about how this
  Tower is set up, not a model's opinion.
- `confidence` — always `null`. The Tower has no calibrated confidence for
  any of these, and a number here would be invented.
- `headline` — the experiment's single most important number, always
  first in the list.
- `aggregation` — how this number was combined across frames:

  | Value | Combined by | Because |
  |---|---|---|
  | `rate` | mean | summing a fraction is nonsense |
  | `count` | sum | including a 0/1 flag, whose sum is "how many frames it fired on" |
  | `constant` | the value observed | neither a sum nor a mean of an image width means anything |
  | `unaggregated` | **nothing** — `value` is `null` | `dominant_direction_deg` is circular: the mean of 179° and −179° is 0°, the one direction neither frame was moving in |

- `varied` — a `constant` that was not constant. Its `value` is `null` and
  this says why, so `null` is not read as "never observed".
- `baseline` and `higher_is_better` — **always `null`**, and this is not an
  omission. iOS renders a better/worse verdict only when **both** arrive,
  and the Lab holds no reference run to compare against. A comparison
  against nothing is the "declaring an approach 'better' without a
  measurement" that `EXPERIMENTAL-CV.md` rules out. Offline corpus
  comparison is `scripts/cv_lab_benchmark.py`, and it is not this channel.

---

## 5. Annotations and imagery

```json
{"count": 3, "count_unavailable_reason": null,
 "artifact": null,
 "artifact_unavailable_reason": "this Tower serves no imagery for CV Lab results. ..."}
```

`count` is `null` when the experiment produces no annotation count and a
**number** when it does, **including zero**. `0` is a real result meaning
"found nothing" and must not merge with "did not say".

`artifact` is **always `null` in this contract**, and the reason is not
that it was forgotten:

- `IOS-to-Tower.md` §5 withholds any image whose treatment was not stated,
  with no lenient default: *"An unstated treatment is not a treatment."*
- The same section states that artifact fetching itself is **UNKNOWN** —
  iOS *"holds no URL, no id format, and no bytes, because inventing a
  fetch scheme would be exactly the fabricated contract this work refuses
  to produce."*

Serving an inline image here would be the Tower inventing that scheme
unilaterally, and an experiment gets no privacy exemption for being a
debug surface. The field exists so that a later contract adds a payload
where a `null` is, rather than adding a field.

**To enable it later**, in this order: (1) a redaction-state vocabulary
shared with §5 of `IOS-to-Tower.md`; (2) an artifact fetch contract; (3)
per-experiment declaration of whether its visual output contains source
pixels — an edge map or a depth map is derived, a detection overlay is the
original frame with boxes on it, and those are not the same privacy
object. None of the three exist today.

---

## 6. Timing and throughput

```json
"timings": {"processing_ms": 1.12, "processing_ms_max": 5.19,
            "stage_ms": {"blur": 0.80, "canny": 0.15, "decode": 0.16,
                         "summarize": 0.01},
            "observed_at": 1787810180.83, "time_basis": "tower-receipt"}
"throughput": {"processed_fps": 0.79, "offered_fps": 0.79,
               "capacity_fps": 892.83}
```

`processing_ms` is the **mean** over the run and `processing_ms_max` the
worst frame — the Tower measuring itself, the same quantity
`frame_result.processing_ms` carries per frame.

`stage_ms` is an **open map**: its keys are the experiment's own stage
names (`decode`, `blur`, `canny`, `summarize`, …) and a client must not
switch on them. Same for `runtime` in §3.3.

`observed_at` is when the Tower last produced a result for this run.
**There is no capture timestamp anywhere on the wire** — `tower/frames.py`
carries no time field — so this is when the Tower saw a frame, never when
the glasses did. That is why `time_basis` is stated on every timing block.

**There is deliberately no end-to-end latency field.** It would be
computed across two clocks whose relationship is an open question in
`07-PLATFORM-CONSTRAINTS.md`, and a number derived from two unrelated
clocks is not a latency. iOS asked for none.

`processed_fps` and `offered_fps` are per second of run wall-clock.
`capacity_fps` is `1000 / processing_ms` — how fast the Lab could go if
frames never stopped arriving. Read together they say whether the Lab or
the link is the limit: the current sender forwards roughly one frame in
thirty, so `processed_fps` is normally bounded by what arrives, not by
what the Lab can do.

---

## 7. Debug, Release, and not claiming what cannot arrive

The iOS camera path is `#if DEBUG` — the DAT capture, the JPEG encode, the
frames→Tower bridge and both stream-lifecycle bridges. **A Release build
has no camera, sends no frame, and therefore receives no `frame_result`.**
That predates this work and is not fixed by it.

What this contract does about it:

1. **The read-only half is reachable in Release.** The capability
   declaration, the result channel and the status document are not gated
   on iOS and do not depend on frames. A Release build can enumerate
   experiments and read the Lab's state truthfully.
2. **The Tower reports whether frames are arriving** (`source`, §3.5). A
   Release build that showed "running" with no frames would be claiming
   something it cannot receive; `receiving_frames: false` and
   `frames_offered: 0` are what stop it.
3. **The Tower never claims a client's stream is running.** It reports
   what it observed. `lifecycle.state: running` means *the Lab is armed
   and processing whatever arrives*, not *frames are arriving*. Those are
   two facts and the document keeps them apart.

The rule for iOS: **`.running` may only be shown as live when
`source.receiving_frames` is true.** Otherwise show the run as armed and
waiting for a stream, and in Release say the build has no camera. Never
render a Start control in a configuration that has no `startCameraSession`
to call.

---

## 8. Control messages

All are plain WebSocket JSON on the existing `/ws` socket. Every reply
carries the **whole status document**, so a client is never left guessing
what state it is now in.

### Client → Tower

| Type | Fields | Effect |
|---|---|---|
| `cv_lab_status` | `request_id?` | read the document |
| `cv_lab_start` | `experiment_id`, `request_id?` | select **and** arm. Replaces whatever was running |
| `cv_lab_pause` | `run_id?`, `request_id?` | stop processing; keep the experiment loaded |
| `cv_lab_resume` | `run_id?`, `request_id?` | resume processing |
| `cv_lab_stop` | `run_id?`, `request_id?` | end the run, release the experiment, keep the figures |

There is **no separate select message**. Selection without arming is a
state nobody needs on the wire — the phone holds the choice until Start,
and iOS's `run(_ experiment:)` is already one call.

`run_id`, when sent, is checked: a command naming a run that is no longer
current is refused with `stale_run` rather than applied to whichever run
is. Send it whenever the button was drawn against a run you have seen.

`request_id` is an opaque token of at most 64 characters, echoed back. A
client that sends none still gets a complete reply; a client that sends
one can match a reply to the button that was pressed, which matters when
two commands are in flight and one is refused.

### Tower → client

**`cv_lab_status`** — the document. `accepted_command` is present only
when this is the reply to a command, which is how a pushed status is told
from an answer.

```json
{"type": "cv_lab_status",
 "control_contract": "experimental_cv.control/2026-08-27",
 "contract": "experimental_cv.status/2026-08-27",
 "request_id": "req-1", "accepted_command": "cv_lab_start",
 "status": { ... }}
```

**`cv_lab_error`** — a refusal. **Every one of them means the request did
not take effect.** There is no partial application.

| `reason` | When | Extra fields |
|---|---|---|
| `malformed_request` | `experiment_id` or `run_id` missing or wrong-typed | `command` |
| `unknown_experiment` | no experiment with that id on this Tower | `available` (array of ids) |
| `experiment_unavailable` | the experiment exists but this Tower cannot run it (the `[ml]` extra is absent) | `experiment_id` |
| `lab_busy` | a start or stop is already in flight | — |
| `invalid_state` | the command does not apply from the current state (resume when idle, pause when stopped) | — |
| `stale_run` | the `run_id` named is not the current one | `current_run_id` |
| `lab_unavailable` | this Tower runs no CV Lab, or its module failed | — |
| `start_failed` | accepted, then the experiment failed to load | — |

Every `cv_lab_error` also carries `control_contract`, `message` (prose for
a person), and `status` (the document, unchanged).

**Refused, never queued.** `lab_busy` exists because the Lab holds one
experiment: queueing a second request behind the first would let two
clients each believe they chose what is running.

### The frame path during a switch

While `lifecycle.state` is not `running`, a frame is answered with
`frame_error` rather than silence:

| `reason` | State |
|---|---|
| `cv_lab_idle` | `idle` |
| `cv_lab_starting` | `starting` |
| `cv_lab_paused` | `paused` |
| `cv_lab_stopped` | `stopped` |
| `cv_lab_failed` | `failed` |
| `cv_lab_unavailable` | `unavailable` |

These sit alongside the transport's existing `invalid_frame`,
`frame_skipped` and `module_unavailable`. They are refusals, not failures:
the module stays ACTIVE and the next frame is accepted the moment the Lab
is running again. The `message` beside each one says what to send.

---

## 9. `frame_result` provenance

Additive. Everything that was on `frame_result` before is still there,
unchanged, in the same place.

```json
{"type": "frame_result", "seq": 30, "processing_ms": 1.4,
 "result_value": 0.041, "result_label": "edge_density",
 "stage_ms": {...},
 "cv_lab": {
   "contract": "experimental_cv.frame_result/2026-08-27",
   "tower_instance_id": "2a5b04b1b77c",
   "run_id": "2a5b04b1b77c-2",
   "result_seq": 41,
   "experiment_id": "edge_detection",
   "experiment_name": "Edge detection",
   "provenance": "measured",
   "backend": "opencv",
   "device": null,
   "device_requested": "auto",
   "result_label": "edge_density",
   "processing_ms": 1.4,
   "tower_received_at": 1787810180.83,
   "time_basis": "tower-receipt"
 }}
```

`result_seq` is dense within the run, starting at 1. **The wire `seq` is
the phone's capture index and skips by design** — the current sender
forwards one frame in thirty — so it cannot be used to order results.

### The staleness rule, and why it is one line

> **Discard any `frame_result` whose `cv_lab.run_id` is not the run you
> are watching.**

The Tower makes this structural rather than checked: a new experiment is a
new run, and the old experiment is released **before** the new run id is
published, so there is no window in which a result computed by one
experiment can carry another's name. The client-side rule exists for the
case the Tower cannot cover — a reconnect to a **restarted** Tower, which
starts counting runs again. `tower_instance_id` is part of every run id
for that reason, so comparing `run_id` alone is sufficient.

---

## 10. Limits and bounds

| Bound | Value | Why |
|---|---|---|
| Metrics reported per run | **16** | the largest registered experiment emits 14; this bounds a future one, and says how many it dropped |
| Metric names tracked per run | the experiment's own declared set — **12** at its largest | a name is filed only if the experiment declared it. There is no separate cap, because one would never fire |
| Unclassified metric names reported | **8** | a name list a producer controls must not grow without limit |
| `request_id` length | **64** characters | it is echoed onto the wire |
| Status document size | measured **< 9 KB** worst case (`optical_flow`, 14 metrics + the 8-experiment catalog) | a fixed arity with no unbounded list |
| Stream-idle threshold | **5.0 s** | ~4 missed frames at the sender's observed 0.8 fps |
| Arm timeout | **120 s** | the same bound and the same reason as the module container's load timeout: 119 MB of MiDaS weights does not fit a 10 s bound on any ordinary link |

**Everything a run accumulates is O(1) in frames.** A mean is a running
total and a count; a maximum is a maximum. There is no frame list, no
metric history and no sample buffer — `handoff.md` 9.3 says a
`stream_stop` may never arrive, so "for the length of a run" means "for as
long as the Tower is up".

**Cost on the wire.** While running, the status document is re-sent when
its revision changes (a frame was processed) or every 2 s otherwise, so at
the sender's observed ~0.8 fps a subscriber sees roughly 1.3 documents per
second — about 11 KB/s, against ~16 KB/s for the frame stream itself.
Unsubscribe when the CV Lab screen is not visible.

---

## 11. Known limitations

1. **One Lab, shared by every connection.** The module container holds one
   module and the Lab holds one experiment. Two phones streaming to one
   Tower feed the *same* run, and for a stateful experiment
   (`optical_flow`) that means frames from two sources are diffed against
   each other. `optical_flow` has a 2 s staleness guard that catches the
   common case; the residual needs a session-boundary hook on the module
   contract, which is blocked V1.0/V1.1 work. `source.clients_connected`
   is reported so the condition is at least visible.
2. **Last start wins.** Two clients starting different experiments in
   sequence both succeed; the second replaces the first, and both see it
   in the pushed status. There is no ownership model, because a bench with
   one slot and two operators has a social problem, not a protocol one.
3. **A failed STARTUP experiment is terminal.** If `TOWER_CV_EXPERIMENT`
   names something unknown, or its load fails at boot, the module is
   marked FAILED — which is terminal by design — and the Lab reports
   `unavailable` until the Tower restarts. A failed *interactive* start is
   recoverable: the Lab goes `failed` and another start may be sent.
4. **No artifact, no baseline, no direction.** See §4 and §5. All three
   are `null` with a stated reason rather than omitted.
5. **No cancellation of an in-flight arm from the client's point of
   view**, beyond `cv_lab_stop`, which does cancel it. There is no way to
   ask "how far through the download are you"; torch.hub does not report
   it.

---

## 12. Where the code is

| Concern | File |
|---|---|
| Identifiers, states, refusal reasons, bounds | `tower/cv_lab/contracts.py` |
| The catalog | `tower/cv_lab/catalog.py` |
| One run's identity and measurements | `tower/cv_lab/run.py` |
| Lifecycle, selection, the frame path, the document | `tower/cv_lab/lab.py` |
| The module that holds the Lab | `tower/modules/experimental_cv.py` |
| Experiment registration and metadata | `tower/experiments/__init__.py` |
| Control messages | `tower/routes/cv_lab_ws.py` |
| `GET /cv-lab` | `tower/routes/cv_lab.py` |
| The result-channel producer | `tower/results/experimental_cv.py` |
| The capability declaration | `tower/results/registry.py` |
| `frame_result` provenance on the wire | `tower/routes/ws.py` |

Adding an experiment: `guidelines/docs/modules/EXPERIMENTAL-CV.md`, "Adding
a new experiment".

---

## 13. Changelog

### `experimental_cv.status/2026-08-27`, `.control/2026-08-27`, `.frame_result/2026-08-27`

First offer. Before this, `experimental_cv` was listed in the declaration's
`not_offered` with the reason *"results already reach the client on
`frame_result`; a typed contract awaits the experiment-registry and
provenance work described in IOS-to-Tower.md 2.1–2.3"*. That is the work
this contract is.
