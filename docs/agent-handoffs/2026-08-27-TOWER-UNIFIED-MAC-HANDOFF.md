# Mac handoff — the unified Tower, 2026-08-27

**Branch to build against:** `integration/tower-unified-cartridges-v1`
**Wire contract:** `docs/contracts/TOWER-UNIFIED-CARTRIDGES.md` — read that first; this document is what to *do*.
**Do not build against a lane branch.** Three of the four describe a Tower that no longer exists in isolation.

Four lanes were merged into one green branch. Five cartridges are live,
four are declared, and the shared runtime was reviewed by two independent
adversarial reviewers plus a final one. What follows is per cartridge:
what to build, what to decode, what will bite you, and what to test with
your hands.

**Every Tower-side identifier here was read off a running process on the
merged tree**, not quoted from a lane document. The four claims this
document makes about *your* side were checked against `ios/` as well,
read-only, on 2026-08-27:

| Claim | Verified |
|---|---|
| `transform_to_world` is never decoded | appears only in `GlassesTests/WorldGeometryTests.swift`, always as `null` — no production decoder reads it |
| the geometry cache is keyed on `contentHash` alone | `WorldBuilderClient.swift:324,332` — `retainOnly(Set(…contentHash))` and `chunk(forHash:)` |
| `TowerCapabilities.towerCartridgeNames` is the mapping you must extend | `Cartridges/Integration/CartridgeClient.swift:69` |
| there is no `frame_error` case | no match for `frame_error` anywhere in `ios/**/*.swift` |

`ios/` was **not modified** by this integration.

---

## 0. Start here — the five-minute pre-flight

Run this before writing a line of Swift. It starts its own Tower, so
there is nothing to configure and no chance of testing a stale process.

```
cd tower
.venv\Scripts\python.exe scripts\unified_cartridge_smoke.py
.venv\Scripts\python.exe scripts\unified_cartridge_smoke.py --with-models
```

Expect `all 56 checks passed` and `all 68 checks passed`. The second loads
torch and easyocr and is the only way to watch Scene's discard-on-stop and
Document's keep-on-stop actually happen.

**If either fails, stop.** Nothing below will work, and the fault is the
Tower's, not the phone's.

Then, against a Tower you started yourself:

```
curl http://<host>:8000/cartridges
curl http://<host>:8000/health
.venv\Scripts\python.exe scripts\cv_lab_smoke.py --host <host>
```

---

## 1. World Builder

### Build

Two HTTP routes, plus a status subscription on the socket:

```
GET /worlds/{world_id}/geometry/manifest
GET /worlds/{world_id}/geometry/segment/{segment_index}
result_subscribe world_builder / status
```

### Decode `transform_to_world`

A **Sim3**: `p_ref = scale * (R(q) · p_segment) + t`. Rotation is a
**wxyz quaternion**, not a matrix, so there is no row/column-major
question to get wrong. Translation is in the **reference segment's**
units — `translation_units` is `"world"`, **never metres**.

**`WorldGeometryDecoder.chunk` does not read this field today.** It is
absent from the decoder guard list and `WorldSegmentChunk` has nowhere to
put it, so a Tower emitting a Sim3 is silently dropped on the floor.
That is the first thing to add.

Three refusals to implement, not to soften:

- `transform_to_world: null` means **not registered**. It is **not**
  identity — treating it as identity places the segment at the reference
  origin and looks plausible.
- Segments with **different `reference_segment`s must not be
  composited.** Same reference, fine. Different, never.
- `registered: false` **forbids** placing two segments in one space.
  Their scales disagree by up to **~87×** on a real walk.
- `pose_convention` is compared **key by key** and a mismatch **refuses
  the render**. Compare `pose_type`, `quaternion_order`, `handedness`,
  `camera_axes`, `translation_units`. Exclude `up_axis` for a 2-D view.

### The cache trap — the one that is invisible if you get it wrong

**`WorldGeometryStore` is keyed on `contentHash` alone. It must become
`(contentHash, placementHash)`.**

`content_hash` covers **poses and points only**, deliberately, so a
segment that gains a placement keeps its content hash. Without the
placement half, the day a segment gains a placement the client keeps its
cached chunk forever and draws an **unplaced** version of a segment the
world now knows how to place. Nothing looks broken. The fragment simply
sits in the wrong place, permanently.

`placement_hash` includes `refusal_reason`, and that matters: on the real
corpus **26 of 29 segments are refused and share one `placement_hash`**,
so a re-registration that changed every refusal reason moved no hash.

> **The deliberate regression test:** change only a placement, same
> points. The client must refetch and re-place. Write this test first;
> it is the one that is invisible if you get it wrong.

### Unknown / relative scale

Two states are reachable and only two. **`unknown` must never be mapped
to `relative`** — it is a strictly weaker claim. `meters_per_unit: null`
**does not mean 1.0**. A world with more than one segment stays
`unknown`, and will stay `unknown`: segments do not share a coordinate
frame and calibration does not change that.

`distanceDisplayable` is **always false**. Render
`labelledFigureDisplayable` instead: "6.6 world units", with the unit
attached and "Shape and layout only. No real-world distances are
claimed." beneath it. **The gate is the unit, not the scale** — a bare
number is what a reader silently reads as metres.

### The wrong-basin caveat — carry this forward

**On roughly 2% of scenes the two-view solve lands in a second,
self-consistent basin about 90° from the truth, reports `solved`, and
looks healthy.** Measured 1 in 50 seeds; 865–925 matches, 527–870
inliers, deterministic across runs. There is a shipped test named
`test_no_pose_is_ever_confidently_wrong` and the failing seed is outside
its set.

**The gate that would catch it was measured and REJECTED**, and must not
be reintroduced without new evidence. The discriminator (cheirality
inliers over epipolar inliers) separates cleanly on synthetic scenes —
but on real footage there is a long low tail the synthetic scenes do not
have, and a gate near the synthetic separation point **refuses 17.1% of
currently-solved edges**. That trades **a measured 17% loss against an
unmeasured 2.5% gain**, on a corpus with no ground truth to settle it.

Whether this occurs on real Ray-Ban footage is **unknown, and the corpus
has no ground truth to detect it with. That is precisely why it is
dangerous: on real footage there is no way to notice.** PT-1 footage is
what would unlock it.

### PT-1 — the physical test that is worth more than the rest combined

Registration was **not auto-wired**, and the evidence is why: 2 of 8
captures register anything, registration costs 2.2× all replay+build, and
**135 of 141 refusals are `span_over_depth`** — "the wearer stood still",
cameras spanning 2–6% of scene depth. The binding constraint is the
capture, not the estimator.

**Procedure.** One walk, 2–4 minutes, in a room already walked so content
is comparable.

- Move **sideways** past furniture rather than pivoting on the spot.
  Strafing creates baseline; turning your head creates none.
- Keep a roughly constant distance from what you are looking at.
- Re-enter the same area **twice, at least 60 s apart**, for a genuine
  revisit.
- Avoid: standing still and panning; walking straight at a wall (the
  epipole sits in the image and parallax collapses); fast head turns.
- Rule of thumb: **the camera should travel at least its own distance to
  what it is looking at.** Table 2 m away → move 2 m.

**Measure** (read-only):
`world_registration.py --root <data>/world_builder --world <id> --format json`
Keep `segments_registered`, `points_registered`, `candidate_pairs`,
`admitted_pairs`, and the full refusal histogram.

**PASS:** `segments_registered` rises well above the current 3 of 51; the
`span_over_depth` share falls from 96% of refusals; **median span/depth
clears 0.05** on most pairs.
**FALSIFIED:** span/depth stays in the 0.02–0.06 band despite a
deliberate strafing walk. That is a far more serious finding and would
justify reopening whether monocular-only can ever register on this
hardware.

**PT-4 rides on the same footage and is the real product bar:** build the
world, render the registered geometry, and without being told which is
which, identify **at least three distinct pieces of furniture or
architecture from the point cloud alone.** "Points appeared" is not the
bar.

---

## 2. Object Memory

### Build

**Object Memory is not in `/cartridges`.** Reach it over HTTP; learn
nothing about it from the declaration. A `result_subscribe` for it is
refused `unknown_cartridge`, and that is intended (§9 of the contract).

```
GET  /cartridges/object_memory/session
POST /cartridges/object_memory/session/{start|pause|resume|stop}
GET  /object-memory/observations
GET  /object-memory/last-seen/{object_class}
GET  /object-memory/observations/{id}/imagery
GET  /object-memory/observations/{id}/frame
GET  /object-memory/observations/{id}/crop
```

### Session and shared capture

```
GET  session                 -> {state: "stopped", supported: true}
POST session/start           -> {state: "active",  changed: true}
GET  session                 -> {state: "active", following: ["<capture id>"]}
POST session/pause           -> {state: "paused"}
POST session/stop            -> {state: "stopped"}
```

- **Start is idempotent** and works from `paused` too. A second start is
  **200 with `changed: false`** — honoured, nothing moved. Not an error.
- **Resume from `stopped` is 409.** Use start.
- **Stop is never refused.**
- A Tower restart comes back **stopped**. Nothing is persisted.
- Start before the camera is legal: `attached_capture_id: null`, and the
  next capture to open finds the gate open.
- **Late attachment is a consent decision.** A wearer who starts
  remembering at 15:03 has not asked for the 15:00 part of the walk.

> **Render liveness from `following`, never from `state`.** Reproduced
> during this integration: a Pause whose producer ignores `SIGTERM`
> answers 200, `state: "paused"`, `changed: true` — while `following`
> still names the capture and the process is still recording. A Pause
> button keyed on `state` tells a person they stopped being recorded
> when they did not.

### Query and image retrieval

**Read `recorded_classes` off the payload.** It is configuration-
dependent: `["laptop", "cell phone"]` by default, twelve more with the
verifier on.

`retention` reports `requested_days`, `effective_days`, `clamped` and a
policy of `min(persisted, requested)` — **a reader may narrow and can
never widen.**

Imagery status codes, and what each must look like on screen:

| Code | `reason` | Render |
|---|---|---|
| 200 | `null` | the picture |
| **410** | `imagery-no-longer-available` | **"the memory is kept, the picture is gone"** — `memory_retained: true` is in the body. **Never a broken image or an empty row.** |
| 404 | `no-such-observation` | nothing matched within retention |
| 404 | `record-has-no-frame-reference` | the record never had a pointer |
| 503 | `display-filter-unavailable` | refuse. **Do not work around this.** |

`/imagery` answers **200 even when there is no picture**. Only an unknown
handle is a real 404 there. **Do not cache the bytes** —
`Cache-Control: no-store` is on the response.

### Privacy and filtering

The filter runs **on read**, so it is a **display filter**, never
"redaction", "anonymised" or "privacy-safe". A Tower with no weights
serves **nothing** — there is no lenient default, because the lenient
default here is a raw first-person frame.

`regions_filled: 0` means **nothing was detected**, not that nothing was
there. **`subject_obscured > 0` means a fill overlaps the object the
record is about** — the filter fires on 40.2% of real frames and of 36
firings inspected by eye only 4 were a real face. Say the subject is
behind a fill, or fall back to `/frame`.

Language rules, enforced by tests on the iOS side and worth mirroring:
**`observed`, never `present`. "a laptop", never "your laptop". Never
"still there", never "last seen in".** `recordable: false` means an
absence carries no information at all.

> A picture is a much stronger location cue than a sentence, and no
> string test can catch it. The caption carries the whole burden.
> **Test it on a person, cold. If the word "where" comes back, the
> caption is wrong.**

### Model and config state

The shipped stack: `ssdlite320_mobilenet_v3_large` detector (CPU by
default), plus an optional `google/owlv2-base-patch16-ensemble` verifier
that **ships OFF**. Do not surface a model picker; `recorded_classes` is
the only model-dependent thing a client should read.

### The 360×640 limitation, and the test that is owed

DAT delivers **360×640** and offers 504×896 and 720×1280, all 9:16, **no
landscape at any resolution.** The shipped detector has **0.000 recall
below 1% of frame area**, and the objects worth remembering — keys,
wallet, glasses, medication — live in that band. **Semantics added
downstream of a blind stage one produce a well-characterised memory of
laptops.**

**The 720×1280 test stays a physical experiment, not a global resolution
change.** Raising the stream is measured as actively harmful to World
Builder tracking (73.3% of frames fall below `min_sharpness` at 720p).
What is wanted is a way to request an **occasional higher-resolution
still**, or failing that a way to learn which rung of the adaptive ladder
is active. Somebody should measure that before more model work is built
on top of a blind stage one.

Note one coded consequence: the face filter's upscale is a cap on the
long side — exactly 2× at 360×640, **1.0 at DAT's 720×1280 maximum**.
Verified during this integration at both sizes; `subject_obscured` came
out 0.1266 vs 0.1262, so the cap is not costing detections at the ceiling.

---

## 3. Experimental CV Lab

### Build

**Advertised identifier is `experimental_cv`.** The phone-side catalog key
is `experimental-cv` with a hyphen and **must** be mapped via
`TowerCapabilities.towerCartridgeNames`. Without that entry nothing else
works.

```
GET /cv-lab                             (read)
socket cv_lab_status                    (read)
result_subscribe experimental_cv/status (read)
socket cv_lab_start | pause | resume | stop   (control)
```

**There is no HTTP surface for start, pause or stop.** Commands never
travel on the result channel.

### Experiment list, select, start

`status.available[]` is the catalog — eight experiments, sorted by `id`,
each with `available` and `unavailable_reason`. **There is no separate
select message**: `cv_lab_start` selects and arms in one step and
replaces whatever was running.

`request_id` is opaque, max 64 chars, echoed back; longer is **dropped,
not refused**. A stale `run_id` is refused `stale_run`.

**One Lab slot, shared by every connection.** Two phones streaming to one
Tower feed the *same* run. **Last start wins** — there is no ownership
model, because a bench with one slot and two operators has a social
problem, not a protocol one. `source.clients_connected` makes it visible.

Note the consequence, which bit us during this integration: **any
connection can pause the Lab.** It no longer starves the other cartridges
(fixed here), but it does stop *your* results.

### Provenance and stale-result invalidation

> **Discard any `frame_result` whose `cv_lab.run_id` is not the run you
> are watching.**

The Tower makes this structural: the old experiment is released **before**
the new run id is published, so no result can carry another's name.
`run_id` embeds `tower_instance_id`, so comparing `run_id` alone also
covers a reconnect to a restarted Tower. **Clear the held run id on
`sendStreamStop()` and on teardown.**

`result_seq` is dense within a run from 1. **The wire `seq` is the
phone's capture index and skips by design** — one frame in thirty — so it
cannot order results.

`confidence`, `baseline` and `higher_is_better` are **always null**.
Never render a better/worse verdict.

### `frame_error` — you must add a case

`TowerClient.handleInboundMessage` has **no `frame_error` case today**; it
falls to `default:` and logs. Add one. Six Lab reasons —
`cv_lab_idle`, `cv_lab_starting`, `cv_lab_paused`, `cv_lab_stopped`,
`cv_lab_failed`, `cv_lab_unavailable` — plus the transport's
`invalid_frame`, `frame_skipped`, `module_unavailable`.

`cv_lab_starting` is the **arming window**, bounded by the **120 s arm
timeout**, with **no progress reporting** (torch.hub offers none). Show
"arming", not an error.

### Terminal FAILED, truthfully

**There is no `start_failed` message.** An arm is asynchronous, so by the
time a load fails the command has already been answered `accepted`.

> **The outcome arrives as state.** A client that sends commands and does
> not also read status **will never learn that a start failed.**

A failed interactive start is recoverable. A failed **startup** experiment
is terminal until restart. **And note: the CV Lab refuses `cv_lab_stop`
from `failed`** — so a "Stop then Start" recovery path is refused on step
one. Send `cv_lab_start` directly.

### Debug vs Release

**A Release build has no camera, sends no frame, and receives no
`frame_result`.** That predates this work.

> **`.running` may be shown as LIVE only when this build is itself
> streaming AND `source.receiving_frames` is true.** Both halves.
> `source` is Tower-wide, so it is `true` for a Release build with no
> camera whenever a second phone is attached.

Never render a Start control where there is no `startCameraSession` to
call. On a build that never processed a frame the run publishes **`null`,
not zero** — a rate over a zero-length window is undefined.

### Smoke plan

`scripts/cv_lab_smoke.py` walks browse → start → frames → pause → resume →
stop → summary → refusals → subscription and **sends its own frames**, so
a failure is a Tower problem and never a phone problem.

With glasses, nine steps; the two that matter most:

- **Step 5:** blank wall vs cluttered desk on `edge_detection` —
  `edge_density` **~0.01–0.03 on the wall, 0.10–0.25 on the desk**, a
  ~10× swing. A number that does not move is a broken pipeline.
- **Step 6:** `cv_lab_pause` → `frame_error`/`cv_lab_paused`, metrics
  frozen, **`frames_refused` still climbing**, `receiving_frames` still
  `true`.

**Falsifiers:** a `frame_result` whose `cv_lab.experiment_id` disagrees
with its `result_label`; a run whose counters move after a stop;
`receiving_frames: true` with the phone switched off; a switch that
leaves the previous experiment running.

---

## 4. Document Memory

### Build

```
GET  /documents?limit=&retention_days=
GET  /documents/search?text=&limit=
GET  /documents/around?at=&window_seconds=
GET  /documents/{document_id}
GET  /documents-session
POST /documents-session/{start|pause|resume|stop}
result_subscribe document_memory / status
```

**Two contracts, deliberately**: `status` on the socket, `library` on
HTTP. A change to one is not a change to the other.

`/documents*` 404 when `TOWER_DOCUMENT_ROOT` is unset. `/documents-session*`
404 when `TOWER_DOCUMENT_CAPTURE` is off **even with a root set** — a root
with capture off serves a library recorded elsewhere and records nothing
itself. Both 404s name the variable.

### Typed status and library

The three answers are a **closed vocabulary**: `matched`, `not_found`,
`no_observation`. Render `no_observation` as "**Never observed**" — and
say explicitly that this is **not** the same as the document not
existing. `no_observation_note` carries the sentence.

`text_availability.state`: `unknown` (no pages), **`not_readable` (a real
answer — we looked and found no readable text)**, `extracted`.

Read `snippet_max_chars` (**48**) off the envelope rather than hard-coding.
Titles clip at 60; a null title renders "Untitled document", **never an
invented name**. `observed_seconds` is **not** a claim that the wearer
looked at it, noticed it, or read it.

The session block keeps its shape in every state — every field present,
`null` when absent — so do not treat fields as optional.

### Lifecycle — Stop KEEPS documents

**Stop keeps what was recorded**, unlike Scene. A record of what was read
is exactly as true after the session ends. **A dwell in progress is
flushed, not dropped** — a wearer still reading when a session stops has
read something.

Document does **not** follow the stream by default (`follows_stream:
false`): this cartridge writes, and a session that persists what a wearer
read gets an explicit start.

The OCR reader takes about **5 s** to construct. Poll for
`session.state == "running"`; do not assume start is synchronous.

### Provenance and limitations

`capture_id_validated` is **always false** — nothing checks the capture
still exists. `retention.writer_window_days` is **always null** — the
store persists no retention manifest, so a reader cannot learn the window
its writer used.

**`joinable: true` is said out loud**, with a note. This block *is*
joinable — a capture id, frame sequence numbers and a timestamp locate the
reading in a recording on disk. Scene Understanding refuses exactly this.
**A document is a record; a scene is not.**

### The limitation you must render

> **An empty library is the expected result today.** The page detector
> fired **six times in 9,199 real frames and every one was a false
> positive**; after the gate was re-derived it fires **zero** times. No
> capture on this platform has ever contained a sheet of paper. At
> 360×640 EasyOCR returned **zero dictionary words** across 919 sampled
> real frames dense with screen text.

**A client that renders an empty library as "no documents yet" is
inviting a person to wait for something that is not coming.** Render
`recording_limitations`.

### The real-paper test — the single most valuable hour on this cartridge

1. `TOWER_DOCUMENT_ROOT=…`, `TOWER_DOCUMENT_CAPTURE=true`.
2. `POST /documents-session/start`; wait for `running` (~5 s).
3. Connect the glasses. **Hold a printed page square-on at reading
   distance for 10 seconds**, well lit, filling most of the view.
4. `GET /documents-session` — did `pages_detected` move? Did `in_dwell`
   go true? **Expect zero.** 5,204 real corpus frames through the live
   path detected 0 pages. **If your printed page moves either counter,
   that is the first positive this cartridge has ever seen and is worth
   writing down.**
5. `GET /documents` — is `text_availability.state` `extracted` or
   `not_readable`?
6. Repeat tilted, at arm's length, in poor light.
7. **Record the false-positive case:** point at a venetian blind and at a
   backlit keyboard. Both used to fire and must not now.

**Validator:** one document, legible text, and a `provenance.capture_id`
that resolves to the capture you just recorded.
**Falsifier:** zero detections on a square-on page at reading distance —
which is the expected outcome at 360×640.

---

## 5. Scene Understanding

### Build

```
GET  /scene
POST /scene/{start|pause|resume|stop}     (operator, never the phone)
result_subscribe scene_understanding / live
```

Result type is **`live`, not `status`**. **Every key is present in every
state** — do not model fields as optional; you would lose the ability to
tell "zero of these" from "this Tower did not say".

### Stream-bound lifecycle

**`stream_start` starts. `stream_stop` or a disconnect ends AND
DISCARDS.** The phone sends **nothing** to open a cartridge, and a test
asserts the wire stays silent.

After a stop: `scene_available: false`, `counts: null`, `where: null`,
`people: null`, and `scene_unavailable_reason` says the last scene was
discarded.

> **Do not cache the last scene across a stop.** A scene held past the end
> of a session is a claim about a room the wearer has left. No staleness
> number makes that safe, because a client that renders counts above
> staleness shows the room first.

**Pause is the deliberately different case:** the scene survives with its
age and `scene_is_current: false`. That is "last known", and it must be
visually distinct from "observing".

**Two payloads with different `session_id` must not be compared.**

Fixed during this integration: a `stream_start` **no longer resumes a
session the wearer paused.** An explicit Start still does.

### Lower bound, limitations, and the four silences

**`count_is_lower_bound` is `true` on every payload. Render it somewhere a
person will see it.** Recall against an oracle over 14,128 real frames:
**0.306** person, **0.497** cell phone, **0.209** tv, **0.161** chair,
**0.108** couch, and **0.000 below 1% of frame area**. The oracle shares
COCO training data with the shipped model, so **0.306 is an upper bound**.

> **An undercount published without disclosure looks exactly like a quiet
> room.**

`scene_available: false` in **four** distinct situations, told apart by
`scene_unavailable_reason`: stopped / still loading / failed /
running-but-no-frame-yet. **All-zero counts with `scene_available: true`
is a fifth and different case** — "I looked and saw nothing". Render all
five differently.

`facing_wearer` is **null, never 0, when unmeasured.** `load_overdue` is
**not a failure**.

### Privacy — what you must not ask for

`tracks`, `relations` and `confidence` are **always null**, each with a
reason and a refusal list. **There is no key in this payload that could
hold an entity or a relation.** No face recognition exists on this
platform; keypoints are anonymous landmarks producing no descriptor.
Track ids are session-scoped and never published.

iOS asked for a session-scoped anonymous track handle and a signed
bearing. **V1 serves neither**, and the consequence is concrete: **you
cannot render per-entity rows for people, only a count and an aggregate.**
If that is the wrong trade it is a contract change with a new identifier,
not a field quietly populated later.

`where` excludes `person` — a per-person position, sampled repeatedly, is
a movement trace.

### The real-person / real-object test

> **Nobody has ever worn these glasses in a room with another person and
> checked what the Tower said.** Every `person` detection in the corpus is
> the wearer's own torso.

1. `TOWER_SCENE_UNDERSTANDING=true`, **`TOWER_SCENE_TORCH_THREADS=2`**.
2. `POST /scene/start`; wait for `running`.
3. One other person, good light, **~2 m**. `GET /scene` and **record
   `people.count` against the truth.** Expect an undercount; expect the
   wearer's own torso to inflate it.
4. Repeat at **4 m** and at the **edge of view**.
5. **Walk.** Watch `frames_skipped` — if it climbs, this Tower cannot
   keep up and the counts are less stable than they look.
6. `POST /scene/stop` and confirm `scene_available` goes false
   **immediately, on both the route and the subscription.**

**Falsifier:** counts that do not track the truth even loosely at 2 m, or
a `person` count that never distinguishes one bystander from none.

**Set `TOWER_SCENE_TORCH_THREADS=2`.** Measured **1.03 cores with it
against 4.12 without, at identical throughput.** It is process-global and
therefore also affects the CV Lab.

---

## 6. Consolidated physical-test plan

Nothing below has been run. Ordered by value.

| # | Test | Cartridge | Why it is worth the hour |
|---|---|---|---|
| 1 | **PT-1 lateral-translation walk** (§1) | World Builder | Worth more than the rest combined. The binding constraint is the capture, and this is the only way to find out. Unlocks the wrong-basin question too. |
| 2 | **Real-paper test** (§4) | Document Memory | The detector has never been shown a positive it was built for. One printed page settles a premise the whole cartridge rests on. |
| 3 | **Real-person test** (§5) | Scene Understanding | Every `person` in the corpus is the wearer's own torso. |
| 4 | **PT-4 recognisability** (§1) | World Builder | Rides on PT-1 footage. "Points appeared" is not the bar. |
| 5 | **Object Memory found-record screen**, shown cold to a person | Object Memory | The caption carries the whole burden and no string test can catch it. If "where" comes back, it is wrong. |
| 6 | **Coexistence soak**: World Builder + Scene for ten minutes | shared runtime | Watch `frames_skipped` on both and frame-path latency. Scene is the first thing a loaded Tower starves — ~84 ms service against an 83.5 ms interval. |
| 7 | **720×1280 still** (§2) | all three | One measurement, upstream of a lot of model work. A **still**, not a stream. |
| 8 | **PT-2 / PT-3** | World Builder | Feature-starvation gate cost; multi-reference depth on a long vs sparse walk. |

Run 1 and 2 first. They are the two that can falsify something.

---

## 7. Known defects you will meet

Reproduced during this integration and **left open**, with the reasoning
in `tower/docs/agent-handoffs/2026-08-27-TOWER-UNIFIED-INTEGRATION.md`.

| What | Impact on the Mac |
|---|---|
| **Pause can report success without stopping the producer** | Key liveness on `following`, not `state`. Non-negotiable. |
| **Scene / Document silently no-op** on a verb they cannot honour (200, no refusal field) | Read the returned `state`; never treat 200 as "it worked". |
| **CV Lab refuses `cv_lab_stop`** from `stopped`/`idle`/`failed` | Do not build "Stop then Start" recovery. Send `cv_lab_start`. |
| **A phone's `stream_stop` can end a Scene session an operator started by hand** | During a physical test, drive Scene from the routes and do not stream from a phone at the same time. |
| **Shutdown can take up to ~24 s** with stubborn producers | Do not treat a slow Tower shutdown as a hang. |
| **`world_builder.geometry` and `object_memory.observations` are declared nowhere** | Hard-code those two identifiers; they are not in `http_contracts`. |
| **World Builder's ~2% wrong-basin defect** | Open, unfixable without ground truth, and undetectable on real footage. |

---

## 8. What changed for you in this integration, in one list

1. `/cartridges` now offers **four** cartridges; `not_offered` is empty.
2. `document_memory.library` appears under a new **`http_contracts`**
   block. Two other HTTP contracts are still undeclared.
3. `declare()` is keyword-only behind `declaration_inputs`; **HTTP and
   socket declarations are byte-identical** and a test holds it.
4. Object Memory's session control at `/cartridges/{cartridge}/session` is
   **generic** — the next cartridge that needs a button gets one free.
5. A CV Lab refusal **no longer starves** the recorder, Scene or Document.
6. A `stream_start` **no longer resumes** a Scene session the wearer
   paused.
7. Attaching a capture worker **no longer freezes** the Tower.
8. Two contract values that had drifted from the wire were corrected:
   Document's `claim` and `snippet_max_chars`.
