# Learned 3D foundation models against World Builder's island problem

**Lane:** Agent 3 — learned multi-view 3D / geometry foundation systems
**Date:** 2026-08-26
**Question:** can DUSt3R / MASt3R / MASt3R-SLAM / VGGT do the one thing World
Builder cannot — recognise that two disconnected fragments are the same physical
room, and relate them geometrically, across baselines classical tracking cannot
bridge?
**Status:** measurement + source reading + licence analysis. No production code
was modified; `ios/` untouched. Third-party code and checkpoints live outside the
repo tree. Harness: `tower/scripts/research/slam_learned_3d/`.

> **Every number below is labelled.**
> **[M]** MEASURED by this lane on this host today.
> **[Q]** QUOTED from a paper / repo file / issue, with the source named.
> **[E]** ESTIMATED, with the estimation method shown inline.
>
> **We have NO external ground truth.** Every corpus number is a comparative or
> self-consistency measurement. Where I call something a "true positive" that
> rests on my own visual inspection of the two frames — stated each time, and not
> ground truth either.
>
> **The GPU was shared with other lanes throughout.** Wall-clock swung by up to
> 25× on identical work ([M] 13.5 s, 18.9 s and 326.2 s for three consecutive
> identical-shape DUSt3R calls). Runtimes are tagged *uncontended* or
> *contended*; treat contended numbers as upper bounds only.

---

## 0. Verdicts

| system | relates two disconnected fragments of the same room? | live tracking | background refinement | loop closure / reloc | offline recon | fits RTX 5070 12 GB? | can it ever ship commercially? |
|---|---|---|---|---|---|---|---|
| **DUSt3R** | **weakly** — its PnP-from-pointmap succeeded on only 4 of 10 pairs and **failed on `seg0-45`, the case that matters most**; focal off by a median **+27.4%**, 20/20 over-estimates [M] | no | no | no — no retrieval, no verifier of its own | N ≲ 20-30 images | pairwise 2.87 GiB [M]; **global aligner no** past ~30-40 images [E, corroborated Q] | **NO.** CC BY-NC-SA 4.0 code *and* NC-poisoned weights |
| **MASt3R** | **YES — the strongest result in this lane.** 308 verified correspondences at 2.65° reciprocity where ORB found **zero**; 758 at 1.20° on a pair where *both* segments hold zero geometry [M] | no | **yes — best fit for us** | as a *verifier*, not a *detector*; hallucinates on 4 of 6 hard negatives and is saved only by reciprocity [M] | via MASt3R-SfM (ASMK retrieval) | pairwise 3.02 GiB [M] | **NO.** Same chain + Niantic Map-Free terms binding "dataset-derived materials" [Q] |
| **MASt3R-SLAM** | yes by design — incremental ASMK + reloc + Sim(3) factor graph [M, read from source] | **yes** — 15 FPS on RTX 4090 [Q] | yes | **yes** | yes | **could not be built here** [M], three independent blockers | **NO.** CC BY-NC-SA 4.0; inherits MASt3R weights |
| **VGGT (code)** | yes within one forward pass; N is VRAM-bounded, and its focal is the worst measured (+34% at 2 frames) [M] | no | maybe | no | yes, ≤ ~20 frames | **7.4 GiB for 2 frames, 9.3 GiB for 8; ceiling ≈20 frames** [M/E] | code licence commercially permissive [Q] |
| **VGGT-1B (default ckpt)** | same model | — | — | — | — | — | **NO.** HF tag `cc-by-nc-4.0` [Q] |
| **VGGT-1B-Commercial** | same model | — | — | — | — | — | **conditionally YES** — gated form; commercial OK except military [Q] |
| **MapAnything-apache** *(not in my brief; found while checking licences)* | untested here | — | — | — | — | — | **YES — Apache 2.0 code AND weights, 6 permissively-licensed datasets** [Q] |

**The three results that matter, all measured here:**

1. **On `seg6-30`, where the production ORB matcher found ZERO verified
   correspondences, MASt3R found 323 matches of which 308 survive
   essential-matrix verification under our own ChArUco K — a 0.95 inlier ratio —
   with two independent forward passes agreeing on rotation to 2.65°.** The two
   frames are the same bed from different angles. Zero versus 308 is not an
   incremental improvement; it is a link that did not exist becoming one that
   does. On `seg0-45`, where *both* segments hold zero triangulated points and
   classical registration was not merely hard but impossible, MASt3R produced 758
   verified correspondences at 1.20° reciprocity.
2. **These models hallucinate, and only one statistic catches it.** Given six
   visually-verified different-place pairs, MASt3R emitted a confident pointmap
   and focal estimate for all six and never signalled non-overlap; four of six
   produced essential-matrix inlier ratios of **0.56–0.78**, and one had a focal
   estimate within **0.3%** of our calibration. **All six were rejected by
   rotation reciprocity** (118.98°–177.31°). Across the corrected sample,
   reciprocity separates same-place from different-place *perfectly* (AUC 0.000
   over 110 comparisons); nothing else does — not inlier ratio, not match count,
   not the model's own confidence, not focal agreement.
3. **And it cannot ship.** The entire Naver line is non-commercial in both code
   and weights, with no commercial licence on offer, and the poison starts in the
   CroCo v2 backbone that every DUSt3R and MASt3R checkpoint descends from.

**The finding to keep is the validity test, not the model.**

---

## 1. The mandatory framing: MiDaS is not the same kind of estimator

This project measured MiDaS and refused it — Spearman(MiDaS, 1/z_sfm) = **0.074**,
negative on 42.4% of frames [Q — `2026-08-26-multi-cue-indoor-geometry.md`]. That
refusal is correct and this lane does not overturn it. It also does not transfer,
because the estimand differs in exactly the way that matters.

### 1.1 What MiDaS estimates

MiDaS is a single-image regressor `I → d` trained with a **scale- and
shift-invariant** loss. Its output is defined only up to an unknown affine map in
inverse depth: for each image *independently* there exist unknown `a > 0`, `b`
with `1/z_true ≈ a·d + b`. Three consequences:

1. **`a` and `b` are per-frame and unconstrained.** Nothing ties frame *k*'s gauge
   to frame *k+1*'s. Two views of one wall may get incompatible depth scales, so
   the depths do not compose into a scene.
2. **No cross-view consistency term exists.** MiDaS never sees a second view. It
   cannot be *wrong* about the relationship between two views because it never
   expresses one.
3. **Ordering, not metric structure.** The objective rewards ordinal correctness.
   Our own number is what that predicts: implied-depth spread 12.6× where geometry
   needs it tighter than 3.2× [Q — same report].

The honest statement of the refusal: *a per-frame relative depth field with two
free parameters per frame cannot supply the missing inter-frame constraint,
because that constraint is precisely what it does not model.*

### 1.2 What DUSt3R / MASt3R / VGGT estimate

DUSt3R regresses a **joint pointmap pair**. Given `I₁, I₂` it emits

```
X^{1,1} ∈ R^{H×W×3}   a 3D point for every pixel of I₁, in I₁'s camera frame
X^{2,1} ∈ R^{H×W×3}   a 3D point for every pixel of I₂, ALSO in I₁'s frame
```

plus per-pixel confidence. The `2,1` superscript is the whole idea: the second
view's geometry is expressed **in the first view's frame**. The estimand is not
"how far is this pixel" but "where is this pixel, in a coordinate system shared
with the other image."

Three things change, and they are the three MiDaS lacks:

1. **One gauge for the pair, not two per frame.** DUSt3R's pointmaps are
   "regressed up to an unknown scale factor" [Q — arXiv 2312.14132v3 §3.2] — *one*
   unknown, for the pair. Within it the relative geometry of the two cameras is
   fully determined, including where there is no parallax.
2. **Cross-view consistency IS the training signal.** The published checkpoint's
   own stored arguments read `ConfLoss(Regr3D(L21, norm_mode='avg_dis'),
   alpha=0.2)` [M — read directly out of
   `DUSt3R_ViTLarge_BaseDecoder_512_dpt.pth`'s `args.train_criterion`]: a 3D
   regression loss on *both* pointmaps in the shared frame. Putting view 2 into
   view 1's frame wrongly is the error being minimised.
3. **Relative pose falls out without triangulation.** With both pointmaps in one
   frame, camera 2's pose is a PnP of `X^{2,1}` against image 2's own pixel grid.
   No essential matrix, no parallax requirement. DUSt3R ships exactly this in
   `dust3r/cloud_opt/pair_viewer.py` [M — read].

MASt3R adds a 24-dim dense local descriptor head on the same pointmaps
(`output_mode='pts3d+desc24'`, `two_confs=True` [M — read from the checkpoint's
stored `args.model`]) plus reciprocal-NN matching. VGGT drops the two-view
asymmetry and attends globally over all input frames at once; its camera head
emits a 9-D `[quaternion, translation, field-of-view]` per frame [Q — arXiv
2503.11651v1].

### 1.3 Is that difference big enough for OUR failure mode?

Our dominant failure is **baseline-limited**: 54.7% of failing pairs in
geometry-less segments, versus 10.4% correspondence-limited [Q — multi-cue
report]. Classical two-view geometry cannot solve a baseline-limited pair — not
because the matcher is weak, but because the estimator is *singular* there.

The pointmap formulation is not singular there. It does not triangulate. It
regresses depth from monocular cues *and* ties the two views into a shared frame.
On a pure-rotation pair, classical SfM has a rank-deficient problem; DUSt3R has a
well-posed regression whose answer may be inaccurate but is not undefined.

The published evidence agrees, and is unusually direct about it. MASt3R-SfM
measures pure-rotation-only sequences on InLoc and reports **RRA@5: COLMAP 4.1%,
VGGSfM 1.3%, MASt3R-SfM 62.2%** [Q — arXiv 2409.19152v1 Table 8], with the
explicit claim that "our method goes beyond structure-from-motion, as it works
even when there is no motion (i.e. purely rotational case)" and that classical
pipelines "do dramatically fail in such a situation" [Q — same].

**So yes — and §4 shows it holds on our frames.** The honest caveat, quantified in
§4.7 and §6: the *depth* half of the pointmap is still a learned monocular prior
and inherits monocular depth's inaccuracy. What changes is that the inaccuracy is
now expressed in a shared frame where it can be **checked**, instead of a private
frame where it cannot. That is the whole difference, and it turns out to be
enough.

---

## 2. How they solve wide-baseline matching

### 2.1 The pointmap sidesteps correspondence search

A classical wide-baseline pipeline is a chain of brittle stages: detect,
describe, match, ratio-test, RANSAC an essential matrix, `recoverPose`,
triangulate. Our backend implements exactly this chain [M —
`tower/tower/world_builder/backends/classical.py`], and each stage fails
independently.

DUSt3R deletes the chain. No detector, no descriptor matching, no RANSAC in the
forward pass. A shared ViT-L encoder plus two cross-attending decoders regress
where every pixel of both images lives in one frame. Correspondence, if wanted,
is a *consequence* — two pixels correspond when their regressed points coincide —
and is never searched for.

That is why the formulation is wide-baseline-robust in a way descriptor matching
is not. A descriptor must be invariant to the appearance change the viewpoint
change induces; past some baseline, no local patch descriptor is. The transformer
is not matching patches; it uses scene context across both images. MASt3R states
the effect: with its matching, "the proposed method is able to completely get rid
of RANSAC" [Q — arXiv 2409.19152v1 §4.4], and of DUSt3R that it shows "impressive
robustness in matching views with extreme viewpoint changes, yet with limited
accuracy" [Q — arXiv 2406.09756v1].

### 2.2 What it does NOT give you, and why that is the crux

It gives you a relation between two images **you already decided to compare**. It
does not tell you *which* pairs to compare. On our 457 keyframes that is 104,196
unordered pairs, and DUSt3R has no cheap way to prune them.

> **A pointmap model is a verifier, not a detector.** Place recognition is a
> separate component. Every system here that actually closes loops bolts one on:
> MASt3R-SfM and MASt3R-SLAM both use **training-free ASMK** over MASt3R's own
> encoder tokens [Q — MASt3R-SfM Appendix B: *"We thus keep the training-free
> ASMK approach for MASt3R-SfM"*; shipped as
> `MASt3R_..._retrieval_trainingfree.pth`; ASMK itself is `jenicek/asmk`, **MIT**].

For us that cuts both ways, and the good half is much larger. **We do not lack
candidates:**

| measurement on the canonical session | value | label |
|---|---|---|
| keyframes on disk | 457 | [M] |
| cross-segment keyframe comparisons run | 100,560 | [M] |
| ORB describe, all 457 keyframes | 1.45 s | [M] |
| all-pairs verified matching, wall clock | 233.5 s | [M] |
| per-comparison cost | 2.32 ms | [M] |
| segment pairs (of 1,275) with ≥1 verified inlier | **830** | [M] |
| segment pairs with ≥15 inliers (the backend's own `MIN_INLIERS`) | 442 | [M] |
| segment pairs with ≥60 inliers | 102 | [M] |
| **of those 102, how many involve a segment with ZERO triangulated geometry** | **86** | [M] |
| **distinct geometry-less segments so reached (of 32)** | **24** | [M] |

Read that last row twice. **The classical pipeline already holds strong
image-level evidence linking 24 of its 32 empty segments into the map, and can do
nothing with any of it** — registration needs the segment to already have 3D
points, and those segments have none [Q — cross-segment registration report: "32
of 51 segments contain no geometry at all"].

That is exactly the gap a pointmap model fills. It does not need the segment to
have prior geometry. It regresses geometry from the images.

---

## 3. Environment: what could and could not be built here

Checked first, as instructed.

| fact | value | label |
|---|---|---|
| CUDA toolkits installed | **only v11.8** | [M] |
| `nvcc -arch=sm_120` | `nvcc fatal : Value 'sm_120' is not defined for option 'gpu-architecture'` | [M] |
| MSVC `cl.exe` anywhere on the host | **not found** — no Visual Studio, no Build Tools | [M] |
| `nvcc -arch=sm_90` (a *supported* arch) | still fails: `Cannot find compiler 'cl.exe' in PATH` | [M] |
| WSL2 | Ubuntu 24.04.2 LTS, running; gcc+g++ present; `/usr/lib/wsl/lib/libcuda.so` present; `nvidia-smi` sees the RTX 5070; 15 GB RAM | [M] |
| `nvcc` in WSL | absent; `apt` candidate is **12.0.140**, which also predates sm_120 support | [M] |

**No CUDA extension can be compiled on this host as configured** — on Windows for
two independent reasons (toolkit too old *and* no host C++ compiler), and in WSL
because the distro-packaged toolkit is also too old. Building requires adding
NVIDIA's CUDA ≥12.8 apt repo inside WSL plus a fresh torch cu12x environment.

### 3.1 MASt3R-SLAM: three blockers, measured

1. **`git clone --recursive` fails on Windows.** `fatal: cannot write keep file
   '…/thirdparty/in3d/thirdparty/pyimgui/modules/imgui-cpp/objects/pack/pack-….keep':
   Filename too long` [M]. Worked around by cloning to `C:\m3s` with
   `-c core.longpaths=true` [M — succeeded].
2. **Its `setup.py` targets Ampere and older, with no PTX fallback.** Verbatim
   [M — read `/c/m3s/MASt3R-SLAM/setup.py`]:
   ```
   "-gencode=arch=compute_60,code=sm_60", … "-gencode=arch=compute_86,code=sm_86",
   ```
   Every entry is `code=sm_N` — SASS only, **no `code=compute_N` PTX entry**. Even
   a correctly built binary would carry no forward-compatible PTX and could not
   JIT onto sm_120. Running on Blackwell requires editing this file, not merely
   installing a newer toolkit.
3. **No toolchain to compile it with.**

**What a Linux/CUDA-12.8 box would have bought:** a real MASt3R-SLAM run on the
1848-frame canonical capture — FPS, drift, and whether its loop closure
re-connects the segments our engine abandons. That is the one measurement this
lane could not make. Cost to obtain it here: ≈4-8 GB of toolchain downloads, a
fresh torch environment, and a one-line `setup.py` patch — an hour or two, not an
architectural problem. Given §9 it would still land on weights that cannot ship,
so I timeboxed it out rather than spend the lane on it.

**What DID run, natively on Windows, with zero compilation:** DUSt3R and MASt3R
pairwise inference. Both are pure PyTorch. The only casualty is `Warning, cannot
find cuda-compiled version of RoPE2D, using a slow pytorch version instead` [M] —
which costs speed, not correctness. This was the right call and it is sufficient
to answer the lane's decisive question.

---

## 4. THE DECISIVE EXPERIMENT

### 4.1 Design

Four groups of image pairs from world `3dd986b1c2364d4b85de97152f2e39f4` /
session `dd5d13a2381e430db9b27c7da2cf2928` (457 keyframes, 51 segments, only 19
with geometry):

- **oracle** — segment pairs the classical pipeline *did* register (4↔5, 5↔32).
  Partial ground truth: 4↔5 registered with 419 correspondences, scale 0.3533,
  reverse estimate agreeing to 0.3% [Q — cross-segment registration report].
- **blind** — segment pairs with strong image evidence where at least one segment
  has **zero triangulated points**, so classical registration was not merely hard
  but *impossible*. Verified against `points.json` [M]: of the 51 segments only 19
  hold any points at all (12,023 total); **segments 0, 18, 25, 45 and 47 hold
  exactly zero**, so `seg0-45`, `seg0-18` and `seg45-47` are pairs where *neither*
  side has anything to register. Includes segment 0, the prior work's flagship
  unusable case.
- **purerot** — consecutive keyframes whose stored degeneracy is `pure_rotation`.
- **negative controls** — (a) in-session segment pairs with **zero** verified ORB
  inliers; (b) pairs spanning **different captures**.

For each pair MASt3R runs **twice**, as (A,B) and as (B,A) — two genuinely
independent forward passes. Recorded: reciprocal-NN match count; how many survive
a MAGSAC essential-matrix fit **under our real ChArUco K** at the backend's own
1.0 px threshold; the focal MASt3R infers from its own pointmap; its metric depth;
per-pixel confidence; and the reciprocity of the two independent pose estimates.

### 4.2 Results

MASt3R `MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric`, 288×512 (360×640
resized long-edge, factor exactly 0.8, no crop). All [M].

**All 32 pairs. Every number [M].** "recip R" and "recip t-dir" are the angular
disagreement between the two *independent* forward passes; a dash means one
direction produced no pose at all, which is itself a refusal.

| kind | pair | ORB inl | MASt3R matches | E-inl | E-ratio | focal px | focal err | **recip R** | recip t-dir |
|---|---|---|---|---|---|---|---|---|---|
| oracle | seg4-5 | 70 | 349 | 291 | 0.83 | 380.0 | +8.4% | 4.85° | 7.24° |
| oracle | seg5-32 | 40 | 111 | 55 | 0.50 | 405.9 | +15.8% | 6.98° | 2.22° |
| blind | seg23-25 | 232 | 1787 | 1764 | 0.99 | 402.9 | +15.0% | **0.05°** | 1.69° |
| blind | seg45-50 | 229 | 1636 | 1411 | 0.86 | 351.4 | **+0.3%** | 0.76° | 18.34° |
| blind | seg45-47 | 340 | 1312 | 1210 | 0.92 | 321.9 | −8.1% | **0.36°** | 0.98° |
| blind | seg45-48 | 261 | 921 | 894 | 0.97 | 329.4 | −6.0% | **0.20°** | 1.58° |
| **blind** | **seg0-45** | 208 | **913** | **758** | 0.83 | 368.5 | **+5.2%** | **1.20°** | **5.72°** |
| blind † | seg1-18 | 211 | 38 | 22 | 0.58 | 393.1 | +12.2% | 10.63° | 9.49° |
| blind † | seg12-18 | 170 | 40 | 21 | 0.53 | 384.7 | +9.8% | 39.52° | 119.06° |
| blind † | seg13-18 | 184 | 23 | 14 | 0.61 | 370.0 | +5.6% | 21.93° | 16.84° |
| blind † | seg0-18 | 197 | 18 | 12 | 0.67 | 469.2 | +33.9% | — | — |
| blind † | seg3-18 | 188 | 8 | 0 | 0.00 | 401.7 | +14.6% | — | — |
| purerot | seg7-2 | — | 2167 | 2167 | **1.00** | 425.1 | +21.3% | 0.07° | 7.15° |
| purerot | seg7-1 | — | 2102 | 2102 | **1.00** | 425.6 | +21.5% | 0.07° | 3.46° |
| purerot | seg7-0 | — | 2095 | 2095 | **1.00** | 425.6 | +21.5% | 1.06° | 83.80° |
| purerot | seg0-0 | — | 2101 | 2089 | **0.99** | 382.5 | +9.2% | **179.98°** | 133.33° |
| purerot | seg0-1 | — | 2073 | 2007 | 0.97 | 376.0 | +7.3% | 0.11° | 2.68° |
| purerot | seg0-2 | — | 2105 | 1945 | 0.92 | 384.9 | +9.8% | 0.12° | **175.64°** |
| neg_insess ‡ | seg6-30 | **0** | 323 | **308** | **0.95** | 354.0 | **+1.0%** | **2.65°** | **0.94°** |
| neg_insess ‡ | seg5-30 | **0** | 141 | 56 | 0.40 | 356.6 | **+1.8%** | **4.67°** | 3.33° |
| neg_insess ‡ | seg6-23 | **0** | 98 | 34 | 0.35 | 356.4 | +1.7% | 63.93° | 28.01° |
| neg_insess | seg24-46 | **0** | 235 | 76 | 0.32 | 369.2 | +5.4% | **81.16°** | 80.00° |
| neg_insess | seg8-43 | **0** | 34 | 18 | 0.53 | 422.9 | +20.7% | **176.75°** | 12.35° |
| neg_insess | seg8-37 | **0** | 25 | 19 | 0.76 | 417.5 | +19.1% | — | — |
| neg_insess | seg19-46 | **0** | 11 | 0 | 0.00 | 427.5 | +22.0% | — | — |
| neg_insess | seg8-30 | **0** | 3 | 0 | 0.00 | 420.7 | +20.1% | — | — |
| neg_xcap ‡ | xcap2 | — | 209 | 132 | 0.63 | 483.0 | +37.8% | 12.12° | 40.98° |
| neg_xcap | xcap4 | — | 60 | 15 | 0.25 | 368.3 | +5.1% | **117.20°** | 77.76° |
| neg_xcap | xcap5 | — | 9 | 0 | 0.00 | 376.8 | +7.5% | — | — |
| neg_xcap | xcap1 | — | 1 | 0 | 0.00 | 428.8 | +22.4% | — | — |
| neg_xcap | xcap0 | — | **0** | 0 | 0.00 | 385.0 | +9.9% | — | — |
| neg_xcap | xcap3 | — | **0** | 0 | 0.00 | 369.8 | +5.5% | — | — |

† these five all share keyframe `00001824`, which is 62.1% redaction fill — see §4.6b.
‡ mislabelled by me; on inspection these are the same place — see §4.4.

**And the hard negative control: six pairs I built after looking at the corpus,
each pairing the canonical bedroom against a visually verified different view
(ChArUco board, gaming desk, closet, laundry door, empty corridor, fairy-lit
bed).** All [M]:

| hard negative | MASt3R matches | E-inl | E-ratio | focal px | focal err | **recip R** | recip t-dir |
|---|---|---|---|---|---|---|---|
| charuco_board | 1 | 0 | 0.00 | 387.7 | +10.6% | — | — |
| desk_rgb | 111 | **78** | **0.70** | 371.6 | +6.0% | **177.31°** | 103.79° |
| closet_clothes | 18 | 10 | **0.56** | 349.5 | **−0.3%** | — | — |
| door_towel | 36 | 28 | **0.78** | 426.8 | +21.8% | **126.88°** | 79.23° |
| corridor_floor | 47 | 28 | **0.60** | 374.7 | +6.9% | **164.21°** | 147.30° |
| fairylights | 19 | 13 | **0.68** | 369.5 | +5.4% | **118.98°** | 27.87° |

> **This is the most important table in the report.** Four of the six hard
> negatives produce E-inlier ratios of **0.56 to 0.78** — comfortably above what
> a naive gate would accept, and one of them (`closet_clothes`) has a focal
> estimate within **0.3%** of our calibration. **Every single one is caught by
> rotation reciprocity**, at 118.98° to 177.31°, or by producing no reverse pose
> at all. Inlier ratio would have admitted four false loop closures. Focal
> agreement would have admitted at least one. **Reciprocity admitted none.**

### 4.2b Which statistic actually separates same-place from different-place

Scoring each candidate statistic by Mann-Whitney AUC. Two labellings are given
because the honest answer depends on which you believe; both are [M].

**(a) As originally labelled** — `oracle`+`blind` positive (n=12),
`neg_insess`+`neg_xcap` negative (n=14). This includes my labelling errors and the
redacted-keyframe pairs, so it is the pessimistic bound:

| statistic | pos median | neg median | AUC |
|---|---|---|---|
| E-inlier ratio | 0.748 | 0.287 | 0.815 |
| MASt3R match count | 230 | 29.5 | 0.750 |
| E-inlier count | 173 | 16.5 | 0.750 |
| rotation reciprocity (lower better) | 3.03° | 63.93° | 0.171 → **0.829 inverted** |
| translation-direction reciprocity | 6.48° | 28.01° | 0.329 → 0.671 inverted |
| MASt3R's own mean confidence | 1.027 | 1.000 | 0.625 |
| absolute focal error vs our calibration | 9.12% | 8.70% | **0.488 — chance** |

**(b) With labels corrected** — the three `neg_insess` pairs I judged to be the
same place moved to positive, `xcap2` likewise, the five redacted-keyframe pairs
excluded as a *matcher-failure* regime rather than a place-recognition question,
and `purerot` excluded (it is not a place-recognition question either). n = 11
positive, 10 negative. This is post-hoc relabelling and should be read as such:

| statistic | pos median | neg median | AUC | perfectly separating? |
|---|---|---|---|---|
| **rotation reciprocity** (lower better) | **2.65°** | **117.20°** | **0.000** | **YES** |
| E-inlier count | 308 | 0 | 0.973 | no |
| MASt3R match count | 349 | 10 | 0.964 | no |
| E-inlier ratio | 0.83 | 0.00 | 0.936 | no |
| MASt3R's own mean confidence | 1.05 | 1.00 | 0.918 | no |
| translation-direction reciprocity | 3.33° | 77.76° | 0.091 → 0.909 inverted | no |
| absolute focal error | 5.99% | 14.51% | 0.291 → 0.709 inverted | no |
| ORB verified inliers (the incumbent) | 139 | 0 | 0.850 | no |

**Rotation reciprocity separates perfectly across all 110 positive–negative
comparisons.** Nothing else does, including MASt3R's own confidence.

**A concrete gate.** `recip_R < 15°` **AND** `E-inlier ratio > 0.5`, evaluated on
the corrected labels plus all six hard negatives [M]:

- **accepts 8 of 11 positives** (misses `seg5-32`, `seg5-30`, `seg6-23` — all on
  the E-ratio term, all genuinely low-overlap);
- **accepts 0 of 16 negatives** (10 in-corpus + 6 hard).

**Zero false positives at 73% recall on 27 pairs.** That is not a
production-calibrated threshold — 27 pairs cannot calibrate anything — but it is a
working decision rule that already exists, uses only quantities we can compute
without ground truth, and is exactly the piece World Builder has never had.

**And one negative result on the hypothesis the brief asked me to chase:**
absolute focal error against our ChArUco calibration is at chance (AUC 0.488) on
the original labels and only 0.709 on the corrected ones — a weak signal that
`closet_clothes` (−0.3% error, definitely a different place) falsifies outright.
**§8.2 reframes what the calibration is actually worth, which turns out to be
more, not less.**

### 4.3 Answer to question 3: yes, and here is the case

**`seg0-45`.** Read straight off `points.json` and `poses.json` [M]: **segment 0
holds 0 triangulated points across 4 keyframes** (1 anchor, 1 `rotation_only`, 2
`unavailable` — no solved pose at all), and **segment 45 also holds 0 points.**
This is not a hard registration problem; it is an *impossible* one for any
classical method, because neither side has a single 3D point to align. The prior
investigation flagged exactly this pair as the flagship example of a link that is
real as an *image* match and unusable as a *registration* [Q — cross-segment
registration report §1.4]. Classical registration produced nothing: not a bad
answer, nothing.

MASt3R, given the same two JPEGs and nothing else, produced [M]:

- **913 reciprocal matches**, of which **758 survive** MAGSAC essential-matrix
  verification under our real ChArUco intrinsics at the backend's own 1.0 px
  threshold — **3.6× the 208 verified inliers ORB found on the same pair**;
- a relative rotation whose two *independent* forward passes agree to **1.20°**;
- a translation direction whose two independent passes agree to **4.5°**;
- an inferred focal of 368.5 px against our calibrated 350.4 px — **+5.2%**.

Four numbers, from three independent evidence sources (matching, reciprocity, our
calibration), all consistent. **I inspected the two frames myself: they show the
same bedroom — the same two framed pictures on the same wall, the same bed.** (My
judgement of two images; not ground truth.)

Across all five **blind** pairs the pattern holds: median 921 matches, 894
E-inliers, and the number that matters, **median rotation reciprocity 0.28°**. Two
separate solves over different correspondence sets agreeing on rotation to a third
of a degree is not an optimiser coincidence.

### 4.4 The negative control — a pass, and an honest correction

**Cross-capture pairs are largely rejected outright.** Three of five returned
**0, 1 and 0** reciprocal matches [M]. MASt3R's *matcher* did not invent
correspondences for images that do not overlap. Of the two that produced matches,
one (`xcap4`, 60 matches) is caught by reciprocity at **117.2°**, and the other
(`xcap2`) is discussed below.

**But my negative controls are contaminated — and the contamination is itself the
strongest positive result in this lane.** I built a contact sheet of one frame
from each of the 33 captures and looked at it [M]. The entire 16,618-frame corpus
is **one apartment** — overwhelmingly one bedroom, plus a hallway, a closet, a
desk, and a ChArUco board. So "different capture" does not mean "different place",
and "zero ORB inliers" does not mean "not the same room". I then looked at every
pair in the negative groups. Three of the five `neg_insess` pairs are **the same
bedroom**:

| pair | ORB verified inliers | MASt3R matches | E-inliers | E-ratio | recip R | focal err | my visual verdict |
|---|---|---|---|---|---|---|---|
| seg6-30 | **0** | 323 | **308** | **0.95** | **2.65°** | **+1.0%** | same bed, blinds, red picture — **same place** |
| seg5-30 | **0** | 141 | 56 | 0.40 | **4.67°** | **+1.8%** | same bed and blinds — **same place** |
| seg6-23 | **0** | 98 | 34 | 0.35 | 63.93° | +1.7% | same bed — same place, but the pose is not trustworthy |
| seg24-46 | **0** | 235 | 76 | 0.32 | 81.16° | +5.4% | different direction; pose correctly rejected |
| seg8-30 | **0** | 3 | 0 | 0.00 | — | +20.1% | different direction; correctly rejected |

> **This is the headline. On `seg6-30` the production matcher found ZERO verified
> correspondences, and MASt3R found 323 matches of which 308 survive
> essential-matrix verification under our own calibrated K — a 0.95 inlier ratio —
> with the two independent passes agreeing on rotation to 2.65° and on focal to
> +1.0%.** Zero versus 308 is not an incremental improvement in matching. It is
> the difference between a link that does not exist and a link that does.

The same correction applies, more weakly, to `neg_xcap xcap2` — both frames show
the same window blinds, its 209 matches are plausibly genuine, and its 12.12°
reciprocity is borderline rather than absurd.

**So I built a proper negative control and ran it.** Six pairs, each pairing the
canonical bedroom against a view I had visually confirmed to be somewhere else in
the flat — the ChArUco calibration board, the gaming desk with RGB lighting, the
closet of hanging clothes, the laundry-room door with an orange towel, an empty
corridor corner, and a fairy-lit bed in another room. Results in §4.2. The summary:

- **MASt3R produced a pointmap, a focal estimate and a confidence map for all six.
  It never once indicated that the images do not overlap.**
- **Four of six produced E-inlier ratios between 0.56 and 0.78** under our real K
  — high enough that any inlier-ratio gate would have accepted them as loop
  closures. One (`closet_clothes`) has a focal estimate within **0.3%** of our
  calibration, better than most of the true positives.
- **All six are rejected by rotation reciprocity** — 118.98°, 126.88°, 164.21°,
  177.31°, and two that produced no reverse pose at all.

**What this costs the report anyway:** I can no longer quote a false-positive rate
*over the corpus*, because the corpus's own negatives are contaminated. What I can
quote is the hard-negative result above (0 of 6 admitted by the gate) and the
in-corpus result (0 of 10 admitted). Both come from a negative set I chose by eye,
which is a real selection risk, and 16 negatives is a small number.

> **Corpus finding, independent of any model: this corpus contains almost no
> genuinely different places.** Any future loop-closure evaluation on it will
> struggle to measure a false-positive rate, because nearly every honest pair *is*
> a loop closure. That is a limitation of the corpus, not of the method — and it
> is a good reason to capture a second, different environment before trusting any
> place-recognition number measured here.

### 4.4b Where my result and the literature agree — hallucination is real, and I measured it

The published record on hallucination is damning, and my hard-negative result
confirms it rather than contradicting it:

> "Our analysis shows that VGGT, MASt3R, DUSt3R, and Fast3R can hallucinate dense
> geometry and cross-view support for unrelated scenes, repeated images, and
> random noise." … "in the L₃ setting, roughly 89% of view pairs are cross-scene
> pairs and should have zero overlap, yet **DUSt3R reports zero overlap for only
> 26% of pairs**, fabricating shared geometry for a large fraction of unrelated
> views." [Q — SysCON3D, arXiv 2605.18754 §5 / App. H.2 Table 5]

Also: non-overlapping pairs produce large rotation error — **ΔR (deg): DUSt3R
54.40, MASt3R 24.18, VGGT 51.69, π³ 68.46** [Q — arXiv 2603.26584 Table 2]; and
confidence is *overconfident precisely under limited overlap* [Q — LoRA3D, arXiv
2412.07746 §4.1 and Fig. 4: "the prediction confidence may not precisely reflect
the prediction accuracy", "overconfident predictions"].

The reconciliation is the important part:

> **The pointmap head hallucinates. The matcher hallucinates less but still
> hallucinates. Neither the model's own confidence nor the inlier ratio tells you
> which happened. Only reciprocity does.** MASt3R emitted a complete pointmap, a
> focal estimate and a confidence map for **all six** visually-verified
> different-place pairs — it never once said "these images do not overlap." Four
> of six also produced 10-78 essential-matrix inliers at ratios of 0.56-0.78 [M].
> What refused, in every case, was **rotation reciprocity**.

That directly answers the brief's concern — *a model that always returns a
confident pointmap is useless for loop closure* — and the answer is: **yes, it
always returns one, and yes, that makes the raw model useless for loop closure.**
It becomes useful only behind an external verification stage. This is not a
workaround; it is what the field already does. MASt3R-SLAM gates its loop closures
on *match count after decoder verification* rather than on the pointmap
[Q — arXiv 2412.12392v2 §3.4: "we give these pairs to the MASt3R decoder and add
bidirectional edges if the number of matches … is above a threshold ω_l"] — and my
hard negatives show that even that gate is not enough on our footage, because four
of six clear the match-count bar. **Reciprocity is the gate that holds.**

### 4.5 Reciprocity is the safety check — confirmed from a new direction

The prior work established this the hard way: a wrong Sim(3) reprojected at
1.62 px median with 88% of points under 3 px and was wrong by a factor of 3.2 in
scale [Q]. This lane reproduces the same lesson inside a completely different
estimator:

| pair | E-inlier ratio (looks great) | rotation reciprocity (tells the truth) |
|---|---|---|
| purerot seg0-0 | **0.99** (2089 of 2101) | **179.98°** — garbage |
| purerot seg7-0 | **1.00** (2095 of 2095) | 1.06°, but t-direction 83.8° |
| hardneg door_towel | **0.78** (28 of 36) | **126.88°** — garbage |
| hardneg desk_rgb | **0.70** (78 of 111) | **177.31°** — garbage |
| hardneg fairylights | **0.68** (13 of 19) | **118.98°** — garbage |
| hardneg corridor_floor | **0.60** (28 of 47) | **164.21°** — garbage |
| neg_insess seg8-43 | 0.53 | **176.75°** — garbage |
| blind seg0-45 | 0.83 | **1.20°** — good |
| neg_insess seg6-30 (a true positive) | 0.95 | **2.65°** — good |

**Inlier count and inlier ratio do not separate good from garbage. Reciprocity
does — perfectly, on this sample** (AUC 0.000 across all 110 positive–negative
comparisons, §4.2b). `seg0-0` has a 99% inlier ratio on 2,101 matches and a
completely meaningless pose; `door_towel` pairs a bedroom with a laundry-room door
at a 78% inlier ratio. Any adoption of these models must gate on forward/reverse
agreement, never on match count, inlier ratio, reprojection error, or the model's
own confidence. **This is the third independent time this repo has arrived at that
conclusion, now from a completely different estimator.**

### 4.6 Pure rotation: matching survives, the essential-matrix route does not

On `pure_rotation` pairs MASt3R's matcher is at its best — median **2,098 matches
at a 0.98 inlier ratio** [M], far above anything ORB produces. But the pose
recovered by routing those matches through `findEssentialMat` + `recoverPose` is
unreliable: median translation-direction reciprocity **104.6°** [M] — exactly as
theory demands, since with no baseline the essential matrix is rank-deficient and
translation direction is unidentifiable.

> **Feeding MASt3R's matches into classical two-view geometry inherits classical
> two-view geometry's degeneracies.** The escape from pure-rotation degeneracy is
> the *pointmap*, not the matcher. To get it you must use the PnP-on-pointmap
> route (DUSt3R's `PairViewer`), not the essential-matrix route.

This is also the cleanest possible answer to "would a better matcher help us?" It
was already *no* at 54.7% baseline-limited [Q]. This lane confirms it from the
other side: **MASt3R's matcher is dramatically better than ORB and, used
classically, still cannot pose a rotation-only pair.** The literature's
counterpart — MASt3R-SfM at 62.2% RRA@5 on pure rotation where COLMAP gets 4.1%
[Q — Table 8] — comes from its pointmap-based global alignment, not from its
matches.

### 4.6b Our own privacy redaction breaks the dense matcher — the one regime where ORB wins

Five of the ten `blind` pairs share a single keyframe, `00001824`, and all five
behave completely differently from the other five. Measured [M]:

| pair | ORB verified inliers | MASt3R matches | E-inliers | recip R |
|---|---|---|---|---|
| seg3-18 | **188** | **8** | **0** | — |
| seg0-18 | **197** | **18** | 12 | — |
| seg13-18 | **184** | **23** | 14 | 21.93° |
| seg1-18 | **211** | **38** | 22 | 10.63° |
| *(the five pairs not involving kf 00001824)* | 208–340 | 913–1787 | 758–1764 | 0.05–1.20° |

Keyframe `00001824` is **62.1% exactly-black pixels** [M], and that black is a
single connected component whose bounding box is filled to **99.4%** — a solid
339×421 rectangle, not scene darkness (21 black components in this frame against
463–522 in a normal one) [M]. It is a redaction fill. The repo's face redactor
uses `FILL_VALUE = 0` — "Solid fill, not blur. Blur is partially invertible" [Q —
`tower/world_builder/redaction.py`].

Across the whole session [M]: median exactly-black fraction 0.014, mean 0.107,
p90 0.452, max 0.842; **22.1% of the 457 keyframes are more than 10% black, 13.3%
are more than 40% black, and 4.6% are more than 60% black.** This is not a rare
edge case.

> **Finding: solid-fill redaction degrades a dense pointmap matcher far more than
> it degrades a sparse detector, and the repo's own redaction cost analysis cannot
> detect this because it was measured against ORB.** The redaction docstring
> reports "identical ORB retention (86% vs 86% at 30% of the frame)" and "keyframe
> acceptance and pose solving were completely insensitive" [Q — `redaction.py`].
> Both statements are true and neither transfers. ORB only needs corners in the
> surviving sliver; a transformer attends over the whole image, and 62% of the
> attention budget is spent on a constant. **On these frames MASt3R produces 4-25×
> *fewer* matches than ORB** — the only regime in this entire study where the
> classical pipeline outperforms the learned one, and it is a regime we created
> ourselves.

Two consequences, both actionable. First, **any adoption plan must measure against
redacted frames, not clean ones**, and 13.3% of our keyframes are heavily
redacted. Second, this is a reason to revisit the *fill value*: an inpaint, a
noise fill, or blur (the redactor explicitly rejected blur on invertibility
grounds, which is a sound privacy argument) would give a dense model something to
attend to. That is a genuine privacy/geometry trade-off this project has not yet
had to make, because until now the only consumer was ORB.

**It also skews my own blind group.** Half of it is this one degenerate keyframe.
Split [M]: the five clean blind pairs have a median of **1,312 matches, 1,210
E-inliers and 0.36° rotation reciprocity**; the five `00001824` pairs have a median
of **23 matches and 14 E-inliers**. Quoting a single "blind" median over both is
misleading, and §4.2b's group table should be read with that in mind.

### 4.7 The metric-scale oracle — and it fails

MASt3R's `_metric` checkpoint claims real-world scale. Its median scene depths on
our frames land at **1.64 m (range 0.65–3.14 m)** [M, n=42 estimates] — plausible
for a bedroom, but plausibility is not a measurement.

The only real oracle available is the classical Sim(3): segment 5's length unit is
**0.3533** of segment 4's, with the independent reverse estimate agreeing to 0.3%
[Q]. From the stored reconstruction I computed each segment's gauge depth at the
exact keyframes used in the oracle pair [M — `gauge_depths.py`]: seg-4 kf
`00000461` median landmark depth 14.03 (world→cam) / 16.00 (cam→world); seg-5 kf
`00000503` 9.16 / 7.80. If MASt3R's metric head were correct, the ratio of its
metric depths at those two keyframes would have to be

```
m₅/m₄ = 0.3533 · d₅/d₄  →  predicted m₅/m₄ ∈ [0.172, 0.231]     [E]
```
(the interval spans the two possible pose conventions in the stored data; both are
reported because the convention could not be settled from the schema alone).

**Measured: MASt3R returned 1.46 m for both keyframes — a ratio of ≈1.0** [M].
That is **4–6× away from the oracle's prediction.**

**Verdict: do not trust the metric scale.** Two readings are possible and I cannot
separate them without ground truth: either MASt3R's metric head is wrong on our
footage, or the classical 0.3533 is wrong. Note the classical estimate is the one
with an *independent reverse solve agreeing to 0.3%*, so on available evidence the
burden falls on the metric head. Either way the useful output is that **they
disagree by 4-6×** — exactly the kind of silent disagreement a shipping system
must never resolve by picking one.

**Caveat on this test, which a reviewer should weigh.** It assumes the median
*sparse landmark* depth and the median *dense pointmap* depth measure the same
scene extent. They do not exactly: ORB landmarks concentrate on textured regions,
while the pointmap covers everything including near-field hands and a laptop
screen. The two are correlated, not identical, and that could account for a factor
of maybe 1.5×. It does not plausibly account for 4-6×. Also note the two
keyframes are of the same room at similar standoff, so a *correct* metric head
returning ≈1.0 is not absurd on its face — which is precisely why this
disagreement should be read as "one of these two gauges is wrong", not as "MASt3R
is definitely wrong".

---

## 5. Per-system verdicts on role (question 4)

**DUSt3R — measurably worse than MASt3R on our footage, on both axes I could
test.** No matching head, no retrieval, no incremental state. Run on the same 10
pairs [M]:

- **Focal error: median +27.4%, range +16.0% to +48.4%, and 20 of 20 estimates
  are over-estimates** — against MASt3R's +11.0% median on the same imagery. DUSt3R
  is 2.5× worse at recovering a focal we know the true value of.
- **Its PnP-from-pointmap pose succeeded on only 4 of 10 pairs.** Critically, it
  **failed on `seg0-45`** — the pair where MASt3R produced 758 verified
  correspondences at 1.20° reciprocity. On our hardest and most valuable case,
  DUSt3R returns nothing.
- Its one advantage is speed: **0.35–0.68 s per symmetric pair uncontended**,
  roughly 5× faster than MASt3R (§6), because it lacks the descriptor head and the
  reciprocal matcher.

Its global aligner is the memory wall (§7.1). **Verdict: useful as the minimal
reference implementation of the pointmap idea, and as the thing that makes MASt3R's
extra machinery look load-bearing rather than decorative. Not a component.**

**MASt3R — the best fit for us, specifically as a *background refinement /
offline re-registration* pass.** It is the only system here that solved the actual
problem on our actual frames (§4.3, §4.4). It is not a live tracker: ~1.2 s per
directed pass on this GPU unoptimised, at best (§6), against a capture rate of
11.99 fps. It is an excellent *verifier* for a candidate list our existing ORB
pass already produces at 2.32 ms/pair [M].

**MASt3R-SLAM — architecturally the closest thing to what World Builder is
missing.** Read from source [M — `/c/m3s/MASt3R-SLAM/main.py`, `config/base.yaml`]:
a `retrieval_database` (ASMK, `k: 3`, `min_thresh: 5e-3`), a `relocalization()`
routine, a `FactorGraph` with `solve_GN_calib()` / `solve_GN_rays()`, and a
`run_backend` thread — i.e. exactly the covisibility + relocalisation + pose-graph
machinery the lead's supplement confirms we do not have. It supports uncalibrated
(`use_calib: False`) and calibrated operation via `config/intrinsics.yaml`, so our
ChArUco calibration is directly usable. Published: **15 FPS** on an "Intel Core i9
12900K 3.50GHz and a single NVIDIA GeForce RTX 4090"; per-frame tracking 45.9 ms
(encoder 13.2, decoder 26.2, match 1.9, solve 2.2), per-keyframe 164.9 ms
(retrieval 14.6, decoder 99.5, match 6.2, Gauss-Newton 42.4) [Q — arXiv
2412.12392v2 §4, Table 8]. Its loop closure is the design we should copy even if we
never run its code:

> "To close both small and large loops, we adapt the Aggregated Selective Match
> Kernel (ASMK) framework used by MASt3R-SfM for image retrieval from encoded
> features. While this was previously used in a batch setting where all images are
> available from the start, **we modify it to work incrementally.**" [Q — §3.4]

Its own stated limitation is directly relevant to us: **"Since MASt3R is only
trained on images with pinhole images, its geometry predictions degrade with
increasing distortion"** [Q — §5] — and our frames carry measured radial
distortion `k1=0.144, k2=−0.928, k3=1.300`. That is the leading hypothesis for the
focal bias in §8.2.

**VGGT — offline reconstruction of a bounded window. Not live, no loop closure.**
No retrieval, no incremental state; its "loop closure" is simply that all frames
sit in one attention pass, which is why frame count is a hard VRAM question (§7.2).
Its licence is the only one in my brief with a commercial path (§9.2). Its own
Limitations section is short and worth quoting in full: *"the current model does
not support fisheye or panoramic images. Additionally, reconstruction performance
drops under conditions involving extreme input rotations. Moreover, although our
model handles scenes with minor non-rigid motions, it fails in scenarios involving
substantial non-rigid deformation."* [Q — arXiv 2503.11651v1]

**None of them is a live tracker for us.** Our frontend costs ~5 ms/frame and our
ORB backend ~3.9 ms median [Q — repo]. Only MASt3R-SLAM's published 45.9 ms/frame
is even the same order, and that is on a 4090.

---

## 6. Accuracy / latency, measured

**Read the contention caveat first.** The same call took 0.35 s and 85.45 s on
this host within one run [M]. Only the *minima* are meaningful as latency; the
maxima measure the other lane, not the model.

| measurement | value | label |
|---|---|---|
| **DUSt3R, symmetric pair (2 directed passes), uncontended** | **0.35–0.68 s** | [M] |
| → per directed forward pass | **≈0.18–0.34 s** | [E, = /2] |
| same call, contended, same run | 13.0, 37.6, 45.1, 76.9, 85.5 s | [M] |
| **MASt3R pair (2 passes + reciprocal matching + 2 E-fits), least contended** | **2.2–4.2 s, median 2.4 s** | [M] |
| → per directed pass incl. matching | **≈1.2 s** | [E, = median/2] |
| same work, moderately contended (16 of 32 pairs) | 6.3–11.0 s, median 8.0 s | [M] |
| same work, heavily contended | up to **241 s** | [M] |
| **VGGT, 2 frames at 518×518, bf16** | 1.08 s | [M] |
| **VGGT, 4 frames** | 1.13 s | [M] |
| MASt3R peak VRAM, one pair at 288×512, fp32 | **3,019 MiB** | [M] |
| DUSt3R peak VRAM, one symmetric pair at 288×512, fp32 | **2,873 MiB** | [M] |
| VGGT peak VRAM, 2 / 4 frames at 518×518, bf16 | **7,389 / 7,948 MiB** | [M] |
| DUSt3R parameter count | 571.2 M | [M] |
| VGGT parameter count | 1.26 B | [M] |
| our ORB pipeline, per cross-segment keyframe comparison | 2.32 ms | [M] |
| published DUSt3R latency | ≈40 ms/pair on **H100** | [Q — arXiv 2312.14132v3 §3.4] |
| published MASt3R latency (third-party) | **198.16 ms/pair on an A40**; optimised variant 91 ms | [Q — Speedy MASt3R, arXiv 2503.10017] |
| published MASt3R-SLAM | 15 FPS; 45.9 ms/frame tracking on **RTX 4090** | [Q — arXiv 2412.12392v2] |

Our uncontended DUSt3R figure (0.18-0.34 s/pass, fp32, no compiled RoPE kernel, a
consumer card) sits about 5-8× off the published 40 ms on an H100 — which is
roughly what that hardware and precision gap should cost, so the numbers are
mutually consistent. MASt3R's ≈1.2 s carries the extra descriptor head, the
FastNN reciprocal matcher and two essential-matrix fits; the published A40/H100
ratio between the two models (198 ms vs 40 ms, ≈5×) matches our own ratio (1.2 s
vs 0.25 s, ≈5×) closely enough to trust both.

Cost of the pass we would actually want [E — measured candidate counts × the
measured per-pair rate; no extrapolation beyond that]:

| workload | MASt3R at our measured 2.4 s/pair | DUSt3R at our measured 0.5 s/pair |
|---|---|---|
| the 102 segment pairs with ≥60 ORB inliers | **4.1 min** | 51 s |
| all 442 pairs above the backend's own `MIN_INLIERS` | **17.7 min** | 3.7 min |
| all 830 pairs with ≥1 verified inlier | 33 min | 6.9 min |
| the complete 104,196-keyframe-pair graph | 69 days | 14 days |

**Every row but the last is an affordable background pass at our own unoptimised
rate, on this card, today. It is the complete graph that is unaffordable, not the
model** — which is why §7's conclusion is about *how you choose pairs*, not about
whether the model is fast enough.

---

## 7. Scaling on an RTX 5070 12 GB (question 5)

### 7.1 DUSt3R / MASt3R: pairwise is fine, the global aligner is not

Pairwise inference is cheap and flat: **2.87 GiB** (DUSt3R) / **3.02 GiB**
(MASt3R) per pair regardless of session size [M]. The cost is **quadratic in pair
count**, and the aligner's memory is the wall.

The aligner (`BasePCOptimizer._init_from_views` [M — read
`dust3r/cloud_opt/base_opt.py:64-80`]) stores, **per directed edge**, both
pointmaps and both confidences on the device:

```
2 × (512·288·3) × 4 B  +  2 × (512·288) × 4 B  =  4,718,592 B  =  4.50 MiB / directed edge   [M, exact]
```

A complete symmetrised graph on N images has N(N−1) directed edges [E, exact
arithmetic from that measured constant]:

| N images | directed edges | pointmap+conf store | fits 12 GB? |
|---|---|---|---|
| 16 | 240 | 1.05 GiB | yes |
| 24 | 552 | 2.43 GiB | yes |
| 30 | 870 | 3.82 GiB | tight |
| 40 | 1,560 | 6.86 GiB | no (autograd on top) |
| 50 | 2,450 | 10.77 GiB | **no** |
| 100 | 9,900 | 43.51 GiB | no |
| **457** (our keyframes) | 208,392 | **915.79 GiB** | no |
| **1848** (our frames) | 3,413,256 | **14.65 TiB** | no |

Sliding-window graphs do not save it, and cost the only thing we want:

| swin window on N=457 | edges | store | loop closure? |
|---|---|---|---|
| 1 | ~914 | 4.02 GiB | **none** |
| 3 | ~2,742 | 12.05 GiB | none |
| 5 | ~4,570 | 20.08 GiB | none |

Inference time alone, complete graph on 457 keyframes at the uncontended 3.2 s
per directed pass: **208,392 × 3.2 s ≈ 185 hours** [E]. At the published A40 rate
of 198 ms it is still **≈11.5 hours** [E].

This is corroborated from four independent directions:

- Fast3R Table 2, single **A100**, 512×384: DUSt3R **2 views 0.092 s / 3.52 GiB;
  8 views 8.386 s / 24.59 GiB; 32 views 129.0 s / 67.61 GiB; 48 views OOM** [Q —
  arXiv 2501.13928v2].
- DUSt3R OOMs at **29 images on a 16 GB V100** [Q — naver/dust3r issues/1].
- ~300 images → **107,256 pairs**, **256 GB of system RAM exhausted in 30 min** on
  an RTX 3090 [Q — naver/dust3r issues/111].
- Align3R: DUSt3R's global optimisation **OOMs on a 4090 beyond ~30 frames**
  [Q — arXiv 2412.03079].

And the fix the authors themselves adopted is retrieval, not more memory —
MASt3R-SfM Table 4, 200 views on Tanks&Temples [Q — arXiv 2409.19152v1]:

| scene graph | ATE↓ | #pairs | GPU mem | avg time |
|---|---|---|---|---|
| complete | 0.01256 | 39,800 | 29.9 GB | 2.2 h |
| local window | 0.02509 | 2,744 | 7.6 GB | 14.1 min |
| **retrieval** | **0.01243** | 2,758 | **8.4 GB** | **14.3 min** |

14× fewer pairs, 3.6× less memory, 9× faster — **and a better ATE.**

> **Conclusion for question 5: DUSt3R/MASt3R pairwise inference scales to our
> corpus; DUSt3R/MASt3R global alignment does not, by three orders of magnitude.**
> The only viable shape on a 12 GB card is: *retrieval proposes a few hundred pairs
> → the pointmap model verifies each pair independently → the resulting relative
> poses go into OUR pose graph.* That is not "run DUSt3R on the session"; it is
> "use it as a two-view backend" — exactly the seam `backend.py` already declares
> [Q — its docstring anticipates "a feed-forward pointmap model (DA3 and its kin)
> is a *backend*, not an architecture"].

### 7.2 VGGT frame-count ceiling

VGGT holds all frames in one globally-attending pass, so N is a hard VRAM
question. **Measured here** [M], VGGT-1B in bf16 on real Ray-Ban keyframes,
518×518 canvas, RTX 5070 12,227 MiB, `vggt_scaling.py`:

| frames | peak VRAM | forward time | median f̂x | error vs 630.56 px |
|---|---|---|---|---|
| 2 | **7,389 MiB** | 1.08 s | 845.4 | +34.1% |
| 4 | **7,948 MiB** | 1.13 s | 811.4 | +28.7% |
| 8 | **9,324 MiB** | 97.85 s ‡ | 757.2 | +20.1% |

‡ the GPU was shared; the 8-frame forward is not a clean latency measurement,
while the 2- and 4-frame ones are.

Two things stand out. **The model alone costs 7.4 GiB before it has seen a second
frame** — 60% of the card, for a two-image reconstruction — and the marginal cost
is roughly **240 MiB per additional frame** in this range [E, = (9324−7389)/6].
Linear extrapolation puts the ceiling at **≈20 frames** before the 12,227 MiB card
is exhausted [E], which matches the third-party curve below far better than it
matches the paper's.

A further Windows-specific hazard [M]: at 16 frames the process did **not** raise a
clean `OutOfMemoryError`. Windows' WDDM driver spills to shared system memory
instead, so the run degrades to unusable slowness rather than failing fast. **A
capacity plan that assumes a clean OOM will not get one on this platform.**

The published and third-party record, for context:

- Paper Table 9, *"single NVIDIA H100 … with flash attention v3 … 336×518"*,
  backbone/aggregator only [Q — arXiv 2503.11651v1]: 10 frames 0.14 s / 3.63 GB;
  50 frames 1.04 s / 11.41 GB; 100 frames 3.12 s / 21.15 GB; **200 frames 8.75 s /
  40.63 GB**. The table stops at 200.
- Independently measured on stock VGGT (not backbone-only): **8 images 9.72 GB;
  25 images 12.34 GB; 125 images 31.52 GB; 311 images 68.95 GB** [Q —
  `harry7557558/vggt-low-vram` README] — roughly **3× the paper's figures**.
- On a 24 GB 4090: *"Up to around 100 images, the results look reasonable. But
  beyond that, the outputs seem to degrade"* [Q — vggt issues/344]. FastVGGT
  reports stock VGGT OOMing *"around 300 frames"* on an **80 GiB A800** [Q — arXiv
  2509.02560].
- The repo's own release note concedes the ceiling is the point: a May 2026 memory
  fix lets VGGT *"run on roughly 2-3x more input frames"* for the same budget
  [Q — vggt README].

**My measured curve agrees with the third-party one and not with the paper's**:
`vggt-low-vram` reports 8 images at 9.72 GB where I measure 9.32 GiB, against the
paper's ~3.4 GB for 10 frames. The paper's Table 9 is backbone-only with
flash-attention v3 and should not be used for capacity planning.

> **VGGT's ceiling on this card is ≈20 frames [M/E], not 100 and not 200.**
> Against 457 keyframes, let alone 1,848 frames, it is not a session-scale tool —
> it is a *window*-scale tool with no mechanism to relate one window to the next.
> That is the same architectural gap World Builder already has, moved inside a
> transformer.

---

## 8. Intrinsics, and our calibration as a free validity test (question 7)

### 8.1 Who needs intrinsics

- **DUSt3R / MASt3R: intrinsics are an OUTPUT.** Focal is recovered from the
  pointmap by `estimate_focal_knowing_depth`, a Weiszfeld IRLS solving
  `argmin_f Σ |pixel − f·(x,y)/z|` with the principal point pinned at the image
  centre [M — read `dust3r/post_process.py`]. The paper is explicit that it
  assumes "the principal point is approximately centered and pixel are squares,
  hence only the focal f₁ remains to be estimated" [Q — arXiv 2312.14132v3 §3.3].
  **No principal-point offset, no skew, no distortion is modelled anywhere.**
- **VGGT: an OUTPUT**, and a weaker one — the camera head emits *field of view*,
  two numbers, with the principal point assumed centred [Q — arXiv 2503.11651v1].
- **MASt3R-SLAM: optional.** `use_calib: False` by default; supply
  `config/intrinsics.yaml` to run calibrated [M — read `config/base.yaml`]. It
  works in **ray space** and does not output calibrated intrinsics at all [Q —
  arXiv 2412.12392v2: "Our only assumption on the camera model is that of a
  generic central camera"].

So our ChArUco calibration is not *required* by any of them. **That is what makes
it valuable** — it is free, external, and uncorrelated with anything the model
does.

### 8.2 The consistency check — and it works, mostly

Our calibration is real: `fx=438.225, fy=437.778, cx=174.877, cy=323.380`,
reprojection RMS **0.2893 px** over 511 views, self-calibrated [Q — repo
intrinsics file]. `load_images(size=512)` maps 360×640 onto 288×512 by a pure
isotropic scale of exactly **512/640 = 0.8**, no crop [M — traced through
`dust3r/utils/image.py`]. So the expected focal on the network's canvas is

```
0.5·(438.225 + 437.778) × 0.8 = 350.40 px      [M, exact]
```

**Measured, over 64 independent focal estimates from 32 pairs (MASt3R):**

| statistic | value | label |
|---|---|---|
| median error vs 350.40 px | **+11.0%** | [M] |
| mean error | +13.0% | [M] |
| range | −8.1% … +43.0% | [M] |
| fraction that are **over**-estimates | **89%** (57 of 64) | [M] |
| DUSt3R, same check, first 3 pairs / 6 estimates | +21.7, +25.7, +27.3, +28.2, +28.8, +30.0 % | [M] |

Three findings:

**And VGGT, which estimates intrinsics through a completely different head (a 2-D
field-of-view regression rather than a Weiszfeld fit on a pointmap), agrees on the
sign and roughly on the magnitude.** On its 518×518 canvas the expected `fx` is
`438.225 × 518/360 = 630.56 px` [M, exact]:

| VGGT input frames | median f̂x | error vs 630.56 | label |
|---|---|---|---|
| 2 | 845.4 | **+34.1%** | [M] |
| 4 | 811.4 | **+28.7%** | [M] |
| 8 | 757.2 | **+20.1%** | [M] |

Three independent architectures, three independent focal heads, **all
overestimating in the same direction on the same footage** — and VGGT's error
falling monotonically as more views constrain the solution. That is much stronger
evidence of a systematic cause than any single model's bias would be.

1. **These models systematically overestimate focal on our footage** — i.e. they
   underestimate our field of view. MASt3R's bias (+11.0% median over all 64
   estimates) is under half DUSt3R's (+27.4%). The obvious hypothesis is
   distortion: our frames carry measured radial distortion (`k1=0.144, k2=-0.928,
   k3=1.300`) while these models assume a pinhole camera, and MASt3R-SLAM's own
   authors state the consequence directly — *"Since MASt3R is only trained on
   images with pinhole images, its geometry predictions degrade with increasing
   distortion"* [Q - arXiv 2412.12392v2 §5].

   **I tested that hypothesis and it is refuted.** Both models were re-run on the
   same 10 pairs after `cv2.undistort` with our own K and distortion coefficients
   [M]:

   | | raw, median focal error | undistorted, median focal error |
   |---|---|---|
   | DUSt3R (n=20 estimates) | **+27.37%** | **+27.97%** |
   | MASt3R (n=20 estimates) | **+8.80%** | **+9.34%** |

   Removing the distortion these models are not trained for changes the bias by
   less than a percentage point, in the *wrong* direction. **Radial distortion does
   not explain it.** Remaining candidates, none of which I could test: the
   pinned-at-centre principal point against our true `cx=174.877` (139.9 on the
   canvas, 4.1 px off centre); the portrait aspect ratio, which these models handle
   by internal transposition and see rarely in training; or a plain training-prior
   bias — which is what the independent evaluation that found DUSt3R's intrinsics
   the worst of any method tested attributes it to: *"it lacks strict geometric
   constraints, leading to significant inaccuracies in intrinsic estimation"*
   [Q - arXiv 2503.00737].

   **The same experiment produced an unexpected positive, and it is the more
   useful half** [M]:

   | | raw | undistorted |
   |---|---|---|
   | median E-inlier ratio over the 10 pairs | 0.748 | **0.829** |
   | median E-inliers | 212 | **260** |
   | `seg5-30` (a true positive ORB scored zero on): matches / E-inl / ratio | 141 / 56 / 0.40 | **286 / 205 / 0.72** |

   That is exactly what theory predicts and what the focal check does not deliver:
   the essential-matrix fit assumes a pinhole camera, so undistorting first makes
   the epipolar geometry *actually valid*. **Our distortion coefficients are
   load-bearing — for the verification step, not for the focal comparison.
   Undistort before verifying.**
2. **A large focal error is not unique to us.** Independent evaluation on camera
   arrays reports DUSt3R with the worst intrinsics of any method tested — mean
   relative focal error **774.200 ‰ (Linear) / 1309.893 ‰ (DPT)** against COLMAP's
   31.610 ‰ — with the diagnosis that *"it lacks strict geometric constraints,
   leading to significant inaccuracies in intrinsic estimation"* [Q — Multi-Cali
   Anything, arXiv 2503.00737 Table I; note that is a large-scale camera-array
   setting, not ours]. And the DUSt3R authors' own follow-up, **Pow3R**, measures
   the value of supplying intrinsics: GT intrinsics raise focal accuracy by
   **+36.0 points**, and on DTU improve reconstruction by **+19% relative**, while
   supplying GT *pose* alone gives **−4%** [Q — arXiv 2503.17316 Tables 1, 4]. In
   other words: **the calibration we already have is the single most valuable
   thing we could hand one of these models, and there already exists a variant
   built to accept it.**
3. **The focal check is NOT a place-match discriminator. I expected it to be, and
   it is not.** Measured over the 32-pair sample: **AUC 0.488** for separating
   same-place from different-place on the original labels, and only 0.709 after
   correcting them (§4.2b). The anecdote that suggested otherwise — good pairs at
   +5.2%, −8.1%, −6.0%, +0.3% and garbage pairs at +20.7%, +19.1%, +22.0%,
   +33.9%, +37.8% — is falsified outright by three counterexamples in the same
   data: `seg24-46` (focal +5.4%, reciprocity 81.16°), `xcap4` (+5.1%, 117.20°),
   and worst of all the hard negative `closet_clothes`, whose focal estimate is
   **−0.3%** — closer to our calibration than any true positive — on a pair of a
   bedroom and a closet. **This is a negative result on the specific hypothesis
   the brief asked me to pursue, and I am reporting it as one.**

**What the calibration IS worth, which turns out to be more than the focal check
was going to be worth.** Three things, in descending order of value:

- **It is already doing the work, in the verification step — both halves of it.**
  The second-strongest discriminator I measured, E-inlier ratio (AUC 0.936 on
  corrected labels), is the fraction of MASt3R's matches that survive an
  essential-matrix fit **under our real ChArUco K** at the backend's own 1.0 px
  threshold. That test is only meaningful because the K is real: had I used the
  model's own +11% focal, the fit would have been systematically wrong. And the
  *distortion* half of the same calibration lifts that discriminator measurably —
  median E-inlier ratio 0.748 → **0.829** when the frames are undistorted first
  [M]. **The calibration's value is as the metric for geometric verification, not
  as a comparison against the model's guess.**
- **It is a distribution-shift alarm, not a per-pair gate.** A whole capture whose
  focal estimates drift away from 350.4 px means something changed about the
  camera, the crop, or the imaging assumptions. Per-pair it is noise; in aggregate
  it is a real check — and the fact that three architecturally unrelated models all
  land 11-34% high on the same footage is exactly the kind of aggregate signal that
  is worth watching, even though I could not identify its cause.
- **It is the input a purpose-built variant wants.** Pow3R exists precisely to
  consume it, for a measured **+36.0 point** gain in focal accuracy and **+19%
  relative** reconstruction improvement on DTU [Q].

> **Gate on reciprocity and on E-inlier ratio under our real, undistorted K. Do
> not gate on focal agreement.** And 38 pairs is far too few to fix any threshold
> on.

---

## 9. Licensing (question 8) — the part most often misread

I read the licence files in the cloned repositories directly rather than relying
on summaries. **Separate CODE from WEIGHTS from TRAINING-DATA terms.**

### 9.1 The Naver chain: CroCo → DUSt3R → MASt3R → MASt3R-SLAM

**Code.** All four are **CC BY-NC-SA 4.0**, verbatim [Q — `LICENSE` in each repo,
read here]:

> "DUSt3R, Copyright (c) 2024-present Naver Corporation, is licensed under the
> Creative Commons Attribution-NonCommercial-ShareAlike 4.0 license."

identically for MASt3R, CroCo, and MASt3R-SLAM (`LICENSE.md`). Every source file
carries `# Licensed under CC BY-NC-SA 4.0 (non-commercial use only).`

**Weights — the part that gets missed.** The checkpoints carry the CC BY-NC-SA
terms **plus** a stack of independently non-commercial dataset terms. MASt3R's
README is explicit [Q]:

> "Make sure to agree to the license of all the training datasets we used, in
> addition to CC-BY-NC-SA 4.0. **The mapfree dataset license in particular is very
> restrictive.**"

Reading `mast3r/CHECKPOINTS_NOTICE` (1,376 lines) [M — read here]:

| source | terms | why it binds the weights |
|---|---|---|
| **Niantic Map-Free Relocalization** | *"You may only use the Dataset only for non-commercial purposes… Non-commercial use expressly excludes any profit-making or commercial activities"* — and the agreement defines the Dataset as **"the Dataset or dataset-derived materials (collectively, the 'Dataset')"** | The definition explicitly reaches derived materials. Weights trained on it *are* dataset-derived materials. **This alone forecloses commercial use.** |
| **IndoorVL** (Gangnam Station, Hyundai Dept Store) | CC BY-NC-**ND** 4.0 (modified): *"reproduce and Share the Licensed Material… for NonCommercial purposes only"*; *"produce and reproduce, **but not Share**, Adapted Material"*; sharing adapted material limited to "Research purposes", itself defined as *"to publish research achievements in a research paper"* | NoDerivatives, plus a research-publication-only carve-out. |
| **3D_Street_View** | *"you may not use the dataset or any derivative work for commercial purposes"*; *"you do not distribute this dataset or modified versions"* | — |
| ScanNet++ | non-commercial research and educational purposes only | — |
| Waymo Open | Non-Commercial Use | — |
| CO3Dv2 | CC BY-NC 4.0 | — |
| ARKitScenes | CC BY-NC-SA 4.0 | — |
| Virtual KITTI 2 | CC BY-NC-SA 3.0 | — |
| DL3DV-10K | CC BY-NC 4.0 | — |
| Habitat / HM3D | Matterport academic-use EULA | — |
| NVIDIA SegFormer | NVIDIA Source Code License | — |
| Stability CosXL | CosXL License Agreement | — |
| *(permissive, for contrast)* | BlendedMVS CC BY 4.0; MegaDepth MIT; WildRGB-D MIT; StaticThings3D Apache-2.0; TartanAir CC BY 4.0; UnrealStereo4K MIT | do not help — the restrictive terms dominate |

**Two traps in that file.** First, the string **"Apache License"** appears near
line 30 of `CHECKPOINTS_NOTICE` but belongs to *3D_Street_View's* standard terms,
not to the DUSt3R checkpoint [Q]; a skim-read will mistake it for an Apache grant
on the weights. Second, CroCo is CC BY-NC-SA overall but its file tree is mixed —
`models/blocks.py` is Apache-2.0 (from `pytorch-image-models`),
`models/pos_embed.py` derives from MAE under CC BY-NC 4.0 [Q — croco LICENSE].
Neither exception rescues the whole.

**The poison starts one level earlier than most people check.** CroCo v2 — the
pretrained backbone every DUSt3R and MASt3R checkpoint is fine-tuned from — was
trained on `habitat_release+ARKitScenes+MegaDepth+3DStreetView+IndoorVL`
[Q — verbatim `--dataset` argument in croco's own README pre-training command,
read here]. **IndoorVL and 3DStreetView are in the base model.** There is no
DUSt3R or MASt3R checkpoint that does not descend from them.

**No commercial licence is offered anywhere in these repositories.** Neither
checkpoint is HF-gated (`"gated": false` on both Naver models [Q]), which makes
this *easier* to get wrong, not harder — nothing stops you downloading them.

### 9.2 VGGT: a genuinely different situation

- **Code:** `LICENSE.txt` is the **"VGGT License, v1, Last Updated: July 29,
  2025"** [Q — read here]. It grants *"a non-exclusive, worldwide,
  non-transferable and royalty-free limited license … to use, reproduce,
  distribute, copy, create derivative works of, and make modifications to the
  Research Materials."* **There is no non-commercial clause.** Conditions:
  redistribute only under the same agreement, acknowledge in publications, comply
  with the incorporated Acceptable Use Policy, California law, and Meta may modify
  the agreement unilaterally (*"All such changes will be effective immediately"*).
  The repo was CC BY-NC 4.0 until commit `a1179fe9`, 2025-07-29, message
  **"RELICENSE for commercial use"** [Q].
  ⚠ **Caveat worth flagging to counsel: the licence text never uses the word
  "commercial" and never defines it.** The commercial permission is asserted only
  in the README [Q].
- **Weights, and this is the split that matters:**
  - `facebook/VGGT-1B` — HF licence tag **`cc-by-nc-4.0`**, ungated, 433,527
    downloads [Q]. **Not commercially usable.** This is the checkpoint every
    tutorial downloads and the one this lane downloaded.
  - `facebook/VGGT-1B-Commercial` — licence `vggt-aup-license`, **gated:
    `manual`**, 1,983 downloads [Q]. Commercial use permitted; the AUP's prohibited
    uses include *"Military, warfare, nuclear industries or applications,
    espionage, use for materials or activities that are subject to the
    International Traffic Arms Regulations (ITAR)"* [Q]. Meta report it performs
    the same or slightly better (*"AUC@30: 90.37 vs. 89.98 on the Co3D dataset"*)
    [Q].
  - **Whether VGGT-1B-Commercial was trained only on commercially-usable data is
    publicly undocumented** — the gated card is not fetchable [Q, negative
    finding]. Do not assume it was.

### 9.3 The one clean option — outside my brief, found while checking licences

**MapAnything** (Meta, arXiv 2509.13414, 3DV 2026) ships **two checkpoints
differing only in training-data licensing**: `facebook/map-anything-apache`
(**Apache 2.0**, six permissively-licensed datasets — BlendedMVS, Mapillary
Planet-Scale Depth, ScanNet++ v2, Spring, TartanAirV2-WB, UnrealStereo4K) and
`facebook/map-anything` (CC BY-NC 4.0, thirteen datasets). Code is Apache 2.0.
Their README: *"The only difference is the training data composition and resulting
license terms"*; the paper states they *"obtained approval from the dataset owners
that allows training and model release under a permissive license"* [Q].

> **If a pointmap model is ever to ship in this product, that is the citation to
> start from.** It was not in my brief and I did not test it, so this is a
> pointer, not a recommendation — but it is the only fully-permissive pointmap
> model I found, and its existence changes the shape of the decision.

### 9.4 Licence summary

| system | code | weights | commercial? |
|---|---|---|---|
| DUSt3R | CC BY-NC-SA 4.0 | + stacked NC dataset terms | **No** |
| MASt3R | CC BY-NC-SA 4.0 | `CHECKPOINTS_NOTICE`, several NC incl. Niantic | **No** |
| MASt3R-SfM | inherits MASt3R | inherits | **No** |
| MASt3R-SLAM | CC BY-NC-SA 4.0 | Naver MASt3R checkpoints | **No** |
| Spann3R | CC BY-NC-SA 4.0 | not stated | **No** |
| MonST3R | CC BY-NC-SA 4.0 | `cc-by-nc-sa-4.0` | **No** |
| Fast3R | FAIR Noncommercial Research License | same | **No** |
| CUT3R | CC BY-NC-SA 4.0 | not stated | **No** |
| π³ / Pi3 | **BSD-3-Clause** | CC BY-NC 4.0 (README) — ⚠ HF card says BSD-2 + "contact the authors"; **conflicting sources** | code only |
| VGGT | VGGT License v1 | `VGGT-1B` NC; `-Commercial` gated | commercial ckpt only |
| **MapAnything-apache** | **Apache 2.0** | **Apache 2.0** | **Yes** |

**Not legal advice.** These readings should be confirmed by counsel before any
adoption decision — particularly the Niantic "dataset-derived materials" clause,
the π³ source conflict, and whether Meta's licence passes VGGT's own training-data
obligations through to downstream users (Meta's licence, unlike Naver's, does not
enumerate them).

---

## 10. Also-rans, briefly, and why they are here

Included only where they change a conclusion.

- **Fast3R** (CVPR 2025, arXiv 2501.13928) — the direct answer to DUSt3R's
  quadratic wall: 1,000 views in 137.6 s / 63.01 GiB on an A100, where DUSt3R OOMs
  past 32 [Q, Table 2]. Relevant because its own limitation is the one we would
  hit: *"for scenes with very large reconstruction areas, when the number of views
  becomes extreme (e.g., more than 300), the point map of some views … begins to
  exhibit drifting behavior"* [Q]. **FAIR Noncommercial Research License** — not
  shippable.
- **CUT3R** (CVPR 2025 Oral, arXiv 2501.12387) — the strongest published claim on
  our exact problem: it targets *"wide-baseline or even non-overlapping images"*
  with a fixed-size persistent state (768 tokens), at 16.58 FPS on an A100 [Q].
  Architecturally the most interesting alternative to a pose graph. CC BY-NC-SA;
  no loop closure; *"may eventually drift over very long sequences due to the
  absence of global alignment"* [Q].
- **Spann3R** (3DV 2025) — 65 FPS with 11 GB on a 4090 [Q], i.e. the only one in
  reach of live use, but explicitly bad at the thing we need: *"during loop
  closing, our model may not fill the geometry correctly due to the accumulated
  errors and outliers"* [Q]. CC BY-NC-SA.
- **π³** (ICLR 2026, arXiv 2507.13347) — permutation-equivariant, 57.4 FPS on an
  A800, **BSD-3 code**. But its weights are CC BY-NC per the README, its intrinsics
  story is absent from the paper entirely (a full-text scan for
  "intrinsic"/"focal" returns zero matches [Q]), and it scores *worst* on
  non-overlapping rotation error of the four systems benchmarked (ΔR 68.46° [Q]).
- **MonST3R** — dynamic scenes; ~33 GB VRAM for a 65-frame 16:9 video [Q]. Not
  relevant to our static-room failure.

---

## 11. What this lane recommends, and what it explicitly does not

**Does NOT recommend:** replacing the classical backend with DUSt3R/MASt3R;
running any global aligner on a session; treating MASt3R's metric depth as scale
(§4.7); gating anything on match count, inlier ratio, reprojection error, or the
model's own confidence (§4.5, and [Q — LoRA3D on confidence being *"overconfident"*
under limited overlap); or believing that a pointmap model will tell you when two
images do not overlap (§4.4b).

**Recommends, in order:**

1. **Take the finding, not the model.** The measurable facts are (a) that a
   pointmap model produces good relative geometry on pairs where *neither* segment
   has prior geometry and where ORB finds *zero* verified correspondences, and
   (b) that **forward/reverse rotation reciprocity** identifies which of those
   results to trust — perfectly, on 110 comparisons, where inlier ratio, match
   count, model confidence and focal agreement all fail. The concrete rule:

   ```
   undistort both frames with our ChArUco dist_coeffs, then
   accept a cross-segment link iff
       angle(R_forward · R_reverse)  <  15°        # two INDEPENDENT solves agree
   and E_inlier_ratio (under our real ChArUco K) > 0.5
   ```
   Measured: **8 of 11 same-place pairs accepted, 0 of 16 different-place pairs
   accepted** (10 in-corpus + 6 visually-verified hard negatives) [M]. Both terms
   are free, need no ground truth, and are model-agnostic. **Adopt them regardless
   of which backend is chosen — this is the durable output of the lane.** Do not
   treat 15°/0.5 as calibrated; 27 pairs cannot calibrate a threshold.
2. **The candidate list already exists and is unused.** 102 strong segment-pair
   candidates, 86 of them touching a geometry-less segment, produced in 233.5 s of
   CPU [M]. Verifying all of them with a pointmap model costs seconds to minutes
   (§6). No learned retrieval model is needed to get started.
3. **If a learned backend is pursued, the licensing forces the choice.**
   VGGT-1B-Commercial or MapAnything-apache, not the Naver line. Neither was
   measured by this lane; measuring them is the obvious next step and would reuse
   this harness unchanged.
4. **The seam already exists.** `backend.py` takes a window of keyframes, returns
   poses in a local frame, and refuses when it cannot justify an answer [Q — repo].
   A pointmap verifier fits behind it unchanged. Do **not** architect around
   DUSt3R; architect around "a two-view backend that can answer where classical
   cannot," and keep the model swappable — the licence situation alone guarantees
   it will need to be.
5. **Capture a second, genuinely different environment before trusting any
   place-recognition number.** The corpus is one apartment (§4.4); false-positive
   rate is currently unmeasurable on it.

**And the negative result, stated plainly:** these systems are not faster, not
smaller, not simpler, and (except VGGT-Commercial and MapAnything) not licensable.
What they are is *not singular on baseline-limited pairs* — which happens to be our
exact failure mode, and is the only reason this lane returns a positive finding
despite everything else about them being worse.

---

## 12. Reproduction

```
tower/scripts/research/slam_learned_3d/
  select_pairs.py     all-pairs ORB matching over all 457 keyframes (233.5 s)
  build_manifest.py   oracle / blind / purerot / negative pair manifest
  gauge_depths.py     per-segment gauge depth, for the metric-scale oracle
  dust3r_pairs.py     DUSt3R symmetric pair inference + PnP pose + reciprocity
                      (--undistort applies our real ChArUco K + dist first)
  mast3r_pairs.py     MASt3R pair inference + reciprocal matching + E-verify
  analyse.py          group tables + same-place/different-place separability
  dust3r_scaling.py   complete-graph global-alignment scaling until OOM (not run)
  vggt_scaling.py     VGGT frame-count scaling until OOM
  results/            the JSON this report is computed from:
                        pairs.json            all-pairs ORB over 457 keyframes
                        mast3r_analysed.json  32 pairs, corrected reciprocity
                        mast3r_hardneg.json   6 visually-verified hard negatives
                        mast3r_undist.json    the 10-pair undistorted rerun
                        dust3r_raw.json       10 pairs
                        dust3r_undist.json    the same 10, undistorted
                        vggt_scaling.json     N = 2, 4, 8 (+ the 16 note)
```

Third-party code and checkpoints were cloned/downloaded **outside the repo tree**
(`<scratchpad>/thirdparty`, `<scratchpad>/ckpt`, plus `C:\m3s` for MASt3R-SLAM's
long-path clone). Nothing foreign is in git. `roma` and `einops` were installed
with `pip --target` into an isolated directory so `tower/.venv` was **not**
mutated. Runs used `tower/.venv/Scripts/python.exe`, torch 2.13.0+cu132, OpenCV
5.0.0.

### Caveats a reviewer should hold against this report

- **38 pairs total (32 corpus + 6 hard negatives) is a small sample**, and the
  decisive separability claim rests on 11 positives against 16 negatives. The
  separations are large and consistent, but **no threshold should be fixed on
  them.**
- **The label correction in §4.2b(b) is post-hoc and by my own eye.** I moved four
  pairs from negative to positive and excluded five as a different failure mode,
  after seeing the results. Table (a), with the original labels, is given
  alongside precisely so a reviewer can judge how much of the improvement is
  relabelling. Reciprocity is the top discriminator under *both* labellings.
- **The negative set was chosen by me, by eye, from a contact sheet.** That is a
  real selection risk. It is also the only option: the corpus is one apartment and
  contains almost no genuinely different places (§4.4).
- **The GPU was shared throughout.** The same call took 0.35 s and 85.45 s within
  a single run [M]. Only minima are quoted as latency.
- **"Same place" judgements are my visual inspection of two JPEGs.** There is no
  ground truth in this corpus and this report does not pretend otherwise.
- **The metric-scale test (§4.7) compares sparse-landmark depth against dense
  pointmap depth**, which are correlated but not identical quantities.
- **DUSt3R was run on 10 pairs, not 32**, and the raw-vs-undistorted comparison on
  those same 10, after GPU contention forced a reprioritisation. MASt3R carries the
  main result.
- **The VGGT sweep stops at 8 frames.** The 16-frame step did not finish; its
  ceiling (~20 frames) is [E] by linear extrapolation from three measured points,
  cross-checked against a third-party curve, not measured directly.
- **The DUSt3R global-aligner scaling sweep never ran.** §7.1's table is [E] from
  an exactly-measured per-edge constant, corroborated by four published OOM
  reports, not measured on this card.
- **Numbers quoted from the literature carry their own hazards**, flagged where
  relevant: VGGT's Table 9 is backbone-only with flash-attention v3 and understates
  real usage roughly 3×; MASt3R's only per-pair latency figure is third-party; and
  MASt3R-SfM's memory/time table names no GPU.
