# Stage 0 — the reproducible baseline, and what nearly destroyed it

**Commit measured:** `d3d24b5` (`docs: the modern-SLAM research package, preserved as branch evidence`)
**Branch:** `world-builder/next-generation`
**Host:** Windows 11, 20 logical CPUs, Python 3.12.5, OpenCV 5.0.0, numpy 2.5.2
**Corpus:** the 8 PINNED prefixes, 9,372 frames at 360x640, real calibration
`data/world_builder/intrinsics/360x640.json` (fx 438.23, reprojection_rms 0.2893 px, 511 views)
**Captures that failed to process:** none. 8 of 8 pinned prefixes resolved to exactly
one directory each and all 8 completed.

Every number below is **MEASURED** by this run unless tagged **QUOTED**, in which
case it is repeated from prior research for comparison and was not re-derived here.

Artifacts:

- `tower/scripts/research/stage0_baseline/baseline_HEAD_d3d24b5.json` — the machine-readable baseline
- `tower/scripts/research/stage0_baseline/measure_baseline.py` — regenerates it in one command
- `tower/scripts/research/stage0_baseline/shipped_harness_d3d24b5.json` — the shipped harness's own output, kept as a cross-check

---

## 0. The finding that matters more than the baseline

**The first three attempts at this baseline measured a moving codebase, and it
read exactly like nondeterminism.**

The determinism gate failed on its first run. Replaying capture `22e9d428` in
three fresh processes produced two different reconstructions — 68 segments /
131 solved poses / 12,347 points versus 64 / 112 / 11,503 — with the same 448
keyframes. Over 15 fresh processes spread across an hour, both outcomes
appeared repeatedly, in no stable order.

It was not nondeterminism. The persisted keyframe images were **byte-identical
between a diverging pair (448 of 448)**, so nothing upstream of the solver had
moved. What had moved was the source: another lane in this overnight run was
committing to the same worktree. `git rev-parse HEAD` went from `d3d24b5` to
`beb4719` during the measurement, `backends/classical.py` (+230 lines) and
`geometry.py` (+36) changed, and `classical.py` was uncommitted-dirty at the
moment several of my child processes imported it. Commit `4e2d943` is titled
*"the corpus says keep it — 29 more solved poses"*; the corpus totals I
observed drifting were **591 → 620 solved poses**, +29 exactly.

Consequences for tonight, in order of importance:

1. **Every stage must measure from a pinned source tree, not the shared
   worktree.** This baseline was finally produced from `git archive d3d24b5`
   extracted to `C:\wb-src`, isolated from further commits. A Stage N run made
   from the live worktree is not comparable with anything.
2. `measure_baseline.py` now records `configuration.solver_source_sha256`
   (SHA-256 of `classical.py`, `geometry.py`, `engine.py`, `keyframes.py`,
   `frontend.py`), `git_head` and `git_status_porcelain` on every run. Code
   drift can no longer be invisible; it shows up as a changed hash.
3. The shipped comparator VOIDs a comparison when segments or keyframes move.
   Drift moved segments (230 → 232). That guard would have fired and been
   blamed on the change under test.

A second environmental hazard, found on the way and unrelated to drift:
**`redaction.DEFAULT_MODEL_PATH` is `Path("models")/...` — relative, resolved
against the process cwd.** Run from `tower/` the YuNet face detector is found
and every keyframe is redacted; run from the repository root it is not found
and the session records `redaction: none`. On `22e9d428` that is **112 vs 194
solved poses and 11,503 vs 19,376 points** — a 73% swing in solved poses from
nothing but the directory you launched from. The baseline is measured with
redaction **ON**, which is the configuration all prior research and the branch
status document used. `configuration.redaction_available` now records it.

### Reconciliation with the already-committed copy

While this was being finished, another lane committed an earlier draft of
`baseline_HEAD_d3d24b5.json` and wrote
`scripts/research/stage0_baseline/README.md` around it, correctly labelling the
repeat mismatch inside it as *"THE TRAP: not nondeterminism"*. The file on disk
has since been regenerated from the pinned tree. MEASURED comparison of the two:

| | committed draft | regenerated (pinned) |
|---|---|---|
| segments / keyframes / solved / refused / points | 230 / 1,712 / 591 / 891 / 75,369 | **identical** |
| legible / drawable / segments with geometry / largest segment | 91 / 94 / 102 / 29,890 | **identical** |
| exactly-2-view fraction | 0.703830487335642 | **identical** |
| points registered / clusters / reprojection observations | 7,520 / 2 / 185,897 | **identical** |
| `commit` recorded | `29bd35ef` (a drifted HEAD) | **`d3d24b5`** |
| `determinism.verdict` | NOT DETERMINISTIC (contaminated) | **DETERMINISTIC** |
| `configuration` block | absent | **present** |

**Every measured value is unchanged.** Only the provenance and the determinism
verdict differ, and both are corrections. The README's trap paragraph now
describes a condition the regenerated file no longer contains — the drift it
warns about is real and is documented in §0 here, but the artifact itself is
clean. That paragraph should be repointed at this document.

---

## 1. Determinism verdict — **DETERMINISTIC, with the source tree pinned**

MEASURED on the pinned `d3d24b5` tree, canonical capture `22e9d428`:

| check | result |
|---|---|
| fresh processes | 4 |
| keyframes / segments / solved / refused / points | 448 / 64 / 112 / 272 / 11,503 — identical in all 4 |
| `points.json` byte-identical | **yes** (single SHA-256 across all runs) |
| `support.json` byte-identical | **yes** |
| max abs delta point | **0.000e+00** |
| max abs delta pose (quaternion + translation) | **0.000e+00** |
| full-corpus runs compared | **3** (this run + 2 fresh re-runs of the shipped harness) |
| corpus totals across those 3 | identical on every capture and every field |

QUOTED, for comparison: the prior research claims *"8,333 / 8,333 points
identical to max |Δp| = 0.000e+00"* and `support.json` byte-equal across two
fresh processes. **That claim reproduces on this branch**, on a different
capture set, at 4 processes and 3 full-corpus runs.

The gate is therefore green — *conditional on pinning the source*. Unpinned, it
is not merely un-green, it is meaningless.

---

## 2. Headline baseline table (MEASURED, `d3d24b5`, 8 pinned captures)

| capture | frames | keyframes | rejected | segs | with geom | solved | refused | root | cascaded | points | blowup | legible | drawable | reproj median px |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| e1c52b9f | 996 | 160 | 836 | 10 | 9 | 145 | 5 | 5 | 0 | 22,520 | 4.64 | 7 | 8 | 0.450 |
| 22e9d428 | 1,848 | 448 | 1,400 | 64 | 25 | 112 | 272 | 51 | 221 | 11,503 | 3.09 | 21 | 21 | 0.453 |
| b35d8ab8 | 1,694 | 349 | 1,345 | 76 | 31 | 114 | 159 | 56 | 103 | 11,375 | 4.53 | 29 | 29 | 0.447 |
| 20ce3c23 | 1,709 | 285 | 1,424 | 22 | 8 | 75 | 188 | 17 | 171 | 10,259 | 4.96 | 7 | 7 | 0.562 |
| 2e6cffa2 | 1,395 | 240 | 1,155 | 29 | 16 | 52 | 159 | 20 | 139 | 4,317 | 3.11 | 15 | 16 | 0.370 |
| fe744b68 | 541 | 101 | 440 | 16 | 5 | 30 | 55 | 11 | 44 | 6,224 | 2.47 | 5 | 5 | 0.413 |
| 64f48114 | 527 | 75 | 452 | 9 | 6 | 53 | 13 | 6 | 7 | 8,641 | 4.93 | 6 | 6 | 0.466 |
| 4fea31e2 | 662 | 54 | 608 | 4 | 2 | 10 | 40 | 3 | 37 | 530 | 5.69 | 1 | 2 | 0.257 |
| **TOTAL** | **9,372** | **1,712** | **7,660** | **230** | **102** | **591** | **891** | **169** | **722** | **75,369** | **5.69 (worst)** | **91** | **94** | — |

`blowup` on the TOTAL row is the worst capture, not a sum. `scale_state` is
`unknown` for all 8 — every capture has more than one segment, and segments do
not share a unit. Backend `classical-sfm` on all 8, no downgrades.

**Integrity controls both fired correctly.** Negative (pure rotation, 12
keyframes, 2 segments): 0 solved poses, 0 points. Positive (strafe): 4 solved
poses, 1,560 points. No control failures.

### Supporting counts (MEASURED)

| quantity | value |
|---|---|
| keyframes rejected by reason | insufficient_motion 5,184 · blurred 2,271 · tracking_lost 119 · tracking_degraded 85 · no_motion_evidence 1 |
| poses: anchors / positioned | 230 / 693 |
| root refusal degeneracy | no_correspondence 80 · low_parallax 58 · pure_rotation 31 (= 169 roots) |
| points triangulated → published | 94,563 → 75,369 |
| points discarded | low_parallax 11,150 · high_reprojection 8,044 (= 19,194; 94,563 − 19,194 = 75,369 exactly) |
| largest segment points (absolute, summed) | 29,890 |
| mean largest-segment share | 0.394 |

---

## 3. Landmark support — the number the whole night turns on

MEASURED across all 75,369 published landmarks. An observation is a **distinct
keyframe view**, the same definition the prior research used.

| | value |
|---|---|
| landmarks | 75,369 |
| support rows | 186,778 |
| observations: min / median / mean / max | 2 / **2.0** / 2.48 / 13 |
| **exactly 2 views** | **53,047 — 70.4%** |
| ≥ 2 views | 75,369 — 100.0% |
| ≥ 3 views | 22,322 — 29.6% |
| ≥ 5 views | 3,225 — **4.3%** |
| landmarks with no support row | 0 |
| orphan support rows | 0 |

Full histogram (views → landmarks): 2 → 53,047 · 3 → 14,441 · 4 → 4,656 ·
5 → 1,796 · 6 → 777 · 7 → 348 · 8 → 177 · 9 → 70 · 10 → 31 · 11 → 13 ·
12 → 9 · 13 → 4.

Per capture the exactly-2-view share runs 57.5% (`20ce3c23`) to 84.2%
(`4fea31e2`); the median observation count is **2.0 on every one of the eight**.

QUOTED for comparison: **66.1% of 8,333 landmarks seen by exactly two views**,
measured on the canonical capture before the landmark gate landed. The branch
architecture audit flagged that the figure *"has not been re-measured against
gated output"* and that the direction of the shift was not predictable.

**MEASURED answer: it went up, not down — 66.1% → 70.4%**, on 9x the landmarks
across the whole pinned corpus. The gate did not improve multiplicity; it
removed points that were disproportionately the better-supported ones. Every
downstream conclusion that rested on the two-view share (bundle adjustment
measuring 0.00%, local maps being starved) is *strengthened*, not weakened, by
the re-measurement.

**A defect found while measuring this:** 803 distinct 2-D features are bound to
**more than one** landmark. Because `world_registration.read_segments` builds
its association as `{(frame, feature): point}`, **881 support rows are
invisible to every reader keyed that way** — including registration itself and
the reprojection block below (185,897 scored + 881 = 186,778 exactly). It is
0.43% of the table, so it changes no headline number, but it means the
association is not a function of (frame, feature) and anything assuming it is
will silently drop rows.

---

## 4. Covisibility (MEASURED)

A keyframe is `(segment, segment-local frame index)` — the only identity
`support.json` carries. Landmarks never cross a segment boundary, so this graph
is block-diagonal **by construction**.

| | value |
|---|---|
| keyframes total | 1,712 |
| keyframes appearing in the association | 693 |
| **keyframes contributing no observation at all** | **1,019 — 59.5%** |
| keyframe pairs sharing ≥ 1 landmark | 2,688 |
| keyframe pairs sharing ≥ 15 landmarks | 1,533 |
| median degree, per capture | 5, 5, 7, 7, 8, 10, 11, 11 |
| max degree | 23 |
| max shared landmarks in one pair | 717 |
| **cross-segment edges** | **0 — structurally impossible** |

QUOTED: prior research measured *189 covisibility edges, median degree 5.5 over
72 geometry-bearing keyframes, 0 cross-segment* on the canonical capture. The
corpus-wide MEASURED figures are larger in absolute terms (2,688 edges over 693
participating keyframes) and identical in shape: the median degree band 5–11
brackets the quoted 5.5, and the cross-segment count is still zero.

The single most actionable number here is **1,019 of 1,712 keyframes (59.5%)
contribute zero observations**. They were admitted, stored, and never produced a
landmark.

---

## 5. Registration (MEASURED — this branch persists it)

| | value |
|---|---|
| segments with geometry | 102 |
| **segments registered** | **6** |
| **points registered** | **7,520 of 75,369 — 10.0%** |
| **registered clusters** | **2** (3 segments each) |
| candidate pairs examined | 798 |
| pairs admitted | 5 |
| cycles checked | 1 |
| cycle refusals | 0 |
| captures with any registered cluster | 2 of 8 |
| registration wall time | 520.6 s of the run |

Per capture: `e1c52b9f` → 3 segments / 5,603 points / 1 cluster; `2e6cffa2` →
3 segments / 1,917 points / 1 cluster. The other six register nothing.

QUOTED, from the branch status document: *"e1c52b9f places 3 of 10 carrying
5,603 of 22,520 (25%) and 2e6cffa2 places 3 of 29 segments carrying 1917 of
4317 points (44%)"*. **MEASURED here: identical, to the point.** The branch's
committed registration claims reproduce exactly.

**Registered clusters is the metric to watch tonight, not registered segments.**
6 placed segments sounds like one map; it is two disjoint 3-segment islands in
two different captures, and 92 of 102 geometry-bearing segments are placed
nowhere at all.

---

## 6. Reprojection (MEASURED, RECONSTRUCTED — read the caveat)

No per-landmark residual is persisted anywhere. These are recomputed cold from
`poses.json` + `points.json` + `support.json` + the keyframe images, re-running
the same ORB call the backend used so feature indices line up.

| | value |
|---|---|
| observations scored | 185,897 |
| observations with no pose | 0 |
| observations unprojectable (behind camera) | 0 |
| mean, observation-weighted | **0.712 px** |
| median, per capture | 0.257 – 0.562 px |
| max | **143.99 px** |

Caveat that governs how this may be used: the published bar
(`geometry.MAX_LANDMARK_REPROJECTION_PX = 3.0`) is enforced on a landmark's two
**source** views only. Third views and re-observations were never gated, so the
143.99 px maximum is not a violated invariant — it is the size of the ungated
tail. Because the number re-runs ORB, it is a measurement of this host and this
OpenCV build, valid for A/B on this host and not a claim in the abstract.

---

## 7. Cost, for budgeting the rest of the night (MEASURED)

| phase | wall seconds |
|---|---|
| replay + build, 8 captures | 267.8 |
| registration, 8 captures | 520.6 |
| reprojection (31.1) + association analysis (3.5) | 34.7 |
| **full measure pass** | **832.1** |
| determinism, 4 fresh processes | 189.0 |
| corpus rerun stability, 2 fresh full-corpus runs | 387.5 |
| **total for one complete Stage 0** | **≈ 1,409 s (23.5 min)** |

The shipped harness alone, no extended metrics, is **141.6 s**. Registration is
62% of the extended run; `--no-registration` gets a full extended pass in about
5 minutes if a stage only needs support and covisibility.

Peak memory: **368.6 MB** process peak working set (`psutil`
`memory_info().peak_wset`). `tracemalloc` peak was 55.4 MB — Python allocations
only, which is why the working set is the number to read. Per determinism child
process: ~277 MB.

---

## 8. What is `null` and why

Nothing in the required list is unmeasured. Two fields are `null` by
construction and must not be read as zero:

- **`bbox_blowup`** is `null` whenever a capture has no points or a core with no
  extent. All 8 captures produced a value this run (`bbox_blowup_unmeasurable: 0`).
- **`largest_share`** is `null` for a capture with no published points. None this run.
- **`cycle_refusal`** is `null` on all 8 captures. Only one cycle existed
  anywhere in the corpus (`2e6cffa2`) and it was not grossly open, so no cluster
  was refused. `null` here means "no cluster was refused", not "not checked" —
  `cycles_checked: 1` records that the check ran.

`points_discarded` is populated (it was the field the shipped harness documents
as expected-absent); it now carries `low_parallax` and `high_reprojection`.

---

## 9. Regenerating this

```
# from a PINNED source tree, never the shared worktree
git archive <commit> tower | tar -x -C <scratch-src>
cp tower/scripts/research/stage0_baseline/measure_baseline.py \
   <scratch-src>/tower/scripts/research/stage0_baseline/
cd <scratch-src>/tower            # cwd matters: it decides face redaction
<venv>/python.exe scripts/research/stage0_baseline/measure_baseline.py \
    --label <label> --commit <commit> \
    --scratch C:\wb-stage0\<label> \
    --determinism-repeats 4 --corpus-repeats 2 \
    --out <out>.json
```

The output is structurally identical between stages, so two files can be diffed
field by field. Before believing any diff, check that
`configuration.solver_source_sha256` differs **only** in the files the stage
actually changed — that is the check whose absence cost this baseline three
runs.
