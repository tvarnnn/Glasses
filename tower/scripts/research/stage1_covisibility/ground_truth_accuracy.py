#!/usr/bin/env python
"""Does looking further back make the TRAJECTORY better or worse?

THE ONLY KNOWN-ANSWER TEST IN THIS PROGRAMME.

Every corpus number tonight is self-consistency: no surveyed geometry, no
reference trajectory, no metric scale. So a change can raise
`poses_solved`, raise landmark multiplicity, and still be producing a
worse map, and nothing measured on real footage would say so.

Synthetic scenes have exact ground truth. This runs the REAL engine --
`observe()` per frame, then `build()`, the same path the corpus benchmark
drives -- over rendered walks with known camera positions, at two values
of EXTEND_REFERENCE_DEPTH, and compares each solved pose's translation
DIRECTION against the true direction.

Direction, not position: a monocular reconstruction is scale-free and a
two-view translation is defined only up to sign, so the axis is what can
honestly be compared. This mirrors `_direction_error_degrees` in
tests/test_world_builder_pose_accuracy.py rather than inventing a second
metric.

Several seeds and several motion types, because one scene is one scene
and the failure modes differ: lateral motion is the best case for
two-view geometry, forward motion puts the epipole in the image, and
pure rotation should be refused outright rather than solved.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np

TOWER = Path(__file__).resolve().parents[3]
if str(TOWER) not in sys.path:
    sys.path.insert(0, str(TOWER))

WIDTH, HEIGHT = 480, 360


def _resolve():
    import tower.world_builder.backends.classical as classical

    where = Path(classical.__file__).resolve()
    if "Glasses-world-builder" not in str(where):
        raise SystemExit(f"REFUSING: production code resolved to {where}")
    return classical, where


def _intrinsics(matrix):
    from tower.world_builder.records import CameraIntrinsics
    from tower.world_builder.schema import INTRINSICS_SOURCE_SELF_CALIBRATED

    return CameraIntrinsics(
        source=INTRINSICS_SOURCE_SELF_CALIBRATED,
        model="pinhole",
        fx=float(matrix[0, 0]),
        fy=float(matrix[1, 1]),
        cx=float(matrix[0, 2]),
        cy=float(matrix[1, 2]),
        calibrated_width=WIDTH,
        calibrated_height=HEIGHT,
    )


def _reconstruct(tmp_root, seed, poses):
    """The real pipeline, exactly as the accuracy tests drive it."""
    from tests import synthetic_scene as ss
    from tower.world_builder.engine import WorldBuilderEngine
    from tower.world_builder.redaction import FaceRedactor
    from tower.world_builder.store import WorldStore

    matrix = ss.camera_matrix(WIDTH, HEIGHT)
    images = ss.render_sequence(
        ss.furnished_room(seed=seed), poses, matrix, WIDTH, HEIGHT
    )
    store = WorldStore(Path(tmp_root) / f"seed{seed}")
    engine = WorldBuilderEngine(
        store,
        # Redaction off: this measures geometry, and a face detector has
        # no business influencing a pose-accuracy number.
        redactor_factory=lambda: FaceRedactor(path=Path(tmp_root) / "absent.onnx"),
    )
    world_id = engine.create_world("Accuracy")
    session_id = engine.start_session(
        world_id,
        intrinsics=_intrinsics(matrix),
        frame_source="synthetic",
        declared_size=(WIDTH, HEIGHT),
    )
    for index, image in enumerate(images):
        engine.observe(ss.encode_jpeg(image), source_seq=index)
    engine.stop_session()
    engine.build(world_id, session_id)
    derived = store.read_derived(world_id, session_id)
    return ([] if derived is None else derived["poses"]), poses


def _direction_error_degrees(estimated, truth):
    estimated = np.asarray(estimated, dtype=float)
    truth = np.asarray(truth, dtype=float)
    if np.linalg.norm(estimated) < 1e-9 or np.linalg.norm(truth) < 1e-9:
        return None
    estimated = estimated / np.linalg.norm(estimated)
    truth = truth / np.linalg.norm(truth)
    cosine = abs(float(np.dot(estimated, truth)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _errors(rows, truth):
    out = []
    for index, row in enumerate(rows):
        if index == 0 or row.get("translation") is None:
            continue
        if index >= len(truth):
            continue
        error = _direction_error_degrees(
            row["translation"],
            np.asarray(truth[index].position) - np.asarray(truth[0].position),
        )
        if error is not None:
            out.append(error)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depths", default="1,3")
    ap.add_argument("--seeds", default="1000,1001,1002,1003")
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from tests import synthetic_scene as ss

    classical, where = _resolve()
    print(f"production code: {where}")

    motions = {
        "lateral": lambda: ss.strafe(8, step=0.15),
        "forward": lambda: ss.forward_walk(8, step=0.15),
    }
    depths = [int(d) for d in args.depths.split(",")]
    seeds = [int(s) for s in args.seeds.split(",")]

    original = classical.EXTEND_REFERENCE_DEPTH
    rows = []
    try:
        for name, make in motions.items():
            for seed in seeds:
                per_depth = {}
                for depth in depths:
                    classical.EXTEND_REFERENCE_DEPTH = depth
                    scratch = Path(args.scratch) / f"{name}_{seed}_d{depth}"
                    scratch.mkdir(parents=True, exist_ok=True)
                    poses, truth = _reconstruct(scratch, seed, make())
                    errs = _errors(poses, truth)
                    solved = sum(
                        1 for p in poses if p.get("status") == "solved"
                    )
                    per_depth[depth] = {
                        "solved": solved,
                        "n_errors": len(errs),
                        "median_deg": (
                            round(statistics.median(errs), 4) if errs else None
                        ),
                        "worst_deg": round(max(errs), 4) if errs else None,
                    }
                rows.append(
                    {"motion": name, "seed": seed, "depths": per_depth}
                )
                a = per_depth[depths[0]]
                b = per_depth[depths[-1]]
                print(
                    f"  {name:8} seed={seed}  "
                    f"median {a['median_deg']} -> {b['median_deg']}  "
                    f"worst {a['worst_deg']} -> {b['worst_deg']}  "
                    f"solved {a['solved']} -> {b['solved']}"
                )
    finally:
        classical.EXTEND_REFERENCE_DEPTH = original

    control, treatment = depths[0], depths[-1]

    def summarise(field, lower_is_better=True):
        pairs = [
            (r["depths"][control][field], r["depths"][treatment][field])
            for r in rows
            if r["depths"][control][field] is not None
            and r["depths"][treatment][field] is not None
        ]
        better = sum(
            1 for a, b in pairs if (b < a) if lower_is_better
        ) or sum(1 for a, b in pairs if (b > a) and not lower_is_better)
        worse = sum(1 for a, b in pairs if (b > a)) if lower_is_better else sum(
            1 for a, b in pairs if b < a
        )
        same = len(pairs) - better - worse
        deltas = [b - a for a, b in pairs]
        return {
            "n": len(pairs),
            "better": better,
            "same": same,
            "worse": worse,
            "median_delta": (
                round(statistics.median(deltas), 4) if deltas else None
            ),
        }

    summary = {
        "control_depth": control,
        "treatment_depth": treatment,
        "median_deg": summarise("median_deg"),
        "worst_deg": summarise("worst_deg"),
        "solved": summarise("solved", lower_is_better=False),
    }
    print("\n=== ground-truth direction error, treatment vs control ===")
    for field in ("median_deg", "worst_deg", "solved"):
        s = summary[field]
        print(
            f"{field:12} n={s['n']:<3} better={s['better']:<3} "
            f"same={s['same']:<3} worse={s['worse']:<3} "
            f"median_delta={s['median_delta']}"
        )
    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "production_code": str(where),
                    "summary": summary,
                    "rows": rows,
                },
                indent=2,
            )
        )
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
