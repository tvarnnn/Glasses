"""Per-segment gauge depth of the stored reconstruction.

Needed for the ONLY absolute-scale oracle available to us: the classical
pipeline measured that segment 5's length unit is 0.3533 of segment 4's
(reverse estimate agreeing to 0.3%). If MASt3R's metric head is right, then
    metres_per_unit(seg5) / metres_per_unit(seg4)  ==  0.3533
where metres_per_unit(S) = MASt3R_metric_depth(keyframe) / gauge_depth(keyframe).
This script produces gauge_depth: the median depth, in that segment's own
arbitrary units, of the segment's landmarks seen from one of its keyframes.
"""
from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
WORLD = ROOT / "data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4"
SESSION = "dd5d13a2381e430db9b27c7da2cf2928"
D = WORLD / "derived" / SESSION


def quat_to_R(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


poses = json.load(open(D / "poses.json"))["poses"]
points = json.load(open(D / "points.json"))
prows = points["points"] if isinstance(points, dict) else points

seg_pts = defaultdict(list)
for p in prows:
    seg_pts[p["segment_index"]].append(p["xyz"])

out = {}
for r in poses:
    if r["status"] != "solved" or r["rotation"] is None or r["translation"] is None:
        continue
    s = r["segment_index"]
    P = np.array(seg_pts.get(s, []), dtype=float)
    if len(P) < 10:
        continue
    R = quat_to_R(r["rotation"])
    t = np.array(r["translation"], dtype=float)
    # stored convention: engine places poses as camera-in-local-frame; treat
    # (R, t) as world->cam and report BOTH candidate depths so the reader can
    # see the convention did not change the conclusion.
    z_wc = (P @ R.T + t)[:, 2]
    C = -R.T @ t
    z_cw = ((P - C) @ R)[:, 2]
    stem = r["keyframe_id"].split(":")[1]
    out[stem] = {
        "segment": s, "n_points": int(len(P)),
        "median_depth_world_to_cam": float(np.median(z_wc)),
        "median_depth_cam_to_world": float(np.median(z_cw)),
        "median_abs_depth": float(np.median(np.abs(z_wc))),
        "scene_radius": float(np.median(np.linalg.norm(P - P.mean(0), axis=1))),
    }

Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
print("wrote", sys.argv[1], len(out), "solved keyframes with segment geometry")
for k in sorted(out, key=lambda k: (out[k]["segment"], k)):
    v = out[k]
    if v["segment"] in (4, 5, 32, 19, 30):
        print("  seg{:2d} kf {} n={:5d} d_wc={:8.3f} d_cw={:8.3f} radius={:8.3f}".format(
            v["segment"], k, v["n_points"], v["median_depth_world_to_cam"],
            v["median_depth_cam_to_world"], v["scene_radius"]))
