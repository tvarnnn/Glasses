"""What does first-pair seeding cost, and what would re-seeding recover?

`estimate_window` seeds the chain from `features[0], features[1]` --
unconditionally, the first two keyframes of the segment -- and stops
chaining at the first link that does not solve. Both are visible in the
code and both are deliberate; neither has been measured.

The measurement matters because 22 of the 23 empty multi-keyframe segments
in this world contain at least one pairwise-solvable keyframe pair, and
segment 20 contains twenty-two of them while producing no geometry at all.

Three orchestrations are compared over the SAME segments, the SAME images
and the SAME private helpers (`_estimate_pair`, `_extend`), so nothing here
measures a different estimator -- only a different order of operations:

  baseline   seed (0,1), stop at the first failure. Reproduces what is on
             disk, which is the check that licenses the other two.
  best-seed  seed from the pair with the largest median triangulation
             angle, chain forward from there, stop at the first failure.
             Everything before the seed is left unavailable.
  re-seed    best-seed, and on a failure start a new sub-chain from the
             next solvable pair rather than abandoning the segment.
             Sub-chains do NOT share a coordinate frame or a unit, so each
             is reported as its own component -- this is the same honesty
             the engine already applies across segments, applied within
             one.

The last point is the one that must not be fudged. Re-seeding does not
join anything. It produces MORE independent fragments that each carry real
geometry, where today there is one fragment carrying none.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]

import numpy as np

sys.path.insert(0, str(TOWER_ROOT))
from tower.world_builder.backend import KeyframeInput
from tower.world_builder.backends import ClassicalTwoViewBackend
from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import detect_and_describe
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.schema import POSE_STATUS_SOLVED

WORLD = TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
SESS = WORLD / 'sessions/dd5d13a2381e430db9b27c7da2cf2928'
DER = WORLD / 'derived/dd5d13a2381e430db9b27c7da2cf2928'

session = json.loads((SESS / 'session.json').read_text())
intr = session['intrinsics']
backend = ClassicalTwoViewBackend()
backend.prepare(CameraIntrinsics(
    source=intr['source'], model=intr['model'],
    fx=intr['fx'], fy=intr['fy'], cx=intr['cx'], cy=intr['cy'],
    dist_coeffs=tuple(intr['dist_coeffs']),
    calibrated_width=intr['calibrated_width'],
    calibrated_height=intr['calibrated_height'],
    reprojection_rms_px=intr['reprojection_rms_px'],
    view_count=intr['view_count'],
))

kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]
by_seg = {}
for k in kfs:
    by_seg.setdefault(k['segment_index'], []).append(k)
for s in by_seg:
    by_seg[s].sort(key=lambda k: k['source_seq'])


def chain_from(features, start, n):
    """Chain forward from pair (start, start+1). Returns (solved, points, stop).

    Mirrors estimate_window's own loop, calling the same private helpers,
    so this measures orchestration and nothing else.
    """
    pair = backend._estimate_pair(features[start], features[start + 1], 'x')
    if pair.estimate.status != POSE_STATUS_SOLVED:
        return 0, 0, start + 1
    absolute = {start: (np.eye(3), np.zeros(3)),
                start + 1: (pair.estimate.rotation, pair.estimate.translation)}
    landmarks = list(pair.points)
    observed = {}
    for offset, (ia, ib) in enumerate(pair.inlier_index_pairs):
        observed[(start, ia)] = offset
        observed[(start + 1, ib)] = offset
    solved = 1
    current = start + 2
    while current < n:
        est, new_points, new_observed, reobserved = backend._extend(
            features[current - 1], features[current], current - 1, current,
            absolute, landmarks, observed, 'x')
        if est.status != POSE_STATUS_SOLVED:
            break
        absolute[current] = (est.rotation, est.translation)
        observed.update(reobserved)
        base = len(landmarks)
        landmarks.extend(new_points)
        for key, off in new_observed.items():
            observed[key] = base + off
        solved += 1
        current += 1
    return solved, len(landmarks), current


def pair_angle(features, i):
    """Median triangulation angle of pair (i, i+1), or -1 if it will not solve."""
    pair = backend._estimate_pair(features[i], features[i + 1], 'x')
    if pair.estimate.status != POSE_STATUS_SOLVED:
        return -1.0
    return pair.estimate.median_triangulation_deg or 0.0


results = []
t0 = time.perf_counter()
for seg, members in sorted(by_seg.items()):
    n = len(members)
    if n < 2:
        results.append(dict(seg=seg, n=n, base_solved=0, base_points=0,
                            seed_solved=0, seed_points=0,
                            reseed_solved=0, reseed_points=0, reseed_components=0))
        continue
    features = [detect_and_describe(decode_gray((SESS / k['image_relpath']).read_bytes()))
                for k in members]

    b_solved, b_points, _ = chain_from(features, 0, n)

    angles = [pair_angle(features, i) for i in range(n - 1)]
    best = int(np.argmax(angles)) if max(angles) > 0 else None
    if best is None:
        s_solved = s_points = 0
    else:
        s_solved, s_points, _ = chain_from(features, best, n)

    # re-seed: repeatedly take the best remaining solvable pair forward.
    r_solved = r_points = r_comp = 0
    covered = np.zeros(n, bool)
    while True:
        cands = [i for i in range(n - 1)
                 if angles[i] > 0 and not covered[i] and not covered[i + 1]]
        if not cands:
            break
        i = max(cands, key=lambda j: angles[j])
        solved, points, stop = chain_from(features, i, n)
        if solved == 0:
            angles[i] = -1.0
            continue
        covered[i:stop] = True
        r_solved += solved
        r_points += points
        r_comp += 1

    results.append(dict(seg=seg, n=n, base_solved=b_solved, base_points=b_points,
                        seed_solved=s_solved, seed_points=s_points,
                        reseed_solved=r_solved, reseed_points=r_points,
                        reseed_components=r_comp))
    print(f"  seg {seg:>3} kf {n:>3} | base {b_solved:>3}/{b_points:>5} | "
          f"best-seed {s_solved:>3}/{s_points:>5} | re-seed {r_solved:>3}/{r_points:>5} "
          f"({r_comp} comp)", flush=True)

elapsed = time.perf_counter() - t0
json.dump(results, open(str(HERE / 'reseed.json'), 'w'), indent=1)


def tot(k):
    return sum(r[k] for r in results)


print()
print(f"{'orchestration':>14} {'solved poses':>13} {'points':>9} {'segments with geometry':>24} {'components':>11}")
for name, sk, pk in (('baseline', 'base_solved', 'base_points'),
                     ('best-seed', 'seed_solved', 'seed_points'),
                     ('re-seed', 'reseed_solved', 'reseed_points')):
    with_geom = sum(1 for r in results if r[pk] > 0)
    comp = tot('reseed_components') if name == 're-seed' else with_geom
    print(f"{name:>14} {tot(sk):>13} {tot(pk):>9} {with_geom:>24} {comp:>11}")
print()
print(f"on-disk truth for the baseline: 94 solved poses, 12023 points, 19 segments with geometry")
print(f"solve time for all three orchestrations over 51 segments: {elapsed:.1f} s")
