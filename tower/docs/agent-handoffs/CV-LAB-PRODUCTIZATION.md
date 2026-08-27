# Experimental CV Lab — productization lane handoff

**Date:** 2026-08-27
**Lane:** Experimental CV Lab, Tower side.
**Branch:** `cv-lab/productization-v1`
**Worktree:** `C:\Users\tvllo\Projects\Glasses-cv-lab` (a `git worktree` of
`C:\Users\tvllo\Projects\Glasses`; the venv stays in the main tree — see
"Running things" below, the CWD is load-bearing)
**Starting commit:** `6e325f8` — *measure: the shipped detector is blind
below 2% of the frame*
**Ending commit:** `dc37655` — *fix: what three adversarial reviews found*
**Pushed:** yes, `origin/cv-lab/productization-v1`.
**Tree:** clean.

**Not touched:** `ios/`. No Swift was changed and none should have been —
that lane's work is `CV-LAB-IOS-HANDOFF.md`, written to be followed
literally.

---

## 1. What this replaces, and what now exists

Running an experiment used to mean: edit `TOWER_CV_EXPERIMENT`, restart
the Tower, open the Home workspace, press a generic Start, and read an
unlabelled number off a debug panel. Every one of those steps follows from
a single fact — the experiment was decided at process start and nothing on
the wire said which one it was.

The workflow the Tower now supports:

> browse experiments → select one → Start → live results and measurements
> → Pause / Resume → Stop → read the run summary

and every result carries the run, experiment and configuration that
produced it.

| Requirement | Where |
|---|---|
| Enumerate experiments with stable ids and metadata | `status.available[]`, from `tower/cv_lab/catalog.py` |
| Report selected / running | `status.selected`, `status.lifecycle` |
| Select without a restart | `cv_lab_start` |
| Start / Pause / Resume / Stop | `tower/cv_lab/lab.py`, `tower/routes/cv_lab_ws.py` |
| Explicit state, errors, refusals | 7 states, 7 refusal reasons, 6 frame-refusal reasons — all closed sets |
| Preserve `frame_result` | unchanged, plus an additive `cv_lab` provenance block |
| Attach to the shared stream | the Lab sits in the existing module slot; no second camera path, no second transport |
| Remove product dependence on `TOWER_CV_EXPERIMENT` | it is now the startup default only |
| Result provenance | `run_id`, `result_seq`, experiment, backend, device, config, timing basis — on every frame |
| Engineering metrics | ms/frame (mean and max), stage timings, processed/offered/capacity fps, four frame counters |
| Extensible typed envelope | one status document, `MetricKind`-aware aggregation, a declared-and-empty visual slot |
| Debug/Release truthfulness | the read-only half is reachable in Release; `source.receiving_frames` and the two-part rule in the contract §7 |
| Developer path for a new experiment | `guidelines/docs/modules/EXPERIMENTAL-CV.md`, "Adding a new experiment" |
| Benchmarks | `scripts/cv_lab_overhead_benchmark.py`, report in `guidelines/docs/reports/2026-08-27-cv-lab-productization-report.md` |

---

## 2. Architecture, and the decisions behind it

### The module container was NOT changed

`ModuleContainer` still holds exactly one `Module`, constructed once, with
no discovery and no swap path. `04-MODULE-SYSTEM.md` forbids dynamic
discovery before V1.0 and nothing here works around it. What changed is
what is *inside* the one Lab slot — which is what
`tower/modules/experimental_cv.py` has said all along: "one Lab slot, many
experiments".

The alternative considered and rejected was to let the Lab swap MODULES in
the container. It would have required a `replace()` on the shared
container and would have made every experiment switch a module lifecycle
event. Two things killed it: `mark_failed()` is **terminal** by design, so
a weight download timing out would have bricked the Lab; and a module that
cycles READY/ACTIVE several times a minute is not the thing the container
was written to drive.

So the split is: **the container drives the module once, at startup; the
Lab drives what the module is holding.**

### Two planes, deliberately not one

| Plane | Transport | Why |
|---|---|---|
| per-frame result | existing `frame_result` | already the live path, already latency-measured. Duplicating it would mean two answers to "what did the Tower see in that frame" |
| run status / catalog / lifecycle | the existing cartridge result channel, as `experimental_cv`/`status` | subscription, ordering, coalescing, reconnect and slow-consumer handling are already generic and already tested |
| commands | new `cv_lab_*` messages | `tower/results/` is a read-only reporting surface; a mutation there would make the next cartridge's producer a place somebody looks for one |

The status document is built by ONE function and served on three surfaces
(`GET /cv-lab`, `cv_lab_status`, `cartridge_result`). A test asserts they
agree.

### Why a start returns before it has started

`cv_lab_start` validates, publishes `starting`, hands the load to a
background task and returns. Arming `depth` takes seconds — measured 1.05
to 3.46 s on a warm CUDA cache, and up to 120 s on a cold one — and
awaiting that inside a connection's receive loop would stop that socket
reading for minutes. `handoff.md` 13.7 says iOS replaces a connection it
cannot write to for two seconds.

The consequence, which the iOS handoff states twice because it is the
thing most likely to be got wrong: **an arm failure is reported as STATE,
not as a refusal.** There is no `start_failed` error code, because by the
time a load fails the command has already been answered `accepted`.

### Staleness is structural

A run is the unit of provenance and a new experiment is a new run. The old
experiment is **released before** the new run id is published, so there is
no window in which a result computed by one experiment can carry another's
name. Frames arriving in that window are refused with `cv_lab_starting`
rather than answered by the experiment being replaced.

`run_id` is `"<tower_instance_id>-<n>"`, so a client comparing `run_id`
alone is also protected against a reconnect to a *restarted* Tower.

### Concurrency

Three contexts touch the Lab:

- `process()` — the frame path, synchronous, on the event loop, no awaits.
  That is what makes `frame_provenance()` (read by `ws.py` immediately
  after, with no await between) describe the frame it just answered.
- commands — the event loop. `_switching` is a plain bool because
  check-and-set with no await between is atomic there, and an
  `asyncio.Lock` would bind itself to whichever loop touched it first
  (`create_app` uses `asyncio.run`; everything after runs on uvicorn's).
- `status()` — a **worker thread**, because `ResultHub.poll_once` computes
  snapshots with `asyncio.to_thread`. Every state transition and every
  status build therefore happens under a `threading.Lock`.

The frame path deliberately does **not** take that lock. It mutates only
per-run counters, and `frames_offered` is derived from the other three
rather than stored — so the sum invariant holds at every read without
putting a lock on the measured path.

---

## 3. Commits

| Commit | What |
|---|---|
| `43b590d` | feat: the CV Lab stops being an environment variable — the whole implementation, contract document, and 110 tests |
| `3adc484` | fix: a shutdown that waits for the load it cancelled — plus the overhead benchmark and the iOS handoff |
| `ee10594` | test: drive a real Tower, not an in-process shim — `scripts/cv_lab_smoke.py` |
| `dc37655` | fix: what three adversarial reviews found — see §5. 22 findings from the first two, 3 found while fixing them, 10 more from a verification pass over the fixes, 5 investigated and deliberately not changed |

---

## 4. Tests and gates

**Command** (from the worktree's `tower/` directory):

```powershell
C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe -m pytest
```

**Results:**

| Gate | Before | After |
|---|---|---|
| `pytest` (everything) | 1523 passed, 64 skipped | **1669 passed, 64 skipped, 0 failed** |
| `pytest -m slow` (subset of the above) | — | **16 passed, 10 skipped** |
| `test_architecture_boundaries.py` | 20 passed | 20 passed |
| Real-Tower smoke (`scripts/cv_lab_smoke.py`) | — | all checks passed, six times: `edge_detection` and `depth`, before the review fixes, after them, and after the verification pass |

There is no linter, no type checker and no CI in this repository —
`pytest` is the gate, and inside it `test_architecture_boundaries.py` plus
the doc-drift tests do the work a linter would.

### One failure seen once, investigated, and not this change

`test_result_channel_hostile.py::test_the_channel_survives_the_world_vanishing_mid_subscription`
failed in **one** full-suite run out of several and passed in every other,
including four consecutive runs of its own file. It is a World Builder
test and this change does not touch that producer. What was established:

- **Not cross-test pollution.** Its `world` fixture is function-scoped
  over `tmp_path`, so it gets a fresh world every time.
- **Not the heartbeat.** The obvious theory — that the hub's
  poll-on-attach delivers an extra heartbeat envelope and shifts the
  sequence — was tested by forcing that condition three different ways.
  The test passes through all of them.
- **Not this change.** The one thing this branch put in that test's path
  is `json_safe` at the socket. Measured against a real World Builder
  envelope: **byte-identical output, zero type changes.**
- **A mechanism that does fit**, unproven but demonstrated as possible:
  the test calls `world_path.unlink()` while the hub's poll-on-attach may
  still be inside `path.read_text()` **on a worker thread**, and on
  Windows unlinking a file another thread holds open raises
  `PermissionError [WinError 32]` — verified directly. That would be a
  pre-existing race, Windows-specific, and far likelier on a host running
  four lanes' suites at once, which this one was.

Left alone deliberately: it is another lane's test, the fix is theirs to
choose (a bounded retry around the `unlink`, or closing the poll window
before it), and changing it here would be an unrelated edit to a file this
work has no business in.

**New test files** (~145 tests):

| File | Covers |
|---|---|
| `tests/cv_lab_fixtures.py` | shared harness. Nothing sleeps: a start hands its load to a task and the tests await it |
| `tests/test_cv_lab_catalog.py` | the metadata must be TRUE — declared headline matches what the experiment emits, declared units name metrics that exist, only the model-backed ones claim inference |
| `tests/test_cv_lab_lifecycle.py` | selection actually selects; pause/resume/stop; every refusal; a switch that races itself; a failed arm is recoverable |
| `tests/test_cv_lab_protocol.py` | the wire: discovery, three surfaces agreeing, every message, every error, frame provenance, and doc-drift gates |
| `tests/test_cv_lab_bounds.py` | constant memory, the aggregation arithmetic, no imagery, payload bounds |
| `tests/test_cv_lab_hostile.py` | ways the Lab could lie or take the frame path down, plus one test per review finding |
| `tests/test_cv_lab_shutdown.py` | an arm in flight when the Tower stops |

**Doc-drift gates**, modelled on the existing ones: every contract
identifier, lifecycle state, refusal reason, message type, numeric bound
and payload key must appear in `docs/contracts/EXPERIMENTAL-CV-LAB.md`, and
every registered experiment must be named there. A catalog that grows
without the document is a list that becomes a surprise.

**Existing tests changed** (4, all narrowing an assertion that said
"world_builder is the only offer"): `test_result_channel_protocol.py`
(offered/silent sets, the `offered` array in an `unknown_cartridge`
error, the registry-refusal test), `test_result_channel_isolation.py`
(the loop that expected `experimental_cv` to be refused),
`test_main_module_factory.py` (settings moved from the module to the Lab).

---

## 5. What the adversarial reviews found

Two independent reviewers with different lenses — correctness/concurrency
and contract honesty — read the first cut. They found **25 issues between
them**, with three overlapping. Every confirmed finding was fixed and has
a regression test; the ones judged not to be defects are listed with the
reasoning.

### Fixed

| # | Finding | Fix |
|---|---|---|
| 1 | A **stopped run kept counting** refused frames against a frozen `elapsed_s`, so `offered_fps` grew without bound — measured at 45.3 fps from a nine-second window. The Tower's own refusal message says "the last run's figures are final" | `LabRun.is_over` guards every recorder. `source` (Tower-scoped) keeps counting, which is what actually answers "is the phone still streaming?" |
| 2 | **The four frame counters did not sum.** `frames_offered` was incremented on arrival and the outcome afterwards; a status read from the worker thread between them published numbers that did not add up — 2,741 times over one run | `frames_offered` is now **derived** from the other three. True by construction, no lock on the frame path |
| 3 | **The revision changed on every poll** with no frame processed, because `elapsed_s` and the throughput rates are wall-clock derived. `revision_changed` — defined as "news, not a heartbeat" — fired twice a second on an idle Lab | Three `VOLATILE_PATHS` excluded from the hash. `capacity_fps` and `receiving_frames` deliberately are not: they move only when something happened |
| 4 | **NaN sanitisation covered one of three surfaces.** `GET /cv-lab` answered **500** and `cv_lab_status` put a bare `NaN` on the wire — and a poisoned RATE accumulator never recovers, so the message stays undecodable for the session | `json_safe` applied in `CVLab.status()`, where the document is built, so all three surfaces are covered at once |
| 5 | `cv_lab_error(lab_unavailable)` **omitted `status`** while the contract said every error carries it — a conforming decoder would drop the refusal on exactly the Tower it describes | The refusal now carries a hollow document, and `unavailable_payload` carries the **real** contract identifiers rather than `null` (an identifier compared for equality that can never equal anything is worse than none) |
| 6 | `release()` and `_fail_arm()` **never set `ended_at`**, so a dead Lab published a run with `elapsed_s` growing forever | Both end the run. `release()` also clears `_switching`, which had stopped being an invariant |
| 7 | pause/resume/stop on a released Lab answered **`invalid_state`** — "try from another state", of a condition no state change fixes | All four commands share one `_unavailable_refusal()` |
| 8 | **`start_failed` was declared, imported and never emitted.** An async start failure produced no control-socket message at all | The constant is gone and the contract says, twice, that an arm failure arrives as state. A client that sends commands without reading status will sit on `.starting` |
| 9 | `available: true` was decided by **one `torch` probe**. `object_detection` needs `torchvision`; `depth` needs `timm` | `_REQUIRED_MODULES` per experiment. What still cannot be checked is the network, and the contract now says so |
| 10 | `run.experiment` had **two fewer keys** than an `available[]` entry while the document claimed the same shape — one decoder, two shapes | Both go through `_with_availability()` |
| 11 | A deliberate refusal was counted as a **frame processing error**. A Lab paused five minutes reported hundreds of errors, and drove `frames_rejected` non-zero, which `metrics.py` says makes `sampling_stride_avg` untrustworthy | Only an unnamed failure counts as an error. `frames_rejected` still counts refusals, correctly — they ARE missing from the measured numbers |
| 12 | **Unbounded client-controlled echo**: `experiment_id` and `run_id` went into refusal messages at any length, while `request_id` was capped for exactly that reason | `_clip()` at 120 characters on every echoed value, including a failed load's `str(exc)` |
| 13 | The control handler **swallowed `WebSocketDisconnect`** (so the receive loop kept polling a dead socket) and answered internal failures with **silence** | Disconnect re-raised; an internal failure gets a best-effort `cv_lab_error`. Dead `malformed_message()` deleted |
| 14 | An unknown device was reported as the **string `"unknown"`** | `null`. "We do not know which device" and "the device is called None" are different claims |
| 15 | Doc: "byte-identical" across the three surfaces was **false by construction** | Reworded to the claim that holds — same keys, same types, one builder — and the clock-derived fields are named |
| 16 | Doc: fields that are `null` on every fresh Tower were shown as numbers; `null` vs `0.0` was not distinguished | §3.3 now shows the empty-run document explicitly |
| 17 | Doc: `receiving_frames` was sold as the field that keeps Release honest, but it is **Tower-wide** — with two phones it is `true` for a build with no camera | The rule is now two-part: this build is streaming AND `receiving_frames` |
| 18 | Doc: "the largest emits 12" — `optical_flow` declares **14**, so real headroom under the 16 cap is two, not four | Corrected in three places |
| 19 | Doc: a `paused` pointer aimed at a section that never discussed it | Points at the iOS handoff §4 |
| 20 | `unavailable_payload` was unreachable and would have emitted `contract: null` | Now reachable (used by the control plane) and carries real identifiers |
| 21 | `wait_until_armed()`'s docstring claimed a shutdown role it did not have | `shutdown()` (added in `3adc484`) is the one with that role; the docstring says which is which |
| 22 | `lab_busy` said "a start **or stop** is in flight"; only a start can be | Corrected in code and document |

### Found while fixing the above

Three more, none of them from a reviewer:

| Finding | Fix |
|---|---|
| A reviewer noted that "frames are arriving but the transport cannot decode them" was the one condition the status document could not express, and that the answer was a server-side log line — which is precisely what `GET /cv-lab` exists because nobody can see over Tailscale | `source.frames_rejected_before_lab`. With `frames_offered_total` at zero it separates "nothing is streaming" from "something is streaming garbage", which need opposite fixes |
| **The per-experiment extra check (fix #9) was a 22× performance regression.** Checking `find_spec` per experiment per required module on every status build cost 0.65 ms of a 1.25 ms document. `json_safe` was the obvious suspect and was innocent at 0.045 ms | `lru_cache` on the probe. The build is now **0.043 ms** — eight times faster than before either change. Caught by the benchmark that exists for exactly this |
| The payload-size test asserted **< 9 216 B** against a measured worst case of 8 852 B — a 364-byte margin, so the next honest field would have failed it, and a test that fails on correct work teaches people to raise the number without reading it | Bound raised to **16 KB**, with the real figure recorded in the report instead. The arity is guarded separately by `test_the_payload_contains_no_unbounded_list` |

### A third pass, verifying the fixes — and five more

A third reviewer checked the 22 fixes above rather than the original
code. Nine verified outright, one verified with a false comment about
*why* it held, four partial — and the partials shared one root cause
worth naming, because it is the mistake, not the symptom:

> **Sanitising the returned document is not sanitising the Lab.**
> `json_safe` was applied to `CVLab.status()`, which covers what
> `status()` returns and nothing else. It protected neither the frame
> path nor the code that BUILDS the document.

| # | Finding | Fix |
|---|---|---|
| A | **CRITICAL. `frame_result` still put bare `NaN` on the wire** — the highest-volume message on the socket, and a strict decoder rejects the whole message rather than one field. Unprotected: `processing_ms`, `result_value`, `stage_ms.*`, `mean_intensity`, `metrics.*`, `cv_lab.processing_ms` | `json_safe` moved to `_ConnectionSender.send` — the socket itself. The only place that covers every message by construction, including the next one somebody adds. Measured at 0.045 ms for a 7.8 KB document, proportionally less for a ~500 B frame result |
| B | The fix for the swallowed-handler-failure emitted a `cv_lab_error` with **no `status`** — reintroducing the defect two branches from its own fix — and reported a transient bug as `lab_unavailable`, which iOS renders as terminal `.unsupported` | New `internal_error` reason, documented as transient, carrying a best-effort status (the Lab's if it can still produce one, a hollow one if the thing that failed was `status()`) |
| C | **A single malformed message killed a frame-serving connection.** `{"type": {"nested": 1}}` reached `message_type in <frozenset>` and raised `TypeError: unhashable type`, uncaught | `isinstance(message_type, str)` before dispatch. Also closes the same shape on the pre-existing `results_ws` branch |
| D | **One non-finite metric made `status()` RAISE**, taking down all three surfaces — 500 on HTTP, an error on the socket, `snapshot_failed` on the channel — *permanently for the run*, because the accumulator never resets. `int(round(nan))` raises, and `json_safe` wraps the finished dict so it cannot protect a computation inside the builder | `math.isfinite` guard before the conversion |
| E | The contract and the iOS handoff both promised `throughput.processed_fps: 0.0` where the code sends `null`. `time.time()` on Windows has ~15.6 ms granularity, so **11 of 12** `cv_lab_start` replies carried `null` — on the reply to the first command a client ever sends | Documents corrected. A rate over a zero-length window is undefined, not zero, and the code was right |
| F | `protocol_error` echoed the client's `type` verbatim (50 000 characters back) and `frame_error` echoed its `seq` (40 000). `_clip` had been applied only inside `cv_lab/` | Both clipped at the transport |
| G | **`LabRun.stage_ms` was unbounded**, contradicting the module header's "constant memory, by construction". A stage name is whatever an experiment passed to `StageTimer`, with nothing declaring it: a probe grew it to 926 280 entries over 15 438 frames | Bounded at 16, with a reject counter. The most any registered experiment uses is four |
| — | The `frames_offered` invariant held under 634 662 frames of real load, but the comment explaining WHY was false: it claimed a lock the code does not hold, and was atomic only by accident of CPython scheduling | `_run_document` reads the three counters into locals and derives the fourth from those. Atomic by construction, and the comment now says the true reason |
| — | An experiment with `requires_model=True` and no `_REQUIRED_MODULES` entry would be advertised as available | `test_every_model_backed_experiment_declares_what_it_needs` ties the two together |
| — | `_released` was sticky across a hypothetical module reload, and fix #7 made that visible | `load_initial()` clears it. Unreachable today — the container has no reload path — but a one-line honest fix |

### Investigated and NOT changed, with reasons

| Finding | Ruling |
|---|---|
| **An experiment raising a non-`FrameProcessingError` mid-frame bricks the Lab** until restart (`mark_failed()` is terminal) | REAL, and **not fixed**: closing it means giving the shared `ModuleContainer` a way back from FAILED, which is V1.0/V1.1 work and out of scope. What WAS fixed is the claim — `contracts.py` said `STATE_FAILED` covered "a run died" and was recoverable; it does not and it is not. Now documented in Known Limitations |
| **`experiment.release()` runs inline on the event loop** — `torch.cuda.empty_cache()` synchronises with the device | MEASURED rather than assumed: **2.5–4.2 ms**, median ~3 ms, for both model-backed experiments. Comparable to one frame's processing and three orders of magnitude under the 2 s connection-replacement threshold. Inline is fine; the measurement is in the report |
| **Memory growth**, which an intermediate benchmark run reported as +2.84 MB over 1 600 frames | NOT a leak, and the benchmark was the thing at fault. RSS includes OpenCV and numpy pools; two runs over identical work reported −524 KB and +2.84 MB, and a quantity that changes sign is not measuring the thing. `tracemalloc` now runs alongside and attributes Python allocations: **+1.07 B/frame over 4 000 frames**, of which the Lab's own share is 736 bytes *total* — the per-metric accumulators, created once each |
| **`cv_lab_unavailable` frame-refusal reason is unreachable** as a mapped state | Kept: it is the fallback for any state not in the map, and a fallback naming the wrong thing is worse. Documented as a defensive default the transport normally pre-empts |
| **A `request_id` over 64 characters is dropped, not refused** | Kept. Failing a command over a cosmetic field is worse than dropping it. Now documented, in both the contract and the iOS handoff |
| **The frame-path/provenance race** | Traced by the reviewer and found sound: no `await` between `process()` and the provenance read, so on a single-threaded loop nothing can interleave, with any number of streaming connections |

---

## 6. Known limitations

1. **One Lab, shared by every connection.** Two phones feed the same run.
   For `optical_flow` that means frames from two sources diffed against
   each other; its 2 s staleness guard catches the common case. Closing it
   needs a session-boundary hook the module contract does not have.
   `source.clients_connected` makes the condition visible.
2. **`source` is Tower-wide, not per connection.** See fix #17 — the iOS
   rule is two-part because of this.
3. **Last start wins.** Two clients starting different experiments both
   succeed; the second replaces the first and both see it. A bench with
   one slot and two operators has a social problem, not a protocol one.
4. **Three failure modes, two terminal.** A failed *interactive* start is
   recoverable. A failed *startup* experiment and an experiment that
   raises the wrong exception type mid-frame both brick the Lab until the
   Tower restarts. See §5.
5. **No imagery, no baseline, no direction.** All `null`, all with a
   stated reason, all documented. Enabling imagery needs a redaction-state
   vocabulary, an artifact fetch contract, and a per-experiment
   declaration of whether a visual contains source pixels — none of which
   exist on either side.
6. **No arm progress.** `torch.hub` does not report download progress, so
   `starting` is all there is, bounded at 120 s.
7. **Benchmark absolutes were measured under contention.** Four other
   lanes were running suites and corpus benchmarks on this host. The
   relative figures are robust; the absolute milliseconds are not, and
   the report says which is which.
8. **`depth` and `object_detection` were not benchmarked under the Lab.**
   Their per-frame costs are in the V1 report and the Lab's overhead does
   not depend on what the experiment did. `depth` WAS exercised
   end-to-end against a real Tower.

---

## 7. Running things — the CWD is load-bearing

The venv lives in the **main** tree and is gitignored, so it is not in the
worktree. `import tower` resolves from the current working directory, and
from anywhere else it silently resolves to the **main tree's** copy. That
is not hypothetical: a scratch script run from a temp directory imported
the wrong `tower` and reported a missing field that was present.

Always run from the worktree's `tower/` directory:

```powershell
cd C:\Users\tvllo\Projects\Glasses-cv-lab\tower

# tests
C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe -m pytest -q -m "not slow"

# a Tower
C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe -m uvicorn tower.main:app --host 0.0.0.0 --port 8000

# the pre-flight, from another terminal
C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe scripts/cv_lab_smoke.py
C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe scripts/cv_lab_smoke.py --experiment depth

# what it costs
C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe scripts/cv_lab_overhead_benchmark.py
```

`python -m pytest` and `python -c` both put the CWD on `sys.path`;
`python scripts/foo.py` puts the SCRIPT's directory there instead, which
is why the scripts insert the project root themselves.

---

## 8. Exact Mac / operator instructions

### Look at a Tower without a phone

```bash
curl http://100.110.156.55:8000/cartridges | python -m json.tool
curl http://100.110.156.55:8000/cv-lab    | python -m json.tool
```

The second lists every experiment with its headline, unit, provenance,
backend, and whether this Tower can run it. This is the surface that
replaces "read the source to find out what `TOWER_CV_EXPERIMENT` accepts".

### Drive the whole workflow without a phone

From the Tower host, or from the Mac with `websockets` installed:

```bash
python scripts/cv_lab_smoke.py --host 100.110.156.55
python scripts/cv_lab_smoke.py --host 100.110.156.55 --experiment depth
```

It walks browse → start → frames → pause → resume → stop → summary →
refusals → subscription, and prints a check per step. **It sends its own
frames**, so a failure is a Tower problem and never a phone problem. Run
it before the physical test; if it passes and the phone shows nothing, the
fault is between the phone and the Tower.

### Switch experiments by hand

On the existing `/ws` socket, no restart:

```json
{"type": "cv_lab_start",  "experiment_id": "edge_detection"}
{"type": "cv_lab_status"}
{"type": "cv_lab_pause",  "run_id": "<from lifecycle.run_id>"}
{"type": "cv_lab_resume", "run_id": "..."}
{"type": "cv_lab_stop",   "run_id": "..."}
```

### iOS

`CV-LAB-IOS-HANDOFF.md`. Two lines of it are the whole gate: add
`"experimental-cv"` to `TowerCapabilities.towerCartridgeNames`, and add
the contract identifier to `supported`. Without the first, the Tower can
offer the contract all it likes and the screen still says "Nothing yet".

---

## 9. Physical validation plan

Nothing here has been in front of real glasses. The Tower side is
exercised end-to-end against a real uvicorn over a real socket, twice,
including a model-backed hot switch on CUDA — but the frames were
synthetic.

**Pre-flight** (no glasses, five minutes):

1. Start the Tower with `.env` as usual.
2. `python scripts/cv_lab_smoke.py` → expect "all checks passed".
3. `python scripts/cv_lab_smoke.py --experiment depth` → same, plus an
   arm time in the log. On a cold cache this downloads 119 MB.

If either fails, stop. Nothing below will work.

**With glasses** — the two experiments chosen because their headline
numbers cannot be confused for one another:

| Step | Do | Expect |
|---|---|---|
| 1 | Start the Tower. `curl /cv-lab` | `lifecycle.state: "running"`, `selected: "baseline"`, `origin: "startup_default"`, `source.receiving_frames: false` |
| 2 | Connect the phone, press Start on Home (Debug build) | `receiving_frames: true`, `frames_processed` climbing, `mean_intensity` between roughly 40 and 200 depending on the light |
| 3 | Point at a blank wall, then at a cluttered desk | `mean_intensity` moves with brightness and **not** with clutter. That is the control |
| 4 | Send `cv_lab_start` for `edge_detection` | a new `run_id`; at most one or two frames refused `cv_lab_starting`; then `result_label: "edge_density"` |
| 5 | Blank wall vs cluttered desk again | **`edge_density` roughly 0.01–0.03 on the wall and 0.10–0.25 on the desk.** This is the visibly distinct pair: a ~10x swing on the same scene change that barely moved `mean_intensity` |
| 6 | `cv_lab_pause` | frames answered `frame_error` / `cv_lab_paused`. `frames_processed` and every metric stop moving; **`frames_refused` keeps climbing** — a paused run is not over, and that counter is how you see the phone is still sending. `receiving_frames` stays `true` |
| 7 | `cv_lab_resume`, then `cv_lab_stop` | results resume; then `ended_at` set and **every** figure under `run` frozen, including `frames_refused`, while `source.frames_offered_total` keeps climbing. That split is the difference between paused and stopped |
| 8 | Walk out of range for 10 s | `receiving_frames: false` with the run intact |
| 9 | `cv_lab_start` for `depth` | armed within a few seconds on a warm cache; `mean_relative_depth` in the hundreds, every metric `provenance: "inferred"`, `runtime.device: "cuda:0"` |

**What would falsify the work:** a `frame_result` whose
`cv_lab.experiment_id` disagrees with its `result_label`; a run whose
counters move after a stop; `receiving_frames: true` with the phone
switched off; a switch that leaves the previous experiment running.

**Not covered by any of this:** real-link latency and bandwidth over
Tailscale, thermal behaviour on the glasses, and how the numbers actually
distribute in a real room. The Lab exists to answer that last one; this
work is what makes asking it a button press.

---

## 10. Leftovers

None in the tree. Three things a next lane may want:

1. **The iOS side.** `CV-LAB-IOS-HANDOFF.md`, ordered in §9 of that
   document so each step is shippable on its own.
2. **A way back from a module FAILED state**, which would make the
   third failure mode in §6.4 recoverable. Shared module system work.
3. **The visual output slot.** Declared, empty, with the three
   prerequisites named in the contract §5. Do not fill it without them.

Two smaller things a reviewer found that are **outside** this change and
were left alone rather than fixed opportunistically:

- `tower/frames.py` echoes a client-supplied `format` string into its
  error message unclipped — a 40 000-character `format` produces a
  40 000-character reply. Same class as the echoes clipped in
  `routes/ws.py`, but it is another module's validation and predates this
  work.
- `ModuleContainer` has no way back from FAILED, which is what makes the
  third failure mode in §6.4 terminal. Deliberate in the shared module
  system, and the place to change it is there rather than here.
