"""Secondary reads of matcher_showdown.json: blur sensitivity and gap sensitivity.

Everything here is CPU-only post-processing of measurements already taken.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from matcher_showdown import klass  # noqa: E402

d = json.loads((HERE / "matcher_showdown.json").read_text())
rows = d["pairs"]
matchers = [k for k in ("orb", "loftr", "disk_lg") if k in rows[0]]
print(f"{len(rows)} pairs, matchers {matchers}")

print("\n=== BLUR SENSITIVITY (variance-of-Laplacian sharpness of the "
      "BLURRIER frame of each pair) ===")
sharp = np.array([min(r["sharp_a"] or 0, r["sharp_b"] or 0) for r in rows])
edges = np.percentile(sharp, [0, 25, 50, 75, 100])
print(f"sharpness quartiles: {[round(float(x), 1) for x in edges]}")
print(f"{'bucket':>18} {'n':>5} " +
      " ".join(f"{m + ' solv%':>14}" for m in matchers) +
      " " + " ".join(f"{m + ' matches':>16}" for m in matchers))
for lo, hi, label in [(edges[0], edges[1], "Q1 blurriest"),
                      (edges[1], edges[2], "Q2"),
                      (edges[2], edges[3], "Q3"),
                      (edges[3], edges[4] + 1, "Q4 sharpest")]:
    sel = [r for r, s in zip(rows, sharp) if lo <= s < hi]
    if not sel:
        continue
    solv = [100 * sum(1 for r in sel if r[m]["verdict"] == "solvable") / len(sel)
            for m in matchers]
    mm = [statistics.median([r[m]["matches"] for r in sel]) for m in matchers]
    print(f"{label:>18} {len(sel):>5} " +
          " ".join(f"{v:>13.1f}%" for v in solv) + " " +
          " ".join(f"{v:>16.0f}" for v in mm))

print("\n=== KEYFRAME GAP (source frames skipped between the two keyframes) ===")
gaps = np.array([r["gap"] for r in rows])
print(f"gap median {np.median(gaps):.0f}  p90 {np.percentile(gaps, 90):.0f}  "
      f"max {gaps.max()}")
for lo, hi, label in [(1, 2, "gap 1"), (2, 4, "gap 2-3"), (4, 9, "gap 4-8"),
                      (9, 10 ** 6, "gap >=9")]:
    sel = [r for r in rows if lo <= r["gap"] < hi]
    if not sel:
        continue
    solv = [100 * sum(1 for r in sel if r[m]["verdict"] == "solvable") / len(sel)
            for m in matchers]
    print(f"{label:>18} {len(sel):>5} " + " ".join(f"{v:>13.1f}%" for v in solv))

print("\n=== TRIANGULATION ANGLE SHIFT, same images, different matcher ===")
both = [r for r in rows
        if all(r[m]["tri"] is not None for m in matchers)]
print(f"{len(both)} pairs where every matcher produced an angle")
for m in matchers:
    t = [r[m]["tri"] for r in both]
    print(f"  {m:>8}  median {statistics.median(t):.3f}  "
          f"p25 {np.percentile(t, 25):.3f}  p75 {np.percentile(t, 75):.3f}  "
          f"frac >= 0.5 deg {100 * sum(1 for x in t if x >= 0.5) / len(t):.1f}%")
if "loftr" in matchers and "orb" in matchers:
    ratio = [r["loftr"]["tri"] / r["orb"]["tri"] for r in both
             if r["orb"]["tri"] > 1e-6]
    print(f"  per-pair loftr/orb angle ratio: median {statistics.median(ratio):.2f}, "
          f"p25 {np.percentile(ratio, 25):.2f}, p75 {np.percentile(ratio, 75):.2f}, "
          f"frac > 1: {100 * sum(1 for x in ratio if x > 1) / len(ratio):.1f}%")

print("\n=== MATCH COUNT ===")
for m in matchers:
    mm = [r[m]["matches"] for r in rows]
    inl = [r[m]["inliers"] for r in rows]
    rr = [r[m]["ratio"] for r in rows if r[m]["ratio"] is not None]
    print(f"  {m:>8}  matches median {statistics.median(mm):>6.0f}  "
          f"inliers median {statistics.median(inl):>6.0f}  "
          f"inlier ratio median {statistics.median(rr):.3f}")

print("\n=== WHOLE-SESSION VERDICT MIX (all 406 consecutive keyframe pairs) ===")
for m in matchers:
    c = Counter(klass(r[m]["verdict"]) for r in rows)
    print(f"  {m:>8}  " + "  ".join(f"{k}={v} ({100 * v / len(rows):.1f}%)"
                                    for k, v in sorted(c.items())))
