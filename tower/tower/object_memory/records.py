from dataclasses import dataclass

# Confidence moved to tower/confidence.py when World Builder became a
# second consumer. Re-exported here so this module's public surface is
# unchanged and no caller has to care where it lives.
from tower.confidence import (  # noqa: F401
    LOW_CONFIDENCE_MAX,
    MEDIUM_CONFIDENCE_MAX,
    Confidence,
)


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
    )
