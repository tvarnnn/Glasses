# Weekend Autonomous Run — Report — 2026-08-20

Executed against
`docs/superpowers/plans/2026-08-20-weekend-autonomous-development-master-guide.md`
after explicit user greenlight. 15 commits, `f664210..da7e01e`, all on
`master`. Working tree clean; full suite `130 passed, 3 skipped`.

---

## What was completed (against Master Guide §17)

### MUST — all complete

| # | Item | Status |
|---|---|---|
| 1 | V0.9.2's three autonomous-safe fixes, each its own commit, with regression tests | ✅ `36e7d43`, `eb34b12`, `f38d192` (+`d1e7c1f`) |
| 2 | Confirm whether real-motion footage is obtainable | ✅ Resolved: **not obtainable locally**; substitute dataset ruled in with a hard acceptance gate |
| 3 | `depth_temporal_consistency` (Experiment 1) | ✅ Measured, reported, raw data committed |

### SHOULD — all complete

| # | Item | Status |
|---|---|---|
| 4 | `feature_trackability` (Experiment 2) | ✅ Measured, reported, raw data committed |
| 5 | Object Memory design/spec review + implementation plan | ✅ `docs/superpowers/plans/2026-08-20-object-memory-first-slice.md`, reviewed and revised |

### STRETCH — one complete, one deliberately stopped

| # | Item | Status |
|---|---|---|
| 6 | Begin Object Memory implementation | ⛔ **Deliberately not started.** Blocked at the plan's Task 4 decision gate — see Stop Conditions. |
| 7 | `source_seq`/`tx_seq` Tower-side prep + Mac handoff | ✅ `0346c05`, `6d44c53` |

### Explicitly out of scope — all respected

World Builder Experiments 3–4 (blocked on intrinsics, **no substitute
intrinsics were fabricated**), Document Memory, Environmental Memory,
Hermes Agent, TensorRT/CV-CUDA/DeepStream, iOS/Swift changes (a handoff
document was produced instead), and the two "needs user judgment" items,
which were preserved and documented rather than patched.

---

## Measured results

### Experiment 1 — `depth_temporal_consistency`

Full report: `V0.9.3-world-builder-experiments-1-2-report.md`.
Raw: `data/V0.9.3-experiment1-depth-temporal-consistency.json`.

150 frames sampled at 16.67 fps from EPIC-KITCHENS-100 `P01_107`, CPU,
analysed on MiDaS-small's 128×256 output grid.

- **Raw flicker: `mad_mean` 0.0633–0.0761** across three independent
  normalization strategies (min-max, 1–99 percentile, median/MAD) —
  6–8% of full depth range between consecutive frames, worst regions
  (p95) 0.19–0.23. The agreement across normalizers is what makes this
  trustworthy; min-max alone is outlier-fragile.
- **EMA α=0.3 is the best cheap mitigation: 42–53% flicker reduction**
  (50.35% on min-max), at **3 frames ≈ 180 ms** of measured
  step-response lag.
- **Short-window stability improves 38%** (`local_temporal_std`
  0.0749 → 0.0463), i.e. the estimate does settle at ~0.3 s timescales.
- Per-frame experiment cost 31.31 ms (CPU, warm-up excluded) — not a
  CPU/GPU comparison.

### Experiment 2 — `feature_trackability`

Raw: `data/V0.9.3-experiment2-feature-trackability.json`.

- **100% of consecutive-frame pairs clear 30 RANSAC-verified inliers**
  (mean 386.5, inlier ratio 0.885) at ~6.6 ms/frame CPU. The research
  pass's biggest open risk — that casual wearable motion lacks trackable
  structure — **is not supported by this footage.**
- **But 53.69% of those pairs are rotation-dominant** by ORB-SLAM's
  `R_H ≥ 0.45` criterion — degenerate for triangulation. Decays to
  41.22% (k=2), **12.41% (k=5)**, 11.72% (k=10).
- **Conclusion for future pose work:** parallax, not match count, is the
  binding constraint at short baselines.

### Test/build state

- `python -m pytest -q` → **130 passed, 3 skipped, 0 warnings**
  (from 98/3/1 at session start; +32 tests, and the 1 pre-existing
  warning eliminated).
- The 3 skips are the pre-existing opt-in model-integration tests. Run
  explicitly with `TOWER_RUN_MODEL_TESTS=1`: **3 passed** — verified, not
  assumed, since `ws.py` and `depth.py` both changed.
- `pip check` → no broken requirements.
- End-to-end smoke test against a real uvicorn server (not just
  TestClient): malformed messages survive, `frame_result` works,
  `frame_error` fires for undecodable frames and for missing-`seq`
  frames with `seq: null`, `tx_seq_gap_total` reports a real number.

---

## Autonomous decisions made

Per §22, each records issue, evidence, ruling, alternatives, and cost if
wrong.

### 1. Use a public dataset as feasibility input for Experiments 1–2

- **Issue:** MUST item 2 gates the whole World Builder track on real-motion
  footage.
- **Evidence:** No webcam hardware (all `cv2.VideoCapture` indices fail);
  no video assets in-repo; V0.7's only real-motion capture was Mac-side;
  GTEA Gaze+ (glasses-mounted, the ideal match) has a dead host (NXDOMAIN).
- **Ruling:** Use a bounded window of EPIC-KITCHENS-100 `P01_107`
  (head-mounted GoPro, CC BY-NC 4.0) as *feasibility evidence only*, with a
  hard acceptance gate requiring both experiments to be re-run on real DAT
  footage before any conclusion counts as validation.
- **Alternatives:** TUM RGB-D freiburg1 (has ground truth, but handheld
  lab motion — the wrong regime, and neither experiment needs its ground
  truth); GTEA Gaze+ (dead); synthetic motion (excluded — would not answer
  the question honestly).
- **Cost if wrong:** Low and bounded. No production code depends on the
  results; re-running is one command per experiment. The real risk is
  over-confidence, which the acceptance gate exists to prevent.
- **Recorded in:** `docs/superpowers/research/2026-08-20-world-builder-dataset-selection.md`

### 2. Verified Experiments 1–2 do not need camera intrinsics

- **Issue:** The intrinsics gap was assumed to block the World Builder
  track generally.
- **Evidence:** Experiment 1 involves no geometry. Experiment 2's RANSAC
  verification uses the fundamental matrix and homography, neither of
  which requires calibration; only `recoverPose` does.
- **Ruling:** Run 1 and 2; keep 3 and 4 blocked. **No substitute
  intrinsics were invented** — a guessed focal length yields a
  plausible-looking, meaningless trajectory.
- **Cost if wrong:** None identified; the claim is checkable from the
  OpenCV API contract.

### 3. torchvision, not ultralytics/YOLO, for Object Memory's detector

- **Evidence:** torchvision 0.28.0 (already installed via the `ml` extra)
  exposes `ssdlite320_mobilenet_v3_large` with COCO weights — verified
  directly.
- **Ruling:** Use torchvision. Adding ultralytics would mean a new
  dependency *and* an AGPL-3.0 obligation for zero measured benefit
  (Rule 17).
- **Cost if wrong:** Low — if measured accuracy on real footage proves
  inadequate, the detector is one file behind a stable interface.

### 4. JSONL, not SQLite, for the first persistence layer

- **Evidence:** The canonical-memory research explicitly sequences
  SQLite + `sqlite-vec` behind a *measured* need.
- **Ruling:** JSONL. The "file stays small" assumption is named in the
  plan as the trigger to revisit, and Task 8 measures it.
- **Cost if wrong:** Moderate but contained — a migration of a
  single module's own store, which is why the plan adopts a stable
  record shape from day one.

### 5. Reverted my own `httpx` removal

- **Issue:** After swapping to `httpx2`, I uninstalled `httpx` to "finish"
  the job.
- **Evidence:** Experiment 1's run surfaced
  `Error importing huggingface_hub.hf_api: No module named 'httpx'`;
  `pip check` confirmed `huggingface_hub 1.28.0` (transitive via `timm`)
  requires it.
- **Ruling:** Reinstall `httpx`; both coexist. Documented in
  `pyproject.toml` so the mistake isn't repeated.
- **Cost if wrong:** None — this *was* the wrong call, caught and fixed.

### 6. Corrected and re-ran the experiments after review

- **Issue:** A code review showed three Experiment 1 metrics could not
  support the report's conclusions.
- **Ruling:** Fix the measurement code, re-run, and rewrite the report
  with a "Corrections from the first draft" table listing the superseded
  numbers, rather than silently replacing them.
- **Cost if wrong:** None — this strictly increased the evidence base.
  Details below.

---

## Corrections made to my own work

Recorded prominently because two of them were claims I had already
committed.

| What I got wrong | Correction |
|---|---|
| Presented `lag_from_raw` (mean \|smoothed − raw\|) as a lag measure, and called raw MiDaS output "the current true frame" — treating inference as ground truth, in a report citing Core Principle 2. Concluded "the trade is close to one-for-one." | **Claim withdrawn.** Metric renamed and disclaimed; real lag measured against a known step: **3 frames / ~180 ms**. |
| Reported 58.14% flicker reduction without re-normalizing smoothed frames, so amplitude compression inflated it. | **50.35%** after correction. |
| Read a whole-window `temporal_std` as "the estimate never settles" — but over 9 s of head motion it measured scene change, not stability. | Recomputed over a 5-frame window: **−38%**. My conclusion was **reversed**. |
| Compared homography vs. fundamental inlier counts directly; their residuals are 2-D and 1-D, so H ≤ F always and the ratio proved nothing. | Replaced with ORB-SLAM's `R_H` at its 0.45 threshold. The caveat survived, better supported. |
| Closed only half the truthful-state gap: module-level failures reported `frame_error`, but transport-level validation failures still returned silently. | Found by end-to-end smoke test (unit tests missed it); added `reason: "invalid_frame"`. |
| Caught broad `Exception` around `receive_json`, which would spin uncancellably on a Starlette state error. | Narrowed to payload errors only; regression test asserts exactly one attempt. |

---

## Stop conditions triggered

**One, and it was the expected one.**

### Object Memory implementation (STRETCH item 6) — stopped at Task 4

Object Memory's `_do_load()` must load a detector synchronously and, on
first run, download weights over the network. Written the obvious way,
this silently reproduces the known unbounded-blocking lifecycle gap that
`DepthEstimationModule` already has — turning a one-off into a pattern.

Master Guide §9 classifies that gap as **needs user judgment**, and §17
STRETCH item 6 says explicitly not to make it a silent copy. So I stopped
and wrote up the decision instead of picking for you.

**State preserved:** the plan is complete, reviewed, revised, and
committed. Tasks 1–3 (record shape, relevance filter, JSONL store) are
autonomous-safe and could proceed first if you want progress while
deciding. No Object Memory code was written.

**Your options are costed in the plan's Task 4**, including two
consequences that are easy to miss: enforcing the 10 s timeout makes a
cold-cache first run fail *deterministically*, and `asyncio.to_thread`
combined with `mark_failed()` leaks a fully-loaded model (release runs
before the orphaned thread finishes assigning it). My recommendation is
**E + A** — give load its own longer timeout (`ModuleContainer` already
accepts one and `main.py` never passes it), plus `to_thread` in this
module only with an invalidation token — then fix the contract centrally
at V1.1. **This is your call, not mine.**

---

## Preserved "needs user judgment" items — not patched

Per your instruction, these were documented, not decided:

1. **Synchronous lifecycle-timeout gap.** `asyncio.wait_for` cannot
   interrupt a blocking call inside `_do_load()` — verified against
   Starlette/asyncio semantics, not assumed. Real today for
   `torch.hub.load()`. Still unfixed; now recorded in `03-ROADMAP.md`
   V0.9.2 and analysed in the Object Memory plan's Task 4.
2. **No auth; `TOWER_HOST` defaults to `0.0.0.0`.** Unchanged, still
   documented as Phase 1.5 work. No *new* security finding surfaced, so
   this did not trigger a fresh stop.

---

## Mac-side handoffs produced

- `docs/superpowers/handoffs/2026-08-20-source-seq-tx-seq-split.md` — the
  iOS half of the protocol split. Tower half is merged (`0346c05`); the
  document gives exact wire shapes, acceptance criteria, and which tests
  each side owns. It flags that `search_dat_docs` was unavailable here, so
  the "~1-in-30 forwarding" premise must be re-verified before
  implementing (Rule 4), and surfaces the still-open `VideoFrame`
  timestamp-semantics question as adjacent work.

---

## What's next

Per §16's sequence, adjusted for what was actually learned:

1. **Decide Task 4** (above). It gates Object Memory / V1.2, which remains
   the recommended next production module.
2. **Capture real DAT/glasses footage and re-run both harnesses.** This is
   the acceptance gate, and it is now one command each
   (`--video <path> --out <path>`). Until it happens, nothing in V0.9.3 may
   be cited as validation.
3. **Resolve camera intrinsics** (Mac-side `search_dat_docs`, or
   checkerboard calibration) — the only thing blocking Experiments 3–4.
   Experiment 2's `R_H` decay curve now tells Experiment 3 where its
   difficulty will be: consecutive frames match well but over half lack
   parallax.
4. **Implement the iOS side of the handoff**, which turns
   `tx_seq_gap_total` from a null into the platform's first real
   transit-loss measurement.

---

## Anything you should specifically review

1. **The Task 4 decision** — the one thing genuinely blocking progress.
2. **The V0.9.3 report's "Corrections from the first draft" table** — I
   published wrong conclusions before catching them. Worth confirming you
   agree with the corrected readings.
3. **Whether the EPIC-KITCHENS substitution was the call you wanted.** You
   authorized it, but the acceptance gate is only as good as our
   willingness to honor it later. If you would rather treat both
   experiments as not-done until real footage exists, say so and I will
   downgrade the roadmap entries.
4. **`.claude/worktrees/v0.8-module-container`** — now an **empty
   directory**, no longer a registered git worktree (`git worktree list`
   shows only the main tree). Safe to delete; left in place because
   removal wasn't authorized.
5. **`torch` in `.venv` is the CPU-only build** (`2.13.0+cpu`). I did not
   change it, since reinstalling from the cu132 index is the kind of
   environment change worth doing deliberately. Any GPU measurement needs
   that first, per `README.md`'s install-order caveat.
6. **`V0.9.2`/`V0.9.3` roadmap numbering** — the Master Guide proposed
   these; I recorded completed work under them per §22, but the numbering
   itself was your architectural call to ratify.
