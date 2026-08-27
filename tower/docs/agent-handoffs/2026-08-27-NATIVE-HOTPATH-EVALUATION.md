# Native hot-path evaluation: should World Builder move to C++?

**Branch:** `world-builder/next-generation`
**Starting commit:** `e68b323`
**Ending commit:** see `git log e68b323..HEAD` — **21 commits**
**Working tree:** clean · **Push status:** all pushed to
`origin/world-builder/next-generation` · **`ios/` untouched** · **not merged**

---

## VERDICT: NO. Do not migrate World Builder to C++.

Not "not yet", and not "not this quarter". On measured evidence the
premise does not hold, and it is overdetermined — four independent
reasons, any one of which would be sufficient:

1. **The product hot path has no Python bottleneck.** 79% of a full
   replay is already executing inside OpenCV's C++.
2. **There is no GIL bottleneck.** A competing pure-Python thread keeps
   **82.7%** of its throughput during a replay, against a **46.5%**
   floor established by a positive control that provably holds the GIL.
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
  switches off from another directory, and it is **33.6%** of the runtime
  on the canonical capture (an earlier draft said 22.8%, which was the
  figure from the smaller capture; 33.6% is the one that matters).
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

**Time in compiled code totals ~79%** on this capture, against 68% on the
smaller one — **the compiled share RISES with scale**, so the case for
C++ gets weaker on exactly the workloads that matter most.

**Two corrections to how that number was first stated.** It was labelled
"native OpenCV totals 25.29 s = 79.1%", and both halves were loose. The
classifier counts every `cv2.*` call, **every numpy ufunc and every
builtin** as compiled, so "native OpenCV" is the wrong label — it is
"time in compiled code". And the rows listed above sum to **22.911 s**,
not 25.29 s; the remainder is in unlisted rows, so the headline could not
be reconstructed from the evidence shown.

Counting numpy as un-migratable was the one tendentious step, and **this
lane's own sharpness win refutes it**: eliminating numpy `_var` was
exactly a "compiled" cost removed by better dispatch.

The share is real and the conclusion is unaffected — and §5 of the review
shows the direction of the profiler's bias makes the TRUE figure higher,
plausibly ~83%.

The largest Python-side costs are JSON serialisation and filesystem
syscalls. There is no Python loop, no object-churn hotspot, and no
NumPy/OpenCV boundary hotspot to migrate.

**And the product is not latency-constrained — but by less than I first
claimed. CORRECTED.**

My first version of this line read "17.3 ms/frame against an ~83 ms
budget — roughly 5x headroom". That averaged over ALL delivered frames,
and most frames are cheap rejections, so it flattered the result.

The scaling lane measured the number that actually matters — latency on
frames that are ACCEPTED as keyframes, which is where the expensive work
happens: **47.2 ms median in the first quarter of a 448-keyframe walk,
50.0 ms in the last.** Against an ~83 ms budget at 12 fps that is roughly
**1.7x headroom, not 5x.**

Still not latency-constrained, and **flat in session length** — a fitted
slope of +0.008 ms per keyframe with r = +0.099, which is noise. But 1.7x
is a margin worth protecting rather than spending, and it makes the
per-frame sharpness win (§4.3) more valuable than I first credited, since
it applies to every delivered frame rather than only to accepted ones.

The live `observe()` path measures **94.7% native** by tottime in
isolation — higher than the 79.1% for replay+build, because that figure
includes `build()` and the filesystem. Its single largest Python frame is
**0.092 s out of 24 s (0.4%).**

And the tightest number in this document, which is the one to watch:
**accepted-keyframe p95 is 65 ms against the 83 ms budget.** That is
~1.28x headroom at the tail, not 1.7x and certainly not 5x. It is still
inside budget, it is still flat in session length, and it is the figure
that would justify future work on the live path if anything ever does.

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

My first run reported **86.9%**, taken while two other agents saturated
the machine. The adversarial reviewer could not get a quiet machine
either — and instead of reporting an indefensible number, made the probe
**self-calibrating** by adding a positive control: a second pure-Python
hog that provably holds the GIL, establishing what "collapsed" looks like
*under that exact load*. Three interleaved rounds:

| | retained |
|---|---|
| negative control (spinner alone) | 100% |
| **subject (during replay)** | **82.7%** (rounds: 68.4 / 91.9 / 82.7) |
| positive control (a real GIL holder) | **46.5%** — against a ~50% prediction |

**82.7% against a 46.5% floor is clean separation.** My 86.9% was about
four points optimistic; the conclusion is unchanged. World Builder
releases the GIL for the large majority of its work, which is what OpenCV
does around native calls, and is consistent with the native-share profile.

That positive control is the better method and is worth reusing: it turns
"the machine was noisy" from an excuse into a calibrated axis.

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
| admitted pairs / segments / points | (4,5),(5,32) / 3 / 3,739 | **same admissions** |

**1.64x end to end against a 1.74x ceiling.** Memory unchanged.

**"94% of what was available" is the flattering framing, and both numbers
belong here.** 1.64/1.74 is a ratio of SPEEDUPS. By time actually
removed, 6.409/1.64 = 3.908 s, so 2.501 s of the 2.724 s removable was
removed: **91.8%**. Both are defensible, 94% is the higher, and neither
changes the verdict.

**And "output identical" was true of one world, not of the change.**
Running the whole `_refine` both ways over 80 problems from a known
Sim(3): **0 of 80 converged bit-identically**, max parameter divergence
**1.405e-09**, max scale drift **0.0006 ppm**. The step-acceptance branch
(`if probe_cost < cost`) does diverge, and the converged Sim(3) moves —
by nanometres on metre-scale translations, against admission gates at
4 px and whole degrees, so no gate can plausibly flip. Determinism is
preserved: same code, same answer every time. The honest phrasing is
**"agrees to ~1e-9 and re-derived the same admissions on every world
tested"**, not "identical".

**Two figures, both real — quote the range, not the better one.** I
measured **1.64x** end to end on the canonical world. The scaling lane,
measuring independently across **sixteen** worlds, got **1.43x** on the
registration stage with byte-identical outcomes. Different populations,
not a disagreement: one world against sixteen, and `register()` end to end
against the stage in isolation. **The honest headline is 1.4–1.6x**, and
the ceiling argument is unaffected either way — the point was never the
exact multiple, it was that numpy reached the neighbourhood of a bound
that C++ could not have exceeded.

The original loop is **kept as `_residuals`, the reference
implementation**, and the two are checked against each other by 19 parity
tests.

**It is not a fallback that will rot.** Instrumented over a real run, the
reference is called **4 times** — once per directed fit, at the
non-hot quality-report site — against **38,435** calls to the vectorised
path. So it is live production code exercised on every registration, at
negligible cost, rather than a dead branch nobody would notice breaking.
That was a deliberate choice: an unexercised reference implementation is
worse than none, because it invites trust it has not earned.

#### 4.1.1 A caveat on the vectorised residual: it INVERTS on tiny inputs

Found by the scaling lane's independent micro-benchmark, and it is a real
property of the change rather than a measurement artifact:

| cameras per call | speedup |
|---|---|
| 1 | **0.82x — SLOWER** |
| 4 (the measured working size) | **3.04x** |
| overall | 1.59x |

The vectorised path is **overhead-bound, not FLOP-bound**: below about
three cameras the gather and the `einsum` setup cost more than the Python
loop they replace.

**On the default configuration that case cannot arise.** MEASURED over a
full registration run, the cameras-per-call distribution is exactly
`{3: 46, 4: 46, 5: 46, 6: 46}` — minimum 3, never fewer. That is
structural, not luck: `Thresholds.min_cameras = 3` is enforced at
`world_registration.py:906` *before* a candidate reaches `_refine`, with
the comment that fewer "are needed before a baseline means" anything.

**But it is reachable by configuration.** `--min-cameras 1` would admit
2-camera and 1-camera fits and land in the inverted regime. That is a
research knob, the slowdown is ~18% on a stage that is not on the product
path, and nothing silently breaks — so it is documented rather than
guarded with a branch. A successor lowering that threshold should know
the residual kernel stops paying for itself there.

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

**The dtype guard added after review costs 0.026 ms/frame** (0.193 →
0.219), i.e. 13% of the win back, or **48 ms across the 1,848-frame
capture — 0.15% of the replay.** That is the price of turning a silent
wrong answer on colour input into a loud refusal, and it is worth paying:
`meanStdDev` returns per-channel deviations, so `[0, 0]` on a 3-channel
array would have quietly reported channel zero where `.var()` pooled all
three — a **7.4e-3 relative** error, twelve orders of magnitude outside
the bound this function's docstring claims.

The intermediate is **exact, not approximate**: 8-bit input with
`ksize=1` bounds the Laplacian at ±1020 against int16's ±32767, so
saturation is unreachable — verified by `np.array_equal` against the
float64 result on real frames (observed range −497..324). The variance
then differs only in the last bits of a float64 — **max 6.22e-16 across
all 9,372 corpus frames** (an earlier draft quoted 4.1e-16, measured on
only 120).

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
| after the review's corrections (+1 test) | **1,665 passed, 64 skipped, 1 flake** — see below |

**The one failure is an environmental flake, not a regression, and here is
why I am confident rather than hopeful:**

`test_result_channel_hostile.py::test_the_channel_survives_the_world_vanishing_mid_subscription`
failed with `PermissionError: [WinError 32] The process cannot access the
file because it is being used by another process`.

- It passes **3/3 in isolation** after the change.
- **The same code already passed**: the 1,665-run above included the
  `storage.py` change and had zero failures. Same code, passed once,
  failed once under heavy concurrent load.
- The test's own docstring documents this exact hazard: it unlinks
  `world.json` while a subscription is live, and records that an earlier
  version "passed or failed by luck" against Windows open handles.
- The direction is wrong for it to be mine: `handle.write(json.dumps(...))`
  holds the file open for LESS time than per-token `json.dump`, so the
  change **narrows** this race window rather than widening it.

Recorded rather than re-run until green, because "it passed on the
retry" is how a real intermittent bug gets buried.

## 6.5 CPU, RAM, GPU, VRAM

- **CPU**: single-process, and the GIL is released for the large majority
  of the work (§3), so it coexists with other cartridges rather than
  monopolising the interpreter.
- **RAM**: registration peak Python-traced memory **24.0 MB -> 24.1 MB**,
  process RSS **186.7 MB -> 183.9 MB**. No regression. The sharpness
  change strictly *reduces* memory traffic: it no longer allocates a
  1.8 MB float64 Laplacian per frame. The JSON change adds a transient
  string bounded by the payload (largest persisted: 1.71 MB).
- **GPU / VRAM: not applicable, and verified rather than assumed.**
  `tower/world_builder/` **does not import torch** and issues no CUDA
  calls; the only two mentions of torch in the package are a comment in
  `redaction.py` explaining a dependency that was *rejected*.
  `FaceDetectorYN` runs on CPU — and per the toolchain lane, OpenCV
  5.0.0's backend/target selectors are inert here (OpenCL and CUDA return
  bit-identical output, and the runtime warns that back-ends are
  unsupported by its new graph engine).

  So World Builder's replay path uses **zero VRAM**, which is worth
  stating plainly: it leaves the whole 12 GB free for Scene Understanding,
  Object Memory and AI workloads. A native migration would not have
  changed that either way.

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
