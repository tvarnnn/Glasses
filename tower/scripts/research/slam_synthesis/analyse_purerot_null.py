"""TENSION 1, resolved: run Lane 3's validity gate against Lane 2's null.

Input: mast3r_purerot_null.json -- MASt3R run through Lane 3's own harness
(`slam_learned_3d/mast3r_pairs.py`, unmodified) on pairs built by
`build_rotation_null_manifest.py`, where the TRUE relative translation is
EXACTLY ZERO by construction.

Lane 3's proposed gate:      recip_R < 15 deg  AND  E_inlier_ratio > 0.5
Candidate repaired gate:     ... AND recip_t_dir < 15 deg

Every acceptance is a FALSE POSITIVE. There is no ground-truth ambiguity here:
the second image is a homography warp of the first about the camera centre.

For comparison the script also scores Lane 3's own measured positives
(mast3r_undist.json / mast3r_analysed.json) through the same gates, so the
cost of the repaired gate in recall is priced rather than asserted.
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent

RECIP_R_MAX = 15.0
E_RATIO_MIN = 0.5
RECIP_T_MAX = 15.0


def gates(r):
    rr = r.get("recip_rot_deg")
    rt = r.get("recip_trans_dir_deg")
    er = max(r["fwd"].get("E_inlier_ratio", 0.0), 0.0)
    lane3 = (rr is not None and rr < RECIP_R_MAX and er > E_RATIO_MIN)
    repaired = lane3 and (rt is not None and rt < RECIP_T_MAX)
    return lane3, repaired, rr, rt, er


def summarise(rows, label, false_by_construction):
    n = len(rows)
    a3 = r3 = 0
    rrs, rts, ers = [], [], []
    for r in rows:
        l3, rep, rr, rt, er = gates(r)
        a3 += l3
        r3 += rep
        if rr is not None:
            rrs.append(rr)
        if rt is not None:
            rts.append(rt)
        ers.append(er)
    d = {
        "label": label,
        "n_pairs": n,
        "lane3_gate_accepts": a3,
        "lane3_gate_accept_pct": round(100 * a3 / n, 2) if n else None,
        "repaired_gate_accepts": r3,
        "repaired_gate_accept_pct": round(100 * r3 / n, 2) if n else None,
        "median_recip_R_deg": round(st.median(rrs), 3) if rrs else None,
        "pct_recip_R_under_15": round(100 * sum(1 for x in rrs if x < 15) / n, 2) if n else None,
        "median_recip_tdir_deg": round(st.median(rts), 2) if rts else None,
        "pct_recip_tdir_under_15": round(100 * sum(1 for x in rts if x < 15) / n, 2) if n else None,
        "median_E_inlier_ratio": round(st.median(ers), 3) if ers else None,
        "pct_E_ratio_over_0.5": round(100 * sum(1 for x in ers if x > 0.5) / n, 2) if n else None,
    }
    if false_by_construction:
        d["ALL ACCEPTANCES ARE FALSE POSITIVES"] = True
    return d


def main():
    scratch = Path(json.load(open(HERE / "paths.json"))["scratch"])
    null = json.load(open(scratch / "mast3r_purerot_null.json"))

    out = {"gate": {"recip_R_deg<": RECIP_R_MAX, "E_inlier_ratio>": E_RATIO_MIN,
                    "repaired adds recip_t_dir_deg<": RECIP_T_MAX},
           "groups": []}

    out["groups"].append(summarise(null, "ALL pure-rotation nulls (true t = 0)", True))
    by_angle = {}
    for r in null:
        by_angle.setdefault(r["kind"], []).append(r)
    for k in sorted(by_angle, key=lambda s: float(s.rsplit("_", 1)[1])):
        out["groups"].append(summarise(by_angle[k], k + "  (true t = 0)", True))

    # Lane 3's own positives, scored through the same code.
    for name, path, kinds in (
        ("Lane 3 undistorted rerun (10 real pairs)",
         RESEARCH / "slam_learned_3d/results/mast3r_undist.json", None),
        ("Lane 3 hard negatives (6, different place)",
         RESEARCH / "slam_learned_3d/results/mast3r_hardneg.json", None),
    ):
        if path.exists():
            rows = json.load(open(path))
            if kinds:
                rows = [r for r in rows if r["kind"] in kinds]
            out["groups"].append(summarise(rows, name, False))

    # Lane 3's own real pure_rotation group, for contrast with the constructed one
    an = json.load(open(RESEARCH / "slam_learned_3d/results/mast3r_analysed.json"))
    pr = [r for r in an if r["kind"] == "purerot"]
    if pr:
        out["groups"].append(summarise(pr, "Lane 3's own 'purerot' group (real frames)", False))
    pos = [r for r in an if r["kind"] in ("oracle", "blind")]
    out["groups"].append(summarise(pos, "Lane 3 oracle+blind (raw, its positives)", False))

    print(json.dumps(out, indent=1))
    (HERE / "purerot_null_gate.json").write_text(json.dumps(out, indent=1))

    # per-pair dump of every null the Lane 3 gate accepted
    bad = []
    for r in null:
        l3, rep, rr, rt, er = gates(r)
        if l3:
            bad.append({"name": r["name"], "true_rot_deg": float(r["kind"].rsplit("_", 1)[1]),
                        "recip_R": round(rr, 3), "E_ratio": round(er, 3),
                        "recip_tdir": None if rt is None else round(rt, 2),
                        "matches": r["fwd"]["n_matches"],
                        "E_inliers": r["fwd"]["E_inliers"],
                        "median_parallax_px": r["fwd"].get("median_parallax_px"),
                        "repaired_gate_still_accepts": rep})
    (HERE / "purerot_null_false_positives.json").write_text(json.dumps(bad, indent=1))
    print(f"\n{len(bad)} false positives written to purerot_null_false_positives.json")
    still = [b for b in bad if b["repaired_gate_still_accepts"]]
    print(f"{len(still)} survive the translation-aware gate:")
    for b in still[:20]:
        print(" ", b)


if __name__ == "__main__":
    main()
