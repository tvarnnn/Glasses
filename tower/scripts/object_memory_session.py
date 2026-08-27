#!/usr/bin/env python
r"""Remember which objects were in view, and when.

Runs in a SEPARATE PROCESS from the Tower, like every other cartridge
producer here. That is what makes this slice possible at all: Object
Memory has been considered blocked on whether a module lifecycle can
bound a synchronous model load, and a follower that tails a capture
journal needs no module lifecycle, no load timeout and no module slot.
The Tower's frame path pays nothing for this.

Frame sources:

  --frames DIR          a recorded capture directory, or any directory of
                        .jpg files. If the directory has a `frames.jsonl`
                        journal it is read instead of globbing, so the
                        real receipt times and source_seq survive; a bare
                        directory of jpegs has no timestamps and the
                        records say so.
  --follow-capture DIR  tail a capture the Tower is writing RIGHT NOW, so
                        objects are remembered while the wearer walks

WHAT THIS WILL AND WILL NOT REMEMBER

Only the classes in `relevance.PERSISTED_CLASSES` -- today `laptop` and
`cell phone`, the only two COCO classes the real 9,199-frame corpus
supports with confidence above 0.8. `person` is excluded, and there is
deliberately NO FLAG to widen the list: re-admitting `person` commits the
project to persisting a record per detected bystander, which is an open
ruling no human has settled here. Read the comment on PERSISTED_CLASSES
before changing it; a command-line switch would let that decision happen
by accident.

A record says a CATEGORY was visible at a time, with a confidence. It is
not a claim that the object is there now, not a claim about WHICH laptop,
and not a position in a room -- `spatial_ref` is null and stays null.

A record is written the moment a class comes into view, so a killed
session loses nothing and `observed_at` means what it says. A stronger
look at the same sighting inside the resample window is folded back into
that record as `best_score`; `detector_score` keeps meaning "the frame
this record describes". Neither is a calibrated probability.

`--retention-days` is recorded in the store's manifest at first append,
and every later read clamps to min(persisted, requested). A reader can
narrow that window; nothing a reader passes can widen it.

    .venv\Scripts\python.exe scripts/object_memory_session.py --frames data/captures/<id>
    .venv\Scripts\python.exe scripts/object_memory_session.py --follow-capture data/captures/<id>
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.capture import CaptureFollower, FRAMES_FILENAME  # noqa: E402
from tower.capture_workers import (  # noqa: E402
    ATTACH_MODE_FROM_NOW,
    ATTACH_MODE_FROM_START,
)
from tower.config import DEFAULT_OBSERVATION_ROOT  # noqa: E402
from tower.object_memory.detector import (  # noqa: E402
    SCORE_THRESHOLD,
    FixedDetector,
    TorchvisionDetector,
)
from tower.object_memory.engine import ObjectMemoryEngine  # noqa: E402
from tower.object_memory.relevance import (  # noqa: E402
    PERSISTED_CLASSES,
    RelevancePolicy,
)
from tower.object_memory.store import (  # noqa: E402
    DEFAULT_RETENTION_DAYS,
    ObservationStore,
)
from tower.storage import read_raw_jsonl  # noqa: E402

# THE SAME DEFAULT THE WEB PROCESS USES, IMPORTED RATHER THAN RESTATED.
#
# This line used to read `Path("data/object_memory")` while
# `tower/config.py` defaulted its observation root to None, and the two
# were never compared. The 2026-08-26 physical run is what that cost: a
# real walk was remembered into this directory, and every HTTP request
# answered 404 about it until an operator set an environment variable by
# hand. One constant, in the settings module, imported here.
DEFAULT_ROOT = Path(DEFAULT_OBSERVATION_ROOT)


def journal_frames(directory: Path):
    """A recorded capture, read through its journal.

    The journal is what carries `received_at` and `source_seq`. Globbing
    the image directory instead would throw both away and leave every
    record stamped with processing time, which makes the resample window
    measure the wrong thing entirely.
    """
    records, _ = read_raw_jsonl(directory / FRAMES_FILENAME)
    for record in records:
        relpath = record.get("relpath")
        if not relpath:
            continue
        path = directory / relpath
        if not path.exists():
            continue
        yield path.read_bytes(), record.get("source_seq"), record.get("received_at")


def loose_frames(directory: Path):
    paths = sorted(directory.glob("*.jpg"))
    if not paths:
        raise SystemExit(f"no .jpg frames found under {directory}")
    for index, path in enumerate(paths):
        # received_at None, not a fabricated interval: this source has no
        # clock, and the records must not pretend otherwise (Rule 3).
        yield path.read_bytes(), index, None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Record which object categories were visible, and when."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--frames", type=Path, default=None)
    parser.add_argument("--follow-capture", type=Path, default=None)
    parser.add_argument(
        "--detector",
        choices=("ssdlite320", "none"),
        default="ssdlite320",
        help=(
            "'none' runs the whole pipeline over no detections, which "
            "exercises the producer without downloading a model and "
            "honestly remembers nothing."
        ),
    )
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--score-threshold", type=float, default=SCORE_THRESHOLD)
    parser.add_argument(
        "--min-score",
        type=float,
        default=RelevancePolicy.min_score,
        help="Detections below this are seen but never remembered.",
    )
    parser.add_argument(
        "--resample-seconds",
        type=float,
        default=RelevancePolicy.resample_seconds,
        help="How long after remembering a class before it is worth again.",
    )
    parser.add_argument(
        "--retention-days",
        type=float,
        default=DEFAULT_RETENTION_DAYS,
        help=(
            "Forget observations older than this. 0 means keep forever. "
            "Recorded in the store manifest at first append, and every "
            "later read is clamped to it."
        ),
    )
    parser.add_argument(
        "--attach-mode",
        choices=(ATTACH_MODE_FROM_START, ATTACH_MODE_FROM_NOW),
        default=ATTACH_MODE_FROM_START,
        help=(
            "Only meaningful with --follow-capture. 'from-start' reads the "
            "whole capture, which is right for a producer attached when the "
            "recording opened. 'from-now' skips whatever the journal "
            "already holds: a producer attached three minutes into a walk "
            "was not asked for the first three minutes, and reading them "
            "would be a consent decision this script has no standing to "
            "make."
        ),
    )
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument("--max-idle-polls", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None, help="Stop after N frames.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    chosen = [
        name
        for name, value in (
            ("--frames", args.frames),
            ("--follow-capture", args.follow_capture),
        )
        if value
    ]
    if len(chosen) != 1:
        parser.error("exactly one of --frames or --follow-capture is required")

    if args.follow_capture:
        if not args.follow_capture.exists():
            raise SystemExit(f"no capture directory at {args.follow_capture}")
        follower = CaptureFollower(
            args.follow_capture,
            poll_seconds=args.poll_seconds,
            start_at_end=args.attach_mode == ATTACH_MODE_FROM_NOW,
        )
        frames = (
            (frame.raw_bytes, frame.source_seq, frame.received_at)
            for frame in follower.follow(max_idle_polls=args.max_idle_polls)
        )
        session_id = args.follow_capture.name
        source = "live-capture"
        timing = "capture-journal"
        attach_mode = args.attach_mode
    else:
        if not args.frames.exists():
            raise SystemExit(f"no frame directory at {args.frames}")
        if (args.frames / FRAMES_FILENAME).exists():
            frames = journal_frames(args.frames)
            timing = "capture-journal"
        else:
            frames = loose_frames(args.frames)
            timing = "none"
        session_id = args.frames.name
        source = "recorded-frames"
        # A replay reads what it was pointed at. There is no live journal
        # to arrive late to, so the flag has nothing to describe and the
        # report says so rather than reporting a default that would look
        # like a decision.
        attach_mode = None

    detector = (
        TorchvisionDetector(
            score_threshold=args.score_threshold, device=args.device
        )
        if args.detector == "ssdlite320"
        else FixedDetector()
    )
    retention = None if args.retention_days <= 0 else args.retention_days * 86400.0
    store = ObservationStore(args.root, retention_seconds=retention)
    engine = ObjectMemoryEngine(
        store,
        detector,
        policy=RelevancePolicy(
            min_score=args.min_score, resample_seconds=args.resample_seconds
        ),
        # The capture id, which is a FRAME identity owned by shared
        # transport -- not a World Builder session. This cartridge cannot
        # see a world and must not imply it can.
        session_id=session_id,
        source="glasses-camera",
    )

    started = time.perf_counter()
    engine.load()
    try:
        for index, (payload, source_seq, received_at) in enumerate(frames):
            if args.limit is not None and index >= args.limit:
                break
            engine.observe(payload, received_at=received_at, source_seq=source_seq)
    finally:
        engine.release()
    elapsed = time.perf_counter() - started

    pruned = store.prune_expired()

    report = {
        "root": str(args.root),
        "frame_source": source,
        "session_id": session_id,
        "detector": detector.name,
        "device": args.device if detector.name != "fixed" else None,
        "timing_source": timing,
        "attach_mode": attach_mode,
        "persisted_classes": list(PERSISTED_CLASSES),
        "frames_observed": engine.frames_observed,
        "frames_undecodable": engine.frames_undecodable,
        "detections_seen": engine.detections_seen,
        "observations_recorded": engine.observations_recorded,
        "recorded_by_class": engine.recorded_by_class,
        # An upgrade is a record whose best_score was raised by a
        # stronger look at the SAME sighting -- not a second record.
        "best_score_upgrades": engine.best_score_upgrades,
        # Not noise: "wrote 11 records" is meaningless without "and
        # declined 4,000, nearly all of them for being off the whitelist".
        "declined": engine.dropped,
        "write_failures": engine.write_failures,
        "upgrade_failures": engine.upgrade_failures,
        "stored_observations": len(store.all_observations()),
        "pruned_expired": pruned,
        "retention_days": args.retention_days,
        "seconds": round(elapsed, 3),
        "ms_per_frame": round(elapsed * 1000 / max(engine.frames_observed, 1), 3),
    }

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            print(f"{key:22s} {value}")
        print(
            "\nOBSERVED, NOT LOCATED: a category was visible in a frame. "
            "There is no position in a room here -- spatial_ref is null."
        )
        print(
            f"Only {', '.join(PERSISTED_CLASSES)} are remembered. `person` "
            "is excluded on purpose; see relevance.PERSISTED_CLASSES."
        )
        print("Times are tower-receipt, never on-glasses capture time.")
        print(
            "Records point back at data/captures/ by session and frame. "
            "That imagery is governed by capture retention, not by this "
            "store's."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
