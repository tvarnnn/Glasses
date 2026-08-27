"""Does r_H -- the statistic World Builder already computes and never uses --
catch the pure-rotation false positives that the triangulation-angle gate and
Lane 3's reciprocity gate both let through?

Lane 1 measured r_H as a LOW-PARALLAX detector on real verified edges and found
AUC 0.765 -- real signal, bad operating points -- and recommended not gating on
it. That is a different question from the one Lane 2's null poses. ORB-SLAM3
does not use r_H as a low-parallax detector either; it uses it as a
PURE-ROTATION / PLANAR model selector at initialisation, which is exactly the
regime Lane 2 constructed.

So: compute r_H on pairs whose true translation is EXACTLY ZERO, with the
production ORB detector and the production Lowe matcher, and compare against
the distribution Lane 1 already measured over 8,989 real verified edges.

Uses a DEFECT-FREE local r_H: production's `geometry.homography_ratio` reads
an uninitialised OpenCV 5 mask when RANSAC returns model=None (Lane 1 §8,
independently reproduced by the lead). This checks the model first.

Read-only against the corpus. No production code modified.
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
TOWER = HERE.parents[2]
sys.path.insert(0, str(TOWER))

from tower.world_builder import geometry as G  # noqa: E402


def safe_rh(pa, pb):
    """geometry.homography_ratio, with the OpenCV-5 mask defect closed."""
    if len(pa) < 8:
        return None, "too_few"
    hm, h_mask = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
    fm, f_mask = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)
    h_in = int(h_mask.sum()) if (hm is not None and h_mask is not None) else 0
    f_in = int(f_mask.sum()) if (fm is not None and f_mask is not None) else 0
    if h_in + f_in == 0:
        return None, "no_model"
    return h_in / (h_in + f_in), "ok"


def main():
    manifest = json.load(open(json.load(open(HERE / "paths.json"))["scratch"]
                              + "/manifest_purerot_null.json"))
    intr = json.load(open(TOWER / "data/world_builder/intrinsics/360x640.json"))
    K = np.array([[intr["fx"], 0, intr["cx"]],
                  [0, intr["fy"], intr["cy"]], [0, 0, 1.0]])

    rows = []
    for k, job in enumerate(manifest):
        ga = cv2.imread(job["a"], cv2.IMREAD_GRAYSCALE)
        gb = cv2.imread(job["b"], cv2.IMREAD_GRAYSCALE)
        ka, da = G.detect_and_describe(ga)
        kb, db = G.detect_and_describe(gb)
        pa, pb = G.match_descriptors(ka, da, kb, db)
        if len(pa) < 15:
            rows.append({"name": job["name"], "angle": job["true_rotation_deg"],
                         "n_matches": len(pa), "rh": None, "tri": None,
                         "verdict": "too_few_matches"})
            continue
        rh, why = safe_rh(pa, pb)
        E, emask = cv2.findEssentialMat(pa, pb, K, method=cv2.USAC_MAGSAC,
                                        prob=0.999, threshold=1.0)
        tri = None
        n_in = 0
        if E is not None and emask is not None and E.shape == (3, 3):
            n_in = int(emask.sum())
            n_ch, R, t, pmask = cv2.recoverPose(E, pa, pb, K, mask=emask.copy())
            keep = pmask.ravel().astype(bool)
            if keep.sum() >= 8:
                tri = G.median_triangulation_angle_deg(
                    pa[keep], pb[keep], R, t, K)
        rows.append({"name": job["name"], "angle": job["true_rotation_deg"],
                     "n_matches": len(pa), "e_inliers": n_in,
                     "rh": rh, "rh_why": why, "tri": tri})
        if (k + 1) % 25 == 0:
            print(f"  {k+1}/{len(manifest)}", flush=True)

    (HERE / "rh_on_null.json").write_text(json.dumps(rows, indent=1))

    print("\n=== r_H on pairs whose TRUE translation is exactly zero ===")
    good = [r for r in rows if r["rh"] is not None]
    allrh = sorted(r["rh"] for r in good)
    print(f"n={len(allrh)}  median r_H={st.median(allrh):.4f}  "
          f"p05={allrh[int(.05*len(allrh))]:.4f}  p95={allrh[int(.95*len(allrh))]:.4f}  "
          f"min={allrh[0]:.4f}")
    for ang in sorted({r["angle"] for r in good}):
        s = sorted(r["rh"] for r in good if r["angle"] == ang)
        tri = [r["tri"] for r in good if r["angle"] == ang and r["tri"] is not None]
        fp = sum(1 for t in tri if t >= G.MIN_TRIANGULATION_ANGLE_DEG)
        print(f"  rot {ang:>4.1f} deg  n={len(s):3d}  median r_H={st.median(s):.4f}  "
              f"min={s[0]:.4f}  frac r_H>0.50={sum(1 for x in s if x > .5)/len(s):.3f}"
              f"   tri-angle FALSE 'solvable' {fp}/{len(tri)}")

    # Lane 1's real-edge distribution, recomputed here from its own artefact.
    cen = json.load(open(RESEARCH / "slam_classical/covisibility_census.json"))
    edges = [p for p in cen["pairs"] if p["f_inliers"] >= 15 and p.get("r_h") is not None]
    er = sorted(p["r_h"] for p in edges)
    print(f"\nLane 1's 8,989 real verified edges: n={len(er)} median r_H={st.median(er):.4f} "
          f"p95={er[int(.95*len(er))]:.4f} max={er[-1]:.4f}")
    for th in (0.50, 0.60, 0.70, 0.80, 0.90):
        caught = sum(1 for x in allrh if x > th) / len(allrh)
        cost = sum(1 for x in er if x > th) / len(er)
        print(f"  gate r_H > {th:.2f}:  catches {100*caught:5.1f}% of TRUE-zero-baseline "
              f"pairs, discards {100*cost:5.2f}% of Lane 1's real verified edges")


if __name__ == "__main__":
    main()
