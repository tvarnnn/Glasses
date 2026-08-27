"""Is DPVO's trajectory determined by our footage, or by its random patches?

We have no ground truth, so we cannot ask "is this trajectory right". We can
ask something almost as useful, and it is the same question the cross-segment
lane answered with reciprocity rather than reprojection error:

    DPVO selects its patches at RANDOM (`CENTROID_SEL_STRAT: 'RANDOM'`, an
    unseeded `torch.randint` in `Patchifier.forward`). Run it twice on the
    SAME frames with the SAME weights and the SAME calibration. If the
    footage determines the trajectory, the two runs agree. If they disagree,
    the trajectory is a property of the random draw, not of the scene.

Monocular trajectories are only defined up to a similarity, so runs are
compared after an exact Umeyama Sim(3) alignment of the camera centres. The
error is reported as a FRACTION of the trajectory's own extent, which is the
only scale-free way to say it.

Usage: dpvo_reproducibility.py a.poses.npy b.poses.npy [c.poses.npy ...]
"""

from __future__ import annotations

import itertools
import sys

import numpy as np


def umeyama_sim3(src: np.ndarray, dst: np.ndarray):
    """Least-squares similarity taking src onto dst. Returns (s, R, t)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    cov = xd.T @ xs / len(src)
    u, d, vt = np.linalg.svd(cov)
    s_mat = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        s_mat[2, 2] = -1
    R = u @ s_mat @ vt
    var_s = (xs ** 2).sum() / len(src)
    scale = float(np.trace(np.diag(d) @ s_mat) / var_s) if var_s > 0 else 1.0
    t = mu_d - scale * R @ mu_s
    return scale, R, t


def main():
    paths = sys.argv[1:]
    if len(paths) < 2:
        raise SystemExit(__doc__)
    runs = []
    for p in paths:
        arr = np.load(p)
        runs.append((p, np.asarray(arr)[:, :3].astype(np.float64)))
        print(f"{p}: {arr.shape[0]} poses")

    n = min(len(x) for _, x in runs)
    print(f"comparing first {n} poses of each run\n")

    for (pa, a), (pb, b) in itertools.combinations(runs, 2):
        a, b = a[:n], b[:n]
        s, R, t = umeyama_sim3(a, b)
        a_al = (s * (R @ a.T).T) + t
        err = np.linalg.norm(a_al - b, axis=1)
        extent = float(np.linalg.norm(b.max(0) - b.min(0)))
        path_b = float(np.linalg.norm(np.diff(b, axis=0), axis=1).sum())
        print(f"{pa.split('/')[-1]}  vs  {pb.split('/')[-1]}")
        print(f"  Sim(3) scale between the two runs : {s:.4f}")
        print(f"  aligned position RMS              : {np.sqrt((err ** 2).mean()):.5f}")
        print(f"  aligned position median / p95     : {np.median(err):.5f} / "
              f"{np.percentile(err, 95):.5f}")
        print(f"  run B bbox extent                 : {extent:.5f}")
        print(f"  run B path length                 : {path_b:.5f}")
        print(f"  >>> RMS as % of extent            : "
              f"{100 * np.sqrt((err ** 2).mean()) / extent:.1f}%")
        print(f"  >>> RMS as % of path length       : "
              f"{100 * np.sqrt((err ** 2).mean()) / path_b:.1f}%")
        print()


if __name__ == "__main__":
    main()
