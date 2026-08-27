# Stage 1 design — widening `_extend` from one reference to K, and the rule that makes it safe

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation`.
**Status:** DESIGN, written before any code was touched, because the roadmap
says to (`2026-08-26-world-builder-modern-slam-comparison.md` §3 Stage 1:
"Budget a week and write the de-duplication rule down before touching
anything"). Nothing in this file has been implemented yet.

---

## 0. What this stage is actually buying

Not "more edges." The measured objective is **landmark multiplicity**.

- **66.1%** of landmarks at HEAD are seen by exactly two views `[QUOTED, synthesis §2]`.
- A two-view landmark is *exactly determined*: two rays, one intersection.
  Bundle adjustment can satisfy both rays perfectly wherever the cameras are,
  so two-thirds of the map is invisible to BA **by construction**. That is why
  BA measured 0.00% and why adding a bigger solver changes nothing `[QUOTED]`.
- The Stage 1 stop/go is therefore **≥3-view landmark share rising from 33.9%
  to >50%**, with median covisibility degree clearing 9.0 against a measured
  oracle ceiling of 14.0.

So the change is not "match more pairs and hope." It is: **give each landmark
more independent observations, so the reconstruction acquires redundancy.**

## 1. The current mechanism, read from source

`backends/classical.py`:

- `_extend(features_previous, features_current, previous_index, current_index,
  absolute, landmarks, observed, keyframe_id)` takes **exactly one** previous
  feature set (`:710`).
- It matches current against that one reference, then for each match looks up
  `observed[(previous_index, index_previous)]` to find an existing landmark
  (`:737`). Hits become PnP correspondences and `reobserved` rows; misses become
  `matched_pairs` for triangulation.
- `claimed: set[int]` (`:722`) exists because `knnMatch` guarantees one entry
  per `queryIdx`, not per `trainIdx` — so two *previous* features can name the
  same *current* feature. Today the rule is **first claim wins**, and that is
  safe because all claims come from a single reference and therefore, at worst,
  disagree about which previous feature — never about which landmark.
- `_Chain.previous_features` is a **single slot** (`:1030`).
- `_Chain.forget_before(index)` prunes `observed` to `key[0] == index` — one
  frame (`:1062`), justified in its docstring by "`_extend()` reads exactly one
  key shape", and carrying a memory measurement (26.1 MB → 0.15 MB at 155
  keyframes; 142.9 MB → 0.15 MB at 1000).

## 2. The change

For keyframe *N*, match against the previous **K** accepted keyframes
(K = 3, justified in §5), accumulate correspondences from all of them, and run
**one** PnP solve over the union.

This is deliberately *not* K separate solves. One solve over more constraints
gives a better-conditioned pose; K solves would give K poses and no rule for
reconciling them.

The effect on multiplicity is direct: a landmark created at frame *N−3* and
re-seen at *N* now records a support row at *N*, where today the association
died the moment the reference advanced past it.

## 3. THE DE-DUPLICATION RULE (the reason this document exists)

Widening breaks the assumption that made `claimed` safe. With K references,
two *different* landmarks can claim the same current feature, because they come
from different reference frames that disagree.

**The rule:**

> Group all candidate correspondences by **current feature index**.
>
> - If every reference claiming that feature agrees on the **same landmark
>   index** → keep it **once**. Agreement across references is corroboration,
>   not duplication, and must not be double-counted into the PnP.
> - If the claiming references name **different landmark indices** → **drop
>   that current feature entirely**, and increment a
>   `conflicting_correspondence` counter.
> - A feature claimed by exactly one reference behaves exactly as today.

**Why drop rather than pick a winner.** A conflict is positive evidence that at
least one of the two matches is wrong. Feeding a known-ambiguous 3D↔2D
correspondence into PnP is precisely how a pose gets corrupted; RANSAC will
often reject it, but "often" is not a rule, and the cost of dropping is one
correspondence out of hundreds. This is the conservative, reversible choice the
run's decision policy asks for, and it is deterministic — no tie-break on
match distance, which would make the output depend on float comparisons.

**Why not keep the nearest reference's claim.** It is a plausible heuristic and
it is *not* obviously right: the nearest reference has the shortest baseline
and therefore the least reliable geometry (§5). Choosing it would systematically
prefer the weakest evidence. If measurement later shows dropping is too costly,
"nearest wins" is the first alternative to try, and the counter added here is
what will say so.

**Corroboration must not inflate the PnP.** The same landmark seen from three
references is still **one** 3D point and **one** image observation in frame *N*.
Adding it three times would triple-weight it and silently bias the solve. One
row per (landmark, current feature).

## 4. What else must change, and what must not

Read off the source; the roadmap named these and each one checked out.

| Site | Today | Must become |
|---|---|---|
| `_Chain.previous_features` (`:1030`) | one slot | bounded deque of the last K accepted `(keypoints, descriptors)` |
| `_Chain.forget_before` (`:1062`) | keeps `key[0] == index` | keeps the last K frame indices |
| `claimed` in `_extend` (`:722`) | first-claim-wins over one reference | the §3 rule over K references |
| `_triangulate_new` (`:866`) | one previous pose, one projection matrix | unchanged in shape — triangulate each unmatched pair against **the reference it came from**, so the baseline is real |
| support `base + offset` bookkeeping | duplicated in `estimate_window()` and the live path | must stay consistent; double-counting a re-observation silently corrupts `support.json` |

**Invariants that must survive, non-negotiable:**

1. **Forward-only.** `_extend` may look *back* K frames; it must never look
   forward. The `_Chain` docstring says that if anything else has to live in
   the chain, "this backend has stopped being forward-only, and the equivalence
   test is the thing that will say so."
2. **Live/rebuild equivalence.** `test_extending_equals_solving_the_whole_window`
   must stay green — `estimate_window()` and the incremental path must widen
   *identically*, or the two paths have silently diverged.
3. **Bit-for-bit determinism.** `test_the_oracle_is_deterministic_which_is_why_the_tolerance_is_zero`
   has a zero tolerance. The §3 rule is deterministic by construction (set
   agreement, no float tie-break) specifically to keep it that way.
4. **Retained state stays flat in keyframe count.**
   `test_retained_state_does_not_grow_with_the_number_of_keyframes` asserts
   `max(sizes) < min(sizes) * 2`. K frames of `observed` is still a *constant*,
   not growth — but it is a **K× larger constant** (~0.15 MB → ~0.45 MB at
   K=3, extrapolating the docstring's own measurement). That docstring carries
   a specific number and **must be updated with a re-measurement**, not left to
   rot.
5. **The cheirality gate stays exactly as it is.** It scored 0.0% false-positive
   on the synthetic zero-baseline null and is the best degeneracy check measured
   anywhere in the programme `[QUOTED]`. Nothing here touches it.

## 5. Why K = 3

Per pair asked, useful-edge yield `[QUOTED, synthesis §3]`: **57.9%** at gap 1,
**49.4%** at gaps 2–5, 29.8% at 6–20, 9.2% at 21–100, 2.4% beyond. Production's
own gate accepts **50.4 / 49.5 / 47.8%** at keyframe gaps 1 / 2 / 3, then decays
to 36.5% at gap 5.

Gaps 1–3 are flat and cheap. Past that you pay more matches for fewer edges, and
the right instrument becomes retrieval (Stage 3), not a wider sweep.

Cost: K−1 extra `match_indices` calls per keyframe. ORB matching was measured at
~3.9 ms median per pair `[QUOTED]`, so K=3 adds roughly **8 ms per keyframe**,
against a ~12 fps capture (83 ms budget). Acceptable, and to be measured rather
than assumed.

**K must be a named constant, not a literal**, so the sweep in §6 is a config
change and not a code change.

## 6. How this gets validated

Per the run's testing philosophy — a mechanism that can be deleted while the
suite stays green is not tested.

1. **Failing-first benchmark.** Extend the Stage 0 baseline harness to report
   the ≥3-view landmark share. At K=1 it must report 33.9%; that is the
   control, and it must be recorded *before* the change.
2. Implement K=3.
3. **Demonstrate** ≥3-view share > 50%, median covisibility degree ≥ 9.0,
   and `poses_solved` / `points` not falling.
4. **Neutralize** — set K back to 1 and confirm the benchmark *notices*, i.e.
   the multiplicity metric returns to baseline. A stop/go criterion that does
   not move when the mechanism is removed is measuring nothing.
5. Restore, re-run the full suite, re-run the corpus benchmark.
6. **Sweep K ∈ {1, 2, 3, 5}** and record the curve. If K=2 captures most of the
   gain, prefer it — smaller change, less memory, fewer conflicts.

**Failure condition, stated in advance:** if multiplicity rises but
`poses_solved` or `points` fall, this has re-run `1272b09`'s mistake — shipping
on a graph statistic while the reconstruction shrank. Stop and investigate;
do not proceed to Stage 2 on a graph number alone.

## 7. Open questions carried into implementation

- ~~**Does `estimate_window()` share enough code with the live path** that one
  edit widens both?~~ **ANSWERED, from source, before implementation.**

  The two paths share `_extend` and `_estimate_pair` — the **geometry** — and
  **deliberately do not share the orchestration**. The seam comment at
  `classical.py:331-338` states the reason outright: *"an oracle that delegates
  to the thing it is checking checks nothing, and
  tests/test_world_builder_incremental.py checks this one bit-for-bit."*

  So this is by design, not by neglect, and the design is correct. Widening
  therefore needs **one geometry change and two orchestration changes**:

  1. `_extend` takes a sequence of references instead of one — the single
     geometry chokepoint, so the two paths cannot drift in what they compute.
  2. `estimate_window`'s loop (`:255-256`, `previous = current - 1`) builds a
     reference *list*.
  3. `extend`'s live path (`:419`) does the same from the `_Chain` deque.

  **The insight that keeps this safe:** `_extend`'s RETURN SHAPE does not have
  to change. It already returns `new_observed` keyed by `(frame, feature)` and
  `published_reobserved` keyed the same way. Both orchestrations' `base +
  offset` support bookkeeping (`:289-307` and its live-path twin) consumes
  exactly those dicts and is indifferent to how many references produced them.
  **If the return shape holds, the duplicated bookkeeping does not need to be
  touched at all** — which removes the roadmap's single most-feared failure
  mode (double-counting a re-observation into `support.json`).

  The one genuinely structural change inside `_extend`: `matched_pairs` must
  now carry **which reference each unmatched pair came from**, because
  `_triangulate_new` triangulates against that reference's pose and emits
  observations for both that frame and the current one. Today the reference is
  implicit because there is only one.
- **What is the real conflict rate?** Unknown until measured. If the §3 rule
  drops a large fraction of correspondences, the rule needs revisiting — the
  counter exists to answer this and should be reported in the benchmark, not
  just logged.
- **Does widening change segment *count*?** It should not — segmentation is
  driven by tracking loss, not by `_extend` — but it must be checked, because
  segment count is the metric this whole effort was chartered against and
  `1272b09` exists because it lied once already.
