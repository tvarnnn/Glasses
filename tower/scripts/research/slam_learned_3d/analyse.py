"""Post-process the MASt3R / DUSt3R pair runs into the report's tables.

Recomputes reciprocity correctly from the stored R,t (recoverPose returns the
transform cam1 -> cam2, so the reverse pass must satisfy t_fwd = -R_fwd @ t_rev,
not -R_fwd.T @ t_rev), and asks the only question that matters for loop
closure: does ANY statistic separate same-place pairs from different-place
pairs?
"""
from __future__ import annotations
import json, sys
from pathlib import Path

import numpy as np


def rot_angle_deg(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))


def recip(fwd, rev):
    if "R" not in fwd or "R" not in rev:
        return None, None
    Rf, Rr = np.array(fwd["R"]), np.array(rev["R"])
    tf, tr = np.array(fwd["t"]), np.array(rev["t"])
    dR = rot_angle_deg(Rf @ Rr)
    pred = -Rf @ tr
    nf, npd = np.linalg.norm(tf), np.linalg.norm(pred)
    if nf < 1e-9 or npd < 1e-9:
        return dR, None
    return dR, float(np.degrees(np.arccos(np.clip(float(tf @ pred) / (nf * npd), -1, 1))))


rows = json.load(open(sys.argv[1]))
print("{:<11} {:<12} {:>5} {:>6} {:>6} {:>5} {:>7} {:>7} {:>7} {:>7} {:>6} {:>6} {:>7}".format(
    "kind", "pair", "orb", "match", "Einl", "rat", "f_fwd", "f_err%", "recipR", "recipT",
    "conf1", "conf2", "depth_m"))
agg = {}
for r in rows:
    f, v = r["fwd"], r["rev"]
    dR, dT = recip(f, v)
    r["recip_rot_deg_fixed"] = dR
    r["recip_trans_dir_deg_fixed"] = dT
    print("{:<11} {:<12} {:>5} {:>6d} {:>6d} {:>5.2f} {:>7.1f} {:>+7.1f} {:>7} {:>7} "
          "{:>6.2f} {:>6.2f} {:>7.2f}".format(
              r["kind"], r["name"], str(r["orb_inliers"]), f["n_matches"], f["E_inliers"],
              f["E_inlier_ratio"], f["focal_px"], r["focal_err_pct"][0],
              "n/a" if dR is None else "{:.2f}".format(dR),
              "n/a" if dT is None else "{:.2f}".format(dT),
              f["mean_conf1"], f["mean_conf2"], f["metric_median_depth_m"]))
    agg.setdefault(r["kind"], []).append(r)

print()
print("--- group summary (medians) ---")
hdr = ["kind", "n", "orb_inl", "m3r_match", "E_inl", "E_ratio", "focal_err%",
       "recipR_deg", "recipT_deg", "conf2", "depth_m"]
print(("{:<11}" + "{:>11}" * (len(hdr) - 1)).format(*hdr))
for k, rs in agg.items():
    def med(fn):
        v = [fn(r) for r in rs]
        v = [x for x in v if x is not None and not (isinstance(x, float) and np.isnan(x))]
        return float(np.median(v)) if v else float("nan")
    print(("{:<11}" + "{:>11d}" + "{:>11.1f}" * 9).format(
        k, len(rs),
        med(lambda r: r["orb_inliers"]),
        med(lambda r: r["fwd"]["n_matches"]),
        med(lambda r: r["fwd"]["E_inliers"]),
        med(lambda r: r["fwd"]["E_inlier_ratio"]),
        med(lambda r: r["focal_err_pct"][0]),
        med(lambda r: r["recip_rot_deg_fixed"]),
        med(lambda r: r["recip_trans_dir_deg_fixed"]),
        med(lambda r: r["fwd"]["mean_conf2"]),
        med(lambda r: r["fwd"]["metric_median_depth_m"])))

# --- separability: same place vs different place --------------------------
POS = {"oracle", "blind"}
NEG = {"neg_insess", "neg_xcap"}
pos = [r for r in rows if r["kind"] in POS]
neg = [r for r in rows if r["kind"] in NEG]
if pos and neg:
    print()
    print("--- discriminator: same-place ({}) vs different-place ({}) ---".format(len(pos), len(neg)))
    stats = {
        "mast3r_matches": lambda r: r["fwd"]["n_matches"],
        "E_inliers": lambda r: r["fwd"]["E_inliers"],
        "E_inlier_ratio": lambda r: r["fwd"]["E_inlier_ratio"],
        "mean_conf2": lambda r: r["fwd"]["mean_conf2"],
        "frac_conf2_gt3": lambda r: r["fwd"]["frac_conf2_gt3"],
        "focal_abs_err_pct": lambda r: abs(r["focal_err_pct"][0]),
        "recip_rot_deg": lambda r: r["recip_rot_deg_fixed"],
        "recip_trans_dir_deg": lambda r: r["recip_trans_dir_deg_fixed"],
        "orb_inliers": lambda r: r["orb_inliers"],
    }
    print("{:<22} {:>12} {:>12} {:>10} {:>12}".format(
        "statistic", "pos median", "neg median", "AUC", "sep(perfect?)"))
    for name, fn in stats.items():
        p = [fn(r) for r in pos]
        q = [fn(r) for r in neg]
        p = [x for x in p if x is not None and not (isinstance(x, float) and np.isnan(x))]
        q = [x for x in q if x is not None and not (isinstance(x, float) and np.isnan(x))]
        if not p or not q:
            continue
        # Mann-Whitney AUC
        wins = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in p for b in q)
        auc = wins / (len(p) * len(q))
        perfect = "YES" if (min(p) > max(q) or max(p) < min(q)) else "no"
        print("{:<22} {:>12.3f} {:>12.3f} {:>10.3f} {:>12}".format(
            name, float(np.median(p)), float(np.median(q)), auc, perfect))

Path(sys.argv[2]).write_text(json.dumps(rows, indent=1))
print("\nwrote", sys.argv[2])
