#!/usr/bin/env python
"""Paired per-segment comparison of EXTEND_REFERENCE_DEPTH on real frames.

Pairs each segment with ITSELF at two depths. Pairing is the whole point:
capture content moves landmark multiplicity nearly as much as an
algorithm change does (one world on disk already sits at 47.5% >=3-view
with no widening at all), so a pooled before/after number cannot tell the
two apart. A per-segment delta can.

Reports, for every segment big enough to mean anything:
  poses_solved, points, support rows, exactly-2-view share, >=3-view share

and then the SIGN TEST across segments, because the decision is "does
this help more often than it hurts", not "did the pooled mean move".

No production code is modified. DEPTH is rebound for the duration and
restored.
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
from pathlib import Path


def _resolve():
    import tower.world_builder.backends.classical as classical

    where = Path(classical.__file__).resolve()
    if "Glasses-world-builder" not in str(where):
        raise SystemExit(f"REFUSING: production code resolved to {where}")
    return classical, where


def _intrinsics(path, width, height):
    from tower.world_builder.records import CameraIntrinsics

    data = json.loads(Path(path).read_text())
    if (data["calibrated_width"], data["calibrated_height"]) != (width, height):
        return None
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


def _segments(derived_dir, min_keyframes):
    poses = json.loads((derived_dir / "poses.json").read_text())["poses"]
    points = json.loads((derived_dir / "points.json").read_text())["points"]
    have_points = collections.Counter(p["segment_index"] for p in points)
    grouped = collections.defaultdict(list)
    for row in poses:
        grouped[row["segment_index"]].append(row["keyframe_id"].split(":")[-1])
    return {
        index: names
        for index, names in grouped.items()
        if len(names) >= min_keyframes and have_points.get(index, 0) > 0
    }


def _measure(classical, window, intrinsics, depth):
    classical.EXTEND_REFERENCE_DEPTH = depth
    backend = classical.ClassicalTwoViewBackend()
    backend.prepare(intrinsics)
    started = time.perf_counter()
    estimate = backend.estimate_window(window)
    elapsed = time.perf_counter() - started

    block = estimate.points
    solved = sum(1 for p in estimate.poses if p.status == "solved")
    if block is None or block.support_views is None:
        return {
            "poses_solved": solved,
            "points": 0,
            "support_rows": 0,
            "two_view_pct": None,
            "ge3_view_pct": None,
            "conflicts": 0,
            "wall_seconds": round(elapsed, 3),
        }

    seen = collections.defaultdict(set)
    claimed = {}
    conflicts = 0
    for frame, feature, landmark in block.support_views.tolist():
        seen[landmark].add(frame)
        key = (frame, feature)
        if key in claimed and claimed[key] != landmark:
            conflicts += 1
        claimed[key] = landmark
    total = len(seen) or 1
    return {
        "poses_solved": solved,
        "points": int(block.xyz.shape[0]),
        "support_rows": int(block.support_views.shape[0]),
        "two_view_pct": round(
            100.0 * sum(1 for v in seen.values() if len(v) == 2) / total, 2
        ),
        "ge3_view_pct": round(
            100.0 * sum(1 for v in seen.values() if len(v) >= 3) / total, 2
        ),
        "conflicts": conflicts,
        "wall_seconds": round(elapsed, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds-root", required=True)
    ap.add_argument("--intrinsics", required=True)
    ap.add_argument("--depths", default="1,3")
    ap.add_argument("--min-keyframes", type=int, default=8)
    ap.add_argument("--max-keyframes", type=int, default=40)
    ap.add_argument("--max-segments", type=int, default=40)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import cv2

    from tower.world_builder.backend import KeyframeInput

    classical, where = _resolve()
    print(f"production code: {where}")
    depths = [int(d) for d in args.depths.split(",")]
    control, treatment = depths[0], depths[-1]

    rows = []
    root = Path(args.worlds_root)
    for world in sorted(root.iterdir()):
        derived_root = world / "derived"
        if not derived_root.is_dir():
            continue
        for derived in sorted(derived_root.iterdir()):
            if not derived.is_dir():
                continue
            session = derived.name
            images = world / "sessions" / session / "images"
            if not images.is_dir():
                continue
            if not (derived / "poses.json").exists():
                continue
            try:
                segments = _segments(derived, args.min_keyframes)
            except Exception as exc:  # noqa: BLE001
                print(f"  skip {world.name}/{session}: {exc}")
                continue
            for index, names in sorted(segments.items()):
                if len(rows) >= args.max_segments:
                    break
                paths = [images / f"{n}.jpg" for n in names][
                    : args.max_keyframes
                ]
                if any(not p.exists() for p in paths):
                    continue
                grays = [
                    cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for p in paths
                ]
                if any(g is None for g in grays):
                    continue
                height, width = grays[0].shape[:2]
                intrinsics = _intrinsics(args.intrinsics, width, height)
                if intrinsics is None:
                    continue
                window = [
                    KeyframeInput(keyframe_id=f"kf{i:05d}", image_gray=g)
                    for i, g in enumerate(grays)
                ]
                original = classical.EXTEND_REFERENCE_DEPTH
                try:
                    per_depth = {
                        str(d): _measure(classical, window, intrinsics, d)
                        for d in depths
                    }
                finally:
                    classical.EXTEND_REFERENCE_DEPTH = original
                row = {
                    "world": world.name,
                    "session": session,
                    "segment": index,
                    "keyframes": len(window),
                    "depths": per_depth,
                }
                rows.append(row)
                a = per_depth[str(control)]
                b = per_depth[str(treatment)]
                print(
                    f"  {world.name[:8]} seg{index:<3} kf={len(window):<3} "
                    f"solved {a['poses_solved']}->{b['poses_solved']}  "
                    f"pts {a['points']}->{b['points']}  "
                    f"2view {a['two_view_pct']}->{b['two_view_pct']}  "
                    f"conflicts {a['conflicts']}->{b['conflicts']}"
                )

    def delta(row, field):
        a = row["depths"][str(control)][field]
        b = row["depths"][str(treatment)][field]
        if a is None or b is None:
            return None
        return b - a

    def sign_test(field):
        values = [d for d in (delta(r, field) for r in rows) if d is not None]
        return {
            "n": len(values),
            "worse": sum(1 for v in values if v < 0),
            "same": sum(1 for v in values if v == 0),
            "better": sum(1 for v in values if v > 0),
            "median_delta": (
                round(statistics.median(values), 3) if values else None
            ),
            "total_delta": round(sum(values), 3) if values else None,
        }

    summary = {
        "control_depth": control,
        "treatment_depth": treatment,
        "segments": len(rows),
        "poses_solved": sign_test("poses_solved"),
        "points": sign_test("points"),
        "support_rows": sign_test("support_rows"),
        "two_view_pct": sign_test("two_view_pct"),
        "ge3_view_pct": sign_test("ge3_view_pct"),
        "conflicts": sign_test("conflicts"),
    }
    Path(args.out).write_text(
        json.dumps(
            {"production_code": str(where), "summary": summary, "rows": rows},
            indent=2,
        )
    )
    print("\n=== paired sign test, treatment vs control ===")
    for field in (
        "poses_solved",
        "points",
        "support_rows",
        "two_view_pct",
        "ge3_view_pct",
        "conflicts",
    ):
        s = summary[field]
        print(
            f"{field:16} n={s['n']:<3} better={s['better']:<3} "
            f"same={s['same']:<3} worse={s['worse']:<3} "
            f"median_delta={s['median_delta']}"
        )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
