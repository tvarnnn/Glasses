"""Filesystem primitives shared by every module that persists to disk.

Extracted once a second module needed them. Both object memory and World
Builder had independently converged on the same three operations, and the
capture recorder -- which is shared transport infrastructure -- was
importing them from inside a cartridge.

The atomic-write pattern in particular is not incidental: the try/finally
exists because a failure mid-write once left a temp file holding a live
copy of data that nothing read, pruned, or deleted. That defect shipped
before it was fixed, which is why it lives in one place now.
"""

import json
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

TEMP_SUFFIX = ".tmp"


def new_id() -> str:
    """Mint an opaque identifier.

    uuid4 hex, never derived from a display name (users rename things) and
    never a content hash (refinement changes content). Anything that
    references an id must survive both.
    """
    return uuid.uuid4().hex


def write_json_atomic(path: Path, payload: dict) -> None:
    """Replace `path` atomically, leaving no temp file behind either way."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + TEMP_SUFFIX)
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def read_json_closed(path: Path) -> dict:
    """Read and parse with the handle closed before parsing.

    Windows cannot os.replace onto an open destination (verified:
    WinError 5), so a reader holding a handle across other work can block
    a writer. Closing first makes that structurally impossible.
    """
    with path.open("r", encoding="utf-8") as handle:
        text = handle.read()
    return json.loads(text)


def append_jsonl(path: Path, payload: dict) -> None:
    """Append one record, and heal a torn line rather than compounding it.

    The newline check is not defensive noise. An interrupted write leaves a
    partial line with NO trailing newline, and a plain append then glues
    the next record onto the end of it -- so ONE crash destroys TWO
    records: the torn one, which is expected, and the next good one, which
    is not. `read_raw_jsonl` drops the fused line as corrupt, and the
    caller never learns the second record existed.

    Starting the new record on its own line confines the damage to the
    write that was actually interrupted. Two opens instead of one; an
    append is never the hot loop in this codebase, since even the capture
    recorder does one per delivered frame.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            needs_newline = handle.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        handle.write(json.dumps(payload) + "\n")


def read_raw_jsonl(path: Path) -> tuple[list[dict], int]:
    """Parse a journal, counting genuinely-corrupt lines separately.

    A line that is not valid JSON is corruption. A well-formed line whose
    fields the caller's schema cannot interpret is NOT corruption, and
    callers treat the two differently. A torn final line from an
    interrupted write lands in the first category and is skipped without
    touching the file.
    """
    if not path.exists():
        return [], 0
    raw_records: list[dict] = []
    corrupt = 0
    # errors="replace" rather than the default strict: a write interrupted
    # mid-codepoint leaves an invalid byte sequence, and a UnicodeDecodeError
    # raised from the file iterator would take out the WHOLE journal rather
    # than the one torn line -- exactly the failure this function promises
    # not to have. Not reachable through this module's own writes today
    # (json.dumps defaults to ensure_ascii, so every byte written is ASCII
    # and a tear can only fall on a character boundary), but the promise
    # should not depend on that staying true.
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw_records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("skipping corrupt line at %s:%s", path, line_number)
                corrupt += 1
    return raw_records, corrupt
