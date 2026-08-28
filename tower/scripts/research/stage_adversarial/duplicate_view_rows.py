#!/usr/bin/env python
"""Characterise the duplicate-view support rows Stage 1 introduces.

WHAT THEY ARE

`duplicate_view_support_rows` counts support rows naming a keyframe that
already observes that landmark -- two DIFFERENT features in ONE image
both bound to ONE landmark. A point projects to exactly one pixel in a
given camera, so that is a geometrically impossible pair of claims. The
Stage 0 baseline records 0 of them corpus-wide; DEPTH=3 records 1,002
(MEASURED, this review), and no document on the branch mentions it.

THE QUESTION SEVERITY TURNS ON

Both rows in such a pair passed a 3.0 px reprojection test against the
SAME pose, so they must lie within 6.0 px of each other -- an upper
bound from the gate, not a measurement. If the real separations cluster
at 1-2 px these are two ORB detections of one corner, and the harm is an
inflated row count. If pairs are far apart, a landmark is being claimed
at two genuinely different places and support.json is being poisoned for
the cross-segment registration that PnPs against it.

`world_registration.read_segments` is used to join the four files --
the same reader registration and the Stage 0 reprojection block use --
so this cannot drift from how the pipeline itself reads support.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(TOWER / "scripts"))

import world_registration as reg  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402
import world_builder_corpus_benchmark as bench  # noqa: E402


def analyse(scratch, prefix):
    store = WorldStore(Path(scratch) / prefix)
    world_ids = store.list_world_ids()
    if not world_ids:
        return None
    world_id = world_ids[0]
    session_id = store.list_session_ids(world_id)[0]
    segments = reg.read_segments(store, world_id, session_id)

    separations = []
    groups = 0
    unresolved = 0
    beyond = []
    for seg_index, segment in segments.items():
        # point -> frame -> [feature]
        by_point = defaultdict(lambda: defaultdict(list))
        for (frame, feature), point_index in segment.observed.items():
            by_point[point_index][frame].append(feature)
        for point_index, frames in by_point.items():
            for frame, feats in frames.items():
                uniq = sorted(set(feats))
                if len(uniq) < 2:
                    continue
                groups += 1
                keypoints = (
                    segment.keypoints[frame]
                    if frame < len(segment.keypoints) else None
                )
                if keypoints is None:
                    unresolved += 1
                    continue
                coords = [keypoints[f] for f in uniq if f < len(keypoints)]
                if len(coords) < 2:
                    unresolved += 1
                    continue
                for i in range(len(coords)):
                    for j in range(i + 1, len(coords)):
                        d = float(np.linalg.norm(
                            np.asarray(coords[i]) - np.asarray(coords[j])
                        ))
                        separations.append(d)
                        if d > 6.0:
                            beyond.append({
                                "segment": int(seg_index), "frame": int(frame),
                                "point": int(point_index),
                                "features": [int(uniq[i]), int(uniq[j])],
                                "separation_px": round(d, 3),
                            })
    return separations, groups, unresolved, beyond


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", default="C:/wb-adv/d3")
    ap.add_argument("--prefixes", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    prefixes = (
        args.prefixes.split(",") if args.prefixes
        else list(bench.PINNED_PREFIXES)
    )
    all_sep, all_groups, all_unres, all_beyond = [], 0, 0, []
    per_capture = {}
    for prefix in prefixes:
        got = analyse(args.scratch, prefix)
        if got is None:
            continue
        sep, groups, unres, beyond = got
        per_capture[prefix] = {
            "groups": groups, "pairs": len(sep),
            "median_px": float(np.median(sep)) if sep else None,
            "max_px": float(max(sep)) if sep else None,
        }
        all_sep.extend(sep)
        all_groups += groups
        all_unres += unres
        all_beyond.extend(beyond)
        print(f"{prefix}: groups {groups}, pairs {len(sep)}", flush=True)

    sep = np.array(all_sep, dtype=np.float64)
    out = {
        "scratch": args.scratch,
        "duplicate_landmark_frame_groups": all_groups,
        "pairs_measured": int(sep.size),
        "unresolved_groups": all_unres,
        "pairs_beyond_6px": len(all_beyond),
        "examples_beyond_6px": all_beyond[:20],
        "per_capture": per_capture,
    }
    if sep.size:
        out.update({
            "separation_px_min": float(sep.min()),
            "separation_px_median": float(np.median(sep)),
            "separation_px_mean": float(sep.mean()),
            "separation_px_p90": float(np.percentile(sep, 90)),
            "separation_px_max": float(sep.max()),
            "fraction_within_2px": float((sep <= 2.0).mean()),
            "fraction_within_6px": float((sep <= 6.0).mean()),
            "histogram_1px_bins_0_to_10": np.histogram(
                sep, bins=np.arange(0, 11, 1)
            )[0].tolist(),
        })
    print(json.dumps({k: v for k, v in out.items()
                      if k != "examples_beyond_6px"}, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
