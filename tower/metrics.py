import time
from typing import Callable

import psutil


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class SessionMetrics:
    """Tracks measurements for a single WebSocket connection's frame stream.

    A new instance must be created per connection, never reused across a
    reconnect: a new session is a new observation stream, not a
    continuation of the previous one (07-PLATFORM-CONSTRAINTS.md,
    Limitation 4).

    ``seq_gap_total`` is a RAW, causally-neutral count of discontinuities
    in the received ``seq`` field. It is deliberately NOT named/labeled as
    "frames lost in transit". Confirmed 2026-08-19: the current iOS sender
    assigns ``seq`` from the DAT/source capture-frame index (``frameCount``
    of incoming VideoFrames), but only forwards roughly 1-in-30 of them
    (a throttled capture -> transmit branch), so the Tower normally
    receives seq like 1, 30, 60, 90, ... by design. Under the CURRENT wire
    protocol (seq, width, height, format, data -- no separate
    transmission-attempt counter), a gap in ``seq`` cannot be attributed
    to any single cause: it may be intentional sender-side sampling,
    a sender-side drop, or genuine network/transit loss, and those look
    identical on the wire. Do not report this number as network loss.
    See 07-PLATFORM-CONSTRAINTS.md Limitation 9 for the future
    source_seq/tx_seq protocol split that would be required to actually
    distinguish these causes -- not implemented as of V0.7.

    ``backpressure_drops`` is tracked separately from ``seq_gap_total`` on
    purpose (2026-08-19 V0.7 planning decision) -- the two have different
    causes (network/link loss or sender sampling vs. a Tower-side drop
    policy) and must never be combined into one number. As of V0.7, no
    code path increments ``backpressure_drops``: the receive -> process ->
    ack loop in tower/routes/ws.py is intentionally left unchanged this
    milestone, so this field will always read 0 until a future milestone
    adds a real drop mechanism.
    """

    SUMMARY_LOG_FRAME_INTERVAL = 150

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._process = psutil.Process()
        self._process.cpu_percent(interval=None)  # prime the internal baseline
        self.start_time = clock()
        self.last_seq: int | None = None
        self.frames_received = 0
        self.seq_gap_total = 0
        self.backpressure_drops = 0
        self.bytes_received = 0
        self._receive_to_result_ms: list[float] = []
        self._cv_processing_ms: list[float] = []
        self._stage_ms: dict[str, list[float]] = {}

    def record_frame(
        self,
        seq: int,
        byte_count: int,
        receive_to_result_ms: float,
        cv_processing_ms: float,
        stage_ms: dict[str, float] | None = None,
    ) -> None:
        if self.last_seq is not None and seq > self.last_seq + 1:
            self.seq_gap_total += seq - self.last_seq - 1
        self.last_seq = seq
        self.frames_received += 1
        self.bytes_received += byte_count
        self._receive_to_result_ms.append(receive_to_result_ms)
        self._cv_processing_ms.append(cv_processing_ms)
        if stage_ms:
            for stage_name, ms in stage_ms.items():
                self._stage_ms.setdefault(stage_name, []).append(ms)

    def should_log_summary(self) -> bool:
        return (
            self.frames_received > 0
            and self.frames_received % self.SUMMARY_LOG_FRAME_INTERVAL == 0
        )

    def snapshot(self) -> dict:
        elapsed_s = max(self._clock() - self.start_time, 1e-9)
        return {
            "session_duration_s": round(elapsed_s, 3),
            "frames_received": self.frames_received,
            "effective_fps": round(self.frames_received / elapsed_s, 2),
            "bytes_received": self.bytes_received,
            "bandwidth_bps": round(self.bytes_received / elapsed_s, 2),
            "seq_gap_total": self.seq_gap_total,
            "backpressure_drops": self.backpressure_drops,
            "receive_to_result_ms_avg": round(_avg(self._receive_to_result_ms), 3),
            "receive_to_result_ms_max": round(
                max(self._receive_to_result_ms, default=0.0), 3
            ),
            "cv_processing_ms_avg": round(_avg(self._cv_processing_ms), 3),
            "process_cpu_percent": self._process.cpu_percent(interval=None),
            "process_rss_bytes": self._process.memory_info().rss,
            "stage_ms_avg": {k: round(_avg(v), 3) for k, v in self._stage_ms.items()},
            "stage_ms_max": {k: round(max(v), 3) for k, v in self._stage_ms.items()},
        }
