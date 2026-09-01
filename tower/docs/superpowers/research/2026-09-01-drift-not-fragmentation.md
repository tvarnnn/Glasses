# Drift, not fragmentation

**Date:** 2026-09-01
**Branch:** `world-builder/tracking-recovery-v1`, from
`world-builder/fragment-registration-v1` @ `e847339`
**Corpus:** five replayed physical walks, 6,548 frames, plus the eight-capture
pinned A/B corpus and ground-truth synthetic scenes
**Status:** measured.

---

## 0. The result in one paragraph

The World Builder was believed to fail because tracking restarts too often: a
two-minute room walk arrived on the phone as 30 segments and 18 disconnected
fragments, and the obvious reading was that the tracker gives up too easily. It
does give up too easily, and that is fixed here. But it is not why the walk does
not become a world. **The forward-only pose chain drifts, badly and silently,
and everything downstream is a consequence of that.** On a perfect synthetic
strafe with nothing refused and nothing blurred, rotation error grows from
0.95° at six keyframes to 33.98° at forty, and the reconstruction contracts by a
factor of three. On the real 2026-09-01 walk the one segment that did survive
170 keyframes has camera centres reaching 8 × 10¹⁰ and points reaching
2.9 × 10¹³ — the largest coherent piece of geometry in the corpus is not
coherent. Cross-segment registration then refuses to place it, **correctly**,
because it solves a Sim3 and two pieces whose internal geometry disagrees should
not be glued together. Fragmentation was the symptom everybody could see; drift
was the thing making the fragments unmergeable.

---

## 1. Physical dataset provenance and baseline correction

This section exists because the experimental provenance was corrected
mid-investigation and the correction changes what "before" means.

**The physical walks were captured while the Windows Tower ran `main @
768cecf`.** `world-builder/fragment-registration-v1` was *not* active during any
physical run. Current `origin/main` has since advanced to `b5c9089` through the
CV Lab and Object Memory validation merges; that advance contains no World
Builder change and this branch does not descend from it.

Three baselines must therefore be distinguished, and are, throughout:

| | what it is | tip |
|---|---|---|
| **A — physical era** | the code that actually processed the walks | `main @ 768cecf` |
| **B — registration** | the branch this work descends from | `world-builder/fragment-registration-v1 @ e847339` |
| **C — this branch** | tracking recovery + bundle adjustment | `world-builder/tracking-recovery-v1` |

**A and B produce identical reconstructions, and that is provable by
inspection rather than by measurement.** `git diff 768cecf e847339 --
tower/tower/world_builder/` is **empty**: the engine, the backend, the keyframe
policy and the frame tracker are byte-identical. The registration branch changed
only `scripts/world_registration.py`, `scripts/world_build_session.py` (the
`--register` wiring), `scripts/world_replay.py` (new), and a `world_register`
setting in `config.py` / `main.py`.

So the A → B delta is entirely **whether registration is invoked at all**. The
physical-era world on disk confirms it: `derived/96e0344d…/` contains
`points.json`, `poses.json` and `support.json` and **no `placements.json`** —
registration never ran, which is exactly why the phone drew 18 unconnected
fragments.

Empirical confirmation of the same fact: replaying the 2026-09-01 frames through
B reproduces the physical session figure for figure — 2,613 frames observed, 434
keyframes, 30 segments, 323 solved poses, 81 refused, 30,382 points, and the
identical four-way rejection histogram (`insufficient_motion` 1782, `blurred`
289, `tracking_lost` 16, `tracking_degraded` 92). The `worldA` and `worldB`
cases likewise report `reproduces_recorded_session: true`.

**Where replay is not exact, this report says so.** `world_replay.py --frames`
reads a directory rather than the capture journal, so `source_seq`, `tx_seq` and
receipt time are enumeration indices rather than the recorder's values. Nothing
in keyframe selection or geometry reads them — which is why the replay comes out
exact — but no transport claim is made from a replay anywhere in this document.

---

## 2. What the physical-era run actually did

2026-09-01, world `b5feee12718c460eabc571074563d669`, session
`96e0344d89ba46299bbe2b783eca797e`. Two captures,
`1ac63b51619f45e18ae8f8cce1440617` then `60bf1b02daf94c0ab713cd0355a5de58`,
2,613 frames, 64.7 MB.

Segment boundaries, read from `events.jsonl`, are 16 `tracking_lost` and 16
`solve_chain_broken` — 32 segment indices minted, 30 of which received a
keyframe. The manifest splits the 81 refused poses into **21 root and 60
cascaded**.

The distribution is the interesting part:

```
boundaries at keyframe:  1 12 13 14 15 19 20 21 22 39 40 47 57 59 62 65 70
                        76 97 102 111 145 146 155 156 190 191 217 246 249 264
                        ... then nothing until 433
```

The first 264 keyframes produced 31 segments. **The last 170 keyframes produced
one** — segment 31, with 168 solved poses, 39% of the walk in a single
coordinate frame. That segment is the subject of §4.

Corpus-wide, over every calibrated session on disk: 1,949 refused poses, of
which **1,812 (93%) are keyframes at which no solver ever ran**, and only 137
were an attempt that failed. Of those 137 root attempts, 118 had **≥100 ORB
matches with a median of 176 epipolar inliers** — the images plainly overlapped
and the pose was refused anyway.

---

## 3. The tracker: what the code actually did

`_Chain.broken` was a one-way latch. Set by the first keyframe whose pose
refused, and thereafter `extend()` returned early with `unavailable` **without
running ORB detection at all**. The engine's only available response was to cut
a segment. Where the restart budget (`MAX_BARREN_SEGMENTS = 1`) was already
spent, not even that happened, and the stranding continued silently with no
journal record — segment 25 of the physical walk stranded 27 consecutive
keyframes that way, segment 9 stranded 15.

Two further facts from reading the code:

- **The pose was solved against exactly one reference**, `observed[(N-1, f)]` —
  landmarks the immediately preceding keyframe had seen. A landmark
  triangulated four keyframes earlier and still in plain view was invisible to
  the solve.
- **A refused keyframe still became the next reference.** It has no entry in
  `absolute`, so it can supply no 3-D correspondence at all, which made the next
  refusal a certainty rather than a risk.

Every mature monocular system holds the opposite invariant, and the survey found
no exception: ORB-SLAM2/3 set `mpReferenceKF` only in `CreateNewKeyFrame()` and
`UpdateLocalKeyFrames()`, both reachable only after a successful track; DSO sets
its coarse tracking reference only from `makeKeyFrame()`, after the window
optimisation; stella_vslam inherits the previous reference unchanged and
advances it only via `local_map_updater`; SVO explicitly restores the last good
pose on failure. **No mature system re-roots on a frame whose pose was not
estimated.**

### 3.1 What was implemented

`references` is now the last `EXTEND_REFERENCE_DEPTH` keyframes that **have**
poses. A refusal contributes no reference, so the next keyframe is solved
against the last view that still has coordinates. `_Chain.failures` counts
consecutive refusals and only `MAX_RECOVERY_KEYFRAMES` of them in a row set
`broken`. **No acceptance threshold moved** — `MIN_PNP_CORRESPONDENCES = 12`,
`PNP_REPROJECTION_ERROR_PX = 3.0`, `MIN_INLIERS = 15`, `MIN_INLIER_RATIO = 0.05`
and `MIN_TRIANGULATION_ANGLE_DEG = 0.5` are the values they were, and a test
pins them.

Setting `MAX_RECOVERY_KEYFRAMES = 1` reproduces the parent branch exactly —
`worldB` returns 36 segments, 108 solved, 13,050 points, dominant component
7,821 points — so the recovery budget is the only variable in every comparison
below.

### 3.2 What was implemented, measured, and REJECTED

Feeding all `EXTEND_REFERENCE_DEPTH` references' correspondences into a single
PnP is the obvious widening and is what ORB-SLAM's `TrackLocalMap` looks like
from a distance. Measured on the 2026-09-01 walk against identical recovery
behaviour:

| references into the PnP | solved | reprojection p99 | rows over 3 px | dominant component |
|---|---|---|---|---|
| 1 | 329 | 4.37 px | 2.21% | 38.8% |
| 3 | 327 | **8.87 px** | **5.19%** | **19.8%** |

`TrackLocalMap` is not "match more keyframes". It projects landmarks through a
**predicted** pose and searches a small radius around the prediction, so
appearance only ever chooses among candidates that are already geometrically
plausible. At the point where our pose is being solved there is no prediction,
so a wider reference set is pure descriptor matching over a wider baseline —
where ORB is weakest. The older references keep their post-solve
re-observation job, gated on reprojecting through the pose that was solved.

A separate prototype of the *proper* form — solve, then project the whole
segment's landmarks through that pose and re-solve within a 12 px radius —
halved the rotation error but did not remove the drift (20.7° → 9.8° median on a
40-keyframe strafe). Long-lived data association is necessary and not
sufficient; the landmarks themselves were triangulated from drifted poses, and
re-observing a wrong landmark constrains you to a wrong pose. That result is
what pointed at §4.

---

## 4. The finding: the chain drifts

Measured on `tests/synthetic_scene.py`'s furnished room, a lateral strafe kept
inside the room envelope, **no refusals, no blur, no injected damage**:

| keyframes | rotation error median / max | max drift ÷ path | per-step scale ratio, first third → last |
|---|---|---|---|
| 6 | 0.95° / 1.69° | 4.7% | 7.63 → 7.87 |
| 12 | 1.69° / 3.46° | 2.7% | 7.63 → 8.47 |
| 20 | 3.19° / 9.17° | 9.8% | 7.63 → 8.85 |
| 30 | 5.71° / 18.88° | 11.3% | 7.63 → **3.46** |
| 40 | 9.21° / 33.98° | 18.2% | 7.63 → **2.43** |

The last column is the ratio of recovered to true camera motion per step. It is
flat for twenty keyframes and then falls by a factor of three: **the
reconstruction contracts.** The pipeline is trustworthy for roughly 15–20
keyframes and progressively falsifies beyond that.

That number matters because the physical walk's segments averaged 14 keyframes.
The fragmentation everybody was trying to remove was, accidentally, holding
segments at about the length this backend can still be trusted over — and
cross-segment Sim3 registration was the only thing in the system absorbing the
scale error between them.

**So reducing segment count is not, by itself, an improvement.** Measured: with
recovery alone the drawer walk goes from 36 segments to 20 and from 108 solved
poses to 120, and its dominant connected component falls from 59.9% of the
geometry to 26.5%. The world got tidier and less true.

### 4.1 The 170-keyframe segment

Independently confirmed on the real data. Segment 31 of the 2026-09-01 walk —
168 solved poses, `source_seq` 1214–2598, the last 21 seconds of the walk:

```
first |camera centre| > 1e3 at pose index 77 of 169
|C|   p50 9,293   p90 6.38e9   p99 5.26e10   max 8.04e10
|xyz| p50 3.14e5  p95 4.78e10  max 2.89e13
```

`span_over_depth` reports 68.67 for that segment and `pair_is_hopeless` lets it
straight through, because the measure has no upper bound and cannot tell
"plenty of parallax" from "the solve diverged".

### 4.2 Why the record said bundle adjustment would not help, and why that is no longer true

The standing conclusion was that a bundle adjuster measured 0.00% improvement at
16, 32 and 104 keyframes because the observation graph is a chain whose median
covisibility span is 1 — 66% of landmarks seen by exactly two views. That was
true of the engine it was measured on. Measured at HEAD on the same fixture:

```
landmarks 5,876   mean views 4.67   >= 3 views 67.2%
observation span: median 3, p90 9, p99 24; 28% span >= 5 frames
```

`EXTEND_REFERENCE_DEPTH`'s guided re-observation built the graph the earlier
attempt was missing.

And the drift is **reachable by optimisation** rather than baked in. Reprojecting
the very same observations through **ground-truth** poses gives RMS 0.49 px
against 0.95 px for the solved poses: the solved reconstruction is demonstrably
not at the minimum. (A first attempt with `scipy.least_squares` reported no
improvement at all; that was a solver failure — a rank-deficient Jacobian under
`x_scale="jac"` terminating on a zero step — not a geometry result, and it is
recorded here because it nearly ended the investigation in the wrong place.)

---

## 5. `world_builder/bundle.py`

Levenberg-Marquardt over camera poses and landmark positions with the Schur
complement eliminating the landmarks. NumPy and OpenCV only — scipy is not a
Tower dependency. Run over a sliding window on the **keyframe** path, never the
frame path.

Structure, and the parts that are load-bearing:

- **Window** `BUNDLE_WINDOW = 12` cameras, the oldest
  `BUNDLE_ANCHOR_CAMERAS = 2` held fixed so an adjustment cannot slide geometry
  that has already been published, and so the seven free parameters of a
  monocular reconstruction stay pinned.
- **Cadence** `BUNDLE_EVERY = 3` solved keyframes, `BUNDLE_ITERATIONS = 4`.
  Bounded rather than run to convergence: the window is re-adjusted a few
  keyframes later anyway, and an unbounded optimiser on a live path is how a
  walk ends mid-room.
- **Landmarks are compacted to the window** before the solve, so an
  adjustment's cost grows with the window rather than with the length of the
  segment.
- **`fixed_points`** for landmarks first seen before the window: they must not
  move, because their older observers cannot follow, but their observations
  stay in the problem as the anchor tying this window to geometry already on
  disk.
- The reduced camera system is formed over observation **pairs** sharing a
  landmark, built once per call rather than per damping attempt, and
  accumulated with `bincount` rather than `np.add.at`. Both changes were forced
  by profiling: the first version spent 3.0 s of a 9.6 s walk inside Python-level
  `tile()` calls, 140,000 of them.

### 5.1 The invariant that had to be learned twice

> **Every observation of a camera that is allowed to move must participate in
> the optimisation.**

Drop an observation for any reason — too few views on its landmark, a per-
landmark view cap, a sampling shortcut — and its landmark stays put while its
camera moves out from under it. The **trajectory** improves and the **support
table**, which cross-segment registration solves PnP against and the viewer
draws, gets worse. It is invisible unless you measure the support table.

This shipped twice on this branch and was caught twice by the corpus:

| constant | value | published reprojection median / p99 | rows over the 3 px gate |
|---|---|---|---|
| *no adjustment at all* | — | 0.543 / 3.974 px | 1.79% |
| `MIN_VIEWS_FOR_ADJUSTMENT` | 3 | 0.723 / **13.698** px | **9.55%** |
| `MIN_VIEWS_FOR_ADJUSTMENT` | 2 | 0.522 / **2.761** px | **0.57%** |

(drawer walk, adjustment on, nothing else changed)

| constant | value | published reprojection median / p99 | over 3 px | dominant component |
|---|---|---|---|---|
| *no adjustment at all* | — | 0.587 / 4.732 px | 2.54% | 8,285 pts (27.3%) |
| `MAX_VIEWS_PER_LANDMARK` | 8 | 0.726 / **15.800** px | 9.51% | 7,521 pts (24.1%) |
| `MAX_VIEWS_PER_LANDMARK` | 16 | 0.546 / **2.781** px | **0.69%** | **16,340 pts (53.5%)** |

(2026-09-01 walk, adjustment on, nothing else changed)

The argument for `min_views = 3` is about **information** and is correct as far
as it goes — a two-view point is exactly determined and constrains nothing. It
is not an argument for removing its rows. A third of the map is two-view.

---

## 6. Corpus results

Five replayed physical walks. **A** is the physical era (`main @ 768cecf`,
what actually processed the walks, registration never invoked). **B** is
`world-builder/fragment-registration-v1 @ e847339`. **C** is this branch.
`dom` is the largest connected component after registration; for A, where
no `placements.json` exists at all, it is necessarily the largest single
segment.

| walk | stage | seg | solved | points | frags | dom pts | dom % | dom kf | dom kf % | admitted |
|---|---|---|---|---|---|---|---|---|---|---|
| **2026-09-01 loop** | A physical era | 30 | 323 | 30,382 | 18 | 6,190 | 20.4% | 170 | 39.2% | 0 |
| | B registration-v1 | 30 | 323 | 30,382 | 13 | 8,285 | 27.3% | 56 | 12.9% | 6 |
| | **C this branch** | 30 | 323 | 30,538 | **10** | **12,558** | **41.1%** | **84** | **19.4%** | **14** |
| **drawer walk** | A physical era | 36 | 108 | 13,050 | 23 | 3,117 | 23.9% | 23 | 10.5% | 0 |
| | B registration-v1 | 36 | 108 | 13,050 | 18 | 7,821 | 59.9% | 61 | 28.0% | 5 |
| | **C this branch** | 33 | **137** | 13,667 | 17 | 7,632 | 55.8% | 61 | 28.0% | **7** |
| **normal walk** | A physical era | 23 | 100 | 9,145 | 8 | 4,311 | 47.1% | 51 | 22.3% | 0 |
| | B registration-v1 | 23 | 100 | 9,145 | 8 | 4,311 | 47.1% | 51 | 22.3% | 0 |
| | C this branch | 23 | 100 | 8,589 | 8 | 3,812 | 44.4% | 51 | 22.3% | 0 |
| **dense 08-29** | B sampler | 6 | 68 | 11,009 | 6 | 6,386 | 58.0% | 42 | 54.5% | 0 |
| | **C this branch** | 6 | 68 | 10,730 | **4** | **9,970** | **92.9%** | **67** | **87.0%** | **2** |
| **long 08-27** | B sampler | 40 | 129 | 18,977 | 20 | 3,739 | 19.7% | 27 | 8.0% | 3 |
| | **C this branch** | 40 | 129 | 19,628 | 19 | **4,332** | **22.1%** | 27 | 8.0% | **4** |

And the quantity this whole line of work is really about — does the
published geometry still reproject:

| walk | B: median / p99 | over 3 px | C: median / p99 | over 3 px |
|---|---|---|---|---|
| 2026-09-01 loop | 0.587 / 4.732 px | 2.54% | **0.546 / 2.781 px** | **0.69%** |
| drawer walk | 0.543 / 3.974 px | 1.79% | **0.521 / 2.780 px** | **0.64%** |
| normal walk | 0.693 / 5.316 px | 3.27% | **0.584 / 3.117 px** | **1.03%** |
| dense 08-29 | 0.648 / 3.100 px | 1.16% | **0.547 / 2.666 px** | **0.56%** |
| long 08-27 | 0.572 / 4.270 px | 2.10% | **0.566 / 2.957 px** | **0.96%** |

**Reprojection improves on every walk in the corpus**, tail and body, and
the fraction of published rows above the gate that admitted them roughly
halves or better. That is the number that says the coherence gained is
not bought with poses a consumer cannot check.

Where C does NOT improve: the normal walk's dominant component loses 499
points while covering the identical 51 keyframes -- that is landmark
de-duplication under a better pose chain, not lost structure -- and the
drawer walk's share falls from 59.9% to 55.8% while its absolute
keyframe coverage is unchanged at 61 and its solved poses rise 27%. On
neither walk does the coherent PART of the world get smaller.

### 6.1 Isolating the registration sampler

Registration is non-destructive and, verified over six repeated runs with
and without reseeding OpenCV, exactly deterministic given a built world.
So the sampler change can be isolated perfectly: hold the reconstruction
fixed and vary only which `world_registration.py` is asked about it.

| world (parent's own reconstruction) | sampler | candidates | admitted | cycles checked | dom pts | dom kf | seconds |
|---|---|---|---|---|---|---|---|
| 2026-09-01 loop | per-side 8 | 153 | 6 | **0** | 8,285 (27.3%) | 56 | 34.1 |
| | product ≤256 | 153 | **10** | **5** | **10,372 (34.1%)** | **70** | 65.7 |
| drawer walk | per-side 8 | 253 | 5 | 0 | 7,821 (59.9%) | 61 | 13.6 |
| | product ≤256 | 253 | 4 | 0 | 7,326 (56.1%) | 56 | 25.8 |
| normal walk | per-side 8 | 28 | 0 | — | 4,311 (47.1%) | 51 | 1.6 |
| | product ≤256 | 28 | 0 | — | 4,311 (47.1%) | 51 | 4.9 |

`cycles_checked: 0` on the 2026-09-01 walk is the line that matters. The
parent's admitted graph there is a **tree**, so not one placement in it
has any independent verification. The wider sample closes five cycles.

It is **not** monotone, and the drawer walk is the counterexample: a
wider sample changes which frame pairs `fit_direction` solves from, so a
pair admitted before can be refused after. The claim the change supports
is that no verdict is reached on less evidence than before, not that no
verdict changes.

### 6.2 What each change is worth, separately

Measured on the 2026-09-01 walk, dominant component as a share of
geometry, each step adding to the one above it:

```
A  physical era, registration never invoked        20.4%  (one diverged segment)
B  + registration invoked                          27.3%
   + registration sampler widened                  34.1%
C  + local bundle adjustment                       41.1%
```

### 6.3 Recovery, measured across the corpus

With the registration sampler fixed, raising `MAX_RECOVERY_KEYFRAMES`
does not produce a consistent result:

| walk | budget 1 | 2 | 4 | 8 |
|---|---|---|---|---|
| 2026-09-01 loop | 41.1% | 37.9% | 39.1% | **67.9%** |
| drawer walk | 55.8% | 55.1% | 28.5% | **27.2%** |

It doubles coherence on one walk and halves it on another, which is the
signature of a mechanism that sometimes glues the right things together
and sometimes glues the wrong ones with nothing able to tell which. §3.1
and `MAX_RECOVERY_KEYFRAMES` carry the ground-truth measurement that says
which: above a gap of 1, over repeating texture, a recovered pose
publishes roughly one keyframe of motion however far the camera walked.
The shipped budget is **1**.

---

## 7. What was not changed

- Object Memory, CV Lab, Document Memory, Translator, Scene Understanding, the
  iOS product shell, the camera profile system: untouched.
- Capture resolution, frame rate, calibration: untouched. The 360×640
  self-calibration is the only one on the machine and every capture in the
  corpus is 360×640.
- No acceptance threshold in the geometry path was loosened. `admit()`'s
  registration gates are byte-identical.
- No metric-scale claim is made anywhere; `scale_state` remains `unknown`.
- No user recording, world, capture or research asset was deleted or moved.

---

## 8. Remaining limitations

*(filled in at completion)*
