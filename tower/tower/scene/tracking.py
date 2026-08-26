"""Following things across frames, so a count means something.

This is the module the brief singles out: *person counting must use
tracking rather than naively summing detections*. Two failure modes make
that non-negotiable, and they pull in opposite directions:

- a detector that misses a person on one frame in five reports a count
  flickering between 2 and 3 while nothing in the room changed;
- a detector that fires twice on one person reports two people.

A tracker with a hit streak fixes the first; association fixes the
second. Neither is fixed by a better detector alone.

There is a third, and it is quieter than both: a confirmed track dropped
while its person is behind a doorframe comes back as a NEW `track_id`
and is counted as somebody new. The count reads plausibly on every frame
either side of the occlusion and is wrong about who was in the room.
That one is bought or avoided entirely by `max_misses` -- which is why
the thresholds below are each derived from a measurement on the real
corpus rather than chosen, in
`docs/superpowers/research/2026-08-26-tracker-retune.md`.

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

# The interval at which frames actually arrive, in seconds. Measured from
# the corpus's own `frames.jsonl` receipt timestamps: a median gap of
# 83.5 ms across 9,145 frames in the 14 captures with more than 50 of
# them, i.e. 12.0 fps, with per-capture medians of 68.5-87.6 ms.
#
# It lives HERE, at the tracker, rather than in the engine that also
# needs it, because one of the thresholds below is derived from it and
# the engine imports this module. A constant a threshold depends on must
# sit no higher than the threshold.
DELIVERED_FRAME_INTERVAL_S = 0.0835


def frames_in(seconds: float) -> int:
    """How many delivered frames fit in a duration.

    The whole defect this module carried was a duration written as a
    frame count: `max_misses = 5` was justified as "roughly 1.5 seconds"
    against an assumed ~3.3 fps, and when the real rate turned out to be
    12.0 fps the number silently became 0.42 s while its comment went on
    claiming 1.5. A duration that is converted rather than counted
    cannot drift like that again.
    """
    return max(1, round(seconds / DELIVERED_FRAME_INTERVAL_S))


# How long a thing may be absent and still be the same thing when it
# comes back. A wall-clock duration, because an occlusion is one: a
# person passing behind a doorframe at walking pace is hidden for about
# half a second, behind another person for a little less, and through a
# head turn away and back for about one.
#
# Where the line is, and why here. Measured on 9,145 corpus frames
# (`docs/superpowers/research/2026-08-26-tracker-retune.md`), the
# run-lengths of real detection gaps are heavy-tailed with no knee --
# 30% last one frame, 58% are within the old budget of 5, 71% within 12,
# 76% within 18, and the tail runs to 1,778. So no percentile picks this
# number; the trade has to be named instead:
#
#   - too short and an occluded person is dropped, returns with a new
#     `track_id` and is COUNTED AS SOMEBODY NEW. Over the corpus,
#     raising the budget from 5 frames to 12 cuts the `person` ids
#     created from 134 to 104, and lifts count stability under 40%
#     detector dropout from 0.939 to 0.965 (0.252 to 0.783 at 60%).
#   - too long and a track whose object has genuinely gone stays
#     confirmed, and the cartridge makes a false claim about who is in
#     the room -- exactly what `06-PRIVACY-DATA.md` calls collecting
#     more than the feature requires, in the shape of asserting more
#     than the evidence supports.
#
# 1.0 s is where those meet. Past it the benefit is invisible: count
# stability at 18 and 24 frames is identical to 12, so the extra
# staleness buys nothing any measurement here can see, and the gaps it
# would newly bridge are increasingly ones where "recovered" means a
# DIFFERENT object arrived in the same place. Under it, at the shipped
# 0.42 s, half a second of occlusion is already a recount.
MAX_ABSENCE_S = 1.0


@dataclass(frozen=True)
class TrackerPolicy:
    """Every threshold, with its reason.

    A value object rather than constants because the benchmark sweeps
    them, and a threshold that cannot be swept cannot be chosen from data.

    Two of these are frame counts and one is a duration, and knowing
    which is which is what the 3.6x frame-rate error turned on.
    `min_hits` and `min_iou` describe what happens BETWEEN two frames --
    detector noise and object motion -- so they are per-frame quantities
    and the rate error left them alone. `max_misses` describes a
    duration in the room, so it must be derived from the rate, and it
    was the one that broke.
    """

    # Below this two boxes are not the same thing one frame later.
    #
    # Derived from the corpus: the 1st percentile of IoU between the same
    # object's boxes in consecutive frames is 0.525 for `person`, 0.613
    # for `laptop` and 0.386 for `cell phone` (medians 0.96, 0.96, 0.91 --
    # at 12 fps a box barely moves). 0.25 is the largest floor that keeps
    # at least 99.5% of every measured label's true associations, and the
    # last point before track fragmentation starts to climb: sweeping the
    # floor up from 0.25 to 0.40 creates 6% more confirmed ids for
    # nothing, and 0.50 creates 19% more.
    #
    # It cannot be raised on the evidence available. The only measurable
    # upper bound would be how often DIFFERENT objects overlap this much,
    # and the corpus cannot supply it: two boxes of one class in one
    # frame never exceed 0.55 IoU because the detector's own NMS
    # suppresses them first, so that distribution describes NMS, not the
    # room. See the caveat in the research note -- there is no bystander
    # footage on this host.
    min_iou: float = 0.25
    # How many CONSECUTIVE frames a track must be seen before it counts.
    # One detection is a flicker; so is one every six frames, which is why
    # this is a streak and not a lifetime total.
    #
    # A frame count, not a duration, and deliberately not rescaled with
    # the corrected rate: a detector's false positives arrive per frame.
    # Swept both ways on the corpus, and 3 is where both neighbours are
    # worse. At 4 the count stops holding under dropout -- 0.774 correct
    # at 40% against 0.965, because re-confirming needs four consecutive
    # hits from a detector that is losing two frames in five. At 2 the
    # frames on which a track the detector was never confident about
    # (best score under 0.5) is counted double, 386 to 808, undoing the
    # confirmation fix that introduced this constant.
    min_hits: int = 3
    # How many consecutive misses before a track is dropped: 12, which is
    # `MAX_ABSENCE_S` at the measured frame interval and nothing else.
    # Written as the arithmetic rather than the answer, because the
    # answer is what went stale last time.
    max_misses: int = frames_in(MAX_ABSENCE_S)


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
