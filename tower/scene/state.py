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
    "in_front_of": (
        "needs depth. The only depth available is MiDaS relative inverse "
        "depth, measured by this project at 6-8% temporal flicker; ordering "
        "two boxes by a flickering field gives a relation that inverts "
        "frame to frame. To settle it: run the depth experiment over a "
        "scene with two objects at a known separation and measure how "
        "often the ordering flips."
    ),
    "behind": "the inverse of in_front_of, and blocked by the same missing depth.",
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
        "than a missing one. Depth would settle it, and depth is what the "
        "entries above are already waiting for."
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
