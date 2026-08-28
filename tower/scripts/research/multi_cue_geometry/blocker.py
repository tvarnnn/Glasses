"""What actually stops a segment from carrying geometry?

The registration research established that 32 of 51 segments hold not one
triangulated point, and named that -- not the registration estimator -- as
the blocker. It did not say WHY those segments are empty, and the answer
decides which cue is worth buying:

  correspondence-limited   too few matches, or too few surviving an
                           essential-matrix fit. A better MATCHER helps.
                           This is what learned features are for.

  parallax-limited         plenty of correspondence, but the two views
                           share a camera centre. NO matcher helps; there
                           is no depth information in the pair at all, and
                           a matcher that produced more correspondences
                           would only produce more of the same ambiguity.

The pipeline already recorded the discriminator per keyframe pair in
`edges.jsonl` -- matches, inliers, inlier_ratio, degeneracy -- so this
reads what is on disk rather than re-solving.
"""
import json
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]

WORLD = TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
SESS = WORLD / 'sessions/dd5d13a2381e430db9b27c7da2cf2928'
DER = WORLD / 'derived/dd5d13a2381e430db9b27c7da2cf2928'

kf = {}
for line in (SESS / 'keyframes.jsonl').read_text().splitlines():
    r = json.loads(line)
    kf[r['keyframe_id']] = r
edges = [json.loads(x) for x in (SESS / 'edges.jsonl').read_text().splitlines() if x.strip()]
poses = json.loads((DER / 'poses.json').read_text())['poses']
points = json.loads((DER / 'points.json').read_text())['points']

seg_of = {k: v['segment_index'] for k, v in kf.items()}
seg_kf = Counter(seg_of.values())
seg_pts = Counter(p['segment_index'] for p in points)
seg_solved = Counter(p['segment_index'] for p in poses if p['status'] == 'solved')
all_segments = sorted(seg_kf)

print(f"segments {len(all_segments)}   keyframes {len(kf)}   points {len(points)}   "
      f"solved poses {sum(seg_solved.values())}")
empty = [s for s in all_segments if seg_pts.get(s, 0) == 0]
print(f"segments with zero points: {len(empty)}")
print()

# --- Why is a segment empty? Classify its internal edges. -------------
def classify(e):
    if e['matches'] == 0:
        return 'no_matches'
    if e['inliers'] < 15:
        return 'few_inliers'
    if (e['inlier_ratio'] or 0) < 0.05:
        return 'low_inlier_ratio'
    if e['degeneracy'] == 'pure_rotation':
        return 'pure_rotation'
    if e['degeneracy'] == 'low_parallax':
        return 'low_parallax'
    return 'ok'


internal = [e for e in edges
            if seg_of.get(e['from_keyframe_id']) is not None
            and seg_of.get(e['from_keyframe_id']) == seg_of.get(e['to_keyframe_id'])]
print(f"intra-segment keyframe pairs: {len(internal)}")
by_empty = {True: Counter(), False: Counter()}
for e in internal:
    by_empty[seg_of[e['from_keyframe_id']] in set(empty)][classify(e)] += 1
print(f"{'edge verdict':>20} {'in EMPTY segments':>19} {'in segments WITH geometry':>26}")
for k in ['no_matches', 'few_inliers', 'low_inlier_ratio', 'pure_rotation', 'low_parallax', 'ok']:
    a, b = by_empty[True][k], by_empty[False][k]
    ta, tb = sum(by_empty[True].values()), sum(by_empty[False].values())
    print(f"{k:>20} {a:>8} ({100*a/max(ta,1):>5.1f}%) {b:>12} ({100*b/max(tb,1):>5.1f}%)")
print()

# --- Are the empty segments even big enough to solve? -----------------
single = [s for s in empty if seg_kf[s] == 1]
print(f"of the {len(empty)} empty segments, {len(single)} contain a SINGLE keyframe")
print("  a one-keyframe segment cannot be solved by any method: there is no second view.")
multi = [s for s in empty if seg_kf[s] >= 2]
print(f"  {len(multi)} have >= 2 keyframes and are the only ones a better matcher could reach")
if multi:
    print(f"  those hold {sum(seg_kf[s] for s in multi)} keyframes total")
print()

# --- Correspondence supply on the reachable ones ----------------------
reach = [e for e in internal if seg_of[e['from_keyframe_id']] in set(multi)]
if reach:
    m = np.array([e['matches'] for e in reach], float)
    inl = np.array([e['inliers'] for e in reach], float)
    print(f"edges inside empty multi-keyframe segments: {len(reach)}")
    print(f"  matches  median {np.median(m):.0f}  p25 {np.percentile(m,25):.0f}  p75 {np.percentile(m,75):.0f}")
    print(f"  inliers  median {np.median(inl):.0f}  fraction with >= 15 inliers: {100*(inl>=15).mean():.1f}%")
    deg = Counter(e['degeneracy'] for e in reach)
    print(f"  degeneracy: {dict(deg)}")
    par = np.array([e['median_parallax_px'] for e in reach if e['median_parallax_px'] is not None], float)
    if len(par):
        print(f"  median_parallax_px median {np.median(par):.1f} (n={len(par)})")
print()

# --- The same question for segments that DID solve --------------------
good = [e for e in internal if seg_of[e['from_keyframe_id']] not in set(empty)]
m = np.array([e['matches'] for e in good], float)
inl = np.array([e['inliers'] for e in good], float)
print(f"edges inside segments WITH geometry: {len(good)}")
print(f"  matches  median {np.median(m):.0f}   inliers median {np.median(inl):.0f}   "
      f">=15 inliers: {100*(inl>=15).mean():.1f}%")
print(f"  degeneracy: {dict(Counter(e['degeneracy'] for e in good))}")
print()

# --- Corpus-wide degeneracy verdict -----------------------------------
print("ALL intra-segment edges by recorded pose_status / degeneracy:")
print(f"  pose_status: {dict(Counter(e['pose_status'] for e in internal))}")
print(f"  degeneracy:  {dict(Counter(e['degeneracy'] for e in internal))}")
