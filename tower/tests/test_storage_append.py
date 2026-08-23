"""Appending a record must not compound an interrupted write.

Found while testing Document Memory's store, but the defect was in shared
infrastructure and every journal in the project inherits the fix: World
Builder's keyframes, edges and events, the capture recorder's frame
journal, and Object Memory's observations.
"""

import json

from tower.storage import append_jsonl, read_raw_jsonl


def test_a_record_appended_after_a_torn_line_survives(tmp_path):
    """ONE crash must destroy ONE record, not two.

    An interrupted write leaves a partial line with no trailing newline.
    A plain append glues the next record onto the end of it, so the fused
    line is dropped as corrupt and the SECOND record -- which was written
    perfectly -- is lost with it.
    """
    path = tmp_path / "journal.jsonl"
    append_jsonl(path, {"n": 1})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"n": 2, "tor')  # interrupted: no newline

    append_jsonl(path, {"n": 3})

    records, corrupt = read_raw_jsonl(path)

    assert [record["n"] for record in records] == [1, 3]
    assert corrupt == 1, "exactly the torn line, and only it"


def test_an_intact_journal_gains_no_blank_lines(tmp_path):
    """The healing must not fire when nothing is torn."""
    path = tmp_path / "journal.jsonl"
    for n in range(5):
        append_jsonl(path, {"n": n})

    raw = path.read_text(encoding="utf-8")

    assert raw.count("\n\n") == 0
    assert len(raw.strip().splitlines()) == 5
    records, corrupt = read_raw_jsonl(path)
    assert [record["n"] for record in records] == [0, 1, 2, 3, 4]
    assert corrupt == 0


def test_the_first_append_creates_the_file_without_a_leading_newline(tmp_path):
    path = tmp_path / "nested" / "journal.jsonl"

    append_jsonl(path, {"n": 0})

    assert path.read_text(encoding="utf-8") == json.dumps({"n": 0}) + "\n"


def test_appending_to_an_empty_existing_file_adds_no_newline(tmp_path):
    path = tmp_path / "journal.jsonl"
    path.write_text("", encoding="utf-8")

    append_jsonl(path, {"n": 1})

    assert not path.read_text(encoding="utf-8").startswith("\n")
