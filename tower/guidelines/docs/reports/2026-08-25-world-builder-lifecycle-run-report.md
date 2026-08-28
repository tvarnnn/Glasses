# World Builder lifecycle hardening — run report

**Date:** 2026-08-25
**Branch:** `integration/world-builder-lifecycle-v1`
**Starting commit:** `35214a1`
**Prompted by:** the first physical World Builder test, 2026-08-24.

Read `docs/superpowers/specs/2026-08-25-world-builder-lifecycle-design.md`
for the design and its evidence. This file records what was measured and
what was verified, and separates the two things that are easy to blur:
what a test proved, and what hardware proved.

---

## The three corrections the physical artifacts forced

All three come from files still on disk under `data/`, not from
recollection of the session.

### 1. "Camera poses: 36" was not 36 poses

```json
{"backend_id": "unposed", "keyframes": 155, "poses_solved": 0,
 "poses_refused": 119, "points": 0, "segments": 36, "scale_state": "unknown"}
```

`poses_solved` is zero. `points.json` is literally `{"points": []}`. All
119 non-anchor pose rows carry `degeneracy: "no_intrinsics"`, and all 119
edges carry `cheirality_fraction: null` — **no geometric gate was ever
evaluated**. The 36 were segment anchors: identity rotation, zero
translation, all at the same point.

The system did not cross the pose boundary. It produced keyframes,
tracking and a persisted world, which is real and worth having, and the
number beside "Camera poses" was an artefact of `keyframes - refused`.

### 2. The lifecycle desync was ten captures, not a detaching follower

```
capture_id                          start      end   frames  end_reason   continues
2e6cffa275b24b7d87d68ec1d6a6cfdf      0.0    121.9     1395  disconnect   None   <- followed
                            ...105 s with no capture at all...
341b0fdac88a4b6f9d6ff720d4341690    226.8    256.9      259  disconnect   None
b058a6af58204483888ff0fb95e4bbbc    257.1    263.5       18  disconnect   341b0f
b1ab1d413c0544f0971d27038818fa44    263.6    272.0       20  stop         b058a6
79233e6486094060a57487225466db4a    272.0    280.1       16  disconnect   None
4fb8236c75904ddf91ee170754373e8c    283.7    296.2      104  disconnect   79233e
0f0c55b662fe4df189fa275bf3dd506d    303.3    344.2       75  disconnect   4fb823
b901bc7fce0c4f5fbd1e1282a28e8c38    344.2    374.9      309  disconnect   0f0c55
1a63a07ad3e24fdeb78c25677fe3dd4c    375.4    379.9        0  disconnect   b901bc
854e9688d2c54ae398eff4fb7c141522    380.0    435.0      610  stop         1a63a0
```

**The reconnect machinery worked, and this is its first physical
validation.** Captures chained through `continues_capture` across every
disconnect; the 105-second gap correctly produced no lineage, because it
exceeded `RESUME_GRACE_SECONDS = 90`; and `79233e` correctly declared no
predecessor despite starting the same second `b1ab1d` ended, because
`resumable_capture()` only offers a capture that ended by *disconnect*
and that one ended by a clean `stop`.

The follower did exactly the right thing and exited. Nothing started one
for the second walk, because nothing has ever started one.

### 3. Fragmentation outranks calibration

36 segments, ten of them a single keyframe. Segments share no coordinate
frame, so `scale_state` is forced to `unknown` and path length is refused
outright — and would be with perfect intrinsics. Calibration unlocks
geometry; fragmentation decides whether that geometry is a map.

---

## The measurement that settled an open question

`docs/agent-handoffs/WORLD-BUILDER.md` §9.4 recorded two disagreeing
synthetic results — a geometry audit seeing 9 segments from "spurious
`blurred` rejections cascading into `tracking_lost`", and an independent
walk seeing 1 — and left the thresholds alone pending a real walk.

All 1395 recorded frames were replayed through the **real**
`FrameTracker` and the **real** `KeyframeSelector`. The replay reproduces
the recorded run bit-identically: 155 keyframes, 35 losses, the exact
four-way rejection histogram, and **zero delta** against every persisted
`sharpness`, `survival_ratio` and `overlap_ratio` value.

**The stated suspect was wrong.**

| configuration | segments | keyframes | 1-kf segs |
|---|---|---|---|
| baseline (shipped that night) | 36 | 155 | 10 |
| `min_sharpness_ratio` 0.45 | 43 | 161 | 15 |
| `min_sharpness_ratio` 0.35 | 43 | 166 | 16 |
| `min_sharpness_ratio` 0.00 (disabled) | **49** | 176 | 22 |
| survival/overlap gates evaluated before blur | **40** | 154 | 16 |
| `overlap` 0.75 / `minsurv` 0.20 / `loss` 0.05 | **20** | 260 | **4** |

Loosening the blur gate makes segmentation monotonically **worse**. 77%
of blur rejections fire when `survival_ratio` is already below 0.15 —
they were *masking* losses that had already happened, and removing the
mask only reveals them sooner. Reordering the gates is worse for the same
reason.

**The real defect:** `overlap_ratio` is not an independent signal from
`survival_ratio`. They are equal in 1283 of 1358 measured frames, max gap
0.029, because on real footage tracks *die* rather than leave frame. The
`overlap_floor` rescue at 0.45 could therefore only fire in
`survival ∈ [0.35, 0.45)` — **36 frames out of 1395**, of which 28 were
already accepted. The one gate written to guarantee "a usable weak link
beats a broken chain" was very nearly dead.

### Verified again with the shipped constants

Re-run after the change landed, against the same real capture, using the
shipped `KeyframePolicy` rather than a simulated one:

```
SHIPPED POLICY: overlap=0.75 minsurv=0.20 loss=0.05 sharp_ratio=0.55
frames in journal: 1395

  keyframes accepted : 260
  segments           : 20
  single-kf segments : 4
  largest segment    : 45
  reasons            : {'session_seed': 20, 'insufficient_motion': 859,
                        'overlap_floor': 198, 'blurred': 227,
                        'parallax': 42, 'tracking_lost': 19,
                        'tracking_degraded': 30}
```

Also visible here, and worth keeping in view: **`overlap_floor` is now
the dominant promotion path** — 198 accepts against 42 for `parallax`.
That is a design shift, not just a threshold move.

### What this does NOT establish

One walk, one room, one wearer, one lighting condition, including a
stretch of near-black frames that dominates the absolute blur count.
These are a hypothesis about the Ray-Ban camera, not tuned constants.

It costs **+68% keyframes** (155 → 260), unbudgeted against storage, the
measured 20.5 ms/keyframe face redaction on the write path, and build
time.

And the thing that matters most is unmeasurable on this data: **whether
the extra keyframes improve the reconstruction**. That world has no
solved poses to check against, because the camera is uncalibrated. The
ORB / fundamental-matrix proxy shows the extra keyframes are not garbage
— inlier ratio flat at 0.63–0.65 across every configuration, no pair
below `MIN_INLIERS` — but a proxy is not the claim.

A second walk in a different space should reproduce the *ordering* of
that sweep before these constants are treated as settled.

### Why synthetic footage could never have settled it

Measured during the sweep: on the shipped synthetic sequences, **neither
policy loses tracking even once**. The perfect-pinhole renderer's tracks
neither die nor leave frame, so `survival_ratio` barely enters the rescue
band and synthetic footage does not exhibit segmentation at all. That is
why the 9-segment audit and the 1-segment walk could disagree
indefinitely.

---

## Real-capture image statistics

Independent of the policy work, sampled across the 1395 frames:

- median ORB keypoints **1334** of 1500 requested; median Laplacian
  variance **344**. The footage is mostly texture-rich and usable.
- a distinct degraded stretch in the back half (frames ~1500–2500 by
  `source_seq`) with 0–700 keypoints and variance as low as 2.1.
- **Tracking losses did not correlate with that stretch.** They begin at
  t+0.35 s, t+1.37 s, t+1.72 s and continue throughout, which is what
  first indicated a policy problem rather than a footage problem.

---

## PROVEN IN AUTOMATED TESTS

- A `stream_start` attaches a builder to the capture it just minted, with
  no manual step. Real subprocess, real capture, real world on disk.
- A reconnect produces **one** world and **one** worker; the successor
  capture is recorded in the first worker's lineage.
- `Start → walk → Stop` leaves exactly one world whose session names the
  streamed capture, with the session closed and the worker reaped.
- Geometry now appears **during** the walk (rebuilds observed at 2 and 4
  keyframes in the traced run).
- A subscriber is told about the world over the wire while the stream is
  open, reporting `calibration: uncalibrated`, `scale: unknown`,
  `pose_count: 0`.
- An uncalibrated build reports **0** positioned poses and its anchor
  count separately.
- The backend downgrade to `unposed` is announced and recorded.
- A worker that fails to spawn, or exits non-zero, is reported against
  its capture and never costs the stream its recording.

## PROVEN ON PHYSICAL HARDWARE

- The 2026-08-24 capture/reconnect lineage behaviour described above.
  That is the **previous** build.
- Nothing else.

## NOT YET PHYSICALLY VALIDATED

**Everything built on 2026-08-25.** The automatic follower attach, the
rebuild cadence, the keyframe policy change, the pose-count correction
and the startup scripts have run against synthetic frames, recorded
frames and a real subprocess — never against the glasses. The previous
version's physical validation does not transfer.
