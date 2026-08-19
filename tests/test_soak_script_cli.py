import subprocess
import sys


def test_soak_script_requires_source_argument():
    result = subprocess.run(
        [sys.executable, "scripts/soak_test_stream.py"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--source" in result.stderr


def test_soak_script_rejects_unknown_source():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/soak_test_stream.py",
            "--source",
            "not-a-real-source",
            "--duration-s",
            "0",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
