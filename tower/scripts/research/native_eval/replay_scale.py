#!/usr/bin/env python
"""Per-frame and per-build scaling probe for World Builder replay.

Reuses `world_builder_corpus_benchmark`'s journal read and
`world_build_session`'s intrinsics resolution so the replay is the one
the live driver runs. The ONLY thing added is instrumentation:

  * `time.perf_counter` around every single `engine.observe()` call,
    recorded with the frame index and the keyframe count accumulated so
    far, so a per-frame cost that grows with session length is visible
    as a trend rather than as an average.
  * `psutil` RSS sampled every frame (checked at import; the run aborts
    if psutil is absent rather than silently reporting nothing).
  * `time.perf_counter` around `stop_session()` and `build()`.

Nothing here writes into the main checkout. `--scratch` is required.
Run with cwd = <worktree>/tower so `redaction.DEFAULT_MODEL_PATH`
(a RELATIVE path resolved against cwd) finds the YuNet model and face
redaction is ON -- which is the live configuration and 22.8% of replay
runtime.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import cv2  # noqa: E402
import psutil  # noqa: E402

from scripts.world_build_session import (  # noqa: E402
    first_observed_frame,
    observed_size_of,
    resolve_intrinsics,
)
from scripts.world_builder_corpus_benchmark import (  # noqa: E402
    DEFAULT_CAPTURES_ROOT,
    MAIN_WORLD_ROOT,
    journal_frames,
)
from tower.world_builder.engine import WorldBuilderEngine  # noqa: E402
from tower.world_builder.intrinsics_store import IntrinsicsStore  # noqa: E402
from tower.world_builder import redaction  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402


def resolve_capture(root: Path, prefix: str) -> Path:
    matches = [d for d in sorted(root.iterdir()) if d.name.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"prefix {prefix!r} matched {len(matches)} captures")
    return matches[0]


def run(prefix: str, scratch: Path, captures_root: Path) -> dict:
    cv2.setRNGSeed(0)
    capture_dir = resolve_capture(captures_root, prefix)

    # Assert the branch under test, in-process, next to the numbers.
    import tower.world_builder.backends.classical as classical

    if "Glasses-world-builder" not in str(classical.__file__):
        raise SystemExit(f"WRONG BRANCH: {classical.__file__}")
    if not hasattr(classical, "EXTEND_REFERENCE_DEPTH"):
        raise SystemExit("WRONG BRANCH: EXTEND_REFERENCE_DEPTH missing")

    redaction_model = redaction.model_path()
    proc = psutil.Process()

    frames = journal_frames(capture_dir)
    first, frames = first_observed_frame(frames)
    if first is None:
        raise SystemExit(f"{capture_dir.name}: no frames")
    observed_size = observed_size_of(first)
    intrinsics = resolve_intrinsics(
        IntrinsicsStore(MAIN_WORLD_ROOT),
        observed_size,
        frame_source="capture-journal-replay",
    )
    if not intrinsics.is_known:
        raise SystemExit(f"no calibration for {observed_size}")

    store = WorldStore(scratch / prefix)
    engine = WorldBuilderEngine(store)
    world_id = engine.create_world(f"scale:{prefix}")
    session_id = engine.start_session(
        world_id,
        intrinsics=intrinsics,
        frame_source="capture-journal-replay",
        declared_size=None,
        capture_id=capture_dir.name,
    )

    rss0 = proc.memory_info().rss
    samples = []
    peak_rss = rss0
    observe_total = 0.0
    t_replay0 = time.perf_counter()
    for index, frame in enumerate(frames):
        t0 = time.perf_counter()
        result = engine.observe(
            frame.payload,
            received_at=frame.received_at,
            source_seq=frame.source_seq,
            wire_seq=frame.wire_seq,
            tx_seq=frame.tx_seq,
        )
        dt = time.perf_counter() - t0
        observe_total += dt
        rss = proc.memory_info().rss
        if rss > peak_rss:
            peak_rss = rss
        samples.append(
            {
                "i": index,
                "ms": round(dt * 1000.0, 4),
                "kf": result.keyframes_accepted,
                "accepted": result.outcome == "accept",
                "rss_mb": round(rss / 1e6, 2),
            }
        )
    replay_wall = time.perf_counter() - t_replay0

    t0 = time.perf_counter()
    summary = engine.stop_session()
    stop_wall = time.perf_counter() - t0

    rss_before_build = proc.memory_info().rss
    t0 = time.perf_counter()
    build = engine.build(world_id, session_id)
    build_wall = time.perf_counter() - t0
    rss_after_build = proc.memory_info().rss
    peak_rss = max(peak_rss, rss_after_build)

    return {
        "capture_id": capture_dir.name,
        "prefix": prefix,
        "redaction_model": str(redaction_model) if redaction_model else None,
        "redaction_on": redaction_model is not None,
        "classical_module": str(classical.__file__),
        "frames_observed": summary.frames_observed,
        "keyframes": build.keyframes,
        "segments": build.segments,
        "poses_solved": build.poses_solved,
        "poses_refused": build.poses_refused,
        "points": build.points,
        "replay_wall_s": round(replay_wall, 4),
        "observe_total_s": round(observe_total, 4),
        "stop_session_s": round(stop_wall, 4),
        "build_s": round(build_wall, 4),
        "rss_start_mb": round(rss0 / 1e6, 2),
        "rss_before_build_mb": round(rss_before_build / 1e6, 2),
        "rss_after_build_mb": round(rss_after_build / 1e6, 2),
        "rss_peak_mb": round(peak_rss / 1e6, 2),
        "samples": samples,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--captures-root", type=Path, default=DEFAULT_CAPTURES_ROOT)
    ap.add_argument(
        "--no-samples",
        action="store_true",
        help="drop the per-frame table from the JSON (build-scaling sweeps)",
    )
    args = ap.parse_args(argv)

    if "Glasses-world-builder" not in str(args.scratch.resolve()):
        # Cheap guard against writing derived geometry into the main
        # checkout's data/world_builder, where another lane's state lives.
        if "Glasses\\tower\\data" in str(args.scratch.resolve()):
            raise SystemExit(f"refusing to write into main checkout: {args.scratch}")

    report = run(args.capture, args.scratch, args.captures_root)
    if args.no_samples:
        report.pop("samples")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"{report['prefix']}  frames={report['frames_observed']} "
        f"kf={report['keyframes']} seg={report['segments']} "
        f"pts={report['points']}  replay={report['replay_wall_s']}s "
        f"build={report['build_s']}s  rss_peak={report['rss_peak_mb']}MB "
        f"redaction={'ON' if report['redaction_on'] else 'OFF'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
