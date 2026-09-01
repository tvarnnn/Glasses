# World Builder — tracking recovery, drift control, retrieval width

**Branch:** `world-builder/tracking-recovery-v1`
**Parent:** `world-builder/fragment-registration-v1` @ `e847339`
**Date:** 2026-09-01
**Full report:** `tower/docs/superpowers/research/2026-09-01-drift-not-fragmentation.md`

This is the current-state handoff. The report is the evidence; this is
what a person needs to know before touching the World Builder next.

---

## 1. The headline, and the correction to the working theory

The working theory was that the World Builder fragments because the
tracker restarts too often. It does restart too often, and that is
addressed. **It is not the reason a walk does not become a world.**

The forward-only pose chain drifts. On a perfect synthetic strafe with
nothing refused and nothing blurred, rotation error grows 0.95° at six
keyframes to 33.98° at forty and the reconstruction contracts by a factor
of three. On the real 2026-09-01 walk, the one segment that survived 170
keyframes has camera centres reaching 8 × 10¹⁰ and points reaching
2.9 × 10¹³. The largest coherent piece of geometry in the corpus was not
coherent, and cross-segment registration was refusing to place it
**correctly**.

So: fragmentation is the symptom; drift is what made the fragments
unmergeable. Anything that reduces segment count without controlling
drift makes the world tidier and less true.

---

## 2. What is now in the code

**`tower/world_builder/bundle.py`** (new). Sparse Levenberg-Marquardt over
poses and landmarks with the Schur complement, numpy and OpenCV only, run
over a sliding window on the **keyframe** path. `BUNDLE_WINDOW = 12`
cameras, oldest 2 fixed, every 3 solved keyframes, 4 iterations.

**`backends/classical.py`.** `_Chain.broken` is no longer a one-way latch;
references are the last keyframes that HAVE poses; a refused keyframe
never becomes a reference. `MAX_RECOVERY_KEYFRAMES` bounds how many
consecutive refusals are tolerated and **is 1** — see §4.

**`scripts/world_registration.py`.** `MAX_KEYFRAMES_PER_SEGMENT_FOR_MATCHING`
is now a floor rather than a cap; `match_budget` splits a
`MAX_MATCH_FRAME_PAIRS = 256` product budget in proportion to the two
segments' lengths. No gate was touched.

**`scripts/world_coherence_report.py`** (new). Reads a built world cold and
reports the dominant connected component AND the reprojection of the
published support rows. It refuses to report one without the other, on
purpose.

---

## 3. Results

2026-09-01 long-loop walk, physical era → this branch:

| | physical era | this branch |
|---|---|---|
| fragments | 18 (no placements written at all) | **10** |
| dominant component | 6,190 pts / 20.4% (one diverged segment) | **12,558 pts / 41.1%** |
| admitted pairs | 0 | **14** |
| cycles verified | — | **5** |
| published reprojection p99 | 4.73 px | **2.78 px** |
| rows over the 3 px gate | 2.54% | **0.69%** |

**Reprojection improves on every walk in the five-walk corpus.** The
dense 08-29 walk goes from 58.0% of its geometry in one frame to **92.9%**.

---

## 4. The thing to be careful about: `MAX_RECOVERY_KEYFRAMES`

That constant is exactly the largest reference gap a solve may be
admitted at, and **no acceptance gate in the backend is a function of the
gap**. Over repeating texture — an ordinary room — a gap above 1
publishes roughly one keyframe of motion however far the camera walked.
Measured, continuous walk, no teleport: at gap 8 the camera moved
1.500 m and the pose reported 0.001 m, with 169 PnP inliers, 0.14° of
rotation error, and support reprojecting at 0.22 px median.

Every instrument this pipeline owns says that pose is excellent.

`tests/test_world_builder_recovery_safety.py` carries the full tables.
**Do not raise this constant without an instrument that checks the
displacement a recovered pose implies against the number of keyframes it
skipped.** A better matcher will not help: appearance is what lies here.

---

## 5. Shutdown risk — REAL, unfixed, and characterised

`CaptureWorkerSupervisor.shutdown` gives each worker
`DEFAULT_GRACE_SECONDS = 10.0`. Registration now takes **14–66 s** on the
corpus's substantial walks (it took 1.6–34 s before). A Tower shutdown
landing inside that window will kill registration.

What that costs, precisely: `register()` writes nothing until it
completes and `write_placements` is its only write, so a kill loses
`placements.json` and **never** the reconstruction. The world is left
exactly as the physical era left it — built, unplaced.

Why it is not fixed here: on Windows `Popen.terminate()` is
`TerminateProcess`, which is not catchable, so no handler in the child
can help. The fix has to be a longer grace for this worker specifically,
or a placement checkpoint, and the first is a product decision about how
long a Stop may take. **Left for a follow-up, deliberately.**

---

## 6. What the next physical test should be

Run `main` as usual for CV Lab and Object Memory. For World Builder,
check out `world-builder/tracking-recovery-v1` on the Tower.

1. **Repeat the 2026-09-01 walk**, same room, same route, ~2 minutes,
   deliberate overlap, return toward the start. That gives a like-for-like
   physical comparison against the best dataset we have.
2. **Then walk a long straight corridor** for 60–90 seconds without
   returning. Every walk in the corpus is a room; the drift measurement
   says the risk concentrates in long unlooped chains, and nothing in the
   corpus tests one.
3. **Do not stop the Tower for at least 90 seconds after ending a walk.**
   See §5.
4. Expect on the phone: fewer fragments, and a dominant fragment holding
   substantially more of the room. Report the fragment count and which
   fragment is largest — that is the number this branch moved.
