from tower.experiments import ExperimentResult, MetricKind
from tower.frame_processing import process_frame

# Baseline's headline IS its whole result: `mean_intensity` travels in
# the dedicated field, which the harness already averages. Empty, and
# empty on purpose -- a metric added below without a line here raises
# rather than being guessed at.
METRIC_KINDS: dict[str, MetricKind] = {}


def run(raw_bytes: bytes) -> ExperimentResult:
    result = process_frame(raw_bytes)
    return ExperimentResult(
        result_value=result.mean_intensity,
        result_label="mean_intensity",
        processing_ms=result.processing_ms,
        stage_ms={"total": result.processing_ms},
        mean_intensity=result.mean_intensity,
    )
