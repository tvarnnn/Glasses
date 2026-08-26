#!/usr/bin/env python
"""A/B benchmark driver over a PINNED set of real Ray-Ban captures.

This is a measuring instrument, not an experiment. It exists to decide
whether a later triangulation change is accepted, which means the only
property it really has to have is that its numbers are comparable
between two runs of two different code states. Everything below that
looks like paranoia is in service of that one property.

WHAT MAKES IT COMPARABLE

1. THE CORPUS IS PINNED, NOT GLOBBED. `PINNED_PREFIXES` is a literal
   tuple of eight capture-id prefixes. `data/captures` grows every time
   anyone walks a room; a glob would silently change what "the corpus"
   means between the before-run and the after-run, and the comparison
   would be meaningless in a way no output could reveal. A prefix that
   matches zero directories, or more than one, is a hard error naming
   the prefix -- never a skipped capture.

2. NOTHING IS EVER SILENTLY DROPPED. Every failure mode a capture can
   have -- no frames, an unreadable resolution, a missing calibration, a
   points file that disagrees with the build result -- raises
   `BenchmarkError` and aborts the whole run. A benchmark that quietly
   records a zero where it meant "I could not measure this" is worse
   than no benchmark, because the zero survives into the verdict.

3. REPLAY GOES THROUGH THE JOURNAL, NOT A DIRECTORY GLOB. See below.

4. THE RNG IS PINNED. See "DETERMINISM" below.

WHY THE JOURNAL PATH AND NOT --frames

`world_build_session.py --frames` sorts `*.jpg` off disk and fabricates
`source_seq` from the enumeration index while leaving `received_at` as
None (world_build_session.py:95-102 -- `load_frames`). Both of those are
inputs to the engine: `observe()` is handed them and they reach the
keyframe journal. Replaying a real capture through that path would
measure a walk that never happened. `--follow-capture` reads
`frames.jsonl`, so `source_seq`, `wire_seq`, `tx_seq` and `received_at`
are the recorder's own values.

This module therefore imports `world_build_session`'s helpers directly
-- `ObservedFrame`, `first_observed_frame`, `observed_size_of`,
`resolve_intrinsics` -- rather than re-implementing them, so the replay
cannot drift away from the driver it is supposed to mirror.

THE ONE DELIBERATE DEVIATION FROM `world_build_session.follow_capture`

`follow_capture` builds a `CaptureFollower` with its default
`follow_reconnects=True`. That is right for the live path and WRONG
here, for two reasons, both of which are load-bearing given requirement
1 above:

  - Three of the eight pinned captures ended by `disconnect`
    (b35d8ab8, 20ce3c23, 2e6cffa2), and two of those have successors on
    disk (e9d0c9ef continues b35d8ab8; 5387a765 continues 20ce3c23).
    A reconnect-following replay of "capture b35d8ab8" would silently
    consume e9d0c9ef's frames as well -- an unpinned capture entering
    the corpus through the back door, which is exactly the drift the
    pinned set exists to prevent.
  - 2e6cffa2 ended by disconnect with no successor, so
    `_await_successor` would poll for the full 90 s `RESUME_GRACE_
    SECONDS` before giving up, contaminating `wall_seconds` with a
    fixed sleep.

So the follower is constructed here with `follow_reconnects=False`.
Everything else about the read -- the `CaptureFollower` itself, the
journal tail, the `FollowedFrame` -> `ObservedFrame` mapping -- is the
same code the live driver runs.

DETERMINISM

`cv2.setRNGSeed(0)` is called before any work, and again before each
capture so that a `--only` subset produces the same per-capture numbers
as a full run. Replay is empirically bit-deterministic on this host,
but `backends/classical.py:605-607` explicitly says
`findEssentialMat(USAC_MAGSAC)` and `solvePnPRansac(SQPNP)` "are not
seeded" and documents a committed test measuring 1.32% on one OpenCV
build and 1.62% on another. Determinism is therefore PINNED here, not
assumed -- and if a future OpenCV makes the seed ineffective, that is a
finding about this instrument, not a reason to trust its output.

WHERE OUTPUT GOES

Derived geometry goes to `--scratch` (a fresh temp dir by default).
`data/captures` is opened read-only and `data/world_builder` is opened
read-only for exactly one file: the 360x640 calibration. Both are
asserted, not merely intended.

USAGE

    python scripts/world_builder_corpus_benchmark.py \
        --label before --out before.json
    python scripts/world_builder_corpus_benchmark.py \
        --label after --out after.json
    python scripts/world_builder_corpus_benchmark.py \
        --compare before.json after.json
"""

import argparse
import json
import logging
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from scripts.world_build_session import (  # noqa: E402
    ObservedFrame,
    first_observed_frame,
    observed_size_of,
    resolve_intrinsics,
)
from tower.capture import CaptureFollower  # noqa: E402
from tower.world_builder.engine import WorldBuilderEngine  # noqa: E402
from tower.world_builder.intrinsics_store import IntrinsicsStore  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402

logger = logging.getLogger("tower.world_builder_corpus_benchmark")

# ---------------------------------------------------------------------
# The pinned corpus. NEVER glob data/captures.
#
# Matched by directory-name PREFIX so the constant stays readable, but
# the match is required to be UNIQUE: a prefix that becomes ambiguous as
# the corpus grows is an error, not a coin flip.
# ---------------------------------------------------------------------
PINNED_PREFIXES = (
    "e1c52b9f",
    "22e9d428",
    "b35d8ab8",
    "20ce3c23",
    "2e6cffa2",
    "fe744b68",
    "64f48114",
    "4fea31e2",
)

DEFAULT_CAPTURES_ROOT = Path(r"C:\Users\tvllo\Projects\Glasses\tower\data\captures")

# The MAIN checkout's world root. Read-only, and only ever for
# intrinsics/360x640.json -- the same calibration world_build_session.py
# discovers by observed resolution. Nothing is ever written here.
MAIN_WORLD_ROOT = Path(r"C:\Users\tvllo\Projects\Glasses\tower\data\world_builder")

# Every capture in the pinned corpus was recorded at this size. Asserted
# per capture rather than assumed: a calibration applied to the wrong
# resolution produces a plausible trajectory that is wrong, which is the
# worst failure available to this instrument.
EXPECTED_RESOLUTION = (360, 640)

# A fragment has to have this many points before anyone would draw it.
MIN_DRAWABLE_POINTS = 20

# The iOS card-fitting rule, mirrored here so the benchmark can say
# whether a fragment would be LEGIBLE on the phone rather than merely
# non-empty. Kept as named constants because these three numbers are a
# contract with the iOS side, not tuning knobs.
CARD_POINTS = 140.0
CARD_FIT_MARGIN = 0.9
LEGIBLE_MIN_POINTS = 20.0

# Percentile band used for the "core" of a cloud, on both the blowup
# ratio and the legibility fit.
CORE_LO = 2.0
CORE_HI = 98.0

# The follower polls; these keep it bounded. Every pinned capture is
# already closed, so the read completes in one pass and neither of these
# ever actually sleeps.
POLL_SECONDS = 0.05
MAX_IDLE_POLLS = 2

# Windows MAX_PATH, checked UP FRONT rather than discovered halfway
# through a 20-minute replay. The deepest path a WorldStore writes is
#
#   <scratch>\<prefix>\worlds\<32>\sessions\<32>\images\<32>.jpg
#
# which is 135 characters after the scratch root. A long-path-unaware
# mkdir fails with WinError 206 somewhere inside `start_session`, and
# the resulting traceback says nothing about the actual problem being
# the directory the operator chose. 120 leaves a little headroom.
STORE_PATH_BUDGET = 135
MAX_SCRATCH_ROOT_CHARS = 260 - STORE_PATH_BUDGET - 5


class BenchmarkError(RuntimeError):
    """Anything that would make a recorded number untrustworthy.

    Deliberately fatal to the whole run. A partial corpus silently
    compared against a full one is the failure this instrument exists to
    make impossible.
    """


# ---------------------------------------------------------------------
# Corpus resolution
# ---------------------------------------------------------------------


def resolve_pinned_captures(captures_root: Path, prefixes) -> list[tuple[str, Path]]:
    """Map each pinned prefix to exactly one capture directory.

    Never globs for the SET -- the set is the constant. It globs only to
    expand each already-chosen prefix, and refuses anything but a unique
    hit.
    """
    if not captures_root.is_dir():
        raise BenchmarkError(f"no capture corpus directory at {captures_root}")

    try:
        entries = sorted(p for p in captures_root.iterdir() if p.is_dir())
    except OSError as exc:
        raise BenchmarkError(f"cannot list capture corpus {captures_root}: {exc}") from exc

    resolved: list[tuple[str, Path]] = []
    for prefix in prefixes:
        matches = [p for p in entries if p.name.startswith(prefix)]
        if not matches:
            raise BenchmarkError(
                f"pinned capture prefix {prefix!r} matched NO directory under "
                f"{captures_root}. The pinned corpus is a fixed set; a missing "
                f"capture is a broken benchmark, not a capture to skip."
            )
        if len(matches) > 1:
            names = ", ".join(p.name for p in matches)
            raise BenchmarkError(
                f"pinned capture prefix {prefix!r} is AMBIGUOUS under "
                f"{captures_root}: matched {len(matches)} directories ({names}). "
                f"Lengthen the prefix in PINNED_PREFIXES."
            )
        resolved.append((prefix, matches[0]))
    return resolved


# ---------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------


def journal_frames(directory: Path):
    """Yield a capture's frames from its JOURNAL, never from a glob.

    A copy of `world_build_session.follow_capture` with exactly one
    change -- `follow_reconnects=False` -- for the reasons in the module
    docstring. The `ObservedFrame` it yields is the driver's own type,
    imported, so the two cannot drift in shape.
    """
    if not directory.exists():
        raise BenchmarkError(f"no capture directory at {directory}")
    follower = CaptureFollower(
        directory,
        poll_seconds=POLL_SECONDS,
        follow_reconnects=False,
    )
    for frame in follower.follow(max_idle_polls=MAX_IDLE_POLLS):
        yield ObservedFrame(
            payload=frame.raw_bytes,
            source_seq=frame.source_seq,
            wire_seq=frame.wire_seq,
            tx_seq=frame.tx_seq,
            received_at=frame.received_at,
            width=frame.width,
            height=frame.height,
        )


# ---------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------


def _core_band(values: np.ndarray) -> tuple[float, float]:
    """The p2/p98 band of a 1-D array.

    `method="linear"` is pinned rather than left to the numpy default so
    that a numpy upgrade cannot move a benchmark number underneath a
    comparison.
    """
    lo, hi = np.percentile(values, (CORE_LO, CORE_HI), method="linear")
    return float(lo), float(hi)


def bbox_blowup(xyz: np.ndarray) -> float | None:
    """How far the full bounding box overruns the p2-p98 core.

    (max over x/y/z of full extent) / (max over x/y/z of core extent).
    A handful of badly-triangulated points can inflate the full box by
    orders of magnitude while the structure a human would recognise sits
    inside the core; this ratio is the number that says so.

    None -- never 0, never an exception -- when there are no points at
    all, and equally when the core has no extent to divide by. Both mean
    "not measurable", and reporting either as 0 would let an empty
    session read as a perfectly tight one.

    NOTE: computed over ALL points in the session, as specified, even
    though segments do NOT share a coordinate frame or a unit (see
    engine.build). Between-segment offsets therefore contribute to the
    numerator. That is fine for an A/B ratio -- both runs see the same
    offsets -- but the absolute value is not a physical measurement.
    """
    if xyz.size == 0:
        return None
    full = float(np.max(xyz.max(axis=0) - xyz.min(axis=0)))
    core = 0.0
    for axis in range(3):
        lo, hi = _core_band(xyz[:, axis])
        core = max(core, hi - lo)
    if core <= 0.0:
        return None
    return full / core


def fragment_counts(points: list[dict]) -> tuple[int, int]:
    """(drawable_fragments, legible_fragments).

    Drawable: a segment with at least MIN_DRAWABLE_POINTS points.
    Legible: of those, the ones whose p2-p98 core still occupies at
    least LEGIBLE_MIN_POINTS when the fragment is fitted to a
    CARD_POINTS-wide card by the iOS rule, on the X and Z axes -- the
    ground plane, which is what the card shows.
    """
    by_segment: dict[int, list[list[float]]] = {}
    for row in points:
        by_segment.setdefault(int(row["segment_index"]), []).append(row["xyz"])

    drawable = 0
    legible = 0
    for _segment, rows in sorted(by_segment.items()):
        if len(rows) < MIN_DRAWABLE_POINTS:
            continue
        drawable += 1
        xyz = np.asarray(rows, dtype=float)
        x = xyz[:, 0]
        z = xyz[:, 2]
        span_x = max(float(x.max() - x.min()), 1e-6)
        span_z = max(float(z.max() - z.min()), 1e-6)
        scale = min(CARD_POINTS / span_x, CARD_POINTS / span_z) * CARD_FIT_MARGIN
        lo_x, hi_x = _core_band(x)
        lo_z, hi_z = _core_band(z)
        core = max(hi_x - lo_x, hi_z - lo_z)
        if core * scale >= LEGIBLE_MIN_POINTS:
            legible += 1
    return drawable, legible


def read_points_discarded(manifest: dict | None) -> dict:
    """The build's discard tally, or an empty one.

    `points_discarded` DOES NOT EXIST in the manifest today and is
    expected to appear alongside the triangulation change this benchmark
    is meant to judge. Its absence is therefore the normal case right
    now and must never crash -- but it must also not be invented, so a
    missing key reads as {} and a present one is passed through
    untouched.
    """
    if not isinstance(manifest, dict):
        return {}
    value = manifest.get("points_discarded")
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    # Present but not the shape promised. Surfaced rather than dropped:
    # a silently discarded diagnostic is how a benchmark starts lying.
    return {"_unexpected_shape": repr(value)}


# ---------------------------------------------------------------------
# One capture
# ---------------------------------------------------------------------


def run_capture(
    prefix: str,
    capture_dir: Path,
    scratch_root: Path,
    intrinsics_store: IntrinsicsStore,
) -> dict:
    """Replay one pinned capture and measure it. Raises rather than skips."""
    # Re-seeded per capture so a --only subset measures each capture
    # identically to a full run. Order must not be an input.
    cv2.setRNGSeed(0)

    started = time.perf_counter()
    capture_id = capture_dir.name

    frames = journal_frames(capture_dir)
    first, frames = first_observed_frame(frames)
    if first is None:
        raise BenchmarkError(
            f"pinned capture {capture_id} delivered NO frames. On the live "
            f"path that is a phone that dropped; in a pinned benchmark corpus "
            f"it is a broken input, and recording zeros for it would put a "
            f"fake zero into the verdict."
        )

    observed_size = observed_size_of(first)
    if observed_size is None:
        raise BenchmarkError(
            f"could not observe the frame resolution of pinned capture "
            f"{capture_id}; refusing to guess a calibration."
        )
    if tuple(observed_size) != EXPECTED_RESOLUTION:
        raise BenchmarkError(
            f"pinned capture {capture_id} measures "
            f"{observed_size[0]}x{observed_size[1]}, not "
            f"{EXPECTED_RESOLUTION[0]}x{EXPECTED_RESOLUTION[1]}. The corpus is "
            f"documented as uniform at that size; nothing here rescales a "
            f"calibration."
        )

    # The same resolution-keyed lookup world_build_session performs, on
    # the MAIN checkout's store, opened read-only.
    intrinsics = resolve_intrinsics(
        intrinsics_store, observed_size, frame_source="capture-journal-replay"
    )
    if not intrinsics.is_known:
        raise BenchmarkError(
            f"no calibration for {observed_size[0]}x{observed_size[1]} in "
            f"{intrinsics_store.path_for(*observed_size)}. Without it the "
            f"unposed backend runs and EVERY capture reports 0 poses and 0 "
            f"points -- a corpus-wide fake zero, which is the single most "
            f"dangerous output this tool could produce."
        )

    # Keyed by the 8-char prefix, not the 32-char capture id: the store
    # nests worlds/<uuid>/sessions/<uuid>/images/<uuid>.jpg underneath
    # this, and on Windows those 24 extra characters are the difference
    # between a run and a WinError 206.
    store = WorldStore(scratch_root / prefix)
    engine = WorldBuilderEngine(store)
    world_id = engine.create_world(f"corpus:{prefix}")
    session_id = engine.start_session(
        world_id,
        intrinsics=intrinsics,
        frame_source="capture-journal-replay",
        # None, always: the size is MEASURED per keyframe off the decoded
        # frame. Declaring one here is the 2026-08-24 bug.
        declared_size=None,
        capture_id=capture_id,
    )

    for frame in frames:
        engine.observe(
            frame.payload,
            received_at=frame.received_at,
            source_seq=frame.source_seq,
            wire_seq=frame.wire_seq,
            tx_seq=frame.tx_seq,
        )

    summary = engine.stop_session()
    result = engine.build(world_id, session_id)

    manifest = store.read_derived_manifest(world_id)
    derived = store.read_derived(world_id, session_id)
    if derived is None:
        raise BenchmarkError(
            f"capture {capture_id} built {result.points} points but its "
            f"derived output could not be read back from "
            f"{store.derived_dir(world_id) / session_id}."
        )
    points = derived["points"]
    if len(points) != result.points:
        # The build result and the file it wrote must agree, or one of
        # the two numbers in every table below is fiction.
        raise BenchmarkError(
            f"capture {capture_id}: build reported {result.points} points but "
            f"points.json holds {len(points)}."
        )

    xyz = (
        np.asarray([row["xyz"] for row in points], dtype=float)
        if points
        else np.empty((0, 3), dtype=float)
    )
    drawable, legible = fragment_counts(points)

    return {
        "prefix": prefix,
        "capture_id": capture_id,
        "frames_observed": summary.frames_observed,
        "segments": result.segments,
        # The engine counts segments twice, from two places. They should
        # agree; recorded separately so a disagreement is visible rather
        # than resolved by whichever one this file happened to pick.
        "segments_observed": summary.segments,
        "keyframes": result.keyframes,
        "poses_solved": result.poses_solved,
        "poses_refused": result.poses_refused,
        "points": result.points,
        "points_discarded": read_points_discarded(manifest),
        "bbox_blowup": bbox_blowup(xyz),
        "legible_fragments": legible,
        "drawable_fragments": drawable,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "backend_id": result.backend_id,
        "downgraded_from": result.downgraded_from,
        "scale_state": result.scale_state,
    }


# ---------------------------------------------------------------------
# Run mode
# ---------------------------------------------------------------------


def totals_of(captures: list[dict]) -> dict:
    discarded: dict[str, float] = {}
    for capture in captures:
        for key, value in capture["points_discarded"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                discarded[key] = discarded.get(key, 0) + value
    blowups = [c["bbox_blowup"] for c in captures if c["bbox_blowup"] is not None]
    return {
        "captures": len(captures),
        "segments": sum(c["segments"] for c in captures),
        "keyframes": sum(c["keyframes"] for c in captures),
        "poses_solved": sum(c["poses_solved"] for c in captures),
        "poses_refused": sum(c["poses_refused"] for c in captures),
        "points": sum(c["points"] for c in captures),
        "points_discarded": discarded,
        "legible_fragments": sum(c["legible_fragments"] for c in captures),
        "drawable_fragments": sum(c["drawable_fragments"] for c in captures),
        "wall_seconds": round(sum(c["wall_seconds"] for c in captures), 3),
        # Not averaged. A mean over a ratio whose denominator differs per
        # capture is not a quantity; the worst case and how many captures
        # could not produce one are.
        "bbox_blowup_max": max(blowups) if blowups else None,
        "bbox_blowup_unmeasurable": len(captures) - len(blowups),
    }


def print_run_table(captures: list[dict], totals: dict) -> None:
    header = (
        f"{'capture':10s} {'segs':>5s} {'kf':>5s} {'solved':>7s} {'refused':>8s} "
        f"{'points':>8s} {'blowup':>8s} {'legible':>8s} {'drawable':>9s} {'secs':>8s}"
    )
    print(header)
    print("-" * len(header))
    for capture in captures:
        blowup = capture["bbox_blowup"]
        print(
            f"{capture['prefix']:10s} {capture['segments']:5d} "
            f"{capture['keyframes']:5d} {capture['poses_solved']:7d} "
            f"{capture['poses_refused']:8d} {capture['points']:8d} "
            f"{(f'{blowup:.2f}' if blowup is not None else 'n/a'):>8s} "
            f"{capture['legible_fragments']:8d} {capture['drawable_fragments']:9d} "
            f"{capture['wall_seconds']:8.2f}"
        )
    print("-" * len(header))
    # poses_solved is printed beside points here and everywhere else, on
    # purpose: a point count without the pose count that produced it
    # invites reading a pile of noise as progress.
    worst = totals["bbox_blowup_max"]
    print(
        f"{'TOTAL':10s} {totals['segments']:5d} {totals['keyframes']:5d} "
        f"{totals['poses_solved']:7d} {totals['poses_refused']:8d} "
        f"{totals['points']:8d} "
        # The corpus column is the WORST blowup, not a sum and not a
        # mean -- a ratio with a per-capture denominator does not add up.
        f"{(f'{worst:.2f}*' if worst is not None else 'n/a'):>8s} "
        f"{totals['legible_fragments']:8d} "
        f"{totals['drawable_fragments']:9d} {totals['wall_seconds']:8.2f}"
    )
    print("* blowup column on the TOTAL row is the worst capture, not a total.")
    if totals["bbox_blowup_unmeasurable"]:
        print(
            f"({totals['bbox_blowup_unmeasurable']} capture(s) had no measurable "
            f"bbox_blowup -- no points, or a core with no extent)"
        )


def do_run(args) -> int:
    captures_root = args.captures.resolve()
    scratch_root = args.scratch.resolve()

    # The corpus is an input. Writing anything into it -- even a stray
    # world directory -- would change what a later run measures.
    if scratch_root == captures_root or captures_root in scratch_root.parents:
        raise BenchmarkError(
            f"--scratch {scratch_root} is inside the READ-ONLY capture corpus "
            f"{captures_root}."
        )
    main_worlds = MAIN_WORLD_ROOT.resolve()
    if scratch_root == main_worlds or main_worlds in scratch_root.parents:
        raise BenchmarkError(
            f"--scratch {scratch_root} is inside {main_worlds}. Benchmark "
            f"output never goes into the real world store."
        )

    if len(str(scratch_root)) > MAX_SCRATCH_ROOT_CHARS:
        raise BenchmarkError(
            f"--scratch {scratch_root} is {len(str(scratch_root))} characters; "
            f"the world store needs {STORE_PATH_BUDGET} more beneath it and "
            f"Windows MAX_PATH is 260. Use a scratch root of at most "
            f"{MAX_SCRATCH_ROOT_CHARS} characters (the default temp dir is "
            f"short enough)."
        )

    prefixes = tuple(PINNED_PREFIXES)
    if args.only:
        wanted = [p.strip() for p in args.only.split(",") if p.strip()]
        unknown = [p for p in wanted if p not in PINNED_PREFIXES]
        if unknown:
            raise BenchmarkError(
                f"--only names prefixes that are not in the pinned set: "
                f"{', '.join(unknown)}. The pinned set is "
                f"{', '.join(PINNED_PREFIXES)}."
            )
        # Kept in PINNED_PREFIXES order, not in the order typed, so the
        # output of a subset run lines up with a full run.
        prefixes = tuple(p for p in PINNED_PREFIXES if p in wanted)

    resolved = resolve_pinned_captures(captures_root, prefixes)
    intrinsics_store = IntrinsicsStore(MAIN_WORLD_ROOT)
    scratch_root.mkdir(parents=True, exist_ok=True)

    print(f"label       {args.label}")
    print(f"corpus      {captures_root} (read-only)")
    print(f"intrinsics  {intrinsics_store.path_for(*EXPECTED_RESOLUTION)}")
    print(f"scratch     {scratch_root}")
    print(f"captures    {len(resolved)} of {len(PINNED_PREFIXES)} pinned")
    if len(resolved) != len(PINNED_PREFIXES):
        print("SUBSET RUN -- not comparable with a full-corpus run.")
    print()

    captures: list[dict] = []
    for index, (prefix, directory) in enumerate(resolved, start=1):
        logger.info(
            "[bench] %s/%s replaying %s (%s)",
            index,
            len(resolved),
            prefix,
            directory.name,
        )
        captures.append(run_capture(prefix, directory, scratch_root, intrinsics_store))

    totals = totals_of(captures)
    report = {
        "label": args.label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "captures_root": str(captures_root),
        "scratch_root": str(scratch_root),
        "pinned_prefixes": list(PINNED_PREFIXES),
        "prefixes_run": list(prefixes),
        "complete_corpus": len(resolved) == len(PINNED_PREFIXES),
        "captures": captures,
        "totals": totals,
    }

    print_run_table(captures, totals)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out.resolve()}")
    return 0


# ---------------------------------------------------------------------
# Compare mode
# ---------------------------------------------------------------------


def _load_report(path: Path) -> dict:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot read benchmark result {path}: {exc}") from exc
    if "captures" not in report or "totals" not in report:
        raise BenchmarkError(f"{path} is not a benchmark result file")
    return report


def do_compare(paths) -> int:
    left_path, right_path = Path(paths[0]), Path(paths[1])
    left, right = _load_report(left_path), _load_report(right_path)

    left_by = {c["prefix"]: c for c in left["captures"]}
    right_by = {c["prefix"]: c for c in right["captures"]}
    if set(left_by) != set(right_by):
        only_left = ", ".join(sorted(set(left_by) - set(right_by))) or "none"
        only_right = ", ".join(sorted(set(right_by) - set(left_by))) or "none"
        raise BenchmarkError(
            "the two runs do not cover the same captures, so nothing about "
            f"them is comparable. Only in {left['label']}: {only_left}. "
            f"Only in {right['label']}: {only_right}."
        )

    order = [p for p in PINNED_PREFIXES if p in left_by]
    order += sorted(p for p in left_by if p not in PINNED_PREFIXES)

    print(f"A = {left['label']}   ({left_path})")
    print(f"B = {right['label']}   ({right_path})")
    print()

    header = (
        f"{'capture':10s} {'segsA':>6s} {'segsB':>6s} {'kfA':>6s} {'kfB':>6s} "
        f"{'solvedA':>8s} {'solvedB':>8s} {'d':>7s} "
        f"{'pointsA':>9s} {'pointsB':>9s} {'d':>8s}  inv"
    )
    print(header)
    print("-" * len(header))

    violations: list[str] = []
    for prefix in order:
        a, b = left_by[prefix], right_by[prefix]
        moved = a["segments"] != b["segments"] or a["keyframes"] != b["keyframes"]
        if moved:
            violations.append(prefix)
        print(
            f"{prefix:10s} {a['segments']:6d} {b['segments']:6d} "
            f"{a['keyframes']:6d} {b['keyframes']:6d} "
            f"{a['poses_solved']:8d} {b['poses_solved']:8d} "
            f"{b['poses_solved'] - a['poses_solved']:+7d} "
            f"{a['points']:9d} {b['points']:9d} "
            f"{b['points'] - a['points']:+8d}  "
            f"{'MOVED' if moved else 'ok'}"
        )

    lt, rt = left["totals"], right["totals"]
    print("-" * len(header))
    print(
        f"{'TOTAL':10s} {lt['segments']:6d} {rt['segments']:6d} "
        f"{lt['keyframes']:6d} {rt['keyframes']:6d} "
        f"{lt['poses_solved']:8d} {rt['poses_solved']:8d} "
        f"{rt['poses_solved'] - lt['poses_solved']:+7d} "
        f"{lt['points']:9d} {rt['points']:9d} "
        f"{rt['points'] - lt['points']:+8d}"
    )

    if violations:
        bar = "!" * len(header)
        print()
        print(bar)
        print("!!  VOID -- THIS COMPARISON MEANS NOTHING  !!")
        print(bar)
        print(
            "segments and/or keyframes MOVED on: " + ", ".join(violations) + "."
        )
        print(
            "Those are invariants for the change under test: keyframe selection\n"
            "and segmentation happen before triangulation and must be identical\n"
            "between the two runs. Movement means the change leaked outside its\n"
            "intended surface -- or the two runs did not see the same corpus, the\n"
            "same calibration, or the same code. Either way the pose and point\n"
            "deltas above are comparisons between two different experiments."
        )
        print()
        print("NO VERDICT. Fix the leak and re-run both sides.")
        print(bar)
        return 1

    print()
    print("invariants hold: segments and keyframes identical on every capture.")
    print()
    d_solved = rt["poses_solved"] - lt["poses_solved"]
    d_points = rt["points"] - lt["points"]
    # Never one without the other.
    print(
        f"corpus poses_solved {lt['poses_solved']} -> {rt['poses_solved']} "
        f"({d_solved:+d}), points {lt['points']} -> {rt['points']} ({d_points:+d})"
    )
    print(
        f"corpus legible_fragments {lt['legible_fragments']} -> "
        f"{rt['legible_fragments']} "
        f"({rt['legible_fragments'] - lt['legible_fragments']:+d}) of "
        f"drawable {lt['drawable_fragments']} -> {rt['drawable_fragments']}"
    )
    la, rb = lt.get("bbox_blowup_max"), rt.get("bbox_blowup_max")
    print(
        f"worst bbox_blowup {('%.2f' % la) if la is not None else 'n/a'} -> "
        f"{('%.2f' % rb) if rb is not None else 'n/a'}"
    )
    if lt.get("points_discarded") or rt.get("points_discarded"):
        print(
            f"points_discarded A={json.dumps(lt.get('points_discarded', {}))} "
            f"B={json.dumps(rt.get('points_discarded', {}))}"
        )
    return 0


# ---------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "A/B benchmark over a pinned set of real Ray-Ban captures. "
            "Run it once before a change and once after, then --compare."
        )
    )
    parser.add_argument("--label", default=None, help="Human label recorded in --out.")
    parser.add_argument("--out", type=Path, default=None, help="Write one JSON result.")
    parser.add_argument(
        "--only",
        default=None,
        help=(
            "Comma-separated subset of the PINNED prefixes, for smoke runs. "
            "Never adds captures; it can only narrow the pinned set."
        ),
    )
    parser.add_argument("--captures", type=Path, default=DEFAULT_CAPTURES_ROOT)
    parser.add_argument(
        "--scratch",
        type=Path,
        default=None,
        help="Where derived output goes. Default: a fresh temp directory.",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("A.json", "B.json"),
        default=None,
        help="Compare two result files instead of running.",
    )
    args = parser.parse_args(argv)

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    # Before ANY work, including the corpus scan. See "DETERMINISM" in
    # the module docstring: replay is empirically bit-deterministic on
    # this host, but backends/classical.py:605-607 states the RANSAC
    # calls are unseeded, so this pins determinism rather than assuming
    # it.
    cv2.setRNGSeed(0)

    try:
        if args.compare:
            if args.label or args.out or args.only:
                parser.error("--compare takes no --label, --out or --only")
            return do_compare(args.compare)

        if not args.label:
            parser.error("--label is required for a run (or use --compare)")
        if args.scratch is None:
            args.scratch = Path(tempfile.mkdtemp(prefix="wb-corpus-bench-"))
        return do_run(args)
    except BenchmarkError as exc:
        print(f"\nBENCHMARK ABORTED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
