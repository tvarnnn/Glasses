# Scene Understanding and Document Memory — the lane report

**Date:** 2026-08-27
**Lane:** Tower / cartridges
**Started from:** `6e325f8` on `integration/world-builder-lifecycle-v1`
**Ended at:** `8faf774` on `integration/document-scene-cartridges-v1`
**Worktree:** `C:\Users\tvllo\Projects\Glasses-cartridges`
**Pushed:** yes, to `origin/integration/document-scene-cartridges-v1`

---

## 0. What changed, in one paragraph

Two cartridges had working Tower code that no product could reach.
`/cartridges` reported both `not_offered`, which iOS renders identically
to a cartridge nobody has written — the most expensive possible wrong
answer, because it invites a person to wait for work that is already
done. Both now appear in the declaration with dated contracts, are
unavailable until configured, and carry their own limits as data rather
than as documentation somebody has to have read.

**Neither got better to earn that.** Document Memory's page detector
still fires on essentially nothing at the geometry the glasses deliver;
Scene Understanding's counts are still undercounts against an oracle that
shares its training data. What changed is that those facts are now on the
wire, in fields a client can switch on, instead of in a research document
a client cannot read.

---

## 1. The starting position, verified against HEAD

Both cartridges' briefs described them as "backend code exists but the
product cannot use it". That was accurate, and the reasons were
different:

| | Scene Understanding | Document Memory |
|---|---|---|
| Why not offered | live in-process state, persists nothing by design, so the journal-follower pattern that gave Object Memory a route was unavailable | implemented and queryable by CLI, no typed contract |
| What existed | `SceneEngine.observe()`, a tracker, a query layer, refusals with measurements behind them | detect → dwell → keyframe → OCR → store → BM25 retrieval, 145 tests |
| What did not | start/stop, any off-loop execution, any state accessor, any non-identifying projection | start/stop, any session concept, any wire contract, retention that ran anywhere but at CLI exit |

Three parallel audits established that before any code was written; a
fourth read the prior research so the contracts could be built on
measurements rather than on intent.

---

## 2. Architecture

### 2.1 One live-session base, two cartridges

`tower/live_session.py` is new and is the load-bearing piece. Both
cartridges need the same three properties around an engine that is
synchronous, blocking and expensive, and the properties are subtle enough
that two implementations would have diverged where nobody would look:

1. **Nothing expensive on the event loop.** `offer_frame` runs inline in
   the connection handler and may only replace a slot and signal.
   Measured at **0.0099 ms median, 0.035 ms p95** over 5,204 frames.
2. **One slot, newest wins, and the drops are on the wire.** A backlog
   answers "what is around me now" with the past. A silently dropped
   frame is indistinguishable from a quiet room, which is why
   `frames_skipped` is a published field and not a log line.
3. **An abandoned load must not install itself.** `stop()` during a model
   load cannot kill the loading thread. It closes a `LoadInvalidation`
   latch — the module container's own guard, reused — and the worker
   checks it before publishing, so a load that finishes after its session
   stopped releases its own model.

`SceneLive` and `DocumentLive` are thin subclasses. The differences
between them are the differences between the cartridges, and each is
stated where it lives:

- **Scene's Stop DISCARDS the scene.** A scene held past the end of a
  session is a claim about a room the wearer has left.
- **Document's Stop KEEPS what it recorded**, and flushes a dwell in
  progress rather than dropping it.
- **Scene follows the stream by default; Document does not.** Document
  Memory writes to disk, and a session that persists gets an explicit
  start.

### 2.2 `main.py` still names neither cartridge

`tower/cartridge_runtime.py` is the one place in the web process that
knows their names. `main.py` asks it a generic question — "which live
cartridges does this configuration enable?" — exactly as it already asks
`tower.results` for a hub.

That is not a dodge around
`test_scene_understanding_is_not_registered_as_a_production_module`. The
second assertion of that test and its Document Memory twin — that
`tower/modules/scene.py` and `tower/modules/document_memory.py` do not
exist — survives verbatim and untouched. Neither cartridge is a `Module`,
neither is in the `ModuleContainer`, and neither runs on the event loop.
What changed is that the web process can hand them frames, which is
precisely the blocker `registry.py` named: *"nothing in the web process
observes it, so there is no state for this channel to read."*

### 2.3 A second observer list

Live cartridges go on `app.state.frame_consumers`, **not**
`frame_observers`. That list is the dataset recorder's and is shaped
around capture lineage: it mints capture ids, `/health` reports on
anything in it, and `ws.py` calls `capture_dir()` on its members
*outside* the per-observer `try`. A cartridge there would have made
`/health` claim frames were being recorded when they were being counted
and dropped, and one missing method would have ended a connection
mid-stream.

### 2.4 The results package still cannot drive anything

`test_the_result_channel_never_writes` forbids a call named `observe` or
`build` anywhere under `tower/results/`. Both adapters are handed a
session object and may only call `status()` and `latest()` on it, which
mechanically prevents that handle from becoming a second frame path.

---

## 3. Contracts

| Contract | Transport | Subscription pair |
|---|---|---|
| `scene_understanding.live/2026-08-27` | result socket | `(scene_understanding, live)` |
| `document_memory.status/2026-08-27` | result socket | `(document_memory, status)` |
| `document_memory.library/2026-08-27` | HTTP | declared in `http_contracts` |

Full field reference: `tower/docs/contracts/CARTRIDGE-RESULTS.md` §14 and
§15. Integration view for the Mac lane:
`docs/agent-handoffs/SCENE-AND-DOCUMENT-MAC-HANDOFF.md`.

### 3.1 Routes added

```
GET  /scene                     the live scene, or why there is not one
POST /scene/{start,pause,resume,stop}

GET  /documents                 recent, newest first, no text
GET  /documents/search          BM25, with bounded snippets
GET  /documents/around          a window around an instant
GET  /documents/{document_id}   one document, with its pages
GET  /documents-session         the capture session
POST /documents-session/{start,pause,resume,stop}
```

Every one answers `404` when its cartridge is unconfigured — a claim
about configuration, never the answer to a query.

### 3.2 Configuration added

`TOWER_SCENE_UNDERSTANDING`, `TOWER_SCENE_DEVICE`,
`TOWER_SCENE_ORIENTATION`, `TOWER_SCENE_TORCH_THREADS`,
`TOWER_SCENE_AUTOSTART`, `TOWER_DOCUMENT_ROOT`, `TOWER_DOCUMENT_CAPTURE`,
`TOWER_DOCUMENT_AUTOSTART`. All off or unset by default; a Tower that
upgrades does nothing new until an operator says so.

---

## 4. Benchmarks

`scripts/cartridge_live_benchmark.py` (new). Real corpus frames fed at
the measured **12.0 fps** delivery rate rather than as fast as possible —
feeding faster measures the harness.

**The first runs were all made on a host at 100% CPU from other lanes,
and that turned out to matter more than expected.** §4.3 is the
measurement on a quieter machine, and it changes the conclusion. The
contended figures are kept because they are a real answer to a real
question -- what this cartridge does on a Tower that is already busy --
but they are not the cartridge's cost.

### 4.1 The torch thread finding

829 frames, CPU:

| | CPU cores | throughput | skipped |
|---|---|---|---|
| torch default (20 threads) | **4.12** | 9.85 fps | 17.6% |
| capped at 2 | **1.03** | 9.88 fps | 17.4% |

Four times the CPU for no throughput at all — which is what the
2026-08-26 measurements predict, since ssdlite320 at an internal 320 px
is bound by kernel-launch overhead rather than arithmetic, but nobody had
measured what it costs a SESSION. The config comment written earlier in
this run said "roughly 40% of a core"; it is corrected in place.

`TOWER_SCENE_TORCH_THREADS` exposes the cap. Not on by default, because
`torch.set_num_threads` is process-global and would silently re-tune the
Experimental CV Lab — but a Tower that leaves it unset now logs the
measurement at startup.

### 4.2 Seven minutes, 5,204 frames

| | Scene (CPU, 2 threads) | Document (cheap path) |
|---|---|---|
| observed / offered | 3,437 / 5,204 | **5,203 / 5,204** |
| skipped | 1,767 (**34%**) | 1 (0.02%) |
| observed rate | 7.91 fps | **11.97 fps** |
| CPU cores | 0.93 | **0.185** |
| mean service time | 117 ms | 15.5 ms |
| `offer_frame` median / p95 | 0.0099 / 0.035 ms | 0.017 / 0.062 ms |
| RSS growth | **+7.8 MB** | +12.2 MB |
| scene retained after stop | **no** | n/a |
| pages detected | n/a | **0** |
| documents recorded | n/a | **0** |

**The internal control.** Both ran on the same host at the same load, and
Document Memory's cheap path kept up completely -- which at the time
looked like evidence that Scene's 34% shortfall was the detector rather
than the box. §4.3 shows that reading was wrong.

**What a skew costs, when it happens.** The tracker's `max_misses` is a
FRAME count derived from a 1.0 s absence at 12 fps, so sustained skipping
stretches what "one second of absence" means. `frames_skipped` is
published for exactly this reason, and `count_limitations` carries a
`departure-lag` entry.

### 4.3 The same benchmark on a quieter host — and it keeps up

1,845 frames, CPU, `TOWER_SCENE_TORCH_THREADS=2`, host at ~70%:

| | value |
|---|---|
| observed / offered | **1,843 / 1,845** |
| skipped | **2 (0.11%)** |
| observed rate | **11.96 fps** of 12.0 delivered |
| CPU cores | 1.41 |
| `offer_frame` median / p95 | 0.015 / 0.038 ms |
| RSS growth over 2.5 min | **+0.55 MB** |

**This corrects §4.2 and it is the number to plan against.** Scene
Understanding keeps up with the glasses. The 34% skip was contention from
other work on this machine, not the cartridge -- and the honest reading
of the two runs together is that a Tower already saturated will drop
about a third of its frames to this cartridge, while a Tower with a spare
core and a half will drop essentially none.

The `worker_service_ms_mean` figure is ~118 ms in both runs, which looks
like a contradiction until the units are read: it is CPU-seconds per
observed frame across a 1.4-core worker, so the wall-clock service time
is ~84 ms -- right at the 83.5 ms delivered interval, which is exactly
why a busy host tips it over and a quiet one does not.

**Memory is bounded.** Both grew and flattened; the larger figure from a
shorter earlier run was model warm-up, not a leak.

**And the headline for Document Memory:** fed 5,204 real frames through
the live path, it detected **0 pages** and recorded **0 documents**. That
is what the gate re-derivation predicts, now confirmed end to end rather
than only in an offline sweep.

---

## 5. Reviewer findings, and what happened to each

Three independent adversarial reviewers ran against the first
implementation. Every finding below was reproduced before it was fixed,
and seven of the fourteen regression tests were **proven to fail** against
the restored pre-fix behaviour before being kept.

### 5.1 Critical

| # | Finding | Resolution |
|---|---|---|
| C1 | **`?retention_days=` was inert while the payload asserted it worked.** An 86-second window served a 400-day-old document in full, on every route. A privacy control that reports success. | `DocumentStore.read_all` now filters on `recorded_at`, using the same static predicate as the prune so the two cannot drift. `include_expired` is the opt-out the prune needs to see what it deletes. The identical bug had already been fixed in `ObservationStore`. |
| C2 | **`stop()` flushed before it closed the door.** For the duration of a 1.19 s-per-page OCR flush, `offer_frame` kept accepting and the worker kept calling `observe()` on the same engine. Traced live: two threads, one `DwellTracker`. Produced **two document memories of one page** with nothing linking them. | The four steps of `stop()` are now: close the door under the lock, flush off the lock, join the worker, release the engine. Steps 3 and 4 were also inverted — releasing before joining tore a model down mid-forward-pass. |
| C3 | **Provenance pointed at the wrong recording.** `_record` stamped the capture id held when the dwell ENDED. A `stream_start` mid-reading moved the whole reading onto a capture it did not come from; a `stream_stop` erased it. | The id travels on the `Dwell`, fixed when it started. `Dwell.lineage` is opaque, so `dwell.py` stays free of any notion of a capture. |

### 5.2 Major

| # | Finding | Resolution |
|---|---|---|
| M1 | **A phone could not start Scene Understanding.** iOS sends nothing when a cartridge is opened, and only an HTTP POST could start a session — so the contract was offered, subscribable, and unservable on the only path a product has. | The session follows the stream. `stream_start` starts it; `stream_stop` and a disconnect end it; a stop only ever ends what the stream started, so a passing connection cannot kill an operator's physical test. `TOWER_SCENE_AUTOSTART=false` restores manual control. |
| M2 | **A document written during a Stop was persisted but not counted.** Two on disk, `documents_recorded: 1`. | `commits_during_consume` on the session base. Declining to publish does not unwrite; it only hides. |
| M3 | **The `session` block changed shape and emitted a state outside its own enum** — 31 fields appearing and disappearing, and `states` was itself one of them. | Every field present and `null` when absent, `"unavailable"` published in `states`. |
| M4 | **The tracks refusal was delivered as silence**, by a payload whose own rule says a refusal that depends on remembering not to fill a field is not a refusal. | `tracks: null`, `tracks_absent_reason`, `refused_entity_fields`. |
| M5 | **`left`/`right` shipped with no statement of which side of the wearer** — the one convention iOS asks the Tower to declare. | `side_convention`, with thresholds and the unmirrored-stream assumption stated. |
| M6 | **`claim` said a document "was read"**, five keys above a note saying the camera cannot establish that. | `a-page-was-in-view-and-was-ocred`. |
| M7 | **Search served 252 verbatim characters per match** inside an object promising it withheld them. | Snippet capped at 48 characters, title clipped to 60, both caps published, and the false absolute replaced with what is actually served. |
| M8 | **`facing_wearer: 0` was reachable when every estimate had expired.** Orientation latches on one lifetime success; estimates age out at 6 s. | `null` with a reason when every person's estimate has expired. Zero is an answer; "never measured" is not. |

### 5.3 Truthfulness of the published measurements

Every one of the twelve figures the reviewers checked against the source
research was **arithmetically correct and correctly attributed**. The
problems were in what surrounded them, and all were fixed:

- Recall quoted the three flattering classes and omitted the two worst
  (chair 0.161, couch 0.108), both of which this payload reports.
- The design had excluded `chair` and `dining table` as detector noise;
  the payload published both. They are now published **with** the
  disclosure, because a class silently absent from `reported_classes`
  would be indistinguishable from one looked for and not seen.
- "no capture has ever contained a sheet of paper" rested on a 51-frame
  sample; it now says so.
- Measurements were present-tense and undated on a corpus that grows
  continuously; `count_measurement` and `recording_measurement` now carry
  `measured_at`, the corpus size, and `is_current: false`.
- "A high-resolution still is the measured fix" was contradicted by the
  gate re-derivation it cites — a still is the remedy for RECOGNITION,
  and detection is the binding constraint. Split into two limitations.

### 5.4 What the reviewers confirmed clean

Scene privacy across eight lifecycle variants: no track id, box, pixel
coordinate, per-person position, landmark evidence, face data or
filesystem path. The refusal machinery for relations. The three
document answers, ordered correctly. Lifecycle honesty — four distinct
silences kept apart rather than collapsed into an empty room. Fixed
arity. `bool()` on every boolean. OCR cadence: at most two calls per
completed dwell, capped structurally. No helper script on the production
path. No unbounded queue.

And the check that mattered most: **severing a production hop was
verified to break the tests.** Commenting out `_offer_to_cartridges` in
`ws.py` produced 7 failures and 14 errors in the e2e suites; severing
`_tell_cartridges_about_capture` broke the lineage test. The tests are
load-bearing, not decorative.

---

## 6. Known limitations

### 6.1 Scene Understanding

1. **Never seen a bystander.** Every `person` box in this platform's only
   corpus is almost certainly the wearer's own torso, and the
   distribution is unimodal with a 34.3% residual no threshold separates.
   `may_include_wearer: true`, `validated: false`.
2. **It keeps up on a quiet host and does not on a busy one.** 0.11%
   skipped at ~70% machine load; 34% at 100%. Wall-clock service time is
   ~84 ms against an 83.5 ms interval, so there is no headroom -- this
   cartridge is the first thing a loaded Tower will starve. Watch
   `frames_skipped`; it is on the wire for this.
3. **Orientation off by default** — 956 ms per call on CPU, and
   `facing_from_keypoints` is unvalidated against ground truth.
4. **No bearing, no distance, no world frame, no track handle.** All
   refused with reasons on the wire.
5. **The payload is ~9.2 KB saturated**, mostly constant
   self-description. That is 4.6 KB/s on the 2 s heartbeat against ~360
   KB/s of frames. Cut once already, and it will not be cut further by
   deleting disclosure.

### 6.2 Document Memory

1. **The premise is untested, not proven.** 0 detections in 5,204 live
   frames, 0 in 9,199 offline. No capture has ever contained paper.
2. **No cross-session document identity.** The same page read twice is
   two unrelated records. `identity` says so; dedup is within a dwell
   only.
3. **No pagination, no semantic retrieval, no thumbnails.** All declared.
4. **`retention.writer_window_days` is null** — `DocumentStore` persists
   no retention manifest, so a reader cannot learn the writer's window.
   Unlike `ObservationStore`, which can and does.
5. **Every query re-parses the journal.** No index. The session status
   block is stat-gated and does not.
6. **A soft library limit is reported, never enforced.** Evicting a
   wearer's memories because a count grew is a policy decision this lane
   declined to make; retention by age is the eviction rule that exists.

### 6.3 Cross-boundary, for other lanes

- **No capture timestamp anywhere on the wire.** Everything is
  tower-receipt. This bounds what both cartridges can say about time and
  is not a Tower gap.
- **World Builder's geometry and Object Memory's observations are not in
  `http_contracts`.** Same shape as Document Memory's library, same
  argument for declaring them; their identifiers live in adapter modules
  rather than `contracts.py`, and `registry.py` must stay cartridge-blind,
  so those two lanes own the move.
- **The 360×640 delivered geometry** is what makes Document Memory
  unusable. A high-resolution **still**, not a higher stream, is the
  remedy for recognition — and detection needs its gate re-derived at any
  new geometry, which nobody has done.

---

## 7. Physical validation — the only thing left

Both cartridges are testable by a person with the glasses and no Swift.
Full procedure in
`docs/agent-handoffs/SCENE-AND-DOCUMENT-MAC-HANDOFF.md` §7. In short:

- **Scene:** enable, connect, stand in a room with one other person at
  2 m, and record `people.count` against the truth. The expected failure
  is an undercount; the expected confound is the wearer's own torso.
- **Document Memory:** enable capture, hold a printed page square-on at
  reading distance for ten seconds, and see whether `pages_detected`
  moves at all. **Expect zero** — and if it does not, that is the first
  positive this cartridge has ever seen.
- **Coexistence:** run both with World Builder for ten minutes and watch
  `frames_skipped` on each. Set `TOWER_SCENE_TORCH_THREADS=2`.

---

## 8. Rollback

Nothing here changes an existing contract, route or payload. To disable
entirely: unset `TOWER_SCENE_UNDERSTANDING` and `TOWER_DOCUMENT_ROOT`.
Both offers become `available: false` with a reason; no session is
constructed, no thread starts, no model loads.

To remove the offers from the declaration, revert the two
`CartridgeOffer` entries and the `NOT_OFFERED` change in
`tower/tower/results/registry.py`. That is the whole surface.

---

## 9. Gates

**1,663 passed, 40 skipped, 0 failed** — the whole suite, corpus tests
included, in one run.

Baseline before any change, on the same host: **1,512 passed, 40
skipped**, with one failure — the documented Windows sharing-violation
flake in `tests/test_result_channel_hostile.py`, which
`docs/agent-handoffs/LANE-OWNERSHIP.md` §3 rules to the World Builder
lane. That flake surfaced twice during this run and passes in isolation
(18/18); it did not appear in the final gate.

### New test files

| File | Pins |
|---|---|
| `test_scene_snapshot_isolation.py` | a held `SceneState` does not change underneath its holder |
| `test_scene_live_session.py` | Start/Pause/Stop control real work; one slot; failures reported |
| `test_scene_wire_e2e.py` | a frame on `/ws` becomes counts on a subscription; the stream lifecycle; what the payload may not say |
| `test_documents_wire_e2e.py` | the three answers; no text in a listing; provenance; the capture session |
| `test_live_cartridge_privacy.py` | a running session writes nothing; a web process cannot store page images |
| `test_live_cartridge_regressions.py` | the five reviewer defects, seven of them proven red pre-fix |
| `test_new_contracts_are_documented.py` | every key of every payload variant appears in the contract document |
| `test_cartridge_live_benchmark_cli.py` | the benchmark stays callable and accounts for every frame |

### Tests changed, and why

- `test_architecture_boundaries.py` — adapter exemptions extended to the
  two new cartridges, mirroring the World Builder precedent; the document
  rule's bare-substring match narrowed to the qualified package path, the
  same correction the World Builder rule already carries; and
  `test_scene_understanding_persists_nothing` **widened** from
  `tower/scene/**` to the whole wire path.
- `test_result_channel_protocol.py`, `test_result_channel_isolation.py` —
  enumerations updated for three offers instead of one; the vocabulary
  scan widened to the two new route files.
- `test_document_memory_store.py` — one retention test now injects a
  clock, because a read that honours the window makes a store built with
  a real clock and records stamped at t=0 incoherent. The assertion is
  strengthened by the change, not weakened.

---

## 10. Left behind, deliberately

- The worktree at `C:\Users\tvllo\Projects\Glasses-cartridges` with a
  junction at `tower/data/captures` pointing at the main checkout's
  corpus, and a junction at `tower/.venv`. Both are local conveniences;
  neither is tracked.
- `tower/data/` in the main checkout is untouched. Every benchmark read
  it; none wrote to it.
- The branch is unmerged. `LANE-OWNERSHIP.md` §5 forbids merging to
  `main`, and integrating with `integration/world-builder-lifecycle-v1`
  is an integration decision rather than this lane's.
