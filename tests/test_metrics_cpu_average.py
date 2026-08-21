"""`process_cpu_percent` must describe the session, not the last snapshot.

It previously came from `psutil.Process.cpu_percent(interval=None)`, which
measures CPU only since the *previous call on that object*. Because
`snapshot()` is also called periodically (every
SUMMARY_LOG_FRAME_INTERVAL frames), the number in a session's FINAL
summary covered just the frames since the last periodic summary -- not
the session. At a healthy frame rate that window is a fraction of a
second, and the field can read 0.0 while a core is pegged.

Measured 2026-08-21: two back-to-back snapshots of one busy session
reported 95.9 then 0.0. That is a truthful-state failure (Rule 3) in the
exact field used to judge Tower headroom, so it is now computed as
cumulative CPU time over the whole session.
"""
import collections

import pytest

from tower.metrics import SessionMetrics

_CpuTimes = collections.namedtuple("_CpuTimes", "user system")
_MemInfo = collections.namedtuple("_MemInfo", "rss")


class _StubProcess:
    """Reports a scripted sequence of cumulative CPU times."""

    def __init__(self, cpu_times_sequence):
        self._sequence = list(cpu_times_sequence)

    def cpu_times(self):
        # Hold the final value once exhausted, so extra snapshots are fine.
        return self._sequence.pop(0) if len(self._sequence) > 1 else self._sequence[0]

    def cpu_percent(self, interval=None):  # pragma: no cover - must go unused
        raise AssertionError(
            "process_cpu_percent must not be derived from cpu_percent(): "
            "it resets its measurement window on every call"
        )

    def memory_info(self):
        return _MemInfo(rss=12345)


def _fake_clock():
    counter = {"t": 0.0}

    def clock():
        return counter["t"]

    def advance(seconds):
        counter["t"] += seconds

    return clock, advance


@pytest.fixture
def stub_process(monkeypatch):
    def install(cpu_times_sequence):
        stub = _StubProcess(cpu_times_sequence)
        monkeypatch.setattr("tower.metrics.psutil.Process", lambda: stub)
        return stub

    return install


def test_cpu_percent_is_cumulative_cpu_time_over_session_duration(stub_process):
    """0.5 s of CPU across a 2 s session is 25% of one core."""
    stub_process([_CpuTimes(user=1.0, system=0.5), _CpuTimes(user=1.4, system=0.6)])
    clock, advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    advance(2.0)

    assert metrics.snapshot()["process_cpu_percent"] == 25.0


def test_cpu_percent_counts_both_user_and_system_time(stub_process):
    stub_process([_CpuTimes(user=0.0, system=0.0), _CpuTimes(user=0.6, system=0.4)])
    clock, advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    advance(1.0)

    assert metrics.snapshot()["process_cpu_percent"] == 100.0


def test_cpu_percent_may_exceed_one_hundred_percent(stub_process):
    """Percent of ONE core, matching psutil's convention -- a multi-core
    process legitimately exceeds 100 and must not be clamped.
    """
    stub_process([_CpuTimes(user=0.0, system=0.0), _CpuTimes(user=3.0, system=0.0)])
    clock, advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    advance(1.0)

    assert metrics.snapshot()["process_cpu_percent"] == 300.0


def test_repeated_snapshots_report_the_same_session_average(stub_process):
    """The regression. Under the old implementation the second snapshot
    reported ~0.0 because the window restarted; the value must instead
    stay anchored to the start of the session.
    """
    stub_process(
        [
            _CpuTimes(user=0.0, system=0.0),  # at construction
            _CpuTimes(user=1.0, system=0.0),  # first snapshot
            _CpuTimes(user=1.0, system=0.0),  # second: no further CPU used
        ]
    )
    clock, advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    advance(2.0)
    first = metrics.snapshot()["process_cpu_percent"]
    second = metrics.snapshot()["process_cpu_percent"]

    assert first == 50.0
    assert second == 50.0  # not 0.0


def test_periodic_summary_does_not_corrupt_the_final_summary(stub_process):
    """The concrete failure mode: a long session logs periodic summaries,
    and the final summary must still describe the whole session rather
    than the sliver since the last periodic one.
    """
    stub_process(
        [
            _CpuTimes(user=0.0, system=0.0),
            _CpuTimes(user=5.0, system=0.0),  # periodic summary, busy period
            _CpuTimes(user=5.0, system=0.0),  # final summary, idle since
        ]
    )
    clock, advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    advance(10.0)
    metrics.snapshot()  # periodic
    advance(10.0)

    # 5 s of CPU across the full 20 s session.
    assert metrics.snapshot()["process_cpu_percent"] == 25.0


def test_zero_cpu_use_reports_zero_not_an_error(stub_process):
    stub_process([_CpuTimes(user=2.0, system=1.0), _CpuTimes(user=2.0, system=1.0)])
    clock, advance = _fake_clock()
    metrics = SessionMetrics(clock=clock)

    advance(5.0)

    assert metrics.snapshot()["process_cpu_percent"] == 0.0


def test_real_process_reports_a_plausible_stable_value():
    """Guards the stub-based tests against drifting from reality: two
    back-to-back snapshots of a real busy process must agree, which is
    exactly what failed before.
    """
    import time

    metrics = SessionMetrics()
    deadline = time.perf_counter() + 0.2
    while time.perf_counter() < deadline:
        pass

    first = metrics.snapshot()["process_cpu_percent"]
    second = metrics.snapshot()["process_cpu_percent"]

    assert first > 10.0, first
    assert second > 10.0, second  # under the old code this was 0.0
    assert abs(first - second) < 25.0, (first, second)
