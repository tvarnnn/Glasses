"""Price the DPVO front end on real Ray-Ban frames, without its CUDA extensions.

The full DPVO system cannot be built on this host (nvcc 11.8 vs torch cu13.2;
see the lane report). But DPVO's *network* is only 3.53 M parameters and the
part that touches every pixel -- the Patchifier, two BasicEncoder4 towers --
is plain PyTorch. Only `altcorr.patchify` (a gather) and `fastba` (the DBA
solve) are CUDA extensions.

So we load the REAL released `dpvo.pth` weights into the REAL extractor source
and run it on REAL frames at the resolution DPVO would actually see, with a
pure-torch `grid_sample` standing in for `altcorr.patchify`. That prices the
per-frame front-end cost and its VRAM honestly. It does NOT price the update
operator's correlation lookups or the bundle adjustment, and the report says so.

Usage:
  python dpvo_frontend_cost.py --dpvo <path to DPVO clone> --frames <dir> -n 200
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

DIM = 384
PATCH = 3


def load_extractor_module(dpvo_root: Path):
    """Import DPVO's extractor.py by path; it only imports torch."""
    path = dpvo_root / "dpvo" / "extractor.py"
    spec = importlib.util.spec_from_file_location("dpvo_extractor", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dpvo_extractor"] = mod
    spec.loader.exec_module(mod)
    return mod


def patchify_grid_sample(fmap: torch.Tensor, coords: torch.Tensor, radius: int):
    """Pure-torch stand-in for dpvo.altcorr.patchify.

    fmap:   (C, H, W) feature map for one frame
    coords: (N, 2) patch centres in feature-map pixels
    returns (N, C, 2r+1, 2r+1)
    """
    c, h, w = fmap.shape
    n = coords.shape[0]
    d = 2 * radius + 1
    dy, dx = torch.meshgrid(
        torch.arange(-radius, radius + 1, device=fmap.device, dtype=torch.float32),
        torch.arange(-radius, radius + 1, device=fmap.device, dtype=torch.float32),
        indexing="ij",
    )
    grid = coords.view(n, 1, 1, 2) + torch.stack([dx, dy], dim=-1).view(1, d, d, 2)
    grid = grid.view(1, n * d, d, 2)
    gx = 2.0 * grid[..., 0] / max(w - 1, 1) - 1.0
    gy = 2.0 * grid[..., 1] / max(h - 1, 1) - 1.0
    g = torch.stack([gx, gy], dim=-1)
    out = F.grid_sample(fmap.unsqueeze(0), g, mode="nearest", align_corners=True)
    return out.view(c, n, d, d).permute(1, 0, 2, 3).contiguous()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpvo", required=True, type=Path)
    ap.add_argument("--frames", required=True, type=Path)
    ap.add_argument("-n", "--num-frames", type=int, default=200)
    ap.add_argument("--patches", type=int, default=96)
    ap.add_argument("--amp", action="store_true", help="mixed precision, DPVO's default")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    import cv2

    ext = load_extractor_module(args.dpvo)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    fnet = ext.BasicEncoder4(output_dim=128, norm_fn="instance").to(dev).eval()
    inet = ext.BasicEncoder4(output_dim=DIM, norm_fn="none").to(dev).eval()

    sd = torch.load(args.dpvo / "dpvo.pth", map_location="cpu", weights_only=True)
    fnet_sd = {
        k[len("module.patchify.fnet.") :]: v
        for k, v in sd.items()
        if k.startswith("module.patchify.fnet.")
    }
    inet_sd = {
        k[len("module.patchify.inet.") :]: v
        for k, v in sd.items()
        if k.startswith("module.patchify.inet.")
    }
    missing_f = fnet.load_state_dict(fnet_sd, strict=True)
    missing_i = inet.load_state_dict(inet_sd, strict=True)
    print(f"loaded fnet {len(fnet_sd)} tensors, inet {len(inet_sd)} tensors")
    print(f"  fnet params {sum(p.numel() for p in fnet.parameters()):,}")
    print(f"  inet params {sum(p.numel() for p in inet.parameters()):,}")

    files = sorted(args.frames.glob("*.jpg"))[: args.num_frames]
    if not files:
        print("no frames", file=sys.stderr)
        return 2
    print(f"{len(files)} frames from {args.frames}")

    torch.cuda.reset_peak_memory_stats() if dev == "cuda" else None
    decode_ms, net_ms, patch_ms = [], [], []
    shape_reported = None

    with torch.no_grad():
        for i, f in enumerate(files):
            t0 = time.perf_counter()
            bgr = cv2.imread(str(f))
            h, w, _ = bgr.shape
            bgr = bgr[: h - h % 16, : w - w % 16]  # DPVO's own stream.py crop
            t1 = time.perf_counter()

            img = torch.from_numpy(bgr).permute(2, 0, 1).to(dev).float()
            img = img[None, None]  # (b=1, n=1, c, h, w)
            img = 2 * (img / 255.0) - 0.5
            if shape_reported is None:
                shape_reported = tuple(img.shape[-2:])
                print(f"network input HxW = {shape_reported} (after DPVO %16 crop)")

            if dev == "cuda":
                torch.cuda.synchronize()
            t2 = time.perf_counter()
            with torch.autocast("cuda", enabled=args.amp and dev == "cuda"):
                fmap = fnet(img) / 4.0
                imap = inet(img) / 4.0
            if dev == "cuda":
                torch.cuda.synchronize()
            t3 = time.perf_counter()

            b, n, c, fh, fw = fmap.shape
            if i == 0:
                print(f"feature map {c}x{fh}x{fw} (fnet), {imap.shape[2]}x{fh}x{fw} (inet)")
            xs = torch.randint(1, fw - 1, (args.patches,), device=dev).float()
            ys = torch.randint(1, fh - 1, (args.patches,), device=dev).float()
            coords = torch.stack([xs, ys], dim=-1)
            gmap = patchify_grid_sample(fmap[0, 0].float(), coords, PATCH // 2)
            ipatch = patchify_grid_sample(imap[0, 0].float(), coords, 0)
            if dev == "cuda":
                torch.cuda.synchronize()
            t4 = time.perf_counter()

            if i >= 5:  # warmup
                decode_ms.append((t1 - t0) * 1e3)
                net_ms.append((t3 - t2) * 1e3)
                patch_ms.append((t4 - t3) * 1e3)

    def stats(xs):
        return {
            "median": round(statistics.median(xs), 3),
            "mean": round(statistics.fmean(xs), 3),
            "p95": round(sorted(xs)[int(0.95 * len(xs))], 3),
        }

    peak = torch.cuda.max_memory_allocated() / 2**20 if dev == "cuda" else 0.0
    reserved = torch.cuda.max_memory_reserved() / 2**20 if dev == "cuda" else 0.0
    total_ms = statistics.median(net_ms) + statistics.median(patch_ms)
    result = {
        "device": torch.cuda.get_device_name(0) if dev == "cuda" else "cpu",
        "amp": bool(args.amp),
        "frames_timed": len(net_ms),
        "input_hw": list(shape_reported),
        "feature_hw": [fh, fw],
        "patches_per_frame": args.patches,
        "jpeg_decode_ms": stats(decode_ms),
        "encoder_ms": stats(net_ms),
        "patchify_gridsample_ms": stats(patch_ms),
        "frontend_median_ms": round(total_ms, 3),
        "frontend_max_fps": round(1000.0 / total_ms, 1),
        "peak_vram_allocated_mib": round(peak, 1),
        "peak_vram_reserved_mib": round(reserved, 1),
    }
    print(json.dumps(result, indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
