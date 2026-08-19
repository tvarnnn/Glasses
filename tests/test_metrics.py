from tower.metrics import SessionMetrics


def _fake_clock():
    counter = {"t": 0.0}

    def clock():
        return counter["t"]

    def advance(seconds):
        counter["t"] += seconds

    return clock, advance


def test_effective_fps_reflects_elapsed_time_and_frame_count():
    clock, advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    advance(1.0)
    metrics.record_frame(seq=1, byte_count=1000, receive_to_result_ms=5.0, cv_processing_ms=2.0)
    advance(1.0)
    metrics.record_frame(seq=2, byte_count=1000, receive_to_result_ms=5.0, cv_processing_ms=2.0)

    snapshot = metrics.snapshot()

    assert snapshot["frames_received"] == 2
    assert snapshot["session_duration_s"] == 2.0
    assert snapshot["effective_fps"] == 1.0


def test_transport_seq_gap_is_counted_when_a_sequence_number_is_skipped():
    clock, _advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    metrics.record_frame(seq=1, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    metrics.record_frame(seq=4, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)

    assert metrics.snapshot()["transport_seq_gaps"] == 2


def test_no_gap_counted_for_consecutive_sequence_numbers():
    clock, _advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    metrics.record_frame(seq=1, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    metrics.record_frame(seq=2, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)

    assert metrics.snapshot()["transport_seq_gaps"] == 0


def test_backpressure_drops_is_tracked_separately_from_transport_seq_gaps():
    metrics = SessionMetrics()

    metrics.record_frame(seq=1, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    metrics.record_frame(seq=3, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    snapshot = metrics.snapshot()

    assert snapshot["transport_seq_gaps"] == 1
    assert snapshot["backpressure_drops"] == 0


def test_bandwidth_reflects_bytes_and_elapsed_time():
    clock, advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    advance(2.0)
    metrics.record_frame(seq=1, byte_count=2000, receive_to_result_ms=1.0, cv_processing_ms=1.0)

    assert metrics.snapshot()["bandwidth_bps"] == 1000.0


def test_should_log_summary_fires_every_configured_interval():
    metrics = SessionMetrics()
    metrics.SUMMARY_LOG_FRAME_INTERVAL = 2

    metrics.record_frame(seq=1, byte_count=1, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    assert metrics.should_log_summary() is False

    metrics.record_frame(seq=2, byte_count=1, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    assert metrics.should_log_summary() is True


def test_snapshot_includes_process_resource_fields():
    metrics = SessionMetrics()
    metrics.record_frame(seq=1, byte_count=1, receive_to_result_ms=1.0, cv_processing_ms=1.0)

    snapshot = metrics.snapshot()

    assert "process_cpu_percent" in snapshot
    assert "process_rss_bytes" in snapshot
    assert snapshot["process_rss_bytes"] > 0


def test_snapshot_includes_separately_labeled_latency_figures():
    metrics = SessionMetrics()
    metrics.record_frame(seq=1, byte_count=1, receive_to_result_ms=9.0, cv_processing_ms=3.0)

    snapshot = metrics.snapshot()

    assert snapshot["receive_to_result_ms_avg"] == 9.0
    assert snapshot["cv_processing_ms_avg"] == 3.0
