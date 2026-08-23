# Research — Foundations for a Passive Monocular World Builder: Next CV Experiments After Depth

Status: research only, produced 2026-08-20. Nothing here authorizes building
World Builder, selects a final model/library, or expands scope beyond
Experimental CV Lab (`docs/modules/EXPERIMENTAL-CV.md`). This document
supersedes an earlier partial draft at this same path — that draft's
strongest finding (the camera-intrinsics gap, see §6) is carried forward and
verified below; its proposed sequence is revised here against the fuller
question set this pass was asked to answer, including temporal depth
consistency, which the earlier draft did not address at all.

Grounded against a live web search pass (2026-08-20) for current model/
library names and capabilities — not recalled from training data alone. See
Sources at the end.

## 0. Where This Starts

V0.9.1 (`guidelines/docs/reports/V0.9.1-depth-cv-baseline-report.md`,
`docs/superpowers/specs/2026-08-20-v0.9.1-depth-cv-baseline-design.md`)
shipped the platform's first real CV/ML capability: a stateful
`DepthEstimationModule` running MiDaS-small monocular relative-depth
estimation, with a measured CPU baseline (~29.35ms avg round-trip) and CUDA
baseline (~20.18ms avg round-trip, ~31% faster) on synthetic 504x896 frames
on the Tower's RTX 5070. That is genuinely all that exists: no SLAM, no
visual odometry, no feature matching/tracking, no pose estimation, no
keyframe selection, no fusion, no point clouds, no persistent storage, no
viewer, and World Builder itself has not been started.

`docs/modules/WORLD-BUILD.md` already sketches a hybrid pipeline (RGB →
keyframe selection → visual SLAM/SfM → ML monocular depth → semantic
understanding → spatial fusion → persistent world representation) but
explicitly declines to commit to any technique, and explicitly says "do not
adopt every technique by default... select the smallest pipeline that
satisfies the project's actual course/research objective." This document
takes that instruction literally: it does not design World Builder, it
designs the smallest next measurable step(s).

## 1. Research Findings

### 1.1 Temporal depth consistency

Per-frame monocular depth (MiDaS included) is a well-documented source of
frame-to-frame flicker when applied naively to video: applying a
non-metric, single-image method to each frame of a sequence "naturally
produces temporally flickering depth maps, necessitating frame-by-frame
alignment or post-processing" — this is exactly the failure mode the
platform's own confidence model implicitly assumes exists (`WORLD-BUILD.md`
requires confidence to *rise* with repeated observation, which presupposes
repeated observations of the same point are comparable enough to accumulate,
not independently noisy each time). MiDaS specifically is named in current
literature as exhibiting this: "MiDaS generates flickering depth maps as
sequences are processed in a per-frame manner."

This is not a solved problem the platform can assume away by picking a
better model off the shelf — it is an active 2025-2026 research area in its
own right (Video Depth Anything / Online Video Depth Anything,
StableDPT, GemDepth all specifically target temporal stability that
single-image models lack), which means the realistic options for this
platform are (a) measure how bad naive flicker actually is on this
platform's own frame content and (b) apply a cheap post-hoc smoothing
step if it helps, not (c) adopt a dedicated video-depth model as a first
move — that would be exactly the kind of technique-adoption-before-
measurement Rule 17 and `01-SYSTEM-ARCHITECTURE.md`'s GPU philosophy warn
against.

**Smallest experiment:** reuse the already-shipped `DepthEstimationModule`
unmodified in its inference path, add a bounded, opt-in capture of the full
per-frame depth array (not just the existing scalar
`mean_relative_depth`) for a short recorded clip, and measure frame-to-frame
stability directly — see §3, Experiment A.

### 1.2 Scale ambiguity / scale recovery

MiDaS-small outputs relative (inverse) depth with no metric scale, which
`07-PLATFORM-CONSTRAINTS.md` Limitation 1 and `WORLD-BUILD.md` already both
name as the core hardware-driven gap. Current realistic options, confirmed
against current tools rather than recalled:

- **Learned metric-depth models.** "Depth Anything V2" (metric variants,
  indoor/outdoor checkpoints) and "Metric3D v2" are both current (2024-2025),
  actively-cited zero-shot metric monocular depth models. Comparative
  benchmarking found in this research pass: Depth Anything V2 reports the
  lowest MAE and relative error in one comparison, Metric3D reports the
  highest structural correlation in the same comparison; ZoeDepth (the
  earlier metric/relative hybrid) shows measurably worse degradation in
  unconstrained outdoor/wild settings in a separate wildlife-monitoring
  benchmark — i.e. ZoeDepth is the *previous* generation here, not the
  current reference point, which matters because it is the name most likely
  to surface first from older material. None of these produce
  centimeter-accurate output; they produce a materially better metric
  estimate than a relative-only model with no scale signal at all.
- **Ground-plane / known camera-height heuristic.** Classical, well-studied
  (multiple 2019-2021 papers on ground-plane-based absolute scale recovery
  for monocular VO still cited as the standard reference approach). No new
  model dependency — can be applied directly to the existing MiDaS-small
  output. Weakness specific to this platform: it assumes the floor is
  visible and the camera height is roughly known/constant, which is a much
  weaker assumption for a face-worn camera (usually pointed near eye level,
  not floorward) than for a robot or handheld-phone-scanning use case.
- **Known-object-size priors.** Classical, requires reliable object
  detection first (a dependency this platform does not yet have), and
  current literature notes it "shows limited robustness under scenes
  without known object classes" — a real, not hypothetical, weakness for
  a passive/undirected wearable feed where the object vocabulary in view
  is not controlled.
- **Multi-view triangulation from camera pose.** The "proper" classical
  answer, but it is gated entirely on visual odometry working first (§1.3)
  and on camera intrinsics existing (§6) — not available as a standalone
  first move.

**Smallest bounded experiment:** cross-check whichever of (a) a
ground-plane heuristic on the existing relative-depth output, or (b) a
metric-capable model swap, comes closest to a handful of physically-taped
real-world reference distances — see §3, Experiment D. This is
deliberately positioned last in the sequence because it is the one most
naturally informed by whether Experiment C (pose) succeeds.

### 1.3 Camera pose estimation / visual odometry

This is the least mature part of the platform and the highest-engineering-
risk item in this whole research pass, for two compounding reasons this
document treats as load-bearing findings, not asides:

1. **No camera intrinsics for the DAT stream exist anywhere in this
   repository as of this research pass** (verified: a grep for
   intrinsic/focal length/principal point/distortion/calibration across
   `guidelines/docs` returns nothing). Any geometric pose recovery
   (essential-matrix VO, SLAM, triangulation) needs focal length and
   principal point at minimum. This is a prerequisite fact-finding item —
   either from DAT documentation (`search_dat_docs`, per
   `02-DEVELOPMENT-RULES.md` Rule 4) or empirical checkerboard calibration
   against a real device — not a CV algorithm choice, and it blocks any
   real pose experiment, not just a convenient one.
2. **Realistic-vs-research-only is a genuine split in this space right
   now**, confirmed by this pass's search results:
   - **Classical feature-based VO** (OpenCV ORB/SIFT + essential-matrix
     recoverPose): zero new heavy dependency (OpenCV is already pinned),
     CPU-only, fully debuggable, well-documented failure modes (drift,
     scale-free, fails under low texture/motion blur — exactly the
     conditions DAT's adaptive bitrate ladder, `07-PLATFORM-CONSTRAINTS.md`
     Limitation 2, is documented to actually produce). This is the
     lowest-risk starting point precisely because its failure modes are
     already well understood in the literature, not because it is
     state-of-the-art.
   - **DPVO / DPV-SLAM** (Deep Patch Visual Odometry, Princeton) — current
     and actively benchmarked: published figures report DPVO at 60-120 FPS
     with a quarter of DROID-SLAM's memory, and DPV-SLAM (its full-SLAM
     extension with loop closure) at 1-3x real-time framerates using
     5-7GB VRAM — comfortably inside the RTX 5070's 12GB. This is a real,
     currently-viable candidate on this exact hardware class, not a
     GPU-cluster-only research artifact. The honest cost is integration
     risk: it is a research codebase with custom CUDA kernels and specific
     PyTorch/CUDA pinning, not a pip-installable package like MiDaS was —
     this platform already has one direct, recent lesson in exactly this
     shape of risk (the V0.9.1 amendment where an unpinned `torch.hub` ref
     and an undocumented `timm` requirement were discovered only during
     implementation), so a DPVO integration should be expected to surface
     similar friction, not less.
   - **NVIDIA cuVSLAM** — a current (2025), production-lineage,
     CUDA-accelerated classical VSLAM library from NVIDIA's robotics stack,
     explicitly supporting monocular mode alongside stereo/multi-camera.
     Its published real-time desktop benchmarks were run on an RTX 4090,
     not a 5070, and its deployment story (Isaac ROS, Jetson, Python
     bindings) is robotics/Linux-centric — Windows-native support is
     unconfirmed by this research pass and would need direct verification
     before this candidate could even be attempted, which is itself a
     reason it is not the first thing to try.
   - **ORB-SLAM3 / DROID-SLAM (full SLAM)** — both premature before a
     lighter VO experiment exists. ORB-SLAM3 is mature and well-documented
     but is a C++ codebase with a real Windows-build dependency chain
     (Pangolin, DBoW2, g2o) that does not fit "smallest bounded
     experiment." DROID-SLAM is accurate but reported around 8 FPS even on
     capable GPUs in published figures and is itself the heavier
     predecessor DPVO was built to outrun.

**Realistic framing for this platform specifically:** a live glasses stream
is closer to DPVO/cuVSLAM's target regime (real-time, single monocular
feed, consumer GPU) than to DROID-SLAM/ORB-SLAM3's, but none of the three
realistic candidates has been run on this Tower, on this data, or against
this camera's actual intrinsics yet — which is exactly what the next bounded
experiment needs to establish, not assume.

### 1.4 Feature detection / matching / optical flow — still worth a dedicated experiment?

Partially, and the honest answer is more precise than a flat yes/no. A
standalone "bake-off" comparing ORB vs. SIFT vs. LightGlue/SuperPoint in the
abstract is *not* worth a dedicated experiment on its own — whichever VO/
SLAM framework gets chosen already internally determines its matching
strategy (DPVO tracks patches via a learned recurrent network with no
separate matching stage at all; a classical VO pipeline pairs naturally with
ORB/SIFT + FLANN). Running matching in isolation from a VO decision would
measure a question nobody downstream is actually asking.

What *is* worth a small, cheap, standalone experiment is a narrower and more
fundamental question this platform genuinely does not know the answer to:
**does ordinary, undirected passive glasses motion produce frame pairs with
enough shared, trackable structure to support any multi-view geometry at
all** — independent of which VO framework eventually consumes it. Standard
VO/SLAM benchmark datasets (EuRoC, TUM-RGBD, TartanAir) are generally
captured with more deliberate, steady, or robot-mounted motion than a person
wearing glasses and looking around casually; nothing in this research
confirms that assumption transfers. Classical ORB + brute-force matching is
the cheapest possible instrument for this question (no GPU, no model
download, already-available OpenCV code) — see §3, Experiment B.

Optical flow (classical Lucas-Kanade/Farneback) is worth naming separately:
it is a plausible, very cheap keyframe-selection signal (large flow = motion
worth a keyframe, near-zero flow = redundant frame) and is more directly
useful to `WORLD-BUILD.md`'s stated live/lightweight tracking need than a
full VO stack — but it does not need its own bounded experiment; it is
cheap enough to fold into whichever VO/keyframe engineering work happens
next as an implementation detail, not a separate research question.

### 1.5 Keyframe selection

The standard, well-understood (not novel-research) approaches are genuinely
settled: motion-based thresholds (translation/rotation/time-since-last-
keyframe exceeding a configured bound) combined with covisibility-based
criteria (a new frame is kept when its shared-feature overlap with the
current keyframe drops below a threshold, indicating either new content or
occlusion). This is not a research gap — it is standard SLAM/VIO front-end
engineering, well documented across the keyframe-selection literature this
pass surveyed, and it maps directly onto `WORLD-BUILD.md`'s own framing
("keyframe selection reconciles passive operation with computational
cost").

Because it is well-understood engineering rather than an open question,
it does **not** warrant its own bounded Experimental CV Lab research
experiment in this sequence — the correct treatment is to apply standard
thresholds as an implementation detail riding on whatever pose/motion
signal Experiment C produces (or, more cheaply, on Experiment B's match
count / optical flow as a proxy), and measure the resulting keyframe rate
as a side output of that experiment rather than a fifth standalone
experiment. This keeps the sequence at 4 experiments instead of 5, and is
itself a Rule 17 judgment call: turning a settled engineering technique
into a dedicated research experiment would be unnecessary process weight.

### 1.6 Multi-view geometry / depth fusion / point clouds / TSDF / Gaussian Splatting

Honest relevance assessment, ordered from "legitimate near-future step" to
"currently impractical for this platform":

- **Multi-view geometry (triangulation from pose)** — legitimate and
  directly useful once pose exists (Experiment C), as a scale-recovery
  and depth-refinement source. Not itself a new bounded experiment; it is
  the mechanism Experiment D would use if pose is available.
- **TSDF/voxel fusion, point-cloud reconstruction** — legitimate,
  well-understood *next* steps once depth + pose + confidence all exist
  and are trustworthy — but starting one now would mean fusing outputs
  this document has not yet established are stable or scale-recoverable.
  This is not "wrong," it is simply **the actual start of World Builder
  itself**, not a bounded de-risking experiment, and is correctly out of
  scope for this sequence per the task's own boundary.
- **Gaussian Splatting (any monocular/RGB-only SLAM variant)** — currently
  impractical for this platform's use case, and this is worth stating
  plainly rather than deferring politely. Current (2025-2026) papers in
  this space (SplatMAP, MAGS-SLAM, Flash-Mono, RGB-only outdoor GS-SLAM,
  WildGS-SLAM, GaussianFlow SLAM) are still actively trying to solve their
  *own* basic problems: "real-time monocular SLAM fundamentally suffers
  from scale ambiguity and a lack of geometric self-correction," monocular
  3DGS SLAM "suffers from critical limitations in time efficiency,
  geometric accuracy, and multi-view consistency," and even the
  feed-forward variants built specifically to address the Train-from-
  Scratch cost problem are 2025 conference submissions, not shipped
  tooling. This is an open, moving research target, not a stable technique
  with off-the-shelf integration cost — and it solves a problem
  (photorealistic dense rendering) `WORLD-BUILD.md` never asks for; the
  module doc asks for relative geometry, confidence-scored structure, and
  "unknown stays unknown," not novel-view synthesis. **Verdict: do not
  evaluate in Experimental CV Lab; revisit only if a future milestone
  explicitly requires photorealistic rendering, which nothing in the
  current roadmap does.**

### 1.7 Confidence propagation

Real SLAM/depth-fusion systems represent per-region confidence as a
continuous quantity, not a fixed label, and this pass found consistent
current examples of the pattern: heteroscedastic Bayesian depth fusion
(weights inversely proportional to per-observation variance, solved via
sparse linear algebra), confidence-weighted TSDF fusion as an explicit
improvement over "traditional TSDF fusion uses simple uniformly weighted
averaging" (which does not account for differing per-observation noise),
and confidence-aware Gaussian-Splatting fusion (ConfidentSplat) doing the
same thing in that different representation. Learned covariance heads
(e.g. depth-covariance-function work, MAC-VO's metrics-aware covariance)
are also an active current direction — a model predicting its own
per-pixel uncertainty alongside its depth/pose output, rather than
uncertainty being bolted on afterward.

This maps cleanly onto `WORLD-BUILD.md`'s documented unknown/low/medium/high
levels: the real-systems pattern is to carry a continuous variance/weight
value through the pipeline and only bucket it into a discrete label
(unknown/low/medium/high) at the point something is displayed or consumed,
rather than discretizing early and losing information — exactly what
`07-PLATFORM-CONSTRAINTS.md` Core Principle 4 ("confidence must survive
the pipeline") already requires in the abstract. This is a design note for
whenever World Builder's actual confidence schema gets built, not a
bounded experiment in itself — none of the experiments below require a
confidence-propagation implementation to produce their result, though
Experiment D's "does confidence rise with repeated observation" check is a
first, minimal empirical test of the underlying assumption.

### 1.8 Loop closure, persistent map storage, incremental updates, coordinate systems, live viewer

One-line honest assessment each, per the task's request:

- **Loop closure** — firmly out of scope. It solves drift accumulated over
  large-scale, long-duration mapping; nothing in the proposed sequence runs
  long enough or covers enough area to accumulate drift worth closing.
- **Persistent map storage** — out of scope until there is a stable,
  scale-recovered, confidence-scored output worth storing; `WORLD-BUILD.md`
  already correctly leaves the storage format undecided for this reason.
- **Incremental map updates** — inherently part of World Builder itself,
  not a de-risking experiment; correctly deferred.
- **Coordinate systems** — not a research question, a convention (typically
  first-camera-pose-as-origin in standard VO/SLAM practice); needs to be
  picked when Experiment C is implemented, not researched separately.
- **Live viewer architecture** — `WORLD-BUILD.md` already explicitly says
  "do not implement the viewer now — it depends on a working reconstruction
  pipeline that does not yet exist"; this research agrees and adds nothing
  new here.

## 2. Challenging `WORLD-BUILD.md`'s Candidate Pipeline (Rule 17)

Per `02-DEVELOPMENT-RULES.md` Rule 17, two things in the existing docs are
worth naming explicitly rather than silently working around:

1. **`WORLD-BUILD.md`'s two pipeline sketches are in mild tension with each
   other**, and the tension matters for sequencing. The main "Candidate
   Pipeline" section orders keyframe selection *before* "visual SLAM /
   Structure-from-Motion." But keyframe selection standard practice (§1.5,
   above) is itself driven by a motion/pose signal — you need at least a
   lightweight tracking estimate to know whether a frame moved enough to be
   a keyframe. The document's own "Real-Time vs. Asynchronous Processing"
   section actually gets this right: `camera -> lightweight tracking /
   pose estimation -> keyframe selection`. This document's recommended
   sequence follows the second (correct) framing, not the first. This is
   not a case where the documented approach needs replacing — it is an
   internal inconsistency within the same module doc worth flagging so a
   future reader doesn't follow the first section literally.
2. **Nothing changes about the currently-deferred items** (semantic
   understanding, persistent storage, live viewer, loop closure) — the
   existing doc is already correctly conservative about these, and this
   research reinforces rather than challenges that. The one place this
   research actively pushes back is Gaussian Splatting (§1.6): the module
   doc's vague "later reconstruction/rendering techniques" placeholder
   should not be read as license to evaluate GS-SLAM soon — current
   literature shows it is not yet a stable, off-the-shelf technique for
   *anyone*, monocular or not.

## 3. The Finding: Recommended Experiment Sequence

Four bounded, individually-measurable experiments, in priority order. Each
follows `docs/modules/EXPERIMENTAL-CV.md`'s Success Criteria pattern
(hypothesis, dataset, metric, baseline, result). None of these build World
Builder; each answers one narrow, load-bearing question the later ones
depend on. Experiments A and B are independent of each other and could run
in either order or in parallel; C depends on B succeeding well enough to be
worth pursuing; D depends on both A and C (or falls back to a single-frame
heuristic if C stalls).

### Experiment A — `depth_temporal_consistency`

- **Hypothesis/question:** Naive per-frame MiDaS-small relative depth is
  too unstable frame-to-frame (under near-static camera content) to be
  usable as-is for anything that accumulates confidence over repeated
  observation, but a cheap post-hoc smoothing filter (exponential moving
  average or short temporal median) meaningfully reduces that instability
  without introducing unacceptable lag.
- **Candidate approaches to measure/compare** (not new models — this
  experiment is about processing the existing MiDaS-small output, not
  replacing it):
  1. **No smoothing (baseline)** — raw per-frame output, to establish the
     actual severity of flicker on this platform's own content, not
     assumed from the literature.
  2. **Exponential moving average / short temporal median filter** — the
     cheapest possible mitigation, zero new dependency, directly testable
     against (1).
  3. **A dedicated temporally-consistent depth model** (e.g., the
     Video-Depth-Anything family) — named here only as the escalation path
     if (2) proves insufficient; not attempted in this experiment, since
     adopting a new model before measuring whether the cheap fix already
     works would violate the same "smallest pipeline" discipline this
     whole document follows.
- **Success criterion:** measured frame-to-frame variance/instability of
  the raw output under near-static real camera content, and a measured,
  quantified reduction from applying (2) — reported as numbers, not a
  pass/fail claim, consistent with `EXPERIMENTAL-CV.md`'s "avoid declaring
  an approach better without a measurement." A concrete, useful outcome is
  either "(2) is sufficient" (proceed with a cheap smoothing stage) or
  "(2) is not sufficient" (a real, measured reason to consider (3) later —
  not something to guess at now).
- **Cost/risk:** **Low.** No new model dependency, reuses the shipped
  `DepthEstimationModule` inference path unmodified, requires only a
  bounded, opt-in capture of full per-frame depth arrays (not a wire-
  protocol change — the existing scalar-only wire shape stays as-is; this
  is an offline/dataset-recording-session analysis per
  `EXPERIMENTAL-CV.md`'s Data Capture provisions) and a small analysis
  script. Main risk is representativeness: a mock-device or phone-camera
  clip will not reproduce real Ray-Ban Meta optics/motion-blur/compression
  characteristics (`07-PLATFORM-CONSTRAINTS.md` Limitation 12) — flag this
  the same way the V0.9.1 report flagged its synthetic-frame limitation,
  don't overclaim from it.

### Experiment B — `feature_trackability`

- **Hypothesis/question:** Consecutive frames captured during ordinary,
  undirected motion (not a deliberate scan) share enough classical
  keypoints, at a high enough geometrically-verified inlier ratio, to make
  any multi-view geometry (VO, later SLAM, triangulation-based scale
  recovery) worth attempting at all.
- **Candidate approaches** (this experiment is deliberately about whether
  trackable structure exists, not about picking a final matcher — see
  §1.4):
  1. **ORB + brute-force/FLANN matching (OpenCV, classical)** — the
     primary candidate: zero new dependency, CPU-only, already the
     platform's de facto standard for "cheap classical CV" per
     `EXPERIMENTAL-CV.md`'s own candidate-experiment list.
  2. **SIFT** — a cheap second data point only if ORB's results are
     ambiguous; same integration cost, generally better under
     scale/rotation change.
  3. **A learned detector (SuperPoint-class)** — named only as the
     escalation path if classical detectors clearly fail under real
     motion blur/low light; not attempted in this experiment.
- **Success criterion:** on a short (~10-30s) real (not purely synthetic)
  test clip, measure keypoint count per frame, match count and
  RANSAC-verified inlier ratio between frame *n* and *n+k* for a few small
  *k*, and per-frame cost. Success = a majority of adjacent-frame pairs
  retain a usable inlier count (a concrete number set from the actual
  data, not pre-assumed here) at a cost well under the existing depth
  experiment's ~20-30ms budget. Failure = matches collapse quickly under
  realistic head motion — a real, measured, useful finding that passive
  glasses motion is a harder regime than standard VO benchmark datasets,
  which would directly deprioritize Experiment C rather than let it
  proceed on an untested assumption.
- **Cost/risk:** **Low.** Same shape as the temporal-depth experiment:
  no new model, near-trivial OpenCV integration. Primary limitation:
  synthetic frames (as used in `scripts/depth_benchmark.py`) cannot
  exercise this hypothesis at all, since they have no real inter-frame
  motion — this experiment specifically needs at-minimum a webcam-sourced
  or mock-device-with-motion clip, flagged explicitly as a dataset
  requirement, not an afterthought.

### Experiment C — `monocular_pose_feasibility`

- **Hypothesis/question:** Given Experiment B's matches, a real-time-
  viable monocular pose/VO approach can produce a qualitatively plausible
  relative trajectory (no wild divergence, roughly matches a coarsely
  known simple test path) on the Tower's RTX 5070, within a frame-
  processing budget compatible with the platform's ~15 FPS target —
  without requiring IMU data DAT does not currently expose.
- **Candidate approaches:**
  1. **Classical monocular VO** (OpenCV essential-matrix `recoverPose` +
     frame-to-frame pose chaining, built directly on Experiment B's
     matches) — lowest integration risk, no new heavy dependency, but
     drift-prone and scale-free by construction; the natural first attempt
     precisely because its failure modes are already well understood.
  2. **DPVO / DPV-SLAM** — currently viable on this hardware class
     (published 60-120 FPS, 5-7GB VRAM, fits the 5070's 12GB) but carries
     real research-codebase integration risk (custom CUDA kernels,
     specific PyTorch/CUDA pinning) — the same shape of risk V0.9.1 already
     hit once with MiDaS's undocumented `timm` requirement and floating
     hub ref; expect similar friction, budget for it, don't treat DPVO as
     a drop-in.
  3. **NVIDIA cuVSLAM** — current, CUDA-native, monocular-capable, but its
     published benchmarks and deployment story are robotics/Linux-centric;
     Windows-native viability is unconfirmed and must be verified before
     this candidate is attempted at all, not assumed from its RTX-4090
     desktop numbers.
- **Success criterion:** trajectory shape is recognizably correct (no
  gross divergence) for a short session against a coarsely-known real test
  path (e.g., "walked ~5m straight, turned ~90°, walked ~3m," hand-recorded
  during capture, not precision ground truth) — explicitly not a metric-
  accuracy claim, a plausibility/robustness gate. Failure = the pose chain
  diverges or degrades unusably fast, a concrete finding that would argue
  for relying more on per-frame depth + geometric priors than on full VO,
  rather than investing further in this direction.
- **Cost/risk:** **Medium-High — the riskiest experiment in this
  sequence,** and arguably the single most important result in it (see
  Summary, below). It is the first real pose/geometry code in the
  platform, the first plausible candidate for a new heavier ML dependency,
  and the most likely of the four to reveal that naturally-worn passive
  footage lacks the parallax/texture/stability classical or even current
  learned VO expects. **Hard prerequisite:** camera intrinsics for the DAT
  stream must be established first (§6) — this experiment cannot produce a
  meaningful pose estimate without them, only a "does the code run" check.

### Experiment D — `depth_scale_fusion`

- **Hypothesis/question:** Combining Experiment A's (stabilized) relative
  depth with a scale signal — either Experiment C's trajectory over a
  known real-world distance, or a single-frame ground-plane/metric-model
  fallback if C did not succeed — produces a distance estimate whose error
  against a hand-measured real distance is small enough to be "useful for
  non-safety-critical purposes" per `07-PLATFORM-CONSTRAINTS.md`
  Limitation 1 (never claimed as centimeter-accurate, which the platform
  docs already rule out).
- **Candidate approaches:**
  1. **Ground-plane / camera-height heuristic** on Experiment A's
     stabilized output — no new model dependency, cheapest, but weaker for
     a face-worn camera that is not reliably floor-pointed.
  2. **Metric-capable model swap** (Depth Anything V2 metric variant, or
     Metric3D v2) in place of MiDaS-small — currently the strongest
     zero-shot metric accuracy in published comparisons found this pass,
     at the cost of a new hub dependency with the same reproducibility
     risk class already encountered once in V0.9.1 (pin the exact ref,
     don't float on a default branch).
  3. **Multi-view triangulation from Experiment C's pose** — the
     "textbook-correct" approach, but entirely contingent on C having
     succeeded and on intrinsics existing; not usable as a fallback if C
     stalled.
- **Success criterion:** measured absolute/relative error against 5-10
  physically-measured real-world reference distances in a controlled
  indoor test space, reported with confidence per `WORLD-BUILD.md`'s
  unknown/low/medium/high levels — and, separately, whether confidence
  measurably improves across repeated observations of the same point, a
  direct empirical test of an assumption `WORLD-BUILD.md` currently states
  but has never measured. No error-band threshold is pre-committed here —
  deciding what error counts as "useful" is a product/UX judgment this
  research does not make.
- **Cost/risk:** **Medium.** Needs a physical ground-truth setup (cheap,
  no special equipment) and, if candidate (2) is chosen, a new model
  dependency with known integration risk. This is the experiment whose
  result most directly answers the milestone's actual question: how close
  does the cheapest available fusion of what already works get to a usable
  approximate distance, under real passive-use conditions — not a
  yes/no on SLAM quality in the abstract, a measured number.

## 4. Explicit Non-Goals for This Sequence

Not attempted by any experiment above, and not required to get a viability
answer: semantic/object understanding, persistent map storage, incremental
map updates, loop closure, TSDF/voxel fusion, point-cloud reconstruction,
Gaussian Splatting in any form, a live viewer, ORB-SLAM3/DROID-SLAM (full
SLAM systems), or a generalized "stateful experiment" framework beyond what
V0.9.1 already built. All remain correctly deferred per the existing docs;
none of them is required to answer "is passive monocular World Builder
viable."

## 5. Summary

Experiment C (`monocular_pose_feasibility`) is the single biggest unknown
in this whole sequence and, honestly, in the platform's path toward World
Builder generally: everything about multi-view scale recovery, keyframe
motion criteria, and eventual spatial fusion assumes pose is obtainable at
real-time-adjacent rates from ordinary, undirected passive glasses motion —
and nothing in the current codebase or this research pass has tested that
assumption against real camera intrinsics or real passive-use footage.
Experiments A and B are cheap, low-risk, and worth running regardless of
Experiment C's eventual outcome, since they answer real questions (does
depth need smoothing; does passive motion produce trackable structure at
all) independent of which VO approach — or whether any VO approach — turns
out to be viable.

## 6. Open Blockers / Prerequisites

- **Camera intrinsics for the DAT stream are not established anywhere in
  this repository** (verified by grep across `guidelines/docs` for
  intrinsic/focal length/principal point/distortion/calibration — no
  matches). This blocks Experiment C and the triangulation path of
  Experiment D. Resolving it requires either a `search_dat_docs` answer
  (per `02-DEVELOPMENT-RULES.md` Rule 4) or empirical calibration against
  a real device — not decided here.
- **No technique named as a candidate above has been run on this Tower
  yet, except MiDaS-small depth.** Every latency/VRAM figure cited for
  ORB, DPVO, cuVSLAM, Depth Anything V2, and Metric3D v2 above comes from
  published literature on other hardware (RTX 3060/4090 and various
  robotics/Jetson targets in different papers), not this platform's RTX
  5070. Per `01-SYSTEM-ARCHITECTURE.md`'s correctness → instrument →
  profile → accelerate philosophy, none of these numbers are a promise —
  they exist only to rank which bounded experiment to try first.
- **Whether passive glasses motion resembles standard VO/SLAM benchmark
  motion patterns is unknown** and is precisely what Experiment B is
  designed to find out — every VO/SLAM figure cited above is only as
  relevant as that assumption holds.

## Sources

Web search pass conducted 2026-08-20 to ground technique names/claims
against current tools rather than recalled model names:

- MiDaS temporal flicker / video depth consistency: StableDPT
  (arxiv.org/html/2601.02793v1), GemDepth (arxiv.org/html/2605.10525),
  Online Video Depth Anything (arxiv.org/html/2510.09182v1)
- Metric depth model comparison: Depth Anything V2
  (arxiv.org/html/2406.09414v2), Metric3D v2
  (github.com/YvanYin/Metric3D, arxiv.org/html/2404.15506v4),
  wildlife-setting metric-depth benchmark (arxiv.org/html/2510.04723v1)
- DPVO / DPV-SLAM: arxiv.org/abs/2408.01654 (Deep Patch Visual SLAM),
  princeton-vl/DPVO, NeurIPS DPVO paper
- ORB-SLAM3: github.com/UZ-SLAMLab/ORB_SLAM3,
  ieeexplore.ieee.org/document/9440682
- cuVSLAM: arxiv.org/abs/2506.04359, arxiv.org/html/2506.04359v2
- LightGlue / SuperPoint vs. classical matching:
  github.com/cvg/lightglue, arxiv.org/html/2505.17973v1
- Gaussian Splatting SLAM limitations: SplatMAP
  (dl.acm.org/doi/full/10.1145/3728310), MAGS-SLAM
  (arxiv.org/pdf/2605.10760), Flash-Mono (openreview.net/forum?id=nv3q3crc5D),
  RGB-only outdoor GS-SLAM (arxiv.org/pdf/2502.15633)
- Keyframe selection standards: MDPI systematic review
  (mdpi.com/2218-6581/12/3/88), keyframe/inlier selection for visual SLAM
  (researchgate.net/publication/261320745)
- Confidence/uncertainty propagation: BayesFusion-SDF
  (arxiv.org/html/2602.19697), ConfidentSplat (arxiv.org/pdf/2509.16863),
  probabilistic volumetric fusion for dense monocular SLAM
  (ar5iv.labs.arxiv.org/html/2210.01276), depth covariance function
  (CVPR 2023, Dexheimer & Davison)
- Ground-plane / known-object-size scale recovery: ground-plane-based
  absolute scale estimation (arxiv.org/abs/1903.00912), plane-geometry
  scale recovery (researchgate.net/publication/348563085)
- RTX 5070 hardware specs: wccftech.com roundup, pcgamesn.com guide
