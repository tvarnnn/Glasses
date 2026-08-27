#!/usr/bin/env python
"""GIL contention, measured so ambient machine load cannot fake the answer.

The original probe (scripts/research/native_eval/gil_contention.py) compares
a spinner's throughput ALONE against its throughput DURING a replay. That
ratio is only meaningful on a quiet machine: if other processes take cores
away during one phase and not the other, the ratio moves for reasons that
have nothing to do with the GIL.

This host is NOT quiet (other agents are running), so this version adds the
thing that makes the measurement self-calibrating:

  * NEGATIVE CONTROL -- spinner alone.
  * SUBJECT         -- spinner during a World Builder replay.
  * POSITIVE CONTROL -- spinner during a second pure-Python CPU hog in the
    SAME process. This one provably holds the GIL, so it establishes what
    "collapsed" actually looks like on this machine right now.

If the subject sits near the negative control and far from the positive
control, the GIL conclusion survives regardless of ambient load, because
all three numbers are taken under the same ambient load and the comparison
is internal to the run.

Phases are also INTERLEAVED and repeated, so slow drift in background load
hits every phase roughly equally instead of biasing one.
"""

from __future__ import annotations

import argparse
import statistics
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
        self._halt = threading.Event()

    def run(self):
        n = 0
        while not self._halt.is_set():
            for _ in range(10_000):
                n += 1
            self.count = n

    def stop(self):
        self._halt.set()


def _spin_alone(seconds: float) -> float:
    s = Spinner()
    started = time.perf_counter()
    s.start()
    time.sleep(seconds)
    s.stop()
    elapsed = time.perf_counter() - started
    rate = s.count / elapsed
    s.join(timeout=2)
    return rate


def _spin_during_gil_holder(seconds: float) -> float:
    """POSITIVE CONTROL: a second pure-Python hog, which holds the GIL."""
    s = Spinner()
    hog = Spinner()
    started = time.perf_counter()
    s.start()
    hog.start()
    time.sleep(seconds)
    s.stop()
    hog.stop()
    elapsed = time.perf_counter() - started
    rate = s.count / elapsed
    s.join(timeout=2)
    hog.join(timeout=2)
    return rate


def _spin_during_replay(prefix, capture, scratch, istore) -> tuple[float, float]:
    import world_builder_corpus_benchmark as bench

    s = Spinner()
    started = time.perf_counter()
    s.start()
    bench.run_capture(prefix, capture, scratch, istore)
    elapsed = time.perf_counter() - started
    s.stop()
    rate = s.count / elapsed
    s.join(timeout=2)
    return rate, elapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    print(f"production code: {_resolve()}")

    from tower.world_builder.intrinsics_store import IntrinsicsStore

    istore = IntrinsicsStore(Path(args.data_root))

    alone, during, holder, elapsed_all = [], [], [], []
    for r in range(args.rounds):
        a = _spin_alone(4.0)
        d, el = _spin_during_replay(
            args.prefix, Path(args.capture), Path(args.scratch) / f"r{r}", istore
        )
        h = _spin_during_gil_holder(4.0)
        alone.append(a)
        during.append(d)
        holder.append(h)
        elapsed_all.append(el)
        print(
            f"round {r}: alone={a:>12,.0f}  during_replay={d:>12,.0f} "
            f"({el:.1f}s)  during_gil_holder={h:>12,.0f}"
        )

    ma, md, mh = (statistics.median(x) for x in (alone, during, holder))
    print("\n" + "=" * 66)
    print(f"NEGATIVE CONTROL  spinner alone           {ma:>12,.0f} /s   100.0%")
    print(f"SUBJECT           spinner during replay   {md:>12,.0f} /s   "
          f"{100.0 * md / ma:>5.1f}%")
    print(f"POSITIVE CONTROL  spinner + GIL holder    {mh:>12,.0f} /s   "
          f"{100.0 * mh / ma:>5.1f}%")
    print("=" * 66)
    print(f"replay wall time: median {statistics.median(elapsed_all):.1f}s "
          f"over {args.rounds} rounds {[round(e,1) for e in elapsed_all]}")
    print(
        "\nRead: the positive control is what a REAL GIL bottleneck measures\n"
        "on this machine under this load. If the subject is far above it and\n"
        "near the negative control, the replay is releasing the GIL."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
