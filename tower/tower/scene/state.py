"""The live scene, and the relationships it is willing to assert.

Everything here is **camera-relative and in memory**. There is no live
world pose to anchor to -- World Builder produces poses offline, after a
session, and is not on the live frame path at all -- so "left of" means
left in the wearer's current view and means something else the moment
they turn their head. Every relation says so.

Nothing is persisted. A cartridge answering "what is around me now" has
no reason to write to disk, and doing so would import all of
Environmental Memory's retention and purge surface for no gain.

**The relationships this module REFUSES are as deliberate as the ones it
asserts**, and each refusal names the evidence it would need. A
relationship nobody can support is worse than a missing one, because a
consumer cannot tell the difference between a wrong answer and a right
one.
"""

from dataclasses import dataclass, field

from tower.confidence import Confidence
from tower.scene.records import (
    REL_HIGHER_IN_VIEW,
    REL_LEFT_OF,
    REL_RIGHT_OF,
    Relation,
    Track,
)

# Two boxes whose centres differ by less than this fraction of the frame
# width are not meaningfully left or right of each other. Without it, a
# one-pixel difference would assert a relation with the same confidence
# as one across the whole view.
MIN_HORIZONTAL_SEPARATION_FRACTION = 0.08
MIN_VERTICAL_SEPARATION_FRACTION = 0.08

# Relationships this cartridge will NOT assert, and what each would need.
# Kept as data rather than prose so a query layer can answer "why not"
# with the same words the design used.
REFUSED_RELATIONSHIPS = {
    # MEASURED, on 9,199 real corpus frames, 2026-08-26. This entry used
    # to cite a 6-8% MiDaS flicker figure taken from EPIC-KITCHENS at
    # 128x256 and reason from it that the ordering would invert. The
    # figure was about right -- this camera's own frames give 4.8%
    # per-object frame-to-frame change -- and the inference from it was
    # wrong, because flicker only breaks an ordering when it exceeds the
    # SEPARATION, and both objects' depths move together. Measuring the
    # ordering directly is what settles it, so it was measured.
    # See docs/superpowers/research/2026-08-26-depth-ordering-on-real-frames.md.
    "in_front_of": (
        "needs depth that survives motion, and MiDaS does not. Measured on "
        "9,199 real frames: ordering two detector boxes by MiDaS relative "
        "inverse depth reverses on 3.8% of consecutive-frame transitions "
        "overall (2,700 object pairs), and the rate IS strongly predicted "
        "by depth separation -- 15.7% below 0.02 separation, 0.0% above "
        "0.40 -- so the ordering does carry information. It carries it "
        "only while the scene is still. Binned by inter-frame box motion, "
        "the same pairs at the same separation go from 0.0% flips (n=124) "
        "in the most static frames to 11.5% (n=52) in the top motion "
        "decile, and a separation gate at 0.05 goes from 0.00% (n=507) to "
        "4.85% (n=206). The corpus's median inter-frame box motion is 4.2 "
        "px of a 734.8 px diagonal and its 99th percentile is 56 px, so it "
        "contains no walking at all: the regime this relation would be "
        "used in is not sampled, and the trend across the bins that do "
        "exist points the wrong way. Cost is NOT the obstacle -- depth is "
        "5.73 ms on CUDA and 18.29 ms on CPU against an 83.4 ms frame "
        "interval, affordable on the default device. To settle it: corpus "
        "footage with sustained wearer locomotion, and the same motion-by-"
        "separation table computed on it. Note that none of this is "
        "accuracy -- there is no ground-truth depth on this host, so it "
        "measures self-consistency, and a stably wrong model would score "
        "perfectly."
    ),
    "behind": (
        "the inverse of in_front_of, and blocked by the same measurement: "
        "an ordering that holds in a still scene and degrades to 11.5% "
        "reversals under the little motion this corpus contains."
    ),
    "on": (
        "needs support-surface reasoning and depth. Box containment is not "
        "it: a laptop IN FRONT OF a desk overlaps its box identically to a "
        "laptop ON the desk."
    ),
    "inside": "same as `on` -- 2-D containment cannot distinguish it.",
    "near": (
        "image proximity is not world proximity. Two things at opposite "
        "ends of a room can be adjacent in a frame, and two things a metre "
        "apart can be at opposite edges of one."
    ),
    "nearer_than_same_class": (
        "SHIPPED, THEN WITHDRAWN. Box area within one class looked like "
        "safe evidence for relative distance, and an adversarial review "
        "produced a counterexample: two chairs at the SAME distance, one "
        "face-on (60000 px area) and one edge-on (24000), give a ratio of "
        "2.5 against a 1.5 threshold -- a WRONG relation asserted, not a "
        "weak one. Nothing in a 2-D box separates shape from distance, and "
        "this cartridge's own rule is that a wrong relationship is worse "
        "than a missing one. Depth was expected to settle it, and as of "
        "the 2026-08-26 measurement it does not: MiDaS ordering was tested "
        "on same-class pairs too (laptop/laptop, phone/phone) and fails "
        "under motion for the same reason `in_front_of` does. This entry "
        "is no longer waiting on depth; it is waiting on the same footage "
        "`in_front_of` names."
    ),
}


@dataclass(frozen=True)
class SceneState:
    """What is around the wearer, as of one frame. Never stored.

    `counts` come from CONFIRMED TRACKS, never from detections -- which is
    the single correctness requirement the brief singles out.
    """

    at: float
    frame_width: int
    frame_height: int
    tracks: tuple[Track, ...] = ()
    relations: tuple[Relation, ...] = ()
    counts: dict = field(default_factory=dict)
    frames_observed: int = 0
    detector: str = "unknown"
    score_threshold: float = 0.0
    orientation_enabled: bool = False

    def count(self, label: str) -> int:
        return int(self.counts.get(label, 0))

    def of_class(self, label: str) -> tuple[Track, ...]:
        return tuple(track for track in self.tracks if track.label == label)

    def facing_wearer(self) -> tuple[Track, ...]:
        """People whose orientation evidence points toward the wearer.

        Note the method name, and note what it is not. This is not "people
        looking at you" -- the camera cannot see attention.
        """
        return tuple(
            track
            for track in self.tracks
            if track.label == "person" and track.facing.appears_facing_wearer
        )

    @property
    def frame_known(self) -> bool:
        """Whether anything positional can be said at all."""
        return bool(self.frame_width and self.frame_height)

    def to_json_dict(self) -> dict:
        return {
            "at": self.at,
            "time_basis": "tower-receipt",
            "frame": {
                "width": self.frame_width,
                "height": self.frame_height,
                "known": self.frame_known,
            },
            "frame_of_reference": "camera",
            "frames_observed": self.frames_observed,
            "detector": self.detector,
            "score_threshold": self.score_threshold,
            "orientation_enabled": self.orientation_enabled,
            "counts": dict(self.counts),
            "tracks": [track.to_json_dict() for track in self.tracks],
            "relations": [relation.to_json_dict() for relation in self.relations],
            "refused_relationships": sorted(REFUSED_RELATIONSHIPS),
        }


def describe_position(track: Track, frame_width: int, frame_height: int) -> dict:
    """Where a track sits, in the only frame of reference available.

    Normalised image coordinates plus a horizontal offset from the view
    centre. The offset is **not** an angle in the world: it assumes
    nothing about focal length, and without intrinsics it cannot. It is a
    monotonic, comparable "how far off-centre", and the field name says
    `view` so nobody reads it as a compass heading.

    **Refuses when the frame size is unknown.** Normalising a pixel
    coordinate by zero would report every object at `normalised_x: 0.0`
    and `side: "left"` -- a specific, confident claim about where things
    are, derived from no information at all.
    """
    if not frame_width or not frame_height:
        return {
            "normalised_x": None,
            "normalised_y": None,
            "view_offset": None,
            "side": "unknown",
            "frame_of_reference": "camera",
            "note": (
                "frame dimensions unknown, so no position can be computed. "
                "Reporting one would be a claim with no evidence behind it"
            ),
        }

    centre_x, centre_y = track.box.centre
    normalised_x = centre_x / frame_width if frame_width else 0.0
    normalised_y = centre_y / frame_height if frame_height else 0.0
    return {
        "normalised_x": round(normalised_x, 4),
        "normalised_y": round(normalised_y, 4),
        "view_offset": round((normalised_x - 0.5) * 2.0, 4),
        "side": (
            "left"
            if normalised_x < 0.45
            else "right"
            if normalised_x > 0.55
            else "centre"
        ),
        "frame_of_reference": "camera",
        "note": (
            "camera-relative; there is no live world pose to anchor to, so "
            "this changes when the wearer turns"
        ),
    }


def relate(tracks, frame_width: int, frame_height: int) -> list[Relation]:
    """Every relationship the evidence supports, and none that it does not.

    Asserted pairwise over CONFIRMED tracks only. An unconfirmed track is
    a flicker, and relating flickers produces relations that appear and
    vanish while the room is still.
    """
    if not frame_width or not frame_height:
        # Without a frame size the minimum-separation guards collapse to
        # zero, and every pair differing by a single pixel would get a
        # confident left/right relation. No frame, no relations.
        return []

    relations: list[Relation] = []
    ordered = sorted(tracks, key=lambda track: track.track_id)
    min_dx = frame_width * MIN_HORIZONTAL_SEPARATION_FRACTION
    min_dy = frame_height * MIN_VERTICAL_SEPARATION_FRACTION

    for index, subject in enumerate(ordered):
        for other in ordered[index + 1 :]:
            subject_x, subject_y = subject.box.centre
            other_x, other_y = other.box.centre

            if abs(subject_x - other_x) >= min_dx:
                if subject_x < other_x:
                    relations.append(
                        Relation(subject.track_id, REL_LEFT_OF, other.track_id)
                    )
                else:
                    relations.append(
                        Relation(subject.track_id, REL_RIGHT_OF, other.track_id)
                    )

            if abs(subject_y - other_y) >= min_dy:
                # Image-space only, and the name says so. "Above" would
                # imply a world relation that a 2-D box cannot support --
                # something further away sits higher in the frame without
                # being higher in the room.
                higher, lower = (
                    (subject, other) if subject_y < other_y else (other, subject)
                )
                relations.append(
                    Relation(
                        higher.track_id,
                        REL_HIGHER_IN_VIEW,
                        lower.track_id,
                        confidence=Confidence.LOW,
                    )
                )

    return relations
