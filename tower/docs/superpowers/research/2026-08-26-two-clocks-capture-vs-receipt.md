# There are two clocks, and Tower only has the worse one

**Date:** 2026-08-26
**Origin:** a measurement made in the **iOS lane** (`f77b623` on
`ios/world-builder-integration`), with Tower-side consequences worked out
here.
**Status:** finding confirmed on both sides. No Tower behaviour changed yet
— §5 says what would have to change and what it would buy.

---

## 1. What the iOS lane measured

DAT's frame timestamps are a **capture clock**, not a receipt time.
1,084 frames off the real Ray-Bans over 45 s, sampled on DAT's callback
thread *before* the main-actor hop, against `mach_absolute_time`.

The argument is the **jitter, not the offset** — and that is what makes it
convincing. A stable offset proves nothing, because a phone-side stamp
applied on arrival would produce one too. What separates them is that an
arrival stamp inherits transport delay:

- `residual_sd / d_host_sd = 1.003` — the residual is *entirely* arrival
  jitter; the PTS carries none of it.
- `d_pts_sd / d_host_sd = 0.141` — PTS deltas hold a tight grid at exactly
  **1/24 s** while arrivals scatter from **2.5 ms bursts to 120 ms stalls**.

A clock that stays regular while delivery is irregular is *upstream of the
delivery*. The epoch agrees independently: microsecond timescale, first
frame at 424.72 s against a host uptime of 519,597 s.

Recorded as **not** established, rather than rounded off: drift (the slope
wandered −4772 → −662 → +701 → +167 ppm as the window grew, which is noise,
not convergence) and whether the epoch survives a reconnect.

## 2. The Tower-side shadow, and a quirk it explains

Tower's journal carries **no capture timestamp**. A record holds:

```
source_seq, wire_seq, tx_seq (None), received_at,
time_basis: "tower-receipt", relpath, byte_count, width, height
```

`received_at` is the only time Tower has, and by the measurement above it
is the one carrying all the jitter.

**`source_seq` steps by 2.** Measured on a real capture: deltas are
predominantly **2** (48 of 74 sampled), with 1s and 3s from jitter. Set
against the iOS lane's 1/24 s capture grid and Tower's measured **83.5 ms
delivered interval (11.97 fps)**, the picture resolves:

> **The camera captures at ~24 fps. Tower is delivered ~12 fps.**
> Roughly every other captured frame never arrives.

The depth study (`2026-08-26-depth-ordering-on-real-frames.md`) found the
`source_seq` step-by-2 empirically and recorded it as a methodology trap —
naive `seq+1` adjacency silently keeps a third of the transitions, 854
candidate frames instead of 2,688. **It now has a cause rather than only a
workaround**, and the two lanes reached it independently by different
routes.

## 3. What this does NOT invalidate

- **The 83.5 ms delivered interval stands**, and remains the right number
  for everything measured so far. Tracking, tracker constants, and cadence
  all operate on frames Tower actually receives, so an *arrival* interval
  is the correct denominator for them.
- **`max_misses = frames_in(MAX_ABSENCE_S)` stands.** It converts seconds
  to delivered frames, which is exactly what a tracker consuming delivered
  frames needs.
- No published Tower measurement is wrong because of this.

What changes is **vocabulary**: "the frame rate" is now ambiguous and
should not be used unqualified. There is a *capture* rate (~24 fps, regular)
and a *delivery* rate (~12 fps, bursty). Any future document must say which.

## 4. What it does cost us today

- **Object Memory's `observed_at` is a receipt time.** Its `time_basis`
  field says so honestly, and the iOS copy is required to say "the Tower's
  receipt time, not the moment the shutter fired". That caveat is currently
  *true and necessary*. A capture clock exists on the phone that would let
  the product state when the shutter actually fired, and it is discarded.
- **Tower cannot distinguish "the camera slowed" from "the network
  stalled".** Both look identical in `received_at` deltas. With a capture
  clock, a 120 ms arrival gap on a regular capture grid is provably a
  transport stall, not a dropped capture.
- **True temporal adjacency is unknowable.** Tower can order frames but
  cannot say how much real time separated two *captures*, only two
  arrivals — and arrivals carry 7x the jitter.

## 5. What would have to change, and whether it is worth it

**The change is additive and backward-compatible:** an optional capture
timestamp field on the frame wire, persisted into the journal beside
`received_at`, with `time_basis` distinguishing the two. Tower must treat
it as **absent-capable** — `null` when a client does not send it, never
zero, and never silently substituted with `received_at`.

**What it would buy, stated as decisions it changes:**

1. Object Memory could report observation time instead of receipt time,
   which is a strictly more truthful answer to the question the cartridge
   exists to answer.
2. Transport diagnostics become possible: stall vs. dropped capture.
3. Any future temporal analysis gets the low-jitter clock.

**What it does not buy:** nothing about tracking, keyframes, or the
existing constants, all of which correctly use delivered frames.

**Not done here, deliberately.** This is a wire-contract change, and the
iOS lane is mid-flight compiling against the current contract. It is
specified as a FOLLOW-UP in `docs/agent-handoffs/IOS-EXECUTION-PLAN.md`
rather than implemented unilaterally, so both halves land together.

**Open question inherited from the iOS lane, and it matters more to Tower
than to iOS:** whether the capture epoch survives a **reconnect**. World
Builder's capture lineage would depend on it — a capture that chains across
a mid-walk reconnect must not silently splice two different epochs into one
timeline. The iOS lane names this as a two-minute test that has not been
run. **Until it is, a transported capture clock must be treated as valid
only within a single uninterrupted connection.**
