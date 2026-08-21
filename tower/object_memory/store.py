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

    def _read(self) -> tuple[list[ObjectObservation], int]:
        """Read observations and count unparseable lines.

        Returns:
            (observations, skipped_count) where skipped_count is the number
            of lines that could not be parsed.
        """
        if not self._path.exists():
            return [], 0
        observations = []
        skipped = 0
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
                    skipped += 1
        return observations, skipped

    def all_observations(self) -> list[ObjectObservation]:
        observations, _ = self._read()
        return observations

    def last_seen(self, object_class: str) -> ObjectObservation | None:
        matching = [
            o for o in self.all_observations() if o.object_class == object_class
        ]
        if not matching:
            return None
        return max(matching, key=lambda o: o.observed_at)

    def purge(self) -> int:
        """Delete all observations and the backing file.

        Returns the count of parseable observations removed. This may be fewer
        than the number of lines the file contained if there are unparseable
        lines. The entire file is deleted regardless.
        """
        count = len(self.all_observations())
        if self._path.exists():
            self._path.unlink()
        return count

    def prune_expired(self, now: float) -> int:
        if self._retention_seconds is None:
            return 0
        observations, skipped = self._read()
        cutoff = now - self._retention_seconds
        # recorded_at, not observed_at: retention is about how long WE
        # have held the data, which is the privacy-relevant clock. They
        # are equal today, but diverge the moment a real capture
        # timestamp is threaded through.
        kept = [o for o in observations if o.recorded_at >= cutoff]
        removed = len(observations) - len(kept)
        # Rewrite if valid records expired OR if unparseable lines exist.
        # An unparseable line cannot be shown to be within retention, so
        # letting it survive would mean retention silently fails to cover
        # data still at rest.
        if removed or skipped:
            self._rewrite(kept)
        # Return count of removed observations only, not unparseable lines:
        # corrupt lines were never observations, just data to clean up.
        return removed

    def _rewrite(self, observations: list[ObjectObservation]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for observation in observations:
                handle.write(json.dumps(observation.to_json_dict()) + "\n")
        temporary.replace(self._path)
