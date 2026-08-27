# About 2% of scenes reconstruct ~90 degrees wrong, and nothing notices

> **HEADLINE CORRECTED.** This document was first written as "JPEG
> compression flips a reconstruction 81 degrees". A 50-seed sweep run
> immediately afterwards shows **JPEG is not the cause**. The corrected
> finding is worse, not better: the two-view solve is BISTABLE on a small
> fraction of scenes, and any tiny perturbation decides which basin it
> lands in. On seed 1006 the JPEG run was the wrong one; on seed 2002 the
> RAW run was the wrong one. The original framing is kept below in §2
> because how it was found matters, but the mechanism claim was wrong and
> is corrected in §0.1.

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation`.
**Status:** MEASURED and REPRODUCIBLE. **Not fixed.** Found incidentally
while validating an unrelated change; investigated because it looked like
a measurement artifact and turned out not to be.
**Independent of tonight's changes** — identical at `EXTEND_REFERENCE_DEPTH`
1 and 3.

---

## 0. The finding (corrected)

On some synthetic scenes a pure lateral strafe is reconstructed as
forward motion — roughly perpendicular to the truth — with a `solved`
status and healthy-looking evidence. The scene that first exposed it,
seed 1006, differs between a correct and a wrong answer **only by JPEG
compression**, which is what made it look like a JPEG problem. §0.1 shows
it is not.

Same keyframes, same code, same thresholds. MEASURED, camera position of
the final pose against ground truth:

| seed | raw pixels | JPEG round-trip |
|---|---|---|
| 1000 | 1.18° | 1.81° |
| 1005 | 0.35° | 1.44° |
| **1006** | **2.30°** | **80.78°** |
| 1007 | 0.81° | 0.75° |

Seed 1006, final camera position:

- raw: `C = [ 2.703, -0.100, -0.041]` — along **+X**, which is correct
- JPEG: `C = [ 0.377, -0.168,  2.317]` — along **+Z**, which is not

True motion is `ss.strafe(8, step=0.15)`: positions moving purely in X,
from `[0.3, -1.6, 0.6]` to `[1.05, -1.6, 0.6]`. Verified collinear —
maximum pairwise direction spread **0.0°**.

## 0.1 The rate, and why JPEG is not the cause — MEASURED

Swept 50 fresh scene seeds (2000-2049), same camera path, solving each
twice — once on raw pixels, once through a JPEG round-trip:

| | raw | JPEG |
|---|---|---|
| final-pose error > 10 deg | **1 / 50 (2.0%)** | 0 / 50 |
| > 20 deg | 1 / 50 | 0 / 50 |
| > 45 deg | **1 / 50 (2.0%)** | 0 / 50 |
| JPEG-INDUCED flips (raw < 10 deg AND jpeg > 20 deg) | **0** | |
| final pose refused | 0 | 0 |

The single large error in the sweep is **seed 2002, where RAW is wrong
(87.53 deg) and JPEG is right (1.33 deg)** — the opposite direction to
seed 1006.

**So the mechanism is not JPEG.** It is that on roughly 2% of scenes the
two-view solve has a second, self-consistent basin about 90 degrees from
the truth, and the two runs sit on opposite sides of a knife edge. JPEG
noise is merely one perturbation among many that can tip it; raw pixels
tip it the other way just as readily.

**The rate is the finding: about 1 scene in 50 reconstructs roughly
perpendicular to reality, with a `solved` status and healthy-looking
evidence, and no existing gate catches it.**

## 0.2 A clean discriminator exists on synthetic data — and does NOT transfer

Both this investigation and the independent adversarial review converged
on the same statistic, from values `classical.py:664-673` **already
computes and discards**: the ratio of **cheirality inliers to epipolar
inliers** at the seed pair.

MEASURED, synthetic, 120 solves across 60 seeds x {raw, JPEG}:

| | RIGHT (<10 deg) | WRONG (>45 deg) |
|---|---|---|
| cheirality fraction | n=119, min **0.924**, p50 0.954 | **0.300** |
| median triangulation angle | min 4.380 | 0.700 |
| epipolar inlier ratio | min 0.924 | 0.900 |

**Cheirality separates cleanly (0.924 vs 0.300); the epipolar inlier ratio
does NOT** (0.924 vs 0.900 — a 0.024 gap). The review reached the same
place independently, at 0.9755 worst-good against 0.3470 best-bad, and
noted that normalising by *epipolar* inliers rather than raw matches
avoids the false-refusal-at-short-baseline problem this codebase's own
comments warn about.

`r_h` does not separate them either (bad 0.474-0.477 sits inside good
0.454-0.494) — one more measurement confirming r_H is not the
discriminator it looks like.

### Then it was measured on real footage, and it does not hold

MEASURED over all persisted `edges.jsonl` — 2,832 edges, of which 126
carry both fields, 70 of those on solved poses:

| | cheirality / epipolar |
|---|---|
| median | **0.982** |
| p5 | **0.204** |
| min | **0.069** |

| a gate at | would refuse, of currently-SOLVED edges |
|---|---|
| 0.5 | **17.1%** |
| 0.6 | 20.0% |
| 0.7 | 25.7% |
| 0.8 | 32.9% |

Most real edges are healthy — but real footage has a **long low tail that
the synthetic scenes do not**. A gate anywhere near the synthetic
separation point removes roughly a sixth of the reconstruction.

**That is only the right trade if those edges are ALSO wrong, and on this
corpus there is no ground truth with which to find out.** So the gate is
NOT implemented. Shipping it would trade a measured 17% loss against an
unmeasured 2.5% gain.

**This is the single most valuable experiment PT-1 footage would unlock**:
with a walk carrying genuine translation, the low tail should thin, and
whether the remaining low-ratio edges are wrong becomes answerable.

Caveat on the real-footage numbers: those edges come from worlds built by
the PREVIOUS engine, and only 126 of 2,832 edges carry both fields. The
tail is real; its exact shape at HEAD is not established.

## 1. Why this matters more than a synthetic-scene curiosity

**A ~2% rate of confidently-wrong reconstructions is a product problem,
not a curiosity.** The wearer's bar is "I can recognise which geometry is
which part of the room". A map whose trajectory is perpendicular to the
walk fails that completely, and the pipeline reports it as solved.

It also means **no amount of perturbation-hygiene fixes it.** Raw pixels
are not safer than JPEG — seed 2002 is wrong on RAW and right on JPEG.
The instability is in the solve, not the input.

The failure is **silent**:

- one segment, not a frame-mismatch artifact
- pose status `solved`, not refused
- healthy-looking evidence: 865–925 matches, 527–870 inliers
- deterministic — reproduces identically across runs and at both
  reference depths
- three other seeds on the **identical camera path** are correct, so it is
  scene-content-dependent, not a systematic sign or convention error

That combination — confidently wrong, plausible-looking, reproducible — is
the exact failure mode this codebase writes about guarding against. There
is even a shipped test named
`test_no_pose_is_ever_confidently_wrong`; it parameterises seeds
1000–1003, and 1006 is outside that set.

## 2. How it was found, including the two wrong turns

Recorded because the wrong turns are instructive.

1. A ground-truth harness reported a median direction error of **84.22°**
   for `lateral seed=1006`, identical at both reference depths. I recorded
   it as a pre-existing defect.
2. **First wrong turn:** solving the same 8 rendered frames directly
   through `estimate_window` gave 0.32–2.51°. That looked like the
   harness was at fault.
3. Found that the engine's keyframe selector accepts only frames
   `[0, 2, 4, 6]` of 8, so pose row *i* is source frame *2i*. **This is
   real** and worth knowing — but it cannot produce this error, because
   the motion is exactly collinear and the metric is direction-only, so
   the truth direction is identical whichever index is taken.
4. **Second wrong turn:** suspected the `T_world_camera` convention.
   `engine.py:862-885` converts correctly (`C = -R.T @ t`) and documents
   having caught precisely that bug before.
5. Solving the engine's actual keyframe subset `[0,2,4,6]` from **raw**
   pixels: 0.34°, 1.90°, 2.29°. Correct.
6. The only remaining difference between that and the engine was the JPEG
   round-trip. Testing raw against JPEG on identical frames isolated it.

The lesson worth keeping: **an anomaly that resists two plausible
explanations is worth a third look.** Both wrong turns would have led to
dismissing a real defect as a measurement artifact, and I nearly did.

## 3. What is NOT established

- **Synthetic only.** Whether this occurs on real Ray-Ban footage is
  unknown, and the corpus has no ground truth to detect it with. That is
  precisely why it is dangerous: on real footage there is no way to notice.
- **The rate is from 50 seeds on ONE camera path and one room generator.**
  1/50 is 2% with a wide confidence interval; it is not established that
  2% is the rate on anything else.
- The mechanism is not identified. "A second self-consistent basin"
  matches the observations but **is a hypothesis, not a measurement.**
- Whether the instability is specific to the 2-frame-gap keyframe subset
  `[0,2,4,6]`, or to the strafe path, is untested.
- Whether the cheirality gate — which scored 0.0% false-positive on the
  synthetic zero-baseline null and is the best degeneracy check in this
  codebase — could be extended to catch it is untested.

## 4. Suggested next steps, in order

1. ~~Sweep seeds.~~ **DONE — see §0.1.** 1 in 50 at >45 deg, and it
   refuted the JPEG mechanism. Harness at
   `scripts/research/stage1_covisibility/wrong_basin_sweep.py`.
2. **Check what the evidence looks like on the wrong answer** —
   `inlier_ratio`, `median_triangulation_deg`, `cheirality_fraction`, and
   reprojection residual. **This is now the highest-value next step:** if
   any of them separates the wrong basin from the right one, there is a
   gate to be had, and the cheirality gate is already the best degeneracy
   check in this codebase. If none separates them, that is a more serious
   result and needs saying.
3. **Widen the sweep** to other paths (forward, mixed), other keyframe
   gaps, and more seeds, to establish whether 2% is representative.
4. **Only then** extend `test_no_pose_is_ever_confidently_wrong`. Adding a
   case now would pin a bug rather than a requirement.

## 5. Reproduction

```
PYTHONPATH=<worktree>/tower <venv>/python.exe   # see the handoff for the exact invocation
```

`scripts/research/stage1_covisibility/wrong_basin_sweep.py <N>` sweeps N
seeds and reports the rate. For the single case:

Render `ss.strafe(8, step=0.15)` over `ss.furnished_room(seed=1006)` at
480x360, take frames `[0, 2, 4, 6]`, and solve
`ClassicalTwoViewBackend.estimate_window` twice: once on the raw grays,
once on `cv2.imdecode(ss.encode_jpeg(image))`. Compare
`C = -R.T @ t` of the final pose against
`poses[6].position - poses[0].position`.
