"""Is there multi-plane structure the single homography is not already using?

The pipeline already fits ONE homography per frame pair, twice: in
`summarise_motion` (the rotation detector) and in `homography_ratio` (r_H,
recorded and deliberately not gated). r_H was measured to saturate at
0.471-0.499 across the full range from total degeneracy to healthy
parallax, and the recorded reason is that "a room is nothing but planes" --
a homography suffices whenever the scene is EITHER purely rotating OR
plane-dominated, so in a room it cannot isolate rotation.

That result says a single plane explains a lot. It does not say whether
there are SEVERAL planes with independent support, which is what a genuine
piecewise-planar constraint would need. So this fits homographies by
sequential RANSAC -- fit, remove the inliers, refit -- and counts how many
planes carry real support.

The distinction that decides the cue:

  one dominant plane        the existing single homography already captures
                            it, and a multi-plane fit is re-deriving what
                            `summarise_motion` computes every frame.

  several supported planes  there is structure the pipeline is not using,
                            and plane-to-plane constraints could add real
                            geometry -- notably a scale link between two
                            views of the same wall.

A plane is only counted if it holds at least MIN_PLANE_SUPPORT
correspondences AND at least 10% of the pair's inliers; below that a
homography will happily fit four random points and call it a wall.
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]

import cv2
import numpy as np

sys.path.insert(0, str(TOWER_ROOT))
from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import detect_and_describe, match_descriptors

MIN_PLANE_SUPPORT = 25
MIN_PLANE_SHARE = 0.10
HOMOGRAPHY_PX = 3.0
MAX_PLANES = 5

WORLD = TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
SESS = WORLD / 'sessions/dd5d13a2381e430db9b27c7da2cf2928'
kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]
by_seg = {}
for k in kfs:
    by_seg.setdefault(k['segment_index'], []).append(k)
for s in by_seg:
    by_seg[s].sort(key=lambda k: k['source_seq'])


def sequential_homographies(pa, pb):
    """Fit, remove inliers, refit. Returns support counts, largest first."""
    remaining = np.arange(len(pa))
    supports = []
    for _ in range(MAX_PLANES):
        if len(remaining) < 12:
            break
        H, mask = cv2.findHomography(pa[remaining], pb[remaining],
                                     cv2.RANSAC, HOMOGRAPHY_PX)
        if H is None or mask is None:
            break
        inl = mask.ravel().astype(bool)
        if inl.sum() < 12:
            break
        supports.append(int(inl.sum()))
        remaining = remaining[~inl]
    return supports


rows = []
for seg, members in sorted(by_seg.items()):
    if len(members) < 2:
        continue
    grays = [decode_gray((SESS / k['image_relpath']).read_bytes()) for k in members]
    feats = [detect_and_describe(g) for g in grays]
    for i in range(len(members) - 1):
        (ka, da), (kb, db) = feats[i], feats[i + 1]
        pa, pb = match_descriptors(ka, da, kb, db)
        if len(pa) < 40:
            continue
        sup = sequential_homographies(pa, pb)
        if not sup:
            continue
        total = len(pa)
        strong = [s for s in sup if s >= MIN_PLANE_SUPPORT and s / total >= MIN_PLANE_SHARE]
        rows.append(dict(seg=seg, matches=total, supports=sup,
                         n_strong=len(strong),
                         dominant_share=sup[0] / total,
                         second_share=(sup[1] / total) if len(sup) > 1 else 0.0))

json.dump(rows, open(str(HERE / 'planes.json'), 'w'))
dom = np.array([r['dominant_share'] for r in rows])
sec = np.array([r['second_share'] for r in rows])
strong = np.array([r['n_strong'] for r in rows])
print(f"keyframe pairs with >= 40 matches: {len(rows)}")
print()
print(f"  dominant plane share of matches   median {np.median(dom):.3f}  "
      f"p25 {np.percentile(dom, 25):.3f}  p75 {np.percentile(dom, 75):.3f}")
print(f"  SECOND plane share of matches     median {np.median(sec):.3f}  "
      f"p75 {np.percentile(sec, 75):.3f}  p90 {np.percentile(sec, 90):.3f}")
print()
print("  planes with >= 25 correspondences AND >= 10% of the pair's matches:")
for n in range(0, 5):
    m = strong == n
    if m.sum():
        print(f"    {n} plane(s): {int(m.sum()):>4} pairs ({100 * m.mean():>5.1f}%)")
print()
print(f"  pairs where a SECOND plane clears the bar: "
      f"{int((strong >= 2).sum())} ({100 * (strong >= 2).mean():.1f}%)")
print(f"  pairs where the dominant plane alone explains > 60% of matches: "
      f"{int((dom > 0.6).sum())} ({100 * (dom > 0.6).mean():.1f}%)")
