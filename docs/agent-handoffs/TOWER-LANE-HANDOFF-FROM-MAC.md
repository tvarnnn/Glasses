# Tower / Windows lane handoff — from the Mac/iOS lane

**From:** Mac/iOS lane, branch `ios/world-builder-integration`
**Date:** 2026-08-26
**Upstream consumed:** `integration/world-builder-lifecycle-v1` @ `25eb794`, fully merged
**Status:** three items. One **answers a blocking prerequisite you named**;
two are **corrections to beliefs recorded in your own contract docs**.

This document exists because
`tower/docs/contracts/IOS-TO-TOWER-RECONCILIATION.md` §8 ("What Tower now
needs from iOS") lists three requirements, and the answers to two of them
were measured on this lane days ago and never handed back. They lived only
in Mac-facing documents and commit messages. That is this lane's process
defect, and this file closes it.

---

## 1. Capture timestamp semantics — **ANSWERED. §8.1 is unblocked.**

`IOS-TO-TOWER-RECONCILIATION.md` §0.3 records this as **BLOCKED**, saying
*"until `CMSampleBuffer`'s presentation timestamp is empirically established
as capture time, Tower cannot invent one."*

**It has been empirically established.** Commits `f77b623`, `002231f`,
`796929e`. Full write-up: `docs/agent-handoffs/MAC-BUILD-VERIFICATION.md` §8.4.

### 1.1 DAT's PTS is a capture clock, not a receipt stamp

1,084 frames off the real Ray-Bans over 45 s, sampled **on DAT's callback
thread before the main-actor hop**, against `mach_absolute_time`.

**The argument is the jitter, not the offset.** A stable offset proves
nothing — a phone-side stamp applied on arrival produces one too. What
separates them is that an arrival stamp inherits transport delay:

| quantity | value | reading |
|---|---|---|
| `residual_sd / d_host_sd` | **1.003** | the residual is *entirely* arrival jitter; the PTS carries none of it |
| `d_pts_sd / d_host_sd` | **0.141** | PTS deltas hold a tight 1/24 s grid while arrivals scatter from 2.5 ms bursts to 120 ms stalls |

A clock that stays regular while delivery is irregular is upstream of the
delivery. The epoch agrees independently: microsecond timescale, first frame
at 424.72 s against a host uptime of 519,597 s.

### 1.2 The blocking prerequisite — does the epoch survive a reconnect?

`tower/docs/superpowers/research/2026-08-26-two-clocks-capture-vs-receipt.md`
names this as **the** blocking prerequisite for the §6.5 wire addition.
Measured. The answer is **neither persistent nor reset**:

| Event | wall gap | clock advanced | ratio |
|---|---|---|---|
| pause → resume | 17.86 s | 17.80 s | 99.7 % |
| pause → resume | 39.165 s | 39.165 s | 100.0 % |
| **stop → start** | **25.95 s** | **7.19 s** | **28 %** |
| **stop → start** | **192.70 s** | **~10.95 s** | **5.7 %** |

A *pause* keeps the camera subsystem alive and the clock runs through it. A
*stop* tears it down and the clock freezes. **The two stop rows are the
finding:** the gaps differ by **7.4x** while the advance barely moves, so what
survives a stop is a fixed teardown-and-startup tail at each end — not
elapsed time, and not proportional to it.

It stays **monotonic** throughout, which is exactly what makes it dangerous.
Nothing looks broken.

### 1.3 The binding rule you must adopt with it

Your research doc's conservative rule — a transported capture clock is
*"valid only within a single uninterrupted connection"* — is **exactly right,
and now evidence-backed rather than cautious.**

> **The wire must carry an epoch/session identity alongside the capture
> timestamp, or the Tower must treat capture timestamps as incomparable
> across a `stream_stop`/`stream_start` boundary.**

Without one of those, splicing two segments of a capture lineage on this
clock produces a plausible, monotonic, **wrong** timeline: a consumer
deriving a duration across a lineage reconnect would report a five-minute
outage as about ten seconds.

**Also bounded:** drift is **~5 ppm**, from a clean bracket across the
39.165 s pause where the clocks disagreed by 0.19 ms. Earlier three-figure
ppm values from the 45 s stream were arrival jitter and are **withdrawn**.

**Still open, deliberately not guessed:** whether the clock survives the
glasses *powering off*. Every measurement kept them awake.

### 1.4 What this asks of you

`time_basis` is currently the constant `"tower-receipt"`
(`tower/tower/results/contracts.py:77`). You may now add a capture basis,
provided it travels with an epoch identity per §1.3. iOS is ready to send
the PTS; say what field and what epoch-identity shape you want and this lane
will add it.

---

## 2. Resolution — **CORRECTION. You already have this, and there is no ladder.**

`IOS-TO-TOWER-RECONCILIATION.md` §3.2 and §8.2 ask iOS for

> *"a way to request an occasional higher-resolution still, or failing that
> a way to learn which rung of the adaptive ladder is active"*

and §1.5 states that *"DAT's ladder changes resolution mid-stream."*

**Two things here are not true, and Document Memory's blocker is misstated
because of them.**

### 2.1 You already learn the resolution, on every single frame

iOS sends `width` and `height` in every `frame` message
(`ios/Glasses/TowerClient.swift:668-669`), taken from the actual decoded
buffer via `CMVideoFormatDescriptionGetDimensions`
(`ios/Glasses/GlassesConnection.swift:832-837`) — not from the requested
setting.

You already read them, and you already read them **twice**:
`tower/tower/routes/ws.py:88-101` handles `frame.declared_width/height`
alongside `frame.decoded_width/decoded_height`.

**Nothing needs to be built for "learn which rung is active."** The
information has been arriving on every frame all along.

### 2.2 There is no adaptive ladder

`StreamingResolution` in `MWDATCamera` is a **fixed three-case enum** —
`high` / `medium` / `low` — chosen **once**, in the `StreamConfiguration`
passed to `session.addCamera(config:)`
(`ios/Glasses/GlassesConnection.swift:614-618`). It is a request made at
stream construction. Nothing in DAT's API renegotiates it mid-stream, and
nothing in this app changes it.

**Measured on the real hardware, not inferred.** The P3 clean walk console
(`docs/evidence/2026-08-26-p3-clean-walk-console.txt`) records **108 frames,
every one of them 360×640, with zero variation** across a two-minute walk
including reconnect-free continuous streaming.

So the resolution-keyed intrinsics design justified in your §1.5 by "DAT's
ladder changes resolution mid-stream" is **defending against something that
does not happen on this hardware path**. Resolution-keying is still harmless
and arguably still correct as future-proofing — but it should not be
described as responding to an observed behaviour, and no other decision
should rest on that premise.

### 2.3 What the real gap is

iOS **pins** `StreamingResolution.low` as a hardcoded constant
(`GlassesConnection.swift:617`). The genuine missing capability is a way to
**request a different rung** — there is no control for it from the wearer,
from the Tower, or from anything short of an edit-and-rebuild.

This lane has now added a DEBUG-only developer control so the rung can be
changed on device without a rebuild, specifically so Document Memory's
premise can be physically tested. See §2.4.

**The tension you already documented remains real and unresolved:** 720p is
*actively harmful* to World Builder tracking — `min_sharpness = 25.0` is
absolute and **73.3%** of 720p frames fall below it and are rejected as
blurred — while Document Memory's word recall goes from **0.429–0.810 at
360×640 to 0.957–1.000 at 1280×720**.

**That is a genuine cross-cartridge conflict and it is not iOS's to decide
alone.** One stream cannot serve both at one rung. The options, none of
which this lane has picked:

1. A per-cartridge rung, requiring more than one stream or a switchable one.
2. An occasional high-resolution *still*, out of band from the tracking
   stream — your §3.2's original phrasing, and the least disruptive.
3. Document Memory accepts degraded recall at 360×640 and **records every
   reading as untrustworthy**, which your §3.2 already names as the fallback.

Tower should state which of these it wants before iOS builds a transport
for it. Rule 4 (do not design a negotiation before the real configuration
model is known) applies.

### 2.4 What iOS did about it this run

A DEBUG-only picker in Developer Tools selects the `StreamingResolution` used
by the next capture session. It changes nothing about the default — the
default remains `.low`, so World Builder's proven path is untouched — and it
exists so a wearer can run a Document Memory experiment at `.high` without a
toolchain. Pair it with §2.1: you will see the change on `decoded_width`.

---

## 3. Object Memory is undiscoverable from `/cartridges` — **CONTRACT GAP**

Object Memory is a real, live, contract-bearing capability:

- contract id `object_memory.observations/2026-08-26`
  (`tower/tower/results/object_memory.py:53`)
- two live HTTP routes (`tower/tower/routes/observations.py:72,85`)
- a store, a producer, an adapter, and iOS decode tests pinned against a
  real Tower's bytes

**But it appears in neither list returned by `/cartridges`.** Not in
`cartridges`, not in `not_offered`. It has **no cartridge constant at all** —
`tower/tower/results/contracts.py:37-41` defines four, and `object_memory` is
not among them.

Probed live this session:

```
GET /cartridges
  cartridges:  world_builder / status / world_builder.status/2026-08-25
  not_offered: experimental_cv, document_memory, scene_understanding
```

The consequence is that **a client cannot discover Object Memory.** iOS
hardcodes the two routes and the contract id, which is precisely the coupling
`/cartridges` was built to remove — your §0.1 calls the capability
declaration the thing to build first, "for exactly the reason you gave."

**The same is true of World Builder geometry.** `world_builder.geometry/2026-08-25`
(`tower/tower/results/world_builder_geometry.py:31`) is served over two HTTP
routes and is not in the declaration either. Only the `status` contract is
declared.

### What is being asked

Not a redesign. Either:

- **(a)** extend the declaration so HTTP-delivered contracts are declarable
  — a cartridge entry whose transport is HTTP rather than the result channel,
  so a client learns the contract id and availability from one place; or
- **(b)** if the declaration is deliberately scoped to the WS result channel
  only, **say so in the declaration itself** and name where HTTP contracts
  are declared instead.

Today it is silent, and silence here is indistinguishable from "this
capability does not exist" — which is the exact failure mode your §0.1
separated `available` from `contract` to prevent.

---

## 4. What this lane is NOT asking for

Stated so nothing is inferred:

- **No World Builder backend work.** That is
  `world-builder/next-generation`'s lane and its handoff
  (`WORLD-BUILDER-NEXT-GENERATION-MAC.md`) correctly declares **no iOS change
  required**. Verified independently: iOS decodes no event kinds at all, so
  the new `solve_chain_broken` kind cannot break any exhaustive switch here.
- **No new cartridge contracts.** The three `not_offered` reasons are sound
  and iOS's three stub clients are *correct*, not unfinished.
- **No bearing convention decision yet** (§8.3). iOS's declared convention —
  degrees from straight ahead, positive to the right — stands unchanged.
  Nothing needs to happen until Scene Understanding has a transport.
