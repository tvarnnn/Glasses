"""The other half of the ROC: what does production's gate accept on REAL pairs?

`production_gate_on_null.py` shows production's shipped two-view criterion has a
0.0% false-'solvable' rate on 200 pairs of exactly-zero baseline, where Lane 2's
transcription of the same criterion has 13.0%. A gate that refuses everything
would also score 0%, so the acceptance rate on real pairs must be priced before
that number means anything.

Runs the SAME two transcriptions over real persisted keyframe pairs at several
frame gaps, so the null result and the recall can be read on one axis.

No ground truth. "Accepted" means "production's degeneracy criterion would have
admitted this pair", never "the pose is right".
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TOWER = HERE.parents[2]
sys.path.insert(0, str(TOWER))

from tower.world_builder.geometry import detect_and_describe, match_descriptors  # noqa: E402
from production_gate_on_null import lane2_verdict, production_verdict  # noqa: E402

WORLD = TOWER / "data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4"
SESSION = WORLD / "sessions/dd5d13a2381e430db9b27c7da2cf2928"
DERIVED = WORLD / "derived/dd5d13a2381e430db9b27c7da2cf2928"


def main():
    intr = json.load(open(TOWER / "data/world_builder/intrinsics/360x640.json"))
    K = np.array([[intr["fx"], 0, intr["cx"]],
                  [0, intr["fy"], intr["cy"]], [0, 0, 1.0]])
    imgs = sorted((SESSION / "images").glob("*.jpg"))
    print(f"{len(imgs)} persisted keyframes")

    cen = json.load(open(HERE.parent / "slam_classical/covisibility_census.json"))
    seg = cen["meta"]["segment_index"]
    pts = json.load(open(DERIVED / "points.json"))["points"]
    segs_with_geometry = {p["segment_index"] for p in pts}

    cache = {}

    def feats(i):
        if i not in cache:
            if len(cache) > 260:
                cache.clear()
            g = cv2.imread(str(imgs[i]), cv2.IMREAD_GRAYSCALE)
            cache[i] = detect_and_describe(g)
        return cache[i]

    out = {}
    for gap in (1, 2, 3, 5, 10, 20):
        rec = []
        for i in range(0, len(imgs) - gap):
            ka, da = feats(i)
            kb, db = feats(i + gap)
            pa, pb = match_descriptors(ka, da, kb, db)
            v2, _ = lane2_verdict(pa, pb, K)
            vp, tp = production_verdict(pa, pb, K)
            rec.append({"i": i, "j": i + gap,
                        "same_seg": seg[i] == seg[i + gap],
                        "geomless": seg[i] not in segs_with_geometry,
                        "lane2": v2, "prod": vp})
        n = len(rec)
        a2 = sum(1 for r in rec if r["lane2"] == "solvable")
        ap = sum(1 for r in rec if r["prod"] == "solvable")
        sub = [r for r in rec if r["same_seg"] and r["geomless"]]
        out[gap] = {
            "n_pairs": n,
            "lane2_accept_pct": round(100 * a2 / n, 2),
            "production_accept_pct": round(100 * ap / n, 2),
            "production_verdict_mix": dict(Counter(r["prod"] for r in rec)),
            "n_pairs_inside_geometryless_segments": len(sub),
            "production_accept_pct_geometryless": (
                round(100 * sum(1 for r in sub if r["prod"] == "solvable") / len(sub), 2)
                if sub else None),
            "lane2_accept_pct_geometryless": (
                round(100 * sum(1 for r in sub if r["lane2"] == "solvable") / len(sub), 2)
                if sub else None),
        }
        print(f"gap {gap:2d}: n={n:4d}  lane2 accepts {out[gap]['lane2_accept_pct']:5.1f}%  "
              f"production accepts {out[gap]['production_accept_pct']:5.1f}%  "
              f"(geometry-less subset: lane2 {out[gap]['lane2_accept_pct_geometryless']}%, "
              f"production {out[gap]['production_accept_pct_geometryless']}%)", flush=True)

    (HERE / "production_gate_on_real.json").write_text(json.dumps(out, indent=1))
    print("\nNULL (true baseline exactly 0): lane2 13.0%, production 0.0% "
          "[M, production_gate_on_null.py]")


if __name__ == "__main__":
    main()
