"""Durable storage for observed documents.

Append-only JSONL plus atomic whole-file rewrite for prune and purge --
the shape World Builder and Object Memory independently converged on, and
the third consumer is where a pattern stops being a coincidence.

Rewrites operate on **raw dicts**, not on parsed records. Round-tripping
through the current dataclass would silently drop any key the schema does
not yet interpret, which is precisely the promise the reserved fields
exist to keep.
"""

import logging
import threading
from pathlib import Path

from tower.document_memory.records import (
    SCHEMA_VERSION,
    DocumentObservation,
    document_observation_from_json_dict,
)
from tower.storage import append_jsonl, read_raw_jsonl

logger = logging.getLogger(__name__)

DOCUMENTS_FILENAME = "documents.jsonl"
IMAGES_DIRNAME = "pages"
TEMP_SUFFIX = ".tmp"


class DocumentStoreError(Exception):
    """Base for every refusal this store makes."""


class UnsupportedSchemaError(DocumentStoreError):
    """A persisted record's schema version is not one this reader knows."""


class DocumentStore:
    """Everything Document Memory keeps, and the only thing that deletes it.

    Retention is a **window**, not "forever". Documents are the platform's
    clearest case of sensitive content, so an unbounded default would be
    the wrong one to pick by omission -- `06-PRIVACY-DATA.md` requires
    retention to be configurable rather than indefinite-by-default.
    """

    def __init__(
        self, directory, retention_seconds: float | None = None, clock=None
    ) -> None:
        import time

        if retention_seconds is not None and retention_seconds < 0:
            raise ValueError(
                f"retention_seconds must be non-negative or None, got "
                f"{retention_seconds!r}"
            )
        self._directory = Path(directory)
        self._retention_seconds = retention_seconds
        self._clock = clock or time.time
        self._path = self._directory / DOCUMENTS_FILENAME
        # Guards append against prune/purge: both replace the backing file,
        # which raises PermissionError on Windows if an append is in
        # flight and can silently lose the line on POSIX.
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def path(self) -> Path:
        return self._path

    @property
    def retention_seconds(self) -> float | None:
        return self._retention_seconds

    def images_dir(self) -> Path:
        return self._directory / IMAGES_DIRNAME

    # -- write ---------------------------------------------------------

    def append(self, document: DocumentObservation) -> None:
        with self._lock:
            append_jsonl(self._path, document.to_json_dict())

    def write_page_image(self, filename: str, jpeg_bytes: bytes) -> Path:
        """Persist one corrected page image. Off the default path.

        The single choke point for every pixel this cartridge ever
        writes, mirroring `world_builder.store.write_keyframe_image` and
        `capture.write_frame`. Whatever redaction policy is eventually
        chosen becomes a change to one function.

        fsync before rename, so a record that references an image is
        never left pointing at a partial file.
        """
        import os

        directory = self.images_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        temp_path = path.with_name(path.name + TEMP_SUFFIX)
        try:
            with temp_path.open("wb") as handle:
                handle.write(jpeg_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)
        return path

    # -- read ----------------------------------------------------------

    def read_all(self) -> list[DocumentObservation]:
        """Every stored document, oldest first.

        A record whose schema version is unknown is **skipped with a
        warning**, not guessed at and not fatal: one unreadable record
        must not make the whole memory unreadable.
        """
        raw_records, corrupt = read_raw_jsonl(self._path)
        if corrupt:
            logger.warning(
                "document store: skipped %s corrupt line(s) in %s",
                corrupt,
                self._path,
            )
        documents = []
        for record in raw_records:
            version = record.get("schema_version")
            if version != SCHEMA_VERSION:
                logger.warning(
                    "document store: skipping record with schema_version %r "
                    "(this reader knows %s)",
                    version,
                    SCHEMA_VERSION,
                )
                continue
            try:
                documents.append(document_observation_from_json_dict(record))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("document store: unparseable record skipped: %s", exc)
        return documents

    def read_one(self, document_id: str) -> DocumentObservation | None:
        for document in self.read_all():
            if document.document_id == document_id:
                return document
        return None

    def count(self) -> int:
        return len(self.read_all())

    def bytes_used(self) -> dict:
        """Storage growth, observable rather than assumed."""
        journal = self._path.stat().st_size if self._path.exists() else 0
        images = 0
        directory = self.images_dir()
        if directory.exists():
            images = sum(
                path.stat().st_size for path in directory.rglob("*") if path.is_file()
            )
        return {"journal": journal, "images": images, "total": journal + images}

    # -- delete --------------------------------------------------------

    def prune_expired(self, now: float | None = None) -> int:
        """Drop documents older than the retention window. Returns the count.

        No retention window means no pruning -- but the window is a
        constructor argument precisely so "forever" has to be chosen.
        """
        if self._retention_seconds is None:
            return 0
        now = self._clock() if now is None else now
        cutoff = now - self._retention_seconds
        return self._rewrite_keeping(
            lambda record: record.get("recorded_at", 0.0) >= cutoff
        )

    def purge(self, document_id: str | None = None) -> dict:
        """Really delete. Reports what it could NOT delete.

        A purge that cannot remove everything must never be presented as
        success -- `06-PRIVACY-DATA.md` requires real deletion, and a
        false claim of deletion is worse than an honest failure.
        """
        removed_images, retained_images = [], []

        if document_id is None:
            removed = self._rewrite_keeping(lambda record: False)
            targets = (
                list(self.images_dir().rglob("*")) if self.images_dir().exists() else []
            )
        else:
            keep_ids = {document_id}
            doomed = [
                page.image_relpath
                for document in self.read_all()
                if document.document_id in keep_ids
                for page in document.pages
                if page.image_relpath
            ]
            removed = self._rewrite_keeping(
                lambda record: record.get("document_id") != document_id
            )
            targets = [self._directory / relpath for relpath in doomed]

        for path in sorted(targets, key=lambda p: len(p.parts), reverse=True):
            try:
                if path.is_dir():
                    path.rmdir()
                elif path.exists():
                    path.unlink()
                removed_images.append(str(path))
            except OSError as exc:
                logger.warning("document store: could not remove %s: %s", path, exc)
                retained_images.append(str(path))

        return {
            "documents_removed": removed,
            "images_removed": len(removed_images),
            "images_retained": retained_images,
            "complete": not retained_images,
        }

    def _rewrite_keeping(self, keep) -> int:
        """Atomically rewrite the journal, returning how many were dropped."""
        import json
        import os

        with self._lock:
            raw_records, _ = read_raw_jsonl(self._path)
            kept = [record for record in raw_records if keep(record)]
            dropped = len(raw_records) - len(kept)
            if not self._path.exists():
                return 0
            temp_path = self._path.with_name(self._path.name + TEMP_SUFFIX)
            try:
                with temp_path.open("w", encoding="utf-8") as handle:
                    for record in kept:
                        handle.write(json.dumps(record) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                temp_path.replace(self._path)
            finally:
                temp_path.unlink(missing_ok=True)
            return dropped
