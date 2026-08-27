# Walk evidence for the World Builder lane — phone-side, 2026-08-26

> **READ §0 FIRST. A second, controlled walk has since been run and it
> REFUTES this document's central hypothesis.** §1 and §2 are kept because
> their measurements are still correct and the reasoning is worth seeing
> falsified, but the conclusion they point at is wrong.

## 0. The controlled walk — the transport gap was NOT the cause

A second walk was run specifically to test §2: **no reconnect, no pause, no
interruption, sustained lateral/arc movement**, on an instrumented build.

**The controlled condition held perfectly.**

| | walk 1 (with the 9 s gap) | walk 2 (clean) |
|---|---|---|
| reconnects | 1 | **0** |
| send stalls | 1 | **0** |
| frames not sent | ~216 | **0** |
| `tracking` != Good | 2 samples | **0 of 129 samples** |
| stream brackets | 2 | **1** |
| keyframes | 141 | 353 |
| segments | 14 | **28** |
| anchors | 14 | **28** |
| solved poses | 30 | 72 |
| points | 3,732 | 7,086 |
| `scale_state` | unknown | **unknown** |

**The fragmentation and the yield collapse happened anyway, and both were
worse.** Marginal reconstruction yield across walk 2:

| keyframes | points | poses | segments | marginal pts/keyframe |
|---|---|---|---|---|
| 91 | 1,138 | 16 | 6 | — |
| 127 | 4,886 | 45 | 9 | 88.6 |
| 174 | 4,958 | 49 | 12 | 2.4 |
| 223 | 6,195 | 59 | 14 | 41.2 |
| 245 | 6,942 | 66 | 18 | 34.0 |
| 300 | 7,086 | 72 | 25 | 4.2 |
| **353** | **7,086** | **72** | **28** | **0.0** |

First half **28.1 points/keyframe**; second half **1.4**. A **20× collapse**,
against the 14× that walk 1 showed — with no transport gap anywhere in it.

**From keyframe ~300 to 353 the reconstruction produced literally nothing:**
points frozen at 7,086, poses frozen at 72, while segments still grew 25 → 28.
The last ~53 keyframes bought three more empty segments and not one point.

**So the hypothesis in §2 is refuted.** The nine-second gap in walk 1 was real
and is still worth avoiding, but it is **not** what fragments the world. This
lane will not offer it as an explanation again, and you should not spend time
on it.

**What the controlled walk points at instead**, stated as observation not
diagnosis, because the algorithm is yours:

- **`anchors == segments` in both walks — 14/14 and 28/28.** Every segment is
  its own anchor. Nothing has ever registered to anything else in any walk this
  lane has observed.
- **Yield is stepwise, not smooth**: 88.6, then 2.4, then 41.2, 34.0, then 4.2,
  then flat. That reads like rebuilds landing intermittently and then ceasing,
  rather than accumulation tailing off.
- **New segments keep opening after point growth has stopped entirely.**
  Whatever decides to start a segment is still firing when whatever solves one
  has given up.
- **`tracking` reported `Good` for the entire walk** while all of the above was
  happening. Whatever "Good" measures, it is not predictive of reconstruction
  succeeding — worth knowing before it is surfaced to a wearer as reassurance.

**P11 also ran, and its prediction failed.** The walk was sustained lateral and
arc movement — the motion the sidestep experiment says should make scale
observable — and `scale` remained `Unknown` from the first status to the last.
That is a negative result on a stated prediction, not a missing measurement.

---

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

### 1.1 Correction — the reconnect is not what cost the nine seconds

**An earlier revision of this document said the phone's reconnect decision cost
the walk nine seconds. That was wrong, and the console says so.** Decomposing
it properly:

- the **first** dropped frame reads `status=failed("Send stalled for 2.0s")`;
- **every one after it reads `status=connecting`.**

There was one reconnect attempt, and it spent roughly **8.5 of the 9 seconds
unable to complete a WebSocket handshake**. The backoff is 0.5 s. So the cost
attributable to the phone deciding to replace the connection is on the order of
**0.6–0.9 s — under 10% of the hole.** The other ~8.5 s is something that
stopped a *brand-new* socket from being established.

**Three hypotheses fit, and they are not equivalent for you:**

1. **A new TCP flow paying SYN retransmission** (1 s / 2 s / 4 s) where an
   established flow would have retransmitted from a measured RTT. Phone-side,
   and ours to measure.
2. **The Tower's event loop was blocked**, serving neither the old socket's
   reads nor the new socket's upgrade. **This walk was the first with World
   Builder reconstruction running on the Tower**, `tower/handoff.md:709`
   already names "blocking the socket read path >2 s" as a known anti-pattern,
   and the original send-window baseline measured a **52-second** Tower-side
   read stall. If a rebuild ran synchronously on the event loop for ~8 s, that
   predicts exactly what was observed — on both sockets at once.
3. **A genuine link outage** for ~8.5 s, in which case nothing either lane does
   would have helped.

**Only hypothesis 2 is yours**, and it is the one we cannot test from the phone.
If a rebuild can occupy the event loop for multiple seconds, the phone's
2.0 s stall detector will keep replacing connections during exactly the moments
reconstruction is working hardest — and each replacement costs a frame gap that
makes reconstruction harder. That is a feedback loop, not a coincidence, and it
would be worth checking whether any World Builder work runs on the request path
rather than in an executor.

**What we have done so we both stop guessing:** the phone now logs each
handshake leg separately — connect+upgrade ms, pong ms, total — and prints the
slot-lifetime max, send-latency max and prior stall-recovery count alongside
every stall verdict. The next walk will say which of the three it was. **If it
turns out to be the Tower's read path, the fix is not in `ios/` and we will not
attempt it.**

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

- **The stall detector is phone-side, and we investigated raising it and
  refused.** `SendWindow` capacity is 4 (12 fps × 1/3), measured against a
  physical baseline and since confirmed at 11.97 fps over 9,199 frames — it is
  not a guess and it is not moving. The 2.0 s stall threshold *is* a judgment
  rather than a measurement, but raising it would not have saved this walk: the
  replacement connection needed ~8.5 s, so any threshold under that fires
  anyway and merely makes the hole longer. It is also a published cross-lane
  invariant (`tower/handoff.md:622`), and the repo pre-registered the condition
  for changing it — "stall recoveries climbing continuously" — which n=1 does
  not meet. **We are not changing `sendStallTimeout`, `outboundLatencyBudget`
  or `FrameRateGate.towerTargetFPS` on this evidence**, and we will coordinate
  with you before touching the frame rate.
- **We did fix a real defect the walk exposed by accident.** The connect leg of
  the handshake had no deadline at all: a peer that accepts TCP and never
  upgrades parked the client in `.connecting` permanently, with the reconnect
  budget never spent and nothing trying again. It is now bounded by a watchdog
  that cancels the socket. Unrelated to your lane; recorded because it means a
  future walk cannot silently stop reconnecting.
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
