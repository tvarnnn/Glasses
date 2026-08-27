"""ADVERSARIAL: is "one connected component" robust to the gate used?

The synthesis declares "connectivity is not the gap" on the strength of the
census criterion: f_inliers >= 15 (F-RANSAC @3.0px) AND tri_angle >= 0.5 deg.
But section 5.1.4 of the same document STRIKES an F/E-RANSAC-with-epipolar-
inliers criterion as unsound under degeneracy (13.0% false-positive on
zero-baseline pairs). So recompute segment connectivity under progressively
stricter criteria, including production's own cheirality-ratio gate, which the
census happens to have recorded (e_inliers is recoverPose's cheirality count).

Also: does a component imply REGISTRABILITY? Count how many segments actually
carry triangulated geometry.
"""
from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path

MIN_INLIERS = 15
MIN_RATIO = 0.05
MIN_TRI = 0.5


def components(seg_adj, segs):
    seen, comps = set(), []
    for s in sorted(segs):
        if s in seen:
            continue
        stack, comp = [s], []
        seen.add(s)
        while stack:
            c = stack.pop()
            comp.append(c)
            for nb in seg_adj.get(c, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        comps.append(sorted(comp))
    comps.sort(key=len, reverse=True)
    return comps


def analyse(path, label):
    d = json.loads(Path(path).read_text())
    seg = d["meta"]["segment_index"]
    rows = d["pairs"]
    segs = sorted(set(seg))
    print(f"\n############ {label}: {len(seg)} keyframes, {len(segs)} segments, "
          f"{len(rows)} pairs")

    def gate_census(p):
        return (p["f_inliers"] >= MIN_INLIERS and p["tri_angle"] is not None
                and p["tri_angle"] >= MIN_TRI)

    def gate_production_like(p):
        m = p["matches"]
        e = p["e_inliers"]
        return (e >= MIN_INLIERS and m and e / m >= MIN_RATIO
                and p["tri_angle"] is not None and p["tri_angle"] >= MIN_TRI)

    def gate_essential_graph(p):
        return p["f_inliers"] >= 100 and p["tri_angle"] is not None and p["tri_angle"] >= MIN_TRI

    for name, g, min_edges in (
            ("census criterion  (F>=15, tri>=0.5)", gate_census, 1),
            ("census, >=3 supporting kf pairs", gate_census, 3),
            ("PRODUCTION-LIKE  (cheirality>=15, ratio>=.05, tri>=0.5)", gate_production_like, 1),
            ("production-like, >=3 supporting kf pairs", gate_production_like, 3),
            ("ORB-SLAM3 essential-graph th=100", gate_essential_graph, 1),
    ):
        cnt = defaultdict(int)
        n_cross = n_edge = 0
        for p in rows:
            if not g(p):
                continue
            n_edge += 1
            a, b = seg[p["i"]], seg[p["j"]]
            if a != b:
                n_cross += 1
                cnt[(min(a, b), max(a, b))] += 1
        adj = defaultdict(set)
        for (a, b), c in cnt.items():
            if c >= min_edges:
                adj[a].add(b)
                adj[b].add(a)
        comps = components(adj, segs)
        iso = [s for s in segs if s not in adj]
        print(f"{name:56s} min_edges={min_edges}  kf-edges={n_edge:6d} cross={n_cross:5d} "
              f"segpairs={sum(1 for c in cnt.values() if c>=min_edges):4d}  "
              f"components={len(comps):2d} largest={len(comps[0])}/{len(segs)} isolated={iso}")


for arg in sys.argv[1:]:
    path, label = arg.split("=", 1)
    analyse(path, label)
