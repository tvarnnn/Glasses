#!/usr/bin/env python3
"""Compare the contract identifiers this iOS build implements against the
identifiers a live Tower actually serves.

Why this exists
---------------
Every contract fixture in `GlassesTests` was captured by hand, off a Tower
that was running at the time. Nothing re-checks them. If a Windows lane
publishes `world_builder.status/2026-09-01`, this build keeps passing 388
green tests against the old bytes and only finds out on a device, in a room,
with the glasses on.

This script is the check that was missing. It reads the identifiers out of
the Swift source (so it cannot drift from the source the way a second list
would) and asks a live Tower what it serves.

Exit codes: 0 agreement, 1 drift, 2 Tower unreachable.

    ./scripts/contract-drift-check.py [--tower http://host:port]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

SWIFT_ROOT = pathlib.Path(__file__).resolve().parent.parent / "Glasses"
IDENTIFIER = re.compile(r'"([a-z_]+\.[a-z_]+/20\d{2}-\d{2}-\d{2})"')
ENVELOPE = re.compile(r'"(cartridge_results\.envelope/20\d{2}-\d{2}-\d{2})"')


def implemented() -> dict[str, str]:
    """Identifier -> the Swift file:line that declares it."""
    found: dict[str, str] = {}
    for path in sorted(SWIFT_ROOT.rglob("*.swift")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in list(IDENTIFIER.finditer(line)) + list(ENVELOPE.finditer(line)):
                found.setdefault(
                    match.group(1), f"{path.relative_to(SWIFT_ROOT.parent)}:{number}"
                )
    return found


def fetch(tower: str, path: str) -> tuple[int, object]:
    request = urllib.request.Request(tower.rstrip("/") + path)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except Exception:
            return error.code, None


def served(tower: str) -> tuple[dict[str, str], list[dict]]:
    """Identifier -> where the Tower stated it, plus the not_offered list."""
    status, body = fetch(tower, "/cartridges")
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"/cartridges answered {status}")

    live: dict[str, str] = {}
    if envelope := body.get("envelope_contract"):
        live[envelope] = "/cartridges envelope_contract"
    for offer in body.get("cartridges", []):
        if contract := offer.get("contract"):
            live[contract] = f"/cartridges {offer.get('cartridge')}/{offer.get('result_type')}"

    # Object Memory is never declared over the socket: its contract travels in
    # the body of an answer, so the only way to learn it is to ask.
    status, body = fetch(tower, "/object-memory/observations")
    if status == 200 and isinstance(body, dict) and (contract := body.get("contract")):
        live[contract] = "/object-memory/observations"
    elif status == 404:
        live["<object-memory: no root configured>"] = f"/object-memory/observations 404"

    return live, body.get("not_offered", []) if isinstance(body, dict) else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tower", default="http://100.110.156.55:8000")
    args = parser.parse_args()

    build = implemented()
    print(f"Tower: {args.tower}\n")

    print("Implemented by this build:")
    for identifier, where in sorted(build.items()):
        print(f"  {identifier:<45} {where}")

    try:
        live, not_offered = served(args.tower)
    except Exception as error:
        print(f"\nTOWER UNREACHABLE: {error}", file=sys.stderr)
        return 2

    print("\nServed by the live Tower:")
    for identifier, where in sorted(live.items()):
        print(f"  {identifier:<45} {where}")

    # Only identifiers the Tower actually stated can drift. A contract this
    # build implements but the Tower does not currently offer is not drift:
    # geometry is fetched per-world over HTTP and is absent until a world
    # exists, and Object Memory's is absent until a root is configured.
    unreadable = {i: w for i, w in live.items() if not i.startswith("<") and i not in build}

    print()
    if not_offered:
        print("Tower is deliberately not offering:")
        for entry in not_offered:
            print(f"  {entry.get('cartridge')}: {entry.get('reason', '')[:100]}")
        print()

    if unreadable:
        print("DRIFT — the Tower serves contracts this build cannot read:")
        for identifier, where in sorted(unreadable.items()):
            print(f"  {identifier:<45} {where}")
        return 1

    print("AGREEMENT — every contract the Tower stated is implemented by this build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
