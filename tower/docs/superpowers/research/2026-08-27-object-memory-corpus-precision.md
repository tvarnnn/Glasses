# Object Memory — what the detector actually sees, and what it gets wrong

**Date:** 2026-08-27
**Corpus:** `tower/data/captures/` — 34 captures, **18,821 frames**, all
360×640 portrait, 0 undecodable. Real Ray-Ban Meta footage relayed through
an iPhone.
**Harnesses:** `tower/scripts/research/object_memory_corpus_dump.py`,
`sighting_contact_sheet.py`, `open_vocab_verifier_bench.py`,
`detector_long_session.py`, `face_filter_false_positives.py`. Every figure
below is reproducible from those five commands.

---

## 0. The one-paragraph version

Every figure this cartridge had ever been designed against described the
**detector's opinion of itself**. `data/captures/` carries no annotation
and nothing in this repository had ever looked at a crop. So the crops
were looked at, and the result reorders the whole design: a ceiling fan
is `airplane` at 0.99 and `scissors` at 0.93, a white door is
`refrigerator` at 0.95, a phone in a hand is `chair` at 0.94, and the
three highest-scoring `remote` sightings in 18,821 frames are all laptop
keyboards. **Score does not order correctness across classes**, so
widening a class whitelist over this detector alone would fill a wearer's
memory with ceiling fans. That is what makes a second opinion structural
rather than decorative.

---

## 1. What the shipped detector reports

`ssdlite320_mobilenet_v3_large`, COCO weights, every class, threshold
0.15, CUDA, over all 18,821 frames.

| threshold | detections |
|---|---|
| ≥ 0.15 | 78,546 |
| ≥ 0.40 (the platform threshold) | 30,727 |
| ≥ 0.50 (this cartridge's `min_score`) | 24,028 |
| ≥ 0.70 | 14,613 |

Sixty-six classes fire at least once. Nine account for 95% of everything
above 0.5.

### 1.1 The classes that carry the corpus

At ≥ 0.5, by detection count:

| class | ≥0.5 | ≥0.7 | median score | median area | captures |
|---|---|---|---|---|---|
| laptop | 8,218 | 6,811 | 0.664 | 21.5% | 32 |
| person | 6,899 | 2,940 | 0.300 | 35.4% | 32 |
| cell phone | 3,613 | 2,814 | 0.604 | 8.5% | 27 |
| bed | 1,314 | 295 | 0.307 | 49.7% | 21 |
| keyboard | 1,086 | 695 | 0.295 | 10.5% | 19 |
| tv | 1,085 | 437 | 0.276 | 16.0% | 23 |
| couch | 396 | 76 | 0.252 | 43.7% | 15 |
| sink | 310 | 166 | 0.243 | 17.0% | 8 |
| chair | 171 | 63 | 0.197 | 9.0% | 15 |

`person` has a median box area of **35.4% of the frame**. On head-mounted
footage that is the wearer's own torso and arms seen while looking down,
which is the same finding the 2026-08-26 pass made on the smaller corpus
and it survives at double the sample.

---

## 2. Sightings: what replaced the 30-second window

A **sighting** is a temporally contiguous run of detections of one class
within one capture, broken by a gap of more than 3 seconds. Grouped that
way, at score ≥ 0.5:

| | count |
|---|---|
| sightings | **763** |
| … of at least 3 frames | **499** |
| … excluding `person` | **404** |
| one- and two-frame flickers | **264** (35%) |

Of the 499, the tiers now split them: **158 `remembered`**, **53
`verify`**, **158 `context`**, the rest ignored or `person`.

Two consequences.

**The 3-frame floor is not taste.** A third of all sightings are one or
two frames — a class that fired once and never again. Writing them would
make a third of the memory noise. Three frames costs a quarter of a
second at the measured ~12 fps delivered rate.

**404 memories over 26 minutes of walking is a scrollable list.** The
30-second resample window could not produce a number with any relationship
to what the camera did: an object glanced at twice in a second gave one
record and an object watched for four minutes gave eight.

---

## 3. Reading the crops — the measurement that changed the design

Method: group into sightings, take the strongest frame of each, crop with
35% padding, lay them out strongest-first on a contact sheet, read them.
One human pass, recorded here in full including the classes that were not
inspected.

| class | sightings | inspected | correct | what the wrong ones actually were |
|---|---|---|---|---|
| laptop | 78 | 24 | **24** | — |
| cell phone | 80 | 24 | **24** | — twenty of the twenty-four scored exactly 1.00 |
| bed | 66 | 24 | 20 | bedding at very close range |
| chair | 11 | 6 | 5 | a phone held in a hand, at **0.94** |
| mouse | 4 | 4 | 3 | an AirPods case, at 0.79 |
| cup | 3 | 3 | 3 | — |
| bottle | 2 | 2 | 2 | — |
| **remote** | 8 | 8 | **3** | the three **highest-scoring** are laptop keyboards (0.87, 0.77, 0.71); one more is a phone |
| suitcase | 5 | 5 | **0** | a backpack being carried — right object, wrong name |
| refrigerator | 7 | 6 | **0** | a white interior door with light switches, at **0.95** |
| scissors | 4 | 4 | **0** | a ceiling fan, at **0.93** |
| airplane | 7 | 7 | **0** | the same ceiling fan, at **0.99** |
| tie | 2 | 2 | **0** | a door frame and window blinds, at 0.84 |
| microwave | 2 | 2 | **0** | a monitor showing a bright logo |
| book | 1 | 1 | **0** | a laptop screen |
| backpack | 1 | 1 | **0** | a closet of hanging clothes |
| toothbrush | 1 | 1 | **0** | a boxed tube of toothpaste |
| tv, couch, sink, toilet, cat, dog, keyboard | — | **0** | — | not inspected; recorded as unknown, never as 0 |

### 3.1 The two findings that follow

**Score does not order correctness across classes.** The single clearest
case is `remote`: the three strongest sightings in the entire corpus are
wrong and the three that appear to be a real remote all score below 0.68.
A threshold cannot fix that, because the ordering is inverted.

**The objects people lose are the ones COCO cannot name.** Keys, a wallet
and a pair of glasses have no COCO class at any threshold. The ones that
do exist — `remote`, `backpack`, `handbag`, `book`, `bottle` — produced
8, 1, 0, 1 and 2 sightings across the whole corpus.

### 3.2 What this corpus cannot say

34 captures from **one home**, overwhelmingly one activity: a person
using a laptop in a bedroom. `laptop` at 24 of 24 is a strong statement
about this laptop in this room and a weak one about laptops. No kitchen
drawer, no car, no office, no bystander and no set of keys was ever
recorded. **Every figure here is a lower bound on how wrong a class can
be, never an upper bound.**

---

## 4. Choosing a verifier

### 4.1 The question, narrowed

Not "detect everything". The funnel has already produced a crop and a
proposed label; all that remains is whether the label survives. So each
model is given the crop and a fixed 31-word vocabulary — every
persistable class plus the confusers this detector actually produces —
and is judged on whether the proposed name comes **first**.

Asking the narrowest question that answers the need is what makes one
model call per 355 frames enough.

### 4.2 The evaluation set

94 crops with human labels, drawn from §3: every class where all
inspected tiles agreed, plus `remote` and `mouse` labelled tile by tile
because they are the two that matter and the two that are mixed. 59
positives, 35 negatives. The labels are hard-coded in
`open_vocab_verifier_bench.py`'s `GOLDEN` dict so they can be argued with.

### 4.3 The result

| model | accepts correct | rejects wrong | balanced | median ms | peak VRAM | license |
|---|---|---|---|---|---|---|
| **owlv2-base-patch16-ensemble** | **0.949** | 0.857 | **0.903** | **128** | 842 MB | Apache-2.0 |
| llmdet-tiny | 0.407 | 1.000 | 0.703 | 3,508 | 1,648 MB | Apache-2.0 |

LLMDet is the stronger model on LVIS rare-class AP and is what a survey
of the literature picks. It loses here for an architectural reason, not a
quality one:

* **OWLv2 embeds each prompt separately** and scores it against the
  image's object queries. Thirty-one names produce thirty-one scores, and
  "did the proposed label rank first" has an answer.
* **LLMDet is phrase grounding.** The vocabulary is joined into one
  sentence, and what comes back is text *spans* — `a set`, `a pair`, `a` —
  that must be mapped back onto class names by string matching. It scored
  0 of 24 on `cell phone`, 0 of 3 on `cup` and 0 of 2 on `bottle` under
  that mapping.
* It also pays for the sentence. **3.5 seconds a crop against 128
  milliseconds**, twenty-seven times slower, because cross-attention
  scales with text length.

A model that answers a different question well is not the better model
for this question.

### 4.4 The threshold

Swept over the same 94 crops, accepting only when the proposed label
ranks first **and** scores at least the threshold:

| min score | accepts | rejects | balanced | false accepts | false rejects |
|---|---|---|---|---|---|
| 0.00 | 0.949 | 0.857 | 0.903 | 5 | 3 |
| 0.40 | 0.932 | 0.886 | 0.909 | 4 | 4 |
| **0.45** | **0.932** | **0.943** | **0.938** | **2** | **4** |
| 0.50 | 0.915 | 0.943 | 0.929 | 2 | 5 |
| 0.55 | 0.814 | 0.943 | 0.878 | 2 | 11 |
| 0.60 | 0.576 | 0.943 | 0.760 | 2 | 25 |

0.40–0.50 is a plateau and **0.45** is its peak. Above 0.55 acceptance
collapses, because the small crops score low even when they are right.

**This threshold is fitted to 94 crops from one home.** It should be
re-measured against any corpus with a different camera, a different room,
or a bystander in it.

### 4.5 What the verifier does not fix

Every false reject at 0.50 is a crop of **5.3% of the frame or smaller**:

| proposed | truth | area | what OWLv2 said |
|---|---|---|---|
| remote | correct | 3.7% | computer mouse 0.34 |
| remote | correct | 3.8% | cell phone 0.35 |
| remote | correct | 3.9% | computer mouse 0.49 |
| cup | correct | 4.3% | drinking cup 0.46 *(below threshold)* |
| cup | correct | 5.3% | drinking cup 0.31 *(below threshold)* |

And both false accepts are small or ambiguous: a door frame read as a
necktie at 0.64, and the AirPods case read as a computer mouse at 0.86 in
a 2.2% crop.

**The size floor is not removed by a second opinion. It moves one stage
later.** On 360×640 source imagery that is a property of the pixels, and
the fix — if there is one — is upstream: a higher capture resolution, or
tiled detection on the async path. Neither is this wave's.

---

## 5. Cost, measured on this host

RTX 5070 (Blackwell, sm_120), 12 GB, driver 596.21; torch 2.13.0+cu132;
Windows 11; 20 logical cores.

### 5.1 The detector

Replaying the physically validated capture (2,203 frames), one run at a
time:

| device | seconds | ms/frame | detections |
|---|---|---|---|
| **CPU** | 152.6 | **69.262** | 4,287 |
| CUDA | 221.3 | 100.436 | 4,285 |

**CPU is ~30% faster than CUDA for this detector on this host**, because
the cost is per-frame preprocessing and transfer rather than the 320×320
forward pass. The CPU figure also reproduces the physically validated
run's 68.176 ms/frame and its detection count **exactly**; CUDA differs
by two detections at the threshold, which is ordinary numeric drift.

That is why `observation_device` defaults to `cpu`.

Reading and decoding the corpus costs **1.06 ms/frame** with 46 MB of
RSS, so essentially none of the above is I/O.

### 5.2 Long-session behaviour — a retraction

A first pass reported a monotonic climb in per-frame cost (49.5 →
87.8 ms over 18,821 frames) and it was **wrong**. That figure was a
*cumulative mean* read off a run that was competing with a test suite and
a contact-sheet render. Measured directly, in windows, one job at a time:

| device | window medians (500 frames each) | drift ratio | peak RSS |
|---|---|---|---|
| CUDA | 120, 114, 100, 85, 96, 101, 124, 123, 99, 112, 101, 117 | **0.968** | 1,442 MB |
| CPU | 154, 142, 165, 98, 97, 94, 115, 134, 99, 115, 93, 125 | **0.808** | **704 MB** |

No trend, no leak: CUDA allocator reserved plateaus at 436 MB and RSS is
flat. `torch.cuda.empty_cache()` every 200 frames made no reliable
difference — the run with it measured lower, but by less than the spread
between windows.

**The producer's steady-state cost is ~700 MB RSS on CPU.**

### 5.3 The verifier

| | |
|---|---|
| CUDA | **128 ms** median / 141 ms p95 per crop, 620 MB resident, 842 MB peak |
| CPU | **2,473 ms** median per crop, +796 MB RSS |
| load | 5.7 s cold, ~600 MB of weights downloaded once |

CPU is 19× slower. Since the detector is faster on CPU and the verifier
is faster on CUDA, the two stages default to **different devices**, which
is also what keeps a 2.5-second burst off the cores the detector is
using.

### 5.4 End to end, on the validated capture

| | observations | seconds | ms/frame | verifier calls | model time |
|---|---|---|---|---|---|
| verifier `none` | 8 | 152.6 | 69.262 | — | — |
| verifier `owlv2` | 13 | 153.1 | 69.487 | 7 | 1.50 s |
| `owlv2` + part-of rule | **12** | — | — | **5** | 1.05 s |

**+0.225 ms/frame — 0.3% — for five more memories.** Seven calls across
2,203 frames is one per 315. Queue peak depth **0**; backlog drops **0**.

The part-of rule (a `keyboard` sighting is suppressed while a `laptop`
sighting is open) removed one duplicate record, suppressed 36 detections,
and saved two model calls: the funnel narrowing itself.

---

## 6. A defect in the face filter, found by using it

`tower/object_memory/imagery.py` serves frames through YuNet at the same
settings `tower/world_builder/redaction.py` uses. On **frame 2708 of the
validated capture** — a desk with a monitor, a lit keyboard and a red
gaming mouse, and no person anywhere in it — the filter fired twice, and
one fill landed squarely on the mouse the record was about. The record is
correct, the verifier agreed with it, and the crop served for it is a
black rectangle.

Measured across 1,845 evenly-spaced corpus frames:

| | |
|---|---|
| frames with at least one firing | **741 of 1,845 — 40.2%** |
| regions filled | 976 |
| median region area | **12.5% of the frame** |
| largest region | 84.2% of the frame |
| cost | 27.5 ms/frame |

Of 36 firings inspected by eye: **4 were a real face** — the wearer
reflected in a mirror — and **32 were not**: hands on a keyboard (the
large majority), a laptop or phone screen, a white door, a sink, a
cartoon on a monitor.

World Builder's own measurement — "0 false positives on 40 face-free
frames" — is not wrong. It was made on forty **synthetic room renders**.
This is real first-person footage.

### 6.1 What was done about it, and what was not

**The filter was not weakened.** A face-detection threshold is not a
picture-quality knob, and the four true positives are exactly the case it
exists for. Instead the overlap between the filled regions and the
record's own box is measured and reported as `subject_obscured`, so a
client can say the subject is behind a fill rather than showing a black
rectangle without comment.

### 6.2 This matters more to World Builder, and is not this lane's to fix

Object Memory filters on **read**: the cost of a false positive is a
spoiled picture, and the stored frame is untouched. World Builder fills
these regions **before persistence**, at `engine._persist_keyframe`. A
40% firing rate with a 12.5% median area there destroys pixels
permanently, and its own analysis priced the honest cost at "the 5% row —
no keyframes lost, about 9% of the point cloud", which assumed a firing
rate far below this one.

Written up for that lane in
`docs/agent-handoffs/OBJECT-MEMORY-HANDOFF.md` §Requirements. Not acted on
here: `tower/tower/world_builder/**` is frozen to another lane, and a
cartridge may not import another cartridge.

---

## 7. Reproducing all of it

```bash
cd tower
V=./.venv/Scripts/python.exe
C=../../Glasses/tower/data/captures      # or wherever data/captures lives

# 1. every detection over the corpus (~28 min on CUDA)
$V scripts/research/object_memory_corpus_dump.py \
    --captures $C --out analysis/corpus-detections.jsonl --device cuda

# 2. contact sheets to read by eye
$V scripts/research/sighting_contact_sheet.py \
    --detections analysis/corpus-detections.jsonl --captures $C \
    --out analysis/sheets

# 3. the verifier bench (~10 min, downloads ~1.3 GB of weights once)
$V scripts/research/open_vocab_verifier_bench.py \
    --detections analysis/corpus-detections.jsonl --captures $C \
    --out analysis/verifier-bench.json --sheets analysis/sheets/verifier

# 4. long-session latency, one at a time, nothing else running
$V scripts/research/detector_long_session.py --captures $C --device cuda --frames 6000
$V scripts/research/detector_long_session.py --captures $C --device cpu  --frames 6000

# 5. the face filter's firing rate
$V scripts/research/face_filter_false_positives.py \
    --captures $C --per-capture 60 --sheet analysis/sheets/_face_firings.png

# 6. the end-to-end A/B, one at a time
$V scripts/object_memory_session.py --frames $C/0fc400bbcc8e4825959f951f904f284f \
    --root analysis/ab-none --device cpu --verifier none --format json
$V scripts/object_memory_session.py --frames $C/0fc400bbcc8e4825959f951f904f284f \
    --root analysis/ab-owl --device cpu --verifier owlv2 --verifier-device cuda \
    --format json
```

`analysis/` is gitignored. The contact sheets are crops of raw
first-person imagery and must stay there.
