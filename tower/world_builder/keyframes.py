"""Which frames become permanent observations, and why.

Capture rate and mapping rate are different things. At the delivered
~3.3 fps most frames carry no new information, and at a future 12 fps
almost none will. The system, not the wearer, decides which ordinary
frames earn the expensive path -- that is what reconciles "the wearer
behaves normally" with "we cannot afford to process everything".

Every threshold below is a documented starting point pending measurement
on real footage, in the same spirit as tower/object_memory/relevance.py's
confidence buckets. None is presented as tuned, and the V0.9.3 acceptance
gate still forbids citing synthetic numbers as validation for the
platform's own camera.

## Why this policy does NOT decide degeneracy

An earlier version gated on the homography residual from
frontend.summarise_motion, on the reasoning that a homography exactly
explains pure rotation, so a near-zero residual means "no baseline, do not
bother". It was removed after measurement, and the measurement is worth
recording because the idea is an attractive one that does not work.

Measured residual / median-displacement across motion types:

    rotation only,  1 deg          0.01110
    rotation only,  4 deg          0.00758
    rotation only, 12 deg          0.00581
    strafe 0.05 m                  0.17785   <- real translation
    strafe 0.30 m                  0.01299   <- real translation
    rotation 2 deg + 0.15 m        0.00812   <- real translation
    rotation 4 deg + 0.25 m        0.00500   <- real translation, LOWEST

The pure-rotation and genuinely-translating distributions OVERLAP, so no
threshold separates them. The reason is the same one that makes ORB-SLAM's
r_H saturate in a room: when a head both turns and moves, the rotation
dominates the pixel motion and a homography absorbs it, leaving a residual
that reflects only the comparatively small translation-induced parallax.
Realistic wearable motion is rotation-dominant -- which is exactly what
V0.9.3 measured when it found 53.69% of consecutive pairs degenerate.

So the responsibilities split:

- this policy answers "is this frame usable, and has enough happened?"
  from cheap, reliable, intrinsics-free signals -- sharpness, track
  survival, overlap, displacement;
- the geometry backend answers "does this pair carry triangulatable
  geometry?" using median triangulation angle, which needs intrinsics and
  separates cleanly (0.11-0.42 deg degenerate vs 0.54+ usable).

When intrinsics are unknown the second question is simply unanswerable,
which is precisely why the uncalibrated backend returns no poses rather
than guessing. The residual is still measured and persisted per keyframe,
because it is a real observation and costs nothing -- it is just not a gate.
"""

from dataclasses import dataclass

from tower.world_builder.frontend import FrameQuality, MotionSummary

# Decision outcomes.
ACCEPT = "accept"
SKIP = "skip"
REJECT = "reject"
TRACKING_LOST = "tracking_lost"

# Reasons. Every decision carries one, and they are counted into the
# session record -- a rejection histogram is the only tuning instrument
# available before real footage exists.
REASON_SESSION_SEED = "session_seed"
REASON_SEGMENT_SEED = "segment_seed"
REASON_PARALLAX = "parallax"
REASON_OVERLAP_FLOOR = "overlap_floor"
REASON_BLURRED = "blurred"
REASON_TRACKING_DEGRADED = "tracking_degraded"
REASON_TRACKING_LOST = "tracking_lost"
REASON_INSUFFICIENT_MOTION = "insufficient_motion"
REASON_RATE_LIMITED = "rate_limited"
REASON_NO_MOTION_EVIDENCE = "no_motion_evidence"


@dataclass(frozen=True)
class KeyframePolicy:
    """Thresholds for keyframe selection.

    Frozen so a policy is a value that can be recorded alongside the
    results it produced -- a sweep that cannot say which policy produced
    which numbers is not a sweep.
    """

    # Absolute blur floor. Measured: 662 sharp, 38 at a 5-px blur kernel.
    # Set well below the sharp value because absolute variance-of-Laplacian
    # is strongly scene-dependent; the ratio test below does the real work.
    min_sharpness: float = 25.0
    # Reject a frame markedly blurrier than its recent neighbours, which
    # catches motion blur during a head turn even in a scene whose
    # absolute sharpness is low throughout.
    min_sharpness_ratio: float = 0.55
    sharpness_window: int = 30

    # Track survival. Below `min` the measurements are untrustworthy;
    # below `loss` the reference frame is simply gone.
    min_survival_ratio: float = 0.35
    loss_survival_ratio: float = 0.15

    # Losing correspondence is worse than a low-parallax keyframe, so a
    # collapsing overlap forces acceptance rather than waiting for more
    # parallax that will never arrive.
    min_overlap_ratio: float = 0.45

    # Motion, in fractions of the image diagonal, so the policy transfers
    # across resolutions.
    target_displacement_frac: float = 0.035
    min_displacement_frac: float = 0.010

    # NOTE: there is deliberately no rotation/degeneracy gate here.
    # A homography-residual gate was implemented and then REMOVED on
    # measurement -- see the module docstring. The authoritative
    # degeneracy decision belongs to the geometry backend, which has
    # intrinsics and can measure triangulation angle.

    # Rate limiter only -- never an accept trigger. See below.
    min_frame_gap: int = 1
    # Stall detector. Crossing it reports that mapping has stalled; it
    # does NOT promote a frame.
    max_frame_gap: int = 90


@dataclass(frozen=True)
class KeyframeDecision:
    outcome: str
    reason: str

    @property
    def accepted(self) -> bool:
        return self.outcome == ACCEPT

    @property
    def lost(self) -> bool:
        return self.outcome == TRACKING_LOST


class KeyframeSelector:
    """Stateful selector. Deliberately separate from the store.

    `note_accepted` is called by the caller only after a keyframe has
    actually been persisted. Folding it into `evaluate` would let a failed
    write leave the selector believing it succeeded, so the next frames
    would be measured against a keyframe that does not exist.
    """

    def __init__(self, policy: KeyframePolicy | None = None) -> None:
        self._policy = policy or KeyframePolicy()
        self._recent_sharpness: list[float] = []
        self._frames_since_keyframe = 0
        self._has_keyframe = False

    @property
    def policy(self) -> KeyframePolicy:
        return self._policy

    @property
    def frames_since_keyframe(self) -> int:
        return self._frames_since_keyframe

    def note_frame(self, quality: FrameQuality) -> None:
        self._recent_sharpness.append(quality.sharpness)
        if len(self._recent_sharpness) > self._policy.sharpness_window:
            self._recent_sharpness.pop(0)
        self._frames_since_keyframe += 1

    def note_accepted(self) -> None:
        self._frames_since_keyframe = 0
        self._has_keyframe = True

    def note_lost(self) -> None:
        self._has_keyframe = False
        self._frames_since_keyframe = 0

    @property
    def is_stalled(self) -> bool:
        return (
            self._has_keyframe
            and self._frames_since_keyframe > self._policy.max_frame_gap
        )

    def _is_sharp_enough(self, quality: FrameQuality) -> bool:
        policy = self._policy
        if quality.sharpness < policy.min_sharpness:
            return False
        if len(self._recent_sharpness) >= 5:
            reference = sorted(self._recent_sharpness)[len(self._recent_sharpness) // 2]
            if reference > 0 and quality.sharpness / reference < policy.min_sharpness_ratio:
                return False
        return True

    def evaluate(
        self, quality: FrameQuality, motion: MotionSummary | None
    ) -> KeyframeDecision:
        policy = self._policy

        # Blur is checked before anything else, including the session
        # seed: anchoring a whole session on a smeared frame poisons every
        # measurement taken against it afterwards.
        if not self._is_sharp_enough(quality):
            return KeyframeDecision(REJECT, REASON_BLURRED)

        if motion is None or not self._has_keyframe:
            return KeyframeDecision(ACCEPT, REASON_SESSION_SEED)

        if motion.survival_ratio < policy.loss_survival_ratio:
            return KeyframeDecision(TRACKING_LOST, REASON_TRACKING_LOST)

        if motion.survival_ratio < policy.min_survival_ratio:
            return KeyframeDecision(REJECT, REASON_TRACKING_DEGRADED)

        if not motion.has_motion_evidence:
            return KeyframeDecision(SKIP, REASON_NO_MOTION_EVIDENCE)

        # Rate limiting comes after the reject gates so that a burst of
        # blurred frames is still counted as blurred rather than hidden
        # behind "rate limited".
        if self._frames_since_keyframe < policy.min_frame_gap:
            return KeyframeDecision(SKIP, REASON_RATE_LIMITED)

        # Correspondence is about to be lost. Take the keyframe now even
        # at low parallax -- a usable weak link beats a broken chain.
        if motion.overlap_ratio < policy.min_overlap_ratio:
            return KeyframeDecision(ACCEPT, REASON_OVERLAP_FLOOR)

        diagonal = quality.diagonal_px
        displacement_frac = (motion.median_displacement_px or 0.0) / diagonal

        if displacement_frac < policy.min_displacement_frac:
            return KeyframeDecision(SKIP, REASON_INSUFFICIENT_MOTION)

        if displacement_frac >= policy.target_displacement_frac:
            return KeyframeDecision(ACCEPT, REASON_PARALLAX)

        return KeyframeDecision(SKIP, REASON_INSUFFICIENT_MOTION)
