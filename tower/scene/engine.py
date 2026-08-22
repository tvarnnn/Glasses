"""Frames in, a live scene state out.

    every frame     detect, associate into tracks       ~32 ms
    optional        keypoints on person tracks         ~744 ms

Nothing is persisted and nothing runs on the Tower event loop. Like World
Builder and Document Memory this is an engine plus a driver, in a separate
process -- and the 744 ms orientation stage is the clearest illustration
of why that separation matters.
"""

import logging
import time

from tower.scene.detect import SCORE_THRESHOLD, Detector
from tower.scene.orientation import age_estimate, facing_from_keypoints
from tower.scene.records import FacingEstimate
from tower.scene.state import SceneState, describe_position, relate
from tower.scene.tracking import Tracker, TrackerPolicy

logger = logging.getLogger(__name__)

# How often the expensive orientation stage may run, in seconds. At 744 ms
# a call, anything more frequent than this spends more time estimating
# facing than observing the room. Orientation is slow-moving, so a
# two-second cadence loses little -- and every estimate carries its age so
# the loss is visible rather than assumed away.
ORIENTATION_INTERVAL_S = 2.0


class SceneEngine:
    """Maintains what is around the wearer right now.

    Deliberately has no store. `state()` returns the current answer and
    the previous one is gone -- which is the whole difference between this
    cartridge and Environmental Memory.
    """

    def __init__(
        self,
        detector: Detector,
        tracker_policy: TrackerPolicy | None = None,
        clock=time.time,
        *,
        pose_estimator=None,
        orientation_interval_s: float = ORIENTATION_INTERVAL_S,
        score_threshold: float = SCORE_THRESHOLD,
    ) -> None:
        self._detector = detector
        self._tracker = Tracker(tracker_policy)
        self._clock = clock
        # OFF unless a caller supplies one. 744 ms per frame on this CPU
        # is 2.5x the interval the glasses deliver; a scene state computed
        # that way would be stale before it existed.
        self._pose = pose_estimator
        self._orientation_interval = orientation_interval_s
        self._score_threshold = score_threshold
        self._last_orientation_at: float | None = None
        # Whether orientation has ever produced a real estimate, as
        # opposed to merely being configured. A pose model that raises on
        # every call -- bad weights, an incompatible torch build -- used
        # to leave `orientation_enabled` True and the query layer
        # answering a confident 0, which is the same observation-gap trap
        # the refusal exists to prevent, one layer further down.
        self._orientation_succeeded = False
        self._frames_observed = 0
        self._frame_size = (0, 0)
        self._loaded = False

    @property
    def frames_observed(self) -> int:
        return self._frames_observed

    @property
    def orientation_enabled(self) -> bool:
        """Configured AND has actually produced an estimate.

        "An object was passed to the constructor" is not evidence that
        anyone's orientation was ever measured.
        """
        return self._pose is not None and self._orientation_succeeded

    @property
    def orientation_configured(self) -> bool:
        return self._pose is not None

    def load(self) -> None:
        self._detector.load()
        if self._pose is not None:
            self._pose.load()
        self._loaded = True

    def release(self) -> None:
        self._detector.release()
        if self._pose is not None:
            self._pose.release()
        self._tracker.reset()

    def observe(self, frame_bgr, *, received_at: float | None = None) -> SceneState:
        """One frame in, the current scene out.

        Returns the state rather than storing it. A caller that wants the
        previous state has to have kept it, which is the correct default
        for something whose whole claim is to describe *now*.
        """
        at = self._clock() if received_at is None else received_at
        self._frames_observed += 1
        if frame_bgr is not None and getattr(frame_bgr, "size", 0):
            self._frame_size = (frame_bgr.shape[1], frame_bgr.shape[0])

        detections = self._detect(frame_bgr)
        self._tracker.update(detections, at=at)

        if self._should_estimate_orientation(at):
            self._estimate_orientation(frame_bgr, at)
        self._age_orientation(at)

        confirmed = self._tracker.confirmed()
        width, height = self._frame_size
        counts: dict = {}
        for track in confirmed:
            counts[track.label] = counts.get(track.label, 0) + 1

        return SceneState(
            at=at,
            frame_width=width,
            frame_height=height,
            tracks=tuple(confirmed),
            relations=tuple(relate(confirmed, width, height)),
            counts=counts,
            frames_observed=self._frames_observed,
            detector=self._detector.name,
            score_threshold=self._score_threshold,
            orientation_enabled=self.orientation_enabled,
        )

    def describe(self, state: SceneState) -> dict:
        """The scene as an answer, not as a data structure."""
        payload = state.to_json_dict()
        payload["positions"] = {
            track.track_id: describe_position(
                track, state.frame_width, state.frame_height
            )
            for track in state.tracks
        }
        return payload

    # -- internals -----------------------------------------------------

    def _detect(self, frame_bgr):
        """Detect, or report an empty frame rather than dying.

        A detector can fail for ordinary reasons -- a model OOM, a bad
        frame. Losing the whole session over one of them would be the same
        defect Document Memory's review found in its OCR path, and the
        answer is the same: an empty result is honest, a crash is not.
        """
        try:
            return self._detector.detect(frame_bgr)
        except Exception:
            logger.exception(
                "scene: detection failed on a frame; treating it as empty "
                "and continuing"
            )
            return []

    def _should_estimate_orientation(self, at: float) -> bool:
        if self._pose is None:
            return False
        if self._last_orientation_at is None:
            return True
        return at - self._last_orientation_at >= self._orientation_interval

    def _estimate_orientation(self, frame_bgr, at: float) -> None:
        try:
            people = self._pose.estimate(frame_bgr)
        except Exception:
            logger.exception("scene: pose estimation failed; leaving facing unknown")
            return
        self._last_orientation_at = at

        person_tracks = [
            track for track in self._tracker.tracks if track.label == "person"
        ]
        for box, keypoint_scores in people:
            # Associate the pose to a track by IoU, the same way
            # detections associate. A pose that matches no track is
            # discarded rather than creating one: the detector decides
            # what exists, and two models disagreeing about a person
            # should not produce a phantom.
            best = None
            best_iou = 0.0
            for track in person_tracks:
                score = track.box.iou(box)
                if score > best_iou:
                    best, best_iou = track, score
            if best is None or best_iou < self._tracker.policy.min_iou:
                continue
            estimate = facing_from_keypoints(keypoint_scores)
            best.facing = age_estimate(estimate, 0.0)
            best.facing_estimated_at = at
            self._orientation_succeeded = True

    def _age_orientation(self, at: float) -> None:
        """Age each estimate from when THAT TRACK was last estimated.

        Not from the last orientation RUN. The two diverge precisely when
        staleness matters most: the pose model runs, fails to find this
        person -- because they turned away, or moved behind something --
        and the track keeps its old reading. Ageing from the run time
        would reset that reading's age to nearly zero on every run, so a
        ten-second-old "facing toward you" would report as one second old
        and would never reach the expiry that exists to catch it.
        """
        if self._pose is None:
            return
        for track in self._tracker.tracks:
            if track.label != "person":
                continue
            if track.facing_estimated_at is None:
                # Never estimated -- a track that appeared since the last
                # run. Unknown, which is the honest answer, and not the
                # previous occupant's reading.
                track.facing = FacingEstimate()
                continue
            track.facing = age_estimate(
                track.facing, at - track.facing_estimated_at
            )
