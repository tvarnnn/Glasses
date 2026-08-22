# Scene Understanding V1 — Implementation Report

Status: **IMPLEMENTED AND MEASURED; DETECTION ACCURACY ON REAL PEOPLE
UNVALIDATED.** Branch `cartridge/experimental-cv-lab-v1`.

Every timing below is a real measurement of this code on this machine.
The imagery is rendered and **contains no COCO object**, so this report
measures the pipeline's cost and behaviour, never its accuracy on a real
room. There is no imagery of people anywhere on this host, which is a
limit on what could be validated and is stated rather than worked around.

---

## 1. The distinction that settled the design

Scene Understanding answers *"what is around me **now**"*. Environmental
Memory answers *"what did I encounter, and when"*.

Two consequences follow immediately, and both are load-bearing:

**Nothing is persisted.** No store, no journal, no imagery — enforced by
a test that fails if any write primitive is called anywhere under
`tower/scene/`. A cartridge answering "how many people are in this room"
has no reason to write to disk, and writing would import the whole of
Environmental Memory's retention, purge and privacy surface for no gain.
This is the strongest privacy posture any cartridge in this project has,
and it was free.

**There is no query CLI.** With nothing persisted there would be nothing
for a second process to read, so the run that observes the frames answers
the questions. That deletion is worth naming: the obvious symmetry with
Document Memory's `document_query.py` would have produced a script with
no data to open.

---

## 2. Counting uses tracking — measured, not asserted

The brief singles this out, and it is the cartridge's one named
correctness requirement. Summing detections fails in two directions at
once: a detector that misses someone on one frame in five reports a count
flickering between 2 and 3 while the room is still, and one that fires
twice on a person reports two people.

Counts come from **confirmed tracks**. Measured against a correct answer
of 2 throughout, over 120 frames per row:

| Detector dropout | Modal count | Counts seen | Fraction correct |
|---|---|---|---|
| 0% | 2 | [2] | **1.000** |
| 10% | 2 | [2] | **1.000** |
| 20% | 2 | [2] | **1.000** |
| 40% | 2 | [1, 2] | 0.974 |

A count taken from raw detections would follow the dropout column
exactly: 10% dropout would mean roughly one frame in ten reporting the
wrong number.

**Association is by IoU only, never appearance.** This is a privacy
decision as much as an engineering one: matching by how something looks
is the first step toward recognising it again. A `track_id` means "the
same blob one frame later", restarts at 1 every session, and a person who
leaves and returns is deliberately a **new track** — a test pins that.

---

## 3. Orientation: implemented, measured, and off

*"How many people appear to be facing my direction?"* is one of the
brief's four questions, and it is the only one that needs evidence a
detection box does not carry. Inferring facing from box shape would be
precisely the weak evidence the brief forbids.

Real evidence exists. COCO keypoints include `left_eye`, `right_eye`,
`left_ear`, `right_ear`, and their **visibility pattern** is genuine
coarse-orientation evidence:

```
both eyes + an ear   -> the front of the head is toward us
both ears, no eyes   -> the back of it
one ear              -> profile
nothing              -> unknown, and say so
```

**The cost decides the default:**

| Model | Per frame, CPU |
|---|---|
| `ssdlite320_mobilenet_v3_large` (detection) | **33 ms** |
| `keypointrcnn_resnet50_fpn` (keypoints) | **798 ms** |

798 ms is **24× the detector** and **2.5× the ~300 ms interval the
glasses deliver**. A "current" scene state computed that way would be two
frames stale before it existed.

So orientation runs at a bounded cadence on person tracks, and **every
estimate carries its age**. Past a limit it expires to `unknown` rather
than being deleted — a missing field would read as "not facing", which is
the same observation-gap error in a different costume.

**The unblocker is named rather than vague:** torch is CPU-only on this
host. A restored CUDA build is what changes this decision, not a
cleverer algorithm.

### It is never gaze, and that is enforced

`07-PLATFORM-CONSTRAINTS.md` Limitation 8: the camera cannot establish
that anyone looked at, noticed or read anything. Head orientation is not
eye direction — a person squarely facing the wearer may be reading over
their shoulder.

The state is `toward_wearer`, the property is `appears_facing_wearer`,
confidence never reaches HIGH for a visibility heuristic over an
inference, and an AST-level boundary test bans the identifiers
`looking_at`, `gaze_direction`, `is_looking`, `face_id` and `person_id`
across **every** cartridge — not just this one. Vocabulary is exactly
what drifts, so it is tested rather than trusted.

### The refusal that matters most

Asking "how many people are facing me" with orientation **disabled**
returns `answered: False` with a reason, not `0`.

Zero would be an observation gap reported as an observation of absence —
Core Principle 3's exact error, and the single most dangerous one here,
because zero *looks like data*. A caller cannot distinguish "nobody is
facing you" from "we never looked" if both render as the same integer.

---

## 4. Relationships: three asserted, four refused

Everything is **camera-relative**, and every relation carries
`frame_of_reference: "camera"`. World Builder produces poses offline,
after a session, and is not on the live frame path — there is no live
pose to anchor to, so none is invented.

**Asserted:**

| Relationship | Basis | Confidence |
|---|---|---|
| `left_of` / `right_of` | Centroid x, with a minimum separation so a one-pixel difference asserts nothing | MEDIUM |
| `higher_in_view` | Centroid y. Named for the **image**, not the room | LOW |
| `nearer_than_same_class` | Box area, within one class, at ≥1.5× | LOW |

`higher_in_view` is not called `above` on purpose: something further away
sits higher in the frame without being higher in the room, and the name
is the only thing stopping a consumer reading it as a world relation.

`nearer_than_same_class` carries its caveat **in its name** for the same
reason. Across classes a size comparison is meaningless — a laptop is not
further away than a sofa for being smaller.

**Refused, each with what would settle it:**

| Refused | Why |
|---|---|
| `in_front_of` / `behind` | Needs depth. The only depth available is MiDaS relative inverse depth, which this project measured at **6–8% temporal flicker**; ordering two boxes by a flickering field gives a relation that inverts frame to frame. **What would settle it:** run the depth experiment over two objects at a known separation and measure how often the ordering flips |
| `on` | Needs support-surface reasoning and depth. Box containment is not it — a laptop *in front of* a desk overlaps its box identically to one *on* it |
| `inside` | Same: 2-D containment cannot distinguish it |
| `near` | Image proximity is not world proximity. Two things at opposite ends of a room can be adjacent in a frame |

`why_not(relationship)` returns those reasons through the query API, and
the scene state lists the refused set. **A relationship nobody can
support is worse than a missing one**, because a consumer cannot tell a
wrong answer from a right one — and a refusal that can explain itself
stops the next cartridge re-deriving the same conclusion.

---

## 5. Measured costs

| Stage | Cost |
|---|---|
| Tracking + relations + query, together | **0.016 ms** |
| Detection, 640×360 | 33.1 ms |
| Detection, 896×504 | 36.8 ms |
| Detection, 1280×720 | 34.4 ms |
| Orientation (optional) | 798 ms |

Two things worth drawing out.

**Detection cost is essentially independent of resolution**, confirming
what the Lab measured: the model resizes to 320 internally, so sending a
bigger frame costs decode time and buys nothing. That is a real
constraint on any future design here.

**The cheap half is negligible** — 0.016 ms for tracking, relationship
derivation and the query layer combined, against 33 ms for the model.
The design's assumption that only the models cost anything holds, and a
test pins it so that stops being an assumption if it ever changes.

---

## 6. What was deliberately not built

| Not built | Why |
|---|---|
| A store | This is a live state. Persistence is Environmental Memory's job, and adding it here would pre-empt that module's whole reason to exist |
| A query CLI | Nothing is persisted, so there would be nothing to query |
| Re-identification across sessions | Needs appearance matching, which is identity |
| A scene *graph* with typed edges | The relation list is a graph; a dedicated graph type would be structure without a consumer |
| Depth-based relationships | See §4 |
| An LLM/VLM re-reading frames | The brief's explicit direction, and the measurements support it: structured perception costs 33 ms and answers the questions |
| Registration as a production module | Same V1.0/V1.1 boundary as every other cartridge |

---

## 7. Limitations

- **Detection accuracy on real people is unvalidated.** No imagery of
  people exists on this host. The pipeline is measured; the detector's
  real-world behaviour is not, and the synthetic room correctly yields
  zero detections rather than anything to check against.
- **Camera-relative only.** "Left of" means left in the current view.
- **No depth**, hence four refused relationships.
- **Orientation is coarse, optional, and not gaze.**
- **A count is of what is visible.** An occluded or out-of-frame person
  is not counted, and absence of a detection is never evidence of
  absence — every count answer says so.
- **Greedy IoU association.** A Kalman filter or Hungarian assignment
  would both be defensible; neither is justified without a measurement
  showing greedy failing.
