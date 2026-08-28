"""DUSt3R pairwise inference on real Ray-Ban keyframes.

RESEARCH HARNESS -- reads corpus, writes JSON to a caller-given path.
Third-party code (DUSt3R, CC BY-NC-SA 4.0) lives OUTSIDE the repo tree and is
imported by path. Nothing here is production code and nothing here may ship.

What it measures, per image pair, with NO ground truth available:
  * focal estimated by DUSt3R from its own pointmap, vs our ChArUco focal
  * relative pose A<-B and B<-A from two INDEPENDENT forward passes
  * reciprocity of those two poses (rotation angle, translation direction)
  * confidence statistics, PnP inlier ratio
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

import numpy as np
import torch

SCRATCH = Path(os.environ["D3R_SCRATCH"])
sys.path.insert(0, str(SCRATCH / "pylibs"))
sys.path.insert(0, str(SCRATCH / "thirdparty/dust3r"))

import cv2  # noqa: E402
from dust3r.model import AsymmetricCroCo3DStereo  # noqa: E402,F401
from dust3r.inference import inference  # noqa: E402
from dust3r.image_pairs import make_pairs  # noqa: E402
from dust3r.utils.image import load_images  # noqa: E402
from dust3r.post_process import estimate_focal_knowing_depth  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
INTR = json.load(open(ROOT / "data/world_builder/intrinsics/360x640.json"))
NAN = float("nan")
inf = float("inf")  # the checkpoint's stored model-args string references `inf`


def build_model(ckpt_path, device):
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    args = ckpt["args"].model.replace("ManyAR_PatchEmbed", "PatchEmbedDust3R")
    if "landscape_only" not in args:
        args = args[:-1] + ", landscape_only=False)"
    else:
        args = args.replace(" ", "").replace("landscape_only=True", "landscape_only=False")
    net = eval(args)
    print("  state_dict:", net.load_state_dict(ckpt["model"], strict=False))
    return net.to(device).eval()


def rot_angle_deg(R):
    c = (np.trace(R) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


MAX_PNP_POINTS = 8000
_RNG = np.random.default_rng(20260826)


def pose_from_pointmap(pts3d_other, focal, pp, conf_other, conf_thr):
    """PnP: 3D points (expressed in view-1 frame) against view-2 pixel grid.

    Subsampled to MAX_PNP_POINTS -- solvePnPRansac on the full 288x512 grid
    (147k points) is minutes per call and adds nothing over a random 8k.
    """
    H, W = pts3d_other.shape[:2]
    pixels = np.mgrid[:W, :H].T.astype(np.float32)
    msk = conf_other > conf_thr
    n_valid = int(msk.sum())
    if n_valid < 100:
        return None, 0.0, n_valid
    P = pts3d_other[msk].astype(np.float32)
    U = pixels[msk].astype(np.float32)
    if len(P) > MAX_PNP_POINTS:
        sel = _RNG.choice(len(P), MAX_PNP_POINTS, replace=False)
        P, U = P[sel], U[sel]
    msk_n = len(P)
    K = np.float32([(focal, 0, pp[0]), (0, focal, pp[1]), (0, 0, 1)])
    ok, rvec, tvec, inliers = cv2.solvePnPRansac(
        P, U, K, None,
        iterationsCount=100, reprojectionError=5, flags=cv2.SOLVEPNP_SQPNP)
    if not ok:
        return None, 0.0, n_valid
    R = cv2.Rodrigues(rvec)[0]
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3:] = tvec
    cam_to_world = np.linalg.inv(T)  # pose of view-2 camera in view-1 frame
    ratio = float(len(inliers) / msk_n) if inliers is not None else 0.0
    return cam_to_world, ratio, n_valid


_UNDIST_CACHE = {}
_UNDIST_DIR = None


def undistorted(path):
    """Undistort with the real ChArUco calibration, keeping the same K.

    DUSt3R assumes a pinhole camera. Our frames carry a measured radtan
    distortion (k1=0.144, k2=-0.928, k3=1.300). Feeding raw frames therefore
    violates the model's own imaging assumption; this isolates that effect.
    """
    global _UNDIST_DIR
    if path in _UNDIST_CACHE:
        return _UNDIST_CACHE[path]
    if _UNDIST_DIR is None:
        _UNDIST_DIR = SCRATCH / "undistorted"
        _UNDIST_DIR.mkdir(exist_ok=True)
    K = np.float64([[INTR["fx"], 0, INTR["cx"]], [0, INTR["fy"], INTR["cy"]], [0, 0, 1]])
    D = np.float64(INTR["dist_coeffs"])
    img = cv2.imread(str(path))
    out = cv2.undistort(img, K, D, None, K)
    dest = _UNDIST_DIR / (str(abs(hash(str(path)))) + "_" + Path(path).name)
    cv2.imwrite(str(dest), out)
    _UNDIST_CACHE[path] = str(dest)
    return str(dest)


def run_pair(model, device, path_a, path_b, conf_thr=3.0, image_size=512, undist=False):
    if undist:
        path_a, path_b = undistorted(path_a), undistorted(path_b)
    imgs = load_images([str(path_a), str(path_b)], size=image_size, verbose=False)
    pairs = make_pairs(imgs, scene_graph="complete", prefilter=None, symmetrize=True)
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    out = inference(pairs, model, device, batch_size=2, verbose=False)
    torch.cuda.synchronize()
    dt = time.time() - t0
    vram = torch.cuda.max_memory_allocated() / 2**20

    res = {"runtime_s": dt, "vram_peak_mib": vram,
           "shape": [int(x) for x in imgs[0]["true_shape"][0]]}
    v1idx = [int(x) for x in out["view1"]["idx"]]
    v2idx = [int(x) for x in out["view2"]["idx"]]
    poses, focals, confs, ratios, npx = {}, {}, {}, {}, {}
    for b in range(len(v1idx)):
        i, j = v1idx[b], v2idx[b]
        p1 = out["pred1"]["pts3d"][b].cpu()                # view i, in frame i
        p2 = out["pred2"]["pts3d_in_other_view"][b].cpu()  # view j, in frame i
        c1 = out["pred1"]["conf"][b].cpu().numpy()
        c2 = out["pred2"]["conf"][b].cpu().numpy()
        H, W = p1.shape[:2]
        pp = torch.tensor((W / 2, H / 2))
        f = float(estimate_focal_knowing_depth(p1[None], pp, focal_mode="weiszfeld"))
        key = str(i) + "_" + str(j)
        focals[key] = f
        confs[key] = {
            "mean_conf1": float(c1.mean()), "mean_conf2": float(c2.mean()),
            "med_conf1": float(np.median(c1)), "med_conf2": float(np.median(c2)),
            "frac_conf1_gt_thr": float((c1 > conf_thr).mean()),
            "frac_conf2_gt_thr": float((c2 > conf_thr).mean()),
        }
        T, ratio, n = pose_from_pointmap(p2.numpy(), f, (W / 2, H / 2), c2, conf_thr)
        poses[key] = None if T is None else T.tolist()
        ratios[key] = ratio
        npx[key] = n
    res.update(focals=focals, conf=confs, pnp_inlier_ratio=ratios, pnp_n_points=npx,
               poses=poses)

    T01 = poses.get("0_1")
    T10 = poses.get("1_0")
    if T01 is not None and T10 is not None:
        A = np.array(T01)  # cam1 pose in frame0
        B = np.array(T10)  # cam0 pose in frame1
        res["recip_rot_deg"] = rot_angle_deg(A[:3, :3] @ B[:3, :3])
        tA = A[:3, 3]
        pred = -A[:3, :3] @ B[:3, 3]
        na, nb = np.linalg.norm(tA), np.linalg.norm(pred)
        if na > 1e-9 and nb > 1e-9:
            cosang = float(np.dot(tA, pred) / (na * nb))
            res["recip_trans_dir_deg"] = float(np.degrees(np.arccos(np.clip(cosang, -1, 1))))
            res["recip_trans_scale_ratio"] = float(nb / na)
        z = out["pred1"]["pts3d"][0][..., 2].cpu().numpy()
        res["baseline_over_depth_0"] = float(na / max(1e-9, float(np.median(np.abs(z)))))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--image-size", type=int, default=512)
    ap.add_argument("--undistort", action="store_true")
    a = ap.parse_args()

    device = "cuda"
    model = build_model(a.ckpt, device)
    jobs = json.load(open(a.manifest))
    scale = a.image_size / 640.0
    expect_f = 0.5 * (INTR["fx"] + INTR["fy"]) * scale
    print("expected focal at long-edge {}: {:.2f} px (calibrated fx={:.3f} fy={:.3f} "
          "at 360x640, scale={})".format(a.image_size, expect_f, INTR["fx"], INTR["fy"], scale))

    results = []
    for k, job in enumerate(jobs):
        pa, pb = Path(job["a"]), Path(job["b"])
        r = run_pair(model, device, pa, pb, image_size=a.image_size, undist=a.undistort)
        r["name"] = job["name"]
        r["kind"] = job["kind"]
        r["a"] = str(pa)
        r["b"] = str(pb)
        r["orb_inliers"] = job.get("orb_inliers")
        f01 = r["focals"].get("0_1")
        f10 = r["focals"].get("1_0")
        r["focal_expected_px"] = expect_f
        r["focal_err_pct"] = [None if f is None else 100 * (f - expect_f) / expect_f
                              for f in (f01, f10)]
        results.append(r)
        print("[{}/{}] {:10s} {:24s} f=({:.1f},{:.1f}) err=({:+.1f}%,{:+.1f}%) "
              "recip_rot={:6.2f} recip_dir={:6.2f} conf2={:.2f} pnp={:.2f} "
              "{:.2f}s {:.0f}MiB".format(
                  k + 1, len(jobs), job["kind"], job["name"], f01, f10,
                  r["focal_err_pct"][0], r["focal_err_pct"][1],
                  r.get("recip_rot_deg", NAN), r.get("recip_trans_dir_deg", NAN),
                  r["conf"]["0_1"]["mean_conf2"], r["pnp_inlier_ratio"]["0_1"],
                  r["runtime_s"], r["vram_peak_mib"]), flush=True)
    Path(a.out).write_text(json.dumps(results, indent=1))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
