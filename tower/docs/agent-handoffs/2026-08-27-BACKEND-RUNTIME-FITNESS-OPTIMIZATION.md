# Backend runtime fitness, resource safety and truthful capability

**Branch:** `optimization/backend-runtime-fitness-v1`
**Base:** `13d308f` (`origin/integration/tower-unified-cartridges-v1`, verified
identical to the remote before branching)
**Date:** 2026-08-27
**Status:** green, pushed, **not merged**. `ios/` untouched: 0 files.

Eleven commits. Four of them are security or resource-safety fixes for defects
that were on nobody's list; two are performance; five are corrections that
reviewers found in the ones before them — **including two regressions this
lane introduced, and one fix that did nothing at all until a reviewer caught
it.**

**The headline is not a speedup.** It is that a whole-backend audit, run to
the same standard as the native-hotpath lane, found **no case for a language
migration and no case for native extraction anywhere in the backend** — and
that the most valuable things it did find were an unauthenticated path
traversal and a cartridge that advertised itself as usable when it was not.

---

## 1. Starting point

| | |
|---|---|
| Branch created from | `13d308f` |
| Remote verified | `origin/integration/tower-unified-cartridges-v1` @ `13d308f` |
| iOS checkpoint read (read-only) | `ios/unified-cartridges-v1` @ `3c98e8c` |

## 2. Ending point

| | |
|---|---|
| HEAD | `0a755d7` |
| Pushed | `origin/optimization/backend-runtime-fitness-v1` |
| Working tree | clean |
| `ios/` files changed | **0** |

## 3. The frozen baseline

Measured on the branch before any production change.

```
Full Tower suite      2160 passed, 64 skipped in 357.26s     exit 0
```

That reproduces the integration report's published 2160/64 exactly, so the
tree this lane started from is the tree that report describes.

**Canonical invocation.** Every measurement in this lane was taken with

    cwd:         C:\Users\tvllo\Projects\Glasses-world-builder\tower
    interpreter: C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe
    asserted:    tower.__file__ under Glasses-world-builder

### 3.1 The code-resolution trap has THREE forms, not one

The native-hotpath lane documented one. This lane hit all three, and the third
produced **145 phantom test failures** that read exactly like a regression.

**Form 1 — wrong directory.** From the worktree root, `tower` resolves as an
empty namespace package (`__file__ is None`); from `<worktree>/tower` it
resolves here. Previously documented.

**Form 2 — a scratch script's own directory.** CPython puts the *script's*
directory on `sys.path[0]`; cwd never enters `sys.path` at all. A harness
written to a scratch directory resolves the MAIN repo even with cwd correct.
**Two independent agents hit this before their first measurement.** Every
scratch script must `sys.path.insert(0, <worktree>/tower)` and assert.

**Form 3 — an earlier `cd`, then a background launch.** A `cd <repo root> &&
git commit` moved the shell's persistent cwd; a later backgrounded pytest
inherited it. Nothing in the output says "wrong tree". The symptoms, in the
order they become visible:

    test IDs read  tower/tests/test_x.py   instead of  tests/test_x.py
    FileNotFoundError: 'tower\main.py'
    UnicodeDecodeError: byte 0xff at 14525
    failures cluster in *_cli.py and other subprocess-based tests

**The tell is the test-ID prefix.** Compare it against a known-good run before
believing any red result. Assert resolution *inside* the run, not before
launching it.

## 4. Backend inventory and classification

Every meaningful production module under `tower/tower/`, from two independent
audits. Full per-finding detail in §6 and §7.

| Component | Classification | Why |
|---|---|---|
| `routes/ws.py` frame path | KEEP | Already minimal; the one real cost is the synchronous `process()` (§14, DEFER) |
| `frames.py` | KEEP | base64 + PIL header parse measured at 0.086 ms/frame; binary frames REFUSED on that number |
| `frame_processing.py` | KEEP | one decode, one cvtColor, one mean |
| `capture.py` recorder | DEFER | ~13 syscalls + 1 fsync per frame on the loop; real, bounded, not taken (§14) |
| `capture.py` follower | **OPTIMIZE_IN_PLACE** | idle bound existed and was never armed (§7.5) |
| `capture_workers.py` | **OPTIMIZE_IN_PLACE** | serial teardown made concurrent (§7.6) |
| `cartridge_runtime.py` | **OPTIMIZE_IN_PLACE** | eager dependency import (§7.3) |
| `live_session.py` | **DEFER** | per-session thread strands a torch pool; fix entangled with open races (§14) |
| `results/publisher.py` | KEEP | 0.5 s poll, off-thread, single-slot, bounded sends, `_failures` pruned |
| `results/envelope.py` | KEEP | `json_safe` deep-copy measured at 0.127 ms; the "faster" replacement is slower |
| `results/registry.py` | **OPTIMIZE_IN_PLACE** | availability was configuration-only (§7.3) |
| `results/world_builder.py` | KEEP | `(size, mtime_ns)` fingerprint cache with a bounded entry count already |
| `results/world_builder_geometry.py` | **OPTIMIZE_IN_PLACE** | unauthenticated traversal on both identifiers (§7.1) |
| `routes/results_ws.py` | **OPTIMIZE_IN_PLACE** | unbounded echo amplification (§7.6) |
| `routes/geometry.py` | KEEP | thin; the guard belongs in the adapter both routes share |
| `document_memory/retrieval.py` | **OPTIMIZE_IN_PLACE** | exactly quadratic in library size (§7.2) |
| `document_memory/store.py` | DEFER | rewrites the journal per record (§15) |
| `object_memory/store.py` | DEFER | rewrites per sighting, re-parses per request (§15) |
| `experiments/frame_quality.py` | **OPTIMIZE_IN_PLACE** | `Laplacian(CV_64F).var()` anti-pattern (§7.7) |
| `experiments/object_detection.py` | **OPTIMIZE_IN_PLACE** | `auto` chose the slower device (§7.7) |
| `experiments/depth.py` | KEEP | `auto` already chooses correctly; CUDA is 1.92x here |
| `logging_config.py` | **OPTIMIZE_IN_PLACE** | `ImportError` disclosed a filesystem path (§7.4) |
| `world_builder/**` | **KEEP** | corpus figures reproduce EXACTLY (§17); redaction already keyframe-only |
| `storage.py` | KEEP | the JSON write win was already taken by a previous lane |
| `modules/`, `scene/`, `cv_lab/` | KEEP | no measured defect this lane could act on |

**Nothing was classified NATIVE_EXTRACTION or LANGUAGE_MIGRATION.** See §23–27.

## 5. Cross-lane evidence: the Mac/iOS checkpoint

Read READ-ONLY at `ios/unified-cartridges-v1` @ `3c98e8c`. Their four contract
findings, checked against this base rather than taken on trust:

| Finding | Verdict | Evidence |
|---|---|---|
| **F1** `limit` documented but absent on `/object-memory/observations` | **CONFIRMED** | contract §9.1:749 documents it; `routes/observations.py:112-120` declares only `object_class` and `retention_days` |
| **F2** refusal table says `not-active`, wire says `not-paused` | **STALE** | fixed by `354f87b`, which landed *after* the commit they tested |
| **F3** every non-200 body nested under `detail`, undocumented | **STALE** | documented by `4cac6e3`, also after their test commit |
| **F4** geometry contract gained fields without moving its identifier | **CONFIRMED** | `GEOMETRY_CONTRACT` unchanged while `placement_hash` et al. emit unconditionally |

**The Mac lane tested `e2ca9b2`, two fixes behind the integration head.** Half
their contract findings evaporate against the current tree. Worth recording so
a future reader does not reopen them.

F1 and F4 are **left open**: both are contract decisions owned by the lanes
that wrote them, and this is an optimization lane. iOS never sends `limit` on
observations (checked at `3c98e8c`), so F1 is inert either way.

Their availability finding was the valuable one and became §7.3.

Of their sixteen reviewer findings (R1–R16), thirteen are fixed on their side
and R7/R8/R16 are iOS-only judgements. **None expose a backend defect.** Their
five Tower follow-ups (T1–T5) are contract/feature work — capture-timestamp
basis, resolution, discoverability, doc staleness, bearing sign — and are out
of scope for this lane rather than ignored.

One item they flagged that no summary carried: **the dataset recorder's frame
copy is never redacted** while World Builder's keyframe copy is, and both
persist. Redaction ordering is a preserved decision (§13) so it was not
touched, but it sharpens §15's retention item, because the unredacted copy is
the one with no pruner.

## 6. Discovery A — runtime, CPU, RAM, VRAM, copies, boundaries

24 findings. Its own verdict: **17 OPTIMIZE_IN_PLACE, 4 DEFER, 1 REJECT, zero
native/migration.**

Highest-value: BM25 quadratic (§7.2); `process()` blocking the loop; orphaned
workers polling forever (§7.5); stub worlds accumulating; `frame_quality`
primitives (§7.7); `auto` device (§7.7).

**It corrected the existing record downward**, which is why its other numbers
were trusted: the integration report's finding 17 documented CV Lab at
67.0 ms and 53.2 ms per frame; A measured **39.5 ms and 13.4 ms**. It kept the
direction and refused the magnitude.

**Four inherited claims did not survive its own measurement** and are marked
as such in its report: `glob("*.jpg")` (0.82 ms, MINOR not MAJOR),
`compute_revision`'s deepcopy (0.127 ms — **KEEP**, and the proposed faster
replacement measured *slower*), the ORB restructure (1.20x not 2x), and a
claimed pruning-timeout breach that needs ~125,000 documents to reach. It also
expected to recommend binary websocket frames and **the measurement refused
it**: base64-in-JSON costs 0.086 ms/frame.

## 7. Discovery B — leaks, unbounded growth, orphans, security

16 findings, four of them CRITICAL and **on nobody's prior list**. It also
verified the integration report's ten open findings: 7, 8, 10, 13, 14, 15, 16,
18, 20 CONFIRMED (several worse or more reachable than stated), and found that
**findings 9 and 19 are the same finding listed twice**.

Its negative results are as useful as its positives: **no VRAM leak**
(0.0 MB after 8 CUDA Start/Stop cycles — the leak it expected and did not
find), no Python-object leak, result-channel bounds sound, subprocess argv not
client-controlled, no `eval`/`exec`/`pickle`/`yaml.load` anywhere, privacy
filter fails closed on all three paths, path handling sound *everywhere except*
the one route in §7.1.

---

# What was changed

Eleven commits. Each was implemented as the smallest change that removed the
harm, gated on the full suite, and reviewed.

## 7.1 Unauthenticated path traversal on the geometry routes — `bc9baa3`, `8601621`

**Two identifiers, both escaping, and the first fix only closed one.**

`session_id` is declared as a bare `str`, so FastAPI binds it as a QUERY
parameter — and unlike a path parameter it is not restricted to `[^/]+`. It
reached `derived_dir(world_id) / session_id`, an unguarded join. Reproduced
against an unauthenticated TestClient with a derived tree planted outside the
world root:

```
normal     -> 200  geometry_revision 94ab93763a4beebf
traversal  -> 200  geometry_revision f9c7889a3cc4bc68   <- the planted file
absolute   -> 200  geometry_revision f9c7889a3cc4bc68   <- the planted file
```

Then a reviewer found `world_id` does the same thing, and that **the first
guard could not see it**: session containment is anchored on
`derived_dir(world_id)`, so an escaped `world_id` moves the anchor and
`parent == base` still holds. Reproduced in three forms, all 200:

```
?world_id=..\..\elsewhere\worlds\victim
?world_id=..%5C..%5Celsewhere%5Cworlds%5Cvictim
?world_id=C:\elsewhere\worlds\victim
```

Two Windows specifics make it reachable: `world_id` is a path parameter, so
`[^/]+` excludes a forward slash — and a **backslash** is equally a separator
on the only platform this Tower ships on, and is not excluded; and `%5C` is
decoded into the path before routing. (`%2F` does not match the route and is
not a vector.)

**Scope, stated precisely rather than dramatically:** `_read` calls
`read_world` first, so this needs a real world id to exist, and the target
must hold `poses.json` and `points.json` in the shape the adapter parses. It
is an escape from the world root, not arbitrary file disclosure. The
absolute-path form is the more dangerous half, because
`Path(base) / "C:/elsewhere"` REPLACES the base rather than traversing out of
it — a guard that only scanned for `..` would have missed it entirely.

**Two different primitives, and the asymmetry is the point.** A session has a
fixed base to anchor containment on; a world does not, because the attacker
supplies the base. So `session_id` gets a direct-child check and `world_id`
gets a whitelist against `list_world_ids()`.

**A whitelist for `session_id` was written first and REVERTED.** It reddened
11 tests in `test_world_builder_placements.py`: `_tiny_world` writes a world
and a derived tree with no session record, so a legitimate derived tree can
exist for a session `list_session_ids` does not return. Requiring the session
record would have turned a containment fix into a behaviour change.

`.parent.resolve()` rather than `.resolve().parent`: resolving the whole path
follows the leaf, so a junctioned session directory resolved to its target and
was refused. Reproduced with `mklink /J`.

Nine regression tests, all proven RED first, including a cross-world case that
served the second world's poses under the first world's `world_id` — a
correctness defect as much as a disclosure one.

## 7.2 Document search was exactly quadratic — `989c451`

`containing` — how many documents hold a term — is a property of
(corpus, term), not of the document being scored, but it sat inside the
per-document loop and rebuilt `set(token_list)` for every document on every
call.

Same-session A/B, both arms in one process, alternating arm order, the old
expression restored by monkeypatch so the only difference is that line:

| n | old | new | speedup | parity |
|---|---|---|---|---|
| 25 | 0.89 ms | 0.49 ms | 1.8x | IDENTICAL |
| 100 | 7.17 ms | 1.78 ms | 4.0x | IDENTICAL |
| 400 | 89.33 ms | 6.78 ms | 13.2x | IDENTICAL |
| 800 | 356.92 ms | 14.18 ms | **25.2x** | IDENTICAL |

Parity is the same documents in the same order with byte-equal scores, on
every repeat. **The multiplier rising with corpus size is the result**; a
constant-factor win would not do that.

Independently re-derived by a reviewer over 3,009 corpora and 63,028 score
comparisons: **0 mismatches**, including every edge case (empty corpus, single
document, empty tokenisation, duplicates, absent terms).

**Honest scope.** This is `/documents/search`, reached on demand, **not the
frame path**. The repo's own numbers disagree about reachable library size:
`LIBRARY_SOFT_LIMIT = 10_000` but "never enforced, evicts by AGE only", while
the detector "fires on essentially nothing", so today's library holds tens.
Measured at 10,000 page-length documents the new arm is 1.53 s where the old
extrapolates to ~450 s. **Headroom, not present-day latency** — and for seven
lines, a trivially good trade.

## 7.3 A cartridge advertised itself as usable when it was not — `8225105`

`/cartridges` reported `available: true` for Scene Understanding on a host
without torch; `POST /scene/start` then answered **200** and failed ~50 ms
later. The declaration is a pure function of configuration, so re-reading it
after the failure still said `true`.

**The honest mechanism already existed.** `build_live_cartridges` try/excepts
`_scene_session` and `main.py` derives `scene_enabled` from whether it
returned a session — the file even says "the cartridge then reports itself
unavailable through the normal path". It never fired for a missing torch
because `_resolve_device` imports torch ONLY when the device is not `cpu`, and
`cpu` is the default. Measured with torch blocked: `auto` and `cuda` **already
answered `available: false`**. `cpu` was the one broken configuration.

So the fix makes construction touch the dependency. It is not a second
unavailability path.

**`find_spec` was the other candidate and was refused on measurement:**

- fixed **0 of 6** trials of the import race below; the eager import fixed 6/6
- against a package with a valid spec whose loader raises, it reported
  `available: true`, answered `/scene/start` with 200, and **still** said
  `available: true` after the session had failed
- it would desynchronise three surfaces that share one truth, re-creating the
  silent no-op the contract's "Off must mean 404" rule forbids

**It also closes a concurrent-import race.** Scene and Document both start on
one `stream_start`, on separate threads, each reaching torchvision lazily and
for the first time there. **8 fresh processes out of 8, both cartridges in
terminal `failed`:**

```
ImportError: cannot import name 'InterpolationMode' from partially
initialized module 'torchvision.transforms'
```

6/6 clean after. Invisible to an in-process suite, because once the first
import succeeds it cannot recur. It needs `document_autostart` on, which is not
the default — real, but not the default posture. **It closes this instance,
not the class:** a reviewer reproduced the identical failure between Document
Memory and `tower/detection.py` with Scene off.

**Cost is moved, not added.** Boot with Scene on 0.32 s → 2.21 s, but boot to a
*running session* 2.019 s → 2.002 s, within 1%. Scene off pays nothing.

**The reason had to travel with it.** `SCENE_DISABLED_REASON` names the
environment variable, which is right when nobody switched it on and wrong when
they did and construction failed — it sends an operator to check the one thing
already correct. That was reachable before this lane via `TOWER_SCENE_DEVICE=cuda`;
making `cpu` honest would have made it *common*. `scene_unavailable_reason` is
`or`-ed, so an omitted reason keeps the pinned wording exactly.

**Document Memory was investigated and deliberately NOT changed.** `easyocr` is
genuinely optional: with it blocked and the real recogniser in place, a
document still persisted (1 page, 2.09 s dwell, `text_availability:
not_readable`). Declaring Document unavailable would be **wrong**. The proposal
to make its eager `load()` non-fatal was **rejected by both judges**: `claim:
"a-page-was-in-view-and-was-ocred"` is stamped on every document and
`recogniser` is *not persisted*, so a document written under a null recogniser
would be permanently indistinguishable from one where OCR ran on a blank page —
silent degradation with no field that could ever contradict it, which is worse
than a loud 51 ms failure that leaves nothing behind. A judge additionally
measured that dedup collapses without OCR (2 pages → 1). See §16.

## 7.4 An `ImportError` on the wire named the file it failed in — `d6f8920`

`client_safe_reason` reduced only `OSError`. CPython appends the module's
`__file__` to an `ImportError` for a failed `from X import Y`:

```
ImportError: cannot import name 'NoSuchNameHere' from 'torchvision.transforms'
(C:\Users\tvllo\Projects\Glasses\tower\.venv\Lib\site-packages\...\__init__.py)
```

**This lane opened the hole and then closed it.** Nothing put an import failure
on a wire until §7.3 made Scene report why it could not be constructed, one
commit earlier. It is also the exact exception the race in §7.3 produces.

Reduced *differently* from `OSError` rather than identically: an OSError's
useful half IS the path, so nothing survives suppression; an ImportError's is
the module NAME. `exc.name` is set by the import system, holds a dotted module
name and never a path, and is read instead of the message rather than parsed
out of it — and still shape-checked.

**Not the general fix, and the docstring says so.** Inverting the rule (pass
through `tower.*`, reduce everything else) was proposed by the audit and NOT
taken: it would discard useful path-free messages like torch's CUDA
diagnostics, and one existing test declares its "domain exception" as a
locally-defined class, so a module-prefix rule would fail it for the wrong
reason. The residual hole is recorded in code.

## 7.5 The idle bound both worker specs promised and neither passed — `a73e26a`

`CaptureFollower.follow()` has always accepted `max_idle_polls` and its
docstring has always promised "Bounded by construction (Rule 15)". The
parameter defaults to `None`; neither spec passed it. So the bound was
documented, implemented, used in a benchmark script — and never armed in the
product. A producer whose Tower died without closing the manifest polled that
directory **forever**.

On Windows that is the ordinary way a Tower dies: `terminate()` is
`TerminateProcess`, which runs no lifespan and closes no capture.

**The value is chosen against what a legitimate silence can be.** Frames arrive
at ~12 fps and every ordinary interruption *closes* the capture and is handled
by the successor path. The longest plausible silence with the manifest still
open is uvicorn's 20–40 s to notice a dead socket (`CaptureRecorder.stop`'s own
docstring). 900 s is an order of magnitude above that and 10x
`RESUME_GRACE_SECONDS`. The failure directions are asymmetric — firing early
costs a wearer the rest of a mapped walk, firing late costs an idle process a
few minutes — so **the test pins the margin against both existing constants,
not the number**.

## 7.6 Echo amplification, and a 24 s teardown — `4dd9f25`

**Echo.** `cartridge`, `result_type`, `subscription_id` and
`requested_contract` were echoed into both a message string and a field,
bounded by nothing. Measured at exactly **2.00x and unbounded** — a 1,000,000-
character `cartridge` produced a 2,000,311-character reply. After: **561 bytes
flat at every input size.**

It costs more than its size: these replies are sent holding the send lock the
frame path shares, which is the starvation `CARTRIDGE-RESULTS.md` forbids in
Tower responsibility #3.

Bound **once** at the top of each handler rather than at each of the eight echo
sites. The audit that found this listed three fields and missed
`requested_contract` — which is the argument for a single choke point, made
concrete. Third copy of a 120-character guard that already exists twice, and
imported from neither: `ws.py`'s passes numbers through because it bounds a
numeric `seq`, and the Lab's lives inside a cartridge the result-channel core
is forbidden to import.

**Teardown.** `shutdown()` waited on each worker in turn while holding
`self._lock`, costing `N * (grace + TERMINATE_TIMEOUT)`. Measured with two
stubborn workers: **24.00 s, with a concurrent `status()` — what `/health`
calls — blocked for 23.95 s**, and two workers still alive at the end. The
waits now run together; every worker still gets its full grace window and the
same terminate-then-confirm sequence.

Asserted by **observed concurrency**, not wall time: a timing assertion would
measure the machine, and this suite already carries load-sensitive flakes.

## 7.7 Two CV Lab primitives — `0a755d7`

**Sharpness — taken.** `frame_quality` carried the exact
`Laplacian(CV_64F).var()` form the World Builder lane already removed from its
own frontend. Same-session A/B over 1,500 real corpus frames:
**1.4885 → 0.3173 ms per frame, 4.69x**, on a stage that runs synchronously on
the event loop when selected.

Exact, and verified rather than argued: `np.array_equal(Laplacian(g, CV_64F),
Laplacian(g, CV_16S))` held on 400 frames with an observed range of −538..392
against int16's ±32767, and the variance agreed to **5.053e-16** across all
1,500. Duplicated rather than imported, because the Lab must not import
another cartridge. Three tests pin the facts the exactness rests on, because
the way it breaks is silent: on colour input `meanStdDev` returns a
per-channel deviation and would report channel zero where `.var()` pooled all
three.

**Device — taken, for one experiment only.** Interleaved A/B, 480 timed frames
per device, 30 warm-up each so CUDA context creation is excluded, block order
alternated:

| | cpu | cuda | winner |
|---|---|---|---|
| `object_detection` | **29.41 ms** | 38.17 ms | CPU, in all 8 blocks |
| `depth` | 20.03 ms | **10.41 ms** | CUDA, in all 8 blocks |

Flipping `auto` globally — which is what the finding as reported implies —
would fix one experiment by making the other roughly twice as slow. Also
returns 196 MB of peak reserved VRAM that bought nothing. `TOWER_CV_DEVICE`
still overrides; provenance still reports `auto` as what was *asked*.

This **contradicts** `config.py`'s `scene_device` comment (ssdlite320 30.4 ms
CUDA vs 32.9 ms CPU, CUDA faster). That figure is **left standing rather than
edited** — it was taken on a harness this lane did not re-run, and two
independent measurements now disagree with it in the same direction. A
successor re-measuring should know both exist.

---

## 8–11. Candidates, judges, and the experiments that settled them

Every consequential candidate went to two independent judges. Where they
disagreed the disagreement was settled by experiment, never by preference.

**The Scene availability fix is the case worth reading.** Judge A endorsed
`find_spec`; Judge B rejected it for an eager import. The tie-break experiment
**contradicted both**:

- Judge B understated his own proposal's case on cost — he argued the 2 s was
  a price; measurement showed it is *moved*, not added (2.019 s → 2.002 s
  end to end).
- Judge B's broken-install objection to `find_spec` was **understated**, not
  overstated: the declaration never self-corrects.
- Judge A's 3% boot saving was real and irrelevant beside a 100%-reproducible
  double-cartridge loss.
- And the experimenter found what neither judge had: `find_spec` cannot fix
  the import race at all, because it never executes the module.

**Judges agreed on Document Memory and were both right**: REJECT, on grounds
neither the finding nor I had considered (§7.3, §16).

## 12. Optimize-in-place changes

All eleven commits are optimize-in-place. See §7.

## 13. Native extractions

**None.** No finding in either audit reached the bar.

## 14. Language migrations

**None attempted, none warranted.** See §23–27.

## 15. Deferred, with the evidence

| Item | Why deferred |
|---|---|
| **Per-session torch thread pool** (+19 threads, +8.1 MB RSS per Start/Stop, linear, reproduced through a real uvicorn child process) | The correct fix — reuse one worker thread, measured to remove it entirely at zero cost — restructures `live_session.py`, which holds three **reproduced and still-open** lifecycle races (integration findings 13/15/16) assigned to another lane. Doing thread-model surgery on top of unfixed races, without runway for the full protocol, would be reckless. **The proposed one-line mitigation was REFUSED on measurement** (§16). |
| **`process()` blocks the event loop** | Real and measured (39.5 ms object_detection, 13.4 ms depth against an 83.3 ms interval). Offloading is measured *free* in the product's shape, but the provenance handshake must move with it — `ws.py` reads it between `process()` and the `await` and that placement is the whole guarantee. Architecture change, not an optimization. |
| **Recorder does ~13 syscalls + 1 fsync per frame on the loop** | Independently found by both an audit and me. Moving it off-thread changes capture ordering and ownership semantics; `append_jsonl`'s heal-a-torn-line read is per-append by design. Wants its own lane. |
| **Stub worlds** — 83 of 120 corpus worlds are empty, minted by `stream_start` before the first frame; the default subscription rescans all of them at 2 Hz uncached (0.49 ms at 1 → 33.82 ms at 120) | The only cost in the audit that grows without bound in *install age*. Two changes (stop minting; cache in the `_FileCache` that already exists), both touching World Builder session creation. |
| **`capture_root` has no pruner** — ~2.1 GB/hour of walking, never pruned; derived records expire at 30 days, the photographs never | A retention decision for a human, sharpened by the Mac lane's note that the recorder's copy is also the unredacted one. |
| **Two JSONL stores rewrite per record and re-parse per request** | Real; one careful pass over `document_memory/store.py` and `object_memory/store.py`. |
| Mac F1 (`limit`) and F4 (geometry identifier) | Contract decisions owned by their lanes (§5). |

## 16. Attempted or proposed and REFUSED, with the measurement that refused it

**A reverted experiment is evidence.** These are recorded so nobody repeats them.

| Candidate | Verdict | The number that decided it |
|---|---|---|
| **`scene_torch_threads` default 0 → 2** | **REFUSED** | Not a fix (still linear, ÷19) and expensive: object_detection 26.91 → 49.11 ms (+83%), depth 19.73 → 55.01 ms (+179%). Under the shipped default, **20% of depth frames and 8.5% of object_detection frames exceeded the entire 83.3 ms interval**. Process-global, on a path that cannot yield. |
| **`find_spec` for Scene availability** | **REFUSED** | 0/6 on the import race; reports `available: true` for a broken install and never self-corrects |
| **Document Memory degrading without OCR** | **REFUSED** | `recogniser` is not persisted and `claim` is stamped on every document, so the result is permanently indistinguishable from OCR-on-a-blank-page; dedup also collapses 2 pages → 1 |
| **`cv2.magnitude` for the gradient chain** | **REFUSED** | estimated 5.36x, **measured 1.72x**, and parity only 2.203e-07 — float32 epsilon, not float64 agreement — on a *reported* metric |
| **Binary websocket frames** | **REFUSED** | base64-in-JSON measured at 0.086 ms/frame |
| **Replacing `compute_revision`'s deepcopy** | **REFUSED** | 0.127 ms, and the proposed replacement measured *slower* |
| **Whitelisting `session_id`** | **REVERTED** | reddened 11 tests; a legitimate derived tree can exist without a session record |
| **Inverting `client_safe_reason`** | **REFUSED** | would discard useful path-free messages and fail an existing test for the wrong reason |

## 17. Performance, before and after

**No aggregate percentage is offered, because the changes are on different
paths and adding them would be misleading.**

| Path | Before | After | Method |
|---|---|---|---|
| `/documents/search`, 800 docs | 356.92 ms | 14.18 ms | same-session A/B, alternating order, byte-equal scores |
| `frame_quality` sharpness | 1.4885 ms/frame | 0.3173 ms/frame | same-session A/B, 1,500 real frames, parity 5.05e-16 |
| `object_detection` under `auto` | 38.17 ms/frame | 29.41 ms/frame | interleaved A/B, warm-up excluded |
| `supervisor.shutdown()`, 2 stuck workers | 24.00 s | bounded by the slowest, not the sum | fake processes, observed concurrency |
| `/health` during that shutdown | blocked 23.95 s | not serialised behind N workers | same |
| result-channel refusal, 1 MB input | 2,000,311 bytes | 561 bytes | direct handler drive |
| Scene boot → running session | 2.019 s | 2.002 s | fresh processes; cost *moved* |

**Unchanged and verified unchanged:** the World Builder replay path (§17.1).

### 17.1 World Builder corpus replay — EXACT

Read-only replay of all 8 pinned real captures on this HEAD, against the
figures the integration report pins:

| Metric | Integration report | This HEAD |
|---|---|---|
| segments | 232 | **232** |
| keyframes | 1,712 | **1,712** |
| poses solved | 620 | **620** |
| poses refused | 860 | **860** |
| points | 71,122 | **71,122** |

Controls behaved: negative (pure rotation) 0 poses / 0 points; positive
(strafe) 4 poses / 1,499 points. Worst bbox blowup 11.01, legible 97,
drawable 98. 94.60 s.

**Exact on all five.** World Builder is bit-for-bit unregressed.

## 18. CPU

`frame_quality` and `object_detection` reduce per-frame CPU on the event loop
(§17). `shutdown()` no longer holds a lock across N serial waits.

**Measured and NOT acted on:** a scene session costs 18.60 cores at torch's
default on this 20-core host, 3.51 capped at 4, 1.78 capped at 2 — against
`config.py`'s recorded 4.12/1.03. The lane did **not** overwrite that figure,
because it was taken on a different harness this lane did not re-run. Also
measured but not acted on: `OMP_WAIT_POLICY=passive` took the same session
from 18.6 cores to **2.29** and host CPU from 100% to 32%, while making the CV
Lab slightly *faster* — most of that CPU is OpenMP spin-waiting, not
arithmetic. A promising separate lever, unvalidated for correctness here.

## 19. RAM and VRAM

- **VRAM: `object_detection` no longer reserves 196 MB peak to be slower.**
- **No VRAM leak**: 0.0 MB allocated/reserved after 8 CUDA Start/Stop cycles.
- **No Python-object leak**: `gc.get_objects()` flat across cycles.
- **Known, unfixed, quantified**: +19 threads and +8.1 MB RSS per live-session
  Start/Stop cycle, linear, no plateau (§15).
- BM25's new per-corpus dict measured at 0.96 MB against 5.55 MB of
  already-resident tokens.

## 20. Resource and leak findings

See §7.5 (orphaned followers), §7.6 (teardown), §15 (thread pool, capture
growth, stores), §19.

## 21. Concurrency findings

Teardown serialisation (§7.6, fixed); the torchvision import race (§7.3,
this instance fixed, class open); the three reproduced lifecycle races
(integration findings 13/15/16) **confirmed by this lane's audit and left to
their owning lane**.

## 22. Security findings

| Finding | Severity | Status |
|---|---|---|
| Unauthenticated traversal on both geometry identifiers | CRITICAL | **fixed** (§7.1) |
| `ImportError` disclosed the venv path and OS username | MAJOR | **fixed** (§7.4) |
| Unbounded echo amplification, 2.00x | MAJOR | **fixed** (§7.6) |
| A cartridge advertising capability it lacks | MAJOR | **fixed** (§7.3) |
| Orphaned producers polling forever | CRITICAL (resource) | **fixed** (§7.5) |
| `frames.py` emits a live heap pointer in a validation message | MINOR | recorded, not fixed |
| `client_safe_reason` still passes third-party messages | MEDIUM | documented in code (§7.4) |

## 23. C++ decisions

**No C++.** Nothing found in this audit is a tight numeric loop with a clean
boundary that is not already in compiled code. The native-hotpath lane's four
independent reasons are unchanged, and its toolchain finding still holds: no
MSVC, no Build Tools, no Windows SDK, no cmake, no ninja, no CI.

## 24. Rust decisions

**No Rust.** The candidates that would nominate it — bounded queues, worker
lifecycle, caches, long-running state — were all found to be **already bounded
and correct**, or fixable with one parameter. The result channel already has a
single slot with replace-not-append, a subscription cap, and pruned failure
counters. The one genuine resource defect (§15) is a *thread-reuse* fix in
Python, not an ownership problem another language would solve.

## 25. Python decisions

**Python stays, everywhere.** Every win in this lane was a bound, a cache, a
hoist, a thread hop, or a better library call. The single largest — 25.2x on
document search — is seven lines of Python removing an O(D²).

## 26. R / tooling decisions

**No R.** No analysis in this lane needed more than medians and a spread, and
adding a language to compute them would have been ceremony.

## 27. Other runtimes

**None considered seriously**, because no finding presented a problem a
different runtime addresses.

## 28. Parity and determinism evidence

- BM25: byte-equal scores on every A/B repeat; 63,028 comparisons, 0 mismatches
- Sharpness: elementwise-identical intermediate; variance parity 5.053e-16
- World Builder: **exact** on all five corpus metrics (§17.1)
- `/cartridges` HTTP vs socket: byte-identical, verified in the smoke
- Geometry: the legitimate request returns the same `geometry_revision` before
  and after the guard

## 29. Reviewer findings

Two reviewers on the mid-lane changes. **The most important finding was
against my own security fix** (§7.1): the containment was half a fix. Also
found: a junction false-refusal; `find_offer` missing a hop, so one of four
surfaces still named the wrong variable — **found independently by both
reviewers**; and three comments of mine that were wrong (a paragraph surviving
from a reverted approach that argued against the code beneath it; a figure
quoted from the wrong corpus; a missing concession).

Clean bills: BM25 correctness, `declare()` purity and byte-identity, the
`_BlockModules` helper's isolation, the `env=` strip, and 30 hostile vectors
against the containment guard that could not defeat it. **Neither reviewer
asked for a revert.**

## 30. Final system review

**Neither final reviewer gave a clean bill, and both top findings were
regressions this lane had introduced.** That is the most useful thing in this
section.

**Reviewer B, F1 (HIGH) — the concurrent shutdown stopped NOTHING on a raise.**
`ThreadPoolExecutor` raises `RuntimeError` when the interpreter is shutting
down and when the OS refuses a thread, and it raises *before* any worker is
stopped:

```
1 worker (fast path)   OK      stopped=[True]
3 workers (pool path)  RAISED  stopped=[False,False,False]
                               registry STILL HOLDS ['c0','c1','c2']
```

Invisible on a one-cartridge Tower, total on a two-cartridge one, and it
compounds with the leak in §15 — the state where shutdown most needs to work
is the state where a pool is most likely to be refused. **Fixed** with a
logged serial fallback.

**Reviewer A, F1 (HIGH) — two more identifiers bypassed the echo bound.**
`world_id` and `session_id` are declared eleven lines below where the guard
binds the other four, were type-checked only, and echoed verbatim: 2,000,000
characters in, **4,001,438 bytes back**. Worse than the path that was fixed,
because that subscribe SUCCEEDS — the string persists on the `Subscription`
and in `Subscription.target`, so `poll_once` re-serialises it every 0.5 s for
the life of the subscription. **This is precisely the "someone adds a ninth
call site next to the guard" failure the guard's own comment predicts.**
**Fixed**, with `None` preserved as absent.

Also fixed from their reports: `detach()` made concurrent (a three-worker
detach blocked `capture_closed` — which runs ON THE EVENT LOOP — for 5.60 s);
the `world_id` whitelist replaced by the O(1) rule after Reviewer B showed the
reasoning behind it was wrong, not merely expensive; `_read`'s canonicalisation
made to actually work (**the first fix for it changed a local and did nothing,
and the test written for it passed vacuously because httpx normalises `/../`
out of a URL path**); `ResultHub._failures` genuinely pruned every pass; and a
`39-179%%` literal in a single-argument `logger.info`, which applies no
`%`-formatting and so reached the operator with the doubled sign — on the one
line that exists to stop them capping torch threads into a regression.

**Recorded, not fixed:** a fifth hard-coded scene-unavailable wording at
`results/__init__.py:136` (currently unreachable); two HTTP surfaces that still
echo unbounded ids; and Reviewer A's F7 — a walk whose socket stays open but
quiet for over 15 minutes would lose its follower to the new idle bound, with
no respawn. That last one is the sharpest open question about §7.5's value.

Between them the reviewers exercised, rather than reasoned about: the four-hop
Scene reason on all four surfaces under a torch block; the real spawned argv
through both scripts' own parsers; a real follower returning after exactly
3599 sleeps and chaining across a reconnect after 750 s of silence; 30 hostile
path vectors with zero escapes; BM25 identical to 12 decimal places against
`989c451^` over 400 page-length documents; sharpness bit-identical on 75 real
frames; HTTP/socket byte-identity; VRAM returning to exactly 0.00; repeated
app lifespan at **+0.00 threads, +0.00 handles, 0 children over 12 cycles**;
and an independent full corpus benchmark reproducing all five pinned figures.

Full reports: `finalA/FINAL-A.md`, `finalB/FINAL-B.md` in the run scratch.

## 31. Final test results

| Check | Baseline | Final |
|---|---|---|
| Full Tower suite | 2160 passed, 64 skipped, 357.26 s | **2200 passed, 68 skipped, 344.42 s** |
| `-m slow` | — | **23 passed, 10 skipped** |
| `unified_cartridge_smoke.py` | — | **57/57** |
| `unified_cartridge_smoke.py --with-models` | — | **69/69** |
| World Builder corpus, 8 captures | pinned figures | **exact on all five** |

**40 net new tests**, every regression test proven RED against the defect it
covers before the fix landed. The 4 extra skips are new opt-in model tests.
The smoke figures match the integration report's 57/57 and 69/69 exactly.

**One known flake, not re-run until green.**
`test_result_channel_hostile.py::test_the_channel_survives_the_world_vanishing_mid_subscription`
failed once under concurrent agent load with `PermissionError: [WinError 32]`.
It passes **3/3 in isolation**, it did not recur in any full run, its own
docstring documents the open-handle hazard, and the native-hotpath lane
recorded the identical flake. Nothing in this lane opens a file handle that
would widen the window.

## 32. Known limitations

- The torch thread-pool leak is **real, measured and unfixed** (§15).
- The torchvision import-race *class* survives with Scene off (§7.3).
- `client_safe_reason` still passes third-party exception messages (§7.4).
- The `auto`-device change rests on two measurements that contradict a third,
  older one which was left standing (§7.7).
- The 900 s idle bound is reasoned from existing constants, not from a
  long-running physical trial.
- **Nothing here was physically validated.** No glasses, no phone.

## 33. Deferred opportunities

See §15, in rough value order: the thread reuse; `process()` offload; the
recorder's per-frame syscalls; stub worlds; the capture pruner; the two JSONL
stores; `OMP_WAIT_POLICY` (§18).

## 34. Components intentionally left unchanged, and why

**This is the section the brief cares most about, and it is long on purpose.**

- **World Builder** — the largest and most expensive subsystem in the backend,
  and **nothing was changed in it**. Its replay is already 79% inside compiled
  code, its redaction already runs only on accepted keyframes, its sharpness
  win was already taken, and its corpus figures reproduce exactly. The right
  answer was to leave it alone and prove it was unharmed.
- **`results/publisher.py`** — 0.5 s poll, computed off-thread, one snapshot
  per distinct target, single-slot replace-not-append, bounded sends, failure
  counters pruned. Already correct.
- **`results/envelope.py: json_safe`** — suspected as a per-send deep copy;
  measured at 0.127 ms and KEPT, and the proposed replacement was *slower*.
- **`frames.py`** — suspected of a wasteful base64/PIL round trip; measured at
  0.086 ms/frame and KEPT.
- **`results/world_builder.py`** — already has `(size, mtime_ns)` fingerprint
  caching with a bounded entry count.
- **`LiveSession`'s single-slot pending frame** — already the right design: a
  busy worker drops rather than grows.
- **Lifespan teardown ordering** — already correct and already off-thread.
- **The `experiments/depth.py` device choice** — `auto` already picks right.
- **Object Memory's model** — the lane's own research tension is unresolved on
  purpose and was not touched (integration report §11).
- **Redaction ordering, privacy filtering, identity semantics** — preserved
  decisions, untouched.
- **`storage.py`** — its win was already taken; `orjson` stays refused.

## 35. Commits

```
<final> fix(results,geometry): the second final reviewer's findings, acted on
b4d626e fix(capture,results): a refused thread pool must not mean a refused shutdown
0a755d7 perf(cv-lab): exact cheaper sharpness, and auto picks the faster device per experiment
4dd9f25 fix(runtime,contracts): bound an echoed identifier, shut down concurrently, and the reviewers' findings
8601621 fix(security): complete the geometry containment -- world_id escapes too
a73e26a fix(capture): arm the idle bound both worker specs promised and neither passed
d6f8920 fix(security): an ImportError on the wire no longer names the file it failed in
8225105 fix(scene,contracts): stop offering Scene Understanding a host cannot run
989c451 perf(document-memory): hoist BM25 document frequency out of the scoring loop
bc9baa3 fix(security): contain session_id on the two geometry HTTP routes
13d308f (base)
```

## 36. Push status

All pushed to `origin/optimization/backend-runtime-fitness-v1`. **Not merged.**
No other branch was modified, force-pushed, or rebased. `ios/` untouched.

## 37. Working tree

Clean.

## 38. Temporary resources

Everything created by this lane lives under the job scratch directory
(`C:\Users\tvllo\.claude\jobs\c78c3eab\tmp\`) — harnesses, agent reports, suite
logs, and the corpus-replay JSON. **Nothing was written under `C:\` or
`C:\Users\tvllo\` directly, and no worktree, clone or scratch repository was
created.** The real capture corpus in the main checkout was read and never
written. The corpus benchmark writes derived output to its own temp directory.

---

## What I would do first

**The torch thread-pool leak** (§15). It is the only measured, unbounded
resource growth left on the product path, the fix is known and proven to work
completely, and it is one careful pass — but it must be taken *together with*
integration findings 13/15/16, because it is the same file and the same
method's ordering. One lane, four defects, one set of tests.

**Do not take the thread cap instead.** It is the intuitive shortcut and the
numbers say it trades a leak for dropped frames.
