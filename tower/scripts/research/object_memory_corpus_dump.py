#!/usr/bin/env python
"""Dump EVERY detection the shipped detector makes over the real corpus.

`capture_corpus_benchmark.py` already walks the same frames, and reports
COUNTS. A relevance policy cannot be designed from counts: the questions
are "which classes appear with what score, at what size, for how long,
and how often does a class come and go" -- and every one of those needs
the individual detection, with its box and its frame.

So this writes one JSONL line per detection, at a threshold BELOW the one
the platform ships (0.15 against 0.4), because a policy that only ever
sees what the current threshold admitted cannot tell "this class is
absent" from "this class is being cut off".

It reads the corpus and writes only to the output file it is given. The
corpus is never modified.

    python scripts/research/object_memory_corpus_dump.py \
        --captures ../../Glasses/tower/data/captures \
        --out analysis/corpus-detections.jsonl --device cuda
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tower.capture import FRAMES_FILENAME  # noqa: E402
from tower.detection import SSDLite320Detector  # noqa: E402
from tower.storage import read_raw_jsonl  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def frames_of(capture_dir: Path):
    records, _ = read_raw_jsonl(capture_dir / FRAMES_FILENAME)
    for record in records:
        relpath = record.get("relpath")
        if not relpath:
            continue
        path = capture_dir / relpath
        if not path.exists():
            continue
        yield record, path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--score-threshold", type=float, default=0.15)
    parser.add_argument("--per-capture-limit", type=int, default=None)
    args = parser.parse_args(argv)

    capture_dirs = sorted(
        d for d in args.captures.iterdir()
        if d.is_dir() and (d / FRAMES_FILENAME).exists()
    )
    detector = SSDLite320Detector(
        score_threshold=args.score_threshold,
        classes=None,
        device=args.device,
        owner="CorpusDump",
    )
    detector.load()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    frames = 0
    undecodable = 0
    detections = 0
    started = time.perf_counter()
    infer_seconds = 0.0
    with args.out.open("w", encoding="utf-8") as handle:
        for capture_dir in capture_dirs:
            for index, (record, path) in enumerate(frames_of(capture_dir)):
                if args.per_capture_limit is not None and index >= args.per_capture_limit:
                    break
                raw = path.read_bytes()
                frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    undecodable += 1
                    continue
                frames += 1
                height, width = frame.shape[:2]
                t0 = time.perf_counter()
                found = detector.detect(frame)
                infer_seconds += time.perf_counter() - t0
                for detection in found:
                    x1, y1, x2, y2 = detection.box
                    handle.write(json.dumps({
                        "capture_id": capture_dir.name,
                        "source_seq": record.get("source_seq"),
                        "received_at": record.get("received_at"),
                        "relpath": record.get("relpath"),
                        "width": width,
                        "height": height,
                        "label": detection.label,
                        "score": round(detection.score, 5),
                        "box": [round(v, 2) for v in (x1, y1, x2, y2)],
                        "area_fraction": round(
                            max(0.0, (x2 - x1)) * max(0.0, (y2 - y1)) / (width * height), 6
                        ),
                    }) + "\n")
                    detections += 1
                if frames % 1000 == 0:
                    print(
                        f"  {frames} frames, {detections} detections, "
                        f"{infer_seconds * 1000 / frames:.1f} ms/frame infer",
                        flush=True,
                    )
    detector.release()
    elapsed = time.perf_counter() - started
    print(json.dumps({
        "captures": len(capture_dirs),
        "frames": frames,
        "undecodable": undecodable,
        "detections": detections,
        "score_threshold": args.score_threshold,
        "device": args.device,
        "seconds": round(elapsed, 2),
        "ms_per_frame_total": round(elapsed * 1000 / max(frames, 1), 3),
        "ms_per_frame_infer": round(infer_seconds * 1000 / max(frames, 1), 3),
        "out": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
