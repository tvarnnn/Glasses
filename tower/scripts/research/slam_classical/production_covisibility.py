"""The covisibility graph production ACTUALLY built, read off disk.

The shared brief says `PointBlock.support_views` is declared and never
populated. That is now STALE: commit 4136b2f ("record which feature in
which keyframe made each landmark") fills it, and `support.json` is on
disk for the canonical session with rows

    [segment_index, frame_index, feature_index, point_index]

where frame_index and point_index are SEGMENT-LOCAL. That table is exactly
the observation graph -- the thing ORB-SLAM3 calls MapPoint::mObservations
and the thing every classical technique derives its power from.

So the chain claim ("median covisibility span is 1") no longer has to be
taken on trust from the handoff doc. It can be counted. This counts it,
and puts the number beside the all-pairs census so the gap between WHAT
PRODUCTION BUILT and WHAT THE FRAMES SUPPORT is one table.

NO GROUND TRUTH. Comparative / self-consistency only.
"""
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]
DER = (TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
       / 'derived/dd5d13a2381e430db9b27c7da2cf2928')

support = json.loads((DER / 'support.json').read_text())['support']
points = json.loads((DER / 'points.json').read_text())['points']
poses = json.loads((DER / 'poses.json').read_text())['poses']

print(f"support rows      : {len(support)}")
print(f"points            : {len(points)}")
print(f"poses             : {len(poses)}")
st = Counter(p.get('status') for p in poses)
print(f"pose status       : {dict(st)}")

# Landmark identity is (segment, point_index) because point_index is
# segment-local.
views = defaultdict(set)
for seg, frame, _feat, pt in support:
    # frame_index and point_index are BOTH segment-local, so the segment has
    # to be part of both keys or keyframes from different segments collide.
    views[(seg, pt)].add((seg, frame))

vc = np.array([len(v) for v in views.values()])
print(f"\nLANDMARKS with a support record: {len(vc)}")
print(f"  views per landmark: median={np.median(vc):.0f}  mean={vc.mean():.2f}  "
       f"max={vc.max()}")
hist = Counter(vc.tolist())
for k in sorted(hist)[:8]:
    print(f"    seen by {k:>2} keyframes: {hist[k]:>7}  ({hist[k]/len(vc)*100:5.1f}%)")
print(f"  landmarks seen by >2 keyframes: {int((vc > 2).sum())} "
      f"({(vc > 2).mean()*100:.2f}%)")
print("  NOTE: a landmark seen by exactly 2 views contributes NO redundancy.")
print("        Bundle adjustment can only tighten what >=3 views constrain.")

# The covisibility graph production actually has: an edge between two
# keyframes for every landmark they share, weighted by the count.
edges = Counter()
for (_seg, _pt), fs in views.items():
    for a, b in combinations(sorted(fs), 2):
        edges[(a, b)] += 1

deg = Counter()
for (a, b), w in edges.items():
    if w >= 15:            # ORB-SLAM3's covisibility threshold
        deg[a] += 1
        deg[b] += 1

kf_in_geom = {f for (_s, _p), fs in views.items() for f in fs}
print(f"\nPRODUCTION COVISIBILITY GRAPH (segment-local frame indices)")
print(f"  keyframes appearing in any support row: {len(kf_in_geom)}")
print(f"  weighted keyframe pairs sharing >=1 landmark: {len(edges)}")
print(f"  pairs with weight >= 15 (ORB-SLAM3 edge)    : "
      f"{sum(1 for w in edges.values() if w >= 15)}")
print(f"  pairs with weight >= 100 (essential graph)  : "
      f"{sum(1 for w in edges.values() if w >= 100)}")
gaps = Counter(b[1] - a[1] for (a, b) in edges if edges[(a, b)] >= 15)
print(f"  SPAN of those edges (|frame_j - frame_i| within a segment):")
for g in sorted(gaps)[:6]:
    print(f"    span {g}: {gaps[g]} edges")
print(f"  spans > 1: {sum(v for k, v in gaps.items() if k > 1)} "
      f"of {sum(gaps.values())}")

d = np.array([deg.get(f, 0) for f in sorted(kf_in_geom)]) if kf_in_geom else np.zeros(1)
print(f"  covisibility DEGREE per geometry-bearing keyframe: "
      f"median={np.median(d):.0f} mean={d.mean():.2f} max={d.max()}")

seg_pts = Counter(p['segment_index'] for p in points)
print(f"\nSEGMENTS: {len(seg_pts)} of 51 carry any triangulated point")
print(f"  points per segment: median={np.median(list(seg_pts.values())):.0f} "
      f"max={max(seg_pts.values())}")
print("\nCROSS-SEGMENT edges in the production graph: 0 BY CONSTRUCTION --")
print("  point_index and frame_index are segment-local, so no landmark can")
print("  be shared across segments and no such edge is representable.")
