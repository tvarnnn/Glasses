"""How far does DUSt3R's pairwise + global-alignment pipeline scale on 12 GB?

Runs the real thing at N = 3, 5, 8, 12, 16... keyframes with a COMPLETE
symmetrized scene graph -- which is what DUSt3R's own demo defaults to and
what the paper's global aligner assumes -- and records pairs, inference time,
alignment time and peak VRAM, until it OOMs or a wall-clock budget is hit.
"""
from __future__ import annotations
import argparse, gc, json, os, sys, time
from pathlib import Path

import numpy as np
import torch

SCRATCH = Path(os.environ["D3R_SCRATCH"])
sys.path.insert(0, str(SCRATCH / "pylibs"))
sys.path.insert(0, str(SCRATCH / "thirdparty/dust3r"))
inf = float("inf")

from dust3r.model import AsymmetricCroCo3DStereo  # noqa: E402,F401
from dust3r.inference import inference  # noqa: E402
from dust3r.image_pairs import make_pairs  # noqa: E402
from dust3r.utils.image import load_images  # noqa: E402
from dust3r.cloud_opt import global_aligner, GlobalAlignerMode  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
WORLD = ROOT / "data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4"
IMAGES = WORLD / "sessions/dd5d13a2381e430db9b27c7da2cf2928/images"
INTR = json.load(open(ROOT / "data/world_builder/intrinsics/360x640.json"))


def build_model(ckpt_path, device):
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    a = ck["args"].model.replace("ManyAR_PatchEmbed", "PatchEmbedDust3R")
    a = a[:-1] + ", landscape_only=False)" if "landscape_only" not in a else \
        a.replace(" ", "").replace("landscape_only=True", "landscape_only=False")
    net = eval(a)
    net.load_state_dict(ck["model"], strict=False)
    return net.to(device).eval()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sizes", default="3,5,8,12,16,20,24")
    ap.add_argument("--niter", type=int, default=100)
    ap.add_argument("--budget-s", type=float, default=1800)
    a = ap.parse_args()

    device = "cuda"
    model = build_model(a.ckpt, device)
    frames = sorted(IMAGES.glob("*.jpg"))
    total_free = torch.cuda.get_device_properties(0).total_memory / 2**20
    print("device total VRAM {:.0f} MiB".format(total_free))
    expect_f = 0.5 * (INTR["fx"] + INTR["fy"]) * 0.8

    rows = []
    t_start = time.time()
    for n in [int(x) for x in a.sizes.split(",")]:
        sel = [str(frames[i]) for i in np.linspace(0, len(frames) - 1, n).astype(int)]
        gc.collect(); torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
        row = {"n_images": n}
        try:
            imgs = load_images(sel, size=512, verbose=False)
            pairs = make_pairs(imgs, scene_graph="complete", prefilter=None, symmetrize=True)
            row["n_pairs"] = len(pairs)
            t0 = time.time()
            out = inference(pairs, model, device, batch_size=1, verbose=False)
            torch.cuda.synchronize()
            row["inference_s"] = time.time() - t0
            row["vram_after_inference_mib"] = torch.cuda.max_memory_allocated() / 2**20
            t0 = time.time()
            scene = global_aligner(out, device=device, mode=GlobalAlignerMode.PointCloudOptimizer)
            loss = scene.compute_global_alignment(init="mst", niter=a.niter, schedule="cosine", lr=0.01)
            torch.cuda.synchronize()
            row["align_s"] = time.time() - t0
            row["align_loss"] = float(loss)
            row["vram_peak_mib"] = torch.cuda.max_memory_allocated() / 2**20
            f = scene.get_focals().detach().cpu().numpy().ravel()
            row["focals_px"] = [float(x) for x in f]
            row["focal_median_px"] = float(np.median(f))
            row["focal_expected_px"] = expect_f
            row["focal_median_err_pct"] = 100 * (float(np.median(f)) - expect_f) / expect_f
            del scene, out
        except torch.cuda.OutOfMemoryError as e:
            row["oom"] = True
            row["error"] = str(e)[:300]
            row["vram_peak_mib"] = torch.cuda.max_memory_allocated() / 2**20
        except Exception as e:
            row["error"] = type(e).__name__ + ": " + str(e)[:300]
            row["vram_peak_mib"] = torch.cuda.max_memory_allocated() / 2**20
        rows.append(row)
        print(json.dumps(row)[:400], flush=True)
        gc.collect(); torch.cuda.empty_cache()
        if row.get("oom") or (time.time() - t_start) > a.budget_s:
            print("stopping: oom={} elapsed={:.0f}s".format(row.get("oom"), time.time() - t_start))
            break
    Path(a.out).write_text(json.dumps(rows, indent=1))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
