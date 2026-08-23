"""The registry contract, after it started holding factories.

It used to map a name to a plain function, which is why a stateful
experiment needed its own Module subclass. It now maps a name to a
zero-argument factory producing something that satisfies the `Experiment`
protocol -- which is what let two Module classes collapse into one.

The important property is the FACTORY, not the instance: `object_detection`
downloads and loads model weights, and a registry of instances would do
that in any process that so much as imported this module.
"""

import io

import pytest
from PIL import Image

from tower.experiments import (
    EXPERIMENTS,
    Experiment,
    ExperimentResult,
    ExperimentSettings,
    baseline,
    edge_detection,
)

# Experiments that need no load() and can therefore be exercised here.
# `depth` and `object_detection` are excluded deliberately: both download
# model weights, which belongs in an opt-in integration test, not in the
# default suite.
CHEAP_EXPERIMENTS = (
    "baseline",
    "edge_detection",
    "frame_quality",
    "feature_detection",
    "redaction_impact",
    "optical_flow",
)

MODEL_BACKED_EXPERIMENTS = ("depth", "object_detection")


@pytest.fixture
def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (96, 72), (140, 90, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_the_registry_holds_exactly_the_v1_experiment_set():
    assert set(EXPERIMENTS) == set(CHEAP_EXPERIMENTS) | set(MODEL_BACKED_EXPERIMENTS)


def test_every_entry_is_a_factory_not_a_shared_instance():
    """Two calls must yield two objects.

    A shared instance would mean two Lab modules -- or a module reloaded
    after a failure -- silently sharing one experiment's state, and for a
    model-backed experiment it would mean loading weights at import time.

    Asserted by construction rather than with `isinstance(entry, Experiment)`:
    a runtime-checkable Protocol only looks for attribute presence, and a
    CLASS has `load`/`run`/`release` attributes too, so that check passes
    for exactly the thing it is meant to reject.
    """
    for name, entry in EXPERIMENTS.items():
        assert callable(entry), name
        first, second = entry(), entry()
        assert first is not second, f"{name} hands out one shared instance"


@pytest.mark.parametrize("name", CHEAP_EXPERIMENTS)
def test_a_cheap_experiment_satisfies_the_protocol_and_runs(name, jpeg):
    experiment = EXPERIMENTS[name]()

    assert isinstance(experiment, Experiment), name
    assert experiment.name == name

    experiment.load(ExperimentSettings())
    try:
        result = experiment.run(jpeg)
    finally:
        experiment.release()

    assert isinstance(result, ExperimentResult)
    assert isinstance(result.result_value, float)
    assert result.result_label
    assert result.processing_ms >= 0.0
    assert result.stage_ms


@pytest.mark.parametrize("name", CHEAP_EXPERIMENTS)
def test_release_is_safe_to_call_twice_and_without_a_load(name):
    """release() runs on the FAILED transition, which is reachable from anywhere."""
    experiment = EXPERIMENTS[name]()

    experiment.release()
    experiment.release()


@pytest.mark.parametrize("name", MODEL_BACKED_EXPERIMENTS)
def test_a_model_backed_experiment_constructs_without_loading_anything(name):
    experiment = EXPERIMENTS[name]()

    assert isinstance(experiment, Experiment), name
    assert experiment.name == name
    experiment.release()


def test_the_stateless_wrapper_still_calls_the_original_function(jpeg):
    """The adapter must not have changed what baseline/edge_detection do."""
    wrapped = EXPERIMENTS["baseline"]()
    wrapped.load(ExperimentSettings())

    assert wrapped.run(jpeg).result_value == baseline.run(jpeg).result_value

    wrapped = EXPERIMENTS["edge_detection"]()
    assert wrapped.run(jpeg).result_value == edge_detection.run(jpeg).result_value


def test_every_experiment_names_a_headline_that_appears_in_its_metrics(jpeg):
    """A headline that is not among the measurements is an orphan number.

    `baseline` and `edge_detection` predate the metrics channel and are
    exempt: they have one number and it IS the headline.
    """
    exempt = {"baseline", "edge_detection"}
    for name in CHEAP_EXPERIMENTS:
        if name in exempt:
            continue
        experiment = EXPERIMENTS[name]()
        experiment.load(ExperimentSettings())
        result = experiment.run(jpeg)
        experiment.release()

        assert result.result_label in result.metrics, name
        assert result.metrics[result.result_label] == pytest.approx(
            result.result_value
        ), name
