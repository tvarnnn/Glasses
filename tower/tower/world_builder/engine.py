"""The World Builder engine: observe cheaply, build expensively.

Two entry points with deliberately different cost profiles:

``observe()`` runs per delivered frame and is cheap (~5 ms measured at
360x640 against a ~300 ms interval). It decodes, scores, tracks, decides,
and on acceptance persists one keyframe. It never calls a geometry
backend.

``build()`` runs at stop time, reads the persisted keyframe journal back,
and writes the reconstruction. It is never reachable from the frame
path, which is what keeps a multi-second write off the event loop.

It used to be a full re-solve as well -- re-reading every keyframe,
re-decoding every JPEG and re-detecting features on all N -- which made
a walk rebuilt every k keyframes cost O(N^2/k), so asking for MORE live
updates cost more than the walk. It now extends one live solve as each
keyframe is accepted (see _LiveSolve) and a rebuild is a flush. The
from-scratch path is still here and still correct: it is what a cold
rebuild, a re-derive, and any keyframe set this engine did not itself
observe fall back to.

That split is also why live-versus-offline is a *driver* choice rather
than an architecture choice: the offline script calls exactly the same
observe() a future module adapter would.
"""

import logging
import time
from dataclasses import dataclass, field, replace

from tower.confidence import Confidence
from tower.world_builder.backend import KeyframeInput
from tower.world_builder.backends import BACKEND_AUTO, select_backend
from tower.world_builder.events import EventLog, WorldEvent
from tower.world_builder.frontend import FrameTracker, analyse_frame, decode_gray
from tower.world_builder.keyframes import (
    KeyframePolicy,
    KeyframeSelector,
)
from tower.world_builder.redaction import FaceRedactor
from tower.world_builder.records import (
    CameraIntrinsics,
    Keyframe,
    KeyframeEdge,
    ScaleState,
    Session,
    World,
    make_keyframe_id,
    new_id,
)
from tower.world_builder.schema import (
    END_REASON_STOP,
    POSE_STATUS_ANCHOR,
    POSE_STATUS_SOLVED,
    SCALE_MEASURED,
    SCALE_RELATIVE,
    SCALE_UNKNOWN,
)
from tower.world_builder.store import WorldStore, compute_input_digest

logger = logging.getLogger(__name__)


class SessionNotActiveError(RuntimeError):
    """observe()/stop_session() called without a live session."""


class ImagesPurgedError(RuntimeError):
    """A rebuild was attempted on a world whose imagery has been deleted.

    Raised loudly rather than producing an empty reconstruction: silently
    returning nothing would look like a mapping failure rather than the
    consequence of a deliberate privacy action.
    """


@dataclass(frozen=True)
class ObserveResult:
    outcome: str
    reason: str
    keyframe_id: str | None = None
    frames_observed: int = 0
    keyframes_accepted: int = 0


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    frames_observed: int
    keyframes_accepted: int
    rejected_by_reason: dict
    segments: int
    end_reason: str


@dataclass(frozen=True)
class BuildResult:
    world_id: str
    session_id: str
    backend_id: str
    keyframes: int
    poses_solved: int
    poses_refused: int
    points: int
    segments: int
    scale_state: str
    downgraded_from: str | None = None
    diagnostics: dict = field(default_factory=dict)


class WorldBuilderEngine:
    def __init__(
        self,
        store: WorldStore,
        policy: KeyframePolicy | None = None,
        backend_name: str = BACKEND_AUTO,
        clock=time.time,
        redactor_factory=None,
    ) -> None:
        self._store = store
        self._policy = policy or KeyframePolicy()
        self._backend_name = backend_name
        # A factory rather than an instance: a redactor holds a loaded
        # detector, and a session that never starts should not pay for
        # one. Injectable so a test can drive both halves without a model
        # file, and so an operator can point at different weights.
        self._redactor_factory = redactor_factory or FaceRedactor
        # None until a session starts. `_persist_keyframe` only ever runs
        # inside one, and a half-built placeholder here would be a worse
        # failure than an AttributeError if that ever stopped being true.
        self._redactor = None
        self._clock = clock

        self._session: Session | None = None
        self._selector: KeyframeSelector | None = None
        self._tracker: FrameTracker | None = None
        self._events: EventLog | None = None
        self._segment_index = 0
        self._rejected: dict[str, int] = {}
        # Survives stop_session() on purpose: the usual order is
        # observe... stop_session() build(), and throwing the solve away
        # at stop would put the whole cost straight back.
        self._live: _LiveSolve | None = None

    # -- lifecycle -----------------------------------------------------

    def create_world(self, display_name: str | None = None) -> str:
        now = self._clock()
        world = World(
            world_id=new_id(),
            created_at=now,
            updated_at=now,
            display_name=display_name,
        )
        self._store.write_world(world)
        return world.world_id

    def start_session(
        self,
        world_id: str,
        *,
        intrinsics: CameraIntrinsics | None = None,
        frame_source: str = "unknown",
        declared_size: tuple[int, int] | None = None,
        capture_id: str | None = None,
    ) -> str:
        world = self._store.read_world(world_id)
        self._store.acquire_writer_lock(world_id)

        session = Session(
            session_id=new_id(),
            world_id=world_id,
            started_at=self._clock(),
            frame_source=frame_source,
            capture_id=capture_id,
            declared_width=declared_size[0] if declared_size else None,
            declared_height=declared_size[1] if declared_size else None,
            intrinsics=intrinsics or CameraIntrinsics.unknown(),
        )
        self._store.write_session(session)
        self._store.write_world(
            replace(
                world,
                updated_at=self._clock(),
                session_ids=world.session_ids + (session.session_id,),
            )
        )

        self._session = session
        self._redactor = self._redactor_factory()
        if not self._redactor.available:
            logger.warning(
                "[Tower][WorldBuilder] persisting UNREDACTED keyframes: %s",
                self._redactor.unavailable_reason,
            )
        self._selector = KeyframeSelector(self._policy)
        self._tracker = FrameTracker()
        self._events = EventLog(
            self._store, world_id, session.session_id, clock=self._clock
        )
        self._segment_index = 0
        self._rejected = {}
        self._events.append("session_started", {"frame_source": frame_source})
        self._open_live_solve(session)
        return session.session_id

    def observe(
        self,
        raw_bytes: bytes,
        *,
        received_at: float | None = None,
        source_seq: int,
        wire_seq: int | None = None,
        tx_seq: int | None = None,
    ) -> ObserveResult:
        if self._session is None:
            raise SessionNotActiveError("observe() requires an active session")

        session = self._session
        received_at = self._clock() if received_at is None else received_at
        self._session = replace(
            session, frames_observed=session.frames_observed + 1
        )
        session = self._session

        try:
            gray = decode_gray(raw_bytes)
        except ValueError:
            # One undecodable frame is frame-scoped: drop it, keep going.
            self._note_rejected("malformed_frame")
            self._events.append("frame_rejected", {"reason": "malformed_frame"})
            return self._result("reject", "malformed_frame")

        quality = analyse_frame(gray)
        self._selector.note_frame(quality)
        motion = self._tracker.measure(gray)
        decision = self._selector.evaluate(quality, motion)

        if decision.lost:
            # A new segment: poses either side are NOT in a common frame,
            # and the records say so rather than implying continuity.
            self._tracker.reset()
            self._selector.note_lost()
            self._segment_index += 1
            if self._live is not None:
                self._live.close_segment(self._segment_index)
            self._note_rejected(decision.reason)
            self._events.append(
                "tracking_lost", {"segment_index": self._segment_index}
            )
            return self._result(decision.outcome, decision.reason)

        if not decision.accepted:
            self._note_rejected(decision.reason)
            return self._result(decision.outcome, decision.reason)

        keyframe, image_bytes = self._persist_keyframe(
            gray_shape=gray.shape,
            raw_bytes=raw_bytes,
            received_at=received_at,
            source_seq=source_seq,
            wire_seq=wire_seq,
            tx_seq=tx_seq,
            quality=quality,
            motion=motion,
            reason=decision.reason,
        )
        if self._live is not None:
            # The REDACTED bytes, because those are what landed on disk
            # and therefore what build() decodes. Feeding `gray` here
            # would solve against pixels no rebuild can ever reproduce --
            # redaction costs about 9% of the point cloud when a face is
            # in frame, so the two would quietly disagree. `is` because
            # redact() hands back the very object it was given whenever
            # it changed nothing, which is the overwhelmingly common case
            # and makes this free.
            self._live.extend(
                keyframe.keyframe_id,
                gray if image_bytes is raw_bytes else decode_gray(image_bytes),
            )

        self._tracker.set_reference(gray)
        self._selector.note_accepted()
        self._session = replace(
            self._session,
            keyframes_accepted=self._session.keyframes_accepted + 1,
        )
        self._events.append(
            "keyframe_accepted",
            {
                "keyframe_id": keyframe.keyframe_id,
                "reason": decision.reason,
                "segment_index": keyframe.segment_index,
            },
        )
        return self._result(
            decision.outcome, decision.reason, keyframe_id=keyframe.keyframe_id
        )

    def stop_session(self, reason: str = END_REASON_STOP) -> SessionSummary:
        if self._session is None:
            raise SessionNotActiveError("stop_session() requires an active session")

        session = replace(
            self._session,
            ended_at=self._clock(),
            end_reason=reason,
            rejected_by_reason=dict(self._rejected),
        )
        self._store.write_session(session)
        self._events.append("session_stopped", {"end_reason": reason})
        self._store.release_writer_lock(session.world_id)

        summary = SessionSummary(
            session_id=session.session_id,
            frames_observed=session.frames_observed,
            keyframes_accepted=session.keyframes_accepted,
            rejected_by_reason=dict(self._rejected),
            segments=self._segment_index + 1,
            end_reason=reason,
        )
        self._session = None
        self._selector = None
        self._tracker = None
        self._events = None
        return summary

    # -- build ---------------------------------------------------------

    def build(self, world_id: str, session_id: str) -> BuildResult:
        """Reconstruct from the persisted journal. Expensive; offline only."""
        world = self._store.read_world(world_id)
        if world.images_purged:
            raise ImagesPurgedError(
                f"world {world_id} has had its imagery purged; a rebuild "
                "would produce an empty reconstruction rather than a map"
            )

        session = self._store.read_session(world_id, session_id)
        keyframes = self._store.read_keyframes(world_id, session_id)
        _require_matching_resolution(session, keyframes)
        # Silent here, deliberately. `_open_live_solve` already announced
        # this at session start, where an operator can still act on it,
        # and build() now runs once per rebuild -- so announcing here
        # turns one actionable warning into one per rebuild. The
        # selection itself is unchanged and still recorded on the
        # session below.
        selection = select_backend(
            self._backend_name, session.intrinsics, announce=False
        )
        backend = selection.backend
        backend.prepare(session.intrinsics)

        if selection.was_downgraded:
            self._store.write_session(
                replace(
                    session,
                    backend_id=backend.capabilities.backend_id,
                    backend_requires_intrinsics=(
                        backend.capabilities.requires_intrinsics
                    ),
                    backend_downgraded_from=selection.downgraded_from,
                    backend_downgrade_reason=selection.downgrade_reason,
                )
            )
        else:
            self._store.write_session(
                replace(
                    session,
                    backend_id=backend.capabilities.backend_id,
                    backend_requires_intrinsics=(
                        backend.capabilities.requires_intrinsics
                    ),
                )
            )

        # Edges are recomputed from the keyframes on every build, so they
        # are derived output despite living in a journal. Without this,
        # each rebuild appends a duplicate set and the reported edge count
        # doubles, triples, and so on.
        self._store.clear_edges(world_id, session_id)

        # Segment -> (keyframe ids fed, estimate). Empty for a cold
        # rebuild, a different session, or a live solve that gave up.
        solved_live = self._live_estimates(world_id, session_id, session, backend)

        poses_solved = poses_refused = 0
        # Counted, not derived by subtraction. `keyframes - poses_refused`
        # silently promotes every anchor to a camera position, and an
        # anchor is definitional rather than measured: identity rotation,
        # zero translation, by construction. On the 2026-08-24 physical
        # walk that arithmetic turned 36 origin markers into "36 camera
        # poses" on the phone while poses_solved was zero.
        #
        # An anchor IS a real position when the chain it anchors resolved
        # -- it is that segment's origin, and dropping it would
        # under-report every segment by one. So the rule is per segment,
        # and it needs the per-segment solve count to state.
        poses_anchor = 0
        poses_positioned = 0
        total_points = 0
        segments = sorted({keyframe.segment_index for keyframe in keyframes})

        pose_rows: list[dict] = []
        point_rows: list[list[float]] = []

        for segment in segments:
            members = [k for k in keyframes if k.segment_index == segment]
            if not members:
                continue
            member_ids = tuple(keyframe.keyframe_id for keyframe in members)
            carried = solved_live.get(segment)
            if carried is not None and carried[0] == member_ids:
                # The flush. Nothing is re-read, re-decoded or re-solved;
                # this is the same estimate estimate_window() would
                # return, which tests/test_world_builder_incremental.py
                # pins bit-for-bit.
                estimate = carried[1]
            else:
                # Whatever this engine did not observe itself: a cold
                # rebuild, a re-derive, a session whose journal no longer
                # matches what was fed. Ids are compared rather than
                # counted because a matching count with different
                # keyframes is exactly the failure worth catching.
                window = [
                    KeyframeInput(
                        keyframe_id=keyframe.keyframe_id,
                        image_gray=self._load_gray(world_id, session_id, keyframe),
                    )
                    for keyframe in members
                ]
                estimate = backend.estimate_window(window)

            segment_solved = 0
            segment_anchors = 0
            for keyframe, pose in zip(members, estimate.poses):
                if pose.status == POSE_STATUS_SOLVED:
                    poses_solved += 1
                    segment_solved += 1
                elif pose.status == POSE_STATUS_ANCHOR:
                    poses_anchor += 1
                    segment_anchors += 1
                else:
                    poses_refused += 1
                pose_rows.append(
                    self._pose_row(keyframe, pose, segment)
                )
            # An anchor counts as a position only if something in its
            # segment actually solved against it. A lone anchor in a
            # segment that resolved nothing is an origin marker for an
            # empty coordinate frame.
            poses_positioned += segment_solved
            if segment_solved:
                poses_positioned += segment_anchors

            for previous, current, pose in zip(
                members, members[1:], estimate.poses[1:]
            ):
                self._store.append_edge(
                    world_id,
                    session_id,
                    KeyframeEdge(
                        from_keyframe_id=previous.keyframe_id,
                        to_keyframe_id=current.keyframe_id,
                        matches=pose.matches,
                        inliers=pose.inliers,
                        inlier_ratio=pose.inlier_ratio,
                        median_parallax_px=pose.median_displacement_px,
                        median_parallax_deg=pose.median_triangulation_deg,
                        cheirality_fraction=pose.cheirality_fraction,
                        r_h=pose.r_h,
                        rotation_dominant=(pose.status != POSE_STATUS_SOLVED),
                        pose_status=pose.status,
                        degeneracy=pose.degeneracy,
                        quality=Confidence.from_score(pose.inlier_ratio),
                    ),
                )

            if estimate.points is not None:
                # Tagged with the segment that produced them. Segments do
                # NOT share a coordinate frame or a unit, so concatenating
                # them untagged produces one cloud that silently merges
                # incompatible geometry.
                point_rows.extend(
                    {"segment_index": segment, "xyz": xyz}
                    for xyz in estimate.points.xyz.tolist()
                )
                total_points += len(estimate.points)

        backend.release()

        # Scale becomes "relative" only once something actually solved:
        # an internally consistent world with an arbitrary unit. Without a
        # solved pose there is no unit at all, so it stays "unknown".
        #
        # A world with MORE THAN ONE segment is not internally consistent
        # either. Each segment is solved in its own window, so each has its
        # own arbitrary unit -- measured 4x apart between two segments of
        # one session. Calling that "relative" would assert a coherence
        # the reconstruction does not have.
        if not poses_solved:
            scale_state = SCALE_UNKNOWN
        elif len(segments) > 1:
            scale_state = SCALE_UNKNOWN
        else:
            scale_state = SCALE_RELATIVE

        # Never clobber a scale this build did not earn. A measured scale
        # carries meters_per_unit, method, confidence and history that a
        # rebuild has no business discarding -- ScaleState promises
        # superseded estimates are appended, never overwritten.
        existing = world.scale
        if existing.state == SCALE_MEASURED:
            scale = existing
        elif existing.state == scale_state:
            scale = existing
        else:
            scale = ScaleState(state=scale_state)

        self._store.write_world(
            replace(world, updated_at=self._clock(), scale=scale)
        )
        self._store.write_derived(
            world_id,
            session_id,
            poses=pose_rows,
            points=point_rows,
            manifest={
                "schema_version": world.schema_version,
                "input_digest": compute_input_digest(keyframes),
                "built_at": self._clock(),
                "backend_id": backend.capabilities.backend_id,
                "session_id": session_id,
                "keyframes": len(keyframes),
                "poses_solved": poses_solved,
                "poses_refused": poses_refused,
                # Both reported. Suppressing the anchors would replace one
                # misleading number with a missing one; a reader should be
                # able to see "36 segment origins and no trajectory",
                # which is a precise description of an uncalibrated walk.
                "poses_anchor": poses_anchor,
                "poses_positioned": poses_positioned,
                "points": total_points,
                "segments": len(segments),
                "scale_state": scale_state,
            },
        )

        return BuildResult(
            world_id=world_id,
            session_id=session_id,
            backend_id=backend.capabilities.backend_id,
            keyframes=len(keyframes),
            poses_solved=poses_solved,
            poses_refused=poses_refused,
            points=total_points,
            segments=len(segments),
            scale_state=scale_state,
            downgraded_from=selection.downgraded_from,
        )

    # -- internals -----------------------------------------------------

    def _open_live_solve(self, session) -> None:
        """Start the solve that observe() will extend.

        Backend selection is deterministic in (name, intrinsics), so the
        instance chosen here is the same one build() would choose; build()
        re-checks both anyway before trusting anything this produces.
        """
        if self._live is not None:
            self._live.release()
            self._live = None
        try:
            selection = select_backend(self._backend_name, session.intrinsics)
            backend = selection.backend
            backend.begin(session.intrinsics)
        except Exception:
            # A live solve is an optimisation. Losing it must never cost
            # the session its keyframes -- build() still has the
            # from-scratch path, and it will raise there, loudly, with
            # the whole journal in hand.
            logger.exception(
                "[Tower][WorldBuilder] live geometry unavailable for session "
                "%s; build() will solve from scratch",
                session.session_id,
            )
            return
        self._live = _LiveSolve(
            world_id=session.world_id,
            session_id=session.session_id,
            backend=backend,
            intrinsics=session.intrinsics,
            segment_index=self._segment_index,
        )

    def _live_estimates(self, world_id, session_id, session, backend) -> dict:
        """What the live solve has, if it is still the right answer.

        Every one of these is a way the carried solve could be answering
        a question nobody asked: a different world, a different session,
        intrinsics rewritten since the session opened, or a backend
        selection that has since changed. Any of them and the whole thing
        is discarded rather than partially believed.
        """
        live = self._live
        if live is None or not live.usable:
            return {}
        if live.world_id != world_id or live.session_id != session_id:
            return {}
        if live.intrinsics != session.intrinsics:
            return {}
        if live.backend_id != backend.capabilities.backend_id:
            return {}
        return live.estimates()

    def _pose_row(self, keyframe, pose, segment) -> dict:
        """Convert a backend pose into the persisted T_world_camera contract.

        The backends work in the convention OpenCV hands them:
        `recoverPose` and `solvePnPRansac` both return (R, t) mapping a
        WORLD point into the CAMERA frame, so `t` is not a position at all
        -- it is where the world origin sits as seen by the camera.

        schema.POSE_CONVENTION declares the opposite: `T_world_camera`,
        whose translation IS the camera's position in world coordinates,
        chosen precisely so no consumer ever has to invert anything.

        Writing the raw `t` under that contract mirrors every camera
        through the origin. It is not a loud failure -- the trajectory
        stays smooth, monotonic and entirely plausible -- which is exactly
        why the convention is frozen and why this conversion lives here
        rather than being left to whoever renders it. An earlier version
        of this function shipped the raw value; a strafe along +X
        persisted as -X, and nothing caught it until the values were
        compared against ground-truth camera positions.

            R_world_camera = R.T
            C              = -R.T @ t
        """
        import numpy as np

        row = {
            "keyframe_id": keyframe.keyframe_id,
            "segment_index": segment,
            "status": pose.status,
            "degeneracy": pose.degeneracy,
            "rotation": None,
            "translation": None,
        }
        if pose.status == POSE_STATUS_ANCHOR:
            row["rotation"] = [1.0, 0.0, 0.0, 0.0]
            row["translation"] = [0.0, 0.0, 0.0]
        elif pose.rotation is not None:
            rotation = np.asarray(pose.rotation, dtype=np.float64)
            row["rotation"] = _rotation_to_quaternion_wxyz(rotation.T)
            if pose.translation is not None:
                translation = np.asarray(
                    pose.translation, dtype=np.float64
                ).reshape(3)
                row["translation"] = [
                    float(v) for v in (-rotation.T @ translation)
                ]
            # A rotation_only pose keeps its rotation and leaves
            # translation null. Discarding both would throw away the real
            # information the degeneracy path exists to preserve.
        return row

    def _load_gray(self, world_id, session_id, keyframe):
        path = self._store.session_dir(world_id, session_id) / keyframe.image_relpath
        return decode_gray(path.read_bytes())

    def _persist_keyframe(
        self, *, gray_shape, raw_bytes, received_at, source_seq, wire_seq,
        tx_seq, quality, motion, reason,
    ) -> tuple[Keyframe, bytes]:
        session = self._session
        filename = f"{source_seq:08d}.jpg"

        # The privacy transformation, and it happens HERE because this is
        # the one place every persisted pixel passes through. Before the
        # write, never after: redacting on read would leave the raw frames
        # on disk, which is a display filter rather than the
        # transformation 06-PRIVACY-DATA asks for.
        #
        # The bytes the reconstruction later reads are the redacted ones,
        # and that was measured before it was chosen: at the ~5% of frame a
        # real face occupies, keyframe acceptance and pose solving are
        # completely unaffected and the point cloud loses about 9%. See
        # redaction.py.
        redaction = self._redactor.redact(raw_bytes)
        image_bytes = redaction.image_bytes

        # Image first, fsynced, THEN the journal line. A journal line
        # pointing at a missing image is corruption; an orphan image is
        # harmless and gets swept.
        self._store.write_keyframe_image(
            session.world_id, session.session_id, filename, image_bytes
        )
        keyframe = Keyframe(
            keyframe_id=make_keyframe_id(session.session_id, source_seq),
            session_id=session.session_id,
            source_seq=source_seq,
            wire_seq=wire_seq,
            tx_seq=tx_seq,
            received_at=received_at,
            image_relpath=f"images/{filename}",
            width=quality.width,
            height=quality.height,
            byte_count=len(image_bytes),
            segment_index=self._segment_index,
            sharpness=quality.sharpness,
            selection_reason=reason,
            median_parallax_px=(
                motion.median_displacement_px if motion else None
            ),
            overlap_ratio=motion.overlap_ratio if motion else None,
            survival_ratio=motion.survival_ratio if motion else None,
            tracked_count=motion.tracked_count if motion else None,
            feature_count=motion.seeded_count if motion else None,
            homography_residual_px=(
                motion.homography_residual_px if motion else None
            ),
            quality=Confidence.from_score(
                motion.survival_ratio if motion else None
            ),
        )
        self._store.append_keyframe(session.world_id, keyframe)
        if self._session.redaction != redaction.label:
            # The session records what was APPLIED, not what was
            # configured. A redactor that is present but failing must not
            # leave the session claiming its imagery was filtered.
            self._session = replace(self._session, redaction=redaction.label)
        # The bytes as well as the record: they are what the live solve
        # must see, because they are what a rebuild will read back.
        return keyframe, image_bytes

    def _note_rejected(self, reason: str) -> None:
        self._rejected[reason] = self._rejected.get(reason, 0) + 1

    def _result(self, outcome, reason, keyframe_id=None) -> ObserveResult:
        return ObserveResult(
            outcome=outcome,
            reason=reason,
            keyframe_id=keyframe_id,
            frames_observed=self._session.frames_observed,
            keyframes_accepted=self._session.keyframes_accepted,
        )


class _LiveSolve:
    """One geometry solve carried across observe() calls.

    The whole reason this class exists is a cost measurement. build()
    re-solved from scratch every time, at roughly O(N^1.2) in the backend
    alone -- 303 ms for 32 keyframes and 641 ms for 64, extrapolating to
    about 2 s at the 155 keyframes of the 2026-08-24 physical walk, plus
    a JPEG decode per keyframe on top. A walk rebuilt every k keyframes
    therefore paid O(N^2/k): 5.9 s of backend work over 64 keyframes at
    --rebuild-every 4, against 0.8 s for the same walk extended. Turning
    the live updates UP made the whole session slower, which is why the
    cadence defaulted to zero and why nothing appeared until a walk had
    ended.

    A segment gets exactly one solve, and it never crosses a
    tracking_lost: segments do not share a coordinate frame or a unit,
    they are independent windows today, and they must stay so. Closing a
    segment freezes its estimate and resets the backend.

    Nothing here is allowed to cost the session a keyframe. Every backend
    call is guarded, and a solve that fails simply stops offering
    answers; build() then does what it always did.
    """

    def __init__(self, *, world_id, session_id, backend, intrinsics, segment_index):
        self.world_id = world_id
        self.session_id = session_id
        self.backend = backend
        self.intrinsics = intrinsics
        self.backend_id = backend.capabilities.backend_id
        self.usable = True
        self._segment_index = segment_index
        self._open: list[str] = []
        self._frozen: dict[int, tuple[tuple[str, ...], object]] = {}

    def extend(self, keyframe_id: str, gray) -> None:
        if not self.usable:
            return
        try:
            self.backend.extend(
                KeyframeInput(keyframe_id=keyframe_id, image_gray=gray)
            )
        except Exception:
            self._give_up("extending")
            return
        self._open.append(keyframe_id)

    def close_segment(self, segment_index: int) -> None:
        if not self.usable:
            return
        try:
            if self._open:
                self._frozen[self._segment_index] = (
                    tuple(self._open),
                    self.backend.snapshot(),
                )
            self.backend.reset()
        except Exception:
            self._give_up("closing a segment of")
            return
        self._open = []
        self._segment_index = segment_index

    def estimates(self) -> dict:
        """Frozen segments plus a live view of the open one.

        Non-destructive: a mid-walk rebuild reads this and the walk keeps
        extending the same solve afterwards. If it were destructive,
        watching a world build would change the world.
        """
        if not self.usable:
            return {}
        carried = dict(self._frozen)
        if self._open:
            try:
                carried[self._segment_index] = (
                    tuple(self._open),
                    self.backend.snapshot(),
                )
            except Exception:
                self._give_up("snapshotting")
                return {}
        return carried

    def release(self) -> None:
        self.usable = False
        try:
            self.backend.release()
        except Exception:
            logger.exception("[Tower][WorldBuilder] backend release failed")

    def _give_up(self, doing: str) -> None:
        self.usable = False
        self._frozen = {}
        self._open = []
        logger.exception(
            "[Tower][WorldBuilder] live geometry gave up %s session %s; "
            "build() will solve from scratch",
            doing,
            self.session_id,
        )


class IntrinsicsResolutionMismatchError(RuntimeError):
    """Intrinsics were calibrated at a resolution the frames are not."""


def _require_matching_resolution(session, keyframes) -> None:
    """Refuse to apply intrinsics to frames of a different size.

    Applying a 480x360 calibration to 720x1280 frames does not fail --
    it silently produces a reconstruction wrong by the resolution ratio.
    CameraIntrinsics.scaled_to() already refuses to rescale without
    established linearity; this is the check that actually routes callers
    into that refusal instead of around it.
    """
    intrinsics = session.intrinsics
    if not intrinsics.is_known or not keyframes:
        return
    sizes = {(keyframe.width, keyframe.height) for keyframe in keyframes}
    calibrated = (intrinsics.calibrated_width, intrinsics.calibrated_height)
    mismatched = sorted(size for size in sizes if size != calibrated)
    if mismatched:
        raise IntrinsicsResolutionMismatchError(
            f"intrinsics were calibrated at {calibrated[0]}x{calibrated[1]} "
            f"but this session contains keyframes at {mismatched}. Refusing "
            "to apply them: the reconstruction would be silently wrong by "
            "the resolution ratio. Calibrate at the delivered resolution, "
            "or establish scales_linearly_across_resolutions and rescale."
        )


def _rotation_to_quaternion_wxyz(rotation) -> list[float]:
    """Rotation matrix to quaternion in the frozen wxyz order.

    Hand-rolled because scipy is not a dependency. Uses the largest
    diagonal term to pick a numerically stable branch rather than the
    trace-only formula, which loses precision near 180 degrees.
    """
    import numpy as np

    m = np.asarray(rotation, dtype=np.float64)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (m[2, 1] - m[1, 2]) * s
        y = (m[0, 2] - m[2, 0]) * s
        z = (m[1, 0] - m[0, 1]) * s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    return [float(w), float(x), float(y), float(z)]
