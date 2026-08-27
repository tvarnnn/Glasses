# Tower unification — integration report

**Branch:** `integration/tower-unified-cartridges-v1`
**Base:** `25eb7944aed2a998a86e9b1b347ec1d316998ea5` (`origin/integration/world-builder-lifecycle-v1`)
**Date:** 2026-08-27
**Status:** green, pushed, not merged to `main`.

Four independently developed Tower lanes are now one branch. This is the
record of what was merged, in what order and why, what conflicted, how
each conflict was resolved and on what grounds, what was verified, what
was found and fixed, and — at least as important — what was found and
deliberately **not** fixed.

---

## 1. Source branches

| Lane | Branch | HEAD | Verified |
|---|---|---|---|
| World Builder | `origin/world-builder/next-generation` | `87a5ffb` | ✅ as briefed |
| Object Memory | `origin/object-memory/lifecycle-and-semantics-v1` | `fff7c04` | ⚠️ see note |
| CV Lab | `origin/cv-lab/productization-v1` | `0472fc9` | ✅ as briefed |
| Document + Scene | `origin/integration/document-scene-cartridges-v1` | `cca3104` | ✅ as briefed |
| Base | `origin/integration/world-builder-lifecycle-v1` | `25eb794` | ✅ as briefed |

> **Note.** The run brief named Object Memory at `ff7c704`. No such object
> exists. The branch's actual head is
> `fff7c045f0bb4b0001d1d33948daaff814e0c9da`, which is what was merged —
> a transposition in the brief, not a different commit. Recorded here so
> nobody later concludes the wrong thing was integrated.

**Ancestry.** All four lanes fork from the single base `25eb794`, verified
by `git merge-base --all` returning exactly that commit for each. A clean
star, no cross-lane merges, no rebases to unpick.

---

## 2. Merge order, and the evidence for it

Shared-file overlap was measured before anything was merged:

| Pair | Files in common |
|---|---|
| World Builder ∩ anything | **0** |
| Object Memory ∩ CV Lab | 6 |
| Object Memory ∩ Doc/Scene | 8 |
| **CV Lab ∩ Doc/Scene** | **15** |

World Builder is genuinely self-contained: it touches only
`tower/tower/world_builder/`, `storage.py`, its own
`results/world_builder_geometry.py`, plus its scripts, tests and docs. It
never touches `main.py`, the routes, `config.py` or the results registry.

The order chosen was **World Builder → Object Memory → Document/Scene → CV Lab**:

1. **World Builder first** because it is free. Zero overlap means zero
   conflicts, and it establishes a green tree with the largest lane
   already in it.
2. **Object Memory second** because it owns the *shared* Start/Stop/
   capture lifecycle — `CartridgeSession`, the gated multi-spec
   `CaptureWorkerSupervisor`, the generic session route. Landing the
   lifecycle **before** the cartridges that attach to it means later
   lanes reconcile *onto* a shared lifecycle rather than having one
   retrofitted underneath them.
3. **Document/Scene third**, because its shared-infrastructure diff is
   roughly four times CV Lab's (2,486 lines against 671) and it
   introduced `declaration_inputs(app_state)` — the extension point CV
   Lab's `cv_lab` then plugs into. The larger structural change lands
   first and the smaller one adapts.
4. **CV Lab last**, reconciling onto both.

The hardest pair (CV ∩ Doc/Scene, 15 files) is deliberately resolved
last, once everything else is settled and green.

---

## 3. Conflicts and semantic resolutions

### Lane 1 — World Builder (`83736e3`)

**No conflicts.** Nothing textual was possible. The risk this lane carries
runs the other way — a later lane's shared-capture change regressing
World Builder — and that is settled quantitatively in §6.

### Lane 2 — Object Memory (`68141f9`)

**No conflicts.** World Builder and Object Memory share no file.

### Lane 3 — Document Memory + Scene Understanding (`84b85a6`)

Four files, four different kinds of resolution.

| File | Conflicts | Resolution |
|---|---|---|
| `tower/tower/config.py` | 3 | union; one merged helper; one real decision |
| `tower/tower/main.py` | 4 | three unions, one genuine choice |
| `docs/agent-handoffs/CARTRIDGE-ROADMAP.md` | 1 | per-row, by owning lane |
| `docs/agent-handoffs/LANE-OWNERSHIP.md` | 1 | both findings kept, renumbered |

`results/contracts.py`, `results/registry.py`, `results/__init__.py`,
`routes/cartridges.py` and `test_architecture_boundaries.py` auto-merged:
Object Memory left them alone, so there was one side to take.

**The truthy set — a real decision, not a preference.** Both lanes
independently wrote an identical `_flag()` helper for the identical stated
reason ("so a fourth flag cannot arrive with a fifth spelling of true").
They disagreed on the accepted set: Object Memory took
`("1","true","yes")`, Document/Scene also took `"on"`. **Taken wider.**
The narrow set does not merely reject `"on"` — it reads it as **FALSE**,
and the flag it would silently switch off is `observation_enabled`, which
defaults ON. An operator writing `TOWER_OBSERVATION_ENABLED=on` would have
disabled the cartridge they were enabling. Widening touches explicit
values only; no default changes for anyone who set nothing.

**`create_app` — the only hunk that is not a union.** Both lanes assign
`app.state.capture_workers`; Object Memory's call passes **gates**,
Document/Scene's does not. The gated call survives and the ungated line is
dropped. An ungated supervisor would run the observation producer at boot,
which is exactly the privacy decision `_observation_spec` exists to make —
object memory attaches only while a session a person started is ACTIVE.
Document/Scene loses nothing: it registers no worker spec, its live
cartridges ride `frame_consumers`.

Ordering inside the merged block is load-bearing twice, and was verified:
`capture_workers` before `CartridgeSession(supervisor=...)`, and `live`
before `build_hub(..., scene_source=live.scene, ...)`.

**`CARTRIDGE-ROADMAP.md`.** Both lanes rewrote the same three rows with
their own progress. Each row taken from the lane that owns it. The Object
Memory row additionally gained the `/cartridges` gap, which neither lane
could see on its own.

**`LANE-OWNERSHIP.md`.** Both lanes appended a cross-lane finding and both
numbered it 4.3. Both kept, renumbered 4.3–4.6. Lane 2 had also left its
trailer at a stale 4.3; fixed rather than carried.

### Lane 4 — Experimental CV Lab (`4f52359`)

Ten conflicts, and **one decision underneath most of them.**

Both lanes hit the same constraint — `declare()` must stay a **pure
function of its arguments**, because that is what lets a test assert the
HTTP route and the WebSocket message are byte-identical rather than merely
equal today — and both solved it, differently:

```
CV Lab            declare(world_root, cv_lab)                   positional
Document/Scene    declare(world_root, *, document_root=None,
                          scene_enabled=False)                  keyword-only
                  + declaration_inputs(app_state)
```

**Document/Scene's shape wins; `cv_lab` joins it as a third keyword-only
argument.** The grounds are Document/Scene's own docstring: with defaults,
a caller not yet taught about a cartridge gets that cartridge declared
**UNAVAILABLE**. Forgetting to thread a value through therefore
under-promises — iOS renders "connect" — instead of promising a channel
the Tower cannot serve. A positional argument has no such fallback.

`declaration_inputs(app_state)` is the other half and is what makes the
change worth making: it is now the **one** reader of declaration state off
an app. Two call sites each reaching for their own subset of `app.state`
is precisely how the two surfaces would drift, and the drift would be
invisible until a phone hit the wrong one. CV Lab's three call sites moved
onto it and its now-dead `_cv_lab()` helper was removed rather than left
unused.

Nothing of CV Lab's actual decision was lost: `cv_lab` stays **duck-typed
and never imported**, `_cv_lab_availability` is kept verbatim, and
`test_the_result_channel_core_is_cartridge_blind` still passes.

**`NOT_OFFERED` is now empty**, and kept as a tuple with a comment because
`not_offered` is a published wire field and a client reads its emptiness as
a claim.

**`ws.py` — not two spellings of one thing.** `_close_cartridge_streams`
is Document/Scene's discard-on-stop; CV Lab's `elif` is a new dispatch
arm. Both kept. Dropping the first leaves a stopped stream publishing a
scene for a room the wearer has left; dropping the second sends every
`cv_lab_*` message to the unknown-type path.

**`CARTRIDGE-RESULTS.md` §9.** Each lane's text declared the *other*
lane's cartridges "not offered". Replaced with one four-row offered table,
the empty-`not_offered` claim, the Object Memory gap, and the reconciled
signature. A section-numbering collision (12b/13 against 18) resolved to
18.

**Three tests** moved from positional to keyword `cv_lab=`, and three
assertions were updated to the unified truth (all four offered,
`not_offered` empty). `test_no_other_cartridge_can_be_subscribed_to` now
pins **Object Memory as unknown-on-the-socket**, so an accidental
declaration gets caught.

---

## 4. Tests after each merge

| Point | Passed | Skipped |
|---|---|---|
| base `25eb794` | 1513 | 64 |
| after World Builder | 1666 | 64 |
| after Object Memory | 1856 | 64 |
| after Document/Scene | 1988 | 64 |
| after CV Lab | 2144 | 64 |
| after reviewer fixes | **2153** | **64** |

`/cartridges` was inspected after every merge, over HTTP **and** on the
socket, with the two compared for byte-identity every time.

Also green on the final tree: `-m slow` (23 passed, 10 skipped); and a
targeted sweep of the 12 boundary/contract/bounds/hostile/startup suites
(264 passed).

---

## 5. Reviewers

Three independent adversarial reviewers, none of whom wrote the code.

**Reviewer A — lifecycle, capture ownership, worker supervisor, races,
result routing.** Six findings, all reproduced with scripts.

**Reviewer B — memory and resources, queue and cache bounds, retained
frames, socket/task/process cleanup, privacy under concurrency, model
lifetime, multi-cartridge coexistence.** Four findings reproduced, six
reasoned.

**Final adversarial reviewer** — the twelve-item integration checklist
(missing cartridge, duplicate lifecycle, control-route-without-worker,
stale results crossing runs, cross-cartridge starvation, privacy bypass,
persistence-root mismatch, dangling workers, schema/doc mismatch, missing
route registration, tests-green-while-wiring-disconnected, World Builder
regression), plus a fact-check of the two Mac-facing documents.

Reviewer B independently **re-verified the Object Memory face-filter lock
with a negative control**: 8 threads at two resolutions, 320 requests,
**0 byte mismatches**; with the lock removed, **311 mismatches** and 200
OKs carrying unfiltered frames. The lock is real and the repro is
sensitive enough to prove it.

---

## 6. World Builder: no regression, quantified

The adversarial checklist's twelfth item is "a World Builder regression
from shared capture changes". World Builder touches no file the other
lanes touch — but the supervisor beneath it became multi-spec and gated,
and `_start_capture` became async in this integration.

A **read-only corpus replay of all 8 pinned real captures** was run on the
final tree against the main checkout's capture corpus:

| Metric | WB lane's published figure | This tree |
|---|---|---|
| poses solved | 620 | **620** |
| poses refused | 860 | **860** |
| points | 71,122 | **71,122** |
| segments | 232 | **232** |
| keyframes | 1,712 | **1,712** |

**Exact on all five.** Controls behaved: negative (pure rotation) 0 poses
/ 0 points; positive (strafe) 4 poses / 1,499 points. Legible fragments
97, drawable 98, worst bbox blowup 11.01, 96.17 s total.

Reviewer A separately verified end-to-end on the real app that the
world-build worker still attaches **ungated** at `capture_opened`, that
Object Memory attaches only on Start with `--attach-mode from-now`, that
Pause detaches Object Memory and leaves world-build alone, and that a
reconnect chains world-build into the successor lineage without starting
Object Memory while its gate is closed.

---

## 7. Findings fixed

### CRITICAL — one cartridge silently starved three others (`b42e6b2`)

`cv_lab_pause` — an ordinary command any connection may send, with no
ownership check — stopped frames reaching the **dataset recorder**, Scene
Understanding and Document Memory. All of them went on reporting
themselves healthy: `/health` said `capture: armed`, the recorder said
`is_recording` with an open capture id, Scene said `running`, and **zero
bytes reached disk**. The walk was lost and nothing in the log said so.
Worse under `module_unavailable`, which is **terminal**: a typo in
`TOWER_CV_EXPERIMENT` or one load timeout made the Tower record nothing
and feed no cartridge for the life of the process.

`_record_capture` and `_offer_to_cartridges` sat on the success path only
and the two exception handlers returned before reaching them. Before this
merge that was defensible — the CV module had no refusal path. The CV Lab
lane added **six client-reachable refusal states** and nothing revisited
the assumption. This is the archetypal integration defect: correct in
each lane, wrong in their union.

Both calls are now `_fan_out_frame`, on every path that decoded a frame.
The rule is recorded at the function: **what the CV module thought of a
frame is the CV module's business.**

Verified against the reviewer's own reproductions: recorder and cartridge
deltas went 0/10 → 10/10 while paused, and 1 → 7 under a FAILED module.

### MAJOR — a wearer's Pause on Scene Understanding was silently undone

`stream_opened` called `start()` unconditionally, and `start()` promotes
PAUSED → RUNNING for "an operator pressing a button twice". A
`stream_start` is not that; it is a socket connecting, arriving from a
reconnect, a second phone, or a Mac running a physical test. Scene
Understanding **detects people** and follows the stream by default.

`start(resume_paused=False)` withholds only that promotion — a keyword
rather than a separate method, so the decision is made inside the lock. A
caller that checked the state and then called `start()` would have a
window in which a Pause landing between the two is silently resumed: the
same bug, smaller. Object Memory already got this right by construction;
the two cartridges now agree.

### MAJOR — attaching a capture worker froze the whole Tower

`supervisor.capture_opened` ran **on the event loop**. Since the
supervisor became multi-spec, that lock is contended by Pause and Stop,
whose `detach` holds it across a `terminate()` and a bounded
`process.wait()`. A producer ignoring SIGTERM blocked `stream_start` for
up to the terminate timeout **per spec** — and on the loop that is every
connection. **Measured: a 1.95 s freeze with one stubborn worker.**

Only that call moved off-thread, matching the rule
`_close_cartridge_streams` already follows. `observer.start()` stays on
the loop, so recorder starts remain serialised as before.

### Two contract values the wire had stopped carrying (`3e7e72b`)

Document Memory's `claim` and `snippet_max_chars`. Both doc-vs-code drift,
both pre-existing, both in the direction that hurts: the **document was
stale and the code was right**, so a Mac client built from the prose would
have compared against a string that never arrives and sized a label three
times too wide.

`test_every_payload_key_is_documented` could not catch either — it holds
that every key is *named*, and these keys were named. Nothing held the
other half. `test_the_contract_quotes_the_values_the_wire_actually_carries`
now does, for the load-bearing constants, and asserts the retired spelling
appears **nowhere** — which caught its own first draft.

### Regression tests, proven red

`tower/tests/test_unified_lifecycle_regressions.py`, 8 tests, in the
integration rather than any lane's file because neither defect was
reachable from one lane. Each was proven RED by reverting one fix at a
time in a scratch copy:

```
revert stream_opened's resume_paused   -> 1 failed, 7 passed
revert the off-thread capture attach   -> 1 failed, 7 passed
revert the fan-out to the success path -> 2 failed, 6 passed
```

Each revert reddens exactly the tests that name it and no others. Two
tests exist to stop the fixes overshooting. The loop test drives the
**real** `_start_capture`; an earlier draft wrapped the inner helper in
its own `to_thread` and would have passed against the very code it was
meant to catch.

---

## 8. Findings NOT fixed, and why

An integrator harmonising four lanes' tested behaviour is not integrating,
it is redesigning. Each of these is recorded with its reproduction so the
next person decides on evidence.

| # | Finding | Why it stands |
|---|---|---|
| 1 | **Pause/Stop can report `changed: true` while the producer keeps running** | The contract already answers this: `state_means: "intent-not-liveness"`, and `following` carries the truth. The lane made this decision deliberately. Surfacing it differently is a wire change. **Both Mac documents state the rule prominently.** |
| 2 | **Four cartridges answer the same verb three different ways** | Both behaviours are tested in their lanes. Unifying them is a contract change that belongs to a human. Documented as a table in the contract synthesis §4.1, which is now the contract until someone decides otherwise. |
| 3 | **CV Lab refuses `cv_lab_stop`** from `stopped`/`idle`/`failed` | Same. Note this contradicts `cartridge_session.py`'s own reasoning ("refusing it would leave the only way out of a bad state being a Tower restart"). Worth a human ruling. |
| 4 | **`LiveSession.stop()`'s flush overlaps one in-flight `_consume`** | Reproduced by Reviewer B. Pre-existing Document/Scene concurrency; the window is ~1 frame, but Document OCR is ~1.19 s/page. Deep surgery on a lane's hardened code, not integration work. |
| 5 | **On a join timeout `stop()` releases the engine under a running `_consume`** | Same. `LoadInvalidation` covers a worker stuck in `_create`, not one inside `_consume`. Both engines self-heal lazily, so the worst case is a reload into a dead session. |
| 6 | **A phone's `stream_stop` can end a Scene session an operator started by hand** | `stream_opened` adopts a running session into the stream's owner set. Two docstrings contradict each other and one is wrong; that is a lane decision. Called out in the Mac handoff's physical-test instructions. |
| 7 | **`supervisor.shutdown()` can cost ~24 s** under the lock, on a premise `lifespan()` does not establish (nothing closes the capture on teardown) | Real, reproduced. Fixing it means either closing captures in `lifespan` or re-timing the grace — both behaviour changes to a lane's teardown. |
| 8 | **`_stop_worker`'s docstring promises something false** | The registry is keyed by lineage root, so an un-killable worker under `cap-1` blocks nothing when the next id is `cap-2`; producers can accumulate one per reconnect. Either the promise or the text is wrong. |
| 9 | **`ResultHub` can be resurrected after `shutdown()`** | No terminal latch, unlike every other lifecycle object here. Reasoned, not reproduced. |
| 10 | **Object Memory retention only runs on a clean producer exit** | `Stop` terminates immediately, skipping `prune_expired()`. On-disk growth, not a read-surface leak — reads still clamp. |
| 11 | **Two HTTP contracts are declared nowhere** | `world_builder.geometry` and `object_memory.observations`. Declaring them means moving identifiers into `contracts.py`, and `registry.py` must stay cartridge-blind. **Those two lanes own the move.** |
| 12 | **`world_builder/redaction.py` resolves its model path relative to CWD** | So face redaction — a privacy feature — is on or off depending on the launch directory, and it changes geometry (112 vs 194 solved poses on one capture). Disclosed by the WB lane, frozen to it. |

### The one deliberate gap: Object Memory is not in `/cartridges`

This will look like finding 1 on any future audit. **It is intended.**
`CARTRIDGE_OBJECT_MEMORY` exists in `contracts.py` and its control surface
is live, but declaring it breaks a pinned iOS test
(`testTheTowerDeclaresOnlyTheWorldBuilderContract`), so the socket
declaration waits for the iOS lane to take both halves in one change. The
Tower side is about four lines.

It is now defended from both directions: a comment at `registry.NOT_OFFERED`
explaining it, a test pinning Object Memory as unknown-on-the-socket, and
a check in the end-to-end smoke. **This is a decision for a human and must
not be closed by an integrator noticing the asymmetry.**

---

## 9. Per-cartridge status on this branch

| Cartridge | Declared | Control surface | State |
|---|---|---|---|
| **World Builder** | ✅ `world_builder`/`status` + HTTP geometry | none (child process, gated by config) | Corpus figures reproduce exactly. Nothing physically validated. |
| **Object Memory** | ❌ **deliberately** | `/cartridges/object_memory/session` | Store, query, imagery, Start/Pause/Resume/Stop all live over HTTP. |
| **Experimental CV Lab** | ✅ `experimental_cv`/`status` | socket `cv_lab_*` | Eight experiments, provenance, staleness-by-structure, truthful FAILED. |
| **Scene Understanding** | ✅ `scene_understanding`/`live` | `/scene/*` + stream-bound | Discards on Stop. Verified with a real model in the smoke. |
| **Document Memory** | ✅ `document_memory`/`status` + `library` under `http_contracts` | `/documents-session/*` | Keeps on Stop. Verified with a real OCR reader in the smoke. |

`/cartridges`: four offered, `not_offered` **empty**, one `http_contracts`
entry. HTTP and socket byte-identical. 27 routes across 9 routers.

---

## 10. Preserved decisions

Checked individually against the merged tree.

**World Builder.** Guided re-observation and the measured wins are intact
(the corpus replay reproduces them to the unit). Registration is **not**
auto-wired — the evidence refused it: 2 of 8 captures register anything,
2.2× the cost of all replay+build, and 135 of 141 refusals are
`span_over_depth`. The **~2% perpendicular/wrong-basin defect is left
open**, and the high-false-refusal gate **stays rejected**: it would trade
a measured 17.1% loss of currently-solved edges against an unmeasured 2.5%
gain, on a corpus with no ground truth to settle it. Unknown/relative
scale truthfulness is unchanged, and `distanceDisplayable` is still always
false. PT-1 is carried forward with its procedure, pass criteria and
falsifier. Redaction ordering is untouched — ephemeral geometry may use
raw pixels; persistence gets the fill; no blackout mask is fed into SLAM.

**Object Memory.** The productised Start/Stop/shared-capture lifecycle,
the unified observation store with **one** `DEFAULT_OBSERVATION_ROOT`
handed to both the read routes and the producer's argv, the concurrency
and privacy fixes (filter lock, Stop/Start race, double-attach race, path
containment), real frame/thumbnail retrieval, face-filter-on-read with
**refusal** rather than fallback, and the 410 "memory retained / picture
gone" semantics. Cautious identity behaviour is intact: `identity:
category-not-instance`, `person` excluded by a constant no model can reach
past, `spatial_ref` nulled on read. **The shipped model was not replaced.**

**CV Lab.** Experiment enumeration, runtime selection, lifecycle,
provenance and staleness-by-structure; one Lab slot / one module; the
`cv_lab_starting` refusal window; NaN/JSON sanitisation at the **sender**;
truthful terminal FAILED (no `start_failed`, the outcome arrives as
state); Debug/Release semantics and the two-part LIVE rule.

**Document Memory.** Typed status and library contracts, kept **separate**
because they govern different transports; the live capture session;
**Stop keeps** and flushes a dwell in progress; provenance and retention
fixes; the truthful 360×640 limitation stated as payload data rather than
implied by an empty list.

**Scene Understanding.** Typed live scene; `stream_start` starts,
`stream_stop`/disconnect end **and discard**; lower-bound counts,
`count_limitations`, and the four silences told apart;
non-identifying privacy — no face recognition, no identity persistence,
`tracks` and `relations` structurally absent rather than merely unfilled.

---

## 11. The Object Memory model-research tension

Carried forward as a **post-integration investigation**, unresolved on
purpose and stated here so it is not mistaken for settled.

The lane shipped `ssdlite320_mobilenet_v3_large` plus an optional
`owlv2-base-patch16-ensemble` verifier that ships OFF. The lane's own
1,902-line vision-model landscape research recommends a **different**
stack (`llmdet_tiny`, patch-pooled DINOv2, an Apache-2.0 tracker with no
re-ID). The shipped choice diverged to owlv2 — the research's own
"simplest possible option" — on a **local benchmark of 94 crops from one
home**, not on the leaderboard reading. That is a defensible divergence
and it is also a thin basis.

Three findings sit above the model choice and are the reason not to act
on it yet:

1. **The binding constraint is upstream of every model.** The shipped
   detector has **0.000 recall below 1% of frame area**, and the objects
   worth remembering — keys, wallet, glasses, medication — live in that
   band. **Semantics added downstream of a blind stage one produce a
   well-characterised memory of laptops.** Swapping the detector does not
   help: the oracle is 11% dearer on CUDA but **16.2× the frame interval
   on CPU**, which is the default.
2. **Context beats appearance**, measured rather than asserted. Removing
   the *background* descriptor — not the object's own features — costs
   34.8 and 24.9 IDF1 points and nearly triples ID switches. The thing
   that disambiguates two identical mugs is not the mug.
3. **The 360×640 limitation is physics, and the 720×1280 test stays a
   physical experiment**, not an automatic global resolution change.
   Raising the *stream* is measured as actively harmful to World Builder
   tracking (73.3% of frames fall below `min_sharpness` at 720p). What is
   wanted is an occasional higher-resolution **still**.

**Do not casually replace the shipped model.** Measure the capture first.

---

## 12. Verification on the exact final tree

| Check | Result |
|---|---|
| Complete Tower suite | **2153 passed, 64 skipped** |
| `-m slow` | 23 passed, 10 skipped |
| Contract drift / documented-values | 10 passed |
| Architecture boundaries (cartridge-blindness) | included in the 264 |
| Boundary/bounds/hostile/startup sweep (12 files) | **264 passed** |
| Route startup and import | `test_startup_scripts.py` green |
| **Corpus replay, 8 real captures** | **reproduces the lane's figures exactly** (§6) |
| **Autonomous uvicorn + socket smoke** | **68/68 with real models** |
| Child processes after shutdown | **0** |
| `/cartridges` HTTP vs socket | byte-identical |
| `ios/` touched | **0 files** |
| Working tree | clean |

**One flake found and fixed.** `test_http_socket_and_result_channel_serve_the_same_document`
failed 2 runs in 10. Not caused by this merge — measured at **3 in 10** on
untouched `origin/cv-lab/productization-v1`. The defect is in the test:
`throughput.processed_fps` and `offered_fps` are deliberately `null` while
`elapsed == 0` and a number thereafter, and Windows `time.time()` ticks at
~15.6 ms, so the three surfaces occasionally straddle a tick. The test
popped `elapsed_s` but not the rates derived from it. Both are now popped;
`capacity_fps` deliberately is not, because it comes from measured
per-frame cost and must agree. **30 consecutive runs green** with the exact
invocation that previously failed 2 in 10.

---

## 13. Mac instructions

Two documents, split the way `CLAUDE.md` splits them:

- **`docs/contracts/TOWER-UNIFIED-CARTRIDGES.md`** — the authoritative
  wire contract. Every identifier in it was read off a **running** Tower
  on this tree rather than quoted from a lane document. Where it and a
  lane's own document disagree, it is the one that was checked.
- **`docs/agent-handoffs/2026-08-27-TOWER-UNIFIED-MAC-HANDOFF.md`** — what
  to build, what to decode, what will bite, and what to test by hand,
  including the consolidated eight-item physical plan ordered by value.

The two traps that are invisible when you get them wrong, repeated here
because they are the ones that will cost a week:

1. **`WorldGeometryDecoder.chunk` does not read `transform_to_world` at
   all.** It is absent from the decoder guard list and `WorldSegmentChunk`
   has nowhere to put it, so a Tower emitting a Sim3 is silently dropped.
2. **`WorldGeometryStore` is keyed on `contentHash` alone and must become
   `(contentHash, placementHash)`.** Without it, the day a segment gains a
   placement the client keeps its cached chunk forever and draws an
   unplaced version. Nothing looks broken; the fragment simply sits in the
   wrong place, permanently.

Start with `scripts/unified_cartridge_smoke.py`. If it fails, the fault is
the Tower's, not the phone's.

---

## 14. Consolidated physical-test plan

Nothing has been run. Full detail in the Mac handoff §6; ordered by value:

1. **PT-1 lateral-translation walk** (World Builder) — worth more than the
   rest combined, and the only thing that can settle whether the binding
   constraint is the capture.
2. **Real-paper test** (Document Memory) — the detector has never been
   shown a positive it was built for.
3. **Real-person test** (Scene Understanding) — every `person` in the
   corpus is the wearer's own torso.
4. **PT-4 recognisability** (World Builder) — rides on PT-1 footage.
5. **Object Memory found-record screen**, shown cold to a person.
6. **Coexistence soak**, World Builder + Scene for ten minutes.
7. **720×1280 still** — one measurement, upstream of a lot of model work.
8. **PT-2 / PT-3**.

Run 1 and 2 first. They are the two that can falsify something.

---

## 15. Tree, push, rollback

**Commits on the branch** (first-parent):

```
923aee6  docs(contracts): the Mac handoff, and the lifecycle divergences
b42e6b2  fix(runtime): three cross-lane defects the reviewers found
3e7e72b  fix(contracts): two documented values the wire had stopped carrying
12ece7f  test(integration): an autonomous smoke that proves the lanes coexist
4f52359  merge(integration): Experimental CV Lab productization
84b85a6  merge(integration): Document Memory + Scene Understanding
68141f9  merge(integration): Object Memory lifecycle-and-semantics
83736e3  merge(integration): World Builder next-generation
25eb794  (base)
```

302 files changed, 149,355 insertions, 1,215 deletions against the base.

**Pushed** to `origin/integration/tower-unified-cartridges-v1` after every
lane. **Not merged to `main`.** No feature branch was force-pushed; no
feature branch was modified at all. `ios/` is untouched.

**Rollback points.** Every lane boundary is a green, pushed commit:

| Roll back to | Leaves you with |
|---|---|
| `25eb794` | the base, before any of this |
| `83736e3` | + World Builder |
| `68141f9` | + Object Memory |
| `84b85a6` | + Document/Scene |
| `4f52359` | all four lanes, before the reviewer fixes |
| `923aee6` | HEAD |

Each merge commit is a true two-parent merge, so `git revert -m 1 <sha>`
backs out exactly one lane. The four source branches are untouched at
their original heads.

---

## 16. What an audit will trip over, in one list

Read this before filing a bug against this branch.

1. **Object Memory is missing from `/cartridges`.** Intended (§8).
2. **`not_offered` is empty.** Intended — a claim, not an oversight.
3. **Scene and Document return 200 for verbs they cannot honour.** Lane
   behaviour, documented, not harmonised.
4. **The CV Lab refuses Stop from `stopped`.** Same.
5. **Pause can report success without stopping the producer.** The
   contract answers this with `following`; both Mac documents say so.
6. **`capacity_fps` is not excluded from the three-surface agreement
   test.** Deliberate — it is not wall-clock derived.
7. **The World Builder ~2% wrong-basin defect is open**, and the gate that
   would close it stays rejected on measured evidence.
8. **`world_builder.geometry` and `object_memory.observations` are
   undeclared.** Those lanes own the move.
