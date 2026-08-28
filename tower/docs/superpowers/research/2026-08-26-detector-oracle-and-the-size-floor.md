# The shipped detector is blind below 2% of the frame

**Date:** 2026-08-26
**Method:** `fasterrcnn_resnet50_fpn_v2` run over the real corpus as an
**oracle** — a better-informed second opinion, not ground truth — and
compared against the shipped `ssdlite320_mobilenet_v3_large`.
**Corpus at time of measurement:** 14,128 frames / 28 captures. The
original 9,199 (17 captures) is an exact subset; both are reported below.
The corpus has since grown again to **31 captures / 14,599 frames** — the
physical-validation lane is producing real data continuously.

---

## 0. The caveat that governs every number here

Both models are **COCO-trained torchvision** detectors. Their mistakes
share a cause, so:

- **Every agreement figure below is an upper bound on correctness**, not an
  estimate of it.
- **Any object class both models fail to see is invisible to this
  measurement entirely.** This method cannot discover that kind of blindness.

This is a second opinion. It is the best available on this host, because
nobody has labelled the corpus, and it is not ground truth.

## 1. Cost — a prior figure corrected in both directions

Decode excluded, `torch.cuda.synchronize()` bracketed, first five calls
dropped as warmup:

| detector | CUDA warm median | CPU |
|---|---|---|
| `fasterrcnn_resnet50_fpn_v2` | **46.8 ms** (n=1,260, p95 49.3) | **1,352.1 ms** (n=107) |
| `ssdlite320_mobilenet_v3_large` | 42.2 ms | 44.1 ms |

First call 519.5 ms; VRAM peak 680 MB.

**A previously quoted 56.3 ms was not reproduced**, and the correction cuts
both ways — better on CUDA, catastrophic off it. Against the **83.5 ms**
delivered interval, the oracle is 0.56x on CUDA and **16.2x on CPU**.
**CPU is the default device.** So the oracle is a CUDA-only instrument.

The genuinely surprising number is the comparison: on CUDA the "heavy"
model costs only **11% more** than the "lightweight" one (46.8 vs 42.2 ms).
MobileNet's advantage is a CPU advantage, and it nearly vanishes on a GPU.

## 2. The finding: a systematic size floor

Recall against oracle boxes, bucketed by box area as a fraction of frame
(n = 7,964 oracle boxes):

| oracle box area | shipped recall |
|---|---|
| < 0.5% | **0.000** |
| 0.5–1% | **0.000** |
| 1–2% | 0.009 |
| 2–5% | 0.080 |
| 5–10% | 0.229 |
| 10–25% | 0.369 |
| > 25% | 0.523 |

**`ssdlite320_mobilenet_v3_large` is effectively blind below ~2% of the
frame**, and never exceeds ~52% recall even on objects filling a quarter of
it. The consequences are concrete:

| class | shipped frames | oracle frames |
|---|---|---|
| bottle | 7 | 1,091 |
| refrigerator | 106 | 1,939 |
| mouse | 80 | 1,091 |
| keyboard | 1,093 | 4,289 |

Per-class precision/recall (shipped @0.40 vs oracle @0.50, IoU ≥ 0.5,
n=14,128): person 0.784/**0.306** · laptop 0.857/0.730 · cell phone
0.926/**0.497** · tv 0.592/0.209 · couch 0.193/0.108 · chair 0.388/0.161.

**Disagreement is overwhelmingly missing, not inventing: 40,075 misses
against 5,660 inventions.** Precision is respectable; recall is poor. The
detector is conservative, which is the safer failure direction for a
privacy-sensitive product — but it means every count this platform
produces is an **undercount**, and the platform has not been saying so.

## 3. Constants judged — and mostly confirmed

**`SCORE_THRESHOLD = 0.4` stands, on evidence.** The F1 sweep over Scene
classes is a plateau, not a peak: 0.512 (T=0.20) → 0.497 (0.30) → 0.467
(0.40). Dropping to 0.30 buys +0.05 recall for **1.7x the false boxes per
frame** (0.35 → 0.60). There is no optimum to find.

For **Object Memory it is inert**: `RelevancePolicy.min_score = 0.5`
dominates it, and T ∈ {0.2, 0.3, 0.4, 0.5} all yield exactly **55**
observations.

**`TRACKED_CLASSES` — a correction to an earlier claim of mine.** I had
written that `cell phone`, the most reliable class, was "untracked",
implying Object Memory was losing it. **That was wrong.** The two constants
are separate:

- `TRACKED_CLASSES` (`experiments/object_detection.py:39`) only drives
  `count_*` metrics in the **CV Lab experiment**.
- `PERSISTED_CLASSES = ("laptop", "cell phone")`
  (`object_memory/relevance.py:37`) drives **Object Memory**, and it
  already includes `cell phone`.

Dropping `dining table` and adding `cell phone` to `TRACKED_CLASSES` is
still correct — `dining table` appears in 48 oracle frames of 9,199 and 1
shipped — but the **effect on Object Memory's 55 observations is exactly
zero**. A replay reproduced 55 (29 laptop / 26 cell phone) precisely; the
oracle in the same pipeline yields 64.

## 4. Wearer geometry — confirmed, and still not separable

The oracle calls the same pixels `person`: 81.3% of shipped person boxes
have an oracle match at IoU ≥ 0.5. Oracle @0.80 gives median y2/H
**0.985**, median cx **0.500**, 58.4% at y2/H ≥ 0.98 (n=5,359 over the
9,199) — independently reproducing the earlier 0.981 / 59%.

**But the distribution is unimodal with a continuous tail, not bimodal.**
A rule of (y2 ≥ 0.95 ∧ y1 ≥ 0.30) captures 65.7%, leaving a **34.3%
residual** whose high-confidence part (11.7%, median y1 0.28, area 39%) is
still bottom-heavy and consistent with the wearer at a different look-down
angle.

**There is no natural boundary, and no confirmed bystander in the corpus to
validate one against.** So this does not resolve the `person` ruling and
was not intended to; it establishes that a purely *geometric* wearer filter
cannot be cleanly derived from the data available here.

## 5. What this changes

**Do not swap the shipped detector.** On CUDA the oracle is only 11% dearer
and vastly better, but **CPU is the default device**, where it is 16.2x the
frame interval. A swap would make the default configuration unusable. The
size floor is therefore a **limitation to disclose, not a bug to fix**, until
a deployment can guarantee CUDA.

**Counts must say they are undercounts.** Person recall is 0.306 against a
correlated oracle — an upper bound. Any wire payload reporting a count of
people must carry that it is recall-limited, alongside the existing
"may include the wearer" and "not validated" qualifications. This is now a
requirement on the Scene Understanding wire design.

**Document Memory gains an explanation.** Keyboards appear in 1,093 shipped
frames against 4,289 oracle frames. That cartridge's detection stage was
already known to be the binding constraint; a detector blind below 2% of
frame area is part of why, and it compounds the ~2 px glyph problem rather
than competing with it.
