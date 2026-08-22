"""On-disk world storage.

Deliberately the same shape as tower/object_memory/store.py: atomic JSON
via temp+fsync+replace inside try/finally, append-only JSONL journals,
raw-dict rewrites, corrupt-line tolerance, and a real purge that removes
every artifact including temp files.

That store was chosen as the model over the numbered-checkpoint/HEAD/mmap
design in the readiness report for a concrete reason. Three Windows
behaviours were verified on this host:

    directory fsync           -> PermissionError [Errno 13]
    replace onto an OPEN dest -> PermissionError [WinError 5]
    unlink an mmap'd file     -> PermissionError [WinError 32]

The checkpoint design needs a validating-recovery path, a fallback policy,
and a retrying garbage collector purely to survive those. Two of the three
do not arise here at all: no directory is renamed and nothing is mmap'd.
The third is already solved by the lock this store inherits. V1 also has
no concurrent reader -- capture, build, and inspect are separate processes
-- so the isolation those subsystems buy has no consumer yet.

Derived output is a single rebuildable directory rather than numbered
checkpoints. Staleness is detected by comparing a digest of the inputs
that produced it, so a stale derived tree is detected rather than trusted.
"""

import hashlib
import os
import json
import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from tower.storage import (
    TEMP_SUFFIX,
    append_jsonl,
    read_json_closed,
    read_raw_jsonl,
    write_json_atomic,
)

from tower.world_builder.records import (
    Keyframe,
    KeyframeEdge,
    Session,
    World,
    keyframe_edge_from_json_dict,
    keyframe_from_json_dict,
    session_from_json_dict,
    world_from_json_dict,
)
from tower.world_builder.schema import (
    POSE_CONVENTION,
    SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

WORLD_FILENAME = "world.json"
SESSION_FILENAME = "session.json"
KEYFRAMES_FILENAME = "keyframes.jsonl"
EDGES_FILENAME = "edges.jsonl"
EVENTS_FILENAME = "events.jsonl"
LOCK_FILENAME = "LOCK"
DERIVED_DIRNAME = "derived"
DERIVED_MANIFEST = "manifest.json"
IMAGES_DIRNAME = "images"


class WorldStoreError(Exception):
    """Base for storage-layer failures."""


class UnsupportedSchemaError(WorldStoreError):
    """A persisted artifact declares a schema version we cannot read."""


class UnknownPoseConventionError(WorldStoreError):
    """A world declares a pose convention this build does not recognise.

    Raised rather than defaulted. A bare [x, y, z] read under the wrong
    convention does not fail loudly -- it yields a plausible, mirrored,
    wrong answer, and every downstream reference inherits the error.
    """


class WorldLockedError(WorldStoreError):
    """Another live process holds this world's writer lock."""


@dataclass(frozen=True)
class PurgeReport:
    """What a purge actually managed to delete.

    Carries `retained` because a purge that could not remove everything
    must never report success: 06-PRIVACY-DATA requires real deletion, and
    a false claim of deletion is worse than an honest failure.
    """

    removed: tuple[str, ...]
    retained: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.retained


def require_schema(data: dict, what: str) -> None:
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"{what} declares schema_version {version!r}, this build reads "
            f"{SCHEMA_VERSION}. Refusing rather than guessing at the meaning "
            "of fields written by a different version."
        )


def require_pose_convention(convention: dict) -> None:
    if convention != POSE_CONVENTION:
        differing = sorted(
            key
            for key in set(convention) | set(POSE_CONVENTION)
            if convention.get(key) != POSE_CONVENTION.get(key)
        )
        raise UnknownPoseConventionError(
            "world declares a pose convention this build does not recognise; "
            f"differing keys: {differing}. Refusing to interpret coordinates "
            "rather than silently reading them under the wrong convention."
        )






class WorldStore:
    """Filesystem storage for one root directory of worlds."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        # Guards journal appends (live path) against rewrite/purge, both
        # of which replace or unlink files out from under a concurrent
        # append -- PermissionError on Windows, silent line loss on POSIX.
        # Non-reentrant: locked public methods call `_locked` helpers, not
        # each other.
        self._lock = threading.Lock()

    # -- paths ---------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    def world_dir(self, world_id: str) -> Path:
        return self._root / "worlds" / world_id

    def world_path(self, world_id: str) -> Path:
        return self.world_dir(world_id) / WORLD_FILENAME

    def session_dir(self, world_id: str, session_id: str) -> Path:
        return self.world_dir(world_id) / "sessions" / session_id

    def session_path(self, world_id: str, session_id: str) -> Path:
        return self.session_dir(world_id, session_id) / SESSION_FILENAME

    def keyframes_path(self, world_id: str, session_id: str) -> Path:
        return self.session_dir(world_id, session_id) / KEYFRAMES_FILENAME

    def edges_path(self, world_id: str, session_id: str) -> Path:
        return self.session_dir(world_id, session_id) / EDGES_FILENAME

    def events_path(self, world_id: str, session_id: str) -> Path:
        return self.session_dir(world_id, session_id) / EVENTS_FILENAME

    def images_dir(self, world_id: str, session_id: str) -> Path:
        return self.session_dir(world_id, session_id) / IMAGES_DIRNAME

    def derived_dir(self, world_id: str) -> Path:
        return self.world_dir(world_id) / DERIVED_DIRNAME

    def lock_path(self, world_id: str) -> Path:
        return self.world_dir(world_id) / LOCK_FILENAME

    # -- worlds --------------------------------------------------------

    def list_world_ids(self) -> list[str]:
        worlds_root = self._root / "worlds"
        if not worlds_root.exists():
            return []
        return sorted(
            entry.name
            for entry in worlds_root.iterdir()
            if entry.is_dir() and (entry / WORLD_FILENAME).exists()
        )

    def write_world(self, world: World) -> None:
        with self._lock:
            write_json_atomic(self.world_path(world.world_id), world.to_json_dict())

    def read_world(self, world_id: str) -> World:
        path = self.world_path(world_id)
        if not path.exists():
            raise WorldStoreError(f"no world at {path}")
        data = read_json_closed(path)
        require_schema(data, f"world {world_id}")
        require_pose_convention(data["pose_convention"])
        return world_from_json_dict(data)

    # -- sessions ------------------------------------------------------

    def write_session(self, session: Session) -> None:
        with self._lock:
            write_json_atomic(
                self.session_path(session.world_id, session.session_id),
                session.to_json_dict(),
            )

    def read_session(self, world_id: str, session_id: str) -> Session:
        data = read_json_closed(self.session_path(world_id, session_id))
        require_schema(data, f"session {session_id}")
        return session_from_json_dict(data)

    def list_session_ids(self, world_id: str) -> list[str]:
        sessions_root = self.world_dir(world_id) / "sessions"
        if not sessions_root.exists():
            return []
        return sorted(
            entry.name
            for entry in sessions_root.iterdir()
            if entry.is_dir() and (entry / SESSION_FILENAME).exists()
        )

    # -- keyframes and edges -------------------------------------------

    def append_keyframe(self, world_id: str, keyframe: Keyframe) -> None:
        with self._lock:
            append_jsonl(
                self.keyframes_path(world_id, keyframe.session_id),
                keyframe.to_json_dict(),
            )

    def read_keyframes(self, world_id: str, session_id: str) -> list[Keyframe]:
        raw_records, _ = read_raw_jsonl(self.keyframes_path(world_id, session_id))
        return _parse_all(raw_records, keyframe_from_json_dict, "keyframe")

    def clear_edges(self, world_id: str, session_id: str) -> None:
        """Drop the edge journal before a rebuild recomputes it.

        Edges between keyframes are recomputed from the keyframes on every
        build, so despite living in an append-only journal they are
        derived. Appending without clearing duplicates the whole set per
        rebuild.
        """
        with self._lock:
            self.edges_path(world_id, session_id).unlink(missing_ok=True)

    def append_edge(
        self, world_id: str, session_id: str, edge: KeyframeEdge
    ) -> None:
        with self._lock:
            append_jsonl(self.edges_path(world_id, session_id), edge.to_json_dict())

    def read_edges(self, world_id: str, session_id: str) -> list[KeyframeEdge]:
        raw_records, _ = read_raw_jsonl(self.edges_path(world_id, session_id))
        return _parse_all(raw_records, keyframe_edge_from_json_dict, "edge")

    def append_event(self, world_id: str, session_id: str, event) -> None:
        with self._lock:
            append_jsonl(
                self.events_path(world_id, session_id), event.to_json_dict()
            )

    def read_events(self, world_id: str, session_id: str) -> list[dict]:
        raw_records, _ = read_raw_jsonl(self.events_path(world_id, session_id))
        return raw_records

    # -- images --------------------------------------------------------

    def write_keyframe_image(
        self, world_id: str, session_id: str, filename: str, jpeg_bytes: bytes
    ) -> Path:
        """Persist one keyframe image, durably, BEFORE its journal line.

        The ordering is deliberate and asymmetric: a journal line pointing
        at a missing image is corruption, while an image with no journal
        line is a harmless orphan that purge and verification both sweep.
        Never invert this.
        """
        images = self.images_dir(world_id, session_id)
        images.mkdir(parents=True, exist_ok=True)
        path = images / filename
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

    # -- derived -------------------------------------------------------

    def derived_manifest_path(self, world_id: str) -> Path:
        return self.derived_dir(world_id) / DERIVED_MANIFEST

    def clear_derived(self, world_id: str) -> None:
        """Delete the whole derived tree.

        Safe by construction: every byte under derived/ is rebuildable
        from the authoritative journals plus the keyframe images. This is
        also the operation the "derived is genuinely derived" test drives.
        """
        derived = self.derived_dir(world_id)
        if derived.exists():
            shutil.rmtree(derived, ignore_errors=True)

    def write_derived_manifest(self, world_id: str, manifest: dict) -> None:
        write_json_atomic(self.derived_manifest_path(world_id), manifest)

    def read_derived_manifest(self, world_id: str) -> dict | None:
        path = self.derived_manifest_path(world_id)
        if not path.exists():
            return None
        try:
            data = read_json_closed(path)
        except json.JSONDecodeError:
            logger.warning("world builder: derived manifest unreadable at %s", path)
            return None
        return data

    def write_derived(
        self, world_id: str, session_id: str, *, poses, points, manifest
    ) -> None:
        """Write the rebuildable reconstruction outputs.

        Poses and points are JSON rather than .npy: at V1 scale a session
        is hundreds of poses and low tens of thousands of points, JSON
        round-trips exactly without a dtype contract to get wrong, and it
        stays inspectable by eye. The trigger to switch to .npy is a world
        large enough that a viewer needs partial or memory-mapped reads --
        the same "small enough that rewriting wholesale is fine" reasoning
        object memory's store already documents for itself.
        """
        # Under the same lock as purge_world. Without it an in-flight
        # build can recreate a world directory that purge has just
        # reported as completely deleted -- and the resurrected tree is
        # then invisible to list_world_ids(), so no later purge targets it.
        with self._lock:
            derived = self.derived_dir(world_id) / session_id
            write_json_atomic(derived / "poses.json", {"poses": poses})
            write_json_atomic(derived / "points.json", {"points": points})
            write_json_atomic(self.derived_manifest_path(world_id), manifest)

    def read_derived(
        self, world_id: str, session_id: str, *, verify: bool = True
    ) -> dict | None:
        """Read the derived reconstruction, refusing stale output.

        The digest is checked by default rather than on request. Serving a
        derived tree that no longer matches the journal that produced it
        is silent corruption of exactly the kind this store is built to
        prevent: the numbers look fine, they are just answers to an older
        question. Returning None makes a stale tree indistinguishable from
        an absent one, which is the honest outcome -- both mean "rebuild".
        """
        if verify:
            digest = compute_input_digest(
                self.read_keyframes(world_id, session_id)
            )
            if not self.derived_is_current(world_id, digest):
                logger.warning(
                    "world builder: derived output for %s is stale; "
                    "treating as absent",
                    world_id,
                )
                return None
        derived = self.derived_dir(world_id) / session_id
        poses_path = derived / "poses.json"
        points_path = derived / "points.json"
        if not poses_path.exists() or not points_path.exists():
            return None
        try:
            return {
                "poses": read_json_closed(poses_path)["poses"],
                "points": read_json_closed(points_path)["points"],
            }
        except (json.JSONDecodeError, KeyError):
            logger.warning("world builder: derived output unreadable for %s", world_id)
            return None

    def derived_is_current(self, world_id: str, input_digest: str) -> bool:
        manifest = self.read_derived_manifest(world_id)
        if manifest is None:
            return False
        return (
            manifest.get("schema_version") == SCHEMA_VERSION
            and manifest.get("input_digest") == input_digest
        )

    def world_bytes(self, world_id: str) -> dict:
        """On-disk size of one world, split by tier.

        Reported rather than capped. A hard cap that stopped mapping
        mid-session would trade a storage problem for a silently truncated
        world, which is worse: the operator would get an incomplete map
        with no obvious sign it was cut short. Making growth visible lets
        retention be decided deliberately -- and the derived figure is the
        reclaimable half, since every byte under derived/ is rebuildable.
        """
        directory = self.world_dir(world_id)
        if not directory.exists():
            return {"total": 0, "images": 0, "derived": 0, "journals": 0}

        totals = {"total": 0, "images": 0, "derived": 0, "journals": 0}
        derived_root = self.derived_dir(world_id)
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            size = path.stat().st_size
            totals["total"] += size
            if path.suffix == ".jpg":
                totals["images"] += size
            elif derived_root in path.parents:
                totals["derived"] += size
            elif path.suffix in (".jsonl", ".json"):
                totals["journals"] += size
        return totals

    # -- locking -------------------------------------------------------

    def acquire_writer_lock(self, world_id: str) -> None:
        """Take the single-writer lock, reclaiming it from a dead process.

        Liveness by pid rather than by timeout. A stale-lock timer has to
        guess how long a legitimate writer might pause; asking the OS
        whether the pid is still running does not guess, and psutil is
        already a dependency.
        """
        path = self.lock_path(world_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                holder = read_json_closed(path)
            except json.JSONDecodeError:
                holder = {}
            pid = holder.get("pid")
            if isinstance(pid, int) and _pid_is_running(pid) and pid != os.getpid():
                raise WorldLockedError(
                    f"world {world_id} is locked by live pid {pid}; refusing a "
                    "second writer"
                )
            logger.warning(
                "world builder: reclaiming lock on %s held by pid %r", world_id, pid
            )
        write_json_atomic(path, {"pid": os.getpid()})

    def release_writer_lock(self, world_id: str) -> None:
        self.lock_path(world_id).unlink(missing_ok=True)

    # -- purge ---------------------------------------------------------

    def purge_world(self, world_id: str) -> PurgeReport:
        """Really delete a world: images, journals, derived tree, temps.

        Reports what could not be removed rather than claiming success.
        06-PRIVACY-DATA requires real deletion, and the failure mode this
        guards against has already shipped once in this repository: a
        purge that returned a success count while leaving a temp file
        holding live data behind.
        """
        with self._lock:
            world_dir = self.world_dir(world_id)
            if not world_dir.exists():
                return PurgeReport(removed=(), retained=())

            removed: list[str] = []
            retained: list[str] = []

            for path in sorted(
                world_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True
            ):
                try:
                    if path.is_dir():
                        path.rmdir()
                    else:
                        path.unlink()
                    removed.append(str(path))
                except OSError as exc:
                    logger.warning("world builder: could not remove %s: %s", path, exc)
                    retained.append(str(path))

            try:
                world_dir.rmdir()
                removed.append(str(world_dir))
            except OSError as exc:
                logger.warning(
                    "world builder: could not remove %s: %s", world_dir, exc
                )
                retained.append(str(world_dir))

            return PurgeReport(removed=tuple(removed), retained=tuple(retained))


def compute_input_digest(keyframes: list[Keyframe]) -> str:
    """Digest the authoritative inputs a derived build consumed.

    Lets a later read detect that derived output no longer matches the
    journal that produced it, instead of trusting whatever is on disk.
    """
    hasher = hashlib.sha256()
    for keyframe in keyframes:
        hasher.update(keyframe.keyframe_id.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _parse_all(raw_records: list[dict], parser, what: str) -> list:
    parsed = []
    for raw in raw_records:
        try:
            require_schema(raw, what)
            parsed.append(parser(raw))
        except (KeyError, ValueError, UnsupportedSchemaError):
            # Valid JSON, schema this build cannot interpret. Not
            # corruption: skipped from the parsed view without touching
            # the file, matching object memory's two-stage discipline.
            logger.warning(
                "world builder: skipping %s record with an unrecognised schema",
                what,
            )
    return parsed


def _pid_is_running(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:  # pragma: no cover - psutil is a hard dependency
        return False
