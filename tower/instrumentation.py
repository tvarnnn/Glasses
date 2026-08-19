import time
from contextlib import contextmanager


class StageTimer:
    """Collects named-stage durations (ms) for one frame's processing."""

    def __init__(self) -> None:
        self._stage_ms: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self._stage_ms[name] = (time.perf_counter() - start) * 1000

    def snapshot(self) -> dict[str, float]:
        return dict(self._stage_ms)

    @property
    def total_ms(self) -> float:
        return sum(self._stage_ms.values())
