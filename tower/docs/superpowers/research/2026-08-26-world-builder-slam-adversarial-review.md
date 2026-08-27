# Adversarial review of the World Builder / modern-SLAM synthesis

**Date:** 2026-08-27. **Branch:** `integration/world-builder-lifecycle-v1`.
**Target:** `2026-08-26-world-builder-modern-slam-comparison.md`.
**Author:** adversarial reviewer. Research only — no production code modified,
`ios/` untouched, nothing merged. New code lives in
`tower/scripts/research/slam_adversarial/`.

**Labelling.** `[MEASURED]` = run by me, on this host, today, harness named.
`[QUOTED]` = taken from the synthesis, a lane, or source. `[ESTIMATED]` = mine,
method shown.

---

## VERDICT — **SAFE WITH SPECIFIED CORRECTIONS**

Stages 0–3 are safe to execute. Their evidence is real and I reproduced it
exactly. **Stage 1's stop/go must be re-derived before it is used, Stage 4's
stop/go must be replaced because it cannot be evaluated at Stage 4, and Stages
5 and 6 must not begin on the gate the document specifies — that gate fails the
document's own 0%-on-the-null acceptance test.**

The core architectural finding — the graph is the problem, not the frontend —
survives everything I threw at it. What does not survive is the headline
arithmetic used to size it (§2's "42×"), the stop/go criteria for the later
stages, and the repaired validity gate that Stage 5 and Stage 6 depend on.

---

## What I did

Every number below labelled `[MEASURED]` came from a run on this host today.

| what | how |
|---|---|
| independent HEAD replay ×2 | `scripts/world_build_session.py` on the canonical 1,848 frames, two fresh processes |
| two-view landmarks, production covisibility, reproducibility | `slam_adversarial/verify_head_replay.py` (new) |
| gate ablation, 2×2 | `slam_adversarial/ablate_gate.py` (new) — 200 nulls + 447 real gap-1 keyframe pairs |
| connectivity under 5 criteria | `slam_adversarial/connectivity_under_gates.py` (new) — both censuses |
| redaction at HEAD | `slam_adversarial/redaction_at_head.py` (new) — 448 keyframes |
| Tension 1 re-run | `slam_synthesis/analyse_purerot_null.py`, `production_gate_on_null.py`, unmodified |
| mask defect | `slam_classical/repro_rate_fresh_process.py`, 40 fresh processes |
| commit archaeology | `git log` on `tower/tower/world_builder/` |

---

## SEVERITY 1 — changes a recommendation or blocks a stage

### F1. The repaired gate fails the review's own stop/go. Stages 5 and 6 cannot start on it.

§5.1.7 specifies `baseline / median scene depth > 0.05` and §5.1.8 calls it
"the sufficient guard." Stage 5's and Stage 6's stop/go both demand **0%
acceptance on the pure-rotation null**.

`[MEASURED]`, recomputed from the synthesis's own
`scratchpad/dust3r_purerot_null.json` (194 of 200 nulls returned a value):

| statistic | value |
|---|---|
| median baseline/depth on zero-baseline pairs | 0.0095 |
| p90 / p95 / p99 | 0.0210 / 0.0279 / 0.1314 |
| **max** | **0.1352** |
| **fraction exceeding the proposed 0.05 gate** | **2.6% (5 of 194)** |

The document reports only "median 0.004–0.012" and "p90 ~0.020". It does not
report the tail. **A gate at 0.05 has a measured 2.6% false-positive rate on
pairs whose true translation is exactly zero, so it does not meet the criterion
the same document makes mandatory.**

Worse, the threshold is derived from one data point, and the surrounding data
contradict it `[MEASURED]`:

| pair | kind | b/d, undistorted | b/d, raw |
|---|---|---|---|
| `seg45-47` | the "blind" candidate the 0.05 threshold is drawn from | **0.0564** | **0.0469** ← below the gate |
| `seg4-5` | the **oracle** — the one pair with independent classical corroboration | (no pose) | **0.0391** ← below the gate |
| `seg0-0` | real pure rotation (true negative) | 0.0219 | 0.0141 |
| `seg0-1` | real pure rotation (true negative) | 0.0260 | 0.0054 |

So the proposed gate **rejects the only corroborated positive**, **straddles
the pair it was fitted to** (passing undistorted, failing raw), and **accepts
2.6% of the nulls**. Only 3 of 10 real pairs produced a baseline/depth value at
all, so its recall is essentially unmeasured.

**Correction required.** Strike "the sufficient guard is the pointmap
baseline-over-depth floor." On this data there is no threshold on this
statistic that separates the corpus's real positives from the null
distribution. Stage 6's stop/go is not achievable as written; Stage 5 must not
be scheduled behind a gate that has not cleared its own test. The honest
statement is the one §5.1.7 already contains: *on this footage, a gate strict
enough to be safe admits very little* — and that, not a threshold, is the
finding.

### F2. Stage 1's stop/go is set above the measured ceiling.

Stage 1 requires "median covisibility degree rises from 5.5 to **>15**".

`[MEASURED]`, `connectivity_under_gates.py` + `verify_head_replay.py`:
restricted to the **same 72 geometry-bearing keyframes** production actually
uses, the all-pairs ORB census — an oracle that asks *every* pair — gives a
median covisibility degree of **14.0**. Lane 1's own header states its edge
weight is computed over verified matches and is therefore "an UPPER BOUND on
the real weight" relative to shared landmarks.

**An oracle that asks every question does not reach 15 on the population that
currently carries geometry.** Honouring this stop/go would stop the roadmap at
Stage 1 even if Stage 1 does exactly what it is supposed to. The criterion is
achievable only if the geometry-bearing population itself grows — which is a
different mechanism (fewer broken chains) than the one Stage 1 is sold on.

**Correction required.** Re-derive the target from the 14.0 ceiling, or state
it against a fixed population, or replace it with a landmark-multiplicity
target (the ≥3-view criterion, which is well posed).

### F3. §2's "42×" — "the one measurement that decides the shape of the work" — is mostly a population-size artifact.

`[MEASURED]`, `verify_head_replay.py` + `connectivity_under_gates.py`:

| comparison | production | census | ratio |
|---|---|---|---|
| as the document frames it: production edges (72 kf, shared **landmarks**) vs census edges (448 kf, verified **matches**) | 189 | 8,021 | **42×** |
| **like for like: both over the same 72 geometry-bearing keyframes** | **189** | **486** | **2.6×** |
| as a rate over pairs asked, same 72 kf (2,556 pairs) | 7.4% | 19.0% | 2.6× |

The remaining ~16× is 376 keyframes that carry no triangulated point at all and
therefore contribute zero production edges *by definition*, plus the
match-versus-landmark unit change. The document's own sentence — "the same
frontend, asked more questions" — is true of the 2.6×; the other factor is "a
different number of keyframes participate", which widening `_extend` does not
directly buy.

**Correction required.** Restate §2 with the like-for-like ratio beside the
42×. The direction is unchanged and the recommendation still follows; the
magnitude used to justify the effort does not.

### F4. Stage 4's stop/go cannot be evaluated at Stage 4.

It requires "a measurable, reproducible reduction in **loop-closure residual**"
and "measure **drift** before and after."

- Loop closure is **Stage 5**. At Stage 4 there are no loop closures, so there
  is no loop-closure residual. The cycles Stage 4 optimises come from
  covisibility, not from closures.
- Drift has **no ground truth on this corpus** — §0.1 of the same document says
  so in its first sentence. The repo's 0.25 deg/keyframe figure is not
  measurable on real footage.

This is exactly the class of criterion §3 exists to forbid: it can only be
"evaluated" by looking at a number and deciding it seems better.

**Correction required.** Replace with something measurable at Stage 4: e.g.
"the sum of squared relative-pose residuals over covisibility cycles falls by
≥X% and the run stays bit-for-bit reproducible", plus a held-out-edge
consistency test. Both are self-consistency measures, which is all this corpus
can support — say so at the point of use.

### F5. "Connectivity is not the gap" is criterion-dependent, and the criterion it uses is one the same document strikes.

The claim reproduces **exactly** `[MEASURED]`, and I say so plainly: on the
stale 457-keyframe census, under a production-like criterion, the largest
component holds **46 of 51** segments with **exactly `[22, 40]`** isolated; at
HEAD, **33 of 33** form one component under both the census criterion and a
production-like one. I could not break either number.

What I could break is what it means:

| criterion (HEAD, 448 kf / 33 seg) | components | largest | isolated |
|---|---|---|---|
| census: F-inliers ≥15, tri ≥0.5° | 1 | 33/33 | — |
| production-like: cheirality ≥15, ratio ≥0.05, tri ≥0.5° | 1 | 33/33 | — |
| **census + §5.1.7's own term 8 (≥3 covisible keyframes propose the link)** | **5** | 29/33 | 7, 12, 18, 27 |
| **production-like + term 8** | **6** | 28/33 | 7, 12, 15, 18, 27 |
| ORB-SLAM3 essential-graph threshold (100 inliers) | **16** | 13/33 | 13 segments |

`[MEASURED]`. The document specifies term 8 as mandatory before a link may move
the map, then declares connectivity solved using a criterion that does not
apply it.

And the criterion carries a measured false-positive rate the document itself
publishes and then strikes for the wrong target.
`slam_synthesis/verify_tensions.json`,
`T1b_zero_baseline_behaviour_of_lane1s_estimator.orb`:
`pct_estimated_ge_0.5deg_FALSE_POSITIVE = 14.38`, with 100% of zero-baseline
pairs clearing `MIN_INLIERS`. **That 14.4% is the correct statement about
Lane 1's census criterion** — the criterion under which every connectivity,
8,021-edge and 6,750-useful-edge number in the document is computed. §0.4
strikes "14.4%" as a claim about *production*, which is right, and then leaves
the document's own headline resting on the criterion the number describes.

**Correction required.** Report connectivity at both strengths. "One connected
component" at term-8 strength is 28/33 with five isolated segments — still a
good result, and an honest one.

### F6. A connected component is not a registrable map. Only 11 of 33 segments carry any geometry.

`[MEASURED]`, from the HEAD replay's own `points.json` / `poses.json`:

- **11 of 33 segments** hold any triangulated point or solved pose:
  `{1, 3, 5, 8, 12, 14, 19, 20, 24, 31, 32}`. The other 22 hold zero.
- Restricted to those 11, the production-like cross-segment graph gives
  **3 components**: `[1,3,8,14,19,20,24,31,32]`, `[5]`, `[12]` — and segment 5
  holds **904 points**, the third largest in the map.
- 12 segments have ≤3 keyframes; 4 have exactly 1. ORB-SLAM3 requires >10
  keyframes for a map, which the document quotes approvingly in row 4.

So "all 33 segments form ONE connected component" is a statement about whether
*images* match, not about whether a *gauge-consistent map* can be assembled.
The question "is connected component too weak a notion of success" is answered
yes — and it is answered by 904 points sitting in an isolated piece.

---

## SEVERITY 2 — changes a stage's priority, or requires a correction in place

### F7. "Production strictly dominates" is false past gap 3, and false on the population that matters — from the synthesis's own data file.

§5.1.4's headline is 50.4% vs 42.3% at gap 1. `production_gate_on_real.json`,
which the review wrote and did not fully report:

| keyframe gap | production accepts | Lane 2's transcription |
|---|---|---|
| 1 | 50.44% | 42.32% |
| 2 | 49.45% | 46.15% |
| 3 | 47.80% | 43.83% |
| 5 | 36.50% | **36.50%** (tied) |
| 10 | **28.64%** | **31.32%** (production lower) |
| 20 | **16.25%** | **18.54%** (production lower) |
| **gap 1, restricted to the 212 pairs inside geometry-less segments** | **33.96%** | **34.91%** (production lower) |

That last row is the fragmentation population — the one the whole programme was
chartered to attack. On it, production accepts *fewer* real pairs than the
transcription it is said to strictly dominate.

There is a second reason "dominates" is too strong: there is no ground truth on
the real pairs, so accepting more of them is not by itself evidence of being
right. The dominance is sound only on the null side, where the answer is known.

**Correction:** state the dominance as holding at gaps 1–3 and reversing
beyond, and report the geometry-less-segment row.

### F8. The 0.0% is a baseline-magnitude floor, not a pure-rotation discriminator — but the causal attribution is right, and I have quantified it.

`[MEASURED]`, `ablate_gate.py`, the 2×2 the synthesis asserted but did not run:

| criterion | false "solvable" on 200 zero-baseline nulls | accepts, 447 real gap-1 keyframe pairs |
|---|---|---|
| `cv2.RANSAC` + epipolar inliers (Lane 2) | 26 = **13.0%** | 190 = 42.5% |
| `cv2.RANSAC` + **cheirality** inliers | 3 = **1.5%** | 207 = 46.3% |
| `USAC_MAGSAC` + epipolar inliers | 22 = 11.0% | 217 = 48.5% |
| **`USAC_MAGSAC` + cheirality (PRODUCTION)** | **0 = 0.0%** | **227 = 50.8%** |

**The synthesis's attribution survives and is now decomposed: the cheirality
inlier set does ~88% of the reduction (13.0 → 1.5), MAGSAC finishes it.** The
0.0% and the 13.0% both reproduce to the unit.

What does not survive is the word *discriminator*. Production's refusal mix on
the nulls is 108 few-inliers-after-cheirality, 61 low-cheirality-ratio, 31
low-parallax — i.e. it refuses by *magnitude*, not by recognising rotation.
`classical.py:451-460` documents exactly this: at 0.02–0.06 m baseline the
cheirality ratio measures 0.001–0.098, and the same file states plainly that
"a real sideways strafe at a 4-6 cm baseline recovers direction to within 2
degrees and is **still refused here**." Calling it "the best pure-rotation
discriminator measured anywhere in this programme" oversells a conservative
baseline floor with a documented false-negative cost. Its own source calls it
"a measurement of baseline over depth wearing another field's name" — which,
usefully, is the *same statistic* §5.1.7 reaches for and F1 shows does not
separate on this corpus.

### F9. `r_H` is not unconsumed. It is a persisted wire field in a cross-subsystem contract.

§5.4 / Stage 2 say "`r_H` is computed and never consumed, so nothing a user
sees is wrong," and price "delete `r_H`" inside a 0.5-day, ~30-LOC stage.

`[MEASURED]`, from source: `classical.py:498` and `unposed.py:175` compute it;
`engine.py:477` puts it on the keyframe edge; `records.py:554,572,592`
serialise it; it is written to `edges.jsonl` on every run; and it is a named
field of **`KeyframeEdge` in `docs/agent-handoffs/TOWER-TO-IOS.md:374`**, the
Tower→iOS handoff. Per `CLAUDE.md`, that is shared protocol truth. Deleting it
is a contract change with an iOS-side consumer question, not a line deletion,
and the roadmap prices it at zero.

**In fairness, the severity call is right even though the reason is wrong.**
`[MEASURED]` on my HEAD replay: 23 of 415 edges carry a non-null `r_h`, all in
0.44–0.51, **bit-identical across two fresh processes**, none anomalous. On
this capture the defect is dormant. I also independently reproduced the defect
itself with `repro_rate_fresh_process.py`: **34 of 40 fresh processes returned
a corrupt mask** (85%; the lead measured 30/40, Lane 1 37/40 — the spread is
itself consistent with the nondeterminism), with sums up to 20,770 on a
242-element binary mask.

**Correction:** keep the low priority; replace "never consumed" with "on the
wire and in the Tower→iOS contract, currently benign on this capture"; move
"delete `r_H`" out of Stage 2 and into a contract change, or downgrade it to
"document as dead and stop populating it."

### F10. Stage 1's effort estimate understates the blast radius.

"1–2 days, ~150–250 LOC ... the change is calling it three times and
accumulating." Reading the code, widening `_extend` from 1 reference to 3
touches, at minimum:

- `_Chain.__slots__` — `previous_features` is a **single** slot;
- `_Chain.forget_before`, whose docstring justifies `key[0] == index` on the
  ground that "**`_extend()` reads exactly one key shape**,
  `observed[(previous, f)]`", and carries a memory measurement (26.1 MB → 0.15
  MB unpruned vs pruned) that the change invalidates;
- the `claimed` de-duplication in `_extend`, which today cannot encounter two
  *different* landmarks claiming the same current feature from two different
  references — with three references it can, and there is no resolution rule;
- `_triangulate_new`, which takes exactly one previous pose and one projection
  matrix — with three references, which pair triangulates?
- the `base + offset` support-block bookkeeping, duplicated in
  `estimate_window()` and in the live path, where double-counting a
  re-observation across references silently corrupts `support.json`;
- the live/rebuild equivalence test the `_Chain` docstring names as the guard
  that the backend is still forward-only.

`[ESTIMATED]` ~1 week, not 1–2 days. The direction of the recommendation is
unaffected; the "first week delivers Stages 0–2" schedule is.

### F11. The re-baseline's causal attribution names the wrong commits.

The replay numbers are right — I reproduced them exactly (see Survivors). The
*attribution* is wrong. `[MEASURED]`, `git log tower/tower/world_builder/`:

- `6e60f76` (2026-08-25 **22:32:57**) "the tracker was losing reach, not losing
  the image" is the commit that took the walk **51 → 33**.
- `85d94a2` (23:09) reports in its own body "33 → 29 segments (448 → 408
  keyframes)" — *on top of the reach change* — and `1272b09` (23:31) **disabled
  that**, returning the walk to 33/448.
- `4136b2f` (2026-08-26 00:02) also postdates the session.

So "Two commits on 2026-08-25 already cut fragmentation 35%" is wrong: **one**
commit did, and it is not either of the two named. Stage 0's instruction ("the
current one predates `85d94a2` and `1272b09`") should name `6e60f76` and
`4136b2f`. The stale-baseline conclusion is unaffected.

### F12. Lead contamination is present — in the cost conclusions, not the measurements.

§5.5's defence is about *measurements* and it holds. I checked the populations:
Lane 1 works over 457 persisted keyframes / all 104,196 pairs; Lane 2 over raw
capture frames in sliding windows with union-find over tracks; both import only
the production detector and thresholds from `tower.world_builder.geometry`. No
shared harness, no shared statistic. **The convergence on "the graph, not the
network" is genuine.**

But `LEAD_SUPPLEMENT.md` does not only frame. It instructs:

> "Price Atlas-style multi-map adoption using the EXISTING scaffolding, not
> from scratch. **Any cost estimate that ignores this will be too high.**"

Stage 5 reproduces this almost verbatim — "Price this as *filling in declared
structure*, not as redesigning persistence" — and every effort figure in the
roadmap is `[E]`. **The part of the document the supplement steered is exactly
the part with no measurement behind it.** §5.5 defends the measurements and is
silent on the estimates. F10 is one instance of the resulting optimism.

The supplement also, to its credit, explicitly left the real gap open ("It does
NOT by itself prove covisibility-plus-BA would be valuable on THIS corpus"),
and §5.5's counter-argument acknowledges it is still open. That is honest and I
am not calling it contamination.

---

## SEVERITY 3 — wording and scope

**F13. Effective sample size.** The "200 pairs" null is 40 distinct source
frames × 5 rotation magnitudes, from **one capture**, selected as the 40
*sharpest* of a 400-frame sample. Independent n is 40 frames, not 200 pairs,
and sharpness selection biases toward the easiest frames. The 61.5% is not
sensitive to this — `[MEASURED]` excluding the 0.0° group it *rises* to
108/160 = 67.5% — but every percentile derived from it, including F1's
baseline/depth tail, inherits n = 40 from one apartment.

**F14. The 0.0° null is not "image A against image A."** §5.1.1 says it is.
`build_rotation_null_manifest.py` warps A by the identity homography, re-encodes
at JPEG q85, decodes, and writes that as B. It matters slightly: the 0.0° group
behaves unlike the others — `[MEASURED]` median `recip_R` 26.67° versus
0.035–0.09° for every non-zero angle — and the document does not explain the
inversion.

**F15. Two `[M-SYN]`-labelled tables are computed on the session the document
declares stale.** §5.2's gap-yield table (57.9 / 49.4 / 29.8 / 9.2 / 2.4) comes
from `verify_tensions.json`, whose own metadata reads `n_pairs: 104196,
n_edges: 8989` — the 457-keyframe census. §5.4's redaction table says so openly
("all 457 keyframes"). Stage 1's "why 3 and not 5" therefore rests on the stale
segmentation. I re-ran §5.4 at HEAD `[MEASURED, redaction_at_head.py]`:
**25 of 27** keyframes with ≤100 ORB features are >40% black fill, median black
fraction **0.750**, 57.4% of keyframes >10% black. **Tension 4 survives the
re-baseline and is marginally stronger than the 20-of-24 quoted.** §5.2 was not
re-run and should be.

**F16. `pyceres` is given two licences in one document.** Stage 4: "`pyceres`
2.6 ... **BSD-3** `[M-L1]`". §4.4: "`pyceres` **Apache-2.0**". The lead's own
`LICENSING_KEY_FINDINGS.md:93,109` says Apache-2.0; Lane 1 conflated the Ceres
core's BSD-3 with the Python binding. Both are permissive so there is no
exposure — but a licensing section must not carry two answers about a component
it recommends for production. Separately and more substantively: the document's
entire Ceres risk model is about **build flags** (`WITH_SUITESPARSE=ON` → GPL),
while the recommendation is a **prebuilt wheel**. Nobody established what the
`pyceres` 2.6 wheel links against. That question is open and should be closed
before Stage 4, not during it.

**F17. Stage 3's stop/go gates on a self-consistency number without saying so.**
Lane 1 is explicit (`bow_retrieval.py:24-25`): "Ground truth for retrieval is
the census's own geometrically VERIFIED edges. That is self-consistency, not
external ground truth." Retrieval is being bought to surface candidates ORB
cannot find by brute force; scored against ORB's own verified edges it can
neither pass nor fail for the right reason. §0.1 covers this globally; the
stage gate reads as an accuracy target and should restate it. Combined with §8
risk 6 (vocabulary trained in-domain on the corpus it is evaluated on) and §5.6
(one apartment, so a false-positive rate is unmeasurable), Stage 3's
"Recall@10 ≥ 60% at precision@5 ≥ 85%" is a circular gate.

**F18. Two small factual slips.** (a) Matrix row 13 and §4.3 conflate two DPVO
experiments: "1,848 poses, 16.93 fps, 682 MiB" is a **single stride-1 run with
no repeat** (`dpvo_stride1.json`), while the 12–38% reproducibility figure comes
from stride-2 repeats over 698–924 frames. (b) §4.1's rejection row "694 / 639
/ 32 / 35" has the last two swapped: `[MEASURED]` the HEAD replay gives
`tracking_degraded: 35, tracking_lost: 32`.

---

## Claims that survived attack, and what I did to break them

I tried to break each of these and could not. Every figure here is `[MEASURED]`
by me today unless marked.

**1. The re-baseline — the highest-priority target — is exactly right.**
I replayed the canonical 1,848 frames at HEAD in a fresh process, in my own
scratch directory, with no reference to the synthesis's output. Result:
**448 keyframes, 33 segments, 61 solved poses, 8,333 points**, rejections
`insufficient_motion 694 / blurred 639 / tracking_degraded 35 / tracking_lost 32`.
Identical to the synthesis's `repeat_A.json` on every field. Session artefacts
confirm the staleness independently: `keyframes.jsonl` mtime **2026-08-25
18:01**, derived geometry **2026-08-26 00:12**, and `6e60f76` / `85d94a2` /
`1272b09` / `4136b2f` all land after 22:32 the same evening. **The charter's
51-segment framing is stale and Stage 0 is correctly load-bearing.**

**2. Bit-for-bit reproducibility.** Two fresh processes: 448/448 pose records
identical after stripping the session id, 8,333/8,333 points identical at
**max |Δp| = 0.000e+00**, and `support.json` byte-equal — a check the synthesis
did not report. The `edges.jsonl` `r_h` column is also identical across runs.

**3. The 66.1% two-view figure — the arithmetic that explains BA-at-0.00%.**
Recomputed from my own replay's `support.json`: 8,333 landmarks, **5,512 seen
by exactly 2 views = 66.1%**, 2,821 seen by ≥3 = 33.9%, none seen by fewer than
2. The claim that BA had nothing to tighten is arithmetic and it holds.

**4. Production's covisibility.** 189 edges at ≥15 shared landmarks, **median
degree 5.5** over **72** geometry-bearing keyframes, **0 cross-segment**.
Exact.

**5. Lane 1's census at HEAD.** 8,021 edges of 100,128 pairs (8.01%), 4,820
cross-segment, 6,750 with parallax ≥0.5°, median degree 36, 14 isolated
keyframes. Every figure exact.

**6. Tension 1's headline. It is real, and it is as bad as stated.** I re-ran
`analyse_purerot_null.py`: **123/200 = 61.5%** accepted, median `recip_R`
**0.05°**, median E-inlier ratio **0.998**, **95.5%** clear the E term. I
audited the null construction and it is genuinely zero-baseline — the second
image is `warpPerspective(A, K R K⁻¹)` on a frame undistorted with the real
ChArUco calibration, so the translation is exactly 0 by construction. I checked
that `mast3r_pairs.py` was not modified for the run: its mtime is 22:39, the
null manifest was built at 23:42 and the run logged at 23:44. I tried to
inflate the result away by excluding the degenerate 0.0° group and it went
*up*, to 67.5%. **Lane 3's gate ranks fabricated translations above every
genuine link in the corpus, and a rotation-reciprocity gate is structurally
incapable of catching a fabricated translation. This survives completely.**

**7. Production scores 0.0% and Lane 2's transcription 13.0% on the identical
200 nulls.** Reproduced to the unit, and I went further and ablated the three
differences (F8) — which confirms rather than undermines the attribution.

**8. Connectivity, as a number.** 46 of 51 in the largest component with
exactly `[22, 40]` isolated on the stale session; 33 of 33 at HEAD. Both
reproduce under two independent criteria. (What it *means* is F5 / F6.)

**9. Lane 3's `seg6-30` zero and `seg0-45` non-zero.** Over all 100 keyframe
pairs between segments 6 and 30: max 13 Lowe matches, max 7 F-inliers,
**0 essential-matrix inliers**, 0 covisibility edges. Over all 32 pairs between
0 and 45: **32 covisibility edges, 211 F-inliers, 192 E-inliers**. Both exact.
The synthesis's deflation of Lane 3's flagship result is correct.

**10. Tension 4.** Survives the re-baseline and strengthens (F15).

**11. The mask defect.** Independently reproduced at 34/40 fresh processes.

**12. The DPVO reproducibility metric is sound.** I checked this specifically
because the raw trajectory extents in `dpvo_runs.json` differ by 2–7× between
repeat runs, which would have been a meaningless comparison. It is not: the
harness does an exact Umeyama Sim(3) alignment of camera centres and reports
RMS as a fraction of extent, which is the correct scale-free formulation for a
monocular system. **The case against learned VO stands.**

**13. Codebase arithmetic.** `tower/world_builder` is exactly **5,511** lines
across 16 files. 900–1,200 new lines is 16.3–21.8% growth; "roughly 20%" is
fair.

---

## What to change before this is handed to an engineer

Ordered by what blocks what.

1. **Do not schedule Stage 5 or Stage 6 against the §5.1.7 gate.** Replace the
   `baseline/depth > 0.05` term, or state honestly that no gate in this
   programme clears the 0% bar and that cross-segment registration is therefore
   not yet fundable. (F1)
2. **Re-derive Stage 1's degree stop/go** against the measured 14.0 ceiling, or
   drop it in favour of the ≥3-view criterion. (F2)
3. **Replace Stage 4's stop/go** with something evaluable at Stage 4 and
   compatible with having no ground truth. (F4)
4. **Restate §2 with the like-for-like 2.6× beside the 42×**, and restate
   connectivity at term-8 strength (28/33) beside 33/33, with the 11-of-33
   geometry-bearing figure. (F3, F5, F6)
5. **Re-price Stage 1 at ~1 week** and mark every effort figure as
   lead-steered. (F10, F12)
6. **Fix in place:** the commit attribution (F11), the gap>3 dominance reversal
   (F7), the `r_H` wire-contract status (F9), the `pyceres` licence and the
   unanswered wheel-linkage question (F16), the Stage 3 circularity note (F17),
   and the two slips in F18. Re-run §5.2's gap table at HEAD (F15).

None of these overturn the architectural conclusion. All of them are things an
engineer would otherwise discover by spending the budget.

---

## Reproduction

New, read-only, under `tower/scripts/research/slam_adversarial/`:

| file | what it does |
|---|---|
| `verify_head_replay.py` | two-view landmark fraction, production covisibility edges and degree, cross-run byte identity of poses / points / support |
| `ablate_gate.py` | the 2×2 RANSAC-method × inlier-set ablation over the 200 nulls and 447 real gap-1 keyframe pairs |
| `connectivity_under_gates.py` | segment connected components under five criteria, on both censuses |
| `redaction_at_head.py` | blackout fraction vs ORB count over the HEAD replay's 448 keyframes |

The replay I ran, twice, in fresh processes:

```
tower/.venv/Scripts/python.exe scripts/world_build_session.py \
  --root <scratch>/A \
  --frames data/captures/22e9d4289cb440fbb3f14e6da369a136/frames \
  --intrinsics data/world_builder/intrinsics/360x640.json --format json
```
