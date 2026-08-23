"""CLI-contract tests for the World Builder environment diagnostic.

Deliberately narrow. The script reports on a GPU, a driver, and a torch
build, none of which the fast suite may assume exist -- so these tests pin
only what is true on any machine: the argument contract, that the
diagnostic still succeeds when the environment it describes is degraded,
and that --strict is the only thing that turns a bad environment into a
non-zero exit.
"""

import json
import subprocess
import sys


def _run(*args):
    return subprocess.run(
        [sys.executable, "scripts/world_builder_env_check.py", *args],
        capture_output=True,
        text=True,
    )


def test_env_check_rejects_unknown_format():
    result = _run("--format", "not-a-real-format")

    assert result.returncode != 0
    assert "--format" in result.stderr


def test_env_check_succeeds_without_arguments():
    """The default run must not fail on an environment it reports as bad.

    This is the whole point of defaulting --strict off: a diagnostic that
    exits non-zero on the broken machine gets read as "the tool is broken"
    and stops being run.
    """
    result = _run()

    assert result.returncode == 0
    assert "=== Verdicts ===" in result.stdout


def test_env_check_json_is_parseable_and_carries_verdicts():
    result = _run("--format", "json")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert {"host", "nvidia_smi", "torch", "opencv", "libraries", "verdicts"} <= set(
        report
    )
    assert report["verdicts"], "expected at least one verdict"
    for verdict in report["verdicts"]:
        assert set(verdict) == {"check", "ok", "detail"}
        assert isinstance(verdict["ok"], bool)


def test_strict_exit_code_follows_the_verdicts():
    """--strict must agree with what the report itself says.

    Pinning the relationship rather than a fixed exit code keeps this test
    honest on a machine where every verdict passes and on one where none
    do -- the failure mode being guarded against is --strict quietly
    exiting 0 while the report shows failures.
    """
    report = json.loads(_run("--format", "json").stdout)
    any_failed = any(not verdict["ok"] for verdict in report["verdicts"])

    strict = _run("--strict")

    assert (strict.returncode != 0) == any_failed
