# Overnight World Builder SLAM implementation run — 2026-08-27

**Branch:** `world-builder/next-generation`
**Starting commit:** `65f64a4` ("test: the branch end state, controls passing")
**Ending commit:** _(filled at close)_
**Working tree:** _(filled at close)_
**Push status:** _(filled at close)_

> **DRAFT IN PROGRESS.** Sections marked _(pending)_ are awaiting the
> full-corpus Stage 1 A/B and the independent adversarial review, both in
> flight. Nothing in this file is a completion claim until this banner is
> removed.

---

## 0. The one-paragraph version

The night's most valuable output is **not** a feature. It is that three
separate recommendations from the modern-SLAM research package turned out
to rest on measurements taken from a pipeline that no longer exists, and
that a large piece of the architecture the package said was missing is
**already built and simply never called**. One production improvement was
implemented, measured, and is under adversarial review; one was
implemented, measured, and **removed** because it provably never fires;
one real non-deterministic defect was fixed at source. No architectural
bet was placed that the evidence did not support.

## 1. Claim types used in this report

Because these are different claims and the difference matters:

- **IMPLEMENTED** — code exists and the suite is green.
- **BENCHMARK-VALIDATED** — measured on real Ray-Ban frames against a
  control.
- **REPLAY-VALIDATED** — measured through the real engine end to end, not
  through a component harness.
- **PHYSICALLY VALIDATED** — a human wore the glasses. **Nothing in this
  run reaches this bar.**
- **NOT VALIDATED** — asserted, not measured.

**There is no ground truth on this corpus.** No surveyed geometry, no
reference trajectory, no metric scale. Every number below is comparative
or self-consistency. The only measurements with a known right answer are
synthetic constructions.

## 2. Research consumed

`tower/docs/superpowers/research/2026-08-26-world-builder-modern-slam-comparison.md`
(revision 2) plus its three lane reports and adversarial review — 5,798
lines, preserved onto this branch in commit `d3d24b5` because they were
sitting UNTRACKED on the integration branch, one `git clean` from gone.

## 3. Three research findings that did not survive contact

Recorded first because they are the most reusable result of the night.

### 3.1 Every persisted world predates this branch's engine

`engine.py:775` writes `points_discarded` unconditionally, and says why:
*"Zero is written explicitly — absent would mean 'this build predates the
counter', which is a different fact."* That makes the manifest a designed
discriminator.

**MEASURED: all 19 derived manifests on disk, newest 2026-08-27 01:04,
lack that key.** So the 66.1%/67.2% two-view figures the research package
built its case on — and my own independent reproduction of 67.2% — all
describe the *previous* pipeline. The landmark gate filters on parallax
and reprojection, both correlated with view count.

**The true HEAD baseline is different and worse**: exactly-2-view
**70.38%**, ≥3-view **29.62%**, obs/landmark 2.478, over 75,369 landmarks
across the 8 pinned captures.

**Rule for successors: before acting on anything read off `data/`, check
`points_discarded` in the manifest.**

### 3.2 The Stage 1 stop/go was unmeetable, then nearly already met

Revision 1 of the research asked for median covisibility degree > 15; the
adversarial review showed the all-pairs *oracle* reaches only 14.0, so the
criterion halts the roadmap on success. Revision 2 lowered it to 9.0.

Separately, world `4cae0b26` already sits at **47.5% ≥3-view with no
widening at all**, and the per-world spread is 24.3%–47.5%. **Capture
content moves this quantity nearly as much as an algorithm change does**,
so a pooled number crossing 50% proves nothing. The criterion was replaced
with a paired per-capture one.

### 3.3 Registration is not missing. It is built, and nothing calls it.

The research package concluded cross-segment registration was
"CONDITIONAL, NOT YET FUNDABLE" and that the persistence scaffolding was
inert. **The scaffolding is not what is inert — the whole mechanism is.**

`tower/scripts/world_registration.py` is **1,755 lines**: `Sim3`,
`MutualEvidence` (structurally unconstructable from anything but two
solves in OPPOSITE directions, with a provenance clause refusing two fits
that are not independent), scale AND rotation reciprocity,
`span_over_depth` pre-refusal, Huber refinement, cycle consistency,
spanning-tree composition, digest-bound persistence. The serving layer
already reads placements and already refuses any whose `input_digest`
does not match the build being served.

**MEASURED, read-only, canonical world:** 3 of 51 segments registered,
**3,739 of 12,023 points (31.1%)**, 2 admitted pairs of 143 candidates —
an exact reproduction of the prior in-repo cross-segment research.

**No module under `tower/tower/` imports it.** The gap is a function call.

The research package never opened the file — three mentions across 5,798
lines, none in the capability analysis — and `MutualEvidence` existed on
the integration branch too, so this was a **coverage gap, not branch
staleness**. Re-measuring would not have caught it.

## 4. Why registration was NOT wired in tonight

It is the obvious cheap win and it was deliberately declined. MEASURED
across the 8 pinned captures at HEAD:

| | |
|---|---|
| captures registering anything | **2 of 8** |
| registration wall time | **472.3 s** against **219.0 s** for all replay+build — **2.2×** |
| where it works | `e1c52b9f` 24.9% of points, `2e6cffa2` 44.4% |

Wiring it into `build()` would more than triple build time to benefit a
quarter of captures, on a Tower that must coexist with Object Memory,
Scene Understanding and other cartridges — and this repo already has a
recorded lifecycle-timeout problem.

**And the reason 6 of 8 register nothing is not the algorithm.** Of 141
refused pairs on the canonical world, **135 are `span_over_depth`** —
"the wearer stood still: one segment's cameras span only 0.02–0.06 of the
scene depth, so its scale is not recoverable from them at any quality of
match."

Two independent lines of work converged on the same statistic and the
same limit: this branch's `span_over_depth`, and the research
programme's search for a validity gate (which proposed `baseline/depth >
0.05` and then struck it). **The binding constraint is the capture.**

So the correct next action is **PT-1 — a walk with deliberate lateral
translation** — not automating a pass that would refuse 96% of pairs.
Wiring it up is the top-priority implementation task *after* PT-1.

## 5. Production changes

_(pending — Stage 1 verdict in flight)_

## 6. Baseline and final metrics

**Stage 0 control** (commit `29bd35e`, 8 pinned captures, this branch's
engine, `scripts/research/stage0_baseline/`):

| metric | value |
|---|---|
| segments | 230 |
| keyframes | 1,712 |
| poses_solved | 591 |
| poses_refused | 891 |
| points | 75,369 |
| points_discarded | low_parallax 11,150 / high_reprojection 8,044 |
| segments_with_geometry | 102 |
| largest_segment_points | 29,890 |
| exactly-2-view | 70.38% |
| ≥3-view | 29.62% |
| obs/landmark | 2.478 |
| wall | 218.7 s |

_(final metrics pending)_

## 7. Test suite

- Start of run: **1,628 passed, 64 skipped, 0 failed** (4m39s).
- After Stage 1 + tests: **1,634 passed, 64 skipped, 0 failed**.
- After r_H fix + tests: **1,637 passed, 64 skipped, 0 failed** (6m09s).
- _(final run pending)_

Note the branch carries 1,628 tests against the integration branch's
1,015–1,163 — a measure of how far ahead it is.

## 8. Physical tests required

See `2026-08-27-PHYSICAL-TESTS-QUEUED.md`. **PT-1 (a walk with deliberate
lateral translation) is worth more than the rest combined**, because 135
of 141 registration refusals say the camera did not move enough.

Each queued test states its hypothesis, the capture to make, the expected
result, and **what would falsify it**.

## 9. Contract / Mac handoff

_(pending)_

## 10. Remaining defects and open questions

_(pending)_
