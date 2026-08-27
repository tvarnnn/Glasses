#!/usr/bin/env python
"""Does the detector get slower the longer a walk lasts?

**No, and the question exists because a first pass said yes.** That
answer was wrong, and the way it was wrong is worth keeping.

Running `ssdlite320_mobilenet_v3_large` on CUDA across all 18,821 real
frames, the CUMULATIVE mean per-frame inference time printed by
`object_memory_corpus_dump.py` rose at every checkpoint -- 49.5 ms at
1,000 frames, 75.0 at 10,000, 87.8 at the end. Read as a trend that is
alarming: a producer following a fifteen-minute walk is ~10,800 frames,
squarely inside the range.

It is not a trend. **A cumulative mean rises monotonically whenever the
underlying series steps up even once**, and it can never come back down.
De-cumulating the same log gives windows of

    49.5  47.5  46.1  55.7  74.2 100.8  99.4  95.6  91.8
    89.4  92.6 100.6 108.5 101.9 106.4  98.4  88.3 106.7

-- a step at frames 3,000-6,000 and then a flat plateau. The step is
where a test suite and a contact-sheet render started competing for the
same cores.

Measured directly, one job at a time, on an idle host, this script
reports **no drift**: window-median ratios of 0.968 (CUDA, 6,000 frames)
and 0.808 (CPU), an independently-run 10,000-frame CUDA pass at 1.041,
flat RSS, and a CUDA allocator reserve that plateaus at 436 MB. There is
no leak and no degradation.

So this script exists for two reasons: to have measured that, and to
measure it again cheaply if anything here changes. It reports per-frame
latency in WINDOWS -- never a cumulative mean -- alongside process RSS
and, on CUDA, the allocator's own figures. It runs the same detector the
cartridge runs, through the same shared class, so a number here is a
number about the shipped code.

    python scripts/research/detector_long_session.py --frames 6000 --device cuda
    python scripts/research/detector_long_session.py --frames 6000 --device cpu

RUN IT ALONE. That is the finding, not a caveat: every wrong latency
figure this cartridge has published came from a contended host.

It reads the corpus and writes only the JSON it prints.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import psutil  # noqa: E402

from tower.capture import FRAMES_FILENAME  # noqa: E402
from tower.detection import SSDLite320Detector  # noqa: E402
from tower.storage import read_raw_jsonl  # noqa: E402


def frame_paths(captures: Path):
    """Every recorded frame, capture by capture, in journal order.

    Journal order rather than a glob, so the sequence a long run sees is
    the sequence a walk would have produced: the same scenes in the same
    order, not an alphabetical shuffle that would change how much work
    each frame is.
    """
    for capture_dir in sorted(
        d for d in captures.iterdir() if (d / FRAMES_FILENAME).exists()
    ):
        records, _ = read_raw_jsonl(capture_dir / FRAMES_FILENAME)
        for record in records:
            relpath = record.get("relpath")
            if not relpath:
                continue
            path = capture_dir / relpath
            if path.exists():
                yield path


def cuda_memory(device: str) -> dict:
    if not device.startswith("cuda"):
        return {}
    import torch

    return {
        "cuda_allocated_mb": round(torch.cuda.memory_allocated() / 1e6, 1),
        "cuda_reserved_mb": round(torch.cuda.memory_reserved() / 1e6, 1),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--frames", type=int, default=6000)
    parser.add_argument("--window", type=int, default=500)
    parser.add_argument(
        "--decode-only",
        action="store_true",
        help=(
            "Decode every frame and run NO inference. Separates 'the "
            "detector slows down' from 'reading and decoding this corpus "
            "slows down', which a single number cannot."
        ),
    )
    parser.add_argument(
        "--empty-cache-every",
        type=int,
        default=0,
        help=(
            "Call torch.cuda.empty_cache() every N frames. 0 disables. A "
            "candidate remedy, measured rather than assumed: if the climb "
            "is allocator fragmentation this flattens it, and if it is "
            "not, this makes it worse."
        ),
    )
    args = parser.parse_args(argv)

    process = psutil.Process()
    detector = None
    if not args.decode_only:
        detector = SSDLite320Detector(
            score_threshold=0.4, classes=None, device=args.device, owner="LongSession"
        )
        load_started = time.perf_counter()
        detector.load()
        load_seconds = time.perf_counter() - load_started
    else:
        load_seconds = 0.0

    windows = []
    latencies: list[float] = []
    detections = 0
    processed = 0
    started = time.perf_counter()

    for path in frame_paths(args.captures):
        if processed >= args.frames:
            break
        # The timer starts at the READ in decode-only mode and at the
        # detector otherwise, because the two runs answer different
        # questions: "does reading and decoding this corpus get slower"
        # and "does inference get slower". Timing the decode inside the
        # inference run would blur a 1 ms cost into an 80 ms one.
        began = time.perf_counter()
        raw = path.read_bytes()
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        if detector is not None:
            began = time.perf_counter()
            detections += len(detector.detect(frame))
        latencies.append((time.perf_counter() - began) * 1000.0)
        processed += 1
        if args.empty_cache_every and processed % args.empty_cache_every == 0:
            if args.device.startswith("cuda"):
                import torch

                torch.cuda.empty_cache()
        if processed % args.window == 0:
            recent = latencies[-args.window :]
            windows.append(
                {
                    "frames": processed,
                    "median_ms": round(statistics.median(recent), 2),
                    "mean_ms": round(statistics.fmean(recent), 2),
                    "p95_ms": round(sorted(recent)[int(0.95 * len(recent)) - 1], 2),
                    "rss_mb": round(process.memory_info().rss / 1e6, 1),
                    **cuda_memory(args.device),
                }
            )
            print(json.dumps(windows[-1]), flush=True)

    if detector is not None:
        detector.release()
    elapsed = time.perf_counter() - started

    first = windows[0]["median_ms"] if windows else None
    last = windows[-1]["median_ms"] if windows else None
    report = {
        "device": args.device,
        "decode_only": args.decode_only,
        "empty_cache_every": args.empty_cache_every,
        "frames": processed,
        "detections": detections,
        "load_seconds": round(load_seconds, 3),
        "seconds": round(elapsed, 2),
        "median_ms": round(statistics.median(latencies), 3) if latencies else None,
        "first_window_median_ms": first,
        "last_window_median_ms": last,
        # The whole question, as one number. 1.0 is a flat run.
        "drift_ratio": (
            round(last / first, 3) if first and last and first > 0 else None
        ),
        "peak_rss_mb": max((w["rss_mb"] for w in windows), default=None),
        "windows": windows,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
