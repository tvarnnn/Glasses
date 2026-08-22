"""The two drivers, run as a user runs them: separate process, cold start.

The query CLI is deliberately independent of any voice path. A future Siri
shortcut or custom wake word would sit ABOVE this; none is required for
the feature to work, and building the voice layer first would have made
the memory untestable.

`--ocr none` throughout: these tests are about the drivers, not about OCR
accuracy, and a suite that downloaded a model would fail on a train.
"""

import json
import subprocess
import sys

import pytest

from tower.document_memory.store import DocumentStore


def _run(script, *args):
    return subprocess.run(
        [sys.executable, f"scripts/{script}", *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def populated(tmp_path):
    """A store with two observed documents, produced by the real driver."""
    root = tmp_path / "memory"
    result = _run(
        "document_memory_session.py",
        "--synthetic",
        "--ocr",
        "none",
        "--root",
        str(root),
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    return root, json.loads(result.stdout)


class TestSessionDriver:
    def test_help_exits_zero(self):
        assert _run("document_memory_session.py", "--help").returncode == 0

    def test_it_requires_exactly_one_frame_source(self, tmp_path):
        assert _run("document_memory_session.py").returncode != 0
        assert (
            _run(
                "document_memory_session.py",
                "--synthetic",
                "--frames",
                str(tmp_path),
            ).returncode
            != 0
        )

    def test_a_missing_capture_directory_exits_nonzero(self, tmp_path):
        result = _run(
            "document_memory_session.py",
            "--follow-capture",
            str(tmp_path / "absent"),
        )

        assert result.returncode != 0

    def test_a_synthetic_run_observes_the_two_rendered_documents(self, populated):
        _, report = populated

        assert report["documents_observed"] == 2
        assert report["stored_documents"] == 2
        assert report["frames_observed"] > 20

    def test_it_reports_that_its_timing_was_assumed(self, populated):
        """A synthetic source has no timestamps. Saying so is the point."""
        _, report = populated

        assert report["timing_source"] == "assumed-interval"
        assert report["assumed_frame_interval_s"] > 0

    def test_page_images_are_off_by_default(self, populated):
        root, report = populated

        assert report["keep_page_images"] is False
        assert report["bytes"]["images"] == 0
        assert not (root / "pages").exists()

    def test_the_text_output_refuses_to_say_read(self, tmp_path):
        """The camera cannot establish attention, and the CLI must not imply it."""
        result = _run(
            "document_memory_session.py",
            "--synthetic",
            "--ocr",
            "none",
            "--root",
            str(tmp_path / "m"),
        )

        assert "OBSERVED, NOT READ" in result.stdout

    def test_a_zero_assumed_fps_is_rejected(self, tmp_path):
        result = _run(
            "document_memory_session.py",
            "--synthetic",
            "--ocr",
            "none",
            "--root",
            str(tmp_path / "m"),
            "--assumed-fps",
            "0",
        )

        assert result.returncode != 0


class TestQueryCli:
    def test_help_exits_zero(self):
        assert _run("document_query.py", "--help").returncode == 0

    def test_it_requires_exactly_one_question(self, tmp_path):
        assert _run("document_query.py", "--root", str(tmp_path)).returncode != 0
        assert (
            _run(
                "document_query.py",
                "--root",
                str(tmp_path),
                "--recent",
                "3",
                "--text",
                "x",
            ).returncode
            != 0
        )

    def test_recent_lists_what_was_observed(self, populated):
        root, _ = populated

        result = _run("document_query.py", "--root", str(root), "--recent", "5")

        assert result.returncode == 0
        assert "OBSERVED, NOT READ" in result.stdout

    def test_recent_json_carries_the_full_records(self, populated):
        root, _ = populated

        result = _run(
            "document_query.py", "--root", str(root), "--recent", "5", "--format", "json"
        )
        payload = json.loads(result.stdout)

        assert payload["count"] == 2
        assert payload["documents"][0]["time_basis"] == "tower-receipt"

    def test_an_empty_store_exits_nonzero_and_says_it_is_about_the_record(
        self, tmp_path
    ):
        result = _run(
            "document_query.py", "--root", str(tmp_path / "empty"), "--recent", "5"
        )

        assert result.returncode == 1
        assert "No record" in result.stdout
        assert "not about the world" in result.stdout

    def test_a_search_that_finds_nothing_exits_nonzero(self, populated):
        root, _ = populated

        result = _run(
            "document_query.py", "--root", str(root), "--text", "fire extinguisher"
        )

        assert result.returncode == 1
        assert "No record" in result.stdout

    def test_coverage_of_an_unknown_document_exits_two(self, populated):
        root, _ = populated

        result = _run("document_query.py", "--root", str(root), "--coverage", "nope")

        assert result.returncode == 2

    def test_coverage_refuses_to_invent_a_page_total(self, populated):
        root, report = populated

        result = _run(
            "document_query.py",
            "--root",
            str(root),
            "--coverage",
            report["document_ids"][0],
            "--format",
            "json",
        )
        coverage = json.loads(result.stdout)

        assert coverage["pages_total"] is None

    def test_minutes_ago_finds_a_recent_document(self, populated):
        root, _ = populated

        result = _run(
            "document_query.py",
            "--root",
            str(root),
            "--minutes-ago",
            "0",
            "--window",
            "60",
        )

        assert result.returncode == 0


class TestPurgeThroughTheCli:
    def test_purge_all_really_empties_the_store(self, populated):
        root, _ = populated
        assert DocumentStore(root).count() == 2

        result = _run("document_query.py", "--root", str(root), "--purge-all")

        assert result.returncode == 0
        assert DocumentStore(root).count() == 0

    def test_purging_one_document_leaves_the_other(self, populated):
        root, report = populated

        result = _run(
            "document_query.py",
            "--root",
            str(root),
            "--purge",
            report["document_ids"][0],
        )

        assert result.returncode == 0
        assert DocumentStore(root).count() == 1

    def test_purge_reports_completeness(self, populated):
        root, _ = populated

        result = _run(
            "document_query.py",
            "--root",
            str(root),
            "--purge-all",
            "--format",
            "json",
        )

        assert json.loads(result.stdout)["complete"] is True
