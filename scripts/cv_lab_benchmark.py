#!/usr/bin/env python
"""What each Experimental CV Lab experiment costs, and what it measures.

SYNTHETIC, NOT PHYSICAL. The timings are real measurements of this code on
this machine; the imagery driving them is rendered, so nothing here says
anything about the Ray-Ban camera's own content. A cost is portable in a
way a measurement of a scene is not -- read the milliseconds as budget
guidance and the metrics as "the experiment responds to this input", never
as a fact about a real room.

Every experiment is run at three resolutions, including the one the
glasses actually deliver today, because a per-frame budget that ignores
resolution is not a budget.

It also carries one deliberate A/B: sparse Lucas-Kanade against dense
Farneback for the same headline question. The Lab is where a rejected
alternative keeps its evidence, rather than becoming a comment saying
"dense was slower".

    .venv\\Scripts\\python.exe scripts/cv_lab_benchmark.py
    .venv\\Scripts\\python.exe scripts/cv_lab_benchmark.py --format json
    .venv\\Scripts\\python.exe scripts/cv_lab_benchmark.py --models
"""

import argparse
import contextlib
import json
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import synthetic_scene as ss  # noqa: E402
from tower.experiments import EXPERIMENTS, ExperimentSettings  # noqa: E402

# The resolution the glasses actually deliver today, first.
RESOLUTIONS = [(640, 360), (896, 504), (1280, 720)]

# Cheap enough to run by default. `depth` and `object_detection` need
# model weights and a download, so they are opt-in behind --models.
CHEAP = (
    "baseline",
    "edge_detection",
    "frame_quality",
    "feature_detection",
    "redaction_impact",
    "optical_flow",
)
MODEL_BACKED = ("object_detection", "depth")


def _timed(fn, repeat: int) -> dict:
    # One untimed warm-up. Without it the first sample carries one-off
    # initialisation and publishes an artifact as a cost.
    fn()
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return {
        "mean_ms": round(statistics.mean(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "max_ms": round(max(samples), 3),
    }


def render_pair(width: int, height: int) -> tuple[bytes, bytes]:
    """Two frames of a real sideways walk, so flow has something to find."""
    scene = ss.furnished_room()
    poses = ss.strafe(2, step=0.12)
    images = ss.render_sequence(
        scene, poses, ss.camera_matrix(width, height), width, height
    )
    return ss.encode_jpeg(images[0]), ss.encode_jpeg(images[1])


def bench_experiment(name: str, frames: tuple[bytes, bytes], repeat: int) -> dict:
    experiment = EXPERIMENTS[name]()
    # MiDaS's hub loader prints "Loading weights: None" straight to
    # stdout, which silently corrupts --format json. A machine-readable
    # stream must carry only the document, so anything a library prints
    # during load goes to stderr where an operator can still see it.
    with contextlib.redirect_stdout(sys.stderr):
        experiment.load(ExperimentSettings(device="cpu"))
    try:
        first, second = frames
        # Prime a stateful experiment with the first frame so the timed
        # call is doing the real work rather than the no-reference path.
        experiment.run(first)
        result = experiment.run(second)
        timing = _timed(lambda: experiment.run(second), repeat)
    finally:
        experiment.release()

    return {
        "experiment": name,
        "headline": result.result_label,
        "headline_value": round(result.result_value, 6),
        "timing": timing,
        "stage_ms": {k: round(v, 3) for k, v in result.stage_ms.items()},
        "metrics": {k: round(v, 6) for k, v in result.metrics.items()},
    }


def bench_flow_sparse_versus_dense(frames: tuple[bytes, bytes], repeat: int) -> dict:
    """The A/B that chose sparse LK, kept so the choice stays evidence."""
    import numpy as np

    grays = [
        cv2.imdecode(np.frombuffer(payload, dtype="uint8"), cv2.IMREAD_GRAYSCALE)
        for payload in frames
    ]
    previous, current = grays

    def sparse():
        seeds = cv2.goodFeaturesToTrack(previous, 300, 0.01, 8)
        cv2.calcOpticalFlowPyrLK(previous, current, seeds, None)

    def dense():
        cv2.calcOpticalFlowFarneback(
            previous, current, None, 0.5, 3, 15, 3, 5, 1.2, 0
        )

    sparse_timing = _timed(sparse, repeat)
    dense_timing = _timed(dense, max(repeat // 4, 1))
    return {
        "sparse_lk": sparse_timing,
        "dense_farneback": dense_timing,
        "dense_cost_multiple": round(
            dense_timing["mean_ms"] / max(sparse_timing["mean_ms"], 1e-6), 2
        ),
        "note": (
            "Same headline question, one answer 'good enough'. The Lab "
            "runs sparse; dense stays here as the measurement that chose."
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark every Experimental CV Lab experiment."
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument(
        "--models",
        action="store_true",
        help="Also benchmark the model-backed experiments (downloads weights).",
    )
    args = parser.parse_args(argv)

    names = list(CHEAP) + (list(MODEL_BACKED) if args.models else [])

    report = {
        "note": (
            "SYNTHETIC, NOT PHYSICAL. Timings measure this code on this "
            "machine; the imagery is rendered."
        ),
        "repeat": args.repeat,
        "resolutions": {},
    }

    for width, height in RESOLUTIONS:
        frames = render_pair(width, height)
        key = f"{width}x{height}"
        report["resolutions"][key] = {
            "jpeg_bytes": len(frames[1]),
            "experiments": [
                bench_experiment(name, frames, args.repeat) for name in names
            ],
            "optical_flow_sparse_vs_dense": bench_flow_sparse_versus_dense(
                frames, args.repeat
            ),
        }

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0

    print(report["note"])
    print(f"repeat={args.repeat}\n")
    for resolution, block in report["resolutions"].items():
        print(f"=== {resolution}  ({block['jpeg_bytes']} B jpeg) ===")
        print(f"{'experiment':<20}{'mean ms':>10}{'max ms':>10}  headline")
        for entry in block["experiments"]:
            print(
                f"{entry['experiment']:<20}"
                f"{entry['timing']['mean_ms']:>10.2f}"
                f"{entry['timing']['max_ms']:>10.2f}"
                f"  {entry['headline']}={entry['headline_value']:.4g}"
            )
        ab = block["optical_flow_sparse_vs_dense"]
        print(
            f"{'  flow sparse LK':<20}{ab['sparse_lk']['mean_ms']:>10.2f}\n"
            f"{'  flow dense FB':<20}{ab['dense_farneback']['mean_ms']:>10.2f}"
            f"      {ab['dense_cost_multiple']}x the cost"
        )
        print()

    print("Metrics for the delivered resolution:")
    delivered = report["resolutions"][f"{RESOLUTIONS[0][0]}x{RESOLUTIONS[0][1]}"]
    for entry in delivered["experiments"]:
        if not entry["metrics"]:
            continue
        print(f"\n  {entry['experiment']}")
        for name, value in entry["metrics"].items():
            print(f"    {name:<30} {value:>14.6g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
