# Can Scene Understanding say `in_front_of`? Measured on 9,199 real frames

**Date:** 2026-08-26
**Verdict:** **No — the refusal stands, and now it rests on evidence.**
**Behaviour changed:** none. Only the justification in `state.py` was replaced.
**Corpus:** `tower/data/captures/` — 18 captures, 9,199 real Ray-Ban frames, 360×640 portrait JPEG
**Host:** RTX 5070 (Blackwell, sm_120, 12,226 MB), `torch 2.13.0+cu132`, `timm 1.0.28`

---

## 0. Summary

- **Depth is affordable on both devices, and that is not the problem.** MiDaS-small
  costs **5.73 ms on CUDA and 18.29 ms on CPU** per frame, warm medians on real
  frames, including the bicubic upsample and the per-box median. Against the
  measured **83.4 ms** delivered interval that is **0.07× and 0.22×**. CPU is the
  default device, and unlike orientation *CPU fits comfortably*. **Cost was never
  the blocker here** — a conclusion available only because both devices were
  measured.
- **The headline flip rate looks excellent: 3.8%**, over 2,700 object-pair
  observations, and it is **strongly ordered by depth separation** — 15.7% below
  0.02 separation falling to **0.0% above 0.40**. That is the opposite of the
  rejected two-view-parallax route, which was 15–25% and *flat*.
- **And it is an artefact of a nearly motionless corpus.** Binned by how far the
  boxes moved between frames, the flip rate climbs from **0.00%** in the most
  static quartile to **4.85%** in the top motion decile *at the same separation
  gate* — and inside the band the gate was meant to protect (separation
  0.10–0.20) it goes from **0.0% to 11.5%**. Median inter-frame box motion in
  this corpus is **4.2 px** of a 734.8 px diagonal. There is no walking in it.
- **So the ordering carries real information in a static scene and degrades
  sharply the moment anything moves**, and the regime the product needs — a
  wearer walking through a room — is not sampled by this corpus at all. The
  relations cannot be emitted honestly.
- **The original 6–8% flicker figure was roughly right in magnitude** — measured
  here at **4.82%** per-object frame-to-frame change — **but the ordering
  conclusion drawn from it did not follow.** A model can have noisy absolute
  depth and stable ordering, and in the static case this one does. The refusal
  was reasonable; the reasoning behind it was not. It is now.
- **There is no ground-truth depth on this host.** Everything below measures
  **self-consistency, not accuracy.** MiDaS can be stably, confidently wrong and
  every number here would look identical.

---

## 1. A methodology warning that cost me a run

**`source_seq` steps by 2 in this corpus, not by 1.** Frame sequence numbers go
`1, 5, 7, 9, …`; the median step between *delivered* frames is 2. Treating
`seq + 1` as "the next frame" therefore names a frame that was never delivered,
and silently keeps only the small minority of transitions where the step happens
to be 1.

Measured cost of that mistake, on this exact analysis: **854 candidate frames
instead of 2,688** — a 3.1× undersample, with no error and no warning.

Adjacency must come from **delivered order** within a capture, and should be
gated on the receipt timestamps in each capture's `frames.jsonl`. Anyone
measuring anything frame-to-frame on this corpus will hit this.

### 1.1 The delivered interval, re-confirmed

From the corpus's own `frames.jsonl` receipt timestamps, all 18 captures:

| | |
|---|---|
| median delivered interval | **83.4 ms** (11.99 fps) |
| p95 | 161.2 ms |

This corroborates the 83.5 ms figure `tracking.DELIVERED_FRAME_INTERVAL_S`
already carries. Three captures (n=16, 18, 20 frames) show ~4–6 ms intervals —
bulk or backfill writes, not live delivery. All transitions used below are gated
to a 40–200 ms window, which excludes those and 651 other transitions.

---

## 2. Cost — both devices, because only measuring one is how orientation went wrong

Method mirrors the orientation measurement: JPEG decode happens **before**
timing, so the number is model cost alone; `torch.cuda.synchronize()` brackets
every CUDA call; the first five calls are dropped from warm statistics. The
upsample-and-sample stage is timed separately because Scene Understanding would
pay it too — a raw MiDaS-small prediction is a **1×256×128** grid, not the frame,
so a box cannot be applied to it without resizing first.

| | **CUDA** | **CPU** |
|---|---|---|
| frames timed | 749 | 329 |
| model load | 1740.5 ms | 1567.9 ms |
| first call (cold kernels) | 222.2 ms | 36.6 ms |
| inference, warm **median** | **5.35 ms** | **17.60 ms** |
| inference, warm p95 | 11.25 ms | 23.03 ms |
| upsample + per-box median | 0.38 ms | 0.69 ms |
| **total per frame** | **5.73 ms** | **18.29 ms** |
| **vs 83.4 ms interval** | **0.07×** | **0.22×** |

**The default device is CPU** (`SSDLite320Detector` and `TorchvisionPoseEstimator`
both default to `device="cpu"`), and at 18.29 ms depth still fits inside the
frame budget with room for the detector's ~33 ms beside it.

This is the specific trap that caught orientation, and it does not catch depth.
Orientation's synthetic 798 ms was wrong in both directions at once — the real
figures are 43.4 ms on CUDA and **956.4 ms** on CPU, the default. MiDaS-small is
a genuinely small model and there is no such gap: the CUDA/CPU ratio is 3.3×, not
22×. **Had this been measured only on CUDA the conclusion about cost would still
have been correct** — but that would have been luck, not method, and it is not
the reason the relations are refused.

---

## 3. What was measured, and how a box becomes a depth

The claim at stake is an **ordering between two detected objects** — "the laptop
is in front of the phone" — so what is measured is the stability of that
ordering, not per-pixel depth variance.

- **Detector:** the shipped `ssdlite320_mobilenet_v3_large`, `COCO_V1` weights,
  the shipped `SCORE_THRESHOLD = 0.4`. Run over all 9,199 frames, **0 failures**,
  341 s on CUDA.
- **Depth:** MiDaS-small via `torch.hub` at the same pinned commit the depth
  experiment uses (`454597711…`), bicubic-upsampled to 360×640.
- **Box → depth: the median of the depth field over the box interior.** Chosen
  because it is the obvious reduction and because a median resists the specific
  contamination that matters — **a box always contains background.** A laptop's
  box includes desk behind it; a `bed` box is mostly bed. The median survives
  that as long as the object occupies more than half the box, and fails
  quietly when it does not.
  - Checked against a **central-50% crop**, which contains proportionally less
    background: it is *worse*, 4.7% overall flip vs 4.0%. MiDaS-small's output is
    smooth at this resolution, so the tighter crop mostly buys a smaller sample.
    The full-box median is kept as both the simpler and the better choice.
- **Association across frames:** IoU ≥ **0.25**, the shipped
  `TrackerPolicy.min_iou`, greedy highest-first and one-to-one within a class.
- **Separation** between two objects is reported as
  `|d_A − d_B| / (p95 − p5)` of that frame's own depth field — dimensionless,
  in units of the scene's own depth range. **There is no metric scale available**;
  MiDaS-small emits relative inverse depth and nothing converts it to distance.
  Higher inverse depth means nearer.
- **Classes:** the cartridge's own `CLASSES_OF_INTEREST`, minus `person`.

### 3.1 The honest limits, stated before the numbers

1. **The `person` boxes are the wearer's own torso.** Median 40% of frame, bottom
   edge at 0.981, horizontally centred, 59% touching the bottom edge. They are
   excluded from every number below. The real external objects are `laptop`
   (score 0.813) and `cell phone` (0.844), and those carry the analysis.
2. **There is no ground truth.** This measures whether MiDaS *agrees with itself*
   from one frame to the next. It cannot detect a model that is confidently and
   consistently wrong about which object is nearer, and such a model would
   produce a 0% flip rate.
3. **Sample size bounds everything.** 2,700 pair observations sounds large; the
   cells that decide the verdict hold 23–52. Per-bin `n` is printed beside every
   rate below, and the zero cells carry rule-of-three upper bounds.

### 3.2 Yield

| | |
|---|---|
| frames carrying depth | 2,688 |
| usable frame transitions | **1,849** (651 skipped for interval) |
| **object-pair observations** | **2,700** |
| captures contributing | 13 of 18 |
| distinct class pairs | 32 |
| `laptop` + `cell phone` pairs specifically | **567** |
| per-object observations across a transition | 4,095 |

---

## 4. The headline flip rate, and why it is not the answer

Across consecutive frames where both objects were detected and associated, how
often does the reported ordering reverse?

**103 / 2,700 = 3.8%.**

And it is strongly, monotonically ordered by depth separation:

| separation | n | flip rate | 95% CI |
|---|---|---|---|
| 0.00 – 0.02 | 343 | **15.74%** | ±3.85 |
| 0.02 – 0.05 | 261 | 9.20% | ±3.51 |
| 0.05 – 0.10 | 293 | 3.75% | ±2.18 |
| 0.10 – 0.20 | 499 | 2.20% | ±1.29 |
| 0.20 – 0.40 | 973 | 0.31% | ±0.35 |
| ≥ 0.40 | 331 | **0.00%** | ±0.00 |

**This is the flatness test, and it passes clearly.** The bin-wise slope is
**−25.6 percentage points per unit separation**; the median separation of a
flipped pair is 0.018 against 0.200 for an unflipped one, an 11× gap. A prior
route was rejected because its flip rate was 15–25% *and flat* — 15.8% even at
>3× separation — which meant the ordering carried no information at all. This is
the opposite shape. Separation predicts reliability, strongly.

On that evidence a gate at separation ≥ 0.05 gives **1.2% flips at 78% yield**,
and it looked implementable.

### 4.1 Two checks that did not move it

**Per-object depth flicker**, the quantity the original refusal cited:

| | median | p95 |
|---|---|---|
| `\|Δd\| / \|d\|` | **4.82%** | 21.14% |
| `\|Δd\| / (p95 − p5)` | 3.21% | 19.20% |

So the **6–8% figure was approximately right in magnitude** — it came from
EPIC-KITCHENS at 128×256, and this platform's own camera gives 4.8%. What did
not follow is the inference. Flicker of that size does **not** imply the ordering
inverts, because both objects' depths move together; the ordering only breaks
when the flicker exceeds the separation. That is precisely what the table above
shows, and it is why per-pixel variance was the wrong thing to measure.

**Lag sweep** — is the ordering merely the previous frame remembered?

| lag | ~elapsed | n | flip (all) | n (sep ≥ 0.05) | flip (gated) |
|---|---|---|---|---|---|
| 1 | 83 ms | 2,700 | 3.81% | 2,096 | 1.19% |
| 2 | 167 ms | 2,742 | 4.19% | 2,177 | 1.47% |
| 4 | 334 ms | 2,432 | 4.19% | 1,967 | 1.68% |
| 8 | 667 ms | 2,018 | 3.47% | 1,651 | 1.51% |
| 12 | 1.0 s | 1,804 | 3.05% | 1,486 | 1.01% |
| 24 | 2.0 s | 1,429 | 3.36% | 1,200 | 1.58% |

Essentially flat from 83 ms to 2 seconds. Read optimistically this says the
ordering is stable over seconds. Read correctly, **it says the scene barely
changes over two seconds** — which is the first sign of the problem in §5.

---

## 5. The motion check, which is what actually decides this

A 3.8% flip rate proves stable ordering **only if the scene was moving.** On a
static corpus the ordering would look stable no matter how bad the depth model
was, and the measurement would be reporting that nothing moved.

How much does this corpus move? Box-centre displacement between consecutive
frames, against a 734.8 px frame diagonal:

| p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|
| 4.2 px | 9.0 px | 18.4 px | 26.7 px | 56.4 px |

**The corpus barely moves.** The 99th percentile of inter-frame motion is 7.7% of
the frame diagonal. These are desk, bed and kitchen-counter scenes.

### 5.1 Flip rate by motion × separation

Flip% with (n) in every cell. Rows are inter-frame box motion; columns are depth
separation.

| motion ↓ / sep → | 0.00–0.02 | 0.02–0.05 | 0.05–0.10 | 0.10–0.20 | 0.20–0.40 | ≥0.40 |
|---|---|---|---|---|---|---|
| 0.0–2.0 px | 5.1% (99) | 3.4% (87) | **0.0% (94)** | **0.0% (124)** | 0.0% (226) | 0.0% (63) |
| 2.0–4.2 px | 9.9% (71) | 2.0% (51) | 1.3% (77) | **0.0% (121)** | 0.0% (262) | 0.0% (84) |
| 4.2–9.0 px | 27.6% (76) | 11.3% (53) | 8.3% (72) | 2.4% (125) | 0.4% (261) | 0.0% (79) |
| 9.0–18.4 px | 16.1% (62) | 9.8% (41) | 7.4% (27) | 2.6% (77) | 0.0% (137) | 0.0% (61) |
| **18.4+ px** | 31.4% (35) | 34.5% (29) | **8.7% (23)** | **11.5% (52)** | 2.3% (87) | 0.0% (44) |

Row totals, at the gate that was proposed:

| motion | all separations | n | **sep ≥ 0.05** | n | sep ≥ 0.20 | n |
|---|---|---|---|---|---|---|
| 0.0–2.0 px | 1.15% | 693 | **0.00%** | 507 | 0.00% | 289 |
| 2.0–4.2 px | 1.35% | 666 | 0.18% | 544 | 0.00% | 346 |
| 4.2–9.0 px | 5.56% | 666 | 1.86% | 537 | 0.29% | 340 |
| 9.0–18.4 px | 4.44% | 405 | 1.32% | 302 | 0.00% | 198 |
| **18.4+ px** | **11.48%** | 270 | **4.85%** | 206 | 1.53% | 131 |

### 5.2 What this says

**The flip rate climbs sharply with motion, and it climbs at matched
separation** — so this is not separation and motion being confounded, it is
motion having an effect of its own:

- At separation **0.10–0.20**, the band a 0.05 gate is specifically meant to
  admit: **0.0% (n=124) in the most static rows → 11.5% (n=52)** in the top
  motion decile.
- At separation **0.05–0.10**: **0.0% (n=94) → 8.7% (n=23)**.
- Gated at ≥0.05 overall: **0.00% (n=507) → 4.85% (n=206)**, a climb from
  nothing to roughly the level that got other routes rejected.

**The proposed gate fails exactly where it matters.** An 8–11% flip rate inside
the admitted band is not a relation that can be asserted; it is the 15–25%
territory the parallax route was rejected for, arrived at from a different
direction.

**And the rescue does not work either.** Raising the gate to ≥0.40 gives 0 flips
in 44 high-motion observations — but rule of three puts the true rate as high as
**6.8%**, and that band is only 12.3% of pairs corpus-wide. Too sparse to claim
safety, too narrow to be useful. Every zero cell in the table above carries the
same caveat; the tightest is 1.1% (n=262) and the loosest 6.8% (n=44).

**The regime the product needs is not in this corpus at all.** The top motion
bin here starts at 18.4 px between frames — 2.5% of the diagonal. A wearer
walking through a room produces motion far beyond anything sampled. The measured
trend across the bins that *do* exist points the wrong way, and there is no basis
for extrapolating it back to safety.

### 5.3 A confound, stated

Box-centre motion conflates **wearer/scene motion** with **detector box jitter** —
a box that wobbles on a stationary object moves the sampling window onto
different pixels, which degrades the depth sample independently of anything
moving in the room. This measurement cannot separate the two.

It does not change the verdict. Both are real, both happen in production, and
both break the ordering. If anything it makes the result worse: detector jitter
is present even when the wearer is still.

---

## 6. Verdict

**`in_front_of` and `behind` cannot be emitted honestly.** No behaviour was
changed.

The refusal now rests on a measurement of the right quantity, on this platform's
own frames:

- the **ordering** flip rate, not per-pixel depth variance;
- **3.8% overall**, strongly ordered by separation, which alone would have
  supported shipping;
- **but 4.85% at the proposed gate and 11.5% inside its admitted band once the
  scene moves at all**, on a corpus whose 99th-percentile motion is 56 px;
- with **no ground truth**, so even the good numbers are self-consistency and not
  accuracy.

What would settle it, stated as narrowly as the evidence allows: **corpus footage
containing sustained wearer locomotion**, and the same motion × separation table
computed on it. If the gated flip rate stays under ~1% in motion bins an order of
magnitude above 18 px, the relation becomes available behind a separation gate
and a per-relation confidence derived from that table. Absent that footage, this
is unproven in the direction that matters, and unproven means refused.

A note for whoever runs that: cost is **not** an open question. Depth is 5.73 ms
on CUDA and 18.29 ms on CPU and fits either way.

---

## 7. Reproducing

Nothing here was persisted to the corpus and no production code path was
exercised. The measurement ran in four passes — detector over all 9,199 frames,
MiDaS over the 2,688 that participate in a usable transition, the ordering
analysis, and the motion binning — using `scripts/capture_corpus_benchmark.py`'s
`iter_capture_frames` for corpus iteration, the shipped detector's own weights
and threshold, and `TrackerPolicy.min_iou` for association. Scripts were scratch
and are not committed; every constant needed to rebuild them is named above.
