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

**CORRECTED 2026-08-27 — the sentence that stood here was FALSE, and the
reasoning behind it was unsound. The adversarial review caught it.**

What I wrote was: *"This is conclusive by construction... Therefore no
keyframe accepted at HEAD is feature-starved."*

**22 of the 1,712 persisted keyframes ARE feature-starved, minimum zero
features** — measured by the reviewer directly on the persisted images.

The reasoning failed because of an ordering detail I had already read and
did not connect: the accept decision happens at `engine.py:303`, and
`_persist_keyframe` — which applies redaction — happens at `:331`. **So
the gate inspected the PRE-redaction frame, while the geometry backend
consumes the REDACTED one.** A frame with plenty of features before a
face is blacked out can have almost none afterwards. The gate could never
have seen the population it was written for; "it never fired" was
evidence about the wrong image.

**The decision to remove it nevertheless stands, on the reviewer's own
measurement**: of those 22 starved keyframes, **0 carry a pose and 0
contribute a support row**. They cost nothing downstream. Six are wasted
segment anchors, which is a real but small inefficiency.

**What would need to change if this is revisited:** the gate must run on
the redacted image, i.e. after `_persist_keyframe`, which means it can no
longer prevent a bad frame from becoming the tracking reference — the
main argument for having it. That is a harder design than the one
attempted here, and it is why this stays refused rather than deferred.

## 3. Why the evidence and the result disagree

The measurement in §1 was taken from a world **built by the previous
engine**. All 19 persisted worlds predate this branch — verified via
`engine.py:775`, which writes `points_discarded` unconditionally and says
so explicitly ("absent would mean this build predates the counter"), and
which is absent from every manifest on disk.

**Superseded by §2's correction.** The starved keyframes are real and
they ARE still accepted at HEAD — 22 of them. What was wrong was my
inference from "the gate never fired", which measured the pre-redaction
image and therefore could not see them.

**The research package's Stage 2 recommendation was correct about the
problem and is now obsolete about the fix.** It was written against
measurements from the older pipeline.

## 4. Why it was removed rather than kept as a safety net

The gate runs `detect_and_describe` on every frame that clears all other
gates — every accepted keyframe, 1,712 of them, at roughly 3.9 ms each —
**and as built it inspects the wrong image**, so it never fires while the
population it targets sails past it.

It is removed rather than repaired because repairing it is a different
and harder design: to see what geometry sees, it must run after
`_persist_keyframe`, and by then the frame has already been installed as
the tracking reference — which was the main argument for having a gate at
all. Refusing a keyframe *after* persisting it is a larger change to the
engine's flow than this stage's budget, and it should be designed rather
than patched.

What justifies leaving it out entirely rather than deferring it: of the 22
starved keyframes that ARE accepted, **0 carry a pose and 0 contribute a
support row**. The cost of admitting them is 6 wasted segment anchors.
That is a real inefficiency and a small one. **Queued as PT-2.**

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
