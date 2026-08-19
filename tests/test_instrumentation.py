import time

from tower.instrumentation import StageTimer


def test_stage_records_positive_elapsed_time():
    timer = StageTimer()

    with timer.stage("sleep"):
        time.sleep(0.01)

    snapshot = timer.snapshot()
    assert "sleep" in snapshot
    assert snapshot["sleep"] > 0


def test_snapshot_returns_a_copy_not_the_live_dict():
    timer = StageTimer()
    with timer.stage("a"):
        pass

    snapshot = timer.snapshot()
    snapshot["a"] = -999.0

    assert timer.snapshot()["a"] != -999.0


def test_total_ms_sums_all_recorded_stages():
    timer = StageTimer()
    with timer.stage("a"):
        time.sleep(0.01)
    with timer.stage("b"):
        time.sleep(0.01)

    snapshot = timer.snapshot()
    assert timer.total_ms == snapshot["a"] + snapshot["b"]
