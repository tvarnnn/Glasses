"""The synthetic scene has a validity envelope, and measurements must respect it.

SYNTHETIC, NOT PHYSICAL.

A trajectory-drift figure of 21.6% at 16 keyframes was recorded as
"unbounded drift with no correction". Investigation found the dominant
cause was that the walk used to produce it -- `strafe(16, step=0.20)` --
puts keyframe 16 at x = 3.00 m, which is exactly the right wall of the
default 6 m room. Match counts fall from ~1000 to ~640 approaching it and
the next pose is refused outright.

Running out of scene and accumulating drift look identical in a single
error percentage. These tests make the difference checkable.
"""

import pytest

from tests import synthetic_scene as ss


class TestPosesOutsideRoom:
    def test_a_short_strafe_stays_inside(self):
        assert ss.poses_outside_room(ss.strafe(8, step=0.20)) == []

    def test_the_sixteen_keyframe_sweep_leaves_the_room(self):
        """The exact configuration that produced the misread drift figure."""
        outside = ss.poses_outside_room(ss.strafe(16, step=0.20))

        assert outside, "strafe(16, step=0.20) must be flagged: it reaches the wall"
        # x = index * 0.20; the usable half-width is 3.0 - 0.5 = 2.5 m,
        # so index 13 (x = 2.6) is the first one out.
        assert outside[0] == 13

    def test_a_forward_walk_that_reaches_the_far_wall_is_flagged(self):
        assert ss.poses_outside_room(ss.forward_walk(40, step=0.15)) != []

    def test_pure_rotation_never_leaves_the_room(self):
        """It does not translate, so it cannot walk out of anything."""
        assert ss.poses_outside_room(ss.pure_rotation(20)) == []

    def test_the_margin_is_honoured(self):
        """A pose inside the walls but inside the margin is still refused.

        Structure leaves the frame well before the camera reaches a
        surface, so the usable envelope is smaller than the room.
        """
        just_inside_the_wall = ss.strafe(1, step=0.0, start=(2.9, -1.6, 0.6))

        assert ss.poses_outside_room(just_inside_the_wall, margin_m=0.5) == [0]
        assert ss.poses_outside_room(just_inside_the_wall, margin_m=0.0) == []

    def test_room_constants_drive_the_planes(self):
        """The bounds check and the geometry must not be able to drift apart."""
        import numpy as np

        planes = ss.room_planes(np.random.default_rng(0))
        xs = [
            float(value)
            for plane in planes
            for value in (
                plane.origin[0],
                plane.origin[0] + plane.edge_u[0],
                plane.origin[0] + plane.edge_v[0],
            )
        ]

        assert max(xs) == pytest.approx(ss.ROOM_WIDTH_M / 2)
        assert min(xs) == pytest.approx(-ss.ROOM_WIDTH_M / 2)


class TestGeometryDegradesAtTheBoundary:
    """The mechanism itself, measured rather than asserted from memory."""

    def test_matches_collapse_as_the_camera_approaches_the_wall(self):
        import cv2

        from tower.world_builder.geometry import detect_and_describe, match_indices

        width, height = 480, 360
        scene = ss.furnished_room()
        camera_matrix = ss.camera_matrix(width, height)
        poses = ss.strafe(16, step=0.20)
        images = ss.render_sequence(scene, poses, camera_matrix, width, height)
        grays = [
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
            for image in images
        ]
        described = [detect_and_describe(gray) for gray in grays]

        counts = [
            len(match_indices(described[i][1], described[i + 1][1]))
            for i in range(len(grays) - 1)
        ]

        inside = ss.poses_outside_room(poses)
        first_outside = inside[0]
        early = counts[1]
        late = counts[first_outside - 1]

        assert late < early * 0.85, (
            "expected correspondence count to fall approaching the wall; "
            f"early={early} late={late}"
        )
