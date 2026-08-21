# First Physical-Glasses Remote End-to-End Baseline

Status: **MEASURED — first successful physical-hardware run of the full
pipeline. This is a PRE-FPS-OPTIMIZATION baseline.** The 0.8 fps received
here is the *starting* point for the observation-rate work, not a result to
be carried forward as the platform's capability. Per
`02-DEVELOPMENT-RULES.md` Rule 3, every number below is reported exactly
as measured.

**This report does not supersede any prior report.** The V0.7 sustained
streaming report and the V0.9.3 World Builder dataset experiments remain
valid for what they measured. In particular, the World Builder Experiments
1–2 remain **dataset-based (EPIC-KITCHENS) feasibility evidence** and are
not affected by this run — this run is *not* a physical World Builder
validation, and must not be cited as one.

## Run metadata

- Date: 2026-08-21
- Frame source: **`physical-glasses`** — the first run of this class. Not
  MockDeviceKit, not prerecorded footage, not same-LAN.
- Tower git commit: `303b2c6` (state at the time of the run; the
  instrumentation described in "Consequences" landed after it)
- CV module: baseline (`mean_intensity`)
- `end_reason` of the measured window: **`disconnect`** — the window was
  closed by connection teardown rather than an explicit `stream_stop`, so
  `session_duration_s` may include a small amount of teardown time.

## Hardware path

The complete physical chain, with no simulation at any hop:

```
Ray-Ban Meta Gen 2 (physical glasses)
  -> Meta DAT runtime
  -> physical iPhone running the Glasses app
  -> Internet / Tailscale
  -> remote Windows Tower
  -> WebSocket
  -> frame decode + verification
  -> Experimental CV module
  -> result returned to the iPhone
```

**Remote, not LAN.** The Tower was approximately **two hours away** from
the glasses and iPhone by road — a genuinely geographically separated WAN
path, not same-subnet operation. This is the first exercise of the
Phase 1.5 remote-access goal (`03-ROADMAP.md:75`), which had until now
been explicitly deferred.

Verified working at each hop:

- **Glasses**: entered Developer Mode; DAT installed; discovered by our
  iOS app; camera access granted; real camera session started; produced
  real physical camera frames.
- **iOS app**: received real DAT frames; connected to the remote Tower
  over Tailscale; transmitted frames.
- **Tower**: accepted the WebSocket connection; received real Ray-Ban
  frames; decoded them; verified declared vs. decoded dimensions;
  processed them; returned results; shut the session down cleanly.

Representative real frame, quoted from the Tower log:

```
Frame #1860
received: 15402 bytes
decoded: 360x640
verified
processed: mean_intensity=22.1122
```

Frame resolution was **360x640** — real, verified (declared dimensions
matched decoded dimensions). Note this is below the roadmap's ~504x896
V0.7 target; whether that is app configuration or DAT's internal adaptive
downscale is not established by this run.

## Networking discoveries

Two genuine blockers were found and resolved. Both are new knowledge, not
previously recorded anywhere in the repository.

### 1. Personal Hotspot blocks DAT provisioning

DAT provisioning initially failed, repeatedly, with:

```
WarpDeviceConnTransport:
[DCTEvent] Failed to open local channel. Scheduling retry.
```

The message is generic and does not name the cause. The actual cause was
only visible in the iPhone's own logs:

```
personal hotspot is active, denying join request from bundleId='com.facebook.stellaapp'
```

**Resolution: turn Personal Hotspot off, leave Wi-Fi available.** DAT
installation then succeeded. Worth recording because the surfaced error
(`Failed to open local channel`) gives no indication that Personal Hotspot
is the problem, and the retry loop makes it look like a transient network
fault.

### 2. Remote transport required Tailscale plus a narrow ATS exception

Because the Tower and iPhone were geographically separated, the previous
LAN Tower endpoint was simply unreachable. The Tower already had Tailscale
installed.

- Tower Tailscale IP: `100.110.156.55`
- iOS endpoint changed from `ws://172.16.60.232:8000/ws`
  to `ws://100.110.156.55:8000/ws`

iOS App Transport Security then **explicitly blocked the plaintext
WebSocket connection**. A **narrow development ATS exception** was added
scoped to that endpoint, rather than enabling arbitrary loads globally.

This matches the direction `02-DEVELOPMENT-RULES.md` Rule 12 and
`03-ROADMAP.md:83` already prefer (a private overlay/tunnel over public
exposure), but it does **not** discharge the security debt:
`07-PLATFORM-CONSTRAINTS.md` Limitation 11 still applies — plaintext
`ws://` with no authentication is development infrastructure, not a
production posture. The narrow exception must stay narrow, and
authentication remains outstanding before any broader exposure.

## Measured — Tower final summary

Quoted as reported:

```
session_duration_s: 78.999
frames_received: 63
effective_fps: 0.8
bytes_received: 1017780
bandwidth_bps: 12883.52
seq_gap_total: 1797
tx_seq_gap_total: None
backpressure_drops: 0
frame_processing_errors: 0
receive_to_result_ms_avg: 1.981
receive_to_result_ms_max: 15.253
cv_processing_ms_avg: 0.82
process_cpu_percent: 0.3
process_rss_bytes: 70893568
stage_ms_avg: {'total': 0.82}
stage_ms_max: {'total': 4.655}
end_reason: disconnect
```

Note on units: `bandwidth_bps` is **bytes** per second, not bits, despite
its name (`bytes_received / elapsed_s`). So `12883.52` is 12.9 kB/s ≈ 0.10
Mbps. Average frame payload was `1017780 / 63` = **16,155 bytes**.

### Observation rate — the headline result

- **0.8 fps received by the Tower** (63 frames / 78.999 s).
- Against the ~15 fps roadmap target: **far below**, and this is the
  finding the run exists to establish.
- **This is not a remote-path regression.** The 2026-08-19 V0.7 soak over
  **LAN** measured **0.81 fps** (695 frames / 856.882 s —
  `V0.7-sustained-streaming-report.md:48`). A same-room LAN and a
  two-hour-distant WAN link produced the same received rate to within
  0.01 fps. Bandwidth and RTT are not what is limiting this pipeline.

### `seq_gap_total: 1797` — fully accounted for, not loss

`seq_gap_total` is a raw, causally-neutral count of discontinuities in the
received `seq` field. It is **not** a "frames lost in transit" figure, and
must not be reported as one.

For this run the stride accounts for **all** of it with no residual:

- last observed `seq` ≈ **1860**; `frames_received` = **63**
- `1860 − 63 = 1797` — exactly the reported `seq_gap_total`
- mean spacing `(1860 − 1) / 62 = 29.98` — a **1-in-30 stride**
- implied capture rate `1860 / 79 ≈ 23.5 fps`, consistent with a DAT
  `frameRate: 24` configuration
  (`07-PLATFORM-CONSTRAINTS.md:80` — `frameRate ∈ {2, 7, 15, 24, 30}`)

This matches the documented, deliberate sender behavior recorded in
`07-PLATFORM-CONSTRAINTS.md` Limitation 9: the iOS sender assigns `seq`
from the DAT capture-frame index but "only forwards roughly 1-in-30 of
them (a throttled capture -> transmit branch)".

`tx_seq_gap_total: None` is correct and deliberate: the iOS side of the
`source_seq`/`tx_seq` split
(`docs/superpowers/handoffs/2026-08-20-source-seq-tx-seq-split.md`) is
still unimplemented, so genuine transit loss **remains formally
unmeasured** for this run. "Nothing is left over after the stride is
accounted for" is strong evidence of no material loss; it is not the same
as a direct measurement of zero loss, and is not reported as one.

### Latency and CV cost

Two distinct figures, neither of which is end-to-end capture-to-result
latency (that would need a capture timestamp from the iPhone, which the
protocol deliberately does not carry):

- `receive_to_result_ms_avg`: **1.981 ms**; max **15.253 ms**
- `cv_processing_ms_avg`: **0.82 ms**; `stage_ms_max.total` **4.655 ms**

### Errors and drops

- `frame_processing_errors`: **0**
- `backpressure_drops`: **0** — correct and expected: no Tower code path
  increments this field yet, so it cannot indicate anything else.
- No dimension mismatches, no decode failures, no `frame_error` messages.

### Resource use

- `process_cpu_percent`: **0.3**
- `process_rss_bytes`: **70,893,568** (~67.6 MiB)

**The Tower was idle for more than 99.8% of the session.** At 0.82 ms of
CV per frame and 0.8 frames/s, roughly 0.07% of wall-clock time was spent
in CV. Tower compute is not the constraint, and no Tower-side backpressure
or drop policy is warranted by this data.

## Tower capacity — measured 2026-08-21, same day

Because the physical run leaves the Tower 99.8% idle, its headroom had to
be established separately before the target rate could be called safe.
Measured with `scripts/soak_test_stream.py` over loopback at the **same
360x640** resolution the glasses actually produced, baseline CV module,
30 s per run, `--source synthetic-script`.

| Target fps | Achieved send fps | Tower `effective_fps` | sent/acked | rx→result avg/max (ms) | cv avg (ms) | cpu% | RSS |
|---|---|---|---|---|---|---|---|
| 15 | 12.94 | 12.95 | 389 / 389 | 1.649 / 10.055 | 0.560 | 2.3 | 68.7 MB |
| 30 | 21.58 | 21.59 | 648 / 648 | 1.531 / 6.110 | 0.537 | 3.4 | 70.6 MB |
| 60 | 32.88 | 32.90 | 987 / 987 | 1.670 / 4.252 | 0.638 | 3.5 | 70.6 MB |
| 120 | 64.97 | 65.01 | 1950 / 1950 | 1.355 / 6.274 | 0.522 | — | 71.3 MB |
| unthrottled | 781.94 | 782.56 | 23460 / 23460 | 0.974 / 6.055 | 0.464 | 80.1 | 72.8 MB |

Every run: `seq_gap_total: 0`, `backpressure_drops: 0`,
`frame_processing_errors: 0`, and `frames_sent == frames_acked` exactly.

**Sustained ceiling: ~736 fps as shipped** (mean of three unthrottled
reps), rising to **~1065 fps** with per-frame logging suppressed. That is
roughly **49x the 15 fps roadmap target** and **900x the 0.8 fps observed
physically**. At the 10–15 fps target the Tower uses **2.3% of one core
and 69 MB RSS**.

Latency does not degrade under load — it *improves*: 1.65 ms average at 13
fps versus 0.97 ms at 782 fps (warm caches, amortized event-loop
wakeups). `cv_processing_ms_avg` is flat at 0.46–0.64 ms across the entire
13→782 fps range, so CV is not load-sensitive. No queue growth, no latency
knee, no drops anywhere. Saturation is a clean single-core CPU limit (the
receive→process→ack loop is single-threaded; one core of 20 pegs), not a
backpressure or memory failure.

**Conclusion: no Tower-side mechanism could produce 0.8 fps, and the
10–15 fps target has ~50x margin.** Headroom is verified, not assumed.

### Three measurement caveats found while doing this

1. **`--fps N` in the soak client never reaches N on Windows, and the
   shortfall is the client's.** `asyncio.sleep()` quantizes to the ~15.4 ms
   Windows timer tick, so achievable send periods are integer multiples of
   it (measured 77.3 / 46.3 / 30.4 / 15.4 ms for targets 15 / 30 / 60 /
   120). `--fps 120` therefore saturated nothing — it just landed on a
   one-tick sleep. Always quote `achieved_send_fps`, never the requested
   `--fps`. Documented in the script.
2. **`TOWER_DEV_MODE=false` does not quiet per-frame logging.** The four
   `[Tower][Frame]` lines per frame are INFO, and `TOWER_DEV_MODE` only
   switches DEBUG↔INFO. Verified: 2 DEBUG lines against 109,736
   `[Tower][Frame]` lines. Per-frame logging costs ~45% of peak throughput
   and ~24 MB per 30 s at saturation, but is being kept — it is the primary
   diagnostic surface for physical runs and costs 2.3% of a core at the
   target rate.
3. **`process_cpu_percent` was not a session average, and is now.** It came
   from `psutil.cpu_percent(interval=None)`, which measures only since its
   own previous call — and `snapshot()` also runs periodically every 150
   frames. So the *final* summary reported CPU for the sliver since the
   last periodic summary; the 120 fps row above read `0.0` for that reason,
   and two back-to-back snapshots of one busy session measured 95.9 then
   0.0. Fixed to cumulative CPU time over the session.

   **This did not affect the physical baseline's `0.3`**: that run received
   63 frames, below the 150-frame periodic-summary interval, so `snapshot()`
   ran exactly once and its window *was* the whole session. But it would
   have corrupted the next run — at 12 fps a periodic summary fires every
   ~12.5 s, so the headroom figure this work exists to verify would have
   been measured over a fraction of a second.

## Conclusion

The physical pipeline **works end to end, remotely, on real hardware.**
That is the milestone.

The observation rate delivered to the Tower — 0.8 fps — is inadequate for
the temporal CV this platform is being built for (World Builder, temporal
depth stabilization, feature tracking, motion estimation, pose estimation,
persistent object tracking, Object/Environmental Memory). The cause is
**a fixed ~1-in-30 frame-decimation stride in the iOS sender**, which
bounds delivered rate to capture-rate ÷ 30 regardless of how much network
or Tower capacity is available.

Ruled out as causes, each with evidence: Tailscale/WAN transport (LAN
control run gave the same 0.81 fps), ATS (connection succeeded), packet
loss (stride accounts for the entire gap total), JPEG decode and Tower CV
(0.82 ms/frame, 99.8% idle), and Tower backpressure (no such mechanism
exists yet).

## Consequences (this session)

**Tower-side, implemented and merged.** `SessionMetrics` now derives the
upstream capture rate and the sender's sampling stride from `source_seq`,
so this diagnosis no longer requires hand arithmetic over log lines. New
additive fields appear in every session summary — `source_seq_span`,
`source_frame_span_s`, `sampling_stride_avg`, `source_fps_estimate` —
each reporting `None` rather than `0` when genuinely unknown. Had they
existed for this run, they would have read ~1859, ~29.98 and ~23.5
alongside `effective_fps: 0.8`, stating the conclusion outright. No
wire-protocol change; every existing sender keeps working unchanged.

Three defects found by review while building that instrumentation, all
fixed here:

- Sequence fields were validated for *presence* but not *type*, so a
  sender emitting `"source_seq": "31"` parsed cleanly and then raised
  `TypeError` inside `snapshot()` — which runs from the endpoint's
  `finally` block, so it destroyed the session's final summary **and**
  skipped `client_disconnected()`, leaving the tracker asserting a
  connected client forever. Sequence fields are now integer-validated at
  the wire boundary and answered with `invalid_frame`.
- Finalizing a measurement can no longer take connection cleanup down
  with it: a diagnostics failure is logged with a traceback, and the
  lifecycle completes regardless.
- `sampling_stride_avg` divides by frames actually recorded, so
  intermittent Tower-side rejection inflates it — a sender forwarding
  *every* frame with every other frame rejected reports a stride of ~2.0,
  misattributing Tower-side loss to the sender. This cannot be corrected
  from inside the metric, so a new `frames_rejected` counter makes the
  condition visible; previously the `invalid_frame` and
  `module_unavailable` paths incremented nothing at all. It was 0 for
  this run, so the numbers above are unaffected.

**iOS-side, handed off.** The fix itself is in Swift code that does not
exist in this repository. See
`docs/superpowers/handoffs/2026-08-21-ios-observation-rate.md` for the
proposed cadence-based replacement for the stride, the bandwidth budget,
the sender-side counters to add, and the acceptance criteria for the next
physical run.

**Not done, deliberately.** No Tower-side queue, drop policy, or adaptive
streaming was added. `01-SYSTEM-ARCHITECTURE.md:97` and `03-ROADMAP.md:71`
both say those decisions must be made from measurements rather than in the
abstract, and the measurement here says the Tower has ~40x headroom and
nothing to shed. Revisit if a raised sender rate produces real pressure.

## Next physical run

Not yet performed. This baseline is pre-optimization by construction: the
iOS change has not been made, so **no higher FPS figure exists yet and
none is claimed here.** The next physical run's instructions and expected
metric ranges are in the handoff document above.
