#!/usr/bin/env python3
"""A structural sanity check for Swift sources on a host with no toolchain.

This is NOT a compiler and must never be reported as one. It exists because
half of this repository is developed on a Windows host with no Swift
toolchain -- swift, swiftc, xcodebuild, SwiftLint and swift-format are all
absent -- so a scripted edit to a .swift file there is otherwise completely
unchecked until it reaches a Mac.

What it can prove: brackets balance, and every string and comment is
terminated. What it CANNOT prove: anything about types, actors,
availability, protocol conformance, or whether the file compiles. A green
run here is not a build and must never be reported as one. It walks the file
as a character stream, tracking line comments, block comments (nested, as
Swift allows), plain strings, multi-line strings and escapes, and then checks
that brackets balance outside all of those. It catches exactly the class of
damage a scripted edit does: an unterminated string, a triple-quote that
lost its closing pair, a stray brace.
"""

import sys
from pathlib import Path

OPEN = {"(": ")", "[": "]", "{": "}"}
CLOSE = {v: k for k, v in OPEN.items()}


def check(path: Path):
    src = path.read_text(encoding="utf-8")
    i, n = 0, len(src)
    line = 1
    stack = []
    problems = []
    block_depth = 0

    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
            continue

        if block_depth:
            if src.startswith("/*", i):
                block_depth += 1
                i += 2
                continue
            if src.startswith("*/", i):
                block_depth -= 1
                i += 2
                continue
            i += 1
            continue

        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue

        if src.startswith("/*", i):
            block_depth = 1
            i += 2
            continue

        if src.startswith('"""', i):
            j = src.find('"""', i + 3)
            while j != -1 and src[j - 1] == "\\":
                j = src.find('"""', j + 3)
            if j == -1:
                problems.append(f"{path.name}:{line}: unterminated multi-line string")
                break
            line += src.count("\n", i, j)
            i = j + 3
            continue

        if ch == '"':
            j = i + 1
            closed = False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "\n":
                    break
                if src[j] == '"':
                    closed = True
                    break
                j += 1
            if not closed:
                problems.append(f"{path.name}:{line}: unterminated string literal")
                break
            i = j + 1
            continue

        if ch in OPEN:
            stack.append((ch, line))
            i += 1
            continue
        if ch in CLOSE:
            if not stack:
                problems.append(f"{path.name}:{line}: unmatched closing {ch!r}")
                break
            opened, opened_line = stack.pop()
            if OPEN[opened] != ch:
                problems.append(
                    f"{path.name}:{line}: closing {ch!r} does not match "
                    f"{opened!r} opened on line {opened_line}"
                )
                break
            i += 1
            continue
        i += 1

    if block_depth:
        problems.append(f"{path.name}: unterminated block comment")
    for opened, opened_line in stack:
        problems.append(
            f"{path.name}:{opened_line}: {opened!r} was never closed"
        )
    return problems


def main(argv):
    failures = []
    for arg in argv:
        path = Path(arg)
        found = check(path)
        status = "ok" if not found else "PROBLEMS"
        print(f"{status:9s} {path}")
        failures.extend(found)
    for problem in failures:
        print("  " + problem)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
