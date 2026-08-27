#!/usr/bin/env python
"""How does world_registration.register() scale, and in what?

Candidate generation is O(pairs) = O(S^2) in the number of
geometry-bearing segments, so the interesting question is not whether
the pair count grows quadratically -- it must -- but whether the
per-pair cost is dominated by the cheap pruning (`pair_is_hopeless`,
which refuses on evidence already in hand) or by the expensive work
behind it (ORB `cross_matches`, then `fit_direction` -> PnP RANSAC ->
`_refine`, whose `_residuals` is a PYTHON loop).

The split is measured by wrapping the module's own globals from OUTSIDE
-- `scripts/world_registration.py` is not modified, and neither is
anything under `tower/`. `register()` resolves these names as module
globals at call time, so rebinding them here times the real calls.

Phases timed, inclusive of each other where nested:

  hopeless   `pair_is_hopeless`     -- the cheap prune
  matching   `cross_matches`        -- ORB detect + knnMatch (native)
  fit        `fit_direction`        -- PnP RANSAC + refine, both directions
  refine     `_refine`              -- the Levenberg-ish loop inside fit
  residuals  `_residuals`           -- the Python loop inside refine

`register()` writes nothing, so main-checkout worlds are safe to read.
"""

import argparse
import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import psutil  # noqa: E402

from scripts import world_registration as wr  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402


def load_pinned(path: Path):
    """Load a PINNED copy of world_registration.py as its own module.

    Needed because this worktree is shared: another lane edits
    `scripts/world_registration.py` while a sweep is running, and a
    measurement that straddles that edit describes neither version. This
    loads a file the caller has pinned (e.g. `git show HEAD:...`) without
    touching the working tree, so the shipped baseline stays measurable
    no matter what is in flight beside it.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("world_registration_pinned", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["world_registration_pinned"] = module
    spec.loader.exec_module(module)
    return module


class PhaseTimer:
    """Rebind module globals with timing wrappers. Restores on exit."""

    NAMES = (
        "pair_is_hopeless",
        "cross_matches",
        "fit_direction",
        "_refine",
        "_residuals",
        # Present only on the in-flight vectorised variant. Timed when
        # present so the two versions are comparable in the same table,
        # skipped silently when absent rather than erroring.
        "_residuals_packed",
        "_pack",
    )

    def __init__(self, module):
        self.module = module
        self.totals = {name: 0.0 for name in self.NAMES}
        self.calls = {name: 0 for name in self.NAMES}
        self._originals = {}

    def __enter__(self):
        for name in self.NAMES:
            if not hasattr(self.module, name):
                continue
            original = getattr(self.module, name)
            self._originals[name] = original
            setattr(self.module, name, self._wrap(name, original))
        return self

    def _wrap(self, name, original):
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.totals[name] += time.perf_counter() - t0
                self.calls[name] += 1

        return wrapper

    def __exit__(self, *exc):
        for name, original in self._originals.items():
            setattr(self.module, name, original)
        return False


def sessions_of(root: Path, world_id: str):
    sessions_dir = root / "worlds" / world_id / "sessions"
    if not sessions_dir.is_dir():
        return []
    return sorted(p.name for p in sessions_dir.iterdir() if p.is_dir())


def measure(root: Path, world_id: str, session_id: str, profile: bool,
            module=None) -> dict:
    module = module or wr
    store = WorldStore(root)
    proc = psutil.Process()

    # Unprofiled, untimed-internally wall clock FIRST. This is the number
    # to trust; the phase wrappers below add a Python call per pair and
    # per residual evaluation, which biases toward Python.
    rss_before = proc.memory_info().rss
    t0 = time.perf_counter()
    report = module.register(store, world_id, session_id)
    clean_wall = time.perf_counter() - t0
    rss_after = proc.memory_info().rss

    with PhaseTimer(module) as timer:
        t0 = time.perf_counter()
        module.register(store, world_id, session_id)
        wrapped_wall = time.perf_counter() - t0

    row = {
        "world_id": world_id,
        "session_id": session_id,
        "segment_count": report["segment_count"],
        "segments_with_geometry": report["segments_with_geometry"],
        "segments_registered": report["segments_registered"],
        "candidate_pairs": report["candidate_pairs"],
        "admitted_pairs": len(report["admitted_pairs"]),
        "points_total": report["points_total"],
        "wall_s": round(clean_wall, 4),
        "wall_wrapped_s": round(wrapped_wall, 4),
        "rss_delta_mb": round((rss_after - rss_before) / 1e6, 2),
        "rss_peak_mb": round(max(rss_before, rss_after) / 1e6, 2),
        "phase_s": {k: round(v, 4) for k, v in timer.totals.items()},
        "phase_calls": dict(timer.calls),
    }
    # The pairs that got past the cheap prune -- the ones that actually
    # cost anything. This is the real driver, not candidate_pairs.
    row["pairs_matched"] = timer.calls["cross_matches"]
    # `candidate_pairs` in the report is len(verdicts), which UNDERCOUNTS:
    # a pair whose cross_matches came back empty `continue`s without
    # recording a verdict. The real size of the double loop is C(G, 2)
    # over geometry-bearing segments, so that is the x-axis for any
    # O(S^2) claim.
    geo = report["segments_with_geometry"]
    row["pairs_all"] = geo * (geo - 1) // 2
    row["pairs_hopeless"] = timer.calls["pair_is_hopeless"] - timer.calls[
        "cross_matches"
    ]
    row["fit_calls"] = timer.calls["fit_direction"]
    row["refine_calls"] = timer.calls["_refine"]
    row["residual_calls"] = timer.calls["_residuals"]
    row["residual_packed_calls"] = timer.calls["_residuals_packed"]
    row["residual_any_s"] = round(
        timer.totals["_residuals"] + timer.totals["_residuals_packed"], 4
    )

    if profile:
        pr = cProfile.Profile()
        pr.enable()
        module.register(store, world_id, session_id)
        pr.disable()
        stream = io.StringIO()
        pstats.Stats(pr, stream=stream).sort_stats("tottime").print_stats(25)
        row["profile"] = stream.getvalue()
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path)
    ap.add_argument(
        "--roots",
        nargs="+",
        type=Path,
        help="several world roots (e.g. one scratch root per replayed capture)",
    )
    ap.add_argument("--worlds", nargs="*", help="world ids; default = all")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--profile-largest", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--registration-source",
        type=Path,
        help="pinned copy of world_registration.py to measure instead of the "
             "working-tree one (this worktree is shared and it moves)",
    )
    args = ap.parse_args(argv)

    import tower.world_builder.backends.classical as classical

    assert "Glasses-world-builder" in str(classical.__file__), classical.__file__
    module = (
        load_pinned(args.registration_source) if args.registration_source else wr
    )
    print(f"module  {classical.__file__}")
    print(f"registration source  {module.__file__}")
    print(f"  has _residuals_packed: {hasattr(module, '_residuals_packed')}")

    roots = list(args.roots or [])
    if args.root:
        roots.insert(0, args.root)
    if not roots:
        raise SystemExit("give --root and/or --roots")

    rows = []
    for root in roots:
        if not (root / "worlds").is_dir():
            print(f"skip {root}: no worlds/")
            continue
        print(f"root    {root}")
        world_ids = args.worlds or sorted(
            p.name for p in (root / "worlds").iterdir() if p.is_dir()
        )
        for world_id in world_ids:
            for session_id in sessions_of(root, world_id):
                try:
                    row = measure(root, world_id, session_id, False, module)
                except Exception as exc:  # noqa: BLE001 - a world that cannot
                    # be registered is a datapoint, not a reason to abort
                    rows.append(
                        {
                            "root": str(root),
                            "world_id": world_id,
                            "session_id": session_id,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                row["root"] = str(root)
                rows.append(row)
                print(
                    f"{world_id[:8]}/{session_id[:8]}  "
                    f"seg={row['segment_count']:>3} "
                    f"geo={row['segments_with_geometry']:>3} "
                    f"pairs={row['pairs_all']:>5} "
                    f"matched={row['pairs_matched']:>4}  "
                    f"wall={row['wall_s']:>8.3f}s  "
                    f"hopeless={row['phase_s']['pair_is_hopeless']:>7.3f} "
                    f"match={row['phase_s']['cross_matches']:>7.3f} "
                    f"fit={row['phase_s']['fit_direction']:>7.3f} "
                    f"refine={row['phase_s']['_refine']:>7.3f} "
                    f"resid={row['phase_s']['_residuals']:>7.3f}"
                )
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    good = [r for r in rows if "error" not in r]
    if args.profile_largest and good:
        largest = max(good, key=lambda r: r["wall_s"])
        print(f"\nprofiling largest by wall time: {largest['world_id'][:8]}")
        detail = measure(
            Path(largest["root"]), largest["world_id"], largest["session_id"],
            True, module,
        )
        print(detail["profile"])
        rows.append({"profiled": detail})
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
