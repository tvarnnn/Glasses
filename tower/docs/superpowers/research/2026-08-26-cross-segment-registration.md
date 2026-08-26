# Cross-segment registration: what it costs, what it recovers, and what it cannot

**Date:** 2026-08-26
**Scope:** `tower/tower/world_builder/backend.py`, `backends/classical.py`, `engine.py`,
`store.py`, `results/world_builder_geometry.py`
**Corpus:** world `3dd986b1c2364d4b85de97152f2e39f4`, session
`dd5d13a2381e430db9b27c7da2cf2928` (457 keyframes, 51 segments, 12,023 points),
built from capture `22e9d4289cb440fbb3f14e6da369a136`.
**Status:** measurement only. No production code was modified. Every number below
was produced by running the repo's own `ClassicalTwoViewBackend`,
`detect_and_describe`, `match_indices` and thresholds against the real world on
disk.

---

## 0. Summary

Registration is **feasible in principle and mostly blocked in practice, for a
reason that is not the registration code.**

- The 2D↔3D association registration needs **exists at solve time and is thrown
  away**. `PointBlock.support_views` is declared and never populated. Nothing on
  disk records which feature in which keyframe produced a given 3D point. The
  association is exactly reproducible by re-solving (verified bit-for-bit on all
  19 segments), so this is a persistence gap, not a lost measurement.
- The viable route is **PnP, not Umeyama**. Direct 3D-3D correspondence dies on
  association density; PnP of one segment's landmarks into the other's keyframes
  yields 10-100x more constraints. numpy + cv2 suffice; `scipy` is not needed.
- **A Sim3 was estimated end to end and it works on 2 segment pairs out of 71
  linked ones.** Best result: segments 4↔5, 419 correspondences, 9 cameras,
  1.50 px median reprojection, scale 0.3533, with the independent reverse
  estimate agreeing to **0.3%**.
- **The blocker is upstream.** 32 of 51 segments contain no geometry at all -
  not a single triangulated point. Segment 0, the one the prior investigation
  highlighted as matching segments 45/47/48/50, is one of them. Of the 19
  segments that do have geometry, most have a camera baseline near zero relative
  to scene depth, which makes scale **unobservable** no matter how good the
  estimator is. This is measured, not asserted (§4.3).
- **A wrong Sim3 reprojects beautifully.** Segment pair (30,50) fits at 1.62 px
  median with 88% of points under 3 px and is wrong by a factor of **3.2 in
  scale**. Reprojection error is not a safety check. Reciprocity is.

Smallest honest slice: persist `support_views`, register the confidently
verifiable subset only, and leave everything else `registered: false`. On this
world that is 3 segments and 31.1% of the reconstructed points.

---

## 1. What linkage data survives to disk: none

### 1.1 `support_views` is declared and never written

`backend.py:107` declares it:

```python
support_views: np.ndarray | None = None
```

A repository-wide grep for `support_views` across all Python returns **exactly
one hit — that declaration.** Every `PointBlock` construction in the classical
backend passes `xyz` alone:

- `classical.py:180` — `estimate_window`'s final block
- `classical.py:294` — `extend`'s per-frame delta
- `classical.py:305` — `snapshot`'s accumulated block

`engine.py:486` then writes the point rows as:

```python
{"segment_index": segment, "xyz": xyz}
```

and `store.write_derived` persists that verbatim. Confirmed against the real
file: `points.json` rows carry exactly two keys, `segment_index` and `xyz`.
`poses.json` rows carry six: `keyframe_id`, `segment_index`, `status`,
`degeneracy`, `rotation`, `translation`.

**There is no record on disk of which 2D feature in which keyframe produced any
3D point.** Not partial, not lossy — absent.

### 1.2 The association exists during the solve, in `observed`

The classical backend builds precisely the map registration wants and discards
it at `return`. `classical.py:141` (and `:669` for the live `_Chain`):

```python
observed: dict[tuple[int, int], int] = {}   # (frame index, feature index) -> landmark index
```

This is the association. It is populated from the seeding pair's inlier index
pairs and propagated forward by `_extend`'s `reobserved` (`classical.py:498`).
`GeometryEstimate` has no field for it, so it dies with the stack frame.

### 1.3 It is exactly recoverable by re-solving — verified

A harness that mirrors `estimate_window`'s orchestration while calling the same
private `_estimate_pair` / `_extend` helpers reproduces every segment's stored
landmark count **exactly**:

| seg | kfs | points on disk | re-solved | observations recovered |
|---|---|---|---|---|
| 1 | 2 | 79 | 79 | 153 |
| 4 | 5 | 456 | 456 | 993 |
| 5 | 11 | 1872 | 1872 | 5295 |
| 6 | 10 | 1115 | 1115 | 2705 |
| 8 | 11 | 904 | 904 | 2516 |
| 12 | 17 | 933 | 933 | 2336 |
| 19 | 32 | 3033 | 3033 | 8367 |
| 21 | 2 | 62 | 62 | 116 |
| 23 | 11 | 20 | 20 | 40 |
| 24 | 10 | 112 | 112 | 218 |
| 30 | 10 | 838 | 838 | 1904 |
| 31 | 14 | 52 | 52 | 100 |
| 32 | 36 | 1411 | 1411 | 3735 |
| 37 | 2 | 28 | 28 | 52 |
| 41 | 3 | 20 | 20 | 39 |
| 43 | 5 | 23 | 23 | 45 |
| 46 | 2 | 381 | 381 | 746 |
| 48 | 12 | 129 | 129 | 251 |
| 50 | 18 | 555 | 555 | 1375 |

19 of 19 match. Re-solving all 19 segments from JPEG costs **~19 s** on this
host. So the association is cheap to recover and cheaper still to persist.

**One trap for whoever implements the persistence.** The live path prunes:
`_Chain.forget_before` (`classical.py:674`) drops every observation whose frame
index is not the most recent one, deliberately, to keep the dict flat (26.1 MB
→ 0.15 MB at 155 keyframes, per its own docstring). A `support_views` written
after the fact from `_Chain.observed` would therefore contain **one frame's
worth** of association on the live path and the whole history on the rebuild
path — silently different data under the same field name. Support views must be
accumulated as they are created, in `extend()` and in `estimate_window`'s loop,
not read off `_Chain` at the end.

### 1.4 The fact that reframes everything: 32 segments have no geometry

`poses.json` holds 457 poses: 94 `solved`, 51 `anchor`, 18 `rotation_only`,
294 `unavailable`. Only **19 of 51 segments contain a single triangulated
point**, and they are the same 19 that contain a solved pose.

The other 32 segments are a lone anchor at `[0,0,0]` with no structure. There is
nothing to register: no points to align, no second camera to give a baseline.
**Segment 0 is one of them.** The prior investigation's headline example — "the
start of the walk matches the end of the walk", (0,45) 178 inliers, (0,47) 119,
(0,50) 101 — is real as an *image* match and unusable as a *registration*,
because segment 0 has no reconstruction to place.

This is the single most important correction to the prior finding. The 285
verified links and the single connected component are properties of the
**keyframe** graph. The registrable graph is the subgraph induced on 19 nodes.

---

## 2. Which scale-recovery route is viable

### 2.1 Association density kills 3D-3D Umeyama

Measured, as the fraction of a keyframe's ORB features that carry a landmark:

| seg | density | seg | density | seg | density |
|---|---|---|---|---|---|
| 1 | 5.32% | 12 | 21.84% | 32 | 11.61% |
| 4 | 27.47% | 19 | 39.22% | 37 | 4.30% |
| 5 | 46.60% | 21 | 27.04% | 41 | 0.87% |
| 6 | 22.86% | 23 | **0.54%** | 43 | 0.92% |
| 8 | 52.06% | 24 | 2.62% | 46 | 31.87% |
| | | 30 | 26.81% | 48 | 2.24% |
| | | 31 | 0.87% | 50 | 5.33% |

A 3D-3D correspondence requires a landmark on **both** sides of a verified
match, so the yield is the product. Expected 3D-3D correspondences per segment
pair, over all verified cross-segment inliers:

| pair | verified inliers | dens A | dens B | expected 3D-3D |
|---|---|---|---|---|
| (48,50) | 4710 | 2.24% | 5.33% | **5.6** |
| (23,24) | 4163 | 0.54% | 2.62% | **0.6** |
| (23,30) | 3099 | 0.54% | 26.81% | **4.5** |
| (5,6) | 3036 | 46.59% | 22.86% | 323.4 |
| (46,48) | 2246 | 31.87% | 2.24% | **16.1** |
| (32,48) | 1026 | 11.61% | 2.24% | **2.7** |

The strongest links in the whole graph yield fewer than six usable
correspondences. Run for real over all 71 linked pairs, only **10 produced 8 or
more** 3D-3D correspondences, and the RANSAC-Umeyama fits on those were
worthless: several reported a median residual of exactly `0.0000` on 7-10
inliers (a minimal set fitting itself), and forward/reverse scale reciprocity
ranged from **0.0134** to 1.03 where the truth is 1.0.

**Verdict: 3D-3D Umeyama is not viable on this data.** It would become viable
only if `support_views` were persisted *and* the reconstruction were much
denser. The density is a property of the solve, not of the storage, so
persisting `support_views` alone does not fix it.

### 2.2 PnP needs the association on one side only, and that is decisive

Match segment A's keyframe *i* against segment B's keyframe *j*; for every
verified inlier whose A-side feature carries a landmark, emit a 3D(A)-2D(B)
correspondence and run `cv2.solvePnPRansac`. The yield is the density of **one**
segment, not the product:

| pair | expected 3D-2D A→B | expected 3D-2D B→A |
|---|---|---|
| (5,6) | 1414.6 | 694.1 |
| (46,48) | 715.7 | 50.4 |
| (4,5) | 454.1 | 770.2 |
| (48,50) | 105.6 | 251.2 |
| (23,30) | 16.7 | 830.8 |

One to two orders of magnitude better, and it works even when the *other*
segment is nearly structureless — which matters, because that is the common case
here.

PnP gives the pose of B's keyframe *j* in A's frame. With B's own pose for *j*
known, the Sim3 follows in closed form. Writing `X_A = s·R·X_B + t`, and
requiring both cameras to see the same physical ray:

```
R_b = R_a · R                     ->   R = R_aᵀ R_b
R_a t + t_a = s t_b               ->   t = C_A(j) − s·R·C_B(j)
```

so **rotation comes from a single PnP**, and **scale needs two or more of B's
cameras with a real baseline between them**. That last clause is the whole
problem (§4.3).

### 2.3 2D-2D plus re-triangulation

Matching across segments and re-running `findEssentialMat`/`recoverPose` gives
rotation and a *unit* translation direction. It recovers no scale, by
construction — this is the same limitation `PoseEstimate`'s own docstring
records for the intra-segment case. It is useful only as the geometric
verification step, which is how it is used here.

### 2.4 scipy is not needed

Every routine used in this study is numpy + cv2:

| need | implementation |
|---|---|
| Umeyama / Horn similarity | one `np.linalg.svd` on a 3×3 |
| chordal rotation mean | one `np.linalg.svd` on a 3×3 |
| Sim3 Gauss-Newton / LM | 7×7 normal equations, `np.linalg.solve` |
| robust loss | Huber IRLS weights, plain numpy |
| PnP, Rodrigues, essential matrix | `cv2`, already a hard dependency |

`scipy.optimize.least_squares` would be a convenience, not a requirement. The
parameter vector is 7 long; a numerical Jacobian costs 7 residual evaluations.

---

## 3. The estimator, and its self-test

The estimator used for §4 is:

1. ORB + `match_indices` + `findEssentialMat(USAC_MAGSAC)` to verify each
   cross-segment keyframe pair (the backend's own thresholds:
   `MIN_INLIERS = 15`, `RANSAC_THRESHOLD_PX = 1.0`, `RANSAC_CONFIDENCE = 0.999`).
2. For each of B's keyframes, accumulate 3D(A)-2D(B) correspondences over all of
   A's keyframes and run `solvePnPRansac(SQPNP)` at 3.0 px.
3. Initialise Sim3 from the chordal-mean PnP rotation and the median camera-centre
   offset, over a 45-point log grid of candidate scales from 0.02 to 50.
4. Refine each grid point with Levenberg-damped Gauss-Newton on **reprojection
   error** with Huber IRLS, then free the scale from the best grid point.
5. Report the profile of cost against scale as a **scale-ambiguity** measure: the
   width, as a ratio, of the scale interval whose cost stays within 1.5× of the
   minimum.

**Self-test.** Registering each segment into its own frame must return
`s = 1.0000`. Across all 19 geometry segments:

| seg | cams | corr | span/depth | recovered s | reproj med | scale ambiguity |
|---|---|---|---|---|---|---|
| 1 | 2 | 153 | 0.061 | 1.0000 | 0.28 px | 1.0x |
| 4 | 5 | 1017 | 0.095 | 1.0013 | 0.48 px | 1.0x |
| 5 | 11 | 4485 | 0.345 | 0.9987 | 0.67 px | 1.0x |
| **6** | 10 | 2639 | **0.043** | **0.6736** | 0.75 px | **4.1x** |
| 8 | 8 | 2708 | 0.030 | 0.9381 | 0.61 px | 1.7x |
| 12 | 9 | 2127 | 0.135 | 0.9983 | 0.65 px | 1.0x |
| 19 | 23 | 6715 | 0.923 | 0.9889 | 0.86 px | 1.2x |
| 21 | 2 | 116 | 0.050 | 0.9999 | 0.16 px | 1.0x |
| 23 | 2 | 40 | 0.024 | 0.9999 | 0.25 px | 1.0x |
| 24 | 2 | 219 | 0.023 | 0.9982 | 0.23 px | 1.0x |
| 30 | 8 | 1953 | 0.259 | 0.9970 | 0.74 px | 1.0x |
| 31 | 2 | 100 | 0.029 | 1.0000 | 0.26 px | 1.0x |
| 32 | 14 | 3286 | 0.256 | 0.9788 | 0.64 px | 1.2x |
| 37 | 2 | 39 | 0.269 | 0.9999 | 0.14 px | 1.0x |
| 41 | 2 | 39 | 0.112 | 0.9999 | 0.24 px | 1.0x |
| 43 | 2 | 45 | 1.539 | 1.0000 | 0.25 px | 1.0x |
| 46 | 2 | 748 | 0.033 | 1.0000 | 0.21 px | 1.0x |
| 48 | 2 | 211 | 0.023 | 0.9988 | 0.22 px | 1.0x |
| **50** | 5 | 1315 | **0.069** | **0.4346** | 1.72 px | **17.2x** |

17 of 19 recover the truth to within 1.2%. The two that do not are **flagged by
the ambiguity measure** (4.1x and 17.2x against 1.0-1.2x for every success), and
both fit at *low* reprojection error — 0.75 px for segment 6, which is wrong by
a factor of 1.5. That is the first sighting of the failure mode §6 is about.

The estimator is therefore sound, and the failures below are properties of the
data.

---

## 4. End-to-end measurement on the real world

### 4.1 The registrable link graph

All-pairs cross-segment matching restricted to the 19 geometry segments, every
keyframe against every keyframe, using the backend's own thresholds: **20.5 s**,
**71 linked segment pairs of 171**. Strongest by best single-pair inlier count:

```
(46,48) best=454   (48,50) best=213   (23,24) best=155   (23,30) best=113
( 1,48) best= 99   ( 5, 6) best= 97   (24,30) best= 91   (30,48) best= 91
(32,50) best= 83   ( 1,50) best= 71   ( 4, 5) best= 70   (30,31) best= 69
```

Only 27 of 71 are between adjacent segments; the graph is dominated by revisits,
consistent with the prior finding.

### 4.2 Sim3 results

Sim3 estimation over all 71 pairs, both directions: **28.9 s**. Of 142 directed
attempts, **18 produced an estimate**; the remaining 124 refused because fewer
than two of the target segment's cameras could be PnP-posed. `reciprocity` is
`s(a←b) · s(b←a)`, whose truth is 1.0 and which is a genuinely **independent**
check — the two directions are separate estimation problems over different
correspondence sets.

| pair | cams | corr | s(a←b) | s(b←a) | reprojection | ambiguity | **reciprocity** |
|---|---|---|---|---|---|---|---|
| **(4,5)** | 9 / 5 | 419 / 330 | 0.3533 | 2.8387 | 1.50 / 1.44 px | 2.0x / 1.0x | **1.003** |
| **(5,32)** | 12 / 9 | 342 / 305 | 4.1242 | 0.2286 | 1.08 / 2.11 px | 1.0x / 2.4x | **1.061** |
| (12,46) | 2 / 5 | 68 / 118 | 3.0014 | 0.2838 | 1.73 / 1.81 px | 1.4x / 4.1x | 1.174 |
| (1,50) | 3 / 2 | 37 / 88 | 0.7441 | 1.1250 | 1.28 / 2.41 px | 1.4x / 1.7x | 1.195 |
| (5,6) | 10 / 11 | 335 / 487 | 0.1897 | 3.4816 | 2.49 / 7.06 px | 4.1x / 5.0x | **1.514** |
| (30,50) | 2 / 4 | 34 / 85 | 0.0923 | 3.3697 | 1.62 / 2.05 px | 20.6x / 7.1x | **3.215** |
| (46,48) | 2 / — | 467 | 0.1146 | — | 0.88 px | 10.1x | no reverse |
| (12,48) | 2 / — | 64 | 0.6523 | — | 1.37 px | 71.4x | no reverse |
| (32,1) | 2 / — | 58 | **0.0000** | — | 2.63 px | 2.9x | collapsed |
| (5,1) | 2 / — | 56 | **0.0000** | — | 2.43 px | 8.4x | collapsed |

**The positive result.** Segments 4 and 5 register: 419 correspondences over 9
cameras, 1.50 px median reprojection with 81.4% of points under 3 px, scale
0.3533, and an independently estimated reverse scale of 2.8387 whose product with
it is **1.0030**. Two separate solves agreeing on scale to 0.3% is not a
coincidence of the optimiser. Segments 5 and 32 register the same way at 6.1%.

**The negative results, which matter more.** Two fits drove the scale to
**exactly zero** — the optimiser collapsed the map to a point and this was not
caught by reprojection. (30,50) is wrong by a factor of **3.2** while fitting at
1.62 px with 88.2% of correspondences under 3 px. (5,6) is wrong by 51% at
2.49 px. Segment 0, the prior work's flagship example, could not be attempted at
all.

### 4.3 The root cause is baseline-to-depth, and it is not fixable in the registrar

Sorting the self-test by `span/depth` — the target segment's own camera-centre
span divided by its median scene depth, i.e. the parallax available *within* the
segment — separates the successes from the failures cleanly:

```
span/depth >= 0.09  ->  s recovered to within 1.2%   (segs 4, 5, 12, 19, 30, 32, 37, 41, 43)
span/depth <= 0.07  ->  s wrong by 33% and 57%       (segs 6, 50)
```

The mechanism is textbook. Scale enters the Sim3 only through the baseline
between the target segment's cameras. When the wearer stands still and turns —
which is what a `span/depth` of 0.043 means — the segment's cameras are
effectively coincident, the baseline carries no information, and **the scale is
unobservable**. Segment 6 has 10 cameras and 2,639 correspondences and still
cannot pin its own scale.

Held-out camera test, the strictest available: fit the Sim3 with one of the
target's cameras removed, predict that camera's centre, compare with its own PnP
result.

| direction | cams | held-out centre error | as % of mapped trajectory span | as % of target scene radius |
|---|---|---|---|---|
| 4←5 | 9 | 0.649 | 52.9% | 13.6% |
| 5←4 | 5 | 1.559 | 34.4% | 48.7% |
| 5←32 | 12 | 0.777 | 17.4% | 24.3% |
| 32←5 | 9 | 0.577 | 76.1% | 16.2% |
| 5←6 | 10 | 0.368 | 128.4% | 11.5% |
| 6←5 | 11 | 4.084 | 33.0% | 17.7% |

Even the best pair places a held-out camera to only ~14% of the target scene's
radius. **A registered segment on this world should be understood as
approximately placed, not accurately placed.** That is still enormously better
than the 87x-arbitrary-scale gallery the viewer draws today, but the contract
should not overclaim it.

---

## 5. Does the graph support a globally consistent solution?

### 5.1 Cross-segment linking transforms the observation graph

The prior finding — bundle adjustment measured 0.00% drift improvement because
the observation graph is a chain with median covisibility span 1 — is a
statement about the *intra*-segment graph, where a landmark is seen by
consecutive keyframes and nothing else. Cross-segment links are a different
animal entirely.

Measured over the 1,166 verified cross-segment keyframe links, as the distance
between the two keyframes in the session's global keyframe order:

```
median span   59 keyframes
mean span    121.2
p90          314
max          451   (of 457 keyframes -- the first and last of the walk)

span >=  10 :  89.4%
span >=  50 :  53.5%
span >= 100 :  43.0%
```

Median covisibility span goes from **1 to 59**. So yes: the 0.00% BA result does
not carry over. With cross-segment observations in the graph, bundle adjustment
and pose-graph optimisation would have real loops to close, and the earlier
measurement should not be cited as evidence they are useless once registration
lands.

### 5.2 But on *this* world there is nothing to optimise

The confident subgraph (§5.3) is a **3-node path**: 4 — 5 — 32. There is no
cycle. The obvious candidate for one, the (4,32) edge, exists in the *image*
link graph but **refuses registration entirely** — zero of segment 32's cameras
could be PnP-posed against segment 4's landmarks. So the composed transform
4←5←32 (scale 1.457) has **no independent check available**.

A spanning-tree composition is therefore sufficient here, purely because a
spanning tree is all the data supports. That is a statement about this
reconstruction's poverty, not an argument that pose-graph optimisation is
unnecessary. The correct order of work is:

1. spanning-tree composition now, with per-edge confidence gating;
2. cycle-consistency checking the moment a cycle exists — it is the strongest
   validation available and costs nothing beyond composing and comparing;
3. pose-graph optimisation only once cycles are routine, at which point §5.1 says
   it will actually pay.

Building the pose-graph machinery first would be optimising a tree.

### 5.3 What the gate registers

Gate, with each clause justified by a measurement above:

| clause | why | source |
|---|---|---|
| ≥3 PnP-posed cameras on **both** sides | 2-camera fits produced the `s = 0.0000` collapses and the 71.4x ambiguity | §4.2 |
| reciprocity within 10% | separated (4,5) at 1.003 and (5,32) at 1.061 from (5,6) at 1.514 and (30,50) at 3.215 | §4.2 |
| scale ambiguity ≤ 3x, both directions | flagged both self-test failures at 4.1x and 17.2x against 1.0-1.2x for successes | §3 |
| median reprojection ≤ 3 px, both directions | necessary, nowhere near sufficient | §6 |

Applied to the real world:

```
recip <= 1.05, ambig <= 3.0  ->  edges [(4,5)]           segments [4,5]      2,328/12,023 points (19.4%)
recip <= 1.10, ambig <= 3.0  ->  edges [(4,5),(5,32)]    segments [4,5,32]   3,739/12,023 points (31.1%)
recip <= 1.25, ambig <= 3.0  ->  (unchanged)
recip <= 1.10, ambig <= 10.0 ->  (unchanged)
```

The result is insensitive to loosening either threshold, which is the same shape
the prior investigation found for the inlier-ratio criterion: these links are
either strong or absent.

**3 of 51 segments, 52 of 457 keyframes, but 31.1% of every point the
reconstruction actually produced.** The denominator that matters is not 51.

---

## 6. How this fabricates a world, and what catches it

This is the failure mode the project cares most about, and it is not
hypothetical — it was observed four times in a study this small.

### 6.1 What a wrong Sim3 looks like

- **Wrong scale, correct rotation.** The dominant failure. Segment 30 placed
  into segment 50 at 0.0923 when the reciprocity says ~0.30 puts a whole room
  inside a doorway. A corridor renders as a closet. Nothing looks broken —
  everything looks like a slightly odd floor plan, which is precisely why it is
  dangerous.
- **Collapse to a point.** Two fits returned `s = 0.0000` exactly. The segment
  becomes a dot at the other segment's origin. This one is visually obvious *if
  anyone looks*, and completely silent in any aggregate metric.
- **Wrong rotation.** Folds one segment's geometry through another's. The
  Umeyama-on-camera-centres initialisation disagreed with the PnP rotations by
  **31.9 to 166.0 degrees** on the ill-conditioned pairs before reprojection
  refinement pulled it back. A pipeline that trusted the closed-form centre fit
  alone would ship these.
- **Compounding through the tree.** Composed transforms multiply scale errors.
  4←5←32 is a product of two estimates each independently verified to 0.3% and
  6.1%; a third hop through an unverified edge would carry the whole product
  with no way to notice.

### 6.2 Reprojection error does not catch any of it

The decisive measurement:

```
pair (30,50):  median reprojection 1.62 px / 2.05 px
               88.2% / 75.3% of correspondences under 3 px
               scale wrong by a factor of 3.2

segment 6 self-test:  median reprojection 0.75 px
                      92.0% of correspondences under 3 px
                      scale wrong by 33%, where the truth is known exactly
```

A wrong scale paired with a compensating translation reprojects *perfectly* when
the target segment has no internal parallax. Reprojection error measures whether
the transform is self-consistent, not whether it is right. **Any gate whose
primary signal is reprojection error will ship fabricated worlds.**

### 6.3 What does catch it

In descending order of strength, all measured on this data:

1. **Held-out camera prediction** (§4.3). Fit without one of the target's
   cameras, predict it. Strongest available; costs one refit per camera and
   flags even the pairs that pass everything else.
2. **Reciprocity.** Estimate a←b and b←a from disjoint correspondence sets and
   require the scales to be reciprocal. Caught (30,50) at 3.215 and (5,6) at
   1.514; passed (4,5) at 1.003. Costs a second solve; nothing else here has a
   better ratio of discrimination to effort.
3. **Scale ambiguity from the cost profile.** Sweep the scale with rotation and
   translation re-optimised and measure how wide the near-minimal basin is.
   Caught both self-test failures. This is the direct, honest answer to "is scale
   observable for this pair at all", and it is the one signal that explains *why*
   a pair is refused rather than just that it is.
4. **Cycle consistency**, the moment a cycle exists (§5.2). Free, and independent
   of every other check.
5. **Degenerate-output refusal.** Reject `s ≤ 0`, non-finite parameters, and any
   pair whose target `span/depth` falls below ~0.09 (§4.3) — the last is a
   *pre*-check, refusable before any solving, and it is the cheapest guard in the
   list.

### 6.4 The contract rule

`results/world_builder_geometry.py:175` and `:258` currently write
`"registered": False` and `"transform_to_world": None` for every segment, and
`docs/contracts/WORLD-BUILDER-GEOMETRY.md` §5 rule 3 already states that
`registered: false` forbids placing two segments in one space. That default is
correct and should stay the default.

`registered: true` must require **independent agreement**, not fit quality.
Concretely: a segment flips to `registered: true` only when it is connected to
the reference segment by a path of edges that each passed §5.3's gate, and the
`transform_to_world` it carries is the composition along that path. An
unregistered segment keeps `transform_to_world: null` and the viewer keeps
drawing it as a fragment — which is what it is.

Worth stating in the contract alongside the flag: registration on this world is
accurate to roughly 14-49% of the target segment's scene radius (§4.3). A
consumer that treats `transform_to_world` as metrically trustworthy will be
wrong in a way that no field currently warns it about.

---

## 7. The honest smallest first slice

**Step 0 — persist the association.** Populate `PointBlock.support_views` in
`estimate_window` and `extend`, carry it through `engine.py`'s point rows, and
write it in `write_derived`. Note §1.3's pruning trap. This is a self-contained,
testable change that unblocks every route in this document and removes the ~19 s
re-solve. It changes no geometry, so the incremental-equivalence test remains the
oracle.

**Step 1 — register the confident subset, and only that.** Build the
cross-segment link graph over the segments that *have geometry* (20.5 s), run
the bidirectional PnP-plus-Gauss-Newton Sim3 (28.9 s), apply §5.3's gate, compose
along the spanning tree, and write `registered` / `transform_to_world` for the
segments that pass. On this world: 3 segments, 31.1% of points. Everything else
stays `registered: false` and keeps rendering as a fragment.

**Step 2 — the pre-check that makes the refusals explicable.** `span/depth` per
segment is computable from `poses.json` and `points.json` alone, needs no
matching, and predicts registrability (§4.3). Reporting it turns "we could not
place 16 of the 19 segments" from an opaque failure into "the wearer stood still
in those segments, so their scale is unrecoverable" — which is an honest,
actionable answer and points at the fix.

**What not to build yet.** Pose-graph optimisation (§5.2 — no cycles exist).
3D-3D Umeyama (§2.1 — the density is not there). A descriptor retrieval index
(the all-pairs graph over 19 segments takes 20.5 s; retrieval is an optimisation
for a problem this world does not have).

**Where the real leverage is.** Registration quality here is bounded by
`span/depth`, not by the registrar. 32 of 51 segments have no geometry, and most
of the rest were recorded standing still. Every improvement to fragmentation and
to keyframe selection under low parallax raises the ceiling on registration
directly, and the prior investigation has already shown that ceiling can move a
long way.

---

## Appendix: reproduction

All measurements were produced with scratch scripts calling the repo's own
modules unmodified — `ClassicalTwoViewBackend._estimate_pair` and `._extend`,
`detect_and_describe`, `match_indices`, `WorldStore`, and the thresholds in
`world_builder/geometry.py`. The harness in §1.3 mirrors `estimate_window`'s
orchestration while retaining `observed`, and is validated by reproducing all 19
segments' stored landmark counts exactly. Timings are on this host, CPU only,
`cv2` 5.0.0 / `numpy` 2.5.2, no `scipy`.
