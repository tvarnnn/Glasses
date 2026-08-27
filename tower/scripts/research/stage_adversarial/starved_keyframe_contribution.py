#!/usr/bin/env python
"""Do the feature-starved ACCEPTED keyframes contribute any geometry?

CONTEXT

`2026-08-27-feature-starvation-gate-refused.md` concludes "no keyframe
accepted at HEAD is feature-starved", called "conclusive by
construction" because a live gate rejected nothing.

Measuring the PERSISTED keyframe images at HEAD contradicts that: 22 of
1,712 accepted keyframes carry fewer than 15 ORB features, minimum 0
(MEASURED, this review).

The likely reconciliation is that the gate ran on `gray` -- the frame as
received -- while `_persist_keyframe` REDACTS before writing, and both
`build()` and the live path decode the REDACTED bytes (engine.py:342-353
says so explicitly). So the gate and the reconstruction were looking at
different images, and the gate was watching the wrong one.

That makes the doc's REASONING unsound but leaves its PRACTICAL
conclusion open: if the starved keyframes contribute no pose and no
support row, the gate is still unnecessary. This measures that directly,
which is the fair test.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(TOWER / "scripts"))

from tower.world_builder.geometry import detect_and_describe  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402
import world_builder_corpus_benchmark as bench  # noqa: E402
from tower.world_builder.schema import POSE_STATUS_SOLVED  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", default="C:/wb-adv/d1")
    ap.add_argument("--threshold", type=int, default=15)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    starved = []
    measured = 0
    missing = []
    for prefix in bench.PINNED_PREFIXES:
        store = WorldStore(Path(args.scratch) / prefix)
        ids = store.list_world_ids()
        if not ids:
            continue
        world_id = ids[0]
        session_id = store.list_session_ids(world_id)[0]
        keyframes = store.read_keyframes(world_id, session_id)
        derived = store.read_derived(world_id, session_id) or {}
        poses = derived.get("poses") or []
        support = derived.get("support") or []

        # support rows are (segment, frame, feature, point); frame is
        # segment-local, so count rows per (segment, frame).
        rows_by = defaultdict(int)
        for row in support:
            seg, frame, _feature, _point = (int(v) for v in row)
            rows_by[(seg, frame)] += 1

        # poses.json is in keyframe order; index it the same way.
        status_by_kfid = {}
        for row in poses:
            if isinstance(row, dict) and row.get("keyframe_id"):
                status_by_kfid[row["keyframe_id"]] = row.get("status")

        local_index = defaultdict(int)
        for kf in keyframes:
            seg = kf.segment_index
            frame = local_index[seg]
            local_index[seg] += 1
            # image_relpath, NOT keyframe_id + ".jpg". The keyframe id is
            # "<session>:<seq>" while the file on disk is "<seq>.jpg", so
            # composing the name from the id silently matches nothing --
            # the first version of this script did that and reported a
            # confident zero after measuring no images at all.
            # session_path() returns session.json, the FILE, so the base
            # for image_relpath ("images/00000001.jpg") is its parent.
            path = (
                store.session_path(world_id, session_id).parent
                / kf.image_relpath
            )
            if not path.exists():
                missing.append(str(path))
                continue
            measured += 1
            gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                continue
            kps, _ = detect_and_describe(gray)
            n = len(kps) if kps is not None else 0
            if n < args.threshold:
                starved.append({
                    "capture": prefix,
                    "keyframe_id": kf.keyframe_id,
                    "segment": int(seg),
                    "frame_in_segment": int(frame),
                    "orb_features": int(n),
                    "persisted_tracker_feature_count": kf.feature_count,
                    "pose_status": status_by_kfid.get(kf.keyframe_id),
                    "support_rows": int(rows_by.get((seg, frame), 0)),
                })

    solved = sum(1 for s in starved if s["pose_status"] == POSE_STATUS_SOLVED)
    with_rows = sum(1 for s in starved if s["support_rows"] > 0)
    out = {
        "scratch": args.scratch,
        "keyframes_measured": measured,
        "images_missing": len(missing),
        "threshold": args.threshold,
        "starved_accepted_keyframes": len(starved),
        "of_which_pose_solved": solved,
        "of_which_contribute_support_rows": with_rows,
        "total_support_rows_from_starved": sum(
            s["support_rows"] for s in starved
        ),
        "pose_status_histogram": {
            k: sum(1 for s in starved if s["pose_status"] == k)
            for k in {s["pose_status"] for s in starved}
        },
        "detail": starved,
    }
    print(json.dumps({k: v for k, v in out.items() if k != "detail"}, indent=2))
    print("\nfirst 15:")
    for s in starved[:15]:
        print(f"  {s['capture']} seg{s['segment']:>3d} f{s['frame_in_segment']:>3d} "
              f"orb={s['orb_features']:>4d} pose={s['pose_status']} "
              f"rows={s['support_rows']}")
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
