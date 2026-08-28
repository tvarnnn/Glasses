"""OpenCV 5.0 changed what findFundamentalMat returns. Verify before trusting.

The census reported 41885 F-inliers on a pair with 242 matches, which is
impossible. Either the mask is not 0/1, or cv2 5.x returns a different
tuple shape than cv2 4.x. Find out which, on real frames, rather than
assuming.
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
from tower.world_builder.geometry import (LOWE_RATIO, detect_and_describe,
                                          match_descriptors)

SESS = (TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
        / 'sessions/dd5d13a2381e430db9b27c7da2cf2928')
kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]

print("cv2", cv2.__version__)
a = detect_and_describe(decode_gray((SESS / kfs[12]['image_relpath']).read_bytes()))
b = detect_and_describe(decode_gray((SESS / kfs[190]['image_relpath']).read_bytes()))
pa, pb = match_descriptors(a[0], a[1], b[0], b[1])
print("matches:", len(pa))

out = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)
print("findFundamentalMat returns", type(out), "len", len(out) if isinstance(out, tuple) else '-')
for idx, o in enumerate(out):
    print(f"  [{idx}] type={type(o).__name__} "
          f"shape={getattr(o, 'shape', None)} dtype={getattr(o, 'dtype', None)}")
    if isinstance(o, np.ndarray) and o.size < 20:
        print("      value:", o.ravel()[:12])
    elif isinstance(o, np.ndarray):
        u = np.unique(o)
        print(f"      unique values (first 8): {u[:8]}  sum={o.sum()}  size={o.size}")

print("\nfindHomography:")
outh = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
for idx, o in enumerate(outh):
    print(f"  [{idx}] type={type(o).__name__} shape={getattr(o, 'shape', None)} "
          f"dtype={getattr(o, 'dtype', None)}")
    if isinstance(o, np.ndarray) and o.size > 20:
        print(f"      unique (first 8): {np.unique(o)[:8]} sum={o.sum()} size={o.size}")

print("\nfindEssentialMat:")
oute = cv2.findEssentialMat(pa, pb, np.eye(3), cv2.RANSAC, 0.999, 1.0)
for idx, o in enumerate(oute):
    print(f"  [{idx}] type={type(o).__name__} shape={getattr(o, 'shape', None)} "
          f"dtype={getattr(o, 'dtype', None)}")
    if isinstance(o, np.ndarray) and o.size > 20:
        print(f"      unique (first 8): {np.unique(o)[:8]} sum={o.sum()} size={o.size}")
