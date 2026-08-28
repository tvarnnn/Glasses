"""Correspondence-limited or parallax-limited? Measured, not read off disk.

`edges.jsonl` cannot answer this. `PoseEstimate.matches` defaults to 0, and
when a segment's seeding pair fails the chain never starts, so every pose
after it is written with the default. 190 of 212 edges inside the empty
segments carry `matches: 0`, and that is the DEFAULT rather than a count --
"not attempted" recorded in the same field as "measured none". So this
re-runs the actual matcher on the actual keyframe images.

For every consecutive keyframe pair inside a segment that produced no
geometry, this records what the pipeline's own front end would find:

  ORB + Lowe ratio matches            is there correspondence at all?
  essential-matrix inliers and ratio  is it geometrically consistent?
  median triangulation angle          is there a baseline to triangulate?

The last one is the discriminator. Correspondence is buyable -- a better
matcher is a real option. Baseline is not: if the two views share a camera
centre, no matcher in existence recovers depth from them, and a matcher
that returns more correspondences returns more of the same ambiguity.
"""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]

import cv2
import numpy as np

import sys
sys.path.insert(0, str(TOWER_ROOT))
from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import (MIN_INLIER_RATIO, MIN_INLIERS,
                                          MIN_TRIANGULATION_ANGLE_DEG,
                                          RANSAC_CONFIDENCE,
                                          RANSAC_THRESHOLD_PX,
                                          detect_and_describe,
                                          match_descriptors,
                                          median_triangulation_angle_deg)

WORLD = TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
SESS = WORLD / 'sessions/dd5d13a2381e430db9b27c7da2cf2928'
DER = WORLD / 'derived/dd5d13a2381e430db9b27c7da2cf2928'

intr = json.loads((SESS / 'session.json').read_text())['intrinsics']
K = np.array([[intr['fx'], 0, intr['cx']],
              [0, intr['fy'], intr['cy']],
              [0, 0, 1.0]])

kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]
points = json.loads((DER / 'points.json').read_text())['points']
seg_pts = Counter(p['segment_index'] for p in points)

by_seg = {}
for k in kfs:
    by_seg.setdefault(k['segment_index'], []).append(k)

cache = {}
def gray(k):
    if k['keyframe_id'] not in cache:
        cache[k['keyframe_id']] = decode_gray((SESS / k['image_relpath']).read_bytes())
    return cache[k['keyframe_id']]


def measure(ka, kb):
    ga, gb = gray(ka), gray(kb)
    pa_kp, da = detect_and_describe(ga)
    pb_kp, db = detect_and_describe(gb)
    pa, pb = match_descriptors(pa_kp, da, pb_kp, db)
    rec = dict(kp_a=len(pa_kp), kp_b=len(pb_kp), matches=len(pa),
               inliers=0, ratio=None, tri=None, verdict='')
    if len(pa) < 8:
        rec['verdict'] = 'no_correspondence'
        return rec
    E, mask = cv2.findEssentialMat(pa, pb, K, cv2.RANSAC,
                                   RANSAC_CONFIDENCE, RANSAC_THRESHOLD_PX)
    if E is None or E.shape != (3, 3) or mask is None:
        rec['verdict'] = 'no_essential'
        return rec
    rec['inliers'] = int(mask.sum())
    rec['ratio'] = round(rec['inliers'] / len(pa), 3)
    if rec['inliers'] < MIN_INLIERS:
        rec['verdict'] = 'few_inliers'
        return rec
    if rec['ratio'] < MIN_INLIER_RATIO:
        rec['verdict'] = 'low_inlier_ratio'
        return rec
    m = mask.ravel().astype(bool)
    _, R, t, _ = cv2.recoverPose(E, pa[m], pb[m], K)
    tri = median_triangulation_angle_deg(pa[m], pb[m], R, t, K)
    rec['tri'] = None if tri is None else round(tri, 4)
    if tri is None:
        rec['verdict'] = 'no_triangulation'
    elif tri < MIN_TRIANGULATION_ANGLE_DEG:
        rec['verdict'] = 'low_parallax'
    else:
        rec['verdict'] = 'solvable'
    return rec


results = {'empty': [], 'geometry': []}
for seg, members in sorted(by_seg.items()):
    if len(members) < 2:
        continue
    bucket = 'empty' if seg_pts.get(seg, 0) == 0 else 'geometry'
    members = sorted(members, key=lambda k: k['source_seq'])
    for a, b in zip(members, members[1:]):
        r = measure(a, b)
        r['segment'] = seg
        results[bucket].append(r)
    cache.clear()

json.dump(results, open(str(HERE / 'blocker_measured.json'), 'w'))

for bucket in ('empty', 'geometry'):
    rows = results[bucket]
    if not rows:
        continue
    m = np.array([r['matches'] for r in rows], float)
    inl = np.array([r['inliers'] for r in rows], float)
    print(f"=== segments with {'NO' if bucket == 'empty' else ''} geometry: "
          f"{len(set(r['segment'] for r in rows))} segments, {len(rows)} consecutive keyframe pairs ===")
    print(f"  ORB matches   median {np.median(m):>6.0f}  p25 {np.percentile(m,25):>6.0f}  p75 {np.percentile(m,75):>6.0f}")
    print(f"  E inliers     median {np.median(inl):>6.0f}   pairs with >= {MIN_INLIERS} inliers: "
          f"{100*(inl>=MIN_INLIERS).mean():.1f}%")
    tri = np.array([r['tri'] for r in rows if r['tri'] is not None], float)
    if len(tri):
        print(f"  triangulation angle deg  median {np.median(tri):.3f}  p75 {np.percentile(tri,75):.3f}  "
              f"n={len(tri)}")
    c = Counter(r['verdict'] for r in rows)
    print("  verdict:")
    for k, v in c.most_common():
        print(f"    {k:>20} {v:>5} ({100*v/len(rows):>5.1f}%)")
    print()

emp = results['empty']
if emp:
    corr = sum(1 for r in emp if r['verdict'] in ('no_correspondence', 'no_essential', 'few_inliers', 'low_inlier_ratio'))
    par = sum(1 for r in emp if r['verdict'] in ('low_parallax', 'no_triangulation'))
    ok = sum(1 for r in emp if r['verdict'] == 'solvable')
    print("THE QUESTION THAT DECIDES WHETHER A BETTER MATCHER IS WORTH BUYING")
    print(f"  pairs inside empty segments:            {len(emp)}")
    print(f"  blocked by CORRESPONDENCE (buyable):    {corr}  ({100*corr/len(emp):.1f}%)")
    print(f"  blocked by BASELINE (not buyable):      {par}  ({100*par/len(emp):.1f}%)")
    print(f"  already solvable pair-wise:             {ok}  ({100*ok/len(emp):.1f}%)")
