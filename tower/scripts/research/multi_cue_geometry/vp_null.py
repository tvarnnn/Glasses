"""Does the Manhattan triplet explain more line length than a random triplet?

The control that decides whether 98.6% "found" means anything. A RANSAC
that maximises a score always returns something; the question is whether
what it returns beats chance on the same lines.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Every path below is relative to the tower project root, so the
# harness runs the same from any working directory.
TOWER_ROOT = HERE.parents[2]
import numpy as np

sys.path.insert(0, str(TOWER_ROOT))
sys.path.insert(0, str(HERE))
from lines import detect_segments, segment_normals, manhattan_frame, refine_manhattan
from tower.world_builder.frontend import decode_gray

INTR = json.loads(TOWER_ROOT / 'data/world_builder/intrinsics/360x640.json'.read_text())
K = np.array([[INTR['fx'],0,INTR['cx']],[0,INTR['fy'],INTR['cy']],[0,0,1.0]])
MOVING = ["22e9d4289cb440fbb3f14e6da369a136","b35d8ab85c364b9da44499d2a7f00638",
          "20ce3c2366ee4cdfb46cb8db09578058","ab10cb203cf048e58cf2f79a120a54a4",
          "5387a76568e84e13936862f612f8bc81","e1c52b9ff7f84dd5a54fee6150b7f854",
          "854e9688d2c54ae398eff4fb7c141522","fe744b6827c44e3e8c3a309d665dbf80"]

def random_rotation(rng):
    A = rng.normal(size=(3,3)); Q,_ = np.linalg.qr(A)
    if np.linalg.det(Q) < 0: Q[:,-1] *= -1
    return Q

def share(normals, lengths, R, tol_deg):
    cos = np.abs(normals @ R.T)
    axis = np.argmin(cos, axis=1)
    owned = cos[np.arange(len(normals)), axis] < np.cos(np.radians(90-tol_deg))
    per = np.array([lengths[owned & (axis==a)].sum() for a in range(3)])
    return per, per.sum()/max(lengths.sum(), 1e-9)

TOLS = [1.0, 1.5, 3.0, 5.0]
rng = np.random.default_rng(7)
res = {t: {'mf': [], 'rand': [], 'axes3': []} for t in TOLS}
N = 0
for cap in MOVING:
    c = TOWER_ROOT / 'data/captures'/cap
    rows = [json.loads(l) for l in (c/'frames.jsonl').read_text().splitlines() if l.strip()]
    for i in np.linspace(0, len(rows)-1, 60).astype(int):
        gray = decode_gray((c/rows[i]['relpath']).read_bytes())
        seg = detect_segments(gray)
        if len(seg) < 12: continue
        length = np.hypot(seg[:,2]-seg[:,0], seg[:,3]-seg[:,1])
        n = segment_normals(seg, K)
        N += 1
        for t in TOLS:
            mf = manhattan_frame(n, length, tol_deg=t, rng=np.random.default_rng(0))
            if mf is None: continue
            R = refine_manhattan(n, length, mf[0], tol_deg=t)
            per, s = share(n, length, R, t)
            res[t]['mf'].append(s)
            res[t]['axes3'].append(int((per > 0.05*length.sum()).sum()))
            # best of 20 random triplets -- a fair-ish null, since the
            # Manhattan fit is itself a maximum over many candidates
            rs = max(share(n, length, random_rotation(rng), t)[1] for _ in range(20))
            res[t]['rand'].append(rs)

print(f"frames: {N}\n")
print(f"{'tol':>5} {'fitted share':>14} {'best-of-20 random':>19} {'ratio':>7} {'axes>=5% of len: 3':>20}")
for t in TOLS:
    a = np.array(res[t]['mf']); b = np.array(res[t]['rand']); ax = np.array(res[t]['axes3'])
    print(f"{t:>5} {np.median(a):>14.3f} {np.median(b):>19.3f} {np.median(a)/max(np.median(b),1e-9):>7.2f} "
          f"{100*(ax==3).mean():>19.1f}%")
