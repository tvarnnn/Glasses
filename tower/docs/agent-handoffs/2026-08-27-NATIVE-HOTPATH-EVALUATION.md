# Native hot-path evaluation: should World Builder move to C++?

**Branch:** `world-builder/next-generation`
**Starting commit:** `e68b323`
**Ending commit:** _(filled at close)_

---

## VERDICT: NO. Do not migrate World Builder to C++.

Not "not yet", and not "not this quarter". On measured evidence the
premise does not hold, and it is overdetermined — four independent
reasons, any one of which would be sufficient:

1. **The product hot path has no Python bottleneck.** 79% of a full
   replay is already executing inside OpenCV's C++.
2. **There is no GIL bottleneck.** A competing pure-Python thread keeps
   **86.9%** of its throughput during a replay.
3. **On the one genuine Python hotspot, vectorised numpy captured 94% of
   the theoretically available win** — measured end to end, not on a
   kernel microbenchmark. C++ could buy at most the remaining 6%.
4. **C++ cannot be built on this host at all.** No MSVC, no Build Tools,
   no Windows SDK, no MinGW, no cmake/ninja; a trivial `PyInit` extension
   fails to compile; and there is **no CI** to build it elsewhere.

**What was done instead:** three pure-Python/OpenCV changes that took the
measured wins without any of the cost. Those are in §4.

## 1. Methodology

- `cProfile` for attribution, `time.perf_counter` for wall time,
  `tracemalloc` + RSS for memory.
- Code resolution asserted every run: the shared venv's editable install
  otherwise resolves `tower` at the MAIN repo, a different branch.
- cwd pinned to `<worktree>/tower`, because
  `redaction.DEFAULT_MODEL_PATH` is RELATIVE — face redaction silently
  switches off from another directory, and it is 22.8% of the runtime.
- **Noise floor MEASURED at 11%** (registration, unprofiled, two runs:
  5.75 s and 6.39 s). No improvement below that is claimed.
- **cProfile inflates Python frames specifically**, so every "native
  share" below is if anything an under-estimate. Profiled 6.41 s against
  unprofiled 5.75–6.39 s.

## 2. Baseline: where the time actually goes

### 2.1 Product hot path — replay + build

Canonical capture, 1,848 frames → 448 keyframes, **32.0 s**:

| | tottime | share | |
|---|---|---|---|
| `FaceDetectorYN.detect` | 10.734 s | **33.6%** | native |
| `calcOpticalFlowPyrLK` | 4.887 s | 15.3% | native |
| `goodFeaturesToTrack` | 1.530 s | 4.8% | native |
| `findHomography` | 1.394 s | 4.4% | native |
| numpy `_var` (sharpness) | 1.302 s | 4.1% | numpy |
| `imdecode` | 1.253 s | 3.9% | native |
| `Laplacian` | 1.129 s | 3.5% | native |
| `detectAndCompute` | 1.111 s | 3.5% | native |
| `resize` | 0.873 s | 2.7% | native |
| file I/O | ~2.42 s | 7.6% | OS |

**Native OpenCV totals 25.29 s = 79.1%.** On the smaller capture it was
68% — **the native share RISES with scale**, so the case for C++ gets
weaker on exactly the workloads that matter most.

The largest Python-side costs are JSON serialisation and filesystem
syscalls. There is no Python loop, no object-churn hotspot, and no
NumPy/OpenCV boundary hotspot to migrate.

**And the product is not latency-constrained:** 1,848 frames in 32.0 s is
**17.3 ms/frame against an ~83 ms budget at 12 fps** — roughly 5×
headroom, and that figure includes `build()`.

Incidentally: **face redaction is the single most expensive operation in
World Builder**, larger than optical flow. It is already native, and §5
records that nothing behaviour-preserving makes it cheaper.

### 2.2 The one real Python hotspot — registration

`scripts/world_registration.py`, canonical world, **6.41 s**:
`_residuals` at **2.487 s tottime = 38.8%**, 38,483 calls, **7.6 M
point-residuals at 327 ns each** — roughly two orders of magnitude above
what the arithmetic costs.

Why: a **Python `for` loop over observations** making ~40 numpy calls per
invocation on arrays of **~44 rows**, where numpy cannot amortise its
dispatch. Measured working size: **4.5 cameras, 197.6 points per call**.
And the observation arrays are **invariant across all 38,483 calls** —
re-walked every time, stacked never.

**THE BOUND THAT DECIDED THIS.** `_residuals` cumtime was **2.724 s of
6.409 s**, so a *free* residual kernel would give **1.74×** and no more.
That is the ceiling for any language.

**And registration is not on the product path.** No module under
`tower/tower/` imports `world_registration` — only the CLI, four test
modules and research harnesses. It is 62% of a benchmark and 0% of what
happens when a wearer walks a room.

## 3. GIL — measured, not argued

"C++ frees the GIL" is checkable. A CPU-bound **pure-Python** counter
thread (deliberately pure Python — a numpy probe would release the GIL
itself and measure nothing) ran alongside a replay in the same process.

**Throughput retained: 86.9%.** World Builder releases the GIL for the
large majority of its work, which is what OpenCV does around native
calls, and is consistent with the 79%-native profile.

_Caveat, stated because it matters: that run was taken while two other
agents were saturating the machine, so the absolute replay time was
inflated. The direction is corroborated independently by the profile; the
figure is re-measured on a quiet machine in §8._

## 4. What was changed — three wins, no native code

### 4.1 Vectorised residual — registration 1.64× end to end

`_pack()` stacks the observation arrays **once per `_refine` call**
instead of walking them per evaluation; `_residuals_packed()` computes
all point-residuals in one pass via a gather and an `einsum`.

| | before | after |
|---|---|---|
| `_residuals` tottime | 2.487 s | **0.985 s** (2.5×) |
| its cumtime | 2.724 s | **1.307 s** |
| `_refine` cumtime | 3.468 s | **2.065 s** |
| **registration wall** | **5.75 / 6.39 s** | **3.10 / 4.02 / 3.99 s** |
| peak Python-traced memory | 24.0 MB | **24.1 MB** |
| process RSS | 186.7 MB | **183.9 MB** |
| admitted pairs / segments / points | (4,5),(5,32) / 3 / 3,739 | **identical** |

**1.64× end to end against a 1.74× ceiling — 94% of everything that was
available.** Memory unchanged. Output identical.

The original loop is **kept as `_residuals`, the reference
implementation**, still called at a non-hot site, and the two are checked
against each other by 19 parity tests.

### 4.2 JSON write — 3.58×, byte-identical

`tower/storage.py`: `json.dump(payload, handle)` streams one `write()`
per token through `TextIOWrapper`. Building the string once and writing
once measured **41.13 ms → 11.48 ms (3.58×)** on a realistic 0.74 MB
payload, with output verified **byte-identical**.

**`orjson` was measured and REFUSED**: its bytes differ (separators,
`1e-07` vs `1e-7`) *and* it writes NaN/Infinity as `null`, which would
silently defeat the `allow_nan=False` guard that keeps
non-interoperable tokens off the wire.

### 4.3 Sharpness — 7.40× on every frame

`frontend.measure_sharpness` ran `cv2.Laplacian(gray, CV_64F).var()` — a
1.8 MB float64 allocation per frame, reduced in numpy. Replaced with
`cv2.meanStdDev(cv2.Laplacian(gray, CV_16S))`.

**MEASURED on 120 real frames: 1.429 ms → 0.193 ms per frame (7.40×)**,
~2.3 s of a 32 s replay.

The intermediate is **exact, not approximate**: 8-bit input with
`ksize=1` bounds the Laplacian at ±1020 against int16's ±32767, so
saturation is unreachable — verified by `np.array_equal` against the
float64 result on real frames (observed range −497..324). The variance
then differs only in the last bits of a float64 (**max 4.1e-16, median
1.2e-16**).

That last point matters because sharpness feeds an absolute threshold and
a rolling ratio, so a frame sitting exactly on the bar could in principle
flip. Corpus parity was therefore re-run: _(result in §6)_.

### 4.4 The closing evidence: the profile no longer contains Python

Re-profiling the same 1,848-frame capture after the three changes, the
top of the profile by tottime is:

| | tottime | |
|---|---|---|
| `FaceDetectorYN.detect` | 9.877 s | native |
| `calcOpticalFlowPyrLK` | 4.282 s | native |
| `goodFeaturesToTrack` | 1.330 s | native |
| `findHomography` | 1.294 s | native |
| `imdecode` | 0.982 s | native |
| `detectAndCompute` | 0.980 s | native |
| `resize` | 0.797 s | native |
| `_io.open` | 0.604 s | OS |
| `nt.replace` | 0.362 s | OS |

**Every Python-side entry has left the top of the profile.** numpy `_var`
(was 1.302 s), `Laplacian` (1.129 s) and the JSON encoder are all gone.
What remains is native OpenCV and filesystem syscalls, in that order.

That is the strongest closing argument for the verdict: **there is now
nothing left in this pipeline that a C++ rewrite could take.** The
remaining cost is either already C++, or it is the operating system.

## 5. Rejected, with the measurement that rejected it

| candidate | verdict | why |
|---|---|---|
| **C++ / pybind11 / nanobind anywhere** | **REJECTED** | §0. Cannot be built here; ≤6% left after numpy; no CI. |
| **numba on `_residuals`** | REJECTED | 7.48× on the kernel, but 528 ms JIT on first call, 42 MB, and a numpy version pin — for 0.33 s on a tool the product never calls. |
| **batched Jacobian (one call for base + 7 probes)** | REJECTED | 4.08× on the kernel *block*, but the Amdahl ceiling is 1.74× and 1.64× is already banked. Buys ≤6% for a 4-D tensor path to keep parity on. |
| **pre-allocated residual buffers** | REJECTED | Measured **0.83× — a pessimisation.** The Python loop was the cost, not allocation. Worth recording because it is the intuitive fix and it is wrong. |
| **`orjson`** | REJECTED | Bytes differ; writes NaN/Inf as `null`, defeating a deliberate guard. |
| **Cheaper `FaceDetectorYN`** | REJECTED | The backend/target lever **does not exist in OpenCV 5.0.0** — OpenCL/CUDA return bit-identical output, i.e. they are ignored, and the runtime warns as much. Only input size is a real lever and it weakens redaction, which is a privacy feature. The 33.6% stays. |
| **Rewriting OpenCV call sites** | REJECTED | They are one Python line entering C++. |

## 6. Corpus parity and tests

### 6.1 Keyframe decisions are unchanged — the gate that mattered

Full 8-capture corpus replay, against the committed baseline:

| metric | baseline `d3d24b5` | after | delta |
|---|---|---|---|
| **keyframes** | 1,712 | **1,712** | **0** |
| **rejection histogram** | insufficient_motion 5184 / blurred 2271 / tracking_lost 119 / tracking_degraded 85 / no_motion_evidence 1 | **identical** | **none** |
| segments | 230 | 232 | +2 |
| poses_solved | 591 | 620 | +29 |
| points | 75,369 | 71,122 | -4,247 |

**The sharpness change flipped no keyframe decision.** That was the only
real risk in it, and it is closed.

The deltas that DID move are not this lane's. `+29 solved`, `-4,247
points`, `+2 segments` are **exactly** the previous lane's guided
re-observation figures, which this baseline artifact predates. Sharpness
and JSON are behaviour-neutral.

### 6.2 A number NOT to quote: the 2.19x is not real

Comparing this run's wall time against the stored baseline gives
**267.5 s -> 122.4 s, 2.19x**. **That comparison is invalid and is
recorded here so nobody repeats it.**

The stored baseline was produced by a different lane, in a separate
`git archive` tree, at a different time, with a cold page cache and
different machine load. The component measurements predict about
**1.17x** (sharpness 7.6% + JSON 6.6%), so most of the apparent 2.19x is
measurement conditions, not code.

This is precisely the benchmark-vanity trap the brief warns against, and
the honest number comes from a same-session A/B running both arms back to
back in one process with alternating arm order --
`scripts/research/native_eval/ab_same_session.py`. Result in section 6.3.

### 6.3 Same-session A/B — the honest number is 1.16x

Both arms run back to back in ONE process, same captures, same warm
cache, **alternating arm order across repeats** so any drift in machine
load is charged to both arms equally. The old implementations are
restored by monkeypatch, so the only difference between arms is the two
functions under test.

| capture | old | new | speedup | parity |
|---|---|---|---|---|
| `64f48114` | 6.34 s | 5.53 s | 1.15x | **IDENTICAL** |
| `4fea31e2` | 5.97 s | 4.92 s | 1.21x | **IDENTICAL** |
| `fe744b68` | 6.89 s | 6.17 s | 1.12x | **IDENTICAL** |
| **TOTAL** | **19.20 s** | **16.62 s** | **1.16x** | |

Parity means keyframes, poses_solved and points were identical in every
arm and every repeat.

**1.16x measured against 1.17x predicted from the component
measurements.** The model was right, and the naive
compare-against-stored-baseline figure was inflated **~1.9x by
measurement conditions alone**. That gap is the most transferable
methodological result in this document.

**Is 1.16x worth keeping?** It clears the 11% noise floor, but not by
much, and it is consistent in direction across three captures and two
repeats. It is kept because it is **free**: no new dependency, no build
system, no fallback path, byte-identical output, behaviour-neutral
keyframe decisions, and less memory traffic per frame. It would NOT be
worth keeping if it cost a native toolchain -- which is exactly the
trade this lane was opened to evaluate.

### 6.4 Tests

| point | result |
|---|---|
| before this lane | 1,637 passed, 64 skipped |
| after residual vectorisation (+19 parity tests) | **1,656 passed, 64 skipped, 0 failed** |
| after sharpness + JSON (+9 tests) | **1,665 passed, 64 skipped, 0 failed** (4m49s) |

## 7. Build / toolchain — the blunt finding

**A native extension cannot be built on this host.** MEASURED by the
toolchain lane: no MSVC, no Visual Studio, no Build Tools, no Windows
SDK, no MinGW/MSYS2/LLVM, no cmake, no ninja. `_get_vc_env('x64')` fails.
A trivial `PyInit_trivial` module **fails to compile**. nvcc is 11.8 and
rejects `sm_120` while the GPU is capability (12,0) — and it needs
`cl.exe` regardless. The `link.exe` on PATH is Git's coreutils, which is
a trap rather than a toolchain.

**There is no CI**: a depth-5 search for `.github`, any `.yml`/`.yaml`,
`tox.ini`, `Makefile` or `CMakeLists.txt` returns **zero files**. The
project is a pure-Python distribution; adding `ext_modules` would break
installation on the only host it runs on.

So the fallback would be the only path ever executed here — unexercised
C++ carrying last-ulp divergence risk inside a Levenberg step-acceptance
test. **Standing up wheel CI is a prerequisite, not an optimisation, and
it is larger than the 0.46 s it would protect.**

## 8. Remaining native candidates

**None that clear the bar.** For the record, if the situation changed:

- If registration were wired into the product path *and* run on much
  larger worlds, `_residuals_packed` would be the only kernel worth
  revisiting — and numba, not C++, is the cheaper next step.
- Everything else is already native.

## 9. Mac / iOS implications

**None. `ios/` untouched.** All three changes are implementation-internal
and wire-compatible:

- JSON output is **byte-identical** — verified, not assumed.
- Sharpness differs by ≤4.1e-16 relative and is not itself on the wire;
  it gates keyframe admission, and corpus parity confirms the decisions.
- The residual change is internal to a script iOS never sees.

No schema, no field, no coordinate convention, no persisted-format change.
