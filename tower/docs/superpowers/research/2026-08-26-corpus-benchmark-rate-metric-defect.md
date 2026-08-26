# The corpus harness sums almost every rate it is given

**Date:** 2026-08-26
**Status:** DEFECT CONFIRMED, fix pending. Not yet contaminating any
published figure — see §3, which is the part to read before panicking.
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
