# Overnight World Builder SLAM implementation run — 2026-08-27

**Branch:** `world-builder/next-generation`
**Starting commit:** `65f64a4` ("test: the branch end state, controls passing")
**Ending commit:** _(filled at close)_
**Commits added:** 12 · **Production files touched: 2** (+256 / −10)
**Working tree / push status:** _(filled at close)_

---

## 1. Executive summary

The night's most valuable output is not a feature. It is that **three
separate recommendations from the modern-SLAM research package rested on
measurements taken from a pipeline that no longer exists**, and that **a
large piece of the architecture the package said was missing is already
built and simply never called**.

One production improvement was implemented and kept on corpus evidence.
One was implemented, measured, and **removed** because it provably never
fires. One real non-deterministic defect was fixed at source. No
architectural bet was placed that the evidence did not support, and the
expensive one available (wiring up registration) was declined with
reasons.

**Nothing here is physically validated.** No one wore the glasses.

## 2. Claim types, because these are different claims

- **IMPLEMENTED** — code exists, suite green.
- **BENCHMARK-VALIDATED** — measured on real Ray-Ban frames against a control.
- **REPLAY-VALIDATED** — measured through the real engine end to end.
- **KNOWN-ANSWER VALIDATED** — measured against synthetic ground truth.
- **PHYSICALLY VALIDATED** — a human wore the glasses. **Nothing reaches this.**

**There is no ground truth on this corpus.** No surveyed geometry, no
reference trajectory, no metric scale. Every real-footage number is
comparative or self-consistency.

## 3. Research consumed

The revision-2 synthesis, its three lane reports and its adversarial
review — 5,798 lines — preserved onto this branch in `d3d24b5` because
they were sitting UNTRACKED on the integration branch, one `git clean`
from gone.

## 4. Three research findings that did not survive contact

### 4.1 Every persisted world predates this branch's engine

`engine.py:775` writes `points_discarded` unconditionally and says why:
*"absent would mean 'this build predates the counter'."* **MEASURED: all
19 derived manifests on disk lack it.** So the 66.1%/67.2% two-view
figures the research built its case on — and my own reproduction of
67.2% — describe the *previous* pipeline.

**True HEAD baseline: exactly-2-view 70.38%, ≥3-view 29.62%.**

**Rule for successors: before acting on anything read off `data/`, check
`points_discarded` in the manifest.**

### 4.2 The Stage 1 stop/go was unmeetable, then nearly already met

Revision 1 demanded median covisibility degree > 15 where the all-pairs
*oracle* reaches 14.0. And world `4cae0b26` already sat at 47.5% ≥3-view
with no change at all, against a "> 50%" bar. **Capture content moves
this quantity nearly as much as an algorithm does.** Replaced with a
paired per-capture criterion.

### 4.3 Registration is not missing — it is built, and nothing calls it

`tower/scripts/world_registration.py` is **1,755 lines**: `Sim3`,
`MutualEvidence` (structurally unconstructable from anything but two
solves in OPPOSITE directions), scale and rotation reciprocity,
`span_over_depth` pre-refusal, Huber refinement, cycle consistency,
digest-bound persistence. The serving layer already reads placements and
already refuses any whose `input_digest` does not match the build served.

**MEASURED, read-only:** 3 of 51 segments registered, **31.1% of points**,
2 admitted pairs of 143 — an exact reproduction of prior in-repo research.
**No module under `tower/tower/` imports it.**

The research package never opened the file — three mentions in 5,798
lines — and `MutualEvidence` existed on the integration branch too, so
this was a **coverage gap, not staleness**.

## 5. Production changes

### 5.1 KEPT — `EXTEND_REFERENCE_DEPTH` + `_reobserve_against_pose`

`backends/classical.py`. `_extend` now looks back 3 accepted keyframes
for further sightings of landmarks already in the map, admitting one only
if it reprojects within `PNP_REPROJECTION_ERROR_PX` through the
just-solved pose, cheirality first. Threshold reused, not invented: it is
what `solvePnPRansac` used to pick inliers for that same pose.

This is ORB-SLAM's guided re-observation (`SearchByProjection`)
reimplemented — **not** the multi-reference PnP the roadmap proposed.

**Corpus A/B, all 8 pinned captures, full engine replay** — the deciding
measurement:

| metric | DEPTH=1 | DEPTH=3 | delta |
|---|---|---|---|
| **poses_solved** | 591 | **620** | **+29** |
| poses_refused | 891 | 860 | −31 |
| points | 75,369 | 71,122 | −4,247 |
| **support rows** | 186,778 | **195,752** | **+8,974** |
| exactly-2-view | 70.38% | **61.70%** | **−8.68 pp** |
| ≥3-view | 29.62% | **38.30%** | **+8.68 pp** |
| segments | 230 | 232 | +2 |
| keyframes | 1,712 | 1,712 | 0 |

Solved rose on 5 captures, unchanged on 2, **fell on one**.

Points falling while support rows rise **and solved poses rise** is
duplicate landmarks merging: structure loss cannot raise the number of
cameras that resolve, because fewer landmarks starve PnP.

**Known-answer validation** (synthetic ground truth, the only place a
right answer exists): **24 paired runs, `poses_solved` unchanged on 24 of
24**; direction error better on 9, same on 11, worse on 4. **Neutral —
it does not degrade the trajectory where the trajectory can be checked.**

### 5.2 KEPT — `homography_ratio` model check

`geometry.py`. Summing RANSAC's mask without checking a model was
produced read **uninitialised memory**. Reproduced on a real pair
(`22e9d428`, keyframes `00000345` × `00001824`): keyframe B carries 5 ORB
features, 242 Lowe matches land on 3 distinct locations, neither F nor H
can fit, and the mask returned 46 distinct values summing to **9,552 on
242 elements** — where a binary mask cannot exceed 242.

**Non-deterministic across fresh processes** (30/40, 34/40, 37/40 corrupt
in three runs) and self-healing within a warm one. After the fix, 8/8
fresh processes return `None`. Three regression tests; the neutralize
check shows the unfixed code returns `0.0` — "could not fit" reported as
"ratio is zero".

### 5.3 REMOVED — the feature-starvation admission gate

Built on real evidence (10 keyframes under 20 ORB features, minimum
**zero**, median black fraction 0.825, none contributing a support row,
two of them segment anchors) with an arithmetic threshold. **It never
fired: 0 rejections corpus-wide, 1,712 keyframes accepted either way.**

Conclusive by construction — the gate was live, so no keyframe accepted
at HEAD is feature-starved. HEAD's existing blur and motion gates already
reject that population; the evidence came from a world built by the
previous engine. Removed rather than kept, because it costs an ORB
detection per accepted keyframe to never execute. Queued as PT-2.

## 6. Why registration was NOT wired in

MEASURED at HEAD: **2 of 8 captures register anything**; registration
costs **472.3 s against 219.0 s** for all replay+build (**2.2×**). And
**135 of 141 refusals are `span_over_depth`** — "the wearer stood still",
cameras spanning 2–6% of scene depth.

Two independent lines of work converged on that statistic and that limit.
**The binding constraint is the capture.** So the correct next action is
PT-1, not automating a pass that refuses 96% of pairs.

## 7. The single most important pattern found

Ranking every capture by how static it is explains the one regression
**and** the whole project's ceiling:

| capture | insufficient_motion % | Δ poses_solved |
|---|---|---|
| `22e9d428` | **49.6%** | **+19** |
| `20ce3c23` | **65.9%** | **+10** |
| … | … | … |
| **`4fea31e2`** | **96.4%** | **−5** |

Largest gains on the captures with the most motion; the only loss on the
most static. Guided re-observation needs baseline; registration needs
baseline; scale needs baseline. **Everything measured tonight points at
the same thing, and PT-1 is the experiment that addresses it.**

## 8. Metrics

**Stage 0 control** (`scripts/research/stage0_baseline/`, 8 pinned
captures): 230 segments · 1,712 keyframes · 591 solved · 891 refused ·
75,369 points · 102 segments-with-geometry · 70.38% two-view · 218.7 s.

**Final** (DEPTH=3): 232 segments · 1,712 keyframes · **620 solved** ·
860 refused · 71,122 points · 61.70% two-view.

## 9. Tests

| point | result |
|---|---|
| start of run | 1,628 passed, 64 skipped, 0 failed |
| after Stage 1 | 1,634 passed, 64 skipped, 0 failed |
| after r_H fix | 1,637 passed, 64 skipped, 0 failed |
| final | _(pending)_ |

Nine tests added. Both new mechanisms were **neutralized and the suite
re-run** to prove the tests notice their removal; both were then restored.

## 10. Contract / Mac handoff

**No contract change.** `r_h` is a Tower-side handoff field, NOT in
`docs/contracts/`, and its only reader takes `len()` of the edge list.
Its *values* now differ where they were previously garbage — that is a
correction, not a schema change.

**What Mac should know:** `support.json` grows ~4.8% (more sightings per
landmark); `points` falls ~5.6% (fewer duplicate landmarks); `segments`
+2 corpus-wide. Nothing changes shape, type or nullability.

The pre-existing Mac items stand unchanged: decode `transform_to_world`,
and key geometry caching on both content identity and placement identity.

## 11. Bugs discovered

1. **`homography_ratio` uninitialised mask** — fixed, tested.
2. **~90° pose error on synthetic `lateral seed=1006`** (median 84.22°,
   worst 87.79°) — **identical at both depths, so pre-existing and NOT
   caused by this run.** A near-perpendicular confidently-wrong pose on
   the *easiest* motion type. Not investigated. **Recorded so it is not
   lost; worth its own session.**
3. `test_world_registration.py`'s real-corpus class (10 tests) **silently
   skips** in this worktree because the corpus lives only in the main repo.
   Those are the only end-to-end checks that the registration gate does
   anything on real data.

## 12. Known remaining defects / declined work

- **`4fea31e2` loses 5 solved poses.** Diagnosed (§7), queued as PT-3.
- **The mitigation is designed and NOT implemented**: refuse guided
  associations whose reference offers insufficient parallax
  (`MIN_TRIANGULATION_ANGLE_DEG` already exists and is the principled
  threshold). Deliberately not done at this hour on one capture's
  evidence — this codebase has recorded threshold-tuning going wrong
  twice. **This is the top next implementation task.**
- **Registration hook** — declined (§6), gated on PT-1.
- **Stages 3–4** (place recognition, pose graph) not attempted; Stage 4's
  solver question is closed (see below).

## 13. Closed research questions

**`pyceres` is OUT.** Its cp312 Windows wheel bundles `cholmod` (2.05 MB)
and `spqr` (351 KB); Ceres's import table names `SuiteSparseQR` and 17
`cholmod_*` symbols; the GPL Supernodal module is present. The wheel
ships **one** licence file, Apache-2.0, with zero mentions of GPL,
SuiteSparse, CHOLMOD or SPQR — disqualifying for a closed-source product
and an independent GPL-2 §3 defect. Use `scipy.optimize` (BSD-3, already
installed) or hand-rolled LM.

## 14. Physical tests required

`2026-08-27-PHYSICAL-TESTS-QUEUED.md`. **PT-1 — a walk with deliberate
lateral translation — is worth more than the rest combined.** Each test
states its hypothesis, the capture, the expected result, and what would
falsify it.

## 15. Honest assessment: is World Builder closer to a recognisable room?

**Marginally, and not in the way the roadmap predicted.**

What improved is real but modest: **+29 solved poses (+4.9%)** and a map
whose landmarks are seen by meaningfully more views (two-view share
70.4% → 61.7%). That is the precondition for a pose graph to do anything
— it is not itself a more recognisable room.

What did *not* happen: no loop closure, no place recognition, no pose
graph, no automatic registration. Segments still do not share a
coordinate frame, so **scale remains Unknown and will stay Unknown.**

**The most useful thing learned is where the ceiling actually is.** Six of
eight captures register nothing, 135 of 141 registration refusals say the
wearer stood still, and the one capture that regressed is the most static
in the corpus. The pipeline is not obviously the limiting factor any
more — **the footage is.** Until a walk with genuine lateral translation
exists, further algorithmic work is optimising against a constraint it
cannot move.

**Recommendation: do PT-1 before anything else.**

## 16. Artifacts created

- Research: `2026-08-27-{stage1-multireference-design, stage1-results,
  stage2-rh-contract-safety, feature-starvation-gate-refused,
  branch-architecture-audit, registration-exists-and-is-never-called,
  pyceres-linkage-and-pgo-solver, overnight-adversarial-review}.md`
- Handoffs: this file, `2026-08-27-PHYSICAL-TESTS-QUEUED.md`
- Harnesses + committed result JSON:
  `scripts/research/{stage0_baseline, stage1_covisibility}/`
- Tests: `tests/test_world_builder_reference_depth.py`, plus additions to
  `test_world_builder_geometry.py` and `test_world_builder_support_views.py`

## 17. Adversarial review

_(pending)_
