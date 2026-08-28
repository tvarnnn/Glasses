"""The null experiment: does a stronger matcher INVENT parallax under pure rotation?

matcher_showdown.py finds that LoFTR turns 75 of ORB's 116 baseline-limited
pairs into "solvable", and lifts the median triangulation angle from 0.282 deg
to 1.181 deg on the same images. Two stories explain that and they have
opposite consequences:

  H1  The baseline was really there. ORB's ~1 px keypoint noise on a
      near-degenerate pair biases the essential matrix toward pure rotation
      and shrinks the apparent triangulation angle. A subpixel, dense matcher
      resolves the real parallax. -> a learned front end BUYS us geometry.

  H2  The baseline was never there. With 1466 correspondences instead of 205,
      RANSAC finds a spurious essential matrix on a rotation-dominant pair and
      the triangulation angle inflates because the pose is wrong. -> a learned
      front end buys us CONFIDENT WRONG POSES, which is worse than a refusal.

Real footage cannot separate these: we have no ground-truth motion. So build a
case where the answer is known by construction.

  Take a real Ray-Ban frame. Undistort it with the real ChArUco calibration,
  putting it in the exact pinhole model the pipeline assumes. Warp it by
  H = K R K^-1 for a known rotation R. That is a PURE ROTATION about the
  camera centre: the true translation is EXACTLY ZERO, the true triangulation
  angle is EXACTLY ZERO, and every pixel of texture, noise and JPEG artefact
  is real.

Any "solvable" verdict on such a pair is a FALSE POSITIVE, full stop. The
false-positive rate of MIN_TRIANGULATION_ANGLE_DEG under each matcher is the
number that decides between H1 and H2.

Controls included:
  * re-JPEG the warped image at the corpus's own quality, so the warped view
    carries compression artefacts like a real second frame
  * an optional synthetic translation arm (--translate), which checks the test
    has power: a matcher that calls everything unsolvable would also score 0%
    false positives.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]
sys.path.insert(0, str(TOWER_ROOT))

from matcher_showdown import build_matcher, klass, verdict  # noqa: E402

from tower.world_builder.frontend import decode_gray  # noqa: E402


def rotation_matrix(yaw_deg, pitch_deg, roll_deg):
    ry = np.radians(yaw_deg)
    rp = np.radians(pitch_deg)
    rr = np.radians(roll_deg)
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
    ap.add_argument("--matchers", default="orb,loftr,disk_lg")
    ap.add_argument("-n", "--num-frames", type=int, default=60)
    ap.add_argument("--angles", default="0.5,1.2,2.5,5.0",
                    help="pure-rotation magnitudes in degrees")
    ap.add_argument("--jpeg-quality", type=int, default=85)
    ap.add_argument("--seed", type=int, default=20260826)
    ap.add_argument("--out", type=Path, default=HERE / "rotation_null.json")
    args = ap.parse_args()

    intr = json.loads((TOWER_ROOT / args.intrinsics).read_text())
    K = np.array([[intr["fx"], 0, intr["cx"]],
                  [0, intr["fy"], intr["cy"]], [0, 0, 1.0]])
    dist = np.array(intr["dist_coeffs"], dtype=np.float64)
    print("calibration", intr.get("model"), "rms",
          intr.get("reprojection_rms_px"))

    frames_dir = TOWER_ROOT / "data/captures" / args.capture / "frames"
    files = sorted(frames_dir.glob("*.jpg"))
    if not files:
        raise SystemExit("no frames at " + str(frames_dir))

    # Prefer sharp frames: a blurred source would confound "matcher invents
    # parallax" with "matcher cannot match at all".
    rng = np.random.default_rng(args.seed)
    sample = rng.choice(len(files), size=min(len(files), 400), replace=False)
    scored = []
    for i in sample:
        g = decode_gray(files[i].read_bytes())
        scored.append((cv2.Laplacian(g, cv2.CV_64F).var(), int(i)))
    scored.sort(reverse=True)
    chosen = [files[i] for _, i in scored[: args.num_frames]]
    print(f"{len(chosen)} sharpest of {len(sample)} sampled frames; "
          f"sharpness range {scored[args.num_frames - 1][0]:.0f} .. "
          f"{scored[0][0]:.0f}")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    built = {n.strip(): build_matcher(n.strip(), dev)
             for n in args.matchers.split(",")}

    angles = [float(a) for a in args.angles.split(",")]
    rows = []
    for f in chosen:
        g = decode_gray(f.read_bytes())
        und = cv2.undistort(g, K, dist)
        for ang in angles:
            # split the rotation over yaw/pitch/roll so the warp is not a pure
            # image-plane translation, which would be a weaker test
            R = rotation_matrix(ang * 0.8, ang * 0.5, ang * 0.2)
            H = K @ R @ np.linalg.inv(K)
            warped = cv2.warpPerspective(und, H, (und.shape[1], und.shape[0]),
                                         flags=cv2.INTER_LINEAR)
            ok, buf = cv2.imencode(".jpg", warped,
                                   [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
            if ok:
                warped = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
            row = {"frame": f.name, "angle_deg": ang,
                   "true_translation": 0.0, "true_tri_deg": 0.0}
            for name, m in built.items():
                pa, pb, _ = m(und, warped)
                r = verdict(np.ascontiguousarray(pa),
                            np.ascontiguousarray(pb), K)
                # how well did it recover the rotation it was actually given?
                r["rot_err_deg"] = (None if r["rot_deg"] is None
                                    else round(abs(r["rot_deg"] - ang), 4))
                row[name] = r
            rows.append(row)
        print(".", end="", flush=True)
    print()

    args.out.write_text(json.dumps({"rows": rows}, indent=1))
    print("wrote " + str(args.out))

    print("\n=== PURE-ROTATION NULL: true triangulation angle is EXACTLY 0 ===")
    print(f"{len(chosen)} real frames x {len(angles)} rotations "
          f"= {len(rows)} pairs, undistorted with the real ChArUco calibration")
    for name in built:
        print(f"\n-- {name} --")
        for ang in angles:
            sel = [r for r in rows if r["angle_deg"] == ang]
            c = Counter(klass(r[name]["verdict"]) for r in sel)
            fp = c.get("solvable", 0)
            tri = [r[name]["tri"] for r in sel if r[name]["tri"] is not None]
            rerr = [r[name]["rot_err_deg"] for r in sel
                    if r[name]["rot_err_deg"] is not None]
            line = (f"   rot {ang:>4.1f} deg  FALSE 'solvable' "
                    f"{fp:>3}/{len(sel)} ({100 * fp / len(sel):>5.1f}%)")
            if tri:
                line += (f"   median est. tri {statistics.median(tri):.3f} deg"
                         f"  p90 {sorted(tri)[int(0.9 * len(tri)) - 1]:.3f}")
            if rerr:
                line += f"   median |rot err| {statistics.median(rerr):.3f} deg"
            print(line)
        allsel = rows
        c = Counter(klass(r[name]["verdict"]) for r in allsel)
        print(f"   OVERALL false-positive rate "
              f"{c.get('solvable', 0)}/{len(allsel)} "
              f"({100 * c.get('solvable', 0) / len(allsel):.1f}%)   "
              f"other verdicts: {dict(c)}")


if __name__ == "__main__":
    main()
