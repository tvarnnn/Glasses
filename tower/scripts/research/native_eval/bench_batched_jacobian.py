"""Two follow-ups to bench_residuals.py.

1. numba JIT warm-up cost (the tax a numba dependency charges once).
2. A PURE-NUMPY algorithmic win that needs no new dependency at all:
   `_refine` evaluates `_residuals` 8 times per iteration (1 base + 7
   numerical-Jacobian probes) with the SAME observations and 8 nearby
   parameter vectors. Those 8 evaluations can be one batched call, which
   amortises the fixed per-call pose/dispatch overhead 8 ways.

Run:
  PYTHONPATH=".;<scratch>" <venv-python> scripts/research/native_eval/bench_batched_jacobian.py
"""

from __future__ import annotations

import math
import time

import cv2
import numpy as np

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_residuals import (  # noqa: E402
    INTRINSICS,
    Pack,
    make_observations,
    residuals_control,
    residuals_flat_gather,
    NUMBA_OK,
)


def batched_pose(pack: Pack, params_batch: np.ndarray):
    """(B,7) params -> (B,C,3,3) rotations and (B,C,3) translations."""
    b = params_batch.shape[0]
    scale = np.exp(params_batch[:, 0])                       # (B,)
    rots = np.empty((b, 3, 3))
    for i in range(b):
        rots[i], _ = cv2.Rodrigues(params_batch[i, 1:4])
    translation = params_batch[:, 4:7]                       # (B,3)
    # r_source[b,c] = r_target[c] @ rots[b].T
    r_source = np.einsum("cik,bjk->bcij", pack.r_target, rots)
    t_source = (
        scale[:, None, None] * pack.t_target[None]
        - np.einsum("bcij,bj->bci", r_source, translation)
    )
    return r_source, t_source


def residuals_batched(params_batch: np.ndarray, pack: Pack) -> np.ndarray:
    """(B,7) params -> (B,N,2) residuals, in one shot."""
    r_source, t_source = batched_pose(pack, params_batch)
    rs = r_source[:, pack.cam_idx]                           # (B,N,3,3)
    camera = np.einsum("bnij,nj->bni", rs, pack.obj) + t_source[:, pack.cam_idx]
    depth = camera[:, :, 2]
    behind = depth <= 1e-6
    safe = np.where(behind, 1e-6, depth)
    residual = camera[:, :, :2] * pack.f / safe[:, :, None] + pack.c - pack.img
    residual[behind] = 1e4
    return residual


def bench(fn, inner=20, rep=30):
    best = float("inf")
    for _ in range(rep):
        t0 = time.perf_counter()
        for _ in range(inner):
            fn()
        best = min(best, (time.perf_counter() - t0) / inner)
    return best


def main():
    cameras, points = 5, 220
    observations = make_observations(cameras, points)
    pack = Pack(observations, INTRINSICS)
    rng = np.random.default_rng(3)
    params = np.concatenate(
        [[math.log(1.03)], rng.normal(scale=0.05, size=3), rng.normal(scale=0.1, size=3)]
    )

    # The exact batch _refine builds: base + 7 finite-difference probes.
    batch = np.tile(params, (8, 1))
    for column in range(7):
        step = 1e-5 * max(abs(params[column]), 1.0)
        batch[column + 1, column] += step

    got = residuals_batched(batch, pack)
    ref = np.stack([residuals_control(batch[i], observations, INTRINSICS) for i in range(8)])
    print("batched matches control exactly:", np.allclose(got, ref, rtol=0, atol=1e-9))

    for _ in range(5):
        residuals_batched(batch, pack)

    t_control_8 = bench(lambda: [residuals_control(batch[i], observations, INTRINSICS) for i in range(8)])
    t_flat_8 = bench(lambda: [residuals_flat_gather(batch[i], pack) for i in range(8)])
    t_batched = bench(lambda: residuals_batched(batch, pack))

    print(f"\n=== one Gauss-Newton Jacobian block: 8 evaluations, {cameras} cam / {points} pts ===")
    print(f"{'strategy':<42} {'us/block':>10} {'us/eval':>9} {'speedup':>8}")
    for name, t in (
        ("(a) control x8 (shipped)", t_control_8),
        ("(b1) flat gather x8", t_flat_8),
        ("(f) ONE batched (B=8) numpy call", t_batched),
    ):
        print(f"{name:<42} {t*1e6:10.2f} {t/8*1e6:9.2f} {t_control_8/t:8.2f}x")

    if NUMBA_OK:
        from bench_residuals import residuals_numba, residuals_c_proxy
        for _ in range(5):
            residuals_numba(params, pack)
            residuals_c_proxy(params, pack)
        t_nb_8 = bench(lambda: [residuals_numba(batch[i], pack) for i in range(8)])
        t_c_8 = bench(lambda: [residuals_c_proxy(batch[i], pack) for i in range(8)])
        print(f"{'(d) numba x8':<42} {t_nb_8*1e6:10.2f} {t_nb_8/8*1e6:9.2f} {t_control_8/t_nb_8:8.2f}x")
        print(f"{'(e) C-proxy x8':<42} {t_c_8*1e6:10.2f} {t_c_8/8*1e6:9.2f} {t_control_8/t_c_8:8.2f}x")

        frac = (t_control_8 - t_batched) / (t_control_8 - t_c_8)
        frac_nb = (t_control_8 - t_nb_8) / (t_control_8 - t_c_8)
        print(f"\nfraction of the C-achievable SAVING captured by pure numpy (f): {frac*100:.1f}%")
        print(f"fraction of the C-achievable SAVING captured by numba (d):      {frac_nb*100:.1f}%")


def warmup():
    """Cost of numba's JIT the first time the process touches it."""
    if not NUMBA_OK:
        print("numba not available; warm-up not measured")
        return
    t0 = time.perf_counter()
    import numba  # noqa: F401
    t_import = time.perf_counter() - t0

    observations = make_observations(5, 220)
    pack = Pack(observations, INTRINSICS)
    params = np.array([0.03, 0.01, 0.02, 0.03, 0.1, 0.05, 0.02])
    from bench_residuals import residuals_numba
    t0 = time.perf_counter()
    residuals_numba(params, pack)
    t_first = time.perf_counter() - t0
    t0 = time.perf_counter()
    residuals_numba(params, pack)
    t_second = time.perf_counter() - t0
    print(f"\nnumba import (already loaded by module): {t_import*1e3:8.2f} ms")
    print(f"numba FIRST call (JIT compile):          {t_first*1e3:8.2f} ms")
    print(f"numba second call:                       {t_second*1e6:8.2f} us")


if __name__ == "__main__":
    warmup()
    main()
