# Scene Understanding V1 — implementation plan

**Status:** PLAN. Written 2026-08-22 on `cartridge/experimental-cv-lab-v1`
@ `da2e678`. Cartridge 3 of the sequential run.

**Creates** the plan for a cartridge that had none. The nearest existing
document is `guidelines/docs/modules/ENVIRONMENTAL-MEMORY.md`, and the
distinction between the two matters enough to state first.

---

## 1. What this is, and what it is not

**Scene Understanding answers "what is around me *now*".** Environmental
Memory answers "what did I encounter, and when". One is a live state; the
other is a history.

That single distinction settles most of the design:

- **Nothing is persisted.** Scene state lives in memory and is discarded.
  A cartridge that answers "how many people are in this room" has no
  reason to write anything to disk, and writing would import all of
  Environmental Memory's retention, purge and privacy surface for no
  gain. If a durable record is ever wanted, that is Environmental
  Memory's job and it should be built there.
- **No identity, ever.** Tracks carry anonymous session-scoped ids that
  mean "the same blob I saw last frame", not "the same person as
  yesterday". Nothing survives the process.

The brief's example questions, and what each honestly requires:

| Question | Requires |
|---|---|
| How many people are in this room? | Detection + **tracking**. Summing detections is wrong |
| Where is the desk? | Detection + a camera-relative position |
| Where is a chair? | Same |
| How many people appear to be facing my direction? | Coarse orientation evidence — see §4, which is where this gets expensive |

---

## 2. What already exists that this reuses

Cartridge 1 measured the detector this cartridge needs, which is exactly
what `EXPERIMENTAL-CV.md`'s promotion path is for — *experiment →
measured success → dedicated module*.

`ssdlite320_mobilenet_v3_large`, COCO, torchvision (already a dependency):

| Resolution | Total | Inference |
|---|---|---|
| 640×360 | 35.3 ms | 30.3 ms |
| 896×504 | 35.5 ms | 31.8 ms |
| 1280×720 | 37.3 ms | 30.9 ms |

**Detection cost is essentially independent of input resolution**, because
the model resizes to 320 internally. That was measured in the Lab and it
is a real constraint on this design: sending bigger frames buys nothing.

COCO gives `person`, `chair`, `couch`, `dining table`, `tv`, `laptop` —
literally the brief's example questions.

**It will not import the Lab.** The Lab's `object_detection` experiment
returns `ExperimentResult`, which is scalars and a `name -> number` bag —
it cannot carry a box. The two need different things from the same model:
the Lab wants swappable models with timings, this wants stable structured
output. A test forbids the import in both directions.

---

## 3. Counting must use tracking, and this is the whole point

The brief is explicit: *person counting must use tracking rather than
naïvely summing detections*. Two failure modes make that non-negotiable:

- A detector that misses a person on one frame in five would report a
  count that flickers between 2 and 3 while nothing in the room changed.
- A detector that fires twice on one person reports two people.

**Design:** an IoU-based multi-object tracker with anonymous ids, a
minimum hit streak before a track is *confirmed*, and a maximum age
before it is dropped. Counts come from **confirmed tracks**, never from
raw detections.

**Deliberately no appearance features.** Re-identification by appearance
is the first step toward identity, and the brief forbids persistent
identity. IoU association across adjacent frames means "the same blob,
one frame later" and nothing more.

---

## 4. Orientation: the expensive question, and an honest answer

*"How many people appear to be facing my direction?"* needs evidence. A
COCO person box carries none — box shape tells you nothing about which
way someone faces, and inferring it from aspect ratio would be exactly
the weak evidence the brief forbids.

Real evidence exists: **COCO keypoints include `left_eye`, `right_eye`,
`left_ear`, `right_ear`**, and their *visibility pattern* is a genuine
coarse-facing signal. Both ears and both eyes visible means facing toward
or away; one ear means profile.

**Measured cost, and it decides the design:**

| Model | Per frame, CPU |
|---|---|
| `ssdlite320_mobilenet_v3_large` (detection) | **32 ms** |
| `keypointrcnn_resnet50_fpn` (keypoints) | **744 ms** |

744 ms is **23× the detector** and **2.5× the ~300 ms interval the
glasses deliver**. It cannot run per frame, and pretending otherwise
would produce a "current" scene state that is two frames stale before it
is computed.

**Decision: orientation is an optional stage, OFF by default, run at a
bounded cadence on person tracks only, and every estimate carries its
age.** A person's facing does not change every 300 ms, so a one- or
two-second-old estimate is still useful — but only if the consumer can
see how old it is.

**And it is never called gaze.** The field is `appears_facing_wearer`.
`07-PLATFORM-CONSTRAINTS.md` Limitation 8 is explicit that the camera
cannot establish attention; head orientation is not eye direction, and a
person facing the wearer may be looking past them.

**The unblocker is named:** torch is CPU-only on this host. A restored
CUDA build is the measurement that would change this decision, not a
different algorithm.

---

## 5. Relationships: only what 2-D boxes can support

The brief lists candidates and says to implement only those supported by
evidence. Sorted honestly:

| Relationship | Verdict |
|---|---|
| `left_of` / `right_of` | **IMPLEMENT.** Box centroid x, camera-relative. Honest and directly useful |
| `above` / `below` | **IMPLEMENT**, as image-space only, named `higher_in_view` so it is not mistaken for a world relation |
| `nearer_than` (same class only) | **IMPLEMENT with the caveat in the name.** A bigger box of the same class is nearer. Across classes it is meaningless — a laptop is not further away than a sofa for being smaller |
| `in_front_of` / `behind` | **REFUSE.** Needs depth. The only depth available is MiDaS relative inverse depth, which this project measured at **6–8% temporal flicker**; ordering two boxes by a flickering field produces a relationship that flips frame to frame. Naming the measurement that would settle it: run the depth experiment over a scene with two objects at known separation and measure how often the ordering inverts |
| `on` | **REFUSE.** "The laptop is on the desk" needs support-surface reasoning and depth. Box containment is not it — a laptop *in front of* a desk overlaps identically |
| `inside` | **REFUSE.** Same reason |
| `near` | **REFUSE.** Image proximity is not world proximity. Two things at opposite ends of a room can be adjacent in a frame |

Refusals are not omissions. Each is recorded with the evidence it would
need, so a later cartridge does not re-litigate it from scratch.

---

## 6. Spatial anchoring: camera-relative, and documented as such

The brief allows this explicitly: *if World Builder cannot yet provide
stable spatial anchoring, keep Scene Understanding functional in
camera-relative coordinates and document the limitation.*

It cannot. World Builder produces poses **offline**, after a session,
through `build()` — there is no live pose, and the engine is not on the
live frame path at all. There is nothing to anchor to in real time.

So: positions are **normalised image coordinates plus a bearing**, and
the record says so. No world ids, no fabricated anchors, no import of
World Builder. The contract for a future upgrade already exists in
`CARTRIDGE-GROUNDWORK.md` §4 and is not pre-empted here.

---

## 7. Privacy

- **Nothing is persisted.** No store, no journal, no imagery. This is
  the strongest privacy posture available and it is free here, because
  the cartridge's purpose is a live answer.
- **No identity.** Anonymous track ids, session-scoped, meaningless
  across processes.
- **No face processing.** No detector exists on this platform anyway
  (established in Cartridge 1: this OpenCV build has no
  `CascadeClassifier`, `FaceDetectorYN` ships no model). Keypoints locate
  eyes and ears as anonymous landmarks; they produce no descriptor and
  support no matching.
- **Raw pixels are ephemeral**, held only for the frame being processed.
- The descriptor declares `persists_data=False`,
  `retains_raw_imagery=False`.

---

## 8. Deliverables

1. `tower/scene/` — detector seam, tracker, scene state, relationships,
   optional orientation, query layer.
2. A `FixedDetector` so pipeline tests are fast, offline and asserted
   against **injected** ground truth (boxes we chose, so counts and
   relations are known independently).
3. `scripts/scene_session.py` — drive a capture, live or recorded.
4. `scripts/scene_query.py` — the questions, answerable from a CLI.
5. Benchmarks: per-frame cost with and without orientation, tracker
   behaviour under simulated detector dropout.
6. Architecture-boundary tests.
7. `guidelines/docs/modules/SCENE-UNDERSTANDING.md` and a report.

## 9. Definition of done

Counts come from tracks and are stable under detector dropout, proven by
test; every implemented relationship is asserted against geometry the
test chose; every refused relationship is documented with the evidence it
would need; orientation is off by default with its cost recorded and is
never called gaze; nothing is persisted; no cartridge is imported;
adversarial review completed and findings fixed; committed clean.

**Explicitly out of scope:** detection accuracy on real people. There is
no imagery of people anywhere on this host, so the detector's real-world
behaviour is unvalidated and the report must say so.
