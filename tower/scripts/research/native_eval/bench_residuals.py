"""Benchmark non-C++ alternatives for the `_residuals` hotspot.

Measured baseline (not re-derived here, quoted from the profiling lane):
`_residuals` in scripts/world_registration.py:543 is 2.487 s tottime,
38.8% of a 6.4 s registration run, over 38,483 calls, mean 4.5 cameras
and 197.6 points per call -> 7.6M point-residuals at 327 ns each.

This harness reproduces that SHAPE synthetically and races:

  (a) control    - byte-for-byte the shipped loop
  (b1) flat_gather  - pack once, gather (C,3,3)->(N,3,3), einsum
  (b2) flat_allcam  - pack once, rotate by every camera, take the right row
  (b3) flat_blocks  - pack once, per-camera slice into one preallocated out
  (c) prealloc   - shipped loop with output buffers reused across calls
  (d) numba      - @njit over the flat pack (skipped if numba absent)
  (e) c_estimate - equivalent scalar loop, njit'd, as a proxy for a
                   hand-written C extension inner loop

Every variant is checked against the control for exact/allclose equality
before it is allowed to post a time.

Run:
  cd C:\\Users\\tvllo\\Projects\\Glasses-world-builder\\tower
  PYTHONPATH=. C:\\Users\\tvllo\\Projects\\Glasses\\tower\\.venv\\Scripts\\python.exe \\
      scripts/research/native_eval/bench_residuals.py
"""

from __future__ import annotations

import math
import statistics
import sys
import time
from dataclasses import dataclass

import cv2
import numpy as np

# ---------------------------------------------------------------- fixtures

HUBER_PX = 4.0
INTRINSICS = np.array(
    [[520.0, 0.0, 320.0], [0.0, 520.0, 240.0], [0.0, 0.0, 1.0]],
    dtype=np.float64,
)


@dataclass
class _Observation:
    """Mirror of scripts/world_registration.py:_Observation (fields used here)."""

    frame: int
    object_points: np.ndarray
    image_points: np.ndarray
    r_target: np.ndarray
    t_target: np.ndarray


def _rand_rotation(rng) -> np.ndarray:
    axis = rng.normal(size=3)
    axis /= np.linalg.norm(axis)
    angle = rng.uniform(0.05, 0.6)
    rot, _ = cv2.Rodrigues((axis * angle).reshape(3, 1))
    return np.asarray(rot, dtype=np.float64)


def make_observations(cameras: int, points_total: int, seed: int = 7) -> list:
    """Synthetic observations matching the MEASURED shape.

    Geometry is built so the residuals are small and `behind` is rare,
    which is the regime the real optimiser spends its iterations in.
    """
    rng = np.random.default_rng(seed)
    fx, fy = INTRINSICS[0, 0], INTRINSICS[1, 1]
    cx, cy = INTRINSICS[0, 2], INTRINSICS[1, 2]

    per = [points_total // cameras] * cameras
    for i in range(points_total - sum(per)):
        per[i] += 1

    observations = []
    for c in range(cameras):
        n = per[c]
        # Points a few metres out in front, the indoor-walk regime.
        obj = np.column_stack(
            [
                rng.uniform(-1.5, 1.5, n),
                rng.uniform(-1.0, 1.0, n),
                rng.uniform(1.5, 6.0, n),
            ]
        ).astype(np.float64)
        r_target = _rand_rotation(rng)
        t_target = rng.uniform(-0.5, 0.5, 3).astype(np.float64)
        cam = (r_target @ obj.T).T + t_target
        depth = cam[:, 2]
        img = np.column_stack(
            [fx * cam[:, 0] / depth + cx, fy * cam[:, 1] / depth + cy]
        )
        img += rng.normal(scale=0.7, size=img.shape)  # a plausible reprojection error
        observations.append(
            _Observation(
                frame=c,
                object_points=obj,
                image_points=np.ascontiguousarray(img),
                r_target=r_target,
                t_target=t_target,
            )
        )
    return observations


# ------------------------------------------------------- (a) the control

def residuals_control(params: np.ndarray, observations: list, intrinsics) -> np.ndarray:
    """Byte-for-byte the shipped implementation (world_registration.py:543)."""
    scale = math.exp(params[0])
    rotation, _ = cv2.Rodrigues(params[1:4])
    translation = params[4:7]
    fx, fy = intrinsics[0, 0], intrinsics[1, 1]
    cx, cy = intrinsics[0, 2], intrinsics[1, 2]

    out = []
    for observation in observations:
        r_source = observation.r_target @ rotation.T
        t_source = scale * observation.t_target - r_source @ translation
        camera = (r_source @ observation.object_points.T).T + t_source
        depth = camera[:, 2]
        residual = np.empty((len(camera), 2))
        behind = depth <= 1e-6
        safe = np.where(behind, 1e-6, depth)
        residual[:, 0] = fx * camera[:, 0] / safe + cx - observation.image_points[:, 0]
        residual[:, 1] = fy * camera[:, 1] / safe + cy - observation.image_points[:, 1]
        residual[behind] = 1e4
        out.append(residual)
    return np.concatenate(out) if out else np.zeros((0, 2))


# -------------------------------------------------------------- the pack

class Pack:
    """Everything constant across the 38k calls, stacked once."""

    def __init__(self, observations: list, intrinsics):
        self.n_cameras = len(observations)
        self.obj = np.ascontiguousarray(
            np.concatenate([o.object_points for o in observations]), dtype=np.float64
        )
        self.img = np.ascontiguousarray(
            np.concatenate([o.image_points for o in observations]), dtype=np.float64
        )
        self.r_target = np.ascontiguousarray(
            np.stack([o.r_target for o in observations]), dtype=np.float64
        )
        self.t_target = np.ascontiguousarray(
            np.stack([o.t_target for o in observations]), dtype=np.float64
        )
        counts = [len(o.object_points) for o in observations]
        self.counts = np.asarray(counts, dtype=np.int64)
        self.cam_idx = np.repeat(np.arange(self.n_cameras), self.counts)
        bounds = np.concatenate([[0], np.cumsum(self.counts)])
        self.slices = [
            (int(bounds[i]), int(bounds[i + 1])) for i in range(self.n_cameras)
        ]
        self.n_points = int(bounds[-1])
        self.fx = float(intrinsics[0, 0])
        self.fy = float(intrinsics[1, 1])
        self.cx = float(intrinsics[0, 2])
        self.cy = float(intrinsics[1, 2])
        self.f = np.array([self.fx, self.fy], dtype=np.float64)
        self.c = np.array([self.cx, self.cy], dtype=np.float64)
        # reusable scratch
        self.out = np.empty((self.n_points, 2), dtype=np.float64)
        self.camera = np.empty((self.n_points, 3), dtype=np.float64)
        self.r_source = np.empty((self.n_cameras, 3, 3), dtype=np.float64)
        self.t_source = np.empty((self.n_cameras, 3), dtype=np.float64)


def _pose(pack: Pack, params: np.ndarray):
    scale = math.exp(params[0])
    rotation, _ = cv2.Rodrigues(params[1:4])
    translation = params[4:7]
    r_source = pack.r_target @ rotation.T          # (C,3,3)
    t_source = scale * pack.t_target - r_source @ translation   # (C,3)
    return r_source, t_source


# ------------------------------------------------ (b1) gather + einsum

def residuals_flat_gather(params, pack: Pack, _intrinsics=None) -> np.ndarray:
    r_source, t_source = _pose(pack, params)
    rs = r_source[pack.cam_idx]                     # (N,3,3)
    camera = np.einsum("nij,nj->ni", rs, pack.obj) + t_source[pack.cam_idx]
    depth = camera[:, 2]
    behind = depth <= 1e-6
    safe = np.where(behind, 1e-6, depth)
    residual = camera[:, :2] * pack.f / safe[:, None] + pack.c - pack.img
    residual[behind] = 1e4
    return residual


# ----------------------------------- (b2) rotate by every camera, then take

def residuals_flat_allcam(params, pack: Pack, _intrinsics=None) -> np.ndarray:
    r_source, t_source = _pose(pack, params)
    # (C,N,3): one BLAS gemm per camera, no (N,3,3) gather.
    allcam = pack.obj @ r_source.transpose(0, 2, 1) + t_source[:, None, :]
    camera = allcam[pack.cam_idx, np.arange(pack.n_points)]
    depth = camera[:, 2]
    behind = depth <= 1e-6
    safe = np.where(behind, 1e-6, depth)
    residual = camera[:, :2] * pack.f / safe[:, None] + pack.c - pack.img
    residual[behind] = 1e4
    return residual


# ------------- (b3) per-camera contiguous slices into one preallocated out

def residuals_flat_blocks(params, pack: Pack, _intrinsics=None) -> np.ndarray:
    r_source, t_source = _pose(pack, params)
    camera = pack.camera
    obj = pack.obj
    for i, (lo, hi) in enumerate(pack.slices):
        np.matmul(obj[lo:hi], r_source[i].T, out=camera[lo:hi])
        camera[lo:hi] += t_source[i]
    depth = camera[:, 2]
    behind = depth <= 1e-6
    safe = np.where(behind, 1e-6, depth)
    out = pack.out
    np.multiply(camera[:, :2], pack.f, out=out)
    np.divide(out, safe[:, None], out=out)
    np.add(out, pack.c, out=out)
    np.subtract(out, pack.img, out=out)
    out[behind] = 1e4
    return out


# --------------------------- (c) shipped loop with reused output buffers

class PreallocState:
    def __init__(self, observations, intrinsics):
        self.counts = [len(o.object_points) for o in observations]
        self.total = sum(self.counts)
        self.out = np.empty((self.total, 2), dtype=np.float64)
        self.cams = [np.empty((n, 3), dtype=np.float64) for n in self.counts]
        bounds = np.concatenate([[0], np.cumsum(self.counts)])
        self.slices = [(int(bounds[i]), int(bounds[i + 1])) for i in range(len(observations))]


def residuals_prealloc(params, observations, intrinsics, state: PreallocState):
    scale = math.exp(params[0])
    rotation, _ = cv2.Rodrigues(params[1:4])
    translation = params[4:7]
    fx, fy = intrinsics[0, 0], intrinsics[1, 1]
    cx, cy = intrinsics[0, 2], intrinsics[1, 2]
    out = state.out
    for i, observation in enumerate(observations):
        lo, hi = state.slices[i]
        r_source = observation.r_target @ rotation.T
        t_source = scale * observation.t_target - r_source @ translation
        camera = state.cams[i]
        np.matmul(observation.object_points, r_source.T, out=camera)
        camera += t_source
        depth = camera[:, 2]
        behind = depth <= 1e-6
        safe = np.where(behind, 1e-6, depth)
        block = out[lo:hi]
        block[:, 0] = fx * camera[:, 0] / safe + cx - observation.image_points[:, 0]
        block[:, 1] = fy * camera[:, 1] / safe + cy - observation.image_points[:, 1]
        block[behind] = 1e4
    return out


# ------------------------------------------------------------- (d)/(e) numba

NUMBA_OK = False
try:
    import numba  # noqa: F401
    from numba import njit

    NUMBA_OK = True
except Exception as exc:  # pragma: no cover
    NUMBA_IMPORT_ERROR = repr(exc)

if NUMBA_OK:

    @njit(cache=False, fastmath=False)
    def _residuals_numba(obj, img, cam_idx, r_source, t_source, fx, fy, cx, cy, out):
        n = obj.shape[0]
        for k in range(n):
            c = cam_idx[k]
            x = obj[k, 0]
            y = obj[k, 1]
            z = obj[k, 2]
            cxp = r_source[c, 0, 0] * x + r_source[c, 0, 1] * y + r_source[c, 0, 2] * z + t_source[c, 0]
            cyp = r_source[c, 1, 0] * x + r_source[c, 1, 1] * y + r_source[c, 1, 2] * z + t_source[c, 1]
            czp = r_source[c, 2, 0] * x + r_source[c, 2, 1] * y + r_source[c, 2, 2] * z + t_source[c, 2]
            if czp <= 1e-6:
                out[k, 0] = 1e4
                out[k, 1] = 1e4
            else:
                out[k, 0] = fx * cxp / czp + cx - img[k, 0]
                out[k, 1] = fy * cyp / czp + cy - img[k, 1]
        return out

    def residuals_numba(params, pack: Pack, _intrinsics=None):
        r_source, t_source = _pose(pack, params)
        return _residuals_numba(
            pack.obj, pack.img, pack.cam_idx,
            np.ascontiguousarray(r_source), np.ascontiguousarray(t_source),
            pack.fx, pack.fy, pack.cx, pack.cy, pack.out,
        )

    @njit(cache=False, fastmath=False)
    def _residuals_c_proxy(obj, img, cam_idx, r_target, t_target, rot, tr, scale,
                           fx, fy, cx, cy, out, n_cam):
        """Scalar loop that ALSO does the pose composition, i.e. exactly the
        work a hand-written C/pybind11 `_residuals` would do end to end,
        with no numpy call at all. Proxy for variant (e)."""
        rs = np.empty((n_cam, 3, 3))
        ts = np.empty((n_cam, 3))
        for c in range(n_cam):
            for i in range(3):
                for j in range(3):
                    s = 0.0
                    for k in range(3):
                        s += r_target[c, i, k] * rot[j, k]   # r_target @ rot.T
                    rs[c, i, j] = s
            for i in range(3):
                s = 0.0
                for j in range(3):
                    s += rs[c, i, j] * tr[j]
                ts[c, i] = scale * t_target[c, i] - s
        n = obj.shape[0]
        for k in range(n):
            c = cam_idx[k]
            x = obj[k, 0]
            y = obj[k, 1]
            z = obj[k, 2]
            a = rs[c, 0, 0] * x + rs[c, 0, 1] * y + rs[c, 0, 2] * z + ts[c, 0]
            b = rs[c, 1, 0] * x + rs[c, 1, 1] * y + rs[c, 1, 2] * z + ts[c, 1]
            d = rs[c, 2, 0] * x + rs[c, 2, 1] * y + rs[c, 2, 2] * z + ts[c, 2]
            if d <= 1e-6:
                out[k, 0] = 1e4
                out[k, 1] = 1e4
            else:
                out[k, 0] = fx * a / d + cx - img[k, 0]
                out[k, 1] = fy * b / d + cy - img[k, 1]
        return out

    def residuals_c_proxy(params, pack: Pack, _intrinsics=None):
        scale = math.exp(params[0])
        rot, _ = cv2.Rodrigues(params[1:4])
        return _residuals_c_proxy(
            pack.obj, pack.img, pack.cam_idx, pack.r_target, pack.t_target,
            np.ascontiguousarray(rot), np.ascontiguousarray(params[4:7]), scale,
            pack.fx, pack.fy, pack.cx, pack.cy, pack.out, pack.n_cameras,
        )


# ------------------------------------------------------------------ timing

def bench(fn, repeats: int, inner: int = 20) -> float:
    """Return best-of-`repeats` mean seconds per call."""
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        for _ in range(inner):
            fn()
        dt = (time.perf_counter() - t0) / inner
        best = min(best, dt)
    return best


def run_case(cameras: int, points: int, label: str, repeats: int = 40, inner: int = 40):
    observations = make_observations(cameras, points)
    pack = Pack(observations, INTRINSICS)
    state = PreallocState(observations, INTRINSICS)
    rng = np.random.default_rng(3)
    params = np.concatenate(
        [[math.log(1.03)], rng.normal(scale=0.05, size=3), rng.normal(scale=0.1, size=3)]
    )

    reference = residuals_control(params, observations, INTRINSICS)
    n_res = reference.shape[0]

    variants = [
        ("(a) control  shipped loop", lambda: residuals_control(params, observations, INTRINSICS)),
        ("(b1) flat gather+einsum", lambda: residuals_flat_gather(params, pack)),
        ("(b2) flat all-camera gemm", lambda: residuals_flat_allcam(params, pack)),
        ("(b3) flat blocks+prealloc", lambda: residuals_flat_blocks(params, pack)),
        ("(c) shipped loop, prealloc", lambda: residuals_prealloc(params, observations, INTRINSICS, state)),
    ]
    if NUMBA_OK:
        variants.append(("(d) numba njit (flat pack)", lambda: residuals_numba(params, pack)))
        variants.append(("(e) njit scalar, C proxy", lambda: residuals_c_proxy(params, pack)))

    # correctness gate
    checks = {}
    for name, fn in variants:
        got = np.asarray(fn()).copy()
        checks[name] = bool(
            got.shape == reference.shape
            and np.allclose(got, reference, rtol=0, atol=1e-9)
        )

    # warm up jits
    for name, fn in variants:
        for _ in range(5):
            fn()

    rows = []
    control_t = None
    for name, fn in variants:
        t = bench(fn, repeats, inner)
        if control_t is None:
            control_t = t
        rows.append((name, t, t / n_res * 1e9, control_t / t, checks[name]))

    # pack cost, so the amortisation can be priced
    t_pack = bench(lambda: Pack(observations, INTRINSICS), 10, 20)

    print(f"\n=== {label}: {cameras} cameras, {n_res} point-residuals ===")
    print(f"{'variant':<30} {'us/call':>9} {'ns/point':>9} {'speedup':>8}  exact")
    for name, t, ns, sp, ok in rows:
        print(f"{name:<30} {t*1e6:9.2f} {ns:9.1f} {sp:8.2f}x  {'yes' if ok else 'NO'}")
    print(f"{'pack build (once per _refine)':<30} {t_pack*1e6:9.2f}")
    return rows, t_pack


def main():
    print("python", sys.version.split()[0], "numpy", np.__version__, "cv2", cv2.__version__)
    print("numba:", "available" if NUMBA_OK else f"NOT available ({NUMBA_IMPORT_ERROR})")
    # The MEASURED mean shape, plus the ends of the measured range.
    run_case(4, 176, "measured-mean-ish (4.5 cam / 197.6 pts -> 4 cam)")
    run_case(5, 220, "measured mean (5 cam x 44)")
    run_case(6, 264, "upper end (6 cam x 44)")
    run_case(2, 88, "sparse pair (2 cam)")
    run_case(12, 528, "large graph (12 cam) - scaling check")


if __name__ == "__main__":
    main()
