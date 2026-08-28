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

The classes `tower/object_memory/classes.py` admits, which is not one
list but two. `laptop` and `cell phone` are written on the detector's
word, because 36 of 36 inspected crops of them over the real corpus were
right. A dozen more -- `remote`, `backpack`, `bottle`, `cup` and the
rest -- are written only if a VERIFIER agrees, because inspection found
the same detector calling a ceiling fan `airplane` at 0.99 and a laptop
keyboard `remote` at 0.87. With `--verifier none`, which is the default,
nothing in the second list is ever written and this script behaves
exactly as the one that was physically validated.

`person` is excluded, and there is deliberately NO FLAG to widen the
list: re-admitting `person` commits the project to persisting a record
per detected bystander, which is an open ruling no human has settled
here. A command-line switch would let that decision happen by accident.

A record says a CATEGORY was visible over a span of time, with a
confidence. It is not a claim that the object is there now, not a claim
about WHICH laptop, and not a position in a room -- `spatial_ref` is null
and stays null.

The unit is a SIGHTING: a run of frames in which a class stayed in view,
broken by a gap of more than three seconds. A record is written once the
sighting is three frames old -- about a quarter of a second -- stamped
with the FIRST frame, so a killed session loses at most that. What the
sighting later becomes (its duration, its frame count, its strongest
look) is folded back into the same record rather than becoming a second
one. None of the scores is a calibrated probability.

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

from tower.artifact_paths import artifact_root_arg  # noqa: E402
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
    RelevancePolicy,
    recordable_classes,
)
from tower.object_memory.verification import (  # noqa: E402
    VerificationQueue,
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
        yield (
            path.read_bytes(),
            record.get("source_seq"),
            record.get("received_at"),
            relpath,
        )


def loose_frames(directory: Path):
    paths = sorted(directory.glob("*.jpg"))
    if not paths:
        raise SystemExit(f"no .jpg frames found under {directory}")
    for index, path in enumerate(paths):
        # received_at None, not a fabricated interval: this source has no
        # clock, and the records must not pretend otherwise (Rule 3).
        yield path.read_bytes(), index, None, path.name


VERIFIERS = ("none", "owlv2")


def _build_verifier(name: str, device: str):
    """Whatever may second-guess a detector label, or None.

    A NAME rather than a flag, because the answer is a model identifier
    and a boolean could never have become one. `none` returns None, and
    None is what makes `verification_available` False -- which keeps the
    `verify` tier unreachable on a Tower with no semantic model, rather
    than reachable and always refused.

    `none` is the DEFAULT, and that is a deliberate conservatism rather
    than a lack of confidence in the alternative. `owlv2` measured ~93%
    acceptance of correct labels and ~94% rejection of wrong ones over
    94 human-labelled crops -- but those 94 crops are from one home, and
    turning it on downloads ~600 MB of weights and takes ~620 MB of VRAM
    on a GPU this cartridge shares. One environment variable enables it;
    the evidence for doing so is in
    `docs/superpowers/research/2026-08-27-object-memory-corpus-precision.md`.
    """
    if name == "none":
        return None
    if name == "owlv2":
        from tower.object_memory.classes import prompt_for, verifier_vocabulary
        from tower.object_memory.verification import OwlV2Verifier

        return OwlV2Verifier(
            device=device,
            vocabulary=verifier_vocabulary(),
            prompt_for=prompt_for,
        )
    raise SystemExit(
        f"unknown verifier {name!r}; this build offers {', '.join(VERIFIERS)}"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Record which object categories were visible, and when."
    )
    parser.add_argument(
        "--root", type=artifact_root_arg, default=str(DEFAULT_ROOT)
    )
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
    parser.add_argument(
        "--verifier",
        default="none",
        help=(
            "What may second-guess a detector label. 'none' (the default) "
            "agrees with nothing, so only the classes measured reliable on "
            "the detector's own word are written. 'owlv2' loads "
            "google/owlv2-base-patch16-ensemble (~600 MB, Apache-2.0) and "
            "unlocks the verify tier."
        ),
    )
    parser.add_argument(
        "--verifier-device",
        choices=("cpu", "cuda"),
        default="cuda",
        help=(
            "Where the verifier runs. CUDA by default even though the "
            "detector defaults to CPU, and deliberately: measured 128 ms "
            "a crop on this GPU against 2,473 ms on this CPU, and putting "
            "the two stages on different devices is what keeps a 2.5-second "
            "burst off the cores the detector is using."
        ),
    )
    parser.add_argument("--score-threshold", type=float, default=SCORE_THRESHOLD)
    parser.add_argument(
        "--min-score",
        type=float,
        default=RelevancePolicy.min_score,
        help="Detections below this are seen but never remembered.",
    )
    parser.add_argument(
        "--gap-seconds",
        type=float,
        default=RelevancePolicy.gap_seconds,
        help=(
            "How long a class may be out of view before its next "
            "appearance counts as a new sighting."
        ),
    )
    parser.add_argument(
        "--min-frames",
        type=int,
        default=RelevancePolicy.min_frames,
        help=(
            "How many frames a sighting must last before it is written. A "
            "third of the sightings in the real corpus are shorter than "
            "three frames, and those are flickers."
        ),
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
            (frame.raw_bytes, frame.source_seq, frame.received_at, frame.relpath)
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
    verifier = _build_verifier(args.verifier, args.verifier_device)
    # Synchronous for a replay, threaded for a live follow. A replay has
    # no reason to be asynchronous and every reason to be deterministic;
    # a live session must not stall the frame path on a model.
    verification = (
        None
        if verifier is None
        else VerificationQueue(verifier, workers=0 if args.frames else 1)
    )
    policy = RelevancePolicy(
        min_score=args.min_score,
        gap_seconds=args.gap_seconds,
        min_frames=args.min_frames,
        verification_available=verifier is not None,
    )
    engine = ObjectMemoryEngine(
        store,
        detector,
        policy=policy,
        verification=verification,
        # The capture id, which is a FRAME identity owned by shared
        # transport -- not a World Builder session. This cartridge cannot
        # see a world and must not imply it can.
        session_id=session_id,
        source="glasses-camera",
    )

    started = time.perf_counter()
    engine.load()
    try:
        for index, frame in enumerate(frames):
            if args.limit is not None and index >= args.limit:
                break
            payload, source_seq, received_at, relpath = frame
            engine.observe(
                payload,
                received_at=received_at,
                source_seq=source_seq,
                relpath=relpath,
            )
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
        "verifier": args.verifier,
        "verifier_device": args.verifier_device if verifier is not None else None,
        "timing_source": timing,
        "attach_mode": attach_mode,
        # What this run could have written, which is narrower than what
        # the store would have accepted: the verify tier is only in reach
        # when something can second-guess the detector.
        "recordable_classes": list(recordable_classes(verifier is not None)),
        # Every counter the engine kept, including why detections did NOT
        # become observations. "wrote 11 records" means nothing without
        # "and declined 4,000, nearly all of them for classes it has no
        # evidence it can read".
        **engine.counters(),
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
            "Only "
            + ", ".join(report["recordable_classes"])
            + " could be remembered on this run. `person` is excluded on "
            "purpose; see object_memory.classes.EXCLUDED_CLASSES."
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
