#!/usr/bin/env python
"""Is `_residuals` slow because it is PYTHON, or because it is WORK?

`_residuals` is the one measured Python hotspot in the whole system:
38.8% of registration tottime, 38,483 calls, mean 4.5 cameras and ~198
points per call. That is a Python `for` loop over cameras doing small
numpy operations on ~(198, 3) arrays -- the shape where per-call numpy
dispatch overhead is comparable to the arithmetic.

This distinguishes two explanations that lead to opposite decisions:

  (a) The arithmetic itself is the cost. Then it is FLOP-bound, numpy is
      already running it in C, and a native port buys little.
  (b) The PYTHON loop and the per-camera numpy dispatch are the cost.
      Then it is overhead-bound -- and the fix is to stack the cameras
      into one array and do the whole thing in a handful of numpy calls,
      which is a PYTHON change, not a native one.

So: real observations are captured off a real registration, the shipped
loop is timed, and a stacked equivalent is timed against it with the
outputs asserted equal. Whatever the ratio is, it is the answer.

Nothing under `tower/` or `scripts/world_registration.py` is modified;
the stacked version lives here as a measurement, not as a patch.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from scripts import world_registration as wr  # noqa: E402
from tower.artifact_paths import artifact_root_arg  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402


def residuals_stacked(params, packed, intrinsics):
    """`_residuals` with the camera loop hoisted into one array op.

    `packed` is what `pack()` below builds ONCE per observation set:
    every camera's object/image points concatenated, plus a per-row
    index into per-camera rotation and translation stacks. Identical
    arithmetic, identical saturation rule, no Python loop.
    """
    scale = math.exp(params[0])
    rotation, _ = cv2.Rodrigues(params[1:4])
    translation = params[4:7]
    fx, fy = intrinsics[0, 0], intrinsics[1, 1]
    cx, cy = intrinsics[0, 2], intrinsics[1, 2]

    r_target, t_target, object_points, image_points, row_of = packed
    # (C, 3, 3) @ (3, 3) -> (C, 3, 3); one matmul for every camera.
    r_source = r_target @ rotation.T
    t_source = scale * t_target - np.einsum("cij,j->ci", r_source, translation)
    # (N, 3) rotated by its own camera's R, gathered per row.
    camera = (
        np.einsum("nij,nj->ni", r_source[row_of], object_points) + t_source[row_of]
    )
    depth = camera[:, 2]
    behind = depth <= 1e-6
    safe = np.where(behind, 1e-6, depth)
    residual = np.empty((len(camera), 2))
    residual[:, 0] = fx * camera[:, 0] / safe + cx - image_points[:, 0]
    residual[:, 1] = fy * camera[:, 1] / safe + cy - image_points[:, 1]
    residual[behind] = 1e4
    return residual


def pack(observations):
    r_target = np.stack([o.r_target for o in observations])
    t_target = np.stack([np.asarray(o.t_target).reshape(3) for o in observations])
    object_points = np.concatenate([o.object_points for o in observations])
    image_points = np.concatenate([o.image_points for o in observations])
    row_of = np.concatenate(
        [np.full(len(o.object_points), i) for i, o in enumerate(observations)]
    )
    return r_target, t_target, object_points, image_points, row_of


def capture_observations(root: Path, world_id: str, session_id: str, want: int):
    """Run a real registration, keeping the observation sets it builds."""
    captured = []
    original = wr._pnp_observations

    def spy(*args, **kwargs):
        result = original(*args, **kwargs)
        if result and len(captured) < want:
            captured.append(result)
        return result

    wr._pnp_observations = spy
    try:
        wr.register(WorldStore(root), world_id, session_id)
    finally:
        wr._pnp_observations = original
    return captured


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=artifact_root_arg)
    ap.add_argument("--world", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--sets", type=int, default=25)
    ap.add_argument("--reps", type=int, default=400)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    observation_sets = capture_observations(
        args.root, args.world, args.session, args.sets
    )
    if not observation_sets:
        raise SystemExit("registration produced no PnP observation sets")

    store = WorldStore(args.root)
    session = store.read_session(args.world, args.session)
    intrinsics = session.intrinsics.camera_matrix()

    params = np.array([0.0, 0.01, 0.02, -0.01, 0.1, -0.2, 0.3])

    rows = []
    for observations in observation_sets:
        packed = pack(observations)
        # Equivalence FIRST: a faster function that computes something
        # else is not a measurement, it is a bug.
        a = wr._residuals(params, observations, intrinsics)
        b = residuals_stacked(params, packed, intrinsics)
        if a.shape != b.shape or not np.allclose(a, b, rtol=1e-9, atol=1e-9):
            raise SystemExit(
                f"stacked version DISAGREES (max abs diff "
                f"{np.abs(a - b).max() if a.shape == b.shape else 'shape'}); "
                "the comparison below would be meaningless"
            )

        t0 = time.perf_counter()
        for _ in range(args.reps):
            wr._residuals(params, observations, intrinsics)
        loop_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        for _ in range(args.reps):
            residuals_stacked(params, packed, intrinsics)
        stacked_s = time.perf_counter() - t0

        rows.append(
            {
                "cameras": len(observations),
                "points": int(sum(len(o.object_points) for o in observations)),
                "loop_us": round(loop_s / args.reps * 1e6, 3),
                "stacked_us": round(stacked_s / args.reps * 1e6, 3),
                "speedup": round(loop_s / stacked_s, 3),
            }
        )

    print(f"world {args.world[:8]} session {args.session[:8]}")
    print(f"observation sets captured: {len(rows)}  reps each: {args.reps}")
    print(f"{'cams':>5} {'points':>7} {'loop us':>10} {'stacked us':>11} {'x':>7}")
    for r in rows:
        print(
            f"{r['cameras']:>5} {r['points']:>7} {r['loop_us']:>10.2f} "
            f"{r['stacked_us']:>11.2f} {r['speedup']:>7.2f}"
        )
    total_loop = sum(r["loop_us"] for r in rows)
    total_stacked = sum(r["stacked_us"] for r in rows)
    print(
        f"\nTOTALS over {len(rows)} sets: loop={total_loop:.1f}us "
        f"stacked={total_stacked:.1f}us  overall={total_loop/total_stacked:.2f}x"
    )
    print(
        f"mean cameras={sum(r['cameras'] for r in rows)/len(rows):.2f} "
        f"mean points={sum(r['points'] for r in rows)/len(rows):.1f}"
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
