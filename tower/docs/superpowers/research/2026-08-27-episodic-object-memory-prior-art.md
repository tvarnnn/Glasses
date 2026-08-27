# Episodic object memory — what has already been tried, and how well it worked

**Date:** 2026-08-27
**Why this file exists:** several decisions in
`tower/tower/object_memory/` cite figures from outside this repository —
"a tracker gets 20–37 average overlap on egocentric video", "MemPal's
last-seen images were right 53% of the time", "best frozen embeddings get
26.4% Recall@1". Those citations were load-bearing and had no source in
the repo. This is the source.

**Provenance is labelled and it matters.** `[FETCHED]` means the paper or
repository was retrieved and read during the research pass. `[SEARCH]`
means it came from a search summary that was **not** confirmed against
the source — verify before relying on it. `[NOT RETRIEVED]` means it
could not be read at all and no number from it should be used.

---

## 0. The three findings that shaped the design

**1. Online episodic object memory, with real detection and tracking, is
not a solved problem — it is barely a working one.** Re-run as a
*streaming* task with non-oracle components, Ego4D visual-query success
collapses to **4.02%**, against **81.92%** with oracle detection and
tracking and 55.89% for the best offline method `[FETCHED
arxiv.org/pdf/2411.16934]`. The authors attribute it to "the limited
performance of current state-of-the-art object detection and tracking
algorithms". Every offline benchmark number is an upper bound this
cartridge will not see.

**2. A cue beats an answer.** MemPal — a neck-worn camera, 15 adults aged
62–96, in their own homes, 20 objects, a 40-minute delay, 3-minute search
windows `[FETCHED ar5iv.labs.arxiv.org/html/2502.01801]`:

| condition | retrieval accuracy | rooms searched | raw TLX |
|---|---|---|---|
| no aid | 0.81 | 1.93 | 56.1 |
| audio answer | 0.97 | 1.10 | 50.5 |
| last-seen image | 0.95 | 1.09 | 44.4 |

**The system's own correctness was far below the task outcome**: audio
answers described the location correctly **72%** of the time and the
visual condition's image showed the true last-seen location **53%** of
the time. People succeeded anyway, because a wrong-but-plausible hint
plus a human search closes the gap. Error breakdown: object detection
24%, room localization 22%, nothing detected 12%.

This is the single strongest argument in the corpus for
`tower/tower/object_memory/imagery.py` existing at all, and for treating
the picture as the product rather than the label.

**3. Objects do not move, and tracking them is the wrong problem.** Aria
Digital Twin: 398 instances over 200 sequences, **324 stationary and 74
dynamic** — 18.6% `[FETCHED arxiv.org/html/2306.06362]`. IT3DEgo adds a
Kalman filter to its best pipeline and gains **+0.5–0.7%** (P@0.5m
26.4 → 27.1) `[FETCHED arxiv.org/html/2312.04117]`; the paper's reading
is that memory heuristics already capture object stasis. *Caveat: that
evaluation is restricted to stationary periods by construction, so it is
partly a property of the protocol.*

---

## 1. Trackers on egocentric video

**EgoTracks** `[FETCHED ar5iv.labs.arxiv.org/html/2301.03213]`: 5,708
videos, 22,028 tracks, 602.9 hours, annotated at 5 fps.

| tracker | AO | F-score | Precision | Recall |
|---|---|---|---|---|
| GlobalTrack | 23.63 | 20.40 | 31.28 | 15.14 |
| MixFormer | 27.93 | 25.54 | 28.30 | 23.27 |
| ToMP | 30.93 | 20.95 | 19.63 | 22.46 |
| STARK | 35.99 | 30.48 | 34.70 | 27.17 |
| Siam-RCNN | 37.48 | 35.38 | 52.80 | 26.67 |
| EgoSTARK (tuned) | **44.25** | 38.20 | — | — |

Off-the-shelf SOTA sits at **20–37 AO**. Note that **recall is far below
precision** (Siam-RCNN 52.8 P against 26.7 R): trackers give up rather
than misfire, which is the **wrong failure direction** for a memory
system whose job is to log a sighting. Stated causes: re-detection after
disappearance, and motion/context/scale priors broken by head motion.

**IT3DEgo** `[FETCHED arxiv.org/html/2312.04117]` — 50 sequences, 220
instances, HoloLens2:

| method | setting | P@0.5m | R@0.5m | L2 (m) |
|---|---|---|---|---|
| VITKT_M (best tracker) | online enrollment | 24.2 | 25.9 | 1.55 |
| SAM+DINOv2+KF | online enrollment | 27.1 | 29.0 | 1.32 |
| SAM+DINOv2+KF | 25 pre-enrolled images | **59.4** | 53.1 | 0.65 |

Three findings that reach this cartridge directly: **foundation-model
re-detection beats every dedicated tracker by 2–5×** on egocentric
footage; **pre-enrollment more than doubles precision**; and RGB-D
trackers were no better than RGB, because the depth was sparse and
misaligned.

**Consequence for `sightings.py`:** associating by CLASS over time asks
much less than a tracker and cannot be wrong in the way a broken motion
model is. A real tracker is a later decision, and it should be evaluated
against re-detection rather than assumed better than it.

---

## 2. Instance identity — why it is not shipped

- Best frozen embeddings get **26.4% Recall@1** on small mass-produced
  objects.
- Tracking IDF1 collapses from **~100% to ~40%** from identical
  same-class distractors alone.
- Zero-shot egocentric object re-ID tops out at **45.3% mAP** for the
  best baseline, 52.8% for a purpose-built four-stage pipeline.
- Humans hit ~0.90 where networks hit ~0.40 on high-similarity instance
  pairs.
- Every candidate small VLM is at or below chance on "are these the same
  object" on the 561k-query Twin benchmark. **Do not ask a VLM that
  question.**

All five are `[SEARCH]` via
`2026-08-27-object-memory-vision-model-landscape.md` §7 and §4.7, which
carries the per-source citations. They are quoted here because
`docs/contracts/OBJECT-MEMORY.md` §1 now rests on them: the
`category-not-instance` position is a measured one rather than an
inherited prohibition, and a measured position needs its measurements
somewhere a reader can find them.

**If it is ever revisited**, the literature has already determined the
shape and it is not a cosine threshold: a weighted candidate set rather
than a hard assignment (Bowman et al.'s EM formulation over latent
associations, `[NOT RETRIEVED]` — the conceptual claim only); an explicit
"new object / none of the above" hypothesis, which *is* the "prefer
ambiguity" primitive and has a published formalism (Doherty et al.,
`[SEARCH]`); spatial and co-occurrence context as a first-class cue
rather than a tiebreaker; and collapse only on evidence accumulated
across observations.

---

## 3. Ego4D visual queries — the benchmark built for this question

**Metric warning, and it is not a footnote:** VQ2D's `Success` is
`stIoU > 0.05`. Almost any overlap counts. Never quote a success figure
from this benchmark without it. `[FETCHED
arxiv.org/html/2412.01826v1]`

Test-server leaderboard, tAP25 / stAP25 / recovery% / success%
`[FETCHED arxiv.org/html/2511.08007]`:

| method | tAP25 | stAP25 | Recovery | Success |
|---|---|---|---|---|
| Ego4D baseline | 0.20 | 0.13 | 32.20 | 39.80 |
| VQLoC | 0.32 | 0.24 | 45.10 | 55.88 |
| RELOCATE | 0.43 | 0.35 | 50.60 | 60.10 |
| EAGLE (SOTA) | **0.46** | **0.40** | 53.51 | 62.70 |

stAP25 went 0.13 → 0.40 in about five years, and **recovery is still
~53%**: barely half the frames in the best system's answer track are
actually on the object at IoU 0.5.

**The failure mode that matters most here** `[FETCHED RELOCATE v2]`: a
manual audit of 100 validation samples found 61 correct, **32 "earlier
occurrence found"** — right object, stale sighting — and 7 wrong object.
**Recency is harder than identity.** That is a direct argument for
`last_seen_at` and `frame_count` being on the record rather than only
`observed_at`.

VQ3D reaches 89% success `[FETCHED EAGLE, EgoLoc]`, and the improvement
from 8.7% is **almost entirely a camera-pose fix**, not an object-memory
advance: baseline frame registration is 14.74% and the winning method's
is 66.67% `[FETCHED arxiv.org/html/2306.16606]`. Mean L2 error at 89%
success is **1.84 m** — room granularity, not drawer granularity — and
the task requires the environment to have been pre-scanned. Per-scene
variance is enormous: 41.18% in "Bakery" against 96.43% in "Bike
mechanic" `[FETCHED ar5iv.labs.arxiv.org/html/2212.06969]`.

**Status signal** `[FETCHED ego4d-data.org/docs/challenge/]`: the 2026
challenge lists NLQ, Goal-Step, Short-Term Object Interaction
Anticipation, Ego-Pose Body and Keystep. **VQ2D, VQ3D, MQ and EgoTracks
are not listed.** Read that as the community moving on, not as solved.

---

## 4. 3D object mapping and open-vocabulary scene graphs — why none of it

Object Memory does not run SLAM, and this section is why it should not
start.

**OpenLex3D** `[FETCHED arxiv.org/html/2503.19764v2]` — an independent
re-benchmark of the whole family, with four label tiers. **Object
retrieval mAP: 1.45%–11.47% across every method tested**, with a "high
number of unmatched queries", and the verdict "no single method performs
well across both tasks". Its clutter tier (0.16–0.29) shows **object
merging and under-segmentation of small items on surfaces** — which is
exactly this cartridge's subject matter.

Cost, where anyone measured it:

| system | cost | licence | limitation that disqualifies it here |
|---|---|---|---|
| ConceptGraphs | **2.0–8.1 s/frame** (RTX 3090, measured independently by Clio) | MIT | "occasionally misses small or thin objects **and makes duplicate detections**" `[FETCHED ar5iv/2309.16650]` |
| HOV-SG | **11 h 12 m** for one Replica scene (measured independently by RAZER) | `[NOT RETRIEVED]` | "assumes a static environment and cannot handle dynamic scenes" `[FETCHED arxiv.org/html/2403.17846v2]` |
| OpenMask3D | 5–10 min/scene | `[NOT RETRIEVED]` | ScanNet200 AP 15.4; oracle masks give **+15.0 AP on tail categories** `[FETCHED ar5iv/2306.13631]` |
| Clio | 0.26–0.31 s/frame | BSD-2 | **over-clusters**: "if two primitives individually have similar cosine similarity to the same task but the task requires distinguishing them" `[FETCHED arxiv.org/html/2404.13696v3]` |

**Data association with duplicates is genuinely unsolved.** QuadricSLAM
states outright: *"we assume the problem of data association is solved"*,
and on real datasets supplied the associations by **manual annotation**
`[FETCHED ar5iv/1804.04011]`. Fusion++ admits it "lacks mechanisms for
consolidating multiple views of identical objects into single models"
and that spurious detections accumulate into "a growing clutter of
partial object reconstructions" `[FETCHED ar5iv/1808.08378]`. vMAP
over-fragments purely from detector label instability — its example is a
globe relabelled a balloon and becoming two objects `[FETCHED
ar5iv/2302.01838]`. BBQ, the one system built specifically to
disambiguate identical objects, scores **0.23** referred-object accuracy
`[FETCHED arxiv.org/html/2406.07113v2]`.

---

## 5. Small objects are the wall, and they are the whole product

Independent of everything above, and corroborated by this repository's
own corpus measurement:

- **Aria Digital Twin**: 2D baselines score AP-box **21.36** (FPN) and
  **11.42** (ViT-B) on egocentric frames — "significantly lower than
  their performance on the COCO dataset" — blamed on fast ego motion and
  sub-optimal viewpoint, with small objects substantially worse
  `[FETCHED arxiv.org/html/2306.06362]`.
- **EPIC-KITCHENS VISOR**: hands **95.4** mask AP against active objects
  **25.7** — a 70-point gap `[FETCHED ar5iv/2209.13064]`.
- **EFM3D**: 3D detection mAP collapses from 0.75 on synthetic to
  **0.22** on real, and the model "cannot detect objects positioned atop
  other objects" `[FETCHED arxiv.org/html/2406.10224v1]`.
- **Aria Everyday Objects** annotates 17 classes, all furniture and
  architecture — **no small portable objects at all**. It cannot validate
  a keys-or-wallet use case `[FETCHED]`.
- **FindingDory**: GPT-4o scores 27.3%, and "tasks targeting small
  objects exhibit little improvement" `[FETCHED
  arxiv.org/html/2506.15635]`.

This repository's own finding lands in the same place:
`2026-08-26-detector-oracle-and-the-size-floor.md` measured the shipped
detector at 0.000 recall below 1% of frame area, and
`2026-08-27-object-memory-corpus-precision.md` §4.5 found every verifier
false reject to be a crop of 5.3% of the frame or smaller.

---

## 6. The reframing worth putting in front of a human

Three independent sources converge, and none of them is about better
recognition:

- objects **overwhelmingly do not move** once placed (§0.3);
- they are typically stowed in **enclosed spaces** — visible when put
  away, invisible afterwards, which is MemPal's most-cited failure
  (§0.2);
- and the clinically discriminating criterion for the population this
  would help is **retrace ability**, not loss frequency `[SEARCH]`.

That points at a **stow-event log** rather than an object localizer: "at
14:32 you set something down, and here is the frame" is more useful, more
honest, and far more achievable on this hardware than "your keys are at
(x, y, z)". Critically it **needs no instance identity at all**, so it
sidesteps §2 entirely and stays inside the existing contract. It is close
to what `ObjectObservation` already is; what it lacks is the *event*
(placement) rather than the *presence*.

Not built here. It needs a hand-object-interaction signal this cartridge
does not have, and it is a product decision rather than an engineering
one.

---

## 7. What was NOT retrieved, and must not be cited

`[NOT RETRIEVED]` in the research pass, listed so nobody quotes a number
from them on the strength of this document:

- D3A / "Where were my keys?" (arXiv 2110.13061) — **no figure from this
  paper appears anywhere in this repository, and none should.**
- Bowman et al. 2017 ICRA — the conceptual claim about EM over latent
  data association is corroborated by secondary sources; **no numeric
  result was read.**
- DSP-SLAM, Node-SLAM — bare mentions only.
- OpenEQA per-category numbers.

`[SEARCH]`-only, so verify before relying on: OVIR-3D's numbers, Hydra's
timings, Ego4D NLQ leaderboard figures, the VQ3D 604/164/264 split sizes,
the VQ3D success-threshold formula, SenseCam/MyLifeBits results, and the
clinical retrace-ability criterion.
