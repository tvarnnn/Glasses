"""Is the line/vanishing-direction cue present in real Ray-Ban frames?

Measures yield and cost only. Nothing here claims a cue is useful; it
answers the prior question -- whether there is anything to use.
"""
import json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]
import numpy as np, cv2

sys.path.insert(0, str(TOWER_ROOT))
sys.path.insert(0, str(HERE))
from lines import (detect_segments, segment_normals, manhattan_frame,
                   refine_manhattan, canonicalise)
from tower.world_builder.frontend import decode_gray, seed_tracks
from tower.world_builder.geometry import detect_and_describe

INTR = json.loads(TOWER_ROOT / 'data/world_builder/intrinsics/360x640.json'.read_text())
K = np.array([[INTR['fx'], 0, INTR['cx']],
              [0, INTR['fy'], INTR['cy']],
              [0, 0, 1.0]])

# The eight captures with real motion, largest first. The static ones are
# excluded here on purpose: a cue that only works when nothing moves is
# not a cue for a walking wearer.
MOVING = ["22e9d4289cb440fbb3f14e6da369a136", "b35d8ab85c364b9da44499d2a7f00638",
          "20ce3c2366ee4cdfb46cb8db09578058", "ab10cb203cf048e58cf2f79a120a54a4",
          "5387a76568e84e13936862f612f8bc81", "e1c52b9ff7f84dd5a54fee6150b7f854",
          "854e9688d2c54ae398eff4fb7c141522", "fe744b6827c44e3e8c3a309d665dbf80"]

PER_CAPTURE = int(sys.argv[1]) if len(sys.argv) > 1 else 120


def frames_of(cap_id, limit):
    cap = TOWER_ROOT / 'data/captures' / cap_id
    rows = [json.loads(l) for l in (cap / 'frames.jsonl').read_text().splitlines() if l.strip()]
    idx = np.linspace(0, len(rows) - 1, min(limit, len(rows))).astype(int)
    for i in idx:
        yield cap / rows[i]['relpath']


rows = []
t_lsd, t_mf, t_orb = [], [], []
for cap_id in MOVING:
    for path in frames_of(cap_id, PER_CAPTURE):
        gray = decode_gray(path.read_bytes())
        t0 = time.perf_counter()
        seg = detect_segments(gray)
        t_lsd.append((time.perf_counter() - t0) * 1000)

        length = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]) if len(seg) else np.zeros(0)
        n = segment_normals(seg, K)

        t0 = time.perf_counter()
        mf = manhattan_frame(n, length, rng=np.random.default_rng(0)) if len(seg) >= 6 else None
        if mf is not None:
            R = refine_manhattan(n, length, mf[0])
            cos = np.abs(n @ R.T)
            axis = np.argmin(cos, axis=1)
            owned = cos[np.arange(len(n)), axis] < np.cos(np.radians(88.5))
            per_axis = np.array([length[owned & (axis == a)].sum() for a in range(3)])
        t_mf.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        kp, desc = detect_and_describe(gray)
        t_orb.append((time.perf_counter() - t0) * 1000)

        rows.append(dict(
            cap=cap_id, frame=path.name,
            n_seg=len(seg),
            total_len=float(length.sum()),
            med_len=float(np.median(length)) if len(length) else 0.0,
            max_len=float(length.max()) if len(length) else 0.0,
            n_orb=len(kp),
            mf=mf is not None,
            axis_len=[float(x) for x in per_axis] if mf is not None else None,
            inlier_share=float(per_axis.sum() / length.sum()) if mf is not None and length.sum() > 0 else 0.0,
            axes_supported=int((per_axis > 100).sum()) if mf is not None else 0,
        ))

def pct(a, q): return round(float(np.percentile(a, q)), 2)
arr = lambda k: np.array([r[k] for r in rows], float)

print(f"frames measured: {len(rows)}  captures: {len(MOVING)}")
print()
print("LINE SEGMENT YIELD (LSD, >=20 px)")
print(f"  segments/frame     p5 {pct(arr('n_seg'),5)}  p25 {pct(arr('n_seg'),25)}  median {pct(arr('n_seg'),50)}  p75 {pct(arr('n_seg'),75)}  p95 {pct(arr('n_seg'),95)}")
print(f"  frames with 0      {int((arr('n_seg')==0).sum())} ({100*(arr('n_seg')==0).mean():.1f}%)")
print(f"  frames with <10    {int((arr('n_seg')<10).sum())} ({100*(arr('n_seg')<10).mean():.1f}%)")
print(f"  median seg length  {pct(arr('med_len'),50)} px   max-in-frame median {pct(arr('max_len'),50)} px")
print(f"  total length/frame median {pct(arr('total_len'),50)} px")
print()
print("ORB, same frames (for reference)")
print(f"  keypoints/frame    p5 {pct(arr('n_orb'),5)}  median {pct(arr('n_orb'),50)}  p95 {pct(arr('n_orb'),95)}")
print()
print("MANHATTAN FRAME")
mf = arr('mf').astype(bool)
print(f"  found              {int(mf.sum())}/{len(rows)} ({100*mf.mean():.1f}%)")
sup = arr('axes_supported')
for a in range(4):
    print(f"  axes with >100px support == {a}: {int((sup==a).sum())} ({100*(sup==a).mean():.1f}%)")
print(f"  inlier length share median {pct(arr('inlier_share'),50)}  p25 {pct(arr('inlier_share'),25)}")
print()
print("COST (ms, this host, 360x640)")
for name, t in (("LSD detect", t_lsd), ("Manhattan RANSAC", t_mf), ("ORB detect+describe", t_orb)):
    print(f"  {name:22} median {np.median(t):7.2f}  p95 {np.percentile(t,95):7.2f}")

json.dump(rows, open(str(HERE / 'cue_availability.json'), 'w'))
