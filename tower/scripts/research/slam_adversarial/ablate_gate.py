"""ADVERSARIAL: decompose WHY production scores 0.0% on the pure-rotation null.

The synthesis credits "the cheirality-ratio gate". But production differs from
Lane 2's transcription in THREE ways at once. Ablate them independently:

    RANSAC method   : cv2.RANSAC  vs  cv2.USAC_MAGSAC
    inlier set used : epipolar mask  vs  recoverPose-narrowed cheirality mask

2 x 2 = 4 criteria over the SAME 200 zero-baseline pairs and the SAME real
keyframe pairs, so the credit can be assigned.

Read-only. No production code modified.
"""
from __future__ import annotations
import json, statistics as st, sys
from collections import Counter
from pathlib import Path
import cv2, numpy as np

HERE = Path(__file__).resolve().parent
TOWER = HERE.parents[2]
sys.path.insert(0, str(TOWER))
from tower.world_builder.geometry import (  # noqa: E402
    MIN_INLIERS, MIN_INLIER_RATIO, MIN_TRIANGULATION_ANGLE_DEG,
    RANSAC_CONFIDENCE, RANSAC_THRESHOLD_PX,
    detect_and_describe, match_descriptors, median_triangulation_angle_deg,
)


def verdict(pa, pb, K, method, use_cheirality):
    if len(pa) < 8:
        return "no_correspondence"
    E, mask = cv2.findEssentialMat(pa, pb, K, method=method,
                                   prob=RANSAC_CONFIDENCE,
                                   threshold=RANSAC_THRESHOLD_PX)
    if E is None or E.shape != (3, 3) or mask is None:
        return "no_essential"
    epi = mask.copy()
    _, R, t, _ = cv2.recoverPose(E, pa, pb, K, mask=mask)
    kept = (mask.ravel() > 0) if use_cheirality else (epi.ravel() > 0)
    inl = int(kept.sum())
    if inl < MIN_INLIERS:
        return "few_inliers"
    if inl / len(pa) < MIN_INLIER_RATIO:
        return "low_ratio"
    tri = median_triangulation_angle_deg(pa[kept], pb[kept], R,
                                         np.asarray(t, np.float64).reshape(3), K)
    if tri is None:
        return "no_triangulation"
    if tri < MIN_TRIANGULATION_ANGLE_DEG:
        return "low_parallax"
    return "solvable"


COMBOS = [("RANSAC+epipolar", cv2.RANSAC, False),
          ("RANSAC+cheirality", cv2.RANSAC, True),
          ("MAGSAC+epipolar", cv2.USAC_MAGSAC, False),
          ("MAGSAC+cheirality (PRODUCTION)", cv2.USAC_MAGSAC, True)]


def run(pairs, K, label):
    tally = {c[0]: Counter() for c in COMBOS}
    for i, (ga, gb) in enumerate(pairs):
        ka, da = detect_and_describe(ga)
        kb, db = detect_and_describe(gb)
        pa, pb = match_descriptors(ka, da, kb, db)
        for name, m, ch in COMBOS:
            tally[name][verdict(pa, pb, K, m, ch)] += 1
        if (i + 1) % 50 == 0:
            print(f"  {label} {i+1}/{len(pairs)}", flush=True)
    n = len(pairs)
    print(f"\n--- {label}: n={n} ---")
    for name, _, _ in COMBOS:
        s = tally[name]["solvable"]
        print(f"{name:32s} solvable {s:4d}/{n} = {100*s/n:5.1f}%   {dict(tally[name])}")
    return tally


def main():
    scratch = json.loads((TOWER / "scripts/research/slam_synthesis/paths.json").read_text())["scratch"]
    intr = json.loads((TOWER / "data/world_builder/intrinsics/360x640.json").read_text())
    K = np.array([[intr["fx"], 0, intr["cx"]], [0, intr["fy"], intr["cy"]], [0, 0, 1.0]])

    manifest = json.loads(Path(scratch + "/manifest_purerot_null.json").read_text())
    nulls = [(cv2.imread(j["a"], cv2.IMREAD_GRAYSCALE),
              cv2.imread(j["b"], cv2.IMREAD_GRAYSCALE)) for j in manifest]
    run(nulls, K, "PURE-ROTATION NULL (true t = 0, any solvable is FALSE)")

    # real consecutive keyframe pairs from the HEAD replay
    root = Path(sys.argv[1])
    w = next((root / "worlds").iterdir())
    sess = next((w / "sessions").iterdir())
    kfs = sorted((sess / "images").glob("*.jpg"))
    print(f"\n{len(kfs)} keyframe images")
    real = []
    for gap in (1,):
        for i in range(0, len(kfs) - gap):
            real.append((cv2.imread(str(kfs[i]), cv2.IMREAD_GRAYSCALE),
                         cv2.imread(str(kfs[i + gap]), cv2.IMREAD_GRAYSCALE)))
    run(real, K, "REAL consecutive keyframe pairs (gap 1)")


main()
