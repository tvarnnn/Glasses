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


def solve(grays):
    win = [KeyframeInput(keyframe_id=f"kf{i}", image_gray=g)
           for i, g in enumerate(grays)]
    b = ClassicalTwoViewBackend(); b.prepare(intr)
    est = b.estimate_window(win)
    out = []
    for p in est.poses:
        if p.status != "solved":
            out.append(None); continue
        R = np.asarray(p.rotation); t = np.asarray(p.translation).reshape(3)
        out.append(-R.T @ t)          # camera position, as engine persists
    return out


for seed in (1000, 1005, 1006, 1007):
    imgs = ss.render_sequence(ss.furnished_room(seed=seed), poses, K, W, H)
    raw = [cv2.cvtColor(imgs[i], cv2.COLOR_BGR2GRAY) for i in SEL]
    jpg = [cv2.imdecode(np.frombuffer(ss.encode_jpeg(imgs[i]), np.uint8),
                        cv2.IMREAD_GRAYSCALE) for i in SEL]
    for tag, grays in (("raw", raw), ("jpeg", jpg)):
        cams = solve(grays)
        last = cams[-1]
        if last is None:
            print(f"seed {seed} {tag:4}: last pose unsolved"); continue
        truth = np.asarray(poses[SEL[-1]].position) - np.asarray(poses[SEL[0]].position)
        u = last / np.linalg.norm(last); v = truth / np.linalg.norm(truth)
        err = math.degrees(math.acos(max(-1, min(1, abs(float(np.dot(u, v)))))))
        print(f"seed {seed} {tag:4}: camera C={np.round(last,3)}  dir_err={err:6.2f}deg")
