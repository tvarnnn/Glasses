"""How exposed is PRODUCTION's own two-view gate to Lane 2's null?

Lane 2 reported "ORB + Lowe: 14.4% false 'solvable' on exactly-zero-baseline
pairs" and built its whole recommendation on that number. But Lane 2's
`verdict()` (matcher_showdown.py:168-205) is a RECONSTRUCTION of the production
criterion, and it differs from `backends/classical.py:434-515` in three ways
that all matter under degeneracy:

  1. `cv2.RANSAC` vs production's `cv2.USAC_MAGSAC`
  2. it triangulates over the EPIPOLAR inlier set; production triangulates over
     the set `recoverPose` narrowed with its CHEIRALITY test
  3. it gates `MIN_INLIER_RATIO` on the epipolar ratio; production gates it on
     the CHEIRALITY ratio (classical.py:478-481, explicitly, with a comment
     saying the field name was wrong for years)

Point 2 and 3 are exactly the guards that pure rotation trips: with no baseline,
few points are genuinely in front of both cameras. So run BOTH verdicts over the
IDENTICAL 200 zero-baseline pairs and report the gap.

Read-only. No production code modified.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TOWER = HERE.parents[2]
sys.path.insert(0, str(TOWER))

from tower.world_builder.geometry import (  # noqa: E402
    MIN_INLIERS, MIN_INLIER_RATIO, MIN_TRIANGULATION_ANGLE_DEG,
    RANSAC_CONFIDENCE, RANSAC_THRESHOLD_PX,
    detect_and_describe, match_descriptors, median_triangulation_angle_deg,
)


def lane2_verdict(pa, pb, K):
    """matcher_showdown.verdict, transcribed."""
    if len(pa) < 8:
        return "no_correspondence", None
    E, mask = cv2.findEssentialMat(pa, pb, K, cv2.RANSAC,
                                  RANSAC_CONFIDENCE, RANSAC_THRESHOLD_PX)
    if E is None or E.shape != (3, 3) or mask is None:
        return "no_essential", None
    inl = int(mask.sum())
    if inl < MIN_INLIERS:
        return "few_inliers", None
    if inl / len(pa) < MIN_INLIER_RATIO:
        return "low_inlier_ratio", None
    m = mask.ravel().astype(bool)
    _, R, t, _ = cv2.recoverPose(E, pa[m], pb[m], K)
    tri = median_triangulation_angle_deg(pa[m], pb[m], R, t.reshape(3), K)
    if tri is None:
        return "no_triangulation", None
    if tri < MIN_TRIANGULATION_ANGLE_DEG:
        return "low_parallax", tri
    return "solvable", tri


def production_verdict(pa, pb, K):
    """backends/classical.py:434-515, transcribed."""
    if len(pa) < 8:
        return "no_correspondence", None
    E, mask = cv2.findEssentialMat(pa, pb, K, method=cv2.USAC_MAGSAC,
                                  prob=RANSAC_CONFIDENCE,
                                  threshold=RANSAC_THRESHOLD_PX)
    if E is None or E.shape != (3, 3):
        return "no_essential", None
    _, R, t, _ = cv2.recoverPose(E, pa, pb, K, mask=mask)
    kept = mask.ravel() > 0
    inliers = int(kept.sum())
    cheirality_ratio = inliers / len(pa)
    tri = None
    if inliers >= 2:
        tri = median_triangulation_angle_deg(
            pa[kept], pb[kept], R, np.asarray(t, np.float64).reshape(3), K)
    if inliers < MIN_INLIERS:
        return "degenerate:few_inliers", tri
    if cheirality_ratio < MIN_INLIER_RATIO:
        return "degenerate:low_cheirality", tri
    if tri is None:
        return "degenerate:no_triangulation", tri
    if tri < MIN_TRIANGULATION_ANGLE_DEG:
        return "degenerate:low_parallax", tri
    return "solvable", tri


def main():
    scratch = json.load(open(HERE / "paths.json"))["scratch"]
    manifest = json.load(open(scratch + "/manifest_purerot_null.json"))
    intr = json.load(open(TOWER / "data/world_builder/intrinsics/360x640.json"))
    K = np.array([[intr["fx"], 0, intr["cx"]],
                  [0, intr["fy"], intr["cy"]], [0, 0, 1.0]])

    rows = []
    for k, job in enumerate(manifest):
        ga = cv2.imread(job["a"], cv2.IMREAD_GRAYSCALE)
        gb = cv2.imread(job["b"], cv2.IMREAD_GRAYSCALE)
        ka, da = detect_and_describe(ga)
        kb, db = detect_and_describe(gb)
        pa, pb = match_descriptors(ka, da, kb, db)
        v2, t2 = lane2_verdict(pa, pb, K)
        vp, tp = production_verdict(pa, pb, K)
        rows.append({"name": job["name"], "angle": job["true_rotation_deg"],
                     "n_matches": int(len(pa)),
                     "lane2_verdict": v2, "lane2_tri": t2,
                     "production_verdict": vp, "production_tri": tp})
        if (k + 1) % 50 == 0:
            print(f"  {k+1}/{len(manifest)}", flush=True)

    (HERE / "production_gate_on_null.json").write_text(json.dumps(rows, indent=1))

    n = len(rows)
    print("\n=== 200 pairs, TRUE translation exactly 0. Any 'solvable' is FALSE ===")
    for label, key in (("Lane 2's transcription", "lane2_verdict"),
                       ("PRODUCTION classical.py", "production_verdict")):
        fp = sum(1 for r in rows if r[key] == "solvable")
        print(f"{label:26s}  false 'solvable' {fp:3d}/{n} = {100*fp/n:5.1f}%")
        print(f"{'':26s}  verdict mix: {dict(Counter(r[key] for r in rows))}")
    print("\nby true rotation:")
    for a in sorted({r["angle"] for r in rows}):
        s = [r for r in rows if r["angle"] == a]
        f2 = sum(1 for r in s if r["lane2_verdict"] == "solvable")
        fp = sum(1 for r in s if r["production_verdict"] == "solvable")
        print(f"  {a:>4.1f} deg  lane2 {f2:2d}/{len(s)}   production {fp:2d}/{len(s)}")
    tri2 = sorted(r["lane2_tri"] for r in rows if r["lane2_tri"] is not None)
    trip = sorted(r["production_tri"] for r in rows if r["production_tri"] is not None)
    if tri2:
        print(f"\nestimated tri angle, Lane 2 path:      n={len(tri2)} "
              f"median={st.median(tri2):.3f} p90={tri2[int(.9*len(tri2))]:.3f} max={tri2[-1]:.2f}")
    if trip:
        print(f"estimated tri angle, production path:  n={len(trip)} "
              f"median={st.median(trip):.3f} p90={trip[int(.9*len(trip))]:.3f} max={trip[-1]:.2f}")


if __name__ == "__main__":
    main()
