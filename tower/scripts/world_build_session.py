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

Intrinsics come from the intrinsics store, keyed by the resolution the
frames MEASURE at -- not by anything this process declares. `--intrinsics`
overrides the store. When neither yields a calibration for the observed
resolution the intrinsics stay unknown, the unposed backend runs, and the
engine honestly produces no poses. There is no flag that invents a focal
length, and nothing rescales a calibration from another resolution.

WHEN THE LOOKUP HAPPENS, AND WHY THAT IS THE HARD PART

The mapping session does not open until a frame has actually been
observed. That ordering is not tidiness; it is the fix for a bug that
cost the 2026-08-25 physical walk.

The Tower does not wait for a frame before attaching a builder. It
attaches at `stream_start`, from `_start_capture`, on the line after the
capture id is minted -- so on the live path this process routinely opens
against a capture directory whose journal has no rows in it yet. This
file used to resolve intrinsics right there, get "resolution not
observed", and freeze `unknown()` into the session record. The 360x640
frames arrived about a second later, a 360x640 calibration was sitting
in the store the whole time, and nothing ever looked again: 75 keyframes,
`backend: unposed`, `downgraded_from: classical`, zero poses.

It was not a race that could be tuned away by starting later. Importing
this module with OpenCV takes ~135ms on the Tower host and the first
frame lands ~1s after `stream_start`, so the worker won every time.

The session's intrinsics are a property of the PIXELS, so the session
cannot honestly be opened before a pixel exists. The world is created
immediately -- it costs nothing and gives the result channel something to
report -- and then this process blocks on the first frame, measures it,
and asks the store about the size it actually saw. A capture that closes
without ever delivering a frame ends that wait and opens an empty session
rather than hanging.

    .venv\\Scripts\\python.exe scripts/world_build_session.py --synthetic --name "Test Room"
    .venv\\Scripts\\python.exe scripts/world_build_session.py --frames data/capture/xyz
"""

import argparse
import io
import itertools
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.capture import CaptureFollower  # noqa: E402
from tower.world_builder.backends import (  # noqa: E402
    BACKEND_AUTO,
    BACKEND_NAMES,
    select_backend,
)
from tower.world_builder.engine import WorldBuilderEngine  # noqa: E402
from tower.world_builder.intrinsics_store import IntrinsicsStore  # noqa: E402
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
    # The size the RECORDER measured off this frame after decoding it,
    # when the source knows it. Carried on the frame rather than looked
    # up from the capture again, because the whole failure this guards
    # against was asking a directory a question about a frame that had
    # not been written into it yet. None means the source did not say,
    # and `observed_size_of` decodes the bytes instead.
    width: int | None = None
    height: int | None = None


def load_frames(directory: Path) -> list[ObservedFrame]:
    paths = sorted(directory.glob("*.jpg"))
    if not paths:
        raise SystemExit(f"no .jpg frames found under {directory}")
    return [
        ObservedFrame(payload=path.read_bytes(), source_seq=index, wire_seq=index)
        for index, path in enumerate(paths)
    ]


def first_observed_frame(frames):
    """Take the first frame off a source, and hand back the whole run.

    This is where the live path now WAITS. `follow_capture` is a
    generator that polls, so `next` blocks until the recorder appends a
    line or gives up on the capture -- which is exactly the wait that
    makes the resolution knowable.

    Returns `(first, frames)` where `frames` still yields that first
    frame: nothing may be consumed for measurement and then dropped, or
    the session silently starts one frame into the walk. `(None, empty)`
    when the source ends without ever producing one, which is a real
    state -- a phone that connects and drops -- and must not hang.
    """
    iterator = iter(frames)
    first = next(iterator, None)
    if first is None:
        return None, iter(())
    return first, itertools.chain((first,), iterator)


def observed_size_of(frame: ObservedFrame) -> tuple[int, int] | None:
    """The size of one frame, preferring what the recorder measured.

    The recorder decodes every frame it stores and journals the resulting
    width and height, so on the live path the answer is already in hand
    and costs nothing. Falling back to decoding the payload covers a
    source that carries no metadata at all.

    Never guesses. None means "this frame did not say and could not be
    read", and the caller turns that into unknown intrinsics rather than
    into a default resolution.
    """
    if isinstance(frame.width, int) and isinstance(frame.height, int):
        return (frame.width, frame.height)
    try:
        from PIL import Image

        with Image.open(io.BytesIO(frame.payload)) as image:
            return image.size
    except Exception:  # noqa: BLE001 -- an undecodable frame is not fatal here
        return None


def observed_size_from_frames(directory: Path) -> tuple[int, int] | None:
    """The size of the first jpeg in a directory, read from its header."""
    paths = sorted(directory.glob("*.jpg"))
    if not paths:
        return None
    try:
        from PIL import Image

        with Image.open(paths[0]) as image:
            return image.size
    except Exception:  # noqa: BLE001 -- an undecodable frame is not fatal here
        return None


def resolve_intrinsics(store: IntrinsicsStore, observed_size, *, frame_source):
    """Look up a calibration for the size the frames MEASURE at.

    Never falls back to another resolution and never rescales: a
    calibration wrong by a crop factor produces a plausible trajectory
    that is wrong, which is the worst failure available. A miss returns
    `unknown()` and the run proceeds exactly as an uncalibrated Tower has
    always proceeded -- but it now says so, loudly, at the top of the log.
    """
    if observed_size is None:
        known = store.list_resolutions()
        logger.warning(
            "[Tower][WorldBuilder] could not observe the frame resolution of "
            "this %s source, so no calibration was looked up. Intrinsics stay "
            "unknown: expect the unposed backend, 0 poses and 0 points. "
            "Calibrations on file: %s",
            frame_source,
            ", ".join(f"{w}x{h}" for w, h in known) or "none",
        )
        return CameraIntrinsics.unknown()

    width, height = observed_size
    intrinsics = store.lookup(width, height)
    if intrinsics.is_known:
        return intrinsics

    # The store already logged where it looked. This line adds what the
    # operator can DO about it, and is the answer to the question the
    # 2026-08-24 walk could not answer: "why is there no geometry?"
    known = store.list_resolutions()
    logger.warning(
        "[Tower][WorldBuilder] NO CALIBRATION for the observed %sx%s frames "
        "(looked for %s). Intrinsics stay unknown, so the unposed backend "
        "runs and this session will produce 0 poses and 0 points. "
        "Calibrations on file: %s. Fix: see docs/CALIBRATION.md and run "
        "scripts/calibrate_charuco.py on board views captured at %sx%s.",
        width,
        height,
        store.path_for(width, height),
        ", ".join(f"{w}x{h}" for w, h in known) or "none",
        width,
        height,
    )
    return CameraIntrinsics.unknown()


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
            width=frame.width,
            height=frame.height,
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
        help=(
            "JSON file holding a CameraIntrinsics record. Overrides the "
            "intrinsics store. Normally unnecessary: a calibration written "
            "by calibrate_charuco.py is discovered automatically from "
            "<root>/intrinsics/ by the observed frame resolution."
        ),
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

    # Keyed by the resolution frames MEASURE at, never by --width/--height.
    intrinsics_store = IntrinsicsStore(args.root)
    # Absolute, always, and before anything else. `--root data/world_builder`
    # resolves against THIS process's working directory, which the Tower
    # sets to TOWER_ROOT rather than inheriting from the shell that
    # started it. A relative path printed as-is cannot show that the
    # store and the calibrator disagreed about which directory they meant.
    logger.info(
        "[Tower][WorldBuilder] world root %s (cwd %s) -- calibrations on "
        "file: %s",
        args.root.resolve(),
        Path.cwd(),
        ", ".join(f"{w}x{h}" for w, h in intrinsics_store.list_resolutions())
        or "NONE",
    )

    capture_id = None
    synthetic_intrinsics = None
    if args.follow_capture:
        frames = follow_capture(
            args.follow_capture,
            poll_seconds=args.poll_seconds,
            max_idle_polls=args.max_idle_polls,
        )
        frame_source = "live-capture"
        capture_id = args.follow_capture.name
        # The sender chooses the stream size and DAT may change it
        # mid-walk. This process measures each frame; it declares nothing.
        declared_size = None
    elif args.synthetic:
        frames, synthetic_intrinsics = synthetic_frames(
            args.synthetic_frames, args.width, args.height
        )
        frame_source = "synthetic"
        # The only source whose size this process actually chose.
        declared_size = (args.width, args.height)
    else:
        frames = load_frames(args.frames)
        frame_source = "recorded-capture"
        # A directory of jpegs whose size was decided by whatever wrote
        # them. Measured per keyframe, not declared here.
        declared_size = None

    # The world BEFORE the wait below, not after. Creating it is a couple
    # of small writes and it is what the result channel looks for, so a
    # Tower whose phone has connected but not yet sent a frame reports a
    # world that exists and is empty rather than no world at all.
    store = WorldStore(args.root)
    engine = WorldBuilderEngine(store, backend_name=args.backend)
    world_id = args.world or engine.create_world(args.name)

    # Only now, with somewhere to put the answer, ask what size the
    # frames are -- and on the live path, wait until there IS a frame to
    # ask about. See "WHEN THE LOOKUP HAPPENS" in the module docstring.
    # What actually answered the calibration question, for the log below.
    # A path when the store was asked, a sentence when it was not: a log
    # that always prints a store path implies the store was consulted
    # even for a synthetic run, and this line exists precisely so nobody
    # has to guess which file the numbers came from.
    consulted = "the store"
    if args.synthetic:
        intrinsics = synthetic_intrinsics
        observed_size = declared_size
        consulted = "not consulted (the synthetic renderer supplies its own)"
    elif args.follow_capture:
        first, frames = first_observed_frame(frames)
        if first is None:
            # The capture closed, or gave up, without a single frame.
            # Not an error: it is a phone that connected and dropped. The
            # session still opens, honestly empty.
            logger.warning(
                "[Tower][WorldBuilder] capture %s delivered no frames, so no "
                "resolution was ever observed and no calibration was looked "
                "up. This session will be empty.",
                capture_id,
            )
            observed_size = None
        else:
            observed_size = observed_size_of(first)
            logger.info(
                "[Tower][WorldBuilder] first frame of capture %s observed at "
                "%s (source_seq=%s); resolving intrinsics against THAT, not "
                "against anything declared",
                capture_id,
                f"{observed_size[0]}x{observed_size[1]}"
                if observed_size
                else "an unreadable size",
                first.source_seq,
            )
        intrinsics = resolve_intrinsics(
            intrinsics_store, observed_size, frame_source=frame_source
        )
    else:
        observed_size = observed_size_from_frames(args.frames)
        intrinsics = resolve_intrinsics(
            intrinsics_store, observed_size, frame_source=frame_source
        )

    if consulted == "the store":
        consulted = (
            str(intrinsics_store.path_for(*observed_size))
            if observed_size
            else "not consulted (no resolution was ever observed)"
        )

    # An explicit file always wins over the store: it is the escape hatch
    # for a calibration that lives elsewhere, and for reproducing an old
    # build against the intrinsics it originally used. Unlike the store
    # this does NOT check the observed resolution -- the engine's
    # `_require_matching_resolution` does, per keyframe, and a hard
    # failure is the right answer when an operator names a file by hand.
    if args.intrinsics:
        intrinsics = camera_intrinsics_from_json_dict(
            json.loads(args.intrinsics.read_text(encoding="utf-8"))
        )
        consulted = f"{args.intrinsics} (--intrinsics override)"
        logger.info(
            "[Tower][WorldBuilder] using --intrinsics %s (source=%s, %sx%s), "
            "overriding the intrinsics store",
            args.intrinsics,
            intrinsics.source,
            intrinsics.calibrated_width,
            intrinsics.calibrated_height,
        )

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

    # Everything a physical run needs in order to answer "is calibration
    # active?" without opening a session record afterwards, on one line.
    # After the 2026-08-25 walk the answer existed only on disk, hours
    # later: the log said `intrinsics=unknown` and nothing about which
    # resolution had been observed or which file had been consulted, so
    # "the calibration is wrong" and "the calibration was never read"
    # looked identical.
    #
    # `announce=False` because the engine announces the selection itself
    # a few lines from now, in `_open_live_solve`. This asks the same
    # deterministic function what it will decide; it does not decide.
    selection = select_backend(args.backend, intrinsics, announce=False)
    logger.info(
        "[Tower][WorldBuilder] session %s in world %s: source=%s capture=%s "
        "root=%s observed=%s calibration=%s intrinsics=%s backend=%s "
        "(requested %s) rebuild_every=%s",
        session_id,
        world_id,
        frame_source,
        capture_id,
        args.root.resolve(),
        f"{observed_size[0]}x{observed_size[1]}" if observed_size else "UNOBSERVED",
        consulted,
        intrinsics.source,
        selection.backend.capabilities.backend_id,
        args.backend,
        args.rebuild_every,
    )
    if selection.was_downgraded:
        logger.warning(
            "[Tower][WorldBuilder] backend downgraded from %s: %s",
            selection.downgraded_from,
            selection.downgrade_reason,
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
