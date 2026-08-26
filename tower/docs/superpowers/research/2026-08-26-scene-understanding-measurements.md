# Scene Understanding: two design claims, measured on the real corpus

**Date:** 2026-08-26
**Status:** research only. No production code was modified, nothing was installed,
nothing was committed. Every number below was produced by running the repo's own
`TorchvisionPoseEstimator`, `TorchvisionDetector`, `iter_capture_frames` and
calibrated intrinsics against `tower/data/captures/`.

**Host:** RTX 5070 (Blackwell, sm_120, 12,227 MB), torch `2.13.0+cu132`,
torchvision `0.28.0+cu132`, cv2 5.0.0.
**Corpus:** 18 captures, 9,199 frames, 360×640 portrait JPEG.

---

## 0. Summary

- **Coarse orientation on CUDA costs 43.4 ms warm median, not 798 ms.** That is a
  **22.0× speedup** over the same model on this host's CPU, which — measured on
  the same real frames — is **956.4 ms**, worse than either number the docs
  record.
- **All three documented figures are wrong.** 798 ms, 744 ms, and the "2.5× the
  ~300 ms interval" ratio. The corpus's own journals put the delivered frame
  interval at **83.5 ms (12.0 fps)**, not 300 ms. On CPU orientation is 11.5× the
  real interval; on CUDA it is 0.52×.
- **The cadence survives; its constant does not.** 2.0 s was derived from a cost
  that no longer exists on the GPU path, but CPU remains a supported device at
  956 ms, so the staleness bookkeeping is still load-bearing there.
- **The depth refusal stands — and the reasoning behind it is weaker than the
  refusal deserves.** The "6–8% flicker" number was measured on EPIC-KITCHENS
  kitchen footage at 128×256, not on synthetic input and not on this platform's
  camera, and it measures per-pixel *value* change, never the *ordering* flips
  the refusal claims. The refusal names that ordering experiment as still-to-run.
  It has still not been run for MiDaS.
- **I ran it for the depth-free alternative instead.** Two-view parallax with the
  repo's real calibration, on real consecutive corpus frames, reverses the depth
  ordering of two image regions **15–25% of the time**, and — decisively — **the
  flip rate barely falls as the two regions get further apart**: even at a >3×
  depth separation it is 15.8%. There is no threshold that rescues it. Yield is
  also only 23–34% of frame pairs.
- **Existing World Builder geometry cannot answer it either**, for a reason not
  in the brief's list: `points.json` persists no 2D↔3D association, so no
  reconstructed point can be attributed to a detection box. Seven of eight
  derived sessions on disk contain zero points.

---

## 1. Claim 1 — coarse orientation's cost

### 1.1 What the repo says, and how many different things it says

| Source | Figure |
|---|---|
| `guidelines/docs/modules/SCENE-UNDERSTANDING.md:13,103-105` | **798 ms**, "24× the detector", "2.5× the ~300 ms interval" |
| `docs/contracts/IOS-TO-TOWER-RECONCILIATION.md:175` | **798 ms**, 24×, 2.5× |
| `docs/superpowers/plans/2026-08-22-scene-understanding-v1.md:108-110` | **744 ms**, 23×, 2.5× |
| `tower/scene/orientation.py:25,209`, `engine.py:4,8,23`, `query.py:12,145`, `records.py:123`, `scripts/scene_session.py:5,84` | **744 ms** |

All were measured on CPU with synthetic input. The named unblocker, in the
module docstring itself, is "a restored CUDA build". That build exists on this
host and was verified live: `torch.cuda.is_available()` is True,
`get_device_properties(0)` reports the RTX 5070 at sm_120 with 12,226 MB.

### 1.2 Method

`scripts/capture_corpus_benchmark.py`'s `iter_capture_frames` was reused for
corpus iteration, as instructed. Frames were JPEG-decoded into memory *before*
timing, so decode is excluded and the number is model cost alone.
`torch.cuda.synchronize()` brackets every CUDA call. The first five calls are
dropped from the warm statistics. CUDA sampled 50 frames/capture (754 frames);
CPU sampled 12 frames/capture (204 frames), which at ~1 s a frame is already
3.4 minutes of wall clock.

### 1.3 `keypointrcnn_resnet50_fpn`, real frames

| | **CUDA** | **CPU** |
|---|---|---|
| frames timed | 754 | 204 |
| model load | 1547.9 ms | 1331.0 ms |
| first call (cold kernels) | 623.5 ms | 922.6 ms |
| warm **median** | **43.4 ms** | **956.4 ms** |
| warm mean | 43.8 ms | 977.5 ms |
| warm **p95** | **50.6 ms** | **1112.8 ms** |
| warm p99 | 57.4 ms | 1167.0 ms |
| warm min / max | 35.1 / 104.7 ms | 731.3 / 1208.1 ms |

**22.0× on the warm median.** Note the CPU column: on *real* frames the CPU cost
is 956 ms, meaningfully worse than the 744 or 798 ms the docs record from
synthetic input. Both documented numbers were optimistic.

The first call costs 623.5 ms on CUDA — 14× the warm median — because kernels
are being compiled and autotuned. Any consumer that measures orientation by
timing one call will get a number that is wrong by an order of magnitude in the
same direction the docs are wrong.

### 1.4 VRAM

| | MB |
|---|---|
| weights resident after `load()` | 229.8 |
| peak allocated during inference | 737.1 |
| peak reserved by the caching allocator | 988.0 |
| whole-device in use at peak | 2,279.6 of 12,226.6 |

Under 1 GB reserved on a 12 GB card. VRAM is not a constraint for this model at
360×640, and would not become one until several models were co-resident.

### 1.5 How it scales with the number of people

CUDA, warm medians, bucketed by how many people the model returned above its
0.7 score threshold:

| people in frame | frames | median ms | mean ms |
|---|---|---|---|
| 0 | 145 | 40.0 | 42.2 |
| 1 | 247 | 43.4 | 43.9 |
| 2 | 194 | 43.6 | 44.2 |
| 3 | 136 | 43.8 | 44.6 |
| 4 | 26 | 44.3 | 45.1 |
| 5 | 1 | 51.6 | 51.6 |

**Essentially flat: ~1 ms per additional person**, +4.3 ms across the whole
range from zero to four. The cost is the ResNet-50 + FPN backbone, which runs
once regardless; the keypoint head is per-proposal and cheap. CPU shows the same
shape buried in noise (921 / 999 / 949 / 963 / 992 ms for 0–4 people). A crowded
room does not change this budget.

### 1.6 The detector, on the same frames — and the ratio that actually matters

`ssdlite320_mobilenet_v3_large`, identical harness:

| | CUDA | CPU |
|---|---|---|
| warm median | **30.4 ms** | **32.9 ms** |
| warm p95 | 35.8 ms | 42.1 ms |
| first call | 361.4 ms | 27.2 ms |
| load | 1134.9 ms | 65.5 ms |

**The detector gets almost nothing from CUDA** — 8% — because MobileNetV3 at an
internal 320 px is bound by kernel-launch overhead, not arithmetic. So the ratio
the docs lean on inverts completely:

| | detector | orientation | ratio |
|---|---|---|---|
| **CPU** | 32.9 ms | 956.4 ms | **29.1×** |
| **CUDA** | 30.4 ms | 43.4 ms | **1.43×** |

The documented "24× the detector" was roughly right for CPU and is off by 20× for
CUDA.

### 1.7 The delivered frame interval is 83.5 ms, not 300 ms

Measured from the corpus's own `frames.jsonl` receipt timestamps, across the 14
captures with more than 50 frames:

```
CORPUS median inter-frame gap  83.5 ms   =  12.0 fps
```

Per capture the medians run 68.5–87.6 ms (11.4–14.6 fps). Three tiny captures
(15–19 frames) show 4–6 ms gaps and are burst/replay artefacts, excluded.

This matters because every ratio in the docs is stated against "the ~300 ms
interval the glasses deliver", and the corpus contradicts that by 3.6×. That
figure is also inconsistent with the repo's own
`docs/superpowers/research/2026-08-21-world-builder-readiness.md`, which already
uses "a delivered 10–12 FPS, consecutive frames sit 83–100 ms apart".

Restating the cost against the real interval:

| | orientation | × the 83.5 ms interval |
|---|---|---|
| CPU | 956.4 ms | **11.5×** |
| CUDA | 43.4 ms | **0.52×** |

The docs said 2.5×. On CPU the true figure is 4.6× worse than documented; on
CUDA it is 4.8× better.

### 1.8 Does CUDA change the cadence decision?

**It changes the constant, not the structure — and it removes most of the force
from the staleness argument, but not all of it.**

The affirmative case for dropping the cadence. Detector plus orientation on CUDA
is **73.8 ms at the median** against an 83.5 ms budget. Per-frame orientation
would, at the median, fit. `ORIENTATION_INTERVAL_S = 2.0` is justified in
`engine.py:23-27` entirely by cost — *"At 744 ms a call, anything more frequent
than this spends more time estimating facing than observing the room"* — and that
sentence is now false by a factor of 17.

The case against dropping it. At p95 the same pair costs **86.4 ms**, which
overruns the interval. A per-frame design would run at an 88% duty cycle at the
median with no headroom, on a GPU that is not exclusively Scene Understanding's,
and would still fall behind on the tail. There is also no accuracy benefit on
offer: a person's facing does not change in 83 ms, so the marginal frames buy
nothing the module can use.

So the cadence should stay and its constant should drop by roughly an order of
magnitude — **~250 ms (3 frames) rather than 2.0 s** — which is affordable at a
~35% duty cycle and puts every estimate's age inside a single tracker
confirmation window. That is a one-constant change, not a redesign.

On the staleness bookkeeping specifically: `age_seconds`, `age_estimate()` and
`MAX_ESTIMATE_AGE_S = 6.0` are **not** made unnecessary by CUDA, for two reasons
that have nothing to do with 43 ms.

1. **CPU is still a supported device**, at 956 ms — 11.5× the frame interval.
   `TorchvisionPoseEstimator` defaults to `device="cpu"`. On that path every word
   of the original argument still holds. Removing the age field would make the
   module correct on one device and silently lying on the other.
2. **`age_estimate()` also carries a correctness guard unrelated to cost.** Its
   docstring records a real bug: a backward NTP step produced a negative age,
   which pushed the expiry deadline further into the future. The `max(seconds,
   0.0)` clamp is protecting against clock behaviour, not against latency.

**Recommendation, and the honest shape of it.** Replace the three conflicting
constants with device-conditioned measured ones; drop the cadence constant to
~250 ms when the estimator is on CUDA; keep the age field. What should *not*
survive is the claim that this is an open question blocked on a CUDA build. It is
measured, and the answer is 43.4 ms.

### 1.9 The caveat, stated plainly

**This measures cost on realistic input. It does not measure orientation
accuracy, and cannot on this machine.**

`docs/superpowers/research/2026-08-26-real-corpus-first-measurement.md` established
that the corpus's `person` detections are almost certainly the wearer's own torso:
median box area 40% of frame, bottom edge 0.981, 59% touching a frame edge. I
re-measured the same geometry for the keypoint model specifically, over 404 real
frames:

| keypointrcnn person boxes, 404 frames | |
|---|---|
| boxes above 0.7 | 667 |
| frames with ≥1 person | 346 / 404 |
| mean people per frame | 1.65 |
| median box area | **21.5% of frame** |
| median box bottom edge | **0.939** of frame height |
| median box width | 61.6% of frame width |
| fraction touching a frame edge | **43%** |

Milder than the detector's figures but the same shape: large, bottom-anchored,
frequently clipped by the frame. That is what the wearer's own body looks like to
a head-mounted camera. There is no bystander footage on this machine, so the
keypoint-visibility heuristic in `facing_from_keypoints` remains **entirely
unvalidated against ground truth**. Nothing here should be read as evidence that
orientation works — only that its cost, on input with the real corpus's blur,
exposure hunting and JPEG artefacts, is 43 ms.

### 1.10 Reproduction

```
tower/.venv/Scripts/python.exe <scratch>/orient_bench.py --device cuda --per-capture-limit 50 --out cuda.json
tower/.venv/Scripts/python.exe <scratch>/orient_bench.py --device cpu  --per-capture-limit 12 --out cpu.json
tower/.venv/Scripts/python.exe <scratch>/detector_and_boxes.py --per-capture-limit 25 --out boxes.json
```

---

## 2. Claim 2 — the depth refusal

### 2.1 What was actually measured, and on what

The refusal lives in `tower/tower/scene/state.py:42-71`.

**`in_front_of` / `behind`** (`state.py:42-50`): *"needs depth. The only depth
available is MiDaS relative inverse depth, measured by this project at 6-8%
temporal flicker; ordering two boxes by a flickering field gives a relation that
inverts frame to frame."*

Provenance, traced to source: World Builder Experiment 1, harness
`scripts/depth_temporal_consistency.py`, recorded in
`docs/superpowers/research/2026-08-21-world-builder-readiness.md:250-262` and
`guidelines/docs/reports/2026-08-20-weekend-autonomous-run-report.md:54-59`.

> Experiment 1, **EPIC-KITCHENS `P01_107`**, 150 frames at effective 16.67 fps,
> **analysis grid 128×256**, CPU. Raw frame-to-frame depth flicker `mad_mean`
> **0.0633–0.0761** across three independent normalizers — 6–8% of full depth
> range between consecutive frames, **p95 regions 19–23%**.

**Three corrections to the brief's framing, in the repo's favour and against it.**

1. **It was not synthetic.** It was a real public dataset video — kitchen task
   footage from a head-mounted camera. That is *better* evidence than "synthetic",
   and the brief understates it.
2. **It was not this platform's camera, and the repo says so loudly.** The
   harness docstring: *"results from a public dataset clip are feasibility
   evidence, NOT physical-glasses/DAT validation"*, and the V0.9.3 acceptance
   gate *"forbids citing any of these numbers as positive validation for the
   platform's own camera until they are re-run on real DAT footage."* The
   refusal in `state.py` cites them anyway. The analysis grid was also ~1/7 the
   linear resolution of the platform budget, and the report calls its own
   figures **a lower bound**.
3. **It never measured ordering at all.** `mad_mean` is mean absolute per-pixel
   change in a normalized depth field. "Would invert the ordering" is an
   inference from that, not a measurement of it — and the refusal text says so
   itself, naming the experiment that would settle it: *"run the depth
   experiment over a scene with two objects at a known separation and measure how
   often the ordering flips."* **That experiment has never been run for MiDaS.**

**`nearer_than_same_class`** (`state.py:62-71`): the brief characterizes this one
correctly. The text is explicit that *"an adversarial review produced a
counterexample"* — two chairs at the same distance, 60000 px face-on against
24000 px edge-on, ratio 2.5 against a 1.5 threshold. Those are two numbers
written down in review. No image was measured. It is a sound argument from
geometry — nothing in a 2-D box separates shape from distance — but it is
reasoning, not data, and the module withdrew a shipped feature on it.

### 2.2 What it would cost to test MiDaS properly

**Missing: `timm`, and nothing else.** Confirmed empirically (no install
attempted):

```
torch.hub.load('intel-isl/MiDaS', 'MiDaS_small')
  -> ModuleNotFoundError: No module named 'timm'
```

**And the requirement is structural, not model-driven — which makes it cheaper
than it looks.** `MiDaS_small` builds `MidasNet_small` on an `efficientnet_lite3`
backbone sourced from the **already-cached** `rwightman/gen-efficientnet-pytorch`
hub repo (`hubconf.py:283-300`). It uses no timm layer. timm is dragged in only
because `midas/blocks.py` imports `midas/backbones/beit.py` at module level, and
that file does `import timm` for the BEiT/Swin/LeViT DPT backbones the small
model never touches.

**Size.** `timm` is a pure-Python wheel (~2–3 MB) plus `huggingface_hub` and
`safetensors`; `PyYAML` 6.0.3 is already installed. `pyproject.toml:18-24` warns
that `httpx` must not be uninstalled because huggingface_hub needs it. **No model
download is required** — the weights are already on disk:

```
~/.cache/torch/hub/checkpoints/midas_v21_small_256.pt          85.8 MB
~/.cache/torch/hub/checkpoints/tf_efficientnet_lite3-*.pth     33.2 MB
```

**One correction to the brief: `scipy` IS installed, at 1.18.1.** Only `timm` is
missing. (`docs/superpowers/research/2026-08-26-cross-segment-registration.md`
independently concludes scipy is not *needed* for registration, which may be
where the impression came from.)

**What a real test needs.**

1. **Consecutive real frames** — the corpus has 9,199 at a measured 12.0 fps, and
   `iter_capture_frames` already walks them in order.
2. **The ordering metric, not the value metric.** For each pair of regions,
   compute the sign of their depth difference; count sign flips between
   consecutive frames; report flips per opportunity.
3. **At 360×640**, not on a 128×256 analysis grid, so the number is not a lower
   bound.
4. **Regions that match the claim being refused.** `in_front_of` would be
   asserted between *tracks*, so the regions must be detection boxes, not grid
   cells — a box straddling a depth discontinuity is the failure mode that
   matters and a grid cell hides it.
5. **Bucketed by separation**, so the result either yields a usable threshold or
   demonstrates that none exists.

`tower/experiments/depth.py` already carries the `capture_depth_array` hook for
exactly this purpose. The whole test is a scratch script gated on one
`pip install timm`. Call it an afternoon.

### 2.3 Is there a depth-free way? I measured it.

The corpus is 12 fps from a moving camera, so parallax between consecutive frames
carries ordering information no single-frame monocular estimate has. The repo
also has real calibration, which I had not expected:
`data/world_builder/intrinsics/360x640.json` — self-calibrated,
fx 438.23, fy 437.78, cx 174.88, cy 323.38, 5 radtan coefficients,
**reprojection RMS 0.289 px over 511 views**. That makes full metric-up-to-scale
two-view geometry possible with cv2 alone.

**Method.** Per frame pair at gap *k*: Shi–Tomasi corners (≤800, quality 0.01) on
frame *t*; pyramidal Lucas–Kanade to *t+k* with a forward–backward consistency
check (< 1.0 px); `undistortPoints` with the real K and distortion;
`findEssentialMat` (RANSAC, 1.5 px); `recoverPose`; `triangulatePoints`; per-point
parallax angle between the two rays; median triangulated depth per cell of a 3×5
grid, requiring ≥4 points per cell. Degenerate pairs are rejected on median
parallax < 0.5°, < 30 pose inliers, or < 60 surviving tracks.

Then **the exact metric the refusal names**: for every pair of grid cells present
in two *consecutive* estimates, does the sign of their depth difference flip?

cv2 + numpy only. No timm, no MiDaS, no scipy, no torch. 11 captures with ≥200
frames, 120 anchor frames each, 1,320 frame pairs per gap.

**Results.**

| gap | baseline | usable pairs | median parallax | **ordering flip rate** | cell-depth jitter, median / p90 \|log ratio\| |
|---|---|---|---|---|---|
| 1 | 83 ms | 34.0% | 1.33° | **28.2%** (n=5,936) | 6.7% / 33.6% |
| 3 | 250 ms | 32.5% | 1.95° | **25.4%** (n=5,637) | 6.0% / 32.0% |
| 6 | 500 ms | 23.0% | 2.22° | **24.4%** (n=2,948) | 4.6% / 29.1% |

**Flip rate against how far apart the two regions were** (gap 3, the 250 ms
baseline the repo's own Experiment 2 identifies as the usable parallax window):

| depth ratio between the two cells | flip rate | n |
|---|---|---|
| 1.0–1.2× | 29.0% | 3,703 |
| 1.2–1.5× | 19.0% | 1,224 |
| 1.5–2.0× | 18.6% | 397 |
| 2.0–3.0× | 17.1% | 199 |
| **>3.0×** | **15.8%** | 114 |

**That last row is the finding.** One object three times as far away as another
still has its ordering reversed between one frame pair and the next **16% of the
time**. The curve is nearly flat: separating the objects further buys almost
nothing. This is precisely the failure that killed `nearer_than_same_class` for
box area — a threshold that does not separate right answers from wrong ones — and
it reappears here with real triangulated 3-D geometry instead of pixel areas.

**Quality gating helps and does not rescue it.** Sweeping minimum median parallax
angle, minimum pose inliers, and rejecting rotation-dominant pairs (homography
inlier fraction ≥ 0.9):

| gate (gap 3) | n | flip rate |
|---|---|---|
| none | 5,637 | 25.4% |
| parallax ≥ 1°, inliers ≥ 80 | 3,518 | 21.7% |
| parallax ≥ 2°, inliers ≥ 80 | 2,142 | 18.9% |
| parallax ≥ 2°, inliers ≥ 80, homography < 0.9 | 1,832 | **18.3%** |
| parallax ≥ 4°, inliers ≥ 150 | 725 | 13.1% |

The single best cell in the entire sweep — gap 3, parallax ≥ 2°, ≥80 inliers,
non-rotation-dominant, restricted to ≥2× separated pairs — gives 3.0%, but on 132
comparisons, and its neighbours in the same sweep give 7–13% on comparable n.
That is a small-sample artefact, not a regime. And each gate costs yield on top of
a base usable rate that is already only a third of frame pairs.

**The value-jitter number lands in the same band MiDaS was refused for.** Median
\|log ratio\| of normalized per-cell depth between consecutive estimates:
**4.6–6.7%**, against MiDaS's reported 6.3–7.6%. These are *not* the same
statistic — MiDaS's `mad_mean` is per-pixel absolute change in a [0,1] normalized
field; mine is per-cell log-ratio of triangulated Z — so the coincidence is
suggestive, not an equality, and I will not claim otherwise. What *is* directly
comparable is the tail: my p90 of 29–34% against MiDaS's reported p95 of 19–23%.
**Parallax's tail is worse.**

**Why it fails, which matters more than that it fails.**

1. **Yield.** Only 23–34% of consecutive frame pairs solve at all. At gap 3 the
   failures are `few_pose_inliers` 479/1,320 and `few_tracks` 368/1,320. The
   corpus's motion blur and low-texture indoor content at 360×640 do not sustain
   correspondence. Same shape as Experiment 2's finding at 504×896, one
   resolution step down.
2. **Rotation dominance.** Median homography inlier fraction is 0.85–0.93: a
   pure-rotation model explains most of the motion most of the time. Head motion
   is rotation-heavy. No translation means no parallax and no depth, at any
   resolution, from any geometric method.
3. **The scene is not static.** The corpus's dominant large moving object is the
   wearer's own torso and arms — median person box 21.5% of frame, bottom edge
   0.939, 43% frame-clipped (§1.9). Every feature on it violates the rigid-scene
   assumption the essential matrix rests on, and biases the pose estimate.
4. **Per-pair scale is arbitrary and independent.** `recoverPose` returns a unit
   translation, so consecutive estimates share no scale. Ordering is
   scale-invariant so this does not cause the flips directly, but it means
   nothing accumulates across frames without a pose chain — and the pose chain is
   World Builder, which is offline.

### 2.4 Could existing World Builder geometry answer it?

**No — and the decisive reason is not one of the three the brief lists.**

1. **Coverage on disk is near-zero.** Eight `derived/*/points.json` files exist
   across all 76 worlds. **Seven contain zero points.** All 12,023 points in the
   entire store belong to one session,
   `3dd986b1…/derived/dd5d13a2…`, built from capture `22e9d4289cb…`. Of 18
   captures, exactly one has any reconstructed geometry at all.
2. **The 2D↔3D association is not persisted — this is the decisive one.**
   `points.json` rows carry `segment_index` and `xyz` and nothing else.
   `PointBlock.support_views` is declared at `backend.py:107` and never written
   anywhere in the repository. So **no reconstructed point can be attributed to a
   pixel, a frame, or a detection box** — which is the only operation "is this
   object nearer than that one" requires. A point cloud with no image association
   cannot answer a question posed about objects.
   (`docs/superpowers/research/2026-08-26-cross-segment-registration.md` §1.1–1.3,
   which also verifies the association is exactly recoverable by re-solving, ~19 s
   for all 19 segments — so this is a persistence gap, not a lost measurement.)
3. **Within-session coverage is thin.** 19 of 51 segments hold any point; poses
   are 94 `solved`, 51 `anchor`, 18 `rotation_only`, 294 `unavailable`; median
   381 points among segments that have any.
4. **Wrong timeline, and this alone is fatal for *this* cartridge.** `state.py`'s
   own docstring: *"There is no live world pose to anchor to — World Builder
   produces poses offline, after a session, and is not on the live frame path at
   all."* Scene Understanding answers "what is around me now". A reconstruction
   answers it minutes late.

**One nuance in the repo's favour, against the brief's framing.** The brief lists
"segments share no coordinate frame" and "scale is arbitrary" as limits. For
*this particular question* neither bites: "which is nearer" **within one segment**
is scale-invariant and needs no cross-segment registration at all. The blocker is
coverage and association, not scale. That is worth recording because it means the
fix, if anyone wanted one, is `support_views` persistence plus denser
reconstruction — not the much harder Sim3 registration problem.

### 2.5 Verdict

**The refusal stands, and it now stands on firmer ground than the reasoning that
produced it.**

The docs justify refusing `in_front_of` by MiDaS's specific weakness. The
measurement says the problem is not MiDaS. A depth-free two-view estimator, with
real calibration, real triangulated geometry, and no learned prior, run on the
real corpus, reverses the ordering of two regions 15–25% of the time on
consecutive frames and does not improve as the regions separate. What is failing
is the **input**: 12 fps of rotation-dominant head motion at 360×640 with the
wearer's own body filling a fifth of the frame. Any depth method — learned or
geometric — is reading those same frames.

So this is the well-argued "no" the brief allowed for. The parallax route is not
a workaround waiting to be built; it is a second, independent confirmation that
the scene does not support the relation.

**What would change the answer**, none of which is in Scene Understanding's
scope: known translation from IMU or a stereo baseline, which would make parallax
observable rather than hoped-for; temporal accumulation over a pose chain instead
of independent per-pair solves; higher capture resolution to lift correspondence
yield.

**What should still be measured.** Install `timm` and run the ordering-flip metric
on MiDaS over the same corpus with the same statistic and the same buckets — not
because the answer is likely to change the refusal, but because the refusal
currently cites a number that measures the wrong quantity on the wrong footage at
one-seventh the resolution, and after one afternoon it could cite the right one.
The parallax figures above give it a baseline: if MiDaS flips *less* than 15–25%,
the refusal's stated reasoning needs revisiting; if it flips more, the refusal is
settled and can finally say so with a measurement of its own instead of an
extrapolation.

### 2.6 Reproduction

```
tower/.venv/Scripts/python.exe <scratch>/parallax_depth.py --gap 1 --frames-per-capture 120 --out px_g1.json
tower/.venv/Scripts/python.exe <scratch>/parallax_depth.py --gap 3 --frames-per-capture 120 --out px_g3.json
tower/.venv/Scripts/python.exe <scratch>/parallax_depth.py --gap 6 --frames-per-capture 120 --out px_g6.json
```

Scratch scripts (not in the repo):
`orient_bench.py`, `detector_and_boxes.py`, `parallax_depth.py` under the
session scratchpad. They read the corpus and the intrinsics file and write only
to the scratchpad; nothing in `data/` was written.

---

## 3. Corrections this document makes to the repo

| Where | Says | Measured |
|---|---|---|
| `SCENE-UNDERSTANDING.md:13,103`, `IOS-TO-TOWER-RECONCILIATION.md:175`, `03-ROADMAP.md:178`, and 3 reports | orientation **798 ms** | **43.4 ms** CUDA / **956.4 ms** CPU |
| `orientation.py:25,209`, `engine.py:4,8,23`, `query.py:12,145`, `records.py:123`, `scene_session.py:5,84`, `2026-08-22-scene-understanding-v1.md:108` | orientation **744 ms** | same |
| all of the above | "**24×** (or 23×) the detector" | **1.43×** on CUDA, **29.1×** on CPU |
| all of the above | "**2.5×** the ~300 ms delivered interval" | interval is **83.5 ms**; ratio is **0.52×** CUDA, **11.5×** CPU |
| `orientation.py:34-36` | "The unblocker is named… a restored CUDA build is what would change this decision" | The build exists and was measured. The question is closed. |
| `state.py:42-49` | "measured by this project at 6-8% temporal flicker" | true, but on EPIC-KITCHENS at 128×256, self-described as a lower bound and forbidden by its own acceptance gate from being cited as validation for this camera — and it measured value change, never ordering |
| the brief's premise | scipy not installed | **scipy 1.18.1 is installed**; only `timm` is missing |
