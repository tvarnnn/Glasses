#!/usr/bin/env python
"""Where does replay memory actually go, and does it grow with keyframes?

`_Chain.forget_before` claims retained state is flat in the number of
keyframes, and there is a committed test asserting it -- on a SYNTHETIC
walk. This measures the same claim on a real long capture, and it
separates four things the RSS number smears together:

  1. `_Chain.observed` -- the dict `forget_before` prunes. Should be
     flat, bounded by EXTEND_REFERENCE_DEPTH frames of ORB features.
  2. `_Chain.support` / `_Chain.landmarks` / `_Chain.poses` -- the
     OPEN segment's output. Deliberately NOT pruned; grows within a
     segment and resets when the segment closes.
  3. `_LiveSolve._frozen` -- one frozen GeometryEstimate per CLOSED
     segment, held for the whole session. This is the term that grows
     monotonically with the walk, and no prune touches it.
  4. Everything else: OpenCV/numpy allocator arenas, the JPEG buffers,
     the interpreter. Visible only as RSS minus tracemalloc.

`tracemalloc` sees (1)-(3) and the Python side of (4); it does NOT see
OpenCV's C++ allocations. RSS sees everything. Both are reported,
because the gap between them IS the native-vs-Python split for memory.
"""

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
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


def deep_size(obj, seen=None) -> int:
    """Bytes retained by an object graph, counting numpy buffers properly.

    `sys.getsizeof` on an ndarray reports the header, not the data, which
    is exactly backwards for this measurement -- so ndarrays are charged
    their `nbytes` and not descended into.
    """
    if seen is None:
        seen = set()
    ident = id(obj)
    if ident in seen:
        return 0
    seen.add(ident)
    if isinstance(obj, np.ndarray):
        return obj.nbytes
    total = sys.getsizeof(obj, 0)
    if isinstance(obj, dict):
        for key, value in obj.items():
            total += deep_size(key, seen) + deep_size(value, seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            total += deep_size(item, seen)
    elif hasattr(obj, "__dict__"):
        total += deep_size(vars(obj), seen)
    elif hasattr(obj, "__slots__"):
        for slot in obj.__slots__:
            if hasattr(obj, slot):
                total += deep_size(getattr(obj, slot), seen)
    return total


def chain_breakdown(engine) -> dict:
    """Size the live solve's retained pieces, named individually."""
    solve = getattr(engine, "_live", None) or getattr(engine, "_live_solve", None)
    if solve is None:
        for name in vars(engine):
            value = getattr(engine, name)
            if value.__class__.__name__ == "_LiveSolve":
                solve = value
                break
    if solve is None:
        return {"error": "no _LiveSolve found on engine"}

    out = {
        "frozen_segments": len(getattr(solve, "_frozen", {})),
        "frozen_bytes": deep_size(getattr(solve, "_frozen", {})),
        "open_keyframe_ids": len(getattr(solve, "_open", [])),
    }
    backend = getattr(solve, "backend", None)
    chain = getattr(backend, "_chain", None)
    if chain is None:
        out["chain"] = None
        return out
    per_field = {}
    for slot in getattr(chain, "__slots__", ()):
        if hasattr(chain, slot):
            per_field[slot] = deep_size(getattr(chain, slot))
    out["chain"] = per_field
    out["chain_total_bytes"] = sum(per_field.values())
    out["chain_count"] = getattr(chain, "count", None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--every", type=int, default=100, help="checkpoint interval")
    ap.add_argument("--captures-root", type=Path, default=DEFAULT_CAPTURES_ROOT)
    args = ap.parse_args(argv)

    cv2.setRNGSeed(0)
    capture_dir = resolve_capture(args.captures_root, args.capture)

    import tower.world_builder.backends.classical as classical

    assert "Glasses-world-builder" in str(classical.__file__), classical.__file__
    assert hasattr(classical, "EXTEND_REFERENCE_DEPTH")

    proc = psutil.Process()
    frames = journal_frames(capture_dir)
    first, frames = first_observed_frame(frames)
    observed_size = observed_size_of(first)
    intrinsics = resolve_intrinsics(
        IntrinsicsStore(MAIN_WORLD_ROOT),
        observed_size,
        frame_source="capture-journal-replay",
    )
    if not intrinsics.is_known:
        raise SystemExit(f"no calibration for {observed_size}")

    store = WorldStore(args.scratch / f"mem-{args.capture}")
    engine = WorldBuilderEngine(store)
    world_id = engine.create_world(f"mem:{args.capture}")
    session_id = engine.start_session(
        world_id,
        intrinsics=intrinsics,
        frame_source="capture-journal-replay",
        declared_size=None,
        capture_id=capture_dir.name,
    )

    tracemalloc.start()
    checkpoints = []
    started = time.perf_counter()
    keyframes = 0
    for index, frame in enumerate(frames):
        result = engine.observe(
            frame.payload,
            received_at=frame.received_at,
            source_seq=frame.source_seq,
            wire_seq=frame.wire_seq,
            tx_seq=frame.tx_seq,
        )
        keyframes = result.keyframes_accepted
        if index % args.every == 0:
            current, peak = tracemalloc.get_traced_memory()
            breakdown = chain_breakdown(engine)
            checkpoints.append(
                {
                    "i": index,
                    "kf": keyframes,
                    "rss_mb": round(proc.memory_info().rss / 1e6, 2),
                    "py_current_mb": round(current / 1e6, 3),
                    "py_peak_mb": round(peak / 1e6, 3),
                    **{
                        f"break_{k}": v
                        for k, v in breakdown.items()
                        if not isinstance(v, dict)
                    },
                    "chain_fields": breakdown.get("chain"),
                }
            )
    replay_wall = time.perf_counter() - started

    final_breakdown = chain_breakdown(engine)
    py_current, py_peak = tracemalloc.get_traced_memory()
    rss_end_replay = proc.memory_info().rss

    engine.stop_session()
    t0 = time.perf_counter()
    build = engine.build(world_id, session_id)
    build_wall = time.perf_counter() - t0
    py_current_after, py_peak_after = tracemalloc.get_traced_memory()
    rss_after_build = proc.memory_info().rss
    top = tracemalloc.take_snapshot().statistics("lineno")[:20]
    tracemalloc.stop()

    report = {
        "capture_id": capture_dir.name,
        "prefix": args.capture,
        "redaction_on": redaction.model_path() is not None,
        "frames": index + 1,
        "keyframes": build.keyframes,
        "segments": build.segments,
        "points": build.points,
        "replay_wall_s": round(replay_wall, 3),
        "build_s": round(build_wall, 3),
        "rss_end_replay_mb": round(rss_end_replay / 1e6, 2),
        "rss_after_build_mb": round(rss_after_build / 1e6, 2),
        "py_current_end_replay_mb": round(py_current / 1e6, 3),
        "py_peak_end_replay_mb": round(py_peak / 1e6, 3),
        "py_current_after_build_mb": round(py_current_after / 1e6, 3),
        "py_peak_after_build_mb": round(py_peak_after / 1e6, 3),
        "final_breakdown": final_breakdown,
        "checkpoints": checkpoints,
        "top_python_allocations": [
            {
                "where": f"{s.traceback[0].filename}:{s.traceback[0].lineno}",
                "mb": round(s.size / 1e6, 3),
                "count": s.count,
            }
            for s in top
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"{args.capture} frames={report['frames']} kf={report['keyframes']} "
        f"seg={report['segments']}"
    )
    print(
        f"  RSS end-replay={report['rss_end_replay_mb']}MB "
        f"after-build={report['rss_after_build_mb']}MB"
    )
    print(
        f"  tracemalloc Python-side current={report['py_current_end_replay_mb']}MB "
        f"peak={report['py_peak_end_replay_mb']}MB (end of replay)"
    )
    print(f"  final live-solve breakdown: {json.dumps(final_breakdown, indent=2)}")
    print("  checkpoints (i, kf, rss_mb, py_current_mb, frozen_bytes, chain_bytes):")
    for c in checkpoints:
        print(
            f"    {c['i']:>5} kf={c['kf']:>4} rss={c['rss_mb']:>7} "
            f"py={c['py_current_mb']:>8} frozen={c.get('break_frozen_bytes')} "
            f"chain={c.get('break_chain_total_bytes')}"
        )
    print("  top Python allocation sites after build:")
    for row in report["top_python_allocations"][:12]:
        print(f"    {row['mb']:>8} MB  {row['count']:>7}  {row['where']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
