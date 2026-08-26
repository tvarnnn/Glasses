from dataclasses import dataclass

# Confidence moved to tower/confidence.py when World Builder became a
# second consumer. Re-exported here so this module's public surface is
# unchanged and no caller has to care where it lives.
from tower.confidence import (  # noqa: F401
    LOW_CONFIDENCE_MAX,
    MEDIUM_CONFIDENCE_MAX,
    Confidence,
)


# --- What the privacy tags on a record mean -------------------------------
#
# DERIVED_ONLY is a claim about the record's CONTENT: a class label, a
# score and a box, with no pixels, no crop and no embedding of the frame.
# That much was always true.
#
# It was read as a claim about REACH, and there it was false.
# `session_id` + `frame_seq` is an exact pointer into
# `data/captures/<session_id>/frames/`, where the JPEG this record was
# derived from is still sitting. Object Memory's retention governs THIS
# store and nothing else: purging every observation here leaves the
# imagery untouched, and any record that survives resolves straight back
# to a frame.
#
# The provenance is worth keeping -- it is what makes a record checkable
# against the footage instead of merely believable. So the fix is to stop
# the tag overclaiming rather than to drop the fields: a record that
# carries a frame pointer says FRAME_REFERENCED as well, so a reader can
# see that its privacy footprint is bounded by capture-side retention and
# not by ours.
DERIVED_ONLY = "derived-only"
FRAME_REFERENCED = "frame-referenced"


def privacy_tags_for(
    session_id: str | None, frame_seq: int | None
) -> tuple[str, ...]:
    """The tags a record with this provenance may honestly carry.

    Either half alone is a reach claim worth making: a session id narrows
    the imagery to one capture directory even with no frame number.
    """
    if session_id is None and frame_seq is None:
        return (DERIVED_ONLY,)
    return (DERIVED_ONLY, FRAME_REFERENCED)


@dataclass(frozen=True)
class ObjectObservation:
    """One "this category was visible at this time" record.

    Deliberately NOT a claim that the object is present now, or that it is
    a specific instance ("my keys" vs "keys"). See 07-PLATFORM-CONSTRAINTS.md
    Core Principle 3 and OBJECT-MEMORY.md's Identity vs. Category section.

    observed_at is qualified by time_basis: this slice can only know
    tower-receipt time, never on-glasses capture time (Rule 16 -- these
    must not be conflated). There is no soft-delete flag by design;
    06-PRIVACY-DATA.md requires real deletion.

    spatial_ref and external_refs are reserved-but-unused: they are carried
    so a later cross-module need does not require rewriting already-persisted
    records (see 2026-08-20-canonical-memory-architecture.md).

    THREE FIELDS ABOUT STRENGTH, AND WHICH TO TRUST FOR WHAT.

    detector_score is PROVENANCE: how confident the detector was in the
    frame that FIRST brought this class into view -- the one frame this
    record's observed_at, frame_seq and bounding_box all describe. It is
    what makes the record auditable, and it never moves.

    best_score is EVIDENCE: the strongest score seen while that same
    sighting stayed in view, filled in afterwards by the producer as the
    sighting continues. Also never revised downwards.

    confidence is the INTERPRETATION, and it is the field a consumer
    reads. The claim a record makes is "this category was in view", so it
    is derived from best_score -- the best evidence for that claim --
    and moves with it. A record first seen at 0.601 and then seen at
    0.962 is a HIGH-confidence record about a laptop, with 0.601 still on
    it saying how the sighting started. At the first write the two scores
    are equal, so the initial label is derived from either.

    None of the three is a calibrated probability. They are detector
    output, and an interpretation of detector output.
    """

    object_class: str
    detector_score: float | None
    confidence: Confidence
    observed_at: float
    time_basis: str
    recorded_at: float
    source: str
    module_id: str
    session_id: str | None
    frame_seq: int | None
    bounding_box: tuple[float, float, float, float] | None
    retention_tag: str
    privacy_tags: tuple[str, ...]
    spatial_ref: None
    external_refs: tuple[()]
    # Last, with a default, so every record persisted before this field
    # existed still constructs -- and so a reader of those records gets an
    # honest "not tracked" rather than an invented number.
    best_score: float | None = None

    def to_json_dict(self) -> dict:
        return {
            "object_class": self.object_class,
            "detector_score": self.detector_score,
            "confidence": self.confidence.value,
            "observed_at": self.observed_at,
            "time_basis": self.time_basis,
            "recorded_at": self.recorded_at,
            "source": self.source,
            "module_id": self.module_id,
            "session_id": self.session_id,
            "frame_seq": self.frame_seq,
            "bounding_box": (
                list(self.bounding_box) if self.bounding_box is not None else None
            ),
            "retention_tag": self.retention_tag,
            "privacy_tags": list(self.privacy_tags),
            "spatial_ref": self.spatial_ref,
            "external_refs": list(self.external_refs),
            "best_score": self.best_score,
        }


def object_observation_from_json_dict(data: dict) -> ObjectObservation:
    box = data.get("bounding_box")
    return ObjectObservation(
        object_class=data["object_class"],
        detector_score=data["detector_score"],
        confidence=Confidence(data["confidence"]),
        observed_at=data["observed_at"],
        time_basis=data["time_basis"],
        recorded_at=data["recorded_at"],
        source=data["source"],
        module_id=data["module_id"],
        # Required-key access, not .get(): to_json_dict always writes
        # these keys, so a missing key means a malformed record, not a
        # None value -- matching detector_score above.
        session_id=data["session_id"],
        frame_seq=data["frame_seq"],
        bounding_box=tuple(box) if box is not None else None,
        retention_tag=data["retention_tag"],
        privacy_tags=tuple(data["privacy_tags"]),
        spatial_ref=None,
        external_refs=(),
        # .get(), unlike every required field above, and deliberately:
        # the records already on disk were written before best_score
        # existed. A required key would make _parse_observations treat
        # every one of them as a schema mismatch and skip it, deleting
        # the wearer's memory to add a field.
        best_score=data.get("best_score"),
    )
