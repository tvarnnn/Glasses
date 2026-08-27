#!/usr/bin/env python
"""Adversarial corpus A/B for EXTEND_REFERENCE_DEPTH.

WHY THIS EXISTS RATHER THAN EDITING THE CONSTANT ON DISK

Another agent is toggling `EXTEND_REFERENCE_DEPTH` in classical.py
concurrently. A measurement that depends on the file's contents at an
unknown instant is not a measurement. All three read sites reference the
module global at CALL time (classical.py:313, :517, :1303), so binding
the value in-process after import is exactly equivalent to editing the
file, and is immune to the race.

The effective value is re-read FROM THE MODULE after the patch and
recorded in the output, so the artifact names what actually ran.

No subprocesses are spawned: --no-determinism and --corpus-repeats 1
keep every capture in this interpreter, which is what makes the
in-process binding authoritative.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
TOWER = HERE.parents[3]
sys.path.insert(0, str(TOWER))
sys.path.insert(0, str(TOWER / "scripts" / "research" / "stage0_baseline"))

import tower.world_builder.backends.classical as classical  # noqa: E402
import measure_baseline  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    assert "Glasses-world-builder" in classical.__file__.replace("\\", "/"), (
        f"WRONG MODULE: {classical.__file__}"
    )

    on_disk = classical.EXTEND_REFERENCE_DEPTH
    classical.EXTEND_REFERENCE_DEPTH = args.depth
    effective = classical.EXTEND_REFERENCE_DEPTH
    assert effective == args.depth

    print(f"module           {classical.__file__}", flush=True)
    print(f"depth on import  {on_disk}", flush=True)
    print(f"depth EFFECTIVE  {effective}", flush=True)

    argv = [
        "--label", f"adversarial_depth{args.depth}",
        "--out", args.out,
        "--scratch", args.scratch,
        "--no-registration",
        "--no-reprojection",
        "--no-determinism",
        "--corpus-repeats", "1",
    ]
    if args.only:
        argv += ["--only", args.only]
    rc = measure_baseline.main(argv)

    # Stamp the effective depth into the report so it cannot be mistaken.
    out = Path(args.out)
    if out.exists():
        report = json.loads(out.read_text(encoding="utf-8"))
        report["_adversarial"] = {
            "effective_extend_reference_depth": effective,
            "depth_as_imported_from_disk": on_disk,
            "classical_module_file": classical.__file__,
            "patched_in_process": True,
        }
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
