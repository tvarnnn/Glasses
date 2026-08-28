# Retuning the tracker against the frame rate it actually runs at

**Date:** 2026-08-26
**Scope:** `tower/tower/scene/tracking.py`. One constant changed
(`max_misses`), two were swept and survived with derivations attached.
**Corpus:** `tower/data/captures/` — 9,145 frames from the 14 captures
with more than 50 frames, 360×640 portrait JPEG, decoded and run through
the shipped `TorchvisionDetector` (`ssdlite320_mobilenet_v3_large`,
`SCORE_THRESHOLD = 0.4`) on CUDA. 348 s of GPU time for the detection
pass; every sweep below re-runs the real `Tracker` over the cached
detections, so the tracker under test is the shipped one.
**Nothing was written to the corpus and nothing was persisted.**

---

## 0. Summary

- **The delivered interval reproduces exactly: 83.5 ms, 11.97 fps**,
  measured here from the receipt timestamps of all 9,145 frames.
  `TrackerPolicy` was tuned against an assumed ~3.3 fps — 3.6× wrong.
- **`max_misses = 5` → `12`.** It was justified as "roughly 1.5 seconds
  of absence" and bought **0.42 s**. It is now
  `frames_in(MAX_ABSENCE_S)` with `MAX_ABSENCE_S = 1.0`, so the duration
  is the constant and the frame count is derived.
- **`min_iou = 0.25` survives**, now derived: it is the largest floor
  that keeps ≥99.5% of measured same-object consecutive-frame
  associations for every label, and the last point before track
  fragmentation climbs.
- **`min_hits = 3` survives**, now derived from a two-sided sweep: 4
  regresses count stability under dropout (0.774 at 40% against 0.965),
  2 doubles the frames on which a track the detector was never confident
  about is counted.
- **Counting improves and does not regress at any dropout rate.** 40%:
  0.939 → **0.965**. 60% (a row that did not exist): 0.252 → **0.783**.
- **The cost is named:** a track whose object has genuinely gone stays
  confirmed for up to 1.0 s instead of 0.42 s.

### The caveat, stated first because it bounds everything below

**The corpus's `person` detections are almost certainly the wearer's own
torso** — the prior measurement note records a median box area of 40% of
the frame, a bottom edge at 0.981, and 59% of boxes touching a frame
edge, and **there is no bystander footage on this machine**. So what is
measured here is *real frame-to-frame dynamics at the real frame rate*,
which is exactly what these three constants encode. It is **not**
tracking accuracy on bystanders, which remains unmeasurable on this
host.

That is why `laptop` and `cell phone` are measured alongside `person`
throughout: they are genuine external objects at 0.828 and 0.842 median
score, they move relative to the camera through the wearer's own motion,
and `cell phone` in particular is a small box — the closest available
proxy for how a distant person's box behaves between frames. Where the
three disagree, the tightest of them is the one the constant respects.

---

## 1. The frame interval, re-measured on every frame

| | ms |
|---|---|
| corpus median inter-frame gap | **83.5** (11.97 fps) |
| p90 | 127.4 |
| p99 | 296.9 |
| per-capture medians | 68.5 – 87.6 (11.4 – 14.6 fps) |

Identical to the figure in
`2026-08-26-scene-understanding-measurements.md`, arrived at from all 14
captures rather than a sample. `DELIVERED_FRAME_INTERVAL_S = 0.0835`
stands.

What the assumed 3.3 fps did to each constant:

| constant | claimed | at 3.3 fps | at the real 12.0 fps |
|---|---|---|---|
| `max_misses = 5` | "roughly 1.5 seconds of absence" | 1.5 s | **0.42 s** |
| `min_hits = 3` | a confirmation streak | 0.9 s | 0.25 s |
| `min_iou = 0.25` | motion between frames | ~300 ms of motion | ~83 ms of motion |

Only one of those is a lie, and it is the one on the constant that
protects counting.

---

## 2. `min_iou` — what a box actually does in 83 ms

IoU between the same object's boxes in consecutive frames. Restricted to
frame pairs where **exactly one** box of that label exists in both
frames, so the correspondence is unambiguous, and to pairs whose receipt
gap is within 2× that capture's median.

| label | n | p0.5 | p1 | p5 | p10 | p25 | median | min |
|---|---|---|---|---|---|---|---|---|
| person | 2318 | 0.388 | **0.525** | 0.699 | 0.808 | 0.910 | 0.955 | 0.155 |
| laptop | 2481 | 0.546 | **0.613** | 0.767 | 0.836 | 0.914 | 0.960 | 0.150 |
| cell phone | 1678 | 0.293 | **0.386** | 0.616 | 0.693 | 0.810 | 0.906 | 0.000 |
| tv | 540 | 0.219 | 0.400 | 0.666 | 0.741 | 0.863 | 0.932 | 0.000 |
| chair | 57 | 0.562 | 0.652 | 0.684 | 0.809 | 0.856 | 0.907 | 0.562 |

**At 12 fps a box barely moves**: the median is 0.95. The floor is set by
the tail, not the median, and the tail belongs to the small object —
`cell phone` at p1 = 0.386.

Fraction of those same-object pairs an IoU floor would keep:

| label | 0.10 | 0.20 | 0.25 | 0.30 | 0.40 | 0.50 | 0.60 |
|---|---|---|---|---|---|---|---|
| person | 1.0000 | 0.9991 | **0.9987** | 0.9974 | 0.9940 | 0.9914 | 0.9780 |
| laptop | 1.0000 | 0.9996 | **0.9996** | 0.9996 | 0.9992 | 0.9972 | 0.9903 |
| cell phone | 0.9994 | 0.9976 | **0.9970** | 0.9946 | 0.9881 | 0.9791 | 0.9565 |
| tv | 0.9944 | 0.9944 | 0.9907 | 0.9907 | 0.9889 | 0.9796 | 0.9630 |

**0.25 is the largest floor keeping ≥99.5% for every label** (0.30 drops
`cell phone` to 0.9946). And the cost of going higher is visible in
fragmentation — distinct confirmed track ids created over the corpus,
which is the recount failure counted directly:

| `min_iou` | person | laptop | cell phone | total ids |
|---|---|---|---|---|
| 0.05 | 100 | 62 | 79 | 364 |
| 0.10 | 100 | 62 | 80 | 365 |
| 0.20 | 102 | 64 | 83 | 375 |
| **0.25** | **104** | **64** | **86** | **382** |
| 0.30 | 102 | 65 | 90 | 385 |
| 0.40 | 110 | 69 | 98 | 406 |
| 0.50 | 132 | 74 | 110 | 456 |
| 0.60 | 139 | 83 | 124 | 492 |

Flat to 0.30, climbing after: +6% ids at 0.40, +19% at 0.50. The four ids
that separate 0.25 from 0.10 are worth paying for the margin.

**Why it cannot be raised on this evidence.** The other side of the
trade — how often *different* objects overlap enough to be wrongly
associated — is not measurable here. Two boxes of one class in one frame
(definitionally different objects) never exceed **0.550** IoU:

| label | n | median | p90 | p99 | max |
|---|---|---|---|---|---|
| person | 1534 | 0.418 | 0.505 | 0.545 | 0.550 |
| laptop | 309 | 0.356 | 0.510 | 0.548 | 0.549 |
| cell phone | 161 | 0.450 | 0.535 | 0.546 | 0.549 |

That ceiling is the detector's own NMS threshold, not a fact about
rooms. The distribution describes NMS. With no crowd footage there is no
honest upper bound, so `min_iou` is set by the association it must not
lose and left there.

---

## 3. `max_misses` — how long real gaps last

Run-lengths of consecutive misses that were later **recovered**, from
the real `Tracker` with an effectively unbounded budget, counting only
tracks with at least 3 hits before the gap (`min_iou = 0.25`):

| label | n | median | p75 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| person | 566 | 4 | 16 | 61 | 113 | 395 | 613 |
| laptop | 269 | 3 | 21 | 101 | 269 | 1128 | 1778 |
| cell phone | 241 | 4 | 25 | 106 | 278 | 682 | 1158 |
| **all** | **1599** | **3** | **17** | **81** | **178** | **596** | **1778** |

Cumulative fraction of gaps a budget of *k* frames bridges:

| k | 1 | 2 | 3 | **5** | 8 | **12** | 18 | 24 | 36 |
|---|---|---|---|---|---|---|---|---|---|
| seconds | 0.08 | 0.17 | 0.25 | **0.42** | 0.67 | **1.00** | 1.50 | 2.00 | 3.01 |
| bridged | 0.305 | 0.442 | 0.514 | **0.583** | 0.650 | **0.707** | 0.761 | 0.786 | 0.826 |

**This distribution is heavy-tailed with no knee, so no percentile picks
the constant.** A p99 budget would be 596 frames — 50 seconds — which is
absurd; long "recoveries" are increasingly a *different* object arriving
in the same place, not the same one returning. The number has to come
from the trade, measured on both sides.

### Both sides, swept

`min_iou = 0.25` throughout. *phantom frames* = frames on which a
confirmed track the detector was **never** confident about (best score
below 0.5, where `SCORE_THRESHOLD = 0.4` is already "noise more often
than not") was counted. *missed frames* = frames on which a track the
detector **was** confident about (best score ≥ 0.8) was detected but not
yet counted. Ground truth is the detector score, which the tracker never
uses for confirmation, so neither metric is circular in the thresholds
being swept. *dropout* is `scene_benchmark.py`'s count-stability
fraction-correct at 0 / 10 / 20 / 40 / 60%.

| `min_hits` | `max_misses` | phantom frames | missed frames | person ids | dropout correct |
|---|---|---|---|---|---|
| 2 | 5 | 526 | 315 | 179 | 1.000 1.000 1.000 0.983 0.696 |
| 2 | 12 | 808 | 288 | 133 | 1.000 1.000 1.000 1.000 1.000 |
| **3** | **5** *(shipped)* | **230** | **623** | **134** | 1.000 1.000 1.000 **0.939 0.252** |
| 3 | 8 | 298 | 603 | 116 | 1.000 1.000 1.000 0.965 0.783 |
| **3** | **12** *(chosen)* | **386** | **584** | **104** | 1.000 1.000 1.000 **0.965 0.783** |
| 3 | 18 | 473 | 571 | 87 | 1.000 1.000 1.000 0.965 0.783 |
| 3 | 24 | 439 | 588 | 81 | 1.000 1.000 1.000 0.965 0.783 |
| 4 | 5 | 110 | 916 | 109 | 1.000 0.983 0.983 0.739 0.043 |
| 4 | 12 | 160 | 852 | 82 | 1.000 0.983 0.983 0.774 0.374 |
| 4 | 18 | 195 | 826 | 69 | 1.000 0.983 0.983 0.774 0.374 |

### Where the line went, and why there

**5 → 12 frames (0.42 s → 1.0 s).** It cuts `person` ids created over the
corpus by 22% (134 → 104), lifts count stability at 40% dropout from
0.939 to 0.965 and at 60% from 0.252 to 0.783.

**Not 18 or 24.** Count stability at 18 and 24 is *identical* to 12 —
0.965 and 0.783 — so past one second the extra staleness buys nothing any
measurement here can see. It still costs: phantom frames rise 386 → 473,
and a departed person is claimed present for 1.5 s instead of 1.0 s. The
remaining ids it would save come from bridging gaps in the tail, which
is where "recovered" stops meaning "the same object".

**The opposite failure is real and is bounded.** `is_confirmed` latches,
so a confirmed track counts for its whole life; a track whose object has
genuinely left is therefore counted for exactly `max_misses` frames after
its last detection. One second, once per departure. Departures are also
far rarer than gaps in this corpus — 1,599 recovered gaps against the
119 distinct `person`/`laptop`/`cell phone` objects an unbounded budget
resolves the whole corpus into, so bridging is the common case and
departing is the rare one. But it is a real claim about who is in the room
(`06-PRIVACY-DATA.md`: collect and assert the minimum the feature
requires), and one second is where it was capped, not waived.

**The interaction, stated rather than hidden.** A longer budget makes
each phantom linger longer too: at `min_hits = 3`, phantom frames go
230 → 386 (+68%) purely from the tail. `min_hits = 4` would more than pay
that back (160, below the shipped level) — and it is rejected anyway, in
§4, because it regresses the headline capability.

---

## 4. `min_hits` — a frame count, and it stays one

`min_hits` counts *evidence between frames*, and a detector's false
positives arrive per frame rather than per second, so unlike `max_misses`
it does not scale with the rate. The 3.6× error did not corrupt it. It
was still swept, because "the error missed it" is not a derivation.

How long tracks actually last, and how confident the detector was about
them (`min_iou = 0.30`, `max_misses = 12`, all labels):

| best streak reached | tracks | median best score |
|---|---|---|
| 1 | 295 | 0.466 |
| 2 | 114 | 0.579 |
| 3 | 64 | 0.625 |
| 4 | 39 | 0.657 |
| 5 | 31 | 0.745 |
| 6+ | 251 | 0.901 |

37% of tracks never survive two consecutive frames, and those are the
detector's noise floor — a median best score of 0.466 against a 0.4
threshold. The population is continuous, though: there is no streak at
which junk stops and objects start, which is why this needs the two-sided
table in §3 rather than a percentile.

From that table, at `max_misses = 12`:

- **4 is rejected.** It regresses count stability at *every* non-zero
  dropout rate — 0.983 at 10% where 3 holds 1.000, and 0.774 at 40%
  against 0.965 — because re-confirming needs four consecutive hits from
  a detector losing two frames in five. It would have bought 226 fewer
  phantom frames for 268 more missed ones, roughly par, and par is not
  worth a regression in the one property the brief singles out.
- **2 is rejected.** Phantom frames double, 386 → 808, undoing the
  documented confirmation fix that introduced this constant.
- **3 stays**, at 0.25 s to first report — where the same number bought
  0.9 s at the rate it was wrongly assumed to run at, so the correction
  makes this constant *better*, not worse.

`ORIENTATION_FRAME_STRIDE` is coupled to `TrackerPolicy.min_hits`, so
leaving `min_hits` at 3 leaves the orientation cadence at 3 frames /
~250 ms unchanged. That coupling was previously a literal `3` held equal
by a test; it is now `ORIENTATION_FRAME_STRIDE = TrackerPolicy.min_hits`,
so a future retune carries the cadence with it instead of failing a test.
The same duplication was removed from `scripts/scene_session.py`, whose
`--max-misses` flag defaulted to a hard-coded `5` and would have gone on
shipping the old constant from the driver.

---

## 5. Counting: before and after

`scripts/scene_benchmark.py`, correct answer 2 throughout. The bench
previously constructed `TrackerPolicy(min_hits=3, max_misses=5)` by hand
and stepped time at 0.3 s — so it reported the old constants regardless
of what shipped, which is a benchmark that cannot see a regression. It
now builds the tracker with **no policy argument** and steps at the real
83.5 ms.

| dropout | before (0.25/3/5) | after (0.25/3/12) |
|---|---|---|
| 0% | 1.000 | 1.000 |
| 10% | 1.000 | 1.000 |
| 20% | 1.000 | 1.000 |
| 40% | 0.939 `[1, 2]` | **0.965** `[1, 2]` |
| 60% | 0.252 `[0, 1, 2]` | **0.783** `[0, 1, 2]` |

Nothing regressed. The detection and orientation sections of the bench
are untouched by tracker constants and are unchanged.

---

## 6. What this does not show

- **Nothing about bystanders.** See the caveat in §0. A walking person
  crossing the view at 3 m subtends a narrower box than the wearer's
  torso and moves faster across it; `cell phone` is the nearest proxy in
  this corpus and it is what set `min_iou`. Confirming these constants on
  people other than the wearer needs footage this host does not have.
- **No upper bound on `min_iou`**, for the NMS reason in §2.
- **The dropout model is harsher than reality.** The bench drops each
  detection independently, so its gaps are geometric; real gaps (§3) are
  heavy-tailed and bursty. The bench is a comparison between constants,
  not a prediction of field accuracy.
- **The phantom/missed metric is a proxy.** Detector score is not ground
  truth; it is merely independent of the thresholds under test, which is
  what the sweep needed.
