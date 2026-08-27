#!/usr/bin/env python
"""Does World Builder hold the GIL, and would native code free it?

"Remove a GIL bottleneck" is one of the standard justifications for moving
Python to C++, and on this project it has a specific meaning: the Tower
runs World Builder alongside Object Memory, Scene Understanding and other
cartridges, so what matters is whether a World Builder replay starves
another Python workload sharing the process.

That is measurable rather than arguable. Run a CPU-bound pure-Python
counter thread, measure its throughput alone, then measure it again while
a World Builder replay runs in another thread of the SAME process.

  * If the counter keeps most of its throughput, World Builder is
    releasing the GIL for most of its work -- which is what OpenCV does
    around native calls -- and there is no GIL bottleneck for C++ to fix.
  * If the counter collapses, World Builder is holding the GIL and native
    extraction would buy real concurrency.

The counter is deliberately pure Python (integer increment) because that
is the thing a GIL holder starves. A numpy or OpenCV workload would
release the GIL itself and measure nothing.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

TOWER = Path(__file__).resolve().parents[3]
if str(TOWER) not in sys.path:
    sys.path.insert(0, str(TOWER))
if str(TOWER / "scripts") not in sys.path:
    sys.path.insert(0, str(TOWER / "scripts"))


def _resolve():
    import tower.world_builder.backends.classical as classical

    where = Path(classical.__file__).resolve()
    if "Glasses-world-builder" not in str(where):
        raise SystemExit(f"REFUSING: production code resolved to {where}")
    if not hasattr(classical, "EXTEND_REFERENCE_DEPTH"):
        raise SystemExit("REFUSING: resolved a build without EXTEND_REFERENCE_DEPTH")
    return where


class Spinner(threading.Thread):
    """A pure-Python CPU hog. Its throughput is the GIL probe."""

    def __init__(self):
        super().__init__(daemon=True)
        self.count = 0
        # NOT `_stop`: threading.Thread has an internal _stop() method
        # and shadowing it breaks join().
        self._halt = threading.Event()

    def run(self):
        n = 0
        while not self._halt.is_set():
            for _ in range(10_000):
                n += 1
            self.count = n

    def stop(self):
        self._halt.set()


def _measure_alone(seconds: float) -> float:
    spinner = Spinner()
    spinner.start()
    time.sleep(seconds)
    spinner.stop()
    rate = spinner.count / seconds
    spinner.join(timeout=2)
    return rate


def _measure_during_replay(prefix, capture, scratch, istore) -> tuple[float, float]:
    import world_builder_corpus_benchmark as bench

    spinner = Spinner()
    spinner.start()
    started = time.perf_counter()
    bench.run_capture(prefix, capture, scratch, istore)
    elapsed = time.perf_counter() - started
    spinner.stop()
    rate = spinner.count / elapsed
    spinner.join(timeout=2)
    return rate, elapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--data-root", required=True)
    args = ap.parse_args()

    where = _resolve()
    print(f"production code: {where}")

    from tower.world_builder.intrinsics_store import IntrinsicsStore

    istore = IntrinsicsStore(Path(args.data_root))

    baseline = _measure_alone(4.0)
    print(f"spinner ALONE:          {baseline:>12,.0f} increments/s")

    during, elapsed = _measure_during_replay(
        args.prefix, Path(args.capture), Path(args.scratch), istore
    )
    print(f"spinner DURING replay:  {during:>12,.0f} increments/s "
          f"(replay took {elapsed:.1f}s)")

    retained = 100.0 * during / baseline if baseline else 0.0
    print(f"\nthroughput retained by the other Python thread: {retained:.1f}%")
    print(
        "  A pure-Python thread that keeps most of its throughput means the\n"
        "  GIL was released for most of the replay -- i.e. the work is\n"
        "  already in native code and there is no GIL bottleneck to fix.\n"
        "  Two threads on a multicore host cannot exceed ~100% each, so\n"
        "  anything near 100% means near-total GIL release."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
