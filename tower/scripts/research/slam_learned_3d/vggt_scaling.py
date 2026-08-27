"""VGGT on real Ray-Ban frames: how many frames fit in 12 GB, and does its
estimated focal agree with our ChArUco calibration?

VGGT holds every frame's tokens in one transformer pass with global attention
across frames, so the question "how many frames" is a hard VRAM question, not a
scheduling one. This walks N up until it OOMs and records what it cost.
"""
from __future__ import annotations
import argparse, gc, json, os, sys, time
from pathlib import Path

import numpy as np
import torch

SCRATCH = Path(os.environ["D3R_SCRATCH"])
sys.path.insert(0, str(SCRATCH / "pylibs"))
sys.path.insert(0, str(SCRATCH / "thirdparty/vggt"))

from vggt.models.vggt import VGGT  # noqa: E402
from vggt.utils.load_fn import load_and_preprocess_images  # noqa: E402
from vggt.utils.pose_enc import pose_encoding_to_extri_intri  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
WORLD = ROOT / "data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4"
IMAGES = WORLD / "sessions/dd5d13a2381e430db9b27c7da2cf2928/images"
INTR = json.load(open(ROOT / "data/world_builder/intrinsics/360x640.json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sizes", default="2,4,8,16,24,32,48,64,96,128,192,256")
    a = ap.parse_args()

    device = "cuda"
    dtype = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16
    model = VGGT()
    sd = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    print("  load_state_dict:", model.load_state_dict(sd, strict=False))
    model = model.to(device).eval()
    n_par = sum(p.numel() for p in model.parameters())
    print("params {:.2f} B  dtype {}  total VRAM {:.0f} MiB".format(
        n_par / 1e9, dtype, torch.cuda.get_device_properties(0).total_memory / 2**20))

    frames = sorted(IMAGES.glob("*.jpg"))
    rows = []
    for n in [int(x) for x in a.sizes.split(",")]:
        sel = [str(frames[i]) for i in np.linspace(0, len(frames) - 1, n).astype(int)]
        gc.collect(); torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
        row = {"n_images": n}
        try:
            imgs = load_and_preprocess_images(sel).to(device)
            row["input_shape"] = list(imgs.shape)
            torch.cuda.synchronize(); t0 = time.time()
            with torch.no_grad():
                with torch.autocast("cuda", dtype=dtype):
                    pred = model(imgs)
            torch.cuda.synchronize()
            row["forward_s"] = time.time() - t0
            row["vram_peak_mib"] = torch.cuda.max_memory_allocated() / 2**20
            row["fps"] = n / row["forward_s"]
            extri, intri = pose_encoding_to_extri_intri(
                pred["pose_enc"], imgs.shape[-2:])
            K = intri[0].float().cpu().numpy()
            fx = K[:, 0, 0]; fy = K[:, 1, 1]
            W_in = imgs.shape[-1]
            # VGGT's canvas is a resize of the 360-wide original by W_in/360
            s = W_in / 360.0
            exp_fx = INTR["fx"] * s
            exp_fy = INTR["fy"] * s
            row["vggt_fx_median"] = float(np.median(fx))
            row["vggt_fy_median"] = float(np.median(fy))
            row["expected_fx"] = exp_fx
            row["expected_fy"] = exp_fy
            row["fx_err_pct"] = 100 * (float(np.median(fx)) - exp_fx) / exp_fx
            row["fy_err_pct"] = 100 * (float(np.median(fy)) - exp_fy) / exp_fy
            row["fx_iqr_pct_of_median"] = float(
                100 * (np.percentile(fx, 75) - np.percentile(fx, 25)) / np.median(fx))
            d = pred["depth"][0].float().cpu().numpy()
            row["median_depth"] = float(np.median(d))
            del pred, imgs, extri, intri
        except torch.cuda.OutOfMemoryError as e:
            row["oom"] = True
            row["error"] = str(e)[:250]
            row["vram_peak_mib"] = torch.cuda.max_memory_allocated() / 2**20
        except Exception as e:
            row["error"] = type(e).__name__ + ": " + str(e)[:250]
        rows.append(row)
        print(json.dumps(row)[:500], flush=True)
        gc.collect(); torch.cuda.empty_cache()
        if row.get("oom"):
            break
    Path(a.out).write_text(json.dumps(rows, indent=1))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
