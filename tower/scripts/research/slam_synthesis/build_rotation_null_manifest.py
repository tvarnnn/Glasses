"""THE DECISIVE EXPERIMENT for Tension 1 — pair builder.

Lane 3 proposed a validity gate for cross-segment links:

    accept iff  recip_R < 15 deg  AND  E_inlier_ratio > 0.5

where recip_R is the disagreement between two INDEPENDENT MASt3R forward
passes, (A,B) and (B,A), on the RELATIVE ROTATION.

Lane 2 independently showed, on synthetic pure-rotation pairs built from real
frames, that under zero baseline every matcher recovers ROTATION to within
0.036-0.214 deg and FABRICATES TRANSLATION. Lane 2 never ran that null against
Lane 3's system; Lane 3's negative controls were different-PLACE pairs, which
test a different failure mode entirely.

So: does Lane 3's gate accept a pair whose true translation is EXACTLY ZERO?
If it does, the gate is structurally blind to the failure mode that would
silently corrupt a map, and cross-segment registration built on it would place
fabricated baselines into the world.

This script builds the pairs. It reproduces Lane 2's rotation_null.py
construction EXACTLY (same capture, same seed, same sharpness ranking, same
angles, same q85 re-JPEG) but writes the pair to disk in the manifest format
that Lane 3's mast3r_pairs.py / dust3r_pairs.py already consume, so the two
lanes' systems are compared on bit-identical inputs.

Construction:
  * real Ray-Ban frame, undistorted with the genuine ChArUco calibration
    (pinhole_radtan, rms 0.2893 px) -> image A, written LOSSLESSLY as PNG so
    it carries exactly the original JPEG's artefacts and no more
  * B = warpPerspective(A, K R K^-1), re-encoded at JPEG q85 and decoded, then
    written as PNG. Pure rotation about the camera centre: true translation is
    EXACTLY 0, true triangulation angle is EXACTLY 0, and every pixel of
    texture, sensor noise and compression artefact is real.
  * angle 0.0 is included as a second, stronger null: A vs A. Zero rotation AND
    zero translation.

RESEARCH ONLY. Writes to a scratch directory outside the repo. Reads the
corpus read-only. Touches no production code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]
sys.path.insert(0, str(TOWER_ROOT))

from tower.world_builder.frontend import decode_gray  # noqa: E402


def rotation_matrix(yaw_deg, pitch_deg, roll_deg):
    """Identical to slam_learned_vo/rotation_null.py."""
    ry, rp, rr = np.radians([yaw_deg, pitch_deg, roll_deg])
    Ry = np.array([[np.cos(ry), 0, np.sin(ry)], [0, 1, 0],
                   [-np.sin(ry), 0, np.cos(ry)]])
    Rp = np.array([[1, 0, 0], [0, np.cos(rp), -np.sin(rp)],
                   [0, np.sin(rp), np.cos(rp)]])
    Rr = np.array([[np.cos(rr), -np.sin(rr), 0], [np.sin(rr), np.cos(rr), 0],
                   [0, 0, 1]])
    return Ry @ Rp @ Rr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", default="22e9d4289cb440fbb3f14e6da369a136")
    ap.add_argument("--intrinsics",
                    default="data/world_builder/intrinsics/360x640.json")
    ap.add_argument("-n", "--num-frames", type=int, default=40)
    ap.add_argument("--angles", default="0.0,0.5,1.2,2.5,5.0")
    ap.add_argument("--jpeg-quality", type=int, default=85)
    ap.add_argument("--seed", type=int, default=20260826)
    ap.add_argument("--imgdir", required=True,
                    help="scratch dir for the generated PNG pairs")
    ap.add_argument("--out", required=True, help="manifest json path")
    args = ap.parse_args()

    intr = json.loads((TOWER_ROOT / args.intrinsics).read_text())
    K = np.array([[intr["fx"], 0, intr["cx"]],
                  [0, intr["fy"], intr["cy"]], [0, 0, 1.0]])
    dist = np.array(intr["dist_coeffs"], dtype=np.float64)
    print("calibration", intr.get("model"), "rms", intr.get("reprojection_rms_px"))

    frames_dir = TOWER_ROOT / "data/captures" / args.capture / "frames"
    files = sorted(frames_dir.glob("*.jpg"))
    if not files:
        raise SystemExit("no frames at " + str(frames_dir))

    # EXACTLY Lane 2's selection: same seed, same 400-frame sample, same rank.
    rng = np.random.default_rng(args.seed)
    sample = rng.choice(len(files), size=min(len(files), 400), replace=False)
    scored = []
    for i in sample:
        g = decode_gray(files[i].read_bytes())
        scored.append((cv2.Laplacian(g, cv2.CV_64F).var(), int(i)))
    scored.sort(reverse=True)
    chosen = [files[i] for _, i in scored[: args.num_frames]]
    print(f"{len(chosen)} sharpest of {len(sample)} sampled; sharpness "
          f"{scored[args.num_frames - 1][0]:.0f} .. {scored[0][0]:.0f}")

    imgdir = Path(args.imgdir)
    imgdir.mkdir(parents=True, exist_ok=True)
    angles = [float(a) for a in args.angles.split(",")]

    jobs = []
    for f in chosen:
        # Colour, because MASt3R/DUSt3R consume RGB. Undistort with the real
        # calibration, keeping K, exactly as dust3r_pairs.undistorted() does.
        bgr = cv2.imread(str(f), cv2.IMREAD_COLOR)
        und = cv2.undistort(bgr, K, dist, None, K)
        pa = imgdir / f"{f.stem}_A.png"
        cv2.imwrite(str(pa), und)
        for ang in angles:
            R = rotation_matrix(ang * 0.8, ang * 0.5, ang * 0.2)
            H = K @ R @ np.linalg.inv(K)
            warped = cv2.warpPerspective(und, H, (und.shape[1], und.shape[0]),
                                         flags=cv2.INTER_LINEAR)
            ok, buf = cv2.imencode(".jpg", warped,
                                   [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
            if ok:
                warped = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            pb = imgdir / f"{f.stem}_B{ang:g}.png"
            cv2.imwrite(str(pb), warped)
            jobs.append({
                "kind": f"purerot_null_{ang:g}",
                "name": f"{f.stem}@{ang:g}deg",
                "a": str(pa), "b": str(pb),
                "orb_inliers": None,
                "true_rotation_deg": ang,
                "true_translation": 0.0,
                "true_triangulation_angle_deg": 0.0,
            })
        print(".", end="", flush=True)
    print()
    Path(args.out).write_text(json.dumps(jobs, indent=1))
    print(f"wrote {len(jobs)} pairs -> {args.out}")


if __name__ == "__main__":
    main()
