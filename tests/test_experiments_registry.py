# tests/test_experiments_registry.py
from tower.experiments import EXPERIMENTS, baseline, edge_detection


def test_experiments_dict_has_exactly_baseline_and_edge_detection():
    assert set(EXPERIMENTS) == {"baseline", "edge_detection"}


def test_experiments_dict_maps_to_correct_functions():
    assert EXPERIMENTS["baseline"] is baseline.run
    assert EXPERIMENTS["edge_detection"] is edge_detection.run
