"""Pin down what OpenCV 5.0 actually changed, since the census tripped on it.

Three candidate explanations for `findFundamentalMat` returning None with an
UNINITIALISED mask on a 242-match pair:
  (a) the positional argument order changed between cv2 4.x and 5.x,
  (b) the method enum constants changed,
  (c) the fit genuinely fails and cv2 5.x leaves the mask uninitialised.
These are distinguishable. Test them.
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
from tower.world_builder.geometry import detect_and_describe, match_descriptors

SESS = (TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
        / 'sessions/dd5d13a2381e430db9b27c7da2cf2928')
kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines() if x.strip()]

print("cv2", cv2.__version__)
print("enums: FM_RANSAC=", cv2.FM_RANSAC, " RANSAC=", cv2.RANSAC,
      " LMEDS=", cv2.LMEDS, " USAC_MAGSAC=", getattr(cv2, 'USAC_MAGSAC', None))
print("\n--- findFundamentalMat doc ---")
print(cv2.findFundamentalMat.__doc__)
print("\n--- findHomography doc ---")
print((cv2.findHomography.__doc__ or '')[:600])


def load(idx):
    return detect_and_describe(decode_gray((SESS / kfs[idx]['image_relpath']).read_bytes()))


# A consecutive pair (should be an easy fit) and the weird long-gap pair.
for label, ia, ib in [("consecutive kf 12/13", 12, 13), ("long-gap kf 12/190", 12, 190)]:
    a, b = load(ia), load(ib)
    pa, pb = match_descriptors(a[0], a[1], b[0], b[1])
    print(f"\n===== {label}: {len(pa)} matches =====")
    if len(pa) < 8:
        continue
    for name, call in [
        ("F kw(method,ransacReprojThreshold,confidence)",
         lambda: cv2.findFundamentalMat(pa, pb, method=cv2.FM_RANSAC,
                                        ransacReprojThreshold=3.0, confidence=0.99)),
        ("F positional 4.x style (method,3.0,0.99)",
         lambda: cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)),
        ("F default method only",
         lambda: cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC)),
        ("F USAC_MAGSAC",
         lambda: cv2.findFundamentalMat(pa, pb, cv2.USAC_MAGSAC, 3.0, 0.99)),
        ("H kw(method,ransacReprojThreshold)",
         lambda: cv2.findHomography(pa, pb, method=cv2.RANSAC,
                                    ransacReprojThreshold=3.0)),
        ("H positional 4.x style (RANSAC,3.0)",
         lambda: cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)),
    ]:
        try:
            m, mask = call()
        except Exception as e:  # noqa: BLE001
            print(f"  {name:<46} EXCEPTION {type(e).__name__}: {e}")
            continue
        ok = m is not None
        u = np.unique(mask) if mask is not None else None
        binary = ok and mask is not None and set(u.tolist()) <= {0, 1}
        print(f"  {name:<46} model={'OK ' if ok else 'None'} "
              f"mask_unique={None if u is None else u[:6].tolist()} "
              f"inliers={int((mask.ravel() > 0).sum()) if mask is not None else None} "
              f"{'BINARY' if binary else 'NON-BINARY/GARBAGE'}")
