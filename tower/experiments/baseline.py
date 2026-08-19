from tower.experiments import ExperimentResult
from tower.frame_processing import process_frame


def run(raw_bytes: bytes) -> ExperimentResult:
    result = process_frame(raw_bytes)
    return ExperimentResult(
        result_value=result.mean_intensity,
        result_label="mean_intensity",
        processing_ms=result.processing_ms,
        stage_ms={"total": result.processing_ms},
        mean_intensity=result.mean_intensity,
    )
