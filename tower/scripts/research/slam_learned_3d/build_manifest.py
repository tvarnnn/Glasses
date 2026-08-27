"""Build the pair manifest for the learned-3D lane.

Four groups, deliberately:
  oracle    -- segment pairs the CLASSICAL pipeline registered (4<->5, 5<->32)
  blind     -- segment pairs with strong image evidence and ZERO classical
               geometry (segment 0 has no triangulated point at all)
  purerot   -- consecutive keyframes inside a segment whose stored degeneracy
               is pure_rotation
  negative  -- (a) segment pairs with ZERO verified ORB inliers in-session
               (b) frames from a DIFFERENT capture entirely
"""
from __future__ import annotations
import json, random, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORLD = ROOT / "data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4"
SESSION = "dd5d13a2381e430db9b27c7da2cf2928"
IMAGES = WORLD / "sessions" / SESSION / "images"
POSES = WORLD / "derived" / SESSION / "poses.json"
CAPTURES = ROOT / "data/captures"

pairs_json = json.load(open(sys.argv[1]))
out_path = Path(sys.argv[2])

rows = json.load(open(POSES))["poses"]
seg_kfs = defaultdict(list)
degen = {}
for r in rows:
    stem = r["keyframe_id"].split(":")[1]
    seg_kfs[r["segment_index"]].append(stem)
    degen[stem] = (r["status"], r["degeneracy"])

best = pairs_json["segment_pair_best"]
GEOM = {1, 4, 5, 6, 8, 12, 19, 21, 23, 24, 30, 31, 32, 37, 41, 43, 46, 48, 50}


def img(stem):
    return str(IMAGES / (stem + ".jpg"))


jobs = []


def add(kind, name, a, b, orb=None):
    jobs.append({"kind": kind, "name": name, "a": img(a) if len(a) == 8 else a,
                 "b": img(b) if len(b) == 8 else b, "orb_inliers": orb})


# --- oracle: classically registered segment pairs -------------------------
for sa, sb in [(4, 5), (5, 32)]:
    e = best.get(str(sa) + "_" + str(sb)) or best.get(str(sb) + "_" + str(sa))
    add("oracle", "seg{}-{}".format(sa, sb), e["kf_a"], e["kf_b"], e["inliers"])

# --- blind: strong image evidence, zero classical geometry ----------------
blind = []
for k, v in best.items():
    sa, sb = (int(x) for x in k.split("_"))
    if v["inliers"] >= 60 and (sa not in GEOM or sb not in GEOM) and abs(sa - sb) > 1:
        blind.append((v["inliers"], sa, sb, v))
blind.sort(reverse=True, key=lambda x: x[0])
for inl, sa, sb, v in blind[:10]:
    add("blind", "seg{}-{}".format(sa, sb), v["kf_a"], v["kf_b"], inl)

# --- purerot: consecutive keyframes flagged pure_rotation -----------------
n = 0
for s, kfs in sorted(seg_kfs.items()):
    for i in range(len(kfs) - 1):
        a, b = kfs[i], kfs[i + 1]
        if degen[b][1] == "pure_rotation" and n < 6:
            add("purerot", "seg{}-{}".format(s, i), a, b, None)
            n += 1

# --- negative (a): in-session, zero verified ORB inliers ------------------
rng = random.Random(20260826)
zeros = [k for k, v in best.items() if v["inliers"] == 0]
# pick zero-inlier pairs that are far apart in time, from geometry segments
zpick = []
for k in zeros:
    sa, sb = (int(x) for x in k.split("_"))
    if abs(sa - sb) >= 15 and sa in GEOM and sb in GEOM:
        zpick.append((sa, sb))
rng.shuffle(zpick)
for sa, sb in zpick[:8]:
    add("neg_insess", "seg{}-{}".format(sa, sb), seg_kfs[sa][0], seg_kfs[sb][0], 0)

# --- negative (b): different capture entirely -----------------------------
others = ["20ce3c2366ee4cdfb46cb8db09578058", "b35d8ab85c364b9da44499d2a7f00638",
          "2e6cffa275b24b7d87d68ec1d6a6cfdf", "ab10cb203cf048e58cf2f79a120a54a4",
          "5387a76568e84e13936862f612f8bc81", "e1c52b9ff7f84dd5a54fee6150b7f854"]
mine = [seg_kfs[s][0] for s in (0, 19, 32, 45, 46, 50)]
for i, cid in enumerate(others):
    fr = sorted((CAPTURES / cid / "frames").glob("*.jpg"))
    if not fr:
        continue
    other = str(fr[len(fr) // 2])
    add("neg_xcap", "xcap{}".format(i), mine[i % len(mine)], other, None)

out_path.write_text(json.dumps(jobs, indent=1))
print("wrote", out_path, len(jobs), "pairs")
for j in jobs:
    print("  ", j["kind"], j["name"], j["orb_inliers"])
