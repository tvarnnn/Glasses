"""Recording raw frames to disk, as an explicit dataset session.

SHARED infrastructure, not a cartridge's. It lives here rather than under
tower/world_builder/ because the transport arms it and any cartridge might
want it -- Text/Document will want OCR-quality stills, Object Memory
occasional high-value frames. Versioning a recording made by the SHARED
transport with a CARTRIDGE's schema constant would mean a geometry-driven
schema bump invalidating capture journals that have nothing to do with
geometry, so this module owns its own version and time basis.

Separate from any keyframe corpus on purpose. A mapper persists a SELECTED
subset of frames; this records everything, because the two jobs it exists
for both need unselected frames:

- camera calibration, which needs board views chosen by a human holding a
  board, not by a parallax policy;
- re-running the V0.9.3 experiments on real DAT footage, which is the
  standing acceptance gate on every dataset-based conclusion the project
  has drawn.

Neither is possible today: a filesystem search found no stored Ray-Ban
footage anywhere, which is why this exists at all.

It is OFF BY DEFAULT and bounded in both duration and bytes. Under
06-PRIVACY-DATA this is an Explicit Dataset-Recording Session: manually
started and stopped, bounded, purgeable, and visibly recording. It is not
incidental capture, and it must never become the default path.
"""

import logging
import time
from dataclasses import dataclass, field

from tower.storage import append_jsonl, new_id, read_raw_jsonl, write_json_atomic

# This module's own schema version and clock label. Deliberately NOT
# imported from a cartridge: a recording made by shared transport must not
# be versioned by a consumer's schema.
CAPTURE_SCHEMA_VERSION = 1
TIME_BASIS = "tower-receipt"

END_REASON_STOP = "stop"
END_REASON_DISCONNECT = "disconnect"
END_REASON_BOUNDED_LIMIT = "bounded_limit"

logger = logging.getLogger(__name__)

CAPTURE_FILENAME = "capture.json"
FRAMES_FILENAME = "frames.jsonl"
FRAMES_DIRNAME = "frames"


@dataclass(frozen=True)
class CaptureLimits:
    """Hard bounds. Rule 15 -- no unbounded operation on the live path."""

    max_seconds: float = 900.0
    max_bytes: int = 1_073_741_824


@dataclass
class CaptureStatus:
    capture_id: str
    started_at: float
    frames_written: int = 0
    bytes_written: int = 0
    ended_at: float | None = None
    end_reason: str | None = None
    rejected: dict = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.ended_at is None


class CaptureRecorder:
    """Writes raw frames plus a journal into one capture directory.

    Every persisted pixel passes through `write_frame`. That single choke
    point is deliberate: whatever redaction policy is eventually chosen,
    it becomes a change to one function rather than an archaeology
    exercise across the frame path. This decides no policy -- it makes one
    implementable.
    """

    def __init__(self, root, limits: CaptureLimits | None = None, clock=time.time):
        from pathlib import Path

        self._root = Path(root)
        self._limits = limits or CaptureLimits()
        self._clock = clock
        self._status: CaptureStatus | None = None

    @property
    def status(self) -> CaptureStatus | None:
        return self._status

    @property
    def is_recording(self) -> bool:
        return self._status is not None and self._status.is_open

    def capture_dir(self, capture_id: str):
        return self._root / "captures" / capture_id

    def start(self) -> str:
        capture_id = new_id()
        self._status = CaptureStatus(
            capture_id=capture_id, started_at=self._clock()
        )
        write_json_atomic(
            self.capture_dir(capture_id) / CAPTURE_FILENAME,
            self._manifest(self._status),
        )
        return capture_id

    def write_frame(
        self,
        raw_bytes: bytes,
        *,
        source_seq: int,
        wire_seq: int | None = None,
        tx_seq: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> bool:
        """Persist one frame. Returns False once a bound is reached.

        Never raises for a bound: hitting a limit is an expected, recorded
        outcome, not an error, and turning it into an exception on the
        frame path would put session teardown at the mercy of a disk quota.
        """
        if not self.is_recording:
            return False

        status = self._status
        now = self._clock()
        if now - status.started_at >= self._limits.max_seconds:
            self.stop(END_REASON_BOUNDED_LIMIT)
            return False
        if status.bytes_written + len(raw_bytes) > self._limits.max_bytes:
            self.stop(END_REASON_BOUNDED_LIMIT)
            return False

        directory = self.capture_dir(status.capture_id)
        frames_dir = directory / FRAMES_DIRNAME
        frames_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{source_seq:08d}.jpg"
        path = frames_dir / filename

        # Image first with fsync, journal line second. A journal line
        # pointing at a missing image is corruption; an orphan image is
        # harmless and gets swept by purge.
        import os

        temp_path = path.with_name(path.name + ".tmp")
        try:
            with temp_path.open("wb") as handle:
                handle.write(raw_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)

        append_jsonl(
            directory / FRAMES_FILENAME,
            {
                "schema_version": CAPTURE_SCHEMA_VERSION,
                "source_seq": source_seq,
                "wire_seq": wire_seq,
                "tx_seq": tx_seq,
                "received_at": now,
                "time_basis": TIME_BASIS,
                "relpath": f"{FRAMES_DIRNAME}/{filename}",
                "byte_count": len(raw_bytes),
                "width": width,
                "height": height,
            },
        )
        status.frames_written += 1
        status.bytes_written += len(raw_bytes)
        return True

    def stop(self, reason: str = END_REASON_STOP) -> CaptureStatus | None:
        if self._status is None or not self._status.is_open:
            return self._status
        self._status.ended_at = self._clock()
        self._status.end_reason = reason
        write_json_atomic(
            self.capture_dir(self._status.capture_id) / CAPTURE_FILENAME,
            self._manifest(self._status),
        )
        return self._status

    def read_frames(self, capture_id: str) -> list[dict]:
        raw_records, _ = read_raw_jsonl(
            self.capture_dir(capture_id) / FRAMES_FILENAME
        )
        return raw_records

    def purge(self, capture_id: str) -> tuple[int, int]:
        """Really delete a capture. Returns (removed, retained).

        Retained is reported rather than swallowed: a purge that could not
        remove everything must not claim success, because 06-PRIVACY-DATA
        requires real deletion and the caller has no other way to learn
        the imagery is still on disk.
        """
        directory = self.capture_dir(capture_id)
        if not directory.exists():
            return 0, 0
        removed = retained = 0
        for path in sorted(
            directory.rglob("*"), key=lambda p: len(p.parts), reverse=True
        ):
            try:
                path.rmdir() if path.is_dir() else path.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("capture: could not remove %s: %s", path, exc)
                retained += 1
        try:
            directory.rmdir()
            removed += 1
        except OSError:
            retained += 1
        return removed, retained

    def _manifest(self, status: CaptureStatus) -> dict:
        return {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_id": status.capture_id,
            "started_at": status.started_at,
            "ended_at": status.ended_at,
            "end_reason": status.end_reason,
            "time_basis": TIME_BASIS,
            "frames_written": status.frames_written,
            "bytes_written": status.bytes_written,
            "max_seconds": self._limits.max_seconds,
            "max_bytes": self._limits.max_bytes,
            "retains_raw_imagery": True,
            "redaction": "none",
            "privacy_tags": ["raw-imagery", "first-person", "dataset-recording"],
        }
