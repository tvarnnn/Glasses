# The first measurement of the real corpus

**Date:** 2026-08-26
**Corpus:** `data/captures/` — 17 captures, **9,199 real Ray-Ban frames**, 360×640 portrait
**Harness:** `scripts/capture_corpus_benchmark.py` (new)
**Hardware:** RTX 5070, `torch 2.13.0+cu132`, sm_120 verified executing

Until today, **no detector or OCR had ever been run against these frames.**
Every CV figure in this repository was measured on synthetic renders or a
handful of hand-made images. This is the first evidence about what the glasses
actually see.

Three findings below change cartridge premises. One of them reframes an
unresolved privacy ruling.

---

## 1. Throughput — the detector keeps up

```
experiment   object_detection  (device=cuda)
captures     17
frames       9199        failed 0
median       38.6 ms   (25.9 fps)
p95          44.2 ms
```

**25.9 fps against a stream that delivers 12.** The detector is not the
bottleneck, and zero frames failed to decode across the whole corpus. VRAM
13.3 MiB.

Prior docs recorded 35.30 ms for this experiment on CPU at 640×360. The GPU
figure is not dramatically better, which is expected: SSDLite320 is a small
mobile model that resizes to 320 internally, so transfer overhead dominates and
resolution barely matters.

---

## 2. Aggregate counts, and why they mislead on their own

```
summed:                          averaged:
  detections        15592          mean_score        0.5477
  raw_detections  2759700          max_score         0.6740
  count_person       5148          score_threshold   0.4000
  count_laptop       3566
  count_tv            732
  count_couch         365
  count_chair          87
  count_dining_table    1
```

`count_person 5148` across 9,199 frames looks like a room full of people. It is
not. See §3.

`count_dining_table: 1` in the entire corpus, and `count_chair: 87`, are the
first hint that **the repo is counting the wrong classes** — see §4.

---

## 3. The "people" are almost certainly the wearer

Sampled every 20th frame across all captures (340 frames), geometry only — no
identity work of any kind:

| | person boxes (n=223) |
|---|---|
| median score | 0.610 |
| median area | **39.99%** of frame |
| max area | 91.99% |
| median top edge `y1/H` | 0.463 |
| **median bottom edge `y2/H`** | **0.981** |
| median horizontal centre | 0.498 |
| **touching the bottom edge** | **132/223 = 59%** |
| taller than half the frame | 90/223 = 40% |

A box that begins mid-frame, extends to the very bottom edge, sits horizontally
centred, and fills ~40% of a head-mounted first-person frame is **the wearer's
own torso, lap and arms when looking down.** A bystander standing in the room
would not be so consistently bottom-anchored *and* centred.

**Stated honestly:** this is strong geometric inference, not proof. Confirming
it requires looking at the frames, which was not done here. But the burden has
shifted — anyone treating `count_person` as a bystander count now needs to
argue for it.

### Why this matters

**The `person` ruling is reframed, not resolved.** Object Memory's Task 6 as
written would persist a record per detected `person`. On this corpus that would
mostly persist **the wearer's own body**, thousands of times — which is
simultaneously less privacy-sensitive than feared (not bystanders) and more
useless than hoped (not a memory of anything).

The privacy question does not go away: real bystanders will appear, and the
platform's redaction posture still applies. But the *design* question changes.
A cartridge that wants "who was here" must first distinguish the wearer from
everyone else, and nothing in the repo does that today.

**Also:** the corpus is not a good test set for bystander perception. Scene
Understanding's counting logic has never been validated against real people
because **there is still no footage of bystanders on this host** — only of the
wearer. The prior finding that "there is no imagery of people anywhere on this
host" was wrong in letter and right in spirit.

---

## 4. The repo tracks the wrong classes

`tower/tower/experiments/object_detection.py:34`:

```python
TRACKED_CLASSES = ("person", "chair", "couch", "dining table", "tv", "laptop")
```

Measured reliability across the sample, ordered by how much you can trust them:

| class | n | median score | median area | verdict |
|---|---|---|---|---|
| **cell phone** | 105 | **0.844** | 8.6% | most reliable class in the corpus — **and untracked** |
| **laptop** | 143 | **0.813** | 20.1% | reliable, tracked |
| person | 223 | 0.610 | 40.0% | see §3 |
| chair | 4 | 0.593 | 15.6% | tracked; 4 detections in 340 frames |
| bed | 63 | 0.521 | 47.9% | untracked, marginal, large-area |
| couch | 13 | 0.496 | 48.1% | tracked; **below the 0.4 threshold's usefulness** |
| tv | 12 | 0.494 | 14.8% | tracked, marginal |
| refrigerator | 3 | 0.466 | 71.0% | untracked, marginal |

**Four of the six tracked classes are near-threshold or nearly absent**
(`chair`, `couch`, `tv`, `dining table`), while the single highest-confidence
class in the corpus — `cell phone` at 0.844 — is not tracked at all.

`bed`, `couch` and `refrigerator` all show ~48-71% median area with sub-0.53
scores, which is the signature of a large soft/flat surface being guessed at
rather than recognised.

### Consequence for Object Memory

The canonical demo question was already known to be unanswerable — COCO has no
`keys` class. This adds the positive half of that finding: **the objects this
corpus can actually support memory for are `laptop` and `cell phone`**, both at
>0.8 confidence. That is a narrower but genuinely honest first slice, and it is
evidence-led rather than aspirational.

`TRACKED_CLASSES` should be revisited before Object Memory's producer is built.
Doing so is cheap; discovering it after building a memory over `dining table` is
not.

---

## 5. What was NOT measured

- **OCR / Document Memory.** `easyocr` is not installed (Stage C). The
  resolution finding — word recall 0.43–0.81 at 640×360 versus 0.96–1.00 at
  1280×720 — is still unverified against real frames, **and the benchmark that
  produced it used landscape sizes against a portrait stream.**
- **Depth / MiDaS.** Needs `timm` (Stage B).
- **Orientation / KeypointRCNN.** Available now (torchvision carries it, no
  extra package) but not run.
- **Whether any detection is actually correct.** Scores and geometry are
  proxies. Nobody has looked at a frame.

---

## 6. Reproducing this

```bash
cd tower
python scripts/capture_corpus_benchmark.py object_detection --device cuda
python scripts/capture_corpus_benchmark.py baseline --per-capture-limit 100 --format json
```

The harness reads and persists nothing — the Experimental CV Lab declares
`persists_data=False` and a boundary test enforces it, so a benchmark that
wrote results would break the cartridge's own guarantee. Counts are summed and
rates are averaged separately, because summing a mean score across 9,199 frames
produces a plausible-looking number that means nothing.
