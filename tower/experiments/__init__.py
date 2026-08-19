from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentResult:
    result_value: float
    result_label: str
    processing_ms: float
    stage_ms: dict[str, float]
    mean_intensity: float | None = None
