# Registration exists, works, and nothing calls it

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation`.
**Status:** MEASURED, read-only. No production code touched. No `--write`.

---

## 0. The finding

The modern-SLAM research package — 5,798 lines across a synthesis, three lane
reports and an adversarial review — concluded that cross-segment registration
was **"CONDITIONAL, NOT YET FUNDABLE"** and that the persistence scaffolding
"already exists and is inert."

**The scaffolding is not what is inert. The whole mechanism is already built,
and it is already good. What is missing is a function call.**

`tower/scripts/world_registration.py` is **1,755 lines** implementing, in
production-quality form with an explicit adversarial posture:

- `Sim3` (`:120`), `DirectedFit` (`:183`), `SegmentGeometry` (`:154`)
- `MutualEvidence` (`:247`) which **structurally cannot be constructed** from
  anything but two solves in OPPOSITE directions, with a provenance clause
  (`:283`) refusing two fits that are not independent — "otherwise reciprocity
  is arithmetic rather than evidence"
- `reciprocity()` (`:296`), `Thresholds.max_reciprocity_error` (`:347`)
- `span_over_depth()` (`:392`) — a baseline-over-scene-depth pre-refusal
- Huber-robust refinement (`:582-645`), `fit_direction()` (`:665`),
  `admit()` (`:727`) which accepts `MutualEvidence` and nothing else
- cycle consistency, spanning-tree composition, digest-bound persistence

The research package **never opened this file.** Across all 5,798 lines the
strings `world_registration`, `MutualEvidence` and `placements.json` appear
three times in total, none in the capability analysis `[credit: branch audit]`.
And `MutualEvidence` existed on the *integration* branch too, so this was a
research coverage gap, not branch staleness — re-measuring would not have
caught it.

## 1. What it does on the real canonical world — MEASURED

Run read-only (no `--write`) against the persisted canonical world
`3dd986b1c2364d4b85de97152f2e39f4`, session `dd5d13a2381e430db9b27c7da2cf2928`
(the STALE session — it predates `6e60f76`; a HEAD re-run is Stage 0's job):

| quantity | value |
|---|---|
| segments | 51 |
| segments with geometry | 19 |
| **segments registered** | **3** |
| points total | 12,023 |
| **points registered** | **3,739 (31.1%)** |
| candidate pairs | 143 |
| **admitted pairs** | **2** — `(4,5)` and `(5,32)` |
| reference segment | 5 |
| cycles checked | 0 |

**31.1% is an exact match for the prior in-repo cross-segment research**, which
concluded: *"Smallest honest slice: persist `support_views`, register the
confidently verifiable subset only... On this world that is 3 segments and
31.1% of the reconstructed points."* Independent reproduction.

## 2. Nothing calls it — MEASURED

- `grep -rln "world_registration"` over the tree returns **only**: the script
  itself, four test modules, and the new Stage 0 harness. **No module under
  `tower/tower/` imports it.**
- `store.write_placements()` exists (`store.py:445`) and `read_placements()`
  (`:466`). **`engine.py` calls neither.** (Grepping `placement` against
  `engine.py` returns two hits, both false positives on
  `median_dis*placement*_px`.)
- The serving layer is fully wired: `results/world_builder_geometry.py:160`
  `usable_placements()` reads placements, and — importantly — **refuses any
  placement whose `input_digest` does not match the build being served**
  (`:190`), because "a rebuild replaces poses and points wholesale and never
  touches `placements.json`, so a consumer would be handed the stale
  transform."

So: algorithm ✅, persistence ✅, serving ✅, **stale-transform invalidation ✅**,
automatic invocation ❌.

That last one is the entire gap. It is a hook, not an algorithm.

## 3. The dominant refusal is the footage, not the code

Of 141 refused pairs, the reason distribution is overwhelming:

| refusal reason (truncated) | count |
|---|---|
| "the wearer stood still: one segment's cameras span only 0.02…" | 66 |
| "…0.03…" | 27 |
| "…0.06…" | 19 |
| "…0.04…" | 12 |
| "…0.05…" | 11 |
| "neither direction could be solved: too few cameras placeable" | 6 |

**135 of 141 refusals are `span_over_depth` — the camera baseline is 2–6% of
scene depth, so scale is unrecoverable at any quality of match.**

This deserves emphasis, because it is the same conclusion the whole research
programme reached by a completely different route, and it is now confirmed from
inside our own production algorithm on our own footage:

- The synthesis identified `baseline/depth` as the only validity statistic with
  any discriminative power, and proposed `> 0.05` as a gate — then struck it
  because it could not separate this corpus's positives from a zero-baseline
  null.
- **This branch already computes exactly that statistic, already uses it as a
  pre-refusal, and is refusing at 0.02–0.06 — right in the disputed band.**

Two independent implementations converging on the same quantity, and on the
same limit, is strong evidence the quantity is the right one and that **the
binding constraint is the capture, not the estimator.** The wearer did not
translate enough. No algorithm recovers scale from a camera that did not move.

## 4. What follows

1. **Wire registration into the build path.** Turning 0% registered into 31.1%
   registered is a real product improvement, it uses code that is already
   tested, and it is non-destructive by construction (a segment's own geometry
   never moves; only `transform_to_world` is set) and already digest-guarded.
   The cost is runtime at finalisation, which must be measured, not assumed.
2. **Do not loosen `max_reciprocity_error` or `span_over_depth` to admit more
   pairs.** The CLI's own help says loosening reciprocity "is a decision about
   how wrong a drawn map may be." The refusals are correct.
3. **The highest-value physical experiment is now obvious and cheap**: capture a
   walk with deliberate lateral translation. 135 of 141 refusals say the camera
   did not move enough. This is queued for the morning report rather than
   guessed at.
4. Stage 1 (multi-reference `_extend`) remains worth doing and is complementary:
   22 of 33 segments at HEAD carry no geometry at all, and a segment with no
   geometry cannot be registered no matter how good the footage is.

## 5. Caveats

- All numbers are from the **stale** session and must be re-run at HEAD.
- No ground truth exists. "Registered" means two independent solves in opposite
  directions agreed within threshold — self-consistency, not accuracy.
- `test_world_registration.py`'s entire real-corpus class (10 tests, `:615-732`)
  **silently skips** in this worktree because the corpus lives only in the main
  repo. Those are the only end-to-end checks that the gate does anything on real
  data, and tonight they are not running `[credit: branch audit]`.
