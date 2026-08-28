"""Can a monocular depth prior catch a wrong scale that reprojects perfectly?

This is the one job worth asking depth to do here. Registration's stated
failure mode is that segment pair (30,50) fits at 1.62 px median with 88%
of correspondences under 3 px while being wrong by a factor of 3.2 in
scale -- so reprojection error cannot police scale, and the current defence
is reciprocity between two independent solves. A depth prior would be a
THIRD, differently-sourced opinion, and MiDaS-small is already vendored,
already measured at 18.3 ms on CPU, and already runs on this corpus.

The premise it rests on is testable directly and cheaply, and it is tested
here before any registration machinery is touched:

    Does MiDaS-small's relative depth agree with the SfM depth of the
    landmarks the pipeline itself triangulated, well enough to bound a
    scale factor?

Method. For each solved component, take its triangulated landmarks, project
them into each solved keyframe, and read MiDaS's inverse depth at that
pixel. MiDaS-small emits RELATIVE INVERSE depth with an unknown affine
transform -- d_midas ~ a / z + b -- so the comparison must be affine
invariant. Two statistics are reported:

  SPEARMAN     rank correlation between MiDaS inverse depth and 1/z.
               Invariant to any monotone transform, so it tests ORDERING
               only. This is the weakest claim depth could support and the
               most likely to hold.

  SCALE SPREAD after fitting the affine transform per frame by least
               squares, the ratio (p84/p16) of implied z. This is the
               number that decides the actual job: to reject a 3.2x scale
               error the prior must itself be tighter than 3.2x, and by a
               margin, or it will reject correct registrations too.

An ordering that correlates while the scale spread is wide would mean depth
can say "which is nearer" and cannot say "by how much" -- which is exactly
the distinction between the claim the Scene Understanding work already
refused and the claim registration would need.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]

import cv2
import numpy as np

sys.path.insert(0, str(TOWER_ROOT))
from tower.world_builder.backends import ClassicalTwoViewBackend
from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import detect_and_describe
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.schema import POSE_STATUS_SOLVED

WORLD = TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
SESS = WORLD / 'sessions/dd5d13a2381e430db9b27c7da2cf2928'
session = json.loads((SESS / 'session.json').read_text())
intr = session['intrinsics']
K = np.array([[intr['fx'], 0, intr['cx']], [0, intr['fy'], intr['cy']], [0, 0, 1.0]])

backend = ClassicalTwoViewBackend()
backend.prepare(CameraIntrinsics(
    source=intr['source'], model=intr['model'], fx=intr['fx'], fy=intr['fy'],
    cx=intr['cx'], cy=intr['cy'], dist_coeffs=tuple(intr['dist_coeffs']),
    calibrated_width=intr['calibrated_width'], calibrated_height=intr['calibrated_height'],
    reprojection_rms_px=intr['reprojection_rms_px'], view_count=intr['view_count']))

import torch
device = 'cuda' if torch.cuda.is_available() else 'cpu'
midas = torch.hub.load('intel-isl/MiDaS', 'MiDaS_small', trust_repo=True).to(device).eval()
transforms = torch.hub.load('intel-isl/MiDaS', 'transforms', trust_repo=True)
midas_transform = transforms.small_transform


def depth_map(gray):
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    batch = midas_transform(rgb).to(device)
    with torch.no_grad():
        pred = midas(batch)
        pred = torch.nn.functional.interpolate(
            pred.unsqueeze(1), size=gray.shape[:2],
            mode='bicubic', align_corners=False).squeeze()
    return pred.cpu().numpy()


kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]
by_seg = {}
for k in kfs:
    by_seg.setdefault(k['segment_index'], []).append(k)
for s in by_seg:
    by_seg[s].sort(key=lambda k: k['source_seq'])


def spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean()
    rb -= rb.mean()
    den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den > 0 else np.nan


rows = []
t_depth = []
for seg, members in sorted(by_seg.items()):
    n = len(members)
    if n < 3:
        continue
    grays = [decode_gray((SESS / k['image_relpath']).read_bytes()) for k in members]
    features = [detect_and_describe(g) for g in grays]

    pair = backend._estimate_pair(features[0], features[1], 'x')
    if pair.estimate.status != POSE_STATUS_SOLVED:
        continue
    seed_angle = pair.estimate.median_triangulation_deg or 0.0
    absolute = {0: (np.eye(3), np.zeros(3)),
                1: (pair.estimate.rotation, pair.estimate.translation)}
    landmarks = list(pair.points)
    observed = {}
    for off, (ia, ib) in enumerate(pair.inlier_index_pairs):
        observed[(0, ia)] = off
        observed[(1, ib)] = off
    for cur in range(2, n):
        try:
            est, new_pts, new_obs, reobs = backend._extend(
                features[cur - 1], features[cur], cur - 1, cur,
                absolute, landmarks, observed, 'x')
        except cv2.error:
            break
        if est.status != POSE_STATUS_SOLVED:
            break
        absolute[cur] = (est.rotation, est.translation)
        observed.update(reobs)
        base = len(landmarks)
        landmarks.extend(new_pts)
        for key, off in new_obs.items():
            observed[key] = base + off
    if len(landmarks) < 50 or len(absolute) < 2:
        continue

    xyz = np.asarray(landmarks, float)
    for idx, (R, t) in sorted(absolute.items()):
        cam = (R @ xyz.T).T + np.asarray(t).reshape(3)
        z = cam[:, 2]
        front = z > 1e-6
        if front.sum() < 40:
            continue
        proj = (K @ cam[front].T).T
        uv = proj[:, :2] / proj[:, 2:3]
        h, w = grays[idx].shape[:2]
        inside = ((uv[:, 0] >= 0) & (uv[:, 0] < w - 1) &
                  (uv[:, 1] >= 0) & (uv[:, 1] < h - 1))
        if inside.sum() < 40:
            continue
        t0 = time.perf_counter()
        dm = depth_map(grays[idx])
        t_depth.append((time.perf_counter() - t0) * 1000)

        zz = z[front][inside]
        u = uv[inside, 0].astype(int)
        v = uv[inside, 1].astype(int)
        d = dm[v, u].astype(float)
        inv = 1.0 / zz

        rho = spearman(d, inv)
        # Affine fit d ~ a*inv + b, then invert to implied z and measure how
        # tight the agreement is in the units that matter.
        A = np.stack([inv, np.ones_like(inv)], 1)
        coef, *_ = np.linalg.lstsq(A, d, rcond=None)
        a, b = coef
        with np.errstate(divide='ignore', invalid='ignore'):
            z_implied = a / (d - b)
        ok = np.isfinite(z_implied) & (z_implied > 0)
        if ok.sum() < 30:
            continue
        ratio = z_implied[ok] / zz[ok]
        spread = float(np.percentile(ratio, 84) / np.percentile(ratio, 16))
        rows.append(dict(seg=seg, frame=idx, n=int(ok.sum()), rho=rho,
                         spread=spread, seed_angle=float(seed_angle),
                         solved_frames=len(absolute),
                         z_dyn=float(np.percentile(zz, 90) / max(np.percentile(zz, 10), 1e-9)),
                         p16=float(np.percentile(ratio, 16)),
                         p84=float(np.percentile(ratio, 84))))

json.dump(rows, open(str(HERE / 'depth_scale.json'), 'w'))
rho = np.array([r['rho'] for r in rows])
spread = np.array([r['spread'] for r in rows])
print(f"device {device}   frames compared {len(rows)}   "
      f"segments {len(set(r['seg'] for r in rows))}")
print(f"landmarks per frame: median {np.median([r['n'] for r in rows]):.0f}")
print()
print("ORDERING -- Spearman(MiDaS inverse depth, 1/z_sfm)")
print(f"  median {np.median(rho):.3f}   p25 {np.percentile(rho,25):.3f}   "
      f"p75 {np.percentile(rho,75):.3f}")
print(f"  frames with rho > 0.5: {100*(rho>0.5).mean():.1f}%   "
      f"rho < 0: {100*(rho<0).mean():.1f}%")
print()
print("SCALE -- spread of implied/actual depth after per-frame affine fit")
print(f"  p84/p16 ratio: median {np.median(spread):.2f}x   "
      f"p25 {np.percentile(spread,25):.2f}x   p75 {np.percentile(spread,75):.2f}x")
print(f"  frames tighter than 1.5x: {100*(spread<1.5).mean():.1f}%")
print(f"  frames tighter than 3.2x (the error it would need to catch): "
      f"{100*(spread<3.2).mean():.1f}%")
print()
print(f"MiDaS cost per frame on {device}: median {np.median(t_depth):.1f} ms")
print()
print("Is the disagreement SfM's fault? Stratified by how well-conditioned the")
print("component's seeding pair was, and by how much depth range the landmarks span.")
sa = np.array([r['seed_angle'] for r in rows])
dyn = np.array([r['z_dyn'] for r in rows])
print(f"{'seed triangulation angle':>26} {'n':>4} {'median rho':>11} {'median spread':>14}")
for lo, hi in [(0, 1), (1, 2), (2, 5), (5, 1e9)]:
    m = (sa >= lo) & (sa < hi)
    if m.sum() < 3:
        continue
    print(f"{f'{lo}-{hi} deg':>26} {m.sum():>4} {np.median(rho[m]):>11.3f} {np.median(spread[m]):>13.2f}x")
print(f"{'landmark depth range p90/p10':>26} {'n':>4} {'median rho':>11} {'median spread':>14}")
for lo, hi in [(0, 3), (3, 10), (10, 100), (100, 1e12)]:
    m = (dyn >= lo) & (dyn < hi)
    if m.sum() < 3:
        continue
    print(f"{f'{lo}-{hi}x':>26} {m.sum():>4} {np.median(rho[m]):>11.3f} {np.median(spread[m]):>13.2f}x")
