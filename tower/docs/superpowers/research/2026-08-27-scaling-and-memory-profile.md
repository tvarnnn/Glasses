# Scaling and memory: does anything in World Builder scale badly in Python?

**Date:** 2026-08-27
**Lane:** scaling and memory profiling, World Builder native-migration evaluation
**Worktree:** `C:\Users\tvllo\Projects\Glasses-world-builder`, branch `world-builder/next-generation`

---

## Verdict

**No. There is no Python-side scaling problem that native code would fix.**
Per-frame `observe()` cost is flat in session length — accepted-keyframe
latency moves from a 47.2 ms median in the first quarter of a 448-keyframe
walk to 50.0 ms in the last, a 1.06x drift with a fitted slope of
+0.008 ms per keyframe and r = +0.099, which is noise; and the live path
is **94.7% native** by tottime, whose single largest Python frame is
0.092 s out of 24 s. `build()` is **linear**, not superlinear: a power fit
across 17 captures spanning 2 to 448 keyframes gives an exponent of
**0.949** (R² = 0.957), and the per-keyframe cost at the top of that range
is the *lowest* in the table; the stage is 88.0% native. Registration's
quadratic term — candidate generation over segment pairs — is real and
costs **0.22%** of registration wall time, because the prune that runs on
each pair costs ~235 µs and the pairs that survive it cost 0.08–2.6 s
each. The one genuine Python hotspot in the whole system is
`world_registration._residuals`, at 37.0% of profiled tottime and 49.7% of
wall across sixteen worlds — and while this lane was measuring it, another
lane **fixed it in Python** by stacking the observations, for a measured
**1.43x** on the whole registration stage with byte-identical registration
outcomes. That is the number a native port of that loop was competing for,
and it has already been collected without leaving Python. Memory is flat:
Python-side allocation at the end of the longest walk is **3.3 MB** against
a **280.6 MB** RSS, the pruned `_Chain.observed` dict shows no upward trend
across 448 real keyframes, and registration peak RSS sits at 205–210 MB
regardless of world size.

---

## Environment — asserted, not assumed

Every number below was produced by:

```
cd C:\Users\tvllo\Projects\Glasses-world-builder\tower
PYTHONPATH="C:\Users\tvllo\Projects\Glasses-world-builder\tower" \
  C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe <script>
```

Asserted in-process, inside each harness, next to the numbers it prints:

| Check | Value |
|---|---|
| `tower.world_builder.backends.classical.__file__` | `C:\Users\tvllo\Projects\Glasses-world-builder\tower\tower\world_builder\backends\classical.py` |
| `classical.EXTEND_REFERENCE_DEPTH` | `3` (present — so this is the branch under test, not the main-repo editable install) |
| `psutil` | 7.2.2, present. RSS is measured, not estimated. |

**Face redaction was ON for every replay in this report.**
`redaction.DEFAULT_MODEL_PATH` is `Path("models")/face_detection_yunet_2023mar.onnx`,
relative and resolved against cwd. Every run had cwd = `<worktree>/tower`,
and each harness prints the resolved model path; all replays report
`redaction=ON`. `FaceDetectorYN.detect` is accordingly the single largest
cost in the live path (9.324 s of a 23.678 s profiled replay).

Corpus was read from the main repo read-only:
`C:\Users\tvllo\Projects\Glasses\tower\data\captures` (34 captures with
frames) and `...\data\world_builder` (persisted worlds and
`intrinsics/360x640.json`). **Nothing was written into the main repo.**
All derived geometry went to `C:\Users\tvllo\Projects\Glasses-world-builder\sc`
and `...\sc2`. `world_registration.register()` writes nothing, so the
main-checkout worlds were safe to register against.

Harness code is in `tower/scripts/research/native_eval/`. Nothing under
`tower/tower/` was modified by this lane.

### The worktree moved underneath the measurements

This has to be stated, because it invalidates a naive reading of any
before/after comparison. **This worktree is shared with other lanes of the
same evaluation, and `scripts/world_registration.py` was rewritten while a
sweep was running.** It was caught because `grep -n` reported
`def _residuals` at line 543 in one call and 651 in another; the file had
grown from 1755 to 1872 lines mid-session, and `tower/storage.py` and
`tower/world_builder/frontend.py` changed too. The relevant commits are
`f00e3bc perf: stack the observations once, and registration gets 1.64x
faster` and `129dd7b perf: two product-path wins that are not C++ — 7.4x
sharpness, 3.6x JSON`.

Everything below is therefore pinned to a code state by SHA-256 of the
source file, and the two registration variants are loaded from pinned
copies via `importlib` rather than from the moving working tree:

| Label | File | sha256[:16] | Lines |
|---|---|---|---|
| **BASELINE** | `sc/world_registration_HEAD.py` (`git show` at commit `74e0ce6`) | `f4031322dc778e0f` | 1755 |
| **PACKED** | `sc/world_registration_PACKED.py` (working-tree snapshot ≈ `f00e3bc`) | `fe7b545f9aacadfa` | 1872 |

Which state each measurement was taken in:

- **State A** (tree at `74e0ce6`, clean): Q1 per-frame trend, Q2 build
  sweep, Q4 memory probe on `0fc400bb`, registration BASELINE sweep.
  Verified by mtime: `classical.py` 02:06, `engine.py` 02:07, all runs
  03:07–03:15, all edits 03:15 or later.
- **State B** (after `f00e3bc` + `129dd7b`): Q1 per-frame trend re-run,
  replay profile split, memory probe on `22e9d428`, registration PACKED
  sweep.

`classical.py` and `engine.py` were **not** changed by the other lanes
(the only working-tree difference on `classical.py` was a line-ending
warning, and `git diff --stat` never listed it), so Q2's build numbers are
on one unchanged backend.

### On profiled vs unprofiled time

Both are reported for every stage. `cProfile` inserts per-call
bookkeeping that is charged to **Python** frames specifically, so its
split **overstates Python** — which biases against this report's own
conclusion, and is the right direction for the bias to run. The
`time.perf_counter` wall time is the number to trust for totals; the
cProfile split is used only for attribution.

The NATIVE/PYTHON classification is mechanical, not eyeballed: `pstats`
keys whose filename is `~` are CPython's marker for a C function with no
Python source — every `cv2.*` call, every numpy ufunc and linalg entry
point, every builtin. Everything with a real `.py` path is interpreter
time, and interpreter time is the only part a compiled-language rewrite
could remove.

---

## Q1 — Does per-frame cost grow with session length?

**No. It is flat, and the live path is 94.7% native.**

Harness: `scripts/research/native_eval/replay_scale.py`, which wraps
`time.perf_counter` around every individual `engine.observe()` call and
records the frame index, the accumulated keyframe count, and RSS for each
one. Replay goes through `world_builder_corpus_benchmark.journal_frames`,
so `source_seq` / `wire_seq` / `tx_seq` / `received_at` are the recorder's
own values, not fabricated by a directory glob.

```
PYTHONPATH=... python scripts/research/native_eval/replay_scale.py \
  --capture 22e9d428 --scratch ...\sc --out ...\sc\22e9d428.json
PYTHONPATH=... python scripts/research/native_eval/analyse_perframe.py \
  ...\sc\22e9d428.json
```

Capture `22e9d4289cb440fbb3f14e6da369a136`: 1,848 frames → 448 keyframes,
68 segments, 12,347 points. Replay wall **29.82 s** (State A) /
**29.55 s** (State B), unprofiled.

Accepted and rejected frames are reported separately, because a slope
fitted across the mixture measures the *acceptance rate* changing rather
than the per-frame cost changing.

| | n | mean | median | p95 | max |
|---|---|---|---|---|---|
| ACCEPTED (State A) | 448 | 47.12 ms | 45.19 ms | 61.14 ms | 204.47 ms |
| REJECTED (State A) | 1400 | 5.70 ms | 5.33 ms | 8.82 ms | 17.64 ms |
| ACCEPTED (State B) | 448 | 49.89 ms | 48.06 ms | 65.12 ms | 191.17 ms |
| REJECTED (State B) | 1400 | 4.61 ms | 4.34 ms | 7.51 ms | 14.98 ms |

Accepted-frame cost against **accumulated keyframe count**, by decile
(State B — State A is the same shape):

```
    d1  kf~ 23  mean= 53.55  med= 51.48   d6  kf~243  mean= 51.96  med= 51.23
    d2  kf~ 67  mean= 44.56  med= 43.74   d7  kf~287  mean= 46.18  med= 44.67
    d3  kf~111  mean= 48.56  med= 46.96   d8  kf~331  mean= 49.37  med= 48.87
    d4  kf~155  mean= 45.11  med= 44.42   d9  kf~375  mean= 55.71  med= 54.66
    d5  kf~199  mean= 52.84  med= 50.71   d10 kf~423  mean= 50.91  med= 49.04
```

There is no trend. The first decile is *slower* than the eighth.

| Fit | State A | State B |
|---|---|---|
| accepted ms ~ keyframe count | **+0.00734 ms/kf**, r = +0.083 | **+0.00817 ms/kf**, r = +0.099 |
| rejected ms ~ frame index | +0.00054 ms/frame, r = +0.169 | +0.00067 ms/frame, r = +0.219 |
| accepted first-quarter → last-quarter median | 46.41 → 47.37 ms = **1.021x** | 47.16 → 49.97 ms = **1.059x** |

Extrapolating the fitted slope over the entire 448-keyframe walk gives
+3.7 ms — smaller than the run-to-run difference between State A and
State B, and smaller than the spread between adjacent deciles.

The same flatness holds *across* captures. From the 17-capture sweep in
Q2, replay cost per frame against capture length:

```
  79233e64     16 frames  18.54 ms/frame      854e9688    610 frames  17.50 ms/frame
  0f0c55b6     75 frames   8.23 ms/frame      ab10cb20   1343 frames  12.41 ms/frame
  4fb8236c    104 frames  17.67 ms/frame      b35d8ab8   1694 frames  12.64 ms/frame
  72b3d6b8    200 frames  19.72 ms/frame      22e9d428   1848 frames  13.92 ms/frame
  4fea31e2    662 frames   9.61 ms/frame      0fc400bb   2203 frames  12.16 ms/frame
```

The 16-frame capture is *more* expensive per frame than the 2,203-frame
one. Total: 11,420 frames in 149.2 s = **13.07 ms/frame** overall.

### Where the live path's time actually goes

```
PYTHONPATH=... python scripts/research/native_eval/profile_split.py replay \
  --capture 22e9d428 --scratch ...\sc --out ...\sc\split-replay.json
```

Unprofiled wall **24.083 s**; profiled total 23.678 s.

| | tottime | share |
|---|---|---|
| **NATIVE** (cv2 / numpy C / builtins) | **22.427 s** | **94.7%** |
| PYTHON (interpreter frames, overstated) | 1.251 s | 5.3% |

Top costs, all native:

```
   9.324 s    448 calls  FaceDetectorYN.detect      <- face redaction
   4.063 s   3516 calls  calcOpticalFlowPyrLK
   1.456 s    448 calls  goodFeaturesToTrack
   1.331 s   1399 calls  findHomography
   0.962 s   2492 calls  imdecode
   0.799 s    448 calls  resize
   0.797 s    254 calls  detectAndCompute
```

The largest **Python** frame in the entire replay is
`frontend.py:217 track_forward_backward` at **0.092 s** — 0.4% of the
stage. `engine.observe` itself is 0.027 s across 1,848 calls. There is no
Python hotspot on the live path to port.

### Against the live budget

The live path has ~83 ms at ~12 fps. Accepted keyframes run at a 48 ms
median and a 65 ms p95, inside budget; the max is 191–204 ms, so
individual frames do exceed it. But those excursions are **not growth** —
they appear in the first decile as readily as the tenth, and they are
inside `FaceDetectorYN.detect` and `calcOpticalFlowPyrLK`, both native.
**The live path is safe and no native work is justified there.**

---

## Q2 — Does `build()` scale superlinearly?

**No. It is linear (exponent 0.949) and 88.0% native.**

Harness: `scripts/research/native_eval/build_scale.py`. Two paths are
timed separately, because they cost different things:

- **WARM** — `build()` on the engine that just observed the walk.
  `_LiveSolve` already solved each segment incrementally, so this is a
  flush: read the journal, join carried estimates, write JSON.
- **COLD** — `build()` on a *fresh* engine over the same store.
  `_live_estimates` returns empty and every segment is re-solved from
  scratch off the persisted JPEGs. This is the path whose complexity
  `engine.py:1001` worries about, and the one a native port would replace.

```
PYTHONPATH=... python scripts/research/native_eval/build_scale.py \
  --captures 79233e64 97f31726 b1a1bb3c 0f0c55b6 4fb8236c 72b3d6b8 6003eafc \
             2327a858 69030fba 64f48114 854e9688 4fea31e2 e1c52b9f ab10cb20 \
             b35d8ab8 22e9d428 0fc400bb \
  --scratch ...\sc --out ...\sc\buildscale.json
```

All 17 unprofiled, `time.perf_counter`:

| prefix | frames | keyframes | segments | points | replay s | warm build s | cold build s | cold ms/kf |
|---|---|---|---|---|---|---|---|---|
| 79233e64 | 16 | 2 | 1 | 289 | 0.30 | 0.015 | 0.028 | 14.15 |
| 97f31726 | 28 | 3 | 2 | 0 | 0.29 | 0.013 | 0.034 | 11.43 |
| 0f0c55b6 | 75 | 6 | 3 | 42 | 0.62 | 0.013 | 0.035 | 5.75 |
| b1a1bb3c | 45 | 9 | 2 | 0 | 0.63 | 0.019 | 0.076 | 8.47 |
| 6003eafc | 271 | 12 | 2 | 796 | 2.56 | 0.033 | 0.171 | 14.26 |
| 4fb8236c | 104 | 32 | 8 | 1134 | 1.84 | 0.049 | 0.235 | 7.36 |
| 4fea31e2 | 662 | 54 | 4 | 426 | 6.36 | 0.058 | 0.373 | 6.91 |
| 72b3d6b8 | 200 | 68 | 15 | 1667 | 3.94 | 0.072 | 0.529 | 7.78 |
| 64f48114 | 527 | 75 | 9 | 7821 | 6.07 | 0.130 | 0.961 | 12.81 |
| 69030fba | 442 | 78 | 5 | 96 | 5.23 | 0.066 | 0.423 | 5.43 |
| 2327a858 | 356 | 80 | 13 | 5504 | 5.26 | 0.114 | 0.695 | 8.69 |
| e1c52b9f | 996 | 160 | 9 | 19872 | 14.87 | 0.381 | 3.071 | 19.19 |
| 854e9688 | 610 | 196 | 38 | 4997 | 10.68 | 0.193 | 1.543 | 7.87 |
| ab10cb20 | 1343 | 263 | 44 | 6257 | 16.67 | 0.207 | 1.879 | 7.15 |
| 0fc400bb | 2203 | 339 | 40 | 18977 | 26.78 | 0.439 | 3.514 | 10.37 |
| b35d8ab8 | 1694 | 349 | 76 | 11364 | 21.42 | 0.293 | 2.413 | 6.91 |
| **22e9d428** | **1848** | **448** | **68** | **12347** | **25.73** | **0.354** | **2.993** | **6.68** |

Log-log power fits (`scripts/research/native_eval/fit_exponent.py`):

```
build_cold_s = 1.087e-02 * keyframes^0.949   R^2 = 0.957   n = 17
build_warm_s = 5.384e-03 * keyframes^0.687   R^2 = 0.924   n = 17
```

**The cold rebuild is linear.** The per-keyframe cost wanders between
5.4 and 19.2 ms with no trend, and the largest capture in the corpus —
448 keyframes — records the **lowest** per-keyframe cost in the whole
table at 6.68 ms/kf. `_extend` being forward-only and `_Chain.forget_before`
pruning is confirmed on real data, not just asserted.

The warm flush is *sublinear* (0.687): per-keyframe cost falls from 7.5 ms
at 2 keyframes to 0.79 ms at 448, because the fixed per-build overhead
(reading the journal, JSON encode) amortises. 448 keyframes flush in
**0.354 s**.

`points_warm == points_cold` on all 17 captures — the live incremental
solve reproduces the cold rebuild exactly, so the warm path is not buying
its speed with a different answer.

### Where the cold build's time goes

```
PYTHONPATH=... python scripts/research/native_eval/profile_split.py cold-build \
  --root ...\sc\bs-22e9d428 --world 6146520e... --session e7eb139b... \
  --out ...\sc\split-coldbuild.json
```

448 keyframes. Unprofiled wall **2.941 s**; profiled total 3.320 s.

| | tottime | share |
|---|---|---|
| **NATIVE** | **2.921 s** | **88.0%** |
| PYTHON (overstated) | 0.399 s | 12.0% |

```
   1.545 s    448 calls  NATIVE  detectAndCompute       <- ORB, 47% of the stage
   0.292 s    375 calls  NATIVE  knnMatch
   0.193 s    107 calls  NATIVE  solvePnPRansac
   0.173 s    448 calls  NATIVE  imdecode
   0.129 s     54 calls  NATIVE  findEssentialMat
   0.097 s     54 calls  NATIVE  findHomography
   0.064 s    377 calls  python  geometry.py:90 match_indices   <- largest Python frame, 1.9%
   0.034 s    386 calls  python  json encoder.py:205 iterencode
   0.030 s    102 calls  python  classical.py:1064 _triangulate_new
```

The build stage is dominated by native OpenCV. The largest Python frame is
`match_indices` at 1.9% of the stage. **There is no term here that isn't
linear, and nothing worth porting.**

---

## Q3 — Does registration scale badly, and in what?

**The quadratic term is real and costs 0.22%. The cost is `_residuals`,
a Python loop — which has already been fixed in Python for 1.43x.**

Harness: `scripts/research/native_eval/registration_scale.py`. Phase
attribution is done by rebinding `world_registration`'s own module globals
with timing wrappers from outside — `register()` resolves
`pair_is_hopeless`, `cross_matches`, `fit_direction`, `_refine` and
`_residuals` as globals at call time, so the real calls are timed without
editing `scripts/world_registration.py` (which another lane owns and was
actively changing). Each world is measured **unprofiled first** for wall
time, then re-run wrapped for attribution.

Sweep: all persisted worlds in the main checkout, plus the 17 worlds this
lane built into scratch during Q2 (needed because most main-checkout worlds
report `SupportMissingError` — stale or absent derived reconstructions,
a legitimate refusal, recorded as a datapoint rather than skipped).

```
PYTHONPATH=... python scripts/research/native_eval/registration_scale.py \
  --root "C:\Users\tvllo\Projects\Glasses\tower\data\world_builder" \
  --roots ...\sc\bs-0fc400bb ...\sc\bs-22e9d428 [...12 roots...] \
  --registration-source ...\sc\world_registration_HEAD.py \
  --out ...\sc\registration_HEAD.json
```

**BASELINE (`f4031322`), 16 worlds with real matching work.** `pairs` is
C(G,2) over geometry-bearing segments — the true size of the double loop.
(`report["candidate_pairs"]` undercounts it: a pair whose `cross_matches`
comes back empty `continue`s without recording a verdict.)

| world | segs | geo | pairs | matched | wall s | hopeless s | match s | refine s | resid s | resid % |
|---|---|---|---|---|---|---|---|---|---|---|
| 32037081 | 8 | 3 | 3 | 1 | 2.64 | 0.001 | 0.038 | 2.261 | 1.941 | 73.6% |
| b2ac9808 | 11 | 4 | 6 | 6 | 3.20 | 0.003 | 0.854 | 2.095 | 1.682 | 52.6% |
| 17edee57 | 13 | 5 | 10 | 3 | 1.01 | 0.002 | 0.207 | 0.599 | 0.491 | 48.5% |
| 9970ffdc | 9 | 6 | 15 | 10 | 10.86 | 0.004 | 1.423 | 8.475 | 7.308 | 67.3% |
| b64a45b4 | 15 | 6 | 15 | 3 | 0.24 | 0.002 | 0.090 | 0.000 | 0.000 | 0.0% |
| 3d49a771 | 14 | 7 | 21 | 15 | 7.10 | 0.005 | 1.400 | 5.685 | 4.645 | 65.4% |
| 4cae0b26 | 23 | 8 | 28 | 15 | 1.95 | 0.010 | 0.722 | 0.000 | 0.000 | 0.0% |
| **8869d7bb** | 9 | 8 | 28 | 15 | **39.76** | 0.012 | 12.669 | 26.252 | 21.854 | 55.0% |
| adc75972 | 28 | 14 | 91 | 15 | 6.60 | 0.016 | 1.230 | 4.105 | 3.284 | 49.8% |
| f80e88a5 | 24 | 15 | 105 | 78 | 19.29 | 0.040 | 7.440 | 9.908 | 8.077 | 41.9% |
| 3f403ed6 | 38 | 16 | 120 | 45 | 8.15 | 0.015 | 1.329 | 5.857 | 4.931 | 60.5% |
| 3dd986b1 | 51 | 19 | 171 | 36 | 7.01 | 0.037 | 1.697 | 4.004 | 3.343 | 47.7% |
| 20333cc5 | 44 | 20 | 190 | 66 | 5.48 | 0.027 | 1.912 | 2.935 | 2.390 | 43.6% |
| 2716b8bd | 40 | 23 | 253 | 153 | 31.60 | 0.072 | 14.675 | 16.918 | 13.768 | 43.6% |
| 6146520e | 68 | 29 | 406 | 190 | 21.36 | 0.096 | 7.059 | 10.912 | 9.055 | 42.4% |
| **1b715e08** | **76** | **31** | **465** | 66 | 14.27 | 0.062 | 4.667 | 8.517 | 7.013 | 49.1% |

`3dd986b1` at 7.01 s corroborates the 6.4 s already measured on this lane's
behalf for the same world.

**Phase totals over all 16 worlds, 180.5 s of wall:**

| Phase | seconds | share | kind |
|---|---|---|---|
| `pair_is_hopeless` — **candidate generation, the O(S²) term** | **0.40** | **0.22%** | Python, but trivially cheap |
| `cross_matches` — ORB detect + knnMatch | 57.41 | 31.80% | **NATIVE** |
| `_refine` — Levenberg-damped Gauss-Newton | 108.52 | 60.12% | mixed |
| ↳ `_residuals` inside it | **89.78** | **49.74%** | **PYTHON loop** |

### The exponent

```
wall_s ~ segments_with_geometry^1.039   R^2 = 0.326   n = 16
wall_s ~ pairs_all^0.486                R^2 = 0.325   n = 16
wall_s ~ pairs_matched^0.632            R^2 = 0.506   n = 16
```

**All three fits are poor, and that is the finding.** Registration wall
time is not a function of segment count. `8869d7bb` has 8 geometry-bearing
segments, 28 pairs, and takes **39.76 s** — the slowest world measured —
while `1b715e08` has 31 segments, 465 pairs, and takes **14.27 s**. Cost
is set by how many pairs survive the prune and how hard `_refine` has to
work on each, both data-dependent, not by S².

The quadratic term is genuinely quadratic but has a tiny constant. Measured
per-pair prune cost across the range:

```
  pairs=  3  hopeless=0.0006s (0.02% of wall)   200 us/pair
  pairs= 28  hopeless=0.0122s (0.03% of wall)   436 us/pair
  pairs=105  hopeless=0.0399s (0.21% of wall)   380 us/pair
  pairs=253  hopeless=0.0716s (0.23% of wall)   283 us/pair
  pairs=406  hopeless=0.0955s (0.45% of wall)   235 us/pair
  pairs=465  hopeless=0.0619s (0.43% of wall)   133 us/pair
```

At ~235 µs/pair, candidate generation would need roughly **4,250 pairs —
about 92 geometry-bearing segments — before the prune alone cost one
second.** The largest world observed has 31. The O(S²) term is not a
problem at any scale this system has produced, and porting it to native
would save 0.22% of a stage that runs offline.

### Where registration's time goes — and the split

```
PYTHONPATH=... python scripts/research/native_eval/profile_split.py registration \
  --root ...\sc\bs-0fc400bb --world 2716b8bd... --session de22af60... \
  --source ...\sc\world_registration_HEAD.py
```

World `2716b8bd` (23 geometry segments, 153 matched pairs). Unprofiled wall
**30.204 s**; profiled total 33.347 s.

| | tottime | share |
|---|---|---|
| NATIVE | 16.085 s | 48.2% |
| **PYTHON** (overstated) | **17.261 s** | **51.8%** |

```
  12.334 s   207232 calls  python  world_registration.py:543 _residuals   <- 37.0%
   6.519 s     5267 calls  NATIVE  knnMatch
   5.586 s     1361 calls  NATIVE  findEssentialMat
   1.560 s     1058 calls  python  world_registration.py:590 _refine
   1.005 s     5267 calls  python  geometry.py:90 match_indices
   0.934 s      224 calls  NATIVE  detectAndCompute
   0.606 s   208376 calls  NATIVE  Rodrigues
```

**This is the only stage in World Builder where Python is the majority of
tottime, and `_residuals` is the whole reason.** 207,232 calls, each a
Python `for` loop over ~4.5 cameras doing small numpy operations on
~(198, 3) arrays — the shape where per-call numpy dispatch is comparable
to the arithmetic itself.

### The Python fix already collected the win

The obvious question is whether `_residuals` is slow because it is
*Python* or because it is *work*. If the arithmetic dominated, numpy is
already running it in C and a native port buys little; if the Python loop
and per-camera dispatch dominate, the fix is to stack the cameras into one
array — **a Python change**.

While this lane was measuring, another lane landed exactly that
(`f00e3bc`): `_pack`, `_residuals_packed`, `_huber_cost_packed`. Both
variants were pinned by SHA and swept over the same 16 worlds:

| world | geo | matched | BASELINE s | PACKED s | speedup |
|---|---|---|---|---|---|
| 8869d7bb | 8 | 15 | 39.76 | 25.02 | 1.59x |
| 2716b8bd | 23 | 153 | 31.60 | 24.05 | 1.31x |
| 6146520e | 29 | 190 | 21.36 | 14.54 | 1.47x |
| f80e88a5 | 15 | 78 | 19.29 | 13.29 | 1.45x |
| 1b715e08 | 31 | 66 | 14.27 | 11.62 | 1.23x |
| 9970ffdc | 6 | 10 | 10.86 | 6.41 | 1.70x |
| 3f403ed6 | 16 | 45 | 8.15 | 5.96 | 1.37x |
| 3d49a771 | 7 | 15 | 7.10 | 3.80 | 1.87x |
| 3dd986b1 | 19 | 36 | 7.01 | 4.60 | 1.53x |
| adc75972 | 14 | 15 | 6.60 | 4.66 | 1.42x |
| 20333cc5 | 20 | 66 | 5.48 | 5.31 | 1.03x |
| b2ac9808 | 4 | 6 | 3.20 | 2.25 | 1.42x |
| 32037081 | 3 | 1 | 2.64 | 1.38 | 1.92x |
| 4cae0b26 | 8 | 15 | 1.95 | 1.94 | 1.00x |
| 17edee57 | 5 | 3 | 1.01 | 0.93 | 1.09x |
| b64a45b4 | 6 | 3 | 0.24 | 0.29 | 0.84x |
| **TOTAL** | | | **180.52** | **126.07** | **1.43x** |

`segments_registered` agrees on **every** world — the change is a speedup,
not a different answer.

The split moves accordingly. On `2716b8bd`, unprofiled wall
30.204 s → **21.445 s**:

| | BASELINE | PACKED |
|---|---|---|
| NATIVE | 48.2% | **62.7%** |
| PYTHON | 51.8% | 37.3% |
| `_residuals` / `_residuals_packed` | 12.334 s | 4.653 s |

An independent check of the same claim, at the level of the function
rather than the stage
(`scripts/research/native_eval/residuals_micro.py`, which captures real
observation sets off a live registration, asserts the stacked form agrees
with the loop to `rtol=atol=1e-9` before timing anything, and refuses to
report if it does not):

```
PYTHONPATH=... python scripts/research/native_eval/residuals_micro.py \
  --root ...\sc\bs-0fc400bb --world 2716b8bd... --session de22af60... \
  --sets 12 --reps 300

 cams  points    loop us  stacked us       x
    4     110      57.76       19.00    3.04
    3     127      62.20       31.84    1.95
    3      66      44.63       22.61    1.97
    2      49      35.38       25.68    1.38
    1      13      18.28       21.14    0.86     <- packing not amortised
    1      22      12.32       14.97    0.82     <- packing not amortised
TOTALS over 12 sets: loop=447.8us stacked=281.2us  overall=1.59x
```

The direction of the effect is confirmed and its mechanism is visible: the
speedup rises with the number of cameras being folded into one array
(3.04x at 4 cameras) and **inverts below two** (0.82x at 1 camera), which
is what an overhead-bound rather than FLOP-bound cost looks like. The
answer to "is `_residuals` slow because it is Python or because it is
work?" is **because it is Python** — and therefore Python could fix it,
and did.

What remains on the Python side is `_refine`'s own numpy scaffolding — the
seven-column numerical Jacobian, `np.linalg.solve` on a 7×7, `norm`,
`diag`, `where` — over 34,000–70,000 tiny calls. That is the *same* class
of problem and the *same* class of fix: batch the Jacobian columns. It is
also still Python-addressable.

**Registration had one real Python hotspot; vectorizing it in Python
returned 1.43x with identical results. That is the win a native port of
that loop was competing for, and it has been taken without one.**

---

## Q4 — Memory

**Flat. Python-side allocation is ~1% of RSS, and no retained structure
grows with keyframe count except the output itself.**

Harness: `scripts/research/native_eval/memory_probe.py`, which runs
`tracemalloc` alongside `psutil` RSS and, at each checkpoint, deep-sizes
the live solve's retained state field by field (numpy arrays charged their
`nbytes`, not their header). `psutil` 7.2.2 was checked, not assumed.

```
PYTHONPATH=... python scripts/research/native_eval/memory_probe.py \
  --capture 0fc400bb --scratch ...\sc --out ...\sc\mem-0fc400bb.json --every 150
PYTHONPATH=... python scripts/research/native_eval/memory_probe.py \
  --capture 22e9d428 --scratch ...\sc2 --out ...\sc\mem-22e9d428.json --every 200
```

### Peak RSS for replay + build

| capture | frames | keyframes | segments | RSS after first frame | RSS end of replay | **RSS after build (peak)** |
|---|---|---|---|---|---|---|
| `0fc400bb` (largest by frames) | 2203 | 339 | 40 | 234.8 MB | 270.1 MB | **279.2 MB** |
| `22e9d428` (largest by keyframes) | 1848 | 448 | 68 | 233.5 MB | 269.7 MB | **280.6 MB** |

The ~234 MB floor is present after the *first* frame — it is the
interpreter plus OpenCV plus the YuNet DNN, paid once. Growth across the
entire remainder of a 2,203-frame walk is **~35 MB**, and the build adds
~10 MB.

### Python-side vs native

| | `0fc400bb` | `22e9d428` |
|---|---|---|
| `tracemalloc` current, end of replay | **3.003 MB** | **3.264 MB** |
| `tracemalloc` peak, end of replay | 7.274 MB | 6.888 MB |
| RSS at the same moment | 270.1 MB | 269.7 MB |

**Python-tracked allocation is ~1.2% of RSS.** `tracemalloc` does not see
OpenCV's C++ allocations, and the gap between the two numbers *is* the
native/Python split for memory: essentially all of it is native. A
compiled rewrite would be competing for 3 MB.

### Is `_Chain.forget_before` actually flat on a real walk?

There is a committed test asserting this on a *synthetic* walk. Verified
here on `0fc400bb`, 2,203 real frames, deep-sized per field (bytes):

```
    i     kf   rss_mb   py_mb  observed  older_feat  prev_feat  support  landmarks   frozen
    0      1    234.8    0.36        64          56     122416       56         56       64
  150     12    241.8    1.60        64      119244     123120       56         56     3417
  450     31    243.2    1.63        64      119244     123120       56         56     3337
  750     54    248.0    1.76        64      128484     128840       56         56    56870
 1050     92    253.3    2.38    221340      262336     132096    32560      23460    80292
 1200    134    263.1    2.79    271712      231624     128136    56512      36124   318894
 1350    180    265.8    2.56     74652      169056      66800     8448       6376   685780
 1500    238    268.8    2.71      4724      126108     114848      544        444   893728
 1800    288    268.9    2.70        64       81228      93728       56         56   925382
 1950    316    269.6    2.58        64          56       6960       56         56   970878
 2100    335    269.9    2.99      9740      257408     125144     1144        936   972390
```

Reading it field by field:

- **`observed`** — the dict `forget_before` prunes. Oscillates between
  64 B and 271 KB depending on where in a segment the sample lands, and
  **shows no upward trend**: 271 KB at 134 keyframes, 9.7 KB at 335.
  `forget_before` works on real data, not just on the synthetic walk the
  committed test uses. Unpruned this would be tens of megabytes (the
  docstring records 26.1 MB at 155 keyframes and 142.9 MB at 1000).
- **`older_features` + `previous_features`** — bounded at ~250–380 KB
  combined, constant. This is the `EXTEND_REFERENCE_DEPTH = 3` window,
  and it behaves as the constant it is documented to be.
- **`support` / `landmarks`** — deliberately not pruned; they grow *within*
  a segment and reset when it closes. Peak observed 56 KB / 36 KB. Bounded
  by segment length, not session length.
- **`_LiveSolve._frozen`** — the **only** monotonically growing term:
  64 B → 972 KB across 339 keyframes / 40 segments (and 690 KB across 448
  keyframes / 67 segments on `22e9d428`). That is ~2–3 KB per keyframe, and
  it is the *output* — one frozen `GeometryEstimate` per closed segment,
  held so a mid-walk rebuild can read it. At 10,000 keyframes it would be
  ~30 MB. It is not a leak and it is not a scaling problem.

Total engine-retained state at the end of the longest walk: **~1.4 MB**.

Top Python allocation sites after build are unremarkable — the largest is
`classical.py:1184` at 0.588 MB, then Python's own importlib at 0.520 MB.

### Registration memory

From the Q3 sweeps, on the six largest worlds:

| world | geo segs | points | wall s | peak RSS | RSS delta |
|---|---|---|---|---|---|
| 8869d7bb | 8 | 19872 | 39.76 | 206.8 MB | −2.5 MB |
| 2716b8bd | 23 | 18977 | 31.60 | 204.6 MB | −0.3 MB |
| 6146520e | 29 | 12347 | 21.36 | 204.2 MB | −1.0 MB |
| f80e88a5 | 15 | 18899 | 19.29 | 204.9 MB | +9.2 MB |
| 1b715e08 | 31 | 11364 | 14.27 | 205.3 MB | −2.1 MB |
| 9970ffdc | 6 | 7821 | 10.86 | 208.5 MB | −3.0 MB |

**Peak RSS is 204–210 MB regardless of world size** — across a 5x range in
geometry-bearing segments and a 2.5x range in point count — and the delta
across a whole registration is between −3 MB and +9 MB. The PACKED variant
is the same (205.5–210.1 MB). Registration does not accumulate.

---

## What a native port would and would not buy

| Stage | Unprofiled wall (largest case) | Native share | Largest Python frame | Verdict |
|---|---|---|---|---|
| Live `observe()` | 24.08 s / 1848 frames | **94.7%** | 0.092 s (0.4%) | Nothing to port. Flat in session length. |
| Cold `build()` | 2.94 s / 448 keyframes | **88.0%** | 0.064 s (1.9%) | Nothing to port. Linear (exp. 0.949). |
| `register()` BASELINE | 30.20 s | 48.2% | `_residuals` **12.33 s (37.0%)** | The one real hotspot — **already fixed in Python for 1.43x**. |
| `register()` PACKED | 21.45 s | **62.7%** | `_refine` 1.31 s (5.4%) | Remaining Python is `_refine`'s numpy scaffolding; same class of fix. |
| Memory, all stages | 280.6 MB peak | ~98.8% native | 3.3 MB Python | Nothing to port. Flat. |

The only quadratic term in the system is registration's candidate
generation, and it costs **0.22%** of that stage — it would need roughly
three times the largest observed segment count before it cost one second.

**Answering the question this lane was asked: nothing in World Builder
scales badly with keyframe or landmark count in Python. The live path is
flat and native-bound. The build is linear and native-bound. Registration's
cost is data-dependent rather than segment-count-dependent, and its single
Python hotspot has already yielded its 1.43x to a pure-Python
vectorization. Memory is flat and 99% native. No native work is justified
on scaling grounds.**

---

## Caveats and threats to validity

1. **The worktree is shared and the code moved mid-session.** Every
   comparison here is pinned by file SHA-256 and the code state is stated
   per measurement. Any future re-run must re-pin; a sweep that straddles
   another lane's commit describes neither version. This was caught only
   because `grep -n` reported two different line numbers for the same
   function.
2. **Run-to-run variance is ±10–35%** on this host. `adc75972` registered
   in 5.659 s on one clean run and 3.651 s on another. Wall-time
   comparisons between adjacent rows should not be read to two significant
   figures; the exponent fits span orders of magnitude and are robust to
   this, the individual speedup ratios less so. The 1.43x total is over
   16 worlds and 180 s, which is the number to quote.
3. **cProfile inflates Python.** Every split above therefore overstates the
   case *against* this report's conclusion. Unprofiled wall times are given
   alongside for every stage.
4. **Registration coverage is thin at the top end.** The largest world has
   31 geometry-bearing segments and 465 pairs. The claim that the O(S²)
   term stays negligible to ~92 segments is an extrapolation from a
   measured ~235 µs/pair, not a measurement at that size.
5. **Most main-checkout worlds could not be registered** — 25 of 37 raise
   `SupportMissingError` for stale or absent derived reconstructions. That
   is why the sweep was extended with 17 worlds this lane built itself.
   Those are branch-current by construction, which is a strength for
   comparability and a weakness for representativeness.
6. **`points_warm == points_cold` was checked; pose-level equality was
   not.** The live and cold paths agree on point count on all 17 captures,
   which is strong but not proof of identical geometry.

## Artifacts

Harnesses (`tower/scripts/research/native_eval/`):

| File | Purpose |
|---|---|
| `replay_scale.py` | Per-frame `observe()` timing + RSS, warm build, one capture |
| `analyse_perframe.py` | Decile / slope / quartile trend analysis of the above |
| `build_scale.py` | Warm and cold `build()` across a capture sweep |
| `fit_exponent.py` | Log-log power-law fit with R² and per-unit cost table |
| `registration_scale.py` | Phase-split registration sweep; `--registration-source` pins a version |
| `profile_split.py` | cProfile with mechanical NATIVE/PYTHON tottime split (replay, cold-build, registration) |
| `memory_probe.py` | `tracemalloc` + RSS + field-by-field deep-size of retained solve state |
| `residuals_micro.py` | Loop-vs-stacked `_residuals` A/B on real captured observation sets, with an equivalence assertion before timing |

Raw results are under `C:\Users\tvllo\Projects\Glasses-world-builder\sc\`
(`buildscale.json`, `registration_HEAD.json`, `registration_PACKED.json`,
`mem-0fc400bb.json`, `mem-22e9d428.json`, `split-replay.json`,
`split-coldbuild.json`, `split-reg-baseline.json`, `split-reg-packed.json`),
outside both repositories' tracked trees.
