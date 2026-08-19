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


def test_seq_gap_total_is_counted_when_a_sequence_number_is_skipped():
    clock, _advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    metrics.record_frame(seq=1, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    metrics.record_frame(seq=4, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)

    assert metrics.snapshot()["seq_gap_total"] == 2


def test_no_seq_gap_counted_for_consecutive_sequence_numbers():
    clock, _advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    metrics.record_frame(seq=1, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    metrics.record_frame(seq=2, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)

    assert metrics.snapshot()["seq_gap_total"] == 0


def test_seq_gap_total_is_counted_for_a_known_intentional_sampling_stride():
    """The iPhone sender currently forwards roughly 1-in-30 DAT frames by
    design (throttled capture -> transmit branch), so seq arrives as
    1, 30, 60, ... . seq_gap_total still counts the raw discontinuity --
    it does not and cannot know this gap was intentional under the current
    protocol (no source_seq/tx_seq split -- see 07-PLATFORM-CONSTRAINTS.md
    Limitation 9). This test locks in that seq_gap_total is a raw,
    causally-neutral count, not a "loss" claim.
    """
    metrics = SessionMetrics()

    metrics.record_frame(seq=1, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    metrics.record_frame(seq=30, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    metrics.record_frame(seq=60, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)

    assert metrics.snapshot()["seq_gap_total"] == 57


def test_backpressure_drops_is_tracked_separately_from_seq_gap_total():
    metrics = SessionMetrics()

    metrics.record_frame(seq=1, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    metrics.record_frame(seq=3, byte_count=100, receive_to_result_ms=1.0, cv_processing_ms=1.0)
    snapshot = metrics.snapshot()

    assert snapshot["seq_gap_total"] == 1
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
