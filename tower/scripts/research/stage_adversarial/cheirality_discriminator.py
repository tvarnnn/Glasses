#!/usr/bin/env python
"""Prevalence of the seed-pair decomposition failure, and whether an
already-computed quantity separates it.

WHAT WAS FOUND (MEASURED, seed1006_engine_pair.py)

  seed 1006, engine pair (0, 2): 923 matches, 804 epipolar inliers,
     279 cheirality inliers, direction error 87.12 deg
  seed 1000, engine pair (0, 2): 948 matches, 910 epipolar inliers,
     910 cheirality inliers, direction error  0.21 deg

`recoverPose` picks among the four decompositions of E by counting
points in front of BOTH cameras. When it picks right, essentially every
epipolar inlier survives (910/910). When it picks wrong, a minority does
(279/804 = 0.347) -- and the returned pose is confidently ~90 deg off.

The pipeline already computes both numbers (classical.py:664-673:
`epipolar_inliers` and `inliers`) and gates on
`cheirality_ratio = inliers / matches < MIN_INLIER_RATIO`, which is
0.05. Seed 1006 scores 279/923 = 0.302, six times the threshold, so it
passes. `r_h` does not separate them either (0.4771 vs 0.4759).

This sweeps many scenes to answer: how often does this happen, and does
cheirality/epipolar separate the failures cleanly enough to gate on?

NO GROUND TRUTH EXISTS ON THE REAL CORPUS. This is synthetic, where the
answer is known. It establishes that the failure mode is real and
detectable, not how often it occurs on real footage.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))

from tests import synthetic_scene as ss  # noqa: E402
from tower.world_builder.geometry import (  # noqa: E402
    detect_and_describe, match_descriptors, homography_ratio,
    RANSAC_THRESHOLD_PX, RANSAC_CONFIDENCE, MIN_INLIER_RATIO,
)

WIDTH, HEIGHT = 480, 360


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--first-seed", type=int, default=1000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    K = ss.camera_matrix(WIDTH, HEIGHT)
    motions = {
        "lateral": ss.strafe(8, step=0.15),
        "forward": ss.forward_walk(8, step=0.15),
    }
    rows = []
    for seed in range(args.first_seed, args.first_seed + args.seeds):
        scene = ss.furnished_room(seed=seed)
        for name, poses in motions.items():
            # The engine selected source frames (0, 2) on this walk, and
            # round-trips through JPEG q90, so both are mirrored here.
            imgs = ss.render_sequence(scene, [poses[0], poses[2]], K,
                                      WIDTH, HEIGHT)
            grays = []
            for img in imgs:
                buf = ss.encode_jpeg(img)
                grays.append(cv2.imdecode(
                    np.frombuffer(buf, np.uint8), cv2.IMREAD_GRAYSCALE
                ))
            ka, da = detect_and_describe(grays[0])
            kb, db = detect_and_describe(grays[1])
            pa, pb = match_descriptors(ka, da, kb, db)
            if len(pa) < 8:
                continue
            E, mask = cv2.findEssentialMat(
                pa, pb, K, method=cv2.USAC_MAGSAC,
                prob=RANSAC_CONFIDENCE, threshold=RANSAC_THRESHOLD_PX,
            )
            if E is None or E.shape != (3, 3):
                continue
            epi = int(mask.sum())
            n, R, t, _ = cv2.recoverPose(E, pa, pb, K, mask=mask.copy())
            d = np.asarray(t).reshape(3)
            d = d / np.linalg.norm(d)
            td = (np.asarray(poses[2].position) - np.asarray(poses[0].position))
            td = td / np.linalg.norm(td)
            err = math.degrees(math.acos(max(-1.0, min(1.0, abs(
                float(np.dot(d, td)))))))
            rh = homography_ratio(pa, pb)
            rows.append({
                "seed": seed, "motion": name,
                "matches": int(len(pa)),
                "epipolar_inliers": epi,
                "cheirality_inliers": int(n),
                "cheirality_over_matches": round(n / len(pa), 4),
                "cheirality_over_epipolar": round(n / epi, 4) if epi else None,
                "r_h": None if rh is None else round(float(rh), 4),
                "direction_error_deg": round(err, 3),
                "passes_current_gate": bool(n / len(pa) >= MIN_INLIER_RATIO),
            })

    bad = [r for r in rows if r["direction_error_deg"] > 30]
    good = [r for r in rows if r["direction_error_deg"] <= 30]
    print(f"pairs measured        {len(rows)}")
    print(f"direction error > 30  {len(bad)}  ({len(bad)/len(rows):.1%})")
    print(f"  of those, PASSING the current cheirality gate: "
          f"{sum(1 for r in bad if r['passes_current_gate'])}")

    def rng(items, key):
        vals = [r[key] for r in items if r[key] is not None]
        return (f"min {min(vals):.3f} max {max(vals):.3f} "
                f"median {np.median(vals):.3f}") if vals else "n/a"

    for key in ("cheirality_over_epipolar", "cheirality_over_matches", "r_h"):
        print(f"\n{key}")
        print(f"  GOOD (<=30 deg): {rng(good, key)}")
        print(f"  BAD  (> 30 deg): {rng(bad, key)}")

    ce_good = [r["cheirality_over_epipolar"] for r in good
               if r["cheirality_over_epipolar"] is not None]
    ce_bad = [r["cheirality_over_epipolar"] for r in bad
              if r["cheirality_over_epipolar"] is not None]
    if ce_good and ce_bad:
        print(f"\nSEPARATION on cheirality/epipolar: "
              f"worst good {min(ce_good):.4f} vs best bad {max(ce_bad):.4f} "
              f"-> {'CLEAN' if min(ce_good) > max(ce_bad) else 'OVERLAPPING'}")

    print("\nfailures:")
    for r in bad:
        print(f"  seed {r['seed']} {r['motion']:8s} err {r['direction_error_deg']:7.2f} "
              f"ch/epi {r['cheirality_over_epipolar']} ch/match "
              f"{r['cheirality_over_matches']} r_h {r['r_h']} "
              f"gate_passes {r['passes_current_gate']}")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
