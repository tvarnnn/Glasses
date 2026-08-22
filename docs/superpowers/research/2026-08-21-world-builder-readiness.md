# Research — World Builder Readiness: Environment, Architecture, and Prerequisites

Status: **research / readiness only, produced 2026-08-21.** Nothing here
authorizes implementing World Builder, creating a cartridge, wiring Object
Memory, altering streaming, or resolving the V1.1 architecture question.

**This document continues `2026-08-20-world-builder-foundations.md`; it does
not supersede it.** That document chose an experiment sequence (A–D). This
one answers a different question — *is the Tower ready, and is the proposed
architecture right* — and it reaches a conclusion that materially changes
the answer to the second half. Where the two disagree, the disagreement is
named explicitly in §7 rather than resolved silently.

**Provenance convention.** Every claim is tagged:

- `[VERIFIED]` — I ran the command or read the file in this session.
- `[REPO]` — quoted from a file in this repository, with path.
- `[PUBLISHED]` — a claim in external literature whose source I fetched and
  confirmed in this session.
- `[AGENT]` — reported by a research subagent from a source I did **not**
  independently re-fetch. Treat as a lead, not a fact.
- `[INFERENCE]` — my reasoning. Not a measurement.
- `[UNKNOWN]` — could not be established. Not guessed.

Per `02-DEVELOPMENT-RULES.md` Rule 3 and Rule 16, no number in this
document is invented, and no inference is presented as a measurement.

---

## 1. Recovery of the interrupted run

The previous session (transcript `ba3f65e2-598d-4b95-834f-2b88a89b54c2`)
was interrupted at 23:12 for an authentication/billing change, roughly one
minute before this session began. **No work was lost, and none was
repeated.**

`[VERIFIED]` What survived, and what did not:

| Artifact | State |
|---|---|
| Git branch / commit | `master @ 21d13c6`, working tree **clean** |
| Stashes, other branches, uncommitted work | **none** — the interrupted session committed nothing |
| Subagent `.output` result files (8) | **all 0 bytes** — every agent was killed mid-run |
| Subagent full transcripts (8) | **all intact**, 726 KB total, recovered and read |

The interrupted session had dispatched five research tracks (A: repo/CV
recovery, B: mapping architecture, C: GPU environment, D: persistence,
F: camera intrinsics), and Track F had itself spawned three sub-agents
(DAT SDK API, Ray-Ban camera specs, calibration sensitivity). All eight
were killed before writing a report, but all eight had already executed
18–56 tool calls whose results are preserved in their transcripts.

**Recovery method:** the transcripts were rendered to text and read rather
than re-derived. Tracks C and F had substantively *completed* their
investigation and needed only synthesis, which is done here. Tracks A, B,
and D were re-dispatched **with their own recovered transcript as required
reading and an explicit instruction not to redo finished work**, so the
expensive web research and repo traversal were not paid for twice.

Interrupted-session work was preserved, not deleted.

### 1.1 Facts the interrupted session had already established

Recorded here so they are not lost with the transcript: the DAT discrete
frame-rate/resolution sets (§3.2), the absence of any capture timestamp on
the wire (§3.3), the synchronous scalar-only module contract (§3.4), and
the observation that Experiment 2's frame-gap curve is really a *time
baseline* curve (§4.2) — which is the seed of this document's central
argument.

---

## 2. Starting state, verified

`[VERIFIED]` Branch `master`, commit `21d13c6`, tree clean at session
start. Baseline suite re-run in this session before any change:

```
210 passed, 3 skipped in 2.15s
```

This matches the expected pre-run baseline exactly.

`[REPO]` Historical rulings carried forward unchanged, and **not** rewritten
by this document: V0.5–V0.7 complete with the V0.7 FPS limitation
attributable to iOS; Phase 1.5 partially exercised with the auth exit
criterion unmet; V0.8/V0.9/V0.9.1/V0.9.2/V0.9.3 complete; V1.0 untriggered;
V1.1 **BLOCKED**; V1.2 the documented next milestone.

`[VERIFIED]` The V1.0 ruling still holds for the stated reason — both
selectable modules genuinely share a descriptor id:

```
tower/modules/depth_cv.py:6:        id="experimental-cv",
tower/modules/experimental_cv.py:5: id="experimental-cv",
```

---

## 3. The Tower environment as it actually is

### 3.1 GPU and CUDA — a regression, not a limitation

`[VERIFIED]` The hardware is present and healthy:

```
NVIDIA GeForce RTX 5070, driver 596.21, 12227 MiB total, 10573 MiB free,
compute capability 12.0 (Blackwell / sm_120), CUDA 13.2, WDDM
```

`[VERIFIED]` **But torch cannot reach it:**

```
torch 2.13.0+cpu   cuda None   available False   arch_list []
torchvision 0.28.0+cpu
cv2 5.0.0          cv2.cuda device count 0
```

`[VERIFIED]` `.venv/Lib/site-packages/torch/lib/` contains **zero**
CUDA/cuBLAS/NVRTC DLLs, and no `nvidia-*` pip packages are installed. This
is a genuine CPU-only build.

**This is a regression, not the original state.** `[REPO]`
`guidelines/docs/reports/V0.9.1-depth-cv-baseline-report.md:43-44` records
that the V0.9.1 benchmark ran on **`torch 2.13.0+cu132`** against this same
RTX 5070 (`get_device_capability(0) == (12, 0)`), allocating 82.7 MB of
VRAM. `[VERIFIED]` The 1.9 GB `torch-2.13.0+cu132` wheel still exists in a
prior session's scratchpad, and `.venv/.../torch/lib/` was rewritten at
**2026-08-20 16:56** — after that benchmark. A later venv operation
replaced the CUDA build with a CPU build.

`[VERIFIED]` Restoration path: `torch 2.13.0+cu130` and
`torchvision 0.28.0+cu130` are both available from
`https://download.pytorch.org/whl/cu130` and match the installed version
numbers exactly. The `cu128` index tops out at torch 2.11.0. **CUDA 12.8+
is required for sm_120**, so cu130 is the correct target and cu128 would
also work at an older torch. *This document does not perform the install
— it is an environment change outside this mission's scope.*

**Consequence: every ML-based option in §6 is unevaluable today.** This is
the single highest-priority prerequisite.

### 3.2 The toolchain gap — the finding that reshapes the architecture choice

`[VERIFIED]`, and load-bearing:

| Component | State |
|---|---|
| Visual Studio / Build Tools | **absent** — neither `Program Files` nor `Program Files (x86)` VS directory exists |
| `cl.exe` | **not on PATH** |
| Windows SDK (`Windows Kits\10\Include`) | **absent** |
| CUDA Toolkit | **11.8 only** (2022) — `CUDA_PATH` points at it; predates Blackwell entirely |
| WSL2 | **available**, distro `ITSC-3146`, version 2, currently Stopped |

**There is no C++/CUDA compiler on this machine.** Any research codebase
requiring custom CUDA kernel compilation cannot be built natively here at
all — not "with difficulty," but not at all until a toolchain is
installed. This is a much harder constraint than "some SLAM systems are
Linux-first," and it is the reason this document departs from the research
track's recommended ordering in §6.5.

### 3.3 What OpenCV gives us for free

`[VERIFIED]` `opencv-python-headless 5.0.0`. Every geometry and
calibration primitive a monocular pipeline needs is present:

- **Features:** `ORB_create`, `SIFT_create` ✅ (note: `AKAZE_create` and
  `BRISK_create` are **absent** in this OpenCV 5 build)
- **Flow:** `calcOpticalFlowPyrLK`, `calcOpticalFlowFarneback`,
  `DISOpticalFlow_create` ✅
- **Geometry:** `findEssentialMat`, `findFundamentalMat`, `findHomography`,
  `recoverPose`, `decomposeEssentialMat`, `triangulatePoints`,
  `solvePnPRansac`, `correctMatches`, `USAC_MAGSAC` ✅
- **Calibration:** `calibrateCamera`, `calibrateCameraRO`,
  `findChessboardCornersSB`, `findCirclesGrid`, `initCameraMatrix2D`,
  `undistort`, `fisheye` ✅
- **ChArUco:** `cv2.aruco.CharucoBoard`, `cv2.aruco.CharucoDetector` ✅
  (`calibrateCameraCharuco` is **gone** in OpenCV 5; the modern path is
  `CharucoDetector` → `matchImagePoints` → `calibrateCamera`)

**Absent:** all contrib modules (`xfeatures2d`, `sfm`, `rgbd`, `optflow`,
`tracking`, `ximgproc`, `quality`) and CUDA support.

**Consequence: self-calibration requires zero new dependencies.** See §5.

### 3.4 Host, libraries, and model cache

`[VERIFIED]` CPU is an **Intel Core Ultra 7 265F, 20 cores / 20 threads**
— *not* the i9 stated in the mission brief. RAM 31.7 GB total. Disk C:
796 GB free. Python 3.12.5.

`[VERIFIED]` Present: numpy 2.5.2, Pillow 12.3.0, timm 1.0.28, psutil.
**Absent:** scipy, kornia, open3d, onnxruntime, tensorrt, numba, cupy,
transformers, matplotlib, sklearn, av, trimesh, pyarrow.

`[AGENT]` Model cache already holds `midas_v21_small_256.pt` (81.8 MB) and
`tf_efficientnet_lite3` (31.6 MB); HF cache holds `all-MiniLM-L6-v2`
(87.3 MB).

### 3.5 Measured compute headroom — new to this session

`[VERIFIED]` Classical front-end cost on this Tower, measured at the three
DAT resolutions. Synthetic max-entropy texture saturating ORB's feature
cap, so **detect cost is an upper bound**; this is not a substitute for a
real-footage measurement:

| Resolution | JPEG decode | ORB detect+describe | knnMatch | **Total** |
|---|---|---|---|---|
| **360×640** (`low`, what we actually receive) | 0.85 ms | 3.83 ms | 0.63 ms | **5.31 ms** |
| 360×640, 2000 features | 0.86 ms | 4.52 ms | 1.39 ms | 6.77 ms |
| **504×896** (`medium`) | 2.09 ms | 6.31 ms | 0.70 ms | **9.09 ms** |
| **720×1280** (`high`) | 4.18 ms | 11.94 ms | 0.92 ms | **17.04 ms** |

At the iOS team's 10–12 FPS target the per-frame budget is **83–100 ms**.
A full classical front-end at the *highest* DAT resolution consumes
**~17–20% of that budget on CPU alone, with the GPU completely idle.**

`[REPO]` This is consistent with the transport handoff's finding that the
Tower sustains **~736 fps** at 360×640 as shipped
(`docs/superpowers/handoffs/2026-08-21-ios-observation-rate.md`).

**The live tracking front-end is not a compute problem and never will be.**
Any GPU requirement in this pipeline comes from learned geometry, not from
tracking.

---

## 4. What this repository already knows

Recovered in full; not re-derived. Full inventory in the Track A synthesis.
The load-bearing items:

### 4.1 Existing CV assets

`[REPO]` `tower/experiments/depth.py` — MiDaS-small via `torch.hub` at a
**pinned commit**, the platform's only ML model; has an opt-in
`capture_depth_array` hook added for Experiment 1.
`tower/experiments/{baseline,edge_detection}.py` — stateless scalar
experiments. `scripts/depth_temporal_consistency.py` (354 ln) and
`scripts/feature_trackability.py` (264 ln) — the Experiment 1 and 2
harnesses, both offline, both bypassing the WebSocket path.
`scripts/verify_cuda.py`, `scripts/depth_benchmark.py`,
`scripts/soak_test_stream.py`. `tests/test_world_builder_experiment_clis.py`
pins 20 harness properties including causality of the smoothers.

`[REPO]` **Not present anywhere:** optical flow in the Tower, SLAM, visual
odometry, pose estimation, keyframe selection, triangulation, fusion, point
clouds, map persistence, or any viewer.

### 4.2 Experiments already run — and one new reading of them

**Experiment 1 (`depth_temporal_consistency`), EPIC-KITCHENS `P01_107`,
150 frames at effective 16.67 fps, analysis grid 128×256, CPU.** Raw
frame-to-frame depth flicker `mad_mean` **0.0633–0.0761** across three
independent normalizers — 6–8% of full depth range between consecutive
frames, p95 regions 19–23%. Best cheap smoother EMA α=0.3: **42–53%**
flicker reduction at a measured **3-frame (~180 ms)** step-response lag.
These are a **lower bound** — the analysis grid is ~1/7 the linear
resolution of the platform budget.

**Experiment 2 (`feature_trackability`), same clip, 504×896, ORB-1000.**
`[REPO]` Read directly from
`guidelines/docs/reports/data/V0.9.3-experiment2-feature-trackability.json`:

| Gap `k` | Time baseline | Verified inliers (mean/median) | Inlier ratio | **Rotation-dominant** | **Pairs with ≥30 inliers** |
|---|---|---|---|---|---|
| 1 | 60 ms | 386.5 / 384 | 0.885 | **53.69%** | **100.0%** |
| 2 | 120 ms | 261.3 / 252 | 0.836 | 41.22% | **100.0%** |
| 5 | **300 ms** | 123.0 / 97 | 0.758 | **12.41%** | **72.41%** |
| 10 | 600 ms | 51.2 / **24** | 0.645 | 11.72% | **47.14%** |

**The two-sided nature of this curve is already recorded, and credit
belongs to the V0.9.3 report.** `[REPO]` It states the tension precisely:
*"consecutive frames match superbly but over half carry too little parallax
to triangulate, while k=5 pairs have good parallax (12% degenerate) but
only 72% clear the inlier floor and the typical pair has fallen to 97
inliers"*, and concludes that *"any future keyframe policy should key off
measured match counts, not a fixed frame interval."*

**What is new here is only the conversion to a time axis.** The report
tabulates frame *gaps*; at the experiment's 16.67 fps effective sampling
those gaps are 60 / 120 / 300 / 600 ms. Reading the curve in time rather
than in frames is what makes it transferable to a different delivery rate:

> **There is a narrow usable window around a ~300 ms time baseline**, where
> rotation-dominance has already dropped to 12.4% but 72% of pairs still
> clear the inlier floor. Below it, geometry is degenerate; above it,
> correspondence is gone.

`[INFERENCE]` Two consequences follow, and they drive §7:
1. **Tracking rate and mapping baseline must be decoupled.** At a delivered
   10–12 FPS, consecutive frames sit 83–100 ms apart — squarely in the
   ~41–54% degenerate band. Reaching the good-parallax regime means pairing
   frames **3–4 apart**, i.e. a mapping rate near 3 Hz regardless of the
   delivery rate.
2. **Wide-baseline correspondence is the binding constraint, and it is
   resolution-sensitive.** The 72%-clear figure was measured at 504×896.
   The glasses actually deliver 360×640.

**Caveat that cuts in our favour, and is unverified.** `[INFERENCE]`
EPIC-KITCHENS `P01_107` is kitchen task footage — largely standing and
manipulating objects, which is rotation-heavy and translation-poor. "Walk
around a room" generates substantially more translation. The 53.69%
figure may therefore be *pessimistic* for the actual World Builder use
case. This is a hypothesis, not a result, and `[REPO]` the V0.9.3
acceptance gate forbids citing any of these numbers as positive validation
for the platform's own camera until they are re-run on real DAT footage.

### 4.3 Other established findings

`[REPO]` MiDaS-small produces **relative inverse depth, never metric**, and
its accuracy has **never been measured** — V0.9.1 measured latency and
throughput only. V0.9.1 CUDA-vs-CPU: inference 15.4 ms vs 22.7 ms (~32%
faster), but `process_cpu_percent` **94.8 vs 1683.2** — the real GPU win
is CPU relief, not latency. `[REPO]` TensorRT/CV-CUDA/DeepStream remain
unjustified by measurement. Gaussian Splatting was explicitly ruled out of
Experimental CV Lab evaluation.

### 4.4 Failed and abandoned work

`[REPO]` GTEA Gaze+ dataset — **dead host** (NXDOMAIN). TUM RGB-D —
rejected as wrong motion regime. Local webcam capture — **failed**, all
`cv2.VideoCapture` indices fail to open. Experiment 1's first draft was
**retracted and re-run** after four metric defects (a lag metric misread,
flicker reduction inflated by amplitude compression, a window statistic
measuring camera movement rather than estimator stability). Experiment 2's
first draft was retracted for an invalid homography-vs-fundamental inlier
comparison, replaced by `R_H` with ORB-SLAM's 0.45 threshold.

**This repository has a strong track record of retracting its own
results.** That norm is why the numbers above can be trusted.

---

## 5. Camera intrinsics — the blocker is real, and it is closable

### 5.1 What the blocked experiments need

`[REPO]` `03-ROADMAP.md:123` and `foundations.md:444-527`. Experiment 3
(`monocular_pose_feasibility`) needs `fx, fy, cx, cy` at minimum because
`recoverPose` decomposes an *essential* matrix, which is defined only for a
calibrated camera. Its stated hard prerequisite: *"this experiment cannot
produce a meaningful pose estimate without them, only a 'does the code run'
check."* Experiment 4 (`depth_scale_fusion`) needs intrinsics **only via
its triangulation path**; its ground-plane and metric-model paths do not.

**Correction to a claim the repo repeats.** `[REPO]`
`2026-08-20-weekend-autonomous-run-report.md:265-266` calls intrinsics
*"the only thing blocking Experiments 3–4."* That is the only *named*
blocker but not the only missing input. Experiment 3 also needs **real
footage with a coarsely-known walked path**, and Experiment 4 also needs
**5–10 physically measured reference distances**. `[VERIFIED]` A filesystem
search across both project repositories found **no captured frames, videos,
or recorded sessions of any kind**. We have zero real Ray-Ban footage saved
anywhere. Intrinsics is one of *three* prerequisites, and it is not the one
that is cheapest to miss.

### 5.2 DAT exposes nothing — settled

`[AGENT]`, from the fetched DAT 0.9 iOS API reference. The complete
`MWDATCamera` surface is: classes `Camera`, `Stream`; enums `CameraState`,
`PhotoCaptureFormat`, `StreamError`, `StreamingResolution`, `StreamState`,
`VideoCodec`; structs `PhotoData`, `StreamConfiguration`, `VideoFrame`,
`VideoFrameSize`.

**`VideoFrame` has exactly two members:** `sampleBuffer: CMSampleBuffer`
and `makeUIImage()`. No timestamp, no dimensions, no orientation, no
intrinsics.

`[AGENT]` The `Stream` class documentation contains **no** mention of
intrinsics, calibration, pose, IMU, or depth. `MWDATCore.DeviceSession`
exposes no motion or inertial API whatsoever.

`[REPO]` `07-PLATFORM-CONSTRAINTS.md:79-83` (verified against DAT 0.9.0):
`StreamingResolution` = `high` 720×1280 / `medium` 504×896 / `low` 360×640,
all 9:16; `frameRate` ∈ **{2, 7, 15, 24, 30}**, a fixed discrete set;
codecs `.raw` or `.hvc1`; and DAT applies an internal adaptive ladder that
**lowers resolution one step first, then frame rate, never below 15**, with
per-frame compression adapting independently.

> **`[INFERENCE]` DAT's adaptive policy degrades exactly the axis World
> Builder cares most about, and we cannot override it.** §4.2 shows the
> binding constraint is wide-baseline correspondence, which is
> resolution-sensitive; DAT sheds resolution first and frame rate second.
> This should be recorded as a platform limitation in its own right.

### 5.3 The published FOV number is not usable — not even as an approximation

`[AGENT]` Third-party sources report the Ray-Ban Meta Gen 2 camera as 12 MP
(3024×4032 stills) with a **100° field of view**; Meta's own Gen 2
announcement publishes **no** FOV or sensor figure. No iFixit teardown
identifies the sensor. No credible EXIF report of focal length was found.

`[INFERENCE]` **Even taking 100° as true, it cannot be converted into
intrinsics for our stream.** The stills are 3:4 (0.75 aspect); the video
stream is 9:16 (0.5625). These are different readouts of the sensor, and
the crop/scale relationship between them is undocumented. A focal length
derived from the stills' FOV and applied to a 360×640 frame would be a
fabricated number wearing the costume of a measurement — precisely what
`02-DEVELOPMENT-RULES.md` Rule 3 forbids and what
`V0.9.3-...-report.md:308-313` already refused to do once.

**Project Aria is a different product.** `[AGENT]` Aria publishes full
per-device calibration (`Fisheye624` / `FisheyeRadTanThinPrism`) via
`projectaria_tools`. **No Aria number is legitimate for Ray-Ban Meta
hardware**, and any use of one would be fabrication.

### 5.4 We can calibrate this ourselves, with zero new dependencies

`[VERIFIED]` §3.3 — `cv2.aruco.CharucoBoard`, `cv2.aruco.CharucoDetector`,
`findChessboardCornersSB`, and `calibrateCamera` are all present in the
already-installed OpenCV.

**Procedure (specified, not executed — it needs the glasses and a printer):**

1. Generate a ChArUco board with `cv2.aruco.CharucoBoard` (e.g. 7×5 squares,
   `DICT_4X4_50`); print it at a known square size onto rigid flat stock.
   ChArUco rather than a plain checkerboard because it tolerates partial
   views and occlusion, which matters when the wearer cannot see the frame.
2. **Capture through the real pipeline** — glasses → DAT → iOS → Tower —
   at the exact `StreamingResolution` that production will use. Do *not*
   calibrate from phone-camera or MockDeviceKit frames: they are a
   different lens and a different sensor.
3. Save 30–60 frames with the board at varied distances, angles up to ~45°,
   and positions covering all four corners plus the centre. Corner coverage
   is what constrains distortion.
4. `CharucoDetector.detectBoard` → `Board.matchImagePoints` →
   `cv2.calibrateCamera`, with `cv2.CALIB_RATIONAL_MODEL` if a wide lens
   fits poorly, or `cv2.fisheye` if it is genuinely fisheye.
5. Record `fx, fy, cx, cy`, distortion coefficients, **the exact resolution
   they were solved at**, the per-view reprojection RMS, and the frame
   count. Persist as `source: "self_calibrated"` (§8.4).
6. **Repeat at a second resolution** and test whether intrinsics scale
   linearly (`fx' = fx·W'/W`). If they do, DAT is pure-scaling and one
   calibration covers all three modes; if they do not, it is cropping and
   each resolution needs its own. **This is currently `[UNKNOWN]` and it
   matters**, because the adaptive ladder changes resolution mid-stream.

**Step 2 is the reason §11's first slice is a capture path, not a mapper.**
We cannot calibrate a camera whose frames we have no way to save.

### 5.5 Are approximate intrinsics acceptable meanwhile?

**For an early feasibility check, partially. For any reported number, no.**

`[AGENT]` The published sensitivity literature (Cheong & Xiang, *Error
Characteristics of SFM with Erroneous Focal Length*, ACCV 2006; *Behaviour
of SFM algorithms with erroneous calibration*, CVIU 2010) establishes the
mechanism — focal-length error propagates into the focus-of-expansion and
couples translation with depth — but `[AGENT]` **no clean published "X%
focal error → Y° rotation error" rule of thumb was found.** I will not
manufacture one.

What stays valid under approximate intrinsics: 2D feature tracks; inlier
counts; the **fundamental**-matrix and homography analysis (Experiments 1
and 2 are `[REPO]` explicitly intrinsics-free and are unaffected); the
qualitative "does tracking survive" question.

What becomes **invalid**: essential-matrix pose, rotation magnitude,
translation direction, trajectory shape, triangulated structure, any
reprojection-error threshold, undistortion, and every metric claim. Note
`[PUBLISHED]` that focal error and translation/depth error are *coupled*
through the scale ambiguity — so a wrong focal length produces a trajectory
that looks plausible and is wrong, which is the worst failure mode
available.

**Ruling: do not fabricate intrinsics. Calibrate. It is days of work, not
months, and §6 shows there is now a second, independent escape route.**

---

## 6. Architecture — the working hypothesis, challenged

The mission's working hypothesis was:

```
monocular RGB → preprocessing → feature detection/tracking → camera-motion
estimation → monocular depth → information-based keyframes → common-
coordinate transformation → multi-view fusion → confidence update →
persistent world
```

`[REPO]` This mirrors `WORLD-BUILD.md`'s Candidate Pipeline. **I recommend
against it as stated**, for reasons that are grounded in this project's own
measurements.

### 6.1 The two facts that collapse the option space

**Fact 1 — every classical pipeline needs intrinsics we do not have.**
ORB-SLAM3, stella_vslam, DSO, SVO, DROID-SLAM, DPVO/DPV-SLAM, and COLMAP
with a fixed camera all require `fx, fy, cx, cy` before producing anything
meaningful.

**Fact 2 — head-worn motion is rotation-dominant, and that is a hard
degeneracy.** `[VERIFIED, our own data]` 53.69% of consecutive pairs at
60 ms. `[PUBLISHED]` Triangulation is *ill-defined*, not merely noisy, when
two views share an optical centre — and `[AGENT]` an ICCV 2025 city-scale
egocentric benchmark reports ORB-SLAM3, DSO, OpenVINS, Kimera, DPVO and
DPV-SLAM all degrading significantly on natural egocentric motion.

**Fact 3 — a model family exists that needs neither.** `[PUBLISHED]` I
fetched and confirmed the MASt3R-SLAM abstract verbatim:

> "We present a real-time monocular dense SLAM system designed bottom-up
> from MASt3R… **robust on in-the-wild video sequences despite making no
> assumption on a fixed or parametric camera model beyond a unique camera
> centre.** We introduce efficient methods for pointmap matching, camera
> tracking and local fusion, graph construction and **loop closure**, and
> second-order global optimisation… operating at **15 FPS**."

`[PUBLISHED]` Its calibrated-vs-uncalibrated cost on TUM RGB-D is
**0.030 m → 0.060 m ATE** — roughly a factor of two, not a factor of ten.

> **Our two hardest problems — no intrinsics and rotation-dominant motion —
> are precisely the two the feed-forward pointmap family was built to
> dissolve.**

### 6.2 Candidate architectures assessed

| Family | Needs intrinsics | Survives pure rotation | Fits 12 GB | Needs CUDA compilation | License |
|---|---|---|---|---|---|
| Classical VO/SLAM (ORB-SLAM3, stella_vslam, DSO, SVO) | **Yes** | **No** | yes | C++ build | ORB-SLAM3 **GPL-3.0** |
| Classical geometry + learned mono depth *(the hypothesis)* | **Yes** | **No** | yes | no | — |
| Learned features + classical geometry (LightGlue, XFeat, LoFTR) | **Yes** | **No** — better matches don't fix a geometric degeneracy | yes | no | XFeat/LightGlue Apache-2.0; **SuperPoint non-commercial** |
| Learned VO/SLAM (DROID, DPVO, DPV-SLAM, GO-SLAM) | **Yes** | Weak | DROID `[AGENT]` ~20 GB — **no**; DPVO ~5 GB — yes | **yes** | DPVO MIT; DROID BSD-3 |
| **Feed-forward pointmap SLAM (MASt3R-SLAM, VGGT-SLAM)** | **No** | **Yes** | MASt3R `[UNKNOWN]`; VGGT-SLAM submap-tunable | MASt3R **yes**; VGGT-SLAM `[VERIFIED]` **no** | MASt3R **CC BY-NC-SA 4.0**; VGGT-SLAM repo `[VERIFIED]` **BSD-2** |
| **Feed-forward geometry model, no SLAM layer (DA3, MoGe-2, MapAnything)** | **No** | **Yes** | `[VERIFIED]` DA3-Streaming **<12 GB** | `[VERIFIED]` **no — pip installable** | `[VERIFIED]` DA3 code Apache-2.0; BASE/SMALL/METRIC-LARGE/MONO-LARGE checkpoints **Apache-2.0** |
| Gaussian-splatting / neural-field SLAM (MonoGS, Photo-SLAM, SplaTAM) | Yes | Weak | no | yes | MonoGS non-commercial; SplaTAM **needs RGB-D** |
| Offline finaliser (COLMAP, GLOMAP, VGGSfM) | partial self-calib | **No** `[AGENT]` — fails under pure rotation | n/a | prebuilt Windows binaries exist | COLMAP/GLOMAP BSD-3 |

`[VERIFIED]` I independently confirmed the two fallback candidates:
**Depth Anything 3** — code Apache-2.0, checkpoints DA3-BASE / DA3-SMALL /
DA3METRIC-LARGE / DA3MONO-LARGE **Apache-2.0** (GIANT/LARGE/NESTED are
CC BY-NC-4.0), predicts geometry "with or without known camera poses",
estimates **both extrinsics and intrinsics**, pip-installable, and
DA3-Streaming does ultra-long video "with less than 12 GB GPU memory".
**VGGT-SLAM** — BSD-2-Clause, submap-structured with configurable
`--submap_size`, loop closure present, **no custom CUDA kernel compilation
mentioned**.

### 6.3 Recommended architecture

> ### Two-rate, keyframe-anchored, feed-forward geometry with a heavy stop-time pass
>
> **Authoritative state is a graph of posed keyframes — not a point cloud.**

```
DAT → iOS → WebSocket (JPEG 360×640)
  │
  ├─ LIVE, every delivered frame  (~5 ms measured, CPU only)
  │    decode → blur/quality gate (variance of Laplacian)
  │    → sparse feature track vs. last keyframe
  │    → overlap + median parallax score
  │    → KEYFRAME? (parallax- and coverage-driven, NOT every N frames)
  │
  ├─ MAPPING, ~1–3 Hz, keyframes only  (GPU)
  │    feed-forward geometry model → per-keyframe pointmap + relative pose
  │    → local sliding-window graph optimisation (bounded VRAM)
  │    → retrieval descriptor banked per keyframe
  │    → push decimated cloud delta + camera frustum to viewer
  │
  └─ STOP-TIME, seconds to ~2 min, entire GPU free
       global retrieval over ALL keyframes → geometric verification
       → global Sim(3) pose-graph optimisation (scale included)
       → re-run geometry at higher quality on the final keyframe set
       → dynamic/low-confidence filtering
       → optional single global metric-scale solve
       → persist graph + keyframes + pointmaps + confidences
```

**Why keyframe-graph-first rather than point-cloud-first.** A fused cloud
cannot be bent back into consistency by loop closure. If the cloud is
authoritative, every drift correction forces a full rebuild — so in
practice it gets skipped, and the map silently stops improving. Storing
per-keyframe `{pose, pointmap, confidence, descriptor, thumbnail}` plus the
pose graph makes global correction a re-render rather than a migration, and
it is what makes a world **re-openable *and* improvable** rather than
frozen. This is the single most consequential structural correction in this
document, and it agrees with §8's persistence design.

### 6.4 Rejected, with the specific reason

- **The stated working hypothesis** — its pose stage is degenerate on our
  own measured motion and its depth stage is unscaled and flickering
  (measured: 6–8% frame-to-frame). Two weak legs and no third.
- **ORB-SLAM3 / stella_vslam / DSO / SVO** — need intrinsics; documented
  failure under low parallax and pure rotation; ORB-SLAM3 is GPL-3.0.
- **SuperPoint / SuperGlue** — non-commercial license contaminates any
  pipeline containing them. Prefer XFeat or DISK+LightGlue (Apache-2.0).
- **DROID-SLAM** — `[AGENT]` ~20 GB measured VRAM; does not fit 12 GB.
- **DPVO / DPV-SLAM** — needs intrinsics; benchmarked as degrading on
  egocentric motion; requires CUDA compilation we cannot do (§3.2). An
  excellent system for a problem we do not have.
- **SplaTAM** — requires RGB-D. We have no depth sensor. Non-starter.
- **MonoGS / Photo-SLAM / 3DGS-SLAM** — optimise photorealism, explicitly
  out of scope; need intrinsics; non-commercial or GPL-contaminated.
- **COLMAP/GLOMAP/VGGSfM as the stop-time finaliser** — `[AGENT]` fails
  under the same pure rotation that breaks the live path, so it is a
  *correlated* failure, not a safety net. (COLMAP remains useful as a
  calibration tool and an interchange format.)
- **Streaming pointmap reconstructors (Spann3R, CUT3R, StreamVGGT,
  Fast3R)** — `[AGENT]` non-commercial licenses, published drift, and no
  loop closure or relocalisation. Research, not a V1 engine.
- **MiDaS-small as a geometry source** — retire it from the World Builder
  path. It has no scale, no pose, no cross-frame consistency, measured
  flicker, and a 128×256 output grid. Keeping it because it is what we
  already shipped is sunk cost, not architecture.

### 6.5 Where I depart from the research track — and why

The architecture research recommended **MASt3R-SLAM under WSL2** as
primary. On published evidence alone that is the right call: it is the most
mature system that is simultaneously uncalibrated-capable, real-time,
dense, loop-closing and relocalising, with the strongest published numbers.

**I rank it second for this machine, on evidence the research track did not
have.** `[VERIFIED]` MASt3R-SLAM requires building custom CUDA kernels
(`lietorch`, `curope`, `asmk`) and there is **no C++/CUDA compiler on this
host at all** (§3.2) — the CUDA Toolkit present is 11.8, which cannot
target sm_120. In WSL2 that means provisioning a complete Linux CUDA
toolchain first. `[AGENT]` reports a user failing for 8 days on a 5070 Ti
against this exact sm_120 issue. Add `[VERIFIED]` CC BY-NC-SA licensing on
both code and checkpoints, and `[UNKNOWN]` VRAM at inference (published
only on a 24 GB 4090).

**Recommended evaluation order, ranked by environment risk rather than by
published accuracy** — because on this host the binding constraint is the
toolchain, not the algorithm:

1. **DA3 (Apache-2.0 checkpoints) + our own submap pose graph.** The only
   option that is `[VERIFIED]` pip-installable, pure PyTorch, Windows-native,
   permissively licensed, fits 12 GB, needs zero compilation — and still
   dissolves the intrinsics blocker. **Cost: we write the SLAM layer**
   (loop closure, pose graph, relocalisation). That is real work and it is
   the honest price of this option.
2. **VGGT-SLAM.** `[VERIFIED]` BSD-2 repo, submap-tunable, loop closure
   present, no custom kernels — a complete system, at the cost of a
   Linux/conda environment and VGGT checkpoint licensing.
3. **MASt3R-SLAM.** Best published accuracy; highest build risk here.
   Worth a strictly time-boxed spike once CUDA is restored, as an
   accuracy *ceiling* to measure the others against.

**Time-box every one of these to one working day** with hard pass/fail
gates: builds against torch ≥2.7/cu130 for sm_120; runs a public sequence
within 12 GB; runs our own recorded 360×640 clip uncalibrated and produces
a recognisable room. Fail any gate, drop to the next.

### 6.6 Which ML earns its complexity

**Earns it:** the feed-forward geometry model (it replaces four pipeline
stages *and* removes the intrinsics prerequisite — the only component here
that changes what is *possible*); retrieval descriptors for loop closure;
person/hand segmentation for dynamic masking (on a wearable, the user's own
hands are in frame constantly).

**Earns it conditionally:** a cheap learned matcher (XFeat, Apache-2.0,
`[AGENT]` 27 FPS sparse on CPU) used only as a *gate* to decide whether to
spend a GPU pass; a metric-depth model at stop time on ~20 frames to solve
one global scale.

**Does not earn it:** MiDaS-class relative depth as geometry; video-depth
models (they patch a flicker problem that only exists if you choose
per-frame depth); Gaussian splatting; semantic segmentation beyond
person/hand masking; learned VO.

### 6.7 The challenge questions, answered directly

- **Point-cloud-first for V1?** **No.** Posed-keyframe-graph-first; the
  cloud is a rendering of it (§6.3).
- **Is monocular depth useful for geometry?** In its MiDaS-class *relative*
  form, mostly visualisation and a liability. But the category moved:
  pointmap models are monocular *geometry* — depth plus intrinsics plus
  extrinsics — and some are metric. Use those; retire MiDaS from this path.
- **Unknown scale?** Do not solve it in V1. Store geometry in world units
  with scale as *metadata* (§8.4). Later, solve one global factor from a
  metric model or a single tape measurement.
- **Scale drift?** Structurally: submap alignment must be **Sim(3)
  (7-DoF, scale included)**, never SE(3), so global optimisation can
  redistribute accumulated scale error.
- **Pure rotation?** The reason for the whole recommendation. Classical
  triangulation is ill-defined; pointmap models predict geometry from
  monocular structure priors and remain defined. Additionally: select
  keyframes on *parallax*, which turns our measured 53.69% problem into a
  12.41% problem for free.
- **Motion blur?** Exposure-driven — **more FPS does not help and may
  hurt**. Gate on variance-of-Laplacian and simply reject blurred keyframe
  candidates; we have ~1000 frames for ~100–300 keyframes and can afford
  to be picky.
- **Textureless walls?** The strongest argument for the learned route: ORB
  finds nothing on a blank wall, a pointmap model predicts a plane. But
  `[INFERENCE]` expect the inverse failure — confident, plausible, *guessed*
  geometry — so the model's confidence channel must survive into the
  persistent state so a predicted wall is distinguishable from a
  triangulated one. `[REPO]` This is exactly what `WORLD-BUILD.md:111`
  ("Unknown space must remain unknown") demands.
- **Repeated patterns?** A loop-closure hazard, not a tracking one. **Never
  admit a loop edge on descriptor similarity alone** — require geometric
  verification.
- **Moving people?** Threshold the per-pixel confidence mask these models
  already emit, and mask people/hands. Not optional on a wearable.
- **Reflective surfaces?** No V1 fix — mirrors generate phantom rooms in
  every method including LiDAR. Down-weight via multi-view disagreement and
  **document it as a known limitation**.
- **Tracking loss / recovery?** Non-negotiable. On loss, **start a new
  submap and let loop closure re-attach it** — never keep integrating into
  the old one. Retrieval-based relocalisation is the first thing to build,
  not the last.
- **Loop closure?** Mandatory. In one room over several minutes the wearer
  re-enters the same viewpoint dozens of times; each one is free drift
  correction. It is also our best ground-truth-free accuracy metric (§10).
- **Are intrinsics mandatory?** **No longer** — twice over. The recommended
  family does not need them, and we can self-calibrate anyway (§5.4).
- **Is ~10–12 FPS sufficient?** **The question is mis-framed.** The
  requirement is *inter-frame baseline*, not rate. `[VERIFIED, our data]`
  at today's ~3.3 FPS the native gap is ~300 ms — already the good-parallax
  regime; at 12 FPS the native gap is 83 ms, back in the ~50% degenerate
  band, and most frames would be discarded again. `[AGENT]` published work
  reports >90% of frames being filterable with no ATE change for this model
  family. **World Builder readiness does not gate on the iOS FPS fix.**
  Higher FPS buys candidate frames to pick a sharp, well-parallaxed
  keyframe from, plus a smoother viewer — real, but second-order.
- **Resolution vs FPS?** **Resolution matters more**, for a specific
  reason: the binding constraint is wide-baseline correspondence (§4.2),
  which is resolution-sensitive, while extra frames at a degenerate
  baseline add nothing. Prefer `medium` (504×896) and accept a lower rate.
  Counter-consideration `[AGENT]`: these models work at ~512 on the long
  side, and 360×640 already exceeds that — so extra resolution buys
  *compression resilience* more than detail. Either way the ranking is
  **image quality > resolution > frame rate**, which is the opposite of
  what DAT's adaptive ladder delivers (§5.2).
- **Lightweight live + heavy stop-time?** **Yes, aggressively.** §6.3. Our
  measured ~1% CPU during capture is not headroom to spend live; it is
  headroom to spend at stop time, where there is no latency budget at all.
- **Integrate rather than reinvent?** Yes — but §6.5's ordering, chosen for
  this machine's toolchain rather than for published accuracy.

---

## 7. Where this contradicts existing project documents

Named explicitly rather than resolved silently, per Rule 17.

1. **`WORLD-BUILD.md`'s Candidate Pipeline is superseded in its mechanism,
   not its principles.** Its ordering (`keyframe selection → SLAM/SfM →
   ML depth → fusion`) is also `[REPO]` internally inconsistent — keyframe
   selection needs a motion signal, so it cannot precede pose estimation.
   The doc's own "Real-Time vs. Asynchronous Processing" section gets the
   order right. Its *principles* — hybrid constraints, confidence on every
   value, unknown space stays unknown, inference ≠ measurement — all
   survive intact and are strengthened by §6.3.
2. **`03-ROADMAP.md:123`'s "blocked on intrinsics" is now over-stated in
   one direction and under-stated in another.** Over-stated: the
   recommended architecture does not require intrinsics, and we can
   self-calibrate regardless. Under-stated: intrinsics was never the only
   missing input — footage and physical reference distances are also
   missing (§5.1), and **no real footage exists anywhere** (§5.1).
3. **The Passive Operation Requirement is in genuine tension with the
   stated V1 product experience — and I am not resolving it.** `[REPO]`
   `WORLD-BUILD.md:13-26` forbids the wearer being asked to perform a
   capture sequence, and states: *"Any future capability that depends on
   the wearer performing a deliberate scan action is not World Build — it
   is a different feature and must be designed and labeled as one."* The
   mission's V1 experience is *"start World Builder → walk around one room
   → observe it building → stop."* That is session-scoped and deliberate.
   It may well be the right V1 — but under the module's own rules it is a
   **different, separately-labelled feature**, and calling it World Build
   requires either amending `WORLD-BUILD.md` or naming the V1 something
   else. **This is a product decision for the user, listed in §14.**
4. **Sequencing.** `[REPO]` World Build is a **Phase 3** module, behind
   V1.0 (untriggered), V1.1 (**BLOCKED** on an unrecorded user ruling), and
   V1.2. Implementing it next jumps three milestones and collides with
   Rule 10. The §11 first slice is chosen partly because it is legitimate
   work *regardless* of how that sequencing is resolved.

---

## 8. Persistence architecture

Full design in the Track D synthesis; the decisions and their reasons:

### 8.1 Filesystem-first hybrid, not SQLite

Every read is a bulk whole-artifact read; every write is append-or-
replace-everything. That is precisely the workload where a row store buys
nothing. `[VERIFIED]` `np.load(mmap_mode="r")` gives the viewer partial and
streamed reads for free — the one capability the viewer most needs and the
one SQLite cannot provide. Named trigger to revisit: >~50 worlds, or
cross-world/vector anchor search — at which point SQLite becomes an
*index over* the store, never the store.

Layout: atomic JSON for small mutable metadata, append-only JSONL for the
live session journal, `.npy` struct-of-arrays for bulk geometry, immutable
numbered checkpoint directories, and a `HEAD.json` pointer.

### 8.2 The authoritative / derived split

The primary structural decision. **Authoritative** (cannot be regenerated):
world metadata, session metadata **including intrinsics and their
provenance**, keyframe images, the session journal, semantic anchors.
**Derived** (rebuildable): poses, map points, fused geometry, descriptors,
coverage grids, exports. Every derived byte may be deleted at any time —
worst case you lose CPU, never information.

**Correction to the current leaning:** *fused geometry is derived, not
authoritative.* If it is authoritative you can never change the mapper
without a data migration — and the first thing that will happen to a V1
monocular mapper is that it changes.

### 8.3 The pose contract, frozen now

`T_world_camera` (world-from-camera, so translation *is* camera position —
no inversion at any consumer); translation + unit quaternion stored
`[tx,ty,tz,qw,qx,qy,qz]`; **quaternion order `wxyz`**, declared in-file;
right-handed; **OpenCV camera axes** (+x right, +y down, +z forward),
because `cv2` is a core dependency and every calibration call already
assumes it; world axes = the first keyframe's camera axes; poses float64,
points float32; `up_axis: "unknown"` until a floor/gravity estimate exists
— declaring y-up with no IMU would be a fabricated fact.

**Every persisted pose block must be self-describing**, and a consumer that
reads a convention string it does not recognise must **refuse, not guess**.
A bare `[x,y,z]` under an ambiguous convention fails silently and
plausibly, and is unfixable once a thousand anchors exist.

### 8.4 Scale, and the gauge log — the highest-value decision

Monocular reconstruction leaves **7 degrees of freedom** free (3 rotation,
3 translation, 1 scale). Designing a scale field alone solves one seventh
of the problem.

**Rule A — geometry always in world units; scale is metadata.**
`scale: {state: "unknown"|"estimated"|"measured", meters_per_unit: null,
method, confidence, history: []}`. Applying a later metric estimate becomes
a one-field write instead of rewriting every point, pose, and anchor.
While `state == "unknown"`, **no consumer may print a distance in metres.**

**Rule B — `frame_revision` plus a Sim(3) gauge log.** `world.json` carries
a monotonic `frame_revision`, and for each increment the Sim(3) mapping
revision *N−1* coordinates into *N*. Every persisted coordinate — every
anchor, every export — is stamped with the revision it was expressed in,
and is brought current by composition rather than rewritten.

> This one mechanism covers scale, loop closure, bundle adjustment, gravity
> alignment, and second-session relocalisation. It costs roughly 40 lines
> and one integer **now**; retrofitted it costs a full migration plus the
> permanent loss of every anchor written before it existed, **because a
> gauge history you did not record cannot be reconstructed.**

### 8.5 Crash safety and concurrency — three verified Windows corrections

`[VERIFIED]` I re-ran these myself because they change the design:

```
dir fsync:              FAILS -> PermissionError [Errno 13]
replace over open dest: FAILS -> PermissionError [WinError 5]
unlink mmap'd file:     FAILS -> PermissionError [WinError 32]
npy mmap load:          works — (1000,3) float32
```

Consequences: `HEAD.json` must be opened, read, and **closed immediately**
by every reader — never held. Directory renames cannot be made durable, so
recovery must **validate** the checkpoint HEAD names and fall back to
`N−1` rather than trusting it. Checkpoint GC **must tolerate failure and
retry later** — "could not delete, a viewer has it mapped" is a normal
outcome, not an error.

Write order is deliberate: **keyframe blob first (fsync), journal line
second.** A journal line pointing at a missing file is corruption; a JPEG
with no journal line is a harmless orphan.

Concurrency is **snapshot isolation by immutability**: readers resolve a
checkpoint directory name and mmap it, taking no lock and blocking the
writer for zero time; the writer only ever writes a *new* checkpoint and
swaps the pointer. One writer per world, enforced by a lock file with
staleness detection.

### 8.6 Storage growth

Derived from `[REPO]` the measured 16,155-byte average JPEG at 360×640, at
1.5 keyframes/s:

| Artifact | Per minute |
|---|---|
| Keyframe JPEGs | **1.39 MB** |
| ORB-1000 descriptors | **4.81 MB** ⚠ *3.5× the images* |
| Keyframe poses | 23 KB |
| Depth maps, every frame, float32 | **633 MB** ❌ never persist |
| Map points (converging, not per-minute) | 3.05 MB at 200k points |

**≈1.5 MB/min with keyframes; a 10-minute room ≈ 25–35 MB; 100 worlds
≈ 3 GB.** Small enough to independently confirm §8.1. The real growth risk
is **descriptors, not images** — which is why descriptors are classified as
a regenerable cache.

### 8.7 What the current leaning gets wrong

Two omissions matter more than the corrections: **no gauge/revision log**
(§8.4 — without it, multi-session refinement is impossible and every anchor
written before the first loop closure becomes silently wrong), and **no
home for camera intrinsics** (without per-session intrinsics *and* their
provenance you cannot re-project, relocalise, or re-run the pipeline over
stored keyframes — the world becomes unrefinable, defeating the premise).

Also: per-frame trajectory should not be a first-class artifact (8× the
volume of keyframe poses, superseded by every optimisation pass);
"confidence" must split into **three** non-interchangeable things —
per-point geometric confidence, per-region coverage/known-ness, and scale
state — because conflating them produces exactly the failure
`WORLD-BUILD.md:111` forbids; and debug artifacts must be **structurally
excluded** from the world directory, not merely "optional", or a purge
leaves imagery-derived files behind.

---

## 9. Keyframe strategy

**Capture FPS ≠ mapping FPS**, and the gap is the whole design.

Select a keyframe on **measured information**, never a fixed interval:

- **median parallax** against the last keyframe — the primary criterion,
  targeting the ~300 ms-equivalent baseline our own data identifies (§4.2);
- **overlap ratio** — too little and correspondence fails, too much and the
  frame is redundant;
- **new coverage** — does it observe currently-unknown space;
- **sharpness gate** — variance of Laplacian, rejecting blurred candidates
  before they can become keyframes;
- **tracking confidence** — never promote a frame captured while tracking
  is degraded;
- **retrieval novelty** — for loop-closure candidacy.

`[REPO]` This is the V0.9.3 report's own recommendation (§4.2) carried
forward and extended: it called for keying off measured match counts rather
than a fixed interval, and the additions here are the parallax target
derived from the time axis, the sharpness gate, and retrieval novelty.
Target ~1–3 keyframes/s → ~100–300 keyframes for a five-minute room walk.

**What to measure to tune it:** keyframes accepted vs frames received;
distribution of achieved parallax at selection; fraction of keyframe pairs
that are rotation-dominant *after* selection (the number the policy exists
to minimise); inlier counts at the selected baselines; coverage growth per
keyframe; and the redundancy rate (keyframes whose removal does not change
the reconstruction).

---

## 10. Evaluation without ground truth

No laser scan is available, and none is needed. Ranked by information per
unit of effort:

1. **Loop-closure residual.** Walk a closed loop, return to the exact
   start, measure position error *before* the closure is applied. Free,
   repeatable, comparable across every architecture.
2. **Camera-height stability.** Fit the floor plane; camera height should
   be flat at ~1.5–1.7 m. Its drift *is* scale drift. Uniquely available
   to us because the camera is head-mounted. **Build this first.**
3. **Planarity / Manhattan residuals.** RMS point-to-plane deviation for
   floor, ceiling and walls, and deviation of wall-normal pairs from 90°.
   Measures *geometric* quality, which trajectory metrics miss entirely.
4. **One tape measure.** Two minutes of work validates global scale
   outright — worth more than any amount of self-consistency analysis.
5. **Held-out-keyframe consistency**; **cross-session repeatability**;
   **scale-drift ratio**; **coverage/completeness** (guards against
   "accurate but 30% of the room missing"); **robustness counters**
   (tracking-loss events, relocalisation success rate, false loop
   closures); **systems metrics** (peak VRAM, keyframes/s, time-to-first-
   geometry, stop-time duration).

### 10.1 FPS and resolution experiments

`[REPO]` **Correction to the mission's proposed design:** DAT frame rates
are a **discrete set {2, 7, 15, 24, 30}** and resolutions are only
`low`/`medium`/`high`. The proposed 6/12/20–24 FPS sweep is not
configurable on this hardware. The achievable design is:

- **Rate arm:** DAT `frameRate` ∈ {7, 15, 24} at fixed resolution, with the
  *delivered* rate recorded separately — the iOS stride and DAT's adaptive
  ladder both intervene, so requested ≠ delivered and only delivered counts.
- **Resolution arm:** `low` / `medium` / `high` at fixed frame rate,
  acknowledging the ladder may override and that this **must be detected
  and reported**, not assumed away.
- **Decisive derived arm, and the one I would run first:** hold capture
  fixed and vary the *mapping baseline* — pair keyframes at 1, 2, 3, 5, 8
  delivered-frame gaps. That isolates the variable §4.2 identifies as
  binding, and it needs no device reconfiguration at all.

Report §10's metrics 1–4 per configuration.

---

## 11. Prerequisites, and the exact first slice

### 11.1 Prerequisites, in order

1. **Restore CUDA torch** (§3.1) — `torch 2.13.0+cu130` /
   `torchvision 0.28.0+cu130`. Blocks every ML option. Verify with
   `scripts/world_builder_env_check.py`.
2. **Capture real Ray-Ban footage to disk** — none exists anywhere
   (§5.1). Blocks calibration, the V0.9.3 acceptance-gate re-run, and every
   architecture spike.
3. **Calibrate the camera** via ChArUco through the real pipeline (§5.4),
   and determine whether intrinsics scale across resolutions.
4. **Decide the sequencing and naming question** (§7.3, §7.4) — a user
   decision, not an engineering one.
5. **Resolve the module-contract gap** (§12) — World Builder cannot be an
   experiment under the current scalar, synchronous contract.
6. *Then*, and only then, time-boxed architecture spikes in §6.5's order.

**Not a prerequisite: the iOS FPS fix** (§6.7).

### 11.2 The exact first implementation slice

> **A session-recording path on the Tower, plus a ChArUco calibration
> harness. Not the mapper.**

Justification: it is the *only* work that unblocks all three of
calibration, the acceptance-gate re-run, and every architecture spike; it
needs no GPU, no new dependency, no registry generalisation, and no
resolution of the V1.1 or Phase-3 sequencing questions; and it is
independently useful even if the architecture recommendation is rejected.

Concretely:

1. An opt-in, explicitly started and stopped **dataset-recording session**
   that writes received frames plus their `seq` / `source_seq` / `tx_seq`
   and tower-receipt time to `data/` — implemented per
   `06-PRIVACY-DATA.md`'s Explicit Dataset-Recording Session rules
   (manually started/stopped, recording state visible, bounded, purgeable),
   **off by default**, with a real `purge()` that removes every artifact
   including temp files.
2. A **single choke point** — one `write_frame(bytes, meta)` function every
   captured pixel passes through — so any future redaction or exclusion
   policy is a change to one function rather than an archaeology exercise.
   *This decides no bystander policy;* it makes one implementable later.
3. An offline `scripts/calibrate_charuco.py` consuming a recorded session
   and emitting intrinsics, distortion, per-view reprojection RMS, the
   resolution solved at, and `source: "self_calibrated"`.
4. Tests in the existing style: CLI contract tests, and unit tests for the
   record/purge path mirroring `tests/test_object_memory_store.py`.

**Note the honest tension, and do not bury it:** this slice writes
photographs of the inside of the user's home to disk. `[REPO]`
`06-PRIVACY-DATA.md:37-39` permits retained raw imagery only where there is
an explicit justified need; there is one here (calibration and
reconstruction are impossible without it), and it must be **written down
per-feature**, not assumed. Any module that persists keyframes must declare
`retains_raw_imagery=True` — unlike both current CV modules, which
truthfully declare `False`. That flag flip is the visible signal that this
is a different privacy posture and should be reviewed as one.

---

## 12. Contract gaps that must be closed before any mapper

`[VERIFIED]` from source, and none of these is a small change:

- **`process()` is synchronous on the event loop.** `tower/routes/ws.py:55`
  calls `module_container.process(frame.raw_bytes)` directly inside the
  async WebSocket handler — no `to_thread`, no executor. Any blocking work
  stalls frame reception *and* result delivery.
- **There is no background execution path anywhere in `tower/`.** No worker
  thread, no task queue, no executor.
- **The result contract is scalar-only.** `ExperimentResult` is
  `(result_value: float, result_label: str, processing_ms: float,
  stage_ms: dict, mean_intensity: float|None)`, and `ws.py:97-106`
  serialises exactly those. **A pose, a pointmap, or a world delta cannot
  be returned over the wire without a protocol change.**
- **The wire frame carries no timestamp of any kind** —
  `REQUIRED_FIELDS = ("seq","width","height","format","data")`. Ordering
  authority is `source_seq`; the retention clock is tower-receipt time;
  neither is capture time, and any record must say so.
- **Stateful modules are fine** — `DepthEstimationModule` is stateful by
  design. State is not the gap; asynchrony and the result channel are.

`[INFERENCE]` Consequence: World Builder cannot be an *experiment* inside
the Experimental CV Lab. It needs its own module with its own result
channel — which is exactly the "second production module with real,
concrete requirements" that `03-ROADMAP.md` names as V1.0's trigger. **The
architecture work and the V1.0 trigger are the same event.**

---

## 13. Object Memory future contract

**Not wired. Not implemented.** Frozen field set, so anchors written later
still resolve:

| Field | Why it is irreversible |
|---|---|
| `world_id` — opaque `uuid4`, never derived from a name or content hash | the user will rename "Bedroom"; refinement changes content |
| `frame_revision` | without it the first loop closure silently invalidates every anchor, undetectably |
| `position` in **world units**, never metres | anchors in metres must be rewritten the day scale is estimated |
| `pose_convention` / `quaternion_order` / `handedness` / `camera_axes`, declared in-file | a bare `[x,y,z]` under an ambiguous convention fails silently and plausibly |
| `observed_at` + **`time_basis`** | there is no capture timestamp on the wire; Object Memory already solved this correctly and World Build must not regress it |
| `position_confidence` as a **label**, never a recomputed score | a later threshold change must not silently relabel history |
| frame key `(session_id, source_seq)`, never `source_seq` alone | `source_seq` resets per session, and its deltas are sampling, not elapsed time |

**Dangling references are a designed outcome, not a bug.** `[REPO]`
`06-PRIVACY-DATA.md:65` requires real deletion, so a purged world's ID must
genuinely stop resolving — tombstones would be soft delete by another name.
Consumers must degrade to "location unknown" rather than erroring.

---

## 14. Risks and unresolved decisions

**Risks:**

1. **`[VERIFIED]` No CUDA torch** — blocks every ML option today.
2. **`[VERIFIED]` No C++/CUDA toolchain** — blocks every research codebase
   needing kernel compilation; WSL2 is the escape hatch, at the cost of
   provisioning a full Linux CUDA environment.
3. **`[VERIFIED]` No real footage exists** — blocks calibration, the
   acceptance-gate re-run, and all spikes.
4. **Licensing.** MASt3R-SLAM and its checkpoints are CC BY-NC-SA;
   SuperPoint is non-commercial; ORB-SLAM3 is GPL-3.0. Fine for a research
   tower, fatal for a product. `[VERIFIED]` DA3's Apache-2.0 checkpoints
   are the clean path — a reason to weight option 1 in §6.5 more heavily
   than published accuracy alone would suggest.
5. **`[UNKNOWN]` VRAM for the recommended engines at our resolution.**
   Published numbers are from 24 GB cards. First thing to measure.
6. **`[REPO]` DAT's adaptive ladder degrades resolution first** — the axis
   that matters most — and cannot be overridden.
7. **Dataset-validity gate.** `[REPO]` V0.9.3's numbers may not be cited as
   positive validation until re-run on real DAT footage. The *architectural*
   conclusion in §6 is robust to this, since rotation-dominance in
   head-worn motion is independently established; the *numbers* are not.
8. **Privacy posture change.** Persisting keyframes is a materially
   different posture from anything shipped so far (§11.2, §8.7).

**Unresolved decisions — for the user, not for an agent:**

1. **Is the session-scoped V1 experience "World Build", or a separate
   feature?** (§7.3.) It cannot be both under the module's current rules.
2. **Roadmap sequencing** — World Build is Phase 3 behind V1.0/V1.1/V1.2,
   and V1.1 is blocked on an unrecorded user ruling (§7.4).
3. **Commercial intent**, which decides whether non-commercial engines are
   admissible at all (§14.4).
4. **Bystander/person policy** — deliberately not decided here. §11.2's
   choke point makes any policy implementable without deciding it now.
5. **Whether to install a build toolchain / provision WSL2 CUDA** — an
   environment change with real cost.

---

## 15. What this session produced

**Files created:**

- `scripts/world_builder_env_check.py` — read-only readiness diagnostic:
  GPU visibility vs. torch's ability to reach it, OpenCV geometry and
  calibration coverage, optional-library inventory, and go/no-go verdicts.
  Installs nothing, writes nothing, exits 0 unless `--strict`.
- `tests/test_world_builder_env_check_cli.py` — 4 CLI-contract tests.
- `docs/superpowers/research/2026-08-21-world-builder-readiness.md` — this
  document.

**Files modified:** `README.md` — repository-structure listing.

**Tests and diagnostics actually run:**

- `pytest -q` before any change → **210 passed, 3 skipped** (baseline
  confirmed).
- `pytest -q` after → **214 passed, 3 skipped**.
- `scripts/world_builder_env_check.py` in `text`, `json`, and `--strict`
  modes — verdicts: `gpu_visible` OK, `torch_cuda_usable` **NO**,
  `gpu_reachable_from_python` **NO**, `opencv_geometry` OK,
  `opencv_self_calibration` OK.
- ORB/decode/match benchmark at 360×640, 504×896, 720×1280 (§3.5).
- Windows filesystem behaviour probes (§8.5).
- Direct GPU/torch/OpenCV capability probes (§3.1, §3.3).

**Nothing was installed, upgraded, or removed. The iOS repository was not
modified.**

---

## 16. Prompt for the eventual World Builder implementation agent

> You are implementing the **first World Builder slice** on the Tower at
> `C:\Users\tvllo\Projects\GlassesTower`. Read
> `docs/superpowers/research/2026-08-21-world-builder-readiness.md` first,
> then `guidelines/docs/modules/WORLD-BUILD.md`,
> `guidelines/docs/06-PRIVACY-DATA.md`, and
> `guidelines/docs/02-DEVELOPMENT-RULES.md`.
>
> **You are NOT implementing the mapper.** The slice is §11.2: an opt-in,
> explicitly started and stopped dataset-recording path that persists
> received frames and their sequence/receipt metadata, plus an offline
> ChArUco calibration harness. Nothing else.
>
> Hard constraints, all verified — do not re-derive them:
> - torch is **CPU-only** (`2.13.0+cpu`) and there is **no C++/CUDA
>   toolchain** on this host. Do not write code that assumes CUDA.
> - OpenCV 5.0.0 has every calibration primitive you need, including
>   `cv2.aruco.CharucoBoard` / `CharucoDetector`. Add no new dependency.
>   Note `calibrateCameraCharuco` does **not** exist in OpenCV 5.
> - The wire frame carries **no timestamp**. Use `source_seq` for ordering
>   and tower-receipt time for retention, and label which is which.
> - `process()` is synchronous on the event loop and returns a scalar
>   `ExperimentResult`. Do not put blocking work behind it, and do not try
>   to return geometry through it.
> - **Never fabricate intrinsics.** If calibration has not run, intrinsics
>   are `null` with `source: "unknown"` — not a guess.
>
> Follow the repository's existing conventions: `tower/object_memory/` is
> the persistence precedent (append-only JSONL, atomic rewrite, real
> `purge()` that removes temp files too, confidence stored as a label).
> Route every persisted frame through a single `write_frame()` choke point.
> Declare `retains_raw_imagery=True` truthfully.
>
> Run the narrowest relevant tests, then the full suite. The baseline is
> **214 passed, 3 skipped**. Report results truthfully, including failures.
> Do not implement the mapper, do not wire Object Memory, do not touch the
> iOS repository, and do not resolve the sequencing or bystander questions
> in §14 — those are the user's.
