"""Select cross-segment keyframe pairs for the learned-3D lane.

RESEARCH HARNESS. Reads only; writes a JSON manifest to the scratchpad.
Uses the repo's OWN ORB detector/matcher and thresholds so the classical
baseline number quoted next to each pair is the number the production
backend would have seen.
"""
from __future__ import annotations
import itertools, json, sys, time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tower.world_builder.geometry import (  # noqa: E402
    MIN_INLIERS, RANSAC_CONFIDENCE, RANSAC_THRESHOLD_PX,
    detect_and_describe, match_indices,
)

WORLD = ROOT / "data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4"
SESSION = "dd5d13a2381e430db9b27c7da2cf2928"
IMAGES = WORLD / "sessions" / SESSION / "images"
POSES = WORLD / "derived" / SESSION / "poses.json"
INTR = ROOT / "data/world_builder/intrinsics/360x640.json"


def load_keyframes():
    rows = json.load(open(POSES))["poses"]
    seg = defaultdict(list)
    for r in rows:
        stem = r["keyframe_id"].split(":")[1]
        p = IMAGES / f"{stem}.jpg"
        if p.exists():
            seg[r["segment_index"]].append((stem, str(p), r["status"]))
    return dict(sorted(seg.items()))


def main():
    seg = load_keyframes()
    K = json.load(open(INTR))
    print(f"segments={len(seg)} keyframes={sum(len(v) for v in seg.values())}")

    # describe every keyframe once
    t0 = time.time()
    feats = {}
    for s, items in seg.items():
        for stem, path, status in items:
            g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            kp, des = detect_and_describe(g)
            feats[stem] = (np.float32([k.pt for k in kp]) if kp else np.zeros((0, 2), np.float32), des)
    t_desc = time.time() - t0
    print(f"described {len(feats)} keyframes in {t_desc:.1f}s")

    Kmat = np.float64([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]])

    def verify(a, b):
        pa, da = feats[a]
        pb, db = feats[b]
        if da is None or db is None:
            return 0, 0
        pairs = match_indices(da, db)
        if len(pairs) < MIN_INLIERS:
            return len(pairs), 0
        ia = [p[0] for p in pairs]
        ib = [p[1] for p in pairs]
        E, mask = cv2.findEssentialMat(
            pa[ia], pb[ib], Kmat, method=cv2.USAC_MAGSAC,
            prob=RANSAC_CONFIDENCE, threshold=RANSAC_THRESHOLD_PX)
        if E is None or mask is None:
            return len(pairs), 0
        return len(pairs), int(mask.sum())

    # all-pairs at SEGMENT level, best keyframe pair per segment pair
    t0 = time.time()
    best = {}
    segs = list(seg)
    for sa, sb in itertools.combinations(segs, 2):
        bi, bk = 0, None
        for (ka, _, _), (kb, _, _) in itertools.product(seg[sa], seg[sb]):
            m, inl = verify(ka, kb)
            if inl > bi:
                bi, bk = inl, (ka, kb, m)
        best[(sa, sb)] = (bi, bk)
    t_match = time.time() - t0
    print(f"all-pairs segment matching ({len(best)} segment pairs) in {t_match:.1f}s")

    ranked = sorted(((v[0], k, v[1]) for k, v in best.items()), reverse=True, key=lambda x: x[0])
    for inl, (sa, sb), bk in ranked[:40]:
        print(f"  seg({sa:2d},{sb:2d}) inliers={inl:4d} kf={bk[:2] if bk else None} matches={bk[2] if bk else 0}")

    zero = [(k, v) for k, v in best.items() if v[0] == 0]
    print(f"segment pairs with ZERO verified inliers: {len(zero)} / {len(best)}")

    out = {
        "session": SESSION,
        "n_segments": len(seg),
        "n_keyframes": sum(len(v) for v in seg.values()),
        "describe_seconds": t_desc,
        "match_seconds": t_match,
        "segment_keyframes": {str(s): [i[0] for i in v] for s, v in seg.items()},
        "segment_pair_best": {f"{a}_{b}": {"inliers": v[0], "kf_a": (v[1][0] if v[1] else None),
                                            "kf_b": (v[1][1] if v[1] else None),
                                            "matches": (v[1][2] if v[1] else 0)}
                              for (a, b), v in best.items()},
    }
    dest = Path(sys.argv[1])
    dest.write_text(json.dumps(out, indent=1))
    print("wrote", dest)


if __name__ == "__main__":
    main()
