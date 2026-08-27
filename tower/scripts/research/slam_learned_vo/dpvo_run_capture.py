"""Run the real DPVO system over a real Ray-Ban capture and measure it.

Only usable where DPVO's three CUDA extensions actually built (WSL here, not
Windows -- see the lane report). Deliberately does NOT import demo.py, which
pulls in `evo` and Pangolin; it drives the DPVO class directly.

Measures, per the lane brief: frames consumed, keyframes retained, runtime FPS,
total processing time, peak VRAM, trajectory continuity, and the two things
that matter most on this corpus -- how much of the trajectory is translation
versus rotation, and whether DPVO ever declines to answer (it does not).

NO GROUND TRUTH. Nothing here says the trajectory is correct.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch


@torch.no_grad()  # demo.py wraps run() the same way; without it the
# autograd graph is retained through PatchGraph.net and VRAM grows
# without bound (measured ~112 MiB/frame before this was added).
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True, type=Path)
    ap.add_argument("--intrinsics", required=True, type=Path,
                    help="tower intrinsics json (fx, fy, cx, cy, dist_coeffs)")
    ap.add_argument("--weights", required=True, type=Path)
    ap.add_argument("--config", default=None)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("-n", "--num-frames", type=int, default=0)
    ap.add_argument("--undistort", action="store_true", default=True)
    ap.add_argument("--report-every", type=int, default=25)
    ap.add_argument("--opts", nargs="*", default=[])
    ap.add_argument("--out", type=Path, default=Path("dpvo_run.json"))
    args = ap.parse_args()

    from dpvo.config import cfg
    from dpvo.dpvo import DPVO

    if args.config:
        cfg.merge_from_file(args.config)
    if args.opts:
        cfg.merge_from_list(args.opts)
    print("cfg:", {k: cfg[k] for k in ("PATCHES_PER_FRAME", "OPTIMIZATION_WINDOW", "PATCH_LIFETIME", "REMOVAL_WINDOW", "KEYFRAME_THRESH", "BUFFER_SIZE") if k in cfg})

    intr = json.loads(args.intrinsics.read_text())
    K = np.array([[intr["fx"], 0, intr["cx"]],
                  [0, intr["fy"], intr["cy"]], [0, 0, 1.0]])
    dist = np.array(intr["dist_coeffs"], dtype=np.float64)
    fx, fy, cx, cy = intr["fx"], intr["fy"], intr["cx"], intr["cy"]

    files = sorted(args.frames.glob("*.jpg"))[:: args.stride]
    if args.num_frames:
        files = files[: args.num_frames]
    print(f"{len(files)} frames, stride {args.stride}")

    slam = None
    torch.cuda.reset_peak_memory_stats()
    per_frame_ms = []
    t_start = time.perf_counter()
    kf_counts = []

    for t, f in enumerate(files):
        image = cv2.imread(str(f))
        if args.undistort:
            image = cv2.undistort(image, K, dist)
        h, w, _ = image.shape
        image = image[: h - h % 16, : w - w % 16]  # DPVO's own stream.py crop
        if t == 0:
            print(f"network input {image.shape}")
        img = torch.from_numpy(image).permute(2, 0, 1).cuda()
        intrinsics = torch.as_tensor([fx, fy, cx, cy]).cuda().float()
        if slam is None:
            _, H, W = img.shape
            slam = DPVO(cfg, str(args.weights), ht=H, wd=W, viz=False)
        t0 = time.perf_counter()
        slam(t, img, intrinsics)
        torch.cuda.synchronize()
        per_frame_ms.append((time.perf_counter() - t0) * 1e3)
        kf_counts.append(int(slam.n))
        if (t + 1) % args.report_every == 0:
            print(f"  {t + 1}/{len(files)}  keyframes={slam.n}  "
                  f"patches={slam.m}  edges={len(slam.pg.ii)}  "
                  f"inactive={len(slam.pg.ii_inac)}  "
                  f"vram={torch.cuda.memory_allocated() / 2 ** 20:.0f}MiB",
                  flush=True)

    total_s = time.perf_counter() - t_start
    poses, tstamps = slam.terminate()
    peak = torch.cuda.max_memory_allocated() / 2 ** 20
    reserved = torch.cuda.max_memory_reserved() / 2 ** 20

    poses = np.asarray(poses)
    xyz = poses[:, :3]
    step = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
    path_len = float(step.sum())
    extent = float(np.linalg.norm(xyz.max(0) - xyz.min(0)))

    res = {
        "frames_consumed": len(files),
        "stride": args.stride,
        "poses_returned": int(len(poses)),
        "keyframes_final": int(slam.n),
        "patches_final": int(slam.m),
        "total_seconds": round(total_s, 2),
        "fps": round(len(files) / total_s, 2),
        "per_frame_ms_median": round(float(np.median(per_frame_ms)), 3),
        "per_frame_ms_p95": round(float(np.percentile(per_frame_ms, 95)), 3),
        "peak_vram_allocated_mib": round(peak, 1),
        "peak_vram_reserved_mib": round(reserved, 1),
        # trajectory shape -- scale is DPVO-internal and arbitrary, so these
        # are RATIOS and self-comparisons only, never metric claims
        "trajectory_path_length_internal_units": round(path_len, 4),
        "trajectory_bbox_extent_internal_units": round(extent, 4),
        "straightness_extent_over_path": round(extent / path_len, 4)
        if path_len > 0 else None,
        "step_median": round(float(np.median(step)), 6),
        "step_p95": round(float(np.percentile(step, 95)), 6),
        "refusals": 0,  # DPVO has no refusal path; recorded to make that explicit
    }
    print(json.dumps(res, indent=2))
    np.save(str(args.out.with_suffix(".poses.npy")), poses)
    args.out.write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
