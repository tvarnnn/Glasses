# Plan — World Builder V1

Status: **implementation plan, reconciled from three independent research
tracks 2026-08-22.** Branch `world-builder/v1` off `b591e30`.

Primary evidence: `docs/superpowers/research/2026-08-21-world-builder-readiness.md`.
That report is not re-derived here. This plan records only what it
*changes*, and why.

---

## 1. The reconciliation

Three tracks were run: an implementation architect, a mandatory simplicity
reviewer ("what can we NOT build?"), and an environment/feasibility probe.
The first two disagreed sharply, and the disagreement was productive.

**The simplicity reviewer argued for a keyframe corpus builder with no
geometry at all** — no poses, no triangulation, no 3D — on the grounds that
without intrinsics, essential-matrix pose is invalid, and with no Ray-Ban
footage nothing is validatable tonight.

**The architect argued for a full engine** — submap pose graph, loop
closure, retrieval, Sim(3) optimisation, numbered checkpoints, an event
bus, quality metrics.

Both are partly right, and the resolution is a single distinction the
simplicity review conflated:

> **"We cannot validate reconstruction *quality*" is not the same claim as
> "we cannot verify the geometry code is *correct*."**

Reconstruction quality needs real Ray-Ban footage and calibration. We have
neither, and no claim about either will be made. But *correctness* is
verifiable tonight, exactly and numerically, because a synthetic scene
gives us ground-truth camera poses and ground-truth intrinsics that real
footage never gives us. Building the geometry and testing it against known
answers is honest; claiming it reconstructs a real room is not.

The architect supplied the reframing that makes this buildable:

> **A feed-forward pointmap model (DA3) is a *backend*, not an
> architecture.** The world model, keyframe policy, persistence, event
> journal, and evaluation harness are all GPU-free and are most of the
> work. Build the seam; the engine choice becomes a one-file diff.

### The governing design decision: calibration-gated geometry

Calibration state gates what the pipeline may **claim**, not whether the
pipeline exists.

| Intrinsics | Backend | Produces | Honest label |
|---|---|---|---|
| unknown (real Ray-Ban today) | `UnposedBackend` | covisibility edges, 2D track/inlier/`R_H` measurements | no poses, no 3D — and it says so |
| known (synthetic tests; future calibrated glasses) | `ClassicalSfmBackend` | relative poses + triangulated landmarks | **relative scale**, never metric |

Same code path. The day a ChArUco calibration lands, real footage moves
from the first row to the second with no code change. Nothing is ever
fabricated: a backend that cannot justify a pose returns `None` plus a
`degeneracy` reason, which is a first-class answer rather than an error.

---

## 2. What is built, and what is refused

### BUILD

| Component | Why it earns its place |
|---|---|
| `schema.py` — frozen conventions, `SCHEMA_VERSION` | Self-describing artifacts; a reader that meets an unknown convention **refuses rather than guesses** |
| `records.py` — World, Session, Keyframe, Intrinsics, ScaleState | Mirrors `object_memory/records.py` exactly, including reserved-but-unused fields |
| `store.py` — atomic JSON + append-only JSONL + purge + writer lock | Mirrors `ObservationStore`, which is already proven and already survived two rounds of its own bug fixes |
| `capture.py` + one `ws.py` hook, **off by default** | The only way real frames ever reach disk. Bounded by seconds and bytes (Rule 15) |
| `frontend.py` — decode, sharpness, LK tracking, parallax, `R_H` | Measured at ~5 ms against a ~300 ms budget. Intrinsics-free, clock-free |
| `keyframes.py` — information-based selection policy | Turns 53.69% rotation-dominant into 12.41% (V0.9.3's own measurement) |
| `backend.py` + `backends/{unposed,classical}.py` | The seam. Both backends run today, CPU-only, zero new dependencies |
| `engine.py` — `start_session` / `observe` / `stop_session` / `build` | `observe()` is cheap; `build()` is expensive and never on the event loop |
| `events.jsonl` — durable, dense `event_id` | Satisfies "expose incremental updates" with no wire-protocol change |
| `inspect.py` + `scripts/world_inspect.py` | Reload and inspect after process restart, cold |
| `scripts/world_build_session.py` | Offline driver — live-vs-offline is a *driver* choice, not an architecture choice |
| `scripts/calibrate_charuco.py` | Testable tonight via a synthetically rendered board recovering known `fx, fy, cx, cy`. Unlocks the calibrated path |

### REFUSED — and the reason each is refused, not merely deferred

| Refused | Reason |
|---|---|
| Loop closure, retrieval descriptors, pose-graph optimiser, bundle adjustment | The plan asks for loop-closure **foundations**, not loop closure. Foundations = stable ids + segments + the revision stamp. Descriptors cost 4.81 MB/min — 3.5× the imagery — to save 3.83 ms of measured recompute. **On BA specifically see the note below: the dependency is available and cheap; what is missing is a measurement justifying it** |
| Gauge **transform algebra** | V1 never bumps `frame_revision`, so the log would govern the empty set. The *stamp* is built (un-retrofittable); the composition code is not (retrofittable, and would be written against guesses) |
| Numbered checkpoints, `HEAD.json`, GC, mmap concurrency | V1 has no concurrent reader: the flow is capture → build → inspect, in separate processes. That removes the problem all three Windows mitigations existed to solve. One `derived/` directory, rebuilt wholesale, staleness detected by `input_digest` |
| In-memory event bus | Nothing subscribes in-process in V1, because module registration is refused (§4). `events.jsonl` is durable and sufficient |
| Any ML backend (DA3, MiDaS, anything) | torch is CPU-only; unvalidatable tonight; and — decisively — **retrofittable**, because it consumes stored keyframes. The footage is the scarce resource, not the model |
| Coverage voxel grids, per-point confidence arrays, dynamic masking | Coverage needs poses at a known scale; masking needs a GPU model. Both arrive with their inputs |
| Camera-height / planarity quality metrics | Need a floor fit over a metric-ish reconstruction. Recorded as the first thing to build once poses exist |

### Bundle adjustment: available, cheap, and deliberately not taken yet

`pycolmap 4.1.1` was verified this session as a **23.5 MB cp312
win_amd64 wheel, BSD-3-Clause, requiring no compiler** — it bundles Ceres,
SuiteSparse, OpenBLAS and even `msvcp140.dll`, and its only Python
dependency is numpy. It exports `BundleAdjuster`, `CeresBundleAdjuster`,
`run_rotation_averaging`, `pose_graph`, `Sim3d`, and the full cost-function
set. Its CUDA path being Linux-only is irrelevant: CPU BA is first-class,
and `_preload_cuda_deps()` explicitly no-ops off Linux. The "archived repo"
concern is a red herring — pycolmap moved into the active `colmap/colmap`.

So the usual objection to bundle adjustment (heavyweight, needs a
toolchain, Linux-first) is simply **false here**.

It is still not taken for V1, for a different and better reason: **there is
no measurement yet showing drift that BA would fix.** Adding an optimiser
before measuring the error it targets inverts this repository's stated
order — correctness, then instrument, then profile, then accelerate — and
is the same discipline under which TensorRT/CV-CUDA were previously
declined. V1 measures per-segment drift against synthetic ground truth;
that measurement is the trigger, and `pycolmap` is the pre-verified answer
waiting behind it.

### The correction the architect found in the readiness report

Readiness §8.4 assumed every `frame_revision` bump is a global Sim(3) that
old coordinates can be composed forward through. **That is false for a
loop closure that re-anchors one submap** — it moves part of the world and
is not a similarity of the whole. Composing through it yields confidently
wrong positions, which is precisely the failure the gauge design exists to
prevent.

V1 does not implement gauge composition, so this is not a live bug. It is
recorded in `schema.py` and in the Object Memory contract so that whoever
builds it inherits the correction:

- gauge entries must be tagged `global_sim3` vs `non_similarity`;
- composition must **raise** across a `non_similarity` entry, never guess;
- and the frozen anchor contract gains two fields **now**, while zero
  anchors exist: `anchor_keyframe_id` and `position_in_anchor_frame`. With
  those, an anchor re-resolves after *any* revision change by reading its
  anchor keyframe's current pose. Without them, the first loop closure
  permanently and undetectably invalidates every earlier anchor.

---

## 3. Geometry: incremental SfM, relative scale, per segment

With known intrinsics the classical backend does standard incremental SfM
using only OpenCV:

```
pair init:  ORB -> ratio-test match -> findEssentialMat(USAC_MAGSAC)
            -> recoverPose  -> triangulatePoints
grow:       solvePnPRansac against triangulated landmarks
            -> triangulate new observations
```

- **Scale is fixed arbitrarily by the first pair's unit baseline.** The
  world is therefore internally consistent and globally unscaled:
  `scale.state = "relative"`, `meters_per_unit = null`. No code path prints
  metres while scale is not `"measured"`, and a test pins that.
- **Degeneracy is refused, not fudged — and the gate is NOT `r_H`.**

  The repository's existing degeneracy signal is `r_H`, ORB-SLAM's
  homography-vs-fundamental ratio at 0.45, used in
  `scripts/feature_trackability.py` and reported in V0.9.3. **A measured
  sweep on synthetic ground truth this session shows `r_H` is a weak
  discriminator for this purpose:** across a baseline sweep from total
  degeneracy to healthy parallax it moved only 0.410 → 0.359, never
  crossing its own threshold, while the truth went from unusable to exact.

  | baseline | median parallax | `r_H` | **cheirality frac** | trans-dir err |
  |---|---|---|---|---|
  | 0.000 m | 0.069° | 0.410 | **0.014** | undefined |
  | 0.005 m | 0.090° | 0.415 | **0.019** | 68.1° |
  | 0.020 m | 0.282° | 0.418 | **0.003** | 64.0° |
  | 0.050 m | 0.677° | 0.398 | **0.997** | 10.0° |
  | 0.200 m | 2.714° | 0.359 | **1.000** | 2.7° |

  The **cheirality-inlier fraction returned by `recoverPose`** is a
  near-binary switch at roughly **0.5° median parallax**. That is the gate:
  `median_parallax_deg` plus `cheirality_fraction`, not `r_H`.

  This matters because the failure it prevents is severe and now
  deterministically reproducible: at zero parallax `recoverPose` recovered
  rotation well *on median* (0.18°) but with a **maximum error of
  179.999°** — the four-fold decomposition disambiguation coin-flips, so a
  degenerate pair can return a confident, mirrored, completely wrong pose.

  `r_H` is still computed and recorded per edge, because it is what V0.9.3
  measured and continuity of evidence matters. It is no longer the gate.

  When the gate fires: rotation is kept, translation direction is
  **refused**, `pose_status = "rotation_only"`.
- **Tracking loss starts a new segment.** Poses in different segments are
  not in a common frame, and the records say so. This is the submap
  foundation without the optimiser.
- **Drift is unbounded without loop closure.** Stated in the docs and in
  the inspector output rather than hidden.

Correctness is asserted against synthetic ground truth via Umeyama
similarity alignment (test helper only — a reconstruction that is correct
up to a similarity is exactly what monocular SfM promises).

---

## 4. The integration boundary — where this stops

`tower/modules/world_builder.py` is **not** built, and nothing is
registered in `_build_cv_module()`. The blockers, verified in source:

| Location | Gap |
|---|---|
| `ws.py:55` | `process()` is synchronous on the event loop and takes only `bytes`; `observe()` needs `received_at`, `source_seq`, `tx_seq` |
| `ws.py:97-106`, `ExperimentResult` | Result channel is five scalars — cannot carry a keyframe decision or a world delta |
| `main.py::_build_cv_module` | Registry of one. A second module id **is** the V1.0 trigger, and V1.0 is untriggered |
| `container.py:16` `LIFECYCLE_TIMEOUT_S = 10.0` | A stop-time build over 300 keyframes exceeds it. That bound is V1.1 hardening, and V1.1 is **BLOCKED** |

`ModuleDataBehavior` does *not* bite: `retains_raw_imagery` already
exists, and World Builder declares `True` where both current modules
truthfully declare `False`. That flip is the visible signal that the
privacy posture changed.

**Product cost of stopping here, stated plainly:** V1 is *Start → Walk →
Stop → the world appears*, not *watch it build live*. Live progressive
rendering is the one part of the ruling's experience that genuinely
requires the blocked lifecycle work.

The capture recorder *is* wired into the live path, because recording is
not processing: it does not return a module result and does not make World
Builder a second active module (Rule 2 respected).

---

## 5. Slices

| # | Slice | Key tests |
|---|---|---|
| 1 | schema, records, store | atomic write leaves no tmp; corrupt line tolerated; unknown schema/convention refused; purge removes tmps; lock reclaimed on dead pid |
| 2 | capture + `ws.py` hook | off by default; image fsynced before journal line; bounded by seconds/bytes; ws path unchanged when off; hook failure never drops a frame result |
| 3 | frontend | sharpness lower on blur; pure rotation flagged; survival drops on scene change; **no decision function reads a clock** |
| 4 | keyframes policy | blurred never promoted; overlap floor forces accept; rotation-dominant needs more parallax; max gap does not force a keyframe; reason histogram totals |
| 5 | backends | classical recovers known R and t-direction; returns `rotation_only` under pure rotation; raises without intrinsics; unposed returns `None` poses with real degeneracy; **backends import nothing from store/engine** |
| 6 | engine + build + derived geometry | observe is cheap and never calls the backend; build writes derived + digest; deleting `derived/` rebuilds identically; journal is authoritative and pose-free |
| 7 | inspect + scripts | reload after simulated restart; refuses unknown convention; never prints metres while scale unknown; prints `unknown` not `0` |
| 8 | ChArUco calibration | synthetic board round-trips known `fx, fy, cx, cy`; too few views refuses rather than emitting intrinsics |
| 9 | docs + adversarial review | — |

Baseline to preserve and grow: **214 passed, 3 skipped**.
