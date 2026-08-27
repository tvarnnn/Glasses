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

## 5a. A REGRESSION THE PER-SEGMENT SWEEP DID NOT SEE

**Added after §2-§5 were written, and it changes the verdict.**

The paired sweep in §2 ran `estimate_window` over each segment's own
keyframes. The **engine** does not work that way: it replays frames
through the live `begin/extend` path and re-segments dynamically. Running
the real pipeline found something the sweep could not.

Capture `4fea31e2` (the smallest pinned capture, 54 keyframes), replayed
end to end — MEASURED:

| | DEPTH=1 | DEPTH=3 |
|---|---|---|
| keyframes | 54 | 54 |
| segments | 4 | 4 |
| **poses_solved** | **10** | **5** |
| points | 530 | 426 |
| exactly-2-view | 84.2% | **62.0%** |
| ≥3-view | 15.8% | **38.0%** |

**Solved poses halved.** DEPTH=1 reproduces the Stage 0 baseline exactly
(10 / 530 / 84.2%), which confirms two things: the run is a valid
control, and the separately-added feature-starvation gate is inert on
this capture (54 keyframes either way). The cause is Stage 1 alone.

**The mechanism.** Guided associations are merged into `observed`. At the
NEXT keyframe, a feature that would have been triangulated as new
structure is instead found to already have a landmark, so it becomes a
re-observation. Fewer new landmarks enter the map, so later PnP has fewer
3-D points to solve against, so chains break earlier. §3's
"duplicates being merged" reading is still correct about *why* the point
count falls — but merging is not free, and on a small capture it starves
the map.

**This is the exact failure mode this stage was warned about**, and it is
why the corpus-level A/B matters more than the segment-level one. A
per-segment harness that hands the backend a segment's keyframes cannot
observe an effect that only appears when the map has to grow itself.

## 5b. THE CORPUS A/B — the deciding measurement, and it reverses §5a

Full replay of all 8 pinned captures through the real engine, twice,
toggling only `EXTEND_REFERENCE_DEPTH`. MEASURED:

| metric | DEPTH=1 | DEPTH=3 | delta |
|---|---|---|---|
| segments | 230 | 232 | +2 |
| keyframes | 1,712 | 1,712 | 0 |
| **poses_solved** | 591 | **620** | **+29** |
| poses_refused | 891 | 860 | **−31** |
| points | 75,369 | 71,122 | −4,247 |
| **support rows** | 186,778 | **195,752** | **+8,974** |
| exactly-2-view | 70.38% | **61.70%** | **−8.68 pp** |
| ≥3-view | 29.62% | **38.30%** | **+8.68 pp** |
| obs/landmark | 2.478 | 2.752 | +0.27 |

Per capture, `poses_solved`:

| capture | 1 → 3 | points | segments |
|---|---|---|---|
| `e1c52b9f` | 145 → **147** | 22520 → 19872 | 10 → 9 |
| `22e9d428` | 112 → **131** | 11503 → **12347** | 64 → 68 |
| `b35d8ab8` | 114 → **115** | 11375 → 11364 | 76 → 76 |
| `20ce3c23` | 75 → **85** | 10259 → 9308 | 22 → 22 |
| `2e6cffa2` | 52 → **54** | 4317 → 4138 | 29 → 28 |
| `fe744b68` | 30 → 30 | 6224 → 5846 | 16 → 16 |
| `64f48114` | 53 → 53 | 8641 → 7821 | 9 → 9 |
| **`4fea31e2`** | **10 → 5** | 530 → 426 | 4 → 4 |

**Rose on 5, unchanged on 2, fell on exactly one — the smallest capture
in the corpus.** The §5a alarm was a real result on a real capture and it
does not generalise.

**And it settles the merging-versus-loss question the ratio argument in
§3 could only suggest.** Points fall 5.6% while support rows RISE 4.8%
and `poses_solved` RISES by 29. Structure loss cannot raise the number of
cameras that solve — fewer landmarks would starve PnP, which is exactly
the mechanism §5a proposed. The corpus says the opposite happens: the map
holds fewer, better-observed landmarks and MORE cameras resolve against
them.

**VERDICT: KEEP.** With one recorded exception, `4fea31e2`, which is
queued as physical test PT-3.

## 5c. The only known-answer test in the programme — and it says NEUTRAL

Every other number tonight is self-consistency. Synthetic scenes have
exact ground truth, so this is the one place a change can be checked
against a right answer rather than against itself.

`scripts/research/stage1_covisibility/ground_truth_accuracy.py` drives the
REAL engine (`observe()` per frame, then `build()`) over rendered walks
with known camera positions, at both depths, and compares each solved
pose's translation DIRECTION against the true direction. Direction and
not position, because the reconstruction is scale-free and a two-view
translation is defined only up to sign — the same metric
`tests/test_world_builder_pose_accuracy.py` already uses.

**16 paired runs — 8 seeds x {lateral, forward}. MEASURED:**

| | better | same | worse | median delta |
|---|---|---|---|---|
| median direction error | 5 | 9 | 2 | 0.0 |
| worst-case direction error | 6 | 7 | 3 | 0.0 |
| poses_solved | 0 | 16 | 0 | 0 |

**Verdict: no measurable effect on trajectory accuracy in either
direction.**

**An honest correction to my own first reading.** The first four runs
(seeds 1000–1001) came back better on 3 of 4 for worst-case error with a
median delta of −0.32°, and I took that as evidence Stage 1 improves
accuracy. Extending to twelve more runs erased it. **Four paired samples
were not enough to distinguish a real effect from scene-to-scene noise,
and the larger sample is the one to believe.**

So the case for keeping Stage 1 rests on §5b — more solved poses, more
support rows, better multiplicity — and NOT on any accuracy claim. What
this test establishes is the thing that actually mattered: **it does not
degrade the trajectory where the trajectory can be checked.**

### A pre-existing defect this test found

`lateral seed=1006` produces a **median direction error of 84.22° and a
worst of 87.79°** — a nearly perpendicular, confidently wrong pose — and
it does so **identically at both depths**, so it is not caused by
anything in this run. A ~90° error on the *easiest* motion type (lateral
is the best case for two-view geometry) is worth investigating on its
own. It is not investigated here, and it is recorded so it is not lost.

### What is still not known

A spatial comparison of segment 19 at the two depths shows the solved
camera path spanning **87.03** units at DEPTH=1 against **8.77** at
DEPTH=3, with the seed-pair baseline pinned at 1 unit in both — so the
two trajectories differ by roughly 10× in their own gauge, not merely in
point count. Relative to their own camera paths the maps are similar in
shape (point extent / camera span 4.65 vs 6.68).

DEPTH=3's ~0.4 units of camera travel per keyframe is more consistent
with a seed baseline of 1 than DEPTH=1's ~2.7, which would ordinarily be
read as less scale drift — **but there is no ground truth on this corpus
and that reading is not established.** It is recorded because it is the
largest unexplained difference found, not because it supports the
verdict. The verdict rests on `poses_solved`, support rows and
multiplicity, all of which are directly measured.

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
