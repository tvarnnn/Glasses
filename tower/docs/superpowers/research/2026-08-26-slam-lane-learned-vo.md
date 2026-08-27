# Learned visual odometry (DPVO / DROID-SLAM) against World Builder

Lane 2 of the modern-SLAM comparison. 2026-08-26.
Harness: `tower/scripts/research/slam_learned_vo/`.
Third-party clones live outside the repo, in the session scratchpad.
No production code was modified. `ios/` was not touched.

**Every number below is labelled `[M]` MEASURED here, `[Q]` QUOTED with a
citation, or `[E]` ESTIMATED with the method shown. There is no external
ground truth for any Ray-Ban capture; every corpus measurement is a
COMPARATIVE / SELF-CONSISTENCY measurement — "would the production
degeneracy criterion have accepted this pair", never "is this pose right".**

---

## 1. Verdicts

**DPVO was built and run end-to-end on real Ray-Ban footage.** The Windows
build is impossible on this host; a no-sudo WSL2 toolchain made it work. All
numbers below marked `[M]` on DPVO are from that running system, not from
papers.

| Question | Verdict | Decisive evidence |
|---|---|---|
| Would learned VO materially improve trajectory *continuity*? | **Yes, spectacularly — and continuity is not the same as correctness.** | DPVO: 1848 frames → **1 map, 1848 poses, 0 resets**. World Builder: same capture → **51 segments, 94 solved poses** `[M]` |
| Is that improvement trustworthy on our footage? | **No.** | Two runs of DPVO on the *same* frames disagree by **12–38% of trajectory extent** and by up to **8.5× in path length**, across four captures `[M]` |
| Is it justified given cost and our measured bottleneck? | **Not as a frontend replacement.** Worth keeping as an offline diagnostic. | Cost is trivially affordable; the problem is that neither DPVO nor a learned matcher addresses the 54.7% baseline limit `[M]` |
| Does DPVO/DROID solve CORRESPONDENCE or OPTIMIZATION? | **Both, but optimization is the larger half — and neither addresses baseline.** | Our replication of the 10.4/54.7 split is exact; learned matchers move correspondence 10.4%→5.2% but cannot manufacture parallax `[M]` |
| Is the differentiable BA the thing worth having? | **Its *precondition* is, and it is available classically.** | Matching each frame to 3 neighbours instead of 1 lifts ≥5-view tracks 18.3%→36.5% with plain ORB `[M]` |
| Can an RTX 5070 12 GB run DPVO at 360×640? | **Yes — 1.41× real time, and memory is bounded.** | Whole system: **16.93 fps, 682 MiB peak VRAM, flat at ~290 MiB across 1848 frames** `[M]` |
| DROID-SLAM on 12 GB? | **Yes at our resolution, but it is the wrong tool** — the heavy end of a family whose light end already suffices. | ≈3.3 GB `[E]` at 640×352, vs a quoted ≥11 GB requirement at their resolutions `[Q]` |
| Behaviour on PURE ROTATION (our dominant failure)? | **Silent, confident, wrong.** DPVO has no refusal code path at all. | Under exact synthetic pure rotation LoFTR calls 35.0% of pairs solvable, ORB 14.4% `[M]`; DPVO returned `refusals: 0` on every run `[M]` |
| Fallback / async backend behind `backend.py`? | **Async yes, fallback no.** The seam fits; the *contract* does not. | `PoseEstimate.translation` is unit-length-when-solved — a two-view assumption in a window-shaped API |
| Licensing | **Clean.** DPVO MIT, DROID BSD-3, LoFTR/DISK/LightGlue Apache-2.0. Avoid SuperPoint. `[Q]` | Weights carry no separate licence text; both are trained on TartanAir (CC BY 4.0) `[Q]` |
| Can we benchmark without touching production? | **Yes, and we did.** | Seven harnesses, read-only against persisted captures and one persisted session |

**One-line answer to the lane question.** DPVO does exactly what it says: it
produces one unbroken trajectory where World Builder produces fifty-one
fragments, at 1.41× real time in 682 MiB. But run it twice on the same frames
and the two trajectories differ by a fifth of their own size, because the
information it needs — camera translation — is not in this footage. A learned
matcher has the same problem in miniature: it doubles the rate at which pure
rotation is mistaken for parallax. **The continuity is real; the geometry is
not. Buying learned VO now would replace visible fragmentation with invisible
error, and the fragmentation is the more honest failure.**

---

## 2. Can it be built here? A precise answer

### 2.1 Windows: blocked twice, independently

| Check | Result |
|---|---|
| `nvcc` present | Yes — CUDA **11.8** at `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8` `[M]` |
| `nvcc --list-gpu-arch` | tops out at `compute_90`; **`sm_120` is not in the list** `[M]` |
| torch | `2.13.0+cu132`, arch list `['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120']` `[M]` |
| MSVC host compiler | **Absent.** No `cl.exe`, no `Microsoft Visual Studio` directory, no `vswhere.exe` `[M]` |

Both `pip install torch-scatter` and `pip install .` (DPVO) fail at the same
line, before nvcc is ever invoked `[M]`:

```
File "...torch/utils/cpp_extension.py", line 646, in _check_cuda_version
  raise RuntimeError(CUDA_MISMATCH_MESSAGE, cuda_str_version, torch.version.cuda)
RuntimeError: ('The detected CUDA version (%s) mismatches the version that was
used to compilePyTorch (%s). ...', '11.8', '13.2')
```

That guard is not the real problem — it is a symptom. Even suppressed, nvcc
11.8 cannot emit `sm_120`, and there is no host C++ compiler on the machine.
**Windows is a dead end for DPVO/DROID without installing MSVC Build Tools and
CUDA Toolkit 13.2, both of which need administrator rights.**

### 2.2 WSL2: viable, and no sudo was needed

WSL2 `ITSC-3146` (Ubuntu 24.04.2) is present, was stopped, and has working GPU
passthrough — `nvidia-smi` inside WSL reports the RTX 5070 `[M]`. gcc 13.3,
g++, make and git are installed; `python3-venv`, `python3-pip` and
`python3-dev` are **not**, and `sudo` **requires a password**, which an
unattended agent does not have `[M]`.

Every one of those was worked around without administrator rights:

| Missing | Workaround `[M]` |
|---|---|
| `pip` | `python3 -m venv --without-pip` + `get-pip.py` |
| CUDA Toolkit 13.2 | **PyPI ships it**: `nvidia-cuda-nvcc==13.2.86` unpacks a complete tree at `site-packages/nvidia/cu13` with `bin/nvcc`, `include/`, `lib/`, `nvvm/`, `cccl/`. `nvcc --list-gpu-code` includes `sm_120`, `sm_121` |
| `Python.h` | `apt-get download` (no sudo) + `dpkg -x` of `libpython3.12-dev` / `python3.12-dev` into `~/pydev/root`, then `CPATH` |

This is the single most reusable finding of the build attempt: **a matching
CUDA toolchain for sm_120 is pip-installable and needs no admin.** The same
trick would work on Windows if MSVC were present.

Scripts: `wsl_build_dpvo.sh`, `wsl_build_dpvo2.sh`, `wsl_build_dpvo3.sh`.

Two further blockers surfaced only once the compiler actually ran, and both are
worth recording because neither is documented anywhere:

**PTX ISA version skew inside the pip CUDA tree.** pip's dependency resolution
mixed CUDA components: `nvidia-nvvm` and `nvidia-cuda-crt` resolved to
**13.3.73** while `nvidia-cuda-nvcc` (which owns `ptxas`) was pinned to
**13.2.86**. The 13.3 front end emits PTX ISA 9.3; the 13.2 `ptxas` accepts at
most 9.2 `[M]`:

```
ptxas /tmp/tmpxft_..._scatter_cuda.ptx, line 9;
  fatal : Unsupported .version 9.3; current version is '9.2'
```

Fix: pin `nvidia-nvvm`, `nvidia-cuda-crt` and `nvidia-cuda-cccl` to `13.2.*`
alongside `nvidia-cuda-nvcc`. **Anyone using the pip-CUDA trick must pin all
four together.**

**ATen API drift in DPVO's kernels.** With a matched toolchain, nvcc reaches
DPVO's own source and fails on `AT_DISPATCH_FLOATING_TYPES_AND_HALF(x.type(),
...)` `[M]`:

```
correlation_kernel.cu(211): error: no suitable conversion function from
  "const at::DeprecatedTypeProperties" to "c10::ScalarType" exists
```

`Tensor::type()` has been deprecated for years and no longer converts. The fix
is mechanical — `x.type()` → `x.scalar_type()` in the dispatch macros, 4 sites
in `dpvo/altcorr/correlation_kernel.cu` and ~30 more across
`dpvo/lietorch/src/lietorch_gpu.cu` and `lietorch_cpu.cpp` `[M]`.

**Link stage.** The pip CUDA wheels ship only versioned sonames
(`libcudart.so.13`), and `ld` needs the unversioned `libcudart.so`. Fixed by
symlinking every `*.so.N` to `*.so` in `nvidia/cu13/lib` `[M]`.

**Outcome: the build SUCCEEDED.** `[M]`

```
Successfully built dpvo
Successfully installed dpvo-0.0.0
cuda_corr OK
cuda_ba OK
lietorch_backends OK
```

All three of DPVO's CUDA extensions — the patch correlation kernel, the
differentiable bundle adjustment, and lietorch's SE(3)/Sim(3) backends —
compile for `sm_120` against torch 2.13.0+cu132 and import cleanly, on this
machine, with **no administrator rights anywhere in the process**.

Two further runtime gaps appeared on first execution and were closed `[M]`:
`dpvo.loop_closure` is not picked up by `find_packages()` (no `__init__.py`);
and `pypose`, `scipy` and `matplotlib` are imported unconditionally by
`net.py` / `patchgraph.py` despite loop closure being nominally optional.

**Cost of the whole port, honestly:** about two hours of unattended agent time
from a cold WSL2 with no sudo, a ~4 GB download, six distinct blockers
(ensurepip, CUDA toolkit, `Python.h`, PTX version skew, ATen `.type()` drift,
unversioned sonames), and a ~40-line pure-torch shim to replace `torch-scatter`,
which still does not build. It is reproducible from the scripts in the harness.
That is far cheaper than "you need a Linux box" implies — but it is nothing
like "pip install and go", and every blocker recurs on any machine without a
matching CUDA 13.2 toolchain.



### 2.3 What the DPVO source will need regardless of toolchain

Read from the clone `[M]`:

- `dpvo/net.py:22` and `dpvo/dpvo.py:16` both do
  `autocast = torch.cuda.amp.autocast`. Deprecated in favour of
  `torch.amp.autocast('cuda', ...)`, but **verified still present and usable as
  a context manager on torch 2.13.0** `[M]` — not a blocker.
- `torch-scatter` is a blocker of a different kind: DPVO's `ba.py`, `blocks.py`
  and `net.py` import it, and it is a *separate* CUDA extension with its own
  version bounds. It needs only `scatter_sum`, `scatter_softmax` and (in the
  optional loop closure) `scatter_max`. All three are exactly expressible in
  stock torch; `torch_scatter_shim.py` in the harness implements them and
  self-tests to **0.0 max absolute error against a hand-written reference for
  `scatter_sum` and `scatter_max`, with `scatter_softmax` group sums exactly
  1.0** `[M]`. This removes one compiled dependency from any future port.
- `environment.yml` pins `pytorch=2.3.1`, `pytorch-cuda=12.1`,
  `numpy==1.26.4`. Our host is torch 2.13 / CUDA 13.2 / numpy 2.5.2 — a
  three-release jump on every axis.
- `dpvo/stream.py` uses `cv2.undistort` and `cv2.imread` only; **OpenCV 5 is
  not a problem for DPVO** (unlike some older SLAM stacks). It crops to a
  multiple of 16: our 360×640 portrait frames become **640×352** `[M]`.
- Pangolin/DPViewer, DBoW2 and DPRetrieval are all optional and were skipped.

---

## 3. What learned tracking actually buys — mechanistically

Not "better features". Three concrete mechanisms, each with a cost:

**(a) The similarity is learned, not hand-designed, and it is dense.**
ORB compares 256-bit binary descriptors at detected corners with a Hamming
ratio test. That pipeline has three lossy stages: detection (a corner must be
found in *both* images), description (a 256-bit summary), and matching (a
nearest-neighbour ratio test with no spatial reasoning). DPVO replaces all
three with a correlation lookup: a 3×3 patch of 128-d CNN features is
correlated against a 7×7 neighbourhood of the target feature map at two
pyramid levels (`dpvo/net.py`, `CorrBlock` with `levels=[1,4]`, `radius=3`),
and a GRU regresses a *sub-pixel flow update plus a confidence weight*
(`Update.d` and `Update.w`) rather than choosing a discrete match `[M], source`.
So there is no detection stage to fail, no discrete assignment to be wrong,
and the confidence is a learned scalar that the optimizer consumes directly.

**(b) It is a tracker, not a matcher.** ORB re-detects independently per image;
DPVO carries a fixed set of patches forward and re-localises each in every new
frame. Patch identity is *given*, not inferred. That is why DPVO gets long
tracks for free where a matcher has to be chained.

**(c) The confidence is calibrated against the optimizer, not against a
threshold.** The weight head feeds the damped Gauss–Newton solve, so a match
that is unreliable is down-weighted continuously rather than discarded by a
ratio test.

**What it does not buy.** Every one of those mechanisms improves *where a
correspondence goes*. None of them changes *where the camera was*. Our
measured recovery of ORB's correspondence failures is real but small
(§4), and our null test shows the extra correspondences make the
translation estimate **less** trustworthy under rotation, not more (§5).

---

## 4. Correspondence or optimization? The crux, with numbers

### 4.1 The prior split reproduces exactly

`matcher_showdown.py` re-runs `multi_cue_geometry/blocker_measured.py`'s exact
verdict pipeline — `cv2.findEssentialMat` at the production RANSAC constants,
`MIN_INLIERS=15`, `MIN_INLIER_RATIO=0.05`, `recoverPose`,
`median_triangulation_angle_deg` against `MIN_TRIANGULATION_ANGLE_DEG=0.5` —
changing only the matcher. 406 consecutive keyframe pairs from the persisted
session `dd5d13a2381e430db9b27c7da2cf2928`; 212 of them lie inside the 23
geometry-less segments that contain at least two keyframes (the brief's 32
zero-geometry segments include nine too short to form a pair) `[M]`.

ORB reproduces the prior lane's headline **to the decimal**: correspondence
10.4%, baseline 54.7%. The harness is therefore measuring the same thing.

**Geometry-less segments, 212 pairs `[M]`:**

| matcher | median matches | solvable | baseline-limited | correspondence-limited | median tri angle |
|---|---|---|---|---|---|
| ORB + Lowe (production) | 205 | 74 (34.9%) | **116 (54.7%)** | **22 (10.4%)** | 0.282° |
| LoFTR (indoor) | 1466 | 139 (65.6%) | 62 (29.2%) | 11 (5.2%) | 1.181° |
| DISK + LightGlue | 672 | 109 (51.4%) | 97 (45.8%) | 6 (2.8%) | 0.613° |

**Cross-tab, ORB → LoFTR, same 212 pairs `[M]`:**

|  | LoFTR: corr | LoFTR: baseline | LoFTR: solvable |
|---|---|---|---|
| **ORB: correspondence** (22) | 10 | 3 | **9** |
| **ORB: baseline** (116) | 0 | 41 | **75** |
| **ORB: solvable** (74) | 1 | 18 | 55 |

Recovery of ORB's *correspondence* failures: LoFTR 9/22 (40.9%), DISK+LightGlue
13/22 (59.1%) `[M]`.

### 4.2 The number that looks like a win, and why it is not

The eye-catching cell is 75/116 — LoFTR turns 64.7% of ORB's *baseline*-limited
pairs into "solvable" `[M]`. Per-pair, the LoFTR/ORB triangulation-angle ratio
has median 1.71 and exceeds 1 on 65.3% of pairs `[M]`. If that were real
parallax that ORB's ~1 px keypoint noise had been hiding, learned matching
would be transformative here.

It is partly real and substantially contaminated. §5 measures the
contamination directly.

### 4.3 Arithmetic on the decision

Correspondence is 10.4% of failing pairs. A perfect matcher — one that never
misses a correspondence — recovers **at most 22 of 212 pairs**, and the two we
tested recovered 9 and 13 of those 22 `[M]`. Even the optimistic reading of the
full LoFTR column (65.6% solvable vs 34.9%) is a claim about a *gate*, not
about *poses*, and §5 shows the gate is the least trustworthy part of the
measurement. **A system that only improves matching cannot move our number
much, and this is now measured on our own frames rather than argued.**

Does differentiable bundle adjustment change that calculus? See §6: it changes
it only if the observation graph has cycles, and the graph is the part we can
build without any network at all.

---

## 5. Pure rotation: the null experiment (the decisive measurement)

Real footage cannot distinguish "LoFTR found parallax ORB missed" from "LoFTR
gave RANSAC enough correspondences to hallucinate a translation", because we
have no ground-truth motion. So `rotation_null.py` constructs a case where the
answer is known by construction:

> take a real Ray-Ban frame, undistort it with the genuine ChArUco calibration
> (`pinhole_radtan`, rms 0.289 px), warp it by `H = K R K⁻¹` for a known
> rotation `R` split across yaw/pitch/roll, and re-JPEG the result at q85.
> That is a **pure rotation about the camera centre**: the true translation is
> exactly zero and the true triangulation angle is exactly zero, while every
> pixel of texture, sensor noise and compression artefact is real.

Any "solvable" verdict is a false positive. 40 of the sharpest frames from the
canonical capture × 4 rotation magnitudes = 160 pairs `[M]`.

| matcher | rot 0.5° | rot 1.2° | rot 2.5° | rot 5.0° | **overall** |
|---|---|---|---|---|---|
| ORB + Lowe | 15.0% | 15.0% | 17.5% | 10.0% | **14.4%** (23/160) |
| **LoFTR** | **55.0%** | **40.0%** | 42.5% | 2.5% | **35.0%** (56/160) |
| DISK + LightGlue | 25.0% | 10.0% | 20.0% | 15.0% | **17.5%** (28/160) |

All figures `[M]`. 1.2° is the corpus's own median true inter-frame rotation
(quoted from the multi-cue lane).

Three things follow, and they are the core of this report.

**(a) The stronger matcher is fooled 2.4× more often.** Not less. More
correspondences on a rank-deficient problem give RANSAC more freedom to fit a
translation that is not there.

**(b) The matchers are not wrong — the *decomposition* is unidentifiable.**
Median absolute rotation error is 0.036–0.214° across every matcher and every
angle `[M]`. The rotation is recovered essentially perfectly. Only the
translation is invented. This is exactly the textbook degeneracy, and it says
the fix is not a better matcher.

That rotation figure doubles as the harness's own correctness check: if the
warp, the calibration or the `recoverPose` convention were wrong, the recovered
rotation would not land within a fifth of a degree of the rotation that was
imposed, at every magnitude, under three independent matchers `[M]`.

**(c) The estimates are not merely marginal, they are wild.** Under LoFTR the
p90 estimated triangulation angle on a *zero-baseline* pair is 36.6° at 0.5°
rotation, 38.5° at 1.2°, 24.6° at 2.5° `[M]`. Under DISK+LightGlue, 59.9° at
2.5°. These would sail past any reasonableness check. This corroborates the
cross-segment lane's finding that *a wrong Sim(3) reprojects beautifully*: on
this footage, geometric self-consistency is not evidence.

### 5.1 Re-reading the 64.7% "recovery" through the null

At the corpus's median rotation of 1.2°, LoFTR's false-positive rate on
*exactly* zero-baseline pairs is 40.0% `[M]`. It called 64.7% of ORB's
baseline-limited pairs solvable. If all 116 of those pairs were truly
zero-baseline, we would expect ≈46 false positives; we observed 75. So:

- roughly **40 percentage points** of the 64.7% is consistent with what pure
  rotation alone produces `[E: null rate at the corpus's own median rotation,
  applied to the 116-pair set]`;
- roughly **25 percentage points** (≈29 pairs) exceeds the null and is the
  honest upper bound on genuinely recovered parallax `[E: same method]`.

29 of 212 pairs — about 14% — is the credible ceiling on what a
state-of-the-art matcher adds here, and it comes bundled with a 40% chance of
a confident wrong translation on any rotation-dominant pair. **That trade is
bad for a system whose stated design invariant is that refusing is a
first-class answer.**

Caveats, stated plainly: the null uses a synthetic homography, so it contains
no independent scene motion, no rolling-shutter effect and no exposure change;
it uses the *sharpest* frames, which favours all matchers; and warping
resamples one image, which may advantage detector-free matching. It is a lower
bound on realism, not a simulation. It is nonetheless the only measurement in
this lane with a known right answer.

---

## 6. Pose and depth representation, and what the memory really costs

### 6.1 DROID-SLAM — dense inverse depth over a frame graph

`droid_slam/depth_video.py` preallocates, per keyframe slot: the RGB image,
a per-pixel inverse-depth field `disps` at 1/8 resolution, an *upsampled*
`disps_up` at full resolution, plus `fmaps`, `nets` and `inps` at 1/8
resolution in half precision `[M, source]`. Optimization is a dense bundle
adjustment over a frame graph whose edges each carry a full 4-level
all-pairs correlation volume (`modules/corr.py`, `CorrBlock`).

At our post-crop 640×352 `[E: tensor shapes × dtype sizes, read from source]`:

| tensor | bytes / keyframe |
|---|---|
| `images` (uint8) | 675,840 |
| `disps` + `disps_sens` (1/8, fp32) | 28,160 |
| `disps_up` (full res, fp32) | 901,120 |
| `fmaps` + `nets` + `inps` (1/8, fp16) | 1,802,240 |
| **total** | **≈3.25 MiB** |

Default `--buffer 512` → **≈1.66 GiB**; `buffer=1024` → ≈3.33 GiB `[E]`.
Each frontend edge's correlation pyramid is ≈33 MB at this resolution, and
`DroidFrontend` sets `max_factors=48` → ≈1.6 GB `[E]`. Total ≈3.3 GB, which
**fits in 12 GB at our resolution**, against the repo's quoted ≥11 GB for its
own demo resolutions `[Q]`. Note the backend deliberately switches to
`corr_impl="alt"` and `update_lowmem` for exactly this reason `[M, source]`.

The memory grows with **pixels × keyframes × graph edges**. That is why long
sequences hurt, and why published practice partitions sequences over five
minutes into non-overlapping segments `[Q]`.

### 6.2 DPVO — sparse patches over a patch graph

DPVO's representation is 96 patches per frame, each a 3×3 grid carrying
`(x, y, inverse-depth)`, with a per-patch 128-d 3×3 feature grid and a 384-d
context vector `[M, source]`. Crucially, the *feature* memory is a **ring
buffer of 36 frames** (`dpvo.py:58`, `self.pmem = self.mem = 36`) — only the
patch graph state scales with sequence length, and even that is a fixed
`BUFFER_SIZE=4096` preallocation `[M, source]`.

At 640×352, half precision `[E: tensor shapes × dtype sizes, read from source]`:

| tensor | bytes |
|---|---|
| `fmap1_` (36 × 128 × 160 × 88, fp16) | ≈130 MB |
| `fmap2_` (36 × 128 × 40 × 22, fp16) | ≈8 MB |
| `gmap_` (36 × 96 × 128 × 3 × 3, fp16) | ≈8 MB |
| `imap_` (36 × 96 × 384, fp16) | ≈2.7 MB |
| `PatchGraph` at 4096 frames (poses, patches, points, colors, index) | ≈52 MB |
| **total preallocated** | **≈200 MB** |

**Our 1848-frame canonical capture fits inside the default 4096-frame buffer
with no resizing, no partitioning and no tuning.** Sequence length is a
non-issue for DPVO in a way it is not for DROID. Published figures: DPVO 60 FPS
/ 4.9 GB and DPVO-fast 120 FPS / 2.5 GB on an RTX-3090, against DROID-VO's
40 FPS / 8.7 GB `[Q]`; the gap between the ≈200 MB of preallocation and the
quoted 4.9 GB is transient activation and correlation memory during the
update iterations.

### 6.3 What DPVO's representation would give us that we throw away

`PointBlock.support_views` is declared in `backend.py:107` and never populated;
the cross-segment lane established that the association exists at solve time
and dies with the stack frame. DPVO's patch graph *is* that table: `index_`
maps patch → source frame and `(ii, jj, kk)` name (source frame, target frame,
patch) for every edge `[M, source]`. A DPVO backend would populate
`support_views` as a side effect of running. That is a genuine architectural
compliment to the seam's design — and it is also achievable by simply writing
down the `observed` dict the classical backend already computes.

---

## 7. Robustness: texture, blur, wide baselines — measured on our frames

**Blur.** Splitting all 406 pairs by the variance-of-Laplacian sharpness of the
*blurrier* frame `[M]`:

| quartile (sharpness) | ORB matches | ORB solvable | LoFTR matches | LoFTR solvable |
|---|---|---|---|---|
| Q1 25.8–60.7 (blurriest) | 116 | 40.2% | 1250 | 68.6% |
| Q2 60.7–101.6 | 188 | 45.5% | 1392 | 73.3% |
| Q3 101.6–231.9 | 227 | 45.5% | 1468 | 66.3% |
| Q4 231.9–941.8 (sharpest) | 319 | 44.1% | 1395 | 63.7% |

(DISK+LightGlue for the same quartiles: 62.7% / 56.4% / 42.6% / 72.5% `[M]`.)
ORB's match count falls **2.75×** from sharpest to blurriest quartile
(319 → 116); LoFTR's is **flat** (1395 → 1250, −10%) `[M]`.
This is a real and clean win for learned matching: it is genuinely
blur-tolerant where ORB is not.

It does not translate into solvability. ORB's solvable rate barely moves across
sharpness quartiles (40.2% → 44.1%) — which independently confirms the
segment-fragmentation lane's finding that our blur gate is not gating the thing
that matters. **Correlation of sharpness with geometric success is weak for
both matchers.** More matches on a blurry frame of a rotating camera is still
a rotating camera.

**Wide baselines / large gaps.** Sweeping the frame gap on raw capture frames
(8 windows × 32 consecutive frames, ORB) `[M]`:

| gap (frames, ~12 fps) | pairs | solvable | baseline-limited | correspondence-limited | median matches | median inliers |
|---|---|---|---|---|---|---|
| 1 | 248 | 28.2% | 65.3% | 6.5% | 548 | 452 |
| 2 | 240 | 35.0% | 57.5% | 7.5% | 462 | 390 |
| 3 | 232 | 35.3% | 55.6% | 9.1% | 398 | 318 |
| 5 | 216 | 44.4% | 43.5% | 12.0% | 320 | 238 |
| 8 | 192 | 43.8% | 43.2% | 13.0% | 234 | 164 |
| 13 | 152 | 42.8% | 39.5% | 17.8% | 167 | 100 |
| 21 | 88 | 38.6% | 38.6% | 22.7% | 144 | 91 |

Two readings, both important.

1. **Widening the baseline is what fixes solvability, not improving the
   matcher.** Going from gap 1 to gap 5 moves solvable 28.2% → 44.4% and
   baseline-limited 65.3% → 43.5% `[M]`. That is a bigger, cheaper and more
   trustworthy improvement than anything a matcher did.
2. **ORB does not fall apart at wide gaps.** At gap 13 — DPVO's own
   `PATCH_LIFETIME` — plain ORB still delivers a median 167 matches and 100
   essential-matrix inliers, and correspondence-limited failures have only
   risen from 6.5% to 17.8% `[M]`.

A second, independently-sampled gap sweep (4 windows × 24 frames, different
window starts, so the absolute rates differ from the table above) runs ORB and
LoFTR side by side on the *same* frame pairs `[M]`:

| gap | ORB solvable / baseline / corr-fail | LoFTR solvable / baseline / corr-fail | ORB matches | LoFTR matches |
|---|---|---|---|---|
| 1 | 14.1% / 69.6% / **16.3%** | 51.1% / 47.8% / **1.1%** | 574 | 2122 |
| 3 | 14.3% / 64.3% / 21.4% | 39.3% / 56.0% / 4.8% | 452 | 1557 |
| 5 | 25.0% / 50.0% / 25.0% | 43.4% / 48.7% / 7.9% | 373 | 1256 |
| 8 | 17.2% / 57.8% / 25.0% | 48.4% / 46.9% / 4.7% | 314 | 1092 |
| 13 | 25.0% / 50.0% / **25.0%** | 59.1% / 38.6% / **2.3%** | 220 | 988 |
| 21 | 41.7% / 41.7% / 16.7% | 66.7% / 33.3% / **0.0%** | 151 | 749 |

This is the strongest genuine case *for* a learned matcher in this report, and
it should be stated fairly: **LoFTR essentially eliminates correspondence
failure at wide baselines** — 25.0% → 2.3% at gap 13, 16.7% → 0.0% at gap 21
`[M]`. If we ever want a covisibility graph with edges spanning 13–21 frames on
*hard* windows, ORB will drop a quarter of them and LoFTR will drop none.

But note what does **not** move: baseline-limited stays at 33–57% for LoFTR at
every single gap `[M]`. The matcher removes the correspondence bottleneck and
leaves the geometry bottleneck exactly where it was — which is the whole
argument of this report in one table.

**Rapid motion / low texture.** Not separable from blur on this corpus and not
claimed here.

---

## 8. The graph, not the network: where DPVO's advantage really comes from

The lead supplement establishes that bundle adjustment was already implemented
and measured at **0.00% drift improvement**, because `_extend` matches keyframe
*i* only to *i−1*, giving a chain with median covisibility span 1 and therefore
no cycle for BA to tighten (`classical.py:246-250`).

DPVO does not have that problem, and the reason is *configuration*, not
learning: `PATCH_LIFETIME: 13` and `OPTIMIZATION_WINDOW: 10` mean each patch
constrains up to 13 poses simultaneously `[M, config/default.yaml; the code
defaults in dpvo/config.py, which the §8b runs used, are 12 and 12]`.

So the load-bearing question is: **on our footage, is that graph available to
a classical matcher?** `covisibility_span.py` builds geometrically-verified
tracks with plain ORB index matching and union-find, varying only how many
previous frames each frame is matched against `[M]`:

| match width | tracks | median track len | mean len | ≥3 views | ≥5 views | median span | p90 span |
|---|---|---|---|---|---|---|---|
| **1** (the production chain) | 4956 | 2.50 | 3.49 | 49.1% | 18.3% | 1.50 | 5.38 |
| 3 | 2770 | 3.50 | 6.21 | 62.8% | 36.5% | 3.25 | 15.00 |
| 5 | 2158 | 3.75 | 7.02 | 63.1% | 38.7% | 4.12 | 16.88 |
| 32 (all pairs) | 1348 | 4.75 | 7.54 | 62.1% | 39.1% | 7.38 | 22.00 |

Width 1 reproduces the repo's own diagnosis on raw frames: median track length
2.50, median covisibility span **1.50** `[M]`. Widening to just **three**
neighbours doubles the ≥5-view fraction (18.3% → 36.5%) and lifts the p90
covisibility span from 5.4 to 15.0 frames `[M]`. Going all the way to all-pairs
adds almost nothing beyond width 5.

**This is the single most actionable measurement in the lane.** The dense,
cyclic observation graph that makes DPVO's differentiable BA non-vacuous — and
that would make our own already-written BA non-vacuous — is obtainable on this
exact footage with the ORB matcher we already ship, by changing one number in
`_extend` from 1 to 3. No network, no CUDA extension, no licence, no VRAM.

It does not follow that covisibility-plus-BA will fix the corpus; 54.7% of
pairs remain baseline-limited and BA cannot create parallax either. But it does
follow that **buying a learned frontend to obtain a graph we can already build
is paying for the wrong half of the system.**

---

## 8b. DPVO end-to-end on the canonical capture

The build succeeded, so this is not an estimate. The full DPVO system — patch
CNN, correlation kernel, differentiable BA, lietorch — was run over the
canonical capture `22e9d4289cb440fbb3f14e6da369a136` with the real ChArUco
calibration (undistorted through `cv2.undistort`, then DPVO's own `%16` crop to
640×352), the released `dpvo.pth`, and DPVO's own code defaults
(`PATCHES_PER_FRAME 80`, `OPTIMIZATION_WINDOW 12`, `PATCH_LIFETIME 12`,
`REMOVAL_WINDOW 20`, `KEYFRAME_THRESH 12.5`, `BUFFER_SIZE 4096` — note these
are `dpvo/config.py`'s values; the shipped `config/default.yaml` is slightly
different at 96/10/13/22/15.0) `[M]`.

| | stride 1 (every frame) | stride 2 (DPVO demo default) |
|---|---|---|
| frames consumed | **1848** | 924 |
| **poses returned** | **1848** | 924 |
| keyframes retained | 508 | 426 |
| patches in graph | 40,640 | 34,080 |
| **tracking resets / lost** | **0** | **0** |
| **maps / fragments** | **1** | **1** |
| **refusals** | **0** (there is no code path for one) | **0** |
| total processing time | 109.14 s | 55.37 s |
| throughput | **16.93 fps** (capture is 11.99 fps → **1.41× real time**) | 16.69 fps |
| per-frame median / p95 | 46.7 / 61.4 ms | 46.2 / 61.8 ms |
| peak VRAM allocated | **682 MiB** | 684 MiB |
| peak VRAM reserved | 2832 MiB | 3010 MiB |
| steady-state VRAM allocated | **273 → 298 MiB over 1848 frames** | 274 → 293 MiB |

All `[M]`, on the RTX 5070 12 GB via WSL2, with the GPU otherwise idle.

**Set against World Builder on the identical capture** (quoted from the
segment-fragmentation lane): 1848 frames → 457 keyframes, **51 segments**, 94
solved poses, 32 segments with zero geometry `[Q]`. DPVO: 1848 frames → 1
trajectory, 1848 poses, no breaks.

Two of those rows deserve emphasis because they settle open questions:

- **Memory is bounded, exactly as the ring-buffer reading of the source
  predicted.** Allocated VRAM moved from 273 MiB at frame 400 to 298 MiB at
  frame 1600 — a 9% rise over 1200 frames, entirely accounted for by the
  inactive-edge index arrays growing to 747,760 entries `[M]`. The §6.2
  estimate of ≈200 MB preallocated is confirmed to the right order. **The
  1848-frame sequence is a non-issue; DROID's five-minute partitioning problem
  does not exist here.**
- **A methodological warning worth recording**: my first runner omitted
  `torch.no_grad()`, which DPVO's own `demo.py` applies to the whole loop.
  Without it the autograd graph is retained through `PatchGraph.net` and VRAM
  grew ≈112 MiB per frame until the card was exhausted, while keyframes,
  patches and edges all stayed flat `[M]`. The apparent "DPVO exhausts 12 GB on
  our footage" finding was mine, not DPVO's. It is recorded here because it is
  exactly the kind of result that would have been reported as fact.

### 8b.1 The trajectory is continuous. It is also not determined by our footage.

`refusals: 0` is not a compliment. DPVO has no degeneracy test at all, so
"1 map, 1848 poses" tells us the system always answers; it does not tell us
the answer is right, and we have no ground truth to ask.

But DPVO hands us a self-consistency test for free. `Patchifier.forward`
selects patch centres with an **unseeded `torch.randint`** (`CENTROID_SEL_STRAT:
'RANDOM'`) `[M, source]`. So running it twice on the same frames, same weights
and same calibration varies nothing except the random draw. If the footage
determines the trajectory, the runs agree. `dpvo_reproducibility.py` aligns
each pair with an exact Umeyama Sim(3) — monocular trajectories are only
defined up to a similarity — and reports the residual as a fraction of the
trajectory's own extent.

Three independent runs, canonical capture, stride 2, 924 poses each `[M]`:

| pair | Sim(3) scale between the runs | aligned RMS | **RMS as % of bbox extent** | RMS as % of path length |
|---|---|---|---|---|
| run A vs run B | **2.2190** | 0.37507 | **23.7%** | 5.4% |
| run A vs run C | **0.8369** | 0.13206 | **19.6%** | 3.1% |
| run B vs run C | **0.3168** | 0.09948 | **14.8%** | 2.3% |

The reconstructed trajectory's own bounding-box extent differed by 2.35×
between runs (1.580 vs 0.673 internal units) `[M]`, and the internal scale
varies by a factor of **7 across three runs of the same 924 frames** `[M]`.

**This is the same lesson the cross-segment lane learned, arriving from the
other direction.** That lane found a Sim(3) that reprojected at 1.62 px median
and was wrong by 3.2× in scale, and concluded that *reciprocity, not
reprojection, is the safety check*. Here DPVO produces a single smooth
continuous trajectory — the thing World Builder most conspicuously lacks — and
reruns of it disagree by 15–24% of its own extent. A smooth trajectory is not
evidence either.

For contrast, DPVO's published EuRoC ATE is 0.105 m on trajectories of tens of
metres `[Q]`. I did not run a benchmark sequence here, so I cannot say what
DPVO's run-to-run spread is on well-conditioned footage; §8b.2 uses our own
corpus as the control instead.

### 8b.2 It is not a property of one capture

The same paired test on the next three largest captures, two runs each, stride
2, everything else identical `[M]`:

| capture | frames | keyframes per run | path length per run | Sim(3) scale between runs | **RMS as % of extent** |
|---|---|---|---|---|---|
| `22e9d428…` (canonical, 3 runs) | 924 | 426 / 424 / 443 | 4.25 / 3.97 / 6.93 | 2.22, 0.84, 0.32 | **14.8 – 23.7%** |
| `20ce3c23…` | 855 | 267 / 263 | **192.05 / 22.55** | 0.1498 | **12.0%** |
| `b35d8ab8…` | 847 | 467 / 468 | 12.60 / 38.03 | 3.7112 | **37.8%** |
| `2e6cffa2…` | 698 | 211 / 207 | 9.76 / 32.67 | 6.3030 | **26.0%** |

Every capture. 12–38% of extent, on four different sequences, from a system
whose *keyframe selection* is nearly deterministic (267 vs 263, 467 vs 468,
211 vs 207 keyframes) `[M]`. The front end is stable; **the reconstructed
translation is not.** On `20ce3c23…` two runs of the same 855 frames produced
trajectories whose path lengths differ by **8.5×**; on `2e6cffa2…`, 3.3×; on
`b35d8ab8…`, 3.0× `[M]`.

The trajectory *shape* statistic moves with it: `straightness = extent / path
length` was 0.2226 vs 0.2775 on `20ce3c23…`, 0.2280 vs 0.4669 on `b35d8ab8…`,
and 0.2882 vs 0.4876 on `2e6cffa2…` `[M]`. Two runs disagree not just on
scale but on whether the wearer walked a line or a loop.

Throughput and memory, by contrast, are rock-steady across all four: 16.2–17.6
fps, 668–691 MiB peak allocated `[M]`.

**The honest limit of this result:** every sequence tested is from our own
corpus, which the multi-cue and fragmentation lanes have already characterised
as rotation-dominant and largely near-static. I did not run a benchmark
sequence, so I cannot separate "DPVO is unstable" from "DPVO is unstable on
*this* footage". The published EuRoC and TartanAir accuracy `[Q]` argues
strongly for the second. But this footage is the deployment target, so the
distinction does not change the recommendation — it only changes the blame.



---

## 9. Compute on an RTX 5070 12 GB

`dpvo_frontend_cost.py` loads the **real released `dpvo.pth`** (13.1 MB
download, 14.17 MB checkpoint, 98 tensors, 3,532,549 parameters — 379,520 in
the Patchifier, 3,153,029 in the update operator `[M]`) into DPVO's **real
`extractor.py`** with `strict=True`, and runs it on real capture frames at the
resolution DPVO's own `stream.py` would produce (640×352 after its `%16` crop).
Only `altcorr.patchify` — a gather — is replaced, by a `grid_sample`
equivalent, because that one is a CUDA extension.

| | fp32 | AMP (DPVO's default) |
|---|---|---|
| JPEG decode | 0.657 ms | 0.576 ms |
| `fnet` + `inet` encoders | 2.552 ms | 2.550 ms |
| patchify (96 patches) | 0.633 ms | 0.544 ms |
| **frontend total** | **3.185 ms → 314 fps** | **3.094 ms → 323 fps** |
| peak VRAM allocated | 74.1 MiB | 39.9 MiB |
| peak VRAM reserved | 132 MiB | 100 MiB |

All `[M]`, 195 timed frames after 5 warmup, feature maps 128×160×88 (fnet) and
384×160×88 (inet). **Caveat: the GPU was concurrently loaded by the other two
research lanes during part of this session** (`nvidia-smi` showed 98–100%
utilisation and ~10.5 GB in use by other processes at several points `[M]`), so
these are conservative — an idle machine would be at least as fast.

Interpretation. Our capture is 11.99 fps. DPVO's frontend alone has **26×
headroom** at that rate and uses 0.6% of the card's memory. The *whole* system,
measured end-to-end in §8b, runs at **16.93 fps and 682 MiB peak** — 1.41× real
time and 5.6% of the card `[M]`, comfortably under the 4.9 GB the paper quotes
for an RTX-3090 at its own resolutions `[Q]`, because our images are small.
Compute is emphatically not the obstacle; **that is precisely why "it is cheap"
is not an argument for adopting it.**

For reference, the matchers we did run end-to-end, per 360×640 pair, under the
same contention `[M]`: ORB+Lowe 8.1 ms (CPU), LoFTR 93.3 ms, DISK+LightGlue
104.5 ms; peak VRAM across all three loaded simultaneously 935.5 MiB. At 12
fps, LoFTR at 93 ms/pair is **not** real-time on this host today.

---

## 10. Fit against the real `backend.py` seam

`backend.py` was read in full. The seam is unusually well-shaped for this class
of system, and its *contract* is not.

**What fits, and fits well.**

- `estimate_window(window: Sequence[KeyframeInput]) -> GeometryEstimate` takes
  a window, and DPVO is natively a sliding-window system
  (`OPTIMIZATION_WINDOW: 10`). The docstring's own argument — "a pairwise
  interface would cripple a pointmap model, which reasons over a whole submap"
  — applies verbatim to DPVO.
- `begin/extend/snapshot/reset` is the incremental seam, and the base class
  warns its default implementation "is correct for every backend and quadratic
  for every backend". **DPVO is forward-only and O(1) per frame**, so it would
  override all four and be one of the few backends for which that seam pays
  off as designed.
- `prepare(intrinsics)` maps directly onto DPVO's `(fx, fy, cx, cy)` tensor,
  and we have a genuine ChArUco calibration with distortion coefficients that
  DPVO's `stream.py` already knows how to apply.
- `PointBlock.support_views` would be populated for free (§6.3).
- The invariant "nothing under backend/ imports store, engine, or paths" is
  preservable; the weights path would be injected through the constructor.

**What does not fit — and this is a contract problem, not a plumbing problem.**

1. **`PoseEstimate.translation` is unit length when SOLVED.** The docstring
   justifies it correctly for *two-view* geometry. But a window solve produces
   translations that are mutually consistent up to a single window-wide scale —
   and that consistency is the main thing DPVO adds over what we have.
   Normalising each translation to unit length would **discard DPVO's actual
   contribution**. Adopting any window-solving backend requires either widening
   `PoseEstimate` (e.g. a `scale_is_window_consistent` flag) or accepting that
   the seam silently degrades the backend to two-view semantics. Worth flagging
   to the synthesis regardless of whether learned VO is adopted — the same
   applies to a pointmap backend.
2. **DPVO has no refusal.** The seam's second pinned invariant is that "a
   backend that cannot justify a pose returns None with a degeneracy reason …
   exactly what lets the whole engine run honestly". DPVO computes no
   triangulation angle, no inlier ratio, no `r_H`, no cheirality fraction, and
   emits a pose for every frame unconditionally: **1848 frames in, 1848 poses
   out, `refusals: 0`, on every capture tested** `[M]`. Under pure rotation it
   produces a smooth, plausible, unreproducible trajectory — §8b measures
   exactly that. Synthesising a degeneracy signal from DPVO's internal patch
   weights is possible in principle but is research, not integration, and the
   weights are not calibrated for it.

   Worth being precise about what DPVO *does* have: `KEYFRAME_THRESH` removes
   a keyframe when the optical flow between its neighbours is too small, which
   is an *insufficient-motion* test — our `insufficient_motion` rejection has a
   direct counterpart. What has no counterpart is *cannot-solve*. DPVO reduces
   near-static stretches to fewer keyframes and then poses them anyway.
3. **`reset()` per segment defeats the point.** Our engine resets the backend
   at every segment boundary — 51 of them on the canonical capture. DPVO's
   value comes from long uninterrupted tracking. Either DPVO runs across
   segment boundaries (violating the reset contract's rationale that "segments
   do not share a coordinate frame or a unit") or it is reset 51 times and
   reduced to short bursts.

**Fallback vs. replacement.** A composite backend that calls DPVO *only where
the classical backend refused* is exactly the wrong deployment: the windows
where classical refuses are the baseline-limited ones, and §5 says that is
where a learned system is most likely to produce a confident wrong answer.
**If learned VO is ever adopted here, it should be the primary path on healthy
motion, never the fallback on degenerate motion.**

**Asynchronous / background.** Yes, and this is the low-risk option. The engine
already defers `build()` until the session ends (`--rebuild-every` defaults to
zero for measured cost reasons documented in `backend.py`). Running DPVO
offline over persisted frames — outside the live path entirely — costs nothing
architecturally and is what any evaluation should do first.

---

## 11. Licensing — code and weights are different questions

| Component | Code | Weights |
|---|---|---|
| **DPVO / DPV-SLAM** | **MIT** (`LICENSE`, Princeton Vision & Learning Lab, 2022) `[M, read from clone]` | `dpvo.pth` distributed via Google Drive / Dropbox with **no separate licence file**; inherits MIT by default but this is an assumption, not a statement `[M]` |
| **DROID-SLAM** | **BSD-3-Clause** (Princeton Vision & Learning Lab, 2021) `[M, read from clone]` | `droid.pth` via Google Drive, **no stated licence terms** `[Q]` |
| Training data for both | — | **TartanAir, CC BY 4.0** `[Q]` — permissive, attribution required |
| **LoFTR** | Apache-2.0 `[Q]` | indoor/outdoor checkpoints released with the repo `[Q]` |
| **DISK** | Apache-2.0 `[Q]` | `depth-save.pth`, trained on MegaDepth `[M, downloaded by kornia]` |
| **LightGlue** | Apache-2.0 `[Q]` | **"the pre-trained weights … are released under the Apache-2.0 license"** — explicitly stated `[Q]` |
| **SuperPoint** | Magic Leap **non-commercial research only** `[Q]` | same restriction, and it covers the weights `[Q]` |

Practical consequences:

- **DPVO's optional extras change the licence surface**: `DPViewer` depends on
  a bundled Pangolin, and the "classical backend" for large loop closures pulls
  in DBoW2. Both are optional and both were skipped here; if adopted, they need
  separate review.
- **Avoid SuperPoint entirely.** The commonly-cited "SuperPoint + LightGlue"
  pairing is licence-poisoned for anything commercial. **DISK + LightGlue is
  the Apache-2.0 equivalent** and is the pairing this lane benchmarked for
  exactly that reason.
- The weights being silent is the real risk on both Princeton systems. If
  learned VO were ever shipped, that needs a direct answer from the authors,
  not an inference from the code licence.

---

## 12. Where the DROID / DPVO family *would* help, and where it would not

- **DEVO** (event-based DPVO) is not applicable: the Ray-Ban glasses have no
  event sensor.
- **DPV-SLAM** adds loop closure to DPVO at 1×–4× real time and 5–7 GB `[Q]`.
  Loop closure is a real architectural gap for us (the brief confirms none
  exists). But DPV-SLAM's loop closure operates on *its own* patch graph, so
  adopting it means adopting the whole system, not borrowing the mechanism —
  and it would inherit §8b's reproducibility problem, since it optimises the
  same unreproducible translations more globally. Note the DPVO build we
  produced already includes `dpvo/loop_closure/`; enabling it is a config flag
  plus DBoW2/DPRetrieval, so this is testable without further porting if
  the synthesis wants it.
- **DROID-SLAM** is the accuracy ceiling of the family and the wrong shape for
  us: heavier, dense, memory-scaling with sequence length, and its published
  practice of segmenting sequences over five minutes `[Q]` is the same
  fragmentation we are trying to eliminate.
- **The genuinely transferable idea** is neither system's network. It is that
  both systems maintain a **many-frame observation graph** and optimise over it
  jointly. §8 shows we can build that graph with ORB.

---

## 13. What I could not do, stated plainly

- **No DPVO run on Windows.** The Windows build is blocked by a CUDA 11.8 /
  cu13.2 mismatch and the total absence of MSVC `[M]`. Everything DPVO-related
  here ran in WSL2 against the same physical GPU.
- **No DROID-SLAM run at all.** Its build is strictly heavier than DPVO's
  (`lietorch`, `droid_backends`, plus an eigen dependency) and DPVO answered
  the lane's question. §6.1 prices it from source arithmetic, not from a run.
- **No benchmark sequence.** I have no EuRoC/TartanAir run to calibrate §8b's
  reproducibility spread against, so I cannot say how much of it is DPVO and
  how much is our footage. Every capture I tested is ours.
- **No ground truth anywhere.** Nothing in this report says a pose is correct.
  §5 is the only measurement with a known right answer, and that answer is
  "zero baseline"; §8b is a self-consistency test, not an accuracy test.
- **The `tdir` cross-matcher agreement check was cut** for time under GPU
  contention; the null experiment answers the same question more directly.
- **`torch-scatter` still does not build** against torch 2.13 here; DPVO ran
  against the pure-torch shim, which is exact for the three ops used but is a
  substitution and is named as one `[M]`.
- The matcher timings in §4 and §9's frontend table were taken while two other
  research lanes were using the same GPU (`nvidia-smi` at 98–100% utilisation
  `[M]`); treat them as upper bounds. The §8b DPVO runs had the card to
  themselves.

---

## 14. Recommendation

**Do not adopt learned visual odometry as World Builder's frontend now.** Not
because it is expensive — measured end-to-end here, it is startlingly cheap:
1.41× real time in 682 MiB with bounded memory over 1848 frames. Not because it
fails to deliver continuity — it delivers exactly the continuity we lack, one
map instead of fifty-one. But because **the continuity it delivers is not
reproducible on our footage**: two runs of the same system on the same frames
disagree by 12–38% of the trajectory's own extent, and the correspondence half
of the story is worse still — a stronger matcher is fooled by pure rotation
2.4× more often than ORB.

Replacing 51 honest fragments with 1 unreliable trajectory is a regression in
everything except appearance. World Builder's design invariant — that a backend
which cannot justify a pose returns `None` with a reason — is the property that
DPVO does not have and cannot easily be given.

In priority order, what this lane's evidence supports:

1. **Widen `_extend` from 1 previous keyframe to 3.** ORB, no new dependency.
   Measured to double the ≥5-view track fraction and triple the p90 covisibility
   span `[M]`. This is the precondition that makes the already-written bundle
   adjustment stop being a no-op, and it honours the repo's own instruction to
   "add covisibility first".
2. **Prefer wider baselines over better matchers.** Gap 1 → gap 5 moved
   solvable from 28.2% to 44.4% `[M]`, a larger effect than any matcher change,
   at zero cost.
3. **Treat `MIN_TRIANGULATION_ANGLE_DEG` as a gate with a measured 14.4% false
   positive rate under pure rotation** `[M]`, and do not raise the match count
   feeding it without re-measuring that rate. This lane's null harness is
   reusable for exactly that.
4. **Adopt the repeat-run test as a standing acceptance criterion**, for *any*
   candidate backend including our own. It needs no ground truth, costs one
   extra run, and it is the only thing in this lane that caught a
   good-looking trajectory being wrong. Pair it with the cross-segment lane's
   reciprocity check: this codebase has now been fooled twice by
   self-consistent-looking geometry, and twice been saved by asking the same
   question a second way.
5. **Keep the WSL DPVO build.** It cost two hours and it is the only way we can
   currently ask "is this footage reconstructible at all by a
   state-of-the-art system" — which is a genuinely useful question to be able
   to answer about a new capture, even if DPVO never ships. Run it on
   healthy-motion captures and judge it on repeat-run agreement, not on how
   the trajectory looks.

---

## 15. Harness index

| file | what it does |
|---|---|
| `matcher_showdown.py` | ORB vs LoFTR vs DISK+LightGlue through the production verdict pipeline, on the persisted session's keyframe pairs |
| `rotation_null.py` | the pure-rotation null: real frames, real calibration, exactly-zero true baseline |
| `covisibility_span.py` | frame-gap sweep and ORB track/covisibility-span measurement on raw capture frames |
| `analyze_showdown.py` | blur- and gap-stratified reads of the showdown output |
| `dpvo_frontend_cost.py` | real `dpvo.pth` weights in DPVO's real extractor, timed and VRAM-profiled on real frames (runs on Windows, no CUDA extensions needed) |
| `dpvo_run_capture.py` | drives the *whole* DPVO system over a capture and measures frames/keyframes/fps/VRAM/trajectory shape (WSL only) |
| `dpvo_reproducibility.py` | Umeyama-Sim(3) comparison of two DPVO runs on identical frames — the repeat-run test |
| `torch_scatter_shim.py` | exact pure-torch `scatter_sum`/`scatter_max`/`scatter_softmax`; copy to `torch_scatter.py` on `sys.path` |
| `wsl_build_dpvo*.sh` | the no-sudo WSL toolchain bootstrap and DPVO build (`3` is the one that works, given `1` and `2` have run) |

Outputs: `matcher_showdown.json`, `rotation_null.json`, `covisibility_orb.json`,
`covisibility_loftr.json`, `dpvo_frontend_cost_{fp32,amp}.json`. DPVO run
outputs stay inside WSL at `~/dpvo_run/` (they are 1848×7 float arrays plus
JSON summaries; the summaries are transcribed into §8b).

### Reproducing the DPVO runs

```bash
wsl -d <distro>
cd ~/dpvo_build && . venv/bin/activate
SP=$(python -c "import site;print(site.getsitepackages()[0])")
export LD_LIBRARY_PATH=$SP/nvidia/cu13/lib:$LD_LIBRARY_PATH
cd ~/dpvo_run   # contains torch_scatter.py (the shim) and dpvo.pth
python dpvo_run_capture.py \
  --frames   /mnt/c/.../tower/data/captures/<id>/frames \
  --intrinsics /mnt/c/.../tower/data/world_builder/intrinsics/360x640.json \
  --weights ./dpvo.pth --stride 2 --out run_a.json
# then again to run_b.json, and:
python dpvo_reproducibility.py run_a.poses.npy run_b.poses.npy
```
