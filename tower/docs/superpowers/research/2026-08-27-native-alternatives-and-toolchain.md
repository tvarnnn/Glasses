# Native alternatives and toolchain: what C++ would have to beat, and whether it could be built

2026-08-27. Worktree `C:\Users\tvllo\Projects\Glasses-world-builder`, branch
`world-builder/next-generation`. Host: Windows 11, RTX 5070 (sm_120), 32 GB,
Python 3.12.5, numpy 2.5.2, **OpenCV 5.0.0**, torch 2.13.0+cu132.

---

## Three verdicts

**Q1 — C++ is REJECTED for `_residuals`.** Restructuring the shipped Python
loop into one batched numpy call is **4.08x** and captures **80.3%** of the
saving a C extension could achieve, with **zero new dependencies**. Adding
`numba` captures **94.6%**. The residual gap C++ would buy over the batched
numpy version is **0.46 s on a 6.4 s registration run (7.2%)**; over numba it
is **0.13 s (2.0%)**.

**Q2 — Yes, two free wins and one dead end.** `json.dump(payload, handle)` is
**3.9x slower than `handle.write(json.dumps(payload))` for byte-identical
output** — a one-line change in `tower/storage.py:51`, no dependency, no
format change. `cv2.meanStdDev` on the Laplacian is **7.8x** faster than
`ndarray.var()` and agrees to **1.2e-16 relative** (last-ulp). `orjson` is
12x but is **not** a drop-in: it changes the bytes *and* silently writes
`NaN`/`Infinity` as `null`, defeating the `allow_nan=False` guard. For
`FaceDetectorYN` there is **no behaviour-preserving speedup** on this build.

**Q3 — A native extension is NOT maintainable on this machine. Blunt: it
cannot be built here at all, and there is no CI to build it elsewhere.**
No MSVC, no Visual Studio, no Build Tools, no Windows SDK, no MinGW, no
MSYS2, no clang, no cmake, no ninja. A trivial C extension fails to compile.
There is no `.github/` directory anywhere in the repository.

---

## Method and provenance

Everything below is labelled:

- **MEASURED-by-me** — with the command that produced it.
- **QUOTED** — with source.
- **ESTIMATED** — with the method.

Environment discipline: no venv exists in this worktree, and the only venv
(`C:\Users\tvllo\Projects\Glasses\tower\.venv`) has an editable install
mapping `tower` at the MAIN repo on a different branch. Every command below
therefore ran as:

```
cd C:\Users\tvllo\Projects\Glasses-world-builder\tower
PYTHONPATH="C:\Users\tvllo\Projects\Glasses-world-builder\tower" \
  C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe <cmd>
```

**MEASURED** — the mapping was verified, not assumed:

```
import tower.world_builder.backends.classical as m
m.__file__  -> C:\Users\tvllo\Projects\Glasses-world-builder\tower\tower\world_builder\backends\classical.py
m.EXTEND_REFERENCE_DEPTH -> 3
```

`numba`, `llvmlite`, `orjson` and `msgspec` were installed with
`pip install --target C:\Users\tvllo\AppData\Local\Temp\native_eval_pkgs`
and reached only through `PYTHONPATH`. **The shared venv was not modified** —
re-checked afterwards: all four still report `absent from shared venv`, and
`numpy` is still 2.5.2, `cv2` still 5.0.0.

**Nothing under `tower/tower/` was modified.** `ios/` was not touched. The
only files written are the three benchmark scripts under
`tower/scripts/research/native_eval/` and this report.

### Is the fixture representative?

The harness builds synthetic observations matching the measured shape
(4–6 cameras, ~44 points each, ~200 total, float64). To check that this
actually reproduces the hotspot rather than a lookalike, the control was run
under `cProfile` the way the original profile was taken:

| | ns per point-residual (tottime) |
|---|---|
| QUOTED, profiling lane, real data | 327 |
| **MEASURED**, this harness under `cProfile` | **321.5** |

Within **1.7%**. The fixture reproduces the measured hotspot. (Outside the
profiler the control runs at ~203 ns/point — the ~120 ns gap is `cProfile`
overhead, which is why all headline numbers below are *ratios*.)

---

## Q1 — the best non-C++ option for `_residuals`

> **Concurrency note.** This worktree is shared with other lanes of the same
> evaluation, which modified `scripts/world_registration.py` while this work
> was in progress. Re-checked at write-up: the shipped `_residuals` body is
> **unchanged and still byte-identical** to the control in
> `bench_residuals.py`; only its line number moved (543 -> 651) because a
> `_residuals_packed(params, pack, intrinsics)` and a `_Pack` class were
> inserted above it. That other lane has independently converged on
> variant (b) of this report — which is corroboration of the Q1 verdict,
> not a conflict with it. All numbers below stand.

`_residuals` (`scripts/world_registration.py:543`, now `:651`) is **QUOTED** at 2.487 s
tottime, **38.8% of a 6.4 s registration run**, 38,483 calls, mean 4.5
cameras / 197.6 points per call.

The structure that matters: it is a Python `for` loop over observations doing
five or six small numpy ops per observation on arrays of ~44 rows. At that
size numpy's per-call dispatch overhead dominates the arithmetic. The loop
runs 38,483 times over observation lists that **never change** within a
`_refine`.

### Candidates

- **(a) control** — the shipped loop, verbatim.
- **(b1) flat gather+einsum** — pack once into `(N,3)` object points,
  `(N,2)` image points, `(C,3,3)` rotations, `(N,)` camera index; then
  `r_source[cam_idx]` gather + `einsum`.
- **(b2) flat all-camera gemm** — rotate the whole point set by *every*
  camera (`(C,N,3)`, pure BLAS), then take the right row. Avoids the
  `(N,3,3)` gather.
- **(b3) flat blocks + prealloc** — per-camera contiguous `np.matmul(...,
  out=)` slices into one preallocated output.
- **(c) prealloc only** — the shipped loop with output buffers reused.
- **(d) numba** `@njit` over the flat pack.
- **(e) C proxy** — an `@njit` **scalar** loop that also does the pose
  composition itself, with no numpy call anywhere in the kernel. See the
  estimate caveat below.

Every variant is gated on `np.allclose(got, reference, rtol=0, atol=1e-9)`
against the control **before** it is allowed to post a time. All passed.

### Per-call results

**MEASURED** —
`PYTHONPATH="<worktree>\tower;<scratch>" <venv-python> scripts/research/native_eval/bench_residuals.py`
Mean measured shape, 5 cameras / 220 point-residuals, best-of-40 blocks of 40:

| variant | µs/call | ns/point-residual | speedup | exact |
|---|---:|---:|---:|:--:|
| (a) control — shipped loop | 44.57 | 202.6 | 1.00x | yes |
| (b1) flat gather+einsum | 22.00 | 100.0 | **2.03x** | yes |
| (b2) flat all-camera gemm | 25.57 | 116.2 | 1.74x | yes |
| (b3) flat blocks+prealloc | 25.07 | 114.0 | 1.78x | yes |
| (c) shipped loop, prealloc buffers | 53.47 | 243.0 | **0.83x** | yes |
| (d) numba `@njit` (flat pack) | 5.96 | 27.1 | **7.48x** | yes |
| (e) njit scalar — C proxy | 3.30 | 15.0 | **13.53x** | yes |
| pack build (once per `_refine`) | 13.70 | — | — | — |

Held across 4/176, 6/264, 2/88 and 12/528 shapes; (b1) ranges 1.34x–3.33x,
(d) 5.13x–11.45x, (e) 8.95x–24.29x. Speedups grow with size, so the mean
shape is the conservative row.

**Negative result worth recording: (c) pre-allocation alone is a
pessimisation** — 0.83x at the mean shape, 0.80x at 12 cameras. Reusing
buffers adds slicing and `out=` bookkeeping without removing a single Python
iteration. The Python loop, not allocation, is the cost. This kills the
cheapest hypothesis on the list.

### The batched Jacobian — the option that changes the verdict

Profiling the per-call number understates what pure numpy can do, because it
prices the wrong unit of work. `_refine` (`world_registration.py:597-616`)
evaluates `_residuals` **eight times per Gauss-Newton iteration** — one base
plus seven finite-difference probes — with the same observations and eight
nearby parameter vectors. Those eight evaluations can be **one** batched
`(B,7) -> (B,N,2)` numpy call, which amortises the fixed pose/dispatch
overhead eight ways. There is a real fixed floor to amortise: **MEASURED**,
the pose composition alone (`math.exp` + `cv2.Rodrigues` + the `(C,3,3)`
compose) is **4.39 µs/call**, of which `cv2.Rodrigues` is 1.11 µs — i.e.
20% of variant (b1)'s entire runtime is per-call overhead that does not
scale with points.

**MEASURED** —
`<venv-python> scripts/research/native_eval/bench_batched_jacobian.py`
One Jacobian block = 8 evaluations, 5 cameras / 220 points. The batched
result was verified `np.allclose(..., atol=1e-9)` against eight separate
control calls:

| strategy | µs/block | µs/eval | speedup |
|---|---:|---:|---:|
| (a) control x8 (shipped) | 455.61 | 56.95 | 1.00x |
| (b1) flat gather x8 | 195.59 | 24.45 | 2.33x |
| **(f) ONE batched (B=8) numpy call** | **111.68** | **13.96** | **4.08x** |
| (d) numba x8 | 50.10 | 6.26 | 9.09x |
| (e) C-proxy x8 | 27.13 | 3.39 | 16.80x |

### The decisive question

Ratios are the wrong scoreboard; the right one is *what fraction of the
saving a C extension could deliver does the non-C++ option already capture*:

**MEASURED**, computed by the script itself:

- pure numpy (f), no new dependency: **80.3%** of the C-achievable saving
- numba (d): **94.6%**

Projected onto the whole registration run (**ESTIMATED** — Amdahl on the
quoted 2.487 s / 6.4 s split, using the measured block speedups):

| option | `_residuals` time | run total | vs 6.4 s |
|---|---:|---:|---:|
| shipped | 2.487 s | 6.40 s | — |
| (b1) flat, per-call | 1.067 s | 4.98 s | −22% |
| **(f) batched numpy** | **0.609 s** | **4.52 s** | **−29%** |
| (d) numba | 0.274 s | 4.19 s | −35% |
| (e) C++ | 0.148 s | 4.06 s | −37% |

**C++ buys 0.46 s over pure numpy and 0.13 s over numba, on a 6.4 s run.**

### How (e) was estimated, and why it is generous to C++

**ESTIMATED.** Variant (e) is not a built extension — no compiler exists on
this host (Q3), so one could not be built to measure. It is an `@njit`
scalar loop that performs *exactly* the end-to-end work a hand-written
pybind11/nanobind `_residuals` would: the pose composition (`r_target @
rot.T`, `scale*t_target - r_source @ translation`) and the per-point project
-and-subtract, entirely in scalar C-level code with no numpy call inside the
kernel. LLVM -O3 on that loop is a fair stand-in for MSVC -O2 on the same
loop.

It is **generous to C++ in three ways**, so the 80.3%/94.6% figures are
lower bounds on how much non-C++ captures:

1. It excludes pybind11/nanobind argument marshalling and `py::array_t`
   bounds/stride checking — realistically another 0.5–1 µs per call, which
   at 3.30 µs/call is 15–30%.
2. Its Python wrapper still calls `cv2.Rodrigues` (1.11 µs of the 3.30 µs),
   as a real extension boundary would unless Rodrigues were reimplemented
   in C too.
3. It assumes the pack (`(N,3)` contiguous arrays) already exists, i.e. the
   extension inherits the same restructuring that variant (b) needs anyway.

### What (f) costs to adopt

`_residuals` alone cannot be swapped — the batching is a change to
`_refine`'s Jacobian loop as well. The pack must be built once per `_refine`
(cleanest at the end of `_pnp_observations`): **MEASURED** 13.70 µs,
amortised over the ~400 `_residuals` calls a `_refine` makes (40 iterations
x ~10 evaluations) is **0.034 µs/call — 0.15% of the batched cost.**
Negligible.

### On numba as a dependency

It is genuinely installable here — a pure wheel install, no compiler
(`numba` 0.67.0 + `llvmlite` 0.49.0, 42 MB). But **MEASURED**: the first
`@njit` call costs **528 ms of JIT compilation**. On a 6.4 s run that is 8%
of the runtime handed straight back unless `cache=True` persists the
artifact across processes. It also pins `numpy<2.6`, adds 42 MB, and buys
**0.33 s over pure numpy on a 6.4 s run**. Recommendation: **take (f), skip
numba.** Revisit only if the batched numpy version is measured and still
dominates.

---

## Q2 — what else is worth attacking without C++

### JSON — a byte-identical 3.9x that needs no dependency

Persistence compatibility is mandatory, so the first question is what the
bytes are. Write path: `tower/storage.py:45-56`, `json.dump(payload, handle)`
into a UTF-8 text handle, then `fsync`, then atomic replace. The only other
site is `tower/world_builder/store.py:463`, a `json.dumps(payload,
allow_nan=False)` **validation** call whose comment says it exists so the
file stays readable by `JSON.parse`, Swift's `JSONSerialization` and Go's
`encoding/json`.

**MEASURED**, realistic 4000-point payload (`json.dump` vs
`handle.write(json.dumps(...))`, best-of-25):

| write strategy | ms | bytes identical |
|---|---:|:--:|
| `json.dump(payload, handle)` (shipped) | 23.97 | reference |
| `handle.write(json.dumps(payload))` | **6.18** | **yes** |
| `handle.write(json.dumps(payload).encode())`, binary handle | 6.22 | yes |
| with `fsync`: shipped 22.06 ms -> rewritten **6.69 ms** | | yes |

**3.9x, byte-for-byte identical output, one line.** `json.dump` streams
through `handle.write` per fragment; `json.dumps` builds one string and
writes once. This is the recommendation.

**`orjson` is NOT a drop-in.** **MEASURED**, same payload:

| | ms | bytes |
|---|---:|---:|
| `json.dumps` | 6.14 | 477,334 |
| `orjson.dumps` | **0.51** | 429,334 |
| byte-identical | | **NO** |
| semantically equal (`json.loads` both) | | yes |

Two disqualifying differences:

1. **Separators.** `json` writes `", "` / `": "`; orjson writes `","` /
   `":"`. 10% smaller, different bytes. Also float formatting diverges:
   `json` writes `1e-07`, orjson writes `1e-7` — both valid JSON parsing to
   the same double, still different bytes.
2. **The `allow_nan` guard is silently defeated.** **MEASURED**:
   `json.dumps({'x': nan}, allow_nan=False)` raises `ValueError: Out of
   range float values are not JSON compliant`. `orjson.dumps` returns
   `b'{"x":null,"y":null}'`. The guard in `store.py:463` exists precisely
   to leave *no file* rather than an unreadable one; orjson turns a loud
   refusal into a silently wrong coordinate. That is a correctness
   regression, not a performance trade.

One mitigating fact, **MEASURED**: `compute_input_digest`
(`store.py:660-670`) hashes **keyframe IDs**, not serialized JSON bytes.
No content hash on disk depends on the serializer's output. So a future
serializer swap would not invalidate existing worlds' digests — but the
`allow_nan` regression stands on its own, and orjson should not be adopted
without an explicit NaN/Inf pre-check restoring the guard.

**Sizing** — **ESTIMATED**: JSON is QUOTED at ~0.42 s of a 6.35 s
replay+build (6.6%). At 3.9x on the serialize-and-write step, the
byte-identical change recovers roughly **0.3 s (~4.7% of replay+build)** for
a one-line diff.

### Sharpness — a 7.8x that is numerically identical

`measure_sharpness` (`tower/world_builder/frontend.py:161-172`) is
`float(cv2.Laplacian(gray, cv2.CV_64F).var())`. `_var` is QUOTED at 0.267 s
over 527 calls.

**MEASURED**, 640x360 uint8 (and 1280x720, same conclusion):

| step | ms @640x360 | ms @1280x720 |
|---|---:|---:|
| `cv2.Laplacian(gray, CV_64F)` | 0.504 | 1.744 |
| `ndarray.var()` on the CV_64F result | **0.720** | **3.116** |
| `cv2.meanStdDev` on the CV_64F result | **0.092** | **0.413** |
| SHIPPED total `Laplacian(CV_64F).var()` | 1.206 | 3.944 |
| ALT `meanStdDev(Laplacian(CV_64F))` | 0.543 (2.2x) | 2.146 (1.8x) |
| **ALT2 `meanStdDev(Laplacian(CV_16S))`** | **0.154 (7.8x)** | **1.209 (3.3x)** |

Numerical agreement with the shipped value: **relative difference 1.2e-16
at 640x360 and 2.5e-16 at 720p** — last-ulp, for both alternatives. Note
`std[0,0]**2` is the variance, so the returned float is the same number.

`CV_16S` is exactly safe for this input, not merely close: `measure_sharpness`
takes 8-bit `gray` and uses the default `ksize=1`, whose kernel is
`[[0,1,0],[1,-4,1],[0,1,0]]`. The output range is bounded by ±1020, far
inside int16's ±32767, so **no saturation is reachable** and the integer
Laplacian is exact. That precondition is what makes ALT2 legitimate; it
must be re-checked if `ksize` or the input dtype ever changes.

**ESTIMATED**: replacing `.var()` with `cv2.meanStdDev` recovers ~86% of the
0.267 s `_var` cost (~0.23 s); also moving the Laplacian to `CV_16S` adds
roughly another 0.18 s. Both preserve the returned value to last-ulp.

### FaceDetectorYN — no behaviour-preserving win exists on this build

`FaceDetectorYN.detect` is QUOTED as the single largest cost (22.8%).
Configuration in `tower/world_builder/redaction.py:270-286`: the frame is
upscaled `UPSCALE = 2` with `INTER_CUBIC` and detected at 1280x720, with
`CONFIDENCE = 0.30`, `NMS_THRESHOLD = 0.30`, `TOP_K = 5000`.

**MEASURED** —
`<venv-python> scripts/research/native_eval/bench_yunet.py`
Real captured frames are not stored in this repo
(`data/world_builder/worlds/*` contains `world.json` only, no imagery), and
synthetic content scores below 0.30 everywhere — which would make
"detections identical" *vacuously* true. So the equality test runs at
confidence 0.01, where the detector emits **2560 candidate boxes**: a
fingerprint of the network's raw arithmetic and a strictly harder test than
comparing the handful surviving 0.30. Timings are the shipped configuration.

Cost split: `INTER_CUBIC` 2x upscale **1.24 ms**, `detect` at 1280x720
**20.59 ms**. The resize is 6% of the cost; the network is 94%.

| configuration | speedup | detections | behaviour |
|---|---:|---:|---|
| SHIPPED (INTER_CUBIC 2x, CPU) | 1.00x | 2560 | reference |
| no upscale (detect @640x360) | 2.05x | 2348 | **WEAKENS redaction** — out of scope |
| `INTER_LINEAR` upscale | 1.02x | 1792 | **CHANGES detections** |
| `DNN_TARGET_OPENCL` | 0.85x | 2560 | identical — **no-op** |
| `DNN_TARGET_OPENCL_FP16` | 0.90x | 2560 | identical — **no-op** |
| `DNN_BACKEND_CUDA` | 0.91x | 2560 | identical — **no-op** |
| `TOP_K` 5000 -> 50 | 2.29x | 5 | **CHANGES detections** |
| `cv2.setNumThreads(1)` | 0.45x | 2560 | identical, much slower |
| `cv2.setNumThreads(4)` | 0.66x | 2560 | identical, much slower |

**The backend/target lever does not exist in OpenCV 5.0.0.** The
OpenCL, OpenCL_FP16 and CUDA targets all return **bit-identical** 2560-box
output — which is the proof they are being ignored, not the proof they are
safe. The runtime says so directly:

```
[ WARN] global net_impl_backend.cpp:297 Net::Impl::setPreferableBackend
        Back-ends are not supported by the new graph engine for now
[ WARN] global net_impl_backend.cpp:345 Net::Impl::setPreferableTarget
        Targets are not supported by the new graph engine for now
```

Independently, **MEASURED** `cv2.cuda.getCudaEnabledDeviceCount() == 0` and
the build info shows no CUDA/cuDNN — the `opencv-python-headless` wheel has
no CUDA DNN backend regardless.

Thread count is **already optimal**: the default (`-1`, 20 threads) beats
every explicit setting tried.

`INTER_LINEAR` changes the pixels the network sees, so it changes the
detections — the 1.02x is not worth even asking the question. `TOP_K` at 50
caps candidates before NMS; it is very likely safe at the shipped 0.30
threshold, but that **cannot be demonstrated without real face imagery**, and
it is 2.29x only in the low-confidence regime that made it measurable. Not
recommended on this evidence.

**Conclusion: none. Every configuration that is meaningfully faster changes
what gets redacted.** The 22.8% stays. The only honest lever would be
running redaction on fewer frames or in parallel with decode — a pipeline
question, not a configuration one, and outside this brief.

---

## Q3 — the build story on this host

### Is there a C++ compiler? No — verified four ways

**MEASURED** —
`<venv-python> scripts/research/native_eval/probe_toolchain.py`

Compilers on `PATH`:

```
cl         NOT FOUND        gcc        NOT FOUND
cl.exe     NOT FOUND        g++        NOT FOUND
clang      NOT FOUND        cc         NOT FOUND
clang-cl   NOT FOUND        cmake      NOT FOUND
                            ninja      NOT FOUND
nvcc       C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin\nvcc.EXE
link       C:\Program Files\Git\usr\bin\link.EXE   <-- Git coreutils, NOT the MSVC linker
```

That `link.exe` is a trap worth naming: it is GNU coreutils `link` shipped
with Git for Windows. Anything that finds it and assumes MSVC will fail
confusingly.

Installed toolchains — **MEASURED**, all ABSENT:
`vswhere.exe`; `C:\Program Files\Microsoft Visual Studio`;
`C:\Program Files (x86)\Microsoft Visual Studio`;
`C:\Program Files (x86)\Microsoft Visual C++ Build Tools`;
any `VC\Tools\MSVC` directory; `C:\Program Files (x86)\Windows Kits\10\Include`
(**no Windows SDK at all**); `C:\msys64`, `C:\MinGW`, `C:\mingw64`,
`C:\tools\mingw64`, `C:\Program Files\LLVM`, `C:\ProgramData\chocolatey\bin`.

setuptools' own MSVC discovery — **MEASURED**:

```
_get_vc_env('x64') FAILED: DistutilsPlatformError
  Microsoft Visual C++ 14.0 or greater is required.
```

And the empirical test, a trivial `PyInit_trivial` module handed to
`distutils.ccompiler`:

```
=== PROBE 4: actually compile trivial.c ===
  compiler class: Compiler
  COMPILE/LINK FAILED: DistutilsPlatformError
  Microsoft Visual C++ 14.0 or greater is required.
  VERDICT: a C extension CANNOT be built on this host as configured.
```

Python's build inputs are present (`Python.h` and `libs\python312.lib` both
exist) — the headers are there, the compiler is not.

**The earlier evidence in this repo is confirmed independently.**

### nvcc

**MEASURED** — nvcc 11.8 (`Cuda compilation tools, release 11.8, V11.8.89`)
against the actual GPU:

```
$ nvcc -arch=sm_120 -c t.cu
nvcc fatal : Value 'sm_120' is not defined for option 'gpu-architecture'
```

**MEASURED** — `torch.cuda.get_device_capability(0) == (12, 0)`, i.e.
sm_120. So the system CUDA toolkit **cannot target this machine's GPU**.
Torch works only because the `+cu132` wheel bundles its own CUDA 13.2
runtime — a fact the project's own `pyproject.toml` documents ("No CUDA
Toolkit install — the Windows wheel bundles its own runtime"). Any CUDA C++
of ours would need a toolkit upgrade first, on top of the missing host
compiler, since nvcc also requires `cl.exe` on Windows.

### pybind11 vs nanobind vs Cython on this host

All three are blocked by the same wall, and it is the *first* wall, before
any of their own differences matter.

| | needs | extra on top of MSVC | if MSVC existed |
|---|---|---|---|
| **Cython** | MSVC | none — generates C, `setup.py build_ext` | lowest ceremony; a `.pyx` + build step |
| **pybind11** | MSVC, C++11+ | header-only, works with plain setuptools | easiest C++ path; no cmake needed |
| **nanobind** | MSVC, **C++17**, **CMake** | cmake + scikit-build-core | smallest binaries, heaviest build |

CMake and ninja are **MEASURED** as absent, so nanobind carries two missing
prerequisites rather than one.

Is MinGW/clang viable for a CPython extension here? **No, and the details
matter.** setuptools does still know a `mingw32` compiler class, but
**MEASURED**: `new_compiler(compiler='mingw32')` raises `FileNotFoundError
[WinError 2]` because gcc is absent. Beyond installing MSYS2 (1–2 GB), the
import library problem is real: **MEASURED**, `libs\python312.lib` exists
(MSVC COFF format) but **`libs\libpython312.a` does not**, so a MinGW build
would first have to synthesize an import library with `gendef`/`dlltool`.
Mixing a MinGW-built extension into an MSVC-built CPython 3.12 with
MSVC-built numpy and OpenCV is an unsupported configuration with known CRT
and exception-model mismatches. It is not a maintenance story, it is a
recurring incident.

### Is there CI that could build it? No

**MEASURED** — there is **no `.github/` directory anywhere in the
repository**. A search of the repo root for CI configuration at depth 3
returns exactly one file: `tower/pyproject.toml`. No GitHub Actions, no
Azure Pipelines, no `.gitlab-ci.yml`, no `appveyor.yml`, no `tox.ini`, no
`cibuildwheel` config.

So there is no machine anywhere in this project that builds anything. A
native extension would have to be built by hand, by the one person with the
host, on a host that cannot build it. Standing up wheel-building CI is
therefore not an optimisation of the plan — it is a **prerequisite**, and it
is a larger project than the 0.46 s it would be protecting.

### Build configuration today

`tower/pyproject.toml` declares `build-system.requires = ["setuptools>=68"]`
with `build-backend = "setuptools.build_meta"` and no `ext_modules`. It is a
**pure-Python distribution**. Adding a C extension converts every install of
this project into a build that requires a compiler — including on this
host, where installs would then fail outright.

### Failure mode when the extension is missing

A clean fallback is *technically* easy — the standard shape is:

```python
try:
    from ._residuals_native import residuals as _residuals_impl
except ImportError:
    _residuals_impl = _residuals_python
```

and the repo already uses optional-import discipline elsewhere (e.g.
`_pid_is_running` in `store.py` guards its `psutil` import). But "cleanly
kept" is the wrong bar. The fallback would be the path that **always** runs
on this machine, because the extension can never be built here. That makes
the C++ path dead code on the only host that exists, while doubling the
surface that must stay numerically identical — and a Sim3 residual that
differs in the last ulp between two implementations changes which Levenberg
step is accepted, so the two paths can converge to different poses. The
fallback is not a safety net; it is a second implementation of the thing
whose correctness is hardest to check.

### Verdict, blunt

**A native extension is not maintainable on this machine as configured, and
the gap it would close does not justify making it maintainable.**

It cannot be compiled here — not by MSVC (absent), not by MinGW (absent and
unsupported for this CPython), not by nvcc (present but cannot target this
GPU, and needs `cl.exe` anyway). There is no CI to build it elsewhere and no
`.github/` to put any in. The project is a pure-Python distribution today,
and adding `ext_modules` would break installation on the very host it runs
on. The fallback path would be the only path ever executed here, so the C++
would be unexercised code carrying a numerical-divergence risk in the Sim3
optimiser.

And the prize is small. Pure numpy — no compiler, no dependency, no CI, no
fallback branch — already captures **80.3%** of what C++ could save on the
one hotspot that justified asking. The remaining **0.46 s on a 6.4 s run**
would cost a toolchain installation, a CI system, a dual-implementation
numerical-equivalence obligation, and a permanent build-from-source
requirement.

**Recommendation: implement the batched numpy Jacobian (f), the
byte-identical JSON write, and `cv2.meanStdDev` for sharpness. Do not build
a C++ extension.**

---

## Artifacts

All under `C:\Users\tvllo\Projects\Glasses-world-builder\tower\`:

- `scripts/research/native_eval/bench_residuals.py` — Q1 variants (a)–(e),
  correctness-gated, five shapes.
- `scripts/research/native_eval/bench_batched_jacobian.py` — variant (f),
  numba JIT warm-up, and the fraction-of-achievable-saving computation.
- `scripts/research/native_eval/bench_yunet.py` — Q2 FaceDetectorYN
  configuration sweep with a non-vacuous detection-equality test.
- `scripts/research/native_eval/probe_toolchain.py` — Q3 toolchain probe;
  attempts a real C extension build.

Other files in `scripts/research/native_eval/` belong to concurrent lanes of
this evaluation and were neither written nor run by this one. Nothing under
`tower/tower/` and nothing in `ios/` was modified by this lane.

Scratch packages (not in the shared venv):
`C:\Users\tvllo\AppData\Local\Temp\native_eval_pkgs`.
Build scratch: `C:\Users\tvllo\AppData\Local\Temp\native_eval_build`.
