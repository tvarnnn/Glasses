#!/usr/bin/env python
"""Which frames did the engine actually seed from on seed=1006, and does
that pair reproduce the ~88 deg error?

Established so far:
  * engine persists t ~ [0.04, -0.04, 1.00] for pose 1 (forward), where
    truth is sideways -- MEASURED, seed1006.py;
  * the RAW seed pair over rendered frames 0 and 1 recovers -X to within
    0.32 deg -- MEASURED, seed1006_rootcause.py.

Two differences remain between those two runs, and this separates them:
  1. only 4 of 8 rendered frames became keyframes, so the engine's seed
     pair is (frame 0, frame k) for some k > 1, not (0, 1);
  2. the engine round-trips every frame through JPEG at quality 90,
     which moves ORB.

This replays the engine, then recomputes the seed pair from the exact
bytes the engine persisted, so the comparison uses the engine's own
frames and the engine's own pixels.
"""
import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(TOWER / "scripts" / "research" / "stage1_covisibility"))

from tests import synthetic_scene as ss  # noqa: E402
import ground_truth_accuracy as gta  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402
from tower.world_builder.geometry import (  # noqa: E402
    detect_and_describe, match_descriptors, homography_ratio,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1006,1000")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    K = ss.camera_matrix(gta.WIDTH, gta.HEIGHT)
    poses = ss.strafe(args.frames, step=0.15)
    out = []

    for seed in (int(s) for s in args.seeds.split(",")):
        tmp = Path(tempfile.mkdtemp(prefix=f"wb-adv-pair{seed}-"))
        rows, truth = gta._reconstruct(tmp / "run", seed, poses)
        store = WorldStore(tmp / "run" / f"seed{seed}")
        world_id = store.list_world_ids()[0]
        session_id = store.list_session_ids(world_id)[0]
        keyframes = store.read_keyframes(world_id, session_id)
        base = store.session_path(world_id, session_id).parent

        # source_seq identifies the rendered frame each keyframe came from.
        seqs = [kf.source_seq for kf in keyframes]
        imgs = []
        for kf in keyframes[:2]:
            path = base / kf.image_relpath
            imgs.append(cv2.imread(str(path), cv2.IMREAD_GRAYSCALE))

        record = {
            "seed": seed,
            "keyframe_source_seqs": seqs,
            "persisted_pose_1_translation": (
                [round(v, 4) for v in rows[1]["translation"]]
                if len(rows) > 1 and rows[1].get("translation") else None
            ),
        }

        if len(imgs) == 2 and all(i is not None for i in imgs):
            ka, da = detect_and_describe(imgs[0])
            kb, db = detect_and_describe(imgs[1])
            pa, pb = match_descriptors(ka, da, kb, db)
            E, mask = cv2.findEssentialMat(
                pa, pb, K, method=cv2.USAC_MAGSAC, prob=0.999, threshold=1.0
            )
            n, R, t, _ = cv2.recoverPose(E, pa, pb, K, mask=mask.copy())
            d = np.asarray(t).reshape(3)
            d = d / np.linalg.norm(d)

            # Truth for the engine's ACTUAL pair, not for frames 0 and 1.
            a_seq, b_seq = seqs[0], seqs[1]
            td = (np.asarray(poses[b_seq].position)
                  - np.asarray(poses[a_seq].position))
            td = td / np.linalg.norm(td)
            err = math.degrees(math.acos(max(-1.0, min(1.0, abs(
                float(np.dot(d, td)))))))

            # C = -R.T @ t is the conversion engine._pose_row applies.
            centre = -R.T @ np.asarray(t).reshape(3)

            record.update({
                "engine_pair": [int(a_seq), int(b_seq)],
                "matches": int(len(pa)),
                "r_h": (lambda v: None if v is None else round(float(v), 4))(
                    homography_ratio(pa, pb)
                ),
                "essential_inliers": int(mask.sum()) if mask is not None else 0,
                "cheirality_inliers": int(n),
                "recovered_t_direction": [round(float(v), 4) for v in d],
                "recovered_camera_centre": [round(float(v), 4) for v in centre],
                "direction_error_deg": round(err, 3),
            })
        out.append(record)
        print(json.dumps(record, indent=2), flush=True)

    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
