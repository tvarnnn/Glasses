"""ADVERSARIAL: does Tension 4's finding survive the re-baseline?

The synthesis measures redaction-vs-features on the STALE 457-keyframe session
that the same document declares stale. Stage 2's admission gate will be built
against HEAD. Re-measure on the HEAD replay's 448 keyframes.
"""
import json, statistics as st, sys
from pathlib import Path
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tower.world_builder.geometry import detect_and_describe

root = Path(sys.argv[1])
w = next((root / "worlds").iterdir())
sess = next((w / "sessions").iterdir())
imgs = sorted((sess / "images").glob("*.jpg"))
rows = []
for p in imgs:
    g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    kp, _ = detect_and_describe(g)
    rows.append((float((g <= 2).mean()), len(kp), p.name))
print(f"n={len(rows)}")
starved = [r for r in rows if r[1] <= 100]
print(f"keyframes with <=100 ORB features : {len(starved)}")
over40 = [r for r in starved if r[0] > 0.40]
print(f"  of which >40% black fill        : {len(over40)}")
if starved:
    print(f"  median black fraction of starved: {st.median([r[0] for r in starved]):.3f}")
print(f"keyframes >10% black              : {sum(1 for r in rows if r[0] > 0.10)} "
      f"= {100*sum(1 for r in rows if r[0] > 0.10)/len(rows):.1f}%")
print(f"keyframes >60% black              : {sum(1 for r in rows if r[0] > 0.60)}")
for r in sorted(starved):
    print(f"   {r[2]}  black={r[0]:.3f}  orb={r[1]}")
