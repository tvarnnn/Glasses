#!/usr/bin/env python
"""Two questions about the homography_ratio fix.

1. DOES IT SILENTLY DISABLE THE FIELD ON HEALTHY PAIRS? Guarding on the
   model is only safe if a model fits whenever a model should. If r_H
   now returns None on ordinary pairs, the fix traded a wrong number for
   a missing one.

2. IS IT DETERMINISTIC ON THE KNOWN-BAD PAIR? The defect was a dirty
   uninitialised mask buffer that self-heals within a warm process, so
   it only shows on the FIRST call in a FRESH process. Repeated calls in
   one process prove nothing. This runs one call per fresh child.

Run with --child to act as the child.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(TOWER / "scripts"))


def bad_pair():
    """The pair the defect was measured on: capture 22e9d428, keyframes
    00000345 x 00001824 -- 242 Lowe matches on 3 distinct locations in a
    keyframe holding 5 ORB features, so neither F (8 points in general
    position) nor H (4) can fit."""
    import cv2
    from tower.world_builder.geometry import (
        detect_and_describe, match_descriptors,
    )
    root = Path(
        r"C:\Users\tvllo\Projects\Glasses\tower\data\world_builder\worlds"
    )
    hits = list(root.glob("*/sessions/*/images/00000345.jpg"))
    if not hits:
        return None
    for a_path in hits:
        b_path = a_path.parent / "00001824.jpg"
        if not b_path.exists():
            continue
        ga = cv2.imread(str(a_path), cv2.IMREAD_GRAYSCALE)
        gb = cv2.imread(str(b_path), cv2.IMREAD_GRAYSCALE)
        if ga is None or gb is None:
            continue
        ka, da = detect_and_describe(ga)
        kb, db = detect_and_describe(gb)
        pa, pb = match_descriptors(ka, da, kb, db)
        return pa, pb
    return None


def child():
    from tower.world_builder.geometry import homography_ratio
    got = bad_pair()
    if got is None:
        print(json.dumps({"available": False}))
        return 0
    pa, pb = got
    value = homography_ratio(pa, pb)
    print(json.dumps({
        "available": True, "matches": int(len(pa)),
        "r_h": None if value is None else float(value),
    }))
    return 0


def healthy():
    """r_H on rendered pairs with real parallax -- a model must fit."""
    sys.path.insert(0, str(TOWER))
    from tests import synthetic_scene as ss
    from tower.world_builder.geometry import (
        detect_and_describe, match_descriptors, homography_ratio,
    )
    import cv2
    W, H = 480, 360
    K = ss.camera_matrix(W, H)
    out = []
    for seed in (1234, 7, 99):
        scene = ss.furnished_room(seed=seed)
        for name, poses in (
            ("strafe", ss.strafe(6, step=0.15)),
            ("forward", ss.forward_walk(6, step=0.15)),
            ("pure_rotation", ss.pure_rotation(6, degrees_per_step=3.0)),
        ):
            imgs = ss.render_sequence(scene, poses, K, W, H)
            grays = [cv2.cvtColor(i, cv2.COLOR_BGR2GRAY) for i in imgs]
            ka, da = detect_and_describe(grays[0])
            kb, db = detect_and_describe(grays[-1])
            pa, pb = match_descriptors(ka, da, kb, db)
            value = homography_ratio(pa, pb)
            out.append({
                "seed": seed, "motion": name, "matches": int(len(pa)),
                "r_h": None if value is None else round(float(value), 4),
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--repeats", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.child:
        return child()

    print("HEALTHY PAIRS -- r_h must not be None where a model fits")
    rows = healthy()
    for r in rows:
        print(f"  seed={r['seed']:5d} {r['motion']:14s} "
              f"matches={r['matches']:4d} r_h={r['r_h']}")
    nones = [r for r in rows if r["r_h"] is None and r["matches"] >= 8]
    print(f"  -> None on {len(nones)} of {len(rows)} pairs with >=8 matches")

    print(f"\nKNOWN-BAD PAIR -- {args.repeats} FRESH processes")
    results = []
    for i in range(args.repeats):
        proc = subprocess.run(
            [sys.executable, str(HERE), "--child"],
            capture_output=True, text=True,
            env={**__import__("os").environ,
                 "PYTHONPATH": str(TOWER)},
        )
        line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            results.append({"error": proc.stdout[-200:], "stderr": proc.stderr[-300:]})
    for i, r in enumerate(results):
        print(f"  run {i+1}: {r}")
    values = {json.dumps(r.get("r_h")) for r in results if "r_h" in r}
    print(f"  -> distinct r_h values across fresh processes: {values}")

    report = {"healthy": rows, "fresh_process_runs": results,
              "distinct_values": sorted(values)}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
