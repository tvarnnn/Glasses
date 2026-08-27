# Baseline profile: where World Builder actually spends its time

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation` at `e68b323`.
**Purpose:** decide whether any part of World Builder justifies migration to C++.
**Status:** MEASURED. No production code modified.

---

## 0. Headline

**The product hot path has no Python bottleneck. ~68% of replay+build is
already executing inside OpenCV's C++.** The one genuine Python hotspot in
the system is in a script that production never calls, and even there the
maximum achievable speedup from making it infinitely fast is **1.74×**.

Numbers below; the verdict is argued in the migration report.

## 1. Method

- Host: Windows 11, RTX 5070 12 GB, 32 GB RAM, Python 3.12.5, **OpenCV
  5.0.0**, numpy 2.5.2.
- Code resolved from the worktree via `PYTHONPATH`, asserted by checking
  `tower.world_builder.backends.classical.__file__` resolves under
  `Glasses-world-builder`. The shared venv's editable install otherwise
  resolves `tower` at the MAIN repo, which is a different branch.
- cwd = `<worktree>/tower`, so `redaction.DEFAULT_MODEL_PATH` (a RELATIVE
  path) resolves and **face redaction is ON**. This matters: redaction is
  22.8% of replay runtime, and the same command from another directory
  measures a different system.
- `cProfile` for attribution, `time.perf_counter` for wall time.

**Noise floor, MEASURED:** registration on the same input, unprofiled, two
consecutive runs: **5.75 s and 6.39 s — 11% spread.** Any improvement
claim below that is indistinguishable from noise, and this document does
not make one.

**cProfile overhead is modest here and biases toward Python**: profiled
6.41 s against unprofiled 5.75–6.39 s. Since profiling inflates Python
frames specifically, the native share reported below is if anything an
*under*-estimate.

## 2. The product hot path — replay + build

Capture `64f481147ec04674a0d857ca4f1964f3`, 527 frames → 75 keyframes, 53
solved poses, 7,821 points. **6.35 s wall.** Top of `cProfile` by tottime:

| function | tottime | share | native? |
|---|---|---|---|
| `FaceDetectorYN.detect` | 1.447 s | 22.8% | **native (OpenCV DNN)** |
| `calcOpticalFlowPyrLK` | 1.235 s | 19.5% | **native** |
| `detectAndCompute` (ORB) | 0.339 s | 5.3% | **native** |
| `findHomography` | 0.294 s | 4.6% | **native** |
| `imdecode` | 0.268 s | 4.2% | **native** |
| numpy `_var` | 0.267 s | 4.2% | native inner, Python dispatch |
| `Laplacian` | 0.248 s | 3.9% | **native** |
| `knnMatch` | 0.205 s | 3.2% | **native** |
| `goodFeaturesToTrack` | 0.199 s | 3.1% | **native** |
| `resize` | 0.104 s | 1.6% | **native** |
| `solvePnPRansac` | 0.086 s | 1.4% | **native** |
| JSON encode (`_iterencode_*`, `dump`) | ~0.42 s | 6.6% | **Python** |
| file I/O (`open`/`read`/`mkdir`/`fsync`/`replace`) | ~0.35 s | 5.5% | OS |

**~68% is inside OpenCV C++.** The largest Python-side cost in the entire
product path is **JSON serialisation at 6.6%**, and the second is
filesystem syscalls.

**There is no Python loop, no object-churn hotspot, and no
NumPy/OpenCV-boundary hotspot in the per-frame path.** Rewriting any of
these call sites in C++ would be rewriting a Python line that immediately
enters C++ anyway.

One incidental finding worth its own note: **face redaction is the single
most expensive operation in the pipeline**, larger than optical flow. It
is already native.

## 3. The one real Python hotspot — registration

`scripts/world_registration.py`, world `3dd986b1c2364d4b85de97152f2e39f4`,
143 candidate pairs, 2 admitted. **6.41 s wall.**

| function | tottime | share | kind |
|---|---|---|---|
| **`_residuals`** (`:543`) | **2.487 s** | **38.8%** | **PYTHON loop** |
| `knnMatch` | 0.890 s | 13.9% | native |
| `detectAndCompute` | 0.699 s | 10.9% | native |
| `findEssentialMat` | 0.622 s | 9.7% | native |
| `_refine` (`:590`) self | 0.294 s | 4.6% | Python |
| `match_indices` | 0.152 s | 2.4% | Python wrapper |
| `Rodrigues` (38,685 calls) | 0.113 s | 1.8% | native |

### 3.1 Why it is slow — MEASURED, not inferred

`_residuals` is a **Python `for` loop over observations**, with small numpy
operations inside each iteration. Instrumented over a full run:

| | value |
|---|---|
| calls | **38,483** |
| observations (cameras) per call | min 3, **median 5, mean 4.5**, max 6 |
| total points per call | min 79, **median 276, mean 197.6**, max 345 |
| points per camera | **43.9** |
| total point-residuals computed | **7,603,651** |
| **cost per point-residual** | **327 ns** |

327 ns for a handful of floating-point operations is roughly two orders of
magnitude off what the arithmetic costs. **The time is numpy per-call
overhead on arrays of ~44 rows** — roughly forty numpy calls per
invocation (`@`, `empty`, `where`, two divisions, boolean assignment,
`concatenate`), none of which can amortise their dispatch cost at that
size.

### 3.2 The data is invariant across all 38,483 calls

`observations` — and therefore `object_points`, `image_points`,
`r_target`, `t_target` — **does not change** across the inner calls. It is
re-traversed 38,483 times and stacked never. The flattening this invites
is a pure-numpy change and needs no native code.

### 3.3 Where the calls come from

`_refine` is Levenberg-damped Gauss-Newton with a **numerical** Jacobian.
Per iteration: 1 residual evaluation for the base, **7 for the Jacobian**
(one per free parameter), plus 1–12 more inside the damping loop. So
roughly 9–10 residual evaluations per iteration, of which **7 exist only
to approximate a derivative**.

Its docstring defends that choice — *"cheaper than being wrong about an
analytic derivative nobody can check"* — and that is a real maintainability
argument, not laziness. But it means the dominant cost of registration is
finite-difference probing, and **an analytic Jacobian would remove ~73% of
all residual evaluations**: a larger factor than any language change
applied to the same kernel.

## 4. THE BOUND THAT DECIDES THIS

`_residuals` **cumtime is 2.724 s of a 6.409 s run.**

So if `_residuals` cost **zero**, registration would take **3.68 s**, a
**1.74× speedup**. That is the ceiling on *any* optimisation of this
function — numpy, Cython, C++, hand-written AVX, anything.

The remaining 3.68 s is `knnMatch` + `detectAndCompute` +
`findEssentialMat` + I/O + JSON, all already native or unavoidable.

**A native rewrite cannot beat 1.74× on the only Python hotspot in the
system, and a vectorised-numpy rewrite competes for the same ceiling at a
fraction of the cost and none of the build risk.**

## 5. And registration is not on the product path

Established in the previous run and unchanged: **no module under
`tower/tower/` imports `world_registration`.** It is invoked by the CLI,
by four test modules, and by research harnesses. It is 62% of the Stage 0
*benchmark* cost, and 0% of what happens when a wearer walks a room.

So the single genuine Python hotspot in World Builder is in code the
product does not currently execute. Optimising it buys research iteration
speed, not product latency — which is a legitimate but much smaller prize,
and it should be priced as such.

## 6. What this does NOT yet establish

- Whether anything scales badly with keyframe or landmark count — a flat
  per-frame cost is assumed from `_Chain.forget_before`'s pruning but is
  measured here only on a 75-keyframe capture. **Being measured separately
  on the 448-keyframe canonical capture.**
- Peak memory on long sessions.
- Whether flattened numpy actually delivers the predicted win, and how
  close it gets to a native kernel. **Being benchmarked separately.**
- Whether a C++ toolchain is even available on this host (earlier
  in-repo evidence says no MSVC and no `cl.exe`).
