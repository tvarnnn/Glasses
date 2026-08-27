# World Builder `next-generation` — status

**Branch:** `world-builder/next-generation`, based on
`origin/integration/world-builder-lifecycle-v1` @ `25eb794`
**Tower tests:** 502 passed, 10 skipped (`-k world`)
**Not merged.** Not force-pushed. The mega branch is untouched.

---

## 1. What this branch changed, and what it bought

Measured on a pinned eight-capture corpus of real Ray-Ban walks, replayed
bit-deterministically through the real engine
(`scripts/world_builder_corpus_benchmark.py`).

| | before | after |
|---|---|---|
| solved poses | 346 | **591** |
| published points | 47,429 | 75,369 |
| legible fragments | 28 of 48 | **91 of 94** |
| worst bbox blowup | 387.7x | **4.4x** |
| keyframes | 1712 | 1712 — untouched |
| segments | 127 | 230 |
| captures with a registered cluster | **0** | **2** |

Four changes produced it.

**Landmarks that are not measurements are no longer published.** Both
triangulation sites gate on the angle the two camera centres subtend at the
landmark, derived as `σ_px / f` — the angle at which depth uncertainty reaches
100% — and on reprojection into both source views. The gate decides
*publication*, not what the solver may use: a landmark with an unconstrained
depth still has a usable bearing, and removing it from the map cost 26 poses
when that was tried.

**A broken solve chain now starts a new segment.** `classical.py` claimed for a
long time that the engine did this; it did not, and every keyframe after a break
was refused without ORB, matching, or any geometry attempted. Measured on one
capture: 354 refusals from 26 real decisions, and 0 of 26 segments ever
recovering.

**Refusals say how many decisions they represent.** `poses_refused` split into
root and cascaded, with a degeneracy histogram over roots.

**Registration results are persisted and served.** `placements.json`,
`transform_to_world`, `registration_state`, and `placement_hash`. A
placement is bound to the `input_digest` of the build it was solved
against, so it cannot outlive its geometry; one whose reference segment is
not itself placed is refused rather than inviting a composite into a frame
nothing defines.

**Registration got affordable.** Cross-segment matching samples 8 keyframes
per segment instead of a full cross-product — measured as the smallest
sample preserving every verdict on both registering captures, where 5 lost
all of them. 192 s to 44 s on one world, 20 s on the other. Comfortable at
finalisation; still not live.

---

## 2. The result that matters most

On capture `e1c52b9f` the baseline registers **0 of 18,162 points**. With the
cascade fixed it registers **3 segments carrying 5,603 of 22,520 (25%)**. On
`2e6cffa2`, **44%**.

The mechanism was not previously known: registration needs a segment to have its
*own* solved camera trajectory, and `min_cameras = 3` is a hard clause. A long
segment that broke early kept all its keyframes and solved almost none of them,
so it was unregistrable however much of the room it saw. **The cascade was not
only discarding reconstruction — it was discarding the cameras registration
depends on.**

---

## 3. What was measured and refused

Recorded because a branch that only lists its wins is not evidence.

| change | result | shipped? |
|---|---|---|
| `min_survival_ratio` 0.20 → 0.06 (a documented "low-medium risk" recommendation) | −18% poses, −19% points | **no** |
| `loss_grace_frames = 3` | −28% poses, −35% points | **no** |
| Landmark gate at `MIN_TRIANGULATION_ANGLE_DEG` (0.5°) | discards 37–44% of points; secretly demands 3.8x the pipeline's own noise floor | **no** — replaced by the derived bound |
| Gate applied at triangulation instead of publication | −26 solved poses | **no** — moved to the emission boundary |
| Split on *every* chain break | +517 poses, but 470 segments at a median of 2 keyframes | **no** — see §5 |
| `MIN_SOLVED_BEFORE_RESTART = 2` | committed, then found unable to fire for seed-pair breaks | **withdrawn** |

Three of these were my own proposals, refuted by measurement after being
committed or after being argued for in a spec.

---

## 4. Where the remaining limit is

Registration refusals across the corpus are dominated by two reasons:

1. **"the wearer stood still"** — `span_over_depth` below 0.09. No algorithm
   change fixes a capture with no camera baseline.
2. **"neither direction could be solved"** — not enough mutually visible
   landmarks with placeable cameras.

The first is a capture-technique question and is the subject of
`docs/superpowers/plans/2026-08-26-world-builder-physical-validation.md` P3,
which is the highest-leverage experiment available and needs a wearer.

---

## 5. Known limits, stated rather than buried

- **Registration cannot run live.** 116 s for a seven-segment world, dominated
  by an O(F²) keyframe cross-product in `cross_matches` that no pair-level prune
  touches. Finalisation-time registration is what this cost supports; live
  registration needs appearance-based retrieval, which does not exist.
- **The benchmark's zero-yield control is no longer a zero.** `4fea31e2` reads
  zero under the shipped rule but produces real geometry under a more permissive
  one — its zero was a cascade artifact. A control that is one algorithm change
  from being non-zero is a weak control and needs replacing.
- **The unrestricted split is worth +517 poses and is not shipped**, because 470
  fragment cards in an unranked grid is unusable. Registration is invariant
  across the whole range, so the extra fragments are raw geometry, not
  coherence. It becomes available the moment fragments can be ranked.
- **`largest_segment_points` is the coherence metric to read, not
  `mean_largest_share`.** The share is a ratio and falls whenever new geometry
  appears beside the largest piece, which is not a loss. That misreading nearly
  discarded a 2.5x reconstruction gain.
- **Nothing here is physically validated.** Every number is replay.
- **Four adversarial reviews have run**, and each found something the tests
  did not. The most valuable finding was that a whole feature could be
  reverted with the suite green, because its only engine-level test asserted
  the mechanism did *not* fire. The second was that a placement outlived the
  reconstruction it was fitted to and was served against points that no
  longer existed. Neither was reachable by reading the code alone.

---

## 6. What iOS must do

`docs/agent-handoffs/WORLD-BUILDER-NEXT-GENERATION-MAC.md` §4b. In short: decode
`transform_to_world` (the chunk decoder does not read it at all today) and re-key
the geometry cache on `(contentHash, placementHash)`.

The cache change is not optional. `content_hash` deliberately excludes the
transform so cached geometry survives a re-placement; that is safe only because
`placement_hash` changes instead. A client keyed on `contentHash` alone draws an
unplaced version of a segment the world knows how to place — permanently, and
without looking broken.

---

## 7. Promotion

Not proposed yet. Per the lane's own rules this branch is promoted only after
Tower tests pass (they do), specialist review passes (three adversarial reviews
have run; a fourth is outstanding), the Mac lane consumes the contract change,
device validation passes, and physical World Builder validation is documented.

**The physical half has not started.** Until P1 and P3 in the validation plan
have been run by someone wearing the glasses, the product claim — that a walk
produces a recognisable room — remains exactly as unproven as it was at
`25eb794`, with better machinery behind it.
