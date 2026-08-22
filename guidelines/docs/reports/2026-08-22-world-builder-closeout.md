# World Builder V1 — Closeout Audit

**Branch:** `world-builder/v1`. **Audited from:** `019cd1c`.
**Suite at audit time:** 376 passed, 3 skipped. **After this closeout:**
429 passed, 3 skipped.

Companion to `2026-08-22-world-builder-v1-report.md`, which describes what
was built and why. This document does something different and narrower:
it walks **every requirement in the root `plan.md`** and states where it
landed, so that the decision to move on to another cartridge is made
against evidence rather than against a feeling that World Builder is
"basically done".

Verdicts are one of **IMPLEMENTED**, **PARTIAL**, **DEFERRED**,
**BLOCKED**, **REJECTED**. A REJECTED item is one we decided not to build
and can defend; a BLOCKED item is one we could not build without breaking
something the brief protects.

---

## 1. Summary

World Builder V1 satisfies its own definition of done, with four
qualifications, all of which were already known and none of which is new:

1. **Live incremental viewing** was PARTIAL. It is now IMPLEMENTED for
   the Tower, by the smallest change that does not touch the blocked
   module lifecycle — see §4. On iOS it remains BLOCKED, because no
   transport exists at all.
2. **Storage is observable, not capped.** The definition of done says
   "bounded"; what exists is a growth figure a caller can read. Accepted
   deliberately — see §5.1.
3. **The 21.6% drift figure at 16 keyframes was a synthetic-scene
   artifact** — the benchmark walk left the room at that exact keyframe.
   Re-measured in-room it is 1.05%. Resolved during this closeout, with a
   proposed fix measured and rejected — see §5.2.
4. **Nothing has been validated on physical footage.** Every measurement
   in the project is synthetic. That gate is unchanged and unmovable
   without hardware.

Four fixes were made during closeout, all tested: production capture
arming (§3.1), the event cursor and follow drivers (§4), the benchmark's
out-of-room walk (§5.2), and documentation corrections (§6).

---

## 2. Coverage matrix

### 2.1 Functional target (`plan.md` §20)

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 1 | Create a world | IMPLEMENTED | `engine.create_world`, `engine.py:125` |
| 2 | Start a mapping session | IMPLEMENTED | `engine.start_session`, `engine.py:136` |
| 3 | Receive frames through existing Tower infrastructure | **PARTIAL** | `engine.observe` is driver-agnostic, but `ws.py:54` routes live frames only to `module_container`. Frames reach the engine through the capture journal, not through `process()`. See §4 |
| 4 | Evaluate frames | IMPLEMENTED | `frontend.analyse_frame`, `summarise_motion` |
| 5 | Reject useless/bad frames | IMPLEMENTED | `KeyframeSelector.evaluate` REJECT/SKIP outcomes |
| 6 | Select meaningful keyframes | IMPLEMENTED | `KeyframePolicy` / `KeyframeSelector` |
| 7 | Maintain persistent keyframe/world state | IMPLEMENTED | `keyframes.jsonl`, `edges.jsonl`, round-tripped in tests |
| 8 | Maintain spatial/trajectory relationships where supportable | IMPLEMENTED | Edges carry matches/inliers/cheirality even when the pose is refused |
| 9 | Generate inspectable derived geometry | IMPLEMENTED | `store.read_derived`, `inspect.points` |
| 10 | Update world incrementally while mapping | IMPLEMENTED | Cheap `observe()` / expensive `build()` split; `--rebuild-every` now advances derived geometry mid-walk |
| 11 | Expose incremental updates | IMPLEMENTED (was PARTIAL) | `store.read_events(..., after_event_id=)`, `WorldView.events`, `world_inspect.py --follow`. See §4 |
| 12 | Stop cleanly | IMPLEMENTED | Writer lock released; `session_stopped` emitted |
| 13 | Persist world | IMPLEMENTED | Atomic fsync'd writes throughout |
| 14 | Restart process/session | IMPLEMENTED | Cold-store test over the same directory |
| 15 | Reload world | IMPLEMENTED | Subprocess-level cold reload in the CLI tests |
| 16 | Inspect without the live session | IMPLEMENTED | `scripts/world_inspect.py` |

### 2.2 Definition of done (`plan.md` §37)

| # | Requirement | Verdict | Note |
|---|---|---|---|
| 1–8 | Creation, session, frames, evaluation, rejection, selection, graph, relationships | IMPLEMENTED | Item 3 carries §2.1's PARTIAL on the live path |
| 9 | Scale/calibration state explicit | IMPLEMENTED | Four-state enum; metres gated at one choke point |
| 10 | Derived inspectable geometry | IMPLEMENTED | |
| 11 | World updates incrementally | IMPLEMENTED | |
| 12 | Incremental updates exposed | IMPLEMENTED | Was PARTIAL; closed in §4 |
| 13–17 | Clean stop, persist, restart, reload, inspect | IMPLEMENTED | |
| 18 | Storage intentional/**bounded** | **PARTIAL, accepted** | Observable, not capped. §5.1 |
| 19 | Failures do not silently corrupt | IMPLEMENTED | Torn lines skipped, schema mismatches left alone, atomic writes, purge reports what it retained |
| 20 | Full suite passes | IMPLEMENTED | 429 passed, 3 skipped |
| 21 | New tests pass | IMPLEMENTED | |
| 22 | Meaningful benchmarks recorded | IMPLEMENTED | Per-stage live-path timings, build timing, trajectory accuracy vs ground truth. Not every category in §32 has its own number — see §5.3 |
| 23 | No unresolved critical correctness/data-loss issue | IMPLEMENTED (was PARTIAL) | Two CRITICALs found and fixed. The one open accuracy question, the 16-keyframe drift figure, was investigated and resolved: it was the walk leaving the room, not the engine. §5.2 |
| 24 | Architecture documented | IMPLEMENTED | V1 report + `CARTRIDGE-GROUNDWORK.md` |
| 25 | Physical-only claims deferred | IMPLEMENTED | Every World Builder test module opens "SYNTHETIC, NOT PHYSICAL" |
| 26 | Shared infrastructure cartridge-neutral | IMPLEMENTED | Enforced by AST tests in `test_architecture_boundaries.py` |
| 27 | Future cartridges have documented extension points | IMPLEMENTED (was PARTIAL) | Translator and Experimental CV were missing from `CARTRIDGE-GROUNDWORK.md`; added in §6 |

### 2.3 Architecture directives (`plan.md` §4–§19, §21–§36)

| Section | Requirement | Verdict | Evidence |
|---|---|---|---|
| §4 | World Builder must not define global camera behaviour | IMPLEMENTED | AST test forbids shared code importing `world_builder`. The iOS 12 fps policy is untouched |
| §5 | Extract shared infrastructure only when justified | IMPLEMENTED | `Confidence` and `capture.py` were promoted; a privacy filter deliberately was not |
| §6 | Do not build other cartridges | IMPLEMENTED | No other cartridge code exists on this branch |
| §7 | Tolerate variable FPS; never assume constant spacing | IMPLEMENTED | Keyframe policy is motion- and quality-driven, not time-driven; elapsed time is a fallback only |
| §8 | Treat the sensor as monocular RGB; invent no intrinsics | IMPLEMENTED | `INTRINSICS_SOURCE_*` has no value meaning "guessed" |
| §9 | Do not equate relative geometry with metric scale | IMPLEMENTED | `SCALE_STATES_ALLOWING_METRES = (SCALE_MEASURED,)`, pinned by test |
| §9 | Persist enough to upgrade scale later | IMPLEMENTED | `ScaleState` carries `meters_per_unit`, `method`, `confidence`, `history` |
| §10 | ChArUco calibration, versioned/resolution/source aware | IMPLEMENTED | `scripts/calibrate_charuco.py`, `CameraIntrinsics` |
| §10 | Exact future physical calibration procedure | IMPLEMENTED | V1 report §8 |
| §11 | Graph authoritative, geometry derived | IMPLEMENTED | Keyframes/edges are the journal; poses/points live under `derived/` and are rebuilt |
| §12 | Point cloud is not sacred | IMPLEMENTED | Sparse landmarks + trajectory; the "cloud" is a derived by-product |
| §13 | Two-rate architecture | IMPLEMENTED | `observe()` per frame, keyframes on information |
| §14 | Benchmark raw vs preprocessed | IMPLEMENTED, **negative result** | V1 report §3.4: preprocessing does not help; it is not applied |
| §15 | A depth prediction is evidence, not ground truth | IMPLEMENTED by omission | No learned depth is used in the reconstruction path at all |
| §16 | Do not blindly choose DA3 | IMPLEMENTED | Classical two-view SfM chosen; no ML in the geometry path. torch is CPU-only here and there is no C++/CUDA compiler |
| §17 | Simplicity challenge | IMPLEMENTED | The homography-residual gate was built and then deleted; loop-closure descriptors, gauge algebra, checkpoints and an event bus were all declined with reasons |
| §18 | A dedicated "what can we delete?" reviewer | IMPLEMENTED | V1 report §5 is that reviewer's output |
| §19 | GPU environment | **NOT EXERCISED** | torch remains `2.13.0+cpu`. Nothing in the shipped geometry path needs CUDA, so no restore was performed and none is claimed. `scripts/world_builder_env_check.py` reports the truth |
| §21 | World/session/keyframe/geometry entities | IMPLEMENTED | |
| §22 | Retention: do not store every frame by default | IMPLEMENTED | Only selected keyframes persist. Raw capture is a separate, off-by-default dataset session |
| §23 | Preserve multi-session capability | IMPLEMENTED | Stable opaque ids, `frame_revision` stamped, segments explicit. Relocalisation not built |
| §24 | Object Memory future contract | IMPLEMENTED as documentation | `CARTRIDGE-GROUNDWORK.md` §4 names the anchor fields that must exist *before* the first anchor does |
| §25 | Live output contract; no production iOS viewer | IMPLEMENTED | Event journal + cursor + follow. No viewer built, per `WORLD-BUILD.md` |
| §26 | Geometric honesty | IMPLEMENTED | `unknown` never renders as `0`; degeneracy reasons persist; `up_axis` stays unknown |
| §27 | Failure handling | IMPLEMENTED | Pure rotation, low parallax, no correspondence and no intrinsics are all first-class refusals |
| §28 | Stop at the integration boundary | IMPLEMENTED | Non-registration is pinned by a test, not left to memory |
| §29 | Use subagents | IMPLEMENTED | |
| §30 | Targeted research only | IMPLEMENTED | |
| §31 | Testing | IMPLEMENTED | 150+ World Builder tests; ground-truth comparisons rather than self-comparison |
| §32 | Benchmarking | PARTIAL | §5.3 |
| §33 | Physical data limitation | IMPLEMENTED | |
| §34 | Durable documentation | IMPLEMENTED | |
| §35 | Future cartridge groundwork report | IMPLEMENTED | |
| §36 | Record consequential rulings | IMPLEMENTED | |

### 2.4 Late additions (`plan.md` §A–§F)

| Requirement | Verdict | Reason |
|---|---|---|
| A. ChArUco calibration | IMPLEMENTED | The single highest-value late addition — it is the switch from "no poses" to "poses", and was arguably core rather than stretch |
| A. Calibration versioned / resolution / source aware | IMPLEMENTED | Refuses to rescale across resolutions until linearity is established |
| A. Environmental fiducials (AprilTag/ArUco) | **REJECTED** | The proposed cross-frame-consistency guard is circular: its reference frame comes from the drifting reconstruction it is supposed to check. A ChArUco board is already a known-size fiducial, and marker scale was evaluation-only value in V1 |
| A. Never let one marker rescale the world | IMPLEMENTED by construction | No marker can, because none is consulted |
| A. Expose scale states | PARTIAL | Four states plus a confidence label. The brief's `Acquiring` has no implemented meaning and is deliberately not shown |
| B. Face redaction before persistence/display | **REJECTED for V1** | This OpenCV build has no `CascadeClassifier`, no cascade XML and no ONNX model; the upstream URL serves a Git-LFS pointer. There is also no face imagery anywhere to validate against. A measured side-finding: after box-blur redaction, 100% of surviving near-region keypoints sat on the redaction boundary, producing consistent-looking but wrong tracked geometry |
| B. A privacy boundary that survives the decision | IMPLEMENTED | `Session.redaction` records provenance; every persisted pixel passes through one function |
| B. No face recognition / no persistent identity | IMPLEMENTED | None exists |
| C. Level 1 recorded-path replay | **DEFERRED — persistence complete, no viewer** | `WorldView.trajectory()` returns ordered keyframes with pose, segment and image path: everything a replay needs. `WORLD-BUILD.md` says not to build the viewer yet |
| C. Level 2 true free-roam | **REJECTED** | Requires one coherent global frame, surfaces and coverage. With segment breaks, sparse points and uncorrected drift it would be a fake. Quantified re-entry gates are recorded in the V1 report |
| D. Viewer contract | IMPLEMENTED as data | Overview, trajectory, keyframe locations, derived geometry, confidence, calibration and scale status are all persisted and readable. No renderer exists, by instruction |
| E. Stretch-goal gate | IMPLEMENTED | Core correctness was protected; two of four additions were dropped rather than half-built |
| F. Independent challenge of the additions | IMPLEMENTED | All four were challenged; two survived |

---

## 3. Fixes made during closeout

### 3.1 Capture could not be armed in a running Tower

**The gap.** `app.state.frame_observers` was populated **only by tests**.
No environment variable, route or flag armed the recorder in a normal
process. Every physical-validation step the project has written down
begins "arm capture on the Tower", and that step was not executable. The
gap was invisible precisely because the test suite armed it by hand.

**The fix.** `TOWER_CAPTURE_ROOT` (unset by default) registers exactly one
`CaptureRecorder`. Arming is not recording: a configured root creates no
directory and writes no byte until a `stream_start` arrives, so this
stays an Explicit Dataset-Recording Session under `06-PRIVACY-DATA.md`
rather than becoming incidental capture. A blank value is treated as
unset — a shell exporting an empty variable is saying "no", and reading
that as the current working directory would arm a raw-imagery recorder
somewhere nobody chose.

**And it now says so.** `/health` gained a `capture` block. `null` means
no recorder is registered; a registered-but-idle recorder reports
`recording: false`. Collapsing those two would make "we are definitely not
recording" indistinguishable from "we are one `stream_start` away".
`06-PRIVACY-DATA.md` requires recording state to be indicated, and until
now the indication was a server-side log line that nobody operating the
Tower over Tailscale can see. The block never raises: `/health` is how an
operator learns the Tower is unwell and must not fail because a subsystem
is broken.

### 3.2 Live incremental viewing

See §4.

### 3.3 Documentation corrections

See §6.

---

## 4. Live incremental viewing — the smallest architectural change

### 4.1 What was actually missing

Not the storage design. The append-only journal has always been an
incremental update stream, `event_id` has always been dense so a gap means
a genuinely dropped event, and images have always been fsynced before
their journal line so a reader can never see a half-written file.

Two things were missing, and neither was a persistence concept:

1. **A cursor.** `read_events()` returned the whole file. A reader wanting
   "what is new" had to re-read everything and filter by hand, and nothing
   in the repository did.
2. **A live producer.** Nothing called `engine.observe()` while frames
   were arriving. The only drivers read a finished directory.

### 4.2 The rejected shortcut

`ws.py` already has a generic side-channel that bypasses `ModuleContainer`
entirely: `app.state.frame_observers`, a genuine list, used today by the
capture recorder. Registering a `WorldBuilderObserver` there would have
made the engine live in about thirty lines, and it would technically not
have touched `tower/modules/base.py`.

**It was rejected.** The capture recorder's justification for sitting on
that channel is precise: *recording is not processing*. It returns no
module result, so it does not make World Builder a second active module
and Rule 2 survives. Running the mapper on that same channel **is**
processing, and the fact that it would evade the type system does not make
it a second module any less. `plan.md` §28 says to stop at the integration
boundary rather than force World Builder into production registration, and
this is exactly the boundary it means. Taking the shortcut would have
bought live viewing by quietly spending the architecture decision the
brief protects.

### 4.3 What was built instead

Three processes, which is the shape V1 already relies on:

```
glasses -> iOS -> WS /ws -> CaptureRecorder writes frames + journal
                                     |
        world_build_session.py --follow-capture <dir>   (separate process)
                                     |
                        keyframes.jsonl + events.jsonl grow
                                     |
        world_inspect.py --world <id> --follow          (separate process)
```

- **`CaptureFollower`** (`tower/capture.py`) yields frames from a capture
  directory as they are written, reading the **journal** rather than
  globbing the image directory — a glob would discard `source_seq`,
  `tx_seq` and receipt time, and with them any ability to reason about
  dropped frames. It is bounded (`max_idle_polls`) so a crashed recorder
  ends the follow instead of hanging it, per Rule 15. It closes the one
  real race: the recorder appends a line and only later rewrites the
  manifest, so a follower that stopped the instant it saw an end reason
  would drop whatever landed in between. It does one final journal read.
- **`world_build_session.py --follow-capture`** drives `engine.observe()`
  from that stream, with `--rebuild-every N` re-deriving geometry after
  every N accepted keyframes. This is affordable **only** because it runs
  in a different process from the one receiving frames: the frame path
  pays nothing for a rebuild, however long it takes.
- **`store.read_events(..., after_event_id=)`**, `WorldView.events()` and
  **`world_inspect.py --follow`** are the read half. A record with no
  `event_id` is skipped when a cursor is given — there is no way to
  advance past it, so returning it would hand it back on every poll
  forever and a viewer would show the same event on a loop.

A test pins that a mid-walk rebuild produces the same final world as a
single build at the end. If it did not, watching a world build would
change the world, and two operators would get different maps from
identical footage.

### 4.4 What is still blocked

**On Tower: nothing.** The product experience — start, walk, watch it
build, stop, inspect — is reachable today with three terminals and no
hardware beyond the glasses.

**On iOS: everything**, and not partially. There is no route, no message
and no push channel carrying world data, because `frame_result` is five
scalars. That is `plan.md` §28's blocker verbatim, recorded in
`docs/agent-handoffs/TOWER-TO-IOS.md` §6.1 with the four exact source
locations that would have to change.

**Still poll-based.** Following is a filesystem poll, not a push. That is
adequate at V1 scale and it is honest about being a poll. A push channel
is the pub/sub bus `events.py` declines to build until something can
subscribe.

---

## 5. Open items, stated plainly

### 5.1 Storage is observable, not capped

`store.world_bytes()` reports total, image, derived and journal bytes, and
a test exercises it. Nothing enforces a ceiling.

Accepted, because a cap has no correct value yet. The only number that
would inform one — bytes per minute of *real* footage at a *real*
resolution — does not exist, and a limit invented before that measurement
would either truncate a legitimate session or never fire. The growth
figure is exposed so the eventual policy can be set from data. The
definition of done says "bounded"; what exists is "observable and
intentional", and the difference is recorded here rather than smoothed
over.

### 5.2 Trajectory drift at 16 keyframes — RESOLVED: it was the wall

The reported figures were 1.06% at 8 keyframes, 1.97% at 12, and **21.61%
at 16**. Smooth accumulating drift does not do that, so this closeout
treated the tenfold jump as the one open correctness question and
investigated it.

**The dominant cause was the synthetic scene, not the engine.** The
keyframe sweep used `strafe(N, step=0.20)`, which advances the camera
0.20 m per keyframe from x = 0. The default room is 6 m wide, so keyframe
16 sits at **x = 3.00 m — exactly the right wall**. Approaching it, the
near-field boxes leave the frame and correspondences collapse from ~1000
to ~640; one step later the pose is refused outright as
`no_correspondence`. The camera was walking through a wall, and running
out of scene looks identical to accumulated drift in a single error
percentage.

Re-measured with the walk kept inside the room (step scaled so the chain
spans a fixed 2.5 m):

| keyframes | step | max drift, % of path |
|---|---|---|
| 8 | 0.200 m | 0.83% |
| 12 | 0.200 m | 0.87% |
| 16 | 0.167 m | **1.05%** |
| 20 | 0.132 m | 10.77% |
| 24 | 0.109 m | 22.64% |

**There is no cliff at 16.** Per-keyframe residuals along the 20-keyframe
chain grow smoothly — 1.1%, 2.7%, 4.5%, 7.6%, 10.8% — with match counts
holding near 1000 throughout. What the longer chains show is ordinary
monocular accumulation, made worse by the shrinking per-pair baseline that
packing more keyframes into a fixed path implies. That is textbook
behaviour for incremental SfM without bundle adjustment, and it is exactly
what `pycolmap` would reduce.

**Fixed:** `world_builder_benchmark.py` now scales its step with the
keyframe count and refuses outright if the walk would leave the room, and
reports `step_m` and `max_offset_m` so two runs at different counts are
comparable rather than silently different. `synthetic_scene.poses_outside_room()`
makes the scene's validity envelope checkable, and
`tests/test_synthetic_scene_bounds.py` pins it.
`tests/test_world_builder_drift.py` pins the *shape* of the error — short
chains bounded, long chains larger — rather than a percentage.

**Rejected fix, with the measurement that rejected it.** The obvious
response was to gate `_extend`'s PnP acceptance on inlier ratio, mirroring
`_estimate_pair`'s gate, since `_extend` checks only an absolute
correspondence count. Measured inlier ratios say that would be backwards:

| walk | median inlier ratio, later keyframes |
|---|---|
| interior, `strafe(16, step=0.09)` — the **good** case | ~0.25 |
| toward the wall, `strafe(16, step=0.20)` — the **bad** case | ~0.47 |

A ratio floor would have refused the healthy configuration and admitted
the failing one. A large healthy match set with plenty of far-field
structure carries proportionally more outliers than a shrinking one, so
the ratio moves the wrong way. The negative result is pinned by a test so
the fix is not re-proposed from first principles.

**Reproducibility caveat, now recorded.** `findEssentialMat(USAC_MAGSAC)`
and `solvePnPRansac(SQPNP)` are not seeded anywhere, and results differ
across OpenCV builds: the committed
`test_trajectory_matches_truth_after_similarity_alignment` docstring
claims 1.32% where the same passing test measures 1.62% on this build.
**Any single-run percentage in this repository is a measurement of one
host, not a portable constant**, and a comment in
`backends/classical.py` that restated two such figures has been replaced
with a pointer to this section.

**The standing answer is unchanged.** `pycolmap 4.1.1` is verified as a
23.5 MB cp312 Windows wheel, BSD-3, needing no compiler and bundling
Ceres. Bundle adjustment was declined because no measurement showed drift
it would fix. The long-chain numbers above are a candidate trigger — but
they must be reproduced on **physical** footage first, because a
synthetic scene's geometry is not evidence about a real camera.

### 5.3 Benchmark coverage is partial

The V1 report records per-stage live-path timings, build timing and
trajectory accuracy against ground truth. `plan.md` §32 lists roughly
fourteen categories; several — GPU, VRAM, learned inference — have no
number because no GPU or learned component is in the shipped path, and
recording a zero for them would be worse than recording nothing. Storage
growth is exposed as an API but was not benchmarked over a long session.

### 5.4 Dead vocabulary, kept deliberately

Four of nine `EVENT_KINDS` are never emitted (`segment_started`,
`backend_downgraded`, `mapping_stalled`, `build_completed`).
`KeyframeSelector.is_stalled` is computed and never consulted.
`BackendCapabilities.preferred_window` is declared and never used —
`build()` passes an entire segment as one window.

None of these is a correctness problem, and all three are cheap to keep,
but they are named here so a future reader does not assume the vocabulary
is a description of behaviour. A consumer must tolerate an unknown event
kind and must not assume the reserved four will never appear.

### 5.5 Nothing is physically validated

Unchanged, and unchangeable without hardware. Distortion is completely
unexercised, since the synthetic input is a perfect pinhole. Whether
intrinsics scale linearly across DAT's three resolutions is deliberately
`null`. Rolling shutter, auto-exposure, real motion blur and JPEG
artefacts have never been seen by this code.

The first physical test procedure is in the V1 report §8 and is now
executable end to end, because §3.1 fixed the step that was not.

---

## 6. Documentation corrections

- `CARTRIDGE-GROUNDWORK.md` cited `tower/world_builder/capture.py`. The
  file is `tower/capture.py`, and the distinction is the whole point of
  that row — capture is shared infrastructure, not a cartridge's.
- `CARTRIDGE-GROUNDWORK.md` had no entry for **Translator** or
  **Experimental CV** despite both having module docs. Added.
- The "infrastructure still missing" list said multi-consumer frame
  distribution does not exist. More precisely: `ModuleContainer` is still
  a registry of one, but `frame_observers` is a real list and is now
  populated in production. The list has been corrected rather than
  deleted — the blocker is the *module* slot, not the observer channel.
- `docs/agent-handoffs/TOWER-TO-IOS.md` did not exist. It does now, and
  it describes only surfaces that actually exist.

---

## 7. Verdict

World Builder V1 is closed. The engine is complete behind a clean
interface, the integration boundary is documented and pinned by a test,
live incremental viewing works on the Tower without spending the
architecture decision that would have made it easy, and the remaining
gaps are named rather than smoothed.

The next thing this project needs is not more World Builder. It is
**physical footage**, which unblocks calibration, the standing V0.9.3
acceptance gate, the drift question in §5.2, and every claim currently
labelled synthetic.
