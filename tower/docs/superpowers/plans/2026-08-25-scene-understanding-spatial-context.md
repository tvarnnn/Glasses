# Scene Understanding × World Builder spatial context — design study

**Status:** RESEARCH + PLAN. Written 2026-08-25 on `main` @ `35214a1`.
No code was changed to produce it.

**Marking convention used throughout.** `EXISTS` is something in this
repository today, with a citation. `PROPOSED` is something this document
argues for and nothing implements. `REFUSED` is something this document
argues against building. An unmarked claim is a citation of another
document's claim, not a new one.

Scene Understanding shipped 2026-08-22 (`tower/scene/`,
`guidelines/docs/reports/2026-08-22-scene-understanding-v1-report.md`).
It has had no substantive change since. Everything World Builder learned
on the 2026-08-24 physical walk arrived afterwards, and this is the first
document to ask what, if anything, that buys the live cartridge.

---

## 0. The constraints this design is built inside

These are not preferences. Each is settled elsewhere and cited; nothing
below may weaken one.

### 0.1 The privacy architecture is settled

The pipeline, in order, from `tower/world_builder/redaction.py:3-7`:

> raw sensor data → necessary ephemeral perception → derived structured
> information → privacy transformation → persistence

and the ordering rule at `redaction.py:16-20`: "**Before persistence, not
on read.** Redacting on the way out would leave the raw frames on disk
[…] That is a display filter, not a privacy transformation."

What that permits and forbids for this cartridge:

- Raw face pixels **may** be processed ephemerally in memory for
  non-identifying perception: anonymous person tracking, coarse
  head/face orientation, whether someone appears oriented generally
  toward the wearer. `06-PRIVACY-DATA.md:37-39` — "Prefer processing raw
  frames in memory and persisting only derived/structured data".
- Raw face imagery **must not** be persisted merely because perception
  used it.
- Persisted and displayed imagery is face-redacted by default
  (`redaction.py`, applied at `engine._persist_keyframe`, the single
  choke point every persisted pixel passes).
- Persist derived structured attributes only — anonymous track id,
  position, coarse orientation, confidence.
- **No identity recognition, ever.**

`06-PRIVACY-DATA.md:81`: "Selected crops or 'reduced' imagery are not
inherently safe: a cropped image can still contain a bystander's face, a
private room, or a document."

`06-PRIVACY-DATA.md:44-50` and `04-MODULE-SYSTEM.md:61-70`: every module
descriptor must declare what it persists, whether raw imagery is
persisted or only derived data, retention behaviour, whether it supports
purge, and whether data leaves the local system. Scene Understanding's
answer to all five is currently the shortest possible one, and §3 argues
for keeping it that way.

### 0.2 Conservative language is part of the contract

`IOS-to-Tower.md:430-444`, quoted exactly because the wording *is* the
contract:

> ### 4.2 Orientation — the wording is part of the contract
>
> **MISSING — TOWER NEEDED**, as body/head orientation relative to the
> camera: `unknown` / `towardCamera` / `awayFromCamera` / `acrossView`.
>
> **This is not gaze, and iOS will not present it as gaze.**
> `.towardCamera` reads **"Facing your direction"**. It does not read
> "Looking at you", "Watching you", or "Making eye contact", at any
> confidence, in any phrasing — a test asserts those words cannot
> appear. Limitation 8 is classified REQUIRES FUTURE HARDWARE/API: there
> is no eye tracking on the target glasses, so there is no gaze to
> report.
>
> **Please do not send a field named `gaze`, `looking_at`, or
> `attention`.** If the Tower ever computes something in that space, it
> needs to arrive named for what it actually measures.

EXISTS, and already honoured on the Tower side: the state is
`FACING_TOWARD = "toward_wearer"` (`tower/scene/records.py:32`), the
property is `appears_facing_wearer` (`records.py:136-138`), confidence
never reaches HIGH (`tower/scene/orientation.py:87-140`), and an
AST-level test bans `looking_at`, `gaze_direction`, `is_looking`,
`face_id`, `person_id` across every cartridge
(`tests/test_architecture_boundaries.py:537-548`) with `gaze`,
`attention` and `viewing_duration` added for the wire
(`tests/test_result_channel_isolation.py:250-266`).

**A reconciliation finding, PROPOSED as a correction.** Tower's four
facing states and iOS's four do not correspond one-to-one by name.
Tower: `unknown` / `toward_wearer` / `away_from_wearer` / `profile`
(`records.py:31-34`). iOS: `unknown` / `towardCamera` / `awayFromCamera`
/ `acrossView`. `profile` has no iOS case; `acrossView` is the case it
maps to. Any wire contract must send iOS's four, snake-cased —
`unknown` / `toward_camera` / `away_from_camera` / `across_view` — and
the mapping must be written down at the one place that does it, not
inferred at the decode site.

### 0.3 No metric scale

Same rule as World Builder: `unknown` or `relative` only. `relative`
means "internally consistent with an arbitrary unit fixed by whatever
baseline the first solved pair happened to have. It is **not** metric"
(`docs/agent-handoffs/WORLD-BUILDER.md:107-110`). `format_distance` is
the single choke point and refuses (`WORLD-BUILDER.md:119-120`).

`IOS-to-Tower.md:453`: a distance "must arrive with `WorldScaleSemantics`
[…] iOS will not render a `.relative` or unlabelled distance as metres."

Scene Understanding emits no distance at all today, which is the strongest
form of compliance. §6 keeps it that way.

### 0.4 No poses until calibration

The 2026-08-24 walk solved zero. The manifest, from
`docs/superpowers/specs/2026-08-25-world-builder-lifecycle-design.md:17-22`:

```json
{"backend_id": "unposed", "keyframes": 155, "poses_solved": 0,
 "poses_refused": 119, "points": 0, "segments": 36, "scale_state": "unknown"}
```

All 119 non-anchor pose rows carry `degeneracy: "no_intrinsics"`; the 36
"poses" were segment anchors — identity rotation, zero translation, all
at the same point
(`guidelines/docs/reports/2026-08-25-world-builder-lifecycle-run-report.md:23-35`).

**What works before calibration**, on real hardware, measured: frame
ingest, capture and reconnect lineage, keyframe selection, frame-to-frame
tracking, segmentation, and face redaction on the write path — 155
keyframes out of 1395 frames, one 122-second walk. Plus every per-keyframe
selection signal: `sharpness`, `feature_count`, `median_parallax_px`,
`overlap_ratio`, `survival_ratio`, `tracked_count`,
`homography_residual_px` (`tower/world_builder/records.py:437-451`),
each authoritative because it was measured against candidate frames that
were rejected and never persisted (`records.py:415-418`).

**What only works after calibration**: any pose, any point, any scale
state above `unknown`, any bearing in degrees, any triangulation-quality
measurement.
`docs/agent-handoffs/IOS-WORLD-BUILDER-INTEGRATION.md:189-199`: "**Do not
treat zeroes here as a bug to work around.**"

Calibration is genuinely blocked and no code change unblocks it honestly:
`calibrate_charuco.py` has never seen a printed board
(`WORLD-BUILDER.md:230-231`), and loosening its view requirements gives
287%–3787% fx error *while improving* reprojection RMS
(`specs/2026-08-25-world-builder-lifecycle-design.md:278-286`).

### 0.5 Multi-segment worlds share no coordinate frame

`records.py:433-435`: "Segment, not 'submap': a segment break means
tracking was lost, so poses either side are **NOT** in a common frame."

The 2026-08-24 walk fragmented into 36 segments, ten of them a single
keyframe. Tonight's keyframe-policy fix — `min_overlap_ratio` 0.45→0.75,
`min_survival_ratio` 0.35→0.20, `loss_survival_ratio` 0.15→0.05
(`tower/world_builder/keyframes.py:169-176`) — gives **20 segments, 260
keyframes, 4 single-keyframe segments** on a replay of that same walk.
That is roughly 20 segments on a real walk *after* the fix, from one
walk, one room, one wearer, one lighting condition
(`WORLD-BUILDER.md:263-276`).

`specs/2026-08-25-world-builder-lifecycle-design.md:86-93`: "Calibration
unlocks geometry; fragmentation would make that geometry a fragmented,
unscalable map."

**The consequence for this design is total.** Even with perfect
intrinsics tomorrow, a walk yields ~20 mutually incomparable coordinate
frames. There is no single space in which to place a chair.

### 0.6 Cartridges do not import each other

Enforced: `tests/test_architecture_boundaries.py:151`
(`test_a_cartridge_does_not_import_another_cartridge`) and `:446`
(`test_scene_understanding_does_not_import_another_cartridge`, which
names `world_builder`, `object_memory`, `document_memory` and
`tower.experiments` explicitly). Shared code may not import a cartridge
either (`:34`, `:527`).

The proposed boundary and its justification are §4.

### 0.7 The face detector's blind spots are inherited by any count

`docs/agent-handoffs/WORLD-BUILDER.md:143-148`: the session records
`faces-detected-and-filled/yunet-2023mar@0.30`, "Never 'redacted',
'anonymised' or 'privacy-safe' — the detector has measured false
negatives on faces occluded past ~60 % and rotated ~90°, and profile
views are a known blind spot."

Note also that `guidelines/docs/modules/SCENE-UNDERSTANDING.md:167-169`
is now **stale**: it says "No face processing. No face detector exists on
this platform anyway." That conclusion was corrected on 2026-08-23
(`guidelines/docs/reports/2026-08-22-cartridge-run-report.md:143`, commit
`b9ff841`): `cv2.FaceDetectorYN` is compiled into our OpenCV and needed
only a 227 KB weights file, and face redaction now ships. The *posture*
in that bullet is still correct for `tower/scene/` — it does no face
processing — but the *reason* given is false, and a false reason is the
kind of thing a successor builds on. PROPOSED: fix that bullet.
**DONE.** The Privacy section of `SCENE-UNDERSTANDING.md` now states the
posture as a decision rather than a limitation, names the vendored
`models/face_detection_yunet_2023mar.onnx` and its use in World Builder's
redaction path, and records that the original search was scoped to `cv2/`
and missed it. The iOS copy of the same document
(`ios/Glasses/Project_Overview_Steps/docs/modules/SCENE-UNDERSTANDING.md`)
is outside Tower's ownership and has NOT been checked.

The relevance here is §6's refusal: any claim about "how many people are
in this room" that leaned on a face detector would systematically
undercount exactly the people who are turned away or occluded — which is
most of a room.

---

## 1. What exists today, precisely

| Piece | File | What it computes |
|---|---|---|
| Detector seam | `tower/scene/detect.py:54-64` | `Detector` protocol; `ssdlite320` real impl, `FixedDetector` for tests. 13 COCO classes (`detect.py:37-51`) |
| Tracker | `tower/scene/tracking.py` | IoU-only association, maximum-cardinality matching, `min_iou=0.25`, `min_hits=3` consecutive, `max_misses=5` |
| Scene state | `tower/scene/state.py:77` | Confirmed tracks, relations, counts, frame size, detector, threshold |
| Positions | `state.py:139` `describe_position` | Normalised image coords, `view_offset`, `side`; refuses when the frame size is unknown |
| Relations | `state.py:188` `relate` | `left_of` / `right_of` / `higher_in_view` only, with an 8%-of-frame minimum separation |
| Refusal registry | `state.py:41` `REFUSED_RELATIONSHIPS` | `in_front_of`, `behind`, `on`, `inside`, `near`, `nearer_than_same_class`, each with the evidence that would settle it |
| Orientation | `tower/scene/orientation.py` | Coarse facing from COCO keypoint *visibility*; 43.4 ms/call on CUDA, 956.4 ms on CPU (2026-08-26 measurement; the 798 ms here was CPU-with-synthetic-input); off by default because CPU is the default device; every estimate carries its age; expires at 6.0 s |
| Query layer | `tower/scene/query.py` | `count`, `where_is`, `facing_wearer`, `relationships`, `why_not`; `Answer.answered=False` plus a reason is a complete response |
| Driver | `scripts/scene_session.py` | Separate process; `--frames`, `--follow-capture`, `--synthetic` |

**What it deliberately refuses**, and this is the module's best property:
six relationships, each with a named unblocker (`state.py:41-73`); a
count of anything but *confirmed tracks* (`query.py:59-89`); an answer to
the facing question when orientation never actually produced an estimate
(`query.py:131-149`); any position at all when the frame size is unknown
(`state.py:150-165`); and any persistence whatsoever
(`tests/test_architecture_boundaries.py:472`, which now bans `open`,
`write_text`, `imwrite`, `save`, `dump`, `mkdir` and eleven others, not
just the project's own helpers).

**What it does not have and this document will not give it:** a world
frame, a bearing in degrees, a distance, a motion model, cross-session
identity, or a store.

---

## 2. The three questions

For each: what is answerable today, what World Builder context changes,
what is not answerable at all. The "literal honest sentence" is the one a
consumer may render; anything stronger is a fabrication.

### 2.1 "How many people are in this room?"

**Answerable today:** how many people are confirmed-tracked in the
camera's current field of view. `SceneQuery.count("person")`
(`query.py:59`) returns an integer from confirmed tracks, not detections,
and it is stable under detector dropout — modal 2 with fraction-correct
1.000 at 0%, 10% and 20% dropout, 0.939 at 40%
(`SCENE-UNDERSTANDING.md:62-67`).

**Literal honest sentence:**

> Two people are currently tracked in the camera's field of view. That is
> not a count of the room: the glasses observe a forward cone, and
> someone occluded or out of frame is simply not seen.

The second sentence is not decoration. `IOS-to-Tower.md:461-464`: "What
the **Tower** must not do is present a count as a statement about the
room. Zero means zero currently tracked **within the camera's field of
view**."

**What World Builder context changes: nothing about the number.** It
changes what the number may be *compared to*. Two counts taken in
different segments are two observations of two viewpoints that share no
frame; World Builder is the only thing in the system that knows a segment
boundary happened. That lets the answer say "these two counts are not
comparable" instead of leaving a consumer to add them.

**Not answerable at all**, and no amount of World Builder work changes
it:

> How many people are in this room.

Three independent blockers, any one of which is sufficient. (a) There is
no concept of a *room* anywhere in this system — World Builder produces
segments, not places, and a segment is "tracking was continuous here",
not "this is one space". (b) Counting a room requires accumulating
observations over time, which is Environmental Memory and requires
persistence this cartridge must not have. (c) A forward cone cannot
observe absence behind it, and `IOS-to-Tower.md:466-473` forbids even
implying it: "an entity at 150° cannot be a camera observation, and a
phrase like 'Behind you, right' would tell the wearer the system had
detected someone behind them."

And even with all three solved, §0.7 applies: any person-finding claim
inherits its detector's blind spots.

### 2.2 "Where is the chair?"

**Answerable today:** where a confirmed chair sits *in the current view*.
`SceneQuery.where_is("chair")` (`query.py:93`) returns normalised image
coordinates, a `view_offset`, and a side of `left` / `centre` / `right`,
every one stamped `frame_of_reference: "camera"`. It refuses when there
is no confirmed chair in view, with the reason "That is a statement about
what is currently visible, not about the room" (`query.py:100-103`).

**Literal honest sentence:**

> A chair is to your left in the current view. This is camera-relative:
> it will mean something different the moment you turn your head, and no
> distance is available.

**What World Builder context changes, today:** it can tell the answer
*when it stopped being true*. World Builder's front end already measures,
per frame, how much of the tracked structure survived and how much of the
image moved — `survival_ratio` and `overlap_ratio`
(`tower/world_builder/frontend.py:186-197`), `homography_residual_px`
("the median distance, in PIXELS, between where a homography fitted to
the tracks predicts each point should land and where it actually landed",
`records.py:447-451`), and the segment index that records a tracking
loss. None of those need intrinsics, poses, or scale. They are the
honest, available answer to "has the viewpoint this claim was made in
gone away?" — which is exactly what `IOS-to-Tower.md:494-500` asks for
when it distinguishes `observing` from `lastKnown`.

**What World Builder context would change after calibration:** a real
bearing in degrees. A bearing needs intrinsics and nothing else —
`IOS-to-Tower.md:451` is explicit that it is "Not gated by scale: a
bearing is an angle and needs no depth". Today `describe_position`
refuses to call `view_offset` an angle, correctly: "it assumes nothing
about focal length, and without intrinsics it cannot"
(`state.py:143-147`). With intrinsics it becomes one. This is the single
largest thing calibration buys this cartridge, and it is not a World
Builder feature — see §4.2.

**Not answerable at all:**

> The chair is 2 metres to your left. — No metric scale exists (§0.3).
>
> The chair is behind you. — Forward cone; `IOS-to-Tower.md:466-473`.
>
> The chair you saw in the kitchen is over there. — Requires a persisted
> world-anchored object across segments. There is no live pose
> (`state.py:1-7`), poses are produced offline and there are currently
> zero of them (§0.4), and ~20 segments share no frame (§0.5).
>
> The chair is in front of the desk. — REFUSED relationship, needs depth
> (`state.py:42-49`).

### 2.3 "What objects are around me?"

**Answerable today:** the confirmed track list, each with a class label
from 13 COCO categories (`detect.py:37-51`), a camera-relative side, and
`left_of` / `right_of` / `higher_in_view` relations between them
(`state.py:188`). Nothing else in this system enumerates objects.

**Literal honest sentence:**

> In view right now: one person, two chairs, a laptop. The laptop is to
> the right of the person and higher in the frame — which is a statement
> about the image, not about the room; something further away sits higher
> in frame without being higher in the room.

The `higher_in_view` caveat is load-bearing and is why the relation is
not named `above` (`records.py:41-43`, `state.py:216-220`).

**What World Builder context changes: nothing.** World Builder has no
object semantics at all. It has keyframes, ORB features, edges, poses and
points. It cannot tell you a chair is a chair.

**Not answerable at all:**

> What is around me. — "Around" is 360°; the sensor is a forward cone.
> iOS caps the vocabulary at `Ahead` / `To your left` / `To your right` /
> `At the edge of view` (`IOS-to-Tower.md:475-477`), and that ceiling is
> correct.
>
> What is in this room that I am not currently looking at. — Memory, not
> perception. Environmental Memory.
>
> Anything outside the 13 classes. — A COCO detector's world is 91
> categories and this cartridge reports 13 of them. Absence of a
> detection is never evidence of absence, and `query.py:84-87` says so on
> every count.

---

## 3. Persistence: keep it ephemeral

**Judgement: keep it ephemeral. Do not add a store to `tower/scene/`, in
any form, including a "volatile" or "purged-on-stop" one.**

This is a legitimate conclusion and here is the argument, because
`registry.py` names the absence of persistence as the blocker and the
tempting reading is that adding a store fixes it. It does not; it trades
a solved problem for an unsolved one.

### 3.1 Both sides have already declared it not wanted

`IOS-to-Tower.md:512-517`, §4.9 Persistence:

> **NOT REQUESTED.** This cartridge stores nothing, on either side, and
> its data-behavior declaration should say so: persists nothing, retains
> nothing, needs no purge because there is nothing to purge. If history
> is wanted, that is Object Memory and a separate privacy review.

And Tower-side, `docs/agent-handoffs/TOWER-TO-IOS.md:749-756`: giving
this cartridge a store "would pre-empt Environmental Memory's entire
reason to exist."

A store here would be built for no declared consumer on either machine.

### 3.2 What it would cost in privacy terms

The cost is not "a file appears". It is specific, and it is worse than it
first looks.

A per-frame track log — `{track_id, label, box, at}` — is a **movement
trace**. Anonymous track ids do not make it anonymous. Two tracks
co-present in a room across a session, with wall-clock timestamps and
relative positions, is a record of who was where and near whom, and
`IOS-to-Tower.md:423-425` already names the mechanism: "A handle that
survived sessions would be a re-identification key by function, whatever
it is made of." A durable trace is a re-identification *substrate* by the
same logic — not because the id is biometric, but because circumstance
is.

It would also drag in the whole declaration surface. Every module
descriptor must state what it persists, retention behaviour, and purge
support (`06-PRIVACY-DATA.md:44-50`), and purge must be *real* deletion
that reports what it could not delete, not hiding rows from a query
(`06-PRIVACY-DATA.md:64-66`). `tower/scene/`'s descriptor today is
`persists_data=False`, `retains_raw_imagery=False`, and the enforcement
is a test that fails if any write primitive is called
(`tests/test_architecture_boundaries.py:472-518`). That test is the
cheapest privacy control in this repository. Deleting it to enable a
feature nobody asked for is a bad trade at any price.

A "volatile" file is not an escape. A file containing person positions is
persistence whatever its retention promise, and "it gets deleted later"
is exactly the claim `06-PRIVACY-DATA.md:64-66` says must be *implemented
and verified* rather than asserted. World Builder already carries the
scar tissue for this: `images_purged_declared` is reported as a flag
precisely because Tower cannot verify it, and
`docs/contracts/CARTRIDGE-RESULTS.md` insists it never be rendered as
"the imagery is gone".

### 3.3 What the minimum record would be, if it ever changed

Stated so it is not invented badly under pressure later. If a durable
record is ever justified, it is **not** a per-frame track log. It is a
session-scoped, non-positional summary:

```json
{"schema_version": 1,
 "session_id": "...", "started_at": 0.0, "ended_at": 0.0,
 "time_basis": "tower-receipt",
 "detector": "ssdlite320", "score_threshold": 0.4,
 "orientation_enabled": false,
 "frames_observed": 1395,
 "max_concurrent_confirmed": {"person": 3, "chair": 2}}
```

No track ids. No boxes. No positions. No per-person facing. No per-frame
rows. That record answers "this session observed at most three people at
once" — a capability claim — and cannot be joined against anything to
reconstruct a path. It is the largest record that is not a trace.

And even that belongs in Environmental Memory's store, written by
Environmental Memory, not by `tower/scene/`.
`guidelines/docs/modules/CARTRIDGE-GROUNDWORK.md:150-158`: "Its boundary
with Scene Understanding is now real, not hypothetical. […] The day a
durable record of the physical world is wanted is the day this module
starts — not the day a store is added there."

---

## 4. The boundary: how Scene Understanding may consume World Builder

### 4.1 The rule, and why the obvious designs all break it

`tower/scene/` may not import `tower.world_builder`
(`tests/test_architecture_boundaries.py:446-470`). Nor may it read World
Builder's journals directly: `WorldStore` is named in the forbidden-call
list of the persists-nothing test (`:490`), and reading another
cartridge's record shapes is importing its implementation details by
another route — which `CLAUDE.md` forbids outright ("Never solve a
cross-system mismatch by importing implementation details across
subsystem boundaries").

Three designs were considered and two rejected:

| Design | Verdict |
|---|---|
| `tower/scene/` reads the world directory | REFUSED. Imports World Builder's record shapes; breaks two tests and the rule behind them |
| A shared `tower/spatial_context.py` that reads a world | REFUSED. Shared code may not import a cartridge (`:34`); moving the import one file up does not change what it is |
| A **seam** in `tower/scene/`, filled by an adapter in the **driver script** | PROPOSED. See below |

### 4.2 PROPOSED: the seam, and why it needs no exemption

`tower/scene/` already has two seams of exactly this shape: `Detector`
(`detect.py:54-64`) and `PoseEstimator` (`orientation.py:167-177`), both
Protocols, both with a `Fixed…` test double, both filled by
`scripts/scene_session.py`. A third follows the same pattern.

The boundary tests scope to `TOWER = pathlib.Path("tower")`
(`tests/test_architecture_boundaries.py:12`). `scripts/` is outside it.
So an adapter living in the driver script may legally know about both
cartridges, and needs no named exemption of the kind
`_RESULT_CHANNEL_ADAPTERS` (`:71-77`) had to grant. That is strictly
better than an exemption, and it is the same pattern `main.py` already
uses for World Builder: `_build_capture_worker_supervisor` is "the ONE
place in the web process that knows a world builder exists, and it knows
it as an argv — a script path and some flags — not as an import"
(`tower/main.py:67-77`).

**The value object carries only what World Builder can honestly supply,
and every field is nullable because "not established" is a real state:**

```python
# PROPOSED — tower/scene/spatial.py. Imports nothing outside
# tower/scene/ and tower/confidence.py.

@dataclass(frozen=True)
class SpatialContext:
    """What is known about the VIEWPOINT a scene was observed from.

    Never about where anything IS. This object cannot place a track in a
    world; it can only say whether two camera-relative claims were made
    from comparable viewpoints.
    """
    # Always "camera" today. There is no live world pose to anchor to.
    frame_of_reference: str = "camera"
    world_id: str | None = None
    segment_index: int | None = None
    # None = not established. Never False merely because we did not look.
    segment_changed: bool | None = None
    # "unknown" | "refused" | "anchor" | "solved". Never a pose.
    pose_status: str = "unknown"
    # "unknown" | "relative". Never metric, and never a number.
    scale_state: str = "unknown"
    source_seq: int | None = None
    age_seconds: float | None = None
    unavailable_reason: str | None = "no spatial context source is attached"
```

**What the seam deliberately does not carry:** a pose, a translation, a
rotation, a point cloud, a distance, a `meters_per_unit`, or a world
coordinate for any track. Not because they are hard, but because a
consumer that receives them will place a chair in a world, and §0.5 says
there is no world to place it in.

### 4.3 The one rule that makes this honest

> **Spatial context may only INVALIDATE a claim. It may never make one.**

Every use below is a use that *withdraws* confidence. None adds any. That
is what keeps a cartridge with no poses, no scale and no shared frame
from quietly acquiring the appearance of one.

### 4.4 The join key already exists

`scripts/scene_session.py --follow-capture DIR` and
`scripts/world_build_session.py --follow-capture DIR` read the *same
capture directory*, and both see `source_seq` — the capture recorder
stamps it into the journal and into the filename
(`tower/capture.py:225,247`), and World Builder persists it on every
keyframe (`tower/world_builder/records.py:422`). So a scene frame at
`source_seq = N` can be attributed to the segment of the nearest keyframe
at `source_seq ≤ N` with no fabrication and no shared clock.

This is a real, working join. It is also **unverified across a reconnect
lineage** — see §8.

### 4.5 A note on intrinsics, which are not World Builder's

`CARTRIDGE-GROUNDWORK.md:41` already says it: "Intrinsics are a
**platform** property, not a World Builder property. Every geometric
cartridge needs them and none should re-derive them." The code disagrees
with the doc — `CameraIntrinsics` lives at
`tower/world_builder/records.py:99`.

PROPOSED, and separable from everything else here: promote
`CameraIntrinsics` to `tower/intrinsics.py`, exactly as `Confidence` was
promoted out of `object_memory` once a second module needed it
(`tower/confidence.py:3-6`). It is a *vocabulary and value-type*
promotion, not a data-service promotion, so Rule 6 is untouched — the
same argument `confidence.py` already makes for itself.

That removes the need for Scene Understanding to ever ask World Builder
for a bearing. It asks the platform. This is the cleanest available
answer to "cartridges do not import each other": the shared thing was
never a cartridge's to begin with.

**Note, as of writing.** The working tree contains uncommitted work
adding `tower/world_builder/intrinsics_store.py` — a resolution-keyed
calibration store at `<world_root>/intrinsics/<width>x<height>.json`,
filed "Beside `worlds/`, not inside one. A calibration describes the
CAMERA, not a world and not a session". That reasoning is the same
argument this section makes, one level short of its conclusion: the
*data* is already declared camera-level and world-independent, while the
*code* still sits inside the cartridge. Nothing above depends on that
work landing, and the promotion stays a separate change — but whoever
picks it up should read that module's docstring first, because it has
already done most of the thinking.

---

## 5. The result-channel contract, and the blocker

### 5.1 The blocker as stated, taken apart

`tower/results/registry.py:70-77`:

> implemented on Tower as a live in-process state with no persistence;
> nothing in the web process observes it, so there is no state for this
> channel to read. See IOS-to-Tower.md 4

Two clauses. They have different truth values now.

**"nothing in the web process observes it" — no longer a law, as of
2026-08-25.** `CaptureWorkerSupervisor`
(`tower/capture_workers.py:81-98`) runs one worker process per capture
lineage and is "deliberately cartridge-blind. It knows how to run an argv
when a capture opens and how to stop it when the capture closes"
(`capture_workers.py:10-16`). `scripts/scene_session.py --follow-capture
{capture_dir}` is already the exact argv shape it wants. Two things stop
it: the supervisor holds a single `WorkerSpec`
(`capture_workers.py:100`), and a scene worker's output has nowhere to
go.

**"no persistence, so there is no state for this channel to read" — still
true, and the fix is not a store.** The result channel is by construction
"A READ-ONLY reporting surface over state other processes have already
persisted" (`tower/results/__init__.py:1-6`). Scene Understanding does
not fit it, and should not be made to fit it by acquiring a file (§3).

### 5.2 PROPOSED: correct the wording, offer no contract

The recommendation is **not** to move `scene_understanding` out of
`NOT_OFFERED`. It is to fix its reason, because the current wording
implies the blocker is persistence when the real blocker is the
live-module path, and a successor reading it will reach for a store.

PROPOSED replacement reason:

> implemented on Tower as a live in-process state that persists nothing,
> deliberately and by test. This channel reads persisted state, so there
> is nothing here for it to read — and giving this cartridge a store to
> make it publishable would pre-empt Environmental Memory. It needs the
> live-module path in TOWER-TO-IOS.md 6.1, not this one. See
> IOS-to-Tower.md 4.9, which does not request persistence on either side.

Nothing else in `registry.py` changes, and `declare()` keeps reporting it
in `not_offered` where "A client must not treat presence here as an offer
of anything" (`registry.py:48-52`).

### 5.3 What the contract WOULD look like, when the live path exists

Sketched now so it is not invented under deadline. `CARTRIDGE-RESULTS.md`
§9 says adding a cartridge costs one adapter file, one `make_snapshot_for`
branch, one `CartridgeOffer`, one contract id — and the envelope,
subscription, ordering, coalescing, reconnect and error machinery are
already generic.

- Contract id `scene_understanding.live/<date>`, opaque, compared for
  equality only (`tower/results/contracts.py:1-35`).
- `result_type: "live"`, not `"status"`. It is not a status.
- `snapshot_only: true`. Every message is a complete scene.
- Coalesced to **≤2 Hz** — `IOS-to-Tower.md:502-510`: "This is the
  cartridge whose real client will emit fastest […] a Tower-side rate
  that is already sensible saves both ends the work." The existing hub
  already coalesces at ~2 Hz.
- **No `counts` field.** `IOS-to-Tower.md:455-459`: iOS derives counts
  from the track list "so a header can never disagree with the rows
  beneath it." Send the list; let it count.
- **No imagery field at all**, so §5's `redacted` / `rawEphemeral` /
  `unknown` question never arises.
- Track: `{track_id, kind: "person"|"object", label: str|null,
  confidence, age_seconds}`. `label` is `null` for `kind: "person"` —
  `IOS-to-Tower.md:419`: iOS's `.person` case "carries **no payload at
  all** […] so there is nowhere for identity to be added without changing
  the type."
- Facing: `{state, confidence, age_seconds}` with `state` in
  `unknown` / `toward_camera` / `away_from_camera` / `across_view`
  (the mapping in §0.2). `age_seconds` is required, never omitted, and
  `null` means never measured — not zero.
- Position: `{frame_of_reference: "camera", side, view_offset,
  bearing_degrees: null, bearing_unavailable_reason: "..."}`. **The sign
  convention, stated as `IOS-to-Tower.md:451` demands: positive to the
  right, matching iOS.** `bearing_degrees` stays `null` until intrinsics
  exist; no distance field is present at all.
- The facing question travels as a refusal-capable answer:
  `{"answered": false, "reason": "..."}`. `TOWER-TO-IOS.md:775-782` is
  emphatic — "A wire that can carry `0` but not `answered: false` would
  turn a refusal into a confident, wrong zero at the boundary."
- Refusals shipped verbatim: `refused_relationships` and, for each, the
  `why_not` text. `IOS-to-Tower.md:481-489` wants the relationship
  vocabulary to stay the Tower's, displayed verbatim and never matched
  on.
- Banned on the wire, tested: `gaze`, `looking_at`, `attention`,
  `viewing_duration`, `is_looking`, `face_id`, `person_id`
  (`tests/test_result_channel_isolation.py:260-266`).

**What has to exist first**, in order:

1. Multi-consumer frame distribution or a second `WorkerSpec`.
   `ModuleContainer` is a registry of one and `CaptureWorkerSupervisor`
   takes one spec. `CARTRIDGE-GROUNDWORK.md:197-203` calls a second
   module id the V1.0 trigger; whether a second *worker* spec is the same
   trigger is genuinely unsettled (§8).
2. A live-result transport from a worker process to the web process that
   is **not** a file. Today the only cross-process channel is the
   filesystem, and §3 rules that out for this payload.
3. Frame metadata into modules — `Module.process()` takes only `bytes`
   (`TOWER-TO-IOS.md:634`), so `received_at` and `source_seq` are
   unavailable in-process.

None of those are this cartridge's to build, and none are on the critical
path for §6.

---

## 6. The smallest honest next slice

**One slice. No wire, no store, no new dependency, no new infrastructure.**

> Scene Understanding declares the viewpoint its camera-relative claims
> were made from, and marks when that viewpoint has gone away.

That is the only thing World Builder can honestly supply before
calibration, it fixes a real gap iOS has already asked about
(`IOS-to-Tower.md:494-500`, `observing` vs `lastKnown`), and it is
symmetric with machinery this module already has and already tests:
`age_estimate` (`orientation.py:143-164`) expires an orientation estimate
because it is old *in time*; this expires a position claim because it is
old *in viewpoint*.

### 6.1 Data shapes

**`tower/scene/spatial.py` (new).** `SpatialContext` as in §4.2, plus:

```python
class SpatialContextSource(Protocol):
    name: str
    def context(self, *, source_seq: int | None, at: float) -> SpatialContext: ...

class NoSpatialContext:
    """The default. Says it does not know, and says why."""
    name = "none"

class FixedSpatialContext:
    """A scripted sequence, for tests. Same role as FixedDetector."""
```

**`SceneEngine`** gains `spatial=None` and, in `observe()`, one call
wrapped in the same try/except discipline `_detect` already uses
(`engine.py:150-165`) — a failing context source must not end a session.

**`SceneState`** gains one field, rendered in `to_json_dict()`:

```json
"viewpoint": {
  "frame_of_reference": "camera",
  "world_id": null,
  "segment_index": 7,
  "comparable_across_segments": false,
  "scale_state": "unknown",
  "pose_status": "unknown",
  "revision": "a3f19c02",
  "age_seconds": 0.4,
  "unavailable_reason": null,
  "note": "two answers with different `revision` were made from different viewpoints and must not be compared"
}
```

`revision` is an **opaque token compared for equality only**, changing
when the viewpoint stops being comparable — the same design and the same
justification as the result channel's `revision`
(`tower/results/envelope.py:113-137`: "inequality is the entire
requirement"). It changes on a segment change. It is **`null`, not a
constant**, when no context source is attached: tri-state, matching the
`artifacts.present` precedent in `CARTRIDGE-RESULTS.md` where `null`
means "not established" and is never `false` merely because nobody
looked.

**No other field changes.** No position gains a distance. No track gains
a world coordinate. No relation gains a new predicate.

### 6.2 Boundary

- `tower/scene/spatial.py` imports `dataclasses`, `typing`, and
  `tower.confidence`. Nothing else.
- The adapter that fills a `SpatialContext` from a world directory lives
  in `scripts/scene_session.py`, behind new `--world-root` /
  `--world-id` flags, joining on `source_seq` (§4.4). `scripts/` is
  outside the boundary tests' scope, so no exemption is minted.
- Absent those flags, `NoSpatialContext` is used and every viewpoint
  field is `null` with `unavailable_reason` set. Today's behaviour is the
  default; nothing regresses.

### 6.3 Tests

New file `tests/test_scene_spatial_context.py`:

1. With no source attached, the scene declares the viewpoint
   unavailable with a reason, and `revision` is `null` — not a constant
   token, which would assert the camera had not moved.
2. A segment change changes `revision`.
3. A segment change does **not** change any count. People do not vanish
   because the camera turned; a test that lets them is the observation-gap
   error again.
4. A segment change does **not** move, delete or extrapolate a track.
   `IOS-to-Tower.md:499-500`: "A lost track should **disappear** rather
   than be extrapolated to a guessed position."
5. With `scale_state: "relative"` supplied, no position gains a distance
   field and no rendered string contains a unit.
6. With `pose_status: "solved"` supplied, no track gains a world
   coordinate. Solved poses are not permission to anchor while segments
   do not share a frame.
7. A context source that raises leaves the session running with the
   viewpoint unavailable — same shape as
   `test_a_failing_pose_estimator_does_not_end_the_session`
   (`tests/test_scene_orientation_staleness.py:175`).
8. A context older than a bound reports unavailable rather than the last
   value, and its age is clamped at zero — the same NTP-regression bug
   `age_estimate` already fixed
   (`tests/test_scene_tracker_hostile.py:212-224`).

Extended in `tests/test_architecture_boundaries.py`:

9. `tower/scene/spatial.py` imports no cartridge — covered by the
   existing `:446` test; add an explicit assertion so a future reader
   sees the intent.
10. `tower/scene/` still persists nothing — the existing `:472` test
    covers the new file automatically via `rglob`.

Extended in `tests/test_scene_cli.py`:

11. The driver with `--world-root` writes nothing into the world
    directory. Scene Understanding is a reader of a world, never a
    writer, and `TOWER-TO-IOS.md`'s "the Lab may read a world; it must
    never write one" applies here identically.

### 6.4 What this slice is worth, stated honestly

It adds no new answer. It adds a *fence* around the answers that exist,
and it is the largest honest thing available while `poses_solved` is 0
and segments number ~20. Its real value is that it makes the next step —
bearings, once intrinsics exist — a change to one function rather than a
new architecture, and it does so without minting a single claim the
sensor cannot support.

---

## 7. What I would refuse to build

Each with the evidence that would change the answer, in the style
`state.py:41` already established for relationships.

| Refused | Why, and what would settle it |
|---|---|
| A store in `tower/scene/`, including a volatile or purged-on-stop one | §3. Both sides declared persistence not requested; a per-frame track log is a movement trace; a deletion promise Tower cannot verify is not a control. Settled by: Environmental Memory starting, with its own privacy review — not by this cartridge |
| Any face embedding, descriptor, or appearance-based association | The tracker's IoU-only rule is a privacy decision: "matching by how something looks is the first step toward recognising it again" (`records.py:79-83`). Nothing settles this. It is the "no identity recognition, ever" constraint |
| Running YuNet in `tower/scene/` to improve person counts | It would systematically undercount the people who are turned away or occluded — measured false negatives past ~60% occlusion and ~90° rotation, profile views a known blind spot (`WORLD-BUILDER.md:143-148`). Tracking already handles the flicker this would be reaching for, better and at 33 ms. Nothing settles it; a better detector would be a different refusal |
| World-anchored track positions, before **or** after calibration | ~20 segments share no coordinate frame (§0.5). Settled by: loop closure or covisibility-based merging producing a single-segment world on a real walk — and BA already measured **0.00%** drift improvement on a chain graph, so "add covisibility first" (`WORLD-BUILDER.md:302-307`) |
| Any distance figure, in metres or in world units | §0.3. Settled by: a `measured` scale state, which is unreachable in V1 — both backends declare `produces_metric_scale=False` |
| A bearing in degrees before intrinsics exist | `state.py:143-147`. Settled by: a real ChArUco calibration at the delivered resolution, plus the intrinsics promotion in §4.5 |
| "Behind you" / "beside you" / any 360° scene | `IOS-to-Tower.md:466-479`. Settled by: a wide-angle or stitched field, "a change worth discussing rather than assuming" |
| Cross-segment track identity | A track id means "the same blob one frame later" (`records.py:155-158`). Across a segment break it does not even mean that. Nothing settles it — this is the identity prohibition, not a capability gap |
| Extrapolating a lost track to a guessed position using World Builder motion | `IOS-to-Tower.md:499-500`. A motion model is also unjustified: "neither is justified without a measurement showing greedy failing" — and the measurement that killed greedy produced a *matching* fix, not a prediction one |
| A `scene_understanding` result-channel offer backed by a file written for the purpose | §5.2. It would satisfy `registry.py` by defeating the property `registry.py` is describing |
| Depth-based relationships from MiDaS to unlock `in_front_of` | 6–8% temporal flicker; ordering by a flickering field inverts frame to frame (`state.py:42-49`). Settled by: the named depth experiment — two objects at a known separation, measure how often the ordering flips |

---

## 8. Open questions

1. **Does the `source_seq` join hold across a reconnect lineage?**
   `CaptureFollower` chains into a successor capture
   (`tower/capture.py:472-478`) and `CaptureWorkerSupervisor` runs one
   worker per lineage. Whether `source_seq` continues monotonically into
   the successor or restarts is not established here, and §4.4's join
   assumes it does. The 2026-08-24 evidence shows frames "continuing from
   the previous `seq`" (`WORLD-BUILDER.md:160-162`) but that is about the
   wire `seq`, not the capture's `source_seq`. **Verify before
   implementing §6.**

2. **Is a second `WorkerSpec` the V1.0 trigger?**
   `CARTRIDGE-GROUNDWORK.md:197-203` names a second *module id* as the
   trigger. `CaptureWorkerSupervisor` is not the module container and is
   cartridge-blind by construction, so a second spec may be a different
   and much cheaper thing. This is a roadmap ruling, not a code question.

3. **What threshold makes a viewpoint "no longer comparable"?**
   §6 changes `revision` on a segment change only, because that is the
   one signal with a measured meaning. Whether a sub-segment threshold on
   `homography_residual_px` or `survival_ratio` is also warranted is
   **unmeasured**, and inventing one now would be a constant with no
   evidence behind it. It needs a walk with a wearer turning
   deliberately.

4. **Does the keyframe-policy fix hold on a second walk?**
   `WORLD-BUILDER.md:268-276`: one walk, one room, one wearer, one
   lighting condition; +68% keyframes; the dominant promotion path
   shifted from parallax to track-decay with unmeasured effect on
   triangulation. If the segment count moves materially, §0.5's
   arithmetic moves with it — though not its conclusion, since 2 segments
   and 20 are equally "no shared frame".

5. **Detection accuracy on real people is still unvalidated.** There is
   no imagery of people anywhere on this host
   (`SCENE-UNDERSTANDING.md:191-193`). Every count number in every
   document about this cartridge measures the *pipeline*, never its
   accuracy on a room.

6. **Two stale statements found while writing this**, both worth
   correcting in place rather than leaving for a successor to build on:
   - `SCENE-UNDERSTANDING.md:167-169` — "No face detector exists on this
     platform anyway" was corrected on 2026-08-23 (§0.7). The posture is
     right, the reason is false. **FIXED** in the Tower copy; the iOS
     copy is not Tower's to change.
   - `2026-08-22-scene-understanding-v1-report.md:228-230` — the
     limitations list still says "Greedy IoU association", which §8.2 of
     the same report replaced with maximum-cardinality matching.

7. **An unreconciled measurement — RESOLVED 2026-08-26.** The plan
   recorded detection at 32 ms and keypoints at 744 ms
   (`docs/superpowers/plans/2026-08-22-scene-understanding-v1.md:107-110`);
   the report recorded 33 ms and 798 ms
   (`2026-08-22-scene-understanding-v1-report.md:96-99`); the code
   comments said 744 ms (`engine.py:7`, `orientation.py:25`). All three
   were CPU measurements on synthetic input that named no device, and all
   three were optimistic. Measured on 754 real corpus frames
   (`docs/superpowers/research/2026-08-26-scene-understanding-measurements.md`):
   **43.4 ms on CUDA, 956.4 ms on CPU**, detection **30.4 / 32.9 ms**,
   against a delivered frame interval of **83.5 ms**, not ~300 ms. The
   code, the module doc, the roadmap and the contract now all state the
   measured pair *with its device*, which is the variable none of the
   conflicting figures named and the reason they could conflict at all.
