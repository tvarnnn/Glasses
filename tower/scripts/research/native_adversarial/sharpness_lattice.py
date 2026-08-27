"""Can the absolute floor (25.0) EVER flip? A lattice argument, checked.

The Laplacian at CV_16S is an INTEGER array. So the variance of N such
values is exactly

    V = (N*sum(x^2) - sum(x)^2) / N^2

whose numerator is an integer. Every achievable sharpness therefore lies
on a lattice of spacing 1/N^2. If that spacing is much larger than the
float64 discrepancy between the two implementations near 25.0, then no
achievable value can lie strictly between them, and the gate CANNOT flip
-- except for the measure-zero case of a value landing exactly on 25.0,
which is tested separately below.
"""
import numpy as np
import cv2

print("=" * 70)
print("A. The lattice spacing at product resolution vs the discrepancy")
print("=" * 70)
eps_at_25 = np.spacing(25.0)
for (h, w), label in (((360, 640), "product frame 360x640"),
                      ((240, 320), "half res"),
                      ((1080, 1920), "1080p"),
                      ((5500, 5500), "hypothetical 30 MP")):
    n = h * w
    spacing = 1.0 / (n * n)
    print(f"  {label:<24} N={n:>10,}  lattice spacing={spacing:.3e}  "
          f"spacing/eps(25)={spacing / eps_at_25:>10.3e}")
print(f"  float64 eps at 25.0 = {eps_at_25:.3e}")
print()
print("  At 360x640 the lattice is ~5300x COARSER than one float64 ULP at")
print("  25.0, so an achievable sharpness is either >= 25 by at least")
print("  1.9e-11, or < 25 by at least that much. A ~1e-15 implementation")
print("  discrepancy cannot move a value across the bar. The absolute")
print("  floor is UNFLIPPABLE at this resolution -- unless a value is")
print("  EXACTLY 25.0.")

print()
print("=" * 70)
print("B. Verify the lattice claim empirically on real-shaped data")
print("=" * 70)
rng = np.random.default_rng(0)
g = rng.integers(0, 256, (360, 640), dtype=np.uint8)
lap = cv2.Laplacian(g, cv2.CV_16S).astype(np.int64)
n = lap.size
num = n * int((lap.astype(object) ** 2).sum()) - int(lap.sum()) ** 2
exact = num / (n * n)
old = float(cv2.Laplacian(g, cv2.CV_64F).var())
_, d = cv2.meanStdDev(cv2.Laplacian(g, cv2.CV_16S))
new = float(d[0, 0] ** 2)
print(f"  exact rational value : {exact!r}")
print(f"  old (.var())         : {old!r}   err={abs(old - exact):.3e}")
print(f"  new (meanStdDev^2)   : {new!r}   err={abs(new - exact):.3e}")
print(f"  numerator is an integer: {float(num).is_integer()}")

print()
print("=" * 70)
print("C. The one flippable case: a value EXACTLY on the bar")
print("=" * 70)
print("  Constructing an int16 array whose variance is exactly 25.0")
print("  (half +5, half -5) and reducing it both ways:")
for n in (230_400, 100, 1024, 230_401):
    if n % 2:
        arr = np.concatenate([np.full(n // 2 + 1, 5), np.full(n // 2, -5)])
    else:
        arr = np.concatenate([np.full(n // 2, 5), np.full(n // 2, -5)])
    arr = arr.astype(np.int16).reshape(-1, 1)
    v_old = float(arr.astype(np.float64).var())
    _, dv = cv2.meanStdDev(arr)
    v_new = float(dv[0, 0] ** 2)
    go_old = v_old < 25.0
    go_new = v_new < 25.0
    flag = "FLIP!" if go_old != go_new else "same"
    print(f"  N={n:<8} old={v_old!r:<22} new={v_new!r:<22} "
          f"rejected old={go_old} new={go_new}  [{flag}]")
print()
print("  A value exactly ON the bar is the only flippable case, and it")
print("  requires N*sum(x^2) - sum(x)^2 == 25*N^2 exactly. On real imagery")
print("  that is measure-zero; part B of sharpness_margins.py measures how")
print("  close the actual corpus ever gets.")
