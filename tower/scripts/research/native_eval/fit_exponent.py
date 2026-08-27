#!/usr/bin/env python
"""Log-log power-law fit: y = a * x^b. Reports b with its R^2.

Used for both build-vs-keyframes and registration-vs-segments. b~1 is
linear, b~2 is quadratic. Rows with x<=0 or y<=0 are dropped and SAID
so, because silently dropping them is how a fit ends up describing a
different dataset than the one named above it.
"""

import json
import math
import sys
from pathlib import Path


def powerfit(xs, ys):
    lx = [math.log(x) for x in xs]
    ly = [math.log(y) for y in ys]
    n = len(lx)
    mx, my = sum(lx) / n, sum(ly) / n
    sxx = sum((v - mx) ** 2 for v in lx)
    sxy = sum((a - mx) * (b - my) for a, b in zip(lx, ly))
    if sxx == 0:
        return float("nan"), float("nan"), float("nan")
    b = sxy / sxx
    a = math.exp(my - b * mx)
    ss_res = sum((ly[i] - (math.log(a) + b * lx[i])) ** 2 for i in range(n))
    ss_tot = sum((v - my) ** 2 for v in ly)
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    return b, a, r2


def report(label, rows, xkey, ykey, unit="s"):
    usable = [
        r
        for r in rows
        if isinstance(r.get(xkey), (int, float))
        and isinstance(r.get(ykey), (int, float))
        and r[xkey] > 0
        and r[ykey] > 0
    ]
    dropped = len(rows) - len(usable)
    if len(usable) < 3:
        print(f"{label}: only {len(usable)} usable rows, no fit")
        return
    xs = [r[xkey] for r in usable]
    ys = [r[ykey] for r in usable]
    b, a, r2 = powerfit(xs, ys)
    print(
        f"{label}: n={len(usable)} (dropped {dropped}) "
        f"{ykey} = {a:.3e} * {xkey}^{b:.3f}   R^2={r2:.3f}"
    )
    # Per-unit cost across the range: the flat-vs-growing read that does
    # not depend on trusting the fit.
    ordered = sorted(usable, key=lambda r: r[xkey])
    print(f"    {xkey:>8} {ykey:>10} {'per-unit ms':>12}")
    for r in ordered:
        print(
            f"    {r[xkey]:>8} {r[ykey]:>10.4f} "
            f"{r[ykey] / r[xkey] * 1000:>12.3f}"
        )


def main(argv):
    path = Path(argv[0])
    xkey, ykey = argv[1], argv[2]
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in rows if isinstance(r, dict) and "error" not in r]
    report(f"{path.name}: {ykey} vs {xkey}", rows, xkey, ykey)


if __name__ == "__main__":
    main(sys.argv[1:])
