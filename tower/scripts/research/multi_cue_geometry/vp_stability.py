"""Two diagnostics that separate "the estimator is noisy" from "the cue is absent".

The rotation test showed the Manhattan triplet does not beat predicting no
rotation at all. That has two very different explanations and they demand
different responses, so they are separated here.

1. STATIC HOLD. On the corpus's nearly-motionless captures the camera moves
   ~0.1 px between frames. Whatever the triplet reports there is pure
   estimator jitter -- the true relative rotation is ~0. If jitter alone is
   several degrees the estimator is the problem. If jitter is small but the
   moving-capture error was large, the estimator is fine and the scene is
   not Manhattan.

2. VERTICAL ONLY. A room's vertical direction is the one indoor direction
   with genuinely many long parallel lines -- door frames, wall corners,
   furniture edges -- and it is the only one gravity keeps consistent
   across a whole building. It constrains 2 of 3 rotational degrees of
   freedom. A triplet can fail while the vertical still works, and the
   vertical is worth far more than a third of the triplet because it is
   what a horizontal-floor / vertical-wall prior rests on.

   The vertical is taken as the triplet axis closest to the camera's own
   +y once, then TRACKED by nearest-axis across frames, so a permutation
   flip in the triplet does not masquerade as a rotation.
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

# Median inter-frame displacement under 0.4 px -- the camera is on a table.
STATIC = ["9d51500898544f1495d8464e1afc6d6e", "6003eafcc4fb4641ba26a03bbc8123b3",
          "be4c8eadb9e24fd6bf49be6b73ac7cd7", "68a7c7ba6cb0443886137422ac7cf336",
          "341b0fdac88a4b6f9d6ff720d4341690", "4fea31e28a7942c8b1a2ed5704be4e66",
          "bed9624befa4436ea31f5322b31cc235", "97f3172678994668b5cabfe33468423a"]
MOVING = ["22e9d4289cb440fbb3f14e6da369a136", "b35d8ab85c364b9da44499d2a7f00638",
          "20ce3c2366ee4cdfb46cb8db09578058", "ab10cb203cf048e58cf2f79a120a54a4",
          "5387a76568e84e13936862f612f8bc81", "e1c52b9ff7f84dd5a54fee6150b7f854",
          "854e9688d2c54ae398eff4fb7c141522", "fe744b6827c44e3e8c3a309d665dbf80"]


def manhattan(gray, tol=3.0, iters=400):
    seg = detect_segments(gray)
    if len(seg) < 12:
        return None, None, None
    length = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1])
    normals = segment_normals(seg, K)
    mf = manhattan_frame(normals, length, tol_deg=tol, iters=iters,
                         rng=np.random.default_rng(0))
    if mf is None:
        return None, None, None
    R = refine_manhattan(normals, length, mf[0], tol_deg=tol)
    cos = np.abs(normals @ R.T)
    axis = np.argmin(cos, axis=1)
    owned = cos[np.arange(len(normals)), axis] < np.sin(np.radians(tol))
    per_axis = np.array([length[owned & (axis == a)].sum() for a in range(3)])
    return R, per_axis, float(length.sum())


def axis_angle_deg(u, v):
    """Angle between two undirected axes, in [0, 90]."""
    c = abs(float(np.dot(u, v)))
    return float(np.degrees(np.arccos(np.clip(c, 0.0, 1.0))))


def pick_vertical(R, per_axis):
    """The axis closest to camera +y, requiring it to actually be supported."""
    order = np.argsort(-np.abs(R[:, 1]))
    for a in order:
        if per_axis[a] > 150.0:
            return R[a], per_axis[a]
    return None, 0.0


def run(cap_ids, label, stride=1, n_pairs=120):
    tri_jitter, vert_jitter, vert_share, found = [], [], [], []
    for cap_id in cap_ids:
        cap = TOWER_ROOT / 'data/captures' / cap_id
        fr = [json.loads(x) for x in (cap / 'frames.jsonl').read_text().splitlines() if x.strip()]
        if len(fr) < stride + 2:
            continue
        take = np.linspace(0, len(fr) - stride - 1, min(n_pairs, len(fr) - stride)).astype(int)
        for i in take:
            a, b = fr[i], fr[i + stride]
            dt = b['received_at'] - a['received_at']
            if not (0.04 < dt < 0.2 * stride + 0.2):
                continue
            Ra, pa, ta = manhattan(decode_gray((cap / a['relpath']).read_bytes()))
            Rb, pb, tb = manhattan(decode_gray((cap / b['relpath']).read_bytes()))
            found.append(Ra is not None and Rb is not None)
            if Ra is None or Rb is None:
                continue
            # Triplet jitter: smallest axis-to-axis mismatch under the
            # nearest-axis assignment, which is the most generous reading.
            best = 0.0
            for row in range(3):
                best = max(best, min(axis_angle_deg(Ra[row], Rb[c]) for c in range(3)))
            tri_jitter.append(best)
            va, sa = pick_vertical(Ra, pa)
            vb, sb = pick_vertical(Rb, pb)
            if va is not None and vb is not None:
                vert_jitter.append(axis_angle_deg(va, vb))
                vert_share.append((sa / ta + sb / tb) / 2)
    def q(v, p):
        return float(np.percentile(v, p)) if len(v) else float('nan')
    print(f"{label} (stride {stride})")
    print(f"  pairs {len(found)}   Manhattan in both frames {100 * np.mean(found):.1f}%")
    print(f"  triplet worst-axis drift deg   median {q(tri_jitter, 50):6.2f}  p90 {q(tri_jitter, 90):6.2f}  n={len(tri_jitter)}")
    print(f"  VERTICAL axis drift deg        median {q(vert_jitter, 50):6.2f}  p90 {q(vert_jitter, 90):6.2f}  n={len(vert_jitter)}")
    print(f"  vertical support, share of line length: median {q(vert_share, 50):.3f}")
    print()
    return dict(label=label, stride=stride, tri=tri_jitter, vert=vert_jitter)


out = []
out.append(run(STATIC, "STATIC captures (camera on a table)", stride=1))
out.append(run(MOVING, "MOVING captures", stride=1))
out.append(run(MOVING, "MOVING captures", stride=12))
json.dump({r['label'] + str(r['stride']): {'tri': r['tri'], 'vert': r['vert']} for r in out},
          open(str(HERE / 'vp_stability.json'), 'w'))
