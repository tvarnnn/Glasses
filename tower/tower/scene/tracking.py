"""Following things across frames, so a count means something.

This is the module the brief singles out: *person counting must use
tracking rather than naively summing detections*. Two failure modes make
that non-negotiable, and they pull in opposite directions:

- a detector that misses a person on one frame in five reports a count
  flickering between 2 and 3 while nothing in the room changed;
- a detector that fires twice on one person reports two people.

A tracker with a hit streak fixes the first; association fixes the
second. Neither is fixed by a better detector alone.

**Association is by IoU only.** Not by appearance. Matching by how
something looks is the first step toward recognising it again, and this
cartridge must never do that -- `track_id` means "the same blob one frame
later" and nothing more.

**Matching maximises how many tracks get a detection, not how good the
single best pair is.** Greedy shipped first and an adversarial review
broke it in one frame: given IoU(T1,D1)=1.00, IoU(T1,D2)=0.33,
IoU(T2,D1)=0.25, IoU(T2,D2)=0.00, a complete matching exists
(T1<-D2, T2<-D1) and greedy takes T1<-D1 instead, stealing T2's only
qualifying detection. T2 then starves across frames and is dropped while
a phantom track confirms in its place -- with the total count sometimes
still reading correct, which is worse, not better.
"""

from dataclasses import dataclass

from tower.scene.records import BoundingBox, Detection, FacingEstimate, Track


@dataclass(frozen=True)
class TrackerPolicy:
    """Every threshold, with its reason.

    A value object rather than constants because the benchmark sweeps
    them, and a threshold that cannot be swept cannot be chosen from data.
    """

    # Below this two boxes are not the same thing one frame later. This
    # was chosen against an assumed ~3.3 fps; the corpus's own journals
    # measure the delivered rate at 12.0 fps (83.5 ms between frames), so
    # a walking person moves LESS between frames than this was tuned for.
    # Left permissive rather than retuned: a threshold that is too
    # forgiving costs an occasional wrong association, and retuning it is
    # a sweep against real footage, not an edit against a corrected
    # number. Recorded here so the next sweep starts from the truth.
    min_iou: float = 0.25
    # How many CONSECUTIVE frames a track must be seen before it counts.
    # One detection is a flicker; so is one every six frames, which is why
    # this is a streak and not a lifetime total.
    min_hits: int = 3
    # How many consecutive misses before a track is dropped. This was
    # justified as "roughly 1.5 seconds of absence" at an assumed 3.3
    # fps; at the measured 12.0 fps it is 0.42 s, which is short enough
    # that a person walking behind a doorframe can be dropped and
    # recounted as new. Same caveat as `min_iou`: the number is now
    # honest about what it buys, and changing it is a sweep, not an edit.
    max_misses: int = 5


class Tracker:
    """Anonymous multi-object tracking. No appearance, no identity.

    Per class, by IoU, with a maximum-cardinality assignment. Greedy was
    the first design and the measurement that killed it is in this
    module's docstring -- "complexity earns its place" cuts both ways, and
    this one earned it in a single constructed frame.

    Still no motion model. **Identity through a symmetric crossing is not
    preserved**, and cannot be: when two people meet and their boxes
    coincide, nothing in a box tells you which one continued which way.
    A Kalman filter would help there and is not justified yet -- and for
    this cartridge, losing identity through a crossing is a small cost,
    because it must never have identity in the first place.
    """

    def __init__(self, policy: TrackerPolicy | None = None) -> None:
        self._policy = policy or TrackerPolicy()
        self._tracks: list[Track] = []
        self._next_id = 1

    @property
    def policy(self) -> TrackerPolicy:
        return self._policy

    @property
    def tracks(self) -> list[Track]:
        """Every live track, confirmed or not."""
        return list(self._tracks)

    def confirmed(self) -> list[Track]:
        """The tracks a count may be taken from."""
        return [
            track
            for track in self._tracks
            if track.confirmed(self._policy.min_hits)
        ]

    def reset(self) -> None:
        self._tracks = []
        self._next_id = 1

    def update(self, detections: list[Detection], *, at: float) -> list[Track]:
        """Associate this frame's detections and return the live tracks.

        Association is **within a class**: a chair box overlapping a
        person box is not evidence that the chair became a person, and
        cross-class association would let one label flip rewrite a
        track's identity.
        """
        assignment = self._match(detections)

        matched_detections: set[int] = set()
        for track_index, detection_index in assignment.items():
            track = self._tracks[track_index]
            detection = detections[detection_index]
            matched_detections.add(detection_index)
            reacquired = track.misses > 0
            track.box = detection.box
            track.score = detection.score
            track.last_seen_at = at
            track.hits += 1
            track.streak += 1
            track.misses = 0
            if track.streak >= self._policy.min_hits:
                track.is_confirmed = True
            if reacquired:
                # Re-matched after a gap. Whatever was behind that gap --
                # an occlusion, or a DIFFERENT PERSON stepping into the
                # same spot -- this box is no longer evidence for the
                # orientation measured before it. Carrying it forward
                # reported one person's facing as another's.
                track.facing = FacingEstimate()
                track.facing_estimated_at = None

        for index, track in enumerate(self._tracks):
            if index not in assignment:
                track.misses += 1
                # A streak is consecutive by definition. Confirmation
                # already latched stays latched; earning it starts over.
                track.streak = 0

        for index, detection in enumerate(detections):
            if index in matched_detections:
                continue
            self._tracks.append(
                Track(
                    track_id=self._next_id,
                    label=detection.label,
                    box=detection.box,
                    score=detection.score,
                    first_seen_at=at,
                    last_seen_at=at,
                    is_confirmed=self._policy.min_hits <= 1,
                )
            )
            self._next_id += 1

        self._tracks = [
            track
            for track in self._tracks
            if track.misses <= self._policy.max_misses
        ]
        return self.tracks

    def _match(self, detections: list[Detection]) -> dict:
        """Maximum-cardinality matching of tracks to detections.

        Augmenting paths (Kuhn's algorithm), with each track's candidates
        ordered by descending IoU. Cardinality first, because the failure
        that matters is a track STARVING while a good-enough detection for
        it sits unclaimed; IoU order then decides among matchings of equal
        size and makes the result deterministic.

        Small by construction -- a handful of tracks and detections per
        frame -- so an exact method costs nothing. Deliberately no scipy:
        `linear_sum_assignment` would do this in one line, but scipy
        arrived here as an OCR dependency and this cartridge must not
        acquire it by accident.
        """
        candidates: dict[int, list[int]] = {}
        for track_index, track in enumerate(self._tracks):
            scored = []
            for detection_index, detection in enumerate(detections):
                if detection.label != track.label:
                    continue
                score = track.box.iou(detection.box)
                if score >= self._policy.min_iou:
                    scored.append((score, detection_index))
            scored.sort(key=lambda entry: (-entry[0], entry[1]))
            candidates[track_index] = [index for _, index in scored]

        detection_to_track: dict[int, int] = {}

        def augment(track_index: int, seen: set) -> bool:
            for detection_index in candidates[track_index]:
                if detection_index in seen:
                    continue
                seen.add(detection_index)
                holder = detection_to_track.get(detection_index)
                if holder is None or augment(holder, seen):
                    detection_to_track[detection_index] = track_index
                    return True
            return False

        # Tracks with the fewest options first: a track with one candidate
        # must take it, and letting a track with several choose first is
        # how the starving case arises.
        order = sorted(
            candidates, key=lambda index: (len(candidates[index]), index)
        )
        for track_index in order:
            augment(track_index, set())

        return {
            track_index: detection_index
            for detection_index, track_index in detection_to_track.items()
        }

    def count(self, label: str) -> int:
        """How many CONFIRMED tracks carry this label.

        The one number the brief insists must not come from detections.
        """
        return sum(1 for track in self.confirmed() if track.label == label)


def detections_from_boxes(label: str, boxes, score: float = 0.9):
    """Convenience for tests and fixtures: boxes are (x0, y0, x1, y1)."""
    return [
        Detection(label=label, score=score, box=BoundingBox(*box)) for box in boxes
    ]
