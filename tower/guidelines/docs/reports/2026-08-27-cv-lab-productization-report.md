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
| `baseline` | 0.00086 ms | 0.00039 ms | **0.00125 ms** | 1.70 ms | **0.074 %** |
| `frame_quality` | 0.00399 ms | 0.00038 ms | **0.00437 ms** | 8.56 ms | **0.051 %** |

`baseline` is the harshest denominator on purpose: it is the cheapest
registered experiment, so overhead that would vanish against `depth` at
26 ms is still visible against it. Even there the Lab adds **1.25
microseconds** to a 1.7 millisecond frame.

The two halves are what was actually added to the frame path:
`LabRun.record_result` folds one frame into the run's accumulators, and
`CVLab._provenance` builds the `cv_lab` block that travels on
`frame_result`. Everything else on that path was there before.

`frame_quality` costs 4.6× more to record than `baseline` because it emits
nine metrics rather than one — the cost tracks the metric count, which is
the shape you would predict and therefore worth confirming. Attribution
costs the same 0.4 µs either way, because it does not depend on what the
experiment found.

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
  baseline         experiment   1.7006 ms   through Lab   1.7045 ms
  frame_quality    experiment   8.5554 ms   through Lab   8.3534 ms
```

One difference is positive and one is negative, and both are noise. They
are consistent with the direct figure in the only way that matters: the
added cost is below what this host can resolve end-to-end.

---

## 2. The status document

| Experiment | build | revision hash | JSON | size | metrics |
|---|---|---|---|---|---|
| `baseline` | 0.043 ms | 0.138 ms | 0.018 ms | 5 775 B | 1 |
| `frame_quality` | 0.051 ms | 0.169 ms | 0.027 ms | 7 842 B | 9 |

The revision hash is `compute_revision`, which canonicalises the payload
to decide whether anything changed. It is now the **dominant** cost of
publishing a snapshot — three times the build — and it is unavoidable: a
hand-maintained counter is a second source of truth about whether
something changed, and the two disagree the first time somebody adds a
field and forgets to bump it.

### The build got 22× faster, and the reason is a bug this benchmark caught

An earlier reading of this table was **1.25 ms** for a build, against
0.35 ms before the adversarial-review fixes landed. `json_safe` — the
non-finite sanitiser those fixes moved into `status()` — was the obvious
suspect and was innocent: measured on its own it costs **0.045 ms** on a
7.8 KB document.

The cost was `importlib.util.find_spec`. Checking whether an experiment's
optional extra is installed had become *per experiment, per required
module, on every status build* — up to four filesystem probes per
document, where the previous code probed `torch` once and reused the
answer. The fix is an `lru_cache`: a module does not appear or disappear
while a process runs, and installing the `[ml]` extra into a live Tower
needs a restart anyway, because the module system loads its experiment
once.

Worth recording because the sequence is the point. A correctness fix
(per-experiment probes instead of one global one) introduced a
performance regression, the benchmark that exists to catch exactly that
caught it, and the result is now **eight times faster than before either
change**.

**Worst case measured separately** (`tests/test_cv_lab_bounds.py`):
`optical_flow`, with fourteen metrics plus the eight-experiment catalog,
produces **8 852 B**. The catalog is ~4.7 KB of that and does not change
between polls.

The test's bound is **16 KB**, deliberately looser. It was 9 216 B, which
left a 364-byte margin — the next legitimate field would have tripped it,
and a test that fails on correct work teaches people to raise the number
without reading it. The arity is guarded separately by
`test_the_payload_contains_no_unbounded_list`; this one catches a payload
that grew a category rather than a field.

---

## 3. The result channel

| Subscribers | one poll pass | p95 | snapshot builds per poll |
|---|---|---|---|
| 1 | 0.71 ms | 0.75 ms | **1.09** |
| 4 | 0.93 ms | 1.01 ms | **1.09** |
| 8 | 1.53 ms | 2.10 ms | **1.09** |

The last column is the point. Wall-clock grows with subscriber count and a
timing alone cannot tell "we built the document eight times" from "we sent
it eight times" — only one of those is a defect. Counting the calls into
`hub._snapshot_for` settles it: **one snapshot build per poll regardless
of how many are watching**, which is the hub's own claim, checked rather
than assumed. The growth is the eight envelope sends.

Eight is the per-connection subscription cap, so this is the ceiling, not
a typical load. At the poll interval of 0.5 s, eight subscribers cost
about **0.3 % of one core**.

**Cost on the wire.** While running, the document is re-sent when its
revision changes or every 2 s otherwise. The revision deliberately
excludes `run.elapsed_s` and the two throughput rates derived from it —
an adversarial review found they made it change on every poll for a Lab
that had seen no frame at all, so `revision_changed` fired twice a second
with no news behind it. With them excluded, at the current sender's
observed ~0.8 frames per second a subscriber sees roughly 1.3 documents
per second — about **11 KB/s**, against ~16 KB/s for the frame stream
itself, and an idle Lab costs the 2 s heartbeat and nothing more.
Unsubscribing when the CV Lab screen is not visible is worth doing and
iOS already works that way.

---

## 4. Memory over a long run

`handoff.md` 9.3 says a `stream_stop` MAY NEVER ARRIVE, so "for the length
of a run" means "for as long as the Tower is up". A run that grew per
frame would be the unbounded store the whole design avoids.

**RSS cannot answer this, and the first version of this section pretended
it could.** RSS is what the process has asked the OS for, and in a process
running OpenCV and numpy that includes their own pools. Two runs of this
benchmark over identical work reported **−524 KB** and **+2.84 MB**. A
quantity that changes sign between runs is not measuring the thing, and
the +2.84 MB reading was very nearly written up as a leak.

So `tracemalloc` now runs alongside it and attributes **Python**
allocations to the lines that made them. 4 000 frames of `frame_quality`
after a 500-frame warm-up:

```
   800 frames  RSS  79.40 MB  (+200 704 B since warm-up)
  1600 frames  RSS  78.97 MB  (-253 952 B)
  2400 frames  RSS  79.09 MB  (-122 880 B)
  3200 frames  RSS  79.18 MB  ( -36 864 B)
  4000 frames  RSS  79.27 MB  ( +65 536 B)

  RSS first -> last checkpoint:  -135 168 B over 3 200 frames (-42.24 B/frame)
  tracemalloc net:                  +4 276 B over 4 000 frames ( +1.07 B/frame)
```

**+1.07 bytes per frame**, and the Lab's own share of it is 736 bytes
**total** — 14 objects at `run.py:69` and 9 at `run.py:106`, which are the
per-metric accumulators being created once each. The rest is the
benchmark's own bookkeeping and `psutil`. A separate probe over 4 000
frames with no benchmark scaffolding measured **+0.64 B/frame**.

The structural claim behind it: every accumulator in `LabRun` is O(1) in
frames — a mean is a running total and a count, a maximum is a maximum.
There is no frame list, no metric history and no sample buffer. The
document was **7 865 B** after 4 000 frames and 7 842 B after 20, and
`test_the_status_document_does_not_grow_with_frames` pins that to within
64 bytes (the digits of the counters).

The distinct metric names a run tracks are bounded by the experiment's own
`METRIC_KINDS` declaration — a compile-time set, fourteen entries at its
largest. An earlier draft carried a `MAX_TRACKED_METRICS = 64` cap on top
of that; it was removed rather than kept, because it could never fire and
an unreachable guard reads as care while providing none.

## 5. Can the Lab coexist with the rest of the Tower

Yes, and three separate things say so.

1. **The frame path.** 1.25 µs added to a 1.7 ms frame. At the sender's
   observed 0.8 frames per second that is one microsecond of CPU per
   second.
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

The one real coexistence cost is **8 subscribers × 0.5 s polls ≈ 0.3 % of
one core**, and it stops entirely when the last subscriber goes: the hub
cancels its poll task when no channel remains, so a Tower nobody is
watching does no work on this channel's behalf.

One more cost, measured because a reviewer asked rather than assumed:
releasing a CUDA-resident model runs **inline on the event loop**, and
`torch.cuda.empty_cache()` synchronises with the device. Measured at
**2.5–4.2 ms**, median ~3 ms, for both `depth` and `object_detection` —
comparable to a single frame's processing and three orders of magnitude
under the 2 s threshold at which iOS replaces a connection. Inline is
fine, and it is now a measurement rather than an assumption.

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
