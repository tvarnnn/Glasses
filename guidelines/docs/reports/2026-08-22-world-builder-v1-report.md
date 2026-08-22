# World Builder V1 — Implementation Report

Status: **ENGINE COMPLETE, PHYSICALLY UNVALIDATED.** Branch
`world-builder/v1`, off `master @ b591e30`.

Every measurement below was produced from **synthetically rendered
imagery**. Per `02-DEVELOPMENT-RULES.md` Rule 3 the numbers are reported
exactly as measured, and per the standing V0.9.3 acceptance gate **none
of them may be cited as validation for the platform's own camera.** No
Ray-Ban footage exists anywhere on this machine; that is not an oversight
in this run, it is the reason the run is shaped the way it is.

---

## 1. What was built

A monocular mapping engine that creates a world, runs a mapping session,
evaluates and rejects frames, selects keyframes on measured information,
reconstructs relative geometry where the data supports it, persists
everything, survives process restart, and can be reloaded and inspected
cold.

```
tower/world_builder/
  schema.py      frozen conventions: pose contract, scale states, statuses
  records.py     World / Session / Keyframe / KeyframeEdge / intrinsics / scale
  store.py       atomic JSON + append-only JSONL + purge + writer lock
  frontend.py    decode, sharpness, LK tracking, motion summary   (cheap)
  keyframes.py   information-based selection policy                (cheap)
  backend.py     the geometry seam
  backends/      unposed (no intrinsics) and classical SfM (intrinsics)
  geometry.py    two-view primitives and the degeneracy criterion
  engine.py      observe() cheap, build() expensive
  events.py      the durable incremental-update journal
  capture.py     raw dataset recording, off by default
  inspect.py     cold reload and reporting

scripts/
  world_build_session.py     offline driver
  world_inspect.py           reload, report, --trajectory, --verify
  calibrate_charuco.py       intrinsics from board views
  world_builder_benchmark.py stage timings
```

### The governing design decision

**Calibration state gates what the pipeline may CLAIM, not whether it
exists.**

| Intrinsics | Backend | Produces | Scale |
|---|---|---|---|
| unknown — the real Ray-Ban case today | `UnposedBackend` | covisibility edges and 2-D measurements; **no poses** | `unknown` |
| known — synthetic tests, and real glasses once calibrated | `ClassicalTwoViewBackend` | incremental SfM: poses + triangulated points | `relative` |

Same pipeline, same journals, same inspector. The day a ChArUco
calibration lands, real footage moves from the first row to the second
with **no code change** — `select_backend` simply picks differently.
Nothing anywhere fabricates an intrinsic to keep the pipeline moving.

---

## 2. Measured results

### Live path — per delivered frame

| Resolution | JPEG | decode | sharpness | tracking | **total** |
|---|---|---|---|---|---|
| **360×640** (delivered today) | 45 KB | 0.33 ms | 1.33 ms | 3.06 ms | **4.71 ms** |
| 504×896 | 69 KB | 0.49 ms | 2.65 ms | 3.49 ms | 6.63 ms |
| 720×1280 | 101 KB | 0.80 ms | 5.61 ms | 4.49 ms | 10.90 ms |

At the delivered ~3.3 fps the interval is ~300 ms, so the live path runs
at a **1.6% duty cycle**. It is not a compute problem and no effort was
spent optimising it.

### Build — offline, never on the event loop

8 keyframes → 7 poses solved → 4,367 points in **59.3 ms** (7.4 ms per
keyframe).

### End-to-end

16 synthetic frames → 6 keyframes accepted (10 rejected,
`insufficient_motion`) → 5 solved poses → 2,944 points → `scale:
relative` → inspected from a cold process → `--verify` clean.

### Trajectory accuracy against ground truth

A walk with deliberately **unequal** 0.30 / 0.60 / 0.30 m spacing:

| | first step | middle step | last step |
|---|---|---|---|
| truth | 1.00 | **2.00** | 1.00 |
| recovered | 1.00 | **1.79** | 0.94 |

Umeyama-aligned residual: **1.32% of path length.** The 1.79-versus-2.00
error is real accumulated scale drift and is exactly what bundle
adjustment would reduce.

---

## 3. Findings that changed the design

Three ideas were implemented and then **removed or rejected on
measurement**. They are recorded here because each is attractive enough
that a successor will otherwise re-invent it.

### 3.1 `r_H` does not discriminate degeneracy in a room

ORB-SLAM's homography-versus-fundamental ratio at 0.45 is what
`scripts/feature_trackability.py` already uses and what V0.9.3 reported.
Measured across the full range from total degeneracy to healthy parallax
it moved only **0.410 → 0.359** — never crossing its own threshold, so
the rule classifies **every** pair as rotation-dominant.

That is not a defect in `r_H`. It asks whether a homography suffices,
which is true both for pure rotation **and** for a plane-dominated scene,
and a room is nothing but planes. It is still computed and persisted per
edge for continuity with V0.9.3. It is not the gate.

### 3.2 Pixel displacement is not parallax

A pure rotation moved pixels **18.4 px** with zero baseline — more than a
real 5 cm sideways step (4.3 px). Any displacement-based gate passes
exactly the case it exists to catch.

### 3.3 The homography-residual gate was built, then deleted

A homography exactly explains pure rotation, so a near-zero residual
should mean "no baseline". It works for cleanly separated motions and
fails for realistic ones. Residual ÷ displacement:

| motion | ratio | |
|---|---|---|
| rotation only, 1° | 0.01110 | |
| rotation only, 12° | 0.00581 | |
| strafe 0.05 m | 0.17785 | real translation |
| rotation 2° + 0.15 m | 0.00812 | real translation |
| **rotation 4° + 0.25 m** | **0.00500** | real translation, **lowest of all** |

The distributions **overlap**, so no threshold exists. Same mechanism as
`r_H`: when a head both turns and moves, the rotation dominates the pixel
motion and the homography absorbs it. This is the measured form of what
V0.9.3 found when 53.69% of consecutive pairs came back degenerate. A
regression test pins the negative result.

**Consequence — the responsibility split:** the keyframe policy answers
*"is this frame usable and has enough happened?"* from cheap
intrinsics-free signals; the geometry backend answers *"does this pair
carry triangulatable geometry?"* using **median triangulation angle**,
which needs intrinsics and does separate cleanly (0.11–0.42° degenerate
versus 0.54°+ usable, threshold 0.5°). When intrinsics are unknown the
second question is unanswerable — which is precisely why the uncalibrated
backend returns no poses rather than guessing.

### 3.4 Preprocessing does not help

Benchmarked raw against gaussian3/gaussian5/sharpen/CLAHE/bilateral. No
variant produced a consistent improvement; `gaussian5` destroyed 16% of
keypoints (1455 → 1226) and `sharpen` cost 11% of matches. The Laplacian
earns its place as a **measurement** instead — variance separates sharp
from blurred by 17× (662 → 38) in well under a millisecond, so blur is
rejected before any expensive stage.

### 3.5 A fabricated trajectory, caught by review

The first backend chained independent two-view solutions. Every
`recoverPose` translation is unit-length, so the chained path had a
**constant step length regardless of how far the camera actually
travelled** — a smooth, confident, entirely invented trajectory. No test
caught it because every geometry test used exactly two keyframes.

Fixed by real incremental SfM (initialise, triangulate, then PnP against
accumulated landmarks). Four-keyframe tests with unequal spacing now
cover it — that is the only shape that distinguishes real scale
propagation from normalisation.

### 3.6 Two silent convention bugs, caught by ground truth

`recoverPose`'s `t` is camera 1's position in camera 2's frame, not the
motion direction — this read as **179° of error** while the geometry was
already correct to 0.075°. And its `R` is the transpose of the intuitive
composition, which made a 2° sweep read as a uniform 4° error.

Both are exactly the silent-mirroring failure `POSE_CONVENTION` refuses
to guess at, and both were invisible until compared against a known
answer. Each conversion now lives in one documented function.

---

## 4. Honest limits

**Scale is never metric.** `relative` means internally consistent with an
arbitrary unit fixed by whatever the first solved baseline happened to
be. `format_distance()` is the single choke point that turns a number
into text, and only a `measured` scale licenses a metre. A test pins it.

**Drift is unbounded.** There is no loop closure, no bundle adjustment,
no relocalisation. Measured drift is 1.32% of path length over a 1.2 m
walk; it grows with path length and nothing corrects it.

**Poses in different segments are not in a common frame.** Tracking loss
starts a new segment and the records say so rather than implying
continuity.

**Bundle adjustment was deliberately declined.** `pycolmap 4.1.1` was
verified as a 23.5 MB cp312 Windows wheel, BSD-3, needing no compiler and
bundling Ceres — so the usual objection is simply false. It was still not
taken, because there is no measurement yet showing drift it would fix.
The trajectory-residual test is that measurement, and `pycolmap` is the
pre-verified answer waiting behind it.

**No ML.** torch is CPU-only on this host and there is no C++/CUDA
compiler, so a learned geometry backend could not be evaluated. It is
also the most retrofittable component: it consumes stored keyframes, so
it can be run over the corpus on any future date. The footage is the
scarce resource; the model is not.

---

## 5. What was NOT built, and why

| Not built | Reason |
|---|---|
| Loop closure, retrieval descriptors, pose-graph optimisation | The brief asks for loop-closure *foundations*. Foundations are stable ids, segments, and the revision stamp — all present. Descriptors alone would cost 4.81 MB/min, 3.5× the imagery, to save 3.83 ms of recompute |
| Gauge transform algebra | `frame_revision` is stamped but never advanced in V1, so a log would govern the empty set. The **stamp** is un-retrofittable and is built; the composition code is retrofittable and is not |
| Numbered checkpoints, `HEAD.json`, mmap | V1 has no concurrent reader — capture, build and inspect are separate processes. That removes the problem all three verified Windows mitigations existed to solve |
| In-process event bus | Nothing can subscribe while the module contract is scalar-only. The append-only journal already IS the update stream |
| Environmental fiducial/marker subsystem | Evaluation-only value in V1, and the ChArUco board is already a known-size fiducial. A marker-derived scale estimate also inherits the reconstruction's local drift, which the proposed guards do not catch |
| Face redaction | Verified: this OpenCV build has **no** `CascadeClassifier`, no cascade XML, and no ONNX model; the upstream model URL returns a Git-LFS pointer, not a model. There is also no face imagery anywhere to validate against. `Session.redaction` records provenance so the boundary exists |
| Free-roam viewer | Requires one coherent global frame, surfaces, and coverage. With segment breaks, sparse points and unbounded drift it would be a fake |
| Any viewer | `WORLD-BUILD.md` says do not build it yet. `inspect.trajectory()` persists everything a viewer needs |

---

## 6. The integration boundary

**World Builder is deliberately NOT registered as a production module.**
There is no `tower/modules/world_builder.py` and nothing in
`main.py::_build_cv_module`. The blockers, verified in source:

| Location | Gap |
|---|---|
| `ws.py` | `process()` is synchronous on the event loop and takes only `bytes`; `observe()` needs `received_at`, `source_seq`, `tx_seq` |
| `ExperimentResult` | Five scalars — cannot carry a keyframe decision or a world delta |
| `main.py::_build_cv_module` | Registry of one; a second module id **is** the V1.0 trigger, and V1.0 is untriggered |
| `container.LIFECYCLE_TIMEOUT_S = 10.0` | A stop-time build would exceed it. That bound is V1.1 hardening, and V1.1 is **BLOCKED** |

The engine is complete behind a clean interface. The future diff is a
~40-line `Module` subclass, one branch in `_build_cv_module`, and passing
frame metadata through `process()`.

**Product cost, stated plainly:** V1 is *Start → Walk → Stop → the world
appears*, not *watch it build live*. Live progressive rendering is the one
part of the product ruling that genuinely requires the blocked lifecycle
work.

The **capture recorder** IS wired into the live path, because recording is
not processing: it returns no module result and does not make World
Builder a second active module (Rule 2 respected). It is off by default.

---

## 7. Privacy posture

This module retains raw imagery, unlike every module shipped so far.

- `Session.retains_raw_imagery = True` and `privacy_tags` carry
  `raw-imagery`, `first-person`. Both current CV modules truthfully
  declare `False`; that flip is the visible signal the posture changed.
- Capture is an **Explicit Dataset-Recording Session** under
  `06-PRIVACY-DATA.md`: off by default, manually started and stopped,
  bounded in seconds *and* bytes, purgeable.
- `purge_world()` and `CaptureRecorder.purge()` perform real deletion and
  report what they could **not** remove. A purge that cannot delete
  everything must never claim success.
- `Session.redaction = "none"` records provenance now. Without it, the day
  redaction ships there would be no way to tell whether an older session's
  imagery was filtered, so every historical session would have to be
  assumed unredacted forever.
- Every persisted pixel passes through one function
  (`store.write_keyframe_image`, `capture.write_frame`). Whatever policy
  is eventually chosen, it is a change to one place.

**Unresolved and deliberately not decided here:** bystander policy.

---

## 8. Physical validation still required

Nothing below can be answered without real glasses.

1. Real intrinsics and, especially, the **distortion model** — completely
   unexercised, since the synthetic input is a perfect pinhole.
2. Whether intrinsics scale linearly across DAT's three resolutions
   (`scales_linearly_across_resolutions` is deliberately `null`, and
   intrinsics refuse to rescale until it is established).
3. Rolling shutter, auto-exposure, real motion blur, JPEG artefacts.
4. Whether real indoor scenes provide enough texture.
5. The V0.9.3 acceptance-gate re-run on real DAT footage.
6. End-to-end mapping quality.

### First physical test procedure

1. Print the board: `calibrate_charuco.py --generate-board board.png`.
   Mount flat and rigid. **Measure the printed square** — the metres in
   the script must match reality.
2. Arm capture on the Tower (`app.state.capture_recorder`), connect the
   glasses, `stream_start`, walk the board through the frame at varied
   distances and angles up to ~45°, covering all four image corners,
   `stream_stop`.
3. `calibrate_charuco.py --frames <capture>/frames --out intrinsics.json`.
   Check reprojection RMS and view count. Repeat at a second DAT
   resolution to establish linearity.
4. Record a room walk with capture armed.
5. `world_build_session.py --frames <capture>/frames --intrinsics
   intrinsics.json`.
6. `world_inspect.py --world <id> --verify --trajectory`.
7. Re-run the V0.9.3 experiments on the same footage to discharge the
   acceptance gate.

**Recommended next step after physical validation:** measure loop-closure
residual on a closed walk. If drift exceeds a few percent of path length,
that is the measured trigger for `pycolmap` bundle adjustment — the
decision the V1 architecture deliberately left open.

---

## 9. The late additions — decisions and follow-up plan

Four requirements were added after implementation began, gated behind
"core correctness wins" and required to be independently challenged. They
were challenged; the verdicts and their evidence are below.

### 9.1 Calibration / fiducials — **calibration BUILT, markers DROPPED**

**ChArUco calibration is built** and is the highest-value item on the
list: it is the switch from "no poses" to "poses". It was also arguably
mis-filed as a stretch goal — it is core, and it is the only addition that
changes what the product *is*.

**Environmental markers (AprilTag/ArUco) were dropped.** `cv2.aruco` is
available, so capability was not the constraint. Three reasons:

1. **Their non-evaluation value is a V2 value.** A marker is a repeatable
   cross-session 6-DoF anchor — genuinely useful for relocalisation and
   loop closure, neither of which V1 has. Building an anchor before its
   consumer is speculation.
2. **The proposed guard has a hole.** The plan's rule — keep relative
   geometry, hold scale separately with confidence, never mutate the
   graph — is right, and it validates only the *marker observation*.
   `meters_per_unit` is (metric distance to marker) ÷ (world-unit distance
   to marker), and the **denominator comes from the drifting
   reconstruction**. Multiple nearby observations agree with each other
   *because they share the same local drift*, so "cross-frame
   consistency" is the failure mode wearing the costume of the check.
   Marker distance error also tracks focal-length error roughly 1:1, so a
   "metric" lock is only as metric as the calibration behind it.
3. **A simpler option already exists.** The ChArUco board is itself a
   known-size fiducial. Photograph it in the room and you have intrinsics
   *and* a metric reference, with no second subsystem. The plan treated
   ChArUco and ArUco as two work items; they are one.

*Follow-up when wanted:* implement marker detection against
`solvePnPGeneric` + `SOLVEPNP_IPPE_SQUARE` — note
`cv2.aruco.estimatePoseSingleMarkers` **does not exist in OpenCV 5**. Use
markers first for evaluation only, and require the scale estimate to be
validated against a *second, independent* reconstruction region before it
is ever recorded.

### 9.2 Face redaction — **DROPPED; provenance field BUILT**

Verified directly on this install: `cv2.CascadeClassifier` **does not
exist** in OpenCV 5, `cv2.data.haarcascades` contains **zero** `.xml`
files, there are **zero** `.onnx` models in the venv, `FaceDetectorYN`
requires a model file it does not have, and the upstream model URL returns
a **Git-LFS pointer** rather than a model. Independently, there are **zero
images of any kind** anywhere in this repository, so a detector could not
be validated even if one were obtained.

Two further findings that change the shape of the eventual work:

- **Redaction is a net positive for geometry, not a cost.** Measured on a
  110×130 px region: blurring destroyed the features inside it (116 → 1)
  but ORB's `nfeatures` cap held the total at 1500 either way — the budget
  was *reallocated*. And the destroyed features were on a moving person,
  which is outlier poison for static-scene epipolar geometry anyway.
- **The real hazard is that redaction CREATES features.** After blurring,
  **100%** of surviving near-region keypoints sat on the redaction
  boundary; after a solid fill, 112 of 116. Those artifacts track the
  *person*, not the scene, and match cleanly between frames — producing
  consistent-looking, entirely wrong geometry. A hard-edged box is the
  worst possible redaction shape; feathering, or passing the region as
  ORB's `mask` argument, is materially better.

There is also an **architectural conflict to resolve before any code**:
plan B's ordering is raw → geometry → redact → persist, but this engine
computes geometry **from the persisted keyframes** during `build()`.
Redacting before persistence means geometry runs on redacted pixels.
Persisting both raw and redacted doubles the imagery and defeats the
purpose. **That is a product decision, not an engineering one.**

*Built instead:* `Session.redaction = "none"`, the one un-retrofittable
piece. Without it, the day redaction ships there is no way to tell whether
an older session's imagery was filtered, so every historical session must
be assumed unredacted forever.

*Follow-up:* resolve the ordering conflict; obtain YuNet via the LFS media
endpoint as a vendored dependency with its own licence review; feather the
mask; validate on real footage against real faces before trusting any
threshold.

### 9.3 Recorded-path first-person replay — **PERSISTENCE BUILT, no viewer**

The Tower needs **no feature** for this. `inspect.trajectory()` already
returns ordered keyframes with their solved poses, segment index, and
image paths — everything a viewer needs to show the path and step into the
wearer's original view at any point. Refused poses come back as
`pose: None` with their degeneracy reason so a viewer shows the gap
honestly rather than interpolating across it.

`WORLD-BUILD.md` says not to build the viewer yet, and building "for a
viewer that does not exist" is the speculative half.

*Worth noting:* a keyframe contact-sheet with `pose_status` beside each
thumbnail delivers most of the user value ("see what the wearer saw here")
and stays honest even where the pose was refused. That is probably the
right first viewer, not a 3-D camera.

### 9.4 Free-roam — **DROPPED**

It would be a fake, for three nameable reasons: there is no single
coherent global frame (segment breaks are explicitly *not* in a common
frame, and drift is uncorrected); ORB yields a sparse point set and finds
**nothing** on the blank wall a free-roam camera most needs; and
`WORLD-BUILD.md` requires unknown space to stay unknown, so an honest
free-roam camera spends most of its time looking at nothing.

*Gate before revisiting, to be met on real footage:* loop-closure residual
below ~2% of loop length, and wall planarity RMS below ~2% of room extent.
Neither is producible without physical capture. Until then, orbit around
the point cloud is the honest substitute — an external view never implies
occupancy or that the camera is standing anywhere real.
