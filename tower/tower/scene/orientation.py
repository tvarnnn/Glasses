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

**The cost, measured on real frames, and why the device is the whole
story.** Warm medians over 754 corpus frames at 360x640, decode excluded,
`torch.cuda.synchronize()` bracketing every CUDA call
(`docs/superpowers/research/2026-08-26-scene-understanding-measurements.md`):

                              CUDA        CPU
    ssdlite320 detection     30.4 ms    32.9 ms
    keypointrcnn_resnet50    43.4 ms   956.4 ms      <- 22.0x
    keypointrcnn p95         50.6 ms  1112.8 ms

    delivered frame interval 83.5 ms (12.0 fps, from the corpus journals)
    orientation / interval      0.52x     11.5x

**Every figure this module used to quote was wrong**, and wrong in a way
that mattered: 744 ms (here and in five other files), 798 ms (in the
module doc), "23x the detector", "2.5x the ~300 ms interval". They were
CPU numbers from synthetic input, none of them named a device, and the
real interval is 83.5 ms rather than 300 ms. On CUDA the detector is
launch-bound and gains almost nothing from the GPU, so orientation is
**1.43x** the detector, not 24x; on CPU it is 29.1x. The ratio inverts
entirely depending on where it runs, which is why the device is now
stated everywhere the cost is.

Cost is flat in the number of people -- ~1 ms each, 40.0 ms at zero to
44.3 ms at four -- because the ResNet-50 + FPN backbone runs once
regardless. A crowded room does not change the budget.

**So it still runs at a cadence**, now ~250 ms rather than 2.0 s (see
`engine.ORIENTATION_INTERVAL_S` for the arithmetic), and **every estimate
still carries its age**. The age is not cadence bookkeeping that CUDA
made redundant: `TorchvisionPoseEstimator` defaults to `device="cpu"`,
where a call is 11.5x the frame interval and every word of the original
argument still holds, and `age_estimate`'s clamp guards a clock bug that
has nothing to do with speed at all.

**The old unblocker is spent.** This module used to say torch was
CPU-only on this host and that a restored CUDA build was what would
change the decision. That build exists -- `torch 2.13.0+cu132`, verified
executing on an RTX 5070 (Blackwell, sm_120), 988 MB reserved of 12 GB --
and the numbers above are from it. The question is measured and closed.

**What is still NOT measured is accuracy.** There is no bystander footage
on this host; the corpus's person boxes are almost certainly the wearer's
own torso (median 21.5% of frame, bottom edge 0.939, 43% frame-clipped).
`facing_from_keypoints` remains entirely unvalidated against ground
truth. Nothing above is evidence that orientation *works* -- only that it
costs 43 ms.
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
# described by a ten-second-old estimate. Unchanged by the CUDA
# measurement: expiry is about how fast a PERSON turns, not how fast the
# model runs, and 6.0 s is ~24 cadence windows either way.
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

    That clamp is a CLOCK guard, not a latency guard. It is the reason
    this function survives independently of how fast the pose model is:
    a GPU that made orientation free would not make a backward NTP step
    any less able to defer an expiry forever.
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
    """`keypointrcnn_resnet50_fpn`, and its cost is the device.

    43.4 ms warm median on CUDA, 956.4 ms on CPU, over real corpus
    frames. **The default is `cpu`**, so the default is the expensive
    one -- deliberately, because a caller that wants the GPU should have
    to say so rather than discover it is holding one.

    The first call costs 623.5 ms on CUDA, 14x the warm median, while
    kernels compile and autotune. Anything that times a single call to
    decide whether orientation is affordable will be wrong by an order
    of magnitude, in the same direction this module's documentation was
    wrong for months.
    """

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
