"""Adversarial verification of storage.write_json_atomic's dumps-then-write.

Attacks: byte-identity across hostile payload shapes, the materialisation
cost at scale, and whether anything observes a partial write.
"""
import io
import json
import time
import tracemalloc

print("=" * 70)
print("A. Byte-identity: json.dump(obj, f) vs f.write(json.dumps(obj))")
print("=" * 70)

CONTROLS = chr(0) + chr(1) + chr(31) + chr(127) + " control"

payloads = {
    "unicode + emoji + controls": {
        "a": "é中文\U0001f600",
        "b": "line\nbreak\ttab",
        "c": "quote\"back\\slash",
        "d": CONTROLS,
        "e": "😀 astral-as-pair",
    },
    "deep nesting x400": None,
    "float repr round-trip": {
        "f": [0.1, 1e-7, 1e16, 1e-300, 5e-324, 1.7976931348623157e308,
              -0.0, 0.30000000000000004, 1 / 3, 2 ** -53],
    },
    "ints beyond 2^53": {
        "i": [2 ** 53, 2 ** 53 + 1, 2 ** 63, 2 ** 64, -(2 ** 70), 10 ** 40],
    },
    "None / bools / empties": {
        "n": None, "t": True, "f": False, "e": {}, "l": [], "s": "",
    },
    "non-finite (NaN/Inf)": {"x": [float("nan"), float("inf"), float("-inf")]},
    "dict key coercion": {"1": "str", "nested": {"2.5": None}},
    "long string 2MB": {"s": "x" * 2_000_000},
}
deep = cur = {}
for _ in range(400):
    cur["n"] = {}
    cur = cur["n"]
cur["leaf"] = 1
payloads["deep nesting x400"] = deep

for name, payload in payloads.items():
    try:
        b1 = io.StringIO()
        json.dump(payload, b1)
        old = b1.getvalue()
    except Exception as e:
        old = f"{type(e).__name__}: {str(e)[:60]}"
    try:
        new = json.dumps(payload)
    except Exception as e:
        new = f"{type(e).__name__}: {str(e)[:60]}"
    same = old == new
    print(f"  [{'IDENTICAL' if same else 'DIFFERENT'}] {name}"
          f"  (len={len(old)})")
    if not same:
        print(f"      old={old[:200]!r}")
        print(f"      new={new[:200]!r}")

print()
print("  Recursion limit -- both share the same encoder, so a payload deep")
print("  enough to blow the stack must fail IDENTICALLY:")
d2 = c2 = {}
for _ in range(100_000):
    c2["n"] = {}
    c2 = c2["n"]
for label, fn in (("dump ", lambda: json.dump(d2, io.StringIO())),
                  ("dumps", lambda: json.dumps(d2))):
    try:
        fn()
        print(f"    {label}: OK")
    except Exception as e:
        print(f"    {label}: {type(e).__name__}")

print("=" * 70)
print("B. Materialisation cost -- peak Python memory, dump vs dumps")
print("=" * 70)


def points_payload(n):
    return {"points": [
        {"id": i, "xyz": [i * 0.001, i * 0.002, i * 0.003],
         "rgb": [i % 256, (i * 3) % 256, (i * 7) % 256], "obs": i % 9}
        for i in range(n)]}


for n, label in ((75_000, "~corpus points (75k)"), (750_000, "10x (750k)")):
    p = points_payload(n)
    size = len(json.dumps(p))
    for kind in ("dump", "dumps"):
        tracemalloc.start()
        t0 = time.perf_counter()
        buf = io.StringIO()
        if kind == "dump":
            json.dump(p, buf)
        else:
            buf.write(json.dumps(p))
        dt = time.perf_counter() - t0
        _cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f"  {label:<22} {kind:<6} {size / 1e6:6.2f} MB doc  "
              f"{dt * 1000:8.2f} ms  peak-traced {peak / 1e6:8.2f} MB")
    del p
