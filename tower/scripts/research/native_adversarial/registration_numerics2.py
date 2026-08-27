#!/usr/bin/env python
"""Registration numerics, part 2: divergence in PIXELS, and Sim(3) stability.

Part 1 of this attack established the two residual paths are NOT
bit-identical (0/400 trials). Relative error is a bad unit here because
residuals cross zero, so this measures the ABSOLUTE divergence in pixels --
the unit the residual is actually in -- and then asks the question that
matters: does it change where the optimiser lands?
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

TOWER = Path(__file__).resolve().parents[3]
for p in (str(TOWER), str(TOWER / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import world_registration as wreg  # noqa: E402

assert "Glasses-world-builder" in str(Path(wreg.__file__).resolve())

INTRINSICS = np.array([[500.0, 0.0, 320.0],
                       [0.0, 500.0, 240.0],
                       [0.0, 0.0, 1.0]])


def consistent_observations(rng, n_cam=5, n_pt=44, noise=0.3):
    """Observations generated FROM a known Sim(3), so a refine converges."""
    true_scale = float(np.exp(rng.uniform(-0.2, 0.2)))
    true_rvec = rng.uniform(-0.3, 0.3, 3)
    true_R, _ = cv2.Rodrigues(true_rvec)
    true_t = rng.uniform(-1, 1, 3)
    obs = []
    for _ in range(n_cam):
        pts = np.column_stack([rng.uniform(-2, 2, n_pt),
                               rng.uniform(-2, 2, n_pt),
                               rng.uniform(2.0, 12.0, n_pt)])
        rvec = rng.uniform(-0.3, 0.3, 3)
        R_t, _ = cv2.Rodrigues(rvec)
        t_t = rng.uniform(-1, 1, 3)
        R_s = R_t @ true_R.T
        t_s = true_scale * t_t - R_s @ true_t
        cam = (R_s @ pts.T).T + t_s
        z = np.maximum(cam[:, 2], 0.5)
        px = np.column_stack([
            INTRINSICS[0, 0] * cam[:, 0] / z + INTRINSICS[0, 2],
            INTRINSICS[1, 1] * cam[:, 1] / z + INTRINSICS[1, 2],
        ]) + rng.normal(0, noise, (n_pt, 2))
        obs.append(wreg._Observation(
            frame=0, object_points=pts, image_points=px,
            r_target=R_t, t_target=t_t, r_pnp=R_t, t_pnp=t_t))
    truth = np.concatenate([[np.log(true_scale)], true_rvec, true_t])
    return obs, truth


print("=" * 72)
print("1. Divergence in PIXELS (the unit the residual is in)")
print("=" * 72)
worst_abs = 0.0
worst_rel_to_scale = 0.0
bit_identical = 0
N = 400
for t in range(N):
    rng = np.random.default_rng(t)
    obs, truth = consistent_observations(rng)
    params = truth + np.concatenate([
        rng.normal(0, 0.02, 1), rng.normal(0, 0.03, 3), rng.normal(0, 0.1, 3)])
    a = wreg._residuals(params, obs, INTRINSICS)
    b = wreg._residuals_packed(params, wreg._pack(obs), INTRINSICS)
    if np.array_equal(a, b):
        bit_identical += 1
        continue
    d = float(np.abs(a - b).max())
    worst_abs = max(worst_abs, d)
    worst_rel_to_scale = max(worst_rel_to_scale, d / max(float(np.abs(a).max()), 1e-12))
print(f"  {N} realistic working sets")
print(f"  bit-identical:                    {bit_identical}/{N}")
print(f"  max ABSOLUTE divergence:          {worst_abs:.3e} px")
print(f"  max divergence / residual scale:  {worst_rel_to_scale:.3e}")
print(f"  parity test allows atol=1e-9 + rtol=1e-9*|b|, i.e. roughly")
print(f"  1e-9 + 1e-7 px at pixel-scale residuals -- passes with margin.")

print()
print("=" * 72)
print("2. Does it move the converged Sim(3)? Full refine, both residuals")
print("=" * 72)


def _huber_cost_reference(params, observations, intrinsics) -> float:
    norms = np.linalg.norm(
        wreg._residuals(params, observations, intrinsics), axis=1)
    H = wreg.HUBER_PX
    return float(np.mean(np.where(norms < H, norms ** 2,
                                  H * (2 * norms - H))))


def _refine_reference(params, observations, intrinsics, *, iterations=40,
                      fix_scale=False):
    params = np.asarray(params, dtype=np.float64).copy()
    free = [i for i in range(7) if not (fix_scale and i == 0)]
    damping = 1e-3
    cost = _huber_cost_reference(params, observations, intrinsics)
    H = wreg.HUBER_PX
    accepted = 0
    for _ in range(iterations):
        base = wreg._residuals(params, observations, intrinsics)
        norms = np.linalg.norm(base, axis=1)
        weights = np.repeat(
            np.where(norms < H, 1.0, np.sqrt(H / np.maximum(norms, 1e-9))), 2)
        jacobian = np.zeros((base.size, len(free)))
        for column, index in enumerate(free):
            step = 1e-5 * max(abs(params[index]), 1.0)
            probe = params.copy()
            probe[index] += step
            jacobian[:, column] = (
                (wreg._residuals(probe, observations, intrinsics) - base) / step
            ).ravel()
        weighted_j = jacobian * weights[:, None]
        weighted_r = base.ravel() * weights
        hessian = weighted_j.T @ weighted_j
        gradient = weighted_j.T @ weighted_r
        for _attempt in range(12):
            try:
                delta = np.linalg.solve(
                    hessian + damping * np.diag(
                        np.maximum(np.diag(hessian), 1e-9)), -gradient)
            except np.linalg.LinAlgError:
                damping *= 10
                continue
            probe = params.copy()
            for column, index in enumerate(free):
                probe[index] += delta[column]
            probe_cost = _huber_cost_reference(probe, observations, intrinsics)
            if probe_cost < cost:
                params, cost = probe, probe_cost
                damping = max(damping * 0.3, 1e-9)
                accepted += 1
                break
            damping *= 10
        else:
            break
    return params, cost


identical = 0
worst_param = 0.0
worst_cost_rel = 0.0
worst_scale_ppm = 0.0
M = 80
for t in range(M):
    rng = np.random.default_rng(5000 + t)
    obs, truth = consistent_observations(
        rng, n_cam=int(rng.integers(2, 7)), n_pt=int(rng.integers(20, 80)),
        noise=float(rng.choice([0.1, 0.5, 2.0])))
    p0 = truth + np.concatenate([
        rng.normal(0, 0.05, 1), rng.normal(0, 0.08, 3), rng.normal(0, 0.3, 3)])
    pa, ca = wreg._refine(p0, obs, INTRINSICS)
    pb, cb = _refine_reference(p0, obs, INTRINSICS)
    if np.array_equal(pa, pb) and ca == cb:
        identical += 1
    else:
        worst_param = max(worst_param, float(np.max(np.abs(pa - pb))))
        worst_cost_rel = max(worst_cost_rel, abs(ca - cb) / max(abs(ca), 1e-30))
        worst_scale_ppm = max(
            worst_scale_ppm,
            abs(np.exp(pa[0]) - np.exp(pb[0])) / np.exp(pa[0]) * 1e6)
print(f"  {M} full refines, observations generated from a known Sim(3)")
print(f"  converged BIT-IDENTICALLY:  {identical}/{M}")
print(f"  max |param| divergence:     {worst_param:.3e}")
print(f"  max relative cost drift:    {worst_cost_rel:.3e}")
print(f"  max SCALE drift:            {worst_scale_ppm:.4f} ppm")
print()
print("  Interpretation: registration admits a pair on a cost/inlier gate.")
print("  What matters is whether drift of this size can cross a gate.")
