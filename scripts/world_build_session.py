#!/usr/bin/env python
"""Drive a World Builder mapping session offline, from frames on disk.

This is the V1 driver. It calls exactly the same `engine.observe()` a
future in-process module adapter would, which is why live-versus-offline
is a driver choice rather than an architecture choice: nothing about the
engine changes when frames arrive over a WebSocket instead of from a
directory.

Frame sources:

  --frames DIR     a directory of .jpg files, processed in sorted order.
                   This is what a recorded capture session looks like.
  --synthetic      render a synthetic walk instead. SYNTHETIC, NOT
                   PHYSICAL -- for exercising the pipeline with no
                   hardware, never for any claim about the real camera.

Intrinsics are unknown unless --intrinsics is given, and unknown
intrinsics mean the engine honestly produces no poses. There is no flag
that invents a focal length.

    .venv\\Scripts\\python.exe scripts/world_build_session.py --synthetic --name "Test Room"
    .venv\\Scripts\\python.exe scripts/world_build_session.py --frames data/capture/xyz
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.world_builder.backends import BACKEND_AUTO, BACKEND_NAMES  # noqa: E402
from tower.world_builder.engine import WorldBuilderEngine  # noqa: E402
from tower.world_builder.records import (  # noqa: E402
    CameraIntrinsics,
    camera_intrinsics_from_json_dict,
)
from tower.world_builder.store import WorldStore  # noqa: E402

DEFAULT_ROOT = Path("data/world_builder")


def load_frames(directory: Path) -> list[bytes]:
    paths = sorted(directory.glob("*.jpg"))
    if not paths:
        raise SystemExit(f"no .jpg frames found under {directory}")
    return [path.read_bytes() for path in paths]


def synthetic_frames(count: int, width: int, height: int):
    """Render a synthetic walk. Returns (jpegs, ground-truth intrinsics).

    Imports the test harness deliberately: it is the only renderer that
    exists, and duplicating it into production code to avoid a test import
    would be worse than the import.
    """
    from tests import synthetic_scene as ss

    camera_matrix = ss.camera_matrix(width, height)
    scene = ss.furnished_room()
    poses = ss.strafe(count, step=0.09)
    images = ss.render_sequence(scene, poses, camera_matrix, width, height)
    intrinsics = CameraIntrinsics(
        source="self_calibrated",
        model="pinhole",
        fx=float(camera_matrix[0, 0]),
        fy=float(camera_matrix[1, 1]),
        cx=float(camera_matrix[0, 2]),
        cy=float(camera_matrix[1, 2]),
        calibrated_width=width,
        calibrated_height=height,
    )
    return [ss.encode_jpeg(image) for image in images], intrinsics


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a World Builder mapping session over frames on disk."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--frames", type=Path, help="Directory of .jpg frames.")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Render a synthetic walk instead of reading frames.",
    )
    parser.add_argument("--synthetic-frames", type=int, default=16)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--name", default=None, help="World display name.")
    parser.add_argument("--world", default=None, help="Add to an existing world.")
    parser.add_argument(
        "--intrinsics",
        type=Path,
        help="JSON file holding a CameraIntrinsics record.",
    )
    parser.add_argument("--backend", choices=BACKEND_NAMES, default=BACKEND_AUTO)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    if bool(args.frames) == bool(args.synthetic):
        parser.error("exactly one of --frames or --synthetic is required")

    if args.synthetic:
        frames, intrinsics = synthetic_frames(
            args.synthetic_frames, args.width, args.height
        )
        frame_source = "synthetic"
    else:
        frames = load_frames(args.frames)
        intrinsics = CameraIntrinsics.unknown()
        frame_source = "recorded-capture"

    if args.intrinsics:
        intrinsics = camera_intrinsics_from_json_dict(
            json.loads(args.intrinsics.read_text(encoding="utf-8"))
        )

    store = WorldStore(args.root)
    engine = WorldBuilderEngine(store, backend_name=args.backend)
    world_id = args.world or engine.create_world(args.name)

    session_id = engine.start_session(
        world_id,
        intrinsics=intrinsics,
        frame_source=frame_source,
        declared_size=(args.width, args.height),
    )

    started = time.perf_counter()
    for index, payload in enumerate(frames):
        engine.observe(payload, source_seq=index, wire_seq=index)
    observe_seconds = time.perf_counter() - started
    summary = engine.stop_session()

    built = time.perf_counter()
    result = engine.build(world_id, session_id)
    build_seconds = time.perf_counter() - built

    report = {
        "world_id": world_id,
        "session_id": session_id,
        "frame_source": frame_source,
        "frames_observed": summary.frames_observed,
        "keyframes_accepted": summary.keyframes_accepted,
        "rejected_by_reason": summary.rejected_by_reason,
        "segments": summary.segments,
        "backend_id": result.backend_id,
        "downgraded_from": result.downgraded_from,
        "poses_solved": result.poses_solved,
        "poses_refused": result.poses_refused,
        "points": result.points,
        "scale_state": result.scale_state,
        "observe_ms_per_frame": round(
            observe_seconds * 1000 / max(len(frames), 1), 3
        ),
        "build_seconds": round(build_seconds, 3),
    }

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            print(f"{key:22s} {value}")
        if frame_source == "synthetic":
            print(
                "\nSYNTHETIC, NOT PHYSICAL: nothing here says anything about "
                "the Ray-Ban camera."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
