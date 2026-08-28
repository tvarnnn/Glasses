"""Confirm, against the SHIPPED function, that r_H reads an uninitialised mask.

`tower/world_builder/geometry.py::homography_ratio` discards the returned
model and reads the mask regardless:

    _, h_mask = cv2.findHomography(...)
    _, f_mask = cv2.findFundamentalMat(...)
    h_inliers = int(h_mask.sum()) if h_mask is not None else 0

On OpenCV 5.0 a FAILED RANSAC returns model=None and leaves the mask
uninitialised, so `.sum()` reads whatever was in that buffer. The test is
non-determinism: call the SAME shipped function on the SAME two frames
repeatedly. A correct implementation is deterministic up to RANSAC's own
randomness in the inlier COUNT; reading uninitialised memory shows up as
counts far outside [0, n_matches].

This is a MEASUREMENT, not a fix. Production is not modified.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]
sys.path.insert(0, str(TOWER_ROOT))

import cv2
import numpy as np

from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import (detect_and_describe, homography_ratio,
                                          match_descriptors)

SESS = (TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
        / 'sessions/dd5d13a2381e430db9b27c7da2cf2928')
kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]


def feats(idx):
    return detect_and_describe(decode_gray((SESS / kfs[idx]['image_relpath']).read_bytes()))


print(f"cv2 {cv2.__version__}\n")
for label, ia, ib in [("healthy consecutive pair kf12/kf13", 12, 13),
                      ("degenerate long-gap pair kf12/kf190", 12, 190)]:
    a, b = feats(ia), feats(ib)
    pa, pb = match_descriptors(a[0], a[1], b[0], b[1])
    print(f"{label}: {len(pa)} ratio-test matches")

    # What the SHIPPED function returns, ten times.
    vals = [homography_ratio(pa, pb) for _ in range(10)]
    print(f"  shipped homography_ratio() x10 -> "
          f"{[None if v is None else round(v, 4) for v in vals]}")

    # And the raw counts it is built from, with the model checked.
    H, hm = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
    F, fm = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)
    raw_h = int(hm.sum()) if hm is not None else 0        # what production does
    raw_f = int(fm.sum()) if fm is not None else 0
    safe_h = int((hm.ravel() > 0).sum()) if (H is not None and hm is not None) else 0
    safe_f = int((fm.ravel() > 0).sum()) if (F is not None and fm is not None) else 0
    print(f"  H model={'OK' if H is not None else 'None'}  "
          f"F model={'OK' if F is not None else 'None'}")
    print(f"  production-style counts (mask.sum(), model ignored): "
          f"h={raw_h} f={raw_f}   <- must be <= {len(pa)}")
    print(f"  model-checked counts:                              "
          f"h={safe_h} f={safe_f}")
    if raw_h > len(pa) or raw_f > len(pa):
        print(f"  *** IMPOSSIBLE: inlier count exceeds the number of matches ***")
    print()
