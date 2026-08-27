#!/usr/bin/env python
"""Characterise the ~84 deg direction error on lateral seed=1006.

THE CLAIM UNDER TEST

`ground_truth_accuracy.py` reports lateral seed=1006 at median 84.22 deg
and worst 87.79 deg -- a nearly perpendicular, confidently wrong pose on
the EASIEST motion for two-view geometry -- identically at both depths.
That was read as a live accuracy failure in shipped code.

THE ALTERNATIVE HYPOTHESIS THIS TESTS

`_errors()` pairs `derived["poses"][index]` with
`truth[index].position - truth[0].position`. That pairing is only valid
if BOTH hold:

  1. every rendered frame became an accepted keyframe, so the two lists
     are the same length and in the same order; and
  2. the session produced exactly ONE segment.

POSE_CONVENTION fixes `world_axes_origin: first_keyframe_camera`. A
SECOND segment restarts that origin, so its poses are expressed in a
different frame and subtracting truth[0] compares two different gauges.
Either violation produces a large, stable, depth-independent error --
exactly the observed signature -- without anything being wrong in the
reconstruction.

This prints what actually happened, so the two readings can be told
apart rather than argued about.
"""
import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(TOWER / "scripts" / "research" / "stage1_covisibility"))

from tests import synthetic_scene as ss  # noqa: E402
import ground_truth_accuracy as gta  # noqa: E402


def direction_error(estimated, truth):
    estimated = np.asarray(estimated, dtype=float)
    truth = np.asarray(truth, dtype=float)
    if np.linalg.norm(estimated) < 1e-9 or np.linalg.norm(truth) < 1e-9:
        return None
    estimated = estimated / np.linalg.norm(estimated)
    truth = truth / np.linalg.norm(truth)
    return math.degrees(math.acos(
        max(-1.0, min(1.0, abs(float(np.dot(estimated, truth)))))
    ))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1006,1000,1002")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = []
    with tempfile.TemporaryDirectory(prefix="wb-adv-1006-") as tmp:
        for seed in (int(s) for s in args.seeds.split(",")):
            poses_rows, truth = gta._reconstruct(
                Path(tmp) / f"s{seed}", seed, ss.strafe(args.frames, step=0.15)
            )
            segments = [r.get("segment_index") for r in poses_rows]
            row = {
                "seed": seed,
                "rendered_frames": len(truth),
                "persisted_poses": len(poses_rows),
                "distinct_segments": sorted(
                    {s for s in segments if s is not None}
                ),
                "statuses": [r.get("status") for r in poses_rows],
                "segment_of_each_pose": segments,
            }
            errs = []
            for index, r in enumerate(poses_rows):
                if index == 0 or r.get("translation") is None:
                    continue
                if index >= len(truth):
                    continue
                e = direction_error(
                    r["translation"],
                    np.asarray(truth[index].position)
                    - np.asarray(truth[0].position),
                )
                if e is not None:
                    errs.append({
                        "pose_index": index,
                        "segment": r.get("segment_index"),
                        "status": r.get("status"),
                        "error_deg": round(e, 3),
                        "translation": [round(v, 4) for v in r["translation"]],
                    })
            row["errors"] = errs
            row["median_deg"] = (
                round(float(np.median([e["error_deg"] for e in errs])), 3)
                if errs else None
            )
            out.append(row)

            print(f"\n=== seed {seed} ===")
            print(f"  rendered frames   {row['rendered_frames']}")
            print(f"  persisted poses   {row['persisted_poses']}")
            print(f"  distinct segments {row['distinct_segments']}")
            print(f"  statuses          {row['statuses']}")
            print(f"  segment per pose  {row['segment_of_each_pose']}")
            print(f"  median error      {row['median_deg']} deg")
            for e in errs:
                print(f"    idx {e['pose_index']} seg {e['segment']} "
                      f"{e['status']:>11s} err {e['error_deg']:>8.3f} "
                      f"t={e['translation']}")

    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
