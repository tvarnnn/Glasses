import os

from tower.config import get_settings


def test_cv_experiment_defaults_to_baseline(monkeypatch):
    monkeypatch.delenv("TOWER_CV_EXPERIMENT", raising=False)

    settings = get_settings()

    assert settings.cv_experiment == "baseline"


def test_cv_experiment_respects_env_var(monkeypatch):
    monkeypatch.setenv("TOWER_CV_EXPERIMENT", "edge_detection")

    settings = get_settings()

    assert settings.cv_experiment == "edge_detection"
