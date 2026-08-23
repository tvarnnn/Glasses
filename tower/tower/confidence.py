"""The platform's confidence vocabulary.

Promoted out of tower/object_memory/records.py once a second module needed
it. The alternative -- two independently-evolving four-label vocabularies
-- is exactly the silent divergence Rule 16 exists to prevent.

Promoting a frozen enum is a VOCABULARY promotion, not a data-service
promotion, so Rule 6 ("modules own their data") is untouched: no module's
records move, only the shared meaning of a label.

The version constant below is load-bearing. The bucket boundaries are
declared placeholders pending measurement, so they WILL change. When they
do, previously-persisted records keep their old labels while new records
get new ones, and a store that cannot tell the two apart silently mixes
vocabularies. Recording the version on persisted records makes a threshold
change a visible schema event instead of an invisible one.
"""

from enum import Enum

# Bump whenever a label is added, removed, renamed, or a boundary moves.
# Records persisted under an older vocabulary are still readable; they are
# just no longer directly comparable to newer ones.
CONFIDENCE_VOCABULARY_VERSION = 1

# Deliberate placeholders pending measurement, not tuned values. They exist
# so confidence is carried end-to-end from day one (Rule 16) rather than
# retrofitted.
LOW_CONFIDENCE_MAX = 0.5
MEDIUM_CONFIDENCE_MAX = 0.8


class Confidence(Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def from_score(cls, score: float | None) -> "Confidence":
        if score is None:
            return cls.UNKNOWN
        if score < LOW_CONFIDENCE_MAX:
            return cls.LOW
        if score < MEDIUM_CONFIDENCE_MAX:
            return cls.MEDIUM
        return cls.HIGH
