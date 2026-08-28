"""Corpus harness: real frontend, real backend, three orchestrations.

Replays each capture through the shipped `FrameTracker` and
`KeyframeSelector` -- so the segmentation is the one the current tracker
constants produce, not the one frozen in an older world on disk -- and then
solves every segment three ways with the shipped `_estimate_pair` /
`_extend`.

Reports the metrics the brief asks for, including the one that is easy to
lose: LARGEST COHERENT COMPONENT. Points and poses can both rise while the
map gets worse, because a component is what actually shares a coordinate
frame and a unit. A run that triples the point count into a hundred
unrelatable fragments has not built a better map, and only the component
distribution says which happened.

Usage:  python scripts/research/multi_cue_geometry/corpus_solve.py [n_captures]
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
from tower.world_builder.frontend import FrameTracker, analyse_frame, decode_gray
from tower.world_builder.geometry import detect_and_describe
from tower.world_builder.keyframes import KeyframeSelector
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.schema import POSE_STATUS_SOLVED

INTR_JSON = json.loads(TOWER_ROOT / 'data/world_builder/intrinsics/360x640.json'.read_text())
INTRINSICS = CameraIntrinsics(
    source=INTR_JSON['source'], model=INTR_JSON['model'],
    fx=INTR_JSON['fx'], fy=INTR_JSON['fy'],
    cx=INTR_JSON['cx'], cy=INTR_JSON['cy'],
    dist_coeffs=tuple(INTR_JSON['dist_coeffs']),
    calibrated_width=INTR_JSON['calibrated_width'],
    calibrated_height=INTR_JSON['calibrated_height'],
    reprojection_rms_px=INTR_JSON['reprojection_rms_px'],
    view_count=INTR_JSON['view_count'],
)

MOVING = ["22e9d4289cb440fbb3f14e6da369a136", "b35d8ab85c364b9da44499d2a7f00638",
          "20ce3c2366ee4cdfb46cb8db09578058", "ab10cb203cf048e58cf2f79a120a54a4",
          "5387a76568e84e13936862f612f8bc81", "e1c52b9ff7f84dd5a54fee6150b7f854",
          "854e9688d2c54ae398eff4fb7c141522", "fe744b6827c44e3e8c3a309d665dbf80"]

ORCHESTRATIONS = ('baseline', 'reseed', 'augment')

backend = ClassicalTwoViewBackend()
backend.prepare(INTRINSICS)


def segment_keyframes(cap_id):
    """Replay the real frontend. Returns a list of segments, each a list of
    grayscale keyframe images."""
    cap = TOWER_ROOT / 'data/captures' / cap_id
    rows = [json.loads(x) for x in (cap / 'frames.jsonl').read_text().splitlines() if x.strip()]
    tracker, selector = FrameTracker(), KeyframeSelector()
    segments, current = [], []
    for row in rows:
        try:
            gray = decode_gray((cap / row['relpath']).read_bytes())
        except ValueError:
            continue
        quality = analyse_frame(gray)
        selector.note_frame(quality)
        motion = tracker.measure(gray)
        decision = selector.evaluate(quality, motion)
        if decision.lost:
            if current:
                segments.append(current)
            current = []
            tracker.reset()
            selector.note_lost()
            continue
        if decision.accepted:
            current.append(gray)
            tracker.set_reference(gray)
            selector.note_accepted()
    if current:
        segments.append(current)
    return segments


PNP_CRASHES = []


def chain_from(features, start, n):
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
    solved, current = 1, start + 2
    while current < n:
        # cv2.solvePnPRansac(SOLVEPNP_SQPNP) ASSERTS on some degenerate
        # correspondence sets rather than returning ok=False:
        #   sqpnp.cpp:274: (-215) ++num_null_vectors_ <= 6
        # This is not a harness problem -- `_extend` is the shipped code
        # path and it does not catch it. Counted here rather than hidden,
        # because how often it fires is the number that says whether the
        # production path is exposed.
        try:
            est, new_points, new_observed, reobserved = backend._extend(
                features[current - 1], features[current], current - 1, current,
                absolute, landmarks, observed, 'x')
        except cv2.error as exc:
            PNP_CRASHES.append(str(exc).splitlines()[-1][:90])
            break
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


def solve_segment(features):
    """Returns dict of (poses, points, components) for each orchestration.

    A component is (keyframes_in_it, points_in_it) -- keyframes, because
    that is what shares a frame, and a component of one keyframe shares a
    frame with nothing.
    """
    n = len(features)
    out = {}
    if n < 2:
        return {k: (0, 0, []) for k in ORCHESTRATIONS}

    b_solved, b_points, b_stop = chain_from(features, 0, n)
    out['baseline'] = (b_solved, b_points,
                       [(b_stop, b_points)] if b_solved else [])

    angles = []
    for i in range(n - 1):
        pair = backend._estimate_pair(features[i], features[i + 1], 'x')
        angles.append(pair.estimate.median_triangulation_deg or 0.0
                      if pair.estimate.status == POSE_STATUS_SOLVED else -1.0)

    def greedy(covered, angles):
        """Take the highest-parallax uncovered pair, chain forward, repeat."""
        angles = list(angles)
        solved_total = points_total = 0
        comps = []
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
            # Never run past ground another component already holds.
            stop = min(stop, next((j for j in range(i + 1, n) if covered[j]), n))
            if stop - i < 2:
                angles[i] = -1.0
                continue
            solved, points, stop = chain_from(features, i, stop)
            if solved == 0:
                angles[i] = -1.0
                continue
            covered[i:stop] = True
            solved_total += solved
            points_total += points
            comps.append((stop - i, points))
        return solved_total, points_total, comps

    r_solved, r_points, r_comps = greedy(np.zeros(n, bool), angles)
    out['reseed'] = (r_solved, r_points, r_comps)

    # AUGMENT: keep the baseline chain exactly as it is, then fill in only
    # the keyframes it never reached. Strictly dominant by construction --
    # it cannot lose a component the baseline had, which `reseed` can and
    # does (largest component 89 -> 72 keyframes on one capture).
    covered = np.zeros(n, bool)
    a_solved, a_points, a_comps = 0, 0, []
    if b_solved:
        covered[0:b_stop] = True
        a_solved, a_points = b_solved, b_points
        a_comps.append((b_stop, b_points))
    g_solved, g_points, g_comps = greedy(covered, angles)
    out['augment'] = (a_solved + g_solved, a_points + g_points, a_comps + g_comps)
    return out


n_caps = int(sys.argv[1]) if len(sys.argv) > 1 else len(MOVING)
totals = {k: dict(poses=0, points=0, comps=[]) for k in ORCHESTRATIONS}
per_capture = []
t_front = t_solve = 0.0
for cap_id in MOVING[:n_caps]:
    t0 = time.perf_counter()
    segments = segment_keyframes(cap_id)
    t_front += time.perf_counter() - t0
    n_kf = sum(len(s) for s in segments)

    t0 = time.perf_counter()
    row = dict(cap=cap_id, segments=len(segments), keyframes=n_kf)
    agg = {k: dict(poses=0, points=0, comps=[]) for k in totals}
    for seg in segments:
        features = [detect_and_describe(g) for g in seg]
        res = solve_segment(features)
        for k, (p, pts, comps) in res.items():
            agg[k]['poses'] += p
            agg[k]['points'] += pts
            agg[k]['comps'].extend(comps)
    t_solve += time.perf_counter() - t0

    for k in totals:
        totals[k]['poses'] += agg[k]['poses']
        totals[k]['points'] += agg[k]['points']
        totals[k]['comps'].extend(agg[k]['comps'])
        row[f'{k}_poses'] = agg[k]['poses']
        row[f'{k}_points'] = agg[k]['points']
        row[f'{k}_largest_kf'] = max((c[0] for c in agg[k]['comps']), default=0)
    per_capture.append(row)
    print(f"  {cap_id[:12]}  segs {row['segments']:>3} kf {n_kf:>4} | "
          f"base {row['baseline_poses']:>4}p/{row['baseline_points']:>6}pt/"
          f"lc{row['baseline_largest_kf']:>3} | "
          f"reseed {row['reseed_poses']:>4}p/{row['reseed_points']:>6}pt/"
          f"lc{row['reseed_largest_kf']:>3} | "
          f"augment {row['augment_poses']:>4}p/{row['augment_points']:>6}pt/"
          f"lc{row['augment_largest_kf']:>3}", flush=True)

json.dump(dict(per_capture=per_capture,
               totals={k: dict(poses=v['poses'], points=v['points'], comps=v['comps'])
                       for k, v in totals.items()}),
          open(str(HERE / 'corpus_solve.json'), 'w'))

print()
print(f"{'orchestration':>14} {'solved poses':>13} {'points':>9} {'components':>11} "
      f"{'largest comp (kf)':>18} {'median comp':>12}")
for k in ORCHESTRATIONS:
    comps = totals[k]['comps']
    sizes = [c[0] for c in comps] or [0]
    print(f"{k:>14} {totals[k]['poses']:>13} {totals[k]['points']:>9} {len(comps):>11} "
          f"{max(sizes):>18} {np.median(sizes):>12.1f}")
print()
print(f"frontend replay {t_front:.1f} s   all solves {t_solve:.1f} s   "
      f"captures {n_caps}")
print(f"solvePnPRansac assertion failures caught: {len(PNP_CRASHES)}")
for c in PNP_CRASHES[:3]:
    print(f"  {c}")
