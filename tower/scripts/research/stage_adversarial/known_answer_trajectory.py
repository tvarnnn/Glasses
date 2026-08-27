#!/usr/bin/env python
"""KNOWN-ANSWER test: does EXTEND_REFERENCE_DEPTH=3 help or hurt the
trajectory, measured against GROUND TRUTH?

WHY THIS IS THE DECIDING INSTRUMENT

Every number produced on the pinned corpus is ground-truth-free. Solved
poses, point counts and multiplicity are all self-reported by the same
pipeline whose quality is in question, so a metric can improve while the
reconstruction gets worse. `tests/synthetic_scene.py` renders from KNOWN
camera poses, which makes trajectory error directly measurable.

WHAT IS MEASURED

  ATE  -- absolute trajectory error of the camera CENTRES after the best
          similarity alignment (umeyama). A monocular reconstruction is
          correct only up to a similarity, so aligning first is required;
          what survives alignment is real shape error, INCLUDING scale
          drift, which a single global scale cannot absorb.

  scale drift -- the per-step ratio (estimated step length / true step
          length), reported as a coefficient of variation. A perfectly
          scale-consistent trajectory has CV 0 no matter what its global
          scale is. This is the quantity the corpus argument about
          "87.03 units versus 8.77 units" was actually reaching for and
          could not measure without ground truth.

CONVENTION, AND WHY IT IS SPELLED OUT

The backend returns OpenCV's (R, t), which map a WORLD point into the
CAMERA frame. The camera CENTRE is -R.T @ t. engine._pose_row does this
conversion for persisted output and the comment there records that an
earlier version shipped the raw t and mirrored every camera through the
origin. Comparing raw t against ss.CameraPose.position would reproduce
that bug inside the measurement, so the conversion is done here.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))

from tests import synthetic_scene as ss  # noqa: E402
from tower.world_builder.backend import KeyframeInput  # noqa: E402
from tower.world_builder.backends import classical as classical_module  # noqa: E402
from tower.world_builder.backends.classical import (  # noqa: E402
    ClassicalTwoViewBackend,
)
from tower.world_builder.records import CameraIntrinsics  # noqa: E402
from tower.world_builder.schema import (  # noqa: E402
    INTRINSICS_SOURCE_SELF_CALIBRATED,
    POSE_STATUS_SOLVED,
)

WIDTH, HEIGHT = 480, 360


def make_intrinsics(K):
    return CameraIntrinsics(
        source=INTRINSICS_SOURCE_SELF_CALIBRATED,
        model="pinhole",
        fx=float(K[0, 0]), fy=float(K[1, 1]),
        cx=float(K[0, 2]), cy=float(K[1, 2]),
        calibrated_width=WIDTH, calibrated_height=HEIGHT,
    )


def build_window(scene, poses, K):
    grays = [
        cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for img in ss.render_sequence(scene, poses, K, WIDTH, HEIGHT)
    ]
    return [
        KeyframeInput(keyframe_id=f"kf{i:04d}", image_gray=g)
        for i, g in enumerate(grays)
    ]


def solve(window, intrinsics, depth, count_guided=False):
    """Run estimate_window at a given depth, optionally counting how many
    guided associations the mechanism admitted."""
    original = classical_module.EXTEND_REFERENCE_DEPTH
    stats = {"guided_admitted": 0, "guided_calls": 0}
    real = ClassicalTwoViewBackend._reobserve_against_pose
    try:
        classical_module.EXTEND_REFERENCE_DEPTH = depth
        if count_guided:
            def counting(self, *a, **kw):
                out = real(self, *a, **kw)
                stats["guided_calls"] += 1
                stats["guided_admitted"] += len(out)
                return out
            ClassicalTwoViewBackend._reobserve_against_pose = counting
        backend = ClassicalTwoViewBackend()
        backend.prepare(intrinsics)
        return backend.estimate_window(window), stats
    finally:
        classical_module.EXTEND_REFERENCE_DEPTH = original
        ClassicalTwoViewBackend._reobserve_against_pose = real


def centres(estimate):
    """Camera centres in the reconstruction's own gauge, by index.

    The anchor keyframe carries no rotation: it IS the world origin by
    construction (POSE_CONVENTION world_axes_origin =
    first_keyframe_camera), so its centre is exactly the origin.
    """
    out = {}
    for index, pose in enumerate(estimate.poses):
        if pose.status == POSE_STATUS_SOLVED and pose.rotation is not None:
            R = np.asarray(pose.rotation, dtype=np.float64)
            t = np.asarray(pose.translation, dtype=np.float64).reshape(3)
            out[index] = -R.T @ t
        elif pose.rotation is None and pose.status not in ("unavailable",):
            out[index] = np.zeros(3)
    return out


def evaluate(estimate, gt_positions):
    got = centres(estimate)
    shared = sorted(i for i in got if i < len(gt_positions))
    if len(shared) < 3:
        return {"solved_cameras": len(shared), "measurable": False,
                "reason": "fewer than 3 cameras to align"}

    est = np.array([got[i] for i in shared], dtype=np.float64)
    gt = np.array([gt_positions[i] for i in shared], dtype=np.float64)

    scale, R, t = ss.umeyama_similarity(est, gt)
    aligned = (scale * (R @ est.T).T) + t
    residual = np.linalg.norm(aligned - gt, axis=1)

    gt_path = float(np.linalg.norm(np.diff(gt, axis=0), axis=1).sum())
    est_path = float(np.linalg.norm(np.diff(est, axis=0), axis=1).sum())

    # Per-step scale ratio between CONSECUTIVE solved cameras only, so a
    # gap in the chain does not masquerade as a long step.
    ratios = []
    for a, b in zip(shared, shared[1:]):
        if b - a != 1:
            continue
        d_est = float(np.linalg.norm(got[b] - got[a]))
        d_gt = float(np.linalg.norm(gt_positions[b] - gt_positions[a]))
        if d_gt > 1e-9:
            ratios.append(d_est / d_gt)
    ratios = np.array(ratios, dtype=np.float64)

    return {
        "measurable": True,
        "solved_cameras": len(shared),
        "ate_rms": float(np.sqrt((residual ** 2).mean())),
        "ate_max": float(residual.max()),
        # Scale-free: error as a fraction of how far the camera actually
        # travelled. This is the number comparable ACROSS motions.
        "ate_rms_over_gt_path": float(
            np.sqrt((residual ** 2).mean()) / gt_path
        ) if gt_path > 0 else None,
        "gt_path_length": gt_path,
        "est_path_length_own_gauge": est_path,
        "umeyama_scale": float(scale),
        "step_ratio_mean": float(ratios.mean()) if len(ratios) else None,
        "step_ratio_cv": (
            float(ratios.std() / ratios.mean())
            if len(ratios) and ratios.mean() > 0 else None
        ),
        "step_ratio_min": float(ratios.min()) if len(ratios) else None,
        "step_ratio_max": float(ratios.max()) if len(ratios) else None,
        "steps_compared": int(len(ratios)),
        "points": int(estimate.points.xyz.shape[0]),
        "support_rows": int(estimate.points.support_views.shape[0]),
    }


MOTIONS = {
    "strafe_14_s0.05": lambda: ss.strafe(14, step=0.05),
    "strafe_20_s0.10": lambda: ss.strafe(20, step=0.10),
    "strafe_30_s0.05": lambda: ss.strafe(30, step=0.05),
    "forward_20_s0.10": lambda: ss.forward_walk(20, step=0.10),
    "forward_30_s0.05": lambda: ss.forward_walk(30, step=0.05),
    "pure_rotation_14": lambda: ss.pure_rotation(14, degrees_per_step=2.0),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--seeds", type=int, nargs="*", default=[1234, 7, 99])
    args = ap.parse_args()

    assert "Glasses-world-builder" in classical_module.__file__.replace(
        "\\", "/"
    ), f"WRONG MODULE {classical_module.__file__}"

    K = ss.camera_matrix(WIDTH, HEIGHT)
    intrinsics = make_intrinsics(K)
    results = []

    for seed in args.seeds:
        scene = ss.furnished_room(seed=seed)
        for name, maker in MOTIONS.items():
            poses = maker()
            gt = [np.asarray(p.position, dtype=np.float64) for p in poses]
            window = build_window(scene, poses, K)
            row = {"seed": seed, "motion": name}
            for depth in (1, 3):
                est, stats = solve(window, intrinsics, depth,
                                   count_guided=True)
                row[f"d{depth}"] = evaluate(est, gt)
                row[f"d{depth}"]["guided_admitted"] = stats["guided_admitted"]
            results.append(row)
            d1, d3 = row["d1"], row["d3"]
            if d1.get("measurable") and d3.get("measurable"):
                print(
                    f"seed={seed:5d} {name:18s} "
                    f"cams {d1['solved_cameras']:3d}->{d3['solved_cameras']:3d}  "
                    f"ATE/path {d1['ate_rms_over_gt_path']:.4f}->"
                    f"{d3['ate_rms_over_gt_path']:.4f}  "
                    f"stepCV {d1['step_ratio_cv']:.3f}->{d3['step_ratio_cv']:.3f}  "
                    f"pts {d1['points']}->{d3['points']}  "
                    f"guided {d3['guided_admitted']}",
                    flush=True,
                )
            else:
                print(
                    f"seed={seed:5d} {name:18s} NOT MEASURABLE  "
                    f"d1={d1.get('reason', d1.get('solved_cameras'))} "
                    f"d3={d3.get('reason', d3.get('solved_cameras'))}  "
                    f"guided d3={d3.get('guided_admitted')}",
                    flush=True,
                )

    # Verdict across the measurable rows.
    better = worse = same = 0
    for row in results:
        d1, d3 = row["d1"], row["d3"]
        if not (d1.get("measurable") and d3.get("measurable")):
            continue
        a, b = d1["ate_rms_over_gt_path"], d3["ate_rms_over_gt_path"]
        if b < a * 0.99:
            better += 1
        elif b > a * 1.01:
            worse += 1
        else:
            same += 1
    print(f"\nATE/path  DEPTH=3 better {better}  same {same}  worse {worse}")

    if args.out:
        Path(args.out).write_text(
            json.dumps({"results": results,
                        "ate_verdict": {"better": better, "same": same,
                                        "worse": worse}}, indent=2),
            encoding="utf-8",
        )
        print(f"wrote {args.out}")


if __name__ == "__main__":
    raise SystemExit(main())
