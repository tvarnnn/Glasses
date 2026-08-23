# Mac Handoff — raise the iOS observation rate from 0.8 to 10–15 fps

Produced by the 2026-08-21 Windows/Tower session that investigated the
FPS bottleneck observed in the first physical-glasses remote end-to-end
run. **The bottleneck is in Swift code that does not exist in this
repository**, so this session could not implement the fix. The Tower-side
half — instrumentation that makes the bottleneck self-reporting — is
implemented and merged; this document describes the iOS-side half.

Companion documents:
- `guidelines/docs/reports/2026-08-21-first-physical-glasses-remote-baseline.md`
  — the measured baseline this handoff is responding to.
- `docs/superpowers/handoffs/2026-08-20-source-seq-tx-seq-split.md` — the
  earlier, still-unimplemented `source_seq`/`tx_seq` ask. **Do both at
  once**; they touch the same code path and §4 below depends on it.

## Root cause (proven, not suspected)

The Tower received 0.8 fps because **the iOS sender forwards only ~1 in
every 30 DAT capture frames**. Nothing else was limiting the pipeline.

The evidence chain:

1. **Arithmetic.** The run received 63 frames over 78.999 s with the last
   `seq` at ~#1860 and `seq_gap_total` 1797. `1860 − 63 = 1797` exactly,
   so every single missing sequence number is accounted for by the stride
   with **zero residual** attributable to transit loss. Mean spacing
   `(1860 − 1) / 62 = 29.98` — a 1-in-30 stride. Implied capture rate
   `1860 / 79 ≈ 23.5 fps`, consistent with a DAT `frameRate: 24`
   configuration.
2. **The stride is documented, deliberate, and pre-existing.**
   `guidelines/docs/07-PLATFORM-CONSTRAINTS.md` Limitation 9 (2026-08-19
   finding, confirmed with the iOS team in commit `aa2460e`): the sender
   "only forwards roughly 1-in-30 of them (a throttled capture ->
   transmit branch)". Also `README.md:340`, `tower/metrics.py`, and
   `tests/test_metrics.py:52`.
3. **The network is exonerated by a control run.** The 2026-08-19 V0.7
   soak over **LAN** measured **0.81 fps** (695 frames / 856.882 s —
   `guidelines/docs/reports/V0.7-sustained-streaming-report.md:48`). The
   remote Tailscale run measured **0.80 fps**. A ~2-hour-distant WAN path
   and a same-room LAN produce the same number, because a fixed stride is
   bounded by capture rate, not by bandwidth.
4. **The Tower is exonerated by measurement.** CV processing averaged
   0.82 ms and receive-to-result 1.98 ms, i.e. the Tower was idle >99.8%
   of the session. Measured the same day at the same 360x640 resolution,
   the Tower sustains **~736 fps** as shipped — roughly 900x the observed
   rate and ~50x the target — using 2.3% of one core at 12 fps, with
   latency that *falls* rather than rises under load and no drops at any
   rate. Full table in the baseline report.

**Not** the cause: Tailscale, ATS, packet loss, JPEG decode, Tower CV,
Tower backpressure (`backpressure_drops` was 0 and no code path can
increment it yet), or the remote path in general.

### Caveat carried forward — verify before you change code

Per Rule 4 and the earlier handoff (lines 128-133), the "1-in-30" figure
has **never been read off the Swift source**; it comes from the 2026-08-19
"confirmed with the iOS team" note. The wire arithmetic above independently
confirms the *effective* stride is ~30, but **not** its mechanism —
a fixed `frameCount % 30` stride and a 0.8 s timer are indistinguishable
from the Tower. Read the actual capture→transmit branch first; §2's design
differs depending on what you find.

## 1. Target

**10–15 fps received by the Tower**, under the physical
DAT → iPhone → remote Tower path.

At the capture rate observed (~23.5 fps), a 1-in-2 stride yields ~11.8 fps
and lands in range. Do not aim for the full capture rate — see the
bandwidth budget in §3.

## 2. The change: replace the fixed stride with a target-rate cadence

**Preferred: time-based cadence.** Forward a capture frame when
`now - lastForwardedAt >= 1.0 / targetFps`, with `targetFps` a named
constant (start at **12**). Delivered rate becomes
`min(captureFps, targetFps)`.

Why not simply change the stride constant from 30 to 2 — which would also
hit the target and is a smaller edit? Because a stride is defined against
a capture rate that **DAT changes underneath you**.
`07-PLATFORM-CONSTRAINTS.md:82` records that DAT's internal adaptive
ladder lowers frame rate under bandwidth pressure (never below 15 fps),
and `frameRate` is a discrete choice from `{2, 7, 15, 24, 30}`
(line 80). A 1-in-2 stride silently delivers 7.5 fps if DAT drops to 15,
and 15 fps if the config is later raised to 30 — the delivered rate moves
without anyone changing it. A cadence is stable across all of those.
This is a small amount of extra code buying a rate that means what it
says; take it.

**Required properties** (`02-DEVELOPMENT-RULES.md` Rule 15,
`01-SYSTEM-ARCHITECTURE.md` — Backpressure):

- **Latest-frame-wins, never a growing queue.** If a frame is still
  encoding or in flight when the next capture callback fires, *replace*
  the pending frame rather than enqueueing it. At most one frame pending
  plus one in flight.
- **Do not block on the `frame_result` ack.** This is the most likely
  place to reintroduce the bottleneck. If the sender awaits each ack
  before sending the next frame, throughput is capped at `1/(RTT +
  processing)` regardless of `targetFps` — and on a ~2-hour-distant
  Tailscale path an RTT of 40–80 ms alone caps you at 12–25 fps, right on
  top of the target. Keep sends fire-and-forget and consume
  `frame_result` asynchronously for metrics. (For reference: the Tower's
  own soak client, `scripts/soak_test_stream.py`, *is* ack-blocked and so
  is RTT-bound by construction — do not copy its structure.)
- **Drop stale frames under pressure, do not accumulate latency.**
  Freshness beats completeness for temporal CV.
- Keep the existing narrow ATS development exception exactly as it is.
  Do not broaden it, and do not enable arbitrary loads.

## 3. Bandwidth budget — check this before raising `targetFps` further

Measured from the baseline run: `1017780 bytes / 63 frames` = **16,155
bytes per JPEG** at 360x640.

| Delivered fps | JPEG payload | On the wire (+33% base64) |
|---|---|---|
| 0.8 (baseline) | 0.10 Mbps | ~0.14 Mbps |
| 12 (target) | 1.55 Mbps | **~2.07 Mbps** |
| 15 | 1.94 Mbps | ~2.58 Mbps |
| 23.5 (every frame) | 3.04 Mbps | ~4.05 Mbps |

Careful when cross-checking these against the Tower's own summary: the
`bandwidth_bps` field is **bytes** per second despite its name (it is
`bytes_received / elapsed`). The baseline's `bandwidth_bps: 12883.52`
is 12.9 kB/s ≈ 0.10 Mbps, not 12.9 kbps — an 8x trap.

~2 Mbps of sustained uplink is reasonable over broadband or good 5G, and
is the main reason to prefer 12 fps over uncapped forwarding. On a weak
cellular uplink, expect DAT's adaptive ladder to reduce resolution first
— which the cadence design absorbs without changing the delivered rate.

Two things worth noting but explicitly **out of scope** here:
- Frames are base64 inside JSON, costing a flat 33%. A binary WebSocket
  message would remove it, but that is a wire-protocol change affecting
  both sides; do not bundle it with this fix.
- Observed resolution was 360x640, below the roadmap's ~504x896 target.
  Worth understanding (app config vs. DAT adaptive downscale) but it is a
  separate question from the frame *rate*.

## 4. Sender-side counters to report

The Tower can now infer the upstream capture rate and the sampling stride
on its own (§5), but it cannot see anything that happens *before*
transmission. Add these so the next run needs no inference at all. Log
them on the iPhone at `stream_stop`; sending them over the wire is not
required and would need a protocol change.

| Counter | Meaning |
|---|---|
| `captureCallbacks` | DAT `VideoFrame` callbacks received |
| `framesSelected` | passed the cadence gate |
| `framesEncoded` / `encodeMsAvg`, `encodeMsMax` | JPEG encode count and cost |
| `transmitAttempts` | `send` calls issued |
| `sendsSucceeded` | sends that completed without error |
| `framesReplaced` | pending frames dropped by latest-wins |
| `framesDroppedOther` | any other sender-side discard, with reason |

Also implement `source_seq` and `tx_seq` from the earlier handoff — the
dense `tx_seq` is what finally lets the Tower report transit loss
(`tx_seq_gap_total`) instead of a null. Without it, a raised rate cannot
be distinguished from a raised rate *with* new loss.

## 5. What the Tower already does (no iOS work needed)

Merged this session. `SessionMetrics` now reports these additional fields
in every `[Tower][Session] summary` / `final summary` line, derived from
`source_seq` (which falls back to `seq`, so they work with the sender
exactly as it is today):

| Field | Baseline run would have shown |
|---|---|
| `source_seq_span` | 1859 (`1860 − 1`) |
| `source_frame_span_s` | slightly under 78.999 |
| `sampling_stride_avg` | 29.98 (`1859 / 62`) |
| `source_fps_estimate` | ~23.5 |
| `frames_rejected` | 0 |

`source_fps_estimate` is `source_seq_span / source_frame_span_s`, measured
between the first and last frame received — **not** over the whole
`stream_start`-bounded window that `effective_fps` uses. So it would have
read slightly above the `1859 / 78.999 = 23.53` the logged session
duration implies. Both spans are reported so the two rates can be
reconciled instead of looking contradictory.

`frames_rejected` counts frames that arrived and were answered with a
`frame_error`. It matters here because `sampling_stride_avg` divides by
frames actually recorded: if the Tower intermittently rejects frames, the
stride is inflated and would read as a sender throttle that isn't there.
**Check `frames_rejected == 0` before trusting the stride.** It was 0 for
the baseline run, so that run's numbers are unaffected.

Read alongside `effective_fps: 0.8`, those state the diagnosis directly:
*a ~24 fps capture stream, decimated ~1-in-30, delivering 0.8 fps.* All
three report `None` rather than `0` when fewer than two frames have
arrived or the capture index has not advanced (Rule 3).

## 6. Acceptance criteria

1. The capture→transmit branch has been read, and the actual pre-existing
   throttle mechanism is recorded here or in `07-PLATFORM-CONSTRAINTS.md`
   (closes the Rule 4 caveat above).
2. A physical run reports `effective_fps` between 10 and 15.
3. The same run reports `sampling_stride_avg` ≈ 2 and
   `source_fps_estimate` ≈ 23–24 — i.e. the rate rose because the stride
   fell, not because capture changed.
4. `tx_seq_gap_total` is `0` (or a small, honestly-reported number) rather
   than `null`, proving the new rate is not being paid for with transit
   loss.
5. `receive_to_result_ms_avg` stays in single-digit milliseconds and
   `process_cpu_percent` stays modest — expect roughly 1–2 ms and ~2–3%
   of one core at 12 fps, per the measured capacity table. (That field is
   now a true session average; before 2026-08-21 it silently measured only
   the time since the last periodic summary and would have been
   meaningless for a run this long.)
6. Memory on both sides is flat across a 20–30 minute run: latest-wins
   must not have become a queue.
7. Unit test: a capture callback arriving inside the cadence interval does
   **not** advance `tx_seq` and does **not** transmit.
8. Battery/thermal behavior on the iPhone and glasses noted at ~12 fps —
   this is a ~15x increase in sustained radio and encode work over the
   baseline, and it is the one cost this change definitely incurs.

## 7. Explicitly not in scope

Adaptive streaming (IDLE/TRACKING/HIGH_RATE) remains deferred —
`03-ROADMAP.md:71` says not to implement it before real measurements
exist. This handoff produces those measurements; it does not spend them.
Get a fixed 12 fps working and measured first.
