"""Persisted record shapes for World Builder.

Follows tower/object_memory/records.py: frozen dataclasses, explicit
to_json_dict / *_from_json_dict, reserved-but-unused fields carried from
day one so a later need does not require rewriting already-persisted
records, and confidence stored as a LABEL rather than a score.

Confidence itself is imported from object_memory rather than redefined.
Two independently-evolving confidence vocabularies with the same four
labels is exactly the silent-divergence failure Rule 16 exists to prevent.
Rule 6 ("modules own their data") governs data, not a shared vocabulary --
importing a frozen enum is not promoting data to a shared service. Revisit
a tower/confidence.py only when a third consumer appears.
"""

from dataclasses import dataclass, field, replace

from tower.confidence import Confidence
from tower.world_builder.schema import (
    DEGENERACY_NONE,
    INTRINSICS_SOURCE_SELF_CALIBRATED,
    INTRINSICS_SOURCE_UNKNOWN,
    POSE_CONVENTION,
    POSE_STATUS_UNAVAILABLE,
    SCALE_STATES_ALLOWING_METRES,
    SCALE_UNKNOWN,
    SCHEMA_VERSION,
    TIME_BASIS,
)


# Opaque ids: never derived from a display name (the user renames
# "Bedroom") and never a content hash (refinement changes content). Object
# Memory anchors will reference a world_id long after either has changed.
from tower.storage import new_id  # noqa: E402,F401


@dataclass(frozen=True)
class ScaleState:
    """How, if at all, this world's units relate to physical distance.

    Geometry is ALWAYS stored in world units and scale is metadata, never
    baked into coordinates. Applying a later metric estimate is then a
    one-field write instead of a rewrite of every point, pose, and anchor
    -- and it does not invalidate anchors written earlier.

    "relative" is the honest state for monocular reconstruction: the
    reconstruction is internally consistent, but its unit is whatever the
    first solved baseline happened to be. That is not a metre.
    """

    state: str = SCALE_UNKNOWN
    meters_per_unit: float | None = None
    method: str | None = None
    confidence: Confidence = Confidence.UNKNOWN
    # Superseded estimates are appended, never overwritten, so a consumer
    # that cached a distance can detect that it is stale.
    history: tuple[dict, ...] = ()

    @property
    def allows_metres(self) -> bool:
        return self.state in SCALE_STATES_ALLOWING_METRES

    def to_json_dict(self) -> dict:
        return {
            "state": self.state,
            "meters_per_unit": self.meters_per_unit,
            "method": self.method,
            "confidence": self.confidence.value,
            "history": [dict(entry) for entry in self.history],
        }


def scale_state_from_json_dict(data: dict) -> ScaleState:
    return ScaleState(
        state=data["state"],
        meters_per_unit=data["meters_per_unit"],
        method=data["method"],
        confidence=Confidence(data["confidence"]),
        history=tuple(dict(entry) for entry in data["history"]),
    )


def format_distance(value: float, scale: ScaleState) -> str:
    """Render a distance without ever claiming a unit we cannot support.

    The single choke point for turning a number into human-facing text.
    It exists as a function rather than a convention because "remember not
    to print metres" is not a mechanism, and a metre printed from an
    unscaled monocular reconstruction is precisely the
    inference-presented-as-measurement that Rule 16 forbids.
    """
    if scale.allows_metres and scale.meters_per_unit is not None:
        return f"{value * scale.meters_per_unit:.3f} m"
    return f"{value:.3f} world units"


@dataclass(frozen=True)
class CameraIntrinsics:
    """Pinhole intrinsics plus, crucially, where they came from.

    A world whose keyframes have no record of the camera configuration
    that produced them can never be re-projected, relocalised into, or
    re-run through a better pipeline -- it is permanently unrefinable.
    That is why this is authoritative rather than derived.

    Keyed by resolution deliberately: DAT's adaptive ladder changes
    resolution mid-stream and cannot be overridden, and whether intrinsics
    scale linearly across its three modes is genuinely unknown (recorded
    as scales_linearly_across_resolutions=None, not assumed True). A
    single unkeyed block would silently mis-attribute every frame captured
    after a ladder step.

    There is no constructor that produces a guessed value.
    """

    source: str = INTRINSICS_SOURCE_UNKNOWN
    model: str | None = None
    fx: float | None = None
    fy: float | None = None
    cx: float | None = None
    cy: float | None = None
    dist_coeffs: tuple[float, ...] | None = None
    calibrated_width: int | None = None
    calibrated_height: int | None = None
    reprojection_rms_px: float | None = None
    view_count: int | None = None
    calibrated_at: float | None = None
    scales_linearly_across_resolutions: bool | None = None

    @classmethod
    def unknown(cls) -> "CameraIntrinsics":
        return cls()

    @property
    def is_known(self) -> bool:
        return (
            self.source != INTRINSICS_SOURCE_UNKNOWN
            and None not in (self.fx, self.fy, self.cx, self.cy)
        )

    def camera_matrix(self):
        """3x3 K, or None when intrinsics are unknown.

        Returns None rather than raising so callers are pushed toward
        "do I have intrinsics?" rather than toward a try/except that
        would be easy to paper over with a default.
        """
        if not self.is_known:
            return None
        import numpy as np

        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

    def scaled_to(self, width: int, height: int) -> "CameraIntrinsics":
        """Rescale to another resolution, ONLY when that is known to be valid.

        Refuses unless scales_linearly_across_resolutions is explicitly
        True. The linear-scaling assumption holds for a pure resize and
        fails for a crop, and which one DAT performs between its three
        modes has never been established -- so the default is to refuse
        rather than to silently produce intrinsics that are wrong by a
        crop factor.
        """
        if not self.is_known:
            return self
        if self.calibrated_width == width and self.calibrated_height == height:
            return self
        if self.scales_linearly_across_resolutions is not True:
            raise ValueError(
                "refusing to rescale intrinsics calibrated at "
                f"{self.calibrated_width}x{self.calibrated_height} to "
                f"{width}x{height}: scales_linearly_across_resolutions is "
                f"{self.scales_linearly_across_resolutions!r}, not True. "
                "Whether DAT resizes or crops between resolutions is not "
                "established; calibrate at the target resolution instead."
            )
        sx = width / self.calibrated_width
        sy = height / self.calibrated_height
        return replace(
            self,
            fx=self.fx * sx,
            fy=self.fy * sy,
            cx=self.cx * sx,
            cy=self.cy * sy,
            calibrated_width=width,
            calibrated_height=height,
        )

    def to_json_dict(self) -> dict:
        return {
            "source": self.source,
            "model": self.model,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "dist_coeffs": (
                list(self.dist_coeffs) if self.dist_coeffs is not None else None
            ),
            "calibrated_width": self.calibrated_width,
            "calibrated_height": self.calibrated_height,
            "reprojection_rms_px": self.reprojection_rms_px,
            "view_count": self.view_count,
            "calibrated_at": self.calibrated_at,
            "scales_linearly_across_resolutions": (
                self.scales_linearly_across_resolutions
            ),
        }


def camera_intrinsics_from_json_dict(data: dict) -> CameraIntrinsics:
    coeffs = data["dist_coeffs"]
    source = data["source"]
    if source == INTRINSICS_SOURCE_SELF_CALIBRATED and data["fx"] is None:
        raise ValueError(
            "intrinsics claim source=self_calibrated but carry no fx; "
            "a calibration that produced no focal length is not a calibration"
        )
    return CameraIntrinsics(
        source=source,
        model=data["model"],
        fx=data["fx"],
        fy=data["fy"],
        cx=data["cx"],
        cy=data["cy"],
        dist_coeffs=tuple(coeffs) if coeffs is not None else None,
        calibrated_width=data["calibrated_width"],
        calibrated_height=data["calibrated_height"],
        reprojection_rms_px=data["reprojection_rms_px"],
        view_count=data["view_count"],
        calibrated_at=data["calibrated_at"],
        scales_linearly_across_resolutions=data[
            "scales_linearly_across_resolutions"
        ],
    )


@dataclass(frozen=True)
class World:
    """The long-lived artifact. Not a session, not a connection."""

    world_id: str
    created_at: float
    updated_at: float
    display_name: str | None = None
    schema_version: int = SCHEMA_VERSION
    # Monotonic gauge counter. V1 never advances it past 1 -- nothing
    # performs loop closure, bundle adjustment, or scale estimation. It is
    # persisted anyway because it is the un-retrofittable half of the
    # gauge design: a coordinate written without a revision stamp can
    # never be repaired, since you cannot determine after the fact which
    # gauge it meant.
    frame_revision: int = 1
    pose_convention: dict = field(default_factory=lambda: dict(POSE_CONVENTION))
    scale: ScaleState = field(default_factory=ScaleState)
    session_ids: tuple[str, ...] = ()
    # True once keyframe imagery has been purged for privacy. The world
    # survives as a record, but a rebuild must fail loudly rather than
    # quietly producing an empty reconstruction.
    images_purged: bool = False

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "world_id": self.world_id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "frame_revision": self.frame_revision,
            "pose_convention": dict(self.pose_convention),
            "scale": self.scale.to_json_dict(),
            "session_ids": list(self.session_ids),
            "images_purged": self.images_purged,
        }


def world_from_json_dict(data: dict) -> World:
    return World(
        schema_version=data["schema_version"],
        world_id=data["world_id"],
        display_name=data["display_name"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        frame_revision=data["frame_revision"],
        pose_convention=dict(data["pose_convention"]),
        scale=scale_state_from_json_dict(data["scale"]),
        session_ids=tuple(data["session_ids"]),
        images_purged=data["images_purged"],
    )


@dataclass(frozen=True)
class Session:
    """One mapping session: an explicitly started and stopped window."""

    session_id: str
    world_id: str
    started_at: float
    schema_version: int = SCHEMA_VERSION
    ended_at: float | None = None
    end_reason: str | None = None
    time_basis: str = TIME_BASIS
    frame_source: str = "unknown"
    capture_id: str | None = None
    declared_width: int | None = None
    declared_height: int | None = None
    intrinsics: CameraIntrinsics = field(default_factory=CameraIntrinsics.unknown)
    backend_id: str | None = None
    backend_requires_intrinsics: bool | None = None
    backend_downgraded_from: str | None = None
    backend_downgrade_reason: str | None = None
    frames_observed: int = 0
    keyframes_accepted: int = 0
    rejected_by_reason: dict = field(default_factory=dict)
    # This module retains raw imagery, unlike every module shipped so far.
    # Declared on the record itself, not only on the module descriptor, so
    # the posture travels with the data.
    retains_raw_imagery: bool = True
    privacy_tags: tuple[str, ...] = ("raw-imagery", "first-person")
    # What, if anything, was removed from the imagery before it was
    # written. "none" is the honest V1 value: no redaction is implemented.
    #
    # This field exists now because it is the one genuinely
    # un-retrofittable part of any future redaction work. Without it, the
    # day redaction ships there is no way to tell whether an older
    # session's images were filtered, so every historical session must be
    # assumed unredacted forever. One string now avoids that permanently.
    redaction: str = "none"

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "world_id": self.world_id,
            "capture_id": self.capture_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "end_reason": self.end_reason,
            "time_basis": self.time_basis,
            "frame_source": self.frame_source,
            "declared_width": self.declared_width,
            "declared_height": self.declared_height,
            "intrinsics": self.intrinsics.to_json_dict(),
            "backend_id": self.backend_id,
            "backend_requires_intrinsics": self.backend_requires_intrinsics,
            "backend_downgraded_from": self.backend_downgraded_from,
            "backend_downgrade_reason": self.backend_downgrade_reason,
            "frames_observed": self.frames_observed,
            "keyframes_accepted": self.keyframes_accepted,
            "rejected_by_reason": dict(self.rejected_by_reason),
            "retains_raw_imagery": self.retains_raw_imagery,
            "privacy_tags": list(self.privacy_tags),
            "redaction": self.redaction,
        }


def session_from_json_dict(data: dict) -> Session:
    return Session(
        schema_version=data["schema_version"],
        session_id=data["session_id"],
        world_id=data["world_id"],
        capture_id=data["capture_id"],
        started_at=data["started_at"],
        ended_at=data["ended_at"],
        end_reason=data["end_reason"],
        time_basis=data["time_basis"],
        frame_source=data["frame_source"],
        declared_width=data["declared_width"],
        declared_height=data["declared_height"],
        intrinsics=camera_intrinsics_from_json_dict(data["intrinsics"]),
        backend_id=data["backend_id"],
        backend_requires_intrinsics=data["backend_requires_intrinsics"],
        backend_downgraded_from=data["backend_downgraded_from"],
        backend_downgrade_reason=data["backend_downgrade_reason"],
        frames_observed=data["frames_observed"],
        keyframes_accepted=data["keyframes_accepted"],
        rejected_by_reason=dict(data["rejected_by_reason"]),
        retains_raw_imagery=data["retains_raw_imagery"],
        privacy_tags=tuple(data["privacy_tags"]),
        redaction=data["redaction"],
    )


@dataclass(frozen=True)
class Keyframe:
    """One selected observation. Deliberately pose-free.

    Poses are DERIVED -- they change every time the mapper changes, and
    the first thing that will happen to a V1 monocular mapper is that it
    changes. Keeping poses out of this record is what makes a mapper
    upgrade a reprocess rather than a data migration.

    The measured selection signals, by contrast, ARE authoritative: they
    were taken against candidate frames that were rejected and never
    persisted, so they can never be recomputed from the keyframe corpus.
    """

    keyframe_id: str
    session_id: str
    source_seq: int
    received_at: float
    image_relpath: str
    width: int
    height: int
    byte_count: int
    schema_version: int = SCHEMA_VERSION
    time_basis: str = TIME_BASIS
    wire_seq: int | None = None
    tx_seq: int | None = None
    # Segment, not "submap": a segment break means tracking was lost, so
    # poses either side are NOT in a common frame. Recording it is the
    # loop-closure foundation without the loop-closure machinery.
    segment_index: int = 0
    sharpness: float | None = None
    feature_count: int | None = None
    selection_reason: str = "unknown"
    median_parallax_px: float | None = None
    overlap_ratio: float | None = None
    survival_ratio: float | None = None
    tracked_count: int | None = None
    # The median distance, in PIXELS, between where a homography fitted to
    # the tracks predicts each point should land and where it actually
    # landed. Near zero means the motion carried no baseline.
    #
    # Deliberately NOT named r_h. KeyframeEdge.r_h is ORB-SLAM's
    # dimensionless H/(H+F) inlier ratio -- a different quantity, in
    # different units. Both once shared the name, which would have let a
    # successor compare them and get a meaningless answer with no error.
    # Renaming is free now and impossible once data exists.
    homography_residual_px: float | None = None
    quality: Confidence = Confidence.UNKNOWN
    frame_revision: int = 1
    # Reserved-but-unused, carried from day one so a later cross-module
    # need does not require rewriting persisted records.
    spatial_ref: None = None
    external_refs: tuple[()] = ()

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "keyframe_id": self.keyframe_id,
            "session_id": self.session_id,
            "source_seq": self.source_seq,
            "wire_seq": self.wire_seq,
            "tx_seq": self.tx_seq,
            "received_at": self.received_at,
            "time_basis": self.time_basis,
            "image_relpath": self.image_relpath,
            "width": self.width,
            "height": self.height,
            "byte_count": self.byte_count,
            "segment_index": self.segment_index,
            "sharpness": self.sharpness,
            "feature_count": self.feature_count,
            "selection_reason": self.selection_reason,
            "median_parallax_px": self.median_parallax_px,
            "overlap_ratio": self.overlap_ratio,
            "survival_ratio": self.survival_ratio,
            "tracked_count": self.tracked_count,
            "homography_residual_px": self.homography_residual_px,
            "quality": self.quality.value,
            "frame_revision": self.frame_revision,
            "spatial_ref": self.spatial_ref,
            "external_refs": list(self.external_refs),
        }


def keyframe_from_json_dict(data: dict) -> Keyframe:
    return Keyframe(
        schema_version=data["schema_version"],
        keyframe_id=data["keyframe_id"],
        session_id=data["session_id"],
        source_seq=data["source_seq"],
        wire_seq=data["wire_seq"],
        tx_seq=data["tx_seq"],
        received_at=data["received_at"],
        time_basis=data["time_basis"],
        image_relpath=data["image_relpath"],
        width=data["width"],
        height=data["height"],
        byte_count=data["byte_count"],
        segment_index=data["segment_index"],
        sharpness=data["sharpness"],
        feature_count=data["feature_count"],
        selection_reason=data["selection_reason"],
        median_parallax_px=data["median_parallax_px"],
        overlap_ratio=data["overlap_ratio"],
        survival_ratio=data["survival_ratio"],
        tracked_count=data["tracked_count"],
        homography_residual_px=data["homography_residual_px"],
        quality=Confidence(data["quality"]),
        frame_revision=data["frame_revision"],
        spatial_ref=None,
        external_refs=(),
    )


def make_keyframe_id(session_id: str, source_seq: int) -> str:
    """The globally stable frame key.

    (session_id, source_seq), never source_seq alone: source_seq is only
    monotonic within a session and resets when the glasses session
    restarts. Its deltas are also sampling, not elapsed time -- the sender
    decimates frames -- so nothing may derive a duration from them.
    """
    return f"{session_id}:{source_seq:08d}"


@dataclass(frozen=True)
class KeyframeEdge:
    """A measured pairwise relationship between two keyframes.

    Authoritative, not derived: these numbers were measured against
    candidate frames that were then discarded, so no later pass can
    reproduce them from the stored corpus.
    """

    from_keyframe_id: str
    to_keyframe_id: str
    schema_version: int = SCHEMA_VERSION
    matches: int = 0
    inliers: int = 0
    inlier_ratio: float | None = None
    median_parallax_px: float | None = None
    median_parallax_deg: float | None = None
    # The actual degeneracy discriminator (see Keyframe.r_h for why it is
    # not r_h): the fraction of correspondences passing recoverPose's
    # cheirality check. Measured to be near-binary -- ~0.01 when
    # degenerate, ~1.0 when healthy -- at roughly 0.5 deg median parallax.
    cheirality_fraction: float | None = None
    r_h: float | None = None
    rotation_dominant: bool | None = None
    pose_status: str = POSE_STATUS_UNAVAILABLE
    degeneracy: str = DEGENERACY_NONE
    quality: Confidence = Confidence.UNKNOWN
    frame_revision: int = 1

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "from_keyframe_id": self.from_keyframe_id,
            "to_keyframe_id": self.to_keyframe_id,
            "matches": self.matches,
            "inliers": self.inliers,
            "inlier_ratio": self.inlier_ratio,
            "median_parallax_px": self.median_parallax_px,
            "median_parallax_deg": self.median_parallax_deg,
            "cheirality_fraction": self.cheirality_fraction,
            "r_h": self.r_h,
            "rotation_dominant": self.rotation_dominant,
            "pose_status": self.pose_status,
            "degeneracy": self.degeneracy,
            "quality": self.quality.value,
            "frame_revision": self.frame_revision,
        }


def keyframe_edge_from_json_dict(data: dict) -> KeyframeEdge:
    return KeyframeEdge(
        schema_version=data["schema_version"],
        from_keyframe_id=data["from_keyframe_id"],
        to_keyframe_id=data["to_keyframe_id"],
        matches=data["matches"],
        inliers=data["inliers"],
        inlier_ratio=data["inlier_ratio"],
        median_parallax_px=data["median_parallax_px"],
        median_parallax_deg=data["median_parallax_deg"],
        cheirality_fraction=data["cheirality_fraction"],
        r_h=data["r_h"],
        rotation_dominant=data["rotation_dominant"],
        pose_status=data["pose_status"],
        degeneracy=data["degeneracy"],
        quality=Confidence(data["quality"]),
        frame_revision=data["frame_revision"],
    )
