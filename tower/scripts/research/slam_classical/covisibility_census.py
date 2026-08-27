"""Does this corpus CONTAIN the covisibility a classical SLAM stack needs?

The repo already measured that bundle adjustment bought 0.00% drift
improvement at 16, 32 and 104 keyframes, and already diagnosed why: the
observation graph is a CHAIN, because `_extend` matches each keyframe only
to the previous one, so median covisibility span is 1. A chain has no
cycle, so it has no redundant constraint, so BA is a no-op up to
reparameterisation.

That diagnosis says BA-without-covisibility is worthless. It does NOT say
covisibility is AVAILABLE. Those are different claims and only one has
been measured. This harness measures the other one.

Method: take the 457 keyframes the shipped tracker actually accepted on
the canonical capture, with the segment labels it actually assigned, and
match EVERY pair -- all 104,196 of them -- with the SAME ORB detector and
the SAME Lowe ratio matcher production already uses. Nothing here is a
better frontend. The only thing that changes is WHICH PAIRS ARE ASKED.

If the all-pairs graph is still a chain, the failure is a sensor/capture
ceiling and the whole Atlas/loop-closure recommendation collapses. If it
is dense, the failure is that the architecture never asked.

Two things are recorded separately because they answer different
questions and get conflated constantly:

  LOCAL covisibility (small keyframe gap) is what makes local BA
  non-vacuous.  LONG-RANGE / CROSS-SEGMENT covisibility is what loop
  closure and Atlas map merging need. A corpus can have plenty of the
  first and none of the second.

And appearance overlap is recorded separately from GEOMETRIC USEFULNESS.
Two keyframes can share 300 verified features from the same viewpoint and
still carry no baseline, which is exactly the trap the prior lanes found
(54.7% of failing pairs are baseline-limited). So every verified pair also
gets a median triangulation angle and an r_H.

NO GROUND TRUTH EXISTS. Every number here is comparative / self-consistency.

Usage:  python scripts/research/slam_classical/covisibility_census.py [out.json]
"""
import json
import os
import sys
import time
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]
sys.path.insert(0, str(TOWER_ROOT))

import cv2
import numpy as np

from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import (LOWE_RATIO, MIN_INLIERS,
                                          MIN_TRIANGULATION_ANGLE_DEG,
                                          ORB_FEATURES,
                                          detect_and_describe,
                                          median_triangulation_angle_deg)

WORLD = TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
SESS = WORLD / 'sessions/dd5d13a2381e430db9b27c7da2cf2928'
INTR = json.loads((TOWER_ROOT / 'data/world_builder/intrinsics/360x640.json').read_text())
K = np.array([[INTR['fx'], 0, INTR['cx']],
              [0, INTR['fy'], INTR['cy']],
              [0, 0, 1.0]])

# ORB-SLAM3 creates a covisibility edge at 15 shared map points
# (KeyFrame::UpdateConnections) and puts an edge in the essential graph at
# 100. Both are reproduced here against VERIFIED MATCHES rather than
# shared landmarks, which is an UPPER BOUND on the real weight -- not every
# matched feature survives to become a triangulated map point.
COVIS_EDGE_TH = 15
ESSENTIAL_GRAPH_TH = 100

_G = {}


def _init(payload):
    _G['pts'] = payload['pts']
    _G['desc'] = payload['desc']


def _inliers(model, mask):
    """Inlier count that is SAFE on OpenCV 5.0.

    MEASURED on this host: when cv2 5.0's RANSAC fails to fit, it returns
    model=None and leaves the output mask UNINITIALISED -- observed unique
    values [0, 1, 4, 5, 16, 36] on a 242-match pair, and a different sum on
    a repeat run. Reading that mask without first checking the model yields
    a garbage inlier count (the first run of this census reported 41,885
    inliers on 242 matches). A failed fit means NO CONSISTENT GEOMETRY,
    which is exactly 0 inliers, so the model check is the whole guard.
    """
    if model is None or mask is None:
        return 0
    return int((mask.ravel() > 0).sum())


def _ratio_matches(da, db):
    """Lowe-ratio matches as (queryIdx, trainIdx), production's settings."""
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    return [(p[0].queryIdx, p[0].trainIdx) for p in matcher.knnMatch(da, db, k=2)
            if len(p) == 2 and p[0].distance < LOWE_RATIO * p[1].distance]


def _pair(job):
    i, j = job
    da, db = _G['desc'][i], _G['desc'][j]
    out = dict(i=i, j=j, matches=0, mutual=0, f_inliers=0, e_inliers=0,
               f_failed=False, h_failed=False, tri_angle=None, r_h=None)
    if da is None or db is None or len(da) < 2 or len(db) < 2:
        return out

    fwd = _ratio_matches(da, db)
    out['matches'] = len(fwd)
    if len(fwd) < 8:
        return out

    # RECIPROCITY. Prior in-repo research proved reprojection error is NOT a
    # safety check and reciprocity IS. Match the other way too and keep only
    # correspondences both directions agree on. Recorded as its own column so
    # its filtering power can be measured rather than assumed.
    rev = {t: q for q, t in _ratio_matches(db, da)}
    mutual = [(q, t) for q, t in fwd if rev.get(q) == t]
    out['mutual'] = len(mutual)

    pa = _G['pts'][i][[q for q, _ in fwd]]
    pb = _G['pts'][j][[t for _, t in fwd]]

    # Geometric verification, exactly the check a loop-closure candidate
    # must survive before it is allowed to move the map.
    F, fmask = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)
    out['f_failed'] = F is None
    out['f_inliers'] = _inliers(F, fmask)

    H, hmask = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
    out['h_failed'] = H is None
    h_in = _inliers(H, hmask)
    tot = h_in + out['f_inliers']
    if tot:
        out['r_h'] = h_in / tot

    if out['f_inliers'] < MIN_INLIERS:
        return out

    # Appearance overlap is not baseline. Ask the geometry whether these
    # two views actually see the scene from different places.
    E, emask = cv2.findEssentialMat(pa, pb, K, cv2.RANSAC, 0.999, 1.0)
    if E is None or E.shape != (3, 3) or emask is None:
        return out
    n_in, R, t, pmask = cv2.recoverPose(E, pa, pb, K, mask=emask.copy())
    out['e_inliers'] = int(n_in)
    keep = pmask.ravel() > 0
    if keep.sum() >= 2:
        out['tri_angle'] = median_triangulation_angle_deg(
            pa[keep], pb[keep], R, t, K)
    return out


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'covisibility_census.json'
    kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]
    n = len(kfs)
    print(f"keyframes={n}  segments={len({k['segment_index'] for k in kfs})}  "
          f"cv2={cv2.__version__}  orb_features={ORB_FEATURES}  lowe={LOWE_RATIO}")

    t0 = time.perf_counter()
    pts, desc, feat_counts = [], [], []
    for k in kfs:
        gray = decode_gray((SESS / k['image_relpath']).read_bytes())
        kp, d = detect_and_describe(gray)
        pts.append(np.float32([p.pt for p in kp]).reshape(-1, 2) if kp
                   else np.empty((0, 2), np.float32))
        desc.append(d)
        feat_counts.append(len(kp))
    t_detect = time.perf_counter() - t0
    print(f"detect: {t_detect:.1f}s  ({t_detect / n * 1000:.1f} ms/kf)  "
          f"features median={int(np.median(feat_counts))} "
          f"min={min(feat_counts)} max={max(feat_counts)}")

    jobs = list(combinations(range(n), 2))
    print(f"pairs: {len(jobs)}")

    import multiprocessing as mp
    workers = max(1, min(12, (os.cpu_count() or 4) - 2))
    t0 = time.perf_counter()
    payload = dict(pts=pts, desc=desc)
    rows = []
    with mp.Pool(workers, initializer=_init, initargs=(payload,)) as pool:
        for idx, r in enumerate(pool.imap_unordered(_pair, jobs, chunksize=256)):
            rows.append(r)
            if idx % 20000 == 0 and idx:
                print(f"  {idx}/{len(jobs)}  {time.perf_counter() - t0:.0f}s", flush=True)
    t_match = time.perf_counter() - t0
    print(f"all-pairs: {t_match:.1f}s on {workers} workers "
          f"({t_match / len(jobs) * 1000 * workers:.2f} ms/pair/core)")

    meta = dict(
        n_keyframes=n, n_pairs=len(jobs),
        segment_index=[k['segment_index'] for k in kfs],
        source_seq=[k['source_seq'] for k in kfs],
        feature_counts=feat_counts,
        cv2=cv2.__version__, orb_features=ORB_FEATURES, lowe=LOWE_RATIO,
        covis_edge_th=COVIS_EDGE_TH, essential_graph_th=ESSENTIAL_GRAPH_TH,
        min_inliers=MIN_INLIERS, min_tri_angle=MIN_TRIANGULATION_ANGLE_DEG,
        t_detect_s=t_detect, t_match_s=t_match, workers=workers,
    )
    out_path.write_text(json.dumps(dict(meta=meta, pairs=rows)))
    print(f"wrote {out_path}  ({out_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == '__main__':
    main()
