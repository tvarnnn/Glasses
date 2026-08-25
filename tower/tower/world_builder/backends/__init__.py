"""Geometry backends, and the rule for choosing one.

A backend is swapped, never edited-around: adding a learned pointmap
backend later should be a new module here plus a branch in
select_backend(), touching nothing that owns data.
"""

import logging

from tower.world_builder.backend import GeometryBackend
from tower.world_builder.backends.classical import ClassicalTwoViewBackend
from tower.world_builder.backends.unposed import UnposedBackend
from tower.world_builder.records import CameraIntrinsics

logger = logging.getLogger(__name__)

BACKEND_AUTO = "auto"
BACKEND_CLASSICAL = "classical"
BACKEND_UNPOSED = "unposed"

BACKEND_NAMES = (BACKEND_AUTO, BACKEND_CLASSICAL, BACKEND_UNPOSED)


class BackendSelection:
    """The chosen backend plus, crucially, whether it was a downgrade.

    A downgrade is recorded rather than silently applied. "The map has no
    poses" and "the map has no poses because you asked for a calibrated
    backend without calibration" are very different operator experiences,
    and only the second is actionable.
    """

    def __init__(self, backend, downgraded_from=None, downgrade_reason=None):
        self.backend = backend
        self.downgraded_from = downgraded_from
        self.downgrade_reason = downgrade_reason

    @property
    def was_downgraded(self) -> bool:
        return self.downgraded_from is not None


def select_backend(
    name: str, intrinsics: CameraIntrinsics
) -> BackendSelection:
    if name not in BACKEND_NAMES:
        raise ValueError(f"unknown backend {name!r}; expected one of {BACKEND_NAMES}")

    if name == BACKEND_UNPOSED:
        return BackendSelection(UnposedBackend())

    if name == BACKEND_AUTO:
        if intrinsics.is_known:
            return BackendSelection(ClassicalTwoViewBackend())
        # Announced, and recorded, exactly like the explicit request
        # below. This branch used to return silently with
        # downgraded_from=None, on the reasoning that AUTO choosing the
        # only backend it CAN choose is a selection rather than a
        # downgrade.
        #
        # That reasoning is defensible and it cost a night. On the
        # 2026-08-24 physical walk AUTO landed here, the session recorded
        # `backend_id: "unposed", downgraded_from: null`, and the world
        # came back with 155 keyframes, zero poses and zero points with
        # nothing anywhere saying why. The operator's question is "why is
        # there no geometry?", and the answer -- "because nothing has
        # calibrated this camera" -- was computed here and thrown away.
        #
        # Whether AUTO "downgraded" is a question about this function's
        # vocabulary. Whether the reconstruction lost its geometry to
        # missing intrinsics is a question about the world, and it has
        # the same answer either way.
        reason = (
            "no backend that solves poses can run without intrinsics, and "
            f"this session's intrinsics are source={intrinsics.source!r}; "
            "the unposed backend will record keyframes and tracking but "
            "will produce no poses and no points"
        )
        logger.warning("world builder: backend selected unposed -- %s", reason)
        return BackendSelection(
            UnposedBackend(),
            downgraded_from=BACKEND_CLASSICAL,
            downgrade_reason=reason,
        )

    # Explicitly requested classical.
    if intrinsics.is_known:
        return BackendSelection(ClassicalTwoViewBackend())

    reason = (
        "classical backend requires intrinsics, but this session's "
        f"intrinsics are source={intrinsics.source!r}; no intrinsics were "
        "invented"
    )
    logger.warning("world builder: backend downgraded to unposed -- %s", reason)
    return BackendSelection(
        UnposedBackend(),
        downgraded_from=BACKEND_CLASSICAL,
        downgrade_reason=reason,
    )


__all__ = [
    "BACKEND_AUTO",
    "BACKEND_CLASSICAL",
    "BACKEND_NAMES",
    "BACKEND_UNPOSED",
    "BackendSelection",
    "ClassicalTwoViewBackend",
    "GeometryBackend",
    "UnposedBackend",
    "select_backend",
]
