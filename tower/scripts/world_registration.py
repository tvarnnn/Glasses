#!/usr/bin/env python
"""Cross-segment registration, offline. Estimate a Sim3 per segment.

World Builder reconstructs in segments, each an independent two-view-seeded
solve with its own origin and its own arbitrary unit -- camera spans across
one real walk range 1.000 to 86.74, an ~87x spread. The viewer therefore
cannot draw a map; it draws disconnected fragments. This script attempts the
missing step: a per-segment `T_world_segment` similarity transform.

It is ANALYSIS, not a production path. It reads a world and writes nothing
into it. Whether the pipeline should compute this on every build is a later
decision that these numbers exist to inform.

    .venv\\Scripts\\python.exe scripts/world_registration.py --world <id>
    .venv\\Scripts\\python.exe scripts/world_registration.py --world <id> --format json

-- The property that governs the design -----------------------------------

Reprojection error does not catch fabrication. Measured on the real walk
(docs/superpowers/research/2026-08-26-cross-segment-registration.md section
6): segment pair (30,50) fits at 1.62 px median with 88% of correspondences
under 3 px, and its scale is wrong by a factor of 3.2. Segment 6 registered
into its OWN frame -- where the true scale is exactly 1.0 by construction --
fits at 0.75 px and returns 0.674.

The reason is geometric, not a tuning failure. A wrong scale paired with a
compensating translation reprojects perfectly whenever the target segment
has no internal parallax, and "the wearer stood still and turned" is the
common case in this corpus. So a gate resting on fit quality will ship
plausible, wrong maps -- which is the failure mode this project cares most
about.

Registration therefore rests on INDEPENDENT AGREEMENT, and the types below
enforce that rather than describing it:

  * `DirectedFit` is one direction's solve. It carries every fit-quality
    number -- reprojection, correspondence count, ambiguity -- and has no
    method, property or flag that yields a decision. You cannot ask it
    whether it is good enough, because it does not know and cannot know.

  * `MutualEvidence` can only be built from two DirectedFits in OPPOSITE
    directions, and refuses the same object twice. Constructing it is the
    act of obtaining independent evidence.

  * `admit()` accepts `MutualEvidence` and nothing else, by an explicit
    type check that names the reason. Handing it a DirectedFit raises.

Adding a fit-quality-only path later means deleting that type check and
widening that signature, in a file whose tests assert both. That is the
point: it should be hard to do by accident.
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.world_builder.geometry import (  # noqa: E402
    MIN_INLIERS,
    RANSAC_CONFIDENCE,
    RANSAC_THRESHOLD_PX,
    detect_and_describe,
    match_indices,
)
from tower.world_builder.frontend import decode_gray  # noqa: E402
from tower.world_builder.schema import POSE_STATUS_UNAVAILABLE  # noqa: E402
from tower.world_builder.store import WorldStore  # noqa: E402

DEFAULT_ROOT = Path("data/world_builder")

# Minimum 3-D/2-D correspondences before PnP is attempted, and its
# reprojection bar. Both match the classical backend's own constants
# rather than inventing new ones -- this is the same operation it
# performs, across a segment boundary instead of within one.
MIN_PNP_CORRESPONDENCES = 12
PNP_REPROJECTION_ERROR_PX = 3.0

# Huber transition for the Sim3 refinement, in pixels. Above this a
# residual grows linearly rather than quadratically, so a handful of bad
# cross-segment matches cannot dominate the solve.
HUBER_PX = 4.0

# The scale search. Segment units differ by up to 87x on the real walk, so
# the grid has to span orders of magnitude; a local refinement from 1.0
# lands in whatever basin it starts in.
SCALE_GRID_MIN = 0.02
SCALE_GRID_MAX = 50.0
SCALE_GRID_STEPS = 45

# Below this ratio of camera-centre span to scene depth, a segment's own
# cameras carry no parallax and its scale is not observable from them.
# Measured on the real walk: every segment at 0.09 or above recovered its
# own scale to within 1.2% in a self-test, and the two below 0.07 came
# back 33% and 57% wrong while fitting at under 1.8 px.
MIN_SPAN_OVER_DEPTH = 0.09


class SupportMissingError(Exception):
    """The world has no support.json, so the association is not on disk.

    Raised rather than silently re-solving. Recovering the association by
    re-running the backend is possible -- it is what the feasibility study
    did -- but a script that quietly does minutes of hidden work is a
    script whose output nobody can attribute. Rebuilding is one command
    and makes the association a durable artifact instead of a side effect.
    """


# -- data ------------------------------------------------------------------


@dataclass(frozen=True)
class Sim3:
    """X_world = scale * rotation @ X_segment + translation."""

    scale: float
    rotation: np.ndarray
    translation: np.ndarray

    def apply(self, xyz: np.ndarray) -> np.ndarray:
        xyz = np.asarray(xyz, dtype=np.float64)
        if xyz.ndim == 1:
            return self.scale * (self.rotation @ xyz) + self.translation
        return self.scale * (self.rotation @ xyz.T).T + self.translation

    def compose(self, inner: "Sim3") -> "Sim3":
        """self ∘ inner: apply `inner` first, then self."""
        return Sim3(
            scale=self.scale * inner.scale,
            rotation=self.rotation @ inner.rotation,
            translation=self.scale * (self.rotation @ inner.translation)
            + self.translation,
        )

    def to_json_dict(self) -> dict:
        return {
            "rotation_wxyz": _rotation_to_quaternion_wxyz(self.rotation),
            "translation": [float(v) for v in self.translation],
            "scale": float(self.scale),
        }


IDENTITY = Sim3(scale=1.0, rotation=np.eye(3), translation=np.zeros(3))


@dataclass
class SegmentGeometry:
    """One segment's reconstruction, read cold, in its own frame.

    `observed` is the association support.json restored: (frame index,
    feature index) -> index into `points`. Both indices are segment-local,
    which is the only frame of reference the two share -- segments do not
    share a coordinate system either.
    """

    index: int
    keypoints: list          # per frame, (n_features, 2) float64 pixels
    descriptors: list        # per frame, ORB descriptors or None
    points: np.ndarray       # (n_points, 3) in this segment's own frame
    poses: dict              # frame index -> (R_cam_segment, t), OpenCV convention
    observed: dict           # (frame, feature) -> point index
    intrinsics: np.ndarray

    @property
    def centres(self) -> np.ndarray:
        if not self.poses:
            return np.zeros((0, 3))
        return np.array([-R.T @ t for R, t in self.poses.values()])

    @property
    def span_over_depth(self) -> float:
        return span_over_depth(self.centres, self.points)


@dataclass(frozen=True)
class DirectedFit:
    """One direction's Sim3 estimate, mapping `target`'s frame into `source`'s.

    Read that direction twice. The fit is produced by PnP-ing the SOURCE
    segment's landmarks into the TARGET segment's images, so the transform
    it recovers carries target-frame points into source-frame coordinates:
    `fit.sim3.apply(target_points)` lands on the source's geometry. Naming
    it the other way round is not a documentation slip -- it silently
    inverts every map built on top of it, and an inverted map is smooth,
    plausible and wrong, which is the one failure this module exists to
    prevent. Measured on the real walk: applying `fit.sim3` to the target's
    points matches the source at 0.0000 median residual, and the other way
    round gives 21.96.

    Deliberately decision-free. Every field here is fit quality or
    provenance; none of it, alone or combined, is allowed to admit a pair.
    See this module's docstring for why. If you find yourself wanting a
    `.is_good` on this class, you are about to reintroduce the (30,50)
    failure -- put the check in `admit()`, where it is visible next to the
    independent evidence that has to carry it.
    """

    source: int
    target: int
    scale: float
    rotation: np.ndarray
    translation: np.ndarray
    cameras: int
    correspondences: int
    reprojection_px: float
    # WHICH cameras were actually posed to produce this fit: a frozenset of
    # (segment index, frame index). Not diagnostics -- this is what makes
    # `MutualEvidence` mean anything.
    #
    # Checking that `source`/`target` are swapped only checks LABELS, and
    # labels are trivially forged:
    #
    #     reverse = dataclasses.replace(forward, source=t, target=s,
    #                                   scale=1.0 / forward.scale)
    #
    # is an algebraic inversion of the forward fit, agrees with it to
    # 0.0% by construction, and was admitted before this field existed.
    # A genuine reverse solve poses the OTHER segment's cameras, so its
    # provenance cannot coincide with the forward one; a relabelled copy
    # carries the forward provenance and is refused.
    provenance: frozenset
    # Width, as a ratio, of the scale interval whose cost stays within 1.5x
    # of the minimum, with rotation and translation re-optimised at each
    # scale. 1.0x means one scale explains the data; 20x means the fit is
    # indifferent across a 20-fold range and its scale means nothing.
    scale_ambiguity: float
    # The TARGET segment's own camera-centre span over its median scene
    # depth. Scale enters this Sim3 only through the baseline between
    # those cameras, so below MIN_SPAN_OVER_DEPTH the scale is not a
    # measurement at all -- see `span_over_depth`.
    target_span_over_depth: float

    @property
    def sim3(self) -> Sim3:
        """Maps the TARGET segment's frame into the SOURCE segment's frame."""
        return Sim3(self.scale, self.rotation, self.translation)


@dataclass(frozen=True)
class MutualEvidence:
    """Two INDEPENDENT solves of the same segment pair, in both directions.

    This type is the whole safety argument. The forward and reverse fits
    are separate estimation problems over different correspondence sets --
    the forward one PnPs A's landmarks into B's images, the reverse one
    PnPs B's landmarks into A's -- so their agreement is not something
    either solve can manufacture. A single solve, however beautifully it
    reprojects, cannot be turned into one of these.
    """

    forward: DirectedFit
    reverse: DirectedFit

    def __post_init__(self) -> None:
        if self.forward is self.reverse:
            raise ValueError(
                "MutualEvidence needs two independent solves; it was handed "
                "the same DirectedFit twice. Agreement with itself is not "
                "evidence."
            )
        if (self.forward.source, self.forward.target) != (
            self.reverse.target,
            self.reverse.source,
        ):
            raise ValueError(
                "MutualEvidence needs opposite directions: got "
                f"{self.forward.source}<-{self.forward.target} and "
                f"{self.reverse.source}<-{self.reverse.target}"
            )
        # The check that has teeth. Swapped labels are free; posing the
        # other segment's cameras is not. Two fits that were computed from
        # the same cameras are one fit wearing two hats, and their
        # reciprocity is arithmetic rather than evidence.
        if self.forward.provenance == self.reverse.provenance:
            raise ValueError(
                "MutualEvidence needs two INDEPENDENT solves: both fits "
                "name the same posed cameras "
                f"({sorted(self.forward.provenance)}), so the reverse is a "
                "relabelled copy of the forward rather than a second "
                "estimate. Solve the other direction for real -- PnP the "
                "other segment's landmarks into this one's images."
            )

    @property
    def pair(self) -> tuple:
        return (self.forward.source, self.forward.target)

    @property
    def reciprocity(self) -> float:
        """s(a<-b) * s(b<-a). Truth is exactly 1.0.

        The single most discriminating number available. On the real walk
        Measured by THIS script on world 3dd986b1c2364d4b85de97152f2e39f4:
        1.0314 and 0.9823 for the two pairs that survive every other check,
        against 0.6305 for (5,6) and 0.4693 for (30,50). (The feasibility
        study's own harness read 1.003, 1.061, 1.514 and 3.215 on the same
        pairs -- same verdicts, different third digits, because it is a
        different implementation. Quote whichever code you are reading.)
        """
        return float(self.forward.scale * self.reverse.scale)

    @property
    def rotation_disagreement_deg(self) -> float:
        """How far the two directions disagree about orientation.

        The forward fit rotates source into target; the reverse rotates
        target into source. Composed, an honest pair returns to identity,
        so the residual rotation angle IS the disagreement.

        Reciprocity checked SCALE and nothing else, so a pair agreeing on
        scale to 1% while disagreeing 40 degrees about which way a segment
        faces was admitted -- folding one segment's geometry through
        another's, which reads as a slightly odd floor plan rather than as
        an error. Both rotations were already in hand; only the comparison
        was missing.
        """
        composed = np.asarray(self.forward.rotation, dtype=np.float64) @ np.asarray(
            self.reverse.rotation, dtype=np.float64
        )
        cosine = (float(np.trace(composed)) - 1.0) / 2.0
        return float(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))


@dataclass(frozen=True)
class Thresholds:
    """The gate, with every number traceable to a measurement.

    Loosening any of these is a decision about how wrong a map may be
    before it is drawn, so they live in one place with their evidence
    attached rather than as literals inside `admit`.
    """

    # Two-camera fits produced both `s = 0.0000` collapses and the 71.4x
    # ambiguity on the real walk. Three is the minimum at which the
    # centre-based initialisation is over-determined at all.
    min_cameras: int = 3
    # Measured by this script: separates (4,5) at 1.0314 and (5,32) at
    # 0.9823 from (5,6) at 0.6305 and (30,50) at 0.4693. Deliberately not
    # tighter -- the honest pairs already spread to 3.1%.
    max_reciprocity_error: float = 0.10
    # Flagged both self-test failures at 4.1x and 17.2x, where every
    # success sat at 1.0-1.2x.
    max_scale_ambiguity: float = 3.0
    # Necessary, nowhere near sufficient -- see the module docstring.
    # How far the two directions may disagree about ORIENTATION.
    #
    # Set from measurement, not taste. On the real world 3dd986b1 all six
    # solvable pairs compose back to identity within 2.31 deg -- including
    # (30,50), which is 3.2x wrong on SCALE. The research note records
    # wrong rotations at 31.9 to 166.0 deg. 15 sits between, ~6x above the
    # worst honest pair and ~2x below the mildest catastrophic one.
    #
    # HONEST STATUS: this clause changes no verdict on the corpus
    # available today. It guards a documented failure class, it does not
    # fix an observed one. Recorded so a successor does not mistake an
    # inert guard for a load-bearing one -- or delete it as dead weight.
    max_rotation_disagreement_deg: float = 15.0

    max_reprojection_px: float = 3.0
    # The pre-check. A segment whose own cameras carry no parallax cannot
    # have its scale measured from them at any quality of match, so this
    # is refusable before trusting anything the solve reports. Every
    # segment at or above 0.09 recovered its own scale to within 1.2% in
    # a self-test; the two below 0.07 came back 33% and 57% wrong while
    # fitting at under 1.8 px.
    min_span_over_depth: float = MIN_SPAN_OVER_DEPTH


@dataclass(frozen=True)
class Verdict:
    """Whether a pair may be used to place one segment against another."""

    pair: tuple
    registered: bool
    reason: str
    reciprocity: float
    # Every clause's outcome, not just the first failure, so a near-miss
    # is legible without a re-run.
    clauses: dict = field(default_factory=dict)


# -- geometry --------------------------------------------------------------


def span_over_depth(centres: np.ndarray, points: np.ndarray) -> float:
    """Camera-centre span over median scene depth: is scale observable?

    Scale enters a Sim3 only through the baseline between the target
    segment's own cameras. When the wearer stands still and turns, those
    cameras are effectively coincident, the baseline carries no
    information, and the scale is unrecoverable no matter how many
    correspondences or how good the reprojection. This ratio says so
    BEFORE any solving, from poses.json and points.json alone, which is
    what turns "we could not place 16 of 19 segments" into "the wearer
    stood still in those segments".
    """
    centres = np.asarray(centres, dtype=np.float64)
    points = np.asarray(points, dtype=np.float64)
    if len(centres) < 2 or len(points) == 0:
        return 0.0
    span = float(np.max(np.linalg.norm(centres[:, None] - centres[None], axis=-1)))
    depth = float(np.median(np.linalg.norm(points - centres.mean(axis=0), axis=1)))
    if depth <= 1e-9:
        return 0.0
    return span / depth


def _chordal_rotation_mean(rotations: list) -> np.ndarray:
    u, _, vt = np.linalg.svd(sum(rotations))
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    return rotation


@dataclass
class _Observation:
    """One of the target segment's cameras, with what it sees of the source."""

    frame: int
    object_points: np.ndarray   # in the SOURCE segment's frame
    image_points: np.ndarray    # pixels in the TARGET segment's keyframe
    r_target: np.ndarray        # the camera's pose in the TARGET's own frame
    t_target: np.ndarray
    r_pnp: np.ndarray           # the same camera, solved in the SOURCE's frame
    t_pnp: np.ndarray


def _solve_pnp_ransac_or_refuse(object_points, image_points, camera_matrix):
    """solvePnPRansac, converting a solver assertion into a refusal.

    SQPNP raises rather than returning False when the minimal sample
    RANSAC draws has degenerate coordinate variance:

        sqpnp.cpp:236 (-215) point_coordinate_variance >= POINT_VARIANCE_THRESHOLD

    Which sample gets drawn is data-dependent, so this fires on some real
    walks and not others. Reproduced on the 33-segment world built from
    capture 22e9d428.

    A degenerate configuration is exactly what a refusal is FOR. Letting
    the assertion escape turns "this keyframe could not be posed" into
    "the reconstruction process died", which on the live path means a walk
    ends mid-room.

    Inputs are validated BEFORE the call, so a cv2.error reaching the
    handler is a statement about the GEOMETRY rather than about our
    argument marshalling. That distinction needs enforcing rather than
    asserting: OpenCV raises cv2.error for malformed arguments too, so
    catching it without validating first would hide a real bug in this
    repo as an innocent refusal -- which is how a pipeline quietly stops
    reconstructing.
    """
    object_points = np.asarray(object_points, dtype=np.float64)
    image_points = np.asarray(image_points, dtype=np.float64)
    if object_points.ndim != 2 or object_points.shape[1] != 3:
        raise ValueError(
            f"object_points must be (N, 3), got {object_points.shape}"
        )
    if image_points.shape != (len(object_points), 2):
        raise ValueError(
            f"image_points must be ({len(object_points)}, 2), got "
            f"{image_points.shape}"
        )
    try:
        return cv2.solvePnPRansac(
            object_points,
            image_points,
            camera_matrix,
            None,
            reprojectionError=PNP_REPROJECTION_ERROR_PX,
            confidence=RANSAC_CONFIDENCE,
            flags=cv2.SOLVEPNP_SQPNP,
        )
    except cv2.error:
        return False, None, None, None


def _pnp_observations(source, target, matches, intrinsics) -> list:
    """PnP the source segment's landmarks into each of the target's keyframes.

    This is the route that works. A 3-D/3-D correspondence needs a landmark
    on BOTH sides of a match, and the association density on the real walk
    ranges 0.54% to 52%, so the product leaves the strongest links in the
    whole graph with fewer than six usable pairs. PnP needs the association
    on ONE side and yields 10-100x more constraints.
    """
    grouped: dict = {}
    for frame_a, frame_b, pairs in matches:
        objects, images = grouped.setdefault(frame_b, ({}, {}))
        for feature_a, feature_b in pairs:
            landmark = source.observed.get((frame_a, feature_a))
            # A feature in the target frame can be named by more than one
            # match. Keep the first claim, exactly as the backend's own
            # _extend does, so a later one cannot rebind it.
            if landmark is None or feature_b in objects:
                continue
            objects[feature_b] = landmark
            images[feature_b] = target.keypoints[frame_b][feature_b]

    observations = []
    for frame_b in sorted(grouped):
        objects, images = grouped[frame_b]
        if frame_b not in target.poses or len(objects) < MIN_PNP_CORRESPONDENCES:
            continue
        features = sorted(objects)
        object_points = np.asarray(
            [source.points[objects[f]] for f in features], dtype=np.float64
        )
        image_points = np.asarray(
            [images[f] for f in features], dtype=np.float64
        )
        ok, rvec, tvec, inliers = _solve_pnp_ransac_or_refuse(
            object_points, image_points, intrinsics
        )
        if not ok or inliers is None or len(inliers) < MIN_PNP_CORRESPONDENCES:
            continue
        keep = inliers.ravel()
        rotation, _ = cv2.Rodrigues(rvec)
        r_target, t_target = target.poses[frame_b]
        observations.append(
            _Observation(
                frame=frame_b,
                object_points=object_points[keep],
                image_points=image_points[keep],
                r_target=np.asarray(r_target, dtype=np.float64),
                t_target=np.asarray(t_target, dtype=np.float64).reshape(3),
                r_pnp=rotation,
                t_pnp=np.asarray(tvec, dtype=np.float64).reshape(3),
            )
        )
    return observations


def _residuals(params: np.ndarray, observations: list, intrinsics) -> np.ndarray:
    """Reprojection of the source's landmarks into the target's images.

    Writing the Sim3 as X_source = s R X_target + t and requiring both
    frames to describe the same physical ray gives the target camera's
    pose in the source's frame:

        R_source = R_target R^T        t_source = s t_target - R_source t

    so a candidate Sim3 induces a pose per camera and the residual is
    ordinary reprojection. Scale is observable exactly when moving it
    changes those reprojections -- which needs baseline between the
    target's cameras, and is why `span_over_depth` is reported.
    """
    scale = math.exp(params[0])
    rotation, _ = cv2.Rodrigues(params[1:4])
    translation = params[4:7]
    fx, fy = intrinsics[0, 0], intrinsics[1, 1]
    cx, cy = intrinsics[0, 2], intrinsics[1, 2]

    out = []
    for observation in observations:
        r_source = observation.r_target @ rotation.T
        t_source = scale * observation.t_target - r_source @ translation
        camera = (r_source @ observation.object_points.T).T + t_source
        depth = camera[:, 2]
        residual = np.empty((len(camera), 2))
        behind = depth <= 1e-6
        safe = np.where(behind, 1e-6, depth)
        residual[:, 0] = fx * camera[:, 0] / safe + cx - observation.image_points[:, 0]
        residual[:, 1] = fy * camera[:, 1] / safe + cy - observation.image_points[:, 1]
        # A point behind the camera is not a large error, it is a different
        # solution. Saturate rather than let the projection wrap sign and
        # look like a good fit.
        residual[behind] = 1e4
        out.append(residual)
    return np.concatenate(out) if out else np.zeros((0, 2))


def _huber_cost(params, observations, intrinsics) -> float:
    norms = np.linalg.norm(_residuals(params, observations, intrinsics), axis=1)
    return float(
        np.mean(np.where(norms < HUBER_PX, norms ** 2,
                         HUBER_PX * (2 * norms - HUBER_PX)))
    )


def _refine(params, observations, intrinsics, *, iterations=40, fix_scale=False):
    """Levenberg-damped Gauss-Newton with IRLS. numpy solves the 7x7.

    The Jacobian is numerical: seven parameters means seven extra residual
    evaluations per iteration, which is cheaper than being wrong about an
    analytic derivative nobody can check.
    """
    params = np.asarray(params, dtype=np.float64).copy()
    free = [i for i in range(7) if not (fix_scale and i == 0)]
    damping = 1e-3
    cost = _huber_cost(params, observations, intrinsics)

    for _ in range(iterations):
        base = _residuals(params, observations, intrinsics)
        norms = np.linalg.norm(base, axis=1)
        weights = np.repeat(
            np.where(norms < HUBER_PX, 1.0,
                     np.sqrt(HUBER_PX / np.maximum(norms, 1e-9))), 2
        )
        jacobian = np.zeros((base.size, len(free)))
        for column, index in enumerate(free):
            step = 1e-5 * max(abs(params[index]), 1.0)
            probe = params.copy()
            probe[index] += step
            jacobian[:, column] = (
                (_residuals(probe, observations, intrinsics) - base) / step
            ).ravel()
        weighted_j = jacobian * weights[:, None]
        weighted_r = base.ravel() * weights
        hessian = weighted_j.T @ weighted_j
        gradient = weighted_j.T @ weighted_r

        for _attempt in range(12):
            try:
                delta = np.linalg.solve(
                    hessian + damping * np.diag(np.maximum(np.diag(hessian), 1e-9)),
                    -gradient,
                )
            except np.linalg.LinAlgError:
                damping *= 10
                continue
            probe = params.copy()
            for column, index in enumerate(free):
                probe[index] += delta[column]
            probe_cost = _huber_cost(probe, observations, intrinsics)
            if probe_cost < cost:
                params, cost = probe, probe_cost
                damping = max(damping * 0.3, 1e-9)
                break
            damping *= 10
        else:
            break
    return params, cost


def _initial_params(observations: list, scale: float) -> np.ndarray:
    """Rotation from the PnP solves, translation from the camera centres.

    The PnP rotations are the reliable half: measured across independent
    cameras on the real walk they agreed to 0.36-6.6 degrees even on pairs
    whose scale was hopeless. Seeding rotation from them and searching only
    over scale is what makes a 45-point grid enough.
    """
    rotations = [o.r_pnp.T @ o.r_target for o in observations]
    rotation = _chordal_rotation_mean(rotations)
    offsets = [
        (-o.r_pnp.T @ o.t_pnp) - scale * (rotation @ (-o.r_target.T @ o.t_target))
        for o in observations
    ]
    rvec, _ = cv2.Rodrigues(rotation)
    return np.concatenate(
        [[math.log(scale)], rvec.ravel(), np.median(np.array(offsets), axis=0)]
    )


def fit_direction(source, target, matches) -> DirectedFit | None:
    """Estimate the Sim3 mapping `target`'s frame into `source`'s frame.

    Returns None -- never a low-confidence answer -- when the target's
    cameras cannot be placed. A refusal is a first-class result here for
    the same reason it is in the geometry backend: an estimate nobody
    should use is worse than no estimate, because something downstream
    will use it.
    """
    intrinsics = source.intrinsics
    observations = _pnp_observations(source, target, matches, intrinsics)
    if len(observations) < 2:
        return None

    grid = np.exp(
        np.linspace(math.log(SCALE_GRID_MIN), math.log(SCALE_GRID_MAX),
                    SCALE_GRID_STEPS)
    )
    profile = []
    for candidate in grid:
        seeded = _initial_params(observations, float(candidate))
        refined, cost = _refine(seeded, observations, intrinsics,
                                iterations=25, fix_scale=True)
        profile.append((float(candidate), cost, refined))

    best_scale, best_cost, best_params = min(profile, key=lambda row: row[1])
    params, _cost = _refine(best_params, observations, intrinsics, iterations=60)

    costs = np.array([row[1] for row in profile])
    scales = np.array([row[0] for row in profile])
    near = costs <= 1.5 * costs.min()
    ambiguity = (
        float(scales[near].max() / scales[near].min()) if near.any() else float("inf")
    )

    scale = math.exp(params[0])
    rotation, _ = cv2.Rodrigues(params[1:4])
    residuals = np.linalg.norm(_residuals(params, observations, intrinsics), axis=1)
    return DirectedFit(
        source=source.index,
        target=target.index,
        scale=scale,
        rotation=rotation,
        translation=params[4:7].copy(),
        cameras=len(observations),
        correspondences=int(len(residuals)),
        reprojection_px=float(np.median(residuals)),
        scale_ambiguity=ambiguity,
        # Tagged with the segment, not just the frame number. Two segments
        # both numbering their frames from zero would otherwise collide,
        # and a collision here reads as "not independent" and silently
        # refuses a real pair.
        provenance=frozenset(
            (target.index, observation.frame) for observation in observations
        ),
        target_span_over_depth=target.span_over_depth,
    )


# -- the gate --------------------------------------------------------------


def admit(evidence: MutualEvidence, thresholds: Thresholds) -> Verdict:
    """Decide whether a segment pair may be placed. Takes MUTUAL evidence only.

    The type check below is load-bearing, not defensive. A `DirectedFit`
    carries every fit-quality number and would sail through any check
    written in terms of reprojection -- which is exactly how (30,50), wrong
    by 3.2x at 1.62 px, would be admitted. Refusing the type refuses the
    whole class of mistake, at the one place a decision is made.

    The type check is necessary and not sufficient: see
    `MutualEvidence.__post_init__`, where the provenance clause refuses a
    reverse fit that was manufactured from the forward one by relabelling.
    """
    if not isinstance(evidence, MutualEvidence):
        raise TypeError(
            "admit() takes MutualEvidence, not "
            f"{type(evidence).__name__}. A single direction's fit quality "
            "cannot admit a pair: on the real walk, segments (30,50) fit at "
            "1.62 px with 88% of correspondences under 3 px and were wrong "
            "by a factor of 3.2 in scale (measured in "
            "docs/superpowers/research/"
            "2026-08-26-cross-segment-registration.md section 6). Solve the "
            "other direction for real -- PnP the other segment's landmarks "
            "into this one's images -- and compare the scales."
        )

    forward, reverse = evidence.forward, evidence.reverse
    reciprocity = evidence.reciprocity
    cameras = min(forward.cameras, reverse.cameras)
    ambiguity = max(forward.scale_ambiguity, reverse.scale_ambiguity)
    reprojection = max(forward.reprojection_px, reverse.reprojection_px)

    # Both directions' targets, so the clause covers BOTH segments: the
    # forward fit poses the second segment's cameras and the reverse fit
    # poses the first's.
    span_over_depth = min(
        forward.target_span_over_depth, reverse.target_span_over_depth
    )
    rotation_disagreement = evidence.rotation_disagreement_deg
    clauses = {
        "cameras": cameras,
        "reciprocity": reciprocity,
        "rotation_disagreement_deg": rotation_disagreement,
        "scale_ambiguity": ambiguity,
        "reprojection_px": reprojection,
        "span_over_depth": span_over_depth,
        "correspondences": min(forward.correspondences, reverse.correspondences),
    }

    def refuse(reason):
        return Verdict(evidence.pair, False, reason, reciprocity, clauses)

    if not (
        math.isfinite(forward.scale)
        and math.isfinite(reverse.scale)
        and forward.scale > 0
        and reverse.scale > 0
    ):
        return refuse(
            "the solve collapsed: a scale of zero or worse, which places the "
            "whole segment at a point"
        )
    if cameras < thresholds.min_cameras:
        return refuse(
            f"only {cameras} of the segment's cameras could be placed; "
            f"{thresholds.min_cameras} are needed before a baseline means "
            "anything"
        )
    # Checked before fit quality on purpose: this is the independent
    # evidence, and reading it first keeps the ordering of the code honest
    # about which clause is carrying the decision.
    if span_over_depth < thresholds.min_span_over_depth:
        return refuse(
            f"the wearer stood still: one segment's cameras span only "
            f"{span_over_depth:.3f} of the scene depth, so its scale is not "
            "recoverable from them at any quality of match"
        )
    if abs(reciprocity - 1.0) > thresholds.max_reciprocity_error:
        return refuse(
            f"the two directions disagree on scale by {_ratio(reciprocity):.2f}x; "
            "each was solved independently, so they should be reciprocal"
        )
    if rotation_disagreement > thresholds.max_rotation_disagreement_deg:
        return refuse(
            f"the two directions disagree about orientation by "
            f"{rotation_disagreement:.1f} degrees; composed they should "
            "return to identity, so one of them folds this segment's "
            "geometry through the other's"
        )
    if ambiguity > thresholds.max_scale_ambiguity:
        return refuse(
            f"the scale is ambiguous over a {ambiguity:.1f}x range -- the fit "
            "is equally good across it, so its scale is not a measurement"
        )
    if reprojection > thresholds.max_reprojection_px:
        return refuse(
            f"the fit reprojects at {reprojection:.2f} px, above the "
            f"{thresholds.max_reprojection_px:.0f} px bar"
        )
    return Verdict(
        evidence.pair,
        True,
        f"both directions agree on scale to {abs(reciprocity - 1.0):.1%} "
        f"and on orientation to {rotation_disagreement:.1f} deg",
        reciprocity,
        clauses,
    )


def _ratio(value: float) -> float:
    """A disagreement of 0.31x and one of 3.2x are the same disagreement."""
    if value <= 0:
        return float("inf")
    return value if value >= 1.0 else 1.0 / value


# -- composition -----------------------------------------------------------


# How far a loop may fail to close before the cluster containing it is
# refused.
#
# Every clause in `admit()` judges ONE pair from that pair's own evidence.
# None can see an error that only appears going round a loop, which is
# the failure the research note calls the dangerous one: a wrong Sim3
# fits well and reads as a slightly odd floor plan rather than as an
# error.
#
# Set from evidence, like the other thresholds here. The only real cycle
# in the corpus -- (12,16), (12,19), (16,19) on capture 2e6cffa2 --
# closes to 5.899 degrees and a 1.06x scale ratio, and every one of those
# three edges passed reciprocity individually. The documented broken
# cases are wrong rotations of 31.9 to 166.0 degrees and a scale 3.2x
# out. These bars sit between: roughly 3x the measured honest residual
# and comfortably below every documented failure.
#
# Deliberately looser than the single-edge bars (15 deg, 10% scale),
# because a residual accumulates over a whole path while those judge one
# hop.
MAX_CYCLE_ROTATION_DEG = 20.0
MAX_CYCLE_SCALE_RATIO = 2.0


def cycle_refusal_for(residuals, thresholds=None) -> str | None:
    """The reason a cluster's loops disqualify it, or None.

    Refuses on the WHOLE cluster rather than on the closing edge. The
    closure is not in the spanning tree, so dropping it would change no
    placement and leave the bad edge in place. A cycle proves an
    inconsistency exists without saying which edge carries it, and a
    cluster known to contain a false merge must not be presented as one
    space -- that is the failure mode the registration research calls the
    dangerous one, because it reads as a slightly odd floor plan.
    """
    rotation_bar = MAX_CYCLE_ROTATION_DEG
    scale_bar = MAX_CYCLE_SCALE_RATIO
    if thresholds is not None:
        rotation_bar = getattr(thresholds, "max_cycle_rotation_deg", rotation_bar)
        scale_bar = getattr(thresholds, "max_cycle_scale_ratio", scale_bar)
    for residual in residuals:
        if (
            residual["rotation_deg"] > rotation_bar
            or residual["scale_ratio"] > scale_bar
        ):
            return (
                f"the loop through {tuple(residual['edge'])} does not "
                f"close: composing round it disagrees with the direct "
                f"estimate by {residual['rotation_deg']:.1f} degrees and "
                f"{residual['scale_ratio']:.2f}x in scale. One of this "
                "cluster's edges is wrong and the cycle cannot say which, "
                "so the whole cluster is refused rather than drawn with a "
                "fold in it"
            )
    return None


def cycle_residuals(edges, placements, tree_edges=()) -> list:
    """How badly each closing edge disagrees with the path around the loop.

    `compose_tree` places segments along a SPANNING TREE, so every
    admitted edge it did not need is a cycle closure -- an independent
    second opinion about a relationship the tree already asserts.

    For a closure a->b, the placements say where both segments sit, so
    `placement[b] . placement[a]^-1` is the relationship the tree claims.
    The edge's own fit says something too. The difference between them is
    evidence no single pair could produce.

    Tree edges are named explicitly rather than inferred from a
    near-zero residual: a PERFECTLY consistent closure is the best
    possible outcome and would be indistinguishable from a tree edge,
    so inferring would silently discard exactly the evidence worth
    having. Edges touching an unplaced segment are skipped because there
    is nothing to compose against, and inventing a residual would be
    fiction.

    Scale is reported as a ratio >= 1 whichever way it is wrong: 0.31x and
    3.2x are the same disagreement, and a bar on the raw ratio would catch
    one and miss the other.
    """
    tree = {tuple(edge) for edge in tree_edges}
    residuals = []
    for source, target, scale, rotation, translation in edges:
        if (source, target) in tree:
            # The tree was BUILT from this edge. Comparing it against
            # placements derived from it agrees trivially, and counting
            # that as a passing check would overstate the evidence.
            continue
        if source not in placements or target not in placements:
            continue
        edge = Sim3(
            float(scale),
            np.asarray(rotation, dtype=np.float64),
            np.asarray(translation, dtype=np.float64),
        )
        claimed = placements[target].compose(_invert_sim3(placements[source]))
        difference = edge.compose(_invert_sim3(claimed))

        ratio = float(difference.scale)
        if ratio <= 0:
            ratio = float("inf")
        elif ratio < 1.0:
            ratio = 1.0 / ratio
        cosine = (float(np.trace(difference.rotation)) - 1.0) / 2.0
        degrees = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
        offset = float(np.linalg.norm(difference.translation))

        residuals.append({
            "edge": (source, target),
            "scale_ratio": ratio,
            "rotation_deg": degrees,
            "translation": offset,
        })
    return residuals


def _invert_sim3(transform):
    rotation = np.asarray(transform.rotation, dtype=np.float64).T
    scale = 1.0 / float(transform.scale)
    return Sim3(
        scale,
        rotation,
        -scale * (rotation @ np.asarray(transform.translation, dtype=np.float64)),
    )


def compose_tree(edges, reference: int) -> dict:
    """Placements only. See compose_tree_with_edges for the edges used."""
    return compose_tree_with_edges(edges, reference)[0]


def compose_tree_with_edges(edges, reference: int):
    """Place every segment reachable from `reference`, by composing edges.

    Breadth-first, so each segment is placed along the shortest path of
    admitted edges. Scale errors multiply through a composition, so the
    shortest path is the one that multiplies fewest of them.

    A spanning tree is used rather than a pose graph because on the real
    walk the admitted subgraph has no cycle at all -- the candidate
    closure, (4,32), refuses registration entirely. There is nothing for a
    pose-graph optimiser to optimise. When cycles do appear, the right next
    step is cycle-consistency CHECKING, which is free and independent;
    optimisation only after that.

    Unreachable segments are absent from the result rather than present
    with an identity transform. An identity is a claim about where a
    segment is, and "we do not know" is not that claim.
    """
    adjacency: dict = {}
    for source, target, scale, rotation, translation in edges:
        transform = Sim3(float(scale), np.asarray(rotation, dtype=np.float64),
                         np.asarray(translation, dtype=np.float64))
        adjacency.setdefault(source, []).append(
            (target, transform, (source, target))
        )
        inverse_rotation = transform.rotation.T
        inverse_scale = 1.0 / transform.scale
        adjacency.setdefault(target, []).append((
            source,
            Sim3(inverse_scale, inverse_rotation,
                 -inverse_scale * (inverse_rotation @ transform.translation)),
            # The edge is named by its ORIGINAL orientation, so the tree
            # reports the same identity whichever way it traversed it.
            (source, target),
        ))

    placements = {reference: IDENTITY}
    used_edges = set()
    queue = [reference]
    while queue:
        current = queue.pop(0)
        for neighbour, transform, edge in adjacency.get(current, ()):
            if neighbour in placements:
                continue
            placements[neighbour] = placements[current].compose(transform)
            used_edges.add(edge)
            queue.append(neighbour)
    return placements, used_edges


# -- reading a world -------------------------------------------------------


def read_segments(store: WorldStore, world_id: str, session_id: str) -> dict:
    """Every segment that has geometry, with its association restored.

    Segments with no triangulated point are omitted, and that is the
    important framing rather than an implementation detail: on the real
    51-segment walk only 19 qualify. The other 32 are a lone anchor at the
    origin with no structure -- including segment 0, which a prior
    investigation highlighted for matching segments 45, 47, 48 and 50.
    Those matches are real as IMAGE matches and unusable as registrations,
    because segment 0 has no reconstruction to place.
    """
    derived = store.read_derived(world_id, session_id)
    if derived is None:
        raise SupportMissingError(
            f"world {world_id} has no current derived reconstruction; "
            "rebuild it before registering."
        )
    if derived.get("support") is None:
        raise SupportMissingError(
            f"world {world_id} has no support.json: the 2-D/3-D association "
            "(which feature in which keyframe made each point) is not on "
            "disk. Worlds built before that artifact existed do not carry "
            "it. Rebuild the session and run this again -- registration is "
            "not attempted without it, and re-solving silently would hide "
            "minutes of work behind a read."
        )

    session = store.read_session(world_id, session_id)
    intrinsics = session.intrinsics.camera_matrix()
    if intrinsics is None:
        raise SupportMissingError(
            f"world {world_id} has no camera matrix; registration needs the "
            "same calibrated intrinsics the reconstruction used."
        )

    keyframes = store.read_keyframes(world_id, session_id)
    by_segment: dict = {}
    for keyframe in keyframes:
        by_segment.setdefault(keyframe.segment_index, []).append(keyframe)

    points_by_segment: dict = {}
    for row in derived["points"]:
        points_by_segment.setdefault(row["segment_index"], []).append(row["xyz"])

    poses_by_segment: dict = {}
    for row in derived["poses"]:
        poses_by_segment.setdefault(row["segment_index"], []).append(row)

    support_by_segment: dict = {}
    for segment, frame, feature, point in derived["support"]:
        support_by_segment.setdefault(segment, []).append((frame, feature, point))

    session_dir = store.session_dir(world_id, session_id)
    segments: dict = {}
    for index in sorted(points_by_segment):
        members = by_segment.get(index, [])
        support = support_by_segment.get(index)
        if not members or not support:
            continue
        keypoints, descriptors = [], []
        for keyframe in members:
            gray = decode_gray((session_dir / keyframe.image_relpath).read_bytes())
            detected, described = detect_and_describe(gray)
            keypoints.append(
                np.array([kp.pt for kp in detected], dtype=np.float64)
                if detected else np.zeros((0, 2))
            )
            descriptors.append(described)
        segments[index] = SegmentGeometry(
            index=index,
            keypoints=keypoints,
            descriptors=descriptors,
            points=np.asarray(points_by_segment[index], dtype=np.float64),
            poses=_poses_in_segment_frame(poses_by_segment.get(index, [])),
            observed={(frame, feature): point for frame, feature, point in support},
            intrinsics=intrinsics,
        )
    return segments


def _poses_in_segment_frame(rows: list) -> dict:
    """poses.json back to the OpenCV convention PnP and projection want.

    The persisted contract is T_world_camera: the quaternion is
    R_world_camera and the translation IS the camera's position, chosen so
    no consumer has to invert anything. Projection needs the opposite --
    world-into-camera -- so it is inverted here, once, rather than left to
    each caller:

        R = R_world_camera^T          t = -R @ C
    """
    poses = {}
    for frame, row in enumerate(rows):
        if row["status"] == POSE_STATUS_UNAVAILABLE:
            continue
        if row["rotation"] is None or row["translation"] is None:
            continue
        rotation_world_camera = _quaternion_wxyz_to_rotation(row["rotation"])
        rotation = rotation_world_camera.T
        centre = np.asarray(row["translation"], dtype=np.float64)
        poses[frame] = (rotation, -rotation @ centre)
    return poses



def pair_is_hopeless(source, target, thresholds) -> str | None:
    """Why this pair cannot register, decided before any matching.

    `admit()` refuses on min(forward.target_span_over_depth,
    reverse.target_span_over_depth). The forward fit's target is `target`
    and the reverse fit's target is `source`, so that minimum is just the
    smaller of the two segments' own span/depth -- a number computable
    from poses.json and points.json alone, which is what
    `span_over_depth` above already says it is for.

    Using it only AFTER matching meant every hopeless pair paid a full
    keyframe cross-product of brute-force ORB plus a MAGSAC
    essential-matrix fit to reach a conclusion already available. Measured
    before this: 139 s for a seven-segment world, which is why
    registration cannot run anywhere near the live path.

    Returns the refusal reason, or None if the pair is worth matching.
    Deliberately the SAME bar as the gate: a prune stricter than admit()
    would silently refuse pairs the gate would have taken.
    """
    span = min(source.span_over_depth, target.span_over_depth)
    if span < thresholds.min_span_over_depth:
        return (
            f"the wearer stood still: one segment's cameras span only "
            f"{span:.3f} of the scene depth, so its scale is not "
            "recoverable from them at any quality of match"
        )
    return None


# How many keyframes of a segment take part in cross-segment matching.
#
# `cross_matches` compared every keyframe of one segment against every
# keyframe of the other -- an O(F^2) brute-force ORB cross-product that
# dominates registration cost and is why it cannot run anywhere near the
# live path. On the corpus one segment carries 89 keyframes against a
# median of 10, so a handful of segments pay almost all of it.
#
# MEASURED, on both captures in the corpus that register anything at all.
# Verdicts are identical to the full cross-product at 8, and gone at 5:
#
#   e1c52b9f   full 192.4s -> 3 segs / 5603 pts   [(0,3), (3,5)]
#              k=8   43.6s -> 3 segs / 5603 pts   [(0,3), (3,5)]   MATCH
#              k=5   22.7s -> 0 segs / 0 pts      []               LOST
#              k=3   10.0s -> 0 segs / 0 pts      []               LOST
#   2e6cffa2   k=8   19.4s -> 3 segs / 1917 pts   [(12,16),(12,19),(16,19)]
#                             identical to the full run
#
# 8 is therefore a measured boundary rather than a tuning knob: it is the
# smallest sample that preserved every verdict, and the next step down
# lost all of them. It is deliberately NOT lowered for speed -- the whole
# value of this function is the verdicts.
MAX_KEYFRAMES_PER_SEGMENT_FOR_MATCHING = 8


def sampled_frames(count: int, limit: int) -> list:
    """Evenly spread frame indices, always including first and last.

    Spread rather than truncated: a segment's keyframes are ordered in
    time, so the first N of them cover only its opening and would miss
    whatever the wearer walked to. Endpoints are included because a
    segment's two ends are the most likely places to overlap a
    neighbouring segment.
    """
    if count <= limit:
        return list(range(count))
    if limit <= 1:
        return [0]
    return sorted({
        int(round(i * (count - 1) / (limit - 1))) for i in range(limit)
    })


def cross_matches(source, target, *, min_inliers: int = MIN_INLIERS) -> list:
    """Verified feature correspondences between two segments' keyframes.

    Verification is the backend's own: ORB, Lowe ratio, then an essential
    matrix at the same threshold and confidence the reconstruction used.
    An unverified descriptor match is a guess, and on repetitive indoor
    texture it is often a confident one.

    Only a sample of each segment's keyframes takes part -- see
    MAX_KEYFRAMES_PER_SEGMENT_FOR_MATCHING for the measurement that fixed
    the sample size. Returned frame indices are the segment's OWN indices,
    so poses and the observation index still line up.
    """
    matches = []
    intrinsics = source.intrinsics
    frames_a = sampled_frames(
        len(source.descriptors), MAX_KEYFRAMES_PER_SEGMENT_FOR_MATCHING
    )
    frames_b = sampled_frames(
        len(target.descriptors), MAX_KEYFRAMES_PER_SEGMENT_FOR_MATCHING
    )
    for frame_a in frames_a:
        for frame_b in frames_b:
            pairs = match_indices(source.descriptors[frame_a],
                                  target.descriptors[frame_b])
            if len(pairs) < min_inliers:
                continue
            points_a = np.float32([source.keypoints[frame_a][i] for i, _ in pairs])
            points_b = np.float32([target.keypoints[frame_b][j] for _, j in pairs])
            essential, mask = cv2.findEssentialMat(
                points_a, points_b, intrinsics,
                method=cv2.USAC_MAGSAC,
                prob=RANSAC_CONFIDENCE,
                threshold=RANSAC_THRESHOLD_PX,
            )
            if essential is None or mask is None:
                continue
            kept = [p for p, keep in zip(pairs, mask.ravel() > 0) if keep]
            if len(kept) >= min_inliers:
                matches.append((frame_a, frame_b, kept))
    return matches


# -- the run ---------------------------------------------------------------


def register(store: WorldStore, world_id: str, session_id: str,
             thresholds: Thresholds | None = None) -> dict:
    """Read, link, fit both directions, gate, compose. Writes nothing."""
    thresholds = thresholds or Thresholds()
    segments = read_segments(store, world_id, session_id)
    keyframes = store.read_keyframes(world_id, session_id)
    all_segments = sorted({k.segment_index for k in keyframes})
    derived = store.read_derived(world_id, session_id)
    points_total = len(derived["points"])
    points_by_segment: dict = {}
    for row in derived["points"]:
        points_by_segment[row["segment_index"]] = (
            points_by_segment.get(row["segment_index"], 0) + 1
        )

    indices = sorted(segments)
    verdicts, admitted = [], []
    for position, left in enumerate(indices):
        for right in indices[position + 1:]:
            hopeless = pair_is_hopeless(
                segments[left], segments[right], thresholds
            )
            if hopeless is not None:
                # Refused on evidence already in hand, without paying for
                # the matching. Same verdict, same reason string as the
                # gate would have produced -- only sooner.
                verdicts.append(
                    Verdict((left, right), False, hopeless, float("nan"), {})
                )
                continue
            matches = cross_matches(segments[left], segments[right])
            if not matches:
                continue
            forward = fit_direction(segments[left], segments[right], matches)
            reverse = fit_direction(
                segments[right], segments[left],
                [(b, a, [(y, x) for x, y in pairs]) for a, b, pairs in matches],
            )
            if forward is None or reverse is None:
                # Distinguished, because "one direction worked" and
                # "neither did" are different facts about the world and
                # 61 of 74 pairs on the real walk are the second one.
                # Reporting them all as the first overstates how close
                # the pair came.
                if forward is None and reverse is None:
                    reason = (
                        "neither direction could be solved: too few of "
                        "either segment's cameras could be placed against "
                        "the other's landmarks"
                    )
                else:
                    solved = left if forward is not None else right
                    reason = (
                        f"only the {solved}-side direction could be solved, "
                        "so there is no second estimate to check it against"
                    )
                verdicts.append(Verdict(
                    (left, right), False, reason, float("nan"),
                    {"forward": forward is not None,
                     "reverse": reverse is not None},
                ))
                continue
            verdict = admit(MutualEvidence(forward=forward, reverse=reverse),
                            thresholds)
            verdicts.append(verdict)
            if verdict.registered:
                admitted.append(
                    (left, right, forward.scale, forward.rotation,
                     forward.translation)
                )

    reference = _pick_reference(admitted, points_by_segment)
    if reference is None:
        placements, tree_edges = {}, set()
    else:
        placements, tree_edges = compose_tree_with_edges(admitted, reference)

    # The first independent check this module can run. Every clause in
    # admit() judges one pair from that pair's own evidence; a loop is the
    # only thing that can disagree with a relationship the tree already
    # asserts.
    residuals = cycle_residuals(admitted, placements, tree_edges)
    cycle_refusal = cycle_refusal_for(residuals)
    if cycle_refusal is not None:
        # Refusing the WHOLE component, not the closing edge. The closure
        # is not in the tree, so dropping it would change nothing and
        # leave the bad edge in place. A cycle proves an inconsistency
        # exists without localising it, and a cluster known to contain a
        # false merge must not be presented as one space.
        placements = {}

    rows = []
    for index in all_segments:
        rows.append(_segment_row(index, segments, placements, verdicts,
                                 points_by_segment, reference))
    registered = [r for r in rows if r["registered"]]
    return {
        "world_id": world_id,
        "session_id": session_id,
        "reference_segment": reference,
        "segment_count": len(all_segments),
        "segments_with_geometry": len(segments),
        "segments_registered": len(registered),
        "points_total": points_total,
        "points_registered": sum(
            points_by_segment.get(r["segment_index"], 0) for r in registered
        ),
        "candidate_pairs": len(verdicts),
        "admitted_pairs": [[a, b] for a, b, *_ in admitted],
        # Reported whether or not they refuse anything. A cluster whose
        # loops close tightly is better evidence than one with no loops at
        # all, and until now there was no way to tell those apart.
        "cycles_checked": len(residuals),
        "cycle_residuals": [
            {
                "edge": [r["edge"][0], r["edge"][1]],
                "rotation_deg": r["rotation_deg"],
                "scale_ratio": r["scale_ratio"],
                "translation": r["translation"],
            }
            for r in residuals
        ],
        "cycle_refusal": cycle_refusal,
        "pairs": [_verdict_row(v) for v in verdicts],
        "segments": rows,
    }


def _pick_reference(admitted, points_by_segment):
    """The segment carrying the most points in the largest admitted group.

    Arbitrary but not accidental: the reference defines the world frame,
    and anchoring it to the best-reconstructed segment means the composed
    transforms are shortest where the geometry is strongest.
    """
    if not admitted:
        return None
    adjacency: dict = {}
    for left, right, *_ in admitted:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    seen, components = set(), []
    for node in adjacency:
        if node in seen:
            continue
        stack, component = [node], []
        seen.add(node)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(component)
    largest = max(components, key=len)
    return max(largest, key=lambda s: points_by_segment.get(s, 0))


def _segment_row(index, segments, placements, verdicts, points_by_segment,
                 reference) -> dict:
    """One segment's outcome, and in plain terms WHY when it is not placed."""
    geometry = segments.get(index)
    placement = placements.get(index)
    row = {
        "segment_index": index,
        "registered": placement is not None,
        "transform_to_world": placement.to_json_dict() if placement else None,
        "points": points_by_segment.get(index, 0),
        "span_over_depth": (
            round(geometry.span_over_depth, 4) if geometry else None
        ),
        "cameras": len(geometry.poses) if geometry else 0,
    }
    if placement is not None:
        row["reason"] = (
            "reference segment: it defines the world frame"
            if index == reference
            else "placed by composing admitted pairs back to the reference"
        )
        return row

    if geometry is None:
        row["reason"] = (
            "no geometry: this segment triangulated no points at all, so "
            "there is nothing to place -- it is a lone origin marker"
        )
        return row
    if geometry.span_over_depth < MIN_SPAN_OVER_DEPTH:
        row["reason"] = (
            f"the wearer stood still: the segment's own cameras span only "
            f"{geometry.span_over_depth:.3f} of the scene depth, so its scale "
            "is not recoverable from them at any quality of match"
        )
        return row

    involved = [v for v in verdicts if index in v.pair]
    if not involved:
        row["reason"] = (
            "no verified visual link to any other segment with geometry"
        )
        return row
    best = min(involved, key=lambda v: _ratio(v.reciprocity)
               if math.isfinite(v.reciprocity) else float("inf"))
    row["reason"] = (
        f"linked to {len(involved)} segment(s), but none was admitted; "
        f"closest was segment {[s for s in best.pair if s != index][0]}, "
        f"where {best.reason}"
    )
    return row


def _verdict_row(verdict: Verdict) -> dict:
    return {
        "pair": [int(verdict.pair[0]), int(verdict.pair[1])],
        "registered": bool(verdict.registered),
        "reason": verdict.reason,
        "reciprocity": (
            round(float(verdict.reciprocity), 5)
            if math.isfinite(verdict.reciprocity) else None
        ),
        "clauses": {k: _plain(v) for k, v in verdict.clauses.items()},
    }


# -- output ----------------------------------------------------------------


def _plain(value):
    # bool BEFORE int, and np.bool_ before np.integer. `bool` is a subclass
    # of `int` in Python, so the integer branch would silently turn
    # `registered: true` into `registered: 1` -- a field the geometry
    # contract declares as a boolean and a viewer switches on.
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return round(value, 5) if math.isfinite(value) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def report_to_json(report: dict) -> dict:
    """Plain JSON types throughout, so the output survives a round trip."""
    return _plain(report)


def render_text(report: dict) -> str:
    lines = [
        f"world {report['world_id']}  session {report['session_id']}",
        "",
        f"  segments                 {report['segment_count']}",
        f"  with geometry            {report['segments_with_geometry']}",
        f"  registered               {report['segments_registered']}",
        f"  reference segment        {report['reference_segment']}",
        f"  points registered        {report['points_registered']} of "
        f"{report['points_total']}"
        + (
            f" ({report['points_registered'] / report['points_total']:.1%})"
            if report["points_total"] else ""
        ),
        f"  candidate pairs          {report['candidate_pairs']}",
        f"  admitted pairs           {report['admitted_pairs'] or 'none'}",
        "",
        "segments",
    ]
    for row in report["segments"]:
        mark = "REGISTERED" if row["registered"] else "          "
        span = (
            f"{row['span_over_depth']:.3f}"
            if row["span_over_depth"] is not None else "  -  "
        )
        lines.append(
            f"  {row['segment_index']:>3}  {mark}  points {row['points']:>5}  "
            f"cams {row['cameras']:>3}  span/depth {span}"
        )
        lines.append(f"       {row['reason']}")
    if report["pairs"]:
        lines += ["", "pairs"]
        for pair in report["pairs"]:
            mark = "ADMITTED" if pair["registered"] else "refused "
            reciprocity = (
                f"{pair['reciprocity']:.4f}"
                if pair["reciprocity"] is not None else "   -  "
            )
            lines.append(
                f"  ({pair['pair'][0]:>3},{pair['pair'][1]:>3})  {mark}  "
                f"reciprocity {reciprocity}"
            )
            lines.append(f"       {pair['reason']}")
    return "\n".join(lines)


# -- quaternions -----------------------------------------------------------


def _rotation_to_quaternion_wxyz(rotation) -> list:
    rotation = np.asarray(rotation, dtype=np.float64)
    trace = float(np.trace(rotation))
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w = 0.25 * s
        x = (rotation[2, 1] - rotation[1, 2]) / s
        y = (rotation[0, 2] - rotation[2, 0]) / s
        z = (rotation[1, 0] - rotation[0, 1]) / s
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        s = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2
        w = (rotation[2, 1] - rotation[1, 2]) / s
        x = 0.25 * s
        y = (rotation[0, 1] + rotation[1, 0]) / s
        z = (rotation[0, 2] + rotation[2, 0]) / s
    elif rotation[1, 1] > rotation[2, 2]:
        s = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2
        w = (rotation[0, 2] - rotation[2, 0]) / s
        x = (rotation[0, 1] + rotation[1, 0]) / s
        y = 0.25 * s
        z = (rotation[1, 2] + rotation[2, 1]) / s
    else:
        s = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2
        w = (rotation[1, 0] - rotation[0, 1]) / s
        x = (rotation[0, 2] + rotation[2, 0]) / s
        y = (rotation[1, 2] + rotation[2, 1]) / s
        z = 0.25 * s
    return [float(w), float(x), float(y), float(z)]


def _quaternion_wxyz_to_rotation(quaternion) -> np.ndarray:
    w, x, y, z = (float(v) for v in quaternion)
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm <= 1e-12:
        return np.eye(3)
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


# -- cli -------------------------------------------------------------------


def placements_from_report(report: dict, input_digest=None):
    """Turn a registration report into records the store can hold.

    Every segment the report mentions gets a row, registered or refused,
    because "refused, and here is why" is a different and more useful fact
    than the absence of a row -- and absence would be indistinguishable
    from "this pass never looked at that segment".
    """
    from tower.world_builder.records import SegmentPlacement

    reference = report.get("reference_segment")
    rows = []
    # Every row carries the digest of the build it was solved against. A
    # placement is a statement about SPECIFIC points; without this it
    # outlives the reconstruction it was fitted to and is served against
    # geometry that no longer exists.
    for entry in report.get("segments", []):
        transform = entry.get("transform_to_world")
        if entry.get("registered") and transform:
            rows.append(
                SegmentPlacement(
                    segment_index=int(entry["segment_index"]),
                    state="registered",
                    rotation_wxyz=tuple(transform["rotation_wxyz"]),
                    translation=tuple(transform["translation"]),
                    scale=float(transform["scale"]),
                    reference_segment=reference,
                    refusal_reason=None,
                    input_digest=input_digest,
                    evidence={
                        key: entry[key]
                        for key in ("points", "cameras", "span_over_depth")
                        if key in entry
                    },
                )
            )
        else:
            rows.append(
                SegmentPlacement(
                    segment_index=int(entry["segment_index"]),
                    state="refused",
                    rotation_wxyz=None,
                    translation=None,
                    scale=None,
                    reference_segment=None,
                    refusal_reason=entry.get("reason"),
                    input_digest=input_digest,
                    evidence={
                        key: entry[key]
                        for key in ("points", "cameras", "span_over_depth")
                        if key in entry
                    },
                )
            )
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate a per-segment Sim3 for a saved world. Reads a world "
            "and prints the result; writes placements back only with "
            "--write, and never touches poses, points or support."
        )
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--world", required=True, help="World id to register.")
    parser.add_argument(
        "--session",
        help="Session id. Defaults to the world's only session.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Persist the result as derived/<session>/placements.json. "
            "Off by default: registration is an expensive pass whose "
            "verdicts change with its thresholds, and a run made to "
            "explore a threshold must not silently become what the world "
            "serves."
        ),
    )
    parser.add_argument(
        "--max-reciprocity-error", type=float,
        default=Thresholds.max_reciprocity_error,
        help=(
            "How far the two independent directions may disagree on scale. "
            "This is the clause that carries the decision; loosening it is a "
            "decision about how wrong a drawn map may be."
        ),
    )
    parser.add_argument(
        "--max-scale-ambiguity", type=float,
        default=Thresholds.max_scale_ambiguity,
    )
    parser.add_argument(
        "--min-cameras", type=int, default=Thresholds.min_cameras,
    )
    args = parser.parse_args(argv)

    store = WorldStore(args.root)
    session_id = args.session
    if session_id is None:
        session_ids = store.list_session_ids(args.world)
        if len(session_ids) != 1:
            print(
                f"world {args.world} has {len(session_ids)} sessions; "
                "name one with --session",
                file=sys.stderr,
            )
            return 2
        session_id = session_ids[0]

    thresholds = Thresholds(
        min_cameras=args.min_cameras,
        max_reciprocity_error=args.max_reciprocity_error,
        max_scale_ambiguity=args.max_scale_ambiguity,
    )
    try:
        report = register(store, args.world, session_id, thresholds)
    except SupportMissingError as error:
        print(str(error), file=sys.stderr)
        return 1

    if args.write:
        # The RAW report, not report_to_json(): that rounds for
        # display, and a transform that will be applied must not be
        # rounded. Five decimal places puts a quaternion 1.9e-6 off
        # unit, which is invisible until a validator refuses it.
        manifest = store.read_derived_manifest(args.world) or {}
        placements = placements_from_report(
            report, input_digest=manifest.get("input_digest")
        )
        store.write_placements(args.world, session_id, placements)
        registered = sum(1 for p in placements if p.state == "registered")
        print(
            f"wrote {len(placements)} placements "
            f"({registered} registered) to derived/{session_id}/"
            "placements.json",
            file=sys.stderr,
        )

    if args.format == "json":
        print(json.dumps(report_to_json(report), indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
