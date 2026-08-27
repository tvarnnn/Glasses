#!/usr/bin/env python
"""Can the CV_16S sharpness change flip a keyframe decision on REAL frames?

The lane's evidence is "the corpus replay produced identical keyframe
counts". That is a pass/fail on one sample. It does not say how CLOSE the
corpus came to flipping, so it cannot tell you whether the margin is
comfortable or whether the next capture flips.

This measures the margin directly. For every frame of every pinned
capture it computes the OLD and NEW sharpness, replays the exact gate
logic from keyframes.KeyframeGate._is_sharp_enough, and records:

  * the absolute-floor margin   |sharpness - 25.0|
  * the rolling-ratio margin    |sharpness/reference - 0.55|
  * the old-vs-new discrepancy  |old - new|

A flip requires the discrepancy to exceed the margin. The ratio of the
two is the safety factor, and the MINIMUM safety factor over the corpus
is the number that decides whether this change is safe.

It also reports any frame where the two implementations actually disagree
on the gate -- the direct flip search.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

TOWER = Path(__file__).resolve().parents[3]
for p in (str(TOWER), str(TOWER / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tower.world_builder.frontend import decode_gray  # noqa: E402
from tower.world_builder.keyframes import KeyframePolicy  # noqa: E402

import tower.world_builder.frontend as fe  # noqa: E402

assert "Glasses-world-builder" in str(Path(fe.__file__).resolve())


def old_sharpness(gray):
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def new_sharpness(gray):
    _, d = cv2.meanStdDev(cv2.Laplacian(gray, cv2.CV_16S))
    return float(d[0, 0] ** 2)


def gate(sharpness, recent, policy):
    """Verbatim from KeyframeGate._is_sharp_enough."""
    if sharpness < policy.min_sharpness:
        return False
    if len(recent) >= 5:
        reference = sorted(recent)[len(recent) // 2]
        if reference > 0 and sharpness / reference < policy.min_sharpness_ratio:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures", required=True)
    ap.add_argument("--prefixes", required=True,
                    help="comma-separated capture-id prefixes")
    args = ap.parse_args()

    policy = KeyframePolicy()
    print(f"min_sharpness={policy.min_sharpness} "
          f"min_sharpness_ratio={policy.min_sharpness_ratio} "
          f"window={policy.sharpness_window}")

    root = Path(args.captures)
    total = 0
    flips = 0
    worst_disc = 0.0
    worst_rel_disc = 0.0
    min_floor_safety = float("inf")
    min_ratio_safety = float("inf")
    closest_floor = None
    closest_ratio = None
    admitted_old = admitted_new = 0

    for prefix in args.prefixes.split(","):
        matches = [d for d in root.iterdir() if d.name.startswith(prefix)]
        if len(matches) != 1:
            raise SystemExit(f"prefix {prefix} matched {len(matches)}")
        cap = matches[0]
        frames_file = cap / "frames.jsonl"
        names = []
        if frames_file.exists():
            for line in frames_file.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                fn = rec.get("relpath")
                if fn:
                    names.append(cap / fn)
        if not names:
            names = sorted((cap / "frames").glob("*.jpg"))
        if not names:
            raise SystemExit(f"no frames resolved for {cap}")

        recent_old: list[float] = []
        recent_new: list[float] = []
        n_cap = 0
        for path in names:
            if not path.exists():
                continue
            try:
                gray = decode_gray(path.read_bytes())
            except Exception:
                continue
            o = old_sharpness(gray)
            n = new_sharpness(gray)
            disc = abs(o - n)
            worst_disc = max(worst_disc, disc)
            worst_rel_disc = max(worst_rel_disc, disc / max(o, 1e-30))

            # floor margin
            fm = abs(o - policy.min_sharpness)
            if disc > 0:
                s = fm / disc
                if s < min_floor_safety:
                    min_floor_safety = s
                    closest_floor = (cap.name[:8], path.name, o, n, fm, disc)

            # ratio margin (uses the OLD arm's own history, as the old code did)
            if len(recent_old) >= 5:
                ref = sorted(recent_old)[len(recent_old) // 2]
                if ref > 0:
                    rm = abs(o / ref - policy.min_sharpness_ratio)
                    rdisc = abs(o / ref - n / (sorted(recent_new)[len(recent_new) // 2]
                                               if recent_new else ref))
                    if rdisc > 0:
                        s = rm / rdisc
                        if s < min_ratio_safety:
                            min_ratio_safety = s
                            closest_ratio = (cap.name[:8], path.name,
                                             o / ref, rm, rdisc)

            go = gate(o, recent_old, policy)
            gn = gate(n, recent_new, policy)
            admitted_old += go
            admitted_new += gn
            if go != gn:
                flips += 1
                print(f"  FLIP {cap.name[:8]}/{path.name} old={o!r} "
                      f"new={n!r} old_gate={go} new_gate={gn}")

            recent_old.append(o)
            if len(recent_old) > policy.sharpness_window:
                recent_old.pop(0)
            recent_new.append(n)
            if len(recent_new) > policy.sharpness_window:
                recent_new.pop(0)
            n_cap += 1
        total += n_cap
        print(f"  {cap.name[:8]}  {n_cap} frames")

    print()
    print("=" * 70)
    print(f"frames examined:            {total}")
    print(f"gate decisions that FLIPPED: {flips}")
    print(f"sharp-enough count old/new:  {admitted_old} / {admitted_new}")
    print(f"max |old-new| absolute:      {worst_disc:.6e}")
    print(f"max |old-new| relative:      {worst_rel_disc:.6e}")
    print()
    print(f"MIN safety factor, absolute floor: {min_floor_safety:.3e}x")
    if closest_floor:
        c = closest_floor
        print(f"  closest frame {c[0]}/{c[1]}")
        print(f"    sharpness old={c[2]!r}")
        print(f"    sharpness new={c[3]!r}")
        print(f"    margin to 25.0 = {c[4]:.6e},  discrepancy = {c[5]:.6e}")
    print(f"MIN safety factor, rolling ratio:  {min_ratio_safety:.3e}x")
    if closest_ratio:
        c = closest_ratio
        print(f"  closest frame {c[0]}/{c[1]}  ratio={c[2]:.9f}")
        print(f"    margin to 0.55 = {c[3]:.6e},  discrepancy = {c[4]:.6e}")


if __name__ == "__main__":
    main()
