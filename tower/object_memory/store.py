import json
import logging
from pathlib import Path

from tower.object_memory.records import (
    ObjectObservation,
    object_observation_from_json_dict,
)

logger = logging.getLogger(__name__)

OBSERVATIONS_FILENAME = "observations.jsonl"


class ObservationStore:
    """Append-only JSONL store for one module's observations.

    JSONL, not SQLite: at V1 scale a single module's observation history is
    small, and the canonical-memory research explicitly sequences SQLite +
    sqlite-vec behind a measured need. Rewriting this file wholesale during
    prune/purge is acceptable precisely because the file is expected to stay
    small; that assumption is the trigger to revisit, and Task 8 measures it.
    """

    def __init__(self, directory: Path, retention_seconds: float | None) -> None:
        self._directory = Path(directory)
        self._retention_seconds = retention_seconds
        self._path = self._directory / OBSERVATIONS_FILENAME

    def append(self, observation: ObjectObservation) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(observation.to_json_dict()) + "\n")

    def all_observations(self) -> list[ObjectObservation]:
        if not self._path.exists():
            return []
        observations = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    observations.append(
                        object_observation_from_json_dict(json.loads(line))
                    )
                except (json.JSONDecodeError, KeyError, ValueError):
                    # A corrupt line must not make the whole history
                    # unreadable -- losing one record is strictly better
                    # than losing the store.
                    logger.warning(
                        "object memory: skipping unreadable record at %s:%s",
                        self._path,
                        line_number,
                    )
        return observations

    def last_seen(self, object_class: str) -> ObjectObservation | None:
        matching = [
            o for o in self.all_observations() if o.object_class == object_class
        ]
        if not matching:
            return None
        return max(matching, key=lambda o: o.observed_at)

    def purge(self) -> int:
        count = len(self.all_observations())
        if self._path.exists():
            self._path.unlink()
        return count

    def prune_expired(self, now: float) -> int:
        if self._retention_seconds is None:
            return 0
        observations = self.all_observations()
        cutoff = now - self._retention_seconds
        # recorded_at, not observed_at: retention is about how long WE
        # have held the data, which is the privacy-relevant clock. They
        # are equal today, but diverge the moment a real capture
        # timestamp is threaded through.
        kept = [o for o in observations if o.recorded_at >= cutoff]
        removed = len(observations) - len(kept)
        if removed:
            self._rewrite(kept)
        return removed

    def _rewrite(self, observations: list[ObjectObservation]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for observation in observations:
                handle.write(json.dumps(observation.to_json_dict()) + "\n")
        temporary.replace(self._path)
