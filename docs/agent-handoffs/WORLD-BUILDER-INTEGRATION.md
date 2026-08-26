# World Builder integration — current state

> **iOS ENTRY POINT IS `docs/agent-handoffs/IOS-EXECUTION-PLAN.md`.**
> This file is **REFERENCE**: deeper detail, still accurate except where
> the plan says otherwise. Read the plan first — it says what to do now,
> what is already settled, and what the Tower has measured and refused.
> Where the two disagree, the plan wins.

**Living document.** It describes what is true now, not what changed when.
Rewrite stale parts; git history is the record of how it got here.

**Branch:** `ios/world-builder-integration`
**Base:** `main` @ `35214a1`
**Tower source integrated:** `integration/world-builder-lifecycle-v1` @ `71db9c0`
**Last updated:** 2026-08-25

**Status: the app and the Tower speak the same contract again, and the world on
screen is now bound to the capture that produced it.** The Tower's lifecycle
automation is physically proven — a walk on 2026-08-25 recorded a capture, had
a builder attached to it automatically, and rebuilt live every 4 keyframes. The
iOS half of that walk is what §8 is about: the contract identifier moved to
`world_builder.status/2026-08-25`, the phone was refusing it, and it no longer
does. What has **not** been re-run on hardware since is in §5.

Read the boundary itself in **`docs/contracts/WORLD-BUILDER-IOS.md`**. This
document is about evidence: what was run, against what, and what it proved.

---

## 1. What was built

`TowerClient` decodes the result-channel envelope — `cartridges`,
`result_subscribed`, `cartridge_result`, `result_error`, `result_unsubscribed`,
`protocol_error` — caches the capability declaration, and publishes the rest on
one ordered stream. It knows nothing about worlds.

`TowerWorldBuilderClient` owns the World Builder contract, the subscription and
the mapping onto `WorldModelState`/`WorldSnapshot`. `ProjectManager` builds it,
so it outlives every workspace switch. It holds no socket.

No second connection, no view-owned transport, no `GlassesConnection` reachable
from any cartridge client.

**Swift changed:** `TowerClient`, `ProjectManager`, `CartridgeClient`,
`CartridgeAvailability`, `WorldModel`, `WorldBuilderClient`,
`WorldBuilderWorkspaceView`, `WorldCanvasView`. **Added:**
`CartridgeResultChannel`, `TowerWorldBuilderClient`.

**Tower changed: nothing.** The overnight implementation needed no correction
to integrate.

---

## 2. The one integration defect found, and where

`TowerWorldBuilderClient` subscribed to `TowerClient.$status` and
`$cartridgeDeclaration` and read those properties inside the sink. A
`@Published` publisher fires from **`willSet`**, so both sinks saw the value
*before* the change: a connection that had just come online still read
`.offline`, and a declaration that had just arrived still read `nil`. **Nothing
ever subscribed.** Snapshots still decoded, so the screen looked plausible while
the subscription that produced them had never been opened.

Caught by `testTheWorldBuilderLifecycleRunsEndToEnd`, which asserts the phase
sequence rather than the end state. Fixed with `.receive(on: DispatchQueue.main)`
on both — the same thing `WorldBuilderViewModel` and `ProjectManager`'s bridges
already do, for the same reason.

This would have shipped to hardware and presented as "World Builder sometimes
does not appear".

---

## 3. Evidence — synthetic frames, real everything else

Tower host: Windows, `tower.main:app` under uvicorn, reached over Tailscale from
this Mac. `TOWER_CAPTURE_ROOT=data/capture`, `TOWER_WORLD_ROOT=data/worlds`.
Frames were **rendered**, not photographed, and pushed over the real WebSocket
by a driver standing in for the phone. What that proves is the wire, the
capture, the follower, the result channel and the decoder — **not** the camera
and not DAT.

### 3.1 The channel matches the decoder exactly

`GET /health` → `capture.armed: true`, `recording: false`.
`GET /cartridges` and the socket's `{"type":"cartridges"}` both declare
`world_builder`/`status`/`world_builder.status/2026-08-23`, `available: true`.

> **Superseded on 2026-08-25.** The identifier is now
> `world_builder.status/2026-08-25`, and that is what this build implements.
> The observation above is left as recorded. Only `trajectory.pose_count`
> changed, and only in meaning: see `WorldBuilderResultContract.identifier`.

On the socket: `pong` is literally `{"type":"pong"}`; `result_subscribed`
returns `sub-1` with `cursor_status: "absent"`; `cartridge_result` arrives with
dense `seq`, `revision_changed: true` on change and `false` on the ~2 s
heartbeat. A `world_snapshot` captured verbatim from that channel is now a test
fixture (`testARealTowerSnapshotDecodesFieldForField`), so the decoder is pinned
against the Tower's own bytes rather than against a reading of its source.

### 3.2 A full live session, end to end

120 frames at **11.0 fps measured**, `stream_start` → frames → `stream_stop`,
with `scripts/world_build_session.py --follow-capture` running in its own
process.

- capture recorded all 120 frames; `frames_written` climbed monotonically
- `model_state` went `idle` → `receiving` → `finalized`
- **keyframe count climbed live on the wire**: 1, 2, 3 … 10, each arriving as a
  changed revision
- `tracking: good`, 1 segment, 110 frames rejected `insufficient_motion`
- final: `frames_observed: 120`, `keyframes_accepted: 10`

**And no geometry**: `backend_id: "unposed"`, `poses_solved: 0`, `points: 0`,
`scale_state: "unknown"`. That is correct and is the headline finding — see §4.

### 3.3 The real Swift app, against the real Tower

Run in the Simulator — which is the actual `TowerClient`, the actual
`TowerWorldBuilderClient` and the actual decoder, reaching the Windows Tower
over Tailscale. Only the camera half is missing, and the Simulator says so
("Meta AI unavailable"). The shell reported **Tower: Connected, Camera: Off**.

Console, in order, with nothing elided:

```
[Glasses][Init] GlassesConnection created          <- exactly one
[Glasses][Tower] ping sent / pong validated        <- pong still first
[Glasses][Tower] receive loop started
[Glasses][Tower] cartridges sent                   <- after the pong, never before
[Glasses][Tower] cartridges declared: world_builder/status available=true
[Glasses][Tower] result_subscribe(world_builder) sent
[Glasses][Tower] result_subscribed: sub-1 world_builder/status
[Glasses][Tower] cartridge_result: seq=1 revision=30b6f3ef… coalesced=0
```

Then a live mapping session was driven underneath the running app, and the
mapped state followed it:

```
[Glasses][WorldBuilder] awaitingFirstUpdate
[Glasses][WorldBuilder] receiving keyframes=2  … geometry=-  poses=-
[Glasses][WorldBuilder] receiving keyframes=3  … geometry=0  poses=1
[Glasses][WorldBuilder] receiving keyframes=4 … 10
[Glasses][WorldBuilder] finalized  keyframes=10 tracking=Good scale=Unknown
```

**The whole lifecycle, in the real app, from real Tower bytes.** Two details
worth keeping: `seq` skipped 1 → 3 because seq 2 was an unchanged heartbeat that
the client correctly did not republish; and `geometry=-` at two keyframes
against `geometry=0` at three is absent-stays-absent and zero-stays-zero, which
is the distinction the whole contract turns on.

### 3.4 The reconnect race, on a real network

Socket A streamed 40 frames and was then **aborted with no close frame**, which
is what WiFi going away looks like. Socket B opened 0.5 s later and sent
`stream_start` again, continuing the sequence.

| | |
|---|---|
| First capture manifest | `end_reason: "disconnect"`, `continues_capture: null` |
| Successor manifest | `end_reason: "stop"`, **`continues_capture: "879b9a85…"`** |
| Worlds created | **one** (`fe432c9f…`) |
| Sessions | **one** (`e6259524…`) |
| Segments | **1** |
| Frames observed by the follower | **120**, across two capture directories |
| Keyframes across the drop | 4 → 5 → 6 → 7 → 8 → 9 → 10, no reset |
| `/health` `recording` | true throughout socket B, false only after the clean `stream_stop` |

One capture lineage, one follower, one world, one continuously climbing keyframe
count — the overnight capture-ownership work behaves as described, against a
real socket rather than a simulated one.

**The zombie window was then covered deliberately.** uvicorn takes 20–40 s to
notice a dead socket, so the first run's 11-second successor stream was too
short to prove anything about the teardown. A second run slowed the successor to
1.3 fps so it streamed for 61 s: the abort landed at t=102, the successor armed
at t=103, and `recording` stayed **true** until t=168 — three seconds after the
clean `stream_stop`, and 65 s past the abort. **The superseded connection's
teardown did not disarm the live recording.**

An intermediate run of that test *did* show `recording` flipping to false
mid-stream, and it was the driver's own bug rather than the Tower's: the sending
socket was never read, so its receive buffer filled, the transport stopped being
drained, the library's keepalive pong went unprocessed and the connection closed
with 1011 after ~20 s. That is exactly the failure the contract's first client
responsibility names — *"read the socket"* — and `TowerClient`'s continuous
receive loop is why the phone does not have it. Worth knowing, because from
`/health` alone it is indistinguishable from the bug under test.

### 3.5 Persistence and reload

`world_inspect.py` reopened the finished world: same world id, same name, same
scale state, `pose_status {'anchor': 1, 'solved': 7}`, storage split into
authoritative vs reclaimable, and the redaction claim recorded as
`faces-detected-and-filled/yunet-2023mar@0.30`. No missing or corrupt artifacts.

### 3.6 The build

iOS suite **275 passed, 0 failed**. Debug ✅ and Release ✅, with **warning
parity** against the pre-integration baseline — the same four, none new. Device
build and code-signing for the physical iPhone also succeed, and the app
installs.

---

## 4. The finding that matters most

**Without camera intrinsics there is no reconstruction at all.**

`select_backend` downgrades to `UnposedBackend` when intrinsics are unknown, and
nothing in the Tower invents a focal length. The live session above produced ten
keyframes, honest `tracking: good`, and then `poses_solved: 0`, `points: 0`,
`scale: unknown`.

So a first physical walk **will** show a world with a climbing keyframe count
and no geometry, and that is the system being truthful rather than broken.
Getting geometry needs `scripts/calibrate_charuco.py` run against a printed,
physically measured board — and the intrinsics must be calibrated at the
**delivered resolution**, because `_require_matching_resolution` refuses to
apply a calibration from another size rather than silently scaling the world by
the ratio.

A board has been generated and is ready to print: 7×5 squares, 0.04 m square,
0.03 m marker. **Measure the printed square** — those metres set the scale of
everything downstream.

---

## 5. What has NOT been done

Everything below needs a person with the hardware. None of it is blocked on
code.

| Phase | Status |
|---|---|
| App running on the physical iPhone | **not done** — the device is paired over the local network and the app installs, but launch was refused twice: `SBMainWorkspace … Locked`. Nobody unlocked it. The same binary runs correctly in the Simulator (§3.3) |
| Ray-Ban glasses connected, camera capture | **not done** |
| Frames from the real camera reaching the Tower | **not done** |
| Sender FPS / backpressure against the physical baseline | **not done** — the 11.0 fps figure above is this Mac's driver, not the phone's |
| World Builder against a real room | **not done** — the lifecycle end to end is proven (§3.3), but on rendered frames |
| WiFi interruption with the real phone reconnecting | **not done** — §3.3 proves the Tower half against a real socket; the phone's own reconnect is untested here |
| Redaction against a real face | **not done** — the mechanism ran and recorded its claim, but a rendered scene contains no faces, so nothing was detected and nothing was proven |
| Calibration | **not done** — no board has been printed |
| Resolution/FPS experiment (mission phase 13) | **not started**, and correctly so: it is gated on the baseline walk |

Nothing in this repository has been validated against the Ray-Ban camera, DAT,
or real-room footage. Treat every geometry figure as a statement about a
rendered pinhole scene.

---

## 6. Exact next steps

**The Tower is already running** on the Windows host, detached, at
`ws://100.110.156.55:8000/ws` — `capture.armed: true`, `recording: false`, the
World Builder offer available. To restart it (over SSH, `Start-Process` does not
survive a non-interactive session; WMI does):

```powershell
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
  CommandLine = "cmd.exe /c cd /d C:\Users\tvllo\Projects\GlassesTower && " +
    "set TOWER_CAPTURE_ROOT=data/capture && set TOWER_WORLD_ROOT=data/worlds && " +
    ".venv\Scripts\python.exe -m uvicorn tower.main:app --host 0.0.0.0 --port 8000 > tower.log 2>&1"
}
```

1. **Unlock the iPhone** and leave it unlocked. Then:
   `xcrun devicectl device process launch --device <id> --console --terminate-existing com.tristanvarner.Glasses`
   Cold-launch checks, all readable from the console: exactly one
   `[Glasses][Init] GlassesConnection created`; camera OFF until Start;
   `pong validated`; `cartridges declared: world_builder/status available=true`;
   `result_subscribed`. The World Builder panel should read **"No world yet"**
   before any capture — that is `model_state: idle` decoding correctly.
2. **Baseline transport regression** (mission phase 7) with the glasses on:
   Start → viewfinder → `stream_start` → frames → ~10–12 fps → clean Stop. Do
   not proceed past a regression here.
3. **Calibrate.** Print the board, measure a square, capture board views through
   the real pipeline, run `calibrate_charuco.py --frames <capture>/frames --out
   intrinsics.json`. Check reprojection RMS and view count before trusting it —
   the distortion model is completely unexercised on a ~100° wearable lens.
4. **The walk.** Start the follower with `--intrinsics intrinsics.json`, then
   walk: textured area, slow along one wall, gradual turns, lateral movement for
   parallax, no fast head motion. Lateral beats forward by an order of magnitude
   on direction error, and forward is what walking does — expect a sparser map
   than a sidestepping one.
5. **Then** the resolution question. Only after a baseline walk exists to
   compare against.

**The manual follower step is gone.** On
`integration/world-builder-lifecycle-v1` the Tower attaches a builder to every
capture itself, at the moment the capture id is minted, one per capture
*lineage* so a reconnect does not fork the walk (`tower/capture_workers.py`,
`tower/routes/ws.py`, `tower/main.py`). No capture-id lookup, no
`world_build_session.py` to start by hand, and `--rebuild-every 4` rather than
the script's own default of `0` — which is why geometry now appears mid-walk
instead of only after Stop.

What still has to be set, and both fail silently when unset:
`TOWER_CAPTURE_ROOT` and `TOWER_WORLD_ROOT`. The Tower now says so at startup,
in three lines, and `/health` carries a `capture_workers` block answering "is
anything following this capture?" from another machine.

Calibration is still the thing standing between a walk and a reconstruction
(§4). Without intrinsics the backend downgrades to `unposed` and the honest
result is keyframes, segment origins, and no geometry at all — which the phone
now renders as exactly that. See §8.

---

## 7. Known limitations carried forward

- **No world picker and no replay on iOS.** The Tower half of both exists;
  see `docs/contracts/WORLD-BUILDER-IOS.md` §6 for what iOS would need.
- **`.finalizing` draws a progress indicator** for a state the Tower defines as
  "the stored figures are not the final figures", not "a process is working".
  Revisit if it misleads. Tower cannot observe a running build.
- **Scale can only ever be `relative` or `unknown` in V1.** Nothing may be
  rendered in metres, and `format_distance` on the Tower and
  `distanceDisplayable` on the phone both refuse independently.
- **Redaction is a process claim**, `faces-detected-and-filled/yunet-2023mar@0.30`
  — never "redacted" or "anonymised". `retains_raw_imagery` stays true.
- The synthetic worlds this pass created are still in the Tower's world root and
  are self-labelling: their session records carry
  `frame_source: "synthetic"` or a `live-capture` from rendered frames.

---

## 8. The 2026-08-25 pass: the contract, and whose world is on screen

**What the phone was showing.** *"The Tower offers a World Builder contract this
version of the app does not understand (world_builder.status/2026-08-25)."* That
message was correct and the refusal was the Tower's, deliberately: the
identifier moved because `trajectory.pose_count` changed **meaning**, and
serving the old id would have been a lie about compatibility.

**What changed on the wire, established from the Tower branch rather than from
its handoff:**

| Change | Where |
|---|---|
| `world_builder.status/2026-08-23` → `/2026-08-25` | `tower/results/contracts.py` |
| `trajectory.pose_count` now read from the manifest's `poses_positioned` | `tower/results/world_builder.py::_pose_count` |
| `trajectory.poses_anchor` added | `tower/results/world_builder.py::_trajectory_block` |
| **Nothing else.** No new message type, no envelope change, no `stream_started` | `git diff 35214a1..71db9c0 -- tower/` |

`poses_anchor` and `segments` live in the payload's own `trajectory` block, not
in `world_snapshot.trajectory` — `_attach_ios_projection` carries four keys
across and drops the rest — so iOS reads that one evidence block for those two
figures, and only those.

**What iOS now does, in order of how much it matters:**

1. **A world from another capture is no longer rendered as this session's.**
   `WorldSessionGate` compares the phone's own capture bracket against the
   payload's `session` block; a snapshot that is not a live capture with a
   capture directory, while a bracket is open, renders as *waiting* with a
   sentence saying why. This is the 2026-08-24 LIVE-beside-"Capture has ended"
   defect, closed. `docs/contracts/WORLD-BUILDER-IOS.md` §9 has the table and
   the reasoning, including what it deliberately is **not** (an id comparison —
   the phone does not know its own capture id, and `stream_started` is
   unimplemented Tower-side).
2. **Anchors are no longer counted as camera positions.** Three separate rows —
   Camera poses, Segment origins, Segments — never summed, plus the sentence an
   uncalibrated walk needs. §8 of the boundary document.
3. `TowerClient.isStreamingToTower` moved out of `#if DEBUG` (the two functions
   that *write* it did not), because "this phone has a capture open" is the
   phone's half of the binding and a Release build must be able to answer it —
   with `false`, which is the truth about a build with no capture control.

**Unchanged, and checked:** one socket, one subscription per connection,
`TowerClient`/`TowerWorldBuilderClient` separation, cartridge-blind transport,
`frame_result` byte-for-byte, absent-vs-zero, the resubscribe budget, and the
reconnect path. **Tower code: not touched.** No contract defect was found.

**Verification run:** full iOS suite green on iPhone 17 Pro (iOS 26.5); Debug
and Release both build; Debug builds and signs for the physical device. 16 new
tests, of which the load-bearing one is
`testAWorldFromAnEarlierCaptureIsNotShownAsThisSessionsResult`.
