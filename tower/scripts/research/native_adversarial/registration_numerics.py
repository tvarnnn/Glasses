#!/usr/bin/env python
"""Adversarial numerics for the _residuals -> _residuals_packed change.

Three questions the shipped parity tests do not answer:

  1. What is the ACTUAL divergence between the two paths? The test asserts
     rtol=1e-9, which is ~7 orders looser than float64 needs. A loose
     tolerance cannot distinguish "bit-identical" from "quietly wrong at
     1e-10", so it pins nothing useful.
  2. Does the pack alias ANY of its four inputs? The shipped test checks
     object_points only.
  3. Can a last-bit difference flip `if probe_cost < cost` in _refine and
     therefore change the final Sim(3)? Answered by running the WHOLE
     refine both ways -- reference residual vs packed residual -- and
     comparing the converged parameters.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

TOWER = Path(__file__).resolve().parents[3]
for p in (str(TOWER), str(TOWER / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import world_registration as wreg  # noqa: E402

where = Path(wreg.__file__).resolve()
assert "Glasses-world-builder" in str(where), where
print(f"world_registration: {where}\n")

INTRINSICS = np.array([[500.0, 0.0, 320.0],
                       [0.0, 500.0, 240.0],
                       [0.0, 0.0, 1.0]])


def make_observations(rng, n_cam=5, n_pt=44):
    obs = []
    for _ in range(n_cam):
        points = np.column_stack([
            rng.uniform(-2, 2, n_pt), rng.uniform(-2, 2, n_pt),
            rng.uniform(1.5, 12.0, n_pt),
        ])
        rvec = rng.uniform(-0.5, 0.5, 3)
        rot, _ = cv2.Rodrigues(rvec)
        obs.append(wreg._Observation(
            frame=0,
            object_points=points,
            image_points=rng.uniform(0, 480, (n_pt, 2)),
            r_target=rot,
            t_target=rng.uniform(-1, 1, 3),
            r_pnp=rot,
            t_pnp=rng.uniform(-1, 1, 3),
        ))
    return obs


print("=" * 72)
print("1. TRUE divergence, reference vs packed (the test allows rtol=1e-9)")
print("=" * 72)
worst_rel = 0.0
worst_ulp = 0
bit_identical = 0
trials = 400
for t in range(trials):
    rng = np.random.default_rng(t)
    obs = make_observations(rng)
    params = np.concatenate([
        rng.uniform(-0.3, 0.3, 1), rng.uniform(-0.5, 0.5, 3),
        rng.uniform(-2, 2, 3)])
    a = wreg._residuals(params, obs, INTRINSICS)
    b = wreg._residuals_packed(params, wreg._pack(obs), INTRINSICS)
    if np.array_equal(a, b):
        bit_identical += 1
        continue
    denom = np.maximum(np.abs(a), 1e-300)
    worst_rel = max(worst_rel, float(np.max(np.abs(a - b) / denom)))
    ulp = np.abs(a.view(np.int64) - b.view(np.int64))
    worst_ulp = max(worst_ulp, int(ulp.max()))
print(f"  {trials} random working sets (5 cameras x 44 points)")
print(f"  bit-identical:        {bit_identical}/{trials}")
print(f"  max relative divergence: {worst_rel:.3e}")
print(f"  max ULP divergence:      {worst_ulp}")
print(f"  test tolerance is rtol=1e-9 -- looser than reality by "
      f"{1e-9 / max(worst_rel, 1e-300):.1e}x" if worst_rel else
      "  the two paths are BIT-IDENTICAL on every trial")

print()
print("=" * 72)
print("2. Does _pack alias ANY input? (shipped test checks object_points only)")
print("=" * 72)
rng = np.random.default_rng(0)
obs = make_observations(rng, n_cam=1, n_pt=3)
o = obs[0]
pack = wreg._pack(obs)
checks = [
    ("object_points", o.object_points, pack.object_points),
    ("image_points", o.image_points, pack.image_points),
    ("r_target", o.r_target, pack.r_target),
    ("t_target", o.t_target, pack.t_target),
]
for name, src, dst in checks:
    shares = np.shares_memory(src, dst)
    print(f"  {name:<14} shares_memory={shares}  "
          f"{'ALIASED -- BUG' if shares else 'copied, OK'}")
# and the multi-observation case
obs2 = make_observations(np.random.default_rng(1), n_cam=3, n_pt=4)
pack2 = wreg._pack(obs2)
any_alias = any(
    np.shares_memory(getattr(ob, f), getattr(pack2, f))
    for ob in obs2 for f in ("object_points", "image_points", "r_target", "t_target")
)
print(f"  3-observation pack aliases anything: {any_alias}")

print()
print("=" * 72)
print("3. Can a last-bit difference change the converged Sim(3)?")
print("=" * 72)
print("   Running the FULL refine both ways: the shipped _refine (packed)")
print("   against a byte-for-byte copy that uses the REFERENCE residual.")


def _huber_cost_reference(params, observations, intrinsics) -> float:
    norms = np.linalg.norm(
        wreg._residuals(params, observations, intrinsics), axis=1)
    H = wreg.HUBER_PX
    return float(np.mean(np.where(norms < H, norms ** 2,
                                  H * (2 * norms - H))))


def _refine_reference(params, observations, intrinsics, *, iterations=40,
                      fix_scale=False):
    """`_refine` with the loop residual -- i.e. the pre-change behaviour."""
    params = np.asarray(params, dtype=np.float64).copy()
    free = [i for i in range(7) if not (fix_scale and i == 0)]
    damping = 1e-3
    cost = _huber_cost_reference(params, observations, intrinsics)
    H = wreg.HUBER_PX
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
                break
            damping *= 10
        else:
            break
    return params, cost


identical = 0
worst_param = 0.0
worst_cost = 0.0
N = 60
for t in range(N):
    rng = np.random.default_rng(1000 + t)
    obs = make_observations(rng, n_cam=int(rng.integers(2, 7)),
                            n_pt=int(rng.integers(20, 80)))
    p0 = np.concatenate([rng.uniform(-0.2, 0.2, 1), rng.uniform(-0.3, 0.3, 3),
                         rng.uniform(-1, 1, 3)])
    pa, ca = wreg._refine(p0, obs, INTRINSICS)
    pb, cb = _refine_reference(p0, obs, INTRINSICS)
    if np.array_equal(pa, pb) and ca == cb:
        identical += 1
    else:
        worst_param = max(worst_param, float(np.max(np.abs(pa - pb))))
        worst_cost = max(worst_cost, abs(ca - cb))
print(f"  {N} full refines from random starts")
print(f"  converged BIT-IDENTICALLY: {identical}/{N}")
print(f"  max |param| divergence: {worst_param:.3e}")
print(f"  max |cost|  divergence: {worst_cost:.3e}")
