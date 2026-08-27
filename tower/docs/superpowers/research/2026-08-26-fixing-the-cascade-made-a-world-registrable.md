# Fixing the cascade made a world registrable that was not

**Date:** 2026-08-26
**Branch:** `world-builder/next-generation` @ `c4d9ad6`
**Capture:** `e1c52b9f` (996 frames, 83 s, the best-behaved walk in the corpus)
**Status:** measured. This is the first Tower-side change in the project shown to
change a **registration** outcome.

---

## 0. The result

| | baseline engine | with solve-chain segmentation |
|---|---|---|
| segments | 5 | 7 |
| poses_solved | 111 | 135 |
| points | 18,162 | 21,883 |
| candidate pairs | 10 | 19 |
| **segments registered** | **0** | **3** |
| **points in the registered cluster** | **0 of 18,162** | **5,603 of 21,883 (25.6%)** |

The baseline world cannot be registered at all. The same walk, replayed through
the same code with only the segmentation change, produces a three-segment
registered cluster holding a quarter of the world.

---

## 1. Why the change moves registration at all

Registration needs a segment to have **its own solved camera trajectory** — a
Sim3 fit is estimated from cameras placed against the other segment's landmarks,
and `min_cameras = 3` is a hard clause.

Under the cascade, a segment that broke early kept all its keyframes and solved
almost none of them: every pose after the break was refused without geometry
being attempted. A long segment with two solved poses is unregistrable no matter
how much of the room it saw.

Splitting at the break gives each side its own anchor and its own chain. The
geometry was always there; it now has the cameras to support a fit.

That also explains the candidate-pair count, 10 → 19: more segments carrying
real trajectories means more pairs worth attempting.

---

## 2. The admitted pairs, and the refused ones

```
      pair    reg  rot deg   recip  reproj  span/dep
    [0, 3]   True     0.56   0.969    2.17     0.389
    [3, 5]   True     0.93   1.012    2.15     0.265
```

Both agree on orientation to under a degree, on scale to 3.1% and 1.2%, reproject
at ~2.2 px, and sit well above the 0.09 span/depth bar. These are not marginal
admissions.

The refusals are doing real work, which matters more than the admissions:

```
    [3, 4]  False   reciprocity 0.000   -- the two directions disagree by 36x
    [1, 3]  False   reciprocity 1.310   -- 31% scale disagreement despite span/depth 1.485
    [1, 5]  False   rot 10.96 deg, reciprocity 1.689
    [0, 1]  False   reproj 20.29 px, reciprocity 1.571
```

`[3, 4]` is the collapse-to-zero failure the research note warned about — a fit
returning `s = 0.0000`, which would place a segment as a dot at another's origin
and is invisible in every aggregate metric. It is refused on reciprocity.

`[1, 3]` is the more interesting one: **span/depth 1.485**, the best parallax of
any pair here, and still refused because the two independent solves disagree on
scale by 31%. Good parallax is not sufficient evidence, and the gate says so.

---

## 3. What this does and does not claim

**Claims:** on this capture, fixing the refusal cascade took registration from
zero to a three-segment cluster carrying 25.6% of the points, and the pairs
admitted are well-conditioned by every clause the gate measures.

**Does not claim:**

- That the registered cluster is geometrically *correct*. Nothing automated can
  establish that — `WORLD-BUILDER-STATUS.md` P9 is explicit that a wrong Sim3
  can fit at 1.62 px with 88% of points under 3 px while being 3.2x wrong on
  scale. Only a wearer walking a loop and looking at the result settles it.
- That this generalises. It is one capture. `22e9d428` and `64f48114` still
  register 0 of their segments under the same change, and their refusals are
  dominated by "neither direction could be solved".
- That 25.6% is a good number. The historical best recorded in
  `WORLD-BUILDER-STATUS.md` is 31.1% on a different world.

**The honest summary is narrow and still worth having:** the cascade was not only
discarding reconstruction, it was discarding the *cameras that registration needs
to exist*. That was not previously known, and it changes where the remaining
coherence work should look.

---

## 4. What this suggests next

The registration refusals across the corpus are dominated by two reasons, and
they call for different work:

1. **"neither direction could be solved"** — dominates `22e9d428` (35 of 41
   pairs) and `64f48114`. These segments do not have enough mutually visible
   landmarks with placeable cameras. More segmentation will not fix it; better
   candidate retrieval or more keyframes per segment might.
2. **"the wearer stood still"** (`span/depth` below 0.09) — the physical
   problem. `WORLD-BUILDER-STATUS.md` P11 already names the experiment: a walk
   where the wearer sidesteps rather than pans. Nothing on the Tower fixes this.

### The unrestricted variant was measured, and adds nothing here

The obvious next measurement was cheap, so it was run rather than left as a
suggestion.

| | baseline | shipped rule | unrestricted |
|---|---|---|---|
| segments | 5 | 10 | 10 |
| candidate pairs | 10 | 34 | 34 |
| segments registered | 0 | **3** | **3** |
| points registered | 0 | **5,603** | **5,603** |
| admitted pairs | — | `[0,3]`, `[3,5]` | `[0,3]`, `[3,5]` |

(The middle column originally reported a withdrawn restart rule, 7 segments
and the same registered cluster. Registration is invariant across every
restart policy tested — caps of 1, 2 and none all land on the same three
segments and the same 5,603 points.)

**Identical.** Nearly double the segments and nearly double the candidate pairs
produce exactly the same registered cluster, down to the same two pairs with the
same reciprocity and reprojection.

The extra fragments are not registrable — they are the small, low-camera
segments the restricted rule declines to create in the first place. So on this
capture the restricted rule captures the *entire* registration gain at a third
of the fragmentation cost, which is a better argument for shipping it than the
coherence reasoning that originally chose it.

It also narrows what the unrestricted variant is actually worth: its extra
poses and points are real, but they are geometry that cannot currently be placed
in a shared frame. That is a reason to want fragment ranking, not a reason to
want more fragments.
