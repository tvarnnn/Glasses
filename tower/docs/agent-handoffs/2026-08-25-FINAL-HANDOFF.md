# Final handoff — World Builder lifecycle hardening, 2026-08-25

**Starting commit:** `35214a1` (tree clean)
**Branch:** `integration/world-builder-lifecycle-v1`
**Final commit:** `75a5d0f` — 18 commits, tree clean
**Scope:** 42 files, +11,615 / −161
**Tower tests:** 1015 → **1163 passed, 32 skipped** (+148). Zero failures.
**iOS:** unchanged, and unchangeable here. See §3.

---

## 1. The three things that were believed and were wrong

Every correction below is read off artifacts still on disk under
`data/`, not recalled.

### "Camera poses: 36" was not 36 poses

```json
{"backend_id": "unposed", "keyframes": 155, "poses_solved": 0,
 "poses_refused": 119, "points": 0, "segments": 36, "scale_state": "unknown"}
```

`points.json` is literally `{"points": []}`. All 119 non-anchor pose rows
carry `degeneracy: "no_intrinsics"` and all 119 edges carry
`cheirality_fraction: null` — **no geometric gate was ever evaluated**.
The 36 were segment anchors: identity rotation, zero translation, all at
the same point. They reached the phone through
`pose_count = keyframes − poses_refused`, and `unposed.py` says in a
comment that the ANCHOR status exists precisely so a consumer cannot
count it as evidence.

The system did not cross the pose boundary on 2026-08-24. It produced
keyframes, tracking and a persisted world — all real — and one wrong
number.

### The lifecycle desync was ten captures, not a detaching follower

The walk recorded ten captures in 435 s; the world followed the first.
WiFi dropped at t=121.9 s and the successor arrived at t=226.8 s — a
105 s gap against the 90 s `RESUME_GRACE_SECONDS` — so the follower
correctly concluded the walk had ended, finalised, and exited. Nine
further captures were recorded that nothing was reading.

**The reconnect machinery worked, and that is its first physical
validation.** Full table in
`guidelines/docs/reports/2026-08-25-world-builder-lifecycle-run-report.md`.

### Fragmentation outranks calibration

36 segments, ten of them a single keyframe. Segments share no coordinate
frame, so scale is forced to `unknown` and path length refused — and
would be with perfect intrinsics.

---

## 2. What changed

| Before | After |
|---|---|
| Nothing ever started a follower | Every capture gets one, at the moment its id is minted |
| A human read a UUID off a directory listing | Nothing types a capture id, including the tests |
| `--rebuild-every 0`: build once, at the end | Cadence 4 by default; geometry appears mid-walk |
| A rebuild re-solved everything, O(N²/k) over a walk | Extends one live solve; **6.83 s → 0.92 s** over 64 keyframes |
| 36 tracking segments on a real walk | **20**, single-keyframe segments 10 → 4 |
| A silent backend downgrade | Announced and recorded |
| Anchors reported as camera poses | Counted per segment; 0 when nothing solved |
| `declared_size` 480×360 against a 360×640 stream | Given only where it is actually known |
| A follower that logged nothing for a whole walk | Session start, each rebuild, completion |
| `calibrate_charuco --out` had no default; `--intrinsics` no discovery | Resolution-keyed store, found with no flag either end |
| Multiple terminals, manual venv, silent env vars | `start_tower.ps1`, one command |
| README claimed a `0.0.0.0` default that does not exist | Six corrections; `TOWER_WORLD_ROOT` was absent entirely |

**Architecture.** `tower/capture_workers.py` is a cartridge-blind
supervisor: it runs an argv when a capture opens and reaps it when the
capture closes. `main.py` builds that argv as plain strings, so the web
process still imports no cartridge and still **never builds** — it
supervises a child that builds. One worker per capture *lineage*, so a
reconnect cannot fork a walk into two worlds.

---

## 3. iOS — nothing was changed, and why

Two hard blocks, both verified rather than assumed:

1. **No Swift toolchain on this machine.** `xcodebuild`, `swift` and
   `swiftc` are all absent; it is Windows. iOS Debug build, iOS Release
   build and the iOS test suite **could not be run by any means.** They
   are not reported as passing because they were not run.
2. **The Tower-backed `WorldBuilderClient` is in no branch of this
   repository.** `main`, `ios-origin/main`, `ios/cartridge-integration`,
   `ios/integration-candidate`, `ios/fix-camera-start-regression` all
   contain only `UnavailableWorldBuilderClient`, whose state is a
   constant `.unsupported`. I re-fetched `ios-origin`; newest commit
   2026-08-23 00:01, before the test. The client that showed "Building /
   Keyframes 143" is on your Mac and unpushed.

Writing iOS code here would have been unbuildable, unverifiable, and
likely to collide with it. Instead:
**`docs/agent-handoffs/IOS-WORLD-BUILDER-INTEGRATION.md`** — the session
binding that fixes camera-LIVE-beside-a-frozen-world, the contract bump,
what will now appear mid-walk, the test list, and the exact payload for a
trajectory viewer if you ever want one.

**Push the Mac client first.** Nothing in that document can be reviewed
against a tree that lacks it.

---

## 4. Contract change — action required

`world_builder.status/2026-08-23` → **`world_builder.status/2026-08-25`**.

It moved because `trajectory.pose_count` **changed meaning**, not because
a field was added. A consumer that pins the identifier is refused with
`contract_mismatch` and must adopt the new one deliberately. A consumer
that does not pin it is unaffected — the key set is unchanged apart from
the added `poses_anchor`. Full changelog in
`docs/contracts/CARTRIDGE-RESULTS.md` §12.

---

## 5. Calibration — the only physical blocker

Genuinely blocked, and no code can unblock it. The published ~100° FOV
describes a 3:4 still while the stream is 9:16 through an undocumented
crop; `schema.py` refuses a "guessed" source; loosening
`calibrate_charuco.py`'s view requirements yields 287–3787 % fx error
while *improving* reprojection RMS.

**The plumbing is now closed.** A calibration written by
`calibrate_charuco.py` lands in `<world_root>/intrinsics/<w>x<h>.json`
and the builder finds it by observed frame size, with no flag on either
end. A miss behaves exactly as today and says so.

**`docs/CALIBRATION.md`** is the procedure. Two of its claims were
measured rather than repeated, and one corrects the brief that
commissioned it: a **uniform** print-scale error does not affect `fx` at
all, while a **10 % anisotropic** stretch costs 12 % `fx` error at an
unremarkable 0.67 px RMS. So the check is that the squares are square,
not that they are 40 mm.

---

## 6. Verification

### PROVEN IN AUTOMATED TESTS (1163 passed, 32 skipped)

- Start → walk → Stop leaves one world naming the streamed capture, with
  the session closed and the worker reaped. Real subprocess, real world.
- A reconnect produces one world and one worker.
- Geometry appears during the walk.
- A subscriber is told over the wire while the stream is open, reporting
  `uncalibrated` / `unknown` / `pose_count: 0`.
- Incremental extension is **byte-identical** to a cold solve, with a
  canary test proving the RANSAC oracle is deterministic so the
  comparison can be `==`. The pre-existing
  `test_a_mid_walk_rebuild_does_not_change_the_final_result` passes
  **unchanged**.
- A live solve that fails costs the session nothing.
- A worker that fails to spawn is reported and never costs the recording.

### PROVEN ON PHYSICAL HARDWARE

The 2026-08-24 capture and reconnect lineage behaviour, in the previous
build. **Nothing else.**

### NOT YET PHYSICALLY VALIDATED

**Everything written on 2026-08-25.** The automatic attach, the cadence,
the keyframe policy, the pose-count correction, the intrinsics store and
the startup scripts have met synthetic frames, recorded frames and a real
subprocess — never the glasses. The previous validation does not
transfer.

Also not validated: iOS anything (§3).

---

## 7. The next physical test

```powershell
powershell -NoProfile -File scripts\setup_tower.ps1   # once
powershell -NoProfile -File scripts\start_tower.ps1
```

Then: open World Builder, **Start**, walk, **Stop**. That is the whole
procedure. One terminal.

**Watch for, in order of importance:**

1. **`[Tower][Worker] started pid N for capture <id>`** within a second
   of pressing Start. If it does not appear, nothing else matters.
2. **`[Tower][WorldBuilder] rebuild N:` lines during the walk.** This is
   the live-building claim. Note the wall time each one reports.
3. **Keyframe count on the phone climbing, and geometry appearing before
   you press Stop.**
4. **Deliberately break the WiFi mid-walk.** You should see the capture
   chain and **no second worker start**. One world at the end.
5. **`poses 0, points 0, calibration uncalibrated`.** This is the
   CORRECT result and not a fault. If it says anything else, something is
   wrong.
6. **The segment count.** The keyframe change predicts ~20 on a
   121-second walk rather than 36, and +68 % keyframes. Both are
   predictions from one replay of one walk and want a second walk in a
   different room.
7. **Whether the world stops growing while the camera is live.** It
   should not any more.

**Then, if you have twenty minutes:** `docs/CALIBRATION.md`. It is the
single highest-value physical action available and it is what stands
between this system and geometry.

---

## 8. Remaining blockers

| Blocker | Status |
|---|---|
| Camera calibration | Physical. Plumbing closed, procedure written, board unprinted |
| iOS client not in the repo | Push from the Mac |
| iOS build/test | Impossible on this machine, ever |
| `stream_started` with `capture_id` | Not implemented; blocked on a consumer, not on Tower work |
| Pose/point arrays on the wire | Same |
| Metric scale | Unreachable in V1 by any route. Calibration does **not** deliver it |
| Distortion model on a ~100° lens | Completely unexercised; synthetic input has zero distortion |
| Whether 360×640 supports reconstruction at all | Unknown until a calibrated walk |

---

## 9. Secondary work

Four implementation-ready plans, each grounded in this repository:

- **Object Memory × World Builder** — the honest first slice has no
  geometry. Also found: **COCO has no `keys` class**, so the canonical
  demo question is unanswerable by the only detector in the repo. The
  hard part was never the *where*.
- **Scene Understanding × World Builder** — spatial context may only
  *invalidate* a claim, never make one. Recommends keeping the cartridge
  ephemeral, and argues it.
- **Document Memory + Environmental Memory** — Document Memory's wire
  contract is the highest-value next step; bursty capture is **not**
  justified yet and the experiment that would settle it is specified;
  Environmental Memory **should not begin**.
- **Translator** — audio is reachable but **not through DAT**: Bluetooth
  HFP via AVFoundation, documented 8 kHz mono, and A2DP/HFP are mutually
  exclusive. That reshapes the whole benchmark and the prior plan listed
  it as an open question.

Two defects were found by that work and fixed here: the cartridge import
rule checked one ordered pair out of six, and `SCENE-UNDERSTANDING.md`
still justified its privacy posture with "no face detector exists on this
platform anyway", which stopped being true when YuNet was vendored.

---

## 10. Merge recommendation

**Do not merge yet. Physically test first.**

The branch is coherent, every commit is green, and the full suite passes.
But the entire point of this work is a lifecycle that only hardware can
exercise, and the honest position is that none of it has met the glasses.
Run §7. If the worker attaches and the world grows during the walk, merge
it. If it does not, the logs added tonight are designed to say why
without a second terminal.

One caveat if you do merge: the keyframe policy change is tuned on **one
walk in one room**, costs +68 % keyframes, and shifts the dominant
promotion path from parallax to track-decay. It is reversible in three
constants and they are commented with exactly that.
