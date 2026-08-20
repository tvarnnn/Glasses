import pytest


@pytest.fixture(autouse=True)
def _clear_cv_experiment_env(monkeypatch):
    monkeypatch.delenv("TOWER_CV_EXPERIMENT", raising=False)
    monkeypatch.delenv("TOWER_CV_DEVICE", raising=False)
