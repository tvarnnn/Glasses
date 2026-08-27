# CV Lab productization — what it cost, measured

**Date:** 2026-08-27
**Branch:** `cv-lab/productization-v1` (worktree `C:\Users\tvllo\Projects\Glasses-cv-lab`)
**Starting commit:** `6e325f8`
**Contract:** `docs/contracts/EXPERIMENTAL-CV-LAB.md`

**SYNTHETIC, NOT PHYSICAL.** Every figure below is a real measurement of
this code on this host, driven by rendered imagery and an in-process
`TestClient`. Nothing here says anything about the Ray-Ban camera's
content or about a Tailscale link. Read the milliseconds as budget
guidance.

**Measured under contention, and that is stated rather than hidden.** At
the time of measurement this host was also running four other lanes'
pytest suites and two world-builder corpus benchmarks — 16 to 20 Python
processes, several of them multi-threaded over OpenCV and torch. That
governs which numbers below are trustworthy and which are not, and the
benchmark was rewritten once because of it. See "How the frame figure was
measured" below.

Reproduce: `.venv\Scripts\python.exe scripts/cv_lab_overhead_benchmark.py`

---

## 1. Per frame — what productization added

| Experiment | `record_result` | attribution | **added per frame** | the experiment itself | added as % |
|---|---|---|---|---|---|
| `baseline` | 0.00090 ms | 0.00039 ms | **0.00129 ms** | 1.89 ms | **0.068 %** |
| `frame_quality` | 0.00445 ms | 0.00040 ms | **0.00485 ms** | 10.08 ms | **0.048 %** |

`baseline` is the harshest denominator on purpose: it is the cheapest
registered experiment, so overhead that would vanish against `depth` at
26 ms is still visible against it. Even there the Lab adds **1.3
microseconds** to a 1.9 millisecond frame.

The two halves are what was actually added to the frame path:
`LabRun.record_result` folds one frame into the run's accumulators, and
`CVLab._provenance` builds the `cv_lab` block that travels on
`frame_result`. Everything else on that path was there before.

`frame_quality` costs 3.4× more to record than `baseline` because it emits
nine metrics rather than one — the cost tracks the metric count, which is
the shape you would predict and therefore worth confirming.

### How the frame figure was measured, and why it was measured again

The first version of this benchmark subtracted two end-to-end timings —
one frame through the bare experiment, one through the Lab — and reported
the difference. On a loaded machine it reported **−0.28 ms (−12.3 %)** for
`baseline`: the Lab making a frame *faster*. That is not a small error, it
is a measurement of the machine.

The effect is ~1 µs and the terms being differenced are ~2 ms and ~11 ms
with several percent of run-to-run spread. A difference smaller than the
noise in either term is not a measurement, so the bookkeeping is now timed
directly, 800 samples each. The end-to-end pair is still printed beside
it, labelled "for scale only":

```
  baseline         experiment   1.8897 ms   through Lab   1.8862 ms
  frame_quality    experiment  10.0752 ms   through Lab  10.0728 ms
```

Both differences are negative and both are noise. They are consistent with
the direct figure in the only way that matters: the added cost is below
what this host can resolve end-to-end.

---

## 2. The status document

| Experiment | build | revision hash | JSON | size | metrics |
|---|---|---|---|---|---|
| `baseline` | 0.296 ms | 0.129 ms | 0.021 ms | 5 699 B | 1 |
| `frame_quality` | 0.367 ms | 0.177 ms | 0.027 ms | 7 758 B | 9 |

The revision hash is `compute_revision`, which canonicalises the payload
to decide whether anything changed. It is a third of the total cost of
publishing a snapshot and it is unavoidable: a hand-maintained counter is
a second source of truth about whether something changed, and the two
disagree the first time somebody adds a field and forgets to bump it.

**Worst case measured separately** (`tests/test_cv_lab_bounds.py`):
`optical_flow`, with fourteen metrics plus the eight-experiment catalog,
produces **8 766 B**. The bound stated in the contract is < 9 KB and a
test enforces it. The catalog is ~4.7 KB of that and does not change
between polls.

---

## 3. The result channel

| Subscribers | one poll pass | p95 | snapshot builds per poll |
|---|---|---|---|
| 1 | 1.05 ms | 2.43 ms | **1.09** |
| 4 | 2.27 ms | 2.56 ms | **1.09** |
| 8 | 3.13 ms | 3.34 ms | **1.09** |

The last column is the point. Wall-clock grows with subscriber count and a
timing alone cannot tell "we built the document eight times" from "we sent
it eight times" — only one of those is a defect. Counting the calls into
`hub._snapshot_for` settles it: **one snapshot build per poll regardless
of how many are watching**, which is the hub's own claim, checked rather
than assumed. The growth is the eight envelope sends.

Eight is the per-connection subscription cap, so this is the ceiling, not
a typical load. At the poll interval of 0.5 s, eight subscribers cost
about **0.6 % of one core**.

**Cost on the wire.** While running, the document is re-sent when its
revision changes (a frame was processed) or every 2 s otherwise. At the
current sender's observed ~0.8 frames per second that is roughly 1.3
documents per second — about **11 KB/s**, against ~16 KB/s for the frame
stream itself. Unsubscribing when the CV Lab screen is not visible is
worth doing and iOS already works that way.

---

## 4. Memory over a long run

`handoff.md` 9.3 says a `stream_stop` MAY NEVER ARRIVE, so "for the length
of a run" means "for as long as the Tower is up". A run that grew per
frame would be the unbounded store the whole design avoids.

2 000 frames of `frame_quality` after a 500-frame warm-up:

```
   400 frames  RSS  79.71 MB  (+430 080 B since warm-up)
   800 frames  RSS  79.42 MB  (+126 976 B)
  1200 frames  RSS  79.60 MB  (+311 296 B)
  1600 frames  RSS  81.22 MB  (+2 015 232 B)
  2000 frames  RSS  79.74 MB  (+462 848 B)
```

First to last checkpoint: **+32 768 B over 1 600 frames**. A second run of
the same benchmark gave **−524 288 B over the same span**. RSS wanders by
±2 MB with no trend, and a quantity that changes sign between runs is
allocator noise, not growth.

The structural claim behind it: every accumulator in `LabRun` is O(1) in
frames — a mean is a running total and a count, a maximum is a maximum.
There is no frame list, no metric history and no sample buffer. The
document was **7 785 B** after 2 000 frames and **7 758 B** after 20, and
`test_the_status_document_does_not_grow_with_frames` pins that to within
64 bytes (the digits of the counters).

The distinct metric names a run tracks are bounded by the experiment's own
`METRIC_KINDS` declaration — a compile-time set, twelve entries at its
largest. An earlier draft carried a `MAX_TRACKED_METRICS = 64` cap on top
of that; it was removed rather than kept, because it could never fire and
an unreachable guard reads as care while providing none.

---

## 5. Can the Lab coexist with the rest of the Tower

Yes, and three separate things say so.

1. **The frame path.** 1.3 µs added to a 1.9 ms frame. At the sender's
   observed 0.8 frames per second that is 1 microsecond of CPU per second.
2. **The channel does not touch the frame path.** `poll_once` runs the
   snapshot on a worker thread, the sender task shares only the
   connection's send lock, and the existing `SEND_TIMEOUT_S` bound already
   governs how long a `frame_result` can queue behind a result send.
   `tests/test_cv_lab_hostile.py::test_the_frame_path_still_answers_when_the_channel_is_broken`
   drives a reader that raises on every call and asserts frames keep being
   answered.
3. **The channel does not touch the Lab.**
   `test_polling_the_channel_changes_nothing_about_the_lab` freezes the
   Lab's clock, polls five times, and asserts the document is byte-identical
   before and after.
   `test_the_module_container_is_untouched_by_a_cv_lab_subscription` keeps
   the pre-existing guarantee that the module container is unaffected by a
   subscription.

The one real coexistence cost is **8 subscribers × 0.5 s polls ≈ 0.6 % of
one core**, and it stops entirely when the last subscriber goes: the hub
cancels its poll task when no channel remains, so a Tower nobody is
watching does no work on this channel's behalf.

---

## 6. What was NOT measured

- **Anything physical.** No glasses, no real room, no Tailscale link. The
  physical validation plan is in the handoff.
- **`depth` and `object_detection` under the Lab.** Both need the optional
  `[ml]` extra and a weight download; their per-frame costs are already in
  `2026-08-22-cv-lab-v1-report.md` (26.0 ms and 35.3 ms) and the Lab's
  overhead is the same 1–5 µs regardless, because it does not depend on
  what the experiment did.
- **A switch under real load.** The switch is exercised by tests, but the
  arm timing for a model-backed experiment on a cold cache is a network
  measurement, not a code one — the contract bounds it at 120 s and says
  why.
- **Contention-free absolutes.** Every figure here was taken while this
  host ran four other lanes. The relative figures (added cost as a
  fraction of the experiment; snapshot builds per poll; RSS trend) are
  robust to that. The absolute milliseconds are not, and are the ones to
  re-take on a quiet machine if a budget ever depends on them.
