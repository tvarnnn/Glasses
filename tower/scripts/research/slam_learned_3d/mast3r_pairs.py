"""MASt3R pairwise inference + reciprocal dense matching on real Ray-Ban keyframes.

RESEARCH HARNESS. Third-party MASt3R (CC BY-NC-SA 4.0, non-commercial) is
imported from OUTSIDE the repo tree. Nothing here may ship.

Per image pair, with NO ground truth available, this measures:
  * reciprocal-NN match count, and how many survive a MAGSAC essential-matrix
    fit under OUR REAL calibrated K -- directly comparable to the ORB inlier
    counts the production backend computes
  * focal estimated from MASt3R's own pointmap vs the ChArUco focal
  * metric median scene depth (MASt3R's metric head claims real-world scale)
  * relative rotation from the two INDEPENDENT passes -> reciprocity
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

import numpy as np
import torch

SCRATCH = Path(os.environ["D3R_SCRATCH"])
sys.path.insert(0, str(SCRATCH / "pylibs"))
sys.path.insert(0, str(SCRATCH / "thirdparty/mast3r"))
sys.path.insert(0, str(SCRATCH / "thirdparty/mast3r/dust3r"))

import cv2  # noqa: E402
from mast3r.model import AsymmetricMASt3R  # noqa: E402
from mast3r.fast_nn import fast_reciprocal_NNs  # noqa: E402
import mast3r.utils.path_to_dust3r  # noqa: E402,F401
from dust3r.inference import inference  # noqa: E402
from dust3r.utils.image import load_images  # noqa: E402
from dust3r.post_process import estimate_focal_knowing_depth  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
INTR = json.load(open(ROOT / "data/world_builder/intrinsics/360x640.json"))
NAN = float("nan")
inf = float("inf")


def build_model(ckpt_path, device):
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    args = ck["args"].model
    if "landscape_only" not in args:
        args = args[:-1] + ", landscape_only=False)"
    else:
        args = args.replace(" ", "").replace("landscape_only=True", "landscape_only=False")
    net = eval(args)
    print("  state_dict:", net.load_state_dict(ck["model"], strict=False))
    return net.to(device).eval()


def rot_angle_deg(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))


def scaled_K(W, H):
    """Our ChArUco K, mapped into DUSt3R's 288x512 canvas.

    load_images() resizes 360x640 by the LONG edge to 512 with no crop, so the
    map is a pure isotropic scale of 512/640 = 0.8.
    """
    s = H / 640.0
    return np.float64([[INTR["fx"] * s, 0, INTR["cx"] * s],
                       [0, INTR["fy"] * s, INTR["cy"] * s], [0, 0, 1]]), s


def one_pass(model, device, ia, ib, conf_thr=3.0):
    out = inference([tuple([ia, ib])], model, device, batch_size=1, verbose=False)
    v1, p1 = out["view1"], out["pred1"]
    v2, p2 = out["view2"], out["pred2"]
    d1 = p1["desc"].squeeze(0).detach()
    d2 = p2["desc"].squeeze(0).detach()
    m0, m1 = fast_reciprocal_NNs(d1, d2, subsample_or_initxy1=8, device=device,
                                 dist="dot", block_size=2**13)
    H0, W0 = (int(x) for x in v1["true_shape"][0])
    H1, W1 = (int(x) for x in v2["true_shape"][0])
    ok = ((m0[:, 0] >= 3) & (m0[:, 0] < W0 - 3) & (m0[:, 1] >= 3) & (m0[:, 1] < H0 - 3) &
          (m1[:, 0] >= 3) & (m1[:, 0] < W1 - 3) & (m1[:, 1] >= 3) & (m1[:, 1] < H1 - 3))
    m0, m1 = m0[ok], m1[ok]

    pts1 = p1["pts3d"].squeeze(0).cpu().numpy()
    c1 = p1["conf"].squeeze(0).cpu().numpy()
    c2 = p2["conf"].squeeze(0).cpu().numpy()
    pp1 = torch.tensor((W0 / 2.0, H0 / 2.0))
    focal = float(estimate_focal_knowing_depth(
        torch.from_numpy(pts1)[None], pp1, focal_mode="weiszfeld"))

    res = {
        "n_matches": int(len(m0)),
        "focal_px": focal,
        "metric_median_depth_m": float(np.median(pts1[..., 2])),
        "metric_p10_depth_m": float(np.percentile(pts1[..., 2], 10)),
        "metric_p90_depth_m": float(np.percentile(pts1[..., 2], 90)),
        "mean_conf1": float(c1.mean()), "mean_conf2": float(c2.mean()),
        "frac_conf1_gt3": float((c1 > conf_thr).mean()),
        "frac_conf2_gt3": float((c2 > conf_thr).mean()),
        "shape": [H0, W0],
    }

    # geometric verification with OUR calibrated K, backend thresholds
    K, s = scaled_K(W0, H0)
    res["K_scale"] = s
    if len(m0) >= 15:
        pa = m0.astype(np.float64)
        pb = m1.astype(np.float64)
        E, mask = cv2.findEssentialMat(pa, pb, K, method=cv2.USAC_MAGSAC,
                                       prob=0.999, threshold=1.0)
        if E is not None and mask is not None and E.shape == (3, 3):
            res["E_inliers"] = int(mask.sum())
            res["E_inlier_ratio"] = float(mask.mean())
            n, R, t, m2 = cv2.recoverPose(E, pa, pb, K, mask=mask.copy())
            res["recoverPose_cheirality"] = int(n)
            res["R"] = R.tolist()
            res["t"] = t.ravel().tolist()
            # median parallax of inliers, in px on the 512-canvas
            inl = mask.ravel().astype(bool)
            res["median_parallax_px"] = float(np.median(
                np.linalg.norm(pa[inl] - pb[inl], axis=1))) if inl.sum() else None
        else:
            res["E_inliers"] = 0
            res["E_inlier_ratio"] = 0.0
    else:
        res["E_inliers"] = 0
        res["E_inlier_ratio"] = 0.0
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    device = "cuda"
    model = build_model(a.ckpt, device)
    jobs = json.load(open(a.manifest))
    expect_f = 0.5 * (INTR["fx"] + INTR["fy"]) * 0.8
    print("expected focal on the 288x512 canvas: {:.2f} px".format(expect_f))

    results = []
    for k, job in enumerate(jobs):
        imgs = load_images([job["a"], job["b"]], size=512, verbose=False)
        torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        fwd = one_pass(model, device, imgs[0], imgs[1])
        rev = one_pass(model, device, imgs[1], imgs[0])
        torch.cuda.synchronize()
        dt = time.time() - t0
        r = {"name": job["name"], "kind": job["kind"], "a": job["a"], "b": job["b"],
             "orb_inliers": job.get("orb_inliers"), "fwd": fwd, "rev": rev,
             "runtime_s": dt, "vram_peak_mib": torch.cuda.max_memory_allocated() / 2**20,
             "focal_expected_px": expect_f}
        r["focal_err_pct"] = [100 * (fwd["focal_px"] - expect_f) / expect_f,
                              100 * (rev["focal_px"] - expect_f) / expect_f]
        if "R" in fwd and "R" in rev:
            r["recip_rot_deg"] = rot_angle_deg(np.array(fwd["R"]) @ np.array(rev["R"]))
            tf = np.array(fwd["t"])
            pred = -np.array(fwd["R"]).T @ np.array(rev["t"])
            # recoverPose returns R,t mapping cam1 -> cam2; reciprocity on direction
            nf, np_ = np.linalg.norm(tf), np.linalg.norm(pred)
            if nf > 1e-9 and np_ > 1e-9:
                r["recip_trans_dir_deg"] = float(np.degrees(np.arccos(
                    np.clip(float(tf @ pred) / (nf * np_), -1, 1))))
        r["metric_depth_ratio_fwd_rev"] = (fwd["metric_median_depth_m"] /
                                           max(1e-9, rev["metric_median_depth_m"]))
        results.append(r)
        print("[{}/{}] {:10s} {:24s} orb={:>4} m3r_match={:5d} E_inl={:5d} ({:.2f}) "
              "f=({:.1f},{:.1f}) err=({:+.1f}%,{:+.1f}%) recipR={:6.2f} recipT={:6.2f} "
              "depth=({:.2f},{:.2f})m conf=({:.2f},{:.2f}) {:.1f}s {:.0f}MiB".format(
                  k + 1, len(jobs), job["kind"], job["name"],
                  str(job.get("orb_inliers")), fwd["n_matches"], fwd["E_inliers"],
                  fwd["E_inlier_ratio"], fwd["focal_px"], rev["focal_px"],
                  r["focal_err_pct"][0], r["focal_err_pct"][1],
                  r.get("recip_rot_deg", NAN), r.get("recip_trans_dir_deg", NAN),
                  fwd["metric_median_depth_m"], rev["metric_median_depth_m"],
                  fwd["mean_conf1"], fwd["mean_conf2"], dt, r["vram_peak_mib"]), flush=True)
    Path(a.out).write_text(json.dumps(results, indent=1))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
