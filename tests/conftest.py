import os

import pytest

# Module-scope clear, in addition to the autouse fixture below: pytest
# imports conftest.py before any test module, but an ambient
# TOWER_CV_EXPERIMENT=depth in the operator's shell (e.g. left over from
# manually testing the depth experiment per the README) would otherwise
# still be set when tower.main is first imported during test collection.
# tower/main.py's last line is a module-level `app = create_app()` that
# runs at import time -- before any fixture, even an autouse one, gets a
# chance to run, since fixtures only wrap test *execution*, not import.
# Left uncleared, that import-time create_app() would build a real
# DepthEstimationModule and attempt a real torch import / MiDaS network
# fetch during collection, regardless of which tests are selected.
os.environ.pop("TOWER_CV_EXPERIMENT", None)
os.environ.pop("TOWER_CV_DEVICE", None)


@pytest.fixture(autouse=True)
def _clear_cv_experiment_env(monkeypatch):
    monkeypatch.delenv("TOWER_CV_EXPERIMENT", raising=False)
    monkeypatch.delenv("TOWER_CV_DEVICE", raising=False)
