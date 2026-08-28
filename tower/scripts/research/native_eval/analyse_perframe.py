#!/usr/bin/env python
"""Trend analysis over the per-frame table replay_scale.py records.

Two questions, kept separate because they have different answers:

  * Do REJECTED frames (the common case: gate says no, no geometry runs)
    get slower as the session grows?
  * Do ACCEPTED frames (the expensive case: redaction + persist +
    _LiveSolve.extend) get slower as the accumulated keyframe count
    grows? This is the one that would indicate an O(N) term inside the
    forward-only solve.

Reports deciles rather than a single slope, because a slope fitted
across a mixture of accepted and rejected frames measures the acceptance
RATE changing, not the per-frame cost changing.
"""

import json
import statistics
import sys
from pathlib import Path


def quantile(values, q):
    """Linear-interpolated quantile. numpy is available but this keeps
    the analysis readable and dependency-free."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def linfit(xs, ys):
    """Least-squares slope/intercept, plus Pearson r."""
    n = len(xs)
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return float("nan"), float("nan"), float("nan")
    slope = sxy / sxx
    return slope, my - slope * mx, sxy / (sxx**0.5 * syy**0.5)


def describe(name, rows):
    if not rows:
        print(f"  {name}: none")
        return
    ms = [r["ms"] for r in rows]
    print(
        f"  {name}: n={len(rows)} mean={statistics.mean(ms):.2f}ms "
        f"median={statistics.median(ms):.2f}ms "
        f"p95={quantile(ms, 0.95):.2f}ms max={max(ms):.2f}ms"
    )


def deciles(name, rows, key):
    if len(rows) < 10:
        return
    print(f"  {name} by {key}, decile means (ms):")
    chunk = len(rows) // 10
    line = []
    for d in range(10):
        part = rows[d * chunk : (d + 1) * chunk] if d < 9 else rows[9 * chunk :]
        ms = [r["ms"] for r in part]
        line.append(
            f"    d{d+1} {key}~{part[len(part)//2][key]:>4} "
            f"mean={statistics.mean(ms):7.2f} med={statistics.median(ms):7.2f} "
            f"p95={quantile(ms,0.95):7.2f}"
        )
    print("\n".join(line))


def main(paths):
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        samples = report["samples"]
        accepted = [r for r in samples if r["accepted"]]
        rejected = [r for r in samples if not r["accepted"]]
        print(f"\n=== {report['prefix']} ({report['capture_id']}) ===")
        print(
            f"  frames={report['frames_observed']} keyframes={report['keyframes']} "
            f"segments={report['segments']} points={report['points']} "
            f"redaction={'ON' if report['redaction_on'] else 'OFF'}"
        )
        print(
            f"  replay_wall={report['replay_wall_s']}s "
            f"observe_total={report['observe_total_s']}s "
            f"build={report['build_s']}s"
        )
        describe("ALL", samples)
        describe("ACCEPTED", accepted)
        describe("REJECTED", rejected)

        deciles("ACCEPTED", accepted, "kf")
        deciles("REJECTED", rejected, "i")

        for label, rows, key in (
            ("accepted ms ~ keyframe count", accepted, "kf"),
            ("rejected ms ~ frame index", rejected, "i"),
            ("rss_mb ~ keyframe count", accepted, "kf"),
        ):
            ys = [r["rss_mb"] if label.startswith("rss") else r["ms"] for r in rows]
            xs = [r[key] for r in rows]
            slope, _, r = linfit(xs, ys)
            unit = "MB" if label.startswith("rss") else "ms"
            print(f"  fit {label}: slope={slope:+.5f} {unit}/{key}  r={r:+.3f}")

        # First vs last quarter of ACCEPTED frames: the blunt version of
        # the same question, immune to a fit being dragged by outliers.
        if len(accepted) >= 8:
            q = len(accepted) // 4
            a = [r["ms"] for r in accepted[:q]]
            b = [r["ms"] for r in accepted[-q:]]
            print(
                f"  ACCEPTED first-quarter median={statistics.median(a):.2f}ms "
                f"last-quarter median={statistics.median(b):.2f}ms "
                f"ratio={statistics.median(b)/statistics.median(a):.3f}x"
            )
        print(
            f"  RSS start={report['rss_start_mb']}MB "
            f"before_build={report['rss_before_build_mb']}MB "
            f"after_build={report['rss_after_build_mb']}MB "
            f"peak={report['rss_peak_mb']}MB"
        )


if __name__ == "__main__":
    main(sys.argv[1:])
