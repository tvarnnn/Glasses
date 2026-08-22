# Cartridge Groundwork — what World Builder leaves behind

Status: **architecture groundwork, not authorization.** Nothing here
authorizes implementing any cartridge named below. It records what the
first major cartridge built, what is genuinely reusable, and — more
importantly — which of its assumptions must **not** leak into the next one.

Written 2026-08-22 alongside `reports/2026-08-22-world-builder-v1-report.md`.

---

## 1. The governing rule

World Builder is one consumer of the camera. It is **not** the definition
of how the camera behaves.

The transport layer (`tower/frames.py`, `tower/routes/ws.py`,
`tower/metrics.py`) is shared sensor infrastructure. The current iOS
~12 fps selection policy is a **current transport default**, not a
cartridge-independent law. Each cartridge should consume the available
frame stream and make its own decisions about which frames matter.

---

## 2. What is genuinely reusable today

| Asset | Where | Why it generalises |
|---|---|---|
| Append-only JSONL + atomic-rewrite store shape | `tower/object_memory/store.py`, `tower/world_builder/store.py` | Two independent modules have now converged on it. It survives torn lines, purges completely, and needs no engine |
| `Confidence` label vocabulary | `tower/object_memory/records.py` | Stored as a **label**, never a recomputed score, so a later threshold change cannot silently relabel history (Rule 16) |
| Real `purge()` that reports what it could NOT delete | both stores | `06-PRIVACY-DATA.md` requires real deletion; a false claim of deletion is worse than an honest failure |
| Single choke point for persisted pixels | `world_builder/store.write_keyframe_image`, `capture.write_frame` | Any future redaction or filtering policy becomes a change to one function |
| `time_basis` on every timestamp | both modules | There is no capture timestamp on the wire. Every cartridge inherits that and must say which clock it means |
| Explicit Dataset-Recording Session pattern | `tower/capture.py` | Off by default, bounded in seconds and bytes, purgeable, manifest declares posture |
| Synthetic ground-truth harness | `tests/synthetic_scene.py` | Exact poses, exact intrinsics, deterministic. Any cartridge doing geometry can assert real answers instead of eyeballing plausible ones |
| Tailing a capture as it is written | `capture.CaptureFollower` | A cartridge can process a dataset session live, in its own process, reading the journal so `source_seq`/`tx_seq`/receipt time survive. Bounded, so a crashed recorder ends the follow rather than hanging it |
| Calibration record + harness | `records.CameraIntrinsics`, `scripts/calibrate_charuco.py` | Intrinsics are a **platform** property, not a World Builder property. Every geometric cartridge needs them and none should re-derive them |

---

## 3. Assumptions that must NOT leak

These are World Builder's, and they are wrong for other cartridges.

| Assumption | Why it is World-Builder-only |
|---|---|
| **Keyframes over freshness.** Most frames are discarded; the useful ones are chosen for parallax | Visual Q&A and Accessibility want the **freshest** frame. A shared "frame selection" service built from World Builder's policy would actively harm them |
| **Latency does not matter.** `build()` takes tens of ms to seconds and runs offline | Accessibility is a latency-first consumer. Nothing in a shared path may assume deferred processing is acceptable |
| **Retaining raw imagery is justified.** World Builder persists keyframe JPEGs | It has a specific justification (rebuild, relocalisation). Most cartridges should persist derived data only, per `06-PRIVACY-DATA.md`. `retains_raw_imagery=True` must stay an exception that is argued for, not a default |
| **Motion is the signal.** Frames without parallax are worthless | Object Memory cares about object *change*; a static scene is not worthless to it. Text/Document wants deliberate still-like frames — exactly the frames World Builder rejects as `insufficient_motion` |
| **Geometry needs intrinsics.** No intrinsics → no poses | True for geometry, irrelevant for OCR, detection or QA. Nothing should gate a non-geometric cartridge on calibration |
| **A session is a mapping window.** Bounded by `stream_start`/`stream_stop` | Accessibility is continuous and has no natural session boundary |

---

## 4. Per-cartridge notes

### Object Memory (nearest neighbour, data layer already shipped)

- **Reuses:** the store shape it originated, `Confidence`, real purge.
- **Camera pattern:** occasional high-value frames on object change. Not
  parallax-driven, not continuous.
- **Extension point World Builder created:** the **spatial anchor
  contract**. `world_id` is an opaque `uuid4` that survives rename and
  refinement; keyframes are keyed `(session_id, source_seq)`; every record
  carries `frame_revision` and a declared `pose_convention`.
- **Frozen for it now:** an anchor must carry `world_id`,
  `frame_revision`, a position in **world units** (never metres),
  `observed_at` + `time_basis`, and a confidence **label**.
- **Additionally required, and NOT yet in Object Memory's schema:**
  `anchor_keyframe_id` plus `position_in_anchor_frame`. Without them the
  first loop closure permanently and undetectably invalidates every
  earlier anchor, because a submap re-anchor is not a global similarity
  and cannot be composed forward. Add them **before** any anchor exists.
- **Still missing:** relocalisation, and the loop closure that makes
  `frame_revision` ever advance.
- **Do not wire it yet.** Both modules must reach a stable bounded first
  version first.

### Visual Q&A

- **Reuses:** store shape, capture recorder, calibration record.
- **Camera pattern:** freshest observation, possibly a higher-quality
  still on demand.
- **Must not inherit:** keyframe selection, parallax gating, offline build.
- **Missing:** a "give me the current frame" primitive. The frame path
  currently pushes to one module; nothing exposes latest-frame semantics.

### Accessibility

- **Reuses:** almost nothing from World Builder. Possibly the calibration
  record if it ever does geometry.
- **Camera pattern:** continuous, minimum latency, immediate warnings.
- **Must not inherit:** anything deferred or batched, and certainly not a
  synchronous multi-millisecond stage on the frame path.
- **Missing:** a genuine low-latency execution path. `process()` being
  synchronous on the event loop is a blocker for this cartridge
  specifically, and it is the same V1.0/V1.1 work World Builder is
  stopped behind.

### Text / Document

- **Reuses:** capture recorder, calibration record (undistortion helps OCR).
- **Camera pattern:** high resolution, deliberate still-like frames.
- **Must not inherit:** World Builder's blur and motion gates would reject
  precisely the frames this wants — a held-still, high-detail view has
  near-zero parallax.
- **Missing:** resolution negotiation. DAT's adaptive ladder drops
  resolution first and cannot be overridden.

### Environmental Memory

- **Reuses:** store shape, `Confidence`, retention/purge discipline.
- **Camera pattern:** sparse, event-driven.
- **Missing:** the shared spatial service, which depends on the Object
  Memory contract above.

### Experimental CV Lab (the one cartridge that already exists)

- **Reuses:** `Confidence`, the capture recorder and its follower, the
  synthetic ground-truth harness, `StageTimer`.
- **Camera pattern:** whatever the experiment under test needs. This is
  the one cartridge with no single camera posture, and that is its point.
- **Must not inherit:** any World Builder gate. Its job is to *measure*
  gates like blur rejection and parallax, so a Lab that silently applied
  them could not evaluate them.
- **Owns the constraint everyone else is waiting on:** `ExperimentResult`
  is five scalars, and it is the Lab's type. Every other cartridge's
  "there is no non-scalar result channel" problem is a change to a file
  the Lab owns.
- **Must not mutate authoritative state.** The Lab may read a world; it
  must never write one.

### Translator

- **Reuses:** almost nothing shipped so far. Audio is a different sensor
  path entirely (`07-PLATFORM-CONSTRAINTS.md` Limitation 13), and none of
  the camera, keyframe, geometry or calibration work applies.
- **Sensor pattern:** continuous microphone, not camera. It is the first
  planned cartridge whose primary input is not a frame.
- **Must not inherit:** the frame-shaped assumptions in every row above.
  A "sensor observation" in this codebase means a JPEG today; Translator
  is the cartridge that proves that is a transport detail, not a law.
- **Missing:** an audio path of any kind. There is no audio transport, no
  audio recorder, no streaming primitive and no output routing. Its first
  prototype is deliberately specified to run on Tower-local microphone and
  speakers, entirely outside the glasses path, precisely because none of
  that exists yet.

---

## 5. Infrastructure still missing

Named so nobody assumes it exists.

1. **Multi-consumer frame distribution.** `ModuleContainer` is a
   registry of one, so two cartridges cannot both be the active module.
   `app.state.frame_observers` *is* a real list and is now populated in
   production (`TOWER_CAPTURE_ROOT`), but it is a side-errand channel: an
   observer returns no result to the client. It is not a second module
   slot, and using it as one would spend the architecture decision the
   roadmap is protecting.
2. **Frame metadata into modules.** `Module.process()` takes only `bytes`.
   `received_at`, `source_seq` and `tx_seq` are unavailable to a module,
   which is why World Builder's engine is driven offline.
3. **A non-scalar result channel.** `ExperimentResult` is five scalars.
   No geometry, no structured event, no delta can cross the wire.
4. **An asynchronous execution path.** There is no worker, queue or
   executor anywhere in `tower/`.
5. **Cartridge-declared sensor requirements.** Rule 4 forbids designing a
   generalised negotiation protocol before the real DAT configuration
   model is known.
6. **A shared privacy filter.** Deliberately absent: one consumer is not
   an abstraction. The choke points exist; the filter does not.

Items 1–4 are the same V1.0 / V1.1 work that World Builder stops behind.
**A second cartridge with real requirements is exactly the trigger
`03-ROADMAP.md` names for V1.0** — and World Builder is now that second
set of requirements, written down.

---

## 6. Extraction rule

Before moving anything out of a cartridge into shared infrastructure:

1. Is it actually useful to another **known** cartridge?
2. Is the abstraction understood from at least **two** plausible consumers?
3. Does extracting it reduce real duplication?
4. Does it preserve cartridge isolation?
5. Does it add complexity today?

If unclear, **keep it local**. `Confidence` passes (two consumers, frozen,
20 lines). A privacy filter does not — yet.
