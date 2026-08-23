from tower.experiments import ExperimentResult


def test_construct_with_all_fields():
    result = ExperimentResult(
        result_value=0.5,
        result_label="edge_density",
        processing_ms=3.2,
        stage_ms={"decode": 1.0, "canny": 2.2},
    )

    assert result.result_value == 0.5
    assert result.result_label == "edge_density"
    assert result.processing_ms == 3.2
    assert result.stage_ms == {"decode": 1.0, "canny": 2.2}
    assert result.mean_intensity is None


def test_mean_intensity_defaults_to_none_but_can_be_set():
    result = ExperimentResult(
        result_value=128.0,
        result_label="mean_intensity",
        processing_ms=1.1,
        stage_ms={"total": 1.1},
        mean_intensity=128.0,
    )

    assert result.mean_intensity == 128.0
