# Overnight autonomous run — continuation handoff

**Live document.** Updated as the run proceeds, not reconstructed at the end.
If context is lost, a successor session can resume from this file plus
`git log` without replaying the conversation.

**Branch:** `integration/world-builder-lifecycle-v1`
**Run started from:** `3998e5a`
**Last updated:** 2026-08-26, after the lifecycle ruling and the corpus
harness fix
**Suite at last update:** 1533 passed, 30 skipped, 0 failed

`main` is **untouched at `35214a1`**, locally and on origin. Nothing has been
merged to it.

**The integration branch HAS been pushed** — `origin/integration/world-builder-lifecycle-v1`.
Two fast-forward pushes, no force, no rebase, both lanes' commits intact.
This changed on 2026-08-26 when iOS ownership moved to a Mac lane that needs
to pull Tower work. **Fetch before every push and check whether the remote
advanced**; if it has, integrate rather than force.

**iOS is owned by the Mac lane.** This lane does not modify `ios/`. Tower
work that creates an iOS requirement is written to
`docs/agent-handoffs/IOS-EXECUTION-PLAN.md`, which is the single current
iOS document.

---

## 1. How to resume in one minute

```bash
cd C:\Users\tvllo\Projects\Glasses
git log --oneline 3998e5a..HEAD          # everything this run did
cd tower && ./.venv/Scripts/python.exe -m pytest -q
```

**Never pass `--timeout` to pytest.** `pytest-timeout` is not installed; the
unrecognised argument aborts collection before any test runs, and a piped
`tail` masks it as exit code 0. This has bitten twice.

Orientation documents, in reading order:
1. `tower/docs/superpowers/research/2026-08-25-cartridge-evidence-map.md` —
   what exists across all nine cartridges. Has a dated "superseded" block.
2. `docs/agent-handoffs/WORLD-BUILDER-STATUS.md` — World Builder closeout and
   physical gates P1–P11.
3. `docs/agent-handoffs/WORLD-BUILDER-MAC-HANDOFF.md` — the iOS validation doc.
4. This file.

---

## 2. Environment — what changed and why it matters

| | |
|---|---|
| Python | 3.12.5, venv at `tower/.venv` |
| GPU | RTX 5070, **Blackwell sm_120**, driver 596.21 |
| torch | **2.13.0+cu132**, CUDA verified *executing*, not just `is_available()` |
| torchvision | 0.28.0+cu132 |
| easyocr | 1.7.2 (pulled scikit-image, which un-gated 12 redaction tests) |
| cv2 | 5.0.0 headless — **one** cv2, verified |
| numpy | 2.5.2 |
| timm | **1.0.28**, added 2026-08-26 for MiDaS. Verified it did NOT disturb torch: still `+cu132`, kernel executing on `sm_120` |

**The trap, documented in `pyproject.toml`:** a bare `pip install .[ml]`
resolves **CPU-only** torch from PyPI on Windows. It imports, it runs, and it
silently turns every GPU figure into a CPU figure. That is how this venv was
found. Both torch and torchvision are pinned *with the cu132 index in the
comment*.

General web search still recommends "nightly cu128 or WSL2" for Blackwell.
That is stale — cu128/cu129 were removed from the build matrix. The answer was
already in this repo's own history (`V0.9.1-depth-cv-baseline-report.md`).

---

## 3. Completed this run

### World Builder — IMPLEMENTATION COMPLETE, MAC + PHYSICAL VALIDATION PENDING

- **Geometry transport**: manifest + per-segment chunks over HTTP, content-hash
  cached, `world_builder.geometry/2026-08-25`. Geometry is *not* on the
  WebSocket because the result sender shares an `asyncio.Lock` with the frame
  path and `points.json` is 1.07 MB against a 3,884-byte snapshot.
- **Behind-the-journal geometry is served with `current: false`** rather than
  404'd. Without this the gallery stayed empty for an entire capture and only
  populated after Stop — the headline feature silently not working while every
  test stayed green.
- **Tracking fixed.** The tracker was losing *reach*, not losing the image: 47
  of 50 declared losses still had survival above the floor. Reference staleness
  (max 89 frames) meant the tracker was asked to cross the whole gap in one LK
  call. `LK_MAX_LEVEL` 3→4, `FORWARD_BACKWARD_MAX_PX` 1.0→3.0.
  **Five real captures: 151→114 segments, poses 211→265, points 27,406→42,100.**
- **Grace window shipped disabled**, and this is the important one — see §6.
- **Cross-segment registration.** 51 segments, 19 with geometry, **3 registered
  (4, 5, 32) carrying 31.1% of points**. Refuses (30,50) and (5,6).
- **`support.json`** — landmark association persisted separately from
  `points.json` (0.435× its size) so the pinned schema and wire contract were
  untouched.

### Object Memory — FIRST SLICE COMPLETE, reviewed and fixed

Had a data layer and no producer, and had been considered blocked on an
architectural ruling. **That blocker gates registering as a live in-process
`Module`; every other cartridge produces out of process by tailing a capture
journal.** Object Memory now does the same, so the ruling is untouched and
still pending for whoever needs a live module.

- **55 observations from 9,199 real frames** (29 laptop, 26 cell phone).
- **Zero `person` records.** The whitelist is enforced at the store, not only
  the filter — a review found `append()` accepted a `person` record directly.
- **Retention is now a real promise.** A reader could previously pass
  `--retention-days 3650` and be served expired records. The window is
  persisted in a manifest and every read clamps to `min(persisted, requested)`.
- **Confidence follows the evidence**: 19 high/36 medium → 50 high/5 medium,
  and the remaining 5 are genuinely weak (best 0.721–0.794), not a tautology.

**Object Memory now has a wire path — its first.** `tower/routes/observations.py`,
registered as the fifth router. Two GET endpoints,
`/object-memory/observations` and `/object-memory/last-seen/{object_class}`,
both sync `def` so the disk read stays off the event loop.

- **Read-only by construction.** `purge()` and `prune_expired()` are
  unreachable from the wire, guarded by an AST test. Deletion stays in the
  CLI where a human types it — an unauthenticated HTTP endpoint that erases
  a user's memory is not a feature.
- **Retention cannot be widened over HTTP.** Verified by the controller
  against a real corpus copy with one record backdated 40 days: 3650 days
  and 0 ("forever") both return **54, not 55**, reporting
  `effective_days: 30.0, clamped: true`. Narrowing still works.
  **Retention keys on `recorded_at`, not `observed_at`** — it measures how
  long *we* have held the record, not when the event happened. (The
  controller's first check backdated the wrong field and had to be redone.)
- **The payload refuses to overclaim.** It carries `claim:
  "category-was-visible-once"`, `identity: "category-not-instance"`,
  `absence_means: "not-observed-by-this-cartridge"`, and an explicit
  `spatial_ref: null`. "Where" is a **frame reference** — session, frame_seq,
  camera — a pointer into a recording, **not a place**. Nothing in this
  cartridge knows where anything is in a room.
- Booleans verified as JSON `true`/`false` on the wire, not `1`/`0`.

**The iOS surface now exists, UNCOMPILED.**
`ios/Glasses/Workspaces/ObjectMemory/` — model, copy, client, view — plus
`ObjectMemoryTests.swift`, registered in `project.pbxproj` at all four
points. (App sources need no registration: that target uses a
`PBXFileSystemSynchronizedRootGroup`, which is why existing files like
`ContentView` are also absent from the pbxproj. On inspection this looks
like a defect and is not.)

**Its honesty is enforced, not reviewed.** The view holds **no
user-facing string literal** — verified; the only literal is an SF Symbol
name. All copy lives in `ObjectMemoryCopy`, and the tests sweep that same
source, so what is rendered and what is tested cannot drift apart. The
sweep covers chrome as well as records, because "Find my laptop" on a
button would walk straight past a test that only read record rows, and it
asserts the string set is non-empty first — the guard against the vacuous
pass this run shipped twice.

Found: *"A laptop was visible ... A category was in view once. That is the
whole claim: it does not say anything about now, and it cannot tell one
laptop from another."* Empty: distinguishes "no record within the window
it can see" from a class never looked for, whose *"absence carries no
information at all."*

### Module lifecycle — RULED AND IMPLEMENTED, then adversarially reviewed

The decision gate that had been open all run (§4's "needs a human ruling")
was **ruled E+A by this lane** on 2026-08-26 under an explicit autonomy
grant: research had already resolved it with five costed options and a
recommendation. Reversible; **B remains the V1.1 destination.**

- `asyncio.wait_for` **cannot interrupt synchronous work**, so the 10 s
  lifecycle timeout was fiction for any module that loads a model.
- **`LOAD_TIMEOUT_S = 120.0`**, derived not chosen: a cold depth load fetches
  **119.0 MB**, needing ~95 Mbit/s to fit in 10 s — so 10 s meant deterministic
  first-run failure. Warm loads measure 1.80 s (depth, CUDA) and 0.16 s
  (SSDLite), so 120 s is ~65x real cost and still a real bound.
- `tower/loading.py` adds `LoadInvalidation`, fixing an **ordering** bug: on
  timeout the orphaned loader would otherwise install a model into an
  already-released module — on CUDA, holding VRAM nothing would ever free.

**An adversarial reviewer then confirmed six findings.** The core
check-and-assign guarantee holds and the orphan path genuinely frees
(weakref probes inside `empty_cache`). What failed is everything around it —
most seriously that `main.py:212` runs the load under `asyncio.run`, whose
executor shutdown **joins the orphan**, so the bound does not bound startup
at the only place it runs. Full list and evidence:
`research/2026-08-26-lifecycle-adversarial-findings.md`.

### The corpus harness was summing almost every rate

`_RATE_METRICS` was an allowlist that **silently summed anything unnamed**.
8 of 11 entries were dead names; 15 rate-like metrics were summed. Fixed by
moving classification to the experiments (a factory cannot be registered
without a declaration) and making an unclassified metric **an error, not a
default**. Four kinds: RATE, COUNT, CONSTANT, UNAGGREGATED.

Proof on real data: `tracked_fraction` **7,468.205 -> 0.8118** for a quantity
that cannot exceed 1. **No published figure was contaminated** — checked;
the only corpus-scale published run was `object_detection`, whose three rate
metrics were the three live entries.

### Document Memory — PREMISE FALSIFIED

Implemented, 145 tests, and **never ran on a real frame** until this run.

- **Detection fires 6 times in 9,199 frames. All six are false positives** —
  one venetian blind, five backlit keyboards. Zero characters recovered.
- **Detection, not recognition, is the binding constraint** — the inverse of
  what its own module doc claimed.
- The glyph gate's margin was a **renderer artefact**: blinds/keyboards measure
  0 transitions synthetically and **8.0 / 19–23** on real frames against a
  threshold of 8.
- Its recall table was measured in **landscape geometries DAT cannot produce**.
- **No capture contains a sheet of paper.** The cartridge has never had a
  chance to succeed.

### Scene Understanding — CONSTANTS RE-DERIVED

Its tuning was written against an **assumed ~3.3 fps**. The corpus measures
**11.97 fps (83.5 ms)** — 3.6x faster — so every constant expressed in frames
meant something other than what its comment claimed.

- **`max_misses` 5 -> 12.** Documented as "roughly 1.5 seconds of absence";
  at the real rate it was **0.42 s**. A person occluded for half a second got
  a new track ID and was **recounted** — landing squarely on the cartridge's
  headline capability.
- It is now `frames_in(MAX_ABSENCE_S)` with `MAX_ABSENCE_S = 1.0`, not a
  literal. If the frame rate changes, the constant follows.
- **Counting improved and regressed nowhere.** Detector dropout 0/10/20/40/60%:
  before 1.000/1.000/1.000/0.939/**0.252**, after 1.000/1.000/1.000/0.965/**0.783**.
- **`min_iou` 0.25 and `min_hits` 3 kept, but newly derived** — the floor that
  retains >=99.5% of true associations per label, and a two-sided derivation
  (4 regresses dropout at every non-zero rate, 2 doubles phantom frames).
- **Orientation cadence** `2.0 s` -> **0.2505 s** = stride 3 x 0.0835 s, where
  stride 3 is `TrackerPolicy.min_hits`: estimating facing more often than a
  track can be confirmed buys nothing.
- **The trade, named:** a departed track now stays confirmed 1.0 s instead of
  0.42 s, so it can be falsely reported present for longer. Capped at 12
  because 18 and 24 frames measure *identically* on count stability — going
  longer would assert more with nothing measurable to show.
- **Caveat:** corpus `person` boxes are the wearer's torso. `cell phone`
  (small, external, 0.842) is the proxy that set `min_iou`. Bystander tracking
  accuracy remains unmeasurable here.

### Supporting work

- `scripts/capture_corpus_benchmark.py` — the first harness that runs anything
  over the real corpus. Sums counts and averages rates separately.
- Real-corpus measurement: the `person` detections are **the wearer's own
  torso** (median box bottom edge 0.981, 59% touching the frame edge). This
  corpus is not a bystander-perception validation set.
- `TRACKED_CLASSES` is wrong: `dining table` appears **once** in 9,199 frames,
  while `cell phone` at 0.844 — the most reliable class — is untracked.

---

## 4. Verification gates — nothing below has happened

### Mac / Xcode (MAC VERIFICATION REQUIRED)

**66 iOS tests written, 0 executed. No Swift on this machine has been
compiled by anything.** Full detail, including the six compiler-sensitive
areas and what Mac Claude may fix without redesigning, is in
`docs/agent-handoffs/WORLD-BUILDER-MAC-HANDOFF.md` §7–9.

### Physical — P1 to P11

Enumerated in `docs/agent-handoffs/WORLD-BUILDER-STATUS.md` §2. The three that
matter most:

- **P3** — do fragments appear *during* a walk. The entire claim.
- **P11** — **the highest-leverage experiment available.** 16 of 19 segments
  are refused because the wearer stood still, so scale is unobservable. A walk
  where the wearer *sidesteps* rather than pans should raise the registrable
  fraction. It tests a prediction rather than gathering data.
- **P7** — whether redaction fires on real bystanders. **Unanswerable with the
  current corpus**, which contains the wearer and no one else.

### Two that need a human ruling, not more research

- **The module lifecycle execution model.** `_do_load()` loads a detector
  synchronously and `asyncio.wait_for` cannot interrupt sync CPU work, so the
  10 s timeout is fiction. Five options costed in
  `plans/2026-08-20-object-memory-first-slice.md:826-896`. Sidestepped, not
  solved — it still gates any *live* module.
- **The `person` ruling.** Whether Object Memory may persist a record per
  detected bystander. Sidestepped by the whitelist. The corpus finding
  *reframes* it (most "people" are the wearer) but does not settle it.

---

## 5. Known limitations, carried forward

- **Registration composition has no independent check.** The confident subgraph
  is a 3-node path with no cycle, so nothing validates the spanning-tree
  composition. Cycle-consistency is the first thing to add when a cycle exists.
- **Reprojection error cannot police registration.** (30,50) fits at 1.62 px
  with 88% of points under 3 px while being **3.2× wrong on scale**. Admission
  rests on independent agreement only.
- **`session_id` + `frame_seq` resolves to retained raw JPEGs** outside Object
  Memory's retention. Records now tag `frame-referenced`, but capture-side
  retention is the real fix and does not exist.
- **One flaky test, observed once and not reproduced.**
  `test_result_channel_hostile.py::test_the_channel_survives_the_world_vanishing_mid_subscription`
  failed in one full-suite run on 2026-08-26 and passed in the next, plus
  5/5 alone and 18/18 in its own file. **Do not "fix" it by weakening the
  assertion** — it guards against fabricated results, which is the last
  thing that should be softened to get a green run.
  Not a timeout: `drain()` blocks by design and `pump()` is synchronous
  over the portal, precisely so timing cannot decide the outcome. The
  hypothesis was Windows file locking, and it is now **CONFIRMED**: a
  later full-suite run surfaced it as **WinError 32**, the sharing
  violation raised when `unlink()` meets an open handle. The test unlinks
  `world.json` while a subscription is live, which is deliberate — that
  is the case it exists to cover. `read_json_closed()` already narrows
  the window, which is why it is rare rather than constant.
  **It is a real Windows race in the test, not a defect in the result
  channel**, and the fix is to make the unlink tolerate a transient
  sharing violation — never to soften the assertion that follows it.

- **`data/captures/` is never pruned.** 9,199 real frames with no retention
  policy governing them.
- 21 deferred World Builder findings, triaged in
  `plans/2026-08-25-geometry-transport-followups.md`.

---

## 6. Mistakes made this run, and the rules they produced

Recorded because the reasoning is worth more than the fixes.

**I optimised a proxy without measuring the product outcome.** Shipped
`loss_grace_frames=3` on segment count alone (130→99 across eight captures)
and called it "cheaper than what it replaces rather than a trade". The full
solve said otherwise: poses 265→178, points 42,100→27,262 — **a third of the
reconstruction destroyed to buy 18 segments.** The research had explicitly
warned that anything reporting segment count must report `poses_solved` and
points beside it. Reverted; the reasoning is pinned in a test.

→ **Rule: a tracking change is measured by a full end-to-end solve, never by
segment count.**

**I wrote tests that could not fail — twice.** One asserted survival above a
floor on a *white-noise* image, where the pyramid destroys structure, so it
passed *more strongly with the feature deleted* (0.698 at level 0 against
0.127 at level 4). Another imported the function under test and never called
it, asserting against its own inline recomputation.

→ **Rule: every guard must be shown to fail when the production code is
broken. Mutation-test the important ones.**

**I put a confounded claim in a production comment as proof.** Cited rising
solvable-pair fraction and triangulation angle as evidence no bad tracks were
admitted. Fewer segments means longer segments means wider-baseline pairs, and
triangulation angle rises with baseline *by construction*. Retracted in place.

**I ran two implementation agents concurrently on one worktree.** They
collided on `pyproject.toml` and one did `git stash`/`checkout` under the
other. Committed history survived — verified commit by commit — but by luck.

→ **Rule: one implementation agent per worktree at a time. Research agents may
run in parallel.**

**Reports describe intent; files describe what happened.** Checking the
artifact rather than the summary caught three defects: the vacuous test, a
`registered: 1` serialisation that would have failed every Swift `as? Bool`
decode, and a confidence field that never received its upgrade.

---

## 7. Next execution order

1. ~~Shared detector promotion~~ — **done**, `tower/detection.py`.
2. ~~Scene Understanding cadence and tracker constants~~ — **done**, above.
3. **Re-derive `MIN_ROW_TRANSITIONS`** against the 9,199 real negatives — in
   flight. Document Memory's gate was tuned on a renderer and fires only on
   blinds and keyboards. Note the honest ceiling: **no capture contains a
   sheet of paper**, so a correct gate cannot make the cartridge work — it can
   only stop it being wrong.
4. **Object Memory iOS surface.** The cartridge has no product surface at all.
   This is now the largest *product* gap that needs no hardware and no ruling.
5. **Measure depth on real frames.** Needs `timm`. Scene Understanding refused
   `in_front_of`/`behind` on a **synthetic** 6–8% flicker measurement.
   Orientation is already measured (43.4 ms CUDA, not the feared 798 ms).
6. **Scene Understanding wire path.** Blocked on the live-module route, which
   is blocked on the lifecycle ruling. Its status wording currently blames
   persistence, which sends readers toward the wrong fix.

**Do not start:** Environmental Memory (its own design says do not begin, and
six of its seven prerequisites are not engineering), Translator or the voice
halves of Visual Q&A and Accessibility (**no audio path exists anywhere** —
`frames.py` accepts JPEG only and `Module.process()` takes one still image).
