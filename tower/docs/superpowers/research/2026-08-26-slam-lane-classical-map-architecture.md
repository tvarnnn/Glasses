# Classical SLAM map architecture vs World Builder — what actually transfers

Lane: Agent 1, classical SLAM / map-graph architecture.
Date: 2026-08-26. Branch `integration/world-builder-lifecycle-v1`. Research only;
no production code was modified.

**Every number in this report is labelled.**
`[M]` = MEASURED by me, on this host, today — the harness is named.
`[Q]` = QUOTED from source or a paper, with a file:line or citation.
`[E]` = ESTIMATED, with the estimation method shown inline.
Unlabelled numbers do not appear.

**There is no ground truth.** No external room geometry, no reference trajectory,
no surveyed scale exists for this corpus. Every corpus measurement below is a
COMPARATIVE / SELF-CONSISTENCY measurement: it says whether two computations on
the same frames agree with each other, never whether either is right.

---

## 1. Verdicts

| # | Question | Verdict | Basis |
|---|---|---|---|
| 1 | Does our corpus contain the covisibility the classical stack needs? | **YES, abundantly.** Median achievable covisibility degree **40** per keyframe vs the **5** production actually builds. | [M] `covisibility_census.py`, all 104,196 keyframe pairs |
| 2 | Would covisibility reconnect the 51 segments? | **YES.** 51 segments collapse to **3 connected components, largest holding 49/51**. | [M] `analyse_census.py` Q4 |
| 3 | Are there loop-closure opportunities (revisits)? | **YES.** **3,399** verified edges separated by >30 s of capture; **2,023** by >60 s. | [M] `analyse_census.py` Q6 |
| 4 | Is the failure a sensor/capture ceiling? | **NO.** Refuted. The frames support ~30x more graph than production extracts. | [M] Q1–Q3 above |
| 5 | Is our "segment" the same thing as an ORB-SLAM3 Atlas "map"? | **NO — the analogy is misleading and should be retired.** | [Q] source + [M] segment stats |
| 6 | Should we gate on `r_H`? | **NO. Keep not gating.** But the current docstring's reason is wrong; the real reason is worse for `r_H`. | [M] `analyse_census.py` Q5 |
| 7 | Is reciprocity the false-match guard? | **YES, decisively.** AUC **0.985**; a 0.3 threshold rejects **100%** of geometry-less traps while keeping **69.8%** of good edges. | [M] `analyse_census.py` Q6c |
| 8 | Is monocular scale recoverable without IMU/stereo? | **NO. Never. Only drift-controlled.** ORB-SLAM3 agrees — it leaves scale free for MONOCULAR and its loop closure only stops scale *drifting*, it does not fix the gauge. | [Q] `System.cc:213`, `Sim3Solver.cc:373-388`; §11 |
| 9 | Would a DBoW-style keyframe database find our revisits? | **YES.** Recall@10 **73.0%** on long-gap revisits, Recall@50 **90.1%** cross-segment, precision@5 **91.5%** — from a 10,000-word vocabulary trained on our own frames in 10.7 s. | [M] `bow_retrieval.py`; §9 |
| 10 | Do we need ORB-SLAM3's 145 MB vocabulary? | **NO.** An in-domain vocabulary 4 orders of magnitude smaller works. | [M] §9 |
| 11 | Did ORB-SLAM3 build and run on our frames? | **NO.** Hard-blocked, administratively not technically. Exact wall in §3.1. | [M] `wsl_build_attempt.sh` |
| 12 | Are prebuilt ORB-SLAM3 Python bindings available? | **NO.** All three candidate PyPI names are unusable — one Linux ELF, two name collisions. | [M] wheel inspection, §3.2 |
| 13 | Is GPLv3 a blocker for shipping? | **YES for source, NO for ideas.** ORB-SLAM2/3, DSO, LDSO are all GPLv3. Nothing recommended here requires importing any of it. | §12 |
| 14 | Biggest single recommendation | **Build the covisibility graph. Nothing else in the classical stack is non-vacuous without it.** | §13.1 |

### The one-sentence finding

The frames already contain a densely connected, geometrically verified map graph;
World Builder throws it away by only ever asking one question — "does this
keyframe match the previous one?" — and the fix is to ask more questions, not to
get better answers.

### An incidental defect found while measuring (not a lane deliverable)

`tower/tower/world_builder/geometry.py::homography_ratio` reads an
**uninitialised OpenCV mask** on OpenCV 5.0, and it is **confirmed
non-deterministic**: [M] **37 of 40 fresh processes (92.5%)** return a
non-binary mask on the same real frame pair, with **36 distinct sums** — values
up to 21,851 on a **242**-element mask. The shipped function returns two
different answers (`None` ×49, `0.0` ×1) from 50 calls on one identical input.
Full repro, root cause and severity assessment in §8; standalone scripts
`repro_ransac_mask.py` and `repro_rate_fresh_process.py`. Reported, not fixed.

---

## 2. Correction to the shared brief

The brief states (prior finding B) that `PointBlock.support_views` is declared
and never populated, and that "there is no record on disk of which 2D feature in
which keyframe produced any 3D point."

**That is now stale.** [M] `git log` shows commit `4136b2f` — *"feat: record which
feature in which keyframe made each landmark"* — and the observation table is on
disk:

- `tower/tower/world_builder/backends/classical.py:235, :378, :392` populate
  `support_views` via `_support_table` / `_support_block`.
- `.../derived/dd5d13a2381e430db9b27c7da2cf2928/support.json` contains **31,101
  rows** of `[segment_index, frame_index, feature_index, point_index]` covering
  **12,023 landmarks** [M] `production_covisibility.py`.

This matters a great deal for cost: **the observation graph is already
persisted.** Building a covisibility graph is now a query over an existing table,
not a new measurement. The lead supplement's point — that this codebase
repeatedly declared the right structure and left it inert — holds, but this
particular structure has since been filled in.

---

## 3. Benchmarking: what I could and could not run

### 3.1 ORB-SLAM3 did not build. Here is exactly where it stopped.

Timeboxed attempt, harness `tower/scripts/research/slam_classical/wsl_build_attempt.sh`,
run against the WSL2 distro. All [M]:

- WSL2 **is** available: distro `ITSC-3146`, **Ubuntu 24.04.2 LTS**, gcc 13.3.0,
  **20 cores, 15 GB RAM, 952 GB free**. On paper a good build host.
- **`sudo` requires a password.** Non-interactive `sudo -n true` fails, so
  `apt-get install` — the normal and effectively only route to these
  dependencies — is unavailable to an agent.
- The distro is bare. Every single ORB-SLAM3 dependency is missing:

| Probe | Result |
|---|---|
| `/usr/include/eigen3/Eigen/Core` | MISSING |
| `/usr/include/GL/gl.h` | MISSING |
| `/usr/include/GL/glew.h` | MISSING |
| `/usr/include/X11/Xlib.h` | MISSING |
| `/usr/include/boost/serialization/serialization.hpp` | MISSING |
| `/usr/include/opencv4/opencv2/core.hpp` | MISSING |
| `/usr/include/python3.12/Python.h` | MISSING |
| `cmake` | not in PATH |
| `pip3` | **not installed** — so even the userspace `pip install cmake` fallback fails |

The build therefore stopped before the first `cmake` invocation. This is not a
partial failure with a diagnosis; it is a total absence of toolchain.

**A second, independent wall** exists even with dependencies present.
`CMakeLists.txt:33-35` [Q]:

```cmake
find_package(OpenCV 4.4)
   if(NOT OpenCV_FOUND)
      message(FATAL_ERROR "OpenCV > 4.4 not found.")
```

This host has **OpenCV 5.0.0** [M]. And ORB-SLAM3 still references the C-API
constant `CV_LOAD_IMAGE_UNCHANGED` at `src/LoopClosing.cc:2412` [M, grep], which
was removed in OpenCV 4. So the source needs patching for OpenCV 4, let alone 5.
It is also `-std=c++11` with `-march=native` (`CMakeLists.txt:11-24`) [Q].

**[E] Cost to actually get ORB-SLAM3 running on this footage** — method: sum the
independent blockers, each priced by the standard route:
1. A Linux box (or WSL) with **passwordless sudo / root** — this is an
   administrative decision, not engineering time.
2. `apt install` of Eigen3, Pangolin's GL/X11/GLEW stack, Boost.serialization,
   OpenCV 4.4–4.x, cmake — ~30 min.
3. Building Pangolin, DBoW2, g2o, then ORB-SLAM3 itself — ~30–60 min on 20 cores.
4. Patching the OpenCV-5 incompatibilities if OpenCV 4 is not used — unbounded;
   avoid by pinning OpenCV 4.
5. Writing a monocular dataset loader for our `frames.jsonl` + a `.yaml` with our
   real intrinsics — ~1 h.
**Total ~2–4 engineer-hours on a machine with root.** The blocker is
administrative, not technical. I judged spending the lane's budget fighting it a
worse trade than the measurements in §4, and I stand by that: the measurements
answered the lane's actual question and a successful ORB-SLAM3 run would not have.

### 3.2 No prebuilt Python bindings exist. All three candidates are traps.

[M], by downloading and inspecting each wheel:

| PyPI name | What it actually is | Usable? |
|---|---|---|
| `orbslam3` 0.0 | A `py3-none-any` wheel containing **`orbslam3.so`, a Linux ELF** (verified: magic bytes `7f 45 4c 46`). Wraps `hello-binit/ORB_SLAM3-PythonBindings`. METADATA declares `License: UNKNOWN` with a **BSD classifier** while wrapping GPLv3 code. | **No** — wrong OS, and a licensing-metadata hazard |
| `pyslam` 1.2.1 | **Name collision.** "Python implementation of Source Live Audio Mixer", AGPLv3, keywords `csgo,ffmpeg,dmenu`. Not Luigi Freda's pyslam. | **No** |
| `pypangolin` 0.8.0 | **Name collision.** A data-catalog client (`admin.py`, `auth.py`, `catalog.py`, `governance.py`). Not Pangolin. | **No** |
| `g2o-python` | No Windows wheel; pip resolves to nothing. | **No** |
| **`pyceres` 2.6** | **Genuine `cp312-cp312-win_amd64` wheel, 8.5 MB, only dependency numpy.** Resolves and would install clean here. | **YES** |

Two of the three SLAM-sounding names being unrelated packages is a real
supply-chain caution worth carrying into any future dependency decision.

### 3.3 What I ran instead

Reading the ORB-SLAM3 source cost nothing and was the single highest-value thing
in the lane — see §5–§7, all with file:line citations. And the corpus question
turned out to be answerable in pure Python/cv2 on the real frames, which is §4.

---

## 4. The decisive measurement: is the covisibility even there?

### 4.1 Why this is the question

The lead supplement establishes [Q, `docs/agent-handoffs/WORLD-BUILDER.md:452-457`
and `backends/classical.py:246-250`] that bundle adjustment was implemented and
measured at **0.00% drift improvement** at 16, 32 and 104 keyframes, because the
observation graph is a chain.

That result proves *BA-without-covisibility is worthless*. It does **not** prove
covisibility is *available*. Those are different claims and only the first had
been measured. Everything the classical stack offers — local BA, global BA, pose
graph optimisation, loop closure, map merging — derives its power from **cycles
in the observation graph**. If the frames cannot supply cycles, the entire
ORB-SLAM3 recommendation collapses and the honest answer is "sensor ceiling."

So I measured it.

### 4.2 Method

`tower/scripts/research/slam_classical/covisibility_census.py`.

Take the **457 keyframes the shipped tracker actually accepted** on the canonical
capture `22e9d4289cb440fbb3f14e6da369a136` (persisted session
`dd5d13a2381e430db9b27c7da2cf2928`), with the **51 segment labels it actually
assigned**, and match **every pair — all 104,196** — using the **same production
ORB detector** (`geometry.detect_and_describe`, 1500 features) and the **same
production Lowe ratio matcher** (0.75).

Nothing here is a better frontend. No learned matcher, no new descriptor, no
retuned threshold. **The only thing that changes is which pairs are asked.** That
is deliberate: it isolates the architectural variable.

Each pair gets fundamental-matrix RANSAC verification (3.0 px, 0.99), a
homography fit, an essential-matrix `recoverPose`, a **median triangulation
angle**, an `r_H`, and a **reciprocity count** (matches surviving matching in
both directions).

[M] Runtime: detect **2.0 s** (4.3 ms/keyframe); all-pairs **189.5 s** on 12
worker processes. Total under 3.5 minutes on CPU. No GPU used.

#### Methodology confirmation (verified by `robustness_check.py`)

Stated explicitly because this is where the result should be attacked:

| Claim | Verified |
|---|---|
| Full O(n²) sweep, **no sampling** | 104,196 pairs evaluated = C(457,2) = 457·456/2 = **104,196 exactly** [M] |
| ORB parameters unchanged | `nfeatures = 1500` = production `geometry.ORB_FEATURES` [M] |
| Matcher unchanged | Lowe ratio `0.75` = production `geometry.LOWE_RATIO` [M] |
| Edge threshold not retuned | `15` = production `geometry.MIN_INLIERS`, and independently ORB-SLAM3's `th=15` (`KeyFrame.cc:421`) [M]/[Q] |
| Parallax threshold not retuned | `0.5°` = production `geometry.MIN_TRIANGULATION_ANGLE_DEG` [M] |
| 189.5 s / 12 workers | for the **full** 104,196-pair sweep, not a subset [M] |

**No threshold was retuned to enlarge the result.** Every constant is either a
production constant read from `geometry.py` or an ORB-SLAM3 constant read from
its source.

One difference I must disclose rather than bury: the edge criterion uses
**fundamental-matrix** RANSAC at 3.0 px / 0.99 — which is production's own
setting in `geometry.homography_ratio` (`geometry.py:120-123`) — whereas
production's *pose* path uses `findEssentialMat` at 1.0 px / 0.999 followed by
`recoverPose`. §4.9 re-derives the headline under that stricter production
criterion.

### 4.3 Result 1 — the graph is dense, not a chain

[M] `analyse_census.py`:

| Quantity | Value |
|---|---|
| Pairs with any ratio-test match | 97,402 / 104,196 (93.5%) |
| **Covisibility edges** (≥15 verified F-inliers, ORB-SLAM3's threshold) | **8,989** (8.63%) |
| Essential-graph edges (≥100 inliers) | 1,674 (1.61%) |
| **Median covisibility degree per keyframe** | **40** |
| Mean / max / isolated | 39.3 / 127 / 13 keyframes |

Degree percentiles [M]: p10 = 6, p25 = 17, **p50 = 40**, p75 = 59, p90 = 74.

**Against what production actually built** [M] `production_covisibility.py`,
read directly off `support.json`:

| | Production builds | Frames support | Ratio |
|---|---|---|---|
| Covisibility edges ≥15 | **296** | **8,989** | **30x** |
| Median covisibility degree | **5** | **40** | **8x** |
| Keyframes carrying geometry | 113 / 457 | 444 / 457 (largest component) | — |
| Cross-segment edges | **0** (not representable) | **6,245** | ∞ |

### 4.4 Result 2 — the range distribution says *where* the missing edges are

[M] Of the 8,989 edges:

| Range | Edges |
|---|---|
| Consecutive keyframes — **what `_extend` already does** | **398** |
| Keyframe gap 2–5 | 1,248 |
| Keyframe gap 6–20 | 2,493 |
| Keyframe gap 21–100 | 3,170 |
| Keyframe gap >100 | 1,680 |
| **of which CROSS-SEGMENT** | **6,245** |
| cross-segment AND gap >20 | 4,756 |

Read that first row against the total. **Production's entire matching strategy
covers 398 of 8,989 available edges — 4.4%.** The other 95.6% are free: same
detector, same matcher, same frames, never asked for.

### 4.5 Result 3 — the edges carry baseline, not just appearance

This is the trap the prior lanes correctly warned about: two keyframes can share
300 verified features and carry no parallax, in which case the edge constrains
rotation and nothing else. So every edge also got a median triangulation angle,
against production's own criterion `MIN_TRIANGULATION_ANGLE_DEG = 0.5`.

[M]:

| Subset | n | Median angle | Fraction ≥0.5° |
|---|---|---|---|
| Consecutive keyframes | 391 | 1.048° | 67.5% |
| Keyframe gap 2–20 | 3,681 | 2.116° | 78.2% |
| **Keyframe gap >20** | 4,702 | **7.268°** | **94.8%** |
| **Cross-segment** | 6,070 | **5.698°** | **91.2%** |

**Geometrically useful edges (≥15 inliers AND ≥0.5° parallax): 7,600 — 84.5% of
all edges** [M]. Median *useful* degree: **35**.

The direction of this result is the important part and it is the opposite of the
intuition: **the distant edges are the good ones.** Consecutive keyframes are the
*worst*-conditioned pairs in the corpus (median 1.048°, only 67.5% usable),
because consecutive keyframes are where the baseline is shortest. Production
matches exclusively against the one class of pair with the least parallax.

This also refines the brief's "54.7% of failing pairs are baseline-limited."
That figure is about pairs *production tried*. Across the whole corpus, baseline
is available — it is just not available *between adjacent keyframes*.

### 4.6 Result 4 — the segments weld back together

[M] Connected components over the 51 production segments, where an edge exists
if any keyframe pair across two segments clears the threshold:

| Edge set | Components | Largest |
|---|---|---|
| Production today | **51** | 1 segment |
| Edges ≥15 inliers | **3** | **49 / 51 segments** |
| Edges ≥15 AND parallax ≥0.5° | **3** | **49 / 51 segments** |
| Edges ≥100 (essential-graph strength) | 28 | 16 / 51 |

At keyframe level: **14 components, largest holding 444 / 457 keyframes** [M].

Note the third row especially. Requiring *geometric usefulness* as well as
appearance overlap does not degrade the result at all — still 3 components,
still 49/51. The reconnection is not an artifact of counting weak edges.

Also [M]: of the 9 singleton segments (one keyframe each), **8 have a
cross-segment covisibility edge ≥15**. Only **2 of 51** segments have no
cross-segment edge at all.

### 4.7 Result 5 — revisits exist, so loop closure is not vacuous

[M] Edges by capture-time separation (fps 11.99):

| Separation | Edges | With usable parallax |
|---|---|---|
| >5 s | 6,362 | 5,711 |
| >10 s | 5,223 | 4,733 |
| >30 s | 3,399 | 3,159 |
| **>60 s** | **2,023** | **1,894** |

Strongest long-gap links [M] cluster around segments 45 / 48 / 50 — e.g.
kf 394 (seg 45) ↔ kf 414 (seg 48), 386 frames apart (32.2 s), 290 matches,
267 F-inliers, 5.74° parallax. That is a textbook loop closure, sitting
unexploited in a 154-second capture.

**This is a first-class finding and it went the way that keeps the
recommendation alive.** Had the corpus contained no revisits, the Atlas /
loop-closure recommendation would have collapsed. It does not.

### 4.8 Why BA measured 0.00%, in one number

[M] `production_covisibility.py`, views per landmark across all 12,023
persisted landmarks:

| Views | Landmarks | Share |
|---|---|---|
| **2** | **8,079** | **67.2%** |
| 3 | 2,346 | 19.5% |
| 4 | 863 | 7.2% |
| ≥5 | 735 | 6.1% |

Median 2, mean 2.59, max 16. **Only 32.8% of landmarks are seen by more than 2
keyframes.**


A landmark seen by exactly two views contributes **zero** redundancy: its
triangulation is exactly determined, and BA can move the point to satisfy both
rays perfectly regardless of where the cameras are. Two-thirds of our map is
therefore invisible to bundle adjustment by construction. The measured 0.00% was
not a tuning failure or a solver failure. It is arithmetic.

(One nuance worth recording: production's graph is no longer a *pure* chain.
[M] 202 of its 296 edges have span >1, because `_extend` chains landmarks
forward and a landmark re-observed at i+1, i+2 accumulates views. The handoff
doc's "median covisibility span is 1" is now slightly pessimistic. The
*degree* — median 5 — and the two-view landmark share are the binding limits.)

---

### 4.9 Robustness: the conclusion survives every tightening

`robustness_check.py`. Columns: edges, of which cross-segment, median
covisibility degree, connected components over the 51 segments, and segments in
the largest component. All [M].

| Criterion | Edges | Cross-seg | Med. deg | Comps | Largest |
|---|---|---|---|---|---|
| F-inliers ≥15 **[headline]** | 8,989 | 6,245 | 40 | **3** | **49/51** |
| F-inliers ≥30 | 5,171 | 2,894 | 21 | 12 | 37 |
| F-inliers ≥50 | 3,521 | 1,661 | 14 | 19 | 27 |
| F-inliers ≥100 | 1,674 | 504 | 5 | 28 | 16 |
| **recoverPose inliers ≥15 — production's own pose criterion** | **6,521** | **4,368** | **28** | **4** | **46/51** |
| recoverPose ≥30 | 3,569 | 2,075 | 13 | 13 | 38 |
| recoverPose ≥50 | 2,030 | 1,105 | 6 | 22 | 24 |
| E≥15 AND parallax ≥0.5° | 5,623 | 3,964 | 25 | 4 | 46 |
| E≥30 AND parallax ≥1.0° | 2,659 | 1,669 | 9 | 13 | 38 |
| **E≥50 AND parallax ≥1.0° AND reciprocity ≥0.3** (harshest) | **1,506** | **867** | 4 | 23 | 23 |
| **Production actually builds** | **296** | **0** | **5** | **51** | **1** |

**Under production's own essential-matrix pose criterion the headline barely
moves: 6,521 edges (22x production's 296), 4,368 of them cross-segment against
production's zero, and the 51 segments still collapse to 4 components holding
46 of 51.**

Even under the harshest stack I could construct — essential-matrix inliers ≥50
*and* ≥1° parallax *and* ≥0.3 reciprocity — there are still **867 cross-segment
edges where production has none**, and 23 segments still merge into one
component. The qualitative conclusion is not threshold-sensitive.

(The median-degree column crosses production's 5 at the harshest setting, but
that comparison is apples-to-oranges: production's degree is measured over only
the 113 geometry-bearing keyframes, mine over all 457. The cross-segment count
and the component collapse are the robust comparisons.)

---

## 5. Q1: How do these systems recover from tracking loss?

### ORB-SLAM2: relocalize into the same map, or nothing

ORB-SLAM2 has exactly one map. On loss it enters a relocalization loop querying
the keyframe database, and until it succeeds it produces nothing. If the user
walks into a genuinely new area, ORB-SLAM2 cannot recover: there is nowhere to
put new keyframes.

### ORB-SLAM3: a three-tier ladder, and the old map is *kept*

[Q] All citations from the local clone, commit `4452a3c4`.

**Tier 1 — RECENTLY_LOST: keep trying, in the same map.**
State enum `Tracking.h:121-129`: `SYSTEM_NOT_READY, NO_IMAGES_YET,
NOT_INITIALIZED, OK, RECENTLY_LOST, LOST, OK_KLT`.

The timeout is **sensor-dependent, and this is easy to get wrong**:
- Inertial: `time_recently_lost = 5.0` s (`Tracking.cc:48`), checked at `:1993`.
- **Pure visual (our case): a hardcoded `3.0f`** at `Tracking.cc:2006`, and
  crucially the check is `if(mCurrentFrame.mTimeStamp-mTimeStampLost>3.0f && !bOK)`
  — it only gives up if `Relocalization()` (`:2003`) *also* failed.

While RECENTLY_LOST the system relaxes: search radius widens to `th=15`
(`Tracking.cc:3410-3411`), and `TrackLocalMap` succeeds on only **10** inliers
(`:3033`) versus the normal visual threshold of **30** (`:3057`).

**Tier 2 — LOST with a substantial map: start a NEW map, keep the old one.**
`Tracking.cc:2014-2032` and `:2271-2289`:

```cpp
2019:      if (pCurrentMap->KeyFramesInMap()<10)
2021:          mpSystem->ResetActiveMap();      // discard
2023:      }else
2024:          CreateMapInAtlas();              // KEEP the old map, start a new one
```

`Atlas::CreateNewMap()` (`Atlas.cc:58-77`) does **not** delete the old map. It
calls `mpCurrentMap->SetStoredMap()` — which only flips `mIsInUse = false`
(`Map.cc:209-212`) — leaves it in `mspMaps`, and allocates a new active map.
The old map remains a first-class merge candidate forever.

**Tier 3 — LOST with a trivial map: discard it.** The threshold is **10
keyframes**, appearing at `Tracking.cc:1966` (`>10` to be eligible for
RECENTLY_LOST at all), `:2019` (`<10` → discard), and `:2273` (`<=10` → discard).
[Q] Note the shipped off-by-one: a map with *exactly* 10 keyframes is stored by
one path and discarded by the other.

### What this means for us

Our engine has **no tier at all**. `engine.py:240-252`: on `decision.lost` it
resets the tracker, increments `self._segment_index`, and continues. There is no
relocalization attempt, no timeout during which recovery is tried, no
minimum-size discard, and no record that the previous segment is a merge
candidate.

Combined with the prior finding [Q, brief §A, from
`2026-08-26-segment-fragmentation.md`] that **94% of our 50 tracking-loss events
happened on frames the tracker could still follow** (median consecutive-frame
survival 0.634 at the loss; only 3 of 50 were genuine frame-to-frame breaks), the
comparison is stark: ORB-SLAM3 spends 3 seconds
and a widened search radius trying not to break the map, and we break it
immediately on a single gate.

---

## 6. Q2: Degenerate pairs, initialization, and whether we should gate on r_H

### ORB-SLAM3's H/F selection survives — but the threshold is 0.50, not 0.45

[Q] `TwoViewReconstruction.cc:112-128`:

```cpp
113:        if(SH+SF == 0.f) return false;
114:        float RH = SH/(SH+SF);
116:        float minParallax = 1.0;
118:        // Try to reconstruct from homography or fundamental depending on the ratio (0.40-0.45)
119:        if(RH>0.50) // if(RH>0.40)
```

So the answer to "what did ORB-SLAM3 replace from ORB-SLAM2's r_H heuristic" is:
**nothing — it kept it, and retuned it from the paper's 0.45 to 0.50**, leaving
the stale comment behind. Anyone reimplementing from the ORB-SLAM2 paper gets
0.45 and silently diverges from shipped behaviour.

Note also that r_H is **not a rejection gate in ORB-SLAM3 — it is a model
selector.** It chooses *which reconstruction to attempt*, `ReconstructH` vs
`ReconstructF`. Both branches then face much harder gates [Q]:
- `minParallax = 1.0` degrees and `minTriangulated = 50` for both (`:122`, `:127`).
- `ReconstructF`: needs `maxGood >= max(0.9*N, 50)` and no ambiguity
  (`nsimilar>1` where a rival scores `>0.7*maxGood`) — `:505-523`.
- `ReconstructH`: needs `secondBestGood < 0.75*bestGood && bestParallax >=
  minParallax && bestGood > minTriangulated && bestGood > 0.9*N` — `:725`.

Plus, in `Tracking::MonocularInitialization` [Q]: reference frame needs **>100
keypoints** (`:2454`), the second frame aborts if **≤100** (`:2483`), and
**≥100 matches** are required (`:2495`). The initial extractor runs at **5× the
normal feature budget** (`:601`). After initialization, a full BA of **20
iterations** runs immediately (`:2580`), and the map is thrown away if
`medianDepth<0 || pKFcur->TrackedMapPoints(1)<50` (`:2589`, comment: "originally
100 tracks").

**On failure, ORB-SLAM3 does not create a map and does not reset.** It clears
`mbReadyToInitializate` and re-arms from the next frame (`:2485`). It simply
refuses to start until the geometry is good. That is a strictly better policy
than starting a segment that will never solve — and 32 of our 51 segments
contain zero triangulated points [Q, brief].

### Should we gate on r_H? Measured answer: NO, keep not gating

The repo's docstring says r_H "saturates at 0.471-0.499 across the full range" on
synthetic scenes and "separates nothing." I measured it on **real frames**, on
all 8,989 verified edges, against the ground-truth-free but objective criterion
of median triangulation angle.

[M] `analyse_census.py` Q5:

| Quantity | Value |
|---|---|
| n | 8,989 |
| median r_H | 0.435 |
| p5 / p95 | 0.300 / 0.495 |
| r_H on **good**-parallax edges (n=7,600) | median **0.426** |
| r_H on **low**-parallax edges (n=1,174) | median **0.475** |
| Separation | 0.049 |
| **AUC as a low-parallax detector** | **0.765** |

**The docstring is slightly too harsh: r_H is not noise (AUC 0.765, not 0.5).**
It carries real signal. But the operating points are all bad [M]:

| Gate | Catches (low-parallax) | Cost (good edges discarded) |
|---|---|---|
| `r_H > 0.45` (ORB-SLAM2 paper) | 74.9% | **34.8%** |
| `r_H > 0.47` | 56.4% | 20.7% |
| `r_H > 0.50` (ORB-SLAM3 shipped) | **1.4%** | 2.5% |

The paper's 0.45 throws away **more than a third of our good edges**. ORB-SLAM3's
0.50 catches essentially nothing on our data (1.4%). There is no threshold that
buys much.

**And the decisive point: we do not need r_H, because we already compute
something strictly better.** `median_triangulation_angle_deg` measures the
quantity r_H is a weak proxy for, directly, and production already calls it with
a threshold of 0.5°. Using an AUC-0.765 proxy when the actual quantity is in hand
is a downgrade.

**Recommendation: keep computing r_H for continuity, keep not gating on it, and
add a line to the docstring that it was measured on real frames at AUC 0.765 —
informative but dominated by the triangulation angle already in use.**

---

## 7. Q3/Q4/Q5: covisibility, merging, and the false-positive guards

### 7.1 What the covisibility graph buys that a chain cannot

[Q] `KeyFrame.h:460-471` — three parallel structures:

```cpp
460:    std::map<KeyFrame*,int> mConnectedKeyFrameWeights;   // ALL, unthresholded
461:    std::vector<KeyFrame*> mvpOrderedConnectedKeyFrames; // >=15, sorted desc
462:    std::vector<int> mvOrderedWeights;
468:    KeyFrame* mpParent;                                  // spanning tree
469:    std::set<KeyFrame*> mspChildrens;
470:    std::set<KeyFrame*> mspLoopEdges;
471:    std::set<KeyFrame*> mspMergeEdges;
```

Edge threshold **`th = 15`** shared map points (`KeyFrame.cc:421`, used at `:436`).
There is a mandatory fallback at `:443-447`: if nothing clears 15, link the
single best neighbour anyway — **guaranteeing the covisibility graph is never
disconnected**, which the spanning tree depends on. That is a design decision
worth copying.

Three graphs, three jobs [Q]:
1. **Covisibility graph** (≥15) — defines the *local map*: `LocalBundleAdjustment`
   optimises the current keyframe plus `GetVectorCovisibleKeyFrames()`
   (`Optimizer.cc:1125-1132`), with any *other* keyframe observing those points
   added as a **fixed** camera (`:1163-1179`). It **aborts if there are no fixed
   keyframes at all** (`:1182-1186`) — ORB-SLAM3 explicitly refuses to run BA
   when there is no redundancy, which is precisely our 0.00% situation.
2. **Spanning tree** (`mpParent`) — a connected backbone for cheap propagation.
3. **Essential graph** — spanning tree + loop edges + covisibility edges above
   **`minFeat = 100`** (`Optimizer.cc:1530`), optimised as a **Sim(3) pose graph**
   with `BlockSolver_7_3`, 20 iterations (`:1509-1514`, `:1731`).

**The specific thing a chain cannot express: a cycle.** Pose graph optimisation
distributes error around loops; on a tree every configuration is consistent, so
there is nothing to distribute. This is exactly why our BA measured 0.00%, and
exactly why "add BA" was the wrong instinct and "add covisibility" is the right
one. The repo's own instruction — *"Do not add pycolmap; add covisibility
first"* — is correct and should be honoured.

### 7.2 Place recognition and the false-positive guards

[Q] The keyframe database is an **inverted index** — `KeyFrameDatabase.h:91`,
`std::vector<list<KeyFrame*>> mvInvertedFile`, sized to the vocabulary
(`KeyFrameDatabase.cc:35`). **It is global across all maps** (one instance,
`System.cc:213`) — this is the mechanism that makes cross-map merge detection
possible at all.

**Loop vs merge is decided purely by map identity** [Q]
`KeyFrameDatabase.cc:717-724`: candidate in the same map → loop (correct in
place); different map → merge (fuse). *The geometric verification pipeline is
identical for both* — `DetectCommonRegionsFromBoW` is called twice with different
candidate vectors (`LoopClosing.cc:507`, `:512`). That is an important
simplification: **you do not need two algorithms.**

**The guard ladder** [Q], thresholds at `LoopClosing.cc:581-585`:

| # | Guard | Constant | Cite |
|---|---|---|---|
| 0 | Map must be big enough to bother | **12 keyframes** (5 stereo) | `:348-356` |
| 1 | **Covisibility exclusion** — abort if the candidate is already covisible with the query | — | `:628-641` |
| 2 | BoW matches, pooled over candidate + 10 covisibles | **≥20** | `:581`, `:691` |
| 3 | Sim(3) RANSAC inliers, 300 iters | **≥15** | `:582`, `:699` |
| 4 | Projection matches with coarse Sim3 (r=8, ratio 1.5) | **≥50** | `:584`, `:755-758` |
| 5 | `OptimizeSim3` inliers | **≥20** | `:583`, `:767-769` |
| 6 | Projection matches with refined Sim3 (r=5, ratio 1.0) | **≥80** | `:585`, `:777-779` |
| 7 | **Spatial consistency** across ≥3 covisible keyframes of the query | **3** | `:819-847` |
| 8 | **Temporal consistency — 3 CONSECUTIVE confirming keyframes** | **≥3**, reset after 2 misses | `:396`, `:408-413` |
| 9 | Merge sanity: scale must be near unity | **0.90–1.1** | `:144` |

That is **nine independent gates**, and the two most powerful — covisibility
exclusion (#1) and temporal consistency (#8) — are *structural*, not
photometric. Gate #8 in particular: a false positive must recur on three
consecutive keyframes to fire, and two consecutive misses zero the counter.

[Q] Worth knowing: `mnCovisibilityConsistencyTh` (`LoopClosing.h:172`) is
**vestigial** — assigned 3, never read. The live constant is the literal `3`.
And ORB-SLAM2's covisibility-derived `minScore` gate is **gone** from
ORB-SLAM3's live path — `LoopClosing.cc:480-481` computes
`vpConnectedKeyFrames` and never uses it. The temporal consistency check
replaced it.

### 7.3 Our own measurement: reprojection is not a guard, reciprocity is

The prior lane proved a wrong Sim(3) can reproject at 1.62 px median and be wrong
by 3.2x in scale. I set out to find what *does* separate a true link from a
false one, using the census.

**First, the trap population is real** [M] `analyse_census.py` Q6b: of 46,386
pairs offering ≥8 ratio-test matches, **8,656 (18.7%) produce no fundamental
matrix at all**, and **103 pairs offer ≥100 matches yet admit no consistent
two-view geometry**. Those are exactly the repetitive-indoor-texture false
positives a naive match-count threshold would accept. (The kf12↔kf190 pair I hit
while debugging offered **242** ratio-test matches and fits neither H nor F.)

**Second, reciprocity separates them almost perfectly** [M] `analyse_census.py`
Q6c. Reciprocity ratio = (matches surviving matching in both directions) /
(forward matches):

| Population | n | Median reciprocity |
|---|---|---|
| Verified-good edges (≥15 inliers, ≥0.5° parallax) | 7,600 | **0.392** |
| Geometry-less traps (≥50 matches, no F fit) | 328 | **0.000** |

**AUC = 0.985.** Operating points [M]:

| Threshold | Keeps good edges | Admits traps |
|---|---|---|
| 0.3 | **69.8%** | **0.0%** |
| 0.5 | 26.0% | 0.0% |
| 0.7 | 1.7% | 0.0% |

**A reciprocity threshold of 0.3 rejects every single trap while keeping 70% of
genuine edges.** This directly confirms and extends the prior finding, and it is
cheap: one extra `knnMatch` in the reverse direction, which doubled the census's
matching cost from ~95 s to 189 s across 104,196 pairs — [E] ~0.9 ms per pair per
core, by dividing measured wall time by pairs and multiplying by workers.

**This should be the first guard in any registration path we build**, ahead of
anything reprojection-based.

### 7.4 The merge sequence, concretely

[Q] `LoopClosing::MergeLocal()`, `LoopClosing.cc:1215-1780`. Welding window
`numTemporalKFs = 25` (`:1217`).

1. Abort any running global BA; stop LocalMapping and drain its queue
   (`:1231-1256`).
2. Build the **current-side welding window**: 25 best covisibles + current
   keyframe (`:1307-1309`), grown by up to 5 rounds of covisibility expansion
   (`:1312-1331`); harvest their map points (`:1333-1340`).
3. Build the **merge-side window** symmetrically (`:1344-1400`).
4. Compute corrected poses for the whole current-side window into *staging*
   fields `mTcwMerge` / `mfScale` (`:1420-1465`) — nothing is committed yet.
5. **Commit** under both map mutexes (`:1506-1557`): move keyframes and map
   points into the target map, then
   `mpAtlas->ChangeMap(pMergeMap); mpAtlas->SetMapBad(pCurrentMap);` (`:1550-1551`).
   This is the **only** place a map is marked bad.
6. **Rebuild the spanning tree** by walking the old parent chain and inverting it
   (`:1560-1574`).
7. `SearchAndFuse` duplicate landmarks; `UpdateConnections()` on both windows
   (`:1588-1605`).
8. **Welding local BA** (`:1616-1628`) — the 4-arg `LocalBundleAdjustment`
   (`Optimizer.cc:3498`) where the merge-side keyframes are **fixed** and the
   current-side window is free.
9. Then the **non-critical remainder**: essential-graph pose optimisation over
   the merged map (`:1715-1718` — **skipped for pure monocular**) and transfer of
   the remaining keyframes (`:1721-1750`).

So the canonical order is: **place recognition → Sim(3) → welding-window
commit → local BA (merge side fixed) → pose graph over the rest.** The staging
pattern in step 4 is notable and matches our repo's stated intent that
registration be non-destructive.

[Q] Sim(3) itself is **Horn 1987 closed-form on unit quaternions, minimal set of
3 point pairs** (`Sim3Solver.cc:311-314`, `:175`), RANSAC `(0.99, 15, 300)`
(`LoopClosing.cc:699`), inlier test a **symmetric** reprojection check in both
images against χ²(2, 0.99) = 9.210 scaled per octave (`Sim3Solver.cc:99-100`,
`:431`). **Symmetric** — i.e. reciprocity again, in geometric form.

---

## 8. The OpenCV 5.0 defect I hit while measuring

Reported because it is live in production, not because it is this lane's topic.
I did **not** fix it.

**What happens** [M] `debug_api.py`, `debug_mask.py`: on OpenCV 5.0.0, when
`cv2.findFundamentalMat` / `cv2.findHomography` **fail to fit a model**, they
return `model = None` and leave the output mask **uninitialised**. On the
kf12↔kf190 pair (242 matches) the returned mask had unique values
`[0, 1, 4, 5, 16, 36]` — not a 0/1 mask — and summed differently across runs.

**Why it matters** — `geometry.py::homography_ratio` discards the model:

```python
_, h_mask = cv2.findHomography(points_a, points_b, cv2.RANSAC, 3.0)
_, f_mask = cv2.findFundamentalMat(points_a, points_b, cv2.FM_RANSAC, 3.0, 0.99)
h_inliers = int(h_mask.sum()) if h_mask is not None else 0
```

The mask is not `None` when the model is `None`, so the guard does not fire and
`.sum()` reads whatever was in the buffer.

### 8.1 The exact repro

Harness: `repro_ransac_mask.py` (single process) and
`repro_rate_fresh_process.py` (rate across fresh processes).

| Item | Value |
|---|---|
| Capture | `22e9d4289cb440fbb3f14e6da369a136` |
| Session | `dd5d13a2381e430db9b27c7da2cf2928` |
| Keyframe A | index 12, id `...:00000345`, `images/00000345.jpg`, segment 3 |
| Keyframe B | index 190, id `...:00001824`, `images/00001824.jpg`, segment 18 |
| `points_a` / `points_b` | **`dtype=float32`, `shape=(242, 2)`, C-contiguous** — straight out of production `match_descriptors` |
| Call | `cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)` — verbatim `geometry.py:122` |

### 8.2 Root cause — why synthetic degenerate configurations do NOT reproduce it

[M] **Keyframe B has only 5 ORB features.** The Lowe ratio test still returns
**242 matches**, because 1,321 features in A each pick a nearest neighbour among
B's 5 descriptors. Those 242 matches land on **3 distinct point locations in B**
(240 distinct in A).

F needs 8 points in general position; H needs 4. **Three distinct points cannot
support either**, so RANSAC exhausts its iterations and returns `model = None`
*without ever writing the mask* — which is the code path that exposes the
uninitialised buffer.

This is why the lead's four synthetic constructions stayed clean: identical point
sets, collinear points, all-same-point and near-zero-translation planar configs
are *degenerate but well-populated*, and OpenCV's RANSAC still produces a model
(or writes the mask) for them. **The trigger is not degeneracy in the geometric
sense — it is a total fit failure combined with a cold buffer.**

Input layout was ruled out [M]: float32 (N,2), float32 (N,1,2), float64 (N,2)
and a non-contiguous strided view all behaved identically. **It is not a
dtype/shape issue.**

### 8.3 It is non-deterministic — the decisive test

**Within one process** [M], 50 identical calls on the identical arrays:

- Trial 0: `F_model=None`, mask `dtype=uint8 shape=(242,1)`,
  `unique[:8]=[0, 32, 45, 48, 49, 50, 51, 52]`, **46 distinct values**,
  **`sum=9552`** on a 242-element mask.
- Trials 1–49: `sum=0`, clean.

So the buffer is dirty on **first use** and zeroed thereafter — which is exactly
why it is hard to reproduce in a warm process.

**Across fresh processes**, one call each [M] `repro_rate_fresh_process.py`, n=40:

> **GARBAGE (non-binary mask or sum > n): 37/40 = 92.5%**, with **36 distinct
> sums** observed — 2109, 2975, 3641, 3850, 7511, 9552, 9667, 9930, 10009,
> 10111, 10174, 10585, … 21822, 21851. Three runs came back clean (sum 0).

**A binary mask over 242 elements can never sum above 242.** Values above 20,000
are uninitialised memory, and the sum differs on every run. **This is
non-deterministic**, and by the lead's own criterion it is therefore a genuine
production defect rather than a merely surprising deterministic one.

**The shipped function inherits it** [M]: `geometry.homography_ratio()` called 50
times on the identical input returned **`None` 49 times and `0.0` once** — two
different answers from one input. The healthy control pair
(`00000345.jpg` vs `00000353.jpg`, 334 matches) returned `0.4099` on all 50 calls
and a single stable `(model_ok, sum)` outcome, confirming the instability is
specific to the failed-fit path.

### 8.4 Blast radius and fix

[M]: `findFundamentalMat` returns `None` on **8,656 of 46,386** (18.7%)
candidate pairs in the census; `findHomography` on 2,687 (5.8%). So r_H is
unreliable on roughly a fifth of pairs — and *disproportionately on the
degenerate pairs it exists to flag*.

**It is not currently load-bearing** because r_H is computed and never gated
(§6), so no shipped decision depends on it today. But it is live, and the fix is
one line per call site: **check the model before trusting the mask**
(`covisibility_census.py::_inliers` shows the pattern). Any other place in the
codebase that reads a RANSAC mask should be audited the same way.

**Severity note, stated fairly:** this is a latent-correctness bug on an
unused output, not a live miscomputation of anything a user sees. It matters
because (a) it is non-deterministic, so it would be miserable to debug later, and
(b) the moment anyone gates on r_H — which §6 recommends against, but which is a
natural thing for a successor to try — it becomes a real one.

---

## 9. Would a keyframe database actually FIND these revisits?

§4 answered "do revisits exist" by brute force — 104,196 pairs in 189 s. A
shipping system cannot do that; the cost is quadratic in keyframes. That is the
entire reason ORB-SLAM2/3 carry a vocabulary tree and an inverted index. So the
retrieval question is separate and had to be measured separately.

`tower/scripts/research/slam_classical/bow_retrieval.py` is an **independent
reimplementation of the published vocabulary-tree idea** (Nistér & Stewenius
2006; Gálvez-López & Tardós 2012) — hierarchical k-means over binary ORB
descriptors with majority-vote centroids, tf-idf weights, DBoW2's L1 similarity.
No DBoW2 source was used. Ground truth is the census's own geometrically verified
edges, so this measures *agreement between BoW retrieval and brute-force
geometric verification on the same frames* — self-consistency, nothing more.

**Vocabulary: k=10, L=4 → 10,000 words, trained on 120,000 of our own
descriptors in 10.7 s** [M]. For comparison, ORB-SLAM3 ships k=10, L=6
(header line of `ORBvoc.txt` reads `10 6  0 0`, i.e. L1-norm + tf-idf) [Q,
verified by decompressing], as a **42,527,984-byte compressed / 145,250,924-byte
uncompressed** text file [M, `ls -l` and `tar -tzvf` on the clone]. A 145 MB
runtime asset is a serious consideration for glasses.

### 9.1 A database must refuse feature-starved keyframes, or retrieval collapses

The first run reported **Recall@1 = 0.0%** [M]. That was not the corpus; it was
my database. Under DBoW2's L1 score `s = 1 − 0.5·|v−w|₁` on L1-normalised
vectors, **two zero vectors score 1.00 — the maximum possible** — and a normal
keyframe against a zero vector scores 0.50, while two genuinely similar
keyframes typically score well below that. A featureless keyframe is therefore a
**universal attractor** that outranks every real match.

[M] On the canonical session, **24 of 457 accepted keyframes have ≤100 ORB
features and one has ZERO.** ORB-SLAM3 never meets this because it refuses to
initialize on a frame with ≤100 keypoints (`Tracking.cc:2454`, `:2483`) [Q].
Applying that same constant as an index-admission gate:

| | Before gate | After gate (433/457 indexed) |
|---|---|---|
| Recall@1, all neighbours | **0.0%** | **97.7%** |
| Recall@1, long-gap revisits | 5.1% | **56.5%** |
| precision@5 | 70.8% | **91.5%** |

**This is a finding about our pipeline, not just my harness.** The shipped
keyframe selector gates on blur and motion, not on feature count, and admits
keyframes with zero features. Any place-recognition layer we add must refuse
them at the door.

### 9.2 Retrieval works on this corpus

[M], 433 indexed keyframes, standard place-recognition Recall@K (≥1 correct in
top-K):

| K | All verified neighbours | **Long-gap revisits (>30 s, temporal neighbourhood excluded)** | Cross-segment (the merge case) |
|---|---|---|---|
| 1 | 97.7% | 56.5% | 4.8% |
| 5 | 98.4% | 68.8% | 36.0% |
| 10 | 99.1% | **73.0%** | 63.8% |
| 20 | 99.5% | 77.5% | 80.7% |
| 50 | 99.5% | **86.5%** | **90.1%** |

Precision of the raw retrieval stage [M]: **91.5% @5**, 85.8% @10, 76.4% @20.

Two readings matter:

1. **Local retrieval is essentially solved** (97.7% @1). Finding a keyframe's
   covisible neighbours needs no clever index at all.
2. **Loop-closure retrieval works but needs depth.** At K=10 — ORB-SLAM3's
   `nNumCovisibles` — 73.0% of long-gap revisits are surfaced; at K=50, 86.5%.
   ORB-SLAM3 takes only the **top 3** candidates per class
   (`LoopClosing.cc:491`) [Q], which would be too shallow here. That is a
   concrete tuning consequence of our narrow-FOV, portrait, 360×640 footage.

Cost [M]: **13.9 ms/keyframe** to assign words (pure Python/numpy, trivially
optimisable), **30 µs/pair** to score. Scoring 433 keyframes against each other
took 6.3 s. Against production's 4.3 ms/keyframe ORB detection, a database query
is not the bottleneck.

**Verdict: a DBoW-style keyframe database is viable here, trained on our own
corpus, with no 145 MB asset and no DBoW2 source.**

---

## 10. Q7: Are our segments Atlas maps? No — and the analogy is actively misleading

This was the question I was asked to interrogate rather than assume, and the
answer is the most consequential architectural judgement in this report.

| | ORB-SLAM3 Atlas map | Our segment |
|---|---|---|
| Created when | tracking lost **AND** relocalization failed for 3 s **AND** map has >10 keyframes [Q] `Tracking.cc:2006`, `:2019` | one frame-level gate fired [Q] `engine.py:240-252` |
| Count on canonical data | — | **51** [Q, brief] |
| Minimum size enforced | **10 keyframes**; smaller maps are discarded [Q] `:2019`, `:2273` | none — **9 singletons kept** [M] |
| Carries geometry | by construction (it survived initialization's ≥100-match, ≥1° parallax, ≥50-point gates) | **32 of 51 carry ZERO points** [Q, brief]; [M] 19/51 carry any |
| Internal covisibility graph | yes, median degree high | **median degree 5** [M] |
| Eligible for later merging | **yes, forever**, via the global keyframe database [Q] `Atlas.h:159` | **no mechanism exists** [Q, brief] |
| Recovery attempted first | 3 s of relocalization at widened search radius | none |

**The deepest difference: an ORB-SLAM3 map is a self-consistent reconstruction
that failed to connect to another one. Our segment is a bookkeeping label on a
contiguous run of keyframes.** A "map" containing zero landmarks is not a map,
and 32 of ours contain zero.

The numbers make the asymmetry concrete. ORB-SLAM3 would have *discarded* most of
our segments outright (the 10-keyframe rule kills our 9 singletons and much
else), and would never have *created* most of the rest, because it spends 3
seconds relocalizing before conceding — and the prior lane measured [Q, brief §A]
that **94% of our segment breaks occurred on frames the tracker could still
follow**.

### Why the analogy is not merely inaccurate but harmful

Adopting Atlas wholesale means building map-merge machinery for 51 objects, 32 of
which have nothing to merge. That is a large amount of the most intricate code in
ORB-SLAM3 — `MergeLocal` and `MergeLocal2` are ~1.1 kLOC of the 2,539 in
`LoopClosing.cc` [Q], and the subagent's source read found **four genuine pointer
bugs and one infinite loop** in exactly that region (`LoopClosing.cc:1284`,
`:1299`, `:1352`, `:1360`; and `KeyFrameDatabase.cc:712-713`, where a `continue`
skips the iterator increment). This is the least safe code in the system to
imitate.

**The right move is not to promote our segments into Atlas maps. It is to stop
creating so many of them, and to connect keyframes directly by covisibility —
after which the segment concept largely dissolves.** The census already shows
**49 of 51 segments belong to a single connected component** under plain
covisibility edges [M]. There is no multi-map problem to solve here; there is one
map that was cut into 51 pieces by a gate.

### What from Atlas *is* worth copying

Three things, and they are policies, not data structures:

1. **Try hard before conceding.** RECENTLY_LOST with a widened search radius and
   a relaxed inlier floor (10 vs 30), for 3 seconds, with relocalization attempted
   every frame.
2. **Refuse to keep trivial maps.** The 10-keyframe discard rule. Our 9 singleton
   segments and 32 geometry-less segments are noise in every downstream count.
3. **One keyframe database spanning everything.** ORB-SLAM3's single global
   `mpKeyFrameDB` (`Atlas.h:159`) is the entire mechanism by which separated maps
   ever find each other again. If we build only one thing from this report beyond
   covisibility, build this.

---

## 11. Q6: Monocular scale — recoverable, or only drift-controlled?

**Honest answer: NOT recoverable. Ever. Only drift-controlled.**

Monocular vision determines the scene up to an unknown global similarity. No
amount of loop closure, bundle adjustment, or map merging changes that — those
techniques make the reconstruction *self-consistent*, not *metric*.

ORB-SLAM3 says exactly this in code [Q]:
- `System.cc:213` — the loop closer is constructed with
  `bFixScale = (mSensor != MONOCULAR)`. **Scale is left free only for pure
  monocular**, because there is nothing to fix it to.
- `Sim3Solver.cc:373-388` — `if(!mbFixScale) { ... ms12i = nom/den; } else
  ms12i = 1.0f;`. For monocular, every loop closure *re-estimates* a relative
  scale.
- `Tracking.cc:2584` — after initialization the map is normalised to **median
  depth 1.0** (4.0 for IMU-monocular). An arbitrary convention, chosen because
  no correct answer exists.

What loop closure buys monocular systems is that **scale DRIFT** — the slow
accumulation of scale error along a trajectory — gets redistributed around the
cycle by the Sim(3) pose graph. The gauge itself stays unknown. Metric scale
requires an IMU (ORB-SLAM3's inertial initialization), a stereo baseline, a known
object, or a rangefinder.

This vindicates the repo's design decision that `PoseEstimate.translation` is
unit-length when solved and that scale is reported `Unknown`. **Do not let any
recommendation in this programme imply that adding loop closure will resolve
scale.** It will not. It will make the shape consistent.

Our corpus makes this worse than usual: the prior lane measured that most
geometry-bearing segments have camera baseline near zero relative to scene depth,
making even *relative* scale unobservable — and my census confirms the mechanism,
with consecutive keyframes at median **1.048°** parallax [M].

---

## 12. Licensing

All license facts below were verified by reading the actual files in the local
ORB-SLAM3 clone (`git clone --depth 1`, commit `4452a3c4`), not from memory.

### 12.1 The landmines

| Component | License | Ship in closed-source product? | Verified |
|---|---|---|---|
| **ORB-SLAM2** | **GPLv3** | **NO** | [Q] same project family, same contact |
| **ORB-SLAM3** | **GPLv3** (`LICENSE`, 674 lines) | **NO** | [M] read the file |
| **DSO** | **GPLv3** | **NO** (TUM sells a commercial licence) | [Q] subagent, upstream repo |
| **LDSO** | **GPLv3** | **NO** | [Q] subagent, upstream repo |
| ORB-SLAM3 `Thirdparty/DBoW2` | **README says BSD; the referenced `LICENSE.txt` IS ABSENT** | **Do not rely on it** | [M] `ls` shows no license file; `README.txt:3` says "All files included in this version are BSD, see LICENSE.txt" |
| Upstream `dorian3d/DBoW2`, `rmsalinas/DBow3` | BSD **with a 4th condition**: the original author must be notified of any redistribution | Usable but carries an unusual obligation | [Q] subagent |
| ORB-SLAM3 `Thirdparty/g2o` | BSD (`license-bsd.txt`) | Yes | [M] read the file |
| ORB-SLAM3 `Thirdparty/Sophus` | **MIT** | Yes | [M] read `LICENSE.txt` |
| Pangolin | MIT | Yes | [Q] subagent |
| OpenCV 5.x core | Apache 2.0 | Yes | [Q] subagent |
| Eigen | MPL-2.0 for the parts that matter; `Amd.h` and `SimplicialCholesky.h` have been **relicensed to MPL-2.0**, making the classic "LGPL sparse solver" caveat largely historical. `EIGEN_MPL2_ONLY` remains the guard. | Yes, with the guard | [Q] subagent |
| **ORB feature detector** | **Patent-free by design** — Rublee et al. 2011 built it explicitly as a free alternative to SIFT/SURF, and `cv2.ORB` lives in OpenCV's **main** modules (Apache 2.0), not `xfeatures2d`/nonfree | **Yes** | [Q] widely documented; consistent with `cv2.ORB_create` being available in our headless build [M] |

**The single most important licensing fact: ORB-SLAM2, ORB-SLAM3, DSO and LDSO
are all GPLv3.** For a commercial glasses product, linking any of them means
either releasing the product under GPLv3 or buying a commercial licence.
ORB-SLAM3's README makes the latter explicit [M, `README.md:37`]:

> For a closed-source version of ORB-SLAM3 for commercial purposes, please
> contact the authors: orbslam (at) unizar (dot) es.

**Two traps specific to the vendored tree, both verified [M]:**
1. `Thirdparty/DBoW2/` contains **no license file at all**, while every source
   header and the README point at a `LICENSE.txt` that does not exist. Anyone
   who "checked the vendored DBoW2 licence" checked a dangling reference.
2. `Thirdparty/g2o/g2o/solvers/` contains **only** `linear_solver_dense.h` and
   `linear_solver_eigen.h` [M]. The SuiteSparse (CHOLMOD/CSparse, LGPL/GPL)
   exposure people usually worry about with g2o is **absent from this copy** —
   but it is present upstream, so a fresh `git clone` of g2o has a different risk
   profile than the vendored copy.

Also worth recording [M, §3.2]: the PyPI `orbslam3` package declares
`License: UNKNOWN` with an **OSI BSD classifier** while wrapping GPLv3 code. That
is a licensing-metadata hazard independent of its being the wrong platform.

### 12.2 Classification

- **(a) Ideas/algorithms we may independently reimplement.** All of the
  architecture in §5–§7: covisibility graphs, essential graphs, spanning trees,
  keyframe databases, inverted indices, vocabulary trees, tf-idf BoW scoring,
  Sim(3) pose graphs, Horn's closed-form similarity, the loop/merge guard ladder.
  Algorithms are not copyrightable; specific expression is. Papers exist for all
  of it (Mur-Artal & Tardós 2015/2017; Campos et al. 2021; Gálvez-López & Tardós
  2012; Nistér & Stewenius 2006; Horn 1987; Umeyama 1991 — all patent-free).
- **(b) Source safe to ship commercially.** Sophus (MIT), Pangolin (MIT), OpenCV
  main modules (Apache 2.0), Eigen (MPL-2.0 with `EIGEN_MPL2_ONLY`), **Ceres
  Solver (BSD-3)**, g2o core (BSD, avoiding `g2o_viewer`/`g2o_incremental` which
  are GPL3+ and `csparse_extension` which is LGPLv2.1+).
- **(c) Fine for internal benchmarking, not shippable.** ORB-SLAM2/3, DSO, LDSO.
  Running GPLv3 software internally to evaluate our own output triggers no
  distribution obligation. **This is the correct and only use we should make of
  ORB-SLAM3.**
- **(d) Research-only / restricted.** Several modern learned place-recognition
  models (some NetVLAD derivatives and CosPlace/EigenPlaces weight releases)
  carry non-commercial terms — check per-model before adopting.

### 12.3 The clean-room question, stated honestly

**I am not a lawyer and this is not legal advice.** The general position is that
reading GPLv3 source to understand *architecture* and then independently
implementing the *algorithm* is legally distinguishable from copying expression —
copyright protects expression, not ideas. But the safe practice, and the one I
would recommend, is:

- Prefer the **papers** as the specification of record. They are public,
  citable, and carry no copyleft.
- Where I quote a shipped constant in this report (`th=15`, `minFeat=100`,
  `RH>0.50`, the 10-keyframe rule, the nine-gate ladder), treat those as
  **empirical facts about a reference system** to be re-derived and re-tuned on
  our own data — not as values to transcribe. §6 already shows why: `RH>0.45`
  from the paper would discard 34.8% of our good edges [M].
- Do not copy code structure, identifier names, or comment text from the GPLv3
  sources into our tree.
- If anyone ever proposes actually linking ORB-SLAM3, that is a legal decision
  requiring the `orbslam@unizar.es` commercial licence, not an engineering one.

### 12.4 License-clean alternatives to each landmine

| Need | GPL/awkward option | Clean alternative |
|---|---|---|
| Bundle adjustment / pose graph | g2o (BSD but no Windows wheel [M]) | **Ceres Solver (BSD-3)** — `pyceres` 2.6 has a genuine `cp312-win_amd64` wheel here [M]; or `scipy.optimize.least_squares`; or hand-rolled Gauss-Newton |
| Place recognition | DBoW2/DBoW3 (dangling or 4-condition BSD) | **Our own vocabulary tree** — reimplemented and measured in §9, ~120 production LOC [E] |
| Sim(3) / similarity estimation | — | **Horn 1987 / Umeyama 1991, both patent-free**, ~30 LOC; already proven end-to-end by the prior lane |
| Features | SIFT/SURF concerns | **ORB**, already in use, patent-free, OpenCV main modules |
| Visualisation | — | Pangolin is MIT, but we need none of it |

**Net: there is no licensing obstacle to anything this report recommends,
because it recommends implementing ideas, not importing code.**

---

## 13. Q8: What to build, in what order, and what it costs

### 13.1 Ordering — this is a dependency chain, not a menu

Each step is worthless without the one above it. This is the single most
important operational point in the report, and it is why "add bundle adjustment"
measured 0.00%.

**Step 1 — Build the covisibility graph. Nothing else is non-vacuous without it.**
Match each new keyframe against its top-K retrieval candidates and its recent
window, not solely against the previous keyframe. The observation table
(`support.json`) already persists what is needed to weight the edges [M, §2].
- Payoff [M]: 296 → up to 8,989 edges; median degree 5 → 40; two-view landmark
  share 67.2% → materially lower.
- [E] **~150–250 LOC.** Method: the algorithm is a counter over shared landmark
  ids plus a sorted adjacency list; `_extend` already produces the
  `observed` dict per pair, so the change is calling it against several
  references and accumulating. ORB-SLAM3 spends ~100 LOC of `KeyFrame.cc`'s
  1,159 on `UpdateConnections` [Q].
- **Copy the never-disconnect fallback** (`KeyFrame.cc:443-447`): if no
  neighbour clears the threshold, link the single best one anyway.

**Step 2 — Adopt reciprocity as the standing match guard.**
- Payoff [M]: AUC 0.985; a 0.3 threshold rejects 100% of geometry-less traps
  while keeping 69.8% of good edges.
- [E] **~20 LOC** — one reverse `knnMatch` and a dict intersection; the code is
  already written in `covisibility_census.py::_pair`. Cost [E] ~0.9 ms/pair/core.

**Step 3 — Refuse feature-starved keyframes at the database door.**
- Payoff [M]: Recall@1 0.0% → 97.7%; precision@5 70.8% → 91.5%.
- [E] **~5 LOC.** This is the cheapest measured win in the entire lane.

**Step 4 — Keyframe database (vocabulary tree + inverted index) for scalable
retrieval.**
- Payoff [M]: 73.0% Recall@10 on long-gap revisits, 90.1% Recall@50
  cross-segment, 13.9 ms/keyframe, no 145 MB asset.
- [E] **~120 LOC** production subset. Method: `bow_retrieval.py` is 256 LOC
  *including* the vocabulary trainer and the whole evaluation harness; the
  runtime path (assign words, tf-idf, inverted index, query) is roughly half.
  I wrote and validated it inside this lane, which is the cost datapoint.

**Step 5 — Segment registration via Sim(3), non-destructively.**
The scaffolding already exists and is inert [Q, lead supplement]: every emitted
segment carries `registered: False` and `transform_to_world: None`, and the
gauge-revision semantics are already frozen in `schema.py:97-111` — including
the correct hazard note that a loop closure moves *part* of the world and must
not be composed forward.
- Prior lane already estimated a Sim(3) end-to-end with reverse agreement to
  0.3% [Q, brief], and established PnP (not Umeyama) as the route.
- [E] **~200 LOC** for candidate verification (the guard ladder, simplified —
  we do not need nine gates) + **~120 LOC** for RANSAC Sim(3).

**Step 6 — Pose graph optimisation over the essential graph.** Only now does
this do anything, because only now are there cycles.
- [E] **~200–300 LOC** using `pyceres` (BSD, Windows wheel verified [M]).

**Step 7 — Local bundle adjustment. LAST, and only where landmarks have ≥3
views.** Copy ORB-SLAM3's refusal to run BA with no fixed keyframes
(`Optimizer.cc:1182-1186`) [Q] — it is the same guard the 0.00% result needed.

### 13.2 Total cost

[E] **~900–1,200 LOC of new Python**, against the existing 5,511 LOC
`world_builder` — roughly a 20% growth. Method: sum of the per-step estimates
above, each derived from either (i) code I actually wrote in this lane, or
(ii) the ORB-SLAM3 component LOC scaled down for Python and for the features we
do not need.

For scale: ORB-SLAM3 is **34,350 LOC** of C++ across `src/*.cc` + `include/*.h`
[Q, `wc -l`], of which `Optimizer.cc` alone is 5,590 and `Tracking.cc` is 4,126.
But that includes IMU, stereo, RGB-D, fisheye/KB8 camera models, a Pangolin
viewer, Boost serialization, and two merge paths — none of which we need. The
monocular map-graph core is a small fraction.

### 13.3 What I explicitly recommend AGAINST

- **Do not adopt Atlas as a data structure.** §10. Fix the segmentation rate and
  connect keyframes instead.
- **Do not port `MergeLocal`/`MergeLocal2`.** ~1.1 kLOC containing four verified
  pointer bugs and an infinite loop [Q]. Our non-destructive
  `transform_to_world` design is better and already specified.
- **Do not gate on `r_H`.** §6, measured.
- **Do not add bundle adjustment or pycolmap before Step 1.** Already measured at
  0.00% and the repo already says so.
- **Do not ship ORB-SLAM3's 145 MB vocabulary.** Ours, trained in-domain in
  10.7 s, is 10,000 words [M].
- **Do not expect loop closure to resolve scale.** §11.

---

## 14. Honest limitations

- **No ground truth.** Every corpus number is self-consistency. "Verified edge"
  means "two views admitted a consistent fundamental matrix with ≥15 inliers",
  not "these two keyframes truly see the same place." Geometric verification on
  repetitive indoor texture can agree and be wrong — that is precisely why §7.3
  measured reciprocity as a second, independent guard.
- **Covisibility weight is a proxy.** ORB-SLAM3 weights covisibility edges by
  *shared map points*; I weighted by *verified matches*, which is an **upper
  bound** — not every matched feature survives to become a triangulated landmark.
  The 30x edge uplift should be read as a ceiling, not a promise.
- **The BoW vocabulary is in-domain**, trained on the same corpus it is evaluated
  on. That flatters retrieval relative to ORB-SLAM3's externally-trained
  vocabulary. It is also arguably the right choice for a product with a fixed
  sensor.
- **One capture.** All measurements are on `22e9d4289cb440fbb3f14e6da369a136`.
  The brief notes only ~8 of 34 captures have genuine wearer motion; results may
  differ on the others, and the near-static captures almost certainly have less
  parallax and fewer revisits.
- **ORB-SLAM3 was never run.** I have no external baseline on our footage. The
  "external systems fail on the same footage" hypothesis from the brief remains
  untested by this lane — though §4 argues it is unlikely, since the frames
  demonstrably support a dense connected graph.
- **Two analysis bugs were found and fixed mid-lane** (an inverted AUC that
  reported 0.005 for 0.995, and a recall definition capped at K/degree that
  reported 0.0%). Both are documented in the harness source. A third — the
  OpenCV-5 uninitialised mask — turned out to be a live production defect, §8.

---

## 15. Harness

All under `tower/scripts/research/slam_classical/` (1,117 LOC total). Third-party
source was cloned outside the repo tree; nothing foreign is staged.

| File | LOC | Purpose |
|---|---|---|
| `covisibility_census.py` | 216 | All 104,196 keyframe pairs: matches, reciprocity, F/H verification, parallax, r_H |
| `analyse_census.py` | 291 | Q1–Q7 analysis: degree, range, parallax, components, r_H, revisits, reciprocity |
| `bow_retrieval.py` | 256 | Independent vocabulary-tree + tf-idf + L1 BoW; Recall@K / precision@K |
| `production_covisibility.py` | 102 | The graph production actually built, read off `support.json` |
| `robustness_check.py` | 129 | Methodology confirmation + the §4.9 threshold-sweep table |
| **`repro_ransac_mask.py`** | 173 | **Minimal deterministic repro of the OpenCV-5 defect**: exact pair, dtypes, 50 repeated calls, input-layout variants, healthy control |
| **`repro_rate_fresh_process.py`** | 88 | **Reproduction rate across fresh processes (37/40 = 92.5%)** — the test that proves non-determinism |
| `verify_rh_defect.py` | 70 | The defect as seen through the shipped `homography_ratio` |
| `debug_api.py` | 75 | Isolates the OpenCV-5 behaviour (not a signature change — a failed fit) |
| `debug_mask.py` | 58 | First reproduction of the impossible inlier count |
| `wsl_build_attempt.sh` | 49 | Timeboxed ORB-SLAM3 build attempt; records exactly which wall was hit |

Artifact: `covisibility_census.json` (**16.3 MB** [M], `ls -l`) holds all 104,196
pair records, so every number in §4 and §7.3 is re-derivable without re-running
the 189 s census. It is `.gitignore`d in that directory — regenerate rather than
commit it.

Third-party clone (read for architecture only, never linked, outside the repo
tree): `ORB_SLAM3` at commit `4452a3c4`, 1.6 GB on disk [M].

