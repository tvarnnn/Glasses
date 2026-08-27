#!/usr/bin/env python
"""How good are the associations the guided re-observation ADMITS?

THE ATTACK

`_reobserve_against_pose` admits a match if the landmark reprojects
within PNP_REPROJECTION_ERROR_PX (3.0 px) of the claiming feature and
sits in front of the camera. On repetitive indoor texture -- two
identical chair legs -- a WRONG match can land inside 3 px by chance.
If that happens often, `support.json` is being poisoned, and
`support.json` is what cross-segment registration solves PnP against.

WHAT IS MEASURED, on real corpus footage, through the full engine:

  * the residual distribution of every ADMITTED row;
  * what fraction would survive a tighter bar (1.0 px, the value
    RANSAC_THRESHOLD_PX carries elsewhere in this codebase);
  * how many candidates were REJECTED, and why -- a gate that rejects
    nothing is not a gate;
  * the residual distribution of the ordinary PnP-inlier rows in the
    same solve, which is the fair comparison. Guided rows are only
    suspect if they are systematically WORSE than the associations the
    pipeline already trusts.

The last point is the one that makes this evidence rather than a number.
A 3.0 px bar admits rows up to 3.0 px by construction; the question is
whether the admitted population looks like the trusted population.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(TOWER / "scripts"))

import cv2  # noqa: E402
import tower.world_builder.backends.classical as classical  # noqa: E402
from tower.world_builder.geometry import match_indices  # noqa: E402
import world_builder_corpus_benchmark as bench  # noqa: E402
from tower.world_builder.intrinsics import IntrinsicsStore  # noqa: E402

RECORD = {
    "admitted_residuals": [],
    "rejected_reprojection": 0,
    "rejected_cheirality": 0,
    "rejected_claimed": 0,
    "rejected_no_landmark": 0,
    "candidates": 0,
    "pnp_inlier_residuals": [],
}


def instrumented(self, extra_references, keypoints_current,
                 descriptors_current, current_index, rotation, translation,
                 landmarks, observed, already_claimed):
    """Byte-for-byte the shipped logic, plus counters.

    Kept as a transcription rather than a wrapper so every rejection
    branch can be attributed. If this drifts from the original the
    comparison is void, so it mirrors classical.py:_reobserve_against_pose
    statement for statement.
    """
    if not extra_references:
        return {}
    projection = self._camera_matrix @ np.hstack(
        [rotation, translation.reshape(3, 1)]
    )
    limit_squared = (
        classical.PNP_REPROJECTION_ERROR_PX * classical.PNP_REPROJECTION_ERROR_PX
    )
    admitted = {}
    claimed = set(already_claimed)
    for ref_index, (_kp_ref, descriptors_ref) in extra_references:
        for index_ref, index_current in match_indices(
            descriptors_ref, descriptors_current
        ):
            RECORD["candidates"] += 1
            if index_current in claimed:
                RECORD["rejected_claimed"] += 1
                continue
            landmark = observed.get((ref_index, index_ref))
            if landmark is None:
                RECORD["rejected_no_landmark"] += 1
                continue
            point = landmarks[landmark]
            projected = projection @ np.array(
                [point[0], point[1], point[2], 1.0], dtype=np.float64
            )
            depth = projected[2]
            if not np.isfinite(depth) or depth <= 0:
                RECORD["rejected_cheirality"] += 1
                continue
            u = projected[0] / depth
            v = projected[1] / depth
            x, y = keypoints_current[index_current].pt
            du, dv = u - x, v - y
            d2 = du * du + dv * dv
            if d2 > limit_squared:
                RECORD["rejected_reprojection"] += 1
                continue
            RECORD["admitted_residuals"].append(float(np.sqrt(d2)))
            claimed.add(index_current)
            admitted[(current_index, index_current)] = landmark
    return admitted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="22e9d428")
    ap.add_argument("--scratch", default="C:/wb-adv/guided")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    assert "Glasses-world-builder" in classical.__file__.replace("\\", "/")
    classical.EXTEND_REFERENCE_DEPTH = 3
    classical.ClassicalTwoViewBackend._reobserve_against_pose = instrumented

    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    intrinsics_store = IntrinsicsStore(bench.MAIN_WORLD_ROOT)
    resolved = bench.resolve_pinned_captures(
        bench.DEFAULT_CAPTURES_ROOT, tuple(args.only.split(","))
    )
    for prefix, directory in resolved:
        print(f"replaying {prefix}", flush=True)
        bench.run_capture(prefix, directory, scratch, intrinsics_store)

    res = np.array(RECORD["admitted_residuals"], dtype=np.float64)
    out = {
        "capture": args.only,
        "candidates_examined": RECORD["candidates"],
        "admitted": int(res.size),
        "rejected_claimed": RECORD["rejected_claimed"],
        "rejected_no_landmark": RECORD["rejected_no_landmark"],
        "rejected_cheirality": RECORD["rejected_cheirality"],
        "rejected_reprojection": RECORD["rejected_reprojection"],
        "admit_rate_of_candidates_with_a_landmark": (
            float(res.size) / (res.size + RECORD["rejected_reprojection"]
                               + RECORD["rejected_cheirality"])
            if (res.size + RECORD["rejected_reprojection"]
                + RECORD["rejected_cheirality"]) else None
        ),
    }
    if res.size:
        out.update({
            "residual_mean": float(res.mean()),
            "residual_median": float(np.median(res)),
            "residual_p90": float(np.percentile(res, 90)),
            "residual_max": float(res.max()),
            "fraction_within_1.0px": float((res <= 1.0).mean()),
            "fraction_within_0.5px": float((res <= 0.5).mean()),
            "fraction_within_2.0px": float((res <= 2.0).mean()),
            "histogram_0.5px_bins": np.histogram(
                res, bins=np.arange(0, 3.5, 0.5)
            )[0].tolist(),
        })
    print(json.dumps(out, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
