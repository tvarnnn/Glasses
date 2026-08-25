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
  --follow-capture DIR
                   tail a capture directory the Tower is writing RIGHT NOW,
                   observing each frame as it lands. This is the live path:
                   arm the recorder (TOWER_CAPTURE_ROOT), walk the room,
                   and the world builds while you walk. It runs in a
                   SEPARATE PROCESS from the Tower on purpose -- the frame
                   path never pays for reconstruction, which is why an
                   expensive rebuild can run repeatedly mid-session.

                   Unlike --frames, this reads the JOURNAL, so source_seq,
                   tx_seq and receipt time survive. A directory glob would
                   throw them away and with them any ability to reason
                   about dropped frames.

Intrinsics are unknown unless --intrinsics is given, and unknown
intrinsics mean the engine honestly produces no poses. There is no flag
that invents a focal length.

    .venv\\Scripts\\python.exe scripts/world_build_session.py --synthetic --name "Test Room"
    .venv\\Scripts\\python.exe scripts/world_build_session.py --frames data/capture/xyz
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.capture import CaptureFollower  # noqa: E402
from tower.world_builder.backends import BACKEND_AUTO, BACKEND_NAMES  # noqa: E402
from tower.world_builder.engine import WorldBuilderEngine  # noqa: E402
from tower.world_builder.records import (  # noqa: E402
    CameraIntrinsics,
    camera_intrinsics_from_json_dict,
)
from tower.world_builder.store import WorldStore  # noqa: E402

DEFAULT_ROOT = Path("data/world_builder")

logger = logging.getLogger("tower.world_build_session")


@dataclass(frozen=True)
class ObservedFrame:
    """One frame plus whatever the wire actually told us about it.

    `received_at` is None for a source that has no recorded timestamp --
    a directory of loose jpegs. None means unknown and the engine stamps
    its own receipt time; inventing one here would fabricate a clock
    (Rule 3).
    """

    payload: bytes
    source_seq: int
    wire_seq: int | None = None
    tx_seq: int | None = None
    received_at: float | None = None


def load_frames(directory: Path) -> list[ObservedFrame]:
    paths = sorted(directory.glob("*.jpg"))
    if not paths:
        raise SystemExit(f"no .jpg frames found under {directory}")
    return [
        ObservedFrame(payload=path.read_bytes(), source_seq=index, wire_seq=index)
        for index, path in enumerate(paths)
    ]


def follow_capture(directory: Path, *, poll_seconds: float, max_idle_polls):
    """Yield frames from a capture directory as the Tower writes them."""
    if not directory.exists():
        raise SystemExit(f"no capture directory at {directory}")
    follower = CaptureFollower(directory, poll_seconds=poll_seconds)
    for frame in follower.follow(max_idle_polls=max_idle_polls):
        yield ObservedFrame(
            payload=frame.raw_bytes,
            source_seq=frame.source_seq,
            wire_seq=frame.wire_seq,
            tx_seq=frame.tx_seq,
            received_at=frame.received_at,
        )


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
    frames = [
        ObservedFrame(payload=ss.encode_jpeg(image), source_seq=index, wire_seq=index)
        for index, image in enumerate(images)
    ]
    return frames, intrinsics


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
    parser.add_argument(
        "--follow-capture",
        type=Path,
        default=None,
        help="Tail a capture directory the Tower is writing, building live.",
    )
    parser.add_argument(
        "--rebuild-every",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Rebuild derived geometry after every N accepted keyframes so a "
            "viewer sees the world grow. 0 (default) builds once at the end."
        ),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=0.25,
        help="How often to check a followed capture for new frames.",
    )
    parser.add_argument(
        "--max-idle-polls",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Give up after N quiet polls on a capture that never closes. "
            "Unset waits for the recorder to close it."
        ),
    )
    args = parser.parse_args(argv)

    # Configured here rather than at import, so importing this module for
    # a test does not reconfigure the test runner's logging. Only added
    # if nothing else has set logging up: when the Tower spawns this as a
    # capture worker its output is inherited, and a second handler would
    # double every line in that console.
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    chosen = [
        name
        for name, value in (
            ("--frames", args.frames),
            ("--synthetic", args.synthetic),
            ("--follow-capture", args.follow_capture),
        )
        if value
    ]
    if len(chosen) != 1:
        parser.error(
            "exactly one of --frames, --synthetic or --follow-capture is required"
        )
    if args.rebuild_every < 0:
        parser.error("--rebuild-every must not be negative")

    capture_id = None
    if args.follow_capture:
        frames = follow_capture(
            args.follow_capture,
            poll_seconds=args.poll_seconds,
            max_idle_polls=args.max_idle_polls,
        )
        intrinsics = CameraIntrinsics.unknown()
        frame_source = "live-capture"
        capture_id = args.follow_capture.name
        # The sender chooses the stream size and DAT may change it
        # mid-walk. This process measures each frame; it declares nothing.
        declared_size = None
    elif args.synthetic:
        frames, intrinsics = synthetic_frames(
            args.synthetic_frames, args.width, args.height
        )
        frame_source = "synthetic"
        # The only source whose size this process actually chose.
        declared_size = (args.width, args.height)
    else:
        frames = load_frames(args.frames)
        intrinsics = CameraIntrinsics.unknown()
        frame_source = "recorded-capture"
        # A directory of jpegs whose size was decided by whatever wrote
        # them. Measured per keyframe, not declared here.
        declared_size = None

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
        # Only for a source whose size this process actually CHOSE.
        #
        # --width/--height default to 480x360 and describe the synthetic
        # renderer. Passing them for a followed capture records a size
        # nobody measured: the 2026-08-24 session says `declared_width:
        # 480, declared_height: 360` while every one of its 155 keyframes
        # is 360x640. It was harmless only because unknown intrinsics
        # skip the resolution check -- the moment a calibration exists,
        # `_require_matching_resolution` turns it into a hard failure, or
        # worse, invites calibrating at the wrong resolution.
        #
        # Per-keyframe width/height are measured off the decoded frame
        # and were always right. None means unknown, which is the honest
        # value for a stream whose size the sender decides.
        declared_size=declared_size,
        capture_id=capture_id,
    )

    logger.info(
        "[Tower][WorldBuilder] session %s in world %s: source=%s capture=%s "
        "root=%s backend=%s intrinsics=%s rebuild_every=%s",
        session_id,
        world_id,
        frame_source,
        capture_id,
        args.root,
        args.backend,
        intrinsics.source,
        args.rebuild_every,
    )

    started = time.perf_counter()
    rebuilds = 0
    since_rebuild = 0
    accepted = 0
    for frame in frames:
        outcome = engine.observe(
            frame.payload,
            received_at=frame.received_at,
            source_seq=frame.source_seq,
            wire_seq=frame.wire_seq,
            tx_seq=frame.tx_seq,
        )
        if outcome.keyframe_id is None:
            continue
        accepted += 1
        since_rebuild += 1
        # Two keyframes is the minimum a two-view backend can say anything
        # about. Rebuilding on one would burn a build to produce an anchor
        # pose and nothing else.
        if args.rebuild_every and since_rebuild >= args.rebuild_every and accepted >= 2:
            rebuild_started = time.perf_counter()
            interim = engine.build(world_id, session_id)
            rebuilds += 1
            since_rebuild = 0
            # One line per rebuild, not per frame. Over a 15-minute walk
            # this process used to print nothing at all until it was
            # over, so "why isn't World Builder changing?" had no
            # answer short of reading the world directory by hand.
            logger.info(
                "[Tower][WorldBuilder] rebuild %s: %s keyframes -> %s "
                "positioned poses, %s points, %s segments in %.2fs",
                rebuilds,
                interim.keyframes,
                interim.poses_solved,
                interim.points,
                interim.segments,
                time.perf_counter() - rebuild_started,
            )
    observe_seconds = time.perf_counter() - started
    summary = engine.stop_session()

    built = time.perf_counter()
    result = engine.build(world_id, session_id)
    build_seconds = time.perf_counter() - built
    logger.info(
        "[Tower][WorldBuilder] session %s finished: %s frames, %s keyframes, "
        "%s segments, backend=%s (downgraded_from=%s), %s solved poses, "
        "%s points, scale=%s, final build %.2fs",
        session_id,
        summary.frames_observed,
        summary.keyframes_accepted,
        summary.segments,
        result.backend_id,
        result.downgraded_from,
        result.poses_solved,
        result.points,
        result.scale_state,
        build_seconds,
    )

    report = {
        "world_id": world_id,
        "session_id": session_id,
        "frame_source": frame_source,
        "frames_observed": summary.frames_observed,
        "keyframes_accepted": summary.keyframes_accepted,
        "rejected_by_reason": summary.rejected_by_reason,
        "segments": summary.segments,
        "rebuilds": rebuilds,
        "backend_id": result.backend_id,
        "downgraded_from": result.downgraded_from,
        "poses_solved": result.poses_solved,
        "poses_refused": result.poses_refused,
        "points": result.points,
        "scale_state": result.scale_state,
        "observe_ms_per_frame": round(
            observe_seconds * 1000 / max(summary.frames_observed, 1), 3
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
