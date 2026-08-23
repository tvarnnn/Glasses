"""The module factory, after the depth branch was removed.

There is one Module class for the Lab now. Selecting `depth` no longer
picks a different subclass -- it picks a different experiment inside the
same one, which is what "one Lab slot, many experiments" always meant.
"""

from tower.config import Settings
from tower.experiments import ExperimentSettings
from tower.main import _build_cv_module
from tower.modules.experimental_cv import ExperimentalCVModule


def _settings(cv_experiment: str, cv_device: str = "auto") -> Settings:
    return Settings(
        host="0.0.0.0",
        port=8000,
        dev_mode=True,
        cv_experiment=cv_experiment,
        cv_device=cv_device,
    )


def test_every_experiment_selection_yields_the_one_lab_module():
    for name in ("baseline", "edge_detection", "depth", "object_detection"):
        module = _build_cv_module(_settings(name, cv_device="cpu"))
        assert isinstance(module, ExperimentalCVModule)
        assert module.descriptor.id == "experimental-cv"


def test_the_requested_device_reaches_the_experiment_settings():
    module = _build_cv_module(_settings("depth", cv_device="cpu"))

    assert module._settings == ExperimentSettings(device="cpu")


def test_constructing_a_module_loads_no_model():
    """A factory, not an instance, is what the registry holds.

    Building a detector at construction time would download and load
    weights merely because something imported the app factory.
    """
    module = _build_cv_module(_settings("object_detection", cv_device="cpu"))

    assert module._experiment is None
