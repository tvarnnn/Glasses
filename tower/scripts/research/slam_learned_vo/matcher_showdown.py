"""Is the blocker CORRESPONDENCE or BASELINE? Re-asked with learned matchers.

`multi_cue_geometry/blocker_measured.py` asked this with the pipeline's own
ORB + Lowe front end and answered: 10.4% correspondence-limited, 54.7%
baseline-limited. That number decides whether a learned front end -- DPVO's
patch tracker, DROID's dense flow, or a drop-in matcher -- can help us at all.

This re-runs the SAME pairs through the SAME geometric verdict, changing only
the matcher:

  orb        cv2.ORB + Lowe ratio            -- the pipeline's own, as control
  loftr      kornia LoFTR (indoor weights)   -- detector-free dense matching
  disk_lg    kornia DISK + LightGlue         -- learned detector + learned matcher

The verdict pipeline is identical to blocker_measured.py: findEssentialMat with
the production RANSAC constants, MIN_INLIERS, MIN_INLIER_RATIO, recoverPose,
then median_triangulation_angle_deg against MIN_TRIANGULATION_ANGLE_DEG.

NO GROUND TRUTH EXISTS. Every verdict here is a self-consistency verdict:
"would the production degeneracy criterion have accepted this pair". It is not
"is the recovered pose correct".
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]
sys.path.insert(0, str(TOWER_ROOT))

from tower.world_builder.frontend import decode_gray  # noqa: E402
from tower.world_builder.geometry import (  # noqa: E402
    MIN_INLIER_RATIO,
    MIN_INLIERS,
    MIN_TRIANGULATION_ANGLE_DEG,
    RANSAC_CONFIDENCE,
    RANSAC_THRESHOLD_PX,
    detect_and_describe,
    match_descriptors,
    median_triangulation_angle_deg,
    motion_direction,
)

CORRESPONDENCE_VERDICTS = {
    "no_correspondence",
    "no_essential",
    "few_inliers",
    "low_inlier_ratio",
}
BASELINE_VERDICTS = {"low_parallax", "no_triangulation"}


# ---------------------------------------------------------------- matchers


class OrbMatcher:
    name = "orb"

    def __call__(self, ga, gb):
        ka, da = detect_and_describe(ga)
        kb, db = detect_and_describe(gb)
        pa, pb = match_descriptors(ka, da, kb, db)
        return pa, pb, {"kp_a": len(ka), "kp_b": len(kb)}


class LoFTRMatcher:
    name = "loftr"

    def __init__(self, device, conf=0.5):
        import kornia.feature as KF

        self.m = KF.LoFTR(pretrained="indoor").to(device).eval()
        self.device = device
        self.conf = conf

    def _t(self, g):
        x = torch.from_numpy(g).float()[None, None] / 255.0
        h, w = x.shape[-2:]
        x = x[..., : h - h % 8, : w - w % 8]
        return x.to(self.device)

    @torch.no_grad()
    def __call__(self, ga, gb):
        out = self.m({"image0": self._t(ga), "image1": self._t(gb)})
        c = out["confidence"].detach().cpu().numpy()
        keep = c >= self.conf
        pa = out["keypoints0"].detach().cpu().numpy()[keep].astype(np.float32)
        pb = out["keypoints1"].detach().cpu().numpy()[keep].astype(np.float32)
        return pa, pb, {"raw_matches": int(len(c))}


class DiskLightGlueMatcher:
    name = "disk_lg"

    def __init__(self, device, num_features=2048):
        import kornia.feature as KF

        self.disk = KF.DISK.from_pretrained("depth").to(device).eval()
        self.lg = KF.LightGlue("disk").to(device).eval()
        self.device = device
        self.n = num_features

    def _t(self, g):
        """Pad to a multiple of 16 ourselves so LightGlue's normalisation and
        DISK's padding agree on one image size. Padded-region keypoints are
        filtered out after matching."""
        h, w = g.shape
        ph, pw = (-h) % 16, (-w) % 16
        rgb = np.repeat(g[:, :, None], 3, axis=2)
        if ph or pw:
            rgb = np.pad(rgb, ((0, ph), (0, pw), (0, 0)))
        x = torch.from_numpy(rgb).permute(2, 0, 1).float()[None] / 255.0
        return x.to(self.device), (w + pw, h + ph)

    @torch.no_grad()
    def __call__(self, ga, gb):
        ta, sa = self._t(ga)
        tb, sb = self._t(gb)
        fa = self.disk(ta, self.n, window_size=5, score_threshold=0.0)[0]
        fb = self.disk(tb, self.n, window_size=5, score_threshold=0.0)[0]
        wa = torch.tensor(sa, device=self.device).float()[None]
        wb = torch.tensor(sb, device=self.device).float()[None]
        d = {
            "image0": {"keypoints": fa.keypoints[None],
                       "descriptors": fa.descriptors[None], "image_size": wa},
            "image1": {"keypoints": fb.keypoints[None],
                       "descriptors": fb.descriptors[None], "image_size": wb},
        }
        out = self.lg(d)
        idx = out["matches"][0].detach().cpu().numpy()
        info = {"kp_a": int(len(fa.keypoints)), "kp_b": int(len(fb.keypoints))}
        if len(idx) == 0:
            e = np.empty((0, 2), np.float32)
            return e, e, info
        pa = fa.keypoints.detach().cpu().numpy()[idx[:, 0]].astype(np.float32)
        pb = fb.keypoints.detach().cpu().numpy()[idx[:, 1]].astype(np.float32)
        ha, wa_ = ga.shape
        hb, wb_ = gb.shape
        keep = ((pa[:, 0] < wa_) & (pa[:, 1] < ha)
                & (pb[:, 0] < wb_) & (pb[:, 1] < hb))
        return pa[keep], pb[keep], info


def build_matcher(name, device):
    if name == "orb":
        return OrbMatcher()
    if name == "loftr":
        return LoFTRMatcher(device)
    if name == "disk_lg":
        return DiskLightGlueMatcher(device)
    raise SystemExit("unknown matcher " + name)


# ---------------------------------------------------------------- verdict


def verdict(pa, pb, K):
    rec = {"matches": int(len(pa)), "inliers": 0, "ratio": None,
           "tri": None, "tdir": None, "rot_deg": None, "verdict": ""}
    if len(pa) < 8:
        rec["verdict"] = "no_correspondence"
        return rec
    E, mask = cv2.findEssentialMat(
        pa, pb, K, cv2.RANSAC, RANSAC_CONFIDENCE, RANSAC_THRESHOLD_PX
    )
    if E is None or E.shape != (3, 3) or mask is None:
        rec["verdict"] = "no_essential"
        return rec
    rec["inliers"] = int(mask.sum())
    rec["ratio"] = round(rec["inliers"] / len(pa), 4)
    if rec["inliers"] < MIN_INLIERS:
        rec["verdict"] = "few_inliers"
        return rec
    if rec["ratio"] < MIN_INLIER_RATIO:
        rec["verdict"] = "low_inlier_ratio"
        return rec
    m = mask.ravel().astype(bool)
    _, R, t, _ = cv2.recoverPose(E, pa[m], pb[m], K)
    tri = median_triangulation_angle_deg(pa[m], pb[m], R, t, K)
    rec["tri"] = None if tri is None else round(float(tri), 4)
    # Carried so independent matchers can be checked against EACH OTHER:
    # agreement on the translation DIRECTION is evidence the parallax is
    # real; reprojection error is not (a wrong Sim3 reprojects beautifully).
    rec["tdir"] = [round(float(x), 5) for x in motion_direction(R, t)]
    rec["rot_deg"] = round(
        float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1)))), 4
    )
    if tri is None:
        rec["verdict"] = "no_triangulation"
    elif tri < MIN_TRIANGULATION_ANGLE_DEG:
        rec["verdict"] = "low_parallax"
    else:
        rec["verdict"] = "solvable"
    return rec


def klass(v):
    if v in CORRESPONDENCE_VERDICTS:
        return "correspondence"
    if v in BASELINE_VERDICTS:
        return "baseline"
    return "solvable"


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="3dd986b1c2364d4b85de97152f2e39f4")
    ap.add_argument("--session", default="dd5d13a2381e430db9b27c7da2cf2928")
    ap.add_argument("--matchers", default="orb,loftr,disk_lg")
    ap.add_argument("--limit-pairs", type=int, default=0)
    ap.add_argument("--out", type=Path, default=HERE / "matcher_showdown.json")
    args = ap.parse_args()

    world = TOWER_ROOT / "data/world_builder/worlds" / args.world
    sess = world / "sessions" / args.session
    der = world / "derived" / args.session

    intr = json.loads((sess / "session.json").read_text())["intrinsics"]
    K = np.array([[intr["fx"], 0, intr["cx"]],
                  [0, intr["fy"], intr["cy"]],
                  [0, 0, 1.0]])
    print("intrinsics", {k: intr[k] for k in ("fx", "fy", "cx", "cy")})

    kfs = [json.loads(x) for x in (sess / "keyframes.jsonl").read_text().splitlines()
           if x.strip()]
    points = json.loads((der / "points.json").read_text())["points"]
    seg_pts = Counter(p["segment_index"] for p in points)

    by_seg = {}
    for k in kfs:
        by_seg.setdefault(k["segment_index"], []).append(k)

    pairs = []
    for seg, members in sorted(by_seg.items()):
        if len(members) < 2:
            continue
        bucket = "empty" if seg_pts.get(seg, 0) == 0 else "geometry"
        members = sorted(members, key=lambda k: k["source_seq"])
        for a, b in zip(members, members[1:]):
            pairs.append((bucket, seg, a, b))
    if args.limit_pairs:
        pairs = pairs[: args.limit_pairs]
    n_empty = sum(1 for p in pairs if p[0] == "empty")
    print(f"{len(pairs)} consecutive keyframe pairs "
          f"({n_empty} in geometry-less segments)")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    built = {n.strip(): build_matcher(n.strip(), dev)
             for n in args.matchers.split(",")}
    print("matchers:", list(built))

    cache = {}

    def gray(k):
        kid = k["keyframe_id"]
        if kid not in cache:
            cache[kid] = decode_gray((sess / k["image_relpath"]).read_bytes())
        return cache[kid]

    rows = []
    timings = {n: [] for n in built}
    for i, (bucket, seg, a, b) in enumerate(pairs):
        ga, gb = gray(a), gray(b)
        row = {"bucket": bucket, "segment": seg,
               "a": a["keyframe_id"], "b": b["keyframe_id"],
               "gap": b["source_seq"] - a["source_seq"],
               "sharp_a": a.get("sharpness"), "sharp_b": b.get("sharpness")}
        for name, m in built.items():
            t0 = time.perf_counter()
            pa, pb, extra = m(ga, gb)
            if dev == "cuda":
                torch.cuda.synchronize()
            dt = (time.perf_counter() - t0) * 1e3
            timings[name].append(dt)
            r = verdict(np.ascontiguousarray(pa), np.ascontiguousarray(pb), K)
            r.update(extra)
            r["ms"] = round(dt, 2)
            row[name] = r
        rows.append(row)
        if len(cache) > 64:
            cache.clear()
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(pairs)}")

    args.out.write_text(json.dumps({"pairs": rows}, indent=1))
    print("wrote " + str(args.out))

    if dev == "cuda":
        print("\npeak VRAM allocated across all matchers: "
              f"{torch.cuda.max_memory_allocated() / 2**20:.1f} MiB")

    for bucket in ("empty", "geometry"):
        sel = [r for r in rows if r["bucket"] == bucket]
        if not sel:
            continue
        print(f"\n=== segments with {'NO ' if bucket == 'empty' else ''}geometry: "
              f"{len(set(r['segment'] for r in sel))} segments, {len(sel)} pairs ===")
        for name in built:
            c = Counter(r[name]["verdict"] for r in sel)
            kc = Counter(klass(r[name]["verdict"]) for r in sel)
            mm = [r[name]["matches"] for r in sel]
            tri = [r[name]["tri"] for r in sel if r[name]["tri"] is not None]
            print(f"  -- {name} -- median matches {statistics.median(mm):.0f}, "
                  f"median ms {statistics.median(timings[name]):.1f}")
            if tri:
                print(f"     median tri angle {statistics.median(tri):.3f} deg "
                      f"(n={len(tri)})")
            print("     " + "  ".join(f"{k}={v}({100 * v / len(sel):.1f}%)"
                                      for k, v in c.most_common()))
            print("     CLASS: " + "  ".join(
                f"{k}={v} ({100 * v / len(sel):.1f}%)"
                for k, v in sorted(kc.items())))

    sel = [r for r in rows if r["bucket"] == "empty"]
    if sel and "orb" in built:
        for name in built:
            if name == "orb":
                continue
            print(f"\n### CROSS-TAB orb -> {name}, geometry-less segments, "
                  f"n={len(sel)}")
            ct = Counter((klass(r["orb"]["verdict"]), klass(r[name]["verdict"]))
                         for r in sel)
            hdr = "orb \\ " + name
            print(f"{hdr:>22}  {'correspondence':>15} {'baseline':>10} "
                  f"{'solvable':>10}")
            for ok in ("correspondence", "baseline", "solvable"):
                vals = [ct.get((ok, nk), 0)
                        for nk in ("correspondence", "baseline", "solvable")]
                print(f"{ok:>22}  {vals[0]:>15} {vals[1]:>10} {vals[2]:>10}")
            orb_corr = [r for r in sel
                        if klass(r["orb"]["verdict"]) == "correspondence"]
            rescued = [r for r in orb_corr if r[name]["verdict"] == "solvable"]
            orb_base = [r for r in sel if klass(r["orb"]["verdict"]) == "baseline"]
            base_resc = [r for r in orb_base if r[name]["verdict"] == "solvable"]
            print(f"  RECOVERY of ORB correspondence failures: "
                  f"{len(rescued)}/{len(orb_corr)}"
                  + (f" ({100 * len(rescued) / len(orb_corr):.1f}%)"
                     if orb_corr else ""))
            print(f"  'recovery' of ORB baseline failures:     "
                  f"{len(base_resc)}/{len(orb_base)}"
                  + (f" ({100 * len(base_resc) / len(orb_base):.1f}%)"
                     if orb_base else ""))


if __name__ == "__main__":
    main()
