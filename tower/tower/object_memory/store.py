import json
import logging
import os
import threading
import time
from pathlib import Path

from tower.object_memory.records import (
    ObjectObservation,
    object_observation_from_json_dict,
)

logger = logging.getLogger(__name__)

OBSERVATIONS_FILENAME = "observations.jsonl"
TEMP_SUFFIX = ".jsonl.tmp"


class ObservationStore:
    """Append-only JSONL store for one module's observations.

    JSONL, not SQLite: at V1 scale a single module's observation history is
    small, and the canonical-memory research explicitly sequences SQLite +
    sqlite-vec behind a measured need. Rewriting this file wholesale during
    prune/purge is acceptable precisely because the file is expected to stay
    small; that assumption is the trigger to revisit, and Task 8 measures it.

    Rewrites (prune, purge's cleanup) operate on raw JSON dicts, not on
    parsed ObjectObservation instances. That is deliberate: round-tripping
    through the current dataclass schema would silently drop any key the
    schema does not interpret (spatial_ref/external_refs today, whatever
    is reserved next tomorrow), breaking records.py's promise that a
    future cross-module need does not require rewriting already-persisted
    records. Rewriting raw dicts keeps that promise true.
    """

    def __init__(
        self,
        directory: Path,
        retention_seconds: float | None,
        *,
        clock=time.time,
    ) -> None:
        if retention_seconds is not None and retention_seconds < 0:
            raise ValueError(
                "retention_seconds must be non-negative or None, got "
                f"{retention_seconds!r}"
            )
        self._directory = Path(directory)
        self._retention_seconds = retention_seconds
        # Injected so a READ can apply the retention cutoff without every
        # caller having to pass the time in. prune_expired keeps its
        # explicit `now`, so the deterministic tests it was written for
        # read exactly as before; this only supplies a default.
        self._clock = clock
        self._path = self._directory / OBSERVATIONS_FILENAME
        self._temp_path = self._path.with_suffix(TEMP_SUFFIX)
        # Guards append (called from the live frame path) against purge
        # and prune_expired (called from FastAPI's threadpool per a later
        # task): both of the latter unlink/replace the backing file out
        # from under a concurrent append, which raises PermissionError on
        # Windows and can silently lose the appended line on POSIX.
        # Non-reentrant by design: locked public methods never call each
        # other -- they call the `_locked`-suffixed helpers below, which
        # assume the lock is already held.
        self._lock = threading.Lock()

    def append(self, observation: ObjectObservation) -> None:
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(observation.to_json_dict()) + "\n")

    def _read_raw_records(self) -> tuple[list[dict], int]:
        """Read the backing file as JSON objects, without schema validation.

        Returns the parsed dicts plus a count of lines that were not valid
        JSON at all. That is true corruption, distinct from a well-formed
        record whose fields this version's schema cannot interpret --
        callers decide separately, and differently, how to treat each.
        Must be called with the lock held.
        """
        if not self._path.exists():
            return [], 0
        raw_records = []
        corrupt = 0
        with self._path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "object memory: skipping corrupt line at %s:%s",
                        self._path,
                        line_number,
                    )
                    corrupt += 1
        return raw_records, corrupt

    def _parse_observations(self, raw_records: list[dict]) -> list[ObjectObservation]:
        observations = []
        for raw in raw_records:
            try:
                observations.append(object_observation_from_json_dict(raw))
            except (KeyError, ValueError):
                # Valid JSON, schema mismatch (missing field added since,
                # unknown enum label, ...). Not corruption: skip it from
                # the parsed view without touching the file or counting
                # it as a removed/unparseable line.
                logger.warning(
                    "object memory: skipping record with an unrecognised "
                    "schema in %s",
                    self._path,
                )
        return observations

    def _retention_cutoff(self) -> float | None:
        """The oldest recorded_at a read may still serve; None means no bound."""
        if self._retention_seconds is None:
            return None
        return self._clock() - self._retention_seconds

    @staticmethod
    def _is_within_retention(raw: dict, cutoff: float | None) -> bool:
        """Shared by reads and prune so the two can never disagree.

        recorded_at, not observed_at: retention is about how long WE have
        held the data, which is the privacy-relevant clock. They are
        equal today, but diverge the moment a real capture timestamp is
        threaded through. A missing or non-numeric recorded_at can't be
        shown to be within retention, so it is treated as expired.
        (bool is excluded: it's an int subclass in Python.)
        """
        if cutoff is None:
            return True
        recorded_at = raw.get("recorded_at")
        is_numeric = isinstance(recorded_at, (int, float)) and not isinstance(
            recorded_at, bool
        )
        return is_numeric and recorded_at >= cutoff

    def _all_observations_locked(
        self, cutoff: float | None
    ) -> list[ObjectObservation]:
        raw_records, _ = self._read_raw_records()
        if cutoff is not None:
            raw_records = [
                raw for raw in raw_records if self._is_within_retention(raw, cutoff)
            ]
        return self._parse_observations(raw_records)

    def _read_cutoff(self, include_expired: bool) -> float | None:
        return None if include_expired else self._retention_cutoff()

    def all_observations(
        self, *, include_expired: bool = False
    ) -> list[ObjectObservation]:
        """Every observation still within retention.

        Filtering is the DEFAULT and the opt-out has to be asked for by
        name. Retention under 06-PRIVACY-DATA.md is a promise about how
        long data stays AVAILABLE, not merely about how long it sits on
        disk; a read that ignored the cutoff made that promise true only
        for whoever remembered to call prune_expired(), which on a tower
        that stays up for days is nobody.

        `include_expired=True` exists for maintenance paths that must see
        what is physically on disk -- purge counting what it deletes, an
        operator auditing the file. It is never the right answer for
        anything a wearer will be shown.
        """
        with self._lock:
            return self._all_observations_locked(self._read_cutoff(include_expired))

    def last_seen(
        self, object_class: str, *, include_expired: bool = False
    ) -> ObjectObservation | None:
        with self._lock:
            matching = [
                o
                for o in self._all_observations_locked(
                    self._read_cutoff(include_expired)
                )
                if o.object_class == object_class
            ]
        if not matching:
            return None
        return max(matching, key=lambda o: o.observed_at)

    def purge(self) -> int:
        """Delete all observations and every file artifact the store owns.

        Returns the count of parseable observations removed. This may be
        fewer than the number of lines the file contained if there are
        unparseable lines. Both the main file and a stale rewrite temp
        file (left behind by a crash mid-_rewrite) are removed regardless.
        """
        with self._lock:
            # Counted WITHOUT the retention cutoff: purge deletes the
            # files outright, so it must report what it actually removed
            # rather than only the part a read was still willing to serve.
            count = len(self._all_observations_locked(None))
            for artifact in (self._path, self._temp_path):
                artifact.unlink(missing_ok=True)
            return count

    def prune_expired(self, now: float | None = None) -> int:
        """Delete expired records from disk. Reads already refuse to serve them.

        Still required, and not merely tidiness: read-time filtering stops
        expired data being SERVED, while 06-PRIVACY-DATA.md wants it gone.
        `now` stays explicit so the deterministic tests keep working, and
        defaults to the store's clock for a caller with nothing to say.
        """
        if self._retention_seconds is None:
            return 0
        if now is None:
            now = self._clock()
        with self._lock:
            raw_records, corrupt = self._read_raw_records()
            cutoff = now - self._retention_seconds
            kept = []
            removed = 0
            for raw in raw_records:
                if self._is_within_retention(raw, cutoff):
                    kept.append(raw)
                else:
                    removed += 1
            # Rewrite if valid records expired OR if corrupt lines exist.
            # A corrupt line cannot be shown to be within retention, so
            # letting it survive would mean retention silently fails to
            # cover data still at rest.
            if removed or corrupt:
                self._rewrite_locked(kept)
            # Return count of removed observations only, not corrupt
            # lines: corrupt lines were never observations, just data to
            # clean up.
            return removed

    def _rewrite_locked(self, raw_records: list[dict]) -> None:
        # try/finally so a failure anywhere in the write leaves nothing
        # behind: no observations.jsonl.tmp with a live copy of data that
        # nothing else ever reads, prunes, or deletes. If replace()
        # succeeds the temp file is already gone, so the unlink is a
        # harmless no-op; if anything raises before that, it cleans up.
        try:
            with self._temp_path.open("w", encoding="utf-8") as handle:
                for raw in raw_records:
                    handle.write(json.dumps(raw) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._temp_path.replace(self._path)
        finally:
            self._temp_path.unlink(missing_ok=True)
