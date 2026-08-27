"""Every [M-SYN] number added in revision 2 of the comparison document.

Revision 2 exists because an independent adversarial review found six defects
in revision 1. Each correction was re-verified against this review's own
artefacts before being adopted; this script is that verification, in one place,
so an implementation engineer can re-run it rather than trust it.

Produces:
  F1  baseline/depth tail on the pure-rotation null, the real-pair table, and
      the conjunction gate's recall (the finding that struck "the sufficient
      guard")
  F2  the all-pairs oracle ceiling for covisibility degree over the 72
      geometry-bearing keyframes (the finding that Stage 1's >15 stop/go was
      unmeetable)
  F3  like-for-like production-vs-oracle edge counts over the same 72
      keyframes (the finding that "42x" is 2.6x)
  F5  segment connectivity under five criteria, including this document's own
      term-8 consistency requirement
  F6  which segments carry geometry, and connectivity restricted to them
  F15 the gap-yield table recomputed at HEAD

Read-only. Reads the HEAD replay written by `world_build_session.py` into the
scratch directory named in `paths.json`, plus `census_at_head.json` and the
lane artefacts. No production code is modified.
"""

from __future__ import annotations

import collections
import glob
import itertools
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
SCRATCH = json.load(open(HERE / "paths.json"))["scratch"]

MIN_INLIERS = 15
MIN_TRI = 0.5


def head_replay():
    d = glob.glob(SCRATCH + "/repeat_A/worlds/*/derived/*")[0]
    sess = glob.glob(SCRATCH + "/repeat_A/worlds/*/sessions/*")[0]
    return Path(d), Path(sess)


def f1():
    print("\n=== F1  the gate that was struck ===")
    nulls = json.load(open(SCRATCH + "/dust3r_purerot_null.json"))
    bd = sorted(r["baseline_over_depth_0"] for r in nulls
                if r.get("baseline_over_depth_0") is not None)
    print(f"pointmap baseline/depth on TRUE-ZERO-baseline pairs (n={len(bd)} of {len(nulls)}):")
    print(f"  median {st.median(bd):.4f}  p90 {bd[int(.90*len(bd))]:.4f}  "
          f"p95 {bd[int(.95*len(bd))]:.4f}  p99 {bd[int(.99*len(bd))]:.4f}  "
          f"MAX {bd[-1]:.4f}")
    over = sum(1 for x in bd if x > 0.05)
    print(f"  exceeding the 0.05 threshold revision 1 proposed: "
          f"{over}/{len(bd)} = {100*over/len(bd):.1f}%   <-- stop/go demands 0%")

    print("\n  the real pairs the threshold was meant to admit:")
    for tag, path in (("undist", RESEARCH / "slam_learned_3d/results/dust3r_undist.json"),
                      ("raw", RESEARCH / "slam_learned_3d/results/dust3r_raw.json")):
        for r in json.load(open(path)):
            v = r.get("baseline_over_depth_0")
            if v is None:
                continue
            print(f"    {tag:7s} {r['name']:10s} {r['kind']:10s} b/d={v:.4f} "
                  f"{'PASS' if v > 0.05 else 'FAIL'}  "
                  f"recip_t_dir={r.get('recip_trans_dir_deg', float('nan')):.2f}")

    def conj(r):
        b = r.get("baseline_over_depth_0")
        t = r.get("recip_trans_dir_deg")
        q = r.get("recip_rot_deg")
        return (b is not None and t is not None and q is not None
                and b > 0.05 and t < 15 and q < 15)

    a = sum(1 for r in nulls if conj(r))
    print(f"\n  conjunction (b/d>0.05 AND t_dir<15 AND R<15):")
    print(f"    nulls accepted        {a}/{len(nulls)} = {100*a/len(nulls):.1f}%  (0% is the bar)")
    for tag, path in (("undist", RESEARCH / "slam_learned_3d/results/dust3r_undist.json"),
                      ("raw", RESEARCH / "slam_learned_3d/results/dust3r_raw.json")):
        rows = json.load(open(path))
        print(f"    real pairs, {tag:7s}  {sum(1 for r in rows if conj(r))}/{len(rows)} "
              f"<-- ZERO RECALL is why the gate is unusable")


def geometry_nodes(derived, sess):
    """Map support.json's (segment, within-segment index) to global keyframe index."""
    kfs = [json.loads(x) for x in (sess / "keyframes.jsonl").read_text().splitlines() if x.strip()]
    ctr, loc = collections.Counter(), {}
    for gi, k in enumerate(kfs):
        s = k["segment_index"]
        loc[(s, ctr[s])] = gi
        ctr[s] += 1
    sup = json.load(open(derived / "support.json"))["support"]
    by_landmark = collections.defaultdict(set)
    for seg, fr, feat, pt in sup:
        by_landmark[(seg, pt)].add((seg, fr))
    return kfs, loc, by_landmark


def f2_f3():
    derived, sess = head_replay()
    kfs, loc, by_landmark = geometry_nodes(derived, sess)
    nodes = sorted({v for vs in by_landmark.values() for v in vs})
    gid = {v: loc[v] for v in nodes}
    G = sorted(set(gid.values()))

    views = collections.Counter(len(v) for v in by_landmark.values())
    tot = sum(views.values())
    print("\n=== F2 / F3  like-for-like covisibility, and the oracle ceiling ===")
    print(f"landmarks {tot}; seen by exactly 2 views: {views[2]} = {100*views[2]/tot:.1f}%; "
          f">=3 views: {tot-views[2]} = {100*(tot-views[2])/tot:.1f}%")

    edges = collections.Counter()
    for (seg, pt), vs in by_landmark.items():
        for a, b in itertools.combinations(sorted(vs), 2):
            edges[(a, b)] += 1
    prod = [e for e, c in edges.items() if c >= MIN_INLIERS]
    pdeg = collections.defaultdict(set)
    for a, b in prod:
        pdeg[gid[a]].add(gid[b])
        pdeg[gid[b]].add(gid[a])

    cen = json.load(open(HERE / "census_at_head.json"))
    Gs = set(G)
    sub = [p for p in cen["pairs"]
           if p["i"] in Gs and p["j"] in Gs and p["f_inliers"] >= MIN_INLIERS]
    cdeg = collections.defaultdict(set)
    for p in sub:
        cdeg[p["i"]].add(p["j"])
        cdeg[p["j"]].add(p["i"])
    npairs = len(G) * (len(G) - 1) // 2
    print(f"over the SAME {len(G)} geometry-bearing keyframes ({npairs} pairs):")
    print(f"  production {len(prod)} edges ({100*len(prod)/npairs:.1f}%), "
          f"median degree {st.median([len(pdeg.get(k, ())) for k in G]):.1f}")
    print(f"  all-pairs  {len(sub)} edges ({100*len(sub)/npairs:.1f}%), "
          f"median degree {st.median([len(cdeg.get(k, ())) for k in G]):.1f}  <-- ORACLE CEILING")
    print(f"  LIKE-FOR-LIKE RATIO {len(sub)/len(prod):.2f}x   "
          f"(revision 1 quoted 42x, which compared 448 keyframes against 72)")
    allc = sum(1 for p in cen["pairs"] if p["f_inliers"] >= MIN_INLIERS)
    print(f"  for reference, all {cen['meta']['n_keyframes']} keyframes: {allc} edges")


def _components(pairs, seg, sel, min_support, nodes):
    cnt = collections.Counter()
    for p in pairs:
        a, b = seg[p["i"]], seg[p["j"]]
        if a == b or not sel(p):
            continue
        cnt[(min(a, b), max(a, b))] += 1
    ns = set(nodes)
    adj = collections.defaultdict(set)
    for (a, b), c in cnt.items():
        if c >= min_support and a in ns and b in ns:
            adj[a].add(b)
            adj[b].add(a)
    seen, out = set(), []
    for s in nodes:
        if s in seen:
            continue
        stack, comp = [s], []
        seen.add(s)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        out.append(sorted(comp))
    out.sort(key=len, reverse=True)
    return out


def f5_f6():
    cen = json.load(open(HERE / "census_at_head.json"))
    seg, P = cen["meta"]["segment_index"], cen["pairs"]
    S = sorted(set(seg))
    census = lambda p: (p["f_inliers"] >= MIN_INLIERS
                        and p.get("tri_angle") is not None and p["tri_angle"] >= MIN_TRI)
    prodlike = lambda p: (p["e_inliers"] >= MIN_INLIERS and p["matches"]
                          and p["e_inliers"] / p["matches"] >= 0.05
                          and p.get("tri_angle") is not None and p["tri_angle"] >= MIN_TRI)
    eg = lambda p: p["f_inliers"] >= 100

    print("\n=== F5  connectivity is criterion-dependent ===")
    for lab, sel, ms in (("census, >=1 supporting keyframe pair", census, 1),
                         ("production-like, >=1 supporting pair", prodlike, 1),
                         ("census + TERM 8 (>=3 supporting pairs)", census, 3),
                         ("production-like + TERM 8", prodlike, 3),
                         ("essential-graph strength (>=100 inliers)", eg, 1)):
        c = _components(P, seg, sel, ms, S)
        print(f"  {lab:42s} components={len(c):2d} largest={len(c[0]):2d}/{len(S)} "
              f"isolated={[x[0] for x in c if len(x) == 1]}")

    derived, sess = head_replay()
    pts = json.load(open(derived / "points.json"))["points"]
    cnt = collections.Counter(p["segment_index"] for p in pts)
    g = sorted(cnt)
    print("\n=== F6  a component is not a map ===")
    print(f"  segments carrying geometry: {len(g)} of {len(S)} -> {g}")
    print(f"  point counts: {dict(cnt)}")
    for lab, sel, ms in (("census, >=1", census, 1), ("production-like, >=1", prodlike, 1),
                         ("production-like + TERM 8", prodlike, 3)):
        c = _components(P, seg, sel, ms, g)
        print(f"  restricted to those {len(g)}, {lab:24s} -> {len(c)} components {c}")


def f15():
    cen = json.load(open(HERE / "census_at_head.json"))
    seg, P = cen["meta"]["segment_index"], cen["pairs"]
    derived, _ = head_replay()
    gs = {p["segment_index"] for p in json.load(open(derived / "points.json"))["points"]}

    def bucket(i, j):
        gp = abs(j - i)
        return ("consecutive" if gp == 1 else "gap2_5" if gp <= 5 else
                "gap6_20" if gp <= 20 else "gap21_100" if gp <= 100 else "gap>100")

    R = collections.defaultdict(lambda: [0, 0, 0])
    gl = [0, 0, 0]
    for p in P:
        r = R[bucket(p["i"], p["j"])]
        r[0] += 1
        useful = (p["f_inliers"] >= MIN_INLIERS and p.get("tri_angle") is not None
                  and p["tri_angle"] >= MIN_TRI)
        if p["f_inliers"] >= MIN_INLIERS:
            r[1] += 1
            r[2] += useful
        if p["j"] - p["i"] == 1 and seg[p["i"]] == seg[p["j"]] and seg[p["i"]] not in gs:
            gl[0] += 1
            if p["f_inliers"] >= MIN_INLIERS:
                gl[1] += 1
                gl[2] += useful

    print("\n=== F15  gap-yield table, recomputed at HEAD ===")
    print(f"  {'bucket':<14}{'pairs':>8}{'%edges':>10}{'%useful':>10}")
    for b in ("consecutive", "gap2_5", "gap6_20", "gap21_100", "gap>100"):
        n, e, u = R[b]
        print(f"  {b:<14}{n:>8}{100*e/n:>9.1f}%{100*u/n:>9.1f}%")
    print(f"  consecutive pairs inside geometry-less segments: n={gl[0]} "
          f"edges={100*gl[1]/gl[0]:.1f}% useful={100*gl[2]/gl[0]:.1f}%")


if __name__ == "__main__":
    print("NO GROUND TRUTH EXISTS. Every number below is comparative or "
          "self-consistency, except the pure-rotation null, whose true "
          "translation is exactly zero by construction.")
    f1()
    f2_f3()
    f5_f6()
    f15()
