"""Does cProfile make the NATIVE share an UNDER-estimate, as claimed?

The verdict leans on "79.1% native", qualified by: cProfile inflates
Python frames, so the native share is if anything an under-estimate. That
direction is the difference between a conservative claim and a flattering
one, so it is checked here rather than asserted.

Method: a workload with a KNOWN split -- a pure-Python loop plus a big
OpenCV call -- measured two ways. First the true split by
time.perf_counter with no profiler. Then the cProfile split, classified
exactly as profile_split.py does it (filename == "~" is NATIVE).

If the claim holds, the cProfile native share must come out LOWER than
the true native share.
"""
import cProfile
import pstats
import time

import cv2
import numpy as np


def python_work(n):
    total = 0
    for i in range(n):
        total += i * i % 7
    return total


def native_work(img, reps):
    out = None
    for _ in range(reps):
        out = cv2.GaussianBlur(img, (31, 31), 0)
    return out


rng = np.random.default_rng(0)
IMG = rng.integers(0, 256, (1080, 1920), dtype=np.uint8).astype(np.uint8)


def workload(py_n, nat_reps):
    python_work(py_n)
    native_work(IMG, nat_reps)


def true_split(py_n, nat_reps):
    t0 = time.perf_counter()
    python_work(py_n)
    t1 = time.perf_counter()
    native_work(IMG, nat_reps)
    t2 = time.perf_counter()
    return (t1 - t0), (t2 - t1)


def cprofile_split(py_n, nat_reps):
    pr = cProfile.Profile()
    pr.enable()
    workload(py_n, nat_reps)
    pr.disable()
    stats = pstats.Stats(pr)
    native = python = 0.0
    for (filename, _lineno, _name), (_cc, _nc, tottime, _ct, _cs) in \
            stats.stats.items():
        if filename == "~":
            native += tottime
        else:
            python += tottime
    return native, python


print("=" * 74)
print("Claim under test: cProfile makes the NATIVE share an UNDER-estimate")
print("=" * 74)
print(f"{'mix':<26} {'true native%':>13} {'cProfile native%':>18} {'direction':>12}")
print("-" * 74)

all_under = True
for py_n, nat_reps, label in (
    (2_000_000, 12, "python-heavy"),
    (1_000_000, 25, "balanced"),
    (300_000, 40, "native-heavy"),
    (5_000_000, 8, "very python-heavy"),
):
    # warm
    workload(1000, 1)
    py_t, nat_t = true_split(py_n, nat_reps)
    true_native_pct = 100.0 * nat_t / (py_t + nat_t)
    nat_c, py_c = cprofile_split(py_n, nat_reps)
    prof_native_pct = 100.0 * nat_c / (nat_c + py_c)
    under = prof_native_pct < true_native_pct
    all_under &= under
    print(f"{label:<26} {true_native_pct:>12.1f}% {prof_native_pct:>17.1f}% "
          f"{'UNDER (ok)' if under else 'OVER (!!)':>12}")

print("-" * 74)
print(f"cProfile under-estimated the native share in every mix: {all_under}")
print()
print("If True, the 79.1% headline is CONSERVATIVE: the true native share")
print("of the unprofiled run is higher, which strengthens the refusal.")
