# Object Memory × World Builder — spatial context, and the smallest honest slice

**Status:** RESEARCH + PLAN. Written 2026-08-25 on `main` @ `35214a1`.
Nothing here is implemented. Every section is marked EXISTS or PROPOSED.

**The question:** "Where did I leave my keys?" — how should Object Memory
use World Builder as spatial context, and what is the smallest honest
first slice?

**The short answer:** the honest first slice contains no geometry at all.
It is a *temporal and co-observation* claim joined to World Builder's
*tracking-continuity* segments through `source_seq` — a frame identity
owned by shared transport, not by either cartridge. The join is computed
at query time and never persisted. No pose, no distance, no direction, no
room. Sections 6–8 specify it; §9 says what I would refuse to build.

There is also a finding that changes the framing of the whole question,
and it is not about geometry. See §2.

---

## 1. The five constraints this design is built inside

These are not caveats. They are the shape of the problem, and a plan that
designs around them is a plan for a different system.

### 1.1 Scale is `unknown` or `relative`. Never metric. (EXISTS)

`SCALE_STATES_ALLOWING_METRES = (SCALE_MEASURED,)` —
`tower/world_builder/schema.py:85`. `format_distance` is the one function
that turns a number into human text and it refuses:

```python
if scale.allows_metres and scale.meters_per_unit is not None:
    return f"{value * scale.meters_per_unit:.3f} m"
return f"{value:.3f} world units"
```
— `tower/world_builder/records.py:93-95`

`SCALE_ESTIMATED` is defined at `schema.py:79` and referenced nowhere else;
`SCALE_MEASURED` is only ever *defended against*, never written; both
backends declare `produces_metric_scale=False`
(`docs/agent-handoffs/WORLD-BUILDER.md:108-121`). "Your keys are 2 metres
away" is not a hard feature — it is unreachable, and any phrasing that
implies it is a fabrication.

**A consequence worth stating positively, because it is the one door
`relative` scale leaves open:** an arbitrary but internally consistent
unit licenses *comparisons and ratios*, not magnitudes. "The keys were
seen from a point closer to the sofa than to the door" is scale-free and
survives `relative`. "2 m" does not. That distinction is the whole
vocabulary budget geometry ever buys us in V1 (see §5, Stage 2).

### 1.2 More than one segment means no shared coordinate frame. (EXISTS)

`Keyframe.segment_index` — `tower/world_builder/records.py:433-436`:

> Segment, not "submap": a segment break means tracking was lost, so
> poses either side are NOT in a common frame.

A world with more than one segment stays `SCALE_UNKNOWN`
(`WORLD-BUILDER.md:117-119`). The measured reality: the first physical
walk produced **36 segments over 1395 frames**, 155 keyframes, 10 of them
alone in a segment (`WORLD-BUILDER.md:236-244`). The 2026-08-24 keyframe
retuning brings a comparable walk to **20 segments, 260 keyframes, 4
single-keyframe segments** (`WORLD-BUILDER.md:263-268`). Segments have
independent origins and independent arbitrary units.

**Any spatial claim spanning a segment boundary is fiction.** With ~20
segments per walk, the *default* case is that two observations in one
session are in different frames.

### 1.3 There are no camera poses at all until calibration. (EXISTS)

`INTRINSICS_SOURCE_UNKNOWN` is the honest V1 value, and there is
deliberately no value meaning "guessed": the published 100° Ray-Ban FOV
describes a 3:4 still while the stream is 9:16 through an undocumented
crop, so no legitimate conversion exists — `schema.py:87-94`.

The 2026-08-24 walk therefore **solved 0 poses and 0 points**: "intrinsics
unknown → unposed backend → 0 solved poses" (`WORLD-BUILDER.md:276-277`).
`DEGENERACY_NO_INTRINSICS` (`schema.py:71`) is the recorded reason.

`scripts/calibrate_charuco.py` EXISTS and **has never seen a printed
board** (`WORLD-BUILDER.md:232-233`). At the time of writing there is no
`docs/CALIBRATION.md` anywhere in the tree — `find . -iname "CALIBRATION*"`
returns nothing. It is in flight; this document assumes only that the
procedure will exist, not that it will work.

### 1.4 Cartridges must not import each other. (EXISTS, and asymmetric)

- `test_shared_code_does_not_import_a_cartridge` —
  `tests/test_architecture_boundaries.py:34-51`
- `test_the_result_channel_core_is_cartridge_blind` — `:79-105`
- `test_a_cartridge_does_not_import_another_cartridge` — `:151-164`

**A gap worth naming.** `:151-164` scans `tower/world_builder/**` for
imports of `object_memory`. It checks **one direction only**. Document
Memory and Scene Understanding each have a both-ways rule
(`:373-395`, `:446-469`); Object Memory does not. Nothing today stops
`tower/object_memory/*.py` importing `tower.world_builder`. §8 proposes
closing that before any of this work starts, precisely because this
document is the first thing that would want to.

Note also the scan root: `TOWER = pathlib.Path("tower")`
(`test_architecture_boundaries.py:12`). `scripts/` is **not** scanned by
any of these rules. That is not a loophole to exploit silently — it is the
sanctioned composition layer, and §7 argues why it is the right boundary.

### 1.5 Privacy: a keyframe is retained imagery, and a crop is a new decision. (EXISTS)

`Session.retains_raw_imagery: bool = True` and
`privacy_tags = ("raw-imagery", "first-person")` —
`tower/world_builder/records.py:338-341`. Redaction is recorded as a
**process** claim, `faces-detected-and-filled/yunet-2023mar@0.30`, never
"redacted" or "privacy-safe", because YuNet has measured false negatives
on faces occluded past ~60% and rotated ~90°
(`WORLD-BUILDER.md:142-147`). `retains_raw_imagery` stays true after
redaction.

Object Memory's descriptor is planned as `retains_raw_imagery=False`
(first-slice plan, PLAN:1101-1107), and its shipped data layer honours
that: "Derived data only: no crops, no frames, no embeddings. The only
spatial data is a `bounding_box` of floats"
(`guidelines/docs/reports/2026-08-21-object-memory-tasks-1-3-report.md:45-46`).

**Storing an object crop would flip that flag.** `06-PRIVACY-DATA.md:81`:
"Selected crops or 'reduced' imagery are not inherently safe: a cropped
image can still contain a bystander's face, a private room, or a
document." This document treats a crop as a retention decision requiring
its own justification, and declines it (§9).

---

## 2. The finding that reframes the question: the detector cannot see keys

`ssdlite320_mobilenet_v3_large` with `COCO_V1` weights is the detector
that exists — `tower/experiments/object_detection.py:58-65`, and the same
weights in the shipped Scene Understanding cartridge,
`tower/scene/detect.py:134-141`. Its label set is
`weights.meta["categories"]`, the COCO classes.

**COCO has no `keys`.** It has no `wallet`, no `charger`, no `glasses`, no
`remote control`* — of the four example questions in
`guidelines/docs/modules/OBJECT-MEMORY.md` ("keys", "backpack", "charger",
"water bottle"), COCO covers **`backpack` and `bottle`**. Two of four.

\* COCO does have `remote`. The point stands for keys, wallet and charger.

And the shipped test fixture uses `object_class="keys"` —
`tests/test_object_memory_records.py:14`. That is fine as a string in a
data-layer test, but it means the canonical example question in the spec
is currently unanswerable by the only detector in the repository, and
nothing in the tree says so.

**VERIFICATION REQUIRED.** I could not enumerate the categories in this
environment: `torchvision` is an optional `[ml]` extra
(`tests/test_architecture_boundaries.py:349-370` exists to keep it
optional) and is not installed in `.venv`. The claim above is from the
published COCO-80 label set, not from `weights.meta` on this host. **Step
0 of any implementation is to print `weights.meta["categories"]` and paste
it into this document.** If it disagrees with me, this section is wrong
and the rest of the plan is unaffected.

**Why this matters more than the geometry.** The hard part of "where did I
leave my keys" was never the *where*. It is the *keys*. A COCO detector
answers "where did I leave my backpack" and refuses "keys" at the label
layer, long before any spatial question arises. Instance identity ("*my*
keys" vs "keys") is a second, separate wall
(`OBJECT-MEMORY.md`, Identity vs. Category). A spatial-context plan that
does not say this out loud is answering the easy third of the question.

**This does not invalidate the work below.** Substituting `backpack` for
`keys` costs nothing and keeps every claim true. But the honest headline
is: *the first slice answers "where did I leave my backpack", and says so.*

---

## 3. What is possible today, with zero new spatial machinery

### 3.1 What each side actually holds

**Object Memory** (EXISTS, `tower/object_memory/records.py:31-45`, 15
fields): `object_class`, `detector_score`, `confidence` (a persisted
*label*, never recomputed — records.py:3-10 + tasks-1-3 report:35-38),
`observed_at`, `time_basis` (always `"tower-receipt"` — there is no
capture timestamp on the wire), `recorded_at`, `source`, `module_id`,
`session_id`, `frame_seq`, `bounding_box`, `retention_tag`,
`privacy_tags`, `spatial_ref` (typed literally `None`), `external_refs`
(typed `tuple[()]`).

Deliberately absent: any tracker, any embedding, any crop, any soft-delete
flag, any position. `spatial_ref` is not merely unused — it is *actively
nulled on read*: `object_observation_from_json_dict` hardcodes
`spatial_ref=None` (`records.py:88`). A value written there today would be
silently discarded on the next read. (The *file* preserves it: rewrites
operate on raw dicts precisely so unknown keys survive —
`store.py:26-33`, and `test_prune_expired_preserves_unknown_extra_key`,
`tests/test_object_memory_store.py:258`.)

**Nothing produces an observation yet.** Tasks 4–8 of
`docs/superpowers/plans/2026-08-20-object-memory-first-slice.md` are
blocked at an open decision gate requiring a user ruling (PLAN:22-24,
826-896).

**World Builder**, per keyframe (EXISTS,
`tower/world_builder/inspect.py:125-171` — `WorldView.trajectory`):
`keyframe_id`, `source_seq`, `segment_index`, `image_relpath`, pose
`status`, `degeneracy`, and `pose` (which is `None` unless
`POSE_STATUS_SOLVED`/`ANCHOR` *and* a translation exists — `:148-152`).
Per session: `capture_id`, `intrinsics.source`, `redaction`,
`retains_raw_imagery`, `rejected_by_reason`
(`world_builder/records.py:316-351`).

**The keyframe record is deliberately pose-free** (`records.py:407-417`):
poses are derived and change whenever the mapper changes. `segment_index`
is *not* derived from geometry — it comes from `FrameTracker` losing
tracking, which is why the 2026-08-24 walk has 36 segments and 0 poses
simultaneously.

### 3.2 The join key, and why it costs nothing

Both cartridges read the **same capture journal**, written by shared
infrastructure. Each frame record carries
`{source_seq, wire_seq, tx_seq, received_at, time_basis, relpath, ...}` —
`tower/capture.py:243-256` — and `CaptureFollower` hands it back as
`FollowedFrame` (`capture.py:439-451`). `scripts/scene_session.py:117-125`
and `scripts/world_build_session.py:223-232` both consume it this way.

So: `(capture_id, source_seq)` identifies a frame, is owned by
`tower/capture.py`, and is already recorded on the World Builder side
(`Keyframe.source_seq`, `records.py:423`; `Session.capture_id`,
`records.py:327`).

**This is the whole integration.** Two cartridges agreeing on a frame
identity that a third, shared component defines is not cross-cartridge
coupling. It is the same posture as `Confidence`, promoted to
`tower/confidence.py` when World Builder became a second consumer
(`object_memory/records.py:3-10`).

### 3.3 The claims reachable today

With **no world at all**, from Object Memory alone:

> "I last saw a backpack 41 minutes ago (by Tower receipt time — the
> glasses send no capture timestamp). I saw a laptop and a chair within a
> minute either side of it."

Temporal + co-observation. Both are facts about the observation journal.
Neither touches geometry, poses, intrinsics or scale.

With a **built world over the same capture**, adding the segment:

> "...and that was in one unbroken stretch of tracking — the same stretch
> in which I also saw a couch and a television. I cannot tell you where
> that stretch was."

`segment_index` is a **tracking-continuity interval**, available with zero
solved poses. That is what makes it the one spatial-ish fact that survives
the pre-calibration state.

### 3.4 Is that the honest first slice? Yes — with one honesty tax

**Argument for.** It answers the shape of the real question ("when, and
what else was around") using only recorded facts; it needs no calibration,
no poses, no scale, and no new spatial machinery; every additional
capability in §4 strictly extends it rather than replacing it; and it
forces the query surface, the refusal type and the boundary to be designed
now, while they are cheap.

**The honesty tax, stated plainly: a segment is not a room.** Segment
breaks are caused by blur and track decay, not by doorways. Measured: 77%
of `blurred` rejections occur when `survival_ratio` is already below 0.15
(`WORLD-BUILDER.md:248-249`), and 4 of 20 segments in the retuned walk
contain a single keyframe (`:265-266`). A single-keyframe segment is a
stumble, not a place.

Worse, **segment indices are not stable across rebuilds**. The same
1395-frame walk yields 36, 40, 43, 49 or 20 segments depending on
`min_overlap_ratio` / `min_survival_ratio` / `loss_survival_ratio`
(`WORLD-BUILDER.md:250-268`). `frame_revision` is a constant 1 and cannot
be used as a change marker (`:317`), so a rebuild silently renumbers
segments with no detectable signal.

**Both facts drive the design, not just the prose:** the vocabulary must
say "stretch of tracking", never "room"; and the segment must be derived
at query time from the current world, **never persisted into an
observation record**. §6 makes both structural.

---

## 4. What each additional capability unlocks, in dependency order

| # | Capability | Prerequisite | Unlocks | Cost / risk |
|---|---|---|---|---|
| 0 | **Segment context** (§3.3) | A built world over the same capture | "same unbroken stretch of tracking" | ~0. Existing data. |
| 1 | **Calibration** | A printed ChArUco board + a procedure that has never been run (`WORLD-BUILDER.md:232-233`) | Nothing on its own. It is the gate. | Physical. Unknown whether the Ray-Ban optics/crop admit a stable pinhole fit at all. |
| 2 | **Poses within one segment** (`scale=relative`) | 1, plus enough parallax | Ordering along a path; *comparative* proximity within a segment; a bearing from a bounding box | Forward walking solves ~half the poses of sidestepping (`WORLD-BUILDER.md:71-81`). The cheirality gate refuses real 4–6 cm strafes as `pure_rotation` (`:95-99`). Re-deriving that gate is named as the highest-value outstanding geometry work. |
| 3 | **Fewer, longer segments** | 1 + 2 + a second walk to confirm the retuned constants | Claims that hold over minutes rather than seconds | +68% keyframes, unbudgeted for storage, for 20.5 ms/keyframe of redaction, and for build time (`WORLD-BUILDER.md:270-275`). |
| 4 | **Revisit detection** (appearance-only: "this looks like somewhere I have been") | None of 1–3, actually — this is bag-of-words over keyframe imagery | "the place you were in this morning" — a *sameness* claim with no geometry | New machinery, and it belongs in World Builder, not here. |
| 5 | **Multi-segment relocalisation / loop closure** | 1, 2, 4 | One coordinate frame per world; "near the sofa" across a whole walk | Not merely missing — `CARTRIDGE-GROUNDWORK.md §4` lists relocalisation and loop closure as "still missing". No covisibility graph: the observation graph is a chain, and BA measured **0.00% drift improvement** at 16/32/104 keyframes (`WORLD-BUILDER.md:302-308`). Add covisibility before anything else. |
| 6 | **Metric scale** | A measured baseline, an object of known size, or another sensor | Metres | **Out of V1 by declaration**, not by effort. §1.1. |

**The trap at step 5, and why it must be paid for at step 0.** A loop
closure that re-anchors one submap moves *part* of the world, not all of
it. `schema.py:96-111`: a coordinate stamped revision R can be brought
current only if **every** entry from R to HEAD is `GLOBAL_SIM3`;
otherwise it must be re-resolved from its anchor keyframe or reported as
unknown — never composed anyway.

Hence `CARTRIDGE-GROUNDWORK.md §4`'s standing requirement, which
`OBJECT-MEMORY.md` repeats:

> **Additionally required, and NOT yet in Object Memory's schema:**
> `anchor_keyframe_id` plus `position_in_anchor_frame`. Without them the
> first loop closure permanently and undetectably invalidates every
> earlier anchor... Add them **before** any anchor exists.

The first slice below writes **no anchor at all**, which satisfies this
requirement by construction and defers the schema addition to the pass
that actually needs it — with the requirement carried forward in §10.

---

## 5. The honest vocabulary, stage by stage

Literal sentences. What Object Memory may say, and when.

### Stage 0 — today (no world, or a world with no poses)

Reachable:
- "I last observed a backpack **41 minutes ago**." *(Add: "by Tower receipt
  time — the glasses send no capture timestamp." `time_basis` exists for
  exactly this.)*
- "I have **no record** of observing a bottle." *(Never "you have no
  bottle." Core Principle 3.)*
- "Within a minute of that, I also observed a laptop and a chair."
- "In the same **unbroken stretch of tracking**, I also observed a couch."
- "I **cannot tell you where** it was."

Refused:
- Anything with a direction, a distance, a room, or a floor.
- "Your backpack **is** on the desk." Only ever "was last observed".

### Stage 1 — a world exists, still no poses

Adds only: the segment context above, plus honest provenance —
- "That stretch contains 14 keyframes; **no camera positions were solved
  for any of them**, because this Tower has no camera calibration."

That sentence is worth saying. It is the difference between "we don't
know" and "we never tried", which `inspect.py:6-11` names as the exact
conflation Rule 16 forbids.

### Stage 2 — calibrated, poses solved *within* a segment, `scale=relative`

Newly reachable — comparative and ordinal only:
- "Along that stretch, you passed the backpack **before** the couch."
- "The backpack was seen from a point **closer to** where you saw the
  couch than to where you saw the door." *(A ratio. Scale-free. Valid only
  inside one segment.)*
- "**Near the couch**" becomes reachable *here* — as a comparison, and only
  within one segment. This is the earliest point at which a
  landmark-relative phrase is not a lie.

Reachable but useless, and therefore banned by §9:
- "The backpack and the couch were seen from points **2.300 world units**
  apart." `format_distance` will print exactly this
  (`records.py:95`). It is honest and it means nothing to a person.

Still refused: metres, rooms, anything crossing a segment boundary.

### Stage 3 — relocalisation / loop closure

- "**In the space you walked through at 14:32**" — needs sameness across
  segments (§4 step 4 or 5), not metric scale.
- "Near the couch", now valid across a whole walk rather than one segment.

### Never in V1

- "Your keys are **2 metres to your left**." Requires `SCALE_MEASURED`,
  which no backend produces. Not a roadmap item — a declared impossibility.
- "Your keys are **in the kitchen**." Requires a place taxonomy nothing
  produces.
- "Your keys **are** anywhere." Present tense about an unobserved object is
  forbidden outright (`OBJECT-MEMORY.md`, Output; Core Principle 3).

---

## 6. PROPOSED — the smallest first slice

Name: **temporal and co-observation recall, with tracking-stretch
context.** Read-side only. Writes no anchor, persists no geometry, adds no
imagery.

Three parts. Part A is inside Object Memory. Part B is a composition
script. Part C is the boundary tests.

### 6.1 Part A — inside `tower/object_memory/` (imports no cartridge)

**A1. Rename `frame_seq` → `source_seq`, and add `capture_id`.**

`ObjectObservation.frame_seq` (`records.py:40`) is ambiguous: the wire
carries three sequence numbers and `Keyframe` records all three
(`world_builder/records.py:423, 431-432`). The join needs `source_seq`
specifically.

**Rename now or never.** The repository's own argument, from the sibling
field that had this exact problem:

> Renaming is free now and impossible once data exists.
> — `world_builder/records.py:452`

**Nothing has ever produced an observation** (`OBJECT-MEMORY.md`, Status;
tasks-1-3 report:25). There is no persisted data. The window is open and
closes the moment Task 6 ships.

Add `capture_id: str | None = None`. Both fields default to `None`;
`object_observation_from_json_dict` must read them with `.get()`, **not**
required-key access. The existing parser uses required-key access
deliberately (`records.py:80-84`), and a new required key would make every
older record a schema mismatch — which
`test_prune_expired_keeps_schema_mismatched_record_within_retention`
(`tests/test_object_memory_store.py:215`) exists to survive, but which
there is no reason to inflict.

**Do not populate `spatial_ref`.** It stays `None`, stays typed `None`,
and stays nulled on read. Populating it is the anchor work, and the anchor
work needs `anchor_keyframe_id` + `position_in_anchor_frame` first (§4).

**A2. A refusal-capable answer type** — `tower/object_memory/query.py`
(PROPOSED). Copy the shape both shipped cartridges converged on:
`scene.query.Answer` with `answered: bool` + `reason`
(`tower/scene/query.py:26-48`), and
`document_memory.retrieval.QueryResult` with `sufficient_evidence: bool`
+ `reason` (`tower/document_memory/retrieval.py:92-116`).

```
ObjectAnswer            # PROPOSED
    question: str
    answered: bool
    reason: str                 # why, in the caller's words
    observation: ObjectObservation | None
    co_observed: tuple[CoObservation, ...] = ()
    where: WhereContext | None = None      # filled by Part B only
```

`answered=False` plus a reason is a complete, correct response.

**A3. Two queries, both pure Object Memory:**

- `last_seen(object_class) -> ObjectAnswer` — wraps the existing
  `ObservationStore.last_seen` (`store.py:116`) in the answer type, and
  states `time_basis` in the reason.
- `co_observed(observation, window_seconds) -> tuple[CoObservation, ...]`
  — other classes recorded within ±N seconds **of the same `capture_id`**.
  Different-capture matches are excluded, not silently mixed.

`co_observed` is the load-bearing half of the slice and needs no World
Builder at all.

### 6.2 Part B — `scripts/object_where.py` (PROPOSED): the query-time join

```
.venv\Scripts\python.exe scripts/object_where.py --class backpack \
    --world-id <id> [--session-id <id>] [--max-seq-gap 30]
```

Algorithm:

1. `ObjectMemory.last_seen(class)`. If `answered=False`, print and stop.
2. If the observation has no `capture_id`/`source_seq` → **refuse**:
   "this observation predates frame identity; there is nothing to join on."
3. `open_world(root, world_id)` (`inspect.py:236`). For each session,
   `read_session(...).capture_id`. If **no** session's `capture_id` equals
   the observation's → **refuse**: "no world was built from the recording
   this observation came from."
4. `WorldView.trajectory(session_id)` (`inspect.py:125`). Find the
   keyframes bracketing `observation.source_seq`: the greatest
   `source_seq <= obs` (`before`) and the least `source_seq >= obs`
   (`after`).
5. **If `before` and `after` are in different segments → refuse.** The
   observation sits on a tracking break and its segment is genuinely
   ambiguous. Reason must name the break.
6. If `min(seq gap)` exceeds `--max-seq-gap` → refuse. The nearest
   keyframe is too far away in the stream to speak for this frame.
7. Otherwise report `WhereContext`:

```
WhereContext            # PROPOSED — constructed at query time, never stored
    world_id: str
    world_session_id: str
    segment_index: int
    anchor_keyframe_id: str       # the bracketing keyframe used
    source_seq_gap: int           # honesty: how far the join reached
    keyframes_in_segment: int
    poses_solved_in_segment: int  # 0 today, and it must say 0
    scale_state: str              # "unknown" today
    intrinsics_source: str        # "unknown" today
    frame_revision: int           # 1, and see §3.4 on why it is useless
    derived_at: float
    stability_note: str           # "segment indices change on rebuild"
```

8. Render. **The renderer never emits a distance.** In this slice
   `format_distance` is not called at all, because there is no number to
   format.

**Nothing is written.** No store, no file, no cache.

### 6.3 Part C — the tests that pin it

Boundary:
1. `test_object_memory_does_not_import_another_cartridge` — closes the
   missing direction at `tests/test_architecture_boundaries.py:151-164`.
   Both ways, matching `:373-395`.
2. `test_object_memory_persists_no_world_field` — assert the serialised
   dict from `to_json_dict()` has no `segment_index`, no `world_id`, no
   `pose`, no `keyframe_id`. This is the structural form of "derive at
   query time".

Refusal:
3. Observation with `capture_id=None` → `answered=False`, reason names the
   missing frame identity.
4. Observation whose `capture_id` matches no session → refused.
5. Observation bracketed by keyframes in **different segments** → refused,
   reason names the tracking break.
6. Observation whose nearest keyframe exceeds `--max-seq-gap` → refused.

Honesty:
7. `poses_solved_in_segment == 0` renders as "no camera positions were
   solved", never as an absent field and never as a distance. (`inspect.py`
   already models this: unknown prints `unknown`, never `0` — `:6-11`.)
8. **Vocabulary test**, in the spirit of
   `test_no_cartridge_claims_gaze_or_persistent_identity`
   (`test_architecture_boundaries.py:537-592`): the rendered answer must
   contain none of `" m"`, `"metre"`, `"meter"`, `"is at"`, `"currently"`,
   `"in the room"`, `"near the"`. Applied to the renderer's output over
   every fixture, not to source text.
9. **The instability test.** Build two synthetic worlds from the same
   frames under different keyframe constants; assert the same observation
   reports a *different* `segment_index`. This does not fail the feature —
   it pins that the value is query-time-derived and documents §3.4's
   instability as tested behaviour rather than prose.

Co-observation:
10. Co-observations from a different `capture_id` are excluded.
11. `co_observed` with an empty window returns `()` and the answer still
    has `answered=True` — nothing to add is not a failure.

Synthetic fixtures only. `tests/synthetic_scene.py` exists and gives exact
poses and intrinsics (`CARTRIDGE-GROUNDWORK.md §2`), though this slice
needs far less than that.

---

## 7. The boundary, and why it is the right one

**Object Memory persists `capture_id` and `source_seq`.** These are facts
about the wire, defined by `tower/capture.py:243-256`, owned by shared
transport, and equally available to any cartridge that follows a capture.
Recording them is not knowledge of World Builder — Document Memory already
records `capture_id` for its own reasons
(`document_memory/records.py:153`).

**Object Memory persists nothing about a world.** Not `world_id`, not
`segment_index`, not a pose. Two independent reasons:

1. *It would be wrong.* `segment_index` changes on rebuild with no
   detectable signal (§3.4). A persisted copy silently goes stale, which is
   the precise failure `schema.py:96-111` and `frame_revision` exist to
   prevent — and `frame_revision` cannot prevent it, because it is a
   constant 1 (`WORLD-BUILDER.md:317`).
2. *It is not needed.* The join is cheap and exact, and computing it fresh
   is always correct.

**The composition lives in `scripts/`.** `scripts/object_where.py` may
import `tower.object_memory` and `tower.world_builder.inspect`. It is
outside the import rules' scan root (`test_architecture_boundaries.py:12`)
— not as an evasion, but for the same reason
`tower/results/world_builder.py` is exempted at `:71-76`: *something* must
know both shapes or nothing composes, and the safe form is one file named
after the pairing, so the next pairing gets its own file and inherits none
of this one's assumptions.

**The precedent is already in the tree, and it is exact.** Document Memory
solved this question and shipped the answer:

> The spatial fields are **supplied by a caller or absent**. Nothing in
> this module derives them and this module must not import World Builder
> -- a test enforces that. `None` means unknown, which is not the same as
> "nowhere".
> — `tower/document_memory/records.py:134-138`

with `world_id` / `world_session_id` / `frame_revision` as constructor
arguments (`document_memory/engine.py:113-139`), a `--world-id` CLI flag
(`scripts/document_memory_session.py:94`), and two tests:
`test_no_spatial_anchor_is_invented` and
`test_a_supplied_anchor_is_carried_verbatim`
(`tests/test_document_memory_engine.py:176-202`).

**This proposal deliberately diverges from that precedent in one place,
and the divergence is the design.** Document Memory *stores* the supplied
`world_id`; this slice does not store even that. The difference is that a
`world_id` is opaque and permanent (`world_builder/records.py:32-35`),
whereas the thing Object Memory actually wants — the segment — is neither.
Storing an id whose *referent* is unstable is worse than not storing it.

**Not chosen, and why:**

- *A shared spatial service.* `2026-08-20-canonical-memory-architecture.md:38`
  forbids it now; the promotion trigger is two implemented memory modules
  with a concrete repeated need (`:99-101`). One join in one script is not
  that.
- *A World Builder query API for Object Memory to call.* Same coupling in a
  nicer coat, and it would put a cartridge-shaped requirement inside a
  cartridge.
- *Reporting this through the result channel* (`tower/results/`). That
  package is read-only reporting **to iOS**, and iOS has no consumer:
  "iOS links no 3D framework, has no pose schema, holds summary figures
  rather than arrays" (`WORLD-BUILDER.md:213-218`). Building a transport
  for a consumer that does not exist is the fabricated contract this
  project refuses.

---

## 8. Ordering, and what must happen first

This work sits **behind** the first-slice plan's open gate. Nothing here
can be tested end-to-end until something produces an observation, and
Tasks 4–8 are blocked on a user ruling (PLAN:22-24).

The parts that can and should happen now, in order:

| Step | What | Blocked by |
|---|---|---|
| 0 | Print `weights.meta["categories"]` and settle §2 | nothing |
| 1 | `test_object_memory_does_not_import_another_cartridge` | nothing |
| 2 | Rename `frame_seq` → `source_seq`, add `capture_id` (both `.get()`-defaulted) | nothing — and this expires the moment Task 6 ships |
| 3 | `ObjectAnswer` + `last_seen` + `co_observed` (Part A2/A3) | nothing |
| 4 | `scripts/object_where.py` + tests against synthetic worlds | 2, 3 |
| 5 | Run it against the 2026-08-24 walk | an observation producer, i.e. the Task 4 ruling |

Steps 0–4 are testable against synthetic fixtures with no detector, no
torch, and no hardware. Step 5 is where the plan learns whether a segment
is a useful unit to a person, and it cannot be faked.

---

## 9. What I would refuse to build

1. **Any distance or direction phrase before calibration.** There are no
   poses. A bounding box centroid is a position in *the image*, and
   rendering it as "to your left" converts a pixel coordinate into a claim
   about the world.
2. **Any distance phrase after calibration, in world units.** "2.300 world
   units" is honest and meaningless. A number a person cannot act on, in a
   sentence that sounds like a measurement, is worse than a refusal.
3. **Persisting `segment_index`, `world_id`, or any pose into an
   ObjectObservation.** §7.
4. **Persisting an object crop.** `06-PRIVACY-DATA.md:81`; it would flip
   `retains_raw_imagery` and import World Builder's entire redaction and
   retention posture for a feature nobody has asked for.
5. **Persisting a *pointer* to a World Builder keyframe image.** Tempting,
   because the pixels already exist and are already face-filtered, so it
   looks free. It is not: it creates a cross-namespace reference
   (`06-PRIVACY-DATA.md:43` — modules must not read another module's data
   without an explicit shared-data design), and it dangles when the world
   is purged, at which point Object Memory holds a reference to deleted
   imagery. A query-time `WhereContext` may *name* the keyframe id; the
   store may not hold a path.
6. **`spatial_ref` populated in this slice.** It requires
   `anchor_keyframe_id` + `position_in_anchor_frame` first
   (`CARTRIDGE-GROUNDWORK.md §4`), which requires an anchor, which requires
   poses.
7. **Any claim spanning a segment boundary.** §1.2. With ~20 segments per
   walk this refusal will fire often; that is the system being correct.
8. **Calling a segment a room, a place, or a location.** Not in output, not
   in a field name, not in a docstring.
9. **Instance identity — "*my* keys".** `OBJECT-MEMORY.md`: do not claim
   unique-object identity unless the implementation supports it.
10. **Persisting `person` observations.** Already escalated and undecided
    (tasks-1-3 report:108-110; PLAN:30-37). Note that co-observation makes
    this *sharper*, not softer: "who else was around when you last saw your
    backpack" is a materially different privacy object than a list of
    furniture, and the co-observation feature should ship with `person`
    excluded until there is a ruling.
11. **Wiring Object Memory as a live `Module`.** The Task 4 gate is a user
    decision (PLAN:828). This plan requires no wiring: `scripts/` is
    sufficient, exactly as it is for Document Memory and Scene
    Understanding.
12. **An LLM anywhere in the query path.** `OBJECT-MEMORY.md`, Query
    Layer: the history must be queryable independently of one.

---

## 10. Open questions I could not resolve from the repository

1. **Is a segment a useful unit to a person?** Unmeasured, and unmeasurable
   without a walk plus an observation producer. 20 segments over one walk
   in one room means the median "stretch of tracking" may be seconds long.
   If it is, §3.3's sentence is technically true and practically empty, and
   the honest first slice collapses back to co-observation alone. **This is
   the question that decides whether Part B is worth building**, and step 5
   of §8 is the only way to answer it.
2. **What is the right `--max-seq-gap`?** Keyframe density is ~1 in 5.4
   frames (260/1395, `WORLD-BUILDER.md:265`), but that is one walk. The
   default in §6.2 is a placeholder, not a tuned constant.
3. **Can two `CaptureFollower`s tail one capture concurrently?** Object
   Memory and World Builder would both want to. Following is read-only
   (`capture.py:453-`), so it ought to work, and the writer lock guards
   only the world store — but nothing tests it and nothing documents it.
4. **How does a caller find the world for a capture?** `Session.capture_id`
   exists (`world_builder/records.py:327`) but nothing indexes the reverse
   direction. §6.2 step 3 proposes scanning sessions, which is O(worlds ×
   sessions) and fine at V1 scale. Whether World Builder should offer a
   `world_for_capture()` lookup is a World Builder decision, not this one.
5. **Do the COCO categories match §2?** Unverified here; torchvision is not
   installed in this venv. Step 0.
6. **The `person` ruling** (§9.10) — still open, and co-observation raises
   its stakes.
7. **The Task 4 ruling** (PLAN:894-895) — still unrecorded, and everything
   downstream of an actual observation waits on it.
8. **Does the 2026-08-24 walk's capture still exist?** `data/captures/`
   holds ~10 capture directories and `data/world_builder/` is present but I
   did not confirm which capture is the 1395-frame walk, nor whether a
   built world for it survives. If it does, steps 0–4 could be exercised
   against real segment structure without a new walk.
9. **Would `Confidence.LOW` ever appear on a joined answer?** It cannot
   today: `RelevancePolicy.min_score` (0.5) equals `LOW_CONFIDENCE_MAX`
   (0.5), pinned by
   `test_default_min_score_means_persisted_confidence_is_never_low`
   (`tests/test_object_memory_relevance.py:136-145`). The two constants are
   silently coupled (PLAN:1710-1715); if `min_score` drops, low-confidence
   observations start reaching the query surface and the renderer needs to
   say so.
