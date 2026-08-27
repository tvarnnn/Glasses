# Adversarial review of the overnight World Builder run

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation`.
**Range reviewed:** `65f64a4..68adb87`.
**Reviewer stance:** assume the implementation is wrong; try to break it.

Every number below is labelled **MEASURED** (produced by me, this
review), **QUOTED** (taken from the run's own docs, not re-derived), or
**ESTIMATED**. There is **no ground truth on the pinned corpus**; every
corpus number is self-reported by the pipeline under test. Ground-truth
claims come only from the synthetic scenes, which are rendered by a
perfect pinhole and say nothing about the Ray-Ban camera.

Verification code: `tower/scripts/research/stage_adversarial/`.

---

## VERDICT

**SAFE WITH SPECIFIED CORRECTIONS.**

- **Stage 1 (`EXTEND_REFERENCE_DEPTH = 3`): KEEP.** I reproduced the
  corpus A/B independently and got the coordinator's numbers exactly. I
  then attacked the "duplicates merging, not structure lost" claim from
  four directions and could not break it. A known-answer test at ~11x
  the sample the run used shows no accuracy degradation.
- **The `homography_ratio` model check: KEEP.** It survived every attack
  I made on it.
- **The feature-starvation gate refusal: the DECISION stands, the
  DOCUMENT does not.** Its central claim is false as stated and must be
  corrected before a human reads it.
- **Two corrections are required before hand-off** (F2, F3 below), and
  one is a repo-hygiene blocker.

**Separately, and more important than anything in the diff:** I found a
**live accuracy failure in shipped code**, unrelated to tonight's
change, in which JPEG compression flips a reconstruction ~88 degrees.
It passes every existing gate. A discriminator that separates it
perfectly is already computed and thrown away. See **F1**.

---

## What I did to try to break the branch

| Attack | Result |
|---|---|
| Independent full-corpus A/B, both depths | Reproduced the run's numbers **exactly** |
| Known-answer trajectory error vs ground truth, 24 paired runs | No degradation |
| Pure rotation: does guided matching invent associations? | **0 admitted**, 5 seeds |
| Tighter reprojection bar on admitted rows | Survived |
| Geometrically impossible sightings in `support.json` | **Found 1,002 new ones**; measured them; benign |
| Determinism, 3 fresh processes | Byte-identical |
| Bounded state, walks of 10/20/40/60 | Flat |
| Neutralize check (disable the mechanism) | 3 tests fail correctly |
| r_H on healthy pairs / bad pair | Survived |
| Independent measure of ORB features on accepted keyframes | **Contradicts the gate doc** |

---

## My independent corpus A/B (the deciding measurement)

**MEASURED.** All 8 pinned captures, full engine replay,
`--no-registration --no-reprojection --no-determinism`, corpus repeats
disabled.

**Methodology note that matters.** The coordinator was toggling
`EXTEND_REFERENCE_DEPTH` in `classical.py` concurrently with my run. I
did **not** edit the file. All three read sites reference the module
global at call time (`classical.py:313`, `:517`, `:1303`), so
`scripts/research/stage_adversarial/ab_depth.py` binds the value
**in-process after import** and stamps the effective value into the
output. No subprocesses are spawned, so no child could re-read a moving
file. This is exactly equivalent to editing the constant and is immune
to the race. I validated the instrument first against a known single
capture (`4fea31e2` at DEPTH=1: solved 10, points 530, two-view 84.2% —
matched).

| metric | DEPTH=1 | DEPTH=3 | delta |
|---|---|---|---|
| segments | 230 | 232 | +2 |
| keyframes | 1712 | 1712 | 0 |
| **poses_solved** | **591** | **620** | **+29** |
| poses_refused | 891 | 860 | −31 |
| **points** | **75369** | **71122** | **−4247 (−5.6%)** |
| support_rows | 186778 | 195752 | +8974 |
| exactly-2-view | 70.38% | 61.70% | −8.68 pp |
| ≥3-view | 29.62% | 38.30% | +8.68 pp |
| observations/landmark | 2.478 | 2.738 | +0.26 |
| legible_fragments | 91 | 97 | +6 |
| segments_with_geometry | 102 | 105 | +3 |

The DEPTH=1 control reproduces `baseline_HEAD_d3d24b5.json` **exactly**
(230 / 1712 / 591 / 75369 / 70.4%). The treatment matches the
coordinator's independently-run numbers on every field. Two agents, two
harness invocations, identical results.

### Does the point loss mean structure was lost?

This is the claim the whole stage rests on, it is an inference, and
there is no ground truth to settle it. Four attacks:

1. **Poses.** Structure loss starves PnP — fewer landmarks means fewer
   3-D points for later frames to solve against. `poses_solved` **rose
   by 29** and `poses_refused` **fell by 31**. Losing real structure
   cannot raise the number of cameras that solve. *(MEASURED.)*
2. **Coverage, not just count.** `legible_fragments` +6 and
   `segments_with_geometry` +3 — more of the corpus produces drawable
   geometry, not less. A map that thinned in a region would lose
   fragments. *(MEASURED.)*
3. **Known-answer geometry.** On synthetic walks with ground-truth
   cameras, points fell 91,251 → 80,117 (−12.2%) while support rows rose
   345,643 → 382,771 (+10.7%) and **solved cameras were 540 → 540,
   exactly unchanged**. Same signature as the corpus, in a setting where
   the true structure is fixed and known to be present. *(MEASURED.)*
4. **Trajectory error against truth.** Below.

The claim **survives**. The point count falls because sightings that
previously created a second landmark now attach to the first.

### Known-answer trajectory accuracy (closes the run's open weakness)

The coordinator's ground-truth test used 8-frame walks yielding **3
solved poses per run** and reported NEUTRAL, flagging the thin sample as
its weakness. I ran longer walks: **24 paired runs, 14–30 solved poses
each, 540 solved cameras total — about 11x their sample.** Metric is
absolute trajectory error of camera centres after the best similarity
alignment (`umeyama`), normalised by true path length, plus a per-step
scale-drift coefficient of variation.

Camera centres are `-R.T @ t`: the backend returns OpenCV's world→camera
`(R, t)`, and `engine._pose_row` records that shipping the raw `t`
mirrors every camera through the origin. Comparing raw `t` to truth
would have reproduced that bug inside the measurement.

**MEASURED:**

| metric | DEPTH=3 better | worse | median D1 → D3 | sign test |
|---|---|---|---|---|
| ATE / path length | 15 / 24 | 9 | 0.0884 → 0.0519 | p = 0.31 (Wilcoxon p = 0.084) |
| scale-drift CV | 14 / 24 | 10 | 0.479 → 0.385 | p = 0.54 |

**Neither is significant at p < 0.05.** The direction is mildly
favourable and the medians improve, but I will not claim an accuracy
gain. What this **does** establish, at 11x the previous sample, is that
**DEPTH=3 does not degrade trajectory accuracy**. That confirms the
coordinator's NEUTRAL verdict and closes the weakness they named. Their
retraction of the earlier "improves accuracy" reading was correct; I
found no accuracy claim surviving in the code comments or docs.

**On the 87.03 vs 8.77 gauge puzzle the coordinator could not resolve:**
their reasoning that DEPTH=3's ~0.4 units/keyframe "looks more
self-consistent with a unit seed baseline" does not hold. If the seed
pair defines ~1 unit of travel per keyframe step, then 0.4 undershoots
by 2.5x while 2.7 overshoots by 2.7x — **comparably wrong in opposite
directions**, not one better. The scale-drift CV above is the right
instrument for that question, and it says the two are not separable.

---

## Findings, ranked by severity

### F1 — SEVERE, PRE-EXISTING: JPEG compression flips a reconstruction ~88°, and every gate passes it

Not caused by this run. Found while characterising the `lateral
seed=1006` outlier. The coordinator converged on the same phenomenon
independently (their working-tree doc is renamed
`2026-08-27-two-percent-reconstruct-perpendicular.md`, matching my 2.5%
prevalence). What I add is the **mechanism and a free discriminator**.

**MEASURED**, rendered lateral strafe, frames (0, 2), the pair the engine
actually seeds from:

| seed | JPEG | epipolar inliers | cheirality inliers | ch/epi | direction error |
|---|---|---|---|---|---|
| 1006 | off | 870 | 870 | 1.000 | **0.34°** |
| 1006 | **on (q90)** | 804 | 279 | **0.347** | **87.12°** |
| 1018 | off | 939 | 939 | 1.000 | **0.21°** |
| 1018 | **on (q90)** | 823 | 264 | **0.321** | **88.27°** |
| 1000 | on | 910 | 910 | 1.000 | 0.21° |

`recoverPose` chooses among the four decompositions of E by counting
points in front of both cameras. JPEG perturbs the correspondences just
enough that it selects the **wrong** decomposition and returns a
confident baseline rotated ~88°. The trajectory that follows is
internally coherent — a straight line — simply pointing the wrong way,
which is why nothing downstream complains. Only pair (0, 2) is
affected; (0,1) and (0,3) are fine at both settings.

This matters in production because the engine persists JPEG and
reconstructs from those bytes.

**Prevalence: 2 of 80 synthetic seed pairs (2.5%).** Both are *lateral*
motion — the best case for two-view geometry. **Both pass the current
gate**: `cheirality_ratio = inliers/matches` scores 0.302 and 0.275
against `MIN_INLIER_RATIO = 0.05`, six times the threshold.

**A discriminator already exists and is discarded.** `classical.py`
computes both `epipolar_inliers` and cheirality `inliers` at lines
664–673. Their ratio separates cleanly across 80 pairs:

- good (≤30° error): **min 0.976, median 1.000**
- bad (>30° error): **min 0.321, max 0.347**
- **worst good 0.9755 vs best bad 0.3470 — CLEAN, no overlap**

`r_h` does **not** separate them (good 0.454–0.494; bad 0.474–0.477,
sitting inside the good range) — an independent confirmation of the
codebase's own documented finding that r_H separates nothing in a
plane-dominated room.

**Recommendation:** treat as a real defect in shipped code. A gate on
`cheirality_inliers / epipolar_inliers` (anywhere in 0.5–0.95) would
have refused both failures and none of the 78 good pairs on this
sample. Note the existing code comment already warns that raising the
`inliers/matches` ratio would falsely refuse genuine short-baseline
strafes — normalising by *epipolar* inliers avoids exactly that.
Prevalence on real footage is **unknown**: no ground truth exists there.

### F2 — HIGH (hygiene, blocks clean hand-off): the committed Stage 0 control baseline is contaminated, and the working tree overwrites it with treatment numbers

Two separate problems in one file.

**(a) The working tree has overwritten the control with a treatment
run.** `git status` shows `baseline_HEAD_d3d24b5.json` modified
(154 insertions / 589 deletions, uncommitted). The committed file is the
DEPTH=1 control at commit `d3d24b5`. The working-tree version contains
`segments: 232, poses_solved: 620` — the **DEPTH=3** numbers — generated
at commit `beb4719`, which is not in the reviewed range. A human opening
that filename tomorrow expecting the control gets the treatment. It is
uncommitted and recoverable with `git checkout`, but it must not be
handed over as is.

**(b) The committed version's stability section is itself an artifact.**
It records a corpus-rerun mismatch: `run1.poses_solved = 112,
run0.poses_solved = 131` on capture `22e9d428`. That reads as a ±19-pose
noise floor, which would swamp the +29 corpus signal. **It is not
pipeline nondeterminism.** My A/B establishes 112 = DEPTH 1 and
131 = DEPTH 3 (MEASURED). `corpus_repeat_check` re-runs the harness in
**fresh subprocesses**, which re-read `classical.py` **from disk** — so
that run straddled a toggle of the constant and measured a moving file,
not the pipeline.

The real noise floor is zero: my determinism check (below) returns
byte-identical output across 3 fresh processes. **The +29 is real.**
But the committed artifact currently misrepresents the noise floor, and
whoever reads it next will draw the wrong conclusion.

**Recommendation:** restore the control file, regenerate it with the
constant held still, and record in it that subprocess-based repeats are
invalid while the constant is being toggled.

### F3 — MEDIUM: the feature-starvation refusal doc's central claim is false as stated

The doc says, in bold: *"This is conclusive by construction, not by
inference... Therefore no keyframe accepted at HEAD is
feature-starved."*

**MEASURED, independently:** I ran the same detector
(`geometry.detect_and_describe`) over the **1,712 keyframe images the
engine actually persisted** during a HEAD replay — exactly the corpus
total, restricted to the 8 pinned captures. (My first attempt globbed
1,729 images because `run_controls` builds extra synthetic worlds in the
same scratch root; that version is corrected and the numbers below
exclude them.)

- **22 accepted keyframes carry fewer than 15 ORB features.**
- **Minimum: 0 features.** 27 below 20; 85 below 100.

**Why the doc's reasoning is unsound.** The accept decision in
`engine.observe()` completes *before* `_persist_keyframe`, which is
where redaction happens — and both `build()` and the live path decode
the **redacted** bytes (`engine.py:342–353` says so explicitly). A gate
placed "after all existing gates" therefore ran on the **pre-redaction**
frame while the reconstruction consumes the **post-redaction** one. The
gate could not have seen this population. "Conclusive by construction"
does not hold.

**In fairness, the practical conclusion survives.** Of those 22:

- **0 carry a solved pose. 0 contribute a single support row.**
- 16 are `unavailable`, **6 are segment anchors** that resolve nothing.

So the gate would still buy no geometry, and removing it was still
right. But the population is **not gone** — it is present and wasteful,
including 6 wasted segment anchors, which is the doc's own §1 harm
("installs a tracking reference nothing can track against") reproduced
at HEAD rather than eliminated.

**Recommendation:** keep the decision; rewrite §2 and §3. The honest
claim is "no accepted keyframe *contributes geometry* while starved",
not "no accepted keyframe is starved". Note that a gate on the redacted
image would be gating a different and more relevant quantity.

### F4 — MEDIUM-LOW, NEW AND UNREPORTED: `support.json` gains 1,002 geometrically impossible rows

**MEASURED:** `duplicate_view_support_rows` goes **0 → 1,002**
corpus-wide. Zero in all 8 captures at DEPTH=1; non-zero in all 8 at
DEPTH=3. This is one landmark claimed to be seen by **two different
features in the same keyframe** — a point projects to exactly one pixel,
so both claims cannot be true. No document on the branch mentions it.

Cause: `_reobserve_against_pose` tracks `claimed` by *current feature
index*, preventing one feature being bound twice, but nothing prevents
two different current features being admitted for the **same landmark**.

**I attacked this as a poisoning risk and it came back benign.**
Measured separation between the two features, via the same
`world_registration.read_segments` reader registration itself uses:

- median **1.11 px**, mean 1.36 px, p90 2.68 px, max 6.23 px
- 77.3% within 2 px, **99.9% within 6 px**

These are two ORB detections of one corner, not a landmark claimed at
two different places. The 6 px bound follows from both rows passing a
3 px test against the same pose. Registration's reader keys on
`(frame, feature)`, so it does not overwrite. **Not dangerous.**

Two honest caveats: the `+8,974` support-row headline includes ~1,002
rows that add **no new view**; and the ≥3-view improvement is *not*
inflated by this, because the harness counts **distinct keyframe views**
per landmark, so the +8.68 pp survives intact.

**Recommendation:** disclose it in the Stage 1 results; do not block on
it. A one-line `if landmark in admitted.values()` guard would remove it.

### F5 — LOW: a test file's docstring contradicts the code it guards

`tests/test_world_builder_reference_depth.py:1–24` still states the
abandoned design:

> * it runs AFTER the pose is solved, so it cannot change the pose;
> * **its output goes to `support` and NOT to `observed`**, so it cannot
>   change the next keyframe's pose either.
> **Both halves are asserted here rather than described**

The shipped code does the opposite — `reobserved.update(guided)` — and
the class docstring 130 lines below correctly says so ("This change is
NOT pose-neutral and the first version's claim that it was is wrong").
The file therefore contains both the claim and its retraction, and the
stale half is the one a reader meets first. The "both halves are
asserted here" sentence is also untrue: no test asserts pose-neutrality.

Production comments in `classical.py` are **correct** — I checked all
three pose-neutrality mentions (lines 85, 918, 936) and each accurately
describes the merge and its cost.

### F6 — LOW: the `forget_before` memory claim is incomplete

The docstring says retained state goes ~0.15 MB → ~0.45 MB. The
**ratio** is right — **MEASURED**, the `observed` dict grows 0.010 MB →
0.034 MB (3.4x) on a synthetic walk, and is **flat in walk length**
(max length ~1,089 at DEPTH=1 and ~3,670 at DEPTH=3 across walks of 10,
20, 40 and 60 keyframes). The bounded-state claim **holds**.

But the note accounts only for `observed`. `older_features` additionally
retains DEPTH−1 full ORB descriptor arrays — **MEASURED ~0.09 MB**,
about 2.6x the `observed` dict itself — which the docstring does not
mention. Still constant, still small; the claim is understated rather
than wrong.

### F7 — LOW: a shipped test asserts a property that does not hold on real data

`test_widening_adds_no_feature_bound_to_two_landmarks` asserts
`wide <= narrow`. It passes on the synthetic walk. On the **real
corpus**, `features_bound_to_more_than_one_landmark` rises **803 → 809**
(MEASURED). Merging guided rows into `observed` reduces this failure
mode enormously versus the withheld variant (the run's QUOTED 2 → 147),
but it does not eliminate the increase. The test defends a slightly
stronger property than the code delivers.

---

## Claims I tried to break and could not

- **Guided matching under pure rotation.** The sharpest false-association
  attack: zero baseline, no new structure should exist. **0 associations
  admitted across 5 seeds** (MEASURED), and fewer than 3 cameras solve,
  so the degeneracy gate holds. The mechanism cannot fire without
  triangulated landmarks to re-observe, and pure rotation produces none.
- **The 3.0 px admission bar.** The bar is not a new invented number: it
  is `PNP_REPROJECTION_ERROR_PX`, the same threshold `solvePnPRansac`
  used to select inliers for that very pose. Guided rows are tested
  **out-of-sample** against a pose fitted to other data, which is a
  stricter test than the inliers themselves faced. The claim that they
  are "published on the same terms" is fair.
- **Determinism at the shipped default.** 3 fresh processes, DEPTH=3:
  `points_json_byte_identical: true`, `support_json_byte_identical:
  true`, `max_abs_delta_point: 0.0`, `max_abs_delta_pose: 0.0`, verdict
  **DETERMINISTIC** (MEASURED). The fingerprint includes full XYZ and
  all poses, not just scalars.
- **`extend()` / `estimate_window()` equivalence.** The zero-tolerance
  guard `tests/test_world_builder_incremental.py` passes at the shipped
  default. I verified the two paths construct the same reference set:
  `estimate_window` uses `range(previous-1, current-1-DEPTH, -1)` and
  the chain path pushes `(index-1, previous_features)` capped at
  DEPTH−1; both yield references `{previous, previous-1, previous-2}`.
  `forget_before` retains `key[0] >= index-(DEPTH-1)`, exactly the
  frames the next step reads.
- **Hidden cross-segment state.** `reset()` allocates a fresh `_Chain`,
  so `older_features` cannot leak between segments. `__slots__` includes
  it. Checked because a missed reset here would be silent.
- **Neutralize check, redone independently.** Forcing `guided = {}` via a
  pytest plugin (no production edit) fails exactly 3 tests, including
  `test_widening_moves_mass_out_of_the_two_view_bucket`. The mechanism
  is genuinely defended. Note the depth-parameterised tests monkeypatch
  the depth themselves, so they do **not** defend the shipped default —
  but `tests/test_world_builder_support_views.py` imports the real
  constant, so the default is covered.
- **The r_H fix.** 9/9 healthy synthetic pairs still produce a ratio
  (0.481–0.497, inside the docstring's documented 0.471–0.499 saturation
  band) — the field is **not** silently disabled. On the known-bad pair
  (`22e9d428`, keyframes `00000345` × `00001824`) **8/8 fresh processes
  return `None`**, deterministically, and I reproduced the 242-match
  figure exactly (MEASURED). The fix is correct and minimal.

## Contract drift reaching iOS

- `support.json` gains 1,002 duplicate-view rows and 8,974 rows overall
  (F4) — shape unchanged, size +4.8%.
- `points` falls 5.6% corpus-wide. **Reported honestly** everywhere I
  checked, including the uncommitted §5a of the Stage 1 results, which
  leads with "Added after §2–§5 were written, and it changes the
  verdict." No spin found.
- `r_h` now returns `None` where it previously returned garbage. Values
  on healthy pairs are unchanged in distribution.
- Segment count 230 → 232. `poses` and `points` schemas unchanged.

## Production/research contamination

None found. `tower/tower/` contains only the two intended edits; nothing
research-shaped leaked in. `git diff` on `classical.py` is empty
(line-endings only) and the constant is at **3**, verified after all my
runs. My in-process patching means I never wrote to it.

## Repo hygiene

- **F2 is the blocker.** Also uncommitted at review time:
  `measure_baseline.py` (+60/−10), a renamed research doc, and a new
  untracked `stage1_covisibility/wrong_basin_sweep.py` — the coordinator
  working concurrently, not defects, but the tree is not clean.
- ~85k lines added, dominated by research JSON
  (`matcher_showdown.json` 15k lines, `covisibility_orb.json` 14k).
  Large but text, under `scripts/research/`, and defensible as branch
  evidence. No binaries committed.

---

## What I would do before showing this to anyone

1. **Restore `baseline_HEAD_d3d24b5.json`** and regenerate the control
   with the constant held still (F2). Blocker.
2. **Rewrite §2–§3 of the gate-refusal doc** (F3). It currently states
   something false in bold.
3. **Fix the stale docstring** in `test_world_builder_reference_depth.py`
   (F5).
4. **Add one line to the Stage 1 results** disclosing the 1,002
   duplicate-view rows and that they are benign (F4).
5. **Open F1 as its own defect.** It is worth more than the whole diff.
