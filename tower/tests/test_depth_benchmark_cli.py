import subprocess
import sys


def test_depth_benchmark_requires_label_argument():
    result = subprocess.run(
        [sys.executable, "scripts/depth_benchmark.py"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--label" in result.stderr


def test_depth_benchmark_rejects_unknown_label():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/depth_benchmark.py",
            "--label",
            "not-a-real-label",
            "--frame-count",
            "0",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
