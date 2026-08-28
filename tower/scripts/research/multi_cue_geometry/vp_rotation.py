"""Does the vanishing-direction triplet carry the camera's rotation?

The decisive test for the line cue. Everything else about lines --
coverage, cost, yield -- is irrelevant if the recovered Manhattan frame
does not track the camera, so it is measured first and on its own.

There is no ground truth on this corpus, so the reference is the existing
pipeline's own rotation estimate, computed two independent ways:

  E-pose  ORB + essential matrix + recoverPose, restricted to pairs the
          pipeline itself would call solvable (>= MIN_INLIERS inliers,
          inlier ratio >= MIN_INLIER_RATIO, median triangulation angle
          >= MIN_TRIANGULATION_ANGLE_DEG). Trustworthy where it applies,
          degenerate under pure rotation -- which is the common case here.

  H-rot   R = K^-1 H K projected onto SO(3). Exact under pure rotation,
          biased once the camera translates. It covers precisely the
          regime E-pose cannot.

The two references fail in opposite regimes, so agreement with BOTH is
much stronger evidence than agreement with either.

And the null matters more than the reference: `identity` predicts no
rotation at all. Between frames 83 ms apart the true rotation is small,
so a cue that "agrees to 3 degrees" may simply be reporting that little
happened. Any claim for the cue has to beat identity, not zero.
"""
import json
import sys
import time
from itertools import permutations
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]

import cv2
import numpy as np

sys.path.insert(0, str(TOWER_ROOT))
sys.path.insert(0, str(HERE))
from lines import (detect_segments, manhattan_frame, refine_manhattan,
                   segment_normals)
from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import (MIN_INLIER_RATIO, MIN_INLIERS,
                                          MIN_TRIANGULATION_ANGLE_DEG,
                                          RANSAC_CONFIDENCE,
                                          RANSAC_THRESHOLD_PX,
                                          detect_and_describe,
                                          match_descriptors,
                                          median_triangulation_angle_deg)

INTR = json.loads(TOWER_ROOT / 'data/world_builder/intrinsics/360x640.json'.read_text())
K = np.array([[INTR['fx'], 0, INTR['cx']],
              [0, INTR['fy'], INTR['cy']],
              [0, 0, 1.0]])
KINV = np.linalg.inv(K)

MOVING = ["22e9d4289cb440fbb3f14e6da369a136", "b35d8ab85c364b9da44499d2a7f00638",
          "20ce3c2366ee4cdfb46cb8db09578058", "ab10cb203cf048e58cf2f79a120a54a4",
          "5387a76568e84e13936862f612f8bc81", "e1c52b9ff7f84dd5a54fee6150b7f854",
          "854e9688d2c54ae398eff4fb7c141522", "fe744b6827c44e3e8c3a309d665dbf80"]

# The 24 signed permutations with determinant +1 -- the exact gauge freedom
# of an unlabelled orthogonal triplet.
GAUGES = []
for _perm in permutations(range(3)):
    for _signs in range(8):
        _P = np.zeros((3, 3))
        for _r, _c in enumerate(_perm):
            _P[_r, _c] = -1.0 if (_signs >> _r) & 1 else 1.0
        if abs(np.linalg.det(_P) - 1.0) < 1e-9:
            GAUGES.append(_P)


def ang(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1, 1))))


def geodesic(Ra, Rb):
    return ang(Ra.T @ Rb)


def project_so3(M):
    U, _, Vt = np.linalg.svd(M)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    return R


def manhattan(gray, tol=3.0, iters=400):
    seg = detect_segments(gray)
    if len(seg) < 12:
        return None, len(seg)
    length = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1])
    normals = segment_normals(seg, K)
    mf = manhattan_frame(normals, length, tol_deg=tol, iters=iters,
                         rng=np.random.default_rng(0))
    if mf is None:
        return None, len(seg)
    return refine_manhattan(normals, length, mf[0], tol_deg=tol), len(seg)


def vp_relative(Ra, Rb):
    """Relative camera rotation b<-a, gauge resolved by smallest rotation.

    Returns (R, best_deg, second_best_deg). The margin is reported because
    picking the smallest of 24 candidates is only honest if the winner is
    clearly separated; a small margin means the answer was a coin flip.
    """
    cands = sorted((ang(Rb.T @ P.T @ Ra), Rb.T @ P.T @ Ra) for P in GAUGES)
    return cands[0][1], cands[0][0], cands[1][0]


rows = []
t_line, t_orb = [], []
for cap_id in MOVING:
    cap = TOWER_ROOT / 'data/captures' / cap_id
    fr = [json.loads(x) for x in (cap / 'frames.jsonl').read_text().splitlines() if x.strip()]
    for i in np.linspace(0, len(fr) - 2, 150).astype(int):
        a, b = fr[i], fr[i + 1]
        dt = b['received_at'] - a['received_at']
        if not (0.04 < dt < 0.2):
            continue
        ga = decode_gray((cap / a['relpath']).read_bytes())
        gb = decode_gray((cap / b['relpath']).read_bytes())

        t0 = time.perf_counter()
        Ra, na = manhattan(ga)
        Rb, nb = manhattan(gb)
        t_line.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        ka, da = detect_and_describe(ga)
        kb, db = detect_and_describe(gb)
        pa, pb = match_descriptors(ka, da, kb, db)
        t_orb.append((time.perf_counter() - t0) * 1000)

        R_e = R_h = None
        tri = None
        inl = 0
        ratio = 0.0
        if len(pa) >= 8:
            E, mask = cv2.findEssentialMat(pa, pb, K, cv2.RANSAC,
                                           RANSAC_CONFIDENCE, RANSAC_THRESHOLD_PX)
            if E is not None and E.shape == (3, 3) and mask is not None:
                inl = int(mask.sum())
                ratio = inl / len(pa)
                if inl >= MIN_INLIERS and ratio >= MIN_INLIER_RATIO:
                    m = mask.ravel().astype(bool)
                    _, Rr, tt, _ = cv2.recoverPose(E, pa[m], pb[m], K)
                    tri = median_triangulation_angle_deg(pa[m], pb[m], Rr, tt, K)
                    if tri is not None and tri >= MIN_TRIANGULATION_ANGLE_DEG:
                        R_e = Rr
            H, hm = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
            if H is not None and hm is not None and int(hm.sum()) >= 20:
                R_h = project_so3(KINV @ H @ K)

        rec = dict(cap=cap_id, seq=a['source_seq'], n_seg_a=na, n_seg_b=nb,
                   orb_matches=len(pa), e_inliers=inl, e_ratio=round(ratio, 3),
                   tri=None if tri is None else round(tri, 3))
        if Ra is not None and Rb is not None:
            R_vp, g1, g2 = vp_relative(Ra, Rb)
            rec.update(vp=True, vp_deg=round(g1, 3), gauge_margin=round(g2 - g1, 3))
            if R_e is not None:
                rec['err_vp_e'] = round(geodesic(R_vp, R_e), 3)
                rec['err_id_e'] = round(ang(R_e), 3)
            if R_h is not None:
                rec['err_vp_h'] = round(geodesic(R_vp, R_h), 3)
                rec['err_id_h'] = round(ang(R_h), 3)
        else:
            rec.update(vp=False)
        if R_e is not None and R_h is not None:
            rec['err_e_h'] = round(geodesic(R_e, R_h), 3)
        rows.append(rec)

json.dump(rows, open(str(HERE / 'vp_rotation.json'), 'w'))


def stats(key):
    v = [r[key] for r in rows if key in r]
    if not v:
        return None
    v = np.array(v, float)
    return len(v), np.median(v), np.percentile(v, 90)


print(f"pairs examined: {len(rows)}   VP found in both frames: {sum(r['vp'] for r in rows)}")
print(f"E-pose reference available: {sum('err_id_e' in r for r in rows)}")
print(f"H-rot reference available:  {sum('err_id_h' in r for r in rows)}")
print()
print(f"{'comparison':32} {'n':>5} {'median deg':>11} {'p90 deg':>9}")
for k, label in [('err_e_h', 'E-pose vs H-rot (do refs agree)'),
                 ('err_vp_e', 'VP vs E-pose'),
                 ('err_id_e', 'IDENTITY vs E-pose (null)'),
                 ('err_vp_h', 'VP vs H-rot'),
                 ('err_id_h', 'IDENTITY vs H-rot (null)')]:
    s = stats(k)
    if s:
        print(f"{label:32} {s[0]:>5} {s[1]:>11.2f} {s[2]:>9.2f}")
print()
print("Paired, only where both VP and the reference exist:")
for ref in ('e', 'h'):
    pairs = [(r[f'err_vp_{ref}'], r[f'err_id_{ref}']) for r in rows if f'err_vp_{ref}' in r]
    if not pairs:
        continue
    arr = np.array(pairs)
    print(f"  ref={ref}  n={len(arr):4d}  VP median {np.median(arr[:, 0]):6.2f}  "
          f"identity median {np.median(arr[:, 1]):6.2f}  "
          f"VP beats identity on {100 * (arr[:, 0] < arr[:, 1]).mean():.1f}% of pairs")
print()
g = np.array([r['gauge_margin'] for r in rows if 'gauge_margin' in r])
if len(g):
    print(f"gauge margin (2nd best minus best, deg): median {np.median(g):.1f}  p10 {np.percentile(g, 10):.1f}")
print(f"cost per frame-pair: lines+Manhattan x2 {np.median(t_line):.1f} ms   ORB+match x2 {np.median(t_orb):.1f} ms")
