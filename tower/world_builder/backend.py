"""The geometry backend seam.

This is the most important boundary in World Builder. Above it sits the
world model -- keyframes, journals, segments, persistence -- which is
GPU-free, dependency-free, and most of the code. Below it sits whatever
actually estimates geometry.

The point of the seam is that a feed-forward pointmap model (DA3 and its
kin) is a *backend*, not an architecture. Adopting one later should be a
new file under backends/ plus a line in select_backend(), touching nothing
that owns data.

Two invariants make that work, and both are pinned by tests:

1. Nothing under this module or backends/ imports store, engine, or paths.
   Geometry estimation never learns about disk, worlds, or revisions.
2. A backend that cannot justify a pose returns None with a degeneracy
   reason. That is a first-class answer, not an error -- it is exactly
   what lets the whole engine run honestly on uncalibrated footage
   instead of fabricating an intrinsic to keep the pipeline moving.

The estimation call takes a WINDOW of keyframes rather than a pair. A
pairwise interface would cripple a pointmap model, which reasons over a
whole submap; a per-frame interface cannot express relative geometry at
all. Poses come back in the window's own local frame; placing that frame
into the world is the caller's job, so the backend never sees a world
coordinate.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.schema import (
    DEGENERACY_NONE,
    POSE_STATUS_UNAVAILABLE,
)


@dataclass(frozen=True)
class BackendCapabilities:
    """What a backend can and cannot do, declared rather than inferred."""

    backend_id: str
    version: str
    requires_intrinsics: bool
    estimates_intrinsics: bool
    produces_dense_geometry: bool
    produces_metric_scale: bool
    preferred_window: int
    device: str = "cpu"


@dataclass(frozen=True)
class KeyframeInput:
    """One keyframe as the backend sees it: pixels and nothing else."""

    keyframe_id: str
    image_gray: np.ndarray
    image_bgr: np.ndarray | None = None


@dataclass(frozen=True)
class PoseEstimate:
    """A pose, or an honest refusal to give one.

    rotation/translation are in the WINDOW's local frame, with the window
    anchor at identity. translation is a direction of unit length when the
    status is SOLVED -- monocular two-view geometry cannot recover its
    magnitude, and pretending otherwise by leaving an arbitrary scale in
    place is how a plausible-looking wrong trajectory gets built.
    """

    keyframe_id: str
    status: str = POSE_STATUS_UNAVAILABLE
    rotation: np.ndarray | None = None
    translation: np.ndarray | None = None
    degeneracy: str = DEGENERACY_NONE
    # Every measured signal is carried even when the pose is refused --
    # a refusal that cannot be explained is indistinguishable from a bug.
    matches: int = 0
    inliers: int = 0
    inlier_ratio: float | None = None
    median_triangulation_deg: float | None = None
    median_displacement_px: float | None = None
    cheirality_fraction: float | None = None
    r_h: float | None = None

    @property
    def is_solved(self) -> bool:
        return self.rotation is not None and self.translation is not None


@dataclass(frozen=True)
class PointBlock:
    """Triangulated structure in the window's local frame."""

    xyz: np.ndarray
    rgb: np.ndarray | None = None
    support_views: np.ndarray | None = None

    def __len__(self) -> int:
        return int(self.xyz.shape[0])


@dataclass(frozen=True)
class GeometryEstimate:
    """Everything a backend produces for one window."""

    poses: tuple[PoseEstimate, ...]
    points: PointBlock | None = None
    intrinsics_estimate: CameraIntrinsics | None = None
    scale_is_metric: bool = False
    diagnostics: dict = field(default_factory=dict)


class GeometryBackend(ABC):
    """Estimates relative geometry for a window of keyframes."""

    capabilities: BackendCapabilities

    @abstractmethod
    def prepare(self, intrinsics: CameraIntrinsics) -> None:
        """Bind intrinsics. Must raise if required intrinsics are absent."""

    @abstractmethod
    def estimate_window(
        self, window: Sequence[KeyframeInput]
    ) -> GeometryEstimate: ...

    def release(self) -> None:
        """Free any held resource. Default no-op; must not raise."""
        return None
