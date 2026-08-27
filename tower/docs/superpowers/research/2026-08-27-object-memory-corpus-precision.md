# Object Memory — what the detector actually sees, and what it gets wrong

**Date:** 2026-08-27
**Corpus:** `tower/data/captures/` — 34 captures, **18,821 frames**,
**1,942 seconds** of recording, all 360×640 portrait, 0 undecodable. Real
Ray-Ban Meta footage relayed through an iPhone.

**Harnesses:** `tower/scripts/research/object_memory_corpus_dump.py`,
`sighting_contact_sheet.py`, `open_vocab_verifier_bench.py`,
`detector_long_session.py`, `face_filter_false_positives.py`. Every figure
below is reproducible from those five commands.

> **Corrected in place, 2026-08-27, after an independent audit.** Every
> count derived from the corpus survived unchanged. **No latency figure
> did**: all were first measured on a host that was simultaneously
> running a test suite, and all are re-measured here on an idle one. §5.2
> retracts a claim outright, and §4.2 records a methodological error in
> the benchmark itself. Corrections are folded into the sections they
> belong to rather than appended, with the old figure named each time.

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
| person | 6,899 | 2,940 | 0.300 | 38.7% | 32 |
| cell phone | 3,613 | 2,814 | 0.604 | 8.7% | 27 |
| bed | 1,314 | 295 | 0.307 | 49.7% | 21 |
| keyboard | 1,086 | 695 | 0.295 | 10.5% | 19 |
| tv | 1,085 | 437 | 0.276 | 16.0% | 23 |
| couch | 396 | 76 | 0.252 | 43.7% | 15 |
| sink | 310 | 166 | 0.243 | 17.0% | 8 |
| chair | 171 | 63 | 0.197 | 9.0% | 15 |

`person` has a median box area of **38.7% of the frame** at the ≥0.5
threshold this table uses (35.4% if every detection down to 0.15 is
counted — an earlier draft quoted that figure against a table of ≥0.5
rows, which was an apples-to-oranges slip an audit caught). On
head-mounted footage that is the wearer's own torso and arms seen while
looking down, which is the same finding the 2026-08-26 pass made on the
smaller corpus, and it survives at double the sample.

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

**The 3-frame floor is not taste.** 264 of 763 — 35% — are one or two
frames, a class that fired once and never again. Writing them would make
a third of the memory noise. Three frames costs two inter-frame gaps:
**167 ms** at the repo's measured 83.5 ms delivered interval, **206 ms**
against the corpus's own 9.7 frames a second averaged across whole
captures.

**One memory every 9.2 seconds is a scrollable list.** The 211
`remembered`- and `verify`-tier sightings over 1,942 seconds work out at
about 380 an hour. (An earlier draft said "one per 45 seconds", which
came from reading 18,821 ÷ 404 = 46.6 *frames* as seconds. Corrected.)
The 30-second resample window could not produce a number with any
relationship to what the camera did at all: an object glanced at twice in
a second gave one record and an object watched for four minutes gave
eight.

---

## 3. Reading the crops — the measurement that changed the design

Method: group into sightings, take the strongest frame of each, crop with
35% padding, lay them out strongest-first on a contact sheet, read them.
One human pass, recorded here in full including the classes that were not
inspected.

| class | sightings | inspected | correct | what the wrong ones actually were |
|---|---|---|---|---|
| laptop | 78 | 24 | **24** | — |
| cell phone | 80 | 24 | **24** | — 22 of the 24 round to 1.00 at two decimals; none is exactly 1.00 and the highest is 0.9991 |
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

**Provenance, stated because it is weaker than the sighting counts.** The
sighting counts regenerate exactly from
`object_memory_corpus_dump.py`. The `inspected`/`correct` columns are one
human pass over contact sheets read strongest-first. The **sheets**
regenerate; the **per-tile verdicts** were only written down for the
classes that went into the benchmark's `GOLDEN` dict (§4.2). For `bed`
(24 read, 20 right) and `chair` (6 read, 5 right) the counts in this
table are the only record and cannot be re-derived without someone
looking again. Both are `context`-tier and neither is ever written, so
nothing downstream depends on them.

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

**They are 81% block assertions** — `[True] * 24` for laptop and the same
for cell phone — and an audit tested how much that matters. Any single
flip moves balanced accuracy by **at most 0.015**; it takes **seven
adversarial flips (7.4% of the set)** to drop below 0.90; and under every
plausible group relabelling tried (`suitcase` → True, the AirPods case →
True, `remote` all-False, `remote` all-True, four of the 48 laptop and
phone crops wrong) OWLv2 stays between 0.89 and 0.97 and **0.45 remains
the optimal threshold in every scenario**. The conclusion is robust; the
third significant figure is not, which is why §4.3 reports ~93% and ~94%.

**The vocabulary is the shipped one.** It was restated once and the two
drifted — the benchmark ran 34 words while `verifier_vocabulary()`
returned 31, so its figures described a configuration that does not ship.
The harness now imports the list and adds only what the labelled set
needs (`necktie`, for a class the shipped policy ignores entirely),
reported in its output. Re-running against the shipped list changed
nothing.

### 4.3 The result

| model | accepts correct | rejects wrong | balanced | median ms | peak VRAM | license |
|---|---|---|---|---|---|---|
| **owlv2-base-patch16-ensemble** | **0.949** | 0.857 | **0.903** | **126** | 842 MB | Apache-2.0 |
| llmdet-tiny | 0.407 | 1.000 | 0.703 | 3,091 | 1,643 MB | Apache-2.0 |

At rank-1 with no score threshold, over the shipped 31-word vocabulary
plus `necktie`. Resident VRAM: 620 MB (OWLv2) against 692 MB (LLMDet);
cold load 7.0 s against 6.6 s.

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
* It also pays for the sentence. **3.1 seconds a crop against 126
  milliseconds**, twenty-five times slower, because cross-attention
  scales with text length.

A model that answers a different question well is not the better model
for this question.

### 4.4 The threshold

Swept over the same 94 crops, accepting only when the proposed label
ranks first **and** scores at least the threshold:

| min score | accepts | rejects | balanced | false accepts | false rejects |
|---|---|---|---|---|---|
| 0.00 | 0.949 | 0.857 | 0.903 | 5 | 3 |
| 0.35 | 0.932 | 0.857 | 0.895 | 5 | 4 |
| 0.40 | 0.932 | 0.886 | 0.909 | 4 | 4 |
| **0.45** | **0.932** | **0.943** | **0.938** | **2** | **4** |
| 0.50 | 0.915 | 0.943 | 0.929 | 2 | 5 |
| 0.55 | 0.814 | 0.943 | 0.878 | 2 | 11 |
| 0.60 | 0.576 | 0.943 | 0.760 | 2 | 25 |

0.40–0.50 is a **shoulder with its peak at 0.45** — not a plateau; the
balanced figures are 0.909, 0.938 and 0.929. Above 0.55 acceptance
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

**Every figure in this section was re-measured with no other work of
ours running, one job at a time.** The first set was not, and every one
of them was wrong by about a third.

**This host is not quiet, and "idle" would be the wrong word.** It
carries several autonomous agent lanes at the same time — two more
appeared in `git worktree list` while these numbers were being taken. So
the latency figures below are **ranges**, and they are given as ranges.
Four consecutive replays of the same capture, back to back, gave 40.6,
43.4, 45.1 and 46.9 ms/frame: an 11% spread with nothing of ours
competing.

That is the most transferable finding in this section. A benchmark that
shares this box with a test suite reports numbers 30–50% high, and a
*cumulative* mean of such a run looks like a trend (§5.2).

### 5.1 The detector

Replaying the physically validated capture (2,203 frames, 186 s of
recording), one run at a time:

| device | seconds | ms/frame | detections | observations |
|---|---|---|---|---|
| **CPU** | 103.3 | **46.886** | 4,287 | 8 |
| CPU, three more back-to-back runs | 89.4 / 95.5 / 99.3 | **40.572 / 43.366 / 45.086** | 4,287 | 8 |
| CUDA | 107.4 | 48.757 | 4,285 | 8 |

**The two are within noise of each other.** The CPU spread alone is
40.6–46.9 across four consecutive runs; CUDA measured 48.8 here and 43.9
in an independent audit which also measured CPU at 51.0 — i.e. the
ordering flipped between two honest measurements on the same machine. An
earlier draft of this document claimed CPU was ~30% faster on the
strength of contended runs.
An independent audit on the same host measured the ordering the other way
(CUDA 43.9 against CPU 51.0) at a similar margin; run-to-run variance on
this machine is 16–25%, which is larger than the gap. The honest
statement is that this detector costs about the same either way, because
the work is single-frame preprocessing and transfer rather than the
320×320 forward pass.

The CPU run reproduces the physically validated run's detection count
**exactly** (4,287). CUDA differs by two detections at the threshold,
which is ordinary numeric drift.

**So `observation_device` defaults to `cpu` for a different reason than
speed:** the GPU is shared — World Builder, the depth experiment, and
this cartridge's own verifier at 620 MB — and a producer that follows a
capture has no latency requirement at all. It may fall behind and catch
up. It is the one stage that should stay off the contended device.

Reading and decoding the corpus costs about **1.06 ms/frame** with 46 MB
of RSS (3,000 frames in 3.19 s), so essentially none of the above is I/O.

### 5.2 Long-session behaviour — a retraction

A first pass reported a monotonic climb in per-frame cost (49.5 →
87.8 ms over 18,821 frames) and it was **wrong**.

The figure was a *cumulative* mean, printed as a progress line, from a
run competing with a test suite and a contact-sheet render. **A
cumulative mean rises monotonically whenever the underlying series steps
up even once, and can never come back down.** De-cumulating the same log
gives per-1,000-frame windows of

    49.5  47.5  46.1  55.7  74.2 100.8  99.4  95.6  91.8
    89.4  92.6 100.6 108.5 101.9 106.4  98.4  88.3 106.7

— a step at frames 3,000–6,000, where the competing work started, and
then a plateau. Not a climb.

Measured directly, in windows, one job at a time:

| run | window medians (500 frames each) | drift ratio | peak RSS |
|---|---|---|---|
| CUDA, 6,000 frames | 120, 114, 100, 85, 96, 101, 124, 123, 99, 112, 101, 117 | **0.968** | 1,442 MB |
| CPU, 6,000 frames | 154, 142, 165, 98, 97, 94, 115, 134, 99, 115, 93, 125 | **0.808** | **704 MB** |
| CUDA, 10,000 frames (independent audit) | 46.6 → 60.2 → 43.0 → 48.5 | **1.041** | flat |

No trend, no leak. The CUDA allocator's reserve plateaus at 436 MB and
RSS is flat. `torch.cuda.empty_cache()` every 200 frames made no reliable
difference — the run with it measured lower, but by less than the spread
between windows.

**The producer's steady-state cost is ~700 MB RSS on CPU.**

### 5.3 The verifier

| | |
|---|---|
| CUDA | **126 ms** median / 129 ms p95 per crop; 620 MB resident, 842 MB peak |
| CPU | **2,473 ms** median per crop, +796 MB RSS |
| load | ~7 s cold, ~600 MB of weights downloaded once |

CPU is 19× slower. Since the detector costs about the same on either
device and the verifier does not, the two stages default to **different
devices** — which also keeps a 2.5-second burst off the cores the
detector is using.

### 5.4 End to end, on the validated capture

One run at a time, idle host:

| | observations | seconds | ms/frame | verifier calls | model time |
|---|---|---|---|---|---|
| `--verifier none` | 8 | 103.3 | 46.886 | — | — |
| `--verifier owlv2` | **11** | 112.1 | 50.879 | **4** | 1.00 s |

Of the 8.8 extra seconds, **1.0 is inference** and the remainder is the
one-off model load. Excluding the load, that is **+0.45 ms/frame for
three more memories** (2 `bottle`, 1 `mouse`). Queue peak depth **0**;
backlog drops **0**; 250 ms per call end to end, against the 126 ms of
pure inference in §5.3 — the difference is the colour conversion, the
PIL round-trip and the processor.

Four calls across 2,203 frames is **one per 551**, which is sparser than
the corpus-wide 1-in-355 because this particular capture is dominated by
a laptop and a phone.

The part-of rule (a `keyboard` sighting is suppressed while a `laptop`
sighting is open) suppressed 96 detections on this capture and removed
the `keyboard` record entirely — in this walk the keyboard is never in
view without the laptop it belongs to.

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
| cost | 21.8 ms/frame |

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

## 7. Can an open-vocabulary pass find what COCO cannot name?

The verifier fixes wrong labels. It **cannot** touch the second half of
§3.1 — that keys, a wallet and a pair of glasses have no COCO class —
because it only ever sees crops the shipped detector produced, and the
shipped detector never fires on a set of keys.

So the obvious next move is a **discovery pass**: run the open-vocabulary
model on whole frames, asynchronously, with a curated prompt list. Before
anyone builds that, this measures whether it works on this footage.
`scripts/research/open_vocab_discovery.py`, 674 frames sampled evenly
across all 34 captures, threshold 0.15, eight target prompts against
eight distractors.

| prompt | hits | frames | captures | max score | median area |
|---|---|---|---|---|---|
| a charging cable | 128 | 47 | 11 | 0.475 | 1.55% |
| a remote control | 117 | 95 | 23 | 0.605 | 0.58% |
| a backpack | 52 | 33 | 14 | 0.624 | 5.22% |
| a pill bottle | 36 | 19 | 9 | 0.456 | 0.32% |
| a wallet | 23 | 21 | 6 | 0.646 | 2.66% |
| a paper document | 21 | 18 | 11 | 0.320 | 2.12% |
| a pair of eyeglasses | 3 | 3 | 3 | 0.620 | 0.50% |
| **a set of keys** | **1** | 1 | 1 | 0.152 | 0.11% |

**Cost: 119.6 ms per frame.** Running it on every delivered frame would
be about 1.5× the entire frame budget, so a discovery pass is inherently
sampled and asynchronous. That is a design constraint, not a tuning
choice.

### 7.1 What it found, read by eye

Two contact sheets, 66 tiles between them.

**It genuinely finds things COCO cannot name.** A black bag on a luggage
rack comes back as `a backpack` at 0.62 across 14 captures — where
SSDLite's single `backpack` sighting in the whole corpus was a closet of
hanging clothes. `a pill bottle` reliably picks out toiletries on a
bathroom counter (the name is a stretch; the region is right). `a pair of
eyeglasses` at 0.62 is a real pair of glasses.

**It does not solve the small-object problem.** `a set of keys` produced
**one hit in 674 frames**, at 0.11% of the frame. That measures nothing
about recall — this corpus almost certainly contains no keys — but it
does establish that the model is not hallucinating them everywhere,
which was the other thing worth knowing.

**Precision at 0.15 is about a third.** Roughly 12 of 36 tiles on the
general sheet are right. `a remote control` reproduces the shipped
detector's exact failure — laptop keyboards and hands — and `a charging
cable` fires on white door frames and blurred smears. A discovery pass
would need its own threshold and, realistically, its own verification
stage: the same funnel, one level up.

### 7.2 A privacy finding, and it is the important one

**`a pair of eyeglasses` is a face detector in disguise.** Its two
strongest hits on this corpus are a person's face, because that is where
glasses are.

A discovery pass is prompted with a list, and it is tempting to treat
that list as a tuning knob — add a word, see what turns up. It is not.
**A prompt list is a privacy surface**, exactly as `PERSISTED_CLASSES`
is: `eyeglasses`, `wristwatch`, `ring`, `name badge`, `medication` and a
dozen other reasonable-sounding entries all resolve, on first-person
footage, to a person. If a discovery pass is ever built, its prompt list
needs the same treatment `classes.py` gives the class table — a
deterministic, reviewed, closed set with the reasoning written down, and
an exclusion check that runs *after* the model rather than before it.

### 7.3 The recommendation

**Worth building, on the async path, for medium-sized personal
objects** — bags, bottles, documents, chargers — at a threshold well
above 0.15 and behind a verification stage. **Not worth building as a
fix for the size floor**, which is upstream of every model here and is
fixed by capture resolution or tiling, not by vocabulary.

Not built in this wave. It is a new persistence path with a new privacy
surface, and it should be a decision rather than an inference.

---

## 8. Reproducing all of it

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

# 5. does an open-vocabulary pass find what COCO cannot name?
$V scripts/research/open_vocab_discovery.py \
    --captures $C --per-capture 20 --out analysis/discovery.json \
    --sheet analysis/sheets/_discovery.png

# 6. the face filter's firing rate
$V scripts/research/face_filter_false_positives.py \
    --captures $C --per-capture 60 --sheet analysis/sheets/_face_firings.png

# 7. the end-to-end A/B, one at a time
$V scripts/object_memory_session.py --frames $C/0fc400bbcc8e4825959f951f904f284f \
    --root analysis/ab-none --device cpu --verifier none --format json
$V scripts/object_memory_session.py --frames $C/0fc400bbcc8e4825959f951f904f284f \
    --root analysis/ab-owl --device cpu --verifier owlv2 --verifier-device cuda \
    --format json
```

`analysis/` is gitignored. The contact sheets are crops of raw
first-person imagery and must stay there.
