#!/usr/bin/env python
"""How often does the face filter fire on a corpus with no faces in it?

Asked because it happened where it mattered. On frame 2708 of the
physically validated capture -- a desk with a monitor, a lit keyboard and
a red gaming mouse, and no person anywhere in the picture -- YuNet fired
TWICE, and one of the filled regions landed squarely on the mouse a
record was about. The record is correct, the verifier agreed with it, and
the crop served for it is a black rectangle.

`tower/world_builder/redaction.py` measured "0 false positives on 40
face-free frames" and that measurement is not wrong; it was made on forty
SYNTHETIC room renders. This one is made on the real corpus, which is
18,821 frames of a first-person camera in a home -- lit screens, blurred
motion, a ceiling fan, a keyboard, and almost no faces, because a
head-mounted camera does not point at its wearer.

WHY THIS MATTERS TO TWO LANES.

For Object Memory the cost is a spoiled picture, and the response is to
REPORT the overlap rather than to weaken the filter -- a face-detection
threshold is not a picture-quality knob. For World Builder the cost is
larger and is not this lane's to fix: that cartridge fills these regions
BEFORE persistence, so a false positive there destroys pixels
permanently and takes whatever geometry was in them.

    python scripts/research/face_filter_false_positives.py \\
        --captures ../../Glasses/tower/data/captures --per-capture 60

It reads the corpus and writes a contact sheet of what fired, so the
firings can be judged by eye rather than counted on trust. That sheet is
crops of raw first-person imagery: `analysis/` is gitignored and it must
stay that way.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from tower.capture import FRAMES_FILENAME  # noqa: E402
from tower.object_memory.imagery import FaceFilter  # noqa: E402
from tower.storage import read_raw_jsonl  # noqa: E402

from scripts.research.sighting_contact_sheet import sheet  # noqa: E402


def frames(captures: Path, per_capture: int):
    for capture_dir in sorted(
        d for d in captures.iterdir() if (d / FRAMES_FILENAME).exists()
    ):
        records, _ = read_raw_jsonl(capture_dir / FRAMES_FILENAME)
        # Evenly spaced rather than the first N: the first N frames of a
        # capture are the wearer settling, and every capture would
        # contribute the same scene.
        step = max(1, len(records) // max(per_capture, 1))
        for record in records[::step][:per_capture]:
            relpath = record.get("relpath")
            if not relpath:
                continue
            path = capture_dir / relpath
            if path.exists():
                yield capture_dir.name, record.get("source_seq"), path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--per-capture", type=int, default=60)
    parser.add_argument("--sheet", type=Path, default=None)
    parser.add_argument("--tiles", type=int, default=36)
    args = parser.parse_args(argv)

    face_filter = FaceFilter()
    if not face_filter.available:
        raise SystemExit(face_filter.unavailable_reason)

    scanned = fired = regions = 0
    areas = []
    tiles, captions = [], []
    started = time.perf_counter()
    for capture_id, source_seq, path in frames(args.captures, args.per_capture):
        image = cv2.imread(str(path))
        if image is None:
            continue
        scanned += 1
        height, width = image.shape[:2]
        _, filled = face_filter.apply(image.copy())
        if not filled:
            continue
        fired += 1
        regions += len(filled)
        for x0, y0, x1, y1 in filled:
            areas.append((x1 - x0) * (y1 - y0) / (width * height))
        if len(tiles) < args.tiles and args.sheet is not None:
            x0, y0, x1, y1 = filled[0]
            pad_x, pad_y = int((x1 - x0) * 0.6), int((y1 - y0) * 0.6)
            patch = image[
                max(0, y0 - pad_y) : min(height, y1 + pad_y),
                max(0, x0 - pad_x) : min(width, x1 + pad_x),
            ]
            if patch.size:
                scale = 150 / max(patch.shape[:2])
                patch = cv2.resize(
                    patch,
                    (
                        max(1, int(patch.shape[1] * scale)),
                        max(1, int(patch.shape[0] * scale)),
                    ),
                )
                tile = np.full((150, 150, 3), 30, np.uint8)
                top, left = (150 - patch.shape[0]) // 2, (150 - patch.shape[1]) // 2
                tile[top : top + patch.shape[0], left : left + patch.shape[1]] = patch
                tiles.append(tile)
                captions.append(f"{capture_id[:6]} #{source_seq} n={len(filled)}")

    elapsed = time.perf_counter() - started
    if args.sheet is not None and tiles:
        args.sheet.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.sheet), sheet(tiles, captions, 6, 150))

    print(
        json.dumps(
            {
                "frames_scanned": scanned,
                "frames_with_a_firing": fired,
                "firing_rate": round(fired / max(scanned, 1), 4),
                "regions": regions,
                "median_region_area_fraction": (
                    round(float(np.median(areas)), 5) if areas else None
                ),
                "max_region_area_fraction": (
                    round(float(np.max(areas)), 5) if areas else None
                ),
                "ms_per_frame": round(elapsed * 1000 / max(scanned, 1), 2),
                "sheet": None if args.sheet is None else str(args.sheet),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
