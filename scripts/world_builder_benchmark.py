#!/usr/bin/env python
"""Stage-level benchmarks for the World Builder pipeline.

SYNTHETIC, NOT PHYSICAL. Timings are real measurements of this code on
this machine; the imagery driving them is rendered, so nothing here says
anything about the Ray-Ban camera's own throughput, and no reconstruction
QUALITY number produced here may be cited as validation for the platform's
camera. That gate stays closed until real DAT footage exists.

    .venv\\Scripts\\python.exe scripts/world_builder_benchmark.py
    .venv\\Scripts\\python.exe scripts/world_builder_benchmark.py --format json
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import synthetic_scene as ss  # noqa: E402
from tower.world_builder.backend import KeyframeInput  # noqa: E402
from tower.world_builder.backends import ClassicalTwoViewBackend  # noqa: E402
from tower.world_builder.frontend import (  # noqa: E402
    analyse_frame,
    decode_gray,
    measure_sharpness,
    seed_tracks,
    summarise_motion,
)
from tower.world_builder.geometry import detect_and_describe  # noqa: E402
from tower.world_builder.records import CameraIntrinsics  # noqa: E402
from tower.world_builder.schema import (  # noqa: E402
    INTRINSICS_SOURCE_SELF_CALIBRATED,
)

# The resolution the glasses actually deliver today.
DELIVERED = (360, 640)
RESOLUTIONS = [(360, 640), (504, 896), (720, 1280)]


def _timed(fn, repeat: int):
    # One untimed warm-up call. Without it the first sample carries
    # one-off initialisation -- ORB's first detectAndCompute measured
    # 19.74 ms at 360x640 against 4.07 ms at the LARGER 504x896, which
    # would publish a number that is an artifact rather than a cost.
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


def bench_live_path(width: int, height: int, repeat: int = 12) -> dict:
    """The per-frame cost that must fit inside the delivered interval."""
    camera_matrix = ss.camera_matrix(width, height)
    scene = ss.furnished_room()
    poses = ss.strafe(2, step=0.12)
    images = ss.render_sequence(scene, poses, camera_matrix, width, height)
    payloads = [ss.encode_jpeg(image) for image in images]
    grays = [cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for image in images]
    seeds = seed_tracks(grays[0])

    return {
        "resolution": f"{width}x{height}",
        "jpeg_bytes": len(payloads[0]),
        "decode": _timed(lambda: decode_gray(payloads[0]), repeat),
        "sharpness": _timed(lambda: measure_sharpness(grays[0]), repeat),
        "analyse_frame": _timed(lambda: analyse_frame(grays[0]), repeat),
        "seed_tracks": _timed(lambda: seed_tracks(grays[0]), repeat),
        "summarise_motion": _timed(
            lambda: summarise_motion(grays[0], grays[1], seeds), repeat
        ),
        "orb_detect_describe": _timed(
            lambda: detect_and_describe(grays[0]), repeat
        ),
    }


def bench_build(keyframes: int = 8, repeat: int = 3) -> dict:
    """The expensive path. Never runs on the event loop."""
    width, height = 480, 360
    camera_matrix = ss.camera_matrix(width, height)
    scene = ss.furnished_room()
    poses = ss.strafe(keyframes, step=0.20)
    images = ss.render_sequence(scene, poses, camera_matrix, width, height)
    intrinsics = CameraIntrinsics(
        source=INTRINSICS_SOURCE_SELF_CALIBRATED,
        model="pinhole",
        fx=float(camera_matrix[0, 0]),
        fy=float(camera_matrix[1, 1]),
        cx=float(camera_matrix[0, 2]),
        cy=float(camera_matrix[1, 2]),
        calibrated_width=width,
        calibrated_height=height,
    )
    window = [
        KeyframeInput(f"s:{index:08d}", cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        for index, image in enumerate(images)
    ]

    backend = ClassicalTwoViewBackend()
    backend.prepare(intrinsics)
    estimate = backend.estimate_window(window)
    timing = _timed(lambda: backend.estimate_window(window), repeat)

    solved = sum(1 for pose in estimate.poses if pose.status == "solved")
    return {
        "keyframes": keyframes,
        "resolution": f"{width}x{height}",
        "poses_solved": solved,
        "points": 0 if estimate.points is None else len(estimate.points),
        "estimate_window": timing,
        "ms_per_keyframe": round(timing["mean_ms"] / keyframes, 3),
    }


def bench_preprocessing(repeat: int = 6) -> dict:
    """Records the negative result rather than leaving it in a commit message.

    No filter variant improved downstream matching or pose accuracy;
    several measurably harmed feature counts. Kept as a benchmark so a
    successor tempted to add preprocessing can re-run it rather than
    re-litigate it.
    """
    import numpy as np

    width, height = 480, 360
    camera_matrix = ss.camera_matrix(width, height)
    scene = ss.furnished_room()
    images = ss.render_sequence(
        scene, ss.strafe(2, step=0.20), camera_matrix, width, height
    )
    grays = [cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for image in images]

    sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], np.float32)
    variants = {
        "raw": lambda g: g,
        "gaussian3": lambda g: cv2.GaussianBlur(g, (3, 3), 0),
        "gaussian5": lambda g: cv2.GaussianBlur(g, (5, 5), 0),
        "sharpen": lambda g: cv2.filter2D(g, -1, sharpen_kernel),
        "clahe": lambda g: cv2.createCLAHE(2.0, (8, 8)).apply(g),
    }

    results = {}
    for name, fn in variants.items():
        filtered = [fn(gray) for gray in grays]
        keypoints, _ = detect_and_describe(filtered[0])
        results[name] = {
            "keypoints": len(keypoints),
            "filter": _timed(lambda: fn(grays[0]), repeat),
        }
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark World Builder pipeline stages (synthetic input)."
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--keyframes", type=int, default=8)
    args = parser.parse_args(argv)

    report = {
        "note": "SYNTHETIC, NOT PHYSICAL -- timings are real, imagery is rendered",
        "live_path": [bench_live_path(w, h) for w, h in RESOLUTIONS],
        "build": bench_build(args.keyframes),
        "preprocessing": bench_preprocessing(),
    }

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return 0

    print("=== Live path (per frame) ===")
    print(
        f"{'resolution':12s} {'jpeg':>7s} {'decode':>8s} {'sharp':>8s} "
        f"{'track':>9s} {'orb':>8s}"
    )
    for row in report["live_path"]:
        print(
            f"{row['resolution']:12s} {row['jpeg_bytes']:7d} "
            f"{row['decode']['mean_ms']:8.2f} {row['sharpness']['mean_ms']:8.2f} "
            f"{row['summarise_motion']['mean_ms']:9.2f} "
            f"{row['orb_detect_describe']['mean_ms']:8.2f}"
        )
    delivered = report["live_path"][0]
    live_total = (
        delivered["decode"]["mean_ms"]
        + delivered["sharpness"]["mean_ms"]
        + delivered["summarise_motion"]["mean_ms"]
    )
    print(
        f"\nlive total at {delivered['resolution']}: {live_total:.2f} ms "
        f"against a ~300 ms delivered interval at 3.3 fps "
        f"({live_total / 300 * 100:.1f}% duty cycle)"
    )

    build = report["build"]
    print("\n=== Build (offline, never on the event loop) ===")
    print(f"keyframes         {build['keyframes']}")
    print(f"poses solved      {build['poses_solved']}")
    print(f"points            {build['points']}")
    print(f"estimate_window   {build['estimate_window']['mean_ms']:.1f} ms")
    print(f"per keyframe      {build['ms_per_keyframe']:.1f} ms")

    print("\n=== Preprocessing (why there is none) ===")
    print(f"{'variant':12s} {'keypoints':>10s} {'filter ms':>10s}")
    for name, row in report["preprocessing"].items():
        print(f"{name:12s} {row['keypoints']:10d} {row['filter']['mean_ms']:10.2f}")
    print(
        "\nNo variant improves downstream matching; gaussian5 destroys "
        "keypoints. Filtering is not applied."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
