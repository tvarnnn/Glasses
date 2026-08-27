# Reducing segment count makes reconstruction worse, and now we know why

**Date:** 2026-08-26
**Branch:** `world-builder/next-generation`
**Instrument:** `scripts/world_builder_corpus_benchmark.py`, pinned eight captures
**Status:** measurement. `min_survival_ratio = 0.06` was tested and **NOT shipped**.

---

## 0. The headline

`min_survival_ratio` 0.20 → 0.06 is intervention #3 in
`2026-08-26-segment-fragmentation.md`, rated **low-medium risk** and projected to
take the corpus from 130 to 115 segments.

Run through the **full solve** for the first time:

| | baseline | `min_survival_ratio=0.06` | |
|---|---|---|---|
| segments | 127 | **113** | −11% — the predicted win |
| keyframes | 1712 | 1764 | +3% |
| poses_solved | 346 | **283** | **−18%** |
| points | 47,429 | **38,484** | **−19%** |
| legible fragments | 47 of 48 | **39 of 40** | −8 |

`20ce3c23` is the extreme case: **46 solved poses → 1**, 6,633 points → 53.

**The segment-count prediction was correct and the change is still bad.** This
is the third time this project has hit that pattern, and it is the first time
the mechanism has been measured rather than inferred.

---

## 1. The mechanism: merging enlarges the blast radius of the cascade

The refusal cascade is documented in
`2026-08-26-world-builder-point-quality-design.md` §7.3 and instrumented in this
branch: once any pose in a segment is refused, `chain.broken` latches and every
later keyframe in that segment is refused **without ORB detection, matching, or
any geometry attempted at all**. Measured: 0 of 26 segments ever recover.

So a segment's cost when it fails is not one keyframe. It is *every keyframe
after the failure*.

Using the root/cascaded split this branch added to the manifest:

| capture | root refusals | cascaded refusals | keyframes abandoned per root refusal |
|---|---|---|---|
| `20ce3c23` | 11 → **10** | 215 → **267** | 19.5 → **26.7** |
| `b35d8ab8` | 34 → **34** | 211 → **243** | 6.2 → **7.1** |
| `fe744b68` | 7 → **8** | 55 → **68** | 7.9 → **8.5** |

**Root refusals barely move.** The geometry did not get worse; the same number
of chains died for the same reasons, with an essentially unchanged degeneracy
histogram (`20ce3c23`: `pure_rotation` 4→4, `no_correspondence` 5→4,
`low_parallax` 2→2).

What changed is how much each death costs. Longer segments mean more keyframes
sitting downstream of the latch.

**Merging segments does not repair anything. It makes each existing failure more
expensive.**

---

## 2. loss-grace-3, re-run under the same instrument

The inference in the first draft of this note was that grace-3 fails by the same
mechanism. It was cheap to test, so it was tested rather than left inferred, and
the result **partially corrects it**.

| | baseline | `loss_grace_frames=3` | |
|---|---|---|---|
| segments | 127 | 107 | −16% |
| keyframes | 1712 | **1582** | **−130** |
| poses_solved | 346 | **248** | **−28%** |
| points | 47,429 | **30,623** | **−35%** |
| legible fragments | 47 of 48 | 38 of 38 | −9 |

The −28% reproduces the historical figure recorded at `keyframes.py:117-136`
("destroys a third of the reconstruction") on a different corpus and a different
instrument, which is a useful cross-check on both.

Root/cascaded split:

| capture | segments | root refusals | abandoned per root refusal |
|---|---|---|---|
| `22e9d428` | 33 → 29 | 26 → 25 | 12.6 → 12.6 |
| `b35d8ab8` | 43 → 38 | 34 → **23** | 6.2 → **8.1** |
| `20ce3c23` | 13 → 10 | 11 → **8** | 19.5 → **24.5** |
| `2e6cffa2` | 16 → 11 | 12 → **9** | 15.9 → **21.2** |
| `fe744b68` | 11 → 8 | 7 → **5** | 7.9 → **10.2** |
| `64f48114` | 4 → 4 | 3 → 4 | 16.7 → 15.5 |
| **TOTAL** | | **93 → 74** | **11.3 → 13.5** |

**Where the correction lies.** Grace-3 *does* reduce root refusals, 93 → 74. It
genuinely suppresses some real losses, which is what it was designed to do. So
its failure is **not purely** blast-radius enlargement, as the first draft
implied.

Grace-3 pays twice:

1. **Fewer keyframes.** 1712 → 1582. A held frame neither advances the reference
   nor becomes a keyframe, so holding through three frames means more staleness
   at exactly the moment correspondence is already struggling. This is the
   mechanism `keyframes.py:126-130` already records, and it is confirmed.
2. **A larger blast radius per surviving failure.** 11.3 → 13.5 keyframes
   abandoned per root refusal.

`min_survival_ratio=0.06` pays only the second, and loses 18%. Grace-3 pays both,
and loses 28%. The two levers separate the mechanisms cleanly, which is more than
either investigation could do alone.

The generalisation therefore stands, in a narrower and better-supported form:

> **While the cascade exists, merging segments transfers keyframes to the
> downstream side of an existing failure, and that transfer costs reconstruction
> even when the merge suppresses some failures outright.**

`64f48114` is the counter-example worth keeping in view: its segment count did
not change (4 → 4), its root refusals went *up* (3 → 4), and it still collapsed
from 18 solved poses to 1. Not every loss under these levers is a merge effect,
and this note does not claim otherwise.

## 3. What this means for the roadmap

**Fragmentation work is GATED on fixing the cascade.** Not sequenced after it as
a preference — gated, because until the cascade is fixed every fragmentation win
is measured in a currency that converts to reconstruction loss.

The ranked interventions in `2026-08-26-segment-fragmentation.md` §6 should be
read with this in mind. #1 and #2 (`LK_MAX_LEVEL`, `FORWARD_BACKWARD_MAX_PX`)
are already shipped and were verified against solved poses at the time, so they
stand. **#3 is refuted by this measurement.** #4 (grace) is refuted again here, with the mechanism separated (§2).
#5 (chained tracking + hold) is *untested through the full solve* and, because
it reduces segments by 115 → 85 corpus-wide, this result predicts it will lose
poses too — testing it before fixing the cascade is likely to waste the
experiment.

### The cascade fix, stated as a target

`classical.py` refuses every keyframe after the first failure without attempting
geometry. The obvious repair is re-anchoring: when a chain breaks, start a new
sub-chain from the current keyframe rather than abandoning the rest of the
segment. That converts an N-keyframe loss into a one-keyframe loss and a new
local origin.

That is a real design change with real risks — it introduces a second coordinate
origin inside one segment, which the world model currently does not express, and
`schema.py:96-111` is explicit that a gauge decision made wrongly is not
recoverable. It is not attempted here.

**The measurement's job was to say which problem to solve first, and it does.**

---

## 3a. FOLLOW-UP: the cascade was fixed, and it reframes everything above

§3 said fragmentation work is gated on fixing the cascade. The cascade was
then fixed, and the result is larger than this note anticipated.

`classical.py` had long claimed that when a chain breaks "the engine turns this
into a new segment". It did not — `engine.py` incremented the segment index only
on `decision.lost` and never looked at the backend. Making that claim true:

| variant | poses | points | segments | Σ largest-segment points |
|---|---|---|---|---|
| baseline | 346 | 47,429 | 127 | 28,656 |
| split on **every** break | **863** | **107,005** | 470 | **32,756** |
| split when the chain solved ≥ 2 (**shipped**) | 424 | 58,985 | 141 | 28,663 |

**The cascade was discarding roughly 60% of the recoverable poses in this
corpus.** That is a much larger effect than any tracking lever measured here or
in the fragmentation research.

### An intermediate reading that was wrong, recorded because it nearly shipped

Splitting on every break was first judged a **coherence regression**, because the
mean largest-segment *share* of points fell 0.549 → 0.295. That reading was an
artifact of a ratio. The largest coherent piece **never shrinks in any capture**
— it grows corpus-wide, 28,656 → 32,756. The share fell only because new
geometry appeared *alongside* the main piece.

A ratio moved, nothing was lost, and the ratio nearly caused a 2.5x
reconstruction gain to be discarded. The benchmark now reports absolute
`largest_segment_points` beside `largest_share` so that reading cannot recur.

### Why the unrestricted variant is still not shipped

Not coherence — fragmentation the *viewer* cannot cope with. 470 segments, median
2 keyframes, is 470 fragment cards on a phone with no filtering or ranking. The
restricted rule takes the conservative subset (+22% poses, +24% points, segments
+11%) and leaves the rest available once fragments can be ranked or registered.

### The zero-yield control was never a zero

`4fea31e2` was chosen as the benchmark's honest zero: 0 poses, 0 points. Under
the unrestricted variant it produces 18 poses and 1,202 points, and inspection
says that geometry is **real** — segment 1 is a 9-pose chain over 11 keyframes
with a camera baseline of 2.53 against median depth 24.4, a span/depth of 0.104,
above the 0.09 bar registration itself uses. The unit-1.0000 baselines in the
smaller segments are seed-pair normalisation, not degeneracy.

**The control's zero was a cascade artifact, not ground truth.** It still reads
zero under the shipped rule, so it remains usable for now, but a benchmark whose
honest zero is one algorithm change away from being non-zero needs a better
control. Recorded as a known weakness of the instrument.

### What §3 got right and wrong

Right: the cascade was the thing to fix first, and fragmentation levers were
being measured in a currency that converts to reconstruction loss.

Wrong: the prediction that intervention #5 will lose poses was made under the
cascade. With restarts allowed it may behave completely differently, and the
prediction should be re-tested rather than inherited.

---

## 4. Method, so this is reproducible

```
python scripts/world_builder_corpus_benchmark.py --label baseline \
  --scratch <tmp>/A --out results/ab-b-gated.json
python scripts/world_builder_corpus_benchmark.py --label ms-0.06 \
  --policy min_survival_ratio=0.06 --scratch <tmp>/B \
  --out results/exp-min-survival-006.json
python scripts/world_builder_corpus_benchmark.py --compare \
  results/ab-b-gated.json results/exp-min-survival-006.json \
  --expect-tracking-change
```

`--expect-tracking-change` is required: the comparison guard normally VOIDs any
run where segments or keyframes moved, because those are invariants for a
point-path change. A tracking experiment is supposed to move them, and the
waiver is explicit so the guard keeps meaning something everywhere else.

Both arms are bit-deterministic (`cv2.setRNGSeed(0)`, re-seeded per capture).

## 5. What is measured and what is inferred

**Measured:** every number in §0 and §1, on eight real captures through the real
engine.

**Measured, after the first draft inferred it:** the grace-3 comparison in §2.
Re-running it under this instrument cost 82 seconds and corrected the claim --
grace-3 reduces root refusals rather than only enlarging blast radius, and pays
a separate keyframe cost on top. The inference was left in the draft long enough
to be worth naming: it was plausible, cheap to check, and partly wrong.

**Inferred:** that intervention #5 will also lose poses (§3). It follows from the
generalisation, and the generalisation has been tested on exactly one lever.
