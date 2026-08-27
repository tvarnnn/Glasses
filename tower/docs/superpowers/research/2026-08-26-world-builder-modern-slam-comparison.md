# World Builder vs modern SLAM — independent synthesis, verdict and roadmap

**Date:** 2026-08-26. **Branch:** `integration/world-builder-lifecycle-v1`.
**Author:** independent synthesis / adversarial review agent. Research only —
no production code was modified, `ios/` was not touched, nothing was merged.

**Audience:** the engineer who will implement this and who has not read the
three lane reports. You do not need to. Everything load-bearing is restated
here, and where a lane's number did not survive review it is struck and
replaced rather than repeated.

**Revision 2, 2026-08-27.** This document was put through an independent
adversarial review (`2026-08-26-world-builder-slam-adversarial-review.md`),
which independently replayed the capture and reproduced the re-baseline, the
66.1% two-view figure, the 61.5% gate failure, the 0.0%-vs-13.0% gate
comparison and the connectivity figures — then found six defects that would
have cost an implementation team real budget. **All six are accepted and fixed
here**, each re-verified against this review's own artefacts before adoption.
The changes that matter most: the pointmap validity gate this document
previously called "the sufficient guard" **does not clear its own acceptance
test and has been struck** (§5.1.3); §2's headline "42×" is **mostly a
population artefact and is restated at 2.6× like-for-like**; Stage 1's and
Stage 4's stop/go criteria were **unmeetable as written and have been
re-derived**; and "connectivity is not the gap" is **criterion-dependent and is
now stated with the criterion attached**. The architectural conclusion is
unchanged. §10 is the changelog.

---

## 0. READ THIS FIRST

### 0.1 There is no ground truth. None. Anywhere.

This corpus has no surveyed room geometry, no reference trajectory, no metric
scale, and no external pose source. **Every number produced by this entire
research programme — including every number in this document — is a
COMPARATIVE or SELF-CONSISTENCY measurement.** "Verified edge" means two views
admitted a consistent two-view geometry, never that they see the same place.
"Solvable" means our own degeneracy criterion would have accepted the pair,
never that the pose is right. "Same place" judgements are one person looking at
two JPEGs.

There are exactly **two** measurements in the whole programme with a known
right answer, and both are synthetic constructions rather than observations:
Lane 2's pure-rotation null, and the extension of it this review ran. Both work
by warping a real frame by a known rotation about the camera centre, so the
true translation is *exactly* zero by construction. Everything else is
self-consistency. Weight accordingly.

### 0.2 Labelling

`[M-SYN]` measured by this review, today, on this host — harness named.
`[M-L1] [M-L2] [M-L3]` measured by lane 1 / 2 / 3.
`[M-LEAD]` measured by the research lead.
`[Q]` quoted from source or paper, cited.
`[E]` estimated, with the method shown inline.
**Unlabelled numbers from the lane reports have been struck, not propagated.**

### 0.3 The verdict in nine lines

1. **Our map architecture is primitive and our frontend is better than anyone
   in this programme realised.** Both halves are now measured. The graph is the
   problem; the refusal logic is an asset.
2. **The fragmentation baseline every lane and the shared brief quote — "457
   keyframes, 51 segments, 94 solved poses" — is STALE.** At HEAD the same
   1,848 frames give **448 keyframes, 33 segments, 61 solved poses, 8,333
   points** `[M-SYN]`. One commit on 2026-08-25 — **`6e60f76`**, the
   stale-reference fix — already cut fragmentation 35%. Re-baseline before
   optimising.
3. **Do the covisibility change first.** It needs no new dependency and is the
   precondition that makes every other classical technique stop being a no-op.
   Sized honestly: **over the same 72 keyframes production actually uses, the
   frames support 486 covisibility edges where production builds 189 — 2.6×**
   `[M-SYN]`. (The 8,021-vs-189 "42×" this document led with in revision 1 is
   mostly a population artefact; §2.) 2.6× is smaller than it looked and is
   still sufficient, because the binding constraint is landmark multiplicity,
   not edge count: **66.1% of landmarks are seen by exactly two views**, and a
   two-view landmark contributes nothing for bundle adjustment to tighten.
4. **Do not adopt learned VO (DPVO/DROID).** It is cheap and it delivers the
   continuity we lack, but two runs on identical frames disagree by 12–38% of
   trajectory extent `[M-L2]`, while our pipeline is **bit-for-bit reproducible
   across fresh processes** `[M-SYN]`. That trade is a regression.
5. **Do not adopt Lane 3's validity gate. It is broken — and no replacement
   measured in this programme works either.** On 200 pairs whose true
   translation is exactly zero, `recip_R < 15° AND E-ratio > 0.5` accepts
   **61.5%** `[M-SYN]`, and ranks them as the *most* confident links in the
   corpus. Revision 1 of this document proposed a repair; on re-examination
   **that repair is 2.6% false-positive on the same null and rejects the only
   classically-corroborated positive**, and the one variant that reaches 0%
   accepts **nothing at all** `[M-SYN]`. **On this footage, cross-segment
   registration is not yet safely gateable**, so Stages 5 and 6 are
   conditional rather than scheduled (§3, §5.1.3).
6. **Our own shipped two-view gate scores 0.0% on that same test** `[M-SYN]`,
   and accepts *more* real pairs at keyframe gaps 1–3 (the advantage reverses
   past gap 5). The mechanism is not rotation *recognition* — it is a
   conservative baseline-magnitude floor, the cheirality-ratio gate in
   `classical.py`, with a documented false-negative cost its own source
   records. It is still the best-performing degeneracy check measured anywhere
   in this programme, and nobody noticed it was there.
7. **A pointmap model is not needed for connectivity — but "connected" is a
   weaker property than it sounds.** With plain ORB and one supporting keyframe
   pair per link, all 33 segments form one component at HEAD `[M-SYN]`. Require
   the 3-supporting-keyframe-pair consistency this document itself makes
   mandatory and it becomes **6 components, largest 28 of 33**; restrict to the
   **11 of 33 segments that carry any geometry at all** and it is **3
   components, with segment 5 — 904 points, the third largest in the map —
   isolated** `[M-SYN]`. Lane 3's flagship "blind" pair `seg0-45` is still
   linked by ORB with 192 essential-matrix inliers at 4.42° parallax, so the
   deflation of Lane 3 stands. What is missing is a pipeline that can *use*
   those edges, not a foundation model.
8. **Scale is not recoverable. Ever.** No loop closure, BA, merge or learned
   model changes that. Monocular gives shape up to a similarity. Say it in the
   PR description so nobody re-litigates it.
9. **Nothing in the recommended roadmap requires importing third-party source.**
   Every component has a permissively-licensed route or is ~100 lines of our
   own. We adopt architecture; we do not copy implementations.

### 0.4 What this review changed about the programme's conclusions

| Claim as it stood | Status after review |
|---|---|
| "457 keyframes / 51 segments / 94 solved poses is current state" | **STALE.** 448 / 33 / 61 at HEAD `[M-SYN]` §4.1 |
| Lane 3: `recip_R<15 ∧ E-ratio>0.5` accepts 0 of 16 negatives | **INCOMPLETE.** 61.5% false-positive on zero-baseline pairs `[M-SYN]` §5.1 |
| Lane 2: "ORB has a 14.4% false-positive rate under pure rotation" | **STRUCK as a statement about production.** Production's own gate: 0.0% `[M-SYN]` §5.1.4 |
| Lane 2: "widen the baseline — gap 1→5 moves solvable 28.2%→44.4%" | **TRUE on raw frames, FALSE on keyframes.** On keyframes acceptance *falls* with gap `[M-SYN]` §5.2 |
| Lane 1: "consecutive keyframes are the worst-conditioned pairs" | **Base-rate inversion.** Per pair asked they are the *most* productive `[M-SYN]` §5.2 |
| Lane 1: "51 segments collapse to 3 components" | Direction survives; numbers superseded and criterion-dependent: at HEAD, 33 → **1** component at 1 supporting keyframe pair, **6** at 3, **16** at essential-graph strength `[M-SYN]` §5.1.6 |
| **rev 1 of this document: "42× more edges are available"** | **Mostly a population artefact.** Like-for-like over the same 72 keyframes it is **2.6×** `[M-SYN]` §2 |
| **rev 1: "baseline/depth > 0.05 is the sufficient guard"** | **STRUCK.** 2.6% false-positive on the null, and it rejects the only classically-corroborated positive `[M-SYN]` §5.1.3 |
| **rev 1: "`r_H` is computed and never consumed"** | **WRONG.** It is a persisted `KeyframeEdge` field in the Tower→iOS contract `[M-SYN]` §5.1.5 |
| **rev 1: fragmentation was cut by `85d94a2` and `1272b09`** | **Wrong commits.** `6e60f76` (2026-08-25 22:32:57) took the walk 51 → 33 `[M-SYN]` §4.1 |
| Lane 3: "MASt3R links segments where ORB found zero" | **Confirmed for `seg6-30`** by Lane 1's independent census `[M-SYN]`, but the *unique* value is far smaller than presented §5.1.6 |
| Tension 4: redaction and featureless keyframes are separate problems | **They are the same root cause.** 20 of the 24 feature-starved keyframes are >40% redaction fill `[M-SYN]` §5.4 |
| r_H is worth keeping around in case we ever gate on it | **Refuted from a new direction.** r_H median is 0.496 on *exactly*-zero-baseline pairs `[M-SYN]` §5.1.5 |

---

## 1. The comparison matrix

Columns are the four architectures. The final column is the answer to the
original brief's central question: for each capability, are we
**MISSING** it (no structure exists to hold it) or **IMPLEMENTING IT POORLY**
(the structure exists and is starved, inert, or mis-parameterised)?

Read the last column first. It is the whole decision.

| # | Capability | World Builder (HEAD, measured) | ORB-SLAM3-style | DPVO / DROID-style | MASt3R / DUSt3R-style | **Missing or poorly implemented?** |
|---|---|---|---|---|---|---|
| 1 | **Linear keyframe chain** | The only structure that exists. `_extend` matches keyframe *i* to *i−1* only. 189 covisibility edges, median degree 5.5 over 72 geometry-bearing keyframes `[M-SYN]` | superseded by covisibility | superseded by patch graph | n/a — pairwise | — (this *is* the current design) |
| 2 | **Covisibility graph** | none. 0 cross-segment edges. Frames support 486 edges over the same 72 geometry-bearing keyframes (2.6×), or 8,021 over all 448 `[M-SYN]` | `mConnectedKeyFrameWeights`, `th=15` shared map points, never-disconnect fallback `[Q]` | patch graph: `PATCH_LIFETIME 12–13`, each patch constrains up to 13 poses `[M-L2]` | none — a verifier, not a graph | **MISSING.** The single highest-value gap. |
| 3 | **Local map** | none. Solve window is 2 keyframes | `GetVectorCovisibleKeyFrames()` + fixed neighbours `[Q]` | `OPTIMIZATION_WINDOW 10–12` `[M-L2]` | window ≤ ~20–30 images, VRAM-bounded `[M-L3]` | **MISSING**, but trivially derived once (2) exists |
| 4 | **Multiple concurrent maps (Atlas)** | 33 "segments", but they are bookkeeping labels, not maps: no minimum size, no geometry requirement | real Atlas; a map needs >10 keyframes and survived initialisation gates `[Q]` | one map, always | n/a | **MISSING — and we should NOT build it.** §7 |
| 5 | **Relocalization** | none. A break is permanent | 3 s RECENTLY_LOST at widened radius, inlier floor 10 vs 30 `[Q]` | none (no failure state exists) | n/a | **MISSING.** Cheap partial win: §6 Stage 2 |
| 6 | **Place recognition** | none | DBoW2 vocab tree + inverted index, 145 MB asset `[M-L1]` | optional DBoW2 in DPV-SLAM | ASMK over encoder tokens, MIT `[Q]` | **MISSING.** In-domain 10k-word vocab measured at 73% R@10 on long-gap revisits, trained in 10.7 s `[M-L1]` |
| 7 | **Loop closure** | none | 9-gate ladder incl. temporal consistency over 3 consecutive keyframes `[Q]` | DPV-SLAM only, on its own patch graph | MASt3R-SLAM: incremental ASMK + Sim(3) factor graph `[M-L3, source]` | **MISSING.** Blocked on (2) and (6), and on a *working* validity gate — which we do not yet have (§5.1) |
| 8 | **Map merging** | none. `registered:False` / `transform_to_world:None` fields exist and are inert `[Q]` | `MergeLocal`/`MergeLocal2`, ~1.1 kLOC, 4 known pointer bugs + an infinite loop `[Q-L1]` | n/a | n/a | **Poorly implemented — the schema is right and empty.** Fill in the declared structure; do NOT port `MergeLocal`. |
| 9 | **Sim(3) estimation** | none in production. Proven offline end-to-end: 419 correspondences, 1.50 px, reverse agreement 0.3% `[Q, prior lane]` | Horn 1987, RANSAC (0.99, 15, 300), symmetric reprojection inlier test `[Q]` | lietorch Sim(3) available | n/a | **MISSING in production, SOLVED in research.** ~120 LOC, patent-free `[E-L1]` |
| 10 | **Pose graph optimization** | none. Gauge-revision semantics already frozen in `schema.py:97-111` for it `[Q]` | essential graph, `BlockSolver_7_3`, 20 iters `[Q]` | differentiable BA over patch graph | n/a | **MISSING — and vacuous until (2).** A tree has no cycle to distribute error around. |
| 11 | **Local bundle adjustment** | implemented, **measured at 0.00% improvement** at 16/32/104 keyframes `[Q, repo]`. Cause is arithmetic: **66.1% of landmarks at HEAD are seen by exactly 2 views** `[M-SYN]` | refuses to run with no fixed keyframes `[Q]` | differentiable BA is the core | n/a | **IMPLEMENTED, STARVED.** Not a solver problem. Do not touch it until (2) lands. |
| 12 | **Global BA** | none | 20-iteration full BA after init `[Q]` | n/a | global aligner OOMs past ~30–40 images on 12 GB `[M-L3/E-L3]` | **MISSING, and correctly deprioritised.** Same starvation as (11). |
| 13 | **Learned tracking** | none | none | DPVO: 1 map, 1848 poses, 0 resets, 16.93 fps, 682 MiB — *one stride-1 run, not repeated* `[M-L2]`. The 12–38% run-to-run disagreement is a separate set of stride-2 repeats over 698–924 frames `[M-L2]` | none | **MISSING BY CHOICE, and the choice is correct.** §7 |
| 14 | **Learned depth / geometry** | none. MiDaS refused: Spearman 0.074 `[Q]` | none | dense inverse depth (DROID) | pointmap in a shared frame; genuinely a different estimand | **MISSING.** Justified only as an offline verifier, behind a gate we do not yet have. §5.1 |
| 15 | **Wide-baseline matching** | ORB+Lowe. Holds up better than expected: at frame gap 13 still 167 matches / 100 E-inliers `[M-L2]` | ORB + BoW-guided search | learned correlation | strongest measured; LoFTR removes correspondence failure at wide gaps (25.0%→2.3% at gap 13) `[M-L2]` | **IMPLEMENTED ADEQUATELY.** Correspondence is 10.4% of failures; a perfect matcher recovers ≤22 of 212 pairs `[M-L2]` |
| 16 | **Background refinement thread** | none, but `--rebuild-every` and the deferred `build()` are the seam for it `[Q]` | LocalMapping + LoopClosing threads | `run_backend` thread | MASt3R best fits here (≈1.2 s/directed pass) `[M-L3]` | **MISSING, and it is the right home for anything expensive.** |
| 17 | **Failure recovery** | reset tracker, increment segment, continue. 94% of breaks were on frames the tracker could still follow `[Q, prior lane]` — partly addressed at HEAD by `6e60f76` (51 → 33 segments) | 3-tier ladder, old map kept forever `[Q]` | no failure state exists | n/a | **MISSING the ladder; the single-frame verdict is already partly fixed at HEAD.** |

**Tally: 11 architecturally MISSING, 3 implemented-and-starved, 2 adequate, 1
missing by correct choice.** The brief's hypothesis — "our map architecture is
primitive, not our frontend" — is **confirmed**, and more strongly than the
lanes argued, because review also found the frontend to be *better* than the
lanes credited (§5.1.4).

---

## 2. The one measurement that decides the shape of the work

At HEAD, on the canonical capture, with **the production ORB detector, the
production Lowe matcher, and production's own thresholds — changing only which
pairs are asked** `[M-SYN, census_at_head.py]`.

**Revision 1 of this document led with a 42× figure. That was mostly a
population artefact and the adversarial review was right to strike it.** The
honest comparison is like-for-like, over the same keyframes:

| comparison | production | all-pairs oracle | ratio |
|---|---|---|---|
| **like-for-like: both over the same 72 geometry-bearing keyframes (2,556 pairs)** | **189 edges (7.4%)** | **486 edges (19.0%)** | **2.6×** |
| median covisibility degree over those same 72 keyframes | **5.5** | **14.0** | 2.5× |
| *rev 1's framing:* production edges (72 kf, shared **landmarks**) vs census edges (448 kf, verified **matches**) | 189 | 8,021 | *42×* |

The missing ~16× is two things, neither of which widening `_extend` buys:
**376 keyframes that carry no triangulated point at all** and therefore
contribute zero production edges *by definition*, and a **unit change** from
shared landmarks to verified matches. Lane 1's own harness header calls its
match-based weight "an upper bound on the real weight". Use 2.6×.

Two figures are unaffected and they are the ones that carry the argument:

| | production | available |
|---|---|---|
| **cross-segment edges** | **0** | **4,820** |
| **landmarks seen by exactly 2 views** | **66.1%** | — |

The cross-segment zero is structural, not a ratio — segments are not
representable as connected, so no threshold produces one. And the 66.1% is why
bundle adjustment measured 0.00%: a landmark seen by two views is exactly
determined, so BA can satisfy both rays perfectly wherever the cameras are.
Two-thirds of the map is invisible to BA **by construction**. It was never a
solver failure and adding `pycolmap` would not have changed it.

**2.6× on edges, ∞ on cross-segment links, and a two-view landmark share that
must fall — that is the case, and it is smaller than revision 1 claimed.** It
is still the same frontend, asked more questions.

---

## 3. Staged roadmap

Each stage has a **stop/go** criterion. If a stage fails it, **stop** — do not
proceed to the next one. The stages are a dependency chain, not a menu: the
0.00% BA result is what happens when you take them out of order.

Effort figures are `[E]`, by the method named. They are for an engineer already
inside this codebase.

### Stage 0 — Re-baseline (BLOCKING, half a day)

Nothing below can be measured against a stale reference.

- Replay the canonical capture and the seven other motion-bearing captures at
  HEAD. Record segments, keyframes, **poses_solved and points together** —
  `1272b09` exists precisely because segment count alone lied.
- Regenerate the persisted canonical session. The current one ran
  2026-08-25 17:59:00–18:01:34 and predates **`6e60f76`** (22:32:57, "the
  tracker was losing reach, not losing the image" — the commit that actually
  took this walk 51 → 33), `2a90f49`, `85d94a2`, `1272b09` and **`4136b2f`**
  (which fills in `support_views`) `[M-SYN, git log]`.
- Re-derive Lane 1's covisibility census on the new session (109.5 s on 12
  workers `[M-SYN]`; script provided).

**Effort `[E]`: 0.5 day.** Method: I did the replay and the census in this
review; the cost is measured, not guessed.
**Stop/go:** none — this is unconditional.
**Known result already:** 448 kf / 33 seg / 61 solved / 8,333 pts, and the
replay is bit-for-bit reproducible `[M-SYN]`.

### Stage 1 — Covisibility: widen `_extend` from 1 reference to 3 (~1 week)

The highest-value change in the programme, and the cheapest.

- Match each new keyframe against the previous **3** accepted keyframes, not
  only the previous one. Accumulate the `observed` dict across all three.
- Copy ORB-SLAM3's **never-disconnect fallback** as a *policy*, reimplemented:
  if no reference clears the threshold, link the single best one anyway
  `[Q, KeyFrame.cc:443-447]`. This is what keeps the graph connected and is a
  genuinely good idea.
- Persist the resulting adjacency. `support.json` already carries
  `[segment, frame, feature, point]`, so the covisibility weight is a query
  over an existing table, not a new measurement `[M-L1]`.
- **Add the reverse-direction match (reciprocity) at the same time.** One extra
  `knnMatch`, ~0.9 ms/pair/core `[E-L1]`. It rejects 100% of geometry-less
  match traps while keeping 69.8% of good edges, AUC 0.985 `[M-L1]`.

**Why 3 and not 5 or "all pairs":** per pair asked, the useful-edge yield is
57.9% at gap 1, 49.4% at gaps 2–5, 29.8% at 6–20, 9.2% at 21–100, 2.4% beyond
`[M-SYN]`. Production's own gate accepts 50.4 / 49.5 / 47.8% at keyframe gaps
1 / 2 / 3 and then decays to 36.5% at gap 5 `[M-SYN]`. Gaps 1–3 are flat and
cheap; past that you are paying more matches for fewer edges, and you should be
using retrieval (Stage 3) instead of a wider sweep.

**Effort `[E]`: ~1 week, ~150–250 LOC.** Revision 1 said "1–2 days ... the
change is calling it three times and accumulating." The adversarial review read
the code and showed that is too optimistic; I checked and it is right. Widening
`_extend` from one reference to three touches at least: `_Chain.__slots__`
(`previous_features` is a *single* slot); `_Chain.forget_before`, whose
docstring justifies its pruning key on the ground that "`_extend()` reads
exactly one key shape" and carries a memory measurement (26.1 MB → 0.15 MB) the
change invalidates; the `claimed` de-duplication in `_extend`, which today
cannot see two *different* landmarks claim the same current feature from two
different references and has no resolution rule for when it can;
`_triangulate_new`, which takes exactly one previous pose and one projection
matrix; the `base + offset` support-block bookkeeping duplicated across
`estimate_window()` and the live path, where double-counting a re-observation
would silently corrupt `support.json`; and the live/rebuild equivalence test
the `_Chain` docstring names as the guard that the backend is still
forward-only. **Budget a week and write the de-duplication rule down before
touching anything.**

**Stop/go — all four must hold on the Stage 0 baseline:**
- **landmarks seen by ≥3 views rises from 33.9% `[M-SYN]` to >50%** — this is
  the primary criterion, because landmark multiplicity is the quantity BA
  actually consumes;
- **median covisibility degree over the geometry-bearing population rises from
  5.5 toward the measured oracle ceiling of 14.0, and clears 9.0** `[M-SYN]`.
  *Revision 1 said ">15". That was unmeetable:* restricted to the same 72
  keyframes production uses, an all-pairs oracle that asks *every* pair reaches
  only **14.0**, and Lane 1's match-based weight is an upper bound on the
  landmark-based weight production would compute. A criterion above the oracle
  halts the roadmap even when the stage succeeds. 9.0 is ~64% of the measured
  ceiling; re-derive it against the Stage 0 census rather than trusting this
  number;
- **`poses_solved` and `points` do not fall**;
- the run stays bit-for-bit reproducible across two fresh processes.

If the first two hold and the third does not, you have re-run `1272b09`'s
mistake — shipping on a graph statistic while the reconstruction shrank. Stop
and investigate before proceeding.

### Stage 2 — Refuse what should never have been admitted (0.5 day)

Three defects, one root cause, discovered separately by three parties and
unified here `[M-SYN]`:

- **20 of the 24 keyframes with ≤100 ORB features are >40% redaction fill**,
  median black fraction 0.747. Featureless-keyframe admission *is* the
  redaction blackout problem — they are not two issues.
- That single population causes: (a) BoW retrieval collapse — a zero vector is
  a universal attractor scoring 1.00 against another zero vector, which took
  Recall@1 to 0.0% until gated `[M-L1]`; (b) the OpenCV-5 uninitialised-mask
  defect, whose trigger is a 5-feature keyframe producing 242 Lowe matches on 3
  distinct locations `[M-L1, reproduced M-LEAD]`; (c) MASt3R producing 4–25×
  *fewer* matches than ORB on those frames `[M-L3]`.

Actions:
1. **Gate keyframe admission on usable feature count.** ORB-SLAM3 uses >100 for
   initialisation `[Q]`; measure our own operating point, do not transcribe it.
2. **Fix `geometry.py:120-123`.** Check the model before trusting the mask.
   One line per call site. Severity today is **latent** — but not because
   nothing reads `r_H`; it is on the wire (§5.1.5). It is latent because the
   *values* are currently benign: on the HEAD replay only 23 of 415 edges carry
   a non-null `r_h`, all in 0.44–0.51, none anomalous, and bit-identical across
   two fresh processes `[QUOTED, adversarial review]`. It earns its place here
   only because it is *free* to fix while you are already in that file, and
   because it is non-deterministic (30/40 fresh processes returned a corrupt
   mask, sums to 32,880 on a 242-element binary mask `[M-LEAD]`; 37/40
   `[M-L1]`; 34/40 `[QUOTED, adversarial review]`) and would be miserable to
   debug later. **Do not oversell it and do not schedule a sprint for it.**
3. **Stop populating `r_H`, and document it as dead — but do NOT delete the
   field in this stage.** See §5.1.5: it is not merely a weak low-parallax
   detector, it is *provably useless* in the one regime it exists for.
   Revision 1 called it "computed and never consumed" and priced removal at
   zero. **That was wrong.** `r_h` is computed at `classical.py:498` and
   `unposed.py:175`, attached to the edge at `engine.py:477`, serialised at
   `records.py:554,572,592`, written to `edges.jsonl` on every run, and is a
   named field of **`KeyframeEdge` in `docs/agent-handoffs/TOWER-TO-IOS.md:374`**
   `[M-SYN, source]`. Under `CLAUDE.md` that is shared protocol truth: removing
   it is a cross-subsystem contract change with an iOS-side consumer question,
   not a line deletion, and it must not be smuggled into a half-day stage.
   Do this instead: keep the field, keep emitting `null`, add a docstring line
   recording the measurement in §5.1.5, and raise the field's removal as a
   separate contract item.

**Effort `[E]`: 0.5 day, ~30 LOC** for items 1 and 2, **plus a separate
contract change of unknown size** for item 3's field removal, which is not
scheduled here. Method: two one-to-five-line changes plus one threshold sweep.
**Stop/go:** BoW precision@5 must reach ≥90% with the admission gate in place
(Lane 1 measured 70.8% → 91.5% `[M-L1]`); replay `poses_solved` must not fall.

### Stage 3 — Keyframe database and place recognition (1 week)

Only now is retrieval worth having, because only now is there a graph to
attach the retrieved candidates to.

- In-domain vocabulary tree: k=10, L=4, 10,000 words, trained on 120,000 of our
  own descriptors in **10.7 s** `[M-L1]`. **Do not ship ORB-SLAM3's 145 MB
  `ORBvoc.txt`** — it is a 42 MB compressed GPLv3 asset with no separate
  licence, and a landmine independent of the code `[M-L1]`.
- Inverted index, tf-idf, DBoW2's L1 similarity. Reimplemented from the papers
  (Nistér & Stewenius 2006; Gálvez-López & Tardós 2012), not from DBoW2 source.
- **One database spanning everything.** ORB-SLAM3's single global
  `mpKeyFrameDB` is the entire mechanism by which separated maps ever find each
  other `[Q, Atlas.h:159]`. This is the one Atlas idea worth copying.

Measured on the stale session `[M-L1]`: Recall@10 on long-gap revisits 73.0%,
Recall@50 cross-segment 90.1%, precision@5 91.5%, 13.9 ms/keyframe to assign
words (pure Python, trivially optimisable), 30 µs/pair to score.

**Effort `[E]`: 1 week, ~120 LOC production subset.** Method: Lane 1 wrote and
validated 256 LOC *including* the trainer and the whole evaluation harness
inside one lane; the runtime path is about half.
**Stop/go, and read the caveat before using it:** re-measure Recall@K at HEAD
(Stage 0) with the Stage 2 admission gate. Require **Recall@10 ≥ 60% on
long-gap revisits at precision@5 ≥ 85%**. If retrieval does not clear that on
the re-baselined session, stop — loop closure (Stage 5) is not affordable
without it, and brute force is quadratic.

**This gate is circular and you must read it as such.** Lane 1's harness is
explicit (`bow_retrieval.py:24-25`): its ground truth *is* the census's own
geometrically verified edges — "self-consistency, not external ground truth."
Retrieval is being bought to surface candidates brute-force ORB *cannot* find,
and it is being scored against ORB's own verified edges, so it can neither pass
nor fail for the right reason. Compounding it: the vocabulary is trained
in-domain on the corpus it is evaluated on, and the corpus is one apartment, so
a false-positive rate is unmeasurable here (§5.6). **Treat the number as
"retrieval agrees with brute force cheaply enough to replace it", which is a
real and sufficient property for Stage 3's actual job, and not as an accuracy
claim.** The accuracy question needs a second environment.

### Stage 4 — Pose graph optimization over the covisibility graph (1–2 weeks)

Now, and not before, there are cycles.

- Sim(3) pose graph. `pyceres` 2.6 has a genuine `cp312-cp312-win_amd64` wheel,
  8.5 MB, numpy-only dependency, **Apache-2.0** `[Q, licensing findings]` — note
  revision 1 of this document said BSD-3 in this line and Apache-2.0 in §4.4;
  Apache-2.0 is correct, and Lane 1 had conflated the Ceres *core*'s BSD-3 with
  the Python binding. Both are permissive, so there is no exposure — but see
  the **open question** below. Alternatives: `scipy.optimize` (BSD-3), or a
  hand-rolled Gauss-Newton. Prior in-repo work established numpy + cv2 suffice
  for our Sim(3) `[Q]`.
- **OPEN QUESTION, close it before Stage 4 starts, not during.** This
  document's entire Ceres risk model is about *build flags* —
  `WITH_SUITESPARSE=ON` makes a Ceres build GPL (§4.4) — while the
  recommendation is a *prebuilt wheel*. **Nobody established what the
  `pyceres` 2.6 wheel actually links against.** If it bundles a
  SuiteSparse-enabled Ceres, the permissive licence on the binding does not
  save you. Inspect the wheel's linkage, or build Ceres yourself with the flag
  off, or use `scipy`.
- **Leave scale free.** ORB-SLAM3 constructs its loop closer with
  `bFixScale = (mSensor != MONOCULAR)` `[Q, System.cc:213]` for exactly this
  reason. What PGO buys a monocular system is redistribution of scale *drift*
  around a cycle. It does not fix the gauge.

**Effort `[E]`: 1–2 weeks, ~200–300 LOC.** Method: Lane 1's estimate; the
residual and Jacobian for a Sim(3) pose graph are standard and small, the work
is in plumbing and in the gauge-revision bookkeeping `schema.py` already
specifies.
**Stop/go — replaced.** Revision 1 asked for "a measurable, reproducible
reduction in loop-closure residual" and "measure drift before and after". Both
were unusable and the adversarial review was right to reject them: loop closure
is Stage 5, so at Stage 4 there are no closures and no closure residual; and
drift has **no ground truth on this corpus**, which §0.1 of this same document
says in its first sentence. That is exactly the kind of criterion that can only
be "evaluated" by looking at a number and deciding it seems better.

Use these three instead. All are self-consistency measures — which is all this
corpus can support, and saying so is part of the criterion:
1. **Cycle-consistency residual.** Sum of squared relative-pose residuals
   around covisibility cycles falls by **≥30%**. Well posed at Stage 4 because
   the cycles come from covisibility, not from closures, and computable with no
   external reference.
2. **Held-out-edge prediction.** Withhold a random 10% of covisibility edges
   from the optimisation and measure the relative pose the optimised graph
   predicts for them against the pose those edges independently measure.
   Require the median discrepancy to **fall**. This is the closest thing to a
   generalisation test the corpus permits.
3. **Bit-for-bit reproducibility survives**, and `poses_solved` / `points` do
   not fall.

If PGO improves nothing on (1) and (2), that is a real answer — the graph still
has no cycles and you should return to Stage 1 rather than reach for a bigger
solver. **This is where the 0.00% BA result would have been caught if anyone
had set a stop/go criterion.**

### Stage 5 — Non-destructive segment registration and loop closure — **CONDITIONAL, NOT YET FUNDABLE** (2–3 weeks once unblocked)

**Do not schedule this stage yet.** Revision 1 scheduled it behind a validity
gate that, on re-examination of this review's own data, **does not clear the
0%-on-the-null bar this same stage makes mandatory** (§5.1.3). The blocking
finding, stated plainly:

> **No gate measured anywhere in this programme both refuses 100% of
> zero-baseline pairs and accepts a single one of this corpus's real
> positives.** The only configuration that reaches 0% on the null accepts
> **0 of 10** real pairs, including the oracle `[M-SYN]`. On this footage a
> gate strict enough to be safe currently admits nothing at all.

That is not a reason to ship a looser gate. It is a reason not to write
cross-segment registration into a map yet. **Entry condition for Stage 5 —
one of:**

- **(a) capture footage with genuine translation** (a deliberate walk with
  lateral motion, ideally in a second environment) and re-derive a gate on it
  that clears 0% on a null built from *that* footage, at a stated recall; or
- **(b) demonstrate that Stages 1–4 have produced segments with enough internal
  geometry that classical PnP registration is corroborated by an independent
  reverse solve** — the route the prior in-repo lane already proved once
  end-to-end (419 correspondences, 1.50 px, reverse agreement 0.3% `[Q]`) — in
  which case the pointmap verifier is not needed for this stage at all; or
- **(c) find a validity statistic that separates, and measure it.** §5.1.7
  lists what has been tried and what each one costs. None currently works, and
  saying so is the finding.

Note that Stages 1–4 deliver value **without** cross-segment registration, and
that (b) is a plausible outcome of doing them: 22 of 33 segments currently hold
no geometry at all `[M-SYN]`, and the usual reason a link cannot be registered
is that there is nothing on either end to register, not that the link is
unverified.

Design notes for when it is unblocked:

- The persistence scaffolding **already exists and is inert**: every emitted
  segment carries `registered:False` and `transform_to_world:None`; the gauge
  revision counter is persisted; `schema.py:97-111` already froze the
  distinction that a loop closure moves *part* of the world and must never be
  composed forward `[Q]`. Price this as *filling in declared structure*, not as
  redesigning persistence.
- **Registration must be non-destructive**: a segment's own geometry does not
  move; only `transform_to_world` is set. A bad merge is then reversible. This
  is a real safety property and it is better than ORB-SLAM3's design.
- Route is **PnP, not Umeyama** — 10–100× more constraints `[Q, prior lane]`.
- **The guard ladder is the hard part, not the Sim(3), and it is the part that
  does not yet exist.** See §5.1.7 for everything that has been tried and what
  each term costs in recall.

**Effort `[E]`: 2–3 weeks, ~320 LOC** (~200 verification + ~120 RANSAC Sim(3))
**once the entry condition is met** — and that estimate is lead-steered (§5.5)
and excludes the cost of obtaining the entry condition, which for route (a) is
a capture campaign, not engineering time.
**Stop/go — unchanged and non-negotiable:** the chosen gate must be measured on
a **pure-rotation null constructed from the target footage**, must accept
**0%** of it, **and** must accept a stated, non-zero fraction of pairs there is
independent reason to believe are true positives. **Both halves.** Revision 1
stated only the first, which is exactly how it came to propose a gate that
satisfies it vacuously. This review's harness (`slam_synthesis/`) builds the
null in minutes and is reusable unchanged. A wrong Sim(3) reprojects at 1.62 px
median while being wrong by 3.2× in scale `[Q, prior lane]`; reprojection error
is not a safety check.

### Stage 6 (OPTIONAL, parallel, benchmark-only) — pointmap verifier

Only if Stage 5's candidate list still leaves valuable links unmade, and only
as an offline background pass.

- **Not the Naver line.** DUSt3R / MASt3R / MASt3R-SLAM are CC BY-NC-SA in code
  *and* carry stacked non-commercial dataset terms in the weights, including
  Niantic Map-Free's clause binding "dataset-derived materials" `[Q-L3]`. The
  poison starts in the CroCo v2 backbone every checkpoint descends from. No
  commercial licence is offered. **Benchmark only, forever.**
- The two shippable candidates, **neither measured by anyone in this
  programme**: `facebook/VGGT-1B-Commercial` (gated, commercial permitted
  except military/ITAR `[Q-L3]`) and **`facebook/map-anything-apache`**
  (Apache 2.0 code *and* weights, six permissively-licensed datasets
  `[Q-L3]`). MapAnything is the citation to start from.
- Use the **PnP-on-pointmap route, never the essential-matrix route** (§5.1.3).
  Revision 1 added "and gate on baseline-over-depth"; **that instruction is
  withdrawn** — baseline-over-depth has a measured 2.6% false-positive rate at
  the proposed threshold and rejects the only classically-corroborated positive
  (§5.1.3).
- **What this stage is now for.** Not "adopt a pointmap backend". It is a
  *measurement*: does a shippable checkpoint, on footage with genuine
  translation, produce a statistic that separates? Lane 3 answered that
  question for an unshippable checkpoint on footage with almost no translation,
  and the answer was no. Both variables need changing before it is worth
  re-asking.

**Effort `[E]`: 1–2 weeks to a measured yes/no**, reusing Lane 3's harness
unchanged. Method: Lane 3 built the harness; substituting a checkpoint is a
model-loader change.
**Stop/go, both halves:** must clear a pure-rotation null built from the target
footage at **0% acceptance**, *and* accept a stated non-zero fraction of
believed-true positives, on the shippable checkpoint, before it may propose a
single map edge. **On the current corpus with the measured checkpoint, no
configuration satisfies both** `[M-SYN]`.

### Total

**`[E]` ~4–6 weeks of one engineer to the end of Stage 4**, which is as far as
the evidence currently funds. Stage 5 adds 2–3 weeks *after* its entry
condition is met, and meeting that condition may require a capture campaign
rather than engineering time. Total new code ~900–1,200 LOC against 5,511
existing — 16.3–21.8% growth, i.e. "roughly 20%" `[M-SYN, wc -l]`.

**Two honest caveats on every figure in this section.** First, they are all
`[E]`. Second — and the adversarial review is right to press this — the
*estimates* are the part of this document the lead's supplement steered
("Price Atlas-style multi-map adoption using the EXISTING scaffolding, not from
scratch. Any cost estimate that ignores this will be too high."). §5.5 defends
the *measurements* as independent and that defence holds; it does not extend to
the costings, which have no measurement behind them. Stage 1 already had to be
re-priced from 1–2 days to a week for exactly this reason. **Treat every effort
figure as optimistic until an engineer has read the code path.**

Stages 0–2 are the first ~1.5 weeks and deliver most of the measurable
change.

---

## 4. Evidence

### 4.1 The baseline is stale — and the conclusion survives anyway

`[M-SYN]`. The persisted canonical session's `keyframes.jsonl` and `images/`
were written **2026-08-25 17:59:00–18:01:34**, at which point HEAD was
`3998e5a` (17:55:17). Only the *derived* geometry was rebuilt later, on
2026-08-26 00:12. Every lane and the shared brief inherited the pre-fix
session.

Replaying the identical 1,848 frames at HEAD, twice, in fresh processes:

| | quoted everywhere | HEAD `[M-SYN]` |
|---|---|---|
| keyframes | 457 | **448** |
| segments | **51** | **33** |
| solved poses | 94 | 61 |
| points | 12,023 | 8,333 |
| rejections: insufficient_motion / blurred / tracking_lost / tracking_degraded | 670 / 639 / 50 / 32 | 694 / 639 / **32** / **35** |

**Which commit did it — revision 1 named the wrong ones.** `[M-SYN, git log]`,
all after the session and before the replay:

| commit | time | effect on this walk |
|---|---|---|
| **`6e60f76`** "the tracker was losing reach, not losing the image" | 22:32:57 | **51 → 33.** This is the one. |
| `2a90f49` "retract a confounded claim…" | 22:48:52 | test/claim retraction |
| `85d94a2` "a break is permanent…" | 23:09:01 | 33 → 29, per its own body |
| `1272b09` "grace ships disabled…" | 23:31:41 | **reverts that**, back to 33 |
| `4136b2f` "record which feature… made each landmark" | 2026-08-26 00:02:15 | fills in `support_views` |

So it was **one** commit, `6e60f76`, and it is neither of the two revision 1
named. **Fragmentation is already 35% better than the number this programme was
chartered to attack**, and the mechanism is the stale-reference fix the
fragmentation lane predicted — which is a nice independent confirmation of that
lane, and was mis-attributed here until the adversarial review caught it.

Re-running Lane 1's census unchanged on the HEAD replay `[M-SYN,
census_at_head.py, 109.5 s on 12 workers]`:

- 8,021 covisibility edges of 100,128 pairs (8.01%), 4,820 cross-segment;
- 6,750 carry parallax ≥0.5°;
- median covisibility degree 36, 14 isolated keyframes;
- **all 33 segments form ONE connected component** under useful cross-segment
  edges (Lane 1 got 3 components of 51 on the stale session).

Against production at HEAD `[M-SYN, from the replay's own `support.json`]`:
189 covisibility edges, median degree 5.5 over 72 geometry-bearing keyframes,
**0 cross-segment**, and **66.1% of 8,333 landmarks seen by exactly 2 views**
(Lane 1: 67.2% on the stale session — essentially unchanged).

**So: the numbers moved, the architecture finding did not.** That is the
correct outcome, and it is worth more than either half alone.

### 4.2 Our pipeline is bit-for-bit reproducible

`[M-SYN]`. Two fresh processes, identical frames, identical flags:
**448 / 448 pose records identical** after stripping the session id, and
**8,333 / 8,333 points identical to max |Δp| = 0.000e+00.**

This matters because the repo's own source warns that
`findEssentialMat(USAC_MAGSAC)` and `solvePnPRansac(SQPNP)` "are not seeded"
`[Q, classical.py:606]`, and records a test's number moving 1.32% → 1.62% on a
different OpenCV build. So determinism is *build-dependent and not guaranteed
by contract* — but on this build, sequentially, it holds exactly.

Against DPVO: 12–38% of trajectory extent between runs, on four different
captures, with internal scale varying 7× across three runs of the same 924
frames `[M-L2]`.

**We pass the strongest available correctness proxy. The most exciting
alternative fails it.** That single comparison is most of the case against
learned VO.

### 4.3 Latency, memory and resource envelope

Everything below is on the RTX 5070 12 GB / Ryzen host. Capture rate is
**11.99 fps**, so the live budget is ~83 ms/frame.

| component | cost | source |
|---|---|---|
| our frontend (Shi-Tomasi + LK) | ~5 ms/frame | `[Q, repo]` |
| our ORB detect+describe | ~3.9 ms median | `[Q, repo]` |
| **whole engine, `observe()`** | **12.87 / 12.06 ms per frame** over 1,848 frames | `[M-SYN]` |
| our full derived build | 0.32 s | `[M-SYN]` |
| all-pairs ORB census, 448 kf / 100,128 pairs | 109.5 s on 12 CPU workers | `[M-SYN]` |
| reciprocity (reverse knnMatch) | ~0.9 ms/pair/core | `[E-L1]` |
| BoW word assignment | 13.9 ms/kf (pure Python), 30 µs/pair to score | `[M-L1]` |
| in-domain vocabulary training | 10.7 s, 10k words | `[M-L1]` |
| DPVO whole system | 16.93 fps, **682 MiB peak**, flat over 1,848 frames — **one stride-1 run, not repeated**; the 12–38% reproducibility figure is a separate set of stride-2 repeats over 698–924 frames | `[M-L2]` |
| DPVO frontend only | 3.09 ms → 323 fps, 39.9 MiB (AMP) | `[M-L2]` |
| LoFTR | 93.3 ms/pair — **not real-time at 12 fps** | `[M-L2]` |
| DISK+LightGlue | 104.5 ms/pair | `[M-L2]` |
| MASt3R symmetric pair | 2.2–4.2 s uncontended, **3,019 MiB** | `[M-L3]` |
| DUSt3R symmetric pair | 0.35–0.68 s uncontended, **2,873 MiB** | `[M-L3]` |
| VGGT-1B, 2 frames | 1.08 s, **7,389 MiB** — 60% of the card for two images | `[M-L3]` |
| DUSt3R/MASt3R global aligner | 4.50 MiB per directed edge; 457 keyframes ⇒ **915 GiB** | `[M-L3]` exact constant, `[E-L3]` extrapolation |

**Resource conclusions.**
- Stages 0–5 add **zero GPU dependency** and are dominated by CPU matching that
  already runs at ~0.9 ms/pair/core. Widening `_extend` from 1 to 3 roughly
  triples the backend's matching cost — from ~4 ms to ~12 ms per keyframe
  `[E: 3× the measured 3.9 ms ORB match path]` — against a 12.9 ms/frame
  engine budget on frames that are keyframes only ~24% of the time. **It fits.**
- Stage 3's retrieval at 13.9 ms/keyframe in unoptimised pure Python is already
  under budget and is trivially improvable.
- Any pointmap model is **offline-only**: 2.4 s/pair against an 83 ms budget.
  The affordable workloads are the 102 strongest segment-pair candidates
  (4.1 min) or all 442 above `MIN_INLIERS` (17.7 min); the complete
  104,196-pair graph is 69 days `[E-L3, measured rate × measured counts]`.
- **A 12 GB card is not the constraint for the classical roadmap and is a hard
  constraint for the learned one.** VGGT's ceiling here is ~20 frames, not 100
  `[M-L3/E-L3]`, and on Windows the WDDM driver spills to system memory instead
  of raising a clean `OutOfMemoryError`, so a capacity plan that assumes a fast
  failure will not get one `[M-L3]`.

### 4.4 Licensing, in one paragraph each

**Nothing in Stages 0–5 has a licensing problem, with one open question.**
Every component role has a permissive route: vocabulary index (FBoW MIT, DBoW3
BSD-variant, or our own 120 LOC), optimiser (Ceres BSD-3 in its *default*
build, **`pyceres` Apache-2.0** — Lane 1 said BSD-3, conflating the Ceres core
with the Python binding; the lead's primary-source licensing findings say
Apache-2.0 and that is the value to use — scipy BSD-3, PyPose Apache-2.0),
Sim(3)/absolute orientation (Umeyama 1991 and Horn 1987, both patent-free with
high confidence — **not a formal FTO clearance**), features (ORB, patent-free
by design, OpenCV main modules).

**The open question, which must be closed before Stage 4 rather than during
it:** the Ceres risk below is about *build flags*, while the recommendation is
a *prebuilt wheel*. Nobody in this programme established what the `pyceres` 2.6
wheel links against. A permissive licence on the binding does not help if the
wheel bundles a SuiteSparse-enabled Ceres. Inspect the linkage, build Ceres
yourself with the flag off, or use `scipy`.

**The traps worth writing on a wall** `[Q-L1, Q-lead licensing]`:
- ORB-SLAM2/3, DSO, LDSO are **GPLv3**, and `ORBvoc.txt.tar.gz` inherits it —
  a team that cleanly reimplements ORB-SLAM ideas can still poison itself by
  shipping that 42 MB vocabulary file.
- **SuperPoint/SuperGlue** are noncommercial-research-only, covering weights
  *and* the inference file. LightGlue itself is Apache-2.0 including weights;
  pair it with **DISK or ALIKED**, never SuperPoint.
- **SuiteSparse is licensed per module**, and the fast parts (CHOLMOD
  Supernodal, SPQR) are the GPL parts. Ceres defaults `WITH_SUITESPARSE=OFF`
  and warns; **GTSAM silently enables CHOLMOD if it finds one** with no flag
  and no warning. If GTSAM is ever adopted, block CHOLMOD from discovery.
- `Nanne/pytorch-NetVlad` has **no LICENSE file** — all rights reserved.
- **MegaLoc** is MIT but its author's FAQ says the training data "come from
  sources that we are not allowed to redistribute". Permissive licence,
  disclosed-unclean corpus. Legal's call, not engineering's.
- Two of three SLAM-sounding PyPI names (`pyslam`, `pypangolin`) are unrelated
  packages `[M-L1]`. Real supply-chain caution.

**The whole Naver pointmap line cannot ship.** VGGT-1B-Commercial (gated) and
MapAnything-apache are the only routes, and neither has been measured.

---

## 5. Tension resolutions

### 5.1 TENSION 1 — Lane 3's gate does not survive Lane 2's null. It fails badly.

**The decisive experiment had not been run. I ran it.**

#### 5.1.1 What was run

`slam_synthesis/build_rotation_null_manifest.py` reproduces Lane 2's
construction exactly — same capture, same seed `20260826`, same 400-frame
sample, same sharpness ranking, same 40 sharpest frames, same rotation
magnitudes split across yaw/pitch/roll, same q85 re-JPEG — and writes the pairs
to disk in the manifest format **Lane 3's own harness already consumes**. Then
`slam_learned_3d/mast3r_pairs.py` was run over them **unmodified**.

A rotation magnitude of **0.0°** was added as a second, stronger null: A warped
by the *identity* homography, re-encoded at JPEG q85 and decoded — so it is A
against a recompressed copy of A, not A against A. True rotation zero *and*
true translation zero, with one extra JPEG generation as the only difference.
That group behaves unlike the others and the difference is worth knowing:
median `recip_R` is **26.67°** there against 0.035–0.09° at every non-zero
angle `[M-SYN]`, because with literally nothing to estimate the essential
matrix decomposition flips branches freely. **The headline does not depend on
it — excluding the 0.0° group entirely, the false-acceptance rate *rises* to
108/160 = 67.5%** `[M-SYN, reproduced independently by the adversarial
review]`.

200 pairs. True translation is **exactly zero by construction**. Every
acceptance is a false positive with no interpretive room.

#### 5.1.2 Result — the gate is not merely fooled, it is confidently fooled

`[M-SYN, analyse_purerot_null.py]`

| | Lane 3's gate `recip_R<15° ∧ E-ratio>0.5` | + `recip_t_dir < 15°` |
|---|---|---|
| **all 200 zero-baseline pairs** | **123 accepted (61.5%)** | 10 accepted (5.0%) |
| 0.0° (identical images) | 15 / 40 | 1 / 40 |
| 0.5° | 29 / 40 | 4 / 40 |
| 1.2° (the corpus's median inter-frame rotation) | 26 / 40 | 2 / 40 |
| 2.5° | 26 / 40 | 2 / 40 |
| 5.0° | 27 / 40 | 1 / 40 |

Supporting statistics over the 200 `[M-SYN]`: **median `recip_R` = 0.05°**,
median E-inlier ratio **0.998**, and **95.5%** of pairs exceed the E-ratio
term. So the second term contributes almost nothing, and the first term does
worse than nothing:

> **Lane 3's best true positive, `seg0-45`, reciprocates at 1.20°. The median
> pair with exactly zero baseline reciprocates at 0.05°.** The gate does not
> merely fail to reject fabricated translations — it *ranks them above every
> genuine link in the corpus.* The statistic is anti-correlated with the thing
> it is being asked to certify.

The mechanism is exactly what Lane 2 predicted and Lane 3 could not have seen:
under pure rotation the rotation is identifiable and the translation is not, so
two independent solves agree on R to a rounding error while their translations
are unconstrained noise. **A rotation-reciprocity gate is structurally
incapable of detecting a fabricated translation. This is not a threshold
problem and no threshold fixes it.**

#### 5.1.3 The pointmap route is *better behaved*, and it is still not gateable

Lane 3 argued "the escape from pure-rotation degeneracy is the pointmap, not
the matcher." **Partly right — and revision 1 of this document then over-read
it into a threshold that does not hold. The adversarial review caught that, and
it is the single most consequential correction in this revision.**

Running Lane 3's DUSt3R harness (PnP on the pointmap — the `PairViewer` route)
over the identical 200 nulls `[M-SYN]`. Revision 1 reported the median and p90
of the baseline/depth column and **not the tail**, which is where the answer
was:

| statistic | pure-rotation nulls (true translation = 0), n = 194 with a value |
|---|---|
| `recip_R < 15°` | 192 / 200 (96%) — rotation is recovered, as expected |
| **`recip_t_dir < 15°`** | **0 / 200** |
| median baseline / scene depth | 0.0095 |
| p90 / p95 / **p99** | 0.0210 / 0.0279 / **0.1314** |
| **max** | **0.1352** |
| **fraction exceeding the 0.05 threshold revision 1 proposed** | **5 / 194 = 2.6%** |

**A gate at 0.05 therefore has a measured 2.6% false-positive rate on pairs
whose true translation is exactly zero, and this document's own Stage 5/6
stop/go demands 0%.** It fails its own test.

It is worse than that, because the threshold was fitted to a single point and
the surrounding data contradict it `[M-SYN]`:

| pair | what it is | baseline/depth, undistorted | baseline/depth, raw |
|---|---|---|---|
| `seg45-47` | the "blind" pair the 0.05 was drawn from | 0.0564 (passes) | **0.0469 (fails)** |
| **`seg4-5`** | **the oracle — the only pair with independent classical corroboration** (419 correspondences, reverse agreement 0.3%) | no pose returned | **0.0391 (fails)** |
| `seg0-0` | real pure rotation, a true negative | 0.0219 | 0.0141 |
| `seg0-1` | real pure rotation, a true negative | 0.0260 | 0.0054 |

The proposed gate **rejects the only corroborated positive**, **straddles the
pair it was fitted to** (passing undistorted, failing raw), and **accepts 2.6%
of the nulls**. Only **3 of 10** real pairs produced a baseline/depth value at
all, and two of those three are pure-rotation true negatives, so its recall is
essentially unmeasured.

**And the conjunction does not rescue it.** Requiring
`baseline/depth > 0.05 AND recip_t_dir < 15° AND recip_R < 15°` together
`[M-SYN]`:

| | accepted |
|---|---|
| 200 zero-baseline nulls | **0 (0.0%)** ✓ |
| 10 real pairs, undistorted | **0** |
| 10 real pairs, raw | **0** |

> **The only configuration measured in this programme that reaches 0% on the
> null also accepts nothing at all — including the oracle.** That is not a
> gate, it is a refusal. On this corpus there is no threshold on this statistic
> that separates the real positives from the null distribution.

**Corrections carried forward.** Revision 1's sentence "the discriminator is
baseline-over-depth, not reciprocity" is **struck**, as is §5.1.8's "the
sufficient guard is the pointmap baseline-over-depth floor". Stage 5 and
Stage 6 are made conditional (§3).

**What survives, and it is not nothing:**

1. **The pointmap route does not fabricate a large translation.** Median 0.95%
   of scene depth, which is close to the honest answer for a camera that did
   not move, against the essential-matrix route through the *same model's*
   matches returning a confident unit translation at a 0.998 inlier ratio. The
   degeneracy is inherited from `recoverPose`, not from the network. **Use PnP
   on the pointmap, never `findEssentialMat`, if a pointmap model is ever
   used.**
2. **Translation-direction reciprocity is a genuinely strong term** — 0/200 on
   the nulls through this route — and it is the term revision 1 was right about.
   It is just not sufficient on its own through the essential-matrix route
   (5.0% survive there, §5.1.2), and combining it with a magnitude term
   collapses recall to zero.
3. **The failure is a property of the corpus as much as of the method.** The
   real pairs sit inside the null's tail because the wearer barely translated.
   That is why Stage 5's entry condition is footage with genuine translation,
   not a better threshold.

#### 5.1.4 The correction nobody expected: our own gate scores 0.0%

Lane 2's headline — "ORB has a 14.4% false-positive rate under pure rotation" —
is a property of **Lane 2's transcription of the production criterion**, not of
the production criterion. `matcher_showdown.py:168-205` differs from
`backends/classical.py:434-515` in three ways, all of which matter under
degeneracy: it uses `cv2.RANSAC` instead of `USAC_MAGSAC`; it triangulates over
the **epipolar** inlier set where production triangulates over the set
`recoverPose` narrowed with its **cheirality** test; and it gates
`MIN_INLIER_RATIO` on the epipolar ratio where production gates it on the
**cheirality** ratio.

Both transcriptions, over the identical 200 zero-baseline pairs
`[M-SYN, production_gate_on_null.py]`:

| | false "solvable" on true-zero baseline | accepts on real consecutive keyframe pairs |
|---|---|---|
| Lane 2's transcription | **26 / 200 = 13.0%** | 42.3% |
| **production `classical.py`** | **0 / 200 = 0.0%** | **50.4%** |

*(13.0% vs Lane 2's published 14.4% confirms my transcription is faithful; and
on the geometry-less 212-pair subset my Lane-2 transcription reproduces its
34.9% to the decimal.)*

Production's refusal mix on the nulls: 108 few-inliers-after-cheirality, 61
low-cheirality-ratio, 31 low-parallax. **169 of 200 are refused before
parallax is even consulted.**

**Which of the three differences does the work?** The adversarial review ran the
2×2 this document asserted and did not run `[QUOTED from that review, and
consistent with my own refusal mix]`: `cv2.RANSAC` + epipolar inliers 13.0%
false / 42.5% real; `cv2.RANSAC` + **cheirality** inliers 1.5% / 46.3%;
MAGSAC + epipolar 11.0% / 48.5%; **MAGSAC + cheirality (production) 0.0% /
50.8%**. So **the cheirality inlier set does ~88% of the reduction and MAGSAC
finishes it.** The attribution stands and is now decomposed.

> **Production dominates where it matters — the null — and the advantage on
> real pairs holds only at keyframe gaps 1–3.** Revision 1 said "strictly
> dominates"; that is too strong and is corrected below.

**Two corrections to revision 1's framing, both from data this document
produced and under-reported.**

*(a) The real-pair advantage reverses past gap 3* `[M-SYN,
production_gate_on_real.json]`:

| keyframe gap | 1 | 2 | 3 | 5 | 10 | 20 |
|---|---|---|---|---|---|---|
| production accepts | **50.4%** | **49.5%** | **47.8%** | 36.5% (tied) | 28.6% | 16.3% |
| Lane 2's transcription | 42.3% | 46.2% | 43.8% | 36.5% | **31.3%** | **18.5%** |
| | ✓ | ✓ | ✓ | = | ✗ | ✗ |

And on the population the whole programme was chartered to attack — the 212
consecutive pairs inside geometry-less segments — **production accepts 33.96%
against the transcription's 34.91%: production is *lower*.** There is also no
ground truth on the real pairs, so accepting more of them is not by itself
evidence of being right. **The dominance is sound only on the null side, where
the answer is known.**

*(b) It is a baseline-magnitude floor, not a pure-rotation recogniser.*
Revision 1 called it "the best pure-rotation discriminator measured anywhere in
this programme." That oversells it. `classical.py:451-460` records that at
0.02–0.06 m baseline the cheirality ratio measures 0.001–0.098, and the same
file states plainly that "a real sideways strafe at a 4-6 cm baseline recovers
direction to within 2 degrees and is **still refused here**." It refuses by
*magnitude*, with a documented false-negative cost — its own source calls it "a
measurement of baseline over depth wearing another field's name", which is the
**same statistic** §5.1.3 just showed does not separate on this corpus. The
0.0% is real and valuable; the mechanism is a conservative floor, not
recognition.

Two consequences:
- **Strike** "ORB is 14.4% false-positive" as a statement about our system.
- Lane 2's comparative claim (LoFTR fooled 2.4× more often than ORB) is still
  informative *about matchers*, but says nothing about what would happen if
  LoFTR were dropped behind production's gate — which nobody measured. If a
  matcher swap is ever proposed, that is the measurement to demand.
- It also reframes the fragmentation itself: 32 (now 33) segments with no
  geometry are substantially the *correct* output of a gate doing its job on
  rotation-dominant footage. The fragmentation is the honest cost of a correct
  refusal, and the fix is more graph, not a looser gate.

#### 5.1.5 And r_H does not save anyone — measured, in the one regime it is for

ORB-SLAM3 uses `r_H` not as a low-parallax detector but as a **model selector
at initialisation**, i.e. precisely for the pure-rotation / planar case. Lane 1
measured it as a low-parallax detector (AUC 0.765) and said "don't gate". This
review measured it in ORB-SLAM3's own regime, on pairs known to be pure
rotation `[M-SYN, rh_on_null.py]`:

| | median r_H | p05 | p95 | fraction > 0.50 |
|---|---|---|---|---|
| **true-zero-baseline pairs (n=200)** | **0.4960** | 0.4914 | 0.5000 | **4.0%** |
| Lane 1's 8,989 real verified edges | 0.4348 | — | 0.4953 | 2.47% |

A gate at `r_H > 0.50` catches **4.0%** of pairs that are *definitionally* pure
rotation while discarding 2.47% of real edges. At 0.60 and above it catches
nothing.

The reason is structural: under pure rotation the homography fits every point
*and so does some fundamental matrix* — F is unidentifiable, not unfittable — so
the ratio saturates at ½. This confirms the repo docstring's "saturates at
0.471–0.499" from a completely new direction and makes it decisive.

**`r_H` should be documented as dead and stop being populated. There is no
future gate for it.**

**But it is not free to remove, and revision 1 said it was.** Revision 1 wrote
"`r_H` is computed and never consumed, so nothing a user sees is wrong."
**The first clause is false** `[M-SYN, source]`: it is computed at
`classical.py:498` and `unposed.py:175`, attached to the edge at
`engine.py:477`, serialised at `records.py:554,572,592`, written to
`edges.jsonl` on every run, and is a named field of **`KeyframeEdge` in
`docs/agent-handoffs/TOWER-TO-IOS.md:374`** — the Tower→iOS handoff, which
`CLAUDE.md` designates shared protocol truth. Removing the field is a
cross-subsystem contract change with an iOS-side consumer question, not a line
deletion.

**The severity conclusion is unchanged and was right for the wrong reason.**
The defect is latent because the *values* are benign, not because nothing reads
them: on the HEAD replay only 23 of 415 edges carry a non-null `r_h`, all in
0.44–0.51, none anomalous, and **bit-identical across two fresh processes**
`[QUOTED, adversarial review]`. The underlying OpenCV-5 defect is nonetheless
real and nondeterministic — 30/40 corrupt masks `[M-LEAD]`, 37/40 `[M-L1]`,
34/40 `[QUOTED, adversarial review]`, the spread itself being consistent with
the nondeterminism. Fix the mask read (one line per call site); stop populating
the field; raise field removal separately.

#### 5.1.6 What Lane 3's positive result is actually worth

Lane 3's headline — `seg6-30`: ORB found **zero** verified correspondences,
MASt3R found 323 matches, 308 surviving essential-matrix verification — is
**independently corroborated**. Lane 1's census, a completely separate harness,
scored all 100 keyframe pairs between those segments and found a maximum of 13
Lowe matches, 7 F-inliers and **0 essential-matrix inliers** `[M-SYN]`. The
"zero" is real.

But the *unique* value is far smaller than the presentation implies `[M-SYN]`:

- Lane 3's flagship "blind" case **`seg0-45` does not need MASt3R at all.**
  All 32 keyframe pairs between those segments are covisibility edges, with up
  to **211 F-inliers, 192 essential-matrix inliers and 4.42° parallax** under
  plain production ORB. What failed there was *registration* — neither segment
  had triangulated points to align — not *matching*. Stage 1 fixes that pair;
  a foundation model is not required and would be the expensive way to do it.
- **With ORB alone, 46 of 51 segments already form one connected component on
  the stale session, and exactly 2 segments (22 and 40) have no cross-segment
  link at all; at HEAD all 33 segments form one component** `[M-SYN]` — **but
  "one component" is criterion-dependent, and revision 1 declared connectivity
  solved using a criterion this same document elsewhere makes insufficient.**
  At HEAD, over 33 segments `[M-SYN]`:

  | criterion | components | largest | isolated |
  |---|---|---|---|
  | census (F-inliers ≥15, parallax ≥0.5°), ≥1 supporting keyframe pair | 1 | 33/33 | — |
  | production-like (cheirality ≥15, ratio ≥0.05, parallax ≥0.5°), ≥1 pair | 1 | 33/33 | — |
  | census + **§5.1.7's own term 8** (≥3 supporting keyframe pairs) | **5** | 29/33 | 7, 12, 18, 27 |
  | production-like + term 8 | **6** | 28/33 | 7, 12, 15, 18, 27 |
  | ORB-SLAM3 essential-graph strength (≥100 inliers) | **16** | 13/33 | 13 segments |

  And the criterion carries a false-positive rate this document publishes
  elsewhere: **14.4% of pairs with exactly zero baseline clear the ≥0.5°
  parallax test, and 100% clear `MIN_INLIERS`** `[M-SYN, verify_tensions.json]`.
  §0.4 strikes "14.4%" as a claim about *production*, which is correct — but
  that number *is* the right statement about Lane 1's census criterion, under
  which every edge and connectivity figure in this document is computed.
  **Report connectivity at term-8 strength — 28 of 33, five isolated — as the
  honest headline.** It is still a good result.
- **A connected component is not a registrable map, and this is the sharper
  limit.** Only **11 of 33 segments hold any triangulated point or solved
  pose** at HEAD: `{1, 3, 5, 8, 12, 14, 19, 20, 24, 31, 32}` `[M-SYN]`.
  Restricted to those 11 under the production-like criterion the graph has
  **3 components** — `[1,3,8,14,19,20,24,31,32]`, `[5]`, `[12]` — and
  **segment 5 holds 904 points, the third largest in the map, sitting in an
  isolated piece** `[M-SYN]`. (Under the looser census criterion those 11 do
  form one component; the difference is the criterion, and that is the point.)
  So "all 33 form one component" is a statement about whether *images* match,
  not about whether a *gauge-consistent map* can be assembled. **Connectivity
  is not the gap; buildable geometry is** — which is Stage 1's job, not a
  foundation model's.
- 930 of 1,275 segment pairs (72.9%) have zero ORB essential-matrix evidence
  anywhere. Lane 3 sampled five and judged three to be the same place. That is
  a real, untested opportunity for *graph density* — which is what pose-graph
  optimisation actually eats — but it is five samples, and the corpus is one
  apartment, so its false-positive rate is unmeasurable here `[M-L3]`.

**Honest statement of Lane 3's contribution:** it demonstrated that a pointmap
model can produce plausible geometry where classical matching has nothing, on
roughly one clearly-established segment pair, behind a validity gate that this
review has shown to be 61.5% false-positive. That is an interesting research
result and it is not yet an engineering input.

#### 5.1.7 The repaired gate, and its honest price

**No gate below is currently validated.** §5.1.3 shows the magnitude term fails
its own acceptance test and that the only 0%-on-the-null configuration has zero
measured recall. What follows is therefore the *specification of what must be
measured*, in the order the terms should be evaluated — not a rule to
implement today. Stage 5 is conditional on one of these clearing both halves of
its stop/go on footage with genuine translation.

```
1. undistort both frames with our real ChArUco dist_coeffs
     (raises E-inlier ratio 0.748 -> 0.829 on the same pairs [M-L3])
2. refuse if either frame's usable (non-redacted, feature-bearing) area is
     below the Stage-2 admission threshold
3. reciprocity of MATCHING (forward+reverse knnMatch) >= 0.3
     rejects 100% of geometry-less traps, keeps 69.8% of good edges [M-L1]
4. relative pose from the POINTMAP (PnP), never from findEssentialMat
5. baseline / median scene depth  >  THRESHOLD-TO-BE-DERIVED
     *** NOT 0.05. That value FAILS: 2.6% of true-zero-baseline pairs
     *** exceed it (max 0.1352), and it rejects seg4-5, the only pair
     *** with independent classical corroboration. [M-SYN] See 5.1.3.
     *** No value of this threshold separates on the CURRENT corpus.
6. translation-DIRECTION reciprocity between two independent passes < 15 deg
7. rotation reciprocity < 15 deg          <-- LAST, and NEVER alone
8. temporal/spatial consistency: the same link must be proposed by >= 3
     covisible keyframes (ORB-SLAM3's structural guards are the two most
     powerful in its nine-gate ladder, and they are structural, not
     photometric) [Q]
```

**The price, measured, and it is prohibitive** `[M-SYN]`. Adding only term 6 to
Lane 3's gate takes its acceptance on Lane 3's *own positives* from 7/10 to
2/10 on the undistorted rerun, and from 7/12 to 3/12 on the raw oracle+blind
set. Adding term 5 at 0.05 as well takes it to **0 of 10** while finally
reaching 0% on the null. The reason is not that the guards are too strict — it
is that **most "true positives" in this corpus are themselves
rotation-dominant**, so a guard that refuses fabricated translation refuses
most of them too.

That is the real finding, and revision 1 stated it in this paragraph and then
contradicted it two sections later by proposing a threshold: **on this footage,
a gate strict enough to be safe admits nothing.** Which is exactly why Stage 5
is conditional and why Stages 1–4, whose value does not depend on cross-segment
registration at all, come first.

#### 5.1.8 Answering the lead's three sub-questions directly

- *Do Lane 3's accepted positives have genuine translation, or could they be
  rotation-only pairs the gate cannot distinguish?* **The gate cannot
  distinguish them, so the question is not answerable from Lane 3's data.**
  Lane 3's own `purerot` group already contained the refutation: 5 of its 6
  real pure-rotation pairs pass `recip_R < 15° ∧ E-ratio > 0.5` `[M-SYN,
  recomputed from Lane 3's own `mast3r_analysed.json`]`, and Lane 3 excluded
  that group from its AUC analysis as "not a place-recognition question." It
  was not a place-recognition question. It was the *validity* question.
- *Does Lane 3's negative control test the same thing as Lane 2's null?* **No.
  They are different controls for different failure modes**, and the decisive
  experiment had not been run. Lane 3's negatives are *different places*, where
  rotation reciprocity works superbly (median 145.5° on the hard negatives
  `[M-SYN]`, 0 of 6 accepted). Lane 2's null is the *same place, no
  translation*, where it fails completely. Both are true.
- *Is a translation-aware reciprocity check the missing guard?* **It is
  necessary and it is not sufficient, and revision 1's proposed completion of
  it does not work either.** Through the essential-matrix route it still admits
  5.0% of true-zero-baseline pairs `[M-SYN]`, one at `recip_t_dir = 0.0°` with
  a median inlier parallax of **exactly 0.0 px**. Through the pointmap-PnP
  route it admits **0/200** — much better — but pairing it with the
  baseline-over-depth magnitude term revision 1 called "the sufficient guard"
  **drives recall to zero on this corpus** (§5.1.3). **The honest answer to
  this question today is: no guard measured in this programme is both safe and
  usable here, and finding one requires footage with translation rather than a
  cleverer statistic.**

### 5.2 TENSION 2 — the populations are the same; the inference was a base-rate inversion

The lead suspected the 54.7% baseline-limited figure had been misread. It had
not been misread; **it had been correctly measured and then over-generalised in
the opposite direction by Lane 1.**

First, the populations are provably identical. Restricting Lane 1's census to
*consecutive keyframe pairs inside segments that hold zero triangulated points*
gives **exactly n = 212** `[M-SYN]` — the same 212 pairs the multi-cue lane and
Lane 2 used. On them Lane 1's own census says 190 (89.6%) are covisibility
edges and **100 (47.2%) carry parallax ≥0.5°**, against Lane 2's 34.9%
"solvable"; the residual is the criterion difference (F-RANSAC at 3.0 px vs
essential-matrix at 1.0 px with cheirality). **Same population, same direction,
no contradiction.**

Second, Lane 1's conclusion — "the distant edges are the good ones, production
matches exclusively against the class of pair with the least parallax" — is
**conditional-probability inversion**. Its parallax figures are all conditioned
on a pair *already being an edge*. Unconditionally, **recomputed at HEAD**
(448 keyframes / 33 segments / 100,128 pairs) after the adversarial review
pointed out that revision 1's version of this table was computed on the session
it declares stale `[M-SYN, census_at_head.py]`:

| keyframe gap | pairs | % that become edges | **% of all pairs that become useful edges** | *(rev 1, stale session)* |
|---|---|---|---|---|
| 1 (consecutive) | 447 | **86.8%** | **56.2%** | *57.9%* |
| 2–5 | 1,778 | 66.6% | **48.3%** | *49.4%* |
| 6–20 | 6,525 | 34.5% | 27.0% | *29.8%* |
| 21–100 | 31,000 | 9.2% | 8.5% | *9.2%* |
| >100 | 60,378 | 2.2% | **2.1%** | *2.4%* |

The re-baseline moves nothing material — every cell shifts by ~1–3 points and
the ordering is identical — so the conclusion stands on current data rather
than stale data. **Per pair asked, consecutive keyframes are the single most
productive class in the corpus, and yield falls monotonically with gap.**
Distant edges are higher *quality* when they exist and much *rarer*. Both lanes
were looking at the same distribution from opposite ends.

(The same restriction at HEAD gives **217** consecutive pairs inside
geometry-less segments — 88.0% edges, 50.2% useful — against 212 / 89.6% /
47.2% on the stale session `[M-SYN]`. The population is stable too.)

Third, Lane 2's "widen the baseline" recommendation is **true on raw capture
frames and false on keyframes.** Its gap sweep (28.2% → 44.4% solvable from gap
1 to 5) was measured on raw frames at 12 fps, where adjacent frames are nearly
identical. On *keyframes*, which are already motion-selected, production's own
gate accepts `[M-SYN]`:

| keyframe gap | 1 | 2 | 3 | 5 | 10 | 20 |
|---|---|---|---|---|---|---|
| production accepts | **50.4%** | 49.5% | 47.8% | 36.5% | 28.6% | 16.2% |

Flat to gap 3, then decay. **Keyframe selection has already done the baseline
widening.** This is precisely why Stage 1 says *three* references and not five
or "all pairs", and it is a better justification than either lane gave.

**Net correction to the project's standing understanding:** the 54.7% figure is
correct, correctly scoped, and should be retained — with the scope stated. It
is a fact about *consecutive keyframe pairs inside geometry-less segments*, not
a ceiling on what any architecture can achieve, because 4,820 cross-segment
edges with usable parallax exist at HEAD that production never asks about.

### 5.3 TENSION 3 — continuity is a worthless metric; reproducibility is the good one

**Yes, Lane 2 invalidated part of the brief's own instrumentation.** "Number of
maps", "tracking resets" and "trajectory continuity" measure *whether a system
answers*, not whether it is right. DPVO scores perfectly on all three (1 map,
1,848 poses, 0 resets, 0 refusals) and disagrees with itself by 12–38% of
trajectory extent `[M-L2]`. Those three rows should be struck from any future
scorecard, or reported only alongside a reproducibility number.

**Does the repeat-run test bite for us?** It could have — the repo's own source
says the RANSACs are unseeded `[Q]` — and it does not: **448/448 poses and
8,333/8,333 points bit-identical across fresh processes** `[M-SYN]`. So the
test is *not* vacuous, we simply pass it. Note the caveat: n=2, one capture,
one OpenCV build, and the repo already recorded a test number moving across
builds. Pin it with a test rather than assuming it.

**Is the repeat-run test the most valuable methodological output of the
programme?** No — but it is second, and the two belong together.

- **Reciprocity is first.** Four independent arrivals now: the cross-segment
  lane (a wrong Sim(3) reprojecting at 1.62 px while wrong by 3.2× in scale),
  Lane 1 (matching reciprocity, AUC 0.985, a 0.3 threshold rejecting 100% of
  traps), Lane 3 (forward/reverse pose agreement catching all six hard
  negatives), and ORB-SLAM3's own *symmetric* Sim(3) inlier test `[Q]`. But
  this review has now also shown reciprocity has a **blind spot on exactly the
  degeneracy that matters most** (§5.1.2), so it must be stated as
  "reciprocity of the right quantity", not "reciprocity".
- **Reproducibility is second and is the cheaper of the two** — one extra run,
  no ground truth, no threshold. It is the only test in the programme that
  caught a good-looking trajectory being wrong.

Adopt both as standing acceptance criteria for any candidate backend, including
our own.

### 5.4 TENSION 4 — redaction contaminates the census mildly, and it is the same bug as the featureless keyframe

Measured over all 457 keyframes of the *stale* canonical session `[M-SYN,
redaction_vs_census.py]`, black fraction at the lead's threshold (grey ≤ 2)
against Lane 1's covisibility degree. **The adversarial review re-ran this at
HEAD and it survives and strengthens slightly: 25 of 27 feature-starved
keyframes are >40% black fill, median black fraction 0.750, 57.4% of keyframes
>10% black** `[QUOTED, adversarial review]` — against the 20-of-24 / 0.747 /
56.2% below. Use the HEAD figures; the stale table is kept because its
stratification is the part that carries the argument.

| black fraction | n | median ORB features | median covisibility degree | median useful degree |
|---|---|---|---|---|
| <5% | 156 | 810 | 43 | 39 |
| 5–10% | 44 | 950 | 28 | 24 |
| 10–20% | 104 | 1,332 | 54 | 42 |
| 20–40% | 69 | 873 | 30 | 25 |
| 40–60% | 49 | 549 | 41 | 35 |
| **>60%** | **35** | **123** | **6** | **4** |

Spearman(black, degree) = **−0.181**; Spearman(black, ORB count) = −0.148;
Spearman(ORB count, degree) = +0.616.

Answers to the lead's four questions:

1. **Is Lane 1's census a lower bound?** Yes, but only mildly, and the damage is
   concentrated: the correlation is weak until 60% blackout, at which point
   degree collapses from ~30–50 to 6. That is **35 keyframes, 7.7% of the
   session**. Expect a modestly larger graph on unredacted frames, not a
   different conclusion.
2. **Is featureless-keyframe admission the same root cause as redaction?**
   **Yes — and this is the finding.** Of the 24 keyframes with ≤100 ORB
   features, **20 are >40% redaction fill**, with median black fraction
   **0.747** (at HEAD: **25 of 27**, median **0.750**). The 5-feature keyframe that triggers the OpenCV-5 mask defect is
   `00001824`, 62.1% solid black `[M-L3]`. So: one root cause (solid-fill
   redaction on a frame the selector then admits), four symptoms (BoW universal
   attractor, r_H uninitialised mask, MASt3R match collapse, dead covisibility
   node). **Stage 2 fixes all four with one admission gate.**
3. **Should the redaction cost analysis be re-measured?** Yes, and against
   whatever matcher is actually used. The existing analysis measured ORB and
   concluded "keyframe acceptance and pose solving were completely
   insensitive"; both statements are true and neither transfers to a dense
   model `[M-L3]`.
4. **Is there a less destructive privacy fill?** Out of scope for this roadmap,
   and **do not casually reverse the decision** — blur was rejected on
   invertibility grounds `[Q, redaction.py:119-122]` and that is a sound privacy
   argument, not an oversight. The cheap and correct move is not to change the
   fill; it is to **refuse the keyframe** when too little usable image survives.

### 5.5 TENSION 5 — the convergence is genuine, and here is the strongest counter-argument anyway

The lead was right to suspect contamination: all three lanes received the same
`LEAD_SUPPLEMENT` describing BA-at-0.00% and covisibility-span-1. That is a
real source of shared framing.

**But framing is not measurement, and the measurements are independent:**

| lane | population | method | shares anything with the others? |
|---|---|---|---|
| Lane 1 | 457 *persisted keyframes*, all 104,196 pairs | ORB detect + Lowe + F-RANSAC + parallax + reciprocity | detector only |
| Lane 2 | *raw capture frames*, sliding windows | ORB index matching + union-find over tracks, sweeping match width 1/3/5/32 | detector only |
| this review | 448 *HEAD-replay keyframes*, all 100,128 pairs | Lane 1's `_pair` unchanged, new session | Lane 1's code, new data |

Lane 1 and Lane 2 share **no code, no population, and no statistic** — one
counts verified edges over persisted keyframes, the other counts union-find
track lengths over raw frames. They agree that widening the match set produces
a qualitatively denser graph. This review reproduced the effect on a third
population. **The convergence is genuine.** What the shared supplement plausibly
did influence is *what each lane chose to measure*, not what the measurement
returned — and the 2.6× like-for-like edge gap, the 4,820 unrepresentable
cross-segment links and the 66.1% two-view landmark share are facts about the
corpus that hold regardless of who asked.

**The strongest available counter-argument, stated as strongly as I can make
it, because nobody else did:**

> Covisibility gives you cycles. Cycles give pose-graph optimisation something
> to distribute. But *what* it distributes is error in relative poses, and on
> this footage a large share of those relative poses are the near-degenerate
> ones that production is currently right to refuse. 66.1% of landmarks are
> two-view; median parallax on consecutive keyframe edges is 1.048°; and the
> corpus's median inter-frame rotation is 1.22° against a vanishing-point
> estimator noise floor of 2.59°. It is entirely possible that a denser graph
> on this corpus yields a *more confidently wrong* map rather than a better
> one — the exact failure DPVO exhibits, arrived at classically. Nothing
> measured in this programme excludes that outcome.

That counter-argument is why **Stage 1's stop/go requires `poses_solved` and
`points` not to fall**, why Stage 4's stop/go requires a measurable
reproducible improvement rather than "it ran", and why the roadmap refuses to
schedule loop closure before pose-graph optimisation has demonstrated value.
It is also why `1272b09` exists: this project has already once shipped a change
on segment count alone and had to retract it.

**Where contamination IS present, and this defence does not reach: the cost
estimates.** The lead's supplement does not only frame, it instructs — *"Price
Atlas-style multi-map adoption using the EXISTING scaffolding, not from
scratch. **Any cost estimate that ignores this will be too high.**"* Stage 5
reproduces that almost verbatim. Every effort figure in §3 is `[E]` with no
measurement behind it, and the part of this document the supplement steered is
exactly the part with no measurement behind it. The adversarial review
demonstrated the consequence concretely: **Stage 1 was priced at 1–2 days and
is really about a week**, once the `_Chain` single-reference invariants,
the `claimed` de-duplication rule and the triangulation-pair ambiguity are
counted. The measurements in this document are independent; **the costings are
lead-steered and should be treated as optimistic.**

### 5.6 TENSION 6 — coverage gaps, and whether they matter

| what was not done | why | does it weaken the recommendation? |
|---|---|---|
| **ORB-SLAM3 never built or ran** | WSL2 `sudo` requires a password; the distro has no toolchain at all; and `CMakeLists.txt` hard-fails on OpenCV ≥5 while the source still references `CV_LOAD_IMAGE_UNCHANGED` `[M-L1]`. `[E]` ~2–4 engineer-hours **on a machine with root** — administrative, not technical | **Barely.** The recommendation is a change to *our* pipeline, and it is justified by measurements on *our* components: same detector, same matcher, same thresholds, 42× more edges. An ORB-SLAM3 trajectory would have been a datapoint about ORB-SLAM3. **But it does leave the brief's "sensor ceiling" hypothesis untested by an external classical system** — argued against in §2, not disproven. |
| **MASt3R-SLAM never built** | three independent blockers: nvcc 11.8 rejects sm_120, no `cl.exe` anywhere on the host, and its `setup.py` emits SASS only to sm_86 with **no PTX fallback** `[M-L3]` | No. Its weights cannot ship regardless. Its *architecture* was read from source and is in the matrix. |
| **DROID-SLAM never ran** — confirmed | Lane 2 states it explicitly: build strictly heavier than DPVO's, and DPVO answered the question. §6.1 of that report prices it from source arithmetic (~3.3 GB at our resolution) `[E-L2]` | No. It is the heavy end of a family whose light end already showed the disqualifying property. |
| **No benchmark sequence (EuRoC/TartanAir) for DPVO** | not run | **Mildly.** It means we cannot separate "DPVO is unstable" from "DPVO is unstable on *this* footage". The published EuRoC ATE argues for the latter. Since this footage is the deployment target, the recommendation does not change — only the blame does. |
| **VGGT-1B-Commercial and MapAnything-apache never measured** | outside the lanes' briefs | **Yes, materially** — they are the *only* two shippable pointmap options and neither has a number. That is Stage 6's entire content. |
| **No second environment captured** | corpus is one apartment `[M-L3]` | **Yes, materially.** A place-recognition false-positive rate is currently **unmeasurable** on this corpus because almost every honest pair *is* a loop closure. Capture a second, genuinely different environment before trusting any retrieval number. |
| **The pure-rotation null is synthetic** | no ground-truth motion exists | It contains no independent scene motion, no rolling shutter, no exposure change, and one image is a resample of the other. It is a lower bound on realism. **It is also the only test in the programme with a known right answer**, and it changed three of the programme's headline conclusions. |
| **The null's effective sample size is 40, not 200** | 40 distinct source frames × 5 rotation magnitudes, from **one capture**, chosen as the 40 *sharpest* of a 400-frame sample | **Yes, for every percentile derived from it.** The 61.5% headline is insensitive (excluding the 0.0° arm it *rises* to 67.5% `[M-SYN]`), but §5.1.3's baseline/depth tail — p99 0.1314, max 0.1352 — rests on n = 40 frames from one apartment, and sharpness selection biases toward the easiest frames. A gate derived from it must be re-derived on the target footage, which is what Stage 5's entry condition (a) says. |

---

## 6. Answers to the brief's ten questions

**(1) What to change FIRST.** Re-baseline (Stage 0), then widen `_extend` from
1 previous keyframe to 3 and persist the covisibility adjacency, with
match-reciprocity as the guard (Stage 1). Nothing else in the classical stack is
non-vacuous before it, which is not an opinion — it is what the 0.00% BA
measurement means. Budget **a week**, not two days: the change breaks several
single-reference invariants in `_Chain` and needs a landmark-claim
de-duplication rule that does not exist today (§3, Stage 1).

**(2) What to benchmark before touching production.** Three things, in this
order. (a) The Stage 0 replay on all eight motion-bearing captures, reporting
segments, poses_solved and points *together*. (b) The pure-rotation null against
whatever gate you intend to ship — the harness is in `slam_synthesis/` and takes
minutes. (c) The repeat-run reproducibility test, pinned by a committed test.
**Do not** benchmark ORB-SLAM3 first; it costs a machine with root and answers a
question you do not need answered.

**(3) Which existing algorithms remain.** ORB detect/describe, Lowe ratio,
essential matrix + `recoverPose`, PnP chaining, triangulation, the
cheirality-ratio gate, the median-triangulation-angle gate, the blur and
motion gates, the homography fit in the frontend. **All of them stay.** The one
thing to remove is `r_H`, which §5.1.5 shows is useless in the one regime it
exists for. The frontend is adequate; leave it alone.

**(4) Adopt covisibility / local map / Atlas?** **Covisibility: yes, first, and
it is the whole recommendation. Local map: yes, it falls out of covisibility.
Atlas: no.** Our segments are not ORB-SLAM3 maps — they have no minimum size,
no geometry requirement, and no merge eligibility — and at HEAD all 33 of them
form a single connected component under available covisibility edges at one
supporting keyframe pair, **28 of 33 at the 3-supporting-pair strength this
document requires**, and only **11 of 33 carry any geometry at all** `[M-SYN]`.
There is no multi-map problem here; there is one map cut into 33 pieces by a
gate, and most of the pieces are empty. Copy three Atlas *policies* (try hard before conceding;
refuse to keep trivial maps; one global keyframe database), not its data
structure, and do not port `MergeLocal`.

**(5) Loop closure / place recognition now?** **Place recognition at Stage 3
(with its circularity acknowledged); loop closure NOT YET — Stage 5 is
conditional and currently unfunded.** Revisits genuinely exist — 2,023 verified
edges separated by >60 s of capture on a 154-second walk `[M-L1]` — so loop
closure is not vacuous. But no validity gate measured in this programme is both
safe on a zero-baseline null and non-empty on this corpus's real positives
(§5.1.3), and this corpus cannot measure a false-positive rate at all because
it is one apartment (§5.6). **Meet Stage 5's entry condition — footage with
genuine translation, or segments with enough internal geometry to register
classically — before writing any cross-segment transform into a map.**

**(6) Is learned VO justified?** **No.** Not on cost — DPVO is startlingly
cheap at 16.93 fps and 682 MiB with bounded memory over 1,848 frames `[M-L2]`.
On correctness: it disagrees with itself by 12–38% of trajectory extent while
we are bit-for-bit reproducible `[M-L2, M-SYN]`, it has no refusal code path at
all, and its value comes from patch lifetime — a *graph* property obtainable
with the ORB we already ship. Keep the WSL build as a diagnostic for "is this
footage reconstructible at all", judged on repeat-run agreement, never on how
the trajectory looks.

**(7) Learned 3D: live path or background only?** **Background only, and only
at Stage 6, and only on a shippable checkpoint, and only as a measurement
rather than an adoption.** 2.4 s/pair against an 83 ms live budget settles the
live question `[M-L3]`. The background question is settled by licensing (the
whole Naver line is unshippable) and by §5.1: the gate Lane 3 proposed is 61.5%
false-positive on zero-baseline pairs, and **the replacement revision 1 of this
document proposed is 2.6% false-positive and has zero measured recall**
(§5.1.3). Use PnP on the pointmap rather than the essential-matrix route; do
not gate on baseline-over-depth at 0.05; do not let it touch a map until a gate
clears both halves of Stage 6's stop/go.

**(8) What explicitly NOT to pursue.** §7.

**(9) Latency / resource impact.** §4.3. Summary: Stages 0–4 add **no GPU
dependency**; the incremental live cost is roughly 3× the current backend
matching path, ~8 ms/keyframe against a measured 12.87 ms/frame engine budget
`[E, from measured components]`; retrieval adds 13.9 ms/keyframe unoptimised;
the covisibility census, if ever run offline, is 109.5 s on 12 CPU workers
`[M-SYN]`. A pointmap verifier, if adopted, is a 4–18 minute background pass
over the existing candidate list `[E-L3]`, never a live cost.

**(10) The staged roadmap.** §3.

---

## 7. What NOT to pursue

Each with the measurement that kills it.

1. **Do not add bundle adjustment, `pycolmap`, or a bigger solver before
   covisibility.** Measured at 0.00% improvement at 16/32/104 keyframes
   `[Q, repo]`, because **66.1% of landmarks at HEAD are seen by exactly two
   views** `[M-SYN]`. That is arithmetic, not tuning.
2. **Do not adopt Atlas as a data structure**, and specifically do not port
   `MergeLocal`/`MergeLocal2` — ~1.1 kLOC containing four verified pointer bugs
   and an infinite loop `[Q-L1]`. Our non-destructive `transform_to_world`
   design is better and already specified in `schema.py`.
3. **Do not gate on `r_H`. Stop populating it — and do not delete the field
   without a contract change.** Median 0.4960 on pairs that are *definitionally*
   pure rotation; a 0.50 gate catches 4.0% of them `[M-SYN]`. It is useless in
   exactly the regime ORB-SLAM3 uses it for. But it is a persisted
   `KeyframeEdge` field in the Tower→iOS handoff (§5.1.5), so removal is
   cross-subsystem protocol work, not a line deletion.
4. **Do not ship ORB-SLAM3's `ORBvoc.txt`.** 145 MB uncompressed, GPLv3 by
   inheritance, and an in-domain 10,000-word vocabulary trains in 10.7 s
   `[M-L1]`.
5. **Do not adopt DPVO/DROID as the frontend**, and in particular **never as a
   fallback where the classical backend refused** — those are precisely the
   baseline-limited windows where a learned system is most likely to be
   confidently wrong. If it were ever adopted it would have to be the primary
   path on healthy motion.
6. **Do not adopt any DUSt3R/MASt3R/MASt3R-SLAM checkpoint into a product.**
   CC BY-NC-SA code plus stacked non-commercial dataset terms in the weights,
   with no commercial licence offered `[Q-L3]`. Benchmark only.
7. **Do not run any pointmap global aligner over a session.** 4.50 MiB per
   directed edge, exactly measured; 457 keyframes is 915 GiB `[M-L3/E-L3]`.
8. **Do not gate anything on match count, inlier ratio, reprojection error, or
   a model's own confidence.** Four of six visually-verified different-place
   pairs produce essential-matrix inlier ratios of 0.56–0.78 `[M-L3]`; a wrong
   Sim(3) reprojects at 1.62 px median while being wrong by 3.2× in scale
   `[Q]`; 95.5% of true-zero-baseline pairs clear an E-ratio of 0.5 `[M-SYN]`.
9. **Do not gate on rotation reciprocity alone.** §5.1.2. It is anti-correlated
   with validity on the degeneracy that matters.
10. **Do not trust MASt3R's metric depth as scale.** It disagrees with the
    classical Sim(3) oracle by 4–6× `[M-L3]`, and the classical estimate is the
    one with an independent reverse solve agreeing to 0.3%.
11. **Do not expect loop closure, BA, or any learned model to resolve scale.**
    Monocular determines the scene up to a similarity, full stop. Metric scale
    requires an IMU, a stereo baseline, a known object, or a rangefinder.
12. **Do not pursue lines, vanishing directions, second-plane constraints, or
    MiDaS** — all four already measured and refused `[Q, multi-cue lane]`.
13. **Do not reverse the redaction fill decision casually.** Blur was rejected
    because it is partially invertible `[Q]`. Refuse the keyframe instead.
14. **Do not report "number of maps", "tracking resets" or "trajectory
    continuity" as evidence of correctness** without a reproducibility number
    beside them. §5.3.
15. **Do not gate cross-segment registration on pointmap baseline-over-depth at
    0.05.** 2.6% false-positive on the null, max 0.1352, and it rejects the
    oracle `seg4-5` `[M-SYN]`. Revision 1 of this document recommended it; that
    recommendation is withdrawn (§5.1.3).
16. **Do not declare connectivity solved from a one-supporting-pair criterion.**
    At 3 supporting keyframe pairs it is 28 of 33, and among the 11 segments
    that actually hold geometry it is 3 components with a 904-point segment
    isolated `[M-SYN]`. §5.1.6.
17. **Do not treat this document's effort estimates as measurements.** They are
    all `[E]`, they are the part of the document the lead's supplement steered,
    and the one that has been checked against the code was wrong by ~3× (§5.5).

---

## 8. Open risks

1. **The strongest counter-argument in §5.5 is not disproven.** A denser graph
   on rotation-dominant footage may produce a more confidently wrong map. The
   stop/go criteria exist for this; honour them.
2. **The pure-rotation null is synthetic.** Its verdicts are sound for the
   fabricated-translation question and are not a full simulation.
3. **No external classical baseline exists on our footage.** The "sensor
   ceiling" hypothesis is argued against, not disproven.
4. **False-positive rates for place recognition are unmeasurable on this
   corpus** — it is one apartment. Capture a second environment before trusting
   any retrieval threshold.
5. **Reproducibility is build-dependent, not contractual.** The RANSACs are
   unseeded by the repo's own account; pin the property with a test.
6. **All Stage 3 retrieval numbers are from a vocabulary trained in-domain on
   the same corpus it was evaluated on** `[M-L1]`. That flatters it — arguably
   correctly for a fixed sensor, but it is not a generalisation claim.
7. **Every effort estimate is `[E]`.** They are grounded in code actually
   written during this programme, and they are still estimates.
8. **Licensing readings are not legal advice**, and the Sim(3) patent analysis
   is a literature search, not a freedom-to-operate clearance. One licensing
   question is open rather than answered: **what the `pyceres` 2.6 wheel links
   against** (§4.4).
9. **Cross-segment registration is currently un-gateable on this corpus** and
   Stage 5 is therefore unfunded rather than scheduled. If the product needs
   segment registration sooner than a capture campaign allows, that is a real
   schedule risk and it should be surfaced now, not discovered at Stage 5.
10. **The null's independent sample size is 40 frames from one apartment**, and
    every percentile derived from it inherits that. The 61.5% headline is
    robust to it; §5.1.3's tail is not.
11. **This document has been through one adversarial review and six defects
    were found, four of which would have wasted budget.** Assume more remain.
    The stop/go criteria exist so that the next one is caught by a measurement
    rather than by a reviewer.

---

## 9. Reproduction

New harness, `tower/scripts/research/slam_synthesis/` — all read-only against
the corpus; third-party code and checkpoints stay outside the repo tree.

| file | what it does |
|---|---|
| `build_rotation_null_manifest.py` | builds the 200 pure-rotation pairs (true translation exactly 0) in the manifest format Lane 3's harness consumes |
| `analyse_purerot_null.py` | scores Lane 3's gate, and a translation-aware repair, against that null and against Lane 3's own positives and hard negatives |
| `production_gate_on_null.py` | Lane 2's transcription vs `backends/classical.py`'s actual criterion, over identical pairs |
| `production_gate_on_real.py` | the other half of the ROC: both criteria over real keyframe pairs at gaps 1/2/3/5/10/20 |
| `rh_on_null.py` | r_H on true-zero-baseline pairs, with the OpenCV-5 mask defect closed, against Lane 1's real-edge distribution |
| `census_at_head.py` | Lane 1's census re-run unchanged on a HEAD replay (448 kf / 33 segments) |
| `redaction_vs_census.py` | blackout fraction vs ORB count vs covisibility degree, all 457 keyframes |
| `verify_tensions.py` | conditional vs unconditional edge yield by keyframe gap; zero-baseline behaviour of Lane 1's parallax estimator |
| **`verify_corrections.py`** | **every `[M-SYN]` number added in revision 2, in one script** — the struck gate's tail and zero recall (F1), the covisibility oracle ceiling (F2), the like-for-like 2.6× (F3), connectivity under five criteria (F5), which segments carry geometry (F6), and the gap-yield table recomputed at HEAD (F15). Run this first if you are deciding whether to trust §3. |

The HEAD replay itself:

```
tower/.venv/Scripts/python.exe scripts/world_build_session.py \
  --root <scratch>/repeat_A \
  --frames data/captures/22e9d4289cb440fbb3f14e6da369a136/frames \
  --intrinsics data/world_builder/intrinsics/360x640.json --format json
```

Run it twice and diff `derived/*/poses.json` and `derived/*/points.json`; they
should be identical. If they ever stop being identical, that is a finding.

The adversarial review's own harness, independent of the above, is under
`tower/scripts/research/slam_adversarial/`: `verify_head_replay.py`,
`ablate_gate.py`, `connectivity_under_gates.py`, `redaction_at_head.py`.

Source reports, superseded where this document says so:
`2026-08-26-slam-lane-classical-map-architecture.md`,
`2026-08-26-slam-lane-learned-vo.md`,
`2026-08-26-slam-lane-learned-3d.md`.
Review of this document: `2026-08-26-world-builder-slam-adversarial-review.md`.

---

## 10. Changelog — revision 1 → revision 2 (2026-08-27)

All six of the adversarial review's severity-1 findings and all of its
severity-2/3 findings were re-verified against this review's own artefacts
before being adopted. Every one reproduced.

| # | What changed | Where |
|---|---|---|
| F1 | **`baseline/depth > 0.05` struck as "the sufficient guard".** Tail reported (p99 0.1314, max 0.1352, 2.6% > 0.05); shown to reject the oracle `seg4-5`; conjunction shown to reach 0% on the null at **0 of 10** real-pair recall. **Stages 5 and 6 made conditional with explicit entry conditions.** | §5.1.3, §5.1.7, §5.1.8, §3 |
| F2 | **Stage 1's degree stop/go re-derived** from >15 (above the measured all-pairs oracle ceiling of 14.0) to ≥9.0, with the ≥3-view landmark criterion promoted to primary. | §3 Stage 1 |
| F3 | **"42×" restated as 2.6× like-for-like** (486 vs 189 over the same 72 keyframes); the population and unit artefacts named. | §0.3, §2, matrix row 2 |
| F4 | **Stage 4's stop/go replaced** with three criteria evaluable at Stage 4 with no ground truth: cycle-consistency residual ≥30% reduction, held-out-edge prediction, reproducibility. | §3 Stage 4 |
| F5 | **Connectivity restated with the criterion attached** — 1 component at 1 supporting pair, 6 at 3, 16 at essential-graph strength — and the 14.4% zero-baseline false-positive rate of the census criterion acknowledged. | §0.3, §5.1.6 |
| F6 | **"A component is not a map"** added: 11 of 33 segments carry geometry; among them 3 components with segment 5 (904 points) isolated. | §0.3, §5.1.6, §6 Q4 |
| F7 | **"Production strictly dominates" softened** to gaps 1–3, with the reversal at gaps 10/20 and the 33.96%-vs-34.91% geometry-less row reported. | §5.1.4 |
| F8 | **"Best pure-rotation discriminator" softened** to a conservative baseline-magnitude floor with a documented false-negative cost; the review's 2×2 ablation (cheirality does ~88%) incorporated. | §5.1.4 |
| F9 | **"`r_H` is never consumed" corrected** — it is a persisted `KeyframeEdge` field in the Tower→iOS contract; removal moved out of Stage 2 into a separate contract change; severity call retained. | §5.1.5, §3 Stage 2, §7 |
| F10 | **Stage 1 re-priced 1–2 days → ~1 week**, with the six specific code sites named. | §3 Stage 1, §6 Q1 |
| F11 | **Commit attribution corrected** to `6e60f76` (22:32:57), with the full timeline table. | §0.4, §3 Stage 0, §4.1 |
| F12 | **Estimate contamination acknowledged**: §5.5 now separates the (independent) measurements from the (lead-steered) costings. | §5.5, §3 Total, §7 item 17 |
| F13 | **Effective sample size n = 40, not 200**, added as a coverage row and a risk. | §5.6, §8 |
| F14 | **The 0.0° null corrected** — it is A vs a re-JPEG'd copy of A, not A vs A — with the branch-flip explanation for its 26.67° median. | §5.1.1 |
| F15 | **§5.2's gap-yield table re-run at HEAD**; §5.4's redaction figures updated to the HEAD values (25 of 27, median 0.750). | §5.2, §5.4 |
| F16 | **`pyceres` licence unified to Apache-2.0**, and the unanswered wheel-linkage question raised as a Stage 4 blocker and a risk. | §3 Stage 4, §4.4, §8 |
| F17 | **Stage 3's circularity stated at the point of use.** | §3 Stage 3, §6 Q5 |
| F18a | **DPVO stride-1 single run separated** from the stride-2 repeat measurements. | matrix row 13, §4.3 |

**One finding partially rejected.** F18(b) claimed §4.1's rejection row
"694 / 639 / 32 / 35" had its last two values swapped. It did not — the HEAD
replay gives `tracking_lost: 32, tracking_degraded: 35`, and the row followed
the order the shared brief used for the stale figures
(insufficient_motion / blurred / tracking_lost / tracking_degraded). **The
numbers were right and the presentation was ambiguous**, so the column header
is now labelled explicitly rather than the values changed.

**One finding refined rather than adopted verbatim.** F6's "3 components among
the 11 geometry-bearing segments, segment 5 isolated" reproduces under a
**production-like** criterion (cheirality ≥15, ratio ≥0.05, parallax ≥0.5°) and
**not** under the census criterion, which gives 1 component `[M-SYN]`. Both are
now reported with their criteria, because the criterion-dependence is the
finding.
