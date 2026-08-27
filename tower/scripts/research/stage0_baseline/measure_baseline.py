#!/usr/bin/env python
"""Stage 0 baseline: the pinned-corpus benchmark, PLUS what it does not emit.

WHY THIS EXISTS AND WHAT IT IS NOT

`scripts/world_builder_corpus_benchmark.py` is the measuring instrument for
this corpus and this file does not replace it. Every base number below --
frames, keyframes, segments, poses, points, blowup, fragments, coherence --
is produced by CALLING that module's own functions (`resolve_pinned_captures`,
`run_capture`, `run_controls`, `totals_of`), never by a re-implementation
here. If the two ever disagree, the disagreement is a bug in this file, not a
second opinion, and the shipped harness wins.

What this file adds is measurement the shipped harness has no field for:

  * OBSERVATION COUNT PER LANDMARK -- the whole distribution, from
    support.json's (segment, frame, feature, point) association. A mean
    hides the thing that matters: a reconstruction whose landmarks are
    mostly two-view is a pile of independent triangulations, not a map.
  * COVISIBILITY -- how many keyframe PAIRS actually share a landmark, and
    the degree distribution over keyframes. Two-view landmarks produce a
    covisibility graph that is a chain; anything better produces a mesh.
  * REGISTRATION -- segments and points actually placed in a shared frame,
    and how many CLUSTERS those placements form. Computed by calling
    `scripts/world_registration.register` on the built world, not by
    reimplementing the gate.
  * REPROJECTION -- recomputed cold from poses.json + points.json +
    support.json + the keyframe images, because no per-landmark residual is
    persisted anywhere. See `reprojection_stats` for why this is a
    RECONSTRUCTED number and what it can and cannot be compared against.
  * RUNTIME and PEAK MEMORY, per phase.
  * DETERMINISM, at two scales, because the first Stage 0 run found the
    pipeline is NOT bit-for-bit reproducible on this host and that changes
    what every later comparison is allowed to claim. `determinism_check`
    replays ONE capture in N fresh processes; `corpus_repeat_check` re-runs
    the whole shipped harness N times in fresh processes, which is the noise
    floor an A/B verdict actually has to clear.
  * CONFIGURATION, because `redaction.DEFAULT_MODEL_PATH` is relative and so
    the face detector is silently on or off depending on the cwd. See
    `configuration_block`.

THE STANDARD FOR A MISSING NUMBER

`None` (JSON null) means NOT MEASURED, and every site that can produce one
says why, either in a `reason` field beside it or in a `_note` key. A zero in
this file always means a measured zero. That rule is inherited from the
shipped harness's docstring and it is the reason its numbers can be trusted
across a change; breaking it here would make this baseline useless as a
control.

A CAPTURE THAT FAILS IS RECORDED, NOT DROPPED

The shipped harness aborts the whole run when one capture cannot be measured,
which is right for an A/B verdict. For a BASELINE the useful behaviour is
different: record the failure with its exception text under
`capture_failures`, mark `complete_corpus: false`, keep going, and exit
non-zero. A partial baseline that names its gaps beats a complete-looking one
that is wrong.

The corpus itself is still pinned and still hard-fails: a prefix matching zero
or several directories aborts the whole run, because that is a broken corpus
rather than a broken capture.

USAGE

    python scripts/research/stage0_baseline/measure_baseline.py \
        --label HEAD_d3d24b5 \
        --out scripts/research/stage0_baseline/baseline_HEAD_d3d24b5.json

    # determinism only, canonical capture, N fresh child processes
    python scripts/research/stage0_baseline/measure_baseline.py \
        --label x --determinism-repeats 3 --determinism-only

    # internal: one capture in a fresh process, fingerprint to stdout
    python scripts/research/stage0_baseline/measure_baseline.py \
        --probe 22e9d428 --scratch <dir>
"""

import argparse
import hashlib
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
TOWER = HERE.parent.parent.parent.parent          # .../tower
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(TOWER / "scripts"))

import cv2                                         # noqa: E402
import numpy as np                                 # noqa: E402

import world_builder_corpus_benchmark as bench     # noqa: E402
import world_registration as reg                   # noqa: E402
from tower.world_builder.intrinsics_store import IntrinsicsStore  # noqa: E402
from tower.world_builder.store import WorldStore   # noqa: E402

# The one capture the research names as canonical. Determinism is checked on
# it specifically so this baseline's verdict is comparable with that claim.
CANONICAL_PREFIX = "22e9d428"

# Support counts at or above these are reported as fractions. 2 is the floor a
# triangulated landmark can have at all (it took two views to make it); 3 is
# the first count that carries an independent check on the triangulation; 5 is
# where a landmark starts to constrain a pose graph rather than ride on it.
SUPPORT_TIERS = (2, 3, 5)

# A covisibility edge is normally not counted below some shared-landmark
# floor, because one or two shared points is noise. Both the ANY-edge graph
# and the strong graph are reported: the first says what the association
# literally contains, the second what a pose graph would actually use.
COVIS_STRONG_MIN_SHARED = 15
COVIS_STRONG_KEY = (
    f"keyframe_pairs_sharing_ge_{COVIS_STRONG_MIN_SHARED}_landmarks"
)

FINGERPRINT_MARKER = "<<<FINGERPRINT>>>"


def _psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def peak_rss_bytes():
    """Process peak working set, or None.

    `peak_wset` is the OS's own high-water mark for this process, so it
    covers OpenCV's native allocations, which tracemalloc cannot see. On a
    platform or interpreter without it there is no honest substitute, so the
    answer is None rather than current RSS dressed up as a peak.
    """
    ps = _psutil()
    if ps is None:
        return None
    info = ps.Process(os.getpid()).memory_info()
    value = getattr(info, "peak_wset", None)
    return int(value) if value is not None else None


def sha256_of(path: Path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentiles(values, points=(50, 90, 95, 99)):
    """p50/p90/p95/p99, or all-None when there is nothing to take them of.

    `method="linear"` is pinned rather than left to the numpy default for the
    same reason the shipped harness pins it: a numpy upgrade must not move a
    baseline number underneath a comparison.
    """
    if len(values) == 0:
        return {f"p{p}": None for p in points}
    array = np.asarray(values, dtype=float)
    return {
        f"p{p}": float(np.percentile(array, p, method="linear"))
        for p in points
    }


def _histogram(values):
    out = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return {str(k): out[k] for k in sorted(out)}


# ---------------------------------------------------------------------
# The metrics the shipped harness does not emit
# ---------------------------------------------------------------------


def support_stats(points, support):
    """Observation count per landmark, as a full distribution.

    A support row is [segment, frame, feature, point], and BOTH the frame and
    point indices are segment-local (engine.py, the support_rows comment), so
    a landmark is identified by the PAIR (segment, point) and never by `point`
    alone. Collapsing them would merge segment 3's landmark 17 with segment
    9's and inflate every observation count in the corpus.

    AN OBSERVATION IS A DISTINCT VIEW, NOT A ROW. Two support rows naming the
    same keyframe -- two features in one image matched to one landmark -- are
    one view of that landmark, and counting them as two would manufacture
    multiplicity that no additional camera position supports. This is also the
    definition the prior research used
    (`scripts/research/slam_classical/production_covisibility.py`), so the
    66.1%-two-view figure and the number here are the same quantity measured
    on different geometry rather than two different quantities. `support_rows`
    is reported beside it so the gap between the two is visible.

    Landmarks with no support row are counted at ZERO observations and
    reported separately rather than dropped. support.json is an index into the
    reconstruction rather than part of it, so it can legitimately be
    incomplete; a silently shortened denominator would inflate every fraction
    below and there would be nothing in the output to reveal it. The prior
    research's denominator was "landmarks WITH a support record"; this one is
    every published landmark, so `landmarks_with_no_support_row` is the number
    that reconciles the two.
    """
    if support is None:
        return {
            "measured": False,
            "reason": (
                "support.json absent -- the 2-D/3-D association is not on "
                "disk for this world, so no observation count exists to "
                "distribute"
            ),
        }

    # Rebuild the segment-local point ordinal exactly the way the engine wrote
    # it: point rows are appended segment by segment, in sorted segment order,
    # so a point's position within its own segment is its ordinal there.
    counters = {}
    local_of = {}
    for row in points:
        segment = int(row["segment_index"])
        local = counters.get(segment, 0)
        counters[segment] = local + 1
        local_of.setdefault(segment, []).append(local)

    views = {}
    rows_per_landmark = {}
    landmark_of_feature = {}
    contested_features = set()
    orphan_rows = 0
    for row in support:
        segment, frame, feature, point = (int(v) for v in row)
        # One 2-D feature associated with two DIFFERENT landmarks. Measured
        # because `world_registration.read_segments` builds its association as
        # `{(frame, feature): point}`, so every such row silently overwrites
        # its predecessor there and vanishes from anything built on that
        # reader -- including the reprojection block below, whose denominator
        # is short by exactly this many rows.
        key = (segment, frame, feature)
        previous = landmark_of_feature.get(key)
        if previous is not None and previous != point:
            contested_features.add(key)
        else:
            landmark_of_feature[key] = point
        if point >= counters.get(segment, 0):
            # A support row pointing past the end of its segment's points.
            # Counted, never silently ignored: it would mean support.json and
            # points.json disagree about what was published, which is a defect
            # in the build and not a rounding detail.
            orphan_rows += 1
            continue
        views.setdefault((segment, point), set()).add(frame)
        rows_per_landmark[(segment, point)] = (
            rows_per_landmark.get((segment, point), 0) + 1
        )

    total_landmarks = len(points)
    counts = []
    row_counts = []
    for segment, locals_ in local_of.items():
        for local in locals_:
            counts.append(len(views.get((segment, local), ())))
            row_counts.append(rows_per_landmark.get((segment, local), 0))
    duplicate_view_rows = sum(row_counts) - sum(counts)

    tiers = {}
    for tier in SUPPORT_TIERS:
        hits = sum(1 for value in counts if value >= tier)
        tiers[f"landmarks_ge_{tier}_views"] = hits
        tiers[f"fraction_ge_{tier}_views"] = (
            hits / total_landmarks if total_landmarks else None
        )
    exactly_two = sum(1 for value in counts if value == 2)
    return {
        "measured": True,
        "observation_unit": "distinct keyframe views per landmark",
        "total_landmarks": total_landmarks,
        "support_rows": len(support),
        "orphan_support_rows": orphan_rows,
        # Support rows naming a keyframe that already observes the landmark.
        # Reported so `support_rows` and the histogram can be reconciled
        # exactly: support_rows == sum(views) + duplicates + orphans.
        "duplicate_view_support_rows": duplicate_view_rows,
        "features_bound_to_more_than_one_landmark": len(contested_features),
        "landmarks_with_no_support_row": sum(1 for v in counts if v == 0),
        "observations_histogram": _histogram(counts),
        "observations_min": min(counts) if counts else None,
        "observations_max": max(counts) if counts else None,
        "observations_mean": (sum(counts) / len(counts)) if counts else None,
        "observations_median": (
            float(statistics.median(counts)) if counts else None
        ),
        **percentiles(counts),
        **tiers,
        "landmarks_exactly_2_views": exactly_two,
        "fraction_exactly_2_views": (
            exactly_two / total_landmarks if total_landmarks else None
        ),
    }


def covisibility_stats(keyframes, support):
    """How many keyframe PAIRS share a landmark, and the degree distribution.

    A keyframe here is (segment, segment-local frame index), because that is
    the only identifier support.json carries. Landmarks never cross a segment
    boundary -- segments do not share a coordinate frame -- so this graph is
    block-diagonal by construction and every pair below is within one segment.
    That is a property OF the reconstruction, not a limitation of the
    measurement, and it is precisely what the number is for: a pipeline whose
    covisibility graph cannot cross a segment cannot close a loop.

    `keyframes_total` is every keyframe in the journal, including those that
    never contributed an observation, so `keyframes_with_no_observation` is a
    fraction of the whole session and not of a pre-filtered subset.
    """
    if support is None:
        return {
            "measured": False,
            "reason": (
                "support.json absent -- covisibility cannot be derived "
                "without the 2-D/3-D association"
            ),
        }

    frames_of_landmark = {}
    seen_keyframes = set()
    for row in support:
        segment, frame, _feature, point = (int(v) for v in row)
        frames_of_landmark.setdefault((segment, point), set()).add(
            (segment, frame)
        )
        seen_keyframes.add((segment, frame))

    pair_weight = {}
    for nodes in frames_of_landmark.values():
        ordered = sorted(nodes)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                edge = (ordered[i], ordered[j])
                pair_weight[edge] = pair_weight.get(edge, 0) + 1

    degree = {}
    strong_degree = {}
    for (a, b), weight in pair_weight.items():
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
        if weight >= COVIS_STRONG_MIN_SHARED:
            strong_degree[a] = strong_degree.get(a, 0) + 1
            strong_degree[b] = strong_degree.get(b, 0) + 1

    degrees = [degree.get(node, 0) for node in sorted(seen_keyframes)]
    strong = [strong_degree.get(node, 0) for node in sorted(seen_keyframes)]
    weights = list(pair_weight.values())

    return {
        "measured": True,
        "keyframes_total": len(keyframes),
        "keyframes_in_support": len(seen_keyframes),
        "keyframes_with_no_observation": len(keyframes) - len(seen_keyframes),
        "keyframe_pairs_sharing_any_landmark": len(pair_weight),
        COVIS_STRONG_KEY: sum(
            1 for w in weights if w >= COVIS_STRONG_MIN_SHARED
        ),
        "shared_landmarks_per_pair_median": (
            float(statistics.median(weights)) if weights else None
        ),
        "shared_landmarks_per_pair_max": max(weights) if weights else None,
        # Degrees are over keyframes that appear in the association at all.
        # Including the silent ones would drag the median toward zero and say
        # more about keyframe admission than about covisibility; they are
        # reported separately above instead.
        "degree_median": float(statistics.median(degrees)) if degrees else None,
        "degree_mean": (sum(degrees) / len(degrees)) if degrees else None,
        "degree_max": max(degrees) if degrees else None,
        "degree_histogram": _histogram(degrees),
        "strong_degree_median": (
            float(statistics.median(strong)) if strong else None
        ),
        "strong_degree_max": max(strong) if strong else None,
    }


def reprojection_stats(store, world_id, session_id):
    """Per-landmark reprojection error, RECONSTRUCTED cold.

    Nothing persists a residual. What IS persisted is enough to recompute one:
    poses.json (T_world_camera), points.json (segment-frame XYZ), support.json
    ((frame, feature) -> point) and the keyframe images. The feature index is
    an index into `geometry.detect_and_describe`'s output for that image, so
    the keypoints are re-detected with the same ORB call the backend used and
    indexed the same way.

    Three caveats, which is why this is reported in its own block rather than
    mixed in with the harness's own numbers:

      1. It re-runs ORB. If a future OpenCV changes ORB's ordering, this
         number moves without the reconstruction moving. It is a measurement
         OF this host and this OpenCV build, comparable between two runs on
         the same host -- which is exactly the comparison Stage 0 exists to
         support, and not a claim about the pipeline in the abstract.
      2. Only observations whose keyframe HAS a pose can be scored. A refused
         pose has no projection, so those observations are counted under
         `observations_without_pose` and excluded, rather than scored against
         an identity pose that would manufacture a huge plausible-looking
         error.
      3. The published bar, geometry.MAX_LANDMARK_REPROJECTION_PX = 3.0, is
         applied by the pipeline to the two SOURCE views of a landmark only.
         Re-observations and third views were never gated at 3 px, so
         `fraction_over_3px` is NOT a violation count -- it is the size of the
         ungated tail.

    Segment reading is `world_registration.read_segments`, the same reader
    registration uses, so the two cannot drift apart in how they join the four
    files.
    """
    try:
        segments = reg.read_segments(store, world_id, session_id)
    except reg.SupportMissingError as exc:
        return {"measured": False, "reason": str(exc)}

    errors = []
    without_pose = 0
    unprojectable = 0
    for segment in segments.values():
        camera = np.asarray(segment.intrinsics, dtype=np.float64)
        for (frame, feature), point_index in segment.observed.items():
            pose = segment.poses.get(frame)
            if pose is None:
                without_pose += 1
                continue
            keypoints = segment.keypoints[frame]
            if feature >= len(keypoints) or point_index >= len(segment.points):
                unprojectable += 1
                continue
            rotation, translation = pose
            camera_point = rotation @ segment.points[point_index] + translation
            if camera_point[2] <= 1e-9:
                # Behind the camera, or on it. That is not an error magnitude
                # -- it is a projection that does not exist. Counted, never
                # folded into a median it would silently dominate.
                unprojectable += 1
                continue
            projected = camera @ camera_point
            projected = projected[:2] / projected[2]
            errors.append(
                float(np.linalg.norm(projected - keypoints[feature]))
            )

    common = {
        "measured": True,
        "observations_scored": len(errors),
        "observations_without_pose": without_pose,
        "observations_unprojectable": unprojectable,
        "_note": (
            "recomputed by re-detecting ORB and re-projecting; the pipeline "
            "persists no residual. The 3 px bar is enforced on source views "
            "only, so fraction_over_3px is the ungated tail, not a violation "
            "count."
        ),
    }
    if not errors:
        return {
            **common,
            "mean_px": None, "median_px": None, "max_px": None,
            "p50_px": None, "p90_px": None, "p95_px": None, "p99_px": None,
            "fraction_over_3px": None,
        }
    array = np.asarray(errors)
    pct = percentiles(errors)
    return {
        **common,
        "mean_px": float(array.mean()),
        "median_px": float(np.median(array)),
        "max_px": float(array.max()),
        "p50_px": pct["p50"], "p90_px": pct["p90"],
        "p95_px": pct["p95"], "p99_px": pct["p99"],
        "fraction_over_3px": float((array > 3.0).mean()),
    }


def registration_stats(store, world_id, session_id):
    """Registered segments, points and CLUSTERS.

    Calls `world_registration.register`, the shipped gate, rather than
    reimplementing it. The gate's whole design is that admission requires
    independent agreement between two directions; a second implementation of
    that would be a second gate with different bugs and would make the
    baseline a measurement of this file instead of the branch.

    `registered_clusters` is the connected components of the ADMITTED pair
    graph restricted to segments that were actually placed. The report already
    says how many segments were placed; it does not say whether they were
    placed into ONE shared space or into several mutually unregistered
    islands, and that distinction is the entire point of registering anything.

    RANSAC is re-seeded here for the same reason the harness seeds it before
    every capture: the PnP inside the fit is unseeded by default, and an
    unseeded number cannot be a baseline.
    """
    cv2.setRNGSeed(0)
    started = time.perf_counter()
    try:
        report = reg.register(store, world_id, session_id)
    except reg.SupportMissingError as exc:
        return {"measured": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        # Recorded as unmeasured with the exception text, never as zeros.
        # Registration is an analysis pass over an already-built world; its
        # failure must not erase the reconstruction numbers beside it.
        return {
            "measured": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "wall_seconds": round(time.perf_counter() - started, 3),
        }

    registered = {
        row["segment_index"] for row in report["segments"] if row["registered"]
    }
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in report["admitted_pairs"]:
        if a in registered and b in registered:
            union(a, b)
    for index in registered:
        find(index)

    clusters = {}
    for index in registered:
        clusters.setdefault(find(index), []).append(index)
    sizes = sorted((len(v) for v in clusters.values()), reverse=True)

    points_by_segment = {
        row["segment_index"]: row.get("points", 0)
        for row in report["segments"]
    }
    cluster_points = sorted(
        (sum(points_by_segment.get(i, 0) for i in members)
         for members in clusters.values()),
        reverse=True,
    )

    return {
        "measured": True,
        "segment_count": report["segment_count"],
        "segments_with_geometry": report["segments_with_geometry"],
        "segments_registered": report["segments_registered"],
        "points_total": report["points_total"],
        "points_registered": report["points_registered"],
        "fraction_points_registered": (
            report["points_registered"] / report["points_total"]
            if report["points_total"] else None
        ),
        "candidate_pairs": report["candidate_pairs"],
        "admitted_pairs": len(report["admitted_pairs"]),
        "cycles_checked": report["cycles_checked"],
        "cycle_refusal": report["cycle_refusal"],
        "registered_clusters": len(clusters),
        "registered_cluster_sizes": sizes,
        "largest_registered_cluster_segments": sizes[0] if sizes else 0,
        "largest_registered_cluster_points": (
            cluster_points[0] if cluster_points else 0
        ),
        "reference_segment": report["reference_segment"],
        "wall_seconds": round(time.perf_counter() - started, 3),
    }


# ---------------------------------------------------------------------
# One capture: base metrics from the shipped harness, then the rest
# ---------------------------------------------------------------------


def measure_capture(prefix, directory, scratch_root, intrinsics_store,
                    with_registration=True, with_reprojection=True):
    phase = {}
    started = time.perf_counter()
    # THE base numbers. Produced by the shipped harness's own function so this
    # file cannot become a second opinion about them.
    base = bench.run_capture(prefix, directory, scratch_root, intrinsics_store)
    phase["replay_and_build_seconds"] = round(time.perf_counter() - started, 3)

    store = WorldStore(scratch_root / prefix)
    world_ids = store.list_world_ids()
    if len(world_ids) != 1:
        raise bench.BenchmarkError(
            f"scratch for {prefix} holds {len(world_ids)} worlds; expected "
            f"exactly one. Extended metrics cannot name a world."
        )
    world_id = world_ids[0]
    session_ids = store.list_session_ids(world_id)
    if len(session_ids) != 1:
        raise bench.BenchmarkError(
            f"world {world_id} holds {len(session_ids)} sessions; expected "
            f"exactly one."
        )
    session_id = session_ids[0]

    session = store.read_session(world_id, session_id)
    keyframes = store.read_keyframes(world_id, session_id)
    manifest = store.read_derived_manifest(world_id) or {}
    derived = store.read_derived(world_id, session_id)
    if derived is None:
        raise bench.BenchmarkError(
            f"{prefix}: derived output unreadable after a successful build, "
            f"so nothing below it can be measured."
        )

    derived_dir = store.derived_dir(world_id) / session_id
    keyframes_by_segment = {}
    for keyframe in keyframes:
        keyframes_by_segment[keyframe.segment_index] = (
            keyframes_by_segment.get(keyframe.segment_index, 0) + 1
        )

    started = time.perf_counter()
    support = support_stats(derived["points"], derived.get("support"))
    covis = covisibility_stats(keyframes, derived.get("support"))
    phase["association_analysis_seconds"] = round(
        time.perf_counter() - started, 3
    )

    if with_reprojection:
        started = time.perf_counter()
        reprojection = reprojection_stats(store, world_id, session_id)
        phase["reprojection_seconds"] = round(time.perf_counter() - started, 3)
    else:
        reprojection = {
            "measured": False,
            "reason": "--no-reprojection was passed; not attempted",
        }
        phase["reprojection_seconds"] = None

    if with_registration:
        registration = registration_stats(store, world_id, session_id)
        phase["registration_seconds"] = registration.get("wall_seconds")
    else:
        registration = {
            "measured": False,
            "reason": "--no-registration was passed; not attempted",
        }
        phase["registration_seconds"] = None

    extended = {
        "world_id": world_id,
        "session_id": session_id,
        "input_digest": manifest.get("input_digest"),
        "keyframes_rejected_total": sum(session.rejected_by_reason.values()),
        "keyframes_rejected_by_reason": dict(session.rejected_by_reason),
        "keyframes_accepted": session.keyframes_accepted,
        "end_reason": session.end_reason,
        "keyframes_per_segment_max": (
            max(keyframes_by_segment.values()) if keyframes_by_segment else 0
        ),
        "keyframes_per_segment_median": (
            float(statistics.median(list(keyframes_by_segment.values())))
            if keyframes_by_segment else None
        ),
        "segments_with_only_one_keyframe": sum(
            1 for v in keyframes_by_segment.values() if v == 1
        ),
        "poses_refused_root": manifest.get("poses_refused_root"),
        "poses_refused_cascaded": manifest.get("poses_refused_cascaded"),
        "refusal_degeneracy_counts": manifest.get("refusal_degeneracy_counts"),
        "poses_anchor": manifest.get("poses_anchor"),
        "poses_positioned": manifest.get("poses_positioned"),
        "points_triangulated": manifest.get("points_triangulated"),
        "landmark_support": support,
        "covisibility": covis,
        "reprojection": reprojection,
        "registration": registration,
        # points.json and support.json carry no uuid and no timestamp, so a
        # deterministic pipeline makes them byte-identical between runs.
        # poses.json carries freshly generated keyframe uuids, so its hash is
        # EXPECTED to differ run to run and is recorded for completeness only.
        "derived_sha256": {
            "points.json": sha256_of(derived_dir / "points.json"),
            "support.json": sha256_of(derived_dir / "support.json"),
            "poses.json": sha256_of(derived_dir / "poses.json"),
        },
        "phase_seconds": phase,
    }
    return {**base, "extended": extended}


# ---------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------


def probe(prefix, scratch_root):
    """One capture, in THIS process, printing a comparable fingerprint.

    Invoked as a child process by `determinism_check`. The fingerprint goes to
    stdout behind a marker so the parent can find it without depending on log
    formatting, which OpenCV writes to freely.
    """
    cv2.setRNGSeed(0)
    resolved = bench.resolve_pinned_captures(
        bench.DEFAULT_CAPTURES_ROOT, (prefix,)
    )
    _, directory = resolved[0]
    intrinsics_store = IntrinsicsStore(bench.MAIN_WORLD_ROOT)
    scratch_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    base = bench.run_capture(prefix, directory, scratch_root, intrinsics_store)

    store = WorldStore(scratch_root / prefix)
    world_id = store.list_world_ids()[0]
    session_id = store.list_session_ids(world_id)[0]
    derived = store.read_derived(world_id, session_id)
    derived_dir = store.derived_dir(world_id) / session_id
    fingerprint = {
        "prefix": prefix,
        "keyframes": base["keyframes"],
        "segments": base["segments"],
        "poses_solved": base["poses_solved"],
        "poses_refused": base["poses_refused"],
        "points": base["points"],
        "scale_state": base["scale_state"],
        "points_sha256": sha256_of(derived_dir / "points.json"),
        "support_sha256": sha256_of(derived_dir / "support.json"),
        "xyz": [row["xyz"] for row in derived["points"]],
        # keyframe_id is deliberately excluded: it is a fresh uuid every run
        # and would report a false difference. Segment, status, rotation and
        # translation are the whole of what the solve produced.
        "poses": [
            [row["segment_index"], row["status"], row["rotation"],
             row["translation"]]
            for row in derived["poses"]
        ],
        "wall_seconds": round(time.perf_counter() - started, 3),
        "peak_rss_bytes": peak_rss_bytes(),
    }
    sys.stdout.write(FINGERPRINT_MARKER + json.dumps(fingerprint))
    return 0


def determinism_check(prefix, repeats, scratch_root):
    """N fresh processes, then compare. The gate for every A/B tonight.

    Fresh PROCESSES, not fresh engines. An in-process repeat shares OpenCV's
    global RNG state, its thread pool and whatever caches the first run
    warmed, so it can reproduce perfectly while a real second run does not.
    Only a new process tests the thing an A/B comparison actually relies on --
    that a run made now and a run made after a code change differ only because
    of the change.
    """
    runs = []
    failures = []
    for index in range(repeats):
        command = [
            sys.executable, str(HERE), "--probe", prefix,
            "--scratch", str(scratch_root / f"det{index}"),
        ]
        started = time.perf_counter()
        completed = subprocess.run(
            command, capture_output=True, text=True, cwd=str(TOWER),
        )
        elapsed = round(time.perf_counter() - started, 3)
        if completed.returncode != 0:
            failures.append(
                f"determinism run {index} exited {completed.returncode}: "
                f"{completed.stderr[-2000:]}"
            )
            continue
        marker = completed.stdout.find(FINGERPRINT_MARKER)
        if marker < 0:
            failures.append(
                f"determinism run {index} produced no fingerprint; stdout "
                f"tail: {completed.stdout[-500:]}"
            )
            continue
        fingerprint = json.loads(
            completed.stdout[marker + len(FINGERPRINT_MARKER):]
        )
        fingerprint["subprocess_wall_seconds"] = elapsed
        runs.append(fingerprint)

    if len(runs) < 2:
        return {
            "measured": False,
            "reason": "fewer than two runs completed; nothing to compare",
            "repeats_requested": repeats,
            "repeats_completed": len(runs),
            "failures": failures,
        }

    first = runs[0]
    scalar_keys = ("keyframes", "segments", "poses_solved", "poses_refused",
                   "points", "scale_state")
    mismatches = []
    for index, run in enumerate(runs[1:], start=1):
        for key in scalar_keys:
            if run[key] != first[key]:
                mismatches.append(
                    f"run{index}.{key} = {run[key]!r}, run0.{key} = "
                    f"{first[key]!r}"
                )

    max_delta = 0.0
    delta_measurable = True
    base_xyz = np.asarray(first["xyz"], dtype=float)
    for index, run in enumerate(runs[1:], start=1):
        other = np.asarray(run["xyz"], dtype=float)
        if other.shape != base_xyz.shape:
            delta_measurable = False
            mismatches.append(
                f"run{index} point array shape {other.shape} != run0 "
                f"{base_xyz.shape}; max |delta p| is not defined"
            )
            continue
        if other.size:
            max_delta = max(max_delta, float(np.abs(other - base_xyz).max()))

    pose_delta = 0.0
    pose_measurable = True
    for index, run in enumerate(runs[1:], start=1):
        if len(run["poses"]) != len(first["poses"]):
            pose_measurable = False
            mismatches.append(
                f"run{index} has {len(run['poses'])} pose rows, run0 has "
                f"{len(first['poses'])}"
            )
            continue
        for (sa, ta, ra, xa), (sb, tb, rb, xb) in zip(run["poses"],
                                                      first["poses"]):
            if sa != sb or ta != tb:
                mismatches.append(
                    f"run{index} pose segment/status differ: {(sa, ta)} vs "
                    f"{(sb, tb)}"
                )
                continue
            for va, vb in ((ra, rb), (xa, xb)):
                if va is None or vb is None:
                    if (va is None) != (vb is None):
                        mismatches.append(
                            f"run{index} pose value present in one run and "
                            f"absent in the other"
                        )
                    continue
                pose_delta = max(
                    pose_delta,
                    float(np.abs(np.asarray(va) - np.asarray(vb)).max()),
                )

    points_hashes = {run["points_sha256"] for run in runs}
    support_hashes = {run["support_sha256"] for run in runs}
    byte_identical = len(points_hashes) == 1 and len(support_hashes) == 1
    return {
        "measured": True,
        "prefix": prefix,
        "repeats_requested": repeats,
        "repeats_completed": len(runs),
        "fresh_processes": True,
        "scalar_identical": not mismatches,
        "points_json_byte_identical": len(points_hashes) == 1,
        "support_json_byte_identical": len(support_hashes) == 1,
        "points_sha256": sorted(h for h in points_hashes if h),
        "support_sha256": sorted(h for h in support_hashes if h),
        "max_abs_delta_point": max_delta if delta_measurable else None,
        "max_abs_delta_pose": pose_delta if pose_measurable else None,
        "per_run": [
            {k: run[k] for k in
             ("keyframes", "segments", "poses_solved", "poses_refused",
              "points", "scale_state", "wall_seconds",
              "subprocess_wall_seconds", "peak_rss_bytes")}
            for run in runs
        ],
        "mismatches": mismatches,
        "failures": failures,
        "verdict": (
            "DETERMINISTIC"
            if not mismatches and not failures and byte_identical
            else "NOT DETERMINISTIC"
        ),
    }


# ---------------------------------------------------------------------
# Corpus-wide extended totals
# ---------------------------------------------------------------------


def configuration_block():
    """What this process actually is, beyond the code it runs.

    Two things about this pipeline are decided by the ENVIRONMENT rather than
    by the code, and both change the measurement:

      * `redaction.DEFAULT_MODEL_PATH` is `Path("models")/...` -- a RELATIVE
        path, resolved against the process cwd. Launched from `tower/` the
        face detector is found and every persisted keyframe is redacted;
        launched from the repository root it is not found and redaction is
        reported as "none". Measured on capture 22e9d428, that difference is
        112 vs 194 solved poses and 11,503 vs 19,376 points. Two runs of "the
        same benchmark" from two directories are not the same experiment, and
        nothing in the harness's output previously said which one it was.
      * `TOWER_FACE_REDACTION_MODEL` overrides that path outright.

    Recorded here so a later stage can tell instantly whether it is comparable
    with this one, instead of discovering a 70% swing and blaming its change.
    """
    from tower.world_builder import redaction

    override = os.environ.get("TOWER_FACE_REDACTION_MODEL")
    resolved = redaction.model_path()
    return {
        "cwd": os.getcwd(),
        "redaction_model_env_override": override,
        "redaction_default_path": str(redaction.DEFAULT_MODEL_PATH),
        "redaction_model_resolved": str(resolved) if resolved else None,
        "redaction_available": resolved is not None,
        "_note": (
            "redaction.DEFAULT_MODEL_PATH is relative, so face redaction is "
            "on or off depending on the cwd this process was launched from, "
            "and the two produce materially different reconstructions. A "
            "comparison between runs with different redaction_available is "
            "not a comparison."
        ),
    }


def corpus_repeat_check(repeats, scratch_root):
    """Re-run the SHIPPED harness end to end, in fresh processes, N times.

    The single-capture determinism probe answers "is one replay reproducible".
    This answers the question an A/B verdict actually rests on: does the whole
    instrument return the same corpus numbers when nothing has changed? The
    shipped comparator declares a comparison VOID if segments or keyframes
    move between two runs, so the size of the move that re-running ALONE
    produces is the noise floor every claim tonight has to clear.

    It runs `world_builder_corpus_benchmark.py` itself -- the real instrument,
    not a reimplementation -- with cwd pinned to `tower/` so redaction is in
    the same state as the run that produced this baseline.
    """
    runs = []
    failures = []
    for index in range(repeats):
        out = scratch_root / f"repeat{index}.json"
        command = [
            sys.executable,
            str(TOWER / "scripts" / "world_builder_corpus_benchmark.py"),
            "--label", f"stage0-repeat-{index}",
            "--scratch", str(scratch_root / f"run{index}"),
            "--out", str(out),
        ]
        started = time.perf_counter()
        completed = subprocess.run(
            command, capture_output=True, text=True, cwd=str(TOWER),
        )
        elapsed = round(time.perf_counter() - started, 3)
        if completed.returncode != 0 or not out.exists():
            failures.append(
                f"corpus repeat {index} exited {completed.returncode}: "
                f"{completed.stderr[-1500:]}"
            )
            continue
        report = json.loads(out.read_text(encoding="utf-8"))
        runs.append({
            "wall_seconds": elapsed,
            "totals": report["totals"],
            "by_prefix": {
                c["prefix"]: {
                    k: c[k] for k in
                    ("segments", "keyframes", "poses_solved", "poses_refused",
                     "points")
                }
                for c in report["captures"]
            },
        })

    if len(runs) < 2:
        return {
            "measured": False,
            "reason": "fewer than two corpus runs completed",
            "repeats_requested": repeats,
            "repeats_completed": len(runs),
            "failures": failures,
        }

    keys = ("segments", "keyframes", "poses_solved", "poses_refused", "points")
    first = runs[0]["by_prefix"]
    moved = {}
    for prefix in first:
        for key in keys:
            values = [run["by_prefix"][prefix][key] for run in runs]
            if len(set(values)) > 1:
                moved.setdefault(prefix, {})[key] = values
    totals_moved = {
        key: [run["totals"][key] for run in runs]
        for key in keys
        if len({run["totals"][key] for run in runs}) > 1
    }
    # The guard the shipped comparator applies. If these move on a rerun with
    # no code change, that guard can VOID a comparison for no reason.
    invariants_moved = sorted(
        prefix for prefix, fields in moved.items()
        if "segments" in fields or "keyframes" in fields
    )
    return {
        "measured": True,
        "repeats_completed": len(runs),
        "fresh_processes": True,
        "identical_across_runs": not moved,
        "captures_that_moved": moved,
        "totals_that_moved": totals_moved,
        "captures_violating_the_ab_invariant": invariants_moved,
        "per_run_totals": [
            {k: run["totals"][k] for k in keys} for run in runs
        ],
        "wall_seconds": round(sum(run["wall_seconds"] for run in runs), 3),
        "failures": failures,
    }


def extended_totals(captures):
    measured = [c["extended"] for c in captures]
    support = [e["landmark_support"] for e in measured
               if e["landmark_support"].get("measured")]
    covis = [e["covisibility"] for e in measured
             if e["covisibility"].get("measured")]
    regs = [e["registration"] for e in measured
            if e["registration"].get("measured")]
    reproj = [e["reprojection"] for e in measured
              if e["reprojection"].get("measured")]

    histogram = {}
    for entry in support:
        for key, value in entry["observations_histogram"].items():
            histogram[int(key)] = histogram.get(int(key), 0) + value
    total_landmarks = sum(e["total_landmarks"] for e in support)
    ordered = sorted(histogram)

    tiers = {}
    for tier in SUPPORT_TIERS:
        hits = sum(v for k, v in histogram.items() if k >= tier)
        tiers[f"landmarks_ge_{tier}_views"] = hits
        tiers[f"fraction_ge_{tier}_views"] = (
            hits / total_landmarks if total_landmarks else None
        )

    # A corpus-wide median taken from the pooled histogram, NOT a mean of
    # per-capture medians: the captures differ in size by more than an order
    # of magnitude and averaging their medians would weight a 530-point
    # capture like a 22,520-point one.
    cumulative = 0
    median_obs = None
    for key in ordered:
        cumulative += histogram[key]
        if cumulative >= total_landmarks / 2:
            median_obs = float(key)
            break

    rejected = {}
    for entry in measured:
        for reason, count in entry["keyframes_rejected_by_reason"].items():
            rejected[reason] = rejected.get(reason, 0) + count

    degeneracy = {}
    for entry in measured:
        for reason, count in (entry["refusal_degeneracy_counts"] or {}).items():
            degeneracy[reason] = degeneracy.get(reason, 0) + count

    scored = sum(r["observations_scored"] for r in reproj)
    reg_points_total = sum(e["points_total"] for e in regs)
    return {
        "captures_measured": len(measured),
        "keyframes_rejected_total": sum(
            e["keyframes_rejected_total"] for e in measured
        ),
        "keyframes_rejected_by_reason": dict(sorted(rejected.items())),
        "poses_refused_root": sum(
            e["poses_refused_root"] or 0 for e in measured
        ),
        "poses_refused_cascaded": sum(
            e["poses_refused_cascaded"] or 0 for e in measured
        ),
        "refusal_degeneracy_counts": dict(sorted(degeneracy.items())),
        "poses_anchor": sum(e["poses_anchor"] or 0 for e in measured),
        "poses_positioned": sum(e["poses_positioned"] or 0 for e in measured),
        "points_triangulated": sum(
            e["points_triangulated"] or 0 for e in measured
        ),
        "segments_with_only_one_keyframe": sum(
            e["segments_with_only_one_keyframe"] for e in measured
        ),
        "landmark_support": {
            "observation_unit": "distinct keyframe views per landmark",
            "captures_with_support": len(support),
            "total_landmarks": total_landmarks,
            "support_rows": sum(e["support_rows"] for e in support),
            "orphan_support_rows": sum(
                e["orphan_support_rows"] for e in support
            ),
            "duplicate_view_support_rows": sum(
                e["duplicate_view_support_rows"] for e in support
            ),
            "features_bound_to_more_than_one_landmark": sum(
                e.get("features_bound_to_more_than_one_landmark", 0)
                for e in support
            ),
            "landmarks_with_no_support_row": sum(
                e["landmarks_with_no_support_row"] for e in support
            ),
            "observations_histogram": {str(k): histogram[k] for k in ordered},
            "observations_median": median_obs,
            "observations_mean": (
                sum(k * v for k, v in histogram.items()) / total_landmarks
                if total_landmarks else None
            ),
            "observations_max": max(ordered) if ordered else None,
            "landmarks_exactly_2_views": histogram.get(2, 0),
            "fraction_exactly_2_views": (
                histogram.get(2, 0) / total_landmarks
                if total_landmarks else None
            ),
            **tiers,
        },
        "covisibility": {
            "captures_measured": len(covis),
            "keyframes_total": sum(e["keyframes_total"] for e in covis),
            "keyframes_in_support": sum(
                e["keyframes_in_support"] for e in covis
            ),
            "keyframes_with_no_observation": sum(
                e["keyframes_with_no_observation"] for e in covis
            ),
            "keyframe_pairs_sharing_any_landmark": sum(
                e["keyframe_pairs_sharing_any_landmark"] for e in covis
            ),
            COVIS_STRONG_KEY: sum(e[COVIS_STRONG_KEY] for e in covis),
            # Per capture, so the spread is visible. A single corpus-wide
            # median degree would need every degree list pooled, and the
            # per-capture histograms are already in the capture records.
            "degree_median_per_capture": [e["degree_median"] for e in covis],
            "degree_max": max(
                [e["degree_max"] for e in covis
                 if e["degree_max"] is not None],
                default=None,
            ),
            "shared_landmarks_per_pair_max": max(
                [e["shared_landmarks_per_pair_max"] for e in covis
                 if e["shared_landmarks_per_pair_max"] is not None],
                default=None,
            ),
        },
        "registration": {
            "captures_measured": len(regs),
            "segments_registered": sum(e["segments_registered"] for e in regs),
            "segments_with_geometry": sum(
                e["segments_with_geometry"] for e in regs
            ),
            "points_registered": sum(e["points_registered"] for e in regs),
            "points_total": reg_points_total,
            "fraction_points_registered": (
                sum(e["points_registered"] for e in regs) / reg_points_total
                if reg_points_total else None
            ),
            "registered_clusters": sum(e["registered_clusters"] for e in regs),
            "largest_registered_cluster_segments": max(
                [e["largest_registered_cluster_segments"] for e in regs],
                default=None,
            ),
            "candidate_pairs": sum(e["candidate_pairs"] for e in regs),
            "admitted_pairs": sum(e["admitted_pairs"] for e in regs),
            "cycles_checked": sum(e["cycles_checked"] for e in regs),
            "captures_with_cycle_refusal": sum(
                1 for e in regs if e["cycle_refusal"]
            ),
            "wall_seconds": round(
                sum(e.get("wall_seconds") or 0 for e in regs), 3
            ),
        },
        "reprojection": {
            "captures_measured": len(reproj),
            "observations_scored": scored,
            "observations_without_pose": sum(
                r["observations_without_pose"] for r in reproj
            ),
            "observations_unprojectable": sum(
                r["observations_unprojectable"] for r in reproj
            ),
            # Weighted by observation count, so a tiny capture does not get
            # the same vote as a large one.
            "mean_px_weighted": (
                sum(r["mean_px"] * r["observations_scored"]
                    for r in reproj if r["mean_px"] is not None) / scored
                if scored else None
            ),
            "median_px_per_capture": [r["median_px"] for r in reproj],
            "max_px": max(
                [r["max_px"] for r in reproj if r["max_px"] is not None],
                default=None,
            ),
        },
    }


# ---------------------------------------------------------------------


def do_measure(args):
    captures_root = args.captures.resolve()
    scratch_root = args.scratch.resolve()
    if len(str(scratch_root)) > bench.MAX_SCRATCH_ROOT_CHARS:
        raise bench.BenchmarkError(
            f"--scratch {scratch_root} is {len(str(scratch_root))} chars; "
            f"the world store needs {bench.STORE_PATH_BUDGET} more beneath "
            f"it and Windows MAX_PATH is 260."
        )
    if scratch_root == captures_root or captures_root in scratch_root.parents:
        raise bench.BenchmarkError(
            f"--scratch {scratch_root} is inside the READ-ONLY capture "
            f"corpus {captures_root}."
        )
    main_worlds = bench.MAIN_WORLD_ROOT.resolve()
    if scratch_root == main_worlds or main_worlds in scratch_root.parents:
        raise bench.BenchmarkError(
            f"--scratch {scratch_root} is inside {main_worlds}. Baseline "
            f"output never goes into the real world store."
        )
    scratch_root.mkdir(parents=True, exist_ok=True)

    prefixes = tuple(bench.PINNED_PREFIXES)
    if args.only:
        wanted = [p.strip() for p in args.only.split(",") if p.strip()]
        unknown = [p for p in wanted if p not in bench.PINNED_PREFIXES]
        if unknown:
            raise bench.BenchmarkError(
                f"--only names prefixes not in the pinned set: "
                f"{', '.join(unknown)}. The pinned set is "
                f"{', '.join(bench.PINNED_PREFIXES)}."
            )
        prefixes = tuple(p for p in bench.PINNED_PREFIXES if p in wanted)

    # A prefix matching zero or several directories aborts the whole run.
    # Inherited from the harness, not re-implemented.
    resolved = bench.resolve_pinned_captures(captures_root, prefixes)
    intrinsics_store = IntrinsicsStore(bench.MAIN_WORLD_ROOT)

    cv2.setRNGSeed(0)
    tracemalloc.start()
    run_started = time.perf_counter()

    controls = bench.run_controls(scratch_root)
    for failure in controls["failures"]:
        print(f"  !! {failure}", file=sys.stderr)

    captures = []
    failures = []
    for index, (prefix, directory) in enumerate(resolved, start=1):
        print(f"[{index}/{len(resolved)}] {prefix} ({directory.name})",
              flush=True)
        try:
            captures.append(
                measure_capture(
                    prefix, directory, scratch_root, intrinsics_store,
                    with_registration=not args.no_registration,
                    with_reprojection=not args.no_reprojection,
                )
            )
        except Exception as exc:  # noqa: BLE001
            # Recorded, never dropped. See the module docstring.
            print(f"    CAPTURE FAILED: {type(exc).__name__}: {exc}",
                  flush=True, file=sys.stderr)
            failures.append({
                "prefix": prefix,
                "capture_id": directory.name,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    measure_seconds = round(time.perf_counter() - run_started, 3)
    traced_current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    determinism = None
    if not args.no_determinism:
        det_started = time.perf_counter()
        determinism = determinism_check(
            args.determinism_prefix, args.determinism_repeats,
            scratch_root / "determinism",
        )
        determinism["wall_seconds"] = round(
            time.perf_counter() - det_started, 3
        )

    corpus_repeat = None
    if args.corpus_repeats > 1:
        corpus_repeat = corpus_repeat_check(
            args.corpus_repeats, scratch_root / "corpus-repeat"
        )

    totals = bench.totals_of(captures) if captures else None
    ext_totals = extended_totals(captures) if captures else None

    ps = _psutil()
    report = {
        "schema": "stage0-baseline/1",
        "label": args.label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": args.commit or _git(["rev-parse", "HEAD"]),
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version,
            "executable": sys.executable,
            "opencv": cv2.__version__,
            "numpy": np.__version__,
            "cpu_count": os.cpu_count(),
            "total_ram_bytes": ps.virtual_memory().total if ps else None,
        },
        "commands": {
            "shipped_harness": (
                "<python> scripts/world_builder_corpus_benchmark.py "
                "--label <label> --scratch <dir> --out <file>"
            ),
            "this_run": " ".join([sys.executable, str(HERE)] +
                                 list(args.argv)),
        },
        "configuration": configuration_block(),
        "captures_root": str(captures_root),
        "scratch_root": str(scratch_root),
        "intrinsics": str(
            intrinsics_store.path_for(*bench.EXPECTED_RESOLUTION)
        ),
        "pinned_prefixes": list(bench.PINNED_PREFIXES),
        "prefixes_run": list(prefixes),
        "complete_corpus": (
            len(captures) == len(bench.PINNED_PREFIXES) and not failures
        ),
        "controls": controls,
        "captures": captures,
        "capture_failures": failures,
        "totals": totals,
        "extended_totals": ext_totals,
        "determinism": determinism,
        "corpus_rerun_stability": corpus_repeat,
        "runtime": {
            "measure_wall_seconds": measure_seconds,
            "determinism_wall_seconds": (
                determinism.get("wall_seconds") if determinism else None
            ),
            "corpus_rerun_wall_seconds": (
                corpus_repeat.get("wall_seconds") if corpus_repeat else None
            ),
            "replay_and_build_wall_seconds": round(sum(
                c["extended"]["phase_seconds"]["replay_and_build_seconds"]
                for c in captures
            ), 3) if captures else None,
            "registration_wall_seconds": (
                ext_totals["registration"]["wall_seconds"]
                if ext_totals else None
            ),
        },
        "memory": {
            "peak_rss_bytes": peak_rss_bytes(),
            "peak_rss_note": (
                None if _psutil() else
                "psutil is not installed in this interpreter, so the OS "
                "high-water mark is unavailable and is reported as null "
                "rather than substituted with current RSS."
            ),
            "tracemalloc_peak_bytes": traced_peak,
            "tracemalloc_current_bytes": traced_current,
            "tracemalloc_note": (
                "tracemalloc sees Python allocations only. OpenCV's native "
                "buffers -- the bulk of this pipeline -- are invisible to "
                "it, so peak_rss_bytes is the number to read."
            ),
        },
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out.resolve()}")

    _print_summary(report)

    bad = bool(failures) or bool(controls["failures"])
    if determinism and determinism.get("verdict") == "NOT DETERMINISTIC":
        bad = True
    return 1 if bad else 0


def _git(argv):
    try:
        result = subprocess.run(
            ["git"] + argv, capture_output=True, text=True, cwd=str(TOWER),
        )
    except OSError:
        return None
    return result.stdout.strip() or None


def _pct(value):
    return "n/a" if value is None else f"{value:.1%}"


def _print_summary(report):
    if report["totals"]:
        bench.print_run_table(report["captures"], report["totals"])
    print()
    ext = report["extended_totals"]
    if ext:
        support = ext["landmark_support"]
        print(
            f"landmarks {support['total_landmarks']}  "
            f"exactly-2-view {_pct(support['fraction_exactly_2_views'])}  "
            f">=2 {_pct(support['fraction_ge_2_views'])}  "
            f">=3 {_pct(support['fraction_ge_3_views'])}  "
            f">=5 {_pct(support['fraction_ge_5_views'])}  "
            f"median obs {support['observations_median']}"
        )
        covis = ext["covisibility"]
        print(
            f"covisibility pairs any="
            f"{covis['keyframe_pairs_sharing_any_landmark']}  "
            f">={COVIS_STRONG_MIN_SHARED}shared={covis[COVIS_STRONG_KEY]}  "
            f"keyframes with no observation "
            f"{covis['keyframes_with_no_observation']} of "
            f"{covis['keyframes_total']}"
        )
        regs = ext["registration"]
        print(
            f"registration segments {regs['segments_registered']} of "
            f"{regs['segments_with_geometry']} with geometry; points "
            f"{regs['points_registered']} of {regs['points_total']} "
            f"({_pct(regs['fraction_points_registered'])}); clusters "
            f"{regs['registered_clusters']}"
        )
        rep = ext["reprojection"]
        print(
            f"reprojection scored {rep['observations_scored']}  "
            f"mean {rep['mean_px_weighted']}  max {rep['max_px']}"
        )
    if report["capture_failures"]:
        print("\nCAPTURES THAT FAILED:")
        for failure in report["capture_failures"]:
            print(f"  {failure['prefix']}: {failure['error_type']}: "
                  f"{failure['error']}")
    det = report["determinism"]
    if det:
        print(f"\ndeterminism (single capture, fresh processes): "
              f"{det.get('verdict', 'NOT MEASURED')}")
        for line in det.get("mismatches", [])[:6]:
            print(f"  {line}")
    rep = report.get("corpus_rerun_stability")
    if rep and rep.get("measured"):
        print(
            f"corpus rerun stability over {rep['repeats_completed']} fresh "
            f"full-corpus runs: "
            f"{'IDENTICAL' if rep['identical_across_runs'] else 'MOVED'}"
        )
        if rep["totals_that_moved"]:
            print(f"  totals that moved: {rep['totals_that_moved']}")
        if rep["captures_violating_the_ab_invariant"]:
            print(
                "  captures whose segments/keyframes moved (the shipped "
                "comparator VOIDs on this): "
                + ", ".join(rep["captures_violating_the_ab_invariant"])
            )


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description=(
            "Stage 0 baseline over the pinned corpus: the shipped harness's "
            "numbers plus landmark support, covisibility, registration, "
            "reprojection, runtime and peak memory."
        )
    )
    parser.add_argument("--label", default=None,
                        help="Recorded in the output. Required for a run.")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--only", default=None,
                        help="Comma-separated subset of the PINNED prefixes.")
    parser.add_argument("--captures", type=Path,
                        default=bench.DEFAULT_CAPTURES_ROOT)
    parser.add_argument("--scratch", type=Path, default=None)
    parser.add_argument("--commit", default=None,
                        help="Override the recorded commit SHA.")
    parser.add_argument("--determinism-repeats", type=int, default=3)
    parser.add_argument(
        "--corpus-repeats", type=int, default=2,
        help=(
            "Re-run the SHIPPED harness end to end this many times in fresh "
            "processes and report whether the corpus numbers move. This is "
            "the noise floor an A/B claim has to clear. 1 or less skips it."
        ),
    )
    parser.add_argument("--determinism-prefix", default=CANONICAL_PREFIX)
    parser.add_argument("--determinism-only", action="store_true")
    parser.add_argument("--no-determinism", action="store_true")
    parser.add_argument("--no-registration", action="store_true")
    parser.add_argument("--no-reprojection", action="store_true")
    parser.add_argument("--probe", default=None,
                        help="Internal: run one capture, print a fingerprint.")
    args = parser.parse_args(argv)
    args.argv = argv

    try:
        if args.probe:
            if args.scratch is None:
                parser.error("--probe requires --scratch")
            return probe(args.probe, args.scratch.resolve())
        if not args.label:
            parser.error("--label is required")
        if args.scratch is None:
            args.scratch = Path(tempfile.mkdtemp(prefix="wb-stage0-"))
        if args.determinism_only:
            result = determinism_check(
                args.determinism_prefix, args.determinism_repeats,
                args.scratch.resolve() / "determinism",
            )
            print(json.dumps(result, indent=2))
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(result, indent=2),
                                    encoding="utf-8")
            return 0 if result.get("verdict") == "DETERMINISTIC" else 1
        return do_measure(args)
    except bench.BenchmarkError as exc:
        print(f"\nBASELINE ABORTED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
