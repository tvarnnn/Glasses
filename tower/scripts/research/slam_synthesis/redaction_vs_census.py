"""TENSION 4: does redaction blackout contaminate Lane 1's covisibility census?

Lane 3 found solid-fill face redaction (`redaction.py` FILL_VALUE = 0) destroys
a dense pointmap matcher far more than it destroys ORB, and the lead measured
that 56.2% of the 457 canonical keyframes carry >10% exactly-black pixels.

Lane 1's 8,989-edge census was computed with ORB over those same redacted
frames. If blackout suppresses ORB edges too, Lane 1's headline is a LOWER
bound and the real graph is larger. If it does not, Lane 1's headline stands as
measured. Nobody asked the data.

Measures, per keyframe: exactly-black fraction (grey <= 2, the lead's
threshold), ORB feature count, and the covisibility degree Lane 1's census
assigned it. Then reports degree and feature count stratified by blackout.

Read-only. No production code modified.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TOWER = HERE.parents[2]
sys.path.insert(0, str(TOWER))

from tower.world_builder.geometry import detect_and_describe  # noqa: E402

SESSION = (TOWER / "data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4"
           / "sessions/dd5d13a2381e430db9b27c7da2cf2928")


def main():
    cen = json.load(open(HERE.parent / "slam_classical/covisibility_census.json"))
    n = cen["meta"]["n_keyframes"]
    deg = [0] * n
    useful_deg = [0] * n
    for p in cen["pairs"]:
        if p["f_inliers"] >= 15:
            deg[p["i"]] += 1
            deg[p["j"]] += 1
            t = p.get("tri_angle")
            if t is not None and t >= 0.5:
                useful_deg[p["i"]] += 1
                useful_deg[p["j"]] += 1

    imgs = sorted((SESSION / "images").glob("*.jpg"))
    assert len(imgs) == n, (len(imgs), n)

    rows = []
    for i, path in enumerate(imgs):
        g = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        black = float((g <= 2).mean())
        kp, des = detect_and_describe(g)
        rows.append({"i": i, "black": black, "orb": len(kp),
                     "degree": deg[i], "useful_degree": useful_deg[i]})
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{n}", flush=True)

    (HERE / "redaction_vs_census.json").write_text(json.dumps(rows, indent=1))

    def band(lo, hi):
        return [r for r in rows if lo <= r["black"] < hi]

    print("\n=== blackout vs the census Lane 1 measured ===")
    print(f"{'black fraction':>16} {'n':>4} {'med ORB':>8} {'med degree':>11} "
          f"{'med useful deg':>15}")
    for lo, hi, lab in ((0, .05, "<5%"), (.05, .10, "5-10%"), (.10, .20, "10-20%"),
                        (.20, .40, "20-40%"), (.40, .60, "40-60%"), (.60, 1.01, ">60%")):
        b = band(lo, hi)
        if not b:
            continue
        print(f"{lab:>16} {len(b):>4} {st.median(r['orb'] for r in b):>8.0f} "
              f"{st.median(r['degree'] for r in b):>11.0f} "
              f"{st.median(r['useful_degree'] for r in b):>15.0f}")

    bl = np.array([r["black"] for r in rows])
    dg = np.array([r["degree"] for r in rows], float)
    ob = np.array([r["orb"] for r in rows], float)

    def spearman(x, y):
        rx = np.argsort(np.argsort(x)).astype(float)
        ry = np.argsort(np.argsort(y)).astype(float)
        return float(np.corrcoef(rx, ry)[0, 1])

    print(f"\nSpearman(black fraction, covisibility degree) = {spearman(bl, dg):+.3f}")
    print(f"Spearman(black fraction, ORB feature count)    = {spearman(bl, ob):+.3f}")
    print(f"Spearman(ORB feature count, covisibility degree)= {spearman(ob, dg):+.3f}")
    print(f"\nkeyframes >10% black: {int((bl > .10).sum())}/{len(rows)} "
          f"({100*(bl > .10).mean():.1f}%)   >40%: {int((bl > .40).sum())} "
          f"({100*(bl > .40).mean():.1f}%)")
    print(f"keyframes with <=100 ORB features: {int((ob <= 100).sum())}; "
          f"with 0: {int((ob == 0).sum())}")
    starved = [r for r in rows if r["orb"] <= 100]
    if starved:
        print(f"  of those, median black fraction {st.median(r['black'] for r in starved):.3f}; "
              f"how many are >40% black: {sum(1 for r in starved if r['black'] > .4)}")


if __name__ == "__main__":
    main()
