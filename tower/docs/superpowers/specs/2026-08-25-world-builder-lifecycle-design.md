# World Builder lifecycle automation — design

**Date:** 2026-08-25
**Branch:** `integration/world-builder-lifecycle-v1`
**Starting commit:** `35214a1`
**Status:** approved, in implementation

This design responds to the **first physical World Builder test**
(2026-08-24, Ray-Ban Meta glasses to iPhone to Tower). Everything
asserted here about that run is read from artifacts still on disk under
`data/captures/` and `data/world_builder/`, not from recollection.

---

## 1. What the physical run actually produced

`data/world_builder/worlds/4b31766726c648d994a088a7c7b8aa9b/derived/manifest.json`:

```json
{"backend_id": "unposed", "keyframes": 155, "poses_solved": 0,
 "poses_refused": 119, "points": 0, "segments": 36, "scale_state": "unknown"}
```

Three widely-held readings of that run are wrong, and the corrections
drive this design.

### 1.1 "36 camera poses" were not poses

`poses_solved` is **0**. The session ran `UnposedBackend`, selected by
`BACKEND_AUTO` because `session.intrinsics.source == "unknown"`
(`backends/__init__.py:52-55`). That backend withholds every pose by
construction and emits one `POSE_STATUS_ANCHOR` per tracking segment:
36 identity transforms, all at the origin. All 119 non-anchor keyframes
carry `degeneracy: "no_intrinsics"`; not one geometric gate was ever
evaluated.

The wire number came from `results/world_builder.py:_pose_count`:

```python
return max(0, keyframes - refused)      # 155 - 119 = 36
```

That formula is correct for the classical backend, where anchors sit at
real segment origins on a real chain. It is **wrong for the unposed
backend**, where all 36 are the same point. `unposed.py:73-76` says the
ANCHOR status exists precisely so a consumer cannot count it as
evidence. The consumer counted it.

### 1.2 The lifecycle desync was not a follower detaching

Ten captures were recorded in one 435-second session:

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

WiFi dropped at t=121.9 s. The successor did not appear until t=226.8 s,
a **105-second gap against the 90-second `RESUME_GRACE_SECONDS`**, so
the follower correctly concluded the walk had ended, finalised, and
exited. The wearer kept walking; the phone reconnected; nine further
captures were recorded that nothing was following.

**The reconnect machinery worked, and this is its first physical
validation.** Lineage chained correctly through `continues_capture`;
it correctly refused to chain across the 105 s gap, and correctly
refused to chain across a clean `stop` (79233e follows b1ab1d in time
but declares no predecessor, because `resumable_capture()` only offers
a capture that ended by `disconnect`).

The defect is not detachment. **Nothing in the Tower has ever started a
follower.** `main.py` wires `world_root` read-only, and no code path
spawns `world_build_session.py`. "No world yet" was the literally
correct answer.

### 1.3 Segment fragmentation outranks calibration

36 segments do not share a coordinate frame. Ten contain a single
keyframe and can never yield a point even with perfect intrinsics.
`engine.py:421-426` forces `scale_state = unknown` for any world with
more than one segment, and `results/world_builder.py:650-665` refuses
path length outright. Calibration unlocks geometry; fragmentation would
make that geometry a fragmented, unscalable map.

---

## 2. Measured: why the walk fragmented

A replay harness fed all 1395 recorded frames through the **real**
`FrameTracker` and the **real** `KeyframeSelector.evaluate`. It
reproduces the run bit-identically: 155 keyframes, 35 losses, the exact
four-way rejection histogram, and zero delta against every persisted
`sharpness`, `survival_ratio` and `overlap_ratio`.

`docs/agent-handoffs/WORLD-BUILDER.md` section 9.4 recorded the standing
hypothesis, "spurious `blurred` rejections cascading into
`tracking_lost`", and said a real walk would settle it. **It is
settled, and the hypothesis is wrong.**

| configuration | segments | keyframes | 1-kf segs | median inlier ratio |
|---|---|---|---|---|
| baseline | 36 | 155 | 10 | 0.627 |
| `min_sharpness_ratio` 0.45 | 43 | 161 | 15 | — |
| `min_sharpness_ratio` 0.00 (off) | **49** | 176 | 22 | — |
| survival/overlap gates before blur | **40** | 154 | 16 | — |
| **`overlap` 0.75 / `minsurv` 0.20 / `loss` 0.05** | **20** | 260 | **4** | 0.649 |

Loosening the blur gate makes segmentation **monotonically worse**:
blur rejections were *masking* losses that had already happened. 77% of
blur rejections occur when `survival_ratio` is already below 0.15.
Reordering the gates is also worse, for the same reason.

**The actual defect: `overlap_ratio` is not an independent signal from
`survival_ratio`.** They are equal in 1283 of 1358 measured frames
(max gap 0.029), because on this footage tracks *die* rather than leave
frame. So the `overlap_floor` rescue at 0.45 can only fire in the band
`survival` in [0.35, 0.45), which is **36 frames out of 1395**. The gate
written to guarantee "a usable weak link beats a broken chain" is very
nearly dead.

Widening the window from the **top** takes the rescue keyframe while
tracking is decaying but still alive.

---

## 3. The design

### 3.1 Capture worker supervision (P0)

**New:** `tower/capture_workers.py`, holding `CaptureWorkerSupervisor`.

Generic by construction. It knows how to run an argv when a capture
opens and how to reap it when the capture closes. It contains **no
cartridge import and no cartridge name**, so
`test_shared_code_does_not_import_a_cartridge` stays green unmodified.

```
ws.py  _start_capture --> supervisor.capture_opened(capture_id, dir, continues)
       _stop_capture  --> supervisor.capture_closed(capture_id)
       lifespan       --> supervisor.shutdown()
```

`main.py`, the acknowledged wiring point, builds the argv as **plain
strings** when `settings.world_root` is set. No import of
`tower.world_builder` is involved:

```python
[sys.executable, "scripts/world_build_session.py",
 "--follow-capture", "{capture_dir}", "--root", world_root,
 "--rebuild-every", str(n)]
```

**The web process still never builds.** It supervises a child that
builds, which is the invariant `docs/agent-handoffs/WORLD-BUILDER.md`
section 1 protects and the reason live viewing costs the frame path
nothing.

**Duplicate suppression, the load-bearing rule.** The follower already
chains into a successor capture by itself
(`CaptureFollower._await_successor`). Spawning a second worker for that
successor would produce two followers and two worlds on one lineage.
Therefore:

> Spawn on `capture_opened` **unless** `continues` is not None and a
> live worker already owns that lineage.

That covers the 2026-08-24 timeline exactly: 2e6cff spawns; the chained
successors do not; 341b0f at t=226.8 declares no predecessor and
correctly spawns a fresh worker for the second walk.

**Failure is reported, not swallowed.** A worker that exits non-zero, or
fails to spawn at all, is logged with its argv and exit status. Without
this, a follower that dies before acquiring the writer lock leaves the
result channel with nothing to read, and iOS shows "no world", which is
exactly the misleading state of 2026-08-24.

**Assumption, stated:** with `stream_start` pinned to
`{"type":"stream_start"}` by two iOS tests, iOS cannot signal intent.
The Tower therefore builds a world for **every** capture when a world
root is configured. Reversible by configuration.

### 3.2 Tower startup (P0)

`scripts/setup_tower.ps1`, `scripts/start_tower.ps1`, and a gitignored
`tower/.env` consumed through `uvicorn --env-file` (python-dotenv is
already installed transitively; `.env` is already in `.gitignore`).

Roots are forced by the store layouts, not chosen:

- `TOWER_CAPTURE_ROOT=data`, because `capture.py:124` appends
  `captures/<id>`
- `TOWER_WORLD_ROOT=data/world_builder`, because `store.py:158` appends
  `worlds/<id>`, and this must equal `world_build_session.py`'s
  `DEFAULT_ROOT` or the result channel reads a different tree than the
  builder writes.

Both scripts run from the tower root, because `redaction.py:128`
resolves the YuNet weights relative to CWD: run the builder elsewhere
and face redaction silently records `none`.

Port conflicts are **diagnosed** (owning PID, process name, command
line, and whether it looks like our own stale uvicorn) and never killed
without `-Force`. Access-denied is caught and answered with the
elevation instruction rather than a raw exception. The firewall rule is
reported, never mutated (`README.md:178-179` forbids it).

With section 3.1, the second terminal disappears.

### 3.3 Truthfulness repairs (P0)

1. **Anchors are not poses.** Carry a pose-kind breakdown through the
   derived manifest so the channel can report solved and anchor counts
   separately, and never present a stack of origin anchors as a
   trajectory.
2. **The AUTO downgrade is announced.** `BACKEND_AUTO` selecting
   `UnposedBackend` currently returns silently with
   `downgraded_from: None`. It gains the same warning and the same
   recorded reason the explicit branch already has. This is the single
   line whose absence made "no geometry" unexplainable.
3. **`declared_size` stops being fabricated.**
   `world_build_session.py:238` passes the argparse defaults 480x360
   against a 360x640 stream. Once a calibration exists this becomes a
   hard `IntrinsicsResolutionMismatchError`, or worse, invites
   calibrating at the wrong resolution.
4. **Segment count is surfaced live**, from `tracking_lost` events, so
   "Tracking: Good" is not the only thing said about a walk that broke
   into 36 pieces.

### 3.4 Genuinely live building (P1)

`build()` is a full re-solve: it re-reads every keyframe, re-decodes
every JPEG, re-detects ORB on all N, and calls `backend.release()` at
the end. Measured at roughly O(N^1.2), about 2.5 s at 155 keyframes.
Total work over a walk with `--rebuild-every k` is O(N^2/k), so
**lowering the cadence makes it worse**. That is why the default is 0
and why nothing appeared until the walk ended.

But `ClassicalTwoViewBackend` is already strictly forward-only: frame
`i` solves against `features[i-1]` plus accumulated `landmarks`, and
there is no bundle adjustment or loop closure (BA was measured at 0.00%
drift improvement and rejected). `absolute`, `landmarks` and `observed`
are the entire carried state, and they are **local variables**.

Promoting them to instance state behind a `begin / extend / snapshot`
seam gives O(1)-per-keyframe extension with **bit-identical output**.
`test_a_mid_walk_rebuild_does_not_change_the_final_result` already
exists and becomes the regression guard.

Shipped in two stages: a non-zero rebuild cadence first (live, if
expensive), the seam second (live and cheap).

### 3.5 Keyframe policy (P1), evidence-gated

`min_overlap_ratio: 0.45 -> 0.75`, `min_survival_ratio: 0.35 -> 0.20`,
`loss_survival_ratio: 0.15 -> 0.05`. Three constants; no gate
reordering; blur thresholds untouched.

**Recorded honestly:** this is one walk, one room, one wearer, one
lighting condition. It costs +68% keyframes, and it shifts the dominant
promotion path from parallax to track-decay, a design shift whose effect
on triangulation quality **cannot be measured until a calibration
exists**, because this world has no poses to check against. The ORB and
fundamental-matrix proxy shows the extra keyframes are not garbage
(inlier ratio flat at 0.63 to 0.65, no pair below `MIN_INLIERS`); it does
not show the reconstruction is better. A second walk in a different
space should reproduce the ordering before these are treated as tuned.

### 3.6 Calibration (P0/P1), plumbing only

Genuinely blocked on a printed ChArUco board photographed at 360x640.
No code change can honestly unblock it, and every shortcut is
prohibited: the published Ray-Ban FOV describes a 3:4 still while the
stream is 9:16 through an undocumented crop, so no legitimate conversion
exists; `schema.py:92-94` refuses a "guessed" source value; loosening
`calibrate_charuco.py`'s view requirements yields 287% to 3787% fx error
while *improving* reprojection RMS.

What is buildable tonight is the missing plumbing: a resolution-keyed
intrinsics store that `start_session` consults using the **observed**
frame size, returning `CameraIntrinsics.unknown()` on a miss. Today
`calibrate_charuco.py --out` has no default location and `--intrinsics`
has no discovery, so the one working path requires an operator to
remember a flag.

### 3.7 Observability (P1)

Session start logs world id, session id, capture id, resolved root,
backend, intrinsics source and rebuild cadence, which is enough to
answer "what capture is this world following?" from a log line. Each
rebuild logs its inputs, duration and outputs. Four
declared-but-never-emitted event kinds are wired: `segment_started`,
`build_completed`, `mapping_stalled`, `backend_downgraded`.
`world_build_session.py` currently logs **nothing at all** for the
entire duration of a walk.

---

## 4. Out of scope tonight, and why

**All iOS changes.** There is no Swift toolchain on this Windows machine
(`xcodebuild`, `swift`, `swiftc` all absent), and the Tower-backed
`WorldBuilderClient` used in the physical test exists on a Mac and is in
**no branch of this repository**: `ios-origin`'s newest commit predates
the test. Writing iOS code here would be unbuildable, unverifiable, and
likely to collide with unpushed work. A complete integration package is
produced instead: contract additions with worked wire examples, the
session-binding state machine, Swift type sketches, and the test list.

**Any claim of physical validation.** Nothing built tonight has been run
against the glasses. The previous version's physical validation does not
transfer.
