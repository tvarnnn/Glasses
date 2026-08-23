"""The World Builder status producer: a READER, never a second pipeline.

The web process does not build worlds and must not start. Reconstruction
runs in its own process (`scripts/world_build_session.py`), which is the
decision `plan.md` 28 protects and the closeout report defends at length:
the frame path pays nothing for a rebuild precisely because the rebuild is
somewhere else. This module reads what that process has already persisted
and shapes it for the wire. It calls no engine method, holds no engine
object, and starts nothing.

Everything reported here is derived from four things on disk:

    LOCK              a pid file, held for the LIFETIME OF A SESSION
    events.jsonl      the append-only journal, dense event_id per session
    session.json      written at start and rewritten at stop -- see below
    derived/manifest  what the last build produced

The single most important fact about the second and third of those:

    session.json is written at start_session() with frames_observed=0 and
    keyframes_accepted=0, and is not rewritten until stop_session().

(engine.py start_session, stop_session.) So DURING a live session those
counts on disk are stale zeros. Reporting them would be the exact failure
`IOS-to-Tower.md` 1.8 warns about -- "nil and 0 are different claims and
are kept different all the way to the screen" -- with the added insult
that the zero looks like a measurement. The live keyframe count is
therefore counted from `keyframe_accepted` events instead, and
`frames_observed` is reported as UNAVAILABLE while a session is live,
because no event is written for an ordinary rejected frame (engine.py
observe: `_note_rejected` without an append for every reason except
malformed_frame). Tower genuinely does not know it yet, and says so.
"""

import json
import logging
import math
from pathlib import Path

from tower.results.contracts import TIME_BASIS
from tower.results.envelope import Snapshot, compute_revision
from tower.world_builder.records import format_distance
from tower.world_builder.schema import (
    INTRINSICS_SOURCE_UNKNOWN,
    POSE_STATUS_ANCHOR,
    POSE_STATUS_SOLVED,
    SCHEMA_VERSION,
    SCALE_ESTIMATED,
    SCALE_MEASURED,
    SCALE_RELATIVE,
    SCALE_UNKNOWN,
)
from tower.world_builder.store import WorldStore, WorldStoreError

logger = logging.getLogger(__name__)

# Lifecycle, named for the evidence rather than for an intention. Tower
# cannot see a process's intent; it can see a lock, a journal and a
# manifest.
LIFECYCLE_RECEIVING = "receiving"
# NOT "finalizing". An independent audit of the on-disk state proved
# that while build() runs, the files are BYTE-IDENTICAL to "stopped and
# never built" and to "stopped and the build crashed": build() writes
# nothing until it finishes and emits no event, and the writer lock is
# already released by then (engine.stop_session releases before the
# driver calls build). So Tower cannot observe that work is continuing,
# and a state named "finalizing" would assert exactly that.
#
# This name says only what is visible: capture stopped, and the stored
# geometry is not current with the keyframes. iOS may render its own
# .finalizing from it -- lifecycle.build_in_progress carries the caveat
# that makes that an informed choice rather than an inherited guess.
LIFECYCLE_STOPPED_UNBUILT = "stopped_unbuilt"
LIFECYCLE_READY = "ready"
LIFECYCLE_FAILED = "failed"
LIFECYCLE_IDLE = "idle"
LIFECYCLE_UNAVAILABLE = "unavailable"

# Tracking. `limited` is deliberately NEVER emitted -- see _tracking_block.
TRACKING_GOOD = "good"
TRACKING_LOST = "lost"
TRACKING_UNKNOWN = "unknown"

CALIBRATION_UNKNOWN = "unknown"
CALIBRATION_UNCALIBRATED = "uncalibrated"
CALIBRATION_CALIBRATED = "calibrated"

# iOS's vocabulary for scale (IOS-to-Tower.md 1.5), mapped from Tower's.
# `unknown` maps to nothing on purpose: a figure that cannot be labelled
# with one of the three is not sent as a distance at all, which leaves
# iOS's rule -- "a figure that arrives unlabelled is simply not shown as a
# distance" -- with nothing to catch.
SCALE_SEMANTICS = {
    SCALE_RELATIVE: "relative",
    SCALE_ESTIMATED: "inferredMetric",
    SCALE_MEASURED: "measuredMetric",
}

# Fields whose value advances without anything having happened. Excluded
# from the change revision so a UI can tell new data from repeated data
# (IOS-to-Tower.md 1.2).
VOLATILE_PATHS = ("progress.mapping_seconds",)

# The Tower's own name for what it builds. IOS-to-Tower.md 1.3 asks for
# exactly this and promises to display it verbatim and never parse it, so
# it is prose, not an identifier.
GEOMETRY_REPRESENTATION = "sparse point cloud"


class _FileCache:
    """Parse a file only when it has actually changed.

    A measured necessity, not an optimisation. `WorldStore.read_events`
    reads and JSON-parses the ENTIRE journal on every call -- the
    `after_event_id` cursor filters *after* the full read (store.py), so a
    cursor buys nothing. Measured on this host:

        100 events        0.27 ms
        1,000 events      2.35 ms
        10,000 events    26.6 ms
        50,000 events   209 ms

    against a measured frame reply of 1.98 ms average and 15.25 ms worst
    ever observed. A poll loop doing that read twice a second would spend
    more time parsing a journal than the Tower spends answering frames,
    and `asyncio.to_thread` does not save it: the work is `json.loads`,
    which holds the GIL, so offloading turns one 35 ms stall into many
    5 ms ones.

    A `stat()` costs **0.0135 ms** -- roughly 2,000x less at 10k events.
    And because every file here is either append-only or replaced whole,
    (size, mtime_ns) is a sound fingerprint: an append always grows the
    file, and an atomic replace always changes both.

    This also shrinks a genuine WINDOWS hazard. An open read handle in
    this process makes `Path.replace()` fail with WinError 5 in the
    *builder* process -- so a reader that opens files it did not need to
    can break the writer it is only supposed to be watching. Not opening
    them is the strongest available mitigation.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict = {}

    def read(self, path, reader):
        try:
            stat = path.stat()
            fingerprint = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            # Absent or unreadable. Do not cache: a file that appears
            # later must be picked up on the next poll.
            self._entries.pop(str(path), None)
            return reader()
        key = str(path)
        cached = self._entries.get(key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        value = reader()
        self._entries[key] = (fingerprint, value)
        return value

    def fingerprint(self, path):
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns)


class WorldBuilderStatusProducer:
    """Builds one status snapshot per call. Holds only a small cache."""

    def __init__(self, world_root, clock) -> None:
        self._root = Path(world_root)
        self._clock = clock
        self._files = _FileCache()
        # Path length needs the full poses file, which the manifest does
        # not summarise. Reading it on every poll would be the one
        # genuinely unbounded read in this module, so it is computed once
        # per geometry revision and remembered. One entry per target,
        # replaced rather than accumulated -- see _path_length.
        self._path_length_cache: dict[str, tuple[str, dict | None]] = {}

    # -- target selection ---------------------------------------------

    def resolve(self, world_id: str | None, session_id: str | None):
        """Pick which world and session to report on.

        An explicit world_id is iOS's inspection mode
        (`WorldInspectionMode.inspecting(worldID:)`, 1.7), where "there is
        no capture to start, and a counter that moved would be a bug".
        With none given, a live session is preferred over the most
        recently updated world, because a client that did not name one is
        asking about now.
        """
        store = WorldStore(self._root)
        try:
            world_ids = store.list_world_ids()
        except OSError:
            return None, None, "world root is not readable"
        if not world_ids:
            return None, None, "no worlds exist under this Tower's world root"

        if world_id is not None:
            if world_id not in world_ids:
                return None, None, f"no world with id {world_id!r}"
            chosen = world_id
        else:
            chosen = self._most_relevant(store, world_ids)
            if chosen is None:
                return None, None, "no world could be read"

        if session_id is not None:
            if session_id not in store.list_session_ids(chosen):
                return (
                    None,
                    None,
                    f"world {chosen!r} has no session with id {session_id!r}",
                )
            return chosen, session_id, None

        sessions = store.list_session_ids(chosen)
        if not sessions:
            return chosen, None, None
        return chosen, self._latest_session(store, chosen, sessions), None

    def _most_relevant(self, store, world_ids):
        """A live world if one exists, else the most recently updated."""
        live = [wid for wid in world_ids if _lock_holder(store, wid) is not None]
        candidates = live or world_ids
        best, best_at = None, -math.inf
        for wid in candidates:
            try:
                world = store.read_world(wid)
            except (WorldStoreError, KeyError, OSError):
                continue
            if world.updated_at > best_at:
                best, best_at = wid, world.updated_at
        return best

    def _latest_session(self, store, world_id, session_ids):
        best, best_at = session_ids[0], -math.inf
        for sid in session_ids:
            try:
                session = store.read_session(world_id, sid)
            except (WorldStoreError, KeyError, OSError):
                continue
            if session.started_at > best_at:
                best, best_at = sid, session.started_at
        return best

    # -- the snapshot --------------------------------------------------

    def snapshot(self, world_id: str | None, session_id: str | None) -> Snapshot:
        """One complete status payload. Never partial, never a delta."""
        resolved_world, resolved_session, problem = self.resolve(world_id, session_id)
        if problem is not None:
            return self._unavailable(problem)
        try:
            return self._snapshot(resolved_world, resolved_session)
        except (WorldStoreError, KeyError, ValueError, OSError) as exc:
            # A world this build cannot read is a real answer, not a
            # crash. Refusing to interpret an unknown schema is the store's
            # documented behaviour and it must survive to the wire rather
            # than becoming a dropped subscription.
            logger.warning("result channel: world %s unreadable: %s", world_id, exc)
            return self._unavailable(f"world could not be read: {exc}")

    def _unavailable(self, reason: str) -> Snapshot:
        payload = {
            "world": None,
            "session": None,
            "lifecycle": {
                "state": LIFECYCLE_UNAVAILABLE,
                "evidence": "nothing to read",
                "reason": reason,
            },
            "progress": None,
            "tracking": None,
            "calibration": None,
            "scale": None,
            "geometry": None,
            "trajectory": None,
            "persistence": None,
            "artifacts": None,
            "time_basis": TIME_BASIS,
        }
        return Snapshot(
            payload=payload,
            revision=compute_revision(payload, VOLATILE_PATHS),
            volatile_fields=VOLATILE_PATHS,
        )

    def _snapshot(self, world_id: str, session_id: str | None) -> Snapshot:
        store = WorldStore(self._root)
        world = store.read_world(world_id)

        if session_id is None:
            payload = self._payload_no_session(store, world)
        else:
            payload = self._payload(store, world, session_id)

        return Snapshot(
            payload=payload,
            revision=compute_revision(payload, VOLATILE_PATHS),
            volatile_fields=VOLATILE_PATHS,
        )

    def _payload_no_session(self, store, world) -> dict:
        return {
            "world": _world_block(world),
            "session": None,
            "lifecycle": {
                "state": LIFECYCLE_IDLE,
                "evidence": "the world exists and has no sessions",
                "reason": None,
            },
            "progress": None,
            "tracking": None,
            "calibration": None,
            "scale": _scale_block(world),
            "geometry": _geometry_unavailable("this world has no sessions"),
            "trajectory": _trajectory_unavailable("this world has no sessions"),
            "persistence": _persistence_block(world),
            "artifacts": _artifacts_block(store, world.world_id, None, world),
            "time_basis": TIME_BASIS,
        }

    def _payload(self, store, world, session_id: str) -> dict:
        session = store.read_session(world.world_id, session_id)
        # A SUMMARY, not the parsed journal. Two reasons, both measured.
        #
        # Memory: caching the parsed list would hold every event dict for
        # as long as anyone is subscribed -- tens of megabytes for a long
        # session, in a cache whose whole purpose is to be cheap.
        #
        # Time: stat-gating stops the journal being re-PARSED, but the
        # blocks below scan it, and a scan is O(events) on every poll.
        # Measured at 50,000 events: 9.26 ms per snapshot when the parsed
        # list was cached and re-scanned, 0.79 ms when the summary is
        # cached instead. The parse was never the only cost.
        events = self._files.read(
            store.events_path(world.world_id, session_id),
            lambda: _summarise_events(
                store.read_events(world.world_id, session_id)
            ),
        )
        holder = _lock_holder(store, world.world_id)
        manifest = self._files.read(
            store.derived_manifest_path(world.world_id),
            lambda: _read_manifest(store, world.world_id),
        )
        keyframes_current = self._files.read(
            store.keyframes_path(world.world_id, session_id),
            lambda: _keyframes_digest(store, world.world_id, session_id),
        )

        if manifest is not None and manifest.get("session_id") != session_id:
            # THE session check, and the only one. A world with two built
            # sessions has ONE manifest, describing whichever built last.
            # Attributing it to the other session would report one
            # session's geometry as another's -- a confident wrong answer,
            # and the reason _read_manifest deliberately does not filter:
            # its result is cached per FILE, and that file is shared.
            manifest = None

        stopped = events['stopped']
        geometry_current = (
            manifest is not None
            and keyframes_current is not None
            and manifest.get("input_digest") == keyframes_current
        )

        lifecycle = _lifecycle(
            holder=holder,
            stopped=stopped,
            session=session,
            geometry_current=geometry_current,
            has_manifest=manifest is not None,
        )
        live = lifecycle["state"] == LIFECYCLE_RECEIVING

        return {
            "world": _world_block(world),
            "session": _session_block(session),
            "lifecycle": lifecycle,
            "progress": _progress_block(session, events, live, self._clock()),
            "tracking": _tracking_block(events),
            "calibration": _calibration_block(session),
            "scale": _scale_block(world),
            "geometry": _geometry_block(manifest, geometry_current),
            "trajectory": self._trajectory_block(
                store, world, session_id, manifest, geometry_current
            ),
            "persistence": _persistence_block(world),
            "artifacts": _artifacts_block(store, world.world_id, session_id, world),
            "time_basis": TIME_BASIS,
        }

    def _trajectory_block(self, store, world, session_id, manifest, current) -> dict:
        if manifest is None:
            return _trajectory_unavailable(
                "no build has run for this session, so no poses exist"
            )
        if not current:
            return _trajectory_unavailable(
                "the persisted poses are older than the keyframes; a rebuild "
                "is outstanding"
            )
        revision = compute_revision(
            {
                "digest": manifest.get("input_digest"),
                "built_at": manifest.get("built_at"),
                "solved": manifest.get("poses_solved"),
                "refused": manifest.get("poses_refused"),
                "segments": manifest.get("segments"),
            }
        )
        return {
            "available": True,
            # Poses that actually carry a position, which is NOT
            # poses_solved. engine.build counts an ANCHOR as neither
            # solved nor refused, yet an anchor has a translation and is a
            # real point on the path. Reporting poses_solved as "the
            # number of poses" would drop the first keyframe of every
            # segment; reporting the keyframe count would claim a position
            # for keyframes the backend refused. Neither is the trajectory.
            "pose_count": _pose_count(manifest),
            "poses_solved": manifest.get("poses_solved"),
            "poses_refused": manifest.get("poses_refused"),
            "keyframes": manifest.get("keyframes"),
            "segments": manifest.get("segments"),
            "path_length": self._path_length(
                store, world, session_id, manifest, revision
            ),
            "revision": revision,
            "provenance": "inferred",
            "confidence": None,
            "unavailable_reason": None,
        }

    def _path_length(self, store, world, session_id, manifest, revision):
        """Total distance along the camera path, or an honest refusal.

        Refused whenever the session has more than one segment. A segment
        break means tracking was lost and the poses either side are NOT in
        a common coordinate frame (records.py Keyframe.segment_index), so
        adding distances across the break sums numbers that share neither
        a unit nor an origin. The result would be a plausible number that
        means nothing -- worse than no number, because a UI cannot tell.

        Cached per geometry revision: this is the only read here that
        touches the full poses file, and a poll loop must not repeat it
        for an unchanged build.
        """
        key = f"{world.world_id}:{session_id}"
        cached = self._path_length_cache.get(key)
        if cached is not None and cached[0] == revision:
            return cached[1]

        value = self._compute_path_length(store, world, session_id, manifest)
        # Replaced, never appended: one entry per (world, session), so the
        # cache is bounded by the number of distinct targets a subscriber
        # names, not by session length or poll count.
        self._path_length_cache[key] = (revision, value)
        return value

    def _compute_path_length(self, store, world, session_id, manifest):
        refused = manifest.get("poses_refused")
        if refused is None or refused > 0:
            # A refused pose is a HOLE in the path, not a shorter path.
            # Summing across it draws a straight line between the two
            # keyframes either side of the gap and calls that distance
            # walked -- and the wearer may have walked a loop through it.
            # A length with holes in it is not a length.
            return {
                "available": False,
                "reason": (
                    f"{refused} of this session's poses were refused, so the "
                    "path has gaps; a total would draw straight lines across "
                    "them and count the result as distance travelled"
                ),
            }
        segments = manifest.get("segments")
        if segments is None or segments > 1:
            return {
                "available": False,
                "reason": (
                    f"this session has {segments} segments; tracking was lost "
                    "between them, so their poses share no coordinate frame "
                    "and a total length would sum incomparable distances"
                ),
            }
        semantics = SCALE_SEMANTICS.get(world.scale.state)
        if semantics is None:
            return {
                "available": False,
                "reason": (
                    "this world has no scale state, so a distance figure "
                    "could not be labelled and would not be renderable"
                ),
            }
        try:
            derived = store.read_derived(world.world_id, session_id)
        except (WorldStoreError, KeyError, ValueError, OSError):
            derived = None
        if derived is None:
            return {"available": False, "reason": "the derived poses are unreadable"}

        total = 0.0
        previous = None
        for row in derived["poses"]:
            # Status AND translation, matching inspect.trajectory's own
            # test. A rotation_only row carries a rotation with a null
            # translation; anything else is not a position on the path.
            if row.get("status") not in (POSE_STATUS_SOLVED, POSE_STATUS_ANCHOR):
                return {
                    "available": False,
                    "reason": (
                        f"a pose has status {row.get('status')!r}, so the path "
                        "is not continuous"
                    ),
                }
            translation = row.get("translation")
            if translation is None:
                return {
                    "available": False,
                    "reason": "a pose carries no translation, so the path has a gap",
                }
            if previous is not None:
                total += math.dist(previous, translation)
            previous = translation
        if previous is None:
            return {"available": False, "reason": "no pose was solved"}

        return {
            "available": True,
            "value": total,
            "unit": "world units",
            "scale_semantics": semantics,
            "display": format_distance(total, world.scale),
            "provenance": "inferred",
        }


# -- blocks -------------------------------------------------------------


def _world_block(world) -> dict:
    return {
        "world_id": world.world_id,
        # None, never a derived name. IOS-to-Tower.md 1.2: "If the Tower
        # does not name worlds, iOS shows no name rather than deriving
        # one."
        "display_name": world.display_name,
        "schema_version": world.schema_version,
        "created_at": world.created_at,
        "updated_at": world.updated_at,
    }


def _session_block(session) -> dict:
    return {
        "session_id": session.session_id,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "end_reason": session.end_reason,
        "frame_source": session.frame_source,
        "capture_id": session.capture_id,
        # Stated on the record itself. This is the one module that retains
        # raw imagery and the posture travels with the data.
        "retains_raw_imagery": session.retains_raw_imagery,
    }


# Attached to every stopped-and-not-current lifecycle. `null` is the
# whole point: this is not False. Tower does not know whether a build is
# running, and False would be a claim that none is.
_BUILD_UNOBSERVABLE_REASON = (
    "the writer lock is released before build() is called, and build() "
    "emits no event and writes nothing until it finishes, so a build in "
    "progress is indistinguishable on disk from one that never started "
    "and from one that crashed"
)
_BUILD_UNOBSERVABLE = {
    "build_in_progress": None,
    "build_in_progress_unavailable_reason": _BUILD_UNOBSERVABLE_REASON,
}


def _lifecycle(*, holder, stopped, session, geometry_current, has_manifest) -> dict:
    """What the Tower can SEE about whether a world is being built.

    This is `IOS-to-Tower.md` 1.1's central ask -- "a start/stop/failed
    signal **distinct from 'frames are arriving'**" -- and the writer lock
    answers it exactly, because it is held for the lifetime of a mapping
    session and by nothing else (engine.start_session acquires it,
    stop_session releases it).

    A lock held by a pid that is no longer running is a genuine, visible
    failure: a builder process died mid-session. That is worth reporting
    as `failed` with the pid, because the alternative -- reporting
    `receiving` forever -- would be a stale observation presented as
    current state.
    """
    if holder is not None and holder["alive"] and not stopped:
        return {
            "state": LIFECYCLE_RECEIVING,
            "evidence": (
                f"a live process (pid {holder['pid']}) holds the writer lock"
            ),
            "reason": None,
            "build_in_progress": False,
            "build_in_progress_unavailable_reason": None,
        }
    if holder is not None and not holder["alive"] and not stopped:
        return {
            "state": LIFECYCLE_FAILED,
            "evidence": (
                f"the writer lock is held by pid {holder['pid']}, which is no "
                "longer running"
            ),
            "reason": (
                "the process building this world exited without stopping its "
                "session; its keyframes are persisted but the session was "
                "never closed"
            ),
            **_BUILD_UNOBSERVABLE,
        }
    if session.end_reason in ("error", "interrupted"):
        return {
            "state": LIFECYCLE_FAILED,
            "evidence": f"the session recorded end_reason={session.end_reason!r}",
            "reason": f"the mapping session ended with {session.end_reason!r}",
            **_BUILD_UNOBSERVABLE,
        }
    if not stopped:
        return {
            "state": LIFECYCLE_IDLE,
            "evidence": (
                "no writer lock is held and no session_stopped event was "
                "written"
            ),
            "reason": None,
            **_BUILD_UNOBSERVABLE,
        }
    if not has_manifest:
        return {
            "state": LIFECYCLE_STOPPED_UNBUILT,
            "evidence": "capture ended and no build output exists for this session",
            "reason": "no geometry has been built for this session yet",
            **_BUILD_UNOBSERVABLE,
        }
    if not geometry_current:
        return {
            "state": LIFECYCLE_STOPPED_UNBUILT,
            "evidence": (
                "capture ended and the stored geometry is older than the "
                "keyframes"
            ),
            "reason": (
                "a rebuild is outstanding; the figures stored are not the "
                "figures these keyframes would produce"
            ),
            **_BUILD_UNOBSERVABLE,
        }
    return {
        "state": LIFECYCLE_READY,
        "evidence": "capture ended and the stored geometry matches the keyframes",
        "reason": None,
        "build_in_progress": None,
        "build_in_progress_unavailable_reason": _BUILD_UNOBSERVABLE_REASON,
    }


def _summarise_events(events) -> dict:
    """Everything any block needs from the journal, in fixed size.

    Computed once per journal change and cached. Deliberately returns
    scalars: nothing downstream is allowed to hold the event list, so the
    cost of a long session is a few integers rather than the session.
    """
    accepted = 0
    last_tracking = None
    stopped = False
    for event in events:
        kind = event.get("kind")
        if kind == "keyframe_accepted":
            accepted += 1
            last_tracking = kind
        elif kind == "tracking_lost":
            last_tracking = kind
        elif kind == "session_stopped":
            stopped = True
    return {
        "keyframes_accepted": accepted,
        "last_tracking": last_tracking,
        "stopped": stopped,
    }


def _progress_block(session, events, live: bool, now: float) -> dict:
    """What the Tower actually counts, and nothing it does not.

    While a session is live the keyframe count comes from the journal,
    not from session.json, which still holds the zeros written at
    start_session. `frames_observed` has no live source at all: an
    ordinary rejected frame writes no event, so the number simply is not
    knowable yet and is reported as null with the reason.
    """
    accepted = events["keyframes_accepted"]
    ended = session.ended_at
    elapsed = (ended if ended is not None else now) - session.started_at
    return {
        "keyframes_accepted": accepted if live else session.keyframes_accepted,
        "keyframes_accepted_provenance": "measured",
        "frames_observed": None if live else session.frames_observed,
        "frames_observed_unavailable_reason": (
            "no event is written for an ordinary rejected frame, so this "
            "count is only known once the session stops"
            if live
            else None
        ),
        "rejected_by_reason": None if live else dict(session.rejected_by_reason),
        # On the TOWER's clock, per IOS-to-Tower.md 1.8: "the iPhone's idea
        # of elapsed time is not the Tower's idea of mapping time".
        "mapping_seconds": max(0.0, elapsed),
        "mapping_clock": "tower",
        "time_basis": TIME_BASIS,
    }


def _tracking_block(events) -> dict:
    """Coarse tracking state, and why `limited` is never sent.

    `IOS-to-Tower.md` 1.6 accepts good / limited / lost. Tower emits only
    two of the three plus unknown, because `tracking_lost` and
    `keyframe_accepted` are real events with real meanings, while
    "limited" would require a threshold on rejection rate that nobody has
    defined. Inventing one would put a state on screen that looks measured
    and is not -- and iOS explicitly refuses a percentage for that same
    reason.
    """
    last = events["last_tracking"]
    if last == "tracking_lost":
        return {
            "state": TRACKING_LOST,
            "evidence": "the most recent tracking event was tracking_lost",
            "limited_ever_reported": False,
        }
    if last == "keyframe_accepted":
        return {
            "state": TRACKING_GOOD,
            "evidence": "the most recent tracking event was keyframe_accepted",
            "limited_ever_reported": False,
        }
    return {
        "state": TRACKING_UNKNOWN,
        "evidence": "no keyframe has been accepted and no loss recorded",
        "limited_ever_reported": False,
    }


def _calibration_block(session) -> dict:
    """Coarse calibration state. `calibrating` is unreachable in V1.

    Calibration is a property of the SESSION, not the world: intrinsics
    are recorded per session and keyed by resolution, because DAT's
    adaptive ladder changes resolution mid-stream (records.py
    CameraIntrinsics). A world whose sessions were captured at different
    resolutions has no single calibration state.

    There is no in-session calibration procedure -- calibrate_charuco.py
    runs offline, before a session -- so `calibrating` is never emitted.
    """
    intrinsics = session.intrinsics
    if intrinsics.is_known:
        state = CALIBRATION_CALIBRATED
    elif intrinsics.source == INTRINSICS_SOURCE_UNKNOWN:
        state = CALIBRATION_UNCALIBRATED
    else:
        # A source is declared but the numbers do not survive
        # CameraIntrinsics.is_known -- absent, non-finite, or a
        # non-positive focal length. "Unknown" rather than "uncalibrated":
        # something was attempted and this build cannot vouch for it.
        state = CALIBRATION_UNKNOWN
    return {
        "state": state,
        "source": intrinsics.source,
        "calibrated_width": intrinsics.calibrated_width,
        "calibrated_height": intrinsics.calibrated_height,
        "reprojection_rms_px": intrinsics.reprojection_rms_px,
        "view_count": intrinsics.view_count,
        # No percentage, ever. IOS-to-Tower.md 1.5: "'62% calibrated'
        # implies a denominator nobody has defined."
        "calibrating_ever_reported": False,
        "scope": "session",
    }


def _scale_block(world) -> dict:
    scale = world.scale
    return {
        "state": scale.state,
        "semantics": SCALE_SEMANTICS.get(scale.state),
        "meters_per_unit": scale.meters_per_unit,
        "method": scale.method,
        "confidence": scale.confidence.value,
        # The unit string IOS-to-Tower.md 0.5 requires beside every
        # figure. Null when there is no unit at all, which is the honest
        # value for a world with no solved pose.
        "unit": None if scale.state == SCALE_UNKNOWN else "world units",
        "allows_metres": scale.allows_metres,
    }


def _geometry_block(manifest, current: bool) -> dict:
    if manifest is None:
        return _geometry_unavailable(
            "no build has run for this session, so no geometry exists"
        )
    if not current:
        return _geometry_unavailable(
            "the persisted geometry is older than the keyframes; a rebuild "
            "is outstanding"
        )
    return {
        "available": True,
        # The Tower's own word, displayed verbatim and never parsed
        # (IOS-to-Tower.md 1.3).
        "representation": GEOMETRY_REPRESENTATION,
        "element_count": manifest.get("points"),
        "element_name": "point",
        # False, and stated. A build replaces the whole derived tree; it
        # never emits a delta. A UI that assumed otherwise "will draw a
        # partial world as a complete one".
        "is_incremental": False,
        # built_at is in here deliberately, even though it makes an
        # identical rebuild look like a change. input_digest covers only
        # the keyframe IDS (store.compute_input_digest), so a rebuild with
        # a different backend, policy or code version produces DIFFERENT
        # GEOMETRY UNDER THE SAME DIGEST. Between a revision that
        # occasionally cries change when nothing changed and one that can
        # stay silent while the geometry moves underneath a viewer, only
        # the first is safe: the cost is a redundant redraw, and the cost
        # of the second is a stale world shown as current.
        "revision": compute_revision(
            {
                "digest": manifest.get("input_digest"),
                "built_at": manifest.get("built_at"),
                "points": manifest.get("points"),
                "solved": manifest.get("poses_solved"),
                "segments": manifest.get("segments"),
                "scale": manifest.get("scale_state"),
            }
        ),
        "provenance": "inferred",
        # Tower keeps per-keyframe and per-edge confidence labels but has
        # never defined an aggregate for a whole reconstruction. Null
        # rather than an average nobody specified.
        "confidence": None,
        "backend_id": manifest.get("backend_id"),
        "built_at": manifest.get("built_at"),
        "time_basis": TIME_BASIS,
        "unavailable_reason": None,
    }


def _geometry_unavailable(reason: str) -> dict:
    return {
        "available": False,
        "representation": None,
        "element_count": None,
        "element_name": None,
        "is_incremental": False,
        "revision": None,
        "provenance": None,
        "confidence": None,
        "backend_id": None,
        "built_at": None,
        "time_basis": TIME_BASIS,
        "unavailable_reason": reason,
    }


def _trajectory_unavailable(reason: str) -> dict:
    return {
        "available": False,
        "pose_count": None,
        "poses_refused": None,
        "segments": None,
        "path_length": None,
        "revision": None,
        "provenance": None,
        "confidence": None,
        "unavailable_reason": reason,
    }


def _persistence_block(world) -> dict:
    """Did the world survive the session? Always yes, and say so.

    IOS-to-Tower.md 1.7 wants `session` / `saved(revision)` / `reloading`
    kept distinct from "did not say", because "silence is not a promise
    that a world was discarded". World Builder persists everything by
    construction, so this is `saved` with the world's own revision.
    """
    return {
        "state": "saved",
        "revision": compute_revision(
            {
                "world_id": world.world_id,
                "frame_revision": world.frame_revision,
                "sessions": list(world.session_ids),
            }
        ),
        "images_purged": world.images_purged,
        # The Tower owns persistence entirely and iOS stores nothing.
        # Where it is stored is NOT REQUESTED (1.7) and is not sent: a
        # filesystem path on the Tower is useless to a phone and names a
        # machine's layout to a remote consumer.
        "location_disclosed": False,
    }


def _artifacts_block(store, world_id, session_id, world) -> dict:
    """What imagery exists, and why none of it is offered.

    `IOS-to-Tower.md` 5 is the strictest rule in the document: an image
    whose treatment is not stated is "handled exactly as strictly as raw
    -- withheld", and there is "deliberately no `.probablySafe` and no
    lenient default".

    World Builder keyframe images are written with `redaction: "none"`
    (records.py Session.redaction, whose comment says "none" is the honest
    V1 value: no redaction is implemented). They are raw first-person
    frames. So they are reported as PRESENT and NOT FETCHABLE, and no id
    or URL is minted for them -- iOS holds "no URL, no id format, and no
    bytes", and inventing a fetch scheme would be exactly the fabricated
    contract that document refuses to produce.
    """
    present = False
    count = None
    if session_id is not None and not world.images_purged:
        images = store.images_dir(world_id, session_id)
        try:
            if images.exists():
                count = sum(1 for _ in images.glob("*.jpg"))
                present = count > 0
        except OSError:
            count = None
    return {
        "keyframe_images": {
            "present": present,
            "count": count,
            "redaction": "none",
            "fetchable": False,
            "reason": (
                "these are unredacted first-person frames and no artifact "
                "transfer contract exists; a consumer must withhold imagery "
                "whose treatment is not stated"
            ),
        },
        # The FLAG, reported as a flag. An audit confirmed it deletes
        # nothing -- a world with images_purged=True still had every JPEG
        # on disk. What it actually does is make build() refuse
        # (engine.ImagesPurgedError). Reporting it as "the imagery is
        # gone" would be the false assurance 06-PRIVACY-DATA forbids: a
        # purge that cannot delete everything must never report success.
        "images_purged_declared": world.images_purged,
        "images_purged_verified": None,
        "images_purged_meaning": (
            "a declaration that rebuilds are refused for this world, not a "
            "verified deletion of the imagery"
        ),
    }


# -- disk helpers -------------------------------------------------------


def _lock_holder(store, world_id):
    """Who holds the writer lock, and is that process still alive?

    Returns None when no lock file exists. The lock is the ONLY live
    signal the web process has, because the builder runs elsewhere.
    """
    path = store.lock_path(world_id)
    try:
        if not path.exists():
            return None
        holder = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pid = holder.get("pid")
    if not isinstance(pid, int):
        return None
    return {"pid": pid, "alive": _pid_is_running(pid)}


def _pid_is_running(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:  # pragma: no cover - psutil is a hard dependency
        return False


def _read_manifest(store, world_id):
    """The world's derived manifest, unfiltered, or None.

    Deliberately NOT filtered by session, despite the manifest carrying a
    session_id -- the caller does that, and it matters where the check
    lives. This function is called through a file-fingerprint cache keyed
    on the manifest PATH, and that path is shared by every session in a
    world (store.derived_manifest_path). A cached value filtered for one
    session would be handed to another, which is the exact
    misattribution the check exists to prevent.

    So: this reads and validates the schema; `_payload` decides whether
    the manifest describes the session being reported on. An earlier
    version of this function claimed to do both and did neither after the
    cache was introduced.
    """
    manifest = store.read_derived_manifest(world_id)
    if manifest is None:
        return None
    if manifest.get("schema_version") != SCHEMA_VERSION:
        # store.derived_is_current checks this; nothing else does. A
        # manifest from another schema describes fields whose meaning this
        # build does not know.
        return None
    return manifest


def _pose_count(manifest):
    """Poses carrying a position: every keyframe the backend did not refuse."""
    keyframes = manifest.get("keyframes")
    refused = manifest.get("poses_refused")
    if not isinstance(keyframes, int) or not isinstance(refused, int):
        return None
    return max(0, keyframes - refused)


def _keyframes_digest(store, world_id, session_id):
    from tower.world_builder.store import compute_input_digest

    try:
        return compute_input_digest(store.read_keyframes(world_id, session_id))
    except (WorldStoreError, KeyError, ValueError, OSError):
        return None


