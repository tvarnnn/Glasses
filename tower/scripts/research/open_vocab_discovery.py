#!/usr/bin/env python
"""Can an open-vocabulary detector find what COCO cannot name?

THE QUESTION THIS LANE LEFT OPEN.

`2026-08-27-object-memory-corpus-precision.md` establishes two things:
the shipped detector's labels are unreliable for most classes, and **the
objects people actually lose have no COCO class at all** -- keys, a
wallet, a pair of glasses, a charger. The verifier fixed the first. It
cannot touch the second, because it only ever sees crops the shipped
detector produced, and the shipped detector never fires on a set of keys.

So the obvious next move is to run the open-vocabulary model on WHOLE
FRAMES with a curated prompt list, on the async path, and let it discover
what stage one is blind to. Before anyone builds that, it is worth
knowing whether it works on this footage at all.

This measures it. It is a MEASUREMENT, not a feature: nothing in
`tower/object_memory/` calls it, and the answer belongs in a handoff
rather than in a policy.

    python scripts/research/open_vocab_discovery.py \\
        --captures ../../Glasses/tower/data/captures \\
        --per-capture 20 --out analysis/discovery.json \\
        --sheet analysis/sheets/_discovery.png

WHAT IT COSTS, AND WHY THAT IS THE POINT. A full frame is one model call.
At 126 ms a call on this GPU, running it on every delivered frame would
be 1.5x the whole frame budget -- so a discovery pass is inherently a
SAMPLED, asynchronous thing, and this script samples the way such a pass
would have to.

The contact sheet is crops of raw first-person imagery. `analysis/` is
gitignored and it must stay that way.
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
from tower.storage import read_raw_jsonl  # noqa: E402

from scripts.research.sighting_contact_sheet import sheet  # noqa: E402

# What a person actually loses, in the words a language-conditioned model
# is most likely to understand.
#
# The first five are the ones with NO COCO class at any threshold, which
# is the whole reason for the experiment. `remote control` and
# `backpack` are here because COCO has them and this detector reads them
# wrong: 3 of 8 and 0 of 1 respectively.
WANTED = (
    "a set of keys",
    "a wallet",
    "a pair of eyeglasses",
    "a charging cable",
    "a pill bottle",
    "a remote control",
    "a backpack",
    "a paper document",
)

# Prompts that should score high on this footage and are NOT the target.
# Without them a threshold measures the model's willingness to say yes;
# with them it measures whether the target wins.
DISTRACTORS = (
    "a laptop",
    "a cell phone",
    "a computer keyboard",
    "a bed",
    "a wall",
    "a human hand",
    "a ceiling fan",
    "a door",
)


def frames(captures: Path, per_capture: int):
    for capture_dir in sorted(
        d for d in captures.iterdir() if (d / FRAMES_FILENAME).exists()
    ):
        records, _ = read_raw_jsonl(capture_dir / FRAMES_FILENAME)
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
    parser.add_argument("--per-capture", type=int, default=20)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--threshold", type=float, default=0.15)
    parser.add_argument("--tiles", type=int, default=36)
    args = parser.parse_args(argv)

    import torch
    from PIL import Image
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    from tower.object_memory.verification import OWLV2_REPO

    vocabulary = list(WANTED) + list(DISTRACTORS)
    processor = AutoProcessor.from_pretrained(OWLV2_REPO)
    model = (
        AutoModelForZeroShotObjectDetection.from_pretrained(OWLV2_REPO)
        .eval()
        .to(args.device)
    )

    hits, tiles, captions = [], [], []
    scanned = 0
    latencies = []
    started = time.perf_counter()
    for capture_id, source_seq, path in frames(args.captures, args.per_capture):
        image = cv2.imread(str(path))
        if image is None:
            continue
        scanned += 1
        pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        inputs = processor(
            text=[vocabulary], images=pil, return_tensors="pt"
        ).to(args.device)
        began = time.perf_counter()
        with torch.inference_mode():
            outputs = model(**inputs)
        if args.device.startswith("cuda"):
            torch.cuda.synchronize()
        latencies.append((time.perf_counter() - began) * 1000.0)
        results = processor.post_process_grounded_object_detection(
            outputs, threshold=args.threshold, target_sizes=[(pil.height, pil.width)]
        )[0]

        height, width = image.shape[:2]
        for index, score, box in zip(
            results["labels"].tolist(),
            results["scores"].tolist(),
            results["boxes"].tolist(),
        ):
            name = vocabulary[int(index)]
            if name not in WANTED:
                continue
            x1, y1, x2, y2 = box
            hits.append(
                {
                    "capture_id": capture_id,
                    "source_seq": source_seq,
                    "relpath": str(path.relative_to(args.captures / capture_id)),
                    "prompt": name,
                    "score": round(float(score), 4),
                    "area_fraction": round(
                        max(0.0, x2 - x1) * max(0.0, y2 - y1) / (width * height), 5
                    ),
                }
            )
            if len(tiles) < args.tiles and args.sheet is not None:
                pad_x, pad_y = (x2 - x1) * 0.4, (y2 - y1) * 0.4
                patch = image[
                    int(max(0, y1 - pad_y)) : int(min(height, y2 + pad_y)),
                    int(max(0, x1 - pad_x)) : int(min(width, x2 + pad_x)),
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
                    top = (150 - patch.shape[0]) // 2
                    left = (150 - patch.shape[1]) // 2
                    tile[
                        top : top + patch.shape[0], left : left + patch.shape[1]
                    ] = patch
                    tiles.append(tile)
                    captions.append(
                        f"{name.replace('a ', '')[:14]} {score:.2f}"
                    )
        if scanned % 50 == 0:
            print(f"  {scanned} frames, {len(hits)} hits", flush=True)

    elapsed = time.perf_counter() - started
    if args.sheet is not None and tiles:
        args.sheet.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.sheet), sheet(tiles, captions, 6, 150))

    by_prompt: dict[str, list] = {}
    for hit in hits:
        by_prompt.setdefault(hit["prompt"], []).append(hit)

    report = {
        "frames_scanned": scanned,
        "threshold": args.threshold,
        "device": args.device,
        "median_ms_per_frame": round(float(np.median(latencies)), 1)
        if latencies
        else None,
        "seconds": round(elapsed, 1),
        "hits": len(hits),
        "by_prompt": {
            name: {
                "hits": len(rows),
                "frames": len({(r["capture_id"], r["source_seq"]) for r in rows}),
                "captures": len({r["capture_id"] for r in rows}),
                "max_score": max(r["score"] for r in rows),
                "median_area_fraction": float(
                    np.median([r["area_fraction"] for r in rows])
                ),
            }
            for name, rows in sorted(by_prompt.items(), key=lambda kv: -len(kv[1]))
        },
        "sheet": None if args.sheet is None else str(args.sheet),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
