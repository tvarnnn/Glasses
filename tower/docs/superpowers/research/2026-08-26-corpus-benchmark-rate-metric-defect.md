# The corpus harness sums almost every rate it is given

**Date:** 2026-08-26
**Status:** FIXED 2026-08-26 -- see §6 and §7. Never contaminated a
published figure; §3 is the check that established that.
**File:** `tower/scripts/capture_corpus_benchmark.py`

---

## 1. The defect

`_RATE_METRICS` (`:45-57`) is an **allowlist**. `_run` (`:215-219`) does:

```python
for name, value in result.metrics.items():
    if name in _RATE_METRICS:
        averaged.setdefault(name, []).append(value)
    else:
        summed[name] = summed.get(name, 0.0) + value
```

Anything not named in the allowlist is **summed**. The file's own comment
at `:41-44` warns about precisely this outcome — *"a number that looks
plausible and means nothing"* — and then the list fails to match reality.

**Verified by running all eight experiments and reading their emitted
keys**, not by reading the source.

**8 of the 11 allowlist entries are dead.** Nothing emits them:

```
blur_ratio   depth_p50   depth_p95   inlier_ratio
mean_depth   overlap_ratio   sharpness   survival_ratio
```

Only three are live — `score_threshold`, `mean_score`, `max_score` — and
all three belong to `object_detection`.

**15 emitted metrics are rate-like and are being summed:**

```
sharpness_laplacian_var   <- the REAL name; the allowlist says "sharpness"
tracked_fraction          direction_coherence
overexposed_fraction      underexposed_fraction
mean_relative_depth       mean_flow_px        median_flow_px
median_forward_backward_px   mean_keypoint_size   mean_response
boundary_fraction         region_area_fraction
width                     height
```

`width` and `height` are neither rates nor counts: summing an image
dimension across 9,199 frames produces a number in the millions that
means nothing at all. A corpus run of `optical_flow` reports
`tracked_fraction` around 768 — a fraction, summed.

**Root cause: an allowlist keyed on names nobody validated against the
producers.** Several entries look like plausible *guesses* at what an
experiment would emit (`sharpness` for `sharpness_laplacian_var`,
`survival_ratio` for `tracked_fraction`). The classification silently
defaults to "count" on a miss, so a mismatch is invisible.

## 2. Why it survived

`object_detection` is the only experiment that has been run at corpus
scale for a published result, and it is the only one whose rate metrics
are all in the list. The harness has therefore been **correct every time
it has actually been used**, and wrong for every experiment it has not
yet been used with. That is the worst shape a latent bug can have: it
passes its own history.

## 3. Contamination check — none found

Searched every `.md` in the repository for the mis-summed names. Every
hit is a **single-frame wire-payload example** (`TOWER-TO-IOS.md:134-140`)
or a **code snippet inside a plan** — no corpus aggregate. Specifically:

- The real-corpus detection figures (55 observations, the `person`
  detections being the wearer's own torso, per-class scores 0.813 /
  0.844) came from `object_detection`, whose three rate metrics are the
  three live allowlist entries. **Those figures are unaffected.**
- The resolution / sharpness figures (median Laplacian var 356.9 / 94.9 /
  6.1; 73.3% of frames below `min_sharpness` at 720p) come from
  `2026-08-26-segment-fragmentation.md`, which measured directly rather
  than through this harness. **Unaffected.**
- The 83.5 ms / 11.97 fps delivered interval was measured independently
  twice — the tracker retune and the depth study, which got 83.4 ms.
  **Unaffected.**

**No published conclusion rests on a summed rate.** The defect is real,
and its damage is entirely in the future.

## 4. The fix, and why the obvious one is wrong

Do **not** simply correct the names in the allowlist. That repeats the
original mistake — a hand-maintained list, checked against the producers
once, silently defaulting to "count" the next time an experiment adds a
metric. The next `_fraction` metric anyone writes will be summed again.

The classification belongs with the **experiment**, which is the only
component that knows whether a number is a rate, a count, or a constant.
Whatever shape the fix takes, it must satisfy:

1. **A metric that is not explicitly classified must be an error, not a
   default.** The failure mode here is a silent fallthrough.
2. **A test must enumerate every metric every registered experiment
   actually emits and assert each one is classified** — so adding a
   metric without classifying it fails CI rather than corrupting a report
   nobody re-reads.
3. **Three categories, not two.** `width` and `height` are constants;
   both summing and averaging them are meaningless. They should be
   reported once or not at all.
4. The test must be shown to fail if a classification is removed.

## 5. Provenance

Found by a read-only research agent surveying the Experimental CV Lab,
and confirmed independently by the lead by running all eight experiments
over real corpus frames and diffing emitted keys against the allowlist.

---

## 6. The fix as built (2026-08-26)

**Status: FIXED.** `_RATE_METRICS` is gone. Nothing in the harness knows
what a metric name means any more.

### Where classification lives, and why

Each experiment module declares a module-level `METRIC_KINDS` mapping
next to the dict that builds its metrics -- `frame_quality.py`,
`feature_detection.py`, `redaction_impact.py`, `optical_flow.py`,
`object_detection.py`, and the two metricless experiments, which declare
`{}` explicitly so "no metrics" is a statement rather than an absence.
`object_detection` builds its per-class entries from `TRACKED_CLASSES`
with the same comprehension `run()` uses to emit them, so adding a
tracked class cannot produce an unclassified metric.

One exception, and it is temporary: `depth.py` is under review in
another lane and was not writable in this change, so its four
declarations sit in `tower/experiments/__init__.py` beside the registry,
commented as belonging in `depth.py`. Nothing depends on the location.

`tower/experiments/__init__.py` now registers `ExperimentRegistration`
records -- a factory and its `metric_kinds`, in one object. A factory
cannot be registered without a declaration, because that would be a
missing positional argument. `EXPERIMENTS` is derived from the same
dict, so the old `name -> factory` shape still works and the two cannot
drift. `classify_metric(experiment, metric)` returns the kind or raises
`UnclassifiedMetricError`; an unknown EXPERIMENT raises `KeyError`
instead, because that is a different mistake and deserves a different
message.

### Four kinds, not three

RATE (mean), COUNT (sum) and CONSTANT (reported once, with the number of
frames that carried each observed value) are the three §4 asked for.
`width` and `height` are CONSTANT and are now reported as
`360 x9199`-style lines rather than summed to millions; when a corpus
holds more than one resolution, each value is reported with its own
frame count, because a single number there would be a lie rather than a
simplification. A CONSTANT that takes more than 16 distinct values
raises `MisclassifiedConstantError` -- a "constant" that keeps changing
is a declaration bug, and the harness should say so rather than
accumulate one entry per frame.

The fourth kind, UNAGGREGATED, exists for exactly one metric today:
`dominant_direction_deg` is circular, and the mean of 179 and -179
degrees is 0 -- a direction neither frame was moving. Calling it a RATE
would publish that 0, which is the same class of plausible, meaningless
number this whole document is about. It is reported as a frame count and
nothing else.

### The tests

`tests/test_experiment_metric_classification.py` runs **every registered
experiment** and compares the metric keys it actually emits against the
keys it declares, in both directions: emitted-but-undeclared (the
defect) and declared-but-never-emitted (the eight dead names). Frames
are chosen to reach every branch that builds a metrics dict -- optical
flow has four, and three of them a single-frame test never sees.
`object_detection` and `depth` run their real `run()` with the model
replaced by a fake, so the default suite reaches no network and still
checks the names; the opt-in integration tests still cover the weights.
`EXERCISERS` is asserted equal to `EXPERIMENTS`, so a new experiment
cannot slip past by not being listed, and each experiment asserts it
collected something -- a run that quietly collected nothing would pass
vacuously, which is how this class of bug survives.

`tests/test_capture_corpus_benchmark.py` gained a class covering the
four aggregations, the JSON shape, and the case that matters most:
deleting one classification makes `benchmark_corpus` raise instead of
guessing.

**Both were proven to fail without the fix.** Written first, they failed
8-of-8 against the unfixed harness (every rate landing in
`summed_metrics`, no `constant_metrics` attribute at all). Afterwards,
two deliberate breaks were re-applied to the fixed code: removing
`tracked_fraction` from `optical_flow.METRIC_KINDS` (4 failures, in both
test files) and restoring the silent default in the harness (1 failure,
`DID NOT RAISE UnclassifiedMetricError`). Both were reverted and
`grep -rn "DELIBERATE BREAK"` is clean.

### The corpus, before and after

Both experiments re-run over the full real corpus -- 17 captures, 9,199
frames, 0 failures -- with the pre-fix harness (recovered from git) and
the fixed one. Same frames, same experiments; only the aggregation
changed.

`frame_quality`:

| metric | before (summed) | after |
|---|---:|---|
| `sharpness_laplacian_var` | 3,078,074.161 | **334.6096** (mean) |
| `gradient_energy` | 1,222,667.993 | **132.9131** (mean) |
| `entropy_bits` | 64,132.258 | **6.9717** (mean) |
| `contrast_std` | 502,506.933 | **54.6263** (mean) |
| `edge_density` | 277.688 | **0.0302** (mean) |
| `overexposed_fraction` | 80.400 | **0.0087** (mean) |
| `underexposed_fraction` | 1,056.223 | **0.1148** (mean) |
| `width` | 3,311,640.0 | **360 x9199** (constant) |
| `height` | 5,887,360.0 | **640 x9199** (constant) |

Every one of the nine was wrong. The corpus is uniformly 360x640, which
the old harness reported as a width of 3.3 million.

`optical_flow`:

| metric | before (summed) | after |
|---|---:|---|
| `tracked_fraction` | 7,468.205 | **0.8118** (mean) |
| `median_flow_px` | 127,765.035 | **13.8890** (mean) |
| `mean_flow_px` | 131,565.416 | **14.4292** (mean) |
| `max_flow_px` | 217,919.507 | **23.8999** (mean) |
| `median_forward_backward_px` | 14,184.935 | **1.5557** (mean) |
| `direction_coherence` | 7,502.985 | **0.8229** (mean) |
| `seconds_since_reference` | 44.266 | **0.0054** (mean) |
| `dominant_direction_deg` | -37,717.981 | **not aggregated** (9,118 frames) |
| `seeded_count` | 1,723,309 | 1,723,309 (sum, unchanged) |
| `tracked_count` | 1,405,193 | 1,405,193 (sum, unchanged) |
| `rejected_by_forward_backward` | 172,441 | 172,441 (sum, unchanged) |
| `has_reference` | 9,198 | 9,198 (sum, unchanged) |

`tracked_fraction` is the headline: **7,468.205 for a quantity that
cannot exceed 1**, now 0.8118 -- 81.2% of seeded corners survive the
forward-backward check on real Ray-Ban frames. (§1 quoted ~768 from a
smaller run; over the whole corpus the same defect produces 7,468.2.)
The counts are unchanged in both runs, which is the point: the fix moved
seven metrics and left the four that were already right alone.

The other figures are now readable for the first time: median flow of
13.9 px between consecutive delivered frames, direction coherence 0.82,
and a median forward-backward residual of 1.56 px across all ATTEMPTED
tracks -- which is above the 1.0 px keep threshold precisely because the
rejected tracks are in that number, and 172,441 of 1,577,634 were
rejected.
