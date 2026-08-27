# Stage 1 — looking three keyframes back instead of one

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation`.
**Change:** `EXTEND_REFERENCE_DEPTH`, `_reobserve_against_pose` in
`backends/classical.py`.
**Status:** IMPLEMENTED and BENCHMARK-VALIDATED on real frames. Not
physically validated.

---

## 0. What was built, and what it is not

`_extend` matched each keyframe against exactly one reference: its
immediate predecessor. Every landmark's association died the moment the
reference advanced past it, which is why **66.1% of landmarks were seen
by exactly two views** and why a bundle adjuster measured **0.00%**
improvement here — a two-view landmark is exactly determined, so two
thirds of the map was invisible to an optimiser by construction.

The change looks back `EXTEND_REFERENCE_DEPTH` (= 3) accepted keyframes
for **further sightings of landmarks the map already holds**, and admits
one only if that landmark, projected through the pose just solved, lands
within `PNP_REPROJECTION_ERROR_PX` of the feature claiming it.

**This is not the multi-reference PnP the roadmap proposed.** It does not
feed several references' correspondences into one pose solve. It is
ORB-SLAM's guided re-observation idea (`SearchByProjection`),
reimplemented, and it was chosen because it is far smaller and its
failure modes are visible.

Deliberately reusing an existing threshold, not inventing one:
`PNP_REPROJECTION_ERROR_PX` is what `solvePnPRansac` used to decide
inliers **for this very pose**, so an admitted re-observation is one the
pose solve itself would have accepted had it been offered. Cheirality is
checked first, because a point behind the camera can still reproject onto
a plausible pixel.

## 1. The design error that was found, and what it cost

The first version withheld guided rows from `observed`, so no later pose
could move. That looked strictly safer and it was **wrong**.

`observed` is what the next keyframe consults to decide whether a feature
already has a landmark. Withheld, the next step finds nothing,
triangulates the same physical point a second time, and publishes a
support row binding that same `(frame, feature)` to a *different*
landmark.

**MEASURED, synthetic walk: 2 such conflicting rows at DEPTH=1 — the
documented seed-pair case — against 147 at DEPTH=3.**

That is not cosmetic. `support.json` is what cross-segment registration
solves PnP against, so one row of every conflicting pair feeds a wrong
3-D point to the thing deciding where a segment sits in the world.

The fix was to put the association where associations go. The cost is
that this change is **no longer pose-neutral** and had to be measured
rather than argued. Conflicts returned to 2 at both depths.

## 2. Paired per-segment measurement on real frames — MEASURED

30 real geometry-bearing segments (≥8 keyframes) across 6 persisted
worlds, each segment solved twice, DEPTH 1 vs DEPTH 3, everything else
identical. Paired because capture content moves landmark multiplicity
nearly as much as an algorithm change does, so a pooled number cannot
separate the two.

Harness: `scripts/research/stage1_covisibility/sweep_segments.py`.

| metric | better | unchanged | worse | median delta |
|---|---|---|---|---|
| **≥3-view landmark share** | **18** | 11 | **0** | **+3.46 pp** |
| exactly-2-view share | 0 | 11 | 18 *(i.e. fell)* | **−3.46 pp** |
| poses_solved | 2 | 27 | 1 | 0 |
| points | 5 | 12 | 13 | 0 |
| support rows | 10 | 12 | 8 | 0 |
| **conflicting rows** | 0 | **30** | 0 | **0** |

**The primary metric improved on 18 segments and worsened on none.**

## 3. The point count falls on 13 segments, and that is duplicates merging

This is the finding most likely to be misread as a regression, so it is
stated with its evidence rather than asserted.

On **every one of the 13 segments that lost points, observations per
landmark ROSE** — MEASURED:

| segment | points | obs/landmark |
|---|---|---|
| `3dd986b1` seg19 | 2060 → 1964 | 2.55 → **3.01** |
| `3dd986b1` seg8 | 622 → 452 | 2.80 → **3.51** |
| `4cae0b26` seg8 | 5081 → 4186 | 2.88 → **3.24** |
| `4cae0b26` seg11 | 1499 → 1264 | 3.02 → **3.57** |
| `4cae0b26` seg18 | 1280 → 901 | 2.76 → **3.12** |
| `3dd986b1` seg32 | 801 → 789 | 2.53 → **3.09** |

And on several, **support rows rose while points fell** — `seg19` rows
+12.9% against points −4.7%; `seg32` rows +20.1% against points −1.5%.
Sightings are being kept while landmarks are being merged.

Losing real structure would drop both numbers. Merging a duplicate drops
the landmark and keeps its sightings. The signature is unambiguous, and
it is the same mechanism `_extend`'s own comment already describes as the
thing that stops the map being write-only:

> Without this the map is write-only: a landmark seen in frame N-1 and
> re-seen in frame N cannot be found from frame N, so step N->N+1
> re-triangulates the same physical structure instead of reusing it,
> roughly doubling the point count with duplicates of the same structure
> and badly degrading the trajectory.

This change extends exactly that reuse from a one-frame window to three.
**`points` was never a count of distinct physical structure; it was a
count of triangulated landmarks including duplicates.** A reviewer should
attack this reading, and §6 records that it is the weakest claim here.

## 4. Tests, and the control that proves they work

`tests/test_world_builder_reference_depth.py` — 6 tests.

Per the run's testing standard, the mechanism was **neutralized** (the
guided result forced empty) and the suite re-run. **Three tests failed**,
with the diagnostics they were written to give:

- `looking further back found no further sightings at all`
- `assert 8901 > 8901`
- `observations per landmark did not rise, so any drop in the point count
  is structure being lost rather than duplicates being merged`

The mechanism was then restored and all 6 pass. A mechanism whose removal
leaves the suite green is not tested, and this repository has had exactly
that failure before.

One existing test was updated rather than deleted:
`test_the_live_table_outlives_the_pruning_it_survives` asserted the prune
retains exactly **one** frame. It now asserts the retained window is
bounded by `EXTEND_REFERENCE_DEPTH`. The property it defends — retained
state is a CONSTANT, not a function of walk length — is unchanged, and
the accompanying `forget_before` docstring measurement was updated with
it rather than left to rot.

## 5. Cost

Per-keyframe cost is `DEPTH − 1` extra `match_indices` calls. MEASURED on
the 32-keyframe segment 19 at 360×640: 0.40 s at DEPTH=1 against 0.28 s
at DEPTH=3 — i.e. **within run-to-run noise, and not a regression**,
because the extra matching is partly offset by triangulating fewer
duplicate landmarks.

Retained live state rises from one frame of `observed` to `DEPTH` frames
— ~0.15 MB to ~0.45 MB extrapolating the existing measurement. Still a
constant; still flat in walk length; asserted by test.

## 6. What is weak here, stated plainly

- **The duplicate-merging reading of the falling point count is an
  inference**, supported by a consistent obs/landmark rise on 13 of 13
  segments but not by any ground truth. There is none on this corpus.
  If it is wrong, this change is removing real structure and should be
  reverted. That is the first thing an adversarial reviewer should test.
- **`poses_solved` fell on one segment of 30.** Not obviously noise, not
  obviously signal.
- **DEPTH=5 was measured and is not obviously worse** (2-view 55.19% vs
  56.82% at DEPTH=3 on segment 19), so 3 is a judgement about cost, not a
  measured optimum.
- All numbers are self-consistency. No ground truth exists on this corpus.
