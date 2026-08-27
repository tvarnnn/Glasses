#!/usr/bin/env python
"""What the CV Lab productization COSTS, on top of the experiment itself.

A different question from `cv_lab_benchmark.py`, which measures what each
experiment costs to run. This measures what was added around it: the
per-frame bookkeeping and attribution, the status document, and the
result channel that publishes it. The point is to establish that the Lab
can coexist with a Tower that is also answering frames, recording a
capture and supervising a world build -- not to celebrate a small number.

SYNTHETIC, NOT PHYSICAL. The imagery is rendered and the client is a
`TestClient` in this process, so nothing here says anything about the
Ray-Ban camera or about a Tailscale link. What IS real is the code path:
the same `CVLab`, the same status builder, the same envelope.

Read the four sections as:

    frame            what one frame pays for bookkeeping + attribution
    status           what building the document costs, and how it scales
                     with subscribers
    channel          what a subscription costs per published snapshot
    memory           whether a long run grows

    .venv\\Scripts\\python.exe scripts/cv_lab_overhead_benchmark.py
    .venv\\Scripts\\python.exe scripts/cv_lab_overhead_benchmark.py --format json
    .venv\\Scripts\\python.exe scripts/cv_lab_overhead_benchmark.py --frames 5000
"""

import argparse
import asyncio
import gc
import io
import json
import logging
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import psutil
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.cv_lab import CVLab  # noqa: E402
from tower.experiments import EXPERIMENTS, ExperimentSettings  # noqa: E402
from tower.results.envelope import compute_revision  # noqa: E402

# The resolution the glasses actually deliver today.
WIDTH, HEIGHT = 640, 360

# The experiment used wherever the point is the OVERHEAD rather than the
# experiment. `baseline` is the cheapest registered one (~1 ms), so it is
# the harshest denominator: overhead that disappears against `depth` at
# 26 ms is still visible here.
CHEAPEST = "baseline"

# A stateless experiment with a real metrics bag, for the case where
# bookkeeping actually has something to do.
BUSIEST = "frame_quality"


def _frame() -> bytes:
    rng = np.random.default_rng(11)
    array = rng.integers(0, 255, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG", quality=50)
    return buffer.getvalue()


def _timed(call, repeat: int) -> dict:
    """Mean, median and p95 over `repeat` calls, after one warm-up.

    p95 rather than max: a single sample on a machine running three other
    lanes says more about the machine than the code, and the Tower this
    was measured on had two world-builder benchmarks running beside it.
    """
    call()
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        call()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {
        "mean_ms": round(statistics.fmean(samples), 5),
        "median_ms": round(statistics.median(samples), 5),
        "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 5),
        "samples": len(samples),
    }


def measure_frame_overhead(repeat: int) -> dict:
    """One frame through the Lab, against the same frame through the bare
    experiment. The difference is what productization costs per frame."""
    payload = _frame()
    rows = {}
    for experiment_id in (CHEAPEST, BUSIEST):
        bare = EXPERIMENTS[experiment_id]()
        bare.load(ExperimentSettings())
        direct = _timed(lambda: bare.run(payload), repeat)
        bare.release()

        lab = asyncio.run(_armed(experiment_id))

        def through_lab():
            lab.process(payload)
            lab.frame_provenance()

        wrapped = _timed(through_lab, repeat)
        lab.release()

        overhead = wrapped["mean_ms"] - direct["mean_ms"]
        rows[experiment_id] = {
            "experiment_ms": direct,
            "through_lab_ms": wrapped,
            "overhead_ms": round(overhead, 5),
            "overhead_percent": round(100 * overhead / direct["mean_ms"], 2),
        }
    return rows


async def _armed(experiment_id: str) -> CVLab:
    lab = CVLab(experiment_id, connection_count=lambda: 1)
    await lab.load_initial()
    return lab


def measure_status_cost(repeat: int) -> dict:
    """What building the one document costs, and what hashing it costs.

    Both matter because the result channel does both on every poll: the
    hub builds a snapshot and `compute_revision` canonicalises it to
    decide whether anything changed.
    """
    rows = {}
    for experiment_id in (CHEAPEST, BUSIEST):
        lab = asyncio.run(_armed(experiment_id))
        payload = _frame()
        for _ in range(20):
            lab.process(payload)
            lab.frame_provenance()

        build = _timed(lab.status, repeat)
        document = lab.status()
        revision = _timed(lambda: compute_revision(document), repeat)
        serialise = _timed(lambda: json.dumps(document), repeat)
        rows[experiment_id] = {
            "build_ms": build,
            "revision_ms": revision,
            "serialise_ms": serialise,
            "bytes": len(json.dumps(document)),
            "metrics": len(document["run"]["metrics"]),
        }
        lab.release()
    return rows


def measure_channel_cost(repeat: int) -> dict:
    """A full poll pass with N subscribers, through the real hub.

    The hub computes each distinct target ONCE and offers the result to
    every channel, so this is where that claim is checked rather than
    asserted: ten subscribers must not cost ten status builds.
    """
    from fastapi.testclient import TestClient

    from tower.main import create_app

    logging.disable(logging.CRITICAL)
    client = TestClient(create_app())
    client.__enter__()
    try:
        hub = client.app.state.result_hub
        hub._poll_seconds = 3600.0
        hub._heartbeat_seconds = 0.0
        rows = {}
        sockets = []
        try:
            for count in (1, 4, 8):
                while len(sockets) < count:
                    ws = client.websocket_connect("/ws").__enter__()
                    ws.send_json(
                        {
                            "type": "result_subscribe",
                            "cartridge": "experimental_cv",
                            "result_type": "status",
                        }
                    )
                    sockets.append(ws)

                async def poll():
                    await hub.poll_once()

                rows[f"subscribers_{count}"] = _timed(
                    lambda: client.portal.call(poll), repeat
                )
        finally:
            for ws in sockets:
                try:
                    ws.__exit__(None, None, None)
                except Exception:
                    pass
        return rows
    finally:
        client.__exit__(None, None, None)
        logging.disable(logging.NOTSET)


def measure_memory(frames: int) -> dict:
    """Does a long run grow.

    `handoff.md` 9.3 says a `stream_stop` MAY NEVER ARRIVE, so a run is
    open for as long as the Tower is up. A run that grew per frame would
    be the unbounded store this whole design avoids -- measured rather
    than asserted.
    """
    process = psutil.Process()
    payload = _frame()
    lab = asyncio.run(_armed(BUSIEST))
    for _ in range(200):
        lab.process(payload)
        lab.frame_provenance()
    gc.collect()
    before = process.memory_info().rss

    start = time.perf_counter()
    for _ in range(frames):
        lab.process(payload)
        lab.frame_provenance()
    elapsed = time.perf_counter() - start
    gc.collect()
    after = process.memory_info().rss

    document = lab.status()
    lab.release()
    return {
        "frames": frames,
        "rss_before_bytes": before,
        "rss_after_bytes": after,
        "rss_growth_bytes": after - before,
        "rss_growth_bytes_per_frame": round((after - before) / frames, 4),
        "wall_s": round(elapsed, 3),
        "frames_per_second": round(frames / elapsed, 1),
        "document_bytes": len(json.dumps(document)),
        "tracked_metrics": len(document["run"]["metrics"]),
    }


def _render(report: dict) -> str:
    lines = [
        "CV Lab productization overhead -- SYNTHETIC, NOT PHYSICAL",
        f"frame {WIDTH}x{HEIGHT} JPEG q50, {report['host']['cpu_count']} CPUs",
        "",
        "-- per frame ------------------------------------------------",
    ]
    for name, row in report["frame"].items():
        lines.append(
            f"  {name:16s} experiment {row['experiment_ms']['mean_ms']:8.4f} ms"
            f"   through Lab {row['through_lab_ms']['mean_ms']:8.4f} ms"
            f"   overhead {row['overhead_ms']:+.4f} ms"
            f" ({row['overhead_percent']:+.1f}%)"
        )
    lines += ["", "-- status document ------------------------------------------"]
    for name, row in report["status"].items():
        lines.append(
            f"  {name:16s} build {row['build_ms']['mean_ms']:7.4f} ms"
            f"   revision {row['revision_ms']['mean_ms']:7.4f} ms"
            f"   json {row['serialise_ms']['mean_ms']:7.4f} ms"
            f"   {row['bytes']:5d} B  {row['metrics']} metrics"
        )
    lines += ["", "-- one poll pass, by subscriber count ------------------------"]
    for name, row in report["channel"].items():
        lines.append(f"  {name:16s} {row['mean_ms']:8.4f} ms  p95 {row['p95_ms']:8.4f} ms")
    memory = report["memory"]
    lines += [
        "",
        "-- memory over a long run -----------------------------------",
        f"  {memory['frames']} frames in {memory['wall_s']} s"
        f" ({memory['frames_per_second']} fps)",
        f"  RSS growth {memory['rss_growth_bytes']:+d} B"
        f" ({memory['rss_growth_bytes_per_frame']:+.4f} B/frame)",
        f"  document still {memory['document_bytes']} B with"
        f" {memory['tracked_metrics']} metrics",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="What the CV Lab costs on top of its experiments."
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--repeat", type=int, default=40)
    parser.add_argument(
        "--frames",
        type=int,
        default=2000,
        help="frames for the memory-growth measurement",
    )
    args = parser.parse_args(argv)

    report = {
        "host": {"cpu_count": psutil.cpu_count(logical=True)},
        "resolution": [WIDTH, HEIGHT],
        "frame": measure_frame_overhead(args.repeat),
        "status": measure_status_cost(args.repeat),
        "channel": measure_channel_cost(max(4, args.repeat // 4)),
        "memory": measure_memory(args.frames),
        "caveat": (
            "SYNTHETIC, NOT PHYSICAL: rendered imagery, in-process client, "
            "no network. Real for the code, not a statement about a room "
            "or a link."
        ),
    }

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(_render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
