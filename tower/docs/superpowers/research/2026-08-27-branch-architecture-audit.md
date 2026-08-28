# Branch architecture audit — `world-builder/next-generation`

**Audited:** 2026-08-27, worktree `C:\Users\tvllo\Projects\Glasses-world-builder`
**HEAD:** `d3d24b5` "docs: the modern-SLAM research package, preserved as branch evidence"
**Method:** code read only. No benchmarks were run. Every claim below cites
`file:line` at this HEAD.

---

## 0.0 Provenance — which tree this audit actually read

Raised by the coordinator mid-audit: the only virtualenv is in the main repo
(`C:\Users\tvllo\Projects\Glasses\tower\.venv`) and its editable-install finder
maps `tower` → `C:\Users\tvllo\Projects\Glasses\tower\tower`, i.e. the **other**
branch. Any harness run under that interpreter without a `PYTHONPATH` override
would silently measure the wrong pipeline.

**This audit is unaffected, and here is the proof rather than the assurance.**
No Python was executed at any point — no `measure_baseline.py`, no benchmark, no
`import tower`. Every file was read by path inside the worktree, and every `git`
command ran in the worktree. Corroborating line counts:

| file | this worktree (`world-builder/next-generation`) | main repo (`integration/world-builder-lifecycle-v1`) |
|---|---|---|
| `tower/tower/world_builder/engine.py` | **1171** | 942 |
| `tower/tower/world_builder/backends/classical.py` | **1088** | 798 |
| `tower/tower/world_builder/geometry.py` | **416** | 221 |
| `tower/scripts/world_registration.py` | **1755** | 1313 |

Every line number cited in this document indexes the left column. Nothing here
needs re-running.

**For anyone who does run code tonight**, the coordinator's split configuration
is correct and I confirmed its data half:

- **Code** — worktree, forced:
  `PYTHONPATH=C:\Users\tvllo\Projects\Glasses-world-builder\tower` with
  `C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe`. Assert
  `tower.world_builder.backends.classical.__file__` is under
  `Glasses-world-builder` and **abort** if not.
- **Input** — main repo, absolute: `tower/data/captures/` and
  `tower/data/world_builder/intrinsics/360x640.json` do **not** exist in the
  worktree (verified: `tower/data/captures` → no such directory;
  `tower/data/world_builder/intrinsics` → no such directory; `tower/.gitignore:39`
  is `data/`). Captures and calibration are recorded artifacts and are correctly
  shared.
- **Output** — a disposable scratch root. Do not write into the main repo's
  `data/world_builder/worlds/`.

One correction to the coordinator's second message: `tower/data/` in the worktree
is **not** empty. `tower/data/world_builder/worlds/` exists there and holds **26
worlds**. What is missing is `captures/` and `intrinsics/`. This matters for §H —
see the skipped-test finding.

---

## 0. A correction before anything else

The brief states this branch is **155 commits ahead** of
`integration/world-builder-lifecycle-v1`. Measured here:

```
git rev-list --count integration/world-builder-lifecycle-v1..HEAD   ->  42
git rev-list --count HEAD..integration/world-builder-lifecycle-v1   ->   3
```

42 ahead, 3 behind. The other branch's tip is `6e325f8`, dated
2026-08-26 18:39:32; this branch's own status doc says it is based on
`25eb794` (`docs/agent-handoffs/WORLD-BUILDER-NEXT-GENERATION-STATUS.md:3-4`).
So the divergence is real but roughly a quarter the size stated, and the two
branches were being worked in parallel on the same day.

**More importantly: the research package was measured against THIS branch, not
the other one.** The synthesis's own §4.1 baseline table quotes "HEAD" numbers
(448 kf / 33 segments / 61 solved / 8,333 points) and its commit-attribution
table names `4136b2f` (`support_views`), which is a commit on this branch. The
package was then committed *onto* this branch at `d3d24b5`. The staleness is
therefore **not** "wrong branch". It is narrower and more specific: the research
was measured at an earlier point of this branch's own history and **never looked
at `tower/scripts/world_registration.py` at all**. See §9.

---

## 1. Capability table

Status legend: **ABSENT** / **PRESENT-AND-USED** (on the live or build path) /
**PRESENT-BUT-INERT** (implemented, not wired or never read) / **PARTIAL**.

"Live path" = `engine.observe()` / `engine.build()`. "Offline tool" =
`tower/scripts/world_registration.py`, a CLI that is not imported by any
production module.

| # | Capability | Status | Evidence | Research said | Stale? |
|---|---|---|---|---|---|
| 1 | Linear keyframe chain | **PRESENT-AND-USED** | `backends/classical.py:255-256` (`previous = current - 1`), `:418-427` (live `_extend(chain.previous_features, features, index-1, index, …)`), `:723` | "The only structure that exists. `_extend` matches keyframe *i* to *i−1* only" | **Accurate** |
| 2 | Covisibility graph | **ABSENT in production; the input table is PRESENT** | No edge-between-non-consecutive-keyframes code anywhere in `tower/tower/`. `engine.py:644-646` writes edges only for `zip(members, members[1:])`. The observation table that would generate it *is* persisted: `classical.py:988-991`, `engine.py:699-704`, `store.py:396-397` | "MISSING. The single highest-value gap." | **Accurate**, but the research understates how close it is: the association is on disk and already has a consumer (§B) |
| 3 | Local map / windowed optimization | **ABSENT** | `classical.py:317-337` states the design is strictly forward-only; `_Chain.forget_before` (`:1062-1088`) actively *discards* everything older than the previous frame | "none. Solve window is 2 keyframes" | **Accurate** — and worse than stated: state older than *i−1* is deliberately deleted |
| 4 | Multiple concurrent maps | **PARTIAL** | Segments are sequential, not concurrent: `_LiveSolve` holds exactly one open solve plus frozen ones (`engine.py:1028-1029, 1051-1065`). Frozen segments are independent maps with independent gauges (`engine.py:717-722` refuses `relative` scale when `len(segments) > 1`). No minimum size, no geometry requirement | "33 'segments', but they are bookkeeping labels, not maps" | **Half stale.** They are not bookkeeping labels: each is an independently solved map with its own frozen estimate and its own arbitrary unit, and registration treats them as maps. But there is still no admission bar for one |
| 5 | Relocalization | **ABSENT** | No code. A break latches (`classical.py:354-368`) and the engine opens a new segment (`engine.py:396-398`). Nothing ever re-enters an old segment | "none. A break is permanent" | **Accurate** |
| 6 | Place recognition / retrieval | **ABSENT in production** | Grep for `dbow|vocabulary|place recognition|relocaliz` over `tower/tower/` returns only unrelated prose. Retrieval exists only as a research script, `tower/scripts/research/slam_classical/bow_retrieval.py` | "MISSING" | **Accurate** |
| 7 | Loop closure | **ABSENT** | No code. `classical.py:321` states it explicitly | "MISSING" | **Accurate** |
| 8 | Map merging | **PRESENT-BUT-INERT on the live path; PRESENT-AND-USED offline** | `scripts/world_registration.py:1255-1380` (`register`), `:973-1025` (`compose_tree_with_edges`), persisted at `:1729-1745` → `store.write_placements` (`store.py:445-464`), served at `results/world_builder_geometry.py:160-219`, `:262-296` | "none. `registered:False` / `transform_to_world:None` fields exist and are inert" | **STALE.** The fields are filled by a working offline pass and are served on the wire. What is true is that no *automatic* pass runs — `--write` is opt-in (`world_registration.py:1676-1686`) |
| 9 | Sim(3) estimation | **PRESENT-AND-USED (offline)** | `world_registration.py:119-152` (`Sim3`), `:665-723` (`fit_direction`), `:543-644` (Huber-refined residuals over a 45-step scale grid), `:93-95` | "none in production. Proven offline end-to-end" | **Accurate in letter, badly understated.** It is not a proof-of-concept: it is a 1,755-line module with a gate, a threshold record, a persistence path, a wire representation and two dedicated test files |
| 10 | Pose graph optimization | **ABSENT** | `world_registration.py:978-995` states the choice explicitly: a **spanning tree** (BFS, shortest path) is used, not a pose graph, "because on the real walk the admitted subgraph has no cycle at all" | "MISSING — and vacuous until (2)" | **Partially stale.** A cycle has since appeared (`c980748`; `2e6cffa2` admits the triangle (12,16),(12,19),(16,19)), so it is no longer vacuous at the *segment* level. Still absent at the keyframe level |
| 11 | Local bundle adjustment | **ABSENT** | No BA code exists anywhere in `tower/tower/` or `tower/scripts/` (grep `bundle_adjust|BundleAdjust`). Only prose referring to a past measurement: `classical.py:321-325` | "implemented, measured at 0.00% improvement" | **STALE.** BA is *not* implemented on this branch. It was measured historically and removed/never landed. The research's "IMPLEMENTED, STARVED" verdict points at code that is not here |
| 12 | Global bundle adjustment | **ABSENT** | same | "none" | **Accurate** |
| 13 | Cross-segment registration | **PRESENT-AND-USED (offline), served to iOS** | `world_registration.py:1255-1380`; `records.py:302-458` (`SegmentPlacement`); `store.py:445-513`; `results/world_builder_geometry.py:160-296`; contract `docs/contracts/WORLD-BUILDER-GEOMETRY.md:106-109, 138-144, 256-272` | Not described as an implemented mechanism anywhere in the synthesis | **STALE — the largest gap in the research package** |
| 14 | Reciprocity checking | **PRESENT-AND-USED (offline)** | `world_registration.py:246-289` (`MutualEvidence`, incl. the provenance clause), `:295-307` (`reciprocity` = s(a←b)·s(b←a)), `:309-328` (`rotation_disagreement_deg`), gated at `:804-815` with thresholds at `:347, :364` | Discussed only as a *proposal* to add ("Add the reverse-direction match (reciprocity) at the same time", §Stage 1 line 260) and as an unsolved research question (line 1131) | **STALE.** Scale reciprocity + rotation reciprocity + a forgery-resistant provenance check are all implemented and load-bearing |
| 15 | Cycle consistency | **PRESENT-AND-USED (offline)** | `world_registration.py:866-867` (`MAX_CYCLE_ROTATION_DEG=20.0`, `MAX_CYCLE_SCALE_RATIO=2.0`), `:870-900` (`cycle_refusal_for`), `:903-960` (`cycle_residuals`), invoked at `:1336-1344`, reported at `:1367-1377` | Not mentioned | **STALE.** Landed at `859047e`, two commits before the research was committed |
| 16 | Landmark gating / parallax gates | **PRESENT-AND-USED** | `geometry.py:250-348` (`landmark_gate`), threshold derived not tuned at `geometry.py:202-231` (`min_parallax_deg` = σ_px/f ≈ 0.131°), applied at `geometry.py:399-409` and `classical.py:913-924`, and enforced at the *publication* boundary in `classical.py:943-991` | Not covered as a capability | New since the research's baseline; not contradicted |
| 17 | Cheirality gating | **PRESENT-AND-USED, at three sites** | (a) seed pair: `classical.py:608-623` computes `cheirality_ratio` from `recoverPose`'s in-place mask, gated at `:656-661` against `MIN_INLIER_RATIO`; (b) `geometry.py:379-382` `in_front_a & in_front_b`; (c) `classical.py:904-908` `depth_p > 0 & depth_c > 0` | Not covered | Accurate as far as the research goes |
| 18 | `support_views` persistence | **PRESENT-AND-USED, and CONSUMED** | Built: `classical.py:126-138, :238-251, :291-308, :436-456`; emitted: `:943-991`; carried to disk: `engine.py:699-704` → `store.py:367-397` (`support.json`); read back: `store.py:515-541`; **consumed**: `world_registration.py:1048-1056` (hard refusal if absent), `:1079-1081`, `:1105`, `:500-507` | Lane 1 §2 corrects the brief and says it is populated; synthesis §4.1 credits `4136b2f` | **Accurate on persistence, stale on consumption** — no lane report notices that registration already depends on it |
| 19 | Multi-reference matching in `_extend` | **ABSENT — single previous keyframe only** | `classical.py:723`: `index_pairs = match_indices(descriptors_previous, descriptors_current)`. Callers pass only `features[current-1]` / `chain.previous_features` (`:265-273`, `:418-427`) | "matches keyframe *i* to *i−1* only" | **Accurate. Confirmed verbatim.** |
| 20 | Background refinement | **ABSENT** | `build()` is synchronous; the only cadence hook is `scripts/world_build_session.py:577-579`, an inline call in the driver loop. No thread, no executor, no queue. Grep for `run_in_executor|to_thread|Thread(` over the world-builder path returns nothing | "none, but `--rebuild-every` and the deferred `build()` are the seam for it" | **Accurate** |
| 21 | Keyframe admission policy + order | **PRESENT-AND-USED** | `keyframes.py:311-369`. Order given in full in §E below | "the blur gate runs BEFORE the loss check, masking losses" | **Order accurate; the conclusion is STALE.** The hypothesis is recorded as *refuted by measurement* at `keyframes.py:180-189` |
| 22 | `homography_ratio` / r_H | **PARTIAL: computed, persisted, never read, never gated** | Computed `classical.py:642`, `unposed.py:175`; function `geometry.py:112-131` states "NOT used as a gate"; carried `engine.py:659`; persisted `records.py:772, :790, :810`; the *only* reader of `edges.jsonl` is `inspect.py:83`, which uses `len(edges)` (`:118`) and never touches `r_h`; **not on the Tower→iOS wire at all** | rev 1: "computed and never consumed" → rev 2: "**WRONG.** It is a persisted `KeyframeEdge` field in the Tower→iOS contract" | **The rev-2 correction is itself half-wrong.** It *is* a persisted `KeyframeEdge` field. It is **not** in the Tower→iOS contract: `docs/contracts/WORLD-BUILDER-IOS.md` and `WORLD-BUILDER-GEOMETRY.md` contain no `r_h` and no edge payload. rev 1's substantive claim — nothing consumes it — is correct |

---

## 2. The specific questions

### A. What does `_extend` in `backends/classical.py` actually match against today?

**Only the immediately previous keyframe.** Unchanged. The research is correct.

`_extend`'s signature takes exactly two feature sets, and its first act is a
single pairwise match:

```python
# classical.py:710-724
def _extend(
    self,
    features_previous,
    features_current,
    previous_index,
    current_index,
    absolute,
    landmarks,
    observed,
    keyframe_id,
):
    keypoints_previous, descriptors_previous = features_previous
    keypoints_current, descriptors_current = features_current
    index_pairs = match_indices(descriptors_previous, descriptors_current)
```

Both callers pass `i-1`:

```python
# classical.py:255-256   (batch / cold-rebuild path)
for current in range(2, len(window)):
    previous = current - 1
```

```python
# classical.py:418-427   (live path)
) = self._extend(
    chain.previous_features,
    features,
    index - 1,
    index,
    chain.absolute,
    chain.landmarks,
    chain.observed,
    frame.keyframe_id,
)
```

Landmark reuse is looked up under a key shape that admits only the previous
frame:

```python
# classical.py:737
landmark = observed.get((previous_index, index_previous))
```

And the live path *actively deletes* anything older, so multi-reference
matching is not merely unused — the state is gone:

```python
# classical.py:1086-1088
self.observed = {
    key: value for key, value in self.observed.items() if key[0] == index
}
```

`forget_before`'s docstring (`:1062-1084`) makes the coupling explicit:
"`_extend()` reads exactly one key shape, `observed[(previous, f)]`, so once
frame `index` is solved nothing will ever look up a frame older than it."

**Consequence for the implementation run:** widening `_extend` from 1 to K
references requires changing `forget_before` in lockstep, and
`tests/test_world_builder_incremental.py` asserts the live and cold paths are
**bit-identical**, so both paths must widen together or that test fires. That
test is the single most valuable guardrail for this change.

The design comment at `classical.py:317-337` also names the exact invariant a
widening would break: "`absolute`, `landmarks` and `observed` really are the
entire carried state… If anything else ever has to live here, this backend has
stopped being forward-only, and the equivalence test is the thing that will say
so."

### B. Landmark support-view distribution

**Persisted: yes. Consumed: yes — by cross-segment registration. Multiplicity
computed: nowhere in production.**

Production of the table:

- Row schema declared at `classical.py:67-73`: `[frame index, feature index,
  landmark index]`, `int32`.
- Seed pair rows: `classical.py:238-251`. Note `:243-250` — *both* views are
  emitted even when the `observed` dict write collides, precisely so no landmark
  ends up with a single view.
- Re-observation rows: `classical.py:291-297` (batch), `:436-442` (live) — and
  only the rows PnP's RANSAC accepted (`published_reobserved`, built at
  `classical.py:838-842`).
- New-triangulation rows: `classical.py:303-308`, `:451-456`.
- Emitted with landmark-index remapping after gate filtering:
  `classical.py:943-991`.
- Not pruned, deliberately: `classical.py:1049-1057`, `:1072-1077`.

Persistence:

- `engine.py:699-704` widens each row to `[segment, frame, feature, point]`,
  both indices **segment-local** (`engine.py:689-698`).
- `store.py:396-397` writes `support.json`; `store.py:515-541` reads it back —
  including the `bc49177` fix at `:532-537` that refuses a string returned as
  the table.

Consumption — this is what the research misses:

```python
# world_registration.py:1048-1056
if derived.get("support") is None:
    raise SupportMissingError(
        f"world {world_id} has no support.json: the 2-D/3-D association "
        "(which feature in which keyframe made each point) is not on "
        "disk. … registration is not attempted without it"
    )
```

```python
# world_registration.py:1079-1081, 1105
support_by_segment.setdefault(segment, []).append((frame, feature, point))
...
observed={(frame, feature): point for frame, feature, point in support},
```

```python
# world_registration.py:500
landmark = source.observed.get((frame_a, feature_a))
```

So `support_views` is the *only* reason cross-segment PnP can run at all. It is
not an inert artifact.

**Multiplicity (views-per-landmark).** No production code computes it. It is
derivable from `support.json` alone, and the only place it has ever been
computed is `tower/scripts/research/slam_classical/production_covisibility.py`,
which is where the research's 66.1%-two-view figure comes from.

The one thing the code guarantees is a **two-view floor**. Every landmark is
created from exactly one pair, and every additional row requires surviving PnP
RANSAC (`classical.py:836-842`). Pinned by
`tests/test_world_builder_support_views.py:138`
(`test_every_landmark_is_named_by_at_least_two_frames`) — and confirmed
empirically below at exactly 100.00%.

#### B.1 Measured — and the blocking finding

Computed with the coordinator's reference definition, stdlib only, no `tower`
import (so the venv/`PYTHONPATH` hazard does not apply). **The landmark key is
`(segment, point)`, not `point`** — `point_index` is segment-local
(`engine.py:689-698`), so keying on `point` alone silently merges landmarks
across segments and inflates multiplicity. Covisibility edges are likewise keyed
within a segment, because segments share no coordinate frame.

Validation against the coordinator's run on the canonical stale session
`dd5d13a2` — **exact reproduction, every digit**:

| quantity | mine | coordinator |
|---|---|---|
| landmarks `(segment, point)` | 12,023 | 12,023 |
| exactly 2 views | 8,079 = **67.2%** | 8,079 = 67.2% |
| 3 / 4 / 5 / 6 / 7 views | 19.5 / 7.2 / 3.1 / 1.3 / 0.8% | same |
| ≥3 / ≥5 views | 32.8% / 6.1% | 32.8% / 6.1% |
| covisibility edges / median degree | 474 / 8 | 474 / 8 |
| max multiplicity | 16 | — |

Across every world on disk carrying a support table (`(segment, point)` keying
throughout):

| world | landmarks | 2v% | ≥3v% | ≥5v% | max | cov edges | med deg | HEAD-built? |
|---|---|---|---|---|---|---|---|---|
| `3d49a771` | 3,732 | 69.8 | 30.2 | 3.2 | 8 | 110 | 7 | **no** |
| `3dd986b1` | 12,023 | 67.2 | 32.8 | 6.1 | 16 | 474 | 8 | **no** |
| `4cae0b26` | 10,977 | **52.5** | **47.5** | 14.4 | 15 | 441 | **14** | **no** |
| `748cc5d6` | 1,107 | 75.7 | 24.3 | 0.0 | 4 | 9 | 3 | **no** |
| `89ae5a6d` | 95 | 100.0 | 0.0 | 0.0 | 2 | 1 | 1 | **no** |
| `adc75972` | 7,086 | 70.7 | 29.3 | 3.3 | 10 | 223 | 7 | **no** |
| `b2ac9808` | 6,533 | 69.0 | 31.0 | 3.5 | 9 | 123 | 8 | **no** |
| `f80e88a5` | 18,899 | 64.8 | 35.2 | 6.6 | 14 | 442 | 7 | **no** |
| **pooled** | **60,452** | **64.8** | **35.2** | **6.8** | 16 | — | — | — |

Pooled distribution: 2v 64.8% · 3v 20.5% · 4v 7.9% · 5v 3.4% · 6v 1.6% ·
7v 0.9% · 8v 0.5% · 9v 0.2% · 10v 0.1% · >10v 87 landmarks.
**≥2 views: 100.00%** — the two-view floor holds exactly, on 60,452 landmarks.

**The blocking finding: not one persisted world was built by this branch's
engine.** The HEAD engine writes `points_discarded` (`engine.py:775-783`),
`points_triangulated` (`:784`) and `poses_refused_root` (`:756`)
**unconditionally** — `engine.py:773-774` says so in as many words: "Zero is
written explicitly — absent would mean 'this build predates the counter', which
is a different fact." Those three keys occur **zero times** in the other
branch's `engine.py`, and are absent from **all 19** derived manifests on disk
(newest 2026-08-27 01:04). The manifest is a reliable discriminator and it is
unanimous.

Three consequences for the implementation run:

1. **The HEAD ≥3-view share cannot be obtained by reading. It requires a
   rebuild.** Every number in the tables above describes the *other* branch's
   pipeline — pre-landmark-gate, pre-restart-rule. That is Stage 0's job, not
   something a code audit can supply.
2. **The baseline for the stop/go criterion must be a HEAD rebuild too.** The
   gate at `geometry.py:250-348` filters on parallax and reprojection, both of
   which correlate with view count, so it will move this number in a direction
   the code does not let me predict. Comparing a post-widening HEAD number
   against the 66.1% / 67.2% pre-gate figure would be **exactly the population
   mismatch the adversarial review caught** — the same error, one level up.
3. **The ">≥3-view share rises above 50%" bar is already within reach of an
   existing capture, with no widening at all.** `4cae0b26` sits at 47.5% with
   median covisibility degree 14. Per-world spread runs 24.3% → 47.5% (excluding
   the degenerate 2-keyframe `89ae5a6d`). A single-capture pass/fail on a 50%
   threshold is therefore **not a safe stop/go**: capture content moves it
   almost as much as the algorithm would. Recommend the criterion be evaluated
   per-capture over the pinned corpus with the pre/post delta reported, not as
   one pooled number crossing a line.

On the shape of the distribution — the coordinator's reason for wanting the full
histogram is well founded. Today's tail is thin and geometric-looking: past 4
views each bucket is roughly a third of the last. A widening that works by
lengthening tracks should move mass **2→3→4** and lift the median degree; one
that works by finding a few very well-observed landmarks would fatten the tail
while leaving the 2-view share nearly intact. Only the first would un-starve a
bundle adjuster, since BA gains come from many moderately-constrained landmarks
rather than a handful of heavily-observed ones.

### C. The full registration path

Everything below lives in `tower/scripts/world_registration.py`, which is a
**CLI script, not a package module**. No file under `tower/tower/` imports it
(verified by grep). `tests/test_world_builder_solver_robustness.py:35` says so
in as many words: "world_registration.py is a script, not a package module."

**What proposes a link** — `register()`, `world_registration.py:1255-1380`:

1. All-pairs over segments that have geometry: `:1270-1273`,
   `for position, left in enumerate(indices): for right in indices[position+1:]`.
2. A cheap pre-refusal before any matching — `pair_is_hopeless` (`:1136-1163`),
   which applies the *same* span-over-depth bar as the gate so a prune can never
   be stricter than `admit()` (`:1152-1155`). This is `96f6e21`.
3. `cross_matches` (`:1209-1249`): ORB + Lowe + a MAGSAC essential matrix at the
   reconstruction's own thresholds, over a **sampled** 8×8 keyframe grid
   (`:1188`, `:1224-1231`).
4. Two independent Sim(3) solves, forward and reverse — `fit_direction`
   (`:665-723`) — each PnP-ing one segment's landmarks into the other's images
   (`_pnp_observations`, `:487-540`), then Huber-refined (`:590-644`) from a
   45-step log scale grid spanning 0.02–50 (`:93-95`).

**What verifies it** — `admit()`, `:727-833`, taking `MutualEvidence` and
nothing else (`:740-751`, a load-bearing `isinstance` check). Clause order,
which matters:

| order | clause | line | threshold |
|---|---|---|---|
| 1 | finite, positive scale in both directions | `:779-788` | — |
| 2 | `min(forward.cameras, reverse.cameras)` | `:789-794` | `min_cameras = 3` (`:343`) |
| 3 | span-over-depth — "the wearer stood still" | `:798-803` | `0.09` (`:102, :373`) |
| 4 | **scale reciprocity** `s(a←b)·s(b←a)` | `:804-808` | `±0.10` (`:347`) |
| 5 | **rotation reciprocity** | `:809-815` | `15°` (`:364`) |
| 6 | scale ambiguity | `:816-820` | `3.0×` (`:350`) |
| 7 | reprojection | `:821-825` | `3.0 px` (`:366`) |

Clause 3 is deliberately evaluated before fit quality (`:795-797`), and clause 5
is honestly labelled as changing **no verdict on today's corpus** (`:360-363`) —
"Recorded so a successor does not mistake an inert guard for a load-bearing one".

The forgery defence is in `MutualEvidence.__post_init__` (`:261-289`): the two
fits must name **different posed cameras** (`provenance`, a frozenset of
`(segment, frame)`, declared at `:213-228`), because label-swapping alone was
shown to admit an algebraic inversion of the forward fit.

**Cycle consistency**, added at `859047e`: `compose_tree_with_edges` (`:978-1025`)
returns the spanning-tree edges it actually used; `cycle_residuals` (`:903-960`)
scores every admitted edge the tree did *not* need against the relationship the
tree asserts, explicitly skipping tree edges rather than inferring them from a
near-zero residual (`:930-934`); `cycle_refusal_for` (`:870-900`) refuses the
**whole cluster**, not the closing edge (`:1338-1344`), at 20° / 2.0× (`:866-867`).

**What persists it** — only `--write`, off by default (`:1676-1686`):
`placements_from_report` (`:1604-1658`) → `store.write_placements`
(`store.py:445-464`) → `derived/<session>/placements.json`. Both registered and
refused segments get a row (`:1607-1610`). `SegmentPlacement.__post_init__`
(`records.py:355-439`) refuses to construct anything that would be drawn wrongly:
a refused row carrying a transform, a registered row missing any Sim(3)
component, a non-unit quaternion (tolerance `1e-3`, `records.py:283-295`), a
non-finite or non-positive scale, a registered row with a refusal reason.

**What invalidates it** — two independent mechanisms, both in
`tower/tower/results/world_builder_geometry.py:160-219` (`usable_placements`):

1. `input_digest` binding (`69e768f`). Each row carries the digest of the build
   it was solved against (`records.py:336-349`, set at
   `world_registration.py:1734-1737`). At serve time, a mismatch drops the
   placement and logs (`world_builder_geometry.py:190-198`).
2. Reference integrity: a registered row whose `reference_segment` is not itself
   registered is refused (`:201-217`) — "A cluster missing its origin is worse
   than no cluster."

**How it reaches iOS** — `_placement_fields` (`:262-296`) emits `registered`,
`registration_state`, `transform_to_world`, `registration_refusal_reason`;
`placement_hash` (`:222-259`) is a separate cache key because `content_hash`
deliberately excludes the transform. Contract:
`docs/contracts/WORLD-BUILDER-GEOMETRY.md:106-109, 138-144, 256-272`.

**The gap:** nothing calls `register()` automatically. It is a hand-run command
whose own docstring says "It is ANALYSIS, not a production path"
(`world_registration.py:10-12`) — though that line is now out of date with
respect to `4a02590`, which made the results persisted and served.

### D. The segment / anchor model

A segment is created by **exactly two events**, and closed implicitly by the
next one.

**Event 1 — tracking loss** (`engine.py:305-325`). `decision.lost` from the
selector. Resets the tracker, bumps `_segment_index`, zeroes `_segment_solved`,
and — importantly — **zeroes `_barren_segments`** (`:318`): "A tracking loss is
not evidence that the region is unmappable — the wearer moved too fast, that is
all. It must not spend the restart budget." Then `self._live.close_segment(...)`
(`:320`). The frame is *not* persisted; it returns before `_persist_keyframe`.

**Event 2 — solve-chain break** (`engine.py:358-399`). This is the `restart
rule`. The backend's `Extension.chain_broken` is an **edge**, true only on the
keyframe that broke it (`classical.py:470-477`, and the note that a `not
was_broken` guard there was dead code). The engine acts on it only if the
restart budget allows:

```python
# engine.py:358-362
if (
    step is not None
    and step.chain_broken
    and self._barren_segments < MAX_BARREN_SEGMENTS
):
```

```python
# engine.py:393-398
self._barren_segments = (
    self._barren_segments + 1 if self._segment_solved == 0 else 0
)
self._segment_index += 1
self._segment_solved = 0
self._live.close_segment(self._segment_index)
```

`MAX_BARREN_SEGMENTS = 1` (`engine.py:166`), chosen on **marginal efficiency**
over a pinned eight-capture corpus with the full sweep recorded at `:146-151`
(cap 1 → 230 segments / 591 solved / 75,369 points; uncapped → 470 / 863 /
107,005), and settled by the observation that "REGISTRATION IS INVARIANT across
the whole range" (`:156-161`). Two earlier rules are recorded as **measured and
refused** at `:117-128`: `MIN_SOLVED_BEFORE_RESTART = 2` (can never fire for a
seed-pair failure, because an anchor is not a solved pose) and
`MIN_KEYFRAMES_BEFORE_RESTART` (delay is the wrong axis, because `chain_broken`
is an edge and no second opportunity arrives).

Note the ordering subtlety at `engine.py:342, 399, 408-418`: the
`solve_chain_broken` event is emitted **after** the keyframe it belongs to,
because the breaker was already stamped with the old index — inverting this
misattributed exactly one keyframe per break.

**Closing.** `_LiveSolve.close_segment` (`engine.py:1051-1065`) freezes the open
solve's `snapshot()` into `_frozen[old_index]` keyed by the exact tuple of
keyframe ids that produced it, then `backend.reset()`. `build()` reuses a frozen
estimate only if the id tuple still matches (`engine.py:566-572`); otherwise it
cold-solves the segment (`:573-586`). Segments are never merged, never re-opened.

**Anchor semantics.** `POSE_STATUS_ANCHOR` is the first keyframe of every
segment (`classical.py:194-196`, `:379-384`). It is *definitional*, not measured
— identity rotation, zero translation. `build()` counts it as a real position
only if something in its segment solved (`engine.py:624-630`), which is the fix
for "36 origin markers reported as 36 camera poses".

**Gauge.** `engine.py:717-722`: any world with more than one segment is
`SCALE_UNKNOWN`, because each segment has its own arbitrary unit — "measured 4x
apart between two segments of one session".

### E. Keyframe selector gates and their order

`keyframes.py:311-369`, in execution order:

| # | line | condition | outcome |
|---|---|---|---|
| 1 | `:319-320` | `not _is_sharp_enough(quality)` — absolute floor 25.0 **and** ratio 0.55 against the median of the last 30 (`:301-309`) | `REJECT / blurred` |
| 2 | `:322-323` | `motion is None or not self._has_keyframe` | `ACCEPT / session_seed` |
| 3 | `:325-333` | `survival_ratio < 0.05` (loss floor), with a grace counter of `loss_grace_frames = 1` | `TRACKING_LOST` (or `REJECT / tracking_held` inside grace) |
| 4 | `:338` | any frame that tracked resets the grace counter | — |
| 5 | `:340-341` | `survival_ratio < 0.20` | `REJECT / tracking_degraded` |
| 6 | `:343-344` | `not motion.has_motion_evidence` | `SKIP / no_motion_evidence` |
| 7 | `:349-350` | `frames_since_keyframe < min_frame_gap` | `SKIP / rate_limited` |
| 8 | `:357-358` | `overlap_ratio < 0.75` | `ACCEPT / overlap_floor` — the **dominant** accept path (198 of 260 on the real walk) |
| 9 | `:363-364` | `displacement_frac < 0.010` | `SKIP / insufficient_motion` |
| 10 | `:366-367` | `displacement_frac >= 0.035` | `ACCEPT / parallax` |
| 11 | `:369` | otherwise | `SKIP / insufficient_motion` |

**Blur still runs before the loss check.** The research's *observation* is
correct. Its *inference* is refuted here, in the code, with numbers:

> `keyframes.py:180-189`
> "NOT loosened, on the same measurement: the blur thresholds below and the gate
> ORDER in evaluate(). `min_sharpness_ratio` 0.45 gives 43 segments, 0.00 (blur
> gate off) gives 49, and moving the survival/overlap gates ahead of blur gives
> 40 — all WORSE than the 36-segment baseline. 77% of blur rejections occur when
> survival is ALREADY below 0.15: blur was masking losses that had already
> happened, not causing them. The standing hypothesis in
> docs/agent-handoffs/WORLD-BUILDER.md section 9.4, 'spurious `blurred`
> rejections cascading into `tracking_lost`', is refuted. **Do not retry it.**"

The rationale for the order is at `:316-318`: "anchoring a whole session on a
smeared frame poisons every measurement taken against it afterwards."

Also note `keyframes.py:19-58` and `:225-229`: a homography-residual degeneracy
gate **was implemented and removed on measurement**. The selector deliberately
owns no degeneracy decision; that belongs to the backend, which has intrinsics.

### F. All-pairs / bounded-neighbourhood matching

**Within a segment: none.** Strictly `i-1 → i` (§A).

**Across segments: yes, all-pairs over segments, bounded within each pair.**

- Segment pairs: complete upper triangle, `world_registration.py:1270-1273`.
- Keyframes within a pair: an 8×8 sampled cross-product,
  `MAX_KEYFRAMES_PER_SEGMENT_FOR_MATCHING = 8` (`:1188`), applied at
  `:1224-1231`. `sampled_frames` (`:1191-1206`) spreads the sample evenly and
  always includes both endpoints, "because a segment's two ends are the most
  likely places to overlap a neighbouring segment".
- The measurement behind 8 is recorded at `:1174-1187`: on `e1c52b9f`, the full
  cross-product takes 192.4 s and yields 3 segments / 5,603 points; k=8 takes
  43.6 s and yields **the identical verdict**; k=5 and k=3 lose all of them.
  "8 is therefore a measured boundary rather than a tuning knob."
- `pair_is_hopeless` (`:1136-1163`) prunes pairs before any matching, using only
  poses.json and points.json.

So there is prior art for exactly the pattern a covisibility widening needs: a
bounded neighbourhood whose bound was chosen by verdict-preservation, not by
speed.

### G. The Tower→iOS contract

**`r_h` is a persisted `KeyframeEdge` field. It is NOT on the Tower→iOS wire.**

- Computed: `classical.py:642` (`"r_h": homography_ratio(points_a, points_b)`)
  and `unposed.py:175`.
- Declared on the backend estimate: `backend.py:94`.
- Declared and serialised on the record: `records.py:772`, `:790`, `:810`.
- Written: `engine.py:659` → `store.append_edge` → `edges.jsonl`
  (`store.py:66, :261-265`).
- **Read by exactly one caller**, `inspect.py:83`, which uses only `len(edges)`
  (`:118`). No consumer reads the field.
- **Never gated on**, by explicit design: `geometry.py:112-126` — "Recorded for
  continuity with V0.9.3, which measured it, and NOT used as a gate… it
  saturates at 0.471-0.499 across the full range… the conventional 0.45
  threshold classifies every pair as rotation-dominant and separates nothing."
- Deliberately distinguished from `Keyframe.homography_residual_px`, which is a
  *different quantity in different units*: `records.py:662-671` — "Both once
  shared the name, which would have let a successor compare them and get a
  meaningless answer with no error."
- `edges.jsonl` is regenerated wholesale on every build (`engine.py:511-515`),
  so it is derived output, not a journal.

Grep of `docs/contracts/WORLD-BUILDER-IOS.md` and
`docs/contracts/WORLD-BUILDER-GEOMETRY.md` for `r_h`, `edges` or `KeyframeEdge`:
**no matches.** The wire carries poses, points, per-segment `content_hash`,
`placement_hash`, `registration_state`, `transform_to_world`,
`registration_refusal_reason`, `geometry_revision`
(`WORLD-BUILDER-GEOMETRY.md:92-144`).

**What a covisibility-graph or pose-graph change would touch:**

| change | files | notes |
|---|---|---|
| widen `_extend` to K references | `backends/classical.py` `_extend` (`:710`), both call sites (`:265`, `:418`), `_Chain.forget_before` (`:1062`), `_Chain.__slots__` (`:1021`) | must keep the batch and live paths bit-identical or `test_world_builder_incremental.py` fires |
| emit non-consecutive edges | `engine.py:644-665` (currently `zip(members, members[1:])`), `records.KeyframeEdge` (`:750`), `store.append_edge` (`:261`) | `edges.jsonl` has no wire consumer, so this is **free at the contract level** |
| a covisibility graph derived from observations | `store.write_derived` (`:367`) — a new derived artifact beside `support.json`; `store._read_support` (`:515`) is the pattern for an optional-file reader | `support.json` already carries everything needed |
| pose-graph output that moves poses | `derived/poses.json`, therefore `segment_content_hash` (`world_builder_geometry.py:40-50`), therefore `geometry_revision`; and `SegmentPlacement.input_digest` invalidation (`world_builder_geometry.py:190-198`) will correctly drop every existing placement | This is the expensive one |
| a gauge change (re-anchoring a submap) | `schema.py:96-111` — the rule is already frozen: "a coordinate stamped revision R can be brought current only if EVERY entry from R to HEAD is GLOBAL_SIM3", and `frame_revision` is stamped on `Keyframe` (`records.py:673`), `KeyframeEdge` (`:777`) and `SegmentPlacement` (`:352`) | V1 never advances it; no gauge-entry writer exists |

### H. Tests and controls

*(This section is completed in §H-detail below, from a dedicated test survey.)*

**The control story, from the code and commit record:**

`tower/scripts/world_builder_corpus_benchmark.py:448-540` — `run_controls`. The
prior control was capture `4fea31e2`, chosen as a zero-yield case. It **stopped
being a zero** when the refusal cascade was fixed, and the commit that replaced
it (`d01808d`) states the principle directly: "A control one algorithm change
away from moving is not a control."

The replacement is a matched pair whose answers are *logical*, not empirical:

- **NEGATIVE — pure rotation** (`:466-472`, asserted `:526-533`). A camera that
  turns without translating has no baseline, so any triangulated point is
  fabrication by definition. Chosen as the strongest available negative because
  the pipeline still *runs* — it accepts keyframes and forms segments — so the
  control tests refusal rather than the selector silently discarding everything.
- **POSITIVE — a strafe, required non-zero** (`:473-479`, asserted `:534-538`).
  Without it, "0 points" from the negative is indistinguishable from a pipeline
  that has stopped working.

Both were **verified to fire**, which is the part worth trusting: zeroing
`MIN_TRIANGULATION_ANGLE_DEG` and `MIN_INLIER_RATIO` was *not enough*, because
pure rotation is refused by three independent conditions in the seed-pair gate;
removing the whole degeneracy check produced 9 solved poses and 389 points from
a stationary camera and the control caught it loudly (`:480-483`). A failed
control still writes its output but exits non-zero (`:881-885`).

The branch's own status doc records the meta-lesson at
`WORLD-BUILDER-NEXT-GENERATION-STATUS.md:138-143`: four adversarial reviews ran,
and "the most valuable finding was that a whole feature could be reverted with
the suite green, because its only engine-level test asserted the mechanism did
*not* fire."

---

## 3. What the research package gets WRONG about this branch

Ordered by how much an implementation run would waste acting on it.

### 3.1 The package is unaware that `tower/scripts/world_registration.py` exists

This is the big one. Across the 5,798 lines of the synthesis, three lane reports
and the adversarial review, the strings `world_registration`, `MutualEvidence`,
`placements.json` and `cycle_resid` appear **three times total**, and none of
them in the synthesis's capability analysis. (`2026-08-26-cross-segment-registration.md`
— a *different, earlier* research note — is the one that discusses the area, and
it predates the module: its §1.1 says "`support_views` is declared and never
written".)

**And this is not even a branch-staleness excuse.** I compared the module across
both trees. On `integration/world-builder-lifecycle-v1` the script already exists
at 1,313 lines and already contains `MutualEvidence` (12 occurrences) — so
Sim(3), reciprocity, the provenance clause and `admit()` were visible from
*either* branch. The research simply never opened the file.

What is genuinely **new on this branch** (0 occurrences in the main repo's copy,
present here):

| feature | main repo | here |
|---|---|---|
| `MutualEvidence` / reciprocity / `admit()` | present | present |
| `cycle_residuals` / `cycle_refusal_for` | **absent** | `:870-960` |
| `MAX_KEYFRAMES_PER_SEGMENT_FOR_MATCHING` (8× sampling) | **absent** | `:1188` |
| `input_digest` binding | **absent** | `:1616-1650` |
| `write_placements` / `SegmentPlacement` | **absent** (also absent from `records.py`) | `store.py:445`, `records.py:302` |

So: cycle consistency, affordable matching and placement persistence/invalidation
are true branch-staleness findings. Sim(3) and reciprocity are a **research
coverage gap** on both branches, which is worse — it means the omission would not
have been fixed by re-measuring.

Consequences, all of which would cause an implementation run to rebuild
something that exists:

- **Sim(3) estimation** is described as "~120 LOC, patent-free" future work
  (matrix row 9). It is 1,755 lines of shipped, gated, tested, persisted module.
- **Reciprocity** is proposed as a Stage-1 addition (synthesis line 260) and
  treated as an open research question (line 1131). Scale reciprocity
  (`:804-808`), rotation reciprocity (`:809-815`) and a provenance-based forgery
  check (`:277-289`) are implemented and gating.
- **Cycle consistency** is not mentioned. It landed at `859047e` and is the
  module's first independent check (`:903-960`, `:1336-1344`).
- **Map merging** (matrix row 8) is called "the schema is right and empty". The
  schema is right and **full**: `placements.json` is written, digest-bound,
  reference-checked and served.
- **Pose graph optimization** (row 10) is called "vacuous until (2)" because "a
  tree has no cycle". A cycle now exists — `2e6cffa2` admits the triangle
  (12,16),(12,19),(16,19), closing to 5.899° and 1.06× (`:855-861`). The
  premise moved.

### 3.2 "Local bundle adjustment: implemented, measured at 0.00% improvement"

Matrix row 11 says BA is **IMPLEMENTED, STARVED** and instructs "Do not touch it
until (2) lands." There is no BA implementation on this branch. Grep for
`bundle_adjust|BundleAdjust` over `tower/` returns only prose: `classical.py:321`
("There is no bundle adjustment and no loop closure — BA was implemented and
measured at 0.00% drift improvement…"), `records.py:489`, and three research
scripts quoting the same historical result.

An implementation run told "the solver is there, feed it" would go looking for a
file that does not exist. The correct statement is: **BA was implemented on some
earlier branch, measured at 0.00%, and is not present here.** Landing
covisibility does not un-starve an existing solver; it makes writing one
worthwhile.

### 3.3 The r_H correction is itself half-wrong

Synthesis §0.4 strikes rev 1's "`r_H` is computed and never consumed" as
"**WRONG.** It is a persisted `KeyframeEdge` field in the Tower→iOS contract".

Two separate claims, one right and one wrong:

- Persisted `KeyframeEdge` field: **correct** (`records.py:772`).
- "in the Tower→iOS contract": **incorrect**. `edges.jsonl` is not on any wire.
  Neither `docs/contracts/WORLD-BUILDER-IOS.md` nor
  `docs/contracts/WORLD-BUILDER-GEOMETRY.md` mentions `r_h` or edges at all, and
  the only reader of `edges.jsonl` in the entire repo is `inspect.py:83`, which
  uses `len()`.

And rev 1's substantive point survives: **nothing consumes `r_h`.** Deleting the
field would break no consumer. It is retained deliberately as a recorded
observation, not as a live signal (`geometry.py:114-126`).

### 3.4 "Segments are bookkeeping labels, not maps"

Matrix row 4. On this branch a segment is an independently solved map with a
frozen estimate keyed to its exact member set (`engine.py:1051-1065`,
`:566-572`), its own gauge (`engine.py:717-722`), its own published point set
tagged by segment (`engine.py:678-687`), its own content hash and its own
placement (`world_builder_geometry.py:40-50`, `:160-219`). What the research is
right about is narrower: **there is no admission bar** — no minimum keyframe
count, no minimum solved-pose count, no geometry requirement — which is why the
corpus has 230 of them.

### 3.5 "The blur gate masks losses" is presented as a live finding

The observation is correct and the conclusion is refuted *in the file*, with the
ablation numbers, at `keyframes.py:180-189`, ending "Do not retry it." Any plan
item that proposes reordering the selector gates is re-running a completed
experiment.

### 3.6 Landmark gating and the derived parallax bound are absent from the matrix

Not wrong, but a gap. `geometry.py:202-231` derives the publication parallax
bound as σ_px/f (≈0.131° at this calibration) rather than picking a constant, and
records that gating at `MIN_TRIANGULATION_ANGLE_DEG` (0.5°) instead discards
37-44% of points for the same fragment legibility. Any plan that changes what is
published needs to know this bound exists and why it is not 0.5°.

### 3.7 The commit-count premise

The brief's "155 commits ahead" is 42 ahead / 3 behind. Minor, but it inflates
the expected staleness — and, as §0 notes, the research was in fact measured
against this branch's own earlier state.

---

## 4. What is genuinely still missing

Everything in this list I confirmed absent by reading, not by inference from the
research.

**Tier 1 — nothing exists, and the input for it does.**

1. **Covisibility graph.** No code computes shared observations between any two
   keyframes anywhere in `tower/tower/`. `engine.py:644-646` emits only
   consecutive edges. The observation table is on disk and segment-tagged
   (`support.json`), so this is a query, not a measurement. `edges.jsonl` has no
   wire consumer, so widening the edge set is contract-free.
2. **Multi-reference `_extend`.** `classical.py:723` matches one pair. The state
   for more is deliberately deleted (`:1086-1088`). Both the batch and live paths
   must widen together (`test_world_builder_incremental.py`).
3. **Landmark multiplicity as a production quantity.** Derivable from
   `support.json` in a few lines; computed only in a research script today.
   **Now measured — see §B.1.** Pooled over all 60,452 persisted landmarks:
   64.8% exactly-2, 35.2% ≥3, 6.8% ≥5, two-view floor exactly 100.00%.
   **But every persisted world predates this branch's engine**, so the HEAD
   baseline does not exist yet and must be rebuilt before the Stage 1 stop/go
   means anything.

**Tier 2 — nothing exists, and the input for it does not.**

4. **Local map / windowed optimization.** No windowed state survives past `i-1`.
   Blocked on (1) and (2).
5. **Local bundle adjustment.** *No implementation exists on this branch* —
   contrary to the research. Blocked on (1)/(2)/(4), and pointless before them.
6. **Global bundle adjustment.** Same.
7. **Keyframe-level pose graph optimization.** Nothing. Segment-level composition
   is a BFS spanning tree by explicit choice (`world_registration.py:978-995`),
   with cycle *checking* but no cycle *distribution*. Now that a cycle exists, a
   segment-level pose graph is no longer vacuous — but it would optimise 3 nodes.
8. **Place recognition / retrieval.** Nothing in production. This is the named
   blocker for live registration
   (`WORLD-BUILDER-NEXT-GENERATION-STATUS.md:117-120`).
9. **Relocalization.** Nothing. A break is permanent by construction.
10. **Loop closure.** Nothing, and blocked on 1, 8 and a validity gate.
11. **Background refinement.** No thread, no executor. `build()` runs inline
    (`scripts/world_build_session.py:577-579`).

**Tier 3 — exists but is not automatic, or is inert.**

12. **Registration never runs on its own.** `register()` has no caller in
    `tower/tower/`. `--write` is opt-in (`world_registration.py:1676-1686`). At
    44 s and 20 s on the two registering worlds it is affordable at
    *finalisation* and not per-rebuild (a walk rebuilds ~150 times). The missing
    piece is a **finalisation hook**, not an algorithm — this is the cheapest
    item on this entire list.
13. **`r_h` is written and never read.** Either give it a consumer or delete the
    write; a persisted field with no reader is a future misinterpretation
    (`records.py:666-670` says exactly this about its near-namesake).
14. **`rotation_disagreement_deg` gates nothing on today's corpus**, and says so
    (`world_registration.py:360-363`). Honest, but it means the reciprocity
    ladder has one untested rung.
15. **No segment admission bar.** No minimum size or geometry requirement, which
    is what produces 230 fragment cards and what makes the +517-pose uncapped
    restart rule unshippable (`engine.py:163-165`,
    `WORLD-BUILDER-NEXT-GENERATION-STATUS.md:129-132`).
16. **`frame_revision` / gauge entries.** The rule is frozen
    (`schema.py:96-111`) and nothing writes one. Any pose-graph or loop-closure
    work that moves part of the world must implement this first, or every
    persisted coordinate silently changes meaning.
17. **The registration integration tests do not run here** (§H.6): 10 tests
    skip because world `3dd986b1…` is absent from the worktree's corpus, and
    those are the only end-to-end checks on the gate. The corpus benchmark's
    integrity controls likewise never run in CI (§H.4). Both are silent.
18. **Nothing asserts keyframe-edge topology** (§H.2). Convenient for widening
    the edge set — and the reason a wrong widening would go unnoticed.

**Explicitly NOT missing** (do not schedule work for these): Sim(3) estimation,
scale reciprocity, rotation reciprocity, provenance/forgery checking, cycle
consistency, span-over-depth pre-refusal, cross-segment PnP registration,
placement persistence, digest-based placement invalidation, reference-integrity
checking, placement hashing and wire transport, cheirality gating (three sites),
the derived landmark parallax gate, `support_views` production **and**
consumption, the chain-break restart rule, and the keyframe selector's gate
order.

---

## H-detail. Test and control inventory

All paths relative to `C:\Users\tvllo\Projects\Glasses-world-builder\`.

### H.1 Counts

| file (`tower/tests/`) | LOC | test defs |
|---|---|---|
| `test_world_registration.py` | 994 | 59 (**10 silently skip** — H.6) |
| `test_world_builder_point_quality.py` | 1014 | 33 |
| `test_world_builder_frontend.py` | 598 | 32 |
| `test_world_builder_engine.py` | 667 | 31 |
| `test_world_builder_placements.py` | 779 | 31 defs (2 parametrized) |
| `test_world_builder_incremental.py` | 868 | 24 |
| `test_world_builder_support_views.py` | 437 | 14 |
| `test_world_builder_loss_grace.py` | 190 | 10 |
| `test_world_registration_cycles.py` | 181 | 9 |
| `test_world_builder_chain_break_engine.py` | 255 | 5 |
| `test_world_builder_tracking_reach.py` | 168 | 5 |
| `test_world_builder_chain_break_segments.py` | 151 | 3 |

### H.2 Per-mechanism verdicts

**`support_views`** — genuinely controlled. `test_world_builder_support_views.py:167`
reprojects every row (median < 3.0 px) and `:206` is its differential twin: a
shuffled table reprojects at > 100 px. `:246` asserts live-vs-cold `tobytes()`
equality at zero tolerance, and `:271` asserts the prune happened
(`len(retained) == 1`) *while* the table spans multiple frames — wired directly
against `_Chain.forget_before`. `test_world_builder_point_quality.py:916` is
differential on the publication rule: halve the PnP inlier set, published rows
must halve.

**Registration gate** — genuinely controlled at the unit level.
`test_world_registration.py:67` pins the `admit()` type refusal; `:86`
(`test_an_algebraically_inverted_copy_is_not_independent`) kills the documented
relabel-and-invert bypass; `:143` flips the verdict by changing only the reverse
scale; `:153` proves perfect reprojection cannot rescue bad reciprocity; `:770`
refuses on rotation while asserting `abs(reciprocity - 1.0) < 1e-9`, i.e. proving
the scale clause would have admitted it. `:861` monkeypatches `cross_matches` and
asserts `calls == 0`, controlling the cost of the hopeless-pair prune; `:896`
probes ±1e-6 around the shared threshold.

**Cycle consistency** — the best-constructed file in the suite.
`test_world_registration_cycles.py` has a consistent-closure negative (`:64`), a
45° positive (`:80`), a 3× scale positive (`:93`), tree-edge exclusion (`:115`),
and — notably — `:134` brackets the constants two-sidedly against measurement
(`5.899 < MAX_CYCLE_ROTATION_DEG < 31.9`, `1.06 < MAX_CYCLE_SCALE_RATIO < 3.2`)
rather than pinning a literal.

**Placements + digest invalidation** — controlled, and visibly hardened by a past
review. `test_world_builder_placements.py:588` writes a placement, rebuilds
derived under a new digest, and asserts the placement is no longer served. `:244`
is three-way (`content_hash` unchanged ∧ `placement_hash` changed ∧
`geometry_revision` changed). `:474` is the important one: its header (`:457-471`)
records that an adversarial review deleted **all six** hash fields with the suite
green, because the previous test only exercised an unplaced→registered transition
(a 1-key vs 6-key dict comparison). It now varies one field at a time.

**Chain break + restart budget** — controlled, and this is the prior art the brief
asks about. `test_world_builder_chain_break_engine.py`'s module docstring
(`:1-12`) states it plainly: *"An adversarial review found the entire feature
could be reverted with the suite still green. The only engine-level test asserted
that a CLEAN walk is not split — which an implementation that never splits at all
also satisfies."* The replacements are real: `:173` monkeypatches the selector to
accept everything so a tracking loss cannot supply the split, then asserts 2
segments; `:189` and `:203` bracket `MAX_BARREN_SEGMENTS = 1` two-sidedly
(barren breaks give exactly 2 segments, productive ones exactly 4), so both
removing the budget and raising it to 2 fail. `:214` catches cross-session
inheritance. The constant itself is pinned only behaviourally, which is the right
choice.

**Selector gate order** — directly controlled.
`test_world_builder_frontend.py:539`
(`test_blur_is_still_the_first_gate_and_still_on_the_absolute_floor`) feeds a
frame that is *both* unusably blurred (`sharpness=3.0`) and completely untracked
(`survival_ratio=0.0`) and asserts `REASON_BLURRED`. Move the survival gate ahead
of blur and the reason changes. `:437` pins the ordering
`loss < min_survival < min_overlap` and `:467` asserts the rescue actually fires
before a loss is declared — the docstring notes it **failed under the old
constants**, so it is a real regression control.

**Landmark gate** — controlled. `test_world_builder_point_quality.py:129`/`:147`
are a matched reject/keep pair; `:245` asserts the bar equals
`degrees(RANSAC_THRESHOLD_PX / focal)` computed from first principles rather than
a literal; `:272` asserts it scales with focal length; `:286` asserts it is
distinct from `MIN_TRIANGULATION_ANGLE_DEG`. The header at `:309-313` records
that a review found 7 of 8 mutants surviving, and the block after names the
mutant each test now kills.

**Live-vs-cold equivalence** — the guardrail for any `_extend` widening.
`test_world_builder_incremental.py:218` compares digests with `==`, no tolerance,
and `:236` is a meta-control justifying that zero tolerance so nobody is tempted
to loosen it. Note the digest helper at `:180-191`: `support_views` was
**omitted** from it until a review added it, so "bit-identical" did not cover the
association index at all for a period. It does now (`:186-190`).

**Keyframe edges** — thinly covered. `test_world_builder_engine.py:248` asserts
edges exist and carry measurements even when poses are refused; `:543` asserts a
second build does not double the count, which is a real control for
`engine.py:515` (`clear_edges`). **Nothing asserts which keyframe pairs get
edges.** That is convenient for the covisibility work — widening the edge set
breaks no test — and it is also why nothing would notice if the widening were
wrong.

### H.3 Tests that would pass if the mechanism were deleted

Seven, and the codebase is honest about five of them:

1. **`test_world_builder_chain_break_segments.py:104`** —
   `test_engine_starts_a_new_segment_when_the_solve_chain_breaks` asserts
   `segments == {0}`. Its own comment (`:145-147`) says it asserts the mechanism
   *does not fire spuriously*. **This is the exact prior-art test.** It is now
   compensated by `chain_break_engine.py:173`, but the name still misrepresents
   the assertion, and deleting that other file would restore the green-on-revert
   state.
2. **`test_world_builder_placements.py:517`** — docstring declares the
   `state`-drop mutation equivalent and unkilled, with the argument (state is
   implied by the transform fields).
3. **`test_world_builder_loss_grace.py:176`** — pins `loss_grace_frames == 1`,
   i.e. pins the mechanism **off**. The whole 10-test file exercises a code path
   that does not run in production.
4. **`test_world_registration.py:745-750`** — the rotation-reciprocity header
   states the clause changes no verdict on today's corpus.
5. **`test_world_builder_support_views.py:417`** —
   `test_writing_the_association_changes_no_geometry` is a no-change assertion,
   satisfied by never writing support at all.
6. **`test_world_builder_point_quality.py:111`** — a characterisation test by
   name; satisfied by a gate that admits everything.
7. **`test_world_builder_point_quality.py:938`** —
   `test_published_support_rows_reproject_tightly` asserts only
   `len(errors) > 10`; the docstring concedes it asserts no tight bound. The name
   overclaims.

Items 1-4 are declared in-file. Items 5-7 are not.

### H.4 The corpus benchmark controls

`tower/scripts/world_builder_corpus_benchmark.py:452-540`. The two assertions:

```python
# :526
if negative["poses_solved"] or negative["points"]:
    failures.append(
        f"NEGATIVE CONTROL FABRICATED GEOMETRY: pure rotation produced "
        f"{negative['poses_solved']} solved poses and "
        f"{negative['points']} points. A camera that only turns has no "
        f"baseline; nothing can be triangulated from it."
    )
# :533
if not positive["poses_solved"] or not positive["points"]:
    failures.append(
        f"POSITIVE CONTROL PRODUCED NOTHING: a strafe gave "
        f"{positive['poses_solved']} solved poses and "
        f"{positive['points']} points. The negative control below is "
        f"meaningless until this one works."
    )
```

Negative fires on any non-zero yield from `ss.pure_rotation(24)`; positive fires
on any zero from `ss.strafe(12, step=0.12)`. Enforced at `:834`, `:842-845`,
`:885` (`return 1 if controls["failures"] else 0`) — a failed run still writes its
output but exits non-zero (`:881-884`).

Why this is the strongest control in the codebase: the correct answers are
**logical, not empirical**, so no algorithm change can move them — which is
precisely the defect that retired the previous control (`d01808d`: capture
`4fea31e2`'s zero yield stopped being a zero once the refusal cascade was fixed).
And it was **verified to fire**, at the second attempt: zeroing
`MIN_TRIANGULATION_ANGLE_DEG` and `MIN_INLIER_RATIO` was not enough because pure
rotation is refused by three independent seed-pair conditions; removing the whole
degeneracy check produced 9 poses and 389 points and the control caught it
(`:478-484`).

Two weaknesses worth knowing:

- **It never runs in CI.** No file under `tower/tests/` imports
  `world_builder_corpus_benchmark`. It fires only on a manual script invocation.
- **The positive control is bare truthiness.** One pose and one point passes.
  There is no floor on how much reconstruction counts as "working", so a 90%
  regression would not fire it.

`tower/scripts/world_builder_benchmark.py` (251 lines) has **no controls and no
assertions** — a pure timing harness whose own header bars citing quality numbers
from it.

### H.5 Summary of the control story

The branch has a genuine, documented practice of control quality: four adversarial
reviews (`WORLD-BUILDER-NEXT-GENERATION-STATUS.md:138-143`), at least four
in-file records of a test that was found not to kill its mutant and was then
replaced (`chain_break_engine.py:1-12`, `placements.py:457-471`,
`point_quality.py:309-313`, `tracking_reach.py:15-21`), and a benchmark control
that was retired for drifting and replaced with logically-fixed answers. Where
a test does not kill, the file usually says so. **The unstated exceptions are
H.3 items 5-7.**

### H.6 The gap that matters most

`test_world_registration.py`'s entire real-corpus class — `TestTheRealWalk`,
`:615-732`, **10 tests** — pins `REAL_WORLD = "3dd986b1c2364d4b85de97152f2e39f4"`
under `REAL_ROOT = Path("data/world_builder")` (`:597-611`). **That world is not
present in this worktree.** `tower/data/world_builder/worlds/` here holds 26
worlds and `3dd986b1…` is not among them. So the class skips.

Included in the skip: `:692 test_every_admitted_pair_passed_every_clause` and
`:704 test_pairs_whose_directions_disagree_are_never_admitted` — the **only**
end-to-end checks that the registration gate does anything on real data. Their
absence is invisible in a green run.

Two consequences for tonight:

1. The registration gate's unit tests are strong (H.2) but its integration
   evidence is not running here. Any claim that "registration is verified on this
   branch" rests on synthetic fixtures plus the numbers in the status doc, not on
   a passing suite.
2. Because the worktree's `data/` is a *different, partial* corpus from the main
   repo's, a suite run in the worktree and a suite run in the main repo skip
   different tests. Neither skip is announced beyond pytest's `s`.

Minor: `_segment_with_span` is defined twice in `test_world_registration.py`
(`:819` and `:831`); the first is shadowed and dead.

