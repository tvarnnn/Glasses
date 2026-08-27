# JPEG compression flips a reconstruction 81 degrees, silently

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation`.
**Status:** MEASURED and REPRODUCIBLE. **Not fixed.** Found incidentally
while validating an unrelated change; investigated because it looked like
a measurement artifact and turned out not to be.
**Independent of tonight's changes** — identical at `EXTEND_REFERENCE_DEPTH`
1 and 3.

---

## 0. The finding

On one synthetic scene, a pure lateral strafe is reconstructed as forward
motion — roughly perpendicular to the truth — **and the only difference
between the correct and the wrong answer is JPEG compression.**

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

## 1. Why this matters more than a synthetic-scene curiosity

**All real Ray-Ban footage is JPEG.** The corpus is 16,618 `.jpg` files,
and `world_build_session.py` replays them. The perturbation that produces
this is not exotic; it is the pipeline's normal input.

The failure is also **silent**:

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

- **One scene, one seed.** Whether this occurs on real Ray-Ban footage is
  unknown, and the corpus has no ground truth to detect it with. That is
  precisely why it is dangerous: on real footage there is no way to notice.
- The mechanism is not identified. The plausible reading is that the
  two-view solve for this scene has a second, self-consistent basin that
  a small perturbation reaches, but **that is a hypothesis, not a
  measurement.**
- Whether JPEG quality matters (`ss.encode_jpeg` defaults to 90) is
  untested.
- Whether the cheirality gate — which scored 0.0% false-positive on the
  synthetic zero-baseline null and is the best degeneracy check in this
  codebase — could be extended to catch it is untested.

## 4. Suggested next steps, in order

1. **Sweep seeds.** Run raw-vs-JPEG over 100 scene seeds and count how
   often a large flip occurs. If it is one seed in a hundred, that is a
   different problem from one in five. Cheap: the harness exists at
   `scripts/research/stage1_covisibility/ground_truth_accuracy.py` and
   the raw/JPEG comparison is ~40 lines.
2. **Vary JPEG quality** (60, 75, 90, 95, lossless PNG) on seed 1006 and
   find the threshold at which the answer flips. That would settle whether
   this is a knife-edge scene or a broad sensitivity.
3. **Check what the evidence looked like on the wrong answer** —
   `inlier_ratio`, `median_triangulation_deg`, `cheirality_fraction`. If
   any of them separates the wrong basin from the right one, there is a
   gate to be had. If none does, that is important too.
4. **Extend `test_no_pose_is_ever_confidently_wrong`** to cover seed 1006
   once the behaviour is understood. Adding it now would pin a bug rather
   than a requirement.

## 5. Reproduction

```
PYTHONPATH=<worktree>/tower <venv>/python.exe   # see the handoff for the exact invocation
```

Render `ss.strafe(8, step=0.15)` over `ss.furnished_room(seed=1006)` at
480x360, take frames `[0, 2, 4, 6]`, and solve
`ClassicalTwoViewBackend.estimate_window` twice: once on the raw grays,
once on `cv2.imdecode(ss.encode_jpeg(image))`. Compare
`C = -R.T @ t` of the final pose against
`poses[6].position - poses[0].position`.
