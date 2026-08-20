from tower.config import Settings
from tower.main import _build_cv_module
from tower.modules.depth_cv import DepthEstimationModule
from tower.modules.experimental_cv import ExperimentalCVModule


def _settings(cv_experiment: str, cv_device: str = "auto") -> Settings:
    return Settings(
        host="0.0.0.0",
        port=8000,
        dev_mode=True,
        cv_experiment=cv_experiment,
        cv_device=cv_device,
    )


def test_build_cv_module_returns_depth_module_for_depth_experiment():
    module = _build_cv_module(_settings("depth", cv_device="cpu"))
    assert isinstance(module, DepthEstimationModule)


def test_build_cv_module_returns_experimental_cv_module_for_other_names():
    module = _build_cv_module(_settings("baseline"))
    assert isinstance(module, ExperimentalCVModule)
