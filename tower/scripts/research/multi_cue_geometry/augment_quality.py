"""Is the geometry re-seeding ADDS as trustworthy as the geometry already there?

Point and pose counts are the wrong thing to be convinced by. This project's
own record contains a change that improved segment count while destroying a
third of the reconstruction, and the counter-lesson is written into
`keyframes.py`. A change that triples the point count is exactly the shape
of change that deserves the harder question first:

    are the ADDED components' landmarks as well conditioned, and as
    consistent with their own cameras, as the ones the baseline produced?

Three numbers per component, all computed the same way for both groups:

  seed triangulation angle   how much baseline the founding pair had. The
                             existing degeneracy criterion, reported rather
                             than only gated, so the two groups' conditioning
                             can be compared instead of assumed equal.

  reprojection error         median pixel error of every landmark in every
                             camera of its own component. Within a component
                             this IS a valid check -- the scale ambiguity
                             that makes reprojection useless for policing
                             cross-segment scale does not arise inside one
                             coordinate frame.

  landmarks per solved pose  density. A component that solves many poses
                             while triangulating almost nothing is a chain
                             that survived on re-observations without adding
                             structure.

If the added components are systematically worse on all three, re-seeding is
buying quantity with quality. If they match, the geometry was simply being
discarded.
"""
import json
import sys
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
intr = json.loads((SESS / 'session.json').read_text())['intrinsics']
K = np.array([[intr['fx'], 0, intr['cx']], [0, intr['fy'], intr['cy']], [0, 0, 1.0]])
backend = ClassicalTwoViewBackend()
backend.prepare(CameraIntrinsics(
    source=intr['source'], model=intr['model'], fx=intr['fx'], fy=intr['fy'],
    cx=intr['cx'], cy=intr['cy'], dist_coeffs=tuple(intr['dist_coeffs']),
    calibrated_width=intr['calibrated_width'], calibrated_height=intr['calibrated_height'],
    reprojection_rms_px=intr['reprojection_rms_px'], view_count=intr['view_count']))

kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]
by_seg = {}
for k in kfs:
    by_seg.setdefault(k['segment_index'], []).append(k)
for s in by_seg:
    by_seg[s].sort(key=lambda k: k['source_seq'])


def chain(features, start, stop_limit):
    """Chain forward, returning enough to score the component."""
    pair = backend._estimate_pair(features[start], features[start + 1], 'x')
    if pair.estimate.status != POSE_STATUS_SOLVED:
        return None
    seed_angle = pair.estimate.median_triangulation_deg or 0.0
    absolute = {start: (np.eye(3), np.zeros(3)),
                start + 1: (pair.estimate.rotation, pair.estimate.translation)}
    landmarks = list(pair.points)
    observed = {}
    obs_rows = []
    for off, (ia, ib) in enumerate(pair.inlier_index_pairs):
        observed[(start, ia)] = off
        observed[(start + 1, ib)] = off
        obs_rows.append((start, ia, off))
        obs_rows.append((start + 1, ib, off))
    solved, cur = 1, start + 2
    while cur < stop_limit:
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
        for (f, feat_i), lm in reobs.items():
            obs_rows.append((f, feat_i, lm))
        base = len(landmarks)
        landmarks.extend(new_pts)
        for key, off in new_obs.items():
            observed[key] = base + off
            obs_rows.append((key[0], key[1], base + off))
        solved += 1
        cur += 1
    return dict(start=start, stop=cur, solved=solved, seed_angle=float(seed_angle),
                landmarks=np.asarray(landmarks, float), absolute=absolute,
                obs=obs_rows)


def reprojection(comp, features):
    xyz = comp['landmarks']
    if len(xyz) == 0:
        return None
    errs = []
    for frame_i, feat_i, lm in comp['obs']:
        pose = comp['absolute'].get(frame_i)
        if pose is None or lm >= len(xyz):
            continue
        R, t = pose
        cam = R @ xyz[lm] + np.asarray(t).reshape(3)
        if cam[2] <= 1e-6:
            continue
        uv = (K @ cam)[:2] / cam[2]
        kp = features[frame_i][0][feat_i].pt
        errs.append(float(np.hypot(uv[0] - kp[0], uv[1] - kp[1])))
    return float(np.median(errs)) if errs else None


groups = {'baseline': [], 'added': []}
for seg, members in sorted(by_seg.items()):
    n = len(members)
    if n < 2:
        continue
    features = [detect_and_describe(decode_gray((SESS / k['image_relpath']).read_bytes()))
                for k in members]
    covered = np.zeros(n, bool)

    base = chain(features, 0, n)
    if base is not None:
        covered[base['start']:base['stop']] = True
        groups['baseline'].append((base, features))

    angles = []
    for i in range(n - 1):
        p = backend._estimate_pair(features[i], features[i + 1], 'x')
        angles.append(p.estimate.median_triangulation_deg or 0.0
                      if p.estimate.status == POSE_STATUS_SOLVED else -1.0)
    while True:
        cands = [i for i in range(n - 1)
                 if angles[i] > 0 and not covered[i] and not covered[i + 1]]
        if not cands:
            break
        i = max(cands, key=lambda j: angles[j])
        limit = next((j for j in range(i + 1, n) if covered[j]), n)
        if limit - i < 2:
            angles[i] = -1.0
            continue
        comp = chain(features, i, limit)
        if comp is None:
            angles[i] = -1.0
            continue
        covered[comp['start']:comp['stop']] = True
        groups['added'].append((comp, features))

print(f"{'group':>10} {'components':>11} {'solved poses':>13} {'points':>8} "
      f"{'seed angle deg':>15} {'reproj px':>11} {'pts/pose':>9}")
for name in ('baseline', 'added'):
    comps = groups[name]
    if not comps:
        continue
    angles = np.array([c['seed_angle'] for c, _ in comps])
    pts = np.array([len(c['landmarks']) for c, _ in comps], float)
    poses = np.array([c['solved'] for c, _ in comps], float)
    reps = [reprojection(c, f) for c, f in comps]
    reps = np.array([r for r in reps if r is not None])
    print(f"{name:>10} {len(comps):>11} {int(poses.sum()):>13} {int(pts.sum()):>8} "
          f"{np.median(angles):>15.3f} {np.median(reps):>11.3f} "
          f"{np.median(pts / np.maximum(poses, 1)):>9.0f}")
print()
for name in ('baseline', 'added'):
    comps = groups[name]
    if not comps:
        continue
    reps = np.array([r for r in (reprojection(c, f) for c, f in comps) if r is not None])
    angles = np.array([c['seed_angle'] for c, _ in comps])
    print(f"{name}: reprojection p90 {np.percentile(reps, 90):.2f} px, "
          f"components above 3 px {100 * (reps > 3).mean():.1f}%; "
          f"seed angle p10 {np.percentile(angles, 10):.3f} deg")
