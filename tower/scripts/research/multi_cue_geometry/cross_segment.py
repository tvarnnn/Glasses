"""What bounds cross-segment registration: correspondence, or observability?

This is the ceiling calculation for a learned matcher. SuperPoint/LightGlue
and friends buy exactly one thing -- more and better correspondences,
especially across wide baselines and appearance change, which is precisely
the cross-segment case ORB is weakest at. Buying it means a new dependency,
new weights, and a per-pair cost far above ORB's 3.9 ms.

So the question is not "would a learned matcher find more matches" -- it
would -- but "is correspondence what is stopping registration". The
registration work already reported that 16 of 19 geometry-bearing segments
are refused for span/depth, meaning their own cameras carry no baseline and
their scale is unobservable. A matcher cannot create a baseline.

This measures the correspondence side directly, so the two halves can be
compared on the same world:

  For every ordered pair of geometry-bearing segments, match the best
  keyframe of one against every keyframe of the other with the shipped
  ORB + Lowe ratio matcher, and record the strongest link found.

A pair whose best link already clears MIN_INLIERS has no correspondence
problem for a learned matcher to solve.
"""
import json
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]

import cv2
import numpy as np

sys.path.insert(0, str(TOWER_ROOT))
from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import (MIN_INLIER_RATIO, MIN_INLIERS,
                                          RANSAC_CONFIDENCE,
                                          RANSAC_THRESHOLD_PX,
                                          detect_and_describe, match_descriptors)

WORLD = TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
SESS = WORLD / 'sessions/dd5d13a2381e430db9b27c7da2cf2928'
DER = WORLD / 'derived/dd5d13a2381e430db9b27c7da2cf2928'
intr = json.loads((SESS / 'session.json').read_text())['intrinsics']
K = np.array([[intr['fx'], 0, intr['cx']], [0, intr['fy'], intr['cy']], [0, 0, 1.0]])

kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]
points = json.loads((DER / 'points.json').read_text())['points']
seg_pts = Counter(p['segment_index'] for p in points)
by_seg = {}
for k in kfs:
    by_seg.setdefault(k['segment_index'], []).append(k)
for s in by_seg:
    by_seg[s].sort(key=lambda k: k['source_seq'])

# Segments with geometry are the only ones registration can act on today.
with_geom = sorted(s for s in by_seg if seg_pts.get(s, 0) > 0)
print(f"segments with geometry: {len(with_geom)}   "
      f"ordered pairs: {len(with_geom) * (len(with_geom) - 1) // 2}")

# Cap the work: up to 6 keyframes per segment, evenly spaced.
feat = {}
for s in with_geom:
    members = by_seg[s]
    take = np.linspace(0, len(members) - 1, min(6, len(members))).astype(int)
    feat[s] = [detect_and_describe(decode_gray((SESS / members[i]['image_relpath']).read_bytes()))
               for i in dict.fromkeys(take.tolist())]

rows = []
t0 = time.perf_counter()
for sa, sb in combinations(with_geom, 2):
    best = dict(seg_a=sa, seg_b=sb, matches=0, inliers=0, ratio=0.0)
    for ka, da in feat[sa]:
        for kb, db in feat[sb]:
            pa, pb = match_descriptors(ka, da, kb, db)
            if len(pa) < 8:
                continue
            E, mask = cv2.findEssentialMat(pa, pb, K, cv2.RANSAC,
                                           RANSAC_CONFIDENCE, RANSAC_THRESHOLD_PX)
            if E is None or E.shape != (3, 3) or mask is None:
                continue
            inl = int(mask.sum())
            if inl > best['inliers']:
                best = dict(seg_a=sa, seg_b=sb, matches=len(pa), inliers=inl,
                            ratio=round(inl / len(pa), 3))
    rows.append(best)
elapsed = time.perf_counter() - t0
json.dump(rows, open(str(HERE / 'cross_segment.json'), 'w'))

inl = np.array([r['inliers'] for r in rows], float)
ratio = np.array([r['ratio'] for r in rows], float)
linked = (inl >= MIN_INLIERS) & (ratio >= MIN_INLIER_RATIO)
print()
print(f"segment pairs examined: {len(rows)}   "
      f"keyframe comparisons: {sum(len(feat[a]) * len(feat[b]) for a, b in combinations(with_geom, 2))}")
print(f"  best-link inliers  median {np.median(inl):.0f}  p75 {np.percentile(inl, 75):.0f}  "
      f"max {inl.max():.0f}")
print(f"  pairs whose best link ALREADY clears the pipeline's own bar "
      f"({MIN_INLIERS} inliers, ratio {MIN_INLIER_RATIO}): "
      f"{int(linked.sum())} / {len(rows)} ({100 * linked.mean():.1f}%)")
print(f"  pairs with essentially no correspondence (< 8 inliers): "
      f"{int((inl < 8).sum())} ({100 * (inl < 8).mean():.1f}%)")
print()
print("THE CEILING FOR A LEARNED MATCHER, ON THIS WORLD")
print(f"  candidate segment pairs:                        {len(rows)}")
print(f"  already correspondence-sufficient:              {int(linked.sum())}")
print(f"  registration actually admits today:             3")
print(f"  refused for span/depth (scale unobservable):    16 of 19 segments")
print(f"  => a matcher can only act on the {len(rows) - int(linked.sum())} pairs it would newly link,")
print(f"     and every one of those still faces the same span/depth gate.")
print()
print(f"ORB cross-segment sweep cost: {elapsed:.1f} s for "
      f"{sum(len(feat[a]) * len(feat[b]) for a, b in combinations(with_geom, 2))} keyframe comparisons")
