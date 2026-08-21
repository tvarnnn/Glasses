from dataclasses import dataclass


@dataclass
class RelevancePolicy:
    """Thresholds for turning raw detections into stored observations.

    Values are starting points to be revisited against measured retrieval
    behavior (Task 8), not tuned constants -- no data exists yet to tune
    them against.
    """

    min_score: float = 0.5
    resample_seconds: float = 30.0


class RelevanceFilter:
    """Suppresses low-value repeated detections.

    In-memory only and deliberately not persisted: on restart the first
    sighting of each class is recorded again, which is the safe direction
    to err (an extra honest observation, never a suppressed real one).
    """

    def __init__(self, policy: RelevancePolicy) -> None:
        self._policy = policy
        self._last_recorded_at: dict[str, float] = {}

    def should_record(self, object_class: str, score: float, now: float) -> bool:
        if score < self._policy.min_score:
            return False
        previous = self._last_recorded_at.get(object_class)
        if previous is None:
            return True
        return (now - previous) >= self._policy.resample_seconds

    def note_recorded(self, object_class: str, now: float) -> None:
        self._last_recorded_at[object_class] = now
