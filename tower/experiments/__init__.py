from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentResult:
    result_value: float
    result_label: str
    processing_ms: float
    stage_ms: dict[str, float]
    mean_intensity: float | None = None


from typing import Callable

# Import order here is deliberate, not incidental: ExperimentResult must
# be defined above this line. baseline.py/edge_detection.py both do
# `from tower.experiments import ExperimentResult`; by the time that runs,
# this (partially-initialized) module already has ExperimentResult set as
# an attribute, so the circular import resolves. Moving this import above
# the class definition breaks both submodules at import time.
from tower.experiments import baseline, edge_detection  # noqa: E402

EXPERIMENTS: dict[str, Callable[[bytes], ExperimentResult]] = {
    "baseline": baseline.run,
    "edge_detection": edge_detection.run,
}
