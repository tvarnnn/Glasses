"""Adversarial verification of the measure_sharpness CV_16S/meanStdDev change.

Attacks the exactness argument on: default kwargs, dtype/channel
assumptions, degenerate shapes, non-contiguous views, and threshold flips.
"""
import numpy as np
import cv2

OLD = lambda g: float(cv2.Laplacian(g, cv2.CV_64F).var())


def NEW(g):
    _, d = cv2.meanStdDev(cv2.Laplacian(g, cv2.CV_16S))
    return float(d[0, 0] ** 2)


def rel(a, b):
    if a == b:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b), 1e-300)


print("=" * 70)
print("A. cv2.Laplacian actual signature/defaults")
print("=" * 70)
print(cv2.Laplacian.__doc__)

print("=" * 70)
print("B. Laplacian CV_64F vs CV_16S bit-exactness on uint8")
print("=" * 70)
rng = np.random.default_rng(0)
worst = 0
mismatches = 0
for trial in range(300):
    h, w = int(rng.integers(2, 80)), int(rng.integers(2, 80))
    g = rng.integers(0, 256, size=(h, w), dtype=np.uint8)
    if trial % 3 == 0:
        g = ((np.indices((h, w)).sum(0) % 2) * 255).astype(np.uint8)
    a = cv2.Laplacian(g, cv2.CV_64F)
    b = cv2.Laplacian(g, cv2.CV_16S)
    if not np.array_equal(a, b):
        mismatches += 1
        print(f"  MISMATCH shape={(h, w)} maxdiff={np.abs(a - b).max()}")
    worst = max(worst, np.abs(a).max())
print(f"  300 random+checkerboard uint8 images, mismatches={mismatches}")
print(f"  max |Laplacian| observed = {worst}  (int16 limit 32767)")
g = np.zeros((5, 5), np.uint8)
g[1, 2] = g[3, 2] = g[2, 1] = g[2, 3] = 255
print(f"  analytic max cross = {cv2.Laplacian(g, cv2.CV_64F).max()}")
g2 = np.full((5, 5), 255, np.uint8)
g2[2, 2] = 0
print(f"  analytic min cross = {cv2.Laplacian(g2, cv2.CV_64F).min()}")

print("=" * 70)
print("C. Degenerate / hostile inputs")
print("=" * 70)
cases = {
    "uniform 64x64 (zero variance)": np.full((64, 64), 128, np.uint8),
    "uniform zeros": np.zeros((64, 64), np.uint8),
    "1xN row": np.arange(64, dtype=np.uint8).reshape(1, 64),
    "Nx1 col": np.arange(64, dtype=np.uint8).reshape(64, 1),
    "1x1": np.array([[7]], np.uint8),
    "2x2": np.array([[0, 255], [255, 0]], np.uint8),
    "empty 0x0": np.zeros((0, 0), np.uint8),
    "empty 0xN": np.zeros((0, 8), np.uint8),
    "non-contiguous stride-2 view": np.ascontiguousarray(
        rng.integers(0, 256, (64, 128), dtype=np.uint8))[:, ::2],
    "transposed view": np.ascontiguousarray(
        rng.integers(0, 256, (64, 32), dtype=np.uint8)).T,
    "3-channel colour 32x32": rng.integers(0, 256, (32, 32, 3), dtype=np.uint8),
    "float32 input": (rng.random((32, 32)) * 1000.0).astype(np.float32),
    "float64 input": rng.random((32, 32)) * 1e6,
    "uint16 input": rng.integers(0, 65536, (32, 32), dtype=np.uint16),
    "int16 input": rng.integers(-32768, 32767, (32, 32), dtype=np.int16),
}
for name, arr in cases.items():
    def run(f, a=arr):
        try:
            with np.errstate(all="ignore"):
                return f(a)
        except Exception as e:
            return f"{type(e).__name__}: {str(e)[:70]}"
    o, n = run(OLD), run(NEW)
    same = (o == n) or (isinstance(o, float) and isinstance(n, float)
                        and np.isnan(o) and np.isnan(n))
    flag = "OK  " if same else "DIFF"
    if isinstance(o, float) and isinstance(n, float) and not same:
        flag = f"DIFF rel={rel(o, n):.3e}"
    print(f"  [{flag}] {name}")
    print(f"          old={o}")
    print(f"          new={n}")
