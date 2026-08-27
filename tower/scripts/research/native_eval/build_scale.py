#!/usr/bin/env python
"""Does build() scale superlinearly in keyframe count?

There are TWO build paths and they have different costs, so they are
timed separately:

  WARM  -- `engine.build()` on the engine that just observed the walk.
           `_LiveSolve` already solved every segment incrementally, so
           this is a flush: read the journal, join the carried
           estimates, write JSON.

  COLD  -- `engine.build()` on a FRESH engine over the same store, with
           no carried live state. `_live_estimates` returns empty and
           every segment is re-solved from scratch off the persisted
           JPEGs. This is the path whose complexity the docstring at
           engine.py:1001 worries about, and the one a native port would
           be replacing.

Both are wall-clocked with `time.perf_counter` and unprofiled. A
separate `--profile` run attributes the cold build with cProfile, which
inflates Python frames relative to native ones and is therefore reported
alongside, never instead of, the unprofiled wall time.

Replays go to --scratch. Nothing is written to the main checkout.
"""

import argparse
import cProfile
import io
import json
import pstats
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


def one(prefix: str, scratch: Path, captures_root: Path, profile: bool) -> dict:
    cv2.setRNGSeed(0)
    capture_dir = resolve_capture(captures_root, prefix)
    proc = psutil.Process()

    frames = journal_frames(capture_dir)
    first, frames = first_observed_frame(frames)
    if first is None:
        return {"prefix": prefix, "error": "no frames"}
    observed_size = observed_size_of(first)
    intrinsics = resolve_intrinsics(
        IntrinsicsStore(MAIN_WORLD_ROOT),
        observed_size,
        frame_source="capture-journal-replay",
    )
    if not intrinsics.is_known:
        return {"prefix": prefix, "error": f"no calibration for {observed_size}"}

    root = scratch / f"bs-{prefix}"
    store = WorldStore(root)
    engine = WorldBuilderEngine(store)
    world_id = engine.create_world(f"buildscale:{prefix}")
    session_id = engine.start_session(
        world_id,
        intrinsics=intrinsics,
        frame_source="capture-journal-replay",
        declared_size=None,
        capture_id=capture_dir.name,
    )

    t0 = time.perf_counter()
    observed = 0
    for frame in frames:
        engine.observe(
            frame.payload,
            received_at=frame.received_at,
            source_seq=frame.source_seq,
            wire_seq=frame.wire_seq,
            tx_seq=frame.tx_seq,
        )
        observed += 1
    replay_wall = time.perf_counter() - t0
    engine.stop_session()

    t0 = time.perf_counter()
    warm = engine.build(world_id, session_id)
    warm_wall = time.perf_counter() - t0
    # COLD: a brand-new engine over the same store. No carried solve.
    cv2.setRNGSeed(0)
    cold_engine = WorldBuilderEngine(WorldStore(root))
    rss_before = proc.memory_info().rss
    t0 = time.perf_counter()
    cold = cold_engine.build(world_id, session_id)
    cold_wall = time.perf_counter() - t0
    rss_after = proc.memory_info().rss

    row = {
        "prefix": prefix,
        "capture_id": capture_dir.name,
        "frames": observed,
        "keyframes": warm.keyframes,
        "segments": warm.segments,
        "poses_solved_warm": warm.poses_solved,
        "poses_solved_cold": cold.poses_solved,
        "points_warm": warm.points,
        "points_cold": cold.points,
        "replay_wall_s": round(replay_wall, 4),
        "build_warm_s": round(warm_wall, 4),
        "build_cold_s": round(cold_wall, 4),
        "cold_rss_delta_mb": round((rss_after - rss_before) / 1e6, 2),
    }

    if profile:
        cv2.setRNGSeed(0)
        prof_engine = WorldBuilderEngine(WorldStore(root))
        pr = cProfile.Profile()
        pr.enable()
        prof_engine.build(world_id, session_id)
        pr.disable()
        stream = io.StringIO()
        pstats.Stats(pr, stream=stream).sort_stats("tottime").print_stats(30)
        row["cold_profile"] = stream.getvalue()

    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures", nargs="+", required=True)
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--captures-root", type=Path, default=DEFAULT_CAPTURES_ROOT)
    args = ap.parse_args(argv)

    import tower.world_builder.backends.classical as classical

    assert "Glasses-world-builder" in str(classical.__file__), classical.__file__
    assert hasattr(classical, "EXTEND_REFERENCE_DEPTH")
    print(f"module      {classical.__file__}")
    print(f"redaction   {redaction.model_path()}")

    rows = []
    for prefix in args.captures:
        row = one(prefix, args.scratch, args.captures_root, args.profile)
        rows.append(row)
        if "error" in row:
            print(f"{prefix:>10}  SKIPPED: {row['error']}")
            continue
        print(
            f"{prefix:>10}  frames={row['frames']:>5} kf={row['keyframes']:>4} "
            f"seg={row['segments']:>3} pts={row['points_cold']:>6}  "
            f"replay={row['replay_wall_s']:>8.3f}s "
            f"warm_build={row['build_warm_s']:>7.3f}s "
            f"cold_build={row['build_cold_s']:>7.3f}s"
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
