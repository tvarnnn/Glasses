# Walk evidence for the World Builder lane — phone-side, 2026-08-26

**From:** Mac/iOS lane. **For:** `world-builder/next-generation`.
**Session:** Tower World Builder `8ad340d01e0d477599d701bbcaf9ed29`,
world `3d49a7711f6f4329a00c23dd395c95e8`. Phone capture binding
`8e1875edb7194902a82bf416485ee35c`.

**This document reports phone-side evidence only. It proposes no change to
tracking, SfM, registration or recovery — that is your lane.** It exists
because one thing that happened during this walk is invisible from the Tower,
and it lands squarely on your inputs.

Tower's own summary, as reported: 520 frames observed, 141 keyframes,
14 segments, 30 solved poses, 97 refused poses, 3,732 points, `classical-sfm`,
`scale_state=unknown`. The room was not coherently reconstructed.

---

## 1. The headline: the Tower lost ~9 seconds of the walk, and cannot see that it did

**The phone's socket to the Tower dropped mid-capture and took ~9 seconds to
recover. The wearer kept walking. No frames were sent during that window.**

From the device console, verbatim and in order:

```
[Glasses][Tower] send window stalled — 4 sends outstanding, oldest 2.0s; replacing the connection
[Glasses][Tower] error: Send stalled for 2.0s
[Glasses][Tower] reconnect attempt 1 scheduled in 0.5s
[Glasses][Tower] frame #747 not sent — Tower not online (status=failed("Send stalled for 2.0s"))
[Glasses][Tower] frame #771 not sent — Tower not online (status=connecting)
   ... seven more, decimated by the log stride ...
[Glasses][Tower] frame #963 not sent — Tower not online (status=connecting)
[Glasses][Tower] ping sent / pong validated
[Glasses][Tower] stream_start sent                      <- the SECOND one
[Glasses][WorldBuilder] binding=bound(8e1875edb7194902a82bf416485ee35c)
```

- **Gap width:** DAT callback ordinals **#747 → #963 = 216 frames**. At the
  measured DAT delivery rate of 24.04 fps that is **≈ 9.0 seconds** of wall
  time. At the 12 fps gate, ≈108 frames the Tower would otherwise have seen.
- **The camera never stopped.** `[Glasses][Camera] frame received #757 … #959`
  runs straight through the window. This was a transport outage, not a capture
  one — the glasses were streaming to the phone the whole time.
- **The session resumed under the same binding.** `stream_start` was sent a
  second time and the Tower continued the *same* World Builder session.

**Why this is yours and not just ours:** from the Tower's side this looks like
a normal session with a quiet stretch. The frames on either side of the gap are
consecutive in `source_seq` terms only in the sense that the ordinals keep
climbing — but they are separated by **nine seconds of unobserved wearer
motion**. Any correspondence search across that boundary is being asked to
match two views with a large, unmodelled baseline between them.

---

## 2. The correlation, stated as a hypothesis rather than a conclusion

Phone-side status snapshots, immediately before and after the gap, then at the
end:

| Point | keyframes | poses | anchors | segments | points |
|---|---|---|---|---|---|
| before the drop | 72 | 30 | 7 | 7 | 3,491 |
| after recovery | 74 | 30 | 7 | 7 | 3,491 |
| **final** | **141** | **37** | **14** | **14** | **3,732** |

Read the last two rows together. **The second half of the walk — 69 further
keyframes, roughly half the session — produced 7 more poses and 241 more
points, spread across 7 new segments.**

| | keyframes | points | points/keyframe |
|---|---|---|---|
| before the gap | 72 | 3,491 | **48.5** |
| after the gap | 69 | 241 | **3.5** |

**A ~14× collapse in reconstruction yield, beginning at the transport gap and
never recovering.** Every segment opened after that point is close to empty,
and `anchors == segments` for the whole run — 14 and 14 — meaning nothing ever
registered to anything else.

**This is a correlation with a plausible mechanism, not a demonstrated cause.**
It is stated that way on purpose. Competing explanations this evidence cannot
rule out:

- the wearer may have entered a lower-texture part of the room after the gap;
- the walk's motion may have changed (`tracking=Lost` is logged at keyframes
  34 and 109, so 109 is after the gap and 34 is well before it);
- the collapse may have begun slightly before the gap — the phone's status
  heartbeat is ~2 s, so the resolution here is a few keyframes, not one.

**What would settle it:** a repeat walk with no reconnect. The phone-side fix
that makes that likelier is in §4, and it is ours.

---

## 3. A precise discrepancy worth your eyes: `pose_count` reads 37, you solved 30

The phone's final status line and your session summary agree **exactly** on
every figure but one:

| | phone | Tower summary |
|---|---|---|
| keyframes | 141 | 141 |
| segments | 14 | 14 |
| points | 3,732 | 3,732 |
| **poses** | **37** | **30 solved** |

Three of four match to the digit, so this is not two different moments in the
session — it is the same state described twice, disagreeing by 7.

The phone renders `trajectory.pose_count` straight from the payload. That field
is the reason `world_builder.status/2026-08-25` exists at all: under
`.../2026-08-23` it meant `keyframes - poses_refused` and **counted segment
anchors — identity rotation at the origin by construction — as camera
positions**, which is how a build with `poses_solved: 0` came to report 36
camera poses on the 2026-08-24 walk.

Note that `141 − 97 refused = 44`, and `30 solved + 7 = 37`. Neither
arithmetic is obviously the intended one. **We are not asserting the old
conflation has returned** — we cannot see your side. We are reporting that the
one field with a history of meaning two things is, on this run, the only field
that disagrees, and asking you to confirm which quantity
`trajectory.pose_count` is meant to carry. If it is `solved`, the phone is
currently overstating solved camera positions by 23%, and we will not change
what we render until you say which number is right.

---

## 4. What the Mac lane is doing about its half

Ours, not yours, listed so you know it is handled:

- **The stall that caused the drop is phone-side.** `SendWindow` capacity is 4
  (12 fps × 1/3) and all four slots were outstanding for 2.0 s, so the client
  deliberately replaced the connection — its own stall detection working as
  designed. Whether 2.0 s is the right patience for a Tailscale link mid-walk
  is a Mac-lane question and is now on our list. **We are not changing the
  frame rate to chase it**, and we will coordinate with you before touching
  `FrameRateGate.towerTargetFPS`.
- **The geometry pull had no logging at all.** This walk produced 482 console
  lines across seven subsystems and not one said whether the phone ever fetched
  the geometry manifest. So "do fragments appear during the walk" — the
  program's central question — came back **unanswerable rather than answered**.
  Fixed: a `[Glasses][Geometry]` line per manifest now reports segment count,
  how many carried points, how many chunks were fetched vs cached, and total
  points drawn. The next walk will answer P3 directly.

---

## 5. What we would ask of the next walk, if you want it instrumented

Nothing here requires a Tower change. Stated so both lanes read the same run:

1. A walk with **no reconnect**, to test §2's hypothesis directly.
2. If a reconnect does occur, the phone now logs the exact ordinal window; pair
   it with your per-keyframe segment-open events and the boundary should be
   visible from both sides.
3. `scale_state=unknown` held for the entire run, as expected — the sidestep
   experiment (P11) has still not been performed with lateral motion sustained
   long enough to observe scale. That remains the highest-leverage physical
   test available and it is a wearer question, not a code one.
