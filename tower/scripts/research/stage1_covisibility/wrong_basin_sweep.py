import sys, math
sys.path.insert(0, r"C:\Users\tvllo\Projects\Glasses-world-builder\tower")
import numpy as np
import cv2
from tests import synthetic_scene as ss
from tower.world_builder.backend import KeyframeInput
from tower.world_builder.backends.classical import ClassicalTwoViewBackend
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.schema import INTRINSICS_SOURCE_SELF_CALIBRATED

W, H = 480, 360
K = ss.camera_matrix(W, H)
intr = CameraIntrinsics(
    source=INTRINSICS_SOURCE_SELF_CALIBRATED, model="pinhole",
    fx=float(K[0, 0]), fy=float(K[1, 1]), cx=float(K[0, 2]), cy=float(K[1, 2]),
    calibrated_width=W, calibrated_height=H)
poses = ss.strafe(8, step=0.15)
SEL = [0, 2, 4, 6]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 50


def final_err(grays):
    win = [KeyframeInput(keyframe_id=f"kf{i}", image_gray=g)
           for i, g in enumerate(grays)]
    b = ClassicalTwoViewBackend(); b.prepare(intr)
    est = b.estimate_window(win)
    p = est.poses[-1]
    if p.status != "solved":
        return None, p.status
    R = np.asarray(p.rotation); t = np.asarray(p.translation).reshape(3)
    C = -R.T @ t
    truth = np.asarray(poses[SEL[-1]].position) - np.asarray(poses[SEL[0]].position)
    u = C / np.linalg.norm(C); v = truth / np.linalg.norm(truth)
    return math.degrees(math.acos(max(-1, min(1, abs(float(np.dot(u, v))))))), "solved"


rows = []
for seed in range(2000, 2000 + N):
    imgs = ss.render_sequence(ss.furnished_room(seed=seed), poses, K, W, H)
    raw = [cv2.cvtColor(imgs[i], cv2.COLOR_BGR2GRAY) for i in SEL]
    jpg = [cv2.imdecode(np.frombuffer(ss.encode_jpeg(imgs[i]), np.uint8),
                        cv2.IMREAD_GRAYSCALE) for i in SEL]
    er, sr = final_err(raw)
    ej, sj = final_err(jpg)
    rows.append((seed, er, sr, ej, sj))
    if (er is not None and er > 20) or (ej is not None and ej > 20):
        print(f"  seed {seed}: raw={er if er is None else round(er,2)} ({sr})  "
              f"jpeg={ej if ej is None else round(ej,2)} ({sj})   <-- LARGE")

ok = [(s, a, b) for s, a, _x, b, _y in rows if a is not None and b is not None]
print(f"\nseeds tested: {len(rows)}   both solved: {len(ok)}")
for thr in (10, 20, 45):
    nr = sum(1 for _s, a, _b in ok if a > thr)
    nj = sum(1 for _s, _a, b in ok if b > thr)
    print(f"  error > {thr:2d} deg:  raw {nr:3d} ({100*nr/max(len(ok),1):5.1f}%)   "
          f"jpeg {nj:3d} ({100*nj/max(len(ok),1):5.1f}%)")
flips = [(s, a, b) for s, a, b in ok if b > 20 and a < 10]
print(f"  JPEG-INDUCED flips (raw < 10 deg, jpeg > 20 deg): {len(flips)} "
      f"({100*len(flips)/max(len(ok),1):.1f}%)")
for s, a, b in flips:
    print(f"     seed {s}: raw {a:.2f} -> jpeg {b:.2f}")
unsolved = [(s, sr, sj) for s, _a, sr, _b, sj in rows if sr != "solved" or sj != "solved"]
print(f"  seeds where a final pose was refused: {len(unsolved)}")
