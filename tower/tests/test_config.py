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


def test_cv_device_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("TOWER_CV_DEVICE", raising=False)

    settings = get_settings()

    assert settings.cv_device == "auto"


def test_cv_device_respects_env_var(monkeypatch):
    monkeypatch.setenv("TOWER_CV_DEVICE", "cpu")

    settings = get_settings()

    assert settings.cv_device == "cpu"
