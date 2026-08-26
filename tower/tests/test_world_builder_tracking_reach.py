"""How far the tracker can reach between one reference and the next.

Segment breaks were assumed to come from imagery the tracker could not
follow. Replaying all 1,848 frames of the 2026-08-25 walk through the real
`FrameTracker` says otherwise: on the 50 frames where loss was declared, 47
still had frame-to-frame survival above the 0.05 floor. Only 3 were
genuine.

The mechanism is REFERENCE STALENESS. `FrameTracker`'s reference advances
only when a keyframe is accepted (`engine.py:283`), so during a run of
blurred frames it freezes while the camera keeps moving -- median 7, mean
12.4, max 89 frames stale at the moment of loss. The tracker is then asked
to cross that whole gap in a single Lucas-Kanade call.

These tests are DIFFERENTIAL on purpose. An earlier version of this file
asserted survival stayed above a floor on a white-noise image, which was
worse than useless: white noise has no structure across scales, so a
pyramid destroys it, and that test passed MORE strongly with the pyramid
removed entirely (survival 0.698 at level 0 against 0.127 at level 4). A
test that improves when you delete the feature it guards is not a test.
"""

import cv2
import numpy as np
import pytest

from tower.world_builder import frontend


def _room_like(seed: int) -> np.ndarray:
    """A frame with structure at several scales, as a real room has.

    Coarse blobs, mid texture, fine grain. This matters: a pyramid only
    buys reach when there is something left to track after downsampling,
    which white noise does not provide.
    """
    rng = np.random.default_rng(seed)
    height, width = 640, 360
    image = np.zeros((height, width), np.float32)
    for sigma, amplitude in ((48, 90), (16, 50), (5, 25)):
        noise = rng.normal(0, 1, (height, width)).astype(np.float32)
        image += amplitude * cv2.GaussianBlur(noise, (0, 0), sigma)
    image -= image.min()
    image *= 255.0 / image.max()
    return image.astype(np.uint8)


@pytest.fixture
def room():
    return _room_like(7)


class TestPyramidReach:
    def test_the_pyramid_is_deep_enough_for_the_measured_displacement(self):
        """Displacement p99 on the real walk is 85 px.

        Lucas-Kanade's capture range is roughly `winSize/2 * 2**maxLevel`:
        ~80 px at level 3, ~160 px at level 4. The measured p99 sits just
        past level 3, which is the worst place for a threshold to be.

        This is arithmetic over constants, so it guards against someone
        lowering the level without reading the measurement. The test below
        is the one that shows the reach is real.
        """
        reach_px = (frontend.LK_WINDOW[0] / 2) * (2 ** frontend.LK_MAX_LEVEL)
        assert reach_px >= 85.0

    def test_the_extra_level_actually_buys_reach_on_a_real_hop(self, room, monkeypatch):
        """The differential the constant cannot show.

        At an 80 px hop -- squarely inside the gap a stale reference
        produces -- level 3 collapses and level 4 does not. Measured here,
        not asserted: roughly 0.16 against 0.71.
        """
        hopped = np.roll(room, 80, axis=1)
        # Read the configured level BEFORE monkeypatching -- reading it
        # afterwards returns whatever the last patch set, which silently
        # compares level 3 against itself.
        configured = frontend.LK_MAX_LEVEL

        def survival_at(level: int) -> float:
            monkeypatch.setattr(frontend, "LK_MAX_LEVEL", level)
            tracker = frontend.FrameTracker()
            tracker.set_reference(room)
            motion = tracker.measure(hopped)
            return motion.survival_ratio if motion else 0.0

        shallow = survival_at(3)
        deep = survival_at(configured)

        assert deep > shallow * 2.0, (
            f"the extra pyramid level buys no reach (level 3 {shallow:.3f} "
            f"vs deep {deep:.3f}); fragmentation will return"
        )
        assert deep > 0.20


class TestItDoesNotSpliceUnrelatedFrames:
    """The load-bearing negative.

    Fewer segments is only an improvement if the losses removed were
    recoverable. Suppressing a GENUINE break would splice two unrelated
    coordinate frames into one segment, which is worse than fragmentation
    because it fabricates continuity rather than admitting a gap.
    """

    def test_two_unrelated_scenes_stay_below_the_loss_floor(self, room):
        unrelated = _room_like(99)
        tracker = frontend.FrameTracker()
        tracker.set_reference(room)

        motion = tracker.measure(unrelated)
        survival = motion.survival_ratio if motion else 0.0

        assert survival < 0.05, (
            f"unrelated frames survive at {survival:.4f}, at or above the "
            "loss floor -- the tracker would splice two coordinate frames "
            "into one segment and fabricate continuity"
        )


class TestForwardBackwardTolerance:
    def test_the_tolerance_still_rejects_a_track_that_does_not_return(self, room):
        """3.0 px must remain a discriminator, not a rubber stamp.

        Round-trip error grows with distance travelled, and a stale
        reference makes long hops routine, so a 1.0 px budget calibrated
        for adjacent frames rejects tracks that are real. But loosening it
        is NOT free: against a known warp, raising 1.0 -> 3.0 at a fixed
        pyramid level roughly doubles the gross-outlier rate (0.97% ->
        1.74% of survivors beyond 20 px). The pyramid change cuts that
        rate ~6x, so the pair is a net ~3.6x purity improvement -- but the
        forward-backward half is the weaker, costlier half of it.

        This pins the property that keeps it a discriminator at all.
        """
        assert frontend.FORWARD_BACKWARD_MAX_PX <= 3.0

        scrambled = _room_like(4242)
        tracker = frontend.FrameTracker()
        tracker.set_reference(room)
        motion = tracker.measure(scrambled)

        assert (motion.survival_ratio if motion else 0.0) < 0.05


class TestTrackDensityIsNotTheLever:
    def test_the_seed_cap_is_never_the_binding_constraint(self):
        """Raising this does nothing, and the measurement says so.

        MAX_TRACK_POINTS at 300 / 600 / 1200 produced identically 51
        segments on the real walk, because real frames supply a median of
        187 trackable corners and never approach the cap. The pipeline is
        displacement-limited, not feature-starved.

        This exists to stop a future reader "fixing" fragmentation by
        raising a number that cannot move it.
        """
        # Asserted against the REAL measurement, not a synthetic frame:
        # a generated scene yields far more corners than a 360x640 Ray-Ban
        # frame does, so measuring one here would prove nothing about the
        # footage this constant actually meets.
        measured_median_corners_on_real_frames = 187
        assert frontend.MAX_TRACK_POINTS > 2 * measured_median_corners_on_real_frames, (
            "the seed cap has come down near what real frames supply; it "
            "would start binding and the note that it is not a lever no "
            "longer holds"
        )
