# Overnight autonomous run — continuation handoff

**Live document.** Updated as the run proceeds, not reconstructed at the end.
If context is lost, a successor session can resume from this file plus
`git log` without replaying the conversation.

**Branch:** `integration/world-builder-lifecycle-v1`
**Run started from:** `3998e5a`
**Last updated:** 2026-08-26, after the Scene Understanding tracker retune
**Suite at last update:** 1444 passed, 30 skipped, 0 failed

`main` is untouched at `35214a1`. Nothing has been merged or pushed.

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
  leading hypothesis is Windows file locking — the test unlinks
  `world.json` while a subscription is live, and `unlink()` raises
  WinError 32 if a handle is open at that instant. `read_json_closed()`
  already narrows that window, which fits a rare race rather than a
  broken test. **This is a hypothesis; the traceback was never captured.**
  Next occurrence, capture it with `--tb=long` before doing anything else.

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
