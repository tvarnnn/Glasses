"""MINIMAL DETERMINISTIC REPRO: OpenCV 5.0 RANSAC mask on a failed fit.

The research lead could not reproduce this with SYNTHETIC degenerate
configurations (identical point sets, collinear points, all-same-point,
planar with 0.01 px translation) at n=242 with float32 Nx2 inputs. This
script uses the REAL frame pair where it was first observed, so the input
is the actual thing, not a construction.

THE PAIR
  capture      22e9d4289cb440fbb3f14e6da369a136
  session      dd5d13a2381e430db9b27c7da2cf2928
  keyframe A   index 12   id ...:00000345  source_seq 345   segment 3
  keyframe B   index 190  id ...:00001824  source_seq 1824  segment 18
  images/00000345.jpg  vs  images/00001824.jpg

This pair offers 242 Lowe-ratio ORB matches and admits NEITHER a
homography NOR a fundamental matrix -- a repetitive-indoor-texture false
match set. The failed fit is the trigger; a pair that fits cleanly never
shows the behaviour.

WHAT TO LOOK FOR
  A binary mask has unique values within {0, 1} and sum <= n.
  Anything else is the bug. The DECISIVE question the lead asked is
  whether the sum VARIES across repeated identical calls -- that is what
  separates uninitialised memory from a deterministic-but-wrong result.

Run:  python scripts/research/slam_classical/repro_ransac_mask.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]
sys.path.insert(0, str(TOWER_ROOT))

import cv2
import numpy as np

from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import (LOWE_RATIO, detect_and_describe,
                                          homography_ratio, match_descriptors)

SESS = (TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
        / 'sessions/dd5d13a2381e430db9b27c7da2cf2928')
A_REL, B_REL = 'images/00000345.jpg', 'images/00001824.jpg'
TRIALS = 50


def describe(name, arr):
    return (f"{name}: dtype={arr.dtype} shape={arr.shape} "
            f"C_CONTIGUOUS={arr.flags['C_CONTIGUOUS']} "
            f"OWNDATA={arr.flags['OWNDATA']}")


def mask_report(mask):
    if mask is None:
        return "mask=None"
    u = np.unique(mask)
    return (f"dtype={mask.dtype} shape={mask.shape} "
            f"unique[:8]={u[:8].tolist()} n_unique={len(u)} "
            f"sum={int(mask.sum())} nonzero={int((mask.ravel() > 0).sum())}")


def main():
    print(f"cv2 {cv2.__version__}   numpy {np.__version__}")
    print(f"opencv build: "
          f"{[l for l in cv2.getBuildInformation().splitlines() if 'Version control' in l]}")
    print()

    ga = decode_gray((SESS / A_REL).read_bytes())
    gb = decode_gray((SESS / B_REL).read_bytes())
    ka, da = detect_and_describe(ga)
    kb, db = detect_and_describe(gb)
    print(f"keyframe A images/00000345.jpg : {len(ka)} ORB features")
    print(f"keyframe B images/00001824.jpg : {len(kb)} ORB features")

    # EXACTLY the production path: geometry.match_descriptors returns
    # np.float32([...]).reshape(-1, 2), which is what geometry.py:120-123
    # then hands to findHomography / findFundamentalMat.
    pa, pb = match_descriptors(ka, da, kb, db, ratio=LOWE_RATIO)
    print(f"\n--- ITEM 2: exact input dtype/shape at the call site ---")
    print("  " + describe("points_a", pa))
    print("  " + describe("points_b", pb))
    print(f"  n_matches = {len(pa)}")

    print(f"\n--- ITEM 3+4: {TRIALS} repeated calls on the SAME input ---")
    print("  (identical arrays, no re-detection, no re-matching between trials)")
    h_sums, f_sums, h_models, f_models, nonbinary = [], [], [], [], 0
    first_bad = None
    for t in range(TRIALS):
        H, hmask = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
        F, fmask = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)
        h_models.append(H is not None)
        f_models.append(F is not None)
        for label, model, mask in (("H", H, hmask), ("F", F, fmask)):
            if mask is None:
                continue
            u = np.unique(mask)
            if not set(u.tolist()) <= {0, 1} or int(mask.sum()) > len(pa):
                nonbinary += 1
                if first_bad is None:
                    first_bad = (t, label, model is not None, mask_report(mask))
        h_sums.append(int(hmask.sum()) if hmask is not None else -1)
        f_sums.append(int(fmask.sum()) if fmask is not None else -1)
        if t < 8:
            print(f"  trial {t}: H_model={'OK ' if H is not None else 'None'} "
                  f"{mask_report(hmask)}")
            print(f"           F_model={'OK ' if F is not None else 'None'} "
                  f"{mask_report(fmask)}")

    print(f"\n  H model returned None in {TRIALS - sum(h_models)}/{TRIALS} trials")
    print(f"  F model returned None in {TRIALS - sum(f_models)}/{TRIALS} trials")
    print(f"  distinct H mask sums across {TRIALS} identical calls: "
          f"{sorted(Counter(h_sums).items())}")
    print(f"  distinct F mask sums across {TRIALS} identical calls: "
          f"{sorted(Counter(f_sums).items())}")
    print(f"  trials producing a NON-BINARY mask or sum > n: {nonbinary}")
    if first_bad:
        print(f"  first non-binary observation: trial={first_bad[0]} "
              f"call={first_bad[1]} model_ok={first_bad[2]}")
        print(f"    {first_bad[3]}")

    varies = len(set(h_sums)) > 1 or len(set(f_sums)) > 1
    print(f"\n  >>> SUM VARIES ACROSS IDENTICAL CALLS: "
          f"{'YES -- non-deterministic' if varies else 'NO -- deterministic'}")

    print(f"\n--- ITEM 2b: does the INPUT LAYOUT change the behaviour? ---")
    variants = {
        "float32 (N,2) contiguous  [production path]": pa.copy(),
        "float32 (N,1,2)": pa.reshape(-1, 1, 2).copy(),
        "float64 (N,2)": pa.astype(np.float64),
        "float32 (N,2) NON-contiguous (strided view)":
            np.repeat(pa, 2, axis=0)[::2],
    }
    vb = {
        "float32 (N,2) contiguous  [production path]": pb.copy(),
        "float32 (N,1,2)": pb.reshape(-1, 1, 2).copy(),
        "float64 (N,2)": pb.astype(np.float64),
        "float32 (N,2) NON-contiguous (strided view)":
            np.repeat(pb, 2, axis=0)[::2],
    }
    for name, arr in variants.items():
        sums, bad = [], 0
        for _ in range(20):
            F, fmask = cv2.findFundamentalMat(arr, vb[name], cv2.FM_RANSAC, 3.0, 0.99)
            if fmask is not None:
                sums.append(int(fmask.sum()))
                u = np.unique(fmask)
                if not set(u.tolist()) <= {0, 1} or int(fmask.sum()) > len(arr):
                    bad += 1
        print(f"  {name:<46} sums={sorted(set(sums))} non_binary={bad}/20")

    print(f"\n--- ITEM 1/5: the SHIPPED function, {TRIALS} calls, same input ---")
    vals = [homography_ratio(pa, pb) for _ in range(TRIALS)]
    c = Counter('None' if v is None else round(v, 4) for v in vals)
    print(f"  geometry.homography_ratio() -> {sorted(c.items(), key=str)}")
    print(f"  distinct outcomes: {len(c)}  "
          f"({'NON-DETERMINISTIC' if len(c) > 1 else 'deterministic'})")

    print(f"\n--- CONTROL: a HEALTHY pair should be clean and stable ---")
    kc, dc = detect_and_describe(decode_gray((SESS / 'images/00000353.jpg').read_bytes()))
    pca, pcb = match_descriptors(ka, da, kc, dc, ratio=LOWE_RATIO)
    print(f"  images/00000345.jpg vs images/00000353.jpg: {len(pca)} matches")
    cs = []
    for _ in range(TRIALS):
        F, fm = cv2.findFundamentalMat(pca, pcb, cv2.FM_RANSAC, 3.0, 0.99)
        cs.append((F is not None, int(fm.sum()) if fm is not None else -1))
    print(f"  distinct (model_ok, sum) outcomes: {sorted(set(cs))}")
    print(f"  shipped homography_ratio() distinct outcomes: "
          f"{len(set(homography_ratio(pca, pcb) for _ in range(TRIALS)))}")


if __name__ == '__main__':
    main()
