#!/usr/bin/env python
"""Root cause of the ~88 deg seed-pair error on lateral seed=1006.

WHAT IS ALREADY ESTABLISHED (seed1006.py, MEASURED)

Single segment, 4 persisted poses, trajectory internally COHERENT (a
straight line) but oriented ~88 deg away from truth. The camera poses
are identical across seeds -- only the room TEXTURE changes with the
seed -- so this is not a pose-generation artifact.

The world frame is camera 0's frame (POSE_CONVENTION
world_axes_origin: first_keyframe_camera). For this walk camera 0 looks
along world +Z with x_right along world +X, so camera-0 axes coincide
with world axes and the comparison against truth is valid. Seeds 1000
and 1002 recover t ~ [1, 0, 0]: correct. Seed 1006 recovers
t ~ [0.04, -0.04, 1.00]: forward instead of sideways.

THE HYPOTHESIS

Planar degeneracy. `homography_ratio`'s own docstring says a room "is
nothing but planes" and that r_H "saturates at 0.471-0.499 across the
full range from total degeneracy to healthy parallax", so it "classifies
every pair as rotation-dominant and separates nothing" -- and it is
recorded but NOT used as a gate. If seed 1006's seed pair is
plane-dominated, `findEssentialMat` is degenerate, `recoverPose` returns
a confident wrong baseline, and NOTHING in the pipeline is watching.

This measures, for the seed pair of several seeds: r_H, essential-matrix
inlier count and ratio, median parallax, and the recovered translation
direction against truth. If r_H is indistinguishable between the good
and the broken seeds, the detector that exists cannot catch this.
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
)

WIDTH, HEIGHT = 480, 360


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1006,1000,1002,1001,1003")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    K = ss.camera_matrix(WIDTH, HEIGHT)
    poses = ss.strafe(8, step=0.15)
    truth_dir = np.asarray(poses[1].position) - np.asarray(poses[0].position)
    truth_dir = truth_dir / np.linalg.norm(truth_dir)

    rows = []
    for seed in (int(s) for s in args.seeds.split(",")):
        scene = ss.furnished_room(seed=seed)
        imgs = ss.render_sequence(scene, poses[:2], K, WIDTH, HEIGHT)
        grays = [cv2.cvtColor(i, cv2.COLOR_BGR2GRAY) for i in imgs]
        ka, da = detect_and_describe(grays[0])
        kb, db = detect_and_describe(grays[1])
        pa, pb = match_descriptors(ka, da, kb, db)

        r_h = homography_ratio(pa, pb)

        E, mask_e = cv2.findEssentialMat(
            pa, pb, K, method=cv2.USAC_MAGSAC, prob=0.999, threshold=1.0
        )
        e_inliers = int(mask_e.sum()) if mask_e is not None else 0
        n_pose, R, t, _ = (
            cv2.recoverPose(E, pa, pb, K, mask=mask_e.copy())
            if E is not None and E.shape == (3, 3) else (0, None, None, None)
        )
        # Camera-0 frame == world frame for this walk, and recoverPose's t
        # is the direction from camera 0 to camera 1 expressed in camera 0.
        if t is not None:
            direction = np.asarray(t).reshape(3)
            direction = direction / np.linalg.norm(direction)
            err = math.degrees(math.acos(max(-1.0, min(1.0, abs(
                float(np.dot(direction, truth_dir)))))))
        else:
            direction, err = None, None

        # Parallax: median pixel displacement of the matched features.
        parallax = float(np.median(np.linalg.norm(pa - pb, axis=1))) if len(pa) else None

        # How well does a SINGLE homography explain the pair? This is the
        # direct planarity measure r_H is a proxy for.
        H, mask_h = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
        h_inliers = int(mask_h.sum()) if (H is not None and mask_h is not None) else 0

        row = {
            "seed": seed,
            "matches": int(len(pa)),
            "median_parallax_px": None if parallax is None else round(parallax, 3),
            "r_h": None if r_h is None else round(float(r_h), 4),
            "essential_inliers": e_inliers,
            "essential_inlier_ratio": (
                round(e_inliers / len(pa), 4) if len(pa) else None
            ),
            "homography_inliers": h_inliers,
            "homography_inlier_ratio": (
                round(h_inliers / len(pa), 4) if len(pa) else None
            ),
            "recoverpose_cheirality_inliers": int(n_pose),
            "recovered_direction": (
                None if direction is None
                else [round(float(v), 4) for v in direction]
            ),
            "direction_error_deg": None if err is None else round(err, 3),
        }
        rows.append(row)
        print(
            f"seed {seed}: matches {row['matches']:4d}  "
            f"parallax {row['median_parallax_px']:>7}  "
            f"r_h {row['r_h']}  "
            f"E_ratio {row['essential_inlier_ratio']}  "
            f"H_ratio {row['homography_inlier_ratio']}  "
            f"dir {row['recovered_direction']}  "
            f"ERR {row['direction_error_deg']} deg",
            flush=True,
        )

    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
