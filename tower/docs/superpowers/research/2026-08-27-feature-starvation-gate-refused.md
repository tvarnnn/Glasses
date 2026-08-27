# A feature-starvation gate was built, measured, and removed

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation`.
**Outcome: REFUSED on measured evidence. No production code retains it.**

---

## 0. What was proposed

The modern-SLAM research package's Stage 2 asks for a keyframe admission
gate on usable feature count, on the strength of a real and correct
observation: **20 of the 24 keyframes with ≤100 ORB features are >40%
redaction fill**, and that single population causes several separate
symptoms — BoW retrieval collapse, the OpenCV-5 uninitialised-mask
defect, and dense-matcher collapse.

## 1. The evidence for it was real

MEASURED, canonical capture, 457 persisted keyframes. Feature count is a
property of the IMAGE, so this measurement is engine-independent:

| threshold | keyframes below | median black fraction among them |
|---|---|---|
| <8 features | 7 (1.53%) | 0.825 |
| <20 features | 10 (2.19%) | 0.826 |
| <100 features | 24 (5.25%) | 0.747 |

Minimum observed: **zero features**. Correlation between feature count
and black fraction: **−0.363**. The 24-at-<100 with median 0.747 is an
exact independent reproduction of the research package's figure.

And they contribute nothing. Cross-referencing all 10 keyframes under 20
features against the persisted poses and support table:

- **10 of 10** are `unavailable` or `anchor` — none carries a solved pose.
- **0 of 10** contribute a single support row. No geometry at all.
- **2 of 10 are segment ANCHORS** — they start a segment that then
  resolves nothing.

The proposed threshold was arithmetic rather than tuned: matching two
frames yields at most `min(features)` correspondences, so a frame with
fewer than `MIN_INLIERS` (15) features can never reach 15 inliers against
anything. And the harm looked worse than a wasted slot, because
`set_reference()` runs on every accept — admitting an 80%-black keyframe
installs a tracking reference nothing can track against, arranging the
next loss in advance.

That is a good case. It was implemented.

## 2. And then it never fired

Implemented in `engine.observe()` after all existing gates, with reason
`feature_starved`, and run over the full pinned 8-capture corpus.

**MEASURED — corpus-wide rejection histogram with the gate ACTIVE:**

| reason | count |
|---|---|
| insufficient_motion | 5,184 |
| blurred | 2,271 |
| tracking_lost | 119 |
| tracking_degraded | 85 |
| no_motion_evidence | 1 |
| **feature_starved** | **0** |

Keyframes accepted: **1,712 with the gate, 1,712 without** — bit-identical
totals (230 segments, 591 solved, 75,369 points either way).

**This is conclusive by construction, not by inference.** The gate was
live. Had any accepted keyframe carried fewer than 15 features, it would
have rejected it. It rejected none. Therefore **no keyframe accepted at
HEAD is feature-starved.**

## 3. Why the evidence and the result disagree

The measurement in §1 was taken from a world **built by the previous
engine**. All 19 persisted worlds predate this branch — verified via
`engine.py:775`, which writes `points_discarded` unconditionally and says
so explicitly ("absent would mean this build predates the counter"), and
which is absent from every manifest on disk.

The starved keyframes are real, and at HEAD they are no longer *accepted*.
The tracker and selector fixes of 2026-08-25 — `6e60f76` in particular —
already reject that population through the existing blur and motion
gates, before a feature-count gate would ever see them.

**The research package's Stage 2 recommendation was correct about the
problem and is now obsolete about the fix.** It was written against
measurements from the older pipeline.

## 4. Why it was removed rather than kept as a safety net

The gate runs `detect_and_describe` on every frame that clears all other
gates — every accepted keyframe, 1,712 of them, at roughly 3.9 ms each.
That is measurable cost for a branch that provably never executes on the
only corpus that exists.

Keeping it would mean shipping dead code with a real cost on the strength
of a hypothetical: footage with a person close enough to the lens that a
*sharp* frame is mostly redaction fill. That case is plausible and is
**queued as physical test PT-2** rather than guessed at. If a real walk
produces it, the gate is nine lines and this document says exactly where
it went and why.

## 5. What was kept from the same investigation

The other half of Stage 2 **was** real and is retained: the
`homography_ratio` uninitialised-mask defect, whose trigger is precisely
this population (a 5-feature keyframe yielding 242 Lowe matches on 3
distinct locations). That is fixed at source in `geometry.py` by checking
the model before trusting the mask, verified deterministic across 8 fresh
processes where 30/40 previously returned garbage, and covered by three
regression tests including a neutralize check.

So the population caused two problems. One is fixed where it lives. The
other turned out to be already handled upstream.

## 6. The general lesson, since it cost real time

Two of tonight's findings share a shape: **a recommendation derived from
persisted artefacts, where the artefacts predate the code they are being
used to justify changing.** The other was the Stage 1 stop/go criterion,
where the ">50% ≥3-view" bar came from the old engine and was nearly met
already.

Before acting on any measurement read off `data/`, check
`points_discarded` in the manifest. Its absence means the world predates
this engine, and the number describes a pipeline that no longer exists.
