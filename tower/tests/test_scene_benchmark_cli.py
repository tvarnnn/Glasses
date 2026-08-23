"""The benchmark's CLI contract.

`--no-models` throughout: the point is that the driver works and emits a
valid document, not that the models are fast. The model numbers are in
the report, produced by a run an operator does deliberately.
"""

import json
import subprocess
import sys


def _run(*args):
    return subprocess.run(
        [sys.executable, "scripts/scene_benchmark.py", *args],
        capture_output=True,
        text=True,
    )


def test_help_exits_zero():
    assert _run("--help").returncode == 0


def test_json_output_is_a_document_and_nothing_else():
    result = _run("--no-models", "--format", "json", "--repeat", "3")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert "SYNTHETIC" in report["note"]


def test_it_measures_count_stability_under_dropout():
    """The brief's requirement, measured rather than asserted."""
    report = json.loads(_run("--no-models", "--format", "json", "--repeat", "3").stdout)

    rows = report["count_stability_under_dropout"]
    by_rate = {row["dropout_rate"]: row for row in rows}

    assert by_rate[0.0]["fraction_correct"] == 1.0
    assert by_rate[0.2]["modal_count"] == 2, (
        "a 20% detector dropout must not change the reported count"
    )


def test_the_cheap_half_is_actually_cheap():
    """Tracking, relations and the query layer together.

    Worth pinning: if this ever becomes a meaningful share of the frame
    budget, the design's assumption that only the models cost anything has
    stopped being true.
    """
    report = json.loads(_run("--no-models", "--format", "json", "--repeat", "5").stdout)

    assert report["tracker_and_query_only"]["mean_ms"] < 5.0


def test_text_output_names_the_synthetic_caveat():
    result = _run("--no-models", "--repeat", "3")

    assert result.returncode == 0
    assert "SYNTHETIC, NOT PHYSICAL" in result.stdout
