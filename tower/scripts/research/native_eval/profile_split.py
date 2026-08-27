#!/usr/bin/env python
"""cProfile a stage and split tottime into NATIVE and PYTHON.

The whole native-migration decision turns on this ratio, so it is
computed mechanically rather than eyeballed off a top-30 listing.

Classification, from `pstats`' (filename, lineno, funcname) key:

  NATIVE  filename is "~" -- CPython's marker for a C function with no
          Python source. That is every `cv2.*`, every numpy ufunc and
          linalg entry point, every builtin. Their tottime is time spent
          inside compiled code with the GIL usually released.
  PYTHON  anything with a real .py path. Their tottime is interpreter
          time, and it is the ONLY part a rewrite in a compiled language
          could remove.

The caveat that matters: cProfile charges per-call bookkeeping to the
PYTHON side, so this split OVERSTATES Python. It is therefore reported
next to an unprofiled `time.perf_counter` wall time for the same stage,
and the unprofiled number is the one to trust for totals. The split is
for attribution only.
"""

import argparse
import cProfile
import json
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import cv2  # noqa: E402

from scripts.world_builder_corpus_benchmark import MAIN_WORLD_ROOT  # noqa: E402
from tower.world_builder.engine import WorldBuilderEngine  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402


def split(stats: pstats.Stats):
    native = python = 0.0
    rows = []
    for (filename, lineno, funcname), entry in stats.stats.items():
        tottime = entry[2]
        is_native = filename == "~"
        if is_native:
            native += tottime
        else:
            python += tottime
        rows.append(
            {
                "where": f"{Path(filename).name}:{lineno}"
                if filename != "~"
                else "~",
                "func": funcname,
                "tottime": tottime,
                "calls": entry[0],
                "native": is_native,
            }
        )
    rows.sort(key=lambda r: -r["tottime"])
    return native, python, rows


def profile(label: str, fn, out: Path | None):
    # Unprofiled first. This is the trustworthy total.
    t0 = time.perf_counter()
    fn()
    clean = time.perf_counter() - t0

    pr = cProfile.Profile()
    pr.enable()
    fn()
    pr.disable()
    stats = pstats.Stats(pr)
    native, python, rows = split(stats)
    total = native + python

    print(f"\n=== {label} ===")
    print(f"  unprofiled wall (perf_counter): {clean:.3f} s   <- trust this")
    print(f"  profiled   wall (cProfile sum): {total:.3f} s   (inflated)")
    print(
        f"  NATIVE tottime {native:7.3f} s  {native/total*100:5.1f}%   "
        f"(cv2 / numpy C / builtins)"
    )
    print(
        f"  PYTHON tottime {python:7.3f} s  {python/total*100:5.1f}%   "
        f"(interpreter frames; OVERSTATED by cProfile)"
    )
    print("  top 25 by tottime:")
    print(f"    {'tot s':>8} {'calls':>9}  {'kind':<6} where / func")
    for row in rows[:25]:
        print(
            f"    {row['tottime']:>8.3f} {row['calls']:>9}  "
            f"{'NATIVE' if row['native'] else 'python':<6} "
            f"{row['where']} {row['func']}"
        )
    print("  top 12 PYTHON-only by tottime:")
    for row in [r for r in rows if not r["native"]][:12]:
        print(
            f"    {row['tottime']:>8.3f} {row['calls']:>9}  "
            f"{row['where']} {row['func']}"
        )

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "label": label,
                    "unprofiled_wall_s": round(clean, 4),
                    "profiled_total_s": round(total, 4),
                    "native_s": round(native, 4),
                    "python_s": round(python, 4),
                    "native_pct": round(native / total * 100, 2),
                    "python_pct": round(python / total * 100, 2),
                    "rows": [
                        {**r, "tottime": round(r["tottime"], 5)} for r in rows[:60]
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    cold = sub.add_parser("cold-build", help="profile a from-scratch build()")
    cold.add_argument("--root", required=True, type=Path)
    cold.add_argument("--world", required=True)
    cold.add_argument("--session", required=True)
    cold.add_argument("--out", type=Path)

    reg = sub.add_parser("registration", help="profile world_registration.register")
    reg.add_argument("--root", required=True, type=Path)
    reg.add_argument("--world", required=True)
    reg.add_argument("--session", required=True)
    reg.add_argument("--out", type=Path)

    args = ap.parse_args(argv)

    import tower.world_builder.backends.classical as classical

    assert "Glasses-world-builder" in str(classical.__file__), classical.__file__
    assert hasattr(classical, "EXTEND_REFERENCE_DEPTH")
    print(f"module {classical.__file__}")
    assert MAIN_WORLD_ROOT.exists()

    if args.mode == "cold-build":

        def fn():
            cv2.setRNGSeed(0)
            WorldBuilderEngine(WorldStore(args.root)).build(args.world, args.session)

        profile(f"cold build {args.world[:8]}", fn, args.out)
    else:
        from scripts import world_registration as wr

        def fn():
            wr.register(WorldStore(args.root), args.world, args.session)

        profile(f"registration {args.world[:8]}", fn, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
