"""The Lab benchmark's CLI contract.

Driven as a user drives it -- separate process, cold start -- because the
property that matters most is one an in-process call cannot check: that
`--format json` emits a document and nothing else. A library printing to
stdout during model load silently corrupted it once already.
"""

import json
import subprocess
import sys


def _run(*args):
    return subprocess.run(
        [sys.executable, "scripts/cv_lab_benchmark.py", *args],
        capture_output=True,
        text=True,
    )


def test_help_exits_zero():
    assert _run("--help").returncode == 0


def test_json_output_is_parseable_and_nothing_else_reaches_stdout():
    result = _run("--format", "json", "--repeat", "2")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert "SYNTHETIC" in report["note"]


def test_every_cheap_experiment_is_benchmarked_at_the_delivered_resolution():
    result = _run("--format", "json", "--repeat", "2")
    report = json.loads(result.stdout)

    delivered = report["resolutions"]["640x360"]
    names = {entry["experiment"] for entry in delivered["experiments"]}
    assert names == {
        "baseline",
        "edge_detection",
        "frame_quality",
        "feature_detection",
        "redaction_impact",
        "optical_flow",
    }


def test_each_entry_carries_a_headline_a_timing_and_stages():
    report = json.loads(_run("--format", "json", "--repeat", "2").stdout)

    for entry in report["resolutions"]["640x360"]["experiments"]:
        assert entry["headline"], entry["experiment"]
        assert entry["timing"]["mean_ms"] > 0
        assert entry["stage_ms"]


def test_the_rejected_dense_flow_alternative_keeps_its_measurement():
    """A rejected option is only a decision while its evidence survives."""
    report = json.loads(_run("--format", "json", "--repeat", "2").stdout)

    comparison = report["resolutions"]["640x360"]["optical_flow_sparse_vs_dense"]
    assert comparison["dense_farneback"]["mean_ms"] > comparison["sparse_lk"]["mean_ms"]
    assert comparison["dense_cost_multiple"] > 1


def test_cost_grows_with_resolution():
    """Independent truth: more pixels cannot be cheaper."""
    report = json.loads(_run("--format", "json", "--repeat", "3").stdout)

    def mean_for(resolution: str, name: str) -> float:
        entries = report["resolutions"][resolution]["experiments"]
        return next(e for e in entries if e["experiment"] == name)["timing"]["mean_ms"]

    assert mean_for("1280x720", "frame_quality") > mean_for("640x360", "frame_quality")


def test_text_output_names_the_synthetic_caveat():
    result = _run("--repeat", "2")

    assert result.returncode == 0
    assert "SYNTHETIC, NOT PHYSICAL" in result.stdout
