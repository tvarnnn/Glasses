# Segment fragmentation in World Builder: why 154 seconds became 51 shards

**Date:** 2026-08-26
**Scope:** `tower/tower/world_builder/frontend.py`, `keyframes.py`, `engine.py`
**Corpus:** 8 real Ray-Ban captures under `tower/data/captures/` (7,073 frames),
led by `22e9d4289cb440fbb3f14e6da369a136` (1,848 frames, 154.2 s, 11.99 fps),
the capture behind session `dd5d13a2381e430db9b27c7da2cf2928`.
**Status:** measurement only. No production code was modified.

---

## 0. Baseline reproduced bit-for-bit

Every number below comes from replaying real JPEG frames through the real
`FrameTracker` and the real `KeyframeSelector`. The harness reproduces the
persisted session exactly, which is what licenses everything after it:

| | persisted `session.json` | replay |
|---|---|---|
| frames observed | 1848 | 1848 |
| keyframes accepted | 457 | 457 |
| `insufficient_motion` | 670 | 670 |
| `blurred` | 639 | 639 |
| `tracking_lost` | 50 | 50 |
| `tracking_degraded` | 32 | 32 |
| segments | 51 | 51 |

Derived output corroborates the product complaint: `poses.json` holds 457 poses
(94 `solved`, 51 `anchor`, 18 `rotation_only`, 294 `unavailable`) and exactly
**19 segments contain at least one `solved` pose**.

---

## 1. The headline finding: the tracker is not failing. The reference is stale.

**The widely-assumed cause is wrong.** Segment breaks are not caused by imagery
the optical-flow tracker cannot follow. They are caused by `FrameTracker`'s
reference frame going stale while the blur gate refuses to let it advance.

Measured: for every consecutive frame pair in the capture, run the real
`summarise_motion` from frame *n-1* to frame *n*.

```
consecutive-frame survival ratio, n = 1847
  median 0.874   mean 0.760
  p1 0.012  p5 0.124  p10 0.285  p25 0.624  p50 0.874  p75 0.977  p90 1.000
  below the 0.05 loss floor:  42 frames (2.3%)
```

Now the decisive cross-tabulation. On the 50 frames where the engine declared
`tracking_lost`:

```
consecutive-frame survival ON the lost frame: median 0.634
  47 of 50 losses had frame-to-frame survival >= 0.05
  40 of 50 losses had frame-to-frame survival >= 0.20
  only  3 of 50 were genuine frame-to-frame breaks
```

**94% of segment breaks happen on frames the tracker could have followed.**

The mechanism is structural, not parametric. `FrameTracker` measures against the
last *accepted keyframe*, and the reference advances only in `engine.py:283`
(`self._tracker.set_reference(gray)`), which is reached only on an accept. Every
rejection, including all 639 `blurred` rejections, leaves the reference where it
was. Measured staleness at the moment of loss:

```
frames since last keyframe AT LOSS:  median 7, mean 12.4, max 89
  <=2 frames: 10 losses   3-5: 9   6-10: 11   >10: 20
blur-run length immediately before the loss: median 5, mean 9.8, max 86
```

At the measured motion rate the field of view turns over roughly every 1.8 s
(section 5). A reference that has not advanced for 12 frames (one second) is
already looking at substantially different content. The tracker is then asked to
jump the whole accumulated gap in one Lucas-Kanade call, and fails, and the
engine reads that failure as "the world is gone".

`frontend.py:26-31` seeds features once per reference and never again; there is
no re-detection cadence, no top-up, and no frame-to-frame chaining. That is the
proximate cause of track death.

### 1a. Why loosening the blur gate made segmentation *worse*

This was the counter-intuitive prior result, and it now has a clean explanation.
`keyframes.py:272` runs the blur check **before** the loss check at
`keyframes.py:278`. A blurred frame therefore cannot declare loss: it returns
`REJECT/blurred` first. The blur gate is not protecting tracking; it is
**masking losses that have already happened**.

```
blur rejections whose survival was ALREADY below 0.05:  382 / 571  (67%)
frames already below the loss floor, masked by the blur
gate, before the loss finally fired:  median 1, mean 7.2, max 81
```

Loosening the gate removes the mask and the same underlying losses surface as
`tracking_lost`, hence 0.45 giving 43 segments and off giving 49. The prior
conclusion ("do not loosen blur") is correct as stated, but the reasoning behind
it should be updated: the gate is not doing useful tracking work, it is hiding a
bookkeeping failure. Fixing the staleness makes the blur gate's ordering
irrelevant.

Two more facts about the blur gate worth recording:

- 434 of the 639 blur rejections come from the **absolute** floor
  (`min_sharpness = 25.0`, `keyframes.py:97`), not the ratio test. Overall
  sharpness median is 95, p25 is 28: the absolute floor sits inside the working
  distribution of this scene, not below it.
- Of frames rejected by that absolute floor, **57% still tracked with
  frame-to-frame survival >= 0.5**. The gate is discarding usable frames.
  Correlation of `log(1+sharpness)` with frame-to-frame survival is only 0.52.

---

## 2. Loss distribution

```
51 segments, 50 losses.
segment durations (s):   median 1.95, mean 2.96, min 0.01, max 9.24
segment frame counts:    min 2, median 24, max 112
segment keyframe counts: 9 segments have exactly 1 keyframe; none have 0
losses per 10 s bucket:  1 4 2 2 2 2 3 3 2 6 5 6 8 2 2 0
```

Losses are **clustered, not uniform**: 25 of 50 fall in the 90-130 s window,
which is also where blur runs are longest. Nothing in the data suggests a
periodic or cadence-driven failure.

---

## 3. Measured levers

All numbers are **measured**, by replaying the real capture. Nothing in this
section is estimated. Baseline is 51 segments / 457 keyframes.

### 3.1 Tracker parameters (`frontend.py:29-41`)

| change | segments | keyframes | note |
|---|---|---|---|
| `LK_MAX_LEVEL` 1 | 87 | 516 | |
| `LK_MAX_LEVEL` 2 | 68 | 443 | |
| **`LK_MAX_LEVEL` 3 (current)** | **51** | **457** | baseline |
| **`LK_MAX_LEVEL` 4** | **40** | **458** | **-22% segments, free** |
| `LK_MAX_LEVEL` 5 | 40 | 458 | saturated |
| `LK_WINDOW` 11 | 64 | 487 | |
| `LK_WINDOW` 15 | 57 | 477 | |
| **`LK_WINDOW` 21 (current)** | **51** | **457** | |
| `LK_WINDOW` 25 | 51 | 456 | |
| `LK_WINDOW` 31 | 49 | 439 | |
| `LK_WINDOW` 41 | 46 | 440 | |
| `FORWARD_BACKWARD_MAX_PX` 0.5 | 58 | 462 | |
| **1.0 (current)** | **51** | **457** | |
| 2.0 | 49 | 438 | |
| **3.0** | **47** | **431** | |
| 5.0 | 43 | 436 | |
| `TRACK_QUALITY_LEVEL` 0.003 | 49 | 495 | |
| 0.005 | 49 | 481 | |
| **0.01 (current)** | **51** | **457** | |
| 0.02 | 54 | 439 | |
| `TRACK_MIN_DISTANCE` 4 / 7 / 12 | 53 / **51** / 50 | | |
| `MAX_TRACK_POINTS` 300 / 600 / 1200 | **51 / 51 / 51** | | **completely flat** |

**`LK_MAX_LEVEL` 3 to 4 is the single best free lever: -11 segments for a
one-line change and zero measured cost.** The per-frame frontend path measures
4.85 ms at L3 and 4.85 ms at L4 (L5 is 5.04 ms): pyramid level 4 of a 360x640
image is 45x80 pixels.

The physics behind it: measured consecutive-frame displacement is median
12.7 px, p90 40.5 px, p99 85.4 px, max 196.2 px. With `winSize` 21 and
`maxLevel` 3, the coarsest search extent is roughly 10 x 2^3 = 80 px, right at
the p99. `maxLevel` 4 doubles it to ~160 px and covers the whole distribution.
Saturation at level 5 is exactly what that model predicts.

The flat `MAX_TRACK_POINTS` row is important on its own; see section 4.

### 3.2 Policy thresholds (`keyframes.py:169-176`)

| change | segments | keyframes |
|---|---|---|
| `loss_survival_ratio` 0.00 | **1** | **37** (degenerate, see below) |
| 0.01 | 48 | 405 |
| 0.02 | 50 | 444 |
| **0.05 (current)** | **51** | **457** |
| 0.10 | 56 | 460 |
| 0.15 | 57 | 464 |
| `min_survival_ratio` 0.06 | **43** | 482 |
| 0.08 | 43 | 482 |
| 0.10 | 44 | 479 |
| 0.15 | 50 | 468 |
| **0.20 (current)** | **51** | **457** |
| 0.35 | 60 | 409 |
| `min_overlap_ratio` **0.75 (current)** | **51** | 457 |
| 0.85 | 49 | 522 |
| 0.95 | 49 | 692 |
| 1.01 | 49 | 1128 |

Two things to read here.

**`loss_survival_ratio = 0.0` is a trap, not a win.** It gives 1 segment because
loss is never declared, but only 37 keyframes in 154 seconds. Once survival
reaches zero, `has_motion_evidence` (`frontend.py:93-98`) is false forever, the
frame returns `SKIP/no_motion_evidence`, the reference never advances, and the
session quietly stops mapping. One segment containing nothing is worse than 51
containing something. Any future work that reports segment count must report
keyframes and solved poses alongside it.

**Lowering `min_survival_ratio` from 0.20 to 0.06 buys 8 segments for 25 extra
keyframes.** The mechanism is the rescue window: frames in [0.06, 0.20) stop
being discarded as `tracking_degraded` and instead reach the `overlap_floor`
accept at `keyframes.py:298`, which advances the reference and resets the decay.
This is the same "widen the rescue window from the top" argument in the existing
comment at `keyframes.py:130-136`, applied to the bottom edge, and it works for
the same reason.

Raising `min_overlap_ratio` past 0.75 is a bad trade: 0.95 costs +235 keyframes
for -2 segments.

### 3.3 Structural changes

Three variants, each implemented as a local subclass in the scratch harness so
production code stayed untouched.

**Chained tracking.** Propagate the point set forward one frame at a time
(reference to n-1 to n) instead of re-tracking the whole gap in one jump. Each
hop is small, so each hop succeeds; the accumulated correspondence to the
reference keyframe is what decays.

**Hold-on-bad-hop.** A hop whose survival collapses is *not committed*: the
previous good frame and its point set are kept, so the next frame is tracked
from the last frame we could actually follow. Motivated directly by the
measurement that runs of frame-to-frame survival below 0.05 have **median length
1**, one unfollowable frame and then the imagery is fine again.

**Grace window.** Require N consecutive loss verdicts before breaking the
segment.

| variant | segments | keyframes |
|---|---|---|
| baseline | 51 | 457 |
| grace 2 / 3 / 4 / 6 / 8 | 45 / 43 / 40 / 35 / 33 | 424 / 399 / 370 / 341 / 314 |
| chained | 40 | 416 |
| chained + grace 3 / 6 / 8 | 36 / 32 / 30 | 376 / 328 / 304 |
| chained + hold(0.35, max 6) | 41 | 360 |
| chained + hold(0.35, max 12) | 34 | 331 |
| chained + hold(0.35, max 30) | 25 | 253 |
| blur-override rescue (trigger 0.35, floor 8) | 41 | 517 |
| blur-override rescue (trigger 0.50, floor 3) | 37 | 603 |

"Blur-override rescue" takes the rescue keyframe even when the frame fails the
blur gate, provided survival is decaying and sharpness clears a lower emergency
floor. It works, but it is the most expensive lever per segment saved (+146
keyframes for -10 segments) and it puts smeared frames on the reconstruction
path. Not recommended while cheaper levers remain.

### 3.4 Stacking

With `LK_MAX_LEVEL=4`, `FORWARD_BACKWARD_MAX_PX=3.0`, `min_survival_ratio=0.06`:

| stack | segments | keyframes |
|---|---|---|
| baseline | 51 | 457 |
| L4 | 40 | 458 |
| L4 + fb3 | 33 | 448 |
| L4 + fb3 + ms.06 | 30 | 462 |
| + grace 3 | **27** | **429** |
| + grace 6 | 24 | 384 |
| + chained | 27 | 451 |
| + chained + hold12 | 26 | 350 |
| + chained + hold12 + grace3 | 26 | 350 |
| + chained + hold30 | **22** | 295 |
| + blur-rescue + grace3 | 22 | 488 |

**51 to 22 segments** at the far end, with *fewer* keyframes than baseline.

### 3.5 Generalisation across the corpus

One walk is one walk. Re-run across the 8 largest captures (7,073 frames):

| capture | frames | baseline | L4 | L4+fb3 | +ms.06 | +grace3 | +grace6 | +chain+hold12+grace3 |
|---|---|---|---|---|---|---|---|---|
| 22e9d428 | 1848 | 51/457 | 40/458 | 33/448 | 30/462 | 27/429 | 24/384 | 26/350 |
| b35d8ab8 | 1694 | 55/350 | 46/364 | 43/349 | 39/367 | 35/324 | 30/278 | 25/267 |
| 2e6cffa2 | 1395 | 20/260 | 19/266 | 16/240 | 13/248 | 9/240 | 8/233 | 11/178 |
| e1c52b9f | 996 | 5/163 | 5/167 | 5/160 | 5/160 | 5/157 | 4/152 | 2/152 |
| 854e9688 | 610 | 20/200 | 18/207 | 17/196 | 13/202 | 11/192 | 9/181 | 9/164 |
| b5a0d654 | 561 | 11/118 | 8/122 | 9/115 | 8/120 | 5/115 | 5/109 | 6/92 |
| 64f48114 | 527 | 6/75 | 4/74 | 4/75 | 4/76 | 4/72 | 4/68 | 3/68 |
| 69030fba | 442 | 3/82 | 3/82 | 3/78 | 3/78 | 3/78 | 3/78 | 3/63 |
| **TOTAL** | **7073** | **171 / 1705** | **143 / 1740** | **130 / 1661** | **115 / 1713** | **99 / 1607** | **87 / 1483** | **85 / 1334** |

The ordering holds on every capture. **No capture gets worse under any stack.**
Corpus-wide: **171 to 85 segments (-50%) while keyframes fall 1705 to 1334
(-22%)**. Note capture `2e6cffa2` is the 1,395-frame 2026-08-24 walk the current
constants were tuned on; it goes 20 to 9 segments, so the existing tuning was not
already at its optimum even on its own footage.

### 3.6 Are the longer segments real, or just suppressed losses?

The critical control. For each config, run the **real** geometry module
(`geometry.py`) over every consecutive keyframe pair *inside* each segment and
count pairs clearing the backend's own thresholds (`MIN_INLIERS` 15,
`MIN_INLIER_RATIO` 0.05, `MIN_TRIANGULATION_ANGLE_DEG` 0.5).

| config | segs | kf | intra-seg pairs | solvable | no-correspondence | median tri-angle |
|---|---|---|---|---|---|---|
| baseline | 51 | 457 | 406 | 188 (46%) | 5 | 0.43 deg |
| L4 | 40 | 458 | 418 | 202 (48%) | 6 | 0.47 deg |
| L4+fb3 | 33 | 448 | 415 | 211 (51%) | 10 | 0.54 deg |
| L4+fb3+ms.06 | 30 | 462 | 432 | 221 (51%) | 11 | 0.56 deg |
| +grace3 | 27 | 429 | 402 | 210 (52%) | 7 | 0.57 deg |
| +grace6 | 24 | 384 | 360 | 191 (53%) | 7 | 0.63 deg |
| +chain+hold12+grace3 | 26 | 350 | 324 | 166 (51%) | **0** | 0.53 deg |
| +chain+hold30 | 22 | 295 | 273 | 144 (53%) | 2 | 0.56 deg |

The solvable **fraction rises** (46% to 51-53%) and the median triangulation
angle **rises** (0.43 deg to 0.63 deg) as segments fall. Pairs with no usable
correspondence stay in single digits and reach zero under chained+hold. The
segment reduction is not achieved by gluing together chains that cannot be
solved.

The residual 47-49% of unsolvable pairs are **low-parallax**, not
no-correspondence: the rotation-dominant-motion problem already documented at
`keyframes.py:27-43`. That is a separate, unsolved issue and is not addressed by
anything in this report.

---

## 4. The resolution question: 720x1280 would probably make this *worse*

**We are not feature-starved.** Three independent measurements:

1. `MAX_TRACK_POINTS` 300 / 600 / 1200 all yield **exactly 51 segments**. The
   seeding is quality-limited, not cap-limited.
2. Persisted `feature_count` across 406 keyframes: median 187, p10 114, p25 146,
   p90 294, min **59**, max 545. **Zero keyframes reach the 600 cap; none fall
   below 50.** `tracked_count` at accept: median 128, p10 64, comfortably above
   `MIN_TRACKS_FOR_MOTION` (12).
3. Frame-to-frame survival is 0.874 median. Features are not scarce; they are
   being asked to jump too far.

**Direct probe.** We cannot manufacture native 720x1280 from 360x640, but we can
halve the delivered resolution and see which way tracking moves:

| resolution | maxLevel | median seeded | f2f survival median | p10 | frames < 0.05 | median disp |
|---|---|---|---|---|---|---|
| 360x640 (delivered) | 3 | 182 | 0.874 | 0.285 | 42 | 12.7 px |
| 360x640 | 4 | 182 | 0.876 | 0.318 | 38 | 12.7 px |
| **180x320** | 2 | 91 | **0.927** | **0.450** | **23** | 6.3 px |
| **180x320** | 3 | 91 | **0.930** | **0.478** | 27 | 6.3 px |

**Halving the resolution, halving the feature count, makes tracking
substantially better.** Full pipeline at 180x320 (with the absolute blur floor
rescaled, see below) gives **40 segments**, identical to full-resolution
`maxLevel=4`, at 1.00 ms per frame instead of 4.85 ms.

The reason is the same one behind the `maxLevel` result: LK difficulty scales
with *pixel* displacement and *pixel* blur extent, not with information content.
Going to 720x1280 doubles median displacement to ~25 px, p99 to ~170 px, max to
~392 px, and doubles the pixel width of every motion-blur smear. That is the
direction that made 360 worse than 180.

**A concrete hazard, not a hypothesis.** `min_sharpness = 25.0`
(`keyframes.py:97`) is an *absolute* variance-of-Laplacian threshold, and
variance-of-Laplacian is strongly resolution-dependent. Measured on 370 real
frames:

```
180x320  (0.5x)          median Laplacian variance 356.9   below the 25.0 floor:  20/370
360x640  (native)        median Laplacian variance  94.9   below the 25.0 floor:  87/370
720x1280 (2x upsample)   median Laplacian variance   6.1   below the 25.0 floor: 299/370
```

The 2x row is an interpolated upsample, so it is a *lower bound* on what native
720p would score: native 720p has real high-frequency detail an interpolation
lacks. But the direction is certain and the magnitude is large. **Switching DAT
to 720x1280 without rescaling `min_sharpness` would reject the great majority of
frames as blurred.** The same effect is visible at half resolution: keeping the
floor at 25 gives 44 segments / 533 keyframes, rescaling it gives 40 / 458.

**Answer to the question as posed:** more pixels would *not* plausibly reduce
track death, and the measured evidence points the other way. If 720x1280 is
wanted for other reasons (more ORB features and better triangulation precision
in the *backend*), the right architecture is to deliver 720p to `geometry.py`
while running `frontend.py`'s tracker on a 360p or 180p downsample. That is
cheap, testable, and gets both benefits.

**What the data cannot answer:** whether native 720p sensor detail, as opposed
to interpolated pixels, would add trackable corners in the low-texture regions
that currently seed only 59-114 features. The experiment that would settle it:
capture the same scene, same walk, at both 360x640 and 720x1280 through DAT, and
compare (a) `goodFeaturesToTrack` counts at matched `qualityLevel`, (b)
frame-to-frame survival with `LK_WINDOW` and `LK_MAX_LEVEL` scaled to hold the
pixel capture range constant, and (c) native variance-of-Laplacian
distributions. Nothing short of a matched dual-resolution capture answers it.

---

## 5. The honest ceiling

**Field of view is not the hard floor.** Measured per-frame apparent angular
motion, treating all displacement as horizontal (an upper bound, since the
44.7 deg horizontal axis is the narrow one):

```
p50 1.57 deg/frame (19 deg/s)   p75 2.94 deg (35 deg/s)   p90 5.02 deg (60 deg/s)
p95 6.58 deg (79 deg/s)         p99 10.59 deg (127 deg/s)
frames exceeding half the 44.7 deg hFOV in one step:  1
frames exceeding the full hFOV in one step:           0
```

At 12 fps, **no single frame ever jumps clear of the field**. There is always
frame-to-frame overlap. FOV only becomes a floor for *recovery across a
multi-frame gap*, and the cumulative measurement shows why the current design
hits it: the field turns over completely every 1.8 s on average (85 turnovers in
154 s), which is exactly the timescale on which a stale reference dies.

**The frame-to-frame floor.** Counting *runs* of consecutive-frame survival
below threshold, where each run is one episode the tracker genuinely could not
follow:

```
f2f survival < 0.05:  21 runs, 42 frames total, median run 1 frame,  max 7
f2f survival < 0.10:  40 runs, 77 frames total, median run 1 frame,  max 7
f2f survival < 0.20:  62 runs, 130 frames total, median run 1 frame, max 7
```

**~21 irreducible break episodes** on this walk, and the median episode is a
*single frame* long. The measured best stack (22 segments) is already at that
floor. Getting materially below ~20 segments on this footage would require
skipping over multi-frame unfollowable runs, which is where hold-on-bad-hop with
a large `max_hold` is operating, and that is closer to re-localisation than to
tracking.

**Verdict: single digits is not realistic for a 154-second walk at this field
and frame rate. Low-to-mid twenties is.** The corpus-wide result (171 to 85
across 7,073 frames, ~1 segment per 83 frames or ~7 s) is the realistic target.

### 5.1 Therefore the product needs cross-segment registration, and it will work

This is the most important finding for the roadmap, and it is strongly positive.

Sample 130 keyframes across all 51 segments (first, middle, last of each) and
ORB + essential-matrix match every cross-segment pair with the backend's own
thresholds:

| criterion | verified segment-pair links | adjacent | non-adjacent | connected components over 51 segments |
|---|---|---|---|---|
| inliers >= 15, ratio >= 0.05 (backend's own) | 285 | 27 | 258 | **1** (all 51) |
| inliers >= 15, ratio >= 0.50 | 283 | 27 | 256 | **1** (all 51) |
| inliers >= 40 (conservative) | 102 | 17 | 85 | 13, largest component **39 of 51** |
| inliers >= 80 (very conservative) | 30 | 8 | 22 | 34, largest 8 |

Note the inlier-*ratio* criterion is nearly inert (285 to 283 from 0.05 to 0.50):
these links are not marginal. They are either strong or absent.

Strongest non-adjacent links include (46,48) 384 inliers, (45,47) 304, (23,25)
221, and, tellingly, **(0,45) 178, (0,47) 119, (0,50) 101**: the start of the
walk matches the end of the walk. The wearer revisits views constantly.

**The 19 shards are not geometrically disconnected. They are disconnected only
because the pipeline declares them disconnected and never tries to re-link
them.** `engine.py:240-252` increments the segment index, resets the tracker,
freezes the backend, and never looks back; `engine.py:497-504` then correctly
reports the world as not internally consistent. Every one of those decisions is
locally right and collectively gives up geometry that is measurably present.

Even at a conservative 40-inlier bar, a re-localisation pass would merge 39 of
51 shards into a single component. Combined with the tracking fixes above
(51 to 22-27 segments), the two together plausibly produce a single connected
world for this walk.

For contrast, the adjacent-only case is much weaker: matching the last keyframe
of segment N against the first keyframe of segment N+1 succeeds for only
**15 of 50** breaks (median gap across a break is 16 frames, 1.3 s). Bridging
must be a global retrieval problem, not a neighbour-stitching one.

---

## 6. Ranked interventions

| # | intervention | measured effect (this walk) | corpus effect | keyframe cost | risk |
|---|---|---|---|---|---|
| 1 | `LK_MAX_LEVEL` 3 to 4 (`frontend.py:33`) | 51 to 40 | 171 to 143 | +1 kf | **Very low.** One constant. Zero measured runtime cost (4.85 ms both). No test pins it. |
| 2 | `FORWARD_BACKWARD_MAX_PX` 1.0 to 3.0 (`frontend.py:38`) | with #1: 40 to 33 | 143 to 130 | -10 kf | **Low.** Admits looser tracks; the section 3.6 control shows inlier quality and triangulation angle *improve*, not degrade. |
| 3 | `min_survival_ratio` 0.20 to 0.06 (`keyframes.py:169`) | with #1-2: 33 to 30 | 130 to 115 | +14 kf | **Low-medium.** Preserves the documented ordering `loss < min_survival < min_overlap`. **Breaks one test**: `tests/test_world_builder_frontend.py:291` asserts survival 0.10 is `tracking_degraded`; that band moves. |
| 4 | Grace window of 3 before declaring loss (`keyframes.py:278`) | with #1-3: 30 to 27 | 115 to 99 | -33 kf | **Medium.** New selector state; must reset on accept and on `note_lost`. Semantically it delays a real decision, so it needs a cap so a genuinely dead track cannot linger. |
| 5 | Chained frame-to-frame tracking with hold-on-bad-hop (`frontend.py:223-257`) | with #1-3: 30 to 26 | 115 to 85 | -112 kf | **Medium-high.** Real rewrite of `FrameTracker`. Must maintain the reference-correspondence index alongside the propagated point set. Upside beyond segments: eliminates no-correspondence keyframe pairs entirely (11 to 0) and *reduces* keyframes 22%. |
| 6 | **Cross-segment re-localisation** | would merge 39 of 51 shards into one component at a conservative 40-inlier bar; all 51 at the backend's own thresholds | n/a | none | **High effort, highest product value.** New subsystem: keyframe descriptor index, candidate retrieval, geometric verification, similarity-transform alignment across segments' arbitrary scales (`engine.py:497-504` notes segments measured 4x apart in unit). But the evidence says the geometry is there. |
| n/a | Blur-override rescue keyframes | 51 to 37 alone | not run | +146 kf | **Not recommended now.** Most expensive per segment saved; puts smeared frames on the reconstruction path. Revisit only if #1-5 underdeliver. |
| n/a | Loosening the blur gate | worse (43 at 0.45, 49 off) | n/a | n/a | **Confirmed dead.** But see 1a: the reason is masking, not protection. |
| n/a | `min_overlap_ratio` above 0.75 | -2 segments for +235 kf | n/a | n/a | **Bad trade.** |
| n/a | `MAX_TRACK_POINTS`, `TRACK_MIN_DISTANCE` | flat / negligible | n/a | n/a | **No lever here.** |
| n/a | 720x1280 delivery to reduce track death | predicted worse (section 4) | n/a | n/a | **Do not do this for tracking reasons.** If done for backend reasons, downsample before `FrameTracker` and rescale `min_sharpness`. |

**Recommended first commit: #1 + #2.** Two constants, 51 to 33 on the main walk
and 171 to 130 corpus-wide, no new state, no test churn, no keyframe budget
increase, no runtime cost. That is a 24% corpus-wide fragmentation reduction for
a two-line diff.

---

## 7. What is measured and what is inferred

**Measured** (real frames, real code, reproduced baseline): everything in
sections 0-3 and 5; the resolution comparison at 180x320 and the
variance-of-Laplacian-versus-scale figures in section 4; the cross-segment link
graph in 5.1.

**Inferred, not measured:** that native 720x1280 would worsen tracking. The
half-resolution result establishes the direction of the pixel-displacement and
blur-extent effects, and the upsample result establishes that `min_sharpness`
does not transfer across resolution, but neither is a native 720p capture. The
matched dual-resolution experiment is specified at the end of section 4.

**Also inferred:** that intervention #6 would produce a single connected world.
The link graph shows the correspondences exist and are geometrically verifiable;
it does not show that a similarity-transform alignment across segments with
independently arbitrary scales converges to a consistent global solution. That
requires implementing it.

**Explicitly refuted by this work:** that segment breaks are caused by imagery
the tracker cannot follow. 47 of 50 breaks occurred on frames whose
frame-to-frame survival was above the loss threshold; 40 of 50 above four times
the loss threshold. The breaks are a staleness bookkeeping failure, and they are
substantially fixable with constants.
