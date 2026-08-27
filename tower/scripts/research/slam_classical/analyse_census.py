"""What the all-pairs census says about the classical stack's preconditions.

Reads covisibility_census.json and answers, in order, the questions that
decide whether ORB-SLAM3's architecture is worth copying HERE:

  Q1  Is there covisibility to find at all, or is the chain a hard ceiling?
  Q2  Is that covisibility LOCAL (makes BA non-vacuous) or LONG-RANGE
      (makes loop closure / Atlas merging non-vacuous)? These are not the
      same and conflating them is the standard mistake.
  Q3  Does the covisibility carry BASELINE, or only appearance overlap?
      Prior lanes measured 54.7% of failing pairs as baseline-limited, so
      an edge with 300 matches and 0.1 deg of parallax is a trap, not a
      constraint.
  Q4  Would a covisibility graph WELD THE 51 SEGMENTS BACK TOGETHER?
      This is the direct test of the Atlas analogy. Connected components
      over the segment graph is the number of maps that would survive.
  Q5  Does r_H at ORB-SLAM's 0.45 separate anything on REAL frames? The
      repo says it saturates at 0.471-0.499 on SYNTHETIC scenes and
      deliberately does not gate on it. Confirm or refute on real data.

NO GROUND TRUTH. Everything is comparative / self-consistency.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
data = json.loads((Path(sys.argv[1]) if len(sys.argv) > 1
                   else HERE / 'covisibility_census.json').read_text())
meta, pairs = data['meta'], data['pairs']
seg = np.array(meta['segment_index'])
seq = np.array(meta['source_seq'])
n = meta['n_keyframes']

def auc(scores, labels):
    """P(score of a random positive > score of a random negative).

    Rank-based (Mann-Whitney U) so ties count as 0.5, and written out
    rather than reused from sklearn so the direction is auditable: the
    first version of this file counted DISCORDANT pairs and reported
    0.005 where the truth was 0.995.
    """
    scores = np.asarray(scores, float)
    labels = np.asarray(labels, float)
    keep = np.isfinite(scores)
    scores, labels = scores[keep], labels[keep]
    pos, neg = labels.sum(), (1 - labels).sum()
    if pos == 0 or neg == 0:
        return float('nan')
    order = np.argsort(scores)
    ranks = np.empty(len(scores), float)
    ranks[order] = np.arange(1, len(scores) + 1)
    # average ranks over ties
    s_sorted = scores[order]
    start = 0
    for k in range(1, len(s_sorted) + 1):
        if k == len(s_sorted) or s_sorted[k] != s_sorted[start]:
            ranks[order[start:k]] = (start + 1 + k) / 2.0
            start = k
    return float((ranks[labels == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


i = np.array([p['i'] for p in pairs])
j = np.array([p['j'] for p in pairs])
matches = np.array([p['matches'] for p in pairs])
mutual = np.array([p.get('mutual', 0) for p in pairs])
finl = np.array([p['f_inliers'] for p in pairs])
einl = np.array([p['e_inliers'] for p in pairs])
ffail = np.array([bool(p.get('f_failed', False)) for p in pairs])
hfail = np.array([bool(p.get('h_failed', False)) for p in pairs])
tri = np.array([np.nan if p['tri_angle'] is None else p['tri_angle'] for p in pairs])
rh = np.array([np.nan if p['r_h'] is None else p['r_h'] for p in pairs])

kf_gap = np.abs(j - i)                 # distance in KEYFRAME index
frame_gap = np.abs(seq[j] - seq[i])    # distance in SOURCE FRAMES (~12 fps)
same_seg = seg[i] == seg[j]
TH = meta['covis_edge_th']             # 15, ORB-SLAM3 UpdateConnections
EG = meta['essential_graph_th']        # 100, essential graph
MINANG = meta['min_tri_angle']         # 0.5 deg, production's own criterion

print("=" * 74)
print(f"ALL-PAIRS COVISIBILITY CENSUS -- {n} keyframes, {len(pairs)} pairs, "
      f"{len(set(seg.tolist()))} production segments")
print(f"detect {meta['t_detect_s']:.1f}s + match {meta['t_match_s']:.1f}s "
      f"on {meta['workers']} workers; ORB={meta['orb_features']} lowe={meta['lowe']}")
print("=" * 74)

# ---------------------------------------------------------------- Q1 + Q2
edge = finl >= TH
strong = finl >= EG
print(f"\nQ1  EDGES  (verified F-inliers >= {TH}, ORB-SLAM3 covisibility threshold)")
print(f"    pairs with any match      : {(matches > 0).sum():>7} "
      f"({(matches > 0).mean() * 100:.1f}% of all pairs)")
print(f"    covisibility edges >= {TH:<3}  : {edge.sum():>7} "
      f"({edge.mean() * 100:.2f}%)")
print(f"    essential-graph edges >={EG}: {strong.sum():>7} "
      f"({strong.mean() * 100:.2f}%)")

deg = np.zeros(n, int)
for a, b in zip(i[edge], j[edge]):
    deg[a] += 1
    deg[b] += 1
print(f"\n    COVISIBILITY DEGREE per keyframe (the chain's value is 1-2):")
print(f"      median={np.median(deg):.0f}  mean={deg.mean():.1f}  "
      f"min={deg.min()}  max={deg.max()}  "
      f"isolated(deg=0)={int((deg == 0).sum())}")
for q in (10, 25, 50, 75, 90):
    print(f"      p{q:<3}= {np.percentile(deg, q):.0f}", end='')
print()

print(f"\nQ2  RANGE of those {edge.sum()} edges")
for lo, hi, label in [(1, 1, 'consecutive kf (what _extend already does)'),
                      (2, 5, 'kf gap 2-5'), (6, 20, 'kf gap 6-20'),
                      (21, 100, 'kf gap 21-100'), (101, 10 ** 9, 'kf gap >100')]:
    m = edge & (kf_gap >= lo) & (kf_gap <= hi)
    print(f"      {label:<42} {m.sum():>6}")
print(f"      of which CROSS-SEGMENT                     "
      f"{int((edge & ~same_seg).sum()):>6}")
print(f"      of which cross-segment AND kf gap >20      "
      f"{int((edge & ~same_seg & (kf_gap > 20)).sum()):>6}")

# ---------------------------------------------------------------------- Q3
print(f"\nQ3  BASELINE, not just appearance "
      f"(median triangulation angle; production needs >= {MINANG} deg)")
ok = edge & np.isfinite(tri)
print(f"    edges with a recoverable pose  : {int(ok.sum())}")
if ok.sum():
    t = tri[ok]
    print(f"    triangulation angle deg: median={np.median(t):.3f}  "
          f"p10={np.percentile(t, 10):.3f}  p90={np.percentile(t, 90):.3f}")
    for lo, hi, label in [(1, 1, 'consecutive kf'), (2, 20, 'kf gap 2-20'),
                          (21, 10 ** 9, 'kf gap >20')]:
        m = ok & (kf_gap >= lo) & (kf_gap <= hi)
        if m.sum():
            print(f"      {label:<16} n={m.sum():>6}  "
                  f"median angle={np.median(tri[m]):.3f} deg  "
                  f"frac >= {MINANG}: {(tri[m] >= MINANG).mean() * 100:.1f}%")
    m = ok & ~same_seg
    if m.sum():
        print(f"      {'cross-segment':<16} n={m.sum():>6}  "
              f"median angle={np.median(tri[m]):.3f} deg  "
              f"frac >= {MINANG}: {(tri[m] >= MINANG).mean() * 100:.1f}%")

useful = edge & np.isfinite(tri) & (tri >= MINANG)
print(f"\n    GEOMETRICALLY USEFUL edges (>= {TH} inliers AND >= {MINANG} deg): "
      f"{int(useful.sum())}  ({useful.sum() / max(1, edge.sum()) * 100:.1f}% of edges)")
udeg = np.zeros(n, int)
for a, b in zip(i[useful], j[useful]):
    udeg[a] += 1
    udeg[b] += 1
print(f"    useful degree: median={np.median(udeg):.0f}  mean={udeg.mean():.1f}  "
      f"isolated={int((udeg == 0).sum())}")


# ---------------------------------------------------------------------- Q4
def components(mask, nodes, key):
    """Connected components of `key` under the edge set `mask`."""
    parent = {v: v for v in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in zip(key[i[mask]], key[j[mask]]):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups = defaultdict(list)
    for v in nodes:
        groups[find(v)].append(v)
    return sorted((len(v) for v in groups.values()), reverse=True), len(groups)


segs = sorted(set(seg.tolist()))
print(f"\nQ4  WOULD COVISIBILITY WELD THE SEGMENTS BACK TOGETHER?")
print(f"    production today: {len(segs)} segments, never reconnected")
for label, mask in [(f"edges >= {TH}", edge),
                    (f"edges >= {EG}", strong),
                    (f"edges >= {TH} AND parallax >= {MINANG} deg", useful)]:
    sizes, ncomp = components(mask, segs, seg)
    print(f"    under {label:<42} -> {ncomp:>3} components; "
          f"largest holds {sizes[0]}/{len(segs)} segments; sizes={sizes[:6]}")
# keyframe-level too
for label, mask in [(f"edges >= {TH}", edge), ("useful edges", useful)]:
    sizes, ncomp = components(mask, list(range(n)), np.arange(n))
    print(f"    KEYFRAME-level under {label:<28} -> {ncomp:>3} components; "
          f"largest {sizes[0]}/{n} keyframes")

# ---------------------------------------------------------------------- Q5
print(f"\nQ5  r_H ON REAL FRAMES (repo measured 0.471-0.499 on SYNTHETIC and "
      f"does not gate)")
h = rh[np.isfinite(rh) & edge]
if len(h):
    print(f"    n={len(h)}  median={np.median(h):.3f}  p5={np.percentile(h, 5):.3f}  "
          f"p95={np.percentile(h, 95):.3f}  min={h.min():.3f}  max={h.max():.3f}")
    print(f"    fraction above ORB-SLAM's 0.45 rotation-dominant threshold: "
          f"{(h > 0.45).mean() * 100:.1f}%")
    hu = rh[np.isfinite(rh) & useful]
    hb = rh[np.isfinite(rh) & edge & np.isfinite(tri) & (tri < MINANG)]
    if len(hu) and len(hb):
        print(f"    r_H on GOOD-parallax edges (n={len(hu)}): median={np.median(hu):.3f}")
        print(f"    r_H on LOW-parallax  edges (n={len(hb)}): median={np.median(hb):.3f}")
        print(f"    separation between the two classes r_H is supposed to "
              f"distinguish: {abs(np.median(hu) - np.median(hb)):.3f}")
        # How good a classifier is r_H, really? POSITIVE CLASS = LOW
        # PARALLAX, because detecting the rotation-dominant/degenerate case
        # is the entire job r_H is asked to do, and higher r_H is supposed
        # to mean more rotation-dominant.
        a = auc(np.concatenate([hb, hu]),
                np.concatenate([np.ones(len(hb)), np.zeros(len(hu))]))
        print(f"    AUC of r_H as a LOW-PARALLAX detector: {a:.3f} "
              f"(0.5 = coin flip, 1.0 = perfect)")
        for th in (0.45, 0.47, 0.50):
            print(f"      gate at r_H > {th}: catches "
                  f"{(hb > th).mean() * 100:5.1f}% of low-parallax edges, "
                  f"but also discards {(hu > th).mean() * 100:5.1f}% of GOOD ones")

# --------------------------------------------------- revisit / loop closure
print(f"\nQ6  REVISITS -- are there loop-closure opportunities at all?")
fps = 11.99
for gap_s in (5, 10, 30, 60):
    g = frame_gap > gap_s * fps
    print(f"    edges separated by > {gap_s:>2}s of capture: "
          f"{int((edge & g).sum()):>6} edges "
          f"({int((useful & g).sum()):>5} with usable parallax)")
top = np.argsort(-finl * (frame_gap > 30 * fps))[:12]
print(f"    strongest long-gap (>30s) candidate links:")
for k in top:
    if finl[k] < TH or frame_gap[k] <= 30 * fps:
        continue
    print(f"      kf {i[k]:>3}(seg{seg[i[k]]:>2}) <-> kf {j[k]:>3}(seg{seg[j[k]]:>2})  "
          f"gap={frame_gap[k]:>4} frames ({frame_gap[k] / fps:5.1f}s)  "
          f"matches={matches[k]:>4} Finl={finl[k]:>4} "
          f"ang={tri[k]:.2f} r_H={rh[k]:.2f}")

# --------------------------------------------------------- segment autopsy
# ------------------------------------------- false-loop-closure guard power
print(f"\nQ6b RANSAC FAILURE AS A GUARD, and a live OpenCV-5 defect")
cand = matches >= 8
print(f"    pairs offered >= 8 ratio-test matches      : {int(cand.sum())}")
print(f"    of those, fundamental-matrix fit RETURNED None: "
      f"{int(ffail[cand].sum())} ({ffail[cand].mean() * 100:.1f}%)")
print(f"    of those, homography fit RETURNED None       : "
      f"{int(hfail[cand].sum())} ({hfail[cand].mean() * 100:.1f}%)")
print(f"    MEASURED on this host: when cv2 5.0 RANSAC fails it returns")
print(f"    model=None and leaves the mask UNINITIALISED. "
      f"tower/world_builder/geometry.py:homography_ratio discards the model")
print(f"    (`_, h_mask = ...`) and reads the mask regardless, so r_H is")
print(f"    computed from garbage on every one of those pairs.")
hi_match_no_geom = cand & ffail & (matches >= 100)
print(f"    pairs with >= 100 matches but NO fundamental fit: "
      f"{int(hi_match_no_geom.sum())}  <- these are the false-loop-closure traps")

print(f"\nQ6c RECIPROCITY as the guard (prior research: reprojection is not, "
      f"reciprocity is)")
with np.errstate(divide='ignore', invalid='ignore'):
    surv = np.where(matches > 0, mutual / np.maximum(matches, 1), np.nan)
good = edge & np.isfinite(tri) & (tri >= MINANG)
trap = cand & ffail & (matches >= 50)
if good.sum() and trap.sum():
    print(f"    mutual/forward ratio on VERIFIED-good edges (n={int(good.sum())}): "
          f"median={np.nanmedian(surv[good]):.3f}")
    print(f"    mutual/forward ratio on GEOMETRY-LESS traps  (n={int(trap.sum())}): "
          f"median={np.nanmedian(surv[trap]):.3f}")
    # POSITIVE CLASS = the genuinely good edge; higher reciprocity should
    # mean more trustworthy.
    a = auc(np.concatenate([surv[good], surv[trap]]),
            np.concatenate([np.ones(int(good.sum())), np.zeros(int(trap.sum()))]))
    print(f"    AUC of the reciprocity ratio at separating them: {a:.3f} "
          f"(0.5 = coin flip, 1.0 = perfect)")
    for th in (0.3, 0.5, 0.7):
        print(f"      threshold {th}: keeps {(surv[good] >= th).mean() * 100:5.1f}% of "
              f"good edges, admits {(surv[trap] >= th).mean() * 100:5.1f}% of traps")

print(f"\nQ7  THE 32 GEOMETRY-LESS SEGMENTS -- do they have external covisibility?")
size = Counter(seg.tolist())
best_ext = defaultdict(int)
for k in np.where(edge & ~same_seg)[0]:
    best_ext[seg[i[k]]] = max(best_ext[seg[i[k]]], int(finl[k]))
    best_ext[seg[j[k]]] = max(best_ext[seg[j[k]]], int(finl[k]))
singl = [s for s in segs if size[s] == 1]
print(f"    singleton segments (1 keyframe): {len(singl)} "
      f"-- of these {sum(1 for s in singl if best_ext[s] >= TH)} have a "
      f"cross-segment covisibility edge >= {TH}")
print(f"    segments with NO cross-segment edge at all: "
      f"{sum(1 for s in segs if best_ext[s] < TH)}/{len(segs)}")
