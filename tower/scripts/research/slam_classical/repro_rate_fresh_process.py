"""Reproduction RATE of the uninitialised-mask bug, across FRESH processes.

`repro_ransac_mask.py` showed the garbage mask appeared on TRIAL 0 and then
never again in 49 further calls inside the same process. That is the
signature of a buffer that is dirty on first use and zeroed thereafter, and
it explains why the research lead could not reproduce it: any call made
after other OpenCV geometry has already run in that process sees a warm,
already-zeroed buffer.

So the honest way to measure the rate is one call per FRESH process.

Child mode (`--child`) does exactly one thing: build the degenerate real
point set and make ONE `cv2.findFundamentalMat` call, then print the mask
sum and whether it was binary. Parent mode spawns N children and tallies.

Run:  python scripts/research/slam_classical/repro_rate_fresh_process.py [N]
"""
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]

A_REL, B_REL = 'images/00000345.jpg', 'images/00001824.jpg'
SESS_REL = ('data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
            '/sessions/dd5d13a2381e430db9b27c7da2cf2928')


def child():
    sys.path.insert(0, str(TOWER_ROOT))
    import cv2
    import numpy as np

    from tower.world_builder.frontend import decode_gray
    from tower.world_builder.geometry import (detect_and_describe,
                                              match_descriptors)
    sess = TOWER_ROOT / SESS_REL
    ka, da = detect_and_describe(decode_gray((sess / A_REL).read_bytes()))
    kb, db = detect_and_describe(decode_gray((sess / B_REL).read_bytes()))
    pa, pb = match_descriptors(ka, da, kb, db)

    # THE call, first geometric estimation in this process.
    F, mask = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 3.0, 0.99)
    if mask is None:
        print("NOMASK")
        return
    u = np.unique(mask)
    binary = set(u.tolist()) <= {0, 1} and int(mask.sum()) <= len(pa)
    print(f"{'BINARY' if binary else 'GARBAGE'} "
          f"model={'OK' if F is not None else 'None'} "
          f"sum={int(mask.sum())} n_unique={len(u)} n={len(pa)}")


def main():
    if '--child' in sys.argv:
        child()
        return
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 40
    print(f"spawning {n} FRESH processes, one findFundamentalMat call each")
    print(f"pair: {A_REL} vs {B_REL} (242 matches onto 3 distinct points)\n")
    outcomes, sums = Counter(), Counter()
    for k in range(n):
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child'],
                           capture_output=True, text=True, cwd=str(TOWER_ROOT))
        line = (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else 'EMPTY'
        kind = line.split()[0] if line else 'EMPTY'
        outcomes[kind] += 1
        if 'sum=' in line:
            sums[int(line.split('sum=')[1].split()[0])] += 1
        if k < 10 or kind == 'GARBAGE':
            print(f"  run {k:>3}: {line}")
    print(f"\noutcomes over {n} fresh processes: {dict(outcomes)}")
    print(f"distinct mask sums: {sorted(sums.items())}")
    g = outcomes.get('GARBAGE', 0)
    print(f"\n>>> GARBAGE (non-binary mask or sum > n): {g}/{n} "
          f"= {g / n * 100:.1f}% of fresh processes")
    print(">>> A binary mask can NEVER exceed n. Any GARBAGE row is the bug.")


if __name__ == '__main__':
    main()
