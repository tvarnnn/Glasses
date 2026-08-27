#!/usr/bin/env python
"""Landmark multiplicity as a function of EXTEND_REFERENCE_DEPTH.

This is the neutralize-and-check instrument for Stage 1. It runs the REAL
`ClassicalTwoViewBackend.estimate_window` over REAL keyframe images at
several values of DEPTH and reports the support-view distribution.

DEPTH=1 restores the historical one-reference behaviour exactly, so it is
the control. If the metric does not move between DEPTH=1 and DEPTH=3,
the mechanism is not running and no amount of green tests says otherwise.

No production code is modified. DEPTH is rebound on the module for the
duration of a run and restored, which is the same thing a config switch
would do and keeps the control honest.

Usage:
  python measure_depth.py --keyframes <dir-of-jpgs> [--limit N] [--depths 1,2,3,5]
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import statistics
import sys
import time
from pathlib import Path


def _resolve_provenance():
    """Refuse to measure the wrong tree.

    There is an editable install in the shared venv that maps `tower` at
    the MAIN repo. A run that silently picked that up would measure a
    different branch's pipeline and look completely normal doing it.
    """
    import tower.world_builder.backends.classical as classical

    where = Path(classical.__file__).resolve()
    if "Glasses-world-builder" not in str(where):
        raise SystemExit(
            f"REFUSING TO RUN: resolved production code to {where}, which is "
            "not the world-builder worktree. Set PYTHONPATH to the worktree's "
            "tower/ directory."
        )
    return classical, where


def _load(paths):
    import cv2

    from tower.world_builder.backend import KeyframeInput

    window = []
    for index, path in enumerate(paths):
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise SystemExit(f"unreadable image: {path}")
        window.append(
            KeyframeInput(keyframe_id=f"kf{index:05d}", image_gray=gray)
        )
    return window


def _intrinsics(width, height):
    from tower.world_builder.records import CameraIntrinsics

    calib = Path(
        r"C:\Users\tvllo\Projects\Glasses\tower\data\world_builder"
        r"\intrinsics\360x640.json"
    )
    data = json.loads(calib.read_text())
    if (data["calibrated_width"], data["calibrated_height"]) != (width, height):
        raise SystemExit(
            f"calibration is {data['calibrated_width']}x"
            f"{data['calibrated_height']}, frames are {width}x{height}"
        )
    return CameraIntrinsics(
        source=data["source"],
        model=data["model"],
        fx=data["fx"],
        fy=data["fy"],
        cx=data["cx"],
        cy=data["cy"],
        dist_coeffs=tuple(data["dist_coeffs"]),
        calibrated_width=data["calibrated_width"],
        calibrated_height=data["calibrated_height"],
        reprojection_rms_px=data["reprojection_rms_px"],
        view_count=data["view_count"],
        calibrated_at=data["calibrated_at"],
        scales_linearly_across_resolutions=data[
            "scales_linearly_across_resolutions"
        ],
    )


def _stats(estimate):
    """Support-view distribution and covisibility, from the SAME table
    production persists -- rows are [frame, feature, landmark]."""
    block = estimate.points
    if block is None or block.support_views is None:
        return {"landmarks": 0, "note": "no support table produced"}

    obs = collections.defaultdict(set)
    for frame, _feature, landmark in block.support_views.tolist():
        obs[landmark].add(frame)

    mult = collections.Counter(len(v) for v in obs.values())
    total = len(obs)
    if not total:
        return {"landmarks": 0}

    def share(n):
        return round(
            100.0 * sum(c for k, c in mult.items() if k >= n) / total, 2
        )

    cov = collections.Counter()
    for frames in obs.values():
        for a, b in itertools.combinations(sorted(frames), 2):
            cov[(a, b)] += 1
    degree = collections.defaultdict(set)
    for a, b in cov:
        degree[a].add(b)
        degree[b].add(a)
    degrees = sorted(len(v) for v in degree.values())

    solved = sum(
        1 for p in estimate.poses if p.status == "solved"
    )
    return {
        "landmarks": total,
        "exactly_2_view_pct": round(100.0 * mult.get(2, 0) / total, 2),
        "ge3_view_pct": share(3),
        "ge5_view_pct": share(5),
        "max_multiplicity": max(mult),
        "histogram": {str(k): mult[k] for k in sorted(mult)},
        "support_rows": int(block.support_views.shape[0]),
        "covisibility_edges": len(cov),
        "median_covisibility_degree": (
            statistics.median(degrees) if degrees else 0
        ),
        "poses_solved": solved,
        "points_published": int(block.xyz.shape[0]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyframes", required=True)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--depths", default="1,2,3,5")
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--poses",
        default=None,
        help="poses.json; with --segment, restricts the window to one "
        "segment's keyframes. A window spanning a segment break refuses at "
        "the break and measures nothing, which is not a bug in the metric.",
    )
    ap.add_argument("--segment", type=int, default=None)
    args = ap.parse_args()

    classical, where = _resolve_provenance()
    print(f"production code: {where}")

    if args.poses is not None and args.segment is not None:
        poses = json.loads(Path(args.poses).read_text())["poses"]
        wanted = [
            row["keyframe_id"].split(":")[-1]
            for row in poses
            if row["segment_index"] == args.segment
        ]
        root = Path(args.keyframes)
        paths = [root / f"{name}.jpg" for name in wanted]
        missing = [p for p in paths if not p.exists()]
        if missing:
            raise SystemExit(f"{len(missing)} keyframe images missing, e.g. {missing[0]}")
        paths = paths[: args.limit]
    else:
        paths = sorted(Path(args.keyframes).glob("*.jpg"))[: args.limit]
    if len(paths) < 3:
        raise SystemExit(f"need >=3 keyframes, found {len(paths)}")
    window = _load(paths)
    height, width = window[0].image_gray.shape[:2]
    intrinsics = _intrinsics(width, height)
    print(f"{len(window)} keyframes at {width}x{height}")

    original = classical.EXTEND_REFERENCE_DEPTH
    results = {}
    try:
        for depth in [int(d) for d in args.depths.split(",")]:
            classical.EXTEND_REFERENCE_DEPTH = depth
            backend = classical.ClassicalTwoViewBackend()
            backend.prepare(intrinsics)
            started = time.perf_counter()
            estimate = backend.estimate_window(window)
            elapsed = time.perf_counter() - started
            row = _stats(estimate)
            row["depth"] = depth
            row["wall_seconds"] = round(elapsed, 3)
            results[str(depth)] = row
            print(
                f"  DEPTH={depth}: landmarks={row.get('landmarks')} "
                f"2view={row.get('exactly_2_view_pct')}% "
                f">=3view={row.get('ge3_view_pct')}% "
                f"median_deg={row.get('median_covisibility_degree')} "
                f"solved={row.get('poses_solved')} "
                f"pts={row.get('points_published')} "
                f"{row['wall_seconds']}s"
            )
    finally:
        classical.EXTEND_REFERENCE_DEPTH = original

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "production_code": str(where),
                    "keyframes": len(window),
                    "source": str(Path(args.keyframes)),
                    "results": results,
                },
                indent=2,
            )
        )
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
