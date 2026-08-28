"""Is DPVO's advantage the NETWORK, or the GRAPH? Measured on real frames.

The repo already measured that bundle adjustment bought 0.00% drift improvement
"because the observation graph is a chain whose median covisibility span is 1"
(classical.py:246-250). `_extend` matches keyframe i only against keyframe i-1,
so a landmark is seen by two views and there is no cycle for BA to tighten.

DPVO does not do that. Its patches have PATCH_LIFETIME = 13 and are optimised
over an OPTIMIZATION_WINDOW of 10 frames (config/default.yaml), so a single
patch constrains up to 13 poses at once. That -- not the CNN -- is where a
dense, cyclic factor graph comes from.

So the question this harness asks is: on OUR footage, is a covisibility span of
~13 frames available to a CLASSICAL matcher, or does it need a learned one?

  * If ORB already matches across 13-frame gaps on Ray-Ban footage, the graph
    DPVO builds is buildable without any network, and the learned front end is
    not what we would be buying.
  * If ORB collapses beyond a couple of frames and a learned matcher does not,
    then the network is load-bearing and DPVO's advantage is not just graph
    topology.

Two measurements, on RAW capture frames (DPVO consumes frames, not our
keyframes):

  A. gap sweep      for gap g, the fraction of (i, i+g) frame pairs that
                    survive the production geometric test, per matcher
  B. track building  union-find over ORB index matches inside a window,
                    for window widths 1 (our chain), 3, 5, and all-pairs;
                    reports the covisibility span distribution each yields

NO GROUND TRUTH. "Survives" means "the production degeneracy criterion would
have accepted it", not "the pose is correct".
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

from matcher_showdown import build_matcher, verdict  # noqa: E402

from tower.world_builder.frontend import decode_gray  # noqa: E402
from tower.world_builder.geometry import (  # noqa: E402
    MIN_INLIERS,
    detect_and_describe,
    match_indices,
)


class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", default="22e9d4289cb440fbb3f14e6da369a136")
    ap.add_argument("--intrinsics",
                    default="data/world_builder/intrinsics/360x640.json")
    ap.add_argument("--windows", type=int, default=8)
    ap.add_argument("--window-len", type=int, default=32)
    ap.add_argument("--gaps", default="1,2,3,5,8,13,21,31")
    ap.add_argument("--matchers", default="orb,loftr")
    ap.add_argument("--seed", type=int, default=20260826)
    ap.add_argument("--out", type=Path, default=HERE / "covisibility_span.json")
    args = ap.parse_args()

    intr = json.loads((TOWER_ROOT / args.intrinsics).read_text())
    K = np.array([[intr["fx"], 0, intr["cx"]],
                  [0, intr["fy"], intr["cy"]], [0, 0, 1.0]])

    frames_dir = TOWER_ROOT / "data/captures" / args.capture / "frames"
    files = sorted(frames_dir.glob("*.jpg"))
    print(f"{len(files)} frames in {args.capture}")

    rng = np.random.default_rng(args.seed)
    starts = sorted(rng.choice(len(files) - args.window_len,
                               size=args.windows, replace=False).tolist())
    print("window starts:", starts)

    gaps = [int(g) for g in args.gaps.split(",")]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    built = {n.strip(): build_matcher(n.strip(), dev)
             for n in args.matchers.split(",")}

    gap_rows = []
    track_rows = []

    for s in starts:
        window = files[s: s + args.window_len]
        grays = [decode_gray(f.read_bytes()) for f in window]

        # -- A. gap sweep ------------------------------------------------
        for g in gaps:
            if g >= len(window):
                continue
            for i in range(0, len(window) - g):
                for name, m in built.items():
                    pa, pb, _ = m(grays[i], grays[i + g])
                    r = verdict(np.ascontiguousarray(pa),
                                np.ascontiguousarray(pb), K)
                    gap_rows.append({"start": s, "i": i, "gap": g,
                                     "matcher": name, "matches": r["matches"],
                                     "inliers": r["inliers"], "tri": r["tri"],
                                     "verdict": r["verdict"]})

        # -- B. track building (ORB only: LoFTR is detector-free and emits no
        #       reusable feature identity, so it cannot form tracks directly)
        feats = [detect_and_describe(g_) for g_ in grays]
        edges = {}  # (i, j) -> list of (fi, fj), geometrically verified
        for i in range(len(window)):
            for j in range(i + 1, len(window)):
                ki, di = feats[i]
                kj, dj = feats[j]
                idx = match_indices(di, dj)
                if len(idx) < 8:
                    edges[(i, j)] = []
                    continue
                pa = np.float32([ki[a].pt for a, _ in idx])
                pb = np.float32([kj[b].pt for _, b in idx])
                E, mask = cv2.findEssentialMat(pa, pb, K, cv2.RANSAC,
                                               0.999, 1.0)
                if E is None or mask is None or int(mask.sum()) < MIN_INLIERS:
                    edges[(i, j)] = []
                    continue
                keep = mask.ravel().astype(bool)
                edges[(i, j)] = [idx[t] for t in range(len(idx)) if keep[t]]

        for width in (1, 3, 5, args.window_len):
            dsu = DSU()
            for (i, j), pairs in edges.items():
                if j - i > width:
                    continue
                for a, b in pairs:
                    dsu.union((i, a), (j, b))
            groups = {}
            for node in list(dsu.p):
                groups.setdefault(dsu.find(node), []).append(node)
            spans, lens = [], []
            for members in groups.values():
                fr = sorted({n[0] for n in members})
                if len(fr) < 2:
                    continue
                lens.append(len(fr))
                spans.append(fr[-1] - fr[0])
            track_rows.append({
                "start": s, "width": width,
                "tracks": len(lens),
                "track_len_median": statistics.median(lens) if lens else 0,
                "track_len_mean": round(statistics.fmean(lens), 3) if lens else 0,
                "frac_len_ge3": round(sum(1 for x in lens if x >= 3)
                                      / max(len(lens), 1), 4),
                "frac_len_ge5": round(sum(1 for x in lens if x >= 5)
                                      / max(len(lens), 1), 4),
                "span_median": statistics.median(spans) if spans else 0,
                "span_p90": (sorted(spans)[int(0.9 * len(spans)) - 1]
                             if spans else 0),
            })
        print(f"window @{s} done", flush=True)

    args.out.write_text(json.dumps({"gap": gap_rows, "tracks": track_rows},
                                   indent=1))
    print("wrote " + str(args.out))

    print("\n=== A. GAP SWEEP: can a matcher still solve across g frames? ===")
    print(f"{args.windows} windows x {args.window_len} frames from "
          f"{args.capture} (~11.99 fps)")
    for name in built:
        print(f"\n-- {name} --")
        print(f"{'gap':>5} {'pairs':>6} {'solvable':>9} {'baseline':>9} "
              f"{'corr-fail':>10} {'med matches':>12} {'med inliers':>12} "
              f"{'med tri':>8}")
        for g in gaps:
            sel = [r for r in gap_rows if r["gap"] == g and r["matcher"] == name]
            if not sel:
                continue
            c = Counter(r["verdict"] for r in sel)
            solv = c.get("solvable", 0)
            base = c.get("low_parallax", 0) + c.get("no_triangulation", 0)
            corr = len(sel) - solv - base
            mm = statistics.median([r["matches"] for r in sel])
            mi = statistics.median([r["inliers"] for r in sel])
            tri = [r["tri"] for r in sel if r["tri"] is not None]
            mt = statistics.median(tri) if tri else float("nan")
            print(f"{g:>5} {len(sel):>6} {100 * solv / len(sel):>8.1f}% "
                  f"{100 * base / len(sel):>8.1f}% {100 * corr / len(sel):>9.1f}% "
                  f"{mm:>12.0f} {mi:>12.0f} {mt:>8.3f}")

    print("\n=== B. TRACKS from ORB, by how many neighbours we match against ===")
    print("width 1 == the production chain (_extend matches i to i-1 only)")
    print(f"{'width':>6} {'tracks':>8} {'med len':>8} {'mean len':>9} "
          f"{'>=3 views':>10} {'>=5 views':>10} {'med span':>9} {'p90 span':>9}")
    for width in sorted({r["width"] for r in track_rows}):
        sel = [r for r in track_rows if r["width"] == width]
        print(f"{width:>6} {round(statistics.fmean([r['tracks'] for r in sel])):>8} "
              f"{statistics.fmean([r['track_len_median'] for r in sel]):>8.2f} "
              f"{statistics.fmean([r['track_len_mean'] for r in sel]):>9.2f} "
              f"{100 * statistics.fmean([r['frac_len_ge3'] for r in sel]):>9.1f}% "
              f"{100 * statistics.fmean([r['frac_len_ge5'] for r in sel]):>9.1f}% "
              f"{statistics.fmean([r['span_median'] for r in sel]):>9.2f} "
              f"{statistics.fmean([r['span_p90'] for r in sel]):>9.2f}")


if __name__ == "__main__":
    main()
