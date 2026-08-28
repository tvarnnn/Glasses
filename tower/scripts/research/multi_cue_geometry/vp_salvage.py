"""Can the vertical direction be made precise enough to be worth having?

The static-hold measurement put the estimator's own noise floor at 2.59 deg
median on a camera that was not moving, against a median true inter-frame
rotation of 1.22 deg. A cue noisier than the quantity it measures cannot
help, so the only question left is whether that floor can be lowered.

Two levers, both tested against the same static captures where the answer
is known to be "no rotation":

  LENGTH   Restrict to long segments only. A vanishing direction is fixed
           by where lines intersect, and a short segment's direction is
           dominated by endpoint quantisation. If the floor is endpoint
           noise, dropping short segments should lower it.

  TIME     Average the vertical over a window of frames. If the jitter is
           zero-mean and independent, N frames buy a sqrt(N) reduction and
           a 10-frame window would reach ~0.8 deg. If it is not independent
           -- if the estimator is locking onto different real structures in
           different frames -- averaging buys nothing, and that is the
           result that kills the cue rather than the estimator.

The window average is a proper axis mean (principal eigenvector of the
outer-product sum, sign-aligned), not a vector mean: axes have no sign and
averaging them naively cancels.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]

import numpy as np

sys.path.insert(0, str(TOWER_ROOT))
sys.path.insert(0, str(HERE))
from lines import (detect_segments, manhattan_frame, refine_manhattan,
                   segment_normals)
from tower.world_builder.frontend import decode_gray

INTR = json.loads(TOWER_ROOT / 'data/world_builder/intrinsics/360x640.json'.read_text())
K = np.array([[INTR['fx'], 0, INTR['cx']],
              [0, INTR['fy'], INTR['cy']],
              [0, 0, 1.0]])
STATIC = ["9d51500898544f1495d8464e1afc6d6e", "6003eafcc4fb4641ba26a03bbc8123b3",
          "be4c8eadb9e24fd6bf49be6b73ac7cd7", "68a7c7ba6cb0443886137422ac7cf336",
          "341b0fdac88a4b6f9d6ff720d4341690", "4fea31e28a7942c8b1a2ed5704be4e66",
          "bed9624befa4436ea31f5322b31cc235", "97f3172678994668b5cabfe33468423a"]


def vertical(gray, min_len, tol=3.0):
    seg = detect_segments(gray, min_length_px=min_len)
    if len(seg) < 12:
        return None, 0.0, len(seg)
    length = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1])
    normals = segment_normals(seg, K)
    mf = manhattan_frame(normals, length, tol_deg=tol, iters=400,
                         rng=np.random.default_rng(0))
    if mf is None:
        return None, 0.0, len(seg)
    R = refine_manhattan(normals, length, mf[0], tol_deg=tol)
    cos = np.abs(normals @ R.T)
    axis = np.argmin(cos, axis=1)
    owned = cos[np.arange(len(normals)), axis] < np.sin(np.radians(tol))
    per = np.array([length[owned & (axis == a)].sum() for a in range(3)])
    for a in np.argsort(-np.abs(R[:, 1])):
        if per[a] > 100.0:
            return R[a], float(per[a]), len(seg)
    return None, 0.0, len(seg)


def axis_angle(u, v):
    return float(np.degrees(np.arccos(np.clip(abs(float(u @ v)), 0.0, 1.0))))


def axis_mean(axes):
    A = np.stack(axes)
    M = A.T @ A
    _, vecs = np.linalg.eigh(M)
    return vecs[:, -1]


print("Static captures. True relative rotation is ~0, so every number is jitter.\n")
print(f"{'min line length':>16} {'frames':>7} {'yield':>7} {'per-frame drift deg':>21} {'10-frame window':>17}")
print(f"{'':>16} {'':>7} {'':>7} {'median':>10} {'p90':>10} {'median':>8} {'p90':>8}")
for min_len in (20.0, 40.0, 60.0, 90.0):
    per_frame, windowed, n_frames, n_have = [], [], 0, 0
    for cap_id in STATIC:
        cap = TOWER_ROOT / 'data/captures' / cap_id
        fr = [json.loads(x) for x in (cap / 'frames.jsonl').read_text().splitlines() if x.strip()]
        take = np.linspace(0, len(fr) - 1, min(90, len(fr))).astype(int)
        axes = []
        for i in take:
            v, _, _ = vertical(decode_gray((cap / fr[i]['relpath']).read_bytes()), min_len)
            n_frames += 1
            axes.append(v)
            if v is not None:
                n_have += 1
        for j in range(1, len(axes)):
            if axes[j] is not None and axes[j - 1] is not None:
                per_frame.append(axis_angle(axes[j], axes[j - 1]))
        # Windowed: compare each 10-frame axis mean to the next window's.
        good = [a for a in axes if a is not None]
        for j in range(0, len(good) - 20, 10):
            w1 = axis_mean([g * np.sign(g @ good[j] + 1e-12) for g in good[j:j + 10]])
            w2 = axis_mean([g * np.sign(g @ good[j] + 1e-12) for g in good[j + 10:j + 20]])
            windowed.append(axis_angle(w1, w2))
    q = lambda v, p: float(np.percentile(v, p)) if len(v) else float('nan')
    print(f"{min_len:>16.0f} {n_frames:>7} {100 * n_have / max(n_frames, 1):>6.1f}% "
          f"{q(per_frame, 50):>10.2f} {q(per_frame, 90):>10.2f} "
          f"{q(windowed, 50):>8.2f} {q(windowed, 90):>8.2f}")
