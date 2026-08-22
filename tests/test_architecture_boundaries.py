"""Import-direction invariants between the platform and its cartridges.

These are cheap to state and expensive to discover by hand. A cartridge
that leaks into shared transport does not fail loudly -- it just quietly
makes the next cartridge harder to write, which nobody notices until the
next cartridge exists.
"""

import ast
import pathlib

TOWER = pathlib.Path("tower")


def _imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


def _modules_outside(package: str) -> list[pathlib.Path]:
    return [
        path
        for path in TOWER.rglob("*.py")
        if package not in path.parts and "__pycache__" not in path.parts
    ]


def test_shared_code_does_not_import_a_cartridge():
    """Transport, config and the module system must not know about a cartridge.

    World Builder is one consumer of the camera, not the definition of how
    the camera behaves. The moment shared code imports it, the next
    cartridge inherits its assumptions -- keyframes over freshness,
    latency as free, motion as the signal -- every one of which is wrong
    for Accessibility, Visual Q&A or Text/Document.
    """
    offenders = []
    for path in _modules_outside("world_builder"):
        for name in _imports(path):
            if "world_builder" in name:
                offenders.append(f"{path} -> {name}")

    assert offenders == []


def test_a_cartridge_does_not_import_another_cartridge():
    """Rule 6: modules own their data.

    A shared VOCABULARY may be promoted to tower/ (Confidence was), but one
    cartridge reaching into another's namespace couples their schemas: a
    change on one side silently invalidates persisted records on the other.
    """
    offenders = []
    for path in (TOWER / "world_builder").rglob("*.py"):
        for name in _imports(path):
            if "object_memory" in name:
                offenders.append(f"{path} -> {name}")

    assert offenders == []


def test_shared_storage_primitives_have_no_cartridge_dependency():
    """tower/storage.py and tower/capture.py are platform infrastructure.

    capture.py in particular is armed by shared transport, so versioning
    its records with a cartridge's schema constant would let a
    geometry-driven bump invalidate capture journals that have nothing to
    do with geometry.
    """
    offenders = []
    for name in ("storage.py", "capture.py", "confidence.py"):
        for imported in _imports(TOWER / name):
            if "world_builder" in imported or "object_memory" in imported:
                offenders.append(f"{name} -> {imported}")

    assert offenders == []


def test_world_builder_is_not_registered_as_a_production_module():
    """The integration boundary, asserted rather than assumed.

    Registration is blocked behind V1.0 (registry generalisation) and V1.1
    (lifecycle hardening), both of which are untriggered or blocked. If
    this test ever fails, someone has crossed that boundary -- which may
    be correct, but must be a deliberate decision rather than a drift.
    """
    main = (TOWER / "main.py").read_text(encoding="utf-8")

    assert "world_builder" not in main
    assert not (TOWER / "modules" / "world_builder.py").exists()
