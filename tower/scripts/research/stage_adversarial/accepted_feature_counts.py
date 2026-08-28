#!/usr/bin/env python
"""Minimum ORB feature count among keyframes ACCEPTED at HEAD.

WHY THIS IS AN INDEPENDENT CHECK

`2026-08-27-feature-starvation-gate-refused.md` argues the refusal is
"conclusive by construction": the gate was live, it rejected nothing,
therefore no accepted keyframe is feature-starved. That argument depends
on the gate having been positioned where it saw every accepted keyframe
AND on it having been active in the run that produced the histogram.
Neither is checkable now -- the gate was reverted.

This does not rely on either. It reads the keyframe images the engine
ACTUALLY PERSISTED during a HEAD replay and runs the same detector the
gate would have run. Feature count is a property of the image, so if the
minimum over accepted keyframes is >= the threshold the gate would have
used, the conclusion holds regardless of how the gate was wired.

Threshold reference: the doc's arithmetic is that a frame with fewer
than MIN_INLIERS features can never reach MIN_INLIERS inliers.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))

from tower.world_builder.geometry import detect_and_describe  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", default="C:/wb-adv/d1")
    ap.add_argument("--threshold", type=int, default=15)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # ONLY the pinned captures. run_controls() builds extra worlds under
    # `control-<name>` in the same scratch root from SYNTHETIC degenerate
    # inputs -- blank frames among them -- and a glob that swept those in
    # would report a 0-feature "accepted keyframe" that no real capture
    # ever produced. The first version of this script did exactly that
    # and counted 1729 keyframes against the corpus's 1712.
    import world_builder_corpus_benchmark as bench  # noqa: E402
    images = []
    for prefix in bench.PINNED_PREFIXES:
        images.extend(
            sorted((Path(args.scratch) / prefix).glob(
                "worlds/*/sessions/*/images/*.jpg"
            ))
        )
    images = sorted(images)
    if not images:
        print(f"NO IMAGES under {args.scratch}", file=sys.stderr)
        return 2

    counts = []
    for path in images:
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            print(f"unreadable {path}", file=sys.stderr)
            continue
        keypoints, _ = detect_and_describe(gray)
        counts.append(len(keypoints) if keypoints is not None else 0)

    arr = np.array(counts, dtype=np.int64)
    below = int((arr < args.threshold).sum())
    out = {
        "scratch": args.scratch,
        "accepted_keyframes_measured": int(arr.size),
        "orb_min": int(arr.min()),
        "orb_p01": float(np.percentile(arr, 1)),
        "orb_p05": float(np.percentile(arr, 5)),
        "orb_median": float(np.median(arr)),
        "orb_max": int(arr.max()),
        "threshold": args.threshold,
        "count_below_threshold": below,
        "count_below_20": int((arr < 20).sum()),
        "count_below_100": int((arr < 100).sum()),
        "verdict": (
            "NO ACCEPTED KEYFRAME IS FEATURE STARVED"
            if below == 0 else
            f"{below} ACCEPTED KEYFRAMES ARE BELOW {args.threshold}"
        ),
    }
    print(json.dumps(out, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
