"""How far the tracker can reach between one reference and the next.

Segment breaks were assumed to come from imagery the tracker could not
follow. Replaying all 1,848 frames of the 2026-08-25 walk through the real
`FrameTracker` says otherwise: median consecutive-frame survival is 0.874,
and on the 50 frames where loss was declared, 47 still had frame-to-frame
survival above the 0.05 floor. Only 3 were genuine.

The mechanism is REFERENCE STALENESS. `FrameTracker`'s reference advances
only when a keyframe is accepted (`engine.py:283`), so during a run of
blurred frames it freezes while the camera keeps moving -- median 7, mean
12.4, max 89 frames stale at the moment of loss. The tracker is then asked
to cross that whole gap in a single Lucas-Kanade call.

So the fix is reach, not image quality. These tests pin the two constants
that buy it, and -- more importantly -- pin the reasoning, because both
look like arbitrary tuning to anyone who has not read the measurement.
"""

import numpy as np
import pytest

from tower.world_builder import frontend


class TestPyramidReach:
    def test_the_pyramid_is_deep_enough_for_the_measured_displacement(self):
        """Displacement p99 on the real walk is 85 px.

        Lucas-Kanade's capture range is roughly `winSize/2 * 2**maxLevel`.
        At level 3 with a 21 px window that is ~80 px -- just under the p99
        the real footage actually produces, which is exactly the wrong side
        of it. Level 4 doubles the reach to ~160 px.

        Measured: 51 segments -> 40 on the 2026-08-25 walk, at identical
        runtime (4.85 ms either way), for one added keyframe.
        """
        reach_px = (frontend.LK_WINDOW[0] / 2) * (2 ** frontend.LK_MAX_LEVEL)
        assert reach_px >= 85.0, (
            "the pyramid no longer reaches the p99 displacement measured on "
            "real footage; segment count will rise"
        )

    def test_the_window_and_level_are_read_by_both_flow_directions(self):
        """A forward/backward mismatch would silently break the FB check."""
        source = (frontend.__file__)
        text = open(source, encoding="utf-8").read()
        assert text.count("maxLevel=LK_MAX_LEVEL") == 2
        assert text.count("winSize=LK_WINDOW") == 2


class TestForwardBackwardTolerance:
    def test_the_tolerance_admits_a_real_track_across_a_stale_gap(self):
        """1.0 px is a same-frame-pair tolerance, not a cross-gap one.

        Forward-backward error grows with the distance travelled. Holding a
        1.0 px round trip across a 7-to-89 frame gap rejects tracks that are
        real, which is what turned recoverable drift into declared loss.

        3.0 px still refuses coincidences -- it is well inside the 21 px
        window -- and measured 51 -> 33 segments combined with the pyramid
        change, with reconstruction quality RISING rather than falling:
        solvable pairs 46% -> 53%, median triangulation angle 0.43 -> 0.63 deg.
        """
        assert 1.0 < frontend.FORWARD_BACKWARD_MAX_PX <= 3.0
        assert frontend.FORWARD_BACKWARD_MAX_PX < frontend.LK_WINDOW[0] / 4, (
            "a round-trip tolerance approaching the search window stops "
            "discriminating between a track and a coincidence"
        )


class TestTrackDensityIsNotTheLever:
    def test_the_seed_cap_is_far_above_what_real_frames_supply(self):
        """Raising this does nothing, and the measurement says so.

        MAX_TRACK_POINTS at 300 / 600 / 1200 produced identically 51
        segments. Real frames supply a median of 187 trackable corners, so
        the cap is never the binding constraint -- the pipeline is
        displacement-limited, not feature-starved.

        This test exists to stop a future reader "fixing" fragmentation by
        raising a number that cannot move it.
        """
        assert frontend.MAX_TRACK_POINTS >= 300


class TestReachIsRealNotJustConstants:
    @pytest.fixture
    def drifting_pair(self):
        """Two synthetic frames separated by a large shift.

        60 px is beyond level 3's ~80 px only in combination with noise, so
        this asserts the tracker survives a hop that a stale reference makes
        routine -- not that it survives anything at all.
        """
        rng = np.random.default_rng(20260826)
        base = rng.integers(0, 255, (240, 180), dtype=np.uint8)
        base = np.repeat(np.repeat(base, 2, axis=0), 2, axis=1)[:480, :360]
        shifted = np.roll(base, 60, axis=1)
        return base.astype(np.uint8), shifted.astype(np.uint8)

    def test_a_large_hop_still_yields_usable_survival(self, drifting_pair):
        base, shifted = drifting_pair
        tracker = frontend.FrameTracker()
        # set_reference, not measure: the reference advances ONLY on an
        # accept. That asymmetry is the whole mechanism -- a run of blurred
        # frames leaves this reference frozen while the camera moves on.
        tracker.set_reference(base)

        motion = tracker.measure(shifted)

        assert motion is not None
        assert motion.survival_ratio > 0.05, (
            "a 60 px hop reads as total track loss; the pyramid is not "
            "reaching far enough for a stale reference"
        )
