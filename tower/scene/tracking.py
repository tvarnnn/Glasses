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
"""

from dataclasses import dataclass

from tower.scene.records import BoundingBox, Detection, Track


@dataclass(frozen=True)
class TrackerPolicy:
    """Every threshold, with its reason.

    A value object rather than constants because the benchmark sweeps
    them, and a threshold that cannot be swept cannot be chosen from data.
    """

    # Below this two boxes are not the same thing one frame later. At the
    # ~3.3 fps the glasses deliver, a walking person moves a long way
    # between frames, so this is deliberately permissive.
    min_iou: float = 0.25
    # How many frames a track must be seen before it counts. One
    # detection is a flicker; three is a thing.
    min_hits: int = 3
    # How many consecutive misses before a track is dropped. At 3.3 fps
    # this is roughly 1.5 seconds of absence -- long enough to survive a
    # detector dropout, short enough that someone who left the room stops
    # being counted.
    max_misses: int = 5


class Tracker:
    """Anonymous multi-object tracking. No appearance, no identity.

    Deliberately simple: greedy IoU association, per class. A Kalman
    filter or a Hungarian assignment would both be defensible and neither
    is justified yet -- there is no measurement showing greedy association
    failing, and the brief's rule is that complexity earns its place.
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

        Association is greedy over IoU, highest first, and **within a
        class**: a chair box overlapping a person box is not evidence that
        the chair became a person. Cross-class association would let a
        detector's label flip rewrite a track's identity.
        """
        unmatched_tracks = list(self._tracks)
        unmatched_detections = list(detections)

        pairs = []
        for track in unmatched_tracks:
            for detection in unmatched_detections:
                if detection.label != track.label:
                    continue
                score = track.box.iou(detection.box)
                if score >= self._policy.min_iou:
                    pairs.append((score, track, detection))
        pairs.sort(key=lambda pair: pair[0], reverse=True)

        matched_tracks: set[int] = set()
        matched_detections: set[int] = set()
        for _, track, detection in pairs:
            if id(track) in matched_tracks or id(detection) in matched_detections:
                continue
            matched_tracks.add(id(track))
            matched_detections.add(id(detection))
            track.box = detection.box
            track.score = detection.score
            track.last_seen_at = at
            track.hits += 1
            track.misses = 0

        for track in self._tracks:
            if id(track) not in matched_tracks:
                track.misses += 1

        for detection in detections:
            if id(detection) in matched_detections:
                continue
            self._tracks.append(
                Track(
                    track_id=self._next_id,
                    label=detection.label,
                    box=detection.box,
                    score=detection.score,
                    first_seen_at=at,
                    last_seen_at=at,
                )
            )
            self._next_id += 1

        self._tracks = [
            track
            for track in self._tracks
            if track.misses <= self._policy.max_misses
        ]
        return self.tracks

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
