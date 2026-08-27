"""Re-run Lane 1's covisibility census against what HEAD actually produces.

WHY THIS EXISTS. Every lane, and the shared brief, quote "1848 frames -> 457
keyframes, 51 segments, 94 solved poses, 32 segments with zero geometry" as
current state. It is not. Those artefacts were written 2026-08-25 17:59-18:01,
BEFORE `85d94a2` ("a break is permanent, so it takes more than one bad frame")
and `1272b09` ("grace ships disabled"). Only the DERIVED geometry was rebuilt
at HEAD, on 2026-08-26 00:12.

Replaying the same 1848 frames through HEAD today gives 448 keyframes,
33 segments, 61 solved poses, 8,333 points -- measured twice, bit-identical.

So Lane 1's census, and its "51 segments collapse to 3 components" headline,
describe a segmentation the code no longer emits. This re-runs the identical
census -- same detector, same matcher, same thresholds, Lane 1's own `_pair`
function imported unchanged -- against a HEAD replay, so the recommendation is
priced against current state.

Read-only against the corpus; reads a world built into the scratch directory.
"""

from __future__ import annotations

import glob
import json
import multiprocessing as mp
import os
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CLASSICAL = HERE.parent / "slam_classical"
TOWER = HERE.parents[2]
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(CLASSICAL))

import cv2  # noqa: E402
from tower.world_builder.frontend import decode_gray  # noqa: E402
from tower.world_builder.geometry import (  # noqa: E402
    LOWE_RATIO, MIN_INLIERS, MIN_TRIANGULATION_ANGLE_DEG, ORB_FEATURES,
    detect_and_describe,
)
import covisibility_census as CC  # noqa: E402


def main():
    scratch = json.load(open(HERE / "paths.json"))["scratch"]
    sess = Path(glob.glob(scratch + "/repeat_A/worlds/*/sessions/*")[0])
    out_path = HERE / "census_at_head.json"

    kfs = [json.loads(x) for x in (sess / "keyframes.jsonl").read_text().splitlines()
           if x.strip()]
    n = len(kfs)
    segs = {k["segment_index"] for k in kfs}
    print(f"HEAD replay: keyframes={n} segments={len(segs)} cv2={cv2.__version__}")

    pts, desc, feat = [], [], []
    t0 = time.perf_counter()
    for k in kfs:
        gray = decode_gray((sess / k["image_relpath"]).read_bytes())
        kp, d = detect_and_describe(gray)
        pts.append(np.float32([p.pt for p in kp]).reshape(-1, 2) if kp
                   else np.empty((0, 2), np.float32))
        desc.append(d)
        feat.append(len(kp))
    print(f"detect {time.perf_counter()-t0:.1f}s  features median={int(np.median(feat))} "
          f"min={min(feat)} max={max(feat)}  <=100 features: {sum(1 for f in feat if f <= 100)}")

    jobs = list(combinations(range(n), 2))
    workers = max(1, min(12, (os.cpu_count() or 4) - 2))
    t0 = time.perf_counter()
    rows = []
    with mp.Pool(workers, initializer=CC._init,
                 initargs=(dict(pts=pts, desc=desc),)) as pool:
        for idx, r in enumerate(pool.imap_unordered(CC._pair, jobs, chunksize=256)):
            rows.append(r)
            if idx % 20000 == 0 and idx:
                print(f"  {idx}/{len(jobs)} {time.perf_counter()-t0:.0f}s", flush=True)
    print(f"all-pairs {time.perf_counter()-t0:.1f}s on {workers} workers")

    meta = dict(n_keyframes=n, n_pairs=len(jobs),
                segment_index=[k["segment_index"] for k in kfs],
                feature_counts=feat, cv2=cv2.__version__,
                orb_features=ORB_FEATURES, lowe=LOWE_RATIO,
                min_inliers=MIN_INLIERS, min_tri_angle=MIN_TRIANGULATION_ANGLE_DEG)
    out_path.write_text(json.dumps(dict(meta=meta, pairs=rows)))
    print(f"wrote {out_path} ({out_path.stat().st_size/1e6:.1f} MB)")

    # --- the three numbers that matter ---
    seg = meta["segment_index"]
    deg = [0] * n
    edges = cross = useful = 0
    import collections
    adj = collections.defaultdict(set)
    for p in rows:
        if p["f_inliers"] >= MIN_INLIERS:
            edges += 1
            deg[p["i"]] += 1
            deg[p["j"]] += 1
            if seg[p["i"]] != seg[p["j"]]:
                cross += 1
            t = p.get("tri_angle")
            if t is not None and t >= MIN_TRIANGULATION_ANGLE_DEG:
                useful += 1
                adj[seg[p["i"]]].add(seg[p["j"]])
                adj[seg[p["j"]]].add(seg[p["i"]])

    # connected components over segments, useful edges only
    seen, comps = set(), []
    for s in sorted(segs):
        if s in seen:
            continue
        stack, comp = [s], []
        seen.add(s)
        while stack:
            c = stack.pop()
            comp.append(c)
            for nb in adj.get(c, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        comps.append(sorted(comp))
    comps.sort(key=len, reverse=True)

    print(f"\n=== census at HEAD ({n} keyframes, {len(segs)} segments) ===")
    print(f"covisibility edges (>=15 F-inliers): {edges}  "
          f"({100*edges/len(jobs):.2f}% of {len(jobs)} pairs)")
    print(f"  of which cross-segment: {cross}")
    print(f"  with parallax >= 0.5 deg: {useful}")
    print(f"median covisibility degree: {int(np.median(deg))}  "
          f"mean {np.mean(deg):.1f}  isolated {sum(1 for d in deg if d == 0)}")
    print(f"segments -> connected components (useful edges): {len(comps)}, "
          f"largest holds {len(comps[0])}/{len(segs)}")


if __name__ == "__main__":
    main()
