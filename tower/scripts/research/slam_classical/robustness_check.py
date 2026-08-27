"""Is the headline covisibility result an artefact of threshold choice?

The adversarial reviewer's obvious attack: "you picked a verification that
makes the number big." So re-derive the headline under a STRICTER and
production-truer criterion and see whether the conclusion survives.

The census gates a covisibility edge on FUNDAMENTAL-matrix inliers >= 15 at
3.0 px / 0.99 -- the same call and thresholds production already uses in
`geometry.homography_ratio` (geometry.py:120-123).

Production's POSE path is different: `findEssentialMat` at 1.0 px / 0.999
followed by `recoverPose` (backends/classical.py). The census recorded the
recoverPose inlier count as `e_inliers` for every pair that cleared the
F-gate, so the stricter criterion can be applied without re-running.

Caveat stated up front: `e_inliers` was only COMPUTED where f_inliers >= 15,
so the E-based edge set is by construction a SUBSET of the F-based one.
This is a check that the conclusion is robust to tightening, not an
independent re-derivation from scratch.
"""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
data = json.loads((HERE / 'covisibility_census.json').read_text())
meta, pairs = data['meta'], data['pairs']
seg = np.array(meta['segment_index'])
n = meta['n_keyframes']

i = np.array([p['i'] for p in pairs])
j = np.array([p['j'] for p in pairs])
finl = np.array([p['f_inliers'] for p in pairs])
einl = np.array([p['e_inliers'] for p in pairs])
mutual = np.array([p['mutual'] for p in pairs])
tri = np.array([np.nan if p['tri_angle'] is None else p['tri_angle'] for p in pairs])
same = seg[i] == seg[j]

print("=" * 70)
print("METHODOLOGY CONFIRMATION")
print("=" * 70)
print(f"  keyframes                 : {n}")
print(f"  pairs evaluated           : {len(pairs)}")
print(f"  C(n,2) = n(n-1)/2         : {n * (n - 1) // 2}")
print(f"  FULL O(n^2) SWEEP         : {len(pairs) == n * (n - 1) // 2}  "
      f"(no sampling)")
print(f"  ORB nfeatures             : {meta['orb_features']}  "
      f"(production geometry.ORB_FEATURES)")
print(f"  Lowe ratio                : {meta['lowe']}  "
      f"(production geometry.LOWE_RATIO)")
print(f"  edge threshold            : {meta['covis_edge_th']} inliers  "
      f"(= production geometry.MIN_INLIERS, and ORB-SLAM3 KeyFrame.cc:421)")
print(f"  parallax threshold        : {meta['min_tri_angle']} deg  "
      f"(production geometry.MIN_TRIANGULATION_ANGLE_DEG)")
print("  NO threshold was retuned to enlarge the result.")


def components(mask, nodes, key):
    parent = {v: v for v in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in zip(key[i[mask]], key[j[mask]]):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups = defaultdict(list)
    for v in nodes:
        groups[find(v)].append(v)
    return sorted((len(v) for v in groups.values()), reverse=True), len(groups)


segs = sorted(set(seg.tolist()))
print()
print("=" * 70)
print("ROBUSTNESS: does the conclusion survive a stricter criterion?")
print("=" * 70)

criteria = [
    ("F-inliers >= 15  [headline]", finl >= 15),
    ("F-inliers >= 30", finl >= 30),
    ("F-inliers >= 50", finl >= 50),
    ("F-inliers >= 100 (essential graph)", finl >= 100),
    ("recoverPose inliers >= 15  [production pose path]", einl >= 15),
    ("recoverPose inliers >= 30", einl >= 30),
    ("recoverPose inliers >= 50", einl >= 50),
    ("E>=15 AND parallax >= 0.5 deg", (einl >= 15) & np.isfinite(tri) & (tri >= 0.5)),
    ("E>=30 AND parallax >= 1.0 deg", (einl >= 30) & np.isfinite(tri) & (tri >= 1.0)),
    ("E>=50 AND parallax >= 1.0 deg AND reciprocity >= 0.3",
     (einl >= 50) & np.isfinite(tri) & (tri >= 1.0)
     & (mutual >= 0.3 * np.maximum(np.array([p['matches'] for p in pairs]), 1))),
]

print(f"{'criterion':<52} {'edges':>7} {'x-seg':>7} {'deg':>5} {'comp':>5} {'big':>5}")
print("-" * 84)
for label, mask in criteria:
    deg = np.zeros(n, int)
    for a, b in zip(i[mask], j[mask]):
        deg[a] += 1
        deg[b] += 1
    sizes, ncomp = components(mask, segs, seg)
    print(f"{label:<52} {int(mask.sum()):>7} {int((mask & ~same).sum()):>7} "
          f"{int(np.median(deg)):>5} {ncomp:>5} {sizes[0]:>5}")

print()
print("  edges = covisibility edges;  x-seg = of those, cross-segment")
print("  deg   = MEDIAN covisibility degree per keyframe")
print("  comp  = connected components over the 51 production segments")
print("  big   = segments in the largest component")
print()
print(f"  Production actually builds: 296 edges, 0 cross-segment, median degree 5,")
print(f"  51 components. (production_covisibility.py, read from support.json)")
