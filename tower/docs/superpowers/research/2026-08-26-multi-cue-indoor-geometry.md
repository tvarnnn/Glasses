# Multi-cue indoor geometry: five cues measured, four refused, and the one that was already there

**Date:** 2026-08-26
**Scope:** `tower/tower/world_builder/` — `frontend.py`, `geometry.py`,
`keyframes.py`, `backends/classical.py`, `engine.py`
**Corpus:** `tower/data/captures/` — 33 captures, **16,618 real Ray-Ban frames**
at 360×640; the 8 captures with genuine wearer motion carry every cue result
**Host:** RTX 5070 (sm_120), OpenCV **5.0.0**, torch 2.13.0+cu132, numpy 2.5.2
**Status:** measurement only. **No production code was modified.** Harnesses in
`tower/scripts/research/multi_cue_geometry/`.

---

## 0. Summary

The brief asked whether line features, vanishing directions, planar
constraints, edge/gradient information, learned matching and monocular depth
can improve camera-only tracking, reconstruction and cross-segment
registration. Each was measured independently on real footage, against the
pipeline's own thresholds, with a stated null.

**Four of the five new cues are refused on measured evidence. The fifth has a
measured ceiling too small to justify its cost today. And the largest available
improvement is not a cue at all: the pipeline already computes solvable geometry
and throws it away.**

| Cue | Verdict | The number that decided it |
|---|---|---|
| Line segments | **Refuse** | Lines and points fail *together*: r = **0.875** between log ORB count and log LSD count. In ORB-starved frames the median LSD yield is 13 segments against 122 in rich frames |
| Vanishing directions | **Refuse** | Estimator noise floor **2.59°** median on a *motionless* camera, against a median true inter-frame rotation of **1.22°**. Beats "predict no rotation" on 13.3% of pairs |
| Planar constraints | **Already captured** | One dominant plane explains **79.5%** of matches; a second plane clears the bar on only 24.5% of pairs. The single homography already fitted every frame has it |
| Learned correspondence | **Defer** | Only **10.4%** of pairs in geometry-less segments are correspondence-limited; **54.7%** are baseline-limited, where no matcher can help. Cross-segment, correspondence is oversupplied ~19× against what registration admits |
| Monocular depth prior | **Refuse for geometry** | Spearman(MiDaS, 1/z_sfm) = **0.074**, negative on 42.4% of frames. Implied-depth spread **12.6×** where it would need to be tighter than 3.2× |
| **Re-seeding the SfM chain** | **Adopt, pending review** | **545 → 1,459 solved poses (2.7×)**, **86,959 → 239,930 points (2.8×)**, largest coherent component **preserved**, on 8 real captures |

Two defects were found on the way and are recorded in §6.

---

## 1. What the pipeline already extracts

Before measuring anything new, the brief's first instruction: establish what is
already captured, so no work is duplicated. The answer is more than the module
names suggest.

**Explicitly, on every delivered frame** (`frontend.py`, ~5 ms at 360×640):

- Shi-Tomasi corners, pyramidal Lucas-Kanade with a forward-backward check
- `survival_ratio`, `overlap_ratio`, `median_displacement_px`
- variance-of-Laplacian sharpness
- **a full homography fit**, and its median residual

**Explicitly, per keyframe pair** (`geometry.py`, `backends/classical.py`):

- ORB detect+describe (**3.9 ms** median, measured here), Hamming BF, Lowe ratio
- essential matrix + `recoverPose`, PnP chaining, triangulation
- median triangulation angle, inlier count and ratio, cheirality fraction
- **`homography_ratio` — ORB-SLAM's r_H — computed and deliberately not gated**

**Implicitly**, and this is where two of the brief's cues already live:

- **Edge/gradient information is the substrate of the point pipeline.** Both
  Shi-Tomasi and ORB's FAST are gradient operators. The existing
  `edge_detection` experiment adds only a scalar Canny density, which carries no
  structure and no correspondence.
- **The planar cue is the homography, and it is fitted twice per pair** — once in
  `summarise_motion` as a rotation detector, once as r_H. §4 shows there is
  almost nothing left over for a multi-plane method to use.
- **Monocular depth already exists** as a loaded, benchmarked experiment
  (MiDaS-small, 5.7 ms CUDA / 18.3 ms CPU per the Scene Understanding work).

So of six candidate cues, **two were already captured and one was already
installed**. Only lines, vanishing directions and learned matching were genuinely
absent — and all three are refused below.

---

## 2. Lines: present in quantity, and useless where they are needed

**Availability.** LSD (OpenCV 5 restores it; `ximgproc`'s FLD is unavailable in
this build) over 960 frames from the 8 moving captures, segments ≥ 20 px:

| | |
|---|---|
| segments per frame | median **95**, p5 17, p95 223 |
| frames with none | 3 (0.3%) |
| median segment length | 32.9 px; longest-in-frame median 197.8 px |
| cost | **13.3 ms** median (LSD alone) |

So lines exist. That is the weakest possible claim for a cue, and on its own it
is the reason a cue like this gets adopted without evidence.

**The test that matters is complementarity.** A cue earns its place by working
where the incumbent fails, so the question is whether lines survive in the frames
where ORB starves.

| ORB keypoints | frames | median LSD segments | median line px |
|---|---|---|---|
| < 50 (starved) | 63 (6.6%) | **13** | 663 |
| 50–200 | 69 | 31 | 1,382 |
| 200–600 | 180 | 71 | 3,420 |
| 600–1200 | 190 | 88 | 3,754 |
| ≥ 1200 | 458 | **122** | 5,579 |

**r = 0.875** between log ORB count and log segment count. Of the ORB-starved
frames, 34.9% carry fewer than 10 segments and only 7.9% carry 30 or more.

Lines and points die together, and in hindsight the mechanism is obvious: what
starves ORB on this corpus is motion blur and low light, and both destroy the
gradients LSD needs just as thoroughly. **Lines are not complementary structural
evidence on this imagery. They are the same evidence, more expensively.**

---

## 3. Vanishing directions: the noise floor is larger than the signal

This was the most promising cue on paper, and the reasoning is worth stating
because it is sound and the measurement still refuses it. A Manhattan frame
recovered from line directions gives **absolute, drift-free rotation** relative to
the room, from a single frame, with no correspondence at all — exactly the thing
that survives when tracking does not, and exactly the independent opinion that
cross-segment registration lacks.

Implementation (`lines.py`): LSD segments → interpretation-plane normals
`n = Kᵀl` → RANSAC over line pairs for the best mutually-orthogonal triplet,
scored by **inlier length** rather than count, then eigen-refined.

### 3.1 The control that reframed the question

An early version reported a Manhattan frame found in **98.6%** of frames, which
looks like a strong cue and is not. Against a null of the best of 20 random
orthogonal triplets scored the same way:

| tolerance | fitted inlier share | best-of-20 random | ratio |
|---|---|---|---|
| 1.0° | 0.127 | 0.178 | 0.71 |
| 3.0° | 0.305 | 0.429 | 0.71 |

The fit was *losing to random*, which exposed a sign bug in the eigen-refinement
(§6.2). With that fixed the fit wins — raw 0.767 against best-of-2000 random
0.725 — but the margin says what matters: **line normals in a room are so
clustered that many triplets explain much of the line length.** Inlier share is
not a discriminative statistic, and "a Manhattan frame was found" means nothing.

### 3.2 Does the triplet track the camera?

Compared against the pipeline's own rotation, computed two independent ways —
`E-pose` (ORB + essential matrix + `recoverPose`, restricted to pairs the
pipeline itself calls solvable) and `H-rot` (`R = K⁻¹HK` projected to SO(3),
exact under pure rotation) — with the gauge resolved over all 24 signed
permutations. **1,047 frame pairs, VP recovered in both frames on 999.**

The null is `identity`: predict no rotation at all.

| comparison | n | median | p90 |
|---|---|---|---|
| E-pose vs H-rot *(do the references agree)* | 316 | 2.98° | 179.94° |
| **VP vs H-rot** | 937 | **5.30°** | 29.97° |
| **IDENTITY vs H-rot (null)** | 937 | **1.22°** | 5.78° |
| **VP vs E-pose** | 326 | **10.39°** | 173.31° |
| **IDENTITY vs E-pose (null)** | 326 | **3.31°** | 179.87° |

**VP beats predicting no rotation on 13.3% of pairs (H-rot) and 30.4% (E-pose).**
Stratified by true rotation magnitude, VP error grows *with* the rotation and
never crosses the null:

| true rotation | n | VP error | identity error | VP wins |
|---|---|---|---|---|
| 0–1° | 419 | 4.32° | 0.27° | 1.2% |
| 2–5° | 222 | 7.10° | 3.10° | 22.5% |
| 5–10° | 87 | 9.90° | 6.60° | 40.2% |
| 10–20° | 27 | 15.24° | 12.71° | 51.9% |

### 3.3 Whose fault — the estimator or the scene?

The corpus contains captures where the camera sits on a table (median
inter-frame displacement 0.1–0.4 px). There the true relative rotation is ~0, so
anything the estimator reports is its own jitter.

| | triplet worst-axis | vertical axis only |
|---|---|---|
| **STATIC captures**, 654 pairs | **3.62°** median, 13.90° p90 | **2.59°** median, 10.90° p90 |
| MOVING captures, 823 pairs | 5.61° | 4.19° |
| MOVING, 12-frame stride | 18.59° | 15.11° |

**A motionless camera produces 2.59° of apparent rotation.** The median real
inter-frame rotation is 1.22°. The cue is noisier than the quantity it would
measure, which is not a tuning problem — it is a structural one.

### 3.4 Two salvage attempts, both measured, both refused

The vertical alone is the most defensible part of the cue — it constrains 2 of 3
rotational DoF and is the one direction a building keeps consistent throughout.

| min line length | yield | per-frame drift | 10-frame window |
|---|---|---|---|
| 20 px | 100% | **2.86°** | **1.39°** |
| 40 px | 100% | 2.93° | 1.65° |
| 60 px | 99.5% | 3.12° | 2.33° |
| 90 px | **59.4%** | 1.57° | 1.12° |

**Longer lines do not help** — the floor is not endpoint quantisation. Temporal
averaging over 10 frames only *halves* the jitter where independent noise would
give √10 ≈ 3.2×, so the error is substantially correlated: the estimator is
locking onto genuinely different structure from frame to frame, not dithering
around one answer. And 10 frames is **0.83 s** of latency, during which the head
has turned.

**Verdict: refuse.** At 360×640, with 45 ms per frame for the Manhattan RANSAC
on top of 13 ms for LSD, the cue costs more than the entire existing per-frame
path and delivers rotation worse than assuming the camera did not move. Nothing
here refutes the *idea*; it refutes the idea **on 360×640 Ray-Ban frames**, and
that is the only camera the platform has (720p is available but rejected on
independent grounds — 73.3% of frames fall below `min_sharpness` there).

---

## 4. Planar constraints: the single homography already has them

Sequential-RANSAC multi-homography (fit, remove inliers, refit) over 351
keyframe pairs with ≥ 40 matches. A plane counts only if it holds ≥ 25
correspondences **and** ≥ 10% of the pair's matches.

| | |
|---|---|
| dominant plane's share of matches | median **0.795** (p25 0.637, p75 0.887) |
| **second** plane's share | median **0.061**, p90 0.221 |
| pairs with exactly 1 supported plane | **72.9%** |
| pairs where a second plane clears the bar | 24.5% |
| pairs where one plane explains > 60% of matches | **78.3%** |

The scene is single-plane-dominated, which independently corroborates the
recorded r_H finding ("a room is nothing but planes", r_H saturating at
0.471–0.499). The homography the pipeline **already fits on every frame** in
`summarise_motion` captures essentially all of the planar evidence available. A
piecewise-planar method would be re-deriving it at higher cost.

**Verdict: already captured. No new work.**

---

## 5. Learned correspondence and monocular depth: ceilings, measured

### 5.1 Correspondence is not what is missing

`edges.jsonl` appears to say the empty segments have no correspondence — 190 of
212 intra-segment edges record `matches: 0`. **That is a default, not a
measurement** (§6.1). Re-running the shipped matcher on the actual keyframe
images says the opposite:

| | empty segments | segments with geometry |
|---|---|---|
| ORB matches | median **205** | median 208 |
| essential-matrix inliers | median **162** | median 144 |
| pairs with ≥ 15 inliers | **89.6%** | 95.9% |
| median triangulation angle | 0.282° | 0.645° |

Classifying the 212 pairs inside empty segments:

| blocker | pairs | can a better matcher help? |
|---|---|---|
| **baseline** (low parallax / no triangulation) | **116 (54.7%)** | **No.** Two views sharing a camera centre contain no depth information; more correspondences produce more of the same ambiguity |
| correspondence | 22 (10.4%) | Yes |
| **already solvable pairwise** | **74 (34.9%)** | Nothing to buy — see §7 |

### 5.2 The same holds across segments

Registration is where a learned matcher would classically earn its keep. Over
all 171 pairs of the 19 geometry-bearing segments, best link of up to 6×6
keyframe comparisons each (4,071 comparisons, 16.5 s with ORB):

- **56 of 171 (32.7%)** already clear the pipeline's own bar (≥15 inliers, ratio ≥0.05)
- only **11.1%** have essentially no correspondence
- **registration admits 3**

Correspondence is oversupplied by roughly **19×** relative to what registration
accepts. The binding constraint is the recorded one — 16 of 19 segments refused
for `span/depth`, because the wearer stood still and scale is unobservable. A
matcher cannot manufacture a baseline.

**Verdict: defer.** The measured ceiling is 10.4% of intra-segment pairs and a set
of cross-segment links that still face an unchanged scale gate. That does not pay
for a new dependency, new weights, and a per-pair cost far above ORB's 3.9 ms.
**Revisit when the P11 sidestep walk exists** — deliberate translation changes the
span/depth picture, and it is only then that correspondence could become the
binding constraint.

### 5.3 Depth cannot police scale

The one job worth asking depth to do: act as a third, differently-sourced opinion
on registration scale, since reprojection provably cannot (pair (30,50) fits at
1.62 px while being 3.2× wrong).

Landmarks the pipeline itself triangulated, projected into their own solved
keyframes, compared against MiDaS-small inverse depth at those pixels. 99 frames,
12 segments, median 498 landmarks per frame. MiDaS emits relative inverse depth
under an unknown affine map, so the comparison is affine-invariant by
construction.

| | |
|---|---|
| Spearman(MiDaS, 1/z_sfm) | median **0.074**; **42.4%** of frames **negative**; only 2.0% above 0.5 |
| implied/actual depth spread (p84/p16) after per-frame affine fit | median **12.64×** |
| frames tighter than the 3.2× error it must catch | **21.2%** |
| MiDaS cost | 11.0 ms CUDA (18.3 ms CPU, previously measured) |

Stratifying by how well-conditioned the SfM side is does **not** rescue it — at
seed triangulation angles above 5° the correlation is *−0.195*. The spread only
tightens where the landmarks span little depth (3.21× at p90/p10 < 3), which is
where there is nothing to discriminate anyway.

There is no ground truth, so this measures **disagreement, not error**, and it
cannot say which of the two is wrong. For the intended job that does not matter:
**two sources that disagree this much cannot arbitrate each other.**

**Verdict: refuse for geometry.** This is consistent with, and does not
contradict, the Scene Understanding finding that MiDaS *ordering* is stable in a
static scene — ordering is a far weaker claim than a scale bound, and that work
also found the ordering degrades sharply once anything moves.

---

## 6. Two defects found while measuring

### 6.1 "Not attempted" is recorded as "measured zero"

`PoseEstimate.matches` defaults to `0`. When a segment's seeding pair fails,
`estimate_window` never starts the chain, and every subsequent pose is written
with the default. On disk this is indistinguishable from a real measurement of
no correspondence — and it is wrong by two orders of magnitude: those pairs
actually carry a median of **205** matches.

This is the same absent-vs-zero distinction the geometry contract takes care to
preserve on the wire, not preserved in the session journal. It cost this
investigation one wrong conclusion before the images were re-measured, and it
would mislead anyone tuning from `edges.jsonl`.

### 6.2 `cv2.solvePnPRansac(SOLVEPNP_SQPNP)` asserts instead of refusing

```
sqpnp.cpp:274: error: (-215:Assertion failed) ++num_null_vectors_ <= 6
                in function 'cv::sqpnp::PoseSolver::computeOmega'
```

`_extend` calls it without catching `cv2.error`, so a degenerate correspondence
set raises out of the backend rather than returning `ok=False`. It fired **once**
across the 8-capture sweep, so exposure is low but non-zero — and `ModuleContainer`
treats a non-`FrameProcessingError` exception as a **module** failure, and
`mark_failed()` is terminal. The blast radius is larger than the frequency.

*(A third, in the research code rather than the product: the Manhattan
eigen-refinement did not sign-align eigenvectors before orthogonalising, which
made "refinement" reduce the fit from 0.767 to 0.210 and once to 0.000. It
presented exactly as "lines are a weak cue". Fixed in `lines.py` with the
measurement recorded at the fix.)*

---

## 7. The result that outweighs every cue above

While measuring what blocks the empty segments, §5.1 turned up something that is
not about cues at all: **34.9% of keyframe pairs inside segments that produced no
geometry are already pairwise solvable.** 22 of the 23 empty multi-keyframe
segments contain at least one solvable pair. **Segment 20 contains 22 solvable
pairs out of 30 and yields nothing.**

The cause is two lines of orchestration, both visible in `backends/classical.py`
and both deliberate:

1. the chain is seeded from `features[0], features[1]` — **the first pair,
   unconditionally**. A degenerate first pair abandons the whole segment;
2. the chain **stops at the first link that does not solve**, discarding
   everything after it.

Given that a keyframe is promoted for track decay far more often than for
parallax on real footage, the first pair of a segment is frequently the *worst*
available seed.

### 7.1 Measured, on 8 real captures with the current tracker

Three orchestrations over the same frames, the same segmentation, and the **same
private helpers** (`_estimate_pair`, `_extend`) — so this compares order of
operations and nothing else. The baseline reproduces the on-disk world exactly
(94 solved poses, 12,023 points, 19 segments with geometry), which is what
licenses the other two.

| orchestration | solved poses | points | components | largest component (kf) |
|---|---|---|---|---|
| baseline | 545 | 86,959 | 82 | **89** |
| re-seed (best pair first) | 1,403 | 236,245 | 355 | 72 |
| **augment** (baseline chain, then fill the rest) | **1,459** | **239,930** | 317 | **89** |

`augment` **dominates the baseline on every one of the 8 captures** and cannot
lose a component the baseline had, by construction. Plain `re-seed` does not have
that property and gives up the largest component (89 → 72) — which is precisely
the failure mode this project has already shipped once and recorded in
`keyframes.py`, and the reason largest-coherent-component is reported here beside
the counts.

### 7.2 The added geometry is as trustworthy as what was already there

| group | components | solved poses | points | seed angle | reprojection | above 3 px |
|---|---|---|---|---|---|---|
| baseline | 19 | 94 | 12,023 | 1.928° | **0.279 px** | 0.0% |
| **added** | 69 | 133 | 16,200 | **2.943°** | **0.239 px** | 0.0% |

The added components are *better conditioned* (higher seed triangulation angle,
by construction) and reproject *slightly tighter*. Density is lower — 60
landmarks per solved pose against 114 — which is expected: shorter chains
accumulate fewer re-observations.

### 7.3 Cost, and the honest cost

The whole three-way re-solve of 2,095 keyframes across 8 captures runs in **58.5 s
including the baseline**. This is derive-time work, not live-path work; the extra
expense is one `_estimate_pair` scan per segment over already-computed ORB
features.

**The real cost is fragmentation: 82 components become 317.** More fragments, each
carrying real geometry, replace fewer fragments of which most carried none. On
this project's own stated standard — *"one segment containing nothing is worse
than 51 containing something"* — that is the right trade. But it makes the
registration problem larger, and registration is already gated by scale
observability, not by candidate supply. **These two facts should be weighed
together before this is wired into the production path**, and the decision is
not this document's to make.

---

## 8. What would change these verdicts

Stated so nobody re-runs settled work, and so the genuinely open questions stay
open.

- **A capture with deliberate translation (P11).** Every refusal above is shaped
  by a rotation-dominant corpus in which 54.7% of pairs have no baseline. A
  sidestep walk changes the span/depth picture, and it is the *only* thing that
  could make learned correspondence the binding constraint. It remains the
  highest-leverage physical experiment available, exactly as
  `WORLD-BUILDER-STATUS.md` says.
- **A higher-resolution camera.** The vanishing-direction refusal is a
  resolution-and-noise-floor result, not a claim about indoor geometry. It does
  not transfer to a different sensor and should not be cited as if it did.
- **Nothing would revive lines as a complement to points on this camera.** The
  r = 0.875 correlation is a property of what destroys both — blur and darkness —
  and no amount of tuning decouples them.
- **A loop closure (P10).** Still the only independent check on composed
  transforms, and unaffected by anything measured here.

---

## 9. Reproducing

All harnesses read the corpus and write nothing into it. They run from any
working directory.

```
tower/scripts/research/multi_cue_geometry/
  lines.py                LSD + Manhattan-frame estimation (shared module)
  cue_availability.py     line/ORB yield and cost, 960 frames        (§2)
  vp_null.py              the random-triplet control                 (§3.1)
  vp_rotation.py          VP rotation vs E-pose / H-rot / identity   (§3.2)
  vp_stability.py         static-hold and vertical-only jitter       (§3.3)
  vp_salvage.py           line-length and temporal-averaging sweeps  (§3.4)
  planes.py               sequential multi-homography                (§4)
  blocker.py              what edges.jsonl claims                    (§6.1)
  blocker_measured.py     what the images actually say               (§5.1)
  cross_segment.py        correspondence supply across segments      (§5.2)
  depth_scale.py          MiDaS vs SfM depth and scale               (§5.3)
  reseed.py               three orchestrations, one world            (§7)
  corpus_solve.py         three orchestrations, 8 captures           (§7.1)
  augment_quality.py      is the added geometry trustworthy          (§7.2)
```

Every quality number in this document is **self-consistency, not accuracy**.
There is no ground-truth geometry on this host, and a method that is
confidently and consistently wrong would look identical.
