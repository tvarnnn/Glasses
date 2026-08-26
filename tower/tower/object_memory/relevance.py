from dataclasses import dataclass

# The COCO classes this slice will persist an observation for, and the
# only ones.
#
# Chosen from measurement, not from taste. The first pass over the real
# corpus -- all 9,199 Ray-Ban frames in `data/captures/`, recorded in
# `docs/superpowers/research/2026-08-26-real-corpus-first-measurement.md`
# -- found only two classes with confidence worth remembering:
# `cell phone` at a 0.844 median score and `laptop` at 0.813. Everything
# else the repo had been tracking is near-absent or near-noise:
# `dining table` appears ONCE in 9,199 frames, `chair` four times in a
# 340-frame sample, and `couch` (0.496) and `tv` (0.494) sit barely above
# the detector's 0.4 threshold, with the large-area/low-score signature of
# a flat surface being guessed at rather than recognised. A memory built
# over those would be a memory of the detector's uncertainty.
#
# `person` is EXCLUDED, and the exclusion is the load-bearing part.
#
# Whether Object Memory may persist a record per detected bystander is a
# genuinely open ruling -- 06-PRIVACY-DATA.md's Sensitive Visual
# Information section and OBJECT-MEMORY.md's Privacy section both bear on
# it, and no human has settled it in this repo. The corpus measurement
# REFRAMES that question without answering it: the `person` boxes on this
# footage have a median area of 40% of the frame, a median bottom edge at
# 0.981, are horizontally centred and touch the frame edge 59% of the
# time, which on head-mounted footage is the wearer's own torso and arms
# seen while looking down. So a `person` record here would usually be the
# wearer -- simultaneously less sensitive than feared and far less useful
# than hoped -- while real bystanders will still appear eventually and the
# original ruling will still be needed then.
#
# Leaving `person` out is what lets this slice ship WITHOUT that ruling.
# Adding it back is therefore not a tuning change: it commits the project
# to persisting bystander records, and must not happen until a human has
# decided that it may.
PERSISTED_CLASSES = ("laptop", "cell phone")

# What `decide` returns. Strings rather than an enum because their only
# consumers are a counter and a report line.
RECORD = "record"
NOT_WHITELISTED = "not-whitelisted"
BELOW_MIN_SCORE = "below-min-score"
RESAMPLED = "resampled"


@dataclass(frozen=True)
class RelevancePolicy:
    """Thresholds for turning raw detections into stored observations.

    `min_score` and `resample_seconds` are starting points to be revisited
    against measured retrieval behavior (Task 8), not tuned constants.

    `allowed_classes` is different in kind: it is not a threshold to be
    tuned but a decision about what this system is allowed to remember,
    and it defaults CLOSED. See PERSISTED_CLASSES.
    """

    min_score: float = 0.5
    resample_seconds: float = 30.0
    allowed_classes: tuple[str, ...] = PERSISTED_CLASSES


class RelevanceFilter:
    """Suppresses low-value repeated detections.

    In-memory only and deliberately not persisted: on restart the first
    sighting of each class is recorded again, which is the safe direction
    to err (an extra honest observation, never a suppressed real one).
    """

    def __init__(self, policy: RelevancePolicy) -> None:
        self._policy = policy
        self._allowed = frozenset(policy.allowed_classes)
        # Keyed by object_class, not by instance: this slice tracks
        # category sightings, not individual objects. The key space is
        # bounded in practice by the detector's closed label set (Rule
        # 15 governs the real-time path), not by anything enforced here.
        self._last_recorded_at: dict[str, float] = {}

    def decide(self, object_class: str, score: float, now: float) -> str:
        """Why this detection will or will not be persisted.

        Separate from `should_record` so a producer can report how the
        filter actually behaved on real footage -- how much was dropped
        for being off the whitelist versus too weak versus too soon. A
        bare bool made that unmeasurable, and Task 8 exists to measure it.
        """
        # The class check comes FIRST, before score and before resample.
        # A class this slice may not persist must never reach the
        # resample table, or an excluded class would occupy a slot and
        # the suppression accounting would describe work never done.
        if object_class not in self._allowed:
            return NOT_WHITELISTED
        if score < self._policy.min_score:
            return BELOW_MIN_SCORE
        previous = self._last_recorded_at.get(object_class)
        if previous is not None and (now - previous) < self._policy.resample_seconds:
            return RESAMPLED
        return RECORD

    def should_record(self, object_class: str, score: float, now: float) -> bool:
        return self.decide(object_class, score, now) == RECORD

    def note_recorded(self, object_class: str, now: float) -> None:
        # Deliberately a separate call from should_record, not a single
        # record-and-note operation: it lets the caller skip noting the
        # claim if the store write actually fails, so the next frame
        # retries the observation instead of the filter silently
        # believing it was already recorded.
        self._last_recorded_at[object_class] = now
