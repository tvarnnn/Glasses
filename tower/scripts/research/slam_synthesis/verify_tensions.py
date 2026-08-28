"""Independent re-analysis of the lane artefacts for the synthesis review.

Nothing here re-runs a lane. It re-reads the JSON the lanes produced and asks
questions the lanes did not ask of their own data.

T2  Is Lane 1's "distant edges carry more parallax" measured on the same
    population as the multi-cue lane's "54.7% of failing pairs are
    baseline-limited"? Lane 1 reported parallax CONDITIONAL ON BEING AN EDGE
    (>=15 F-inliers). The 54.7% was over ALL consecutive pairs that production
    tried. Those are different denominators; this recomputes Lane 1's numbers
    over the unconditional denominator so the two can be compared.

T1b Lane 1's parallax is `median_triangulation_angle_deg` computed from
    cv2.recoverPose -- the SAME estimator Lane 2 proved fabricates translation
    under pure rotation. This prices the contamination floor by reading Lane 2's
    own zero-baseline null and asking what that estimator reports when the true
    answer is exactly 0.

T5  Are Lane 1's and Lane 2's covisibility measurements methodologically
    independent? Recomputed here on a common axis (keyframe gap) so the two can
    be laid side by side.

Read-only. Writes one JSON summary.
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
TOWER = HERE.parents[2]

MIN_INLIERS = 15
MIN_TRI = 0.5


def pct(a, b):
    return 0.0 if b == 0 else 100.0 * a / b


def main():
    out = {}

    # ---------------- T2: conditional vs unconditional denominators -------
    cen = json.load(open(RESEARCH / "slam_classical/covisibility_census.json"))
    seg = cen["meta"]["segment_index"]
    pairs = cen["pairs"]

    def bucket(i, j):
        gap = abs(j - i)
        if gap == 1:
            return "consecutive"
        if gap <= 5:
            return "gap2_5"
        if gap <= 20:
            return "gap6_20"
        if gap <= 100:
            return "gap21_100"
        return "gap>100"

    rows = {}
    for p in pairs:
        b = bucket(p["i"], p["j"])
        cross = seg[p["i"]] != seg[p["j"]]
        for key in (b, "cross_segment" if cross else "same_segment", "ALL"):
            r = rows.setdefault(key, {"n": 0, "edge": 0, "useful": 0, "tri": []})
            r["n"] += 1
            if p["f_inliers"] >= MIN_INLIERS:
                r["edge"] += 1
                t = p.get("tri_angle")
                if t is not None:
                    r["tri"].append(t)
                    if t >= MIN_TRI:
                        r["useful"] += 1

    t2 = {}
    for k, r in rows.items():
        t2[k] = {
            "n_pairs": r["n"],
            "n_edges": r["edge"],
            "pct_pairs_that_are_edges": round(pct(r["edge"], r["n"]), 2),
            "median_tri_given_edge": round(st.median(r["tri"]), 3) if r["tri"] else None,
            "pct_edges_with_parallax_ge_0.5": round(pct(r["useful"], r["edge"]), 2),
            # THE UNCONDITIONAL NUMBER -- comparable to the 54.7% denominator
            "pct_ALL_pairs_that_are_useful_edges": round(pct(r["useful"], r["n"]), 3),
        }
    out["T2_population_check"] = t2

    # ---------------- T1b: what the same estimator says at TRUE zero -------
    null = json.load(open(RESEARCH / "slam_learned_vo/rotation_null.json"))["rows"]
    t1b = {}
    for m in ("orb", "loftr", "disk_lg"):
        tri = sorted(r[m]["tri"] for r in null if r[m].get("tri") is not None)
        inl = [r[m]["inliers"] for r in null if r[m].get("inliers") is not None]
        rerr = [r[m]["rot_err_deg"] for r in null if r[m].get("rot_err_deg") is not None]
        t1b[m] = {
            "n": len(tri),
            "true_tri_angle_deg": 0.0,
            "estimated_tri_median": round(st.median(tri), 4),
            "estimated_tri_p75": round(tri[int(0.75 * len(tri))], 4),
            "estimated_tri_p90": round(tri[int(0.90 * len(tri))], 4),
            "estimated_tri_max": round(tri[-1], 2),
            "pct_estimated_ge_0.5deg_FALSE_POSITIVE": round(
                pct(sum(1 for t in tri if t >= MIN_TRI), len(tri)), 2),
            "pct_pairs_clearing_MIN_INLIERS_15": round(
                pct(sum(1 for i in inl if i >= MIN_INLIERS), len(inl)), 2),
            "median_rotation_error_deg": round(st.median(rerr), 4),
        }
    out["T1b_zero_baseline_behaviour_of_lane1s_estimator"] = t1b

    # ---------------- T5: the two covisibility measurements side by side ---
    covis_orb = json.load(open(RESEARCH / "slam_learned_vo/covisibility_orb.json"))
    out["T5_lane2_covisibility_keys"] = (
        list(covis_orb.keys()) if isinstance(covis_orb, dict) else "list")

    print(json.dumps(out, indent=1))
    (HERE / "verify_tensions.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
