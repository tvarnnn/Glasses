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


def test_the_experimental_cv_lab_does_not_import_a_cartridge():
    """The Lab must not depend on World Builder or Object Memory.

    Its job is to MEASURE things like blur rejection, feature yield and
    parallax -- the same questions World Builder answers privately. If it
    imported that answer it would be restating a cartridge's opinion
    rather than measuring the underlying property, and a change on the
    cartridge side would silently move a measurement.

    It would also invert the dependency the platform is built on: a
    sandbox may be thrown away, and nothing that can be thrown away should
    be upstream of a persistent world.
    """
    offenders = []
    paths = list((TOWER / "experiments").rglob("*.py"))
    paths.append(TOWER / "modules" / "experimental_cv.py")
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        for name in _imports(path):
            if "world_builder" in name or "object_memory" in name:
                offenders.append(f"{path} -> {name}")

    assert offenders == []


def test_no_experiment_persists_anything():
    """The Lab's descriptor declares persists_data=False. Keep it true.

    The descriptor is what `06-PRIVACY-DATA.md` is enforced against, so an
    experiment that quietly wrote to disk would not merely be untidy -- it
    would make the module's declared data behaviour a lie.

    Dataset recording is not an exception to this: it belongs to the
    SHARED recorder (`tower/capture.py`), armed by the transport, not to
    an experiment.
    """
    forbidden = ("write_json_atomic", "append_jsonl", "WorldStore", "ObservationStore")
    offenders = []
    for path in (TOWER / "experiments").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = node.func
                called = getattr(target, "id", None) or getattr(target, "attr", None)
                if called in forbidden or called in ("open",):
                    offenders.append(f"{path.name} calls {called}()")

    assert offenders == []


def test_shared_code_does_not_import_an_experiment_implementation():
    """`tower/routes` and `tower/frames.py` must stay experiment-agnostic.

    The transport may know the SHAPE of a result; it must not know which
    experiment produced it. A transport that special-cased `depth` would
    make the next experiment a transport change.
    """
    offenders = []
    for name in ("routes/ws.py", "routes/health.py", "frames.py", "metrics.py"):
        for imported in _imports(TOWER / name):
            if imported.startswith("tower.experiments."):
                offenders.append(f"{name} -> {imported}")

    assert offenders == []


def test_importing_the_lab_does_not_import_torch():
    """The optional [ml] extra must stay optional.

    Two experiments need torch; six do not, and the Tower must start on a
    machine that has never installed it. Every torch import is therefore
    inside a function, and this is the only way to check that -- an
    in-process assertion would pass merely because some earlier test in
    the same session had already imported it.
    """
    import subprocess
    import sys

    probe = (
        "import sys, tower.main, tower.experiments; "
        "print([m for m in ('torch','torchvision','timm') if m in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("[]"), result.stdout
