"""Which way is that person facing -- and never, which way are they looking.

`07-PLATFORM-CONSTRAINTS.md` Limitation 8: the camera cannot establish
that anyone looked at, noticed or read anything, and there is no eye
tracking on this hardware. What it CAN see is coarse orientation, and the
two are not the same. A person squarely facing the wearer may be reading
something over their shoulder.

So the state is `toward_wearer`, the property is
`appears_facing_wearer`, and there is deliberately no value meaning
"looking at you".

**The evidence.** COCO keypoints include `left_eye`, `right_eye`,
`left_ear`, `right_ear`, and their VISIBILITY pattern is genuine
orientation evidence:

    both ears + both eyes visible   -> facing toward the camera
    both ears, neither eye          -> facing away
    one ear                         -> profile
    nothing                         -> unknown, and say so

**The cost, measured, and why this is off by default.**

    ssdlite320 detection      32 ms
    keypointrcnn_resnet50    744 ms      <- 23x, on this CPU

744 ms is 2.5x the ~300 ms interval the glasses deliver. It cannot run
per frame; a "current" scene state computed that way would be two frames
stale before it existed. So this runs at a bounded cadence on person
tracks only, and **every estimate carries its age** so a consumer can see
how old the answer is. A person's facing does not change every 300 ms,
which is what makes a one-second-old estimate useful rather than a lie.

The unblocker is named rather than vague: torch is CPU-only on this host.
A restored CUDA build is what would change this decision -- not a
cleverer algorithm.
"""

import logging
from typing import Protocol, runtime_checkable

from tower.confidence import Confidence
from tower.scene.records import (
    FACING_AWAY,
    FACING_PROFILE,
    FACING_TOWARD,
    FACING_UNKNOWN,
    FacingEstimate,
)

logger = logging.getLogger(__name__)

# torchvision's COCO keypoint order.
KEYPOINT_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

# A keypoint below this score is not visible. Keypoint models emit a
# coordinate for every joint whether or not they can see it, so without a
# threshold "visible" would mean "predicted", which is not the same thing
# at all and would make every person appear to be facing the camera.
MIN_KEYPOINT_SCORE = 3.0

# How stale an estimate may be before it is reported as unknown rather
# than as an answer. Generous, because orientation is slow-moving -- but
# finite, because a person who turned around ten seconds ago is not
# described by a ten-second-old estimate.
MAX_ESTIMATE_AGE_S = 6.0


def facing_from_keypoints(scores_by_name: dict) -> FacingEstimate:
    """Coarse facing from which facial keypoints are visible.

    Confidence is deliberately never HIGH. This is a visibility heuristic
    over an inference, two layers away from a measurement, and the brief
    is explicit that "looking at me" must not be claimed from weak
    evidence. MEDIUM is the ceiling.
    """
    eyes = sum(
        1
        for name in ("left_eye", "right_eye")
        if scores_by_name.get(name, 0.0) >= MIN_KEYPOINT_SCORE
    )
    ears = sum(
        1
        for name in ("left_ear", "right_ear")
        if scores_by_name.get(name, 0.0) >= MIN_KEYPOINT_SCORE
    )
    nose_visible = scores_by_name.get("nose", 0.0) >= MIN_KEYPOINT_SCORE

    if eyes == 0 and ears == 0:
        return FacingEstimate(state=FACING_UNKNOWN, confidence=Confidence.UNKNOWN)

    if eyes == 2 and ears >= 1:
        # Both eyes AND an ear: the front of the head is toward us.
        return FacingEstimate(
            state=FACING_TOWARD,
            confidence=Confidence.MEDIUM,
            visible_eyes=eyes,
            visible_ears=ears,
        )
    if eyes == 0 and ears == 2:
        # Both ears, neither eye, no nose: the back of the head.
        return FacingEstimate(
            state=FACING_AWAY,
            confidence=Confidence.MEDIUM if not nose_visible else Confidence.LOW,
            visible_eyes=eyes,
            visible_ears=ears,
        )
    if ears == 1:
        return FacingEstimate(
            state=FACING_PROFILE,
            confidence=Confidence.LOW,
            visible_eyes=eyes,
            visible_ears=ears,
        )
    # One eye and two ears, or two eyes and no ear: real but ambiguous.
    # LOW rather than a coin flip between toward and away.
    return FacingEstimate(
        state=FACING_PROFILE if eyes <= 1 else FACING_TOWARD,
        confidence=Confidence.LOW,
        visible_eyes=eyes,
        visible_ears=ears,
    )


def age_estimate(estimate: FacingEstimate, seconds: float) -> FacingEstimate:
    """Advance an estimate's age, expiring it once it is too old.

    An expired estimate becomes UNKNOWN rather than being deleted, so the
    consumer sees "we do not know" instead of a missing field it might
    read as "not facing".

    Clamped at zero, matching `Track.age_seconds`. Timestamps come from
    the capture journal and are wall clock: a backward NTP step produced a
    NEGATIVE age, which quietly pushed the expiry deadline further into
    the future -- the one direction it must never move.
    """
    from dataclasses import replace

    seconds = max(seconds, 0.0)
    if seconds > MAX_ESTIMATE_AGE_S:
        return FacingEstimate(
            state=FACING_UNKNOWN,
            confidence=Confidence.UNKNOWN,
            age_seconds=seconds,
        )
    return replace(estimate, age_seconds=seconds)


@runtime_checkable
class PoseEstimator(Protocol):
    """Anything that can produce per-person keypoint scores for a frame."""

    name: str

    def load(self) -> None: ...

    def estimate(self, frame_bgr) -> list[tuple]: ...

    def release(self) -> None: ...


class FixedPoseEstimator:
    """Returns keypoint scores the caller chose. For tests.

    Each entry is `(BoundingBox, {keypoint_name: score})`, which is the
    same shape the real estimator produces -- so a test asserts against
    visibility patterns it wrote down rather than against a model's
    opinion.
    """

    name = "fixed"

    def __init__(self, frames=None) -> None:
        self._frames = list(frames or [])
        self.calls = 0

    def load(self) -> None:
        return None

    def estimate(self, frame_bgr) -> list[tuple]:
        self.calls += 1
        if not self._frames:
            return []
        return list(self._frames[min(self.calls - 1, len(self._frames) - 1)])

    def release(self) -> None:
        return None


class TorchvisionPoseEstimator:
    """`keypointrcnn_resnet50_fpn`. 744 ms per frame on this CPU."""

    name = "keypointrcnn"

    def __init__(self, min_person_score: float = 0.7, device: str = "cpu") -> None:
        self._min_person_score = min_person_score
        self._device = device
        self._model = None
        self._transform = None

    def load(self) -> None:
        import torch
        from torchvision.models.detection import keypointrcnn_resnet50_fpn
        from torchvision.models.detection.keypoint_rcnn import (
            KeypointRCNN_ResNet50_FPN_Weights,
        )

        weights = KeypointRCNN_ResNet50_FPN_Weights.COCO_V1
        model = keypointrcnn_resnet50_fpn(weights=weights)
        model.eval()
        self._torch_device = torch.device(self._device)
        model.to(self._torch_device)
        self._model = model
        self._transform = weights.transforms()

    def estimate(self, frame_bgr) -> list[tuple]:
        import numpy as np
        import torch

        from tower.scene.records import BoundingBox

        if self._model is None:
            self.load()

        rgb = frame_bgr[:, :, ::-1]
        tensor = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1)
        batch = [self._transform(tensor).to(self._torch_device)]
        with torch.inference_mode():
            prediction = self._model(batch)[0]

        boxes = prediction["boxes"].detach().cpu().numpy()
        scores = prediction["scores"].detach().cpu().numpy()
        keypoint_scores = prediction["keypoints_scores"].detach().cpu().numpy()

        people = []
        for box, score, per_keypoint in zip(boxes, scores, keypoint_scores):
            if score < self._min_person_score:
                continue
            named = {
                name: float(value)
                for name, value in zip(KEYPOINT_NAMES, per_keypoint)
            }
            people.append(
                (BoundingBox(*(float(value) for value in box)), named)
            )
        return people

    def release(self) -> None:
        was_cuda = self._device.startswith("cuda")
        self._model = None
        self._transform = None
        if was_cuda:
            import torch

            torch.cuda.empty_cache()
