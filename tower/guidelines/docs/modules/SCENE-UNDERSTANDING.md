# Module Concept — Scene Understanding / Environmental Intelligence

## Status

**CURRENTLY IMPLEMENTED** as of 2026-08-22 (`tower/scene/`), with one
part deliberately off by default.

| Part | Status |
|---|---|
| Object detection, anonymous tracking, counts from tracks | **CURRENTLY IMPLEMENTED** |
| Camera-relative positions and relationships | **CURRENTLY IMPLEMENTED** |
| Query layer, including refusals | **CURRENTLY IMPLEMENTED** |
| Coarse head orientation ("appears to be facing your direction") | **IMPLEMENTED, OFF BY DEFAULT** — 43.4 ms per call on CUDA, 956.4 ms on CPU, and CPU is the default device. See Orientation |
| World-anchored positions | **BLOCKED** — no live world pose exists. Camera-relative is the honest alternative and is what ships |
| Depth-dependent relationships (`in_front_of`, `on`, `inside`) | **REFUSED**, each with the evidence it would need |
| Registration as a production module | **BLOCKED** at the same V1.0/V1.1 boundary as every other cartridge |
| Validation on real people | **BLOCKED** — there is no imagery of people anywhere on this host |

Plan: `docs/superpowers/plans/2026-08-22-scene-understanding-v1.md`.
Report: `reports/2026-08-22-scene-understanding-v1-report.md`.

## Goal

Maintain a structured understanding of what exists around the wearer
**right now**, so questions like these can be answered from perception
rather than by asking a model to re-read a raw frame each time:

- How many people are in this room?
- Where is the desk? Where is a chair?
- How many people appear to be facing my direction?

## The distinction that settles the design

**Scene Understanding is a live state. Environmental Memory is a
history.** One answers "what is around me now"; the other answers "what
did I encounter, and when".

From that, two consequences that are not negotiable:

- **Nothing is persisted.** No store, no journal, no imagery. A cartridge
  answering "how many people are in this room" has no reason to write to
  disk, and writing would import all of Environmental Memory's retention,
  purge and privacy surface for no gain. A test asserts that no write
  primitive is ever called. If a durable record is wanted, it belongs in
  Environmental Memory and should be built there.
- **There is no query CLI.** With nothing persisted there would be
  nothing for a separate process to read, so the run that observes the
  frames answers the questions.

## Counting uses tracking, and that is the point

Summing detections is wrong in two directions at once: a detector that
misses someone on one frame in five reports a count flickering between 2
and 3 while nothing in the room changed, and one that fires twice on a
person reports two people.

Counts therefore come from **confirmed tracks** — associated across
frames, with a minimum hit streak before they count and a maximum miss
budget before they expire. Measured, with a correct answer of 2
throughout:

| Detector dropout | Modal count | Counts seen | Fraction correct |
|---|---|---|---|
| 0% | 2 | [2] | 1.000 |
| 10% | 2 | [2] | 1.000 |
| 20% | 2 | [2] | 1.000 |
| 40% | 2 | [1, 2] | **0.965** |
| 60% | 2 | [0, 1, 2] | **0.783** |

A count taken from raw detections would follow the dropout column
exactly.

The 40% row was **0.974 before the confirmation fix in §8.1**, 0.939
after it, and 0.965 since the miss budget was retuned; the 60% row is
new and is where that retune shows, at 0.783 against **0.252** on the
old constant. Requiring a consecutive streak means a track dropped at
extreme dropout takes longer to re-confirm, and it is what stops a
detection present one frame in six from becoming a permanent phantom
person. A count that is occasionally conservative under a detector
losing 40% of frames is a better failure than one that is permanently
wrong under a reflection.

**The miss budget is a duration, and it was written as a frame count.**
`max_misses = 5` was justified as "roughly 1.5 seconds of absence"
against an assumed ~3.3 fps. At the measured 12.0 fps it bought 0.42 s,
so a person occluded for half a second was dropped, returned with a new
`track_id`, and was **counted as somebody new** — the exact failure
counting-from-tracks exists to prevent. It is now derived:
`MAX_ABSENCE_S = 1.0` divided by the measured frame interval, which is
12 frames. The sweep behind that number, on 9,145 real corpus frames,
is in `docs/superpowers/research/2026-08-26-tracker-retune.md`. The other
two thresholds were swept in the same pass and both survived, with
`min_iou = 0.25` now derived from the measured 1st percentile of
same-object consecutive-frame IoU and `min_hits = 3` from a two-sided
sweep that rejects 4 and 2.

The cost is named rather than hidden: a track whose object has genuinely
gone stays confirmed for up to one second, so the count can be one too
high for that long. That is a real claim about the room, and 1.0 s is
where it was put because count stability at 18 and 24 frames is
identical to 12 — a longer window buys nothing measurable and asserts
more.


**Association is by IoU only, never appearance.** Matching by how
something looks is the first step toward recognising it again. A
`track_id` means "the same blob one frame later", restarts at 1 every
session, and a person who leaves and returns is deliberately a **new
track**.

## Orientation, and why it is off

*"How many people appear to be facing my direction?"* needs evidence. A
person box carries none — inferring facing from box shape would be
exactly the weak evidence the brief forbids.

Real evidence exists: COCO keypoints include eyes and ears, and their
**visibility pattern** is genuine coarse-orientation evidence. Both eyes
and an ear means the front of the head is toward the camera; both ears
and no eyes means the back of it.

Measured cost — warm medians over **754 real corpus frames** at 360×640,
decode excluded, `torch.cuda.synchronize()` bracketing every CUDA call
(`docs/superpowers/research/2026-08-26-scene-understanding-measurements.md`):

| Model | CUDA | CPU |
|---|---|---|
| `ssdlite320_mobilenet_v3_large` (detection) | **30.4 ms** | **32.9 ms** |
| `keypointrcnn_resnet50_fpn` (keypoints) | **43.4 ms** | **956.4 ms** |
| keypoints, p95 | 50.6 ms | 1112.8 ms |

**The device is the variable that matters, and none of this document's
earlier figures named one.** This section used to say 798 ms, "24× the
detector" and "2.5× the ~300 ms interval the glasses deliver". All four
numbers are wrong:

- Orientation is **43.4 ms on CUDA** and **956.4 ms on CPU** — a 22.0×
  spread, and the CPU figure is *worse* than either number previously
  documented, because those were measured on synthetic input.
- The detector is launch-bound at an internal 320 px and gains almost
  nothing from the GPU, so orientation is **1.43× the detector on CUDA**
  and 29.1× on CPU. The ratio inverts with the device.
- The delivered frame interval, measured from the corpus's own
  `frames.jsonl` receipt timestamps, is **83.5 ms (12.0 fps)**, not
  ~300 ms — the docs were off by 3.6×. Against the real interval
  orientation is **0.52× on CUDA** and 11.5× on CPU.
- Cost is flat in the number of people: ~1 ms each, 40.0 ms at zero to
  44.3 ms at four. VRAM peaks at 988 MB reserved of 12 GB.

**The cadence survives; its constant did not.** Detector plus orientation
is 73.8 ms against an 83.5 ms budget on CUDA — per-frame fits at the
median and overruns at p95 (86.4 ms), at an 88% duty cycle with no
headroom and no accuracy to show for it, since a person's facing does not
change in 83 ms. So `ORIENTATION_INTERVAL_S` is now **3 delivered frames,
~250 ms**, not 2.0 s. The stride is `TrackerPolicy.min_hits`: estimating
facing more often than a track can be confirmed buys nothing.

**Every estimate still carries its age**, expiring to `unknown` rather
than being deleted — a missing field would read as "not facing". CUDA did
*not* make that bookkeeping redundant, for two reasons unrelated to 43 ms:
`TorchvisionPoseEstimator` defaults to `device="cpu"`, where the original
argument holds in full at 956 ms; and `age_estimate`'s clamp guards a
backward NTP step that pushed an expiry deadline into the future, which is
a clock bug, not a latency one.

**The old unblocker is spent.** This document used to say torch was
CPU-only on this host and a restored CUDA build was what would change the
decision. That build exists — `torch 2.13.0+cu132`, verified executing on
an RTX 5070 (Blackwell, sm_120) — and the numbers above came from it. The
cost question is closed. **Accuracy is not measured and cannot be here**:
there is no bystander footage on this host, and the corpus's person boxes
are almost certainly the wearer's own torso, so `facing_from_keypoints`
remains unvalidated against ground truth.

### It is never gaze

`07-PLATFORM-CONSTRAINTS.md` Limitation 8: the camera cannot establish
that anyone looked at, noticed or read anything, and there is no eye
tracking on this hardware. Head orientation is not eye direction — a
person squarely facing the wearer may be reading over their shoulder.

The state is `toward_wearer`, the property is `appears_facing_wearer`,
confidence never reaches HIGH, and a boundary test bans the identifiers
`looking_at`, `gaze_direction`, `is_looking`, `face_id` and `person_id`
across **every** cartridge.

**Asking the question with orientation disabled returns a refusal, not
zero.** Zero would be an observation gap reported as an observation of
absence — Core Principle 3's exact error, and the one most likely to be
mistaken for data because zero looks like an answer.

## Relationships: what is asserted, and what is refused

Everything is **camera-relative**, and every relation says so. World
Builder produces poses offline, after a session, so there is no live pose
to anchor to. No world ids are invented.

**Asserted:**

| Relationship | Basis |
|---|---|
| `left_of` / `right_of` | Box centroid x, with a minimum separation so a one-pixel difference asserts nothing |
| `higher_in_view` | Box centroid y. Named for the **image**, not the room: something further away sits higher in frame without being higher in the room |

**Refused, each with the evidence it would need:**

| Refused | Why, and what would settle it |
|---|---|
| `in_front_of` / `behind` | Needs depth. The only depth available is MiDaS relative inverse depth, measured by this project at 6–8% temporal flicker; ordering two boxes by a flickering field gives a relation that inverts frame to frame. To settle it: run the depth experiment over two objects at a known separation and measure how often the ordering flips |
| `on` | Needs support-surface reasoning and depth. Box containment is not it — a laptop *in front of* a desk overlaps its box identically to one *on* it |
| `inside` | Same: 2-D containment cannot distinguish it |
| `near` | Image proximity is not world proximity. Two things at opposite ends of a room can be adjacent in a frame |
| `nearer_than_same_class` | **Shipped, then withdrawn.** Box area within one class looked like safe evidence for relative distance; an adversarial review produced two chairs at the *same* distance, one face-on and one edge-on, whose areas differ 2.5x — a wrong relation, not a weak one. Nothing in a 2-D box separates shape from distance |

`why_not(relationship)` returns those reasons, so the next cartridge does
not re-derive them from scratch. **A relationship nobody can support is
worse than a missing one**, because a consumer cannot tell a wrong answer
from a right one.

## Privacy

The strongest posture of any cartridge so far, and it is free here
because the purpose is a live answer:

- **Nothing persisted.** No store, no imagery, no history.
- **No identity.** Anonymous, session-scoped track ids, meaningless
  across processes. No appearance matching, so no re-identification.
- **No face processing.** Keypoints locate eyes and ears as anonymous
  landmarks; they produce no descriptor and support no matching.

  This bullet used to add "no face detector exists on this platform
  anyway", and that justification was **wrong**. `cv2.FaceDetectorYN` is
  compiled into our OpenCV and needed only a 227 KB weights file, which
  is now vendored at `models/face_detection_yunet_2023mar.onnx` and used
  by World Builder to redact faces before a keyframe is written. The
  original search was scoped to `cv2/` and missed it; the same error was
  corrected in `reports/2026-08-22-cartridge-run-report.md` on 2026-08-23
  and missed here.

  **The posture is unchanged and does not depend on that claim.** This
  cartridge does no face processing because it has no need to, not
  because it could not. A capability being available is exactly when
  "we don't do this" has to be a decision rather than a limitation.
- **Raw pixels are ephemeral**, held only for the frame being processed.

## Relationship to other cartridges

- **Environmental Memory** — the history to this cartridge's present. If
  a durable record of "what was in this room" is wanted, it belongs
  there. Do not add a store here.
- **Experimental CV Lab** — measured the detector this cartridge uses
  (35.3 ms, and notably resolution-independent), which is exactly what
  the promotion path is for. It is **not imported**: the Lab's
  `ExperimentResult` cannot carry a box, and the two want different
  things from the same weights.
- **World Builder** — provides no live pose, so no anchoring today. The
  contract for a future upgrade is already written in
  `CARTRIDGE-GROUNDWORK.md` §4 and is not pre-empted here.
- **Object Memory** — tracks *objects over time*; this tracks them
  *across frames*. Do not merge: one needs identity across sessions, and
  this must never have it.

## Limitations

- **Detection accuracy on real people is unvalidated.** There is no
  imagery of people anywhere on this host, so the pipeline is measured
  and the detector's real-world behaviour is not.
- **Camera-relative only.** "Left of" means left in the current view and
  means something else the moment the wearer turns.
- **No depth**, hence the refusals above.
- **Orientation is coarse and optional**, and is not gaze.
- **A count is of what is *visible*.** An occluded or out-of-frame person
  is not counted, and absence of a detection is never evidence of
  absence.
