# World Builder — point quality before coherence

**Date:** 2026-08-26
**Branch:** `world-builder/next-generation` (based on `origin/integration/world-builder-lifecycle-v1` @ `25eb794`)
**Status:** IN IMPLEMENTATION — §2.2 threshold superseded by §2.7 on measured evidence
**Scope:** Tower only. No `ios/` changes. No registration changes.

---

## 0. The claim this document defends

The current user-visible failure is stated as "the result does not look like a
recognizable room", and the assumed cause is that fragments are not registered
into one world. Registration is a real gap and it is documented elsewhere.

**It is not the first cause.** Measured on real persisted worlds, the fragments
are already illegible *before* registration becomes relevant, because the point
clouds contain unconstrained triangulated rays that dominate every bounding box.

Fixing registration on top of these clouds would produce a coherent arrangement
of unreadable fragments.

---

## 1. Evidence

All numbers below were measured on this machine against persisted real worlds
under `tower/data/world_builder/worlds/`, not on synthetic scenes.

### 1.1 The clouds contain unconstrained rays

Reference world `3dd986b1` (session `dd5d13a2`, the 51-segment walk behind the
existing fragmentation research):

```
points beyond 50 baselines (recoverPose's own cull horizon):  1467 / 12023 = 12.2%
segment 6:  590 of 1115 points (53%) beyond 50 baselines, max 33363 baselines
segment 8:  591 of  904 points (65%) beyond 50 baselines, max  4800 baselines
```

A two-view triangulation at 33,363 baselines is not distant geometry. It is a
pair of near-parallel rays whose intersection is numerically arbitrary.

### 1.2 The rays destroy the bounding box

```
world 3dd986b1: full extent 112474.7  vs core (p2-p98) 341.8  ->  329x blowup
```

Per-segment blowup reaches 129x (segment 19, which holds 3033 points — 25% of
the entire world).

### 1.3 The bounding box is what the phone renders against

`ios/Glasses/Workspaces/WorldBuilder/WorldFragmentsView.swift:78-80` fits each
fragment card to the full manifest `bounds`:

```swift
let spanX = Swift.max(bounds.max[0] - bounds.min[0], 1e-6)
let spanZ = Swift.max(bounds.max[2] - bounds.min[2], 1e-6)
let scale = Swift.min(size.width / spanX, size.height / spanZ) * 0.9
```

`bounds` is min/max over all points (`results/world_builder_geometry.py:50-57`),
so the outliers set the zoom. Simulating that projector on a 140pt card:

```
 seg    pts      spanX      spanZ   core px   points landing in one pixel
  19   3033    18942.7   112474.7      1.0p   2908 of 3033
  32   1411     1441.5     5901.7      1.3p   1344
   5   1872     1684.0     3752.1      1.8p   1168
   6   1115     1894.8    18630.4      2.8p    922
```

**9 of 19 drawable fragments render their real geometry into under 20pt of a
140pt card.** The fragments that are legible are the sparse 20-381 point ones.
The phone therefore shows a few thin sparse islands and several near-empty cards
carrying a single dot — which is an accurate description of the reported symptom.

### 1.4 It generalises

Every world on disk carrying real geometry shows it, including `4cae0b26`, the
10,977-point world from the most recent physical live run:

| world | points | bbox blowup | % beyond 50 baselines |
|---|---|---|---|
| 3dd986b1 | 12023 | 329x | 13.2% |
| 4cae0b26 | 10977 | 238x | 3.7% |
| b2ac9808 |  6533 | 129x | 0.6% |
| 748cc5d6 |  1107 |  13x | 30.4% |

n = 4 because the other 111 world directories are empty test artifacts. Replay
is bit-deterministic and a full 29-capture corpus pass costs 194 s, so this set
is cheaply extensible and the A/B in section 5 does extend it.

### 1.5 Why the rays exist

`classical.py` triangulates with **no depth bound, no per-point parallax gate,
and no reprojection gate**. Both triangulation sites keep any point that is
finite with positive depth in both cameras:

- seed pair: `geometry.py:215-218` — finite and `z > 0` in both cameras
- chain extension: `classical.py:718-722` — `isfinite` and `depth_p > 0 and depth_c > 0`

`MIN_TRIANGULATION_ANGLE_DEG = 0.5` (`geometry.py:30`) exists and is applied
**once, to the median angle of the seed pair** (`classical.py:516`), and **not
at all** in `_triangulate_new`. `PNP_REPROJECTION_ERROR_PX = 3.0`
(`classical.py:64`) is RANSAC's inlier threshold for the *pose*, not a filter on
the landmarks that come out of it.

Every landmark is born from exactly two views (`classical.py:726-727`).

**The system already declares 0.5 degrees as its standard for real geometry, and
then retains points violating it by orders of magnitude.**

---

## 2. Design

### 2.1 Principle

Do not introduce a new tuning constant. Enforce the invariant the codebase
already declares, at every site that produces a landmark rather than at one site
on an aggregate.

### 2.2 Gate 1 — per-point triangulation angle

At both triangulation sites, compute the angle subtended at the landmark by the
two camera centres that produced it, and discard the landmark below
`MIN_TRIANGULATION_ANGLE_DEG` (0.5).

This is the existing constant, applied per point instead of to a median.

### 2.3 Gate 2 — per-landmark reprojection error

Reproject each surviving landmark into both source views and discard it above
**`PNP_REPROJECTION_ERROR_PX` (3.0 px, `classical.py:64`)**. This gate does not
exist today in any form.

3.0 px is not a new constant. It is the budget RANSAC already uses to call a pose
an inlier, so a landmark reprojecting worse than the pose that produced it is
inconsistent with that pose by the pipeline's own standard. Per section 2.1, this
reuses a declared invariant rather than inventing a threshold.

### 2.4 Every landmark is assessable — a correction

An earlier draft of this design carried a third category, `unassessable`, for
landmarks in segments with fewer than two solved cameras.

**That state is unreachable and has been removed.** It was an artifact of the
offline analysis in section 1, which reads `poses.json` and genuinely cannot
compute a baseline for a segment holding one solved pose. Inside the backend the
situation does not arise: every landmark is produced from exactly two posed
cameras (`classical.py:726-727`), so both the inter-ray angle and the
reprojection error are always computable at the moment of triangulation.

There are therefore exactly two discard reasons, and no retention category. A
degenerate pair with coincident camera centres yields a zero angle and is
discarded by gate 1, which is the correct outcome rather than a special case.

### 2.5 Reporting — discards are auditable, never silent

Per-segment discard counts by reason are reported in the build manifest:

```
low_parallax        discarded by gate 1 (inter-ray angle below 0.5 deg)
high_reprojection   discarded by gate 2 (reprojection above 3.0 px)
```

Both counts are per segment, and `produced == retained + low_parallax +
high_reprojection` must hold exactly (section 6, test 5).

`BuildResult.diagnostics` already exists at `engine.py:109` and is never
populated (`engine.py:573-584`). This fills it.

Additive to the wire. No contract bump: the geometry contract's stated policy is
that a field an older decoder ignores is not grounds for a version change
(`results/world_builder_geometry.py:189-193`).

### 2.6 Projected effect

Simulated over real worlds, using max-baseline and distance-from-first-camera as
a proxy for the true inter-ray angle:

| gate | 3dd986b1 kept / blowup / legible | 4cae0b26 kept / blowup / legible |
|---|---|---|
| none (today) | 100% / 329x / 10 of 19 | 100% / 238x / 4 of 7 |
| **0.5 deg** | **96.7% / 29x / 17 of 19** | **98.8% / 7x / 7 of 7** |
| 1.0 deg | 89.4% / 15x / 19 of 19 | 96.9% / 5x / 7 of 7 |

**These are projections, not results.** The real gate computes the true inter-ray
angle and will move these numbers. Section 5 is what decides whether the change
is accepted; this table only establishes that the change is worth measuring.

0.5 is chosen over 1.0 because it is the already-declared invariant. 1.0 is a new
constant and is not adopted on the strength of a proxy simulation.

### 2.7 MEASURED CORRECTION — the 0.5 deg bar was wrong

**Superseded: §2.2 and §2.6 above. Recorded, not rewritten, so the
reasoning that failed stays visible.**

§2.6 projected a 1-3% discard from a proxy that used each segment's MAX
camera baseline. The real gate uses the baseline of the specific pair that
produced each landmark, which is smaller. The proxy was optimistic in the
dangerous direction.

Measured against real `support.json` landmark-to-keyframe associations,
recovering the true camera pair behind every landmark:

```
TRUE inter-ray angle, world 3dd986b1 (12,023 landmarks):
  p1 0.0132  p5 0.0634  p10 0.1182  p25 0.2928  p50 0.8904  p75 1.9694  max 149.0

  discarded at 0.10 deg:  1010 / 12023   (8.4%)
  discarded at 0.25 deg:  2598 / 12023  (21.6%)
  discarded at 0.50 deg:  4439 / 12023  (36.9%)
```

A 0.5 deg landmark gate discards **36.9%** of world `3dd986b1` and
**43.9%** of the live-run world `4cae0b26`. Not 1-3%.

Re-running the sweep at TRUE angles puts the knee at 0.05 deg:

| gate | 3dd986b1 kept / blowup / legible | 4cae0b26 kept / blowup / legible |
|---|---|---|
| none | 100.0% / 329x / 10 of 19 | 100.0% / 238x / 4 of 7 |
| 0.05 | 96.1% / 16x / 17 of 19 | 96.4% / 11x / 6 of 7 |
| 0.25 | 78.4% / 9x / 18 of 19 | 79.6% / 7x / 7 of 7 |
| 0.50 | 63.1% / 5x / 19 of 19 | 56.1% / 5x / 7 of 7 |

Nearly all the legibility comes from removing the extreme tail. The extra
33 percentage points of discard buy 16x -> 5x and two fragments.

**This project has already ruled on that trade.** Loss-grace-3 was
rejected for destroying a third of the reconstruction
(`keyframes.py:117-136`). A 0.5 deg landmark gate destroys 37-44%. Same
trade, same verdict.

#### What was actually wrong: two questions were conflated

`MIN_TRIANGULATION_ANGLE_DEG` asks *is this PAIR good enough to trust a
pose from*. At 0.5 deg that is a 26% depth error -- imprecise, but real
geometry.

The landmark gate must ask a different question: *is this a measurement at
all*. That bar is derivable rather than chosen. For two-view triangulation

```
    sigma_d / d  =  sigma_px / (f * theta)
```

so an error bar as wide as the measurement itself -- one that reaches
infinity -- sits at `theta = sigma_px / f`. Using the pipeline's own
`RANSAC_THRESHOLD_PX` (1.0) and the real calibration (f ~ 438):

```
    theta_min = 0.1308 deg      (exactly 100% depth uncertainty)
```

Implemented as `geometry.min_parallax_deg(camera_matrix)`. It is **better**
than the constant it replaces on the criterion §2.1 actually cared about:
it is derived from existing constants, and it scales with focal length, so
it does not silently change meaning if delivered resolution moves. A
garbage camera matrix falls back to `MIN_TRIANGULATION_ANGLE_DEG` rather
than deriving a zero bar that would admit every unconstrained ray.

**The §2.1 principle survives; the §2.2 application of it did not.**

---

---

## 3. What this explicitly does NOT do

- No cross-segment registration work.
- No tracking or fragmentation levers (`min_survival_ratio`, chained tracking,
  hold-on-bad-hop remain unshipped and unmeasured through the full solve).
- No `ios/` changes.
- No change to `bounds` semantics. `bounds` stays min/max over the points that
  are actually shipped; it narrows because the cloud is cleaner, not because the
  reporting rule changed.

---

## 4. iOS implications

**No iOS change is required for this slice.**

The manifest gains additive fields an older decoder ignores, and `bounds`
narrows. That is precisely what makes the existing fragment cards frame
correctly with no Swift change — the renderer already fits to `bounds`.

This is recorded in the Mac handoff as FYI, not as a required change.

---

## 5. Acceptance criteria

The change is accepted only on an 8-capture A/B, full metric report.

### 5.1 Instrument

A new `scripts/world_builder_corpus_benchmark.py`:

- drives `engine.observe` / `engine.build` over a **pinned** capture-id list
- replays via the `--follow-capture` journal path, which preserves `source_seq`
  and `received_at`; `--frames` fabricates both (`world_build_session.py:130-133`)
  and must not be used
- takes `--label`, writes one JSON result per run
- provides `--compare A.json B.json`
- calls `cv2.setRNGSeed` before any work. Replay is empirically bit-deterministic
  across and within processes, but `classical.py:605-607` asserts the opposite,
  so determinism is pinned rather than assumed.

### 5.2 Pinned capture set

Ranked for discriminating power, not size. ~112 s per arm.

| # | capture | role |
|---|---|---|
| 1 | `e1c52b9f` | best-behaved walk (72% poses solved, 22909 points, 5 segments) — the sensitivity control |
| 2 | `22e9d428` | largest complete capture, 33 segments — fragmentation stress |
| 3 | `b35d8ab8` | worst fragmentation (43 segments) |
| 4 | `20ce3c23` | long walk that mostly held tracking |
| 5 | `2e6cffa2` | high-motion / low-yield failure case |
| 6 | `fe744b68` | best points-per-frame, fast inner loop |
| 7 | `64f48114` | cheapest multi-segment geometry |
| 8 | `4fea31e2` | **zero-yield control** — 0 solved poses, 0 points |

The zero-yield control is not optional. A benchmark with no honest zero in it
cannot distinguish "improved" from "started fabricating".

### 5.3 Metrics — all reported together, every run

segments, keyframes, poses_solved, poses_refused, points, points_discarded by
reason, bbox blowup, fragment legibility count, processing time, per-capture
variance.

**Points are never reported alone.** The project has already shipped one change
that improved segment count while costing a third of the reconstruction
(`keyframes.py:117-136`); the same trap in the opposite direction is a gate that
improves blowup by discarding real geometry.

### 5.4 Pass condition

Arm A (unchanged code) establishes the baseline; arm B must satisfy all of:

- **median bbox blowup across the geometry-bearing captures falls by at least
  5x** relative to arm A
- **fragment legibility** (fragments whose p2-p98 core occupies >= 20pt of a
  140pt card, per the section 1.3 projector) **rises, and falls on no capture**
- `poses_solved` falls on **no** capture, and the corpus total does not fall
- `segments` and `keyframes` are **unchanged on every capture** — these gates run
  after pose solving and must not perturb tracking or selection at all. Any
  movement here means the change leaked outside its intended surface.
- `points` falls by exactly the discarded count, per segment
- the zero-yield control `4fea31e2` still yields 0 poses and 0 points

Failure to hold any of these is a refusal, not a threshold to retune.

The `segments`/`keyframes` invariance clause is the strongest single check in
this list: it is the one that catches a change doing something other than what
this design says it does.

Failure to hold any of these is a refusal, not a threshold to retune.

---

## 6. Testing

TDD throughout.

1. **Characterisation first.** Pin today's behaviour: a synthetic near-parallel
   ray pair currently survives triangulation. This test passes before the change
   and inverts after it.
2. **Unit tests per gate**, at both triangulation sites.
3. **Adversarial test, required:** a legitimately distant but well-triangulated
   point must **survive** both gates. Without it, a gate that discards everything
   satisfies every other test in this list.
4. **Degenerate-pair test:** a pair with coincident camera centres yields a zero
   inter-ray angle and is discarded by gate 1 rather than raising, dividing by
   zero, or producing a non-finite angle.
5. **Accounting test:** `produced == retained + low_parallax + high_reprojection`,
   per segment, on real replayed data — not only on synthetic fixtures.
6. Full World Builder suite. Baseline on this worktree is 402 passed, 10 skipped.

---

## 7. Deferred — coherence phase, recorded so they are not lost

Both are real, both are out of scope here.

### 7.1 Reciprocity checks scale only

`scripts/world_registration.py` `admit()` compares the two directions on exactly
one quantity: `forward.scale * reverse.scale` (`:296-307`, gated `:723-727`). It
never compares `forward.rotation` against `reverse.rotation.T`, never compares
translations, and never checks that the composition is near identity. The reverse
fit contributes one scalar and is then discarded (`:997-1000`).

**A pair agreeing on scale to 1% while disagreeing 40 degrees in rotation is
admitted today.** Both rotations are already in hand at `:674`. This is close to
free and it is the exact failure class the module exists to prevent.

### 7.2 Placement changes cannot invalidate the iOS cache

`content_hash` deliberately excludes the transform
(`results/world_builder_geometry.py:44-47`), `geometry_revision` is a rollup of
content hashes only (`:89-97`), and the status channel's `geometry.revision` is
computed from manifest fields containing no placement
(`results/world_builder.py:1106-1115`). `WorldGeometryDecoder.chunk` does not
read `transform_to_world` at all.

The day registration ships, iOS caches and draws stale placements, and
`test_no_segment_claims_registration` would not catch it — it asserts only that
the fields are still constants.

### 7.3 Also recorded

- `world_registration.py` crashes (exit 1, uncaught `cv2.error` from
  `solvePnPRansac` SQPNP at `:436`) on the 33-segment world from `22e9d428` —
  i.e. on precisely the fragmented captures a benchmark most needs.
- Refusals are a cascade: the first non-solved pose latches `chain.broken` and
  every later keyframe is refused without running ORB
  (`classical.py:279-293`). With 23 segments, >=496 of 519 refusals are flood
  fill from ~23 real decisions. The manifest cannot distinguish those two worlds.

---

## 8. Risks and what would disprove this

- **The proxy is wrong.** Section 2.6 uses max-baseline and
  distance-from-first-camera, not the true inter-ray angle. If the real gate
  discards far more than 1-3%, the trade changes and 0.5 must be re-argued on
  measured evidence rather than kept out of loyalty to the constant.
- **Legibility is a proxy for recognisability.** A fragment occupying 20pt of a
  140pt card is legible; that does not make it recognisable as a room. This slice
  removes a blocker. It does not on its own deliver the product bar, and must not
  be reported as though it does.
- **Physical validation is still outstanding.** Nothing here is settled by
  replay. The product claim requires a real walk, and this document makes no
  physical claim.
