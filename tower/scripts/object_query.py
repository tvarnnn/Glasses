#!/usr/bin/env python
r"""Ask Object Memory when it last saw something.

Deliberately independent of any voice path, like Document Memory's query
CLI: a Siri shortcut or a wake word would sit ABOVE this, and building
the voice layer first would have made the memory untestable.

    --last-seen laptop   when was a laptop last in view
    --purge-all          really delete every observation

ON "WHERE"

The obvious question is "when and WHERE did I last see my laptop", and
half of it cannot be answered. Observations carry `spatial_ref: None` --
the field is reserved, never populated, and actively nulled on read.
Nothing in this slice knows where anything is in a room.

So "where" is answered as a FRAME REFERENCE: which capture, which frame
sequence number, which camera. That is a pointer back into the recording,
not a place. This CLI says so on every answer rather than letting a
capture id be mistaken for a location.

Nor is it a claim the object is still there. It is a record that a
CATEGORY was visible once -- not that this is YOUR laptop, and not that
absence of a record means absence of the laptop.

    .venv\Scripts\python.exe scripts/object_query.py --last-seen laptop
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.object_memory.relevance import PERSISTED_CLASSES  # noqa: E402
from tower.object_memory.store import ObservationStore  # noqa: E402

DEFAULT_ROOT = Path("data/object_memory")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Query observed objects (read-only unless --purge-all)."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--last-seen", default=None, metavar="OBJECT_CLASS")
    parser.add_argument(
        "--retention-days",
        type=float,
        default=30.0,
        help=(
            "The retention this store was written under. Reads apply it, "
            "so an expired observation is not served. 0 means keep forever."
        ),
    )
    parser.add_argument(
        "--purge-all",
        action="store_true",
        help="Really delete every stored observation.",
    )
    parser.add_argument("--now", type=float, default=None, help="Override the clock.")
    args = parser.parse_args(argv)

    if (args.last_seen is not None) == args.purge_all:
        parser.error("exactly one of --last-seen or --purge-all is required")

    retention = None if args.retention_days <= 0 else args.retention_days * 86400.0
    now = time.time() if args.now is None else args.now
    store = ObservationStore(args.root, retention_seconds=retention, clock=lambda: now)

    if args.purge_all:
        removed = store.purge()
        if args.format == "json":
            print(json.dumps({"observations_removed": removed}, indent=2))
        else:
            print(f"observations removed  {removed}")
        return 0

    observation = store.last_seen(args.last_seen)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "object_class": args.last_seen,
                    # "observed", never "present": the record says a
                    # category was visible once, not that it is there.
                    "observed": observation is not None,
                    "observation": (
                        observation.to_json_dict() if observation else None
                    ),
                    # Named so a consumer cannot read a capture id as a
                    # place. There is no spatial answer in this slice.
                    "where": (
                        {
                            "kind": "frame-reference",
                            "spatial_ref": None,
                            "session_id": observation.session_id,
                            "frame_seq": observation.frame_seq,
                            "source": observation.source,
                        }
                        if observation
                        else None
                    ),
                },
                indent=2,
            )
        )
        return 0 if observation else 1

    if observation is None:
        print(f"No record of observing a {args.last_seen}.")
        print("(that is a statement about what was captured, not about the world)")
        if args.last_seen not in PERSISTED_CLASSES:
            print(
                f"\nNothing ever records {args.last_seen!r}: this slice only "
                f"remembers {', '.join(PERSISTED_CLASSES)}."
            )
        return 1

    age_minutes = (now - observation.observed_at) / 60.0
    print(f"=== last observed {observation.object_class} ===")
    print(f"  when          {age_minutes:.1f} min ago (tower-receipt time)")
    print(f"  confidence    {observation.confidence.value}")
    print(f"  score         {observation.detector_score}")
    print(f"  capture       {observation.session_id}")
    print(f"  frame_seq     {observation.frame_seq}")
    print(f"  camera        {observation.source}")
    print(
        "\nWHERE: a frame reference, not a place. This slice stores no "
        "spatial position (spatial_ref is null) and cannot say which room "
        "or surface the object was on."
    )
    print(
        "OBSERVED, NOT PRESENT: a category was visible in that frame. Not "
        "a claim it is still there, and not a claim it is YOUR "
        f"{observation.object_class}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
