"""The artifact-root guard, and the rule that CLIs actually use it.

Written against real pollution, not a hypothetical: a cleanup pass found
Glasses run roots at ``C:\\wbr3``, ``C:\\wbr4``, ``C:\\wbrev``,
``C:\\wb-stage0`` and mutation trees at ``C:\\wbmut*``, plus a scratch
directory at ``~/wbscratch``. Each of those is a placement the guard now
refuses, so each gets a test.

The last test is the one that keeps this honest over time: a new session
CLI that grows a ``--root`` flag and forgets the guard is the exact way
this regresses, and it would otherwise regress silently.
"""

import ast
import pathlib

import pytest

from tower.artifact_paths import (
    ArtifactRootError,
    artifact_root_arg,
    resolve_artifact_root,
)

SCRIPTS = pathlib.Path("scripts")


def test_a_normal_project_relative_root_is_accepted(tmp_path):
    root = tmp_path / "data" / "world_builder"
    assert resolve_artifact_root(root) == root.resolve()


def test_the_root_is_returned_absolute(tmp_path, monkeypatch):
    """A relative root is pinned once, here, not re-interpreted later."""
    monkeypatch.chdir(tmp_path)
    resolved = resolve_artifact_root("data/world_builder")
    assert resolved.is_absolute()
    assert resolved == (tmp_path / "data" / "world_builder").resolve()


def test_the_filesystem_root_itself_is_refused():
    root = pathlib.Path(pathlib.Path.cwd().anchor)
    with pytest.raises(ArtifactRootError, match="filesystem root"):
        resolve_artifact_root(root)


@pytest.mark.parametrize(
    "name",
    ["wbr3", "wbr4", "wbrev", "wb-stage0", "wbmut", "wb-adv", "m3s"],
)
def test_a_direct_child_of_the_drive_root_is_refused(name):
    """Every one of these was found on disk as real pollution."""
    candidate = pathlib.Path(pathlib.Path.cwd().anchor) / name
    with pytest.raises(ArtifactRootError, match="drive root"):
        resolve_artifact_root(candidate)


def test_the_home_directory_itself_is_refused():
    with pytest.raises(ArtifactRootError, match="home directory"):
        resolve_artifact_root(pathlib.Path.home())


def test_a_direct_child_of_home_is_refused():
    """``~/wbscratch`` was found on disk; it is not a project location."""
    with pytest.raises(ArtifactRootError, match="home directory"):
        resolve_artifact_root(pathlib.Path.home() / "wbscratch")


def test_a_temp_directory_is_still_allowed(tmp_path):
    """The guard must not break tempfile-based tests and smoke runs.

    ``tmp_path`` lives deep under the home directory on Windows
    (``%LOCALAPPDATA%\\Temp\\...``), not directly in it.
    """
    assert resolve_artifact_root(tmp_path) == tmp_path.resolve()


def test_a_relative_root_from_the_drive_root_is_refused(monkeypatch):
    """The original failure mode, reproduced exactly.

    An agent standing at ``C:\\`` running ``--root wbr3`` used to get
    ``C:\\wbr3`` with no complaint at all.
    """
    monkeypatch.chdir(pathlib.Path(pathlib.Path.cwd().anchor))
    with pytest.raises(ArtifactRootError, match="drive root"):
        resolve_artifact_root("wbr3")


def test_the_argparse_converter_reports_a_usage_error():
    """argparse must see its own error type, not a bare ValueError."""
    import argparse

    candidate = str(pathlib.Path(pathlib.Path.cwd().anchor) / "wbmut")
    with pytest.raises(argparse.ArgumentTypeError):
        artifact_root_arg(candidate)


def _root_flag_is_guarded(path: pathlib.Path) -> bool:
    """True if this script's ``--root`` is converted by the guard."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            continue
        flags = [a.value for a in node.args if isinstance(a, ast.Constant)]
        if "--root" not in flags:
            continue
        converter = next(
            (kw.value for kw in node.keywords if kw.arg == "type"), None
        )
        if not (
            isinstance(converter, ast.Name)
            and converter.id == "artifact_root_arg"
        ):
            return False
    return True


def _scripts_declaring_a_root_flag() -> list[pathlib.Path]:
    return [
        path
        for path in sorted(SCRIPTS.rglob("*.py"))
        if "__pycache__" not in path.parts
        and '"--root"' in path.read_text(encoding="utf-8")
    ]


def test_the_scan_actually_finds_the_session_clis():
    """Guard the guard: an empty scan would make the next test vacuous."""
    found = _scripts_declaring_a_root_flag()
    assert found, "no script declares --root; the scan is broken"


def test_every_cli_root_flag_routes_through_the_guard():
    """A new ``--root`` that forgets the guard is how this regresses."""
    unguarded = [
        str(path)
        for path in _scripts_declaring_a_root_flag()
        if not _root_flag_is_guarded(path)
    ]
    assert not unguarded, (
        "these scripts take --root without artifact_root_arg, so they can "
        f"still write to the drive root: {unguarded}"
    )
