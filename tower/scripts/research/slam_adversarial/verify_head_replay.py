"""ADVERSARIAL: independently recompute the synthesis's HEAD-replay numbers.

Read-only. Verifies:
  * two-view landmark fraction (synthesis: 66.1%)
  * >=3-view landmark fraction (synthesis: 33.9%)
  * production covisibility edges at th>=15 shared points (synthesis: 189)
  * median covisibility degree over geometry-bearing keyframes (synthesis 5.5/72)
  * cross-segment production edges (synthesis: 0)
  * bit-for-bit reproducibility of poses.json / points.json across two runs
"""
import json, statistics as st, sys
from collections import defaultdict
from pathlib import Path


def load(root):
    root = Path(root)
    w = next((root / "worlds").iterdir())
    d = next((w / "derived").iterdir())
    return (json.loads((d / "support.json").read_text())["support"],
            json.loads((d / "points.json").read_text())["points"],
            json.loads((d / "poses.json").read_text())["poses"])


def report(tag, support, points, poses):
    print(f"\n=== {tag} ===")
    # landmark -> set of (segment, frame)
    obs = defaultdict(set)
    for seg, frame, feat, pt in support:
        obs[(seg, pt)].add((seg, frame))
    n = len(obs)
    counts = [len(v) for v in obs.values()]
    two = sum(1 for c in counts if c == 2)
    ge3 = sum(1 for c in counts if c >= 3)
    one = sum(1 for c in counts if c <= 1)
    print(f"points.json landmarks         : {len(points)}")
    print(f"landmarks appearing in support: {n}")
    print(f"  seen by exactly 2 views     : {two} = {100*two/n:.1f}%")
    print(f"  seen by >=3 views           : {ge3} = {100*ge3/n:.1f}%")
    print(f"  seen by <=1 view            : {one} = {100*one/n:.1f}%")

    # covisibility from support: keyframe = (segment, frame)
    kf_pts = defaultdict(set)
    for seg, frame, feat, pt in support:
        kf_pts[(seg, frame)].add((seg, pt))
    kfs = sorted(kf_pts)
    print(f"geometry-bearing keyframes    : {len(kfs)}")
    edges = 0
    cross = 0
    deg = defaultdict(int)
    for i in range(len(kfs)):
        for j in range(i + 1, len(kfs)):
            shared = len(kf_pts[kfs[i]] & kf_pts[kfs[j]])
            if shared >= 15:
                edges += 1
                deg[kfs[i]] += 1
                deg[kfs[j]] += 1
                if kfs[i][0] != kfs[j][0]:
                    cross += 1
    degs = [deg[k] for k in kfs]
    print(f"covisibility edges (>=15 pts) : {edges}   cross-segment: {cross}")
    print(f"median degree over those kf   : {st.median(degs)}")
    # pose statuses
    from collections import Counter
    print("pose status mix:", dict(Counter(p["status"] for p in poses)))
    return edges


def strip_ids(obj, sid):
    s = json.dumps(obj)
    return s.replace(sid, "<SID>")


def main():
    a, b = sys.argv[1], sys.argv[2]
    sa, pa, qa = load(a)
    sb, pb, qb = load(b)
    report("RUN A", sa, pa, qa)
    sid_a = qa[0]["keyframe_id"].split(":")[0]
    sid_b = qb[0]["keyframe_id"].split(":")[0]
    print("\n=== REPRODUCIBILITY A vs B ===")
    print("poses identical after id strip :",
          strip_ids(qa, sid_a) == strip_ids(qb, sid_b),
          f"({len(qa)} vs {len(qb)} records)")
    print("points identical               :", pa == pb,
          f"({len(pa)} vs {len(pb)})")
    if len(pa) == len(pb):
        m = max(abs(x - y) for u, v in zip(pa, pb)
                for x, y in zip(u["xyz"], v["xyz"]))
        print(f"max |delta p|                  : {m:.3e}")
    print("support identical              :", sa == sb)


main()
