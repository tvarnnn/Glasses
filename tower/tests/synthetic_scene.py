"""Synthetic indoor scenes with exact ground truth, for World Builder tests.

SYNTHETIC, NOT PHYSICAL. Nothing rendered here says anything about the
Ray-Ban Meta camera: this is a perfect pinhole with no distortion, no
rolling shutter, no auto-exposure, and no compression. Its value is the
opposite of realism -- because the camera poses, the intrinsics, and the
3-D structure are *inputs*, a test can assert an exact answer instead of
eyeballing a plausible one. Real footage can never give us that.

Rendering is by per-pixel ray/plane intersection rather than by warping
quads. Slower to describe, but it makes near-plane clipping, occlusion,
and behind-camera rejection fall out of the same arithmetic instead of
needing separate clipping code, and it yields analytic per-pixel depth --
which matters, because sampling ground-truth depth from a z-buffer by
nearest pixel disagrees with the analytic value by up to metres on
grazing surfaces, where one pixel of rounding is a long way along the ray.

Deterministic: textures are drawn from a seeded Generator, so a given
scene renders byte-identically across runs and tests can assert numbers
rather than ranges.
"""

from dataclasses import dataclass

import cv2
import numpy as np

# Depths at or below this are treated as behind the camera. Not zero:
# rays near-parallel to a plane produce enormous depths from a division by
# almost-zero, and clamping at a small positive epsilon keeps those out of
# the z-buffer rather than letting them win it.
NEAR_PLANE = 1e-3


@dataclass(frozen=True)
class Plane:
    """A textured parallelogram: origin + two edge vectors spanning [0, 1]."""

    origin: np.ndarray
    edge_u: np.ndarray
    edge_v: np.ndarray
    texture: np.ndarray

    @property
    def normal(self) -> np.ndarray:
        n = np.cross(self.edge_u, self.edge_v)
        return n / np.linalg.norm(n)


@dataclass(frozen=True)
class CameraPose:
    """T_world_camera: p_world = rotation @ p_camera + position.

    Matches the frozen POSE_CONVENTION -- the translation IS the camera
    position in world coordinates, so nothing here ever computes -R.T @ t.
    """

    rotation: np.ndarray
    position: np.ndarray


def make_texture(
    rng: np.random.Generator, width: int, height: int, base: int = 110
) -> np.ndarray:
    """Draw a high-frequency procedural texture ORB can actually track.

    Shape count is per-texel, not per-square-metre. Scaling by physical
    area sounds principled and is wrong: a 0.7 m box face then receives
    two shapes and is effectively textureless, which silently starves the
    feature detector on exactly the near-field objects that carry the
    parallax worth measuring.
    """
    image = np.full((height, width, 3), base, dtype=np.uint8)
    shape_count = max(25, (width * height) // 900)
    for _ in range(shape_count):
        colour = tuple(int(c) for c in rng.integers(0, 256, size=3))
        kind = rng.integers(0, 3)
        x0, y0 = int(rng.integers(0, width)), int(rng.integers(0, height))
        if kind == 0:
            x1 = int(np.clip(x0 + rng.integers(-width // 6, width // 6), 0, width))
            y1 = int(np.clip(y0 + rng.integers(-height // 6, height // 6), 0, height))
            cv2.rectangle(image, (x0, y0), (x1, y1), colour, -1)
        elif kind == 1:
            radius = int(rng.integers(3, max(4, min(width, height) // 12)))
            cv2.circle(image, (x0, y0), radius, colour, -1)
        else:
            x1 = int(np.clip(x0 + rng.integers(-width // 5, width // 5), 0, width))
            y1 = int(np.clip(y0 + rng.integers(-height // 5, height // 5), 0, height))
            cv2.line(image, (x0, y0), (x1, y1), colour, int(rng.integers(1, 4)))
    return image



def camera_matrix(width: int, height: int, focal: float | None = None) -> np.ndarray:
    """Ground-truth K. A test that uses this KNOWS the intrinsics.

    The default is a deliberately wide field of view (~79 deg horizontal at
    4:3). A narrow lens fills most of the frame with the single farthest
    surface -- measured at 75% of pixels on the far wall -- which starves
    near-field parallax and leaves depth-stratified assertions nothing to
    bite on.
    """
    if focal is None:
        focal = 0.6 * max(width, height)
    return np.array(
        [[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def look_at(position, target, up=(0.0, -1.0, 0.0)) -> CameraPose:
    """Build a pose looking from `position` toward `target`.

    Default up is -Y because the camera convention is OpenCV: +y points
    down in image space, so world -Y is "up" on screen.
    """
    position = np.asarray(position, dtype=np.float64)
    forward = np.asarray(target, dtype=np.float64) - position
    forward = forward / np.linalg.norm(forward)
    up = np.asarray(up, dtype=np.float64)
    right = np.cross(forward, up)
    right = right / np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.column_stack([right, down, forward])
    return CameraPose(rotation=rotation, position=position)


def _ray_directions(K: np.ndarray, width: int, height: int) -> np.ndarray:
    """Camera-frame ray per pixel, normalised so the z component is 1.

    With z == 1, the intersection parameter solved below IS the camera
    depth, so no separate depth computation is needed.
    """
    xs, ys = np.meshgrid(np.arange(width), np.arange(height))
    ones = np.ones_like(xs, dtype=np.float64)
    pixels = np.stack([xs, ys, ones], axis=-1).astype(np.float64)
    return pixels @ np.linalg.inv(K).T


def _plane_roi(
    plane: Plane, pose: CameraPose, K: np.ndarray, width: int, height: int
) -> tuple[int, int, int, int] | None:
    """Screen bounding box for a plane, or None when it cannot be visible.

    Restricting the per-pixel maths to this box is what keeps rendering
    affordable inside a test suite: a small object no longer costs a
    full-frame pass per plane. Returns the whole frame when any corner is
    behind the camera, because a projected bbox is meaningless once the
    projection wraps.
    """
    corners = np.array(
        [
            plane.origin,
            plane.origin + plane.edge_u,
            plane.origin + plane.edge_v,
            plane.origin + plane.edge_u + plane.edge_v,
        ]
    )
    local = (corners - pose.position) @ pose.rotation
    if np.all(local[:, 2] <= NEAR_PLANE):
        return None
    if np.any(local[:, 2] <= NEAR_PLANE):
        return 0, 0, width, height

    projected = local @ K.T
    xs = projected[:, 0] / projected[:, 2]
    ys = projected[:, 1] / projected[:, 2]
    x0 = max(0, int(np.floor(xs.min())))
    x1 = min(width, int(np.ceil(xs.max())) + 1)
    y0 = max(0, int(np.floor(ys.min())))
    y1 = min(height, int(np.ceil(ys.max())) + 1)
    if x0 >= x1 or y0 >= y1:
        return None
    return x0, y0, x1, y1


def render(
    planes: list[Plane], pose: CameraPose, K: np.ndarray, width: int, height: int
) -> tuple[np.ndarray, np.ndarray]:
    """Render BGR plus analytic per-pixel camera depth.

    Depth is NaN where no plane was hit, never 0 -- an unobserved pixel is
    unknown, and encoding it as a number a caller might average would be
    the same category error the module docs forbid at a larger scale.
    """
    directions_all = _ray_directions(K, width, height) @ pose.rotation.T

    colour = np.zeros((height, width, 3), dtype=np.uint8)
    depth = np.full((height, width), np.inf, dtype=np.float64)

    for plane in planes:
        roi = _plane_roi(plane, pose, K, width, height)
        if roi is None:
            continue
        x0, y0, x1, y1 = roi

        directions = directions_all[y0:y1, x0:x1]
        depth_roi = depth[y0:y1, x0:x1]

        normal = plane.normal
        denominator = directions @ normal
        # Rays parallel to the plane never hit it; guard the division
        # rather than filtering afterwards on an inf.
        parallel = np.abs(denominator) < 1e-12
        safe = np.where(parallel, 1.0, denominator)
        t = ((plane.origin - pose.position) @ normal) / safe

        hit = pose.position + t[..., None] * directions
        local = hit - plane.origin
        u = (local @ plane.edge_u) / (plane.edge_u @ plane.edge_u)
        v = (local @ plane.edge_v) / (plane.edge_v @ plane.edge_v)

        visible = (
            ~parallel
            & (t > NEAR_PLANE)
            & (u >= 0.0)
            & (u <= 1.0)
            & (v >= 0.0)
            & (v <= 1.0)
            & (t < depth_roi)
        )
        if not visible.any():
            continue

        th, tw = plane.texture.shape[:2]
        map_x = np.clip(u * (tw - 1), 0, tw - 1).astype(np.float32)
        map_y = np.clip(v * (th - 1), 0, th - 1).astype(np.float32)
        sampled = cv2.remap(
            plane.texture, map_x, map_y, interpolation=cv2.INTER_LINEAR
        )

        colour[y0:y1, x0:x1][visible] = sampled[visible]
        depth_roi[visible] = t[visible]

    depth[np.isinf(depth)] = np.nan
    return colour, depth


# The room's dimensions, as module constants rather than defaults buried
# in a signature. A measurement taken with the camera outside these bounds
# is not a measurement of the algorithm -- it is a measurement of running
# out of scene, and it looks exactly like accumulated drift.
ROOM_WIDTH_M = 6.0
ROOM_DEPTH_M = 4.0
ROOM_HEIGHT_M = 2.7


def poses_outside_room(
    poses,
    *,
    width_m: float = ROOM_WIDTH_M,
    depth_m: float = ROOM_DEPTH_M,
    height_m: float = ROOM_HEIGHT_M,
    margin_m: float = 0.5,
) -> list[int]:
    """Indices of poses too close to a wall, floor or ceiling to trust.

    This exists because a real defect hid behind its absence. A keyframe
    sweep using `strafe(N, step=0.20)` puts keyframe 16 at x = 3.00 m --
    exactly the right wall of the default room. Match counts collapse from
    ~1000 to ~640 as the camera approaches it and the pose is refused
    outright one step later, and the resulting trajectory error was read
    as "unbounded drift" for a while rather than as the camera walking
    into a wall.

    `margin_m` is not cosmetic: structure leaves the frame well before the
    camera reaches a surface, so the usable envelope is strictly smaller
    than the room.
    """
    half_w = width_m / 2 - margin_m
    outside = []
    for index, pose in enumerate(poses):
        x, y, z = (float(value) for value in pose.position)
        if not -half_w <= x <= half_w:
            outside.append(index)
        elif not margin_m <= z <= depth_m - margin_m:
            outside.append(index)
        elif not -(height_m - margin_m) <= y <= -margin_m:
            outside.append(index)
    return outside


def room_planes(
    rng: np.random.Generator,
    width_m: float = ROOM_WIDTH_M,
    depth_m: float = ROOM_DEPTH_M,
    height_m: float = ROOM_HEIGHT_M,
) -> list[Plane]:
    """A closed box room. Dimensions are inputs, so tests can assert them.

    World axes: +x right, +y down, +z forward. The floor is at y = 0 and
    the ceiling at y = -height_m, consistent with the OpenCV camera
    convention used throughout.
    """
    w, d, h = width_m, depth_m, height_m
    tex = lambda a, b: make_texture(rng, a, b)  # noqa: E731

    return [
        # floor
        Plane(
            origin=np.array([-w / 2, 0.0, 0.0]),
            edge_u=np.array([w, 0.0, 0.0]),
            edge_v=np.array([0.0, 0.0, d]),
            texture=tex(512, 384),
        ),
        # ceiling
        Plane(
            origin=np.array([-w / 2, -h, 0.0]),
            edge_u=np.array([w, 0.0, 0.0]),
            edge_v=np.array([0.0, 0.0, d]),
            texture=tex(512, 384),
        ),
        # far wall
        Plane(
            origin=np.array([-w / 2, -h, d]),
            edge_u=np.array([w, 0.0, 0.0]),
            edge_v=np.array([0.0, h, 0.0]),
            texture=tex(512, 256),
        ),
        # near wall (behind the start position)
        Plane(
            origin=np.array([-w / 2, -h, 0.0]),
            edge_u=np.array([w, 0.0, 0.0]),
            edge_v=np.array([0.0, h, 0.0]),
            texture=tex(512, 256),
        ),
        # left wall
        Plane(
            origin=np.array([-w / 2, -h, 0.0]),
            edge_u=np.array([0.0, 0.0, d]),
            edge_v=np.array([0.0, h, 0.0]),
            texture=tex(384, 256),
        ),
        # right wall
        Plane(
            origin=np.array([w / 2, -h, 0.0]),
            edge_u=np.array([0.0, 0.0, d]),
            edge_v=np.array([0.0, h, 0.0]),
            texture=tex(384, 256),
        ),
    ]


def box_planes(
    rng: np.random.Generator, centre, size, ) -> list[Plane]:
    """A textured box, for near-field structure the far wall cannot give.

    Without near objects, features cluster at the far wall because it
    dominates the solid angle, and per-depth-bin assertions have nothing
    to bite on.
    """
    cx, cy, cz = centre
    sx, sy, sz = size
    x0, y0, z0 = cx - sx / 2, cy - sy, cz - sz / 2
    tex = lambda: make_texture(rng, 192, 192)  # noqa: E731
    return [
        Plane(np.array([x0, y0, z0]), np.array([sx, 0, 0]), np.array([0, 0, sz]), tex()),
        Plane(np.array([x0, y0, z0]), np.array([sx, 0, 0]), np.array([0, sy, 0]), tex()),
        Plane(np.array([x0, y0, z0 + sz]), np.array([sx, 0, 0]), np.array([0, sy, 0]), tex()),
        Plane(np.array([x0, y0, z0]), np.array([0, 0, sz]), np.array([0, sy, 0]), tex()),
        Plane(np.array([x0 + sx, y0, z0]), np.array([0, 0, sz]), np.array([0, sy, 0]), tex()),
    ]


def furnished_room(seed: int = 1234, **kwargs) -> list[Plane]:
    rng = np.random.default_rng(seed)
    planes = room_planes(rng, **kwargs)
    planes += box_planes(rng, centre=(-1.4, 0.0, 2.2), size=(0.9, 0.75, 0.6))
    planes += box_planes(rng, centre=(1.5, 0.0, 2.8), size=(0.7, 1.1, 0.7))
    return planes


# -- trajectories ------------------------------------------------------
#
# Each returns a list of CameraPose. Motion type matters enormously to
# what a test may assert: lateral motion recovers translation direction
# almost exactly, while forward motion -- which is what a walking person
# actually does -- puts the epipole inside the image and degrades
# translation direction badly even with perfect features. Thresholds must
# therefore be motion-dependent, and a single global tolerance would be
# either useless or wrong.


def strafe(count: int, step: float = 0.1, start=(0.0, -1.6, 0.6)) -> list[CameraPose]:
    """Sideways motion. The best case for two-view geometry."""
    return [
        look_at(
            (start[0] + i * step, start[1], start[2]),
            (start[0] + i * step, start[1], start[2] + 1.0),
        )
        for i in range(count)
    ]


def forward_walk(
    count: int, step: float = 0.1, start=(0.0, -1.6, 0.4)
) -> list[CameraPose]:
    """Walking into the scene. Realistic, and the hard case."""
    return [
        look_at(
            (start[0], start[1], start[2] + i * step),
            (start[0], start[1], start[2] + i * step + 1.0),
        )
        for i in range(count)
    ]


def pure_rotation(
    count: int, degrees_per_step: float = 2.0, position=(0.0, -1.6, 1.2)
) -> list[CameraPose]:
    """Rotation about the camera centre: zero baseline, and degenerate.

    Triangulation is not merely noisy here, it is undefined -- and
    recoverPose will still return a confident answer, which is exactly the
    failure the degeneracy gate exists to catch.
    """
    poses = []
    for i in range(count):
        angle = np.deg2rad(i * degrees_per_step)
        target = (
            position[0] + np.sin(angle),
            position[1],
            position[2] + np.cos(angle),
        )
        poses.append(look_at(position, target))
    return poses



def render_sequence(
    planes: list[Plane],
    poses: list[CameraPose],
    K: np.ndarray,
    width: int,
    height: int,
) -> list[np.ndarray]:
    return [render(planes, pose, K, width, height)[0] for pose in poses]


def encode_jpeg(image: np.ndarray, quality: int = 90) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:  # pragma: no cover - imencode failure is not reachable here
        raise RuntimeError("failed to encode synthetic frame")
    return buffer.tobytes()


def blur(image: np.ndarray, kernel: int = 9) -> np.ndarray:
    return cv2.GaussianBlur(image, (kernel, kernel), 0)



def relative_pose(a: CameraPose, b: CameraPose) -> tuple[np.ndarray, np.ndarray]:
    """Ground truth in exactly cv2.recoverPose's convention.

    Rotation is R_21 (maps a point from camera a's frame into camera b's),
    which is ``b.rotation.T @ a.rotation`` -- the TRANSPOSE of the more
    intuitive "a to b" composition. Translation is the camera motion
    direction expressed in camera a's frame, matching
    recoverpose_motion_direction().

    The transpose is not pedantry. An earlier version returned the other
    convention and every rotation in a 2-degree sweep read as ~4 degrees
    of error -- exactly twice the true angle, because comparing R against
    R.T measures 2R. It looked like a plausible accuracy problem rather
    than a convention bug, which is precisely why the pose contract is
    frozen in schema.py and why readers refuse rather than guess.
    """
    rotation = b.rotation.T @ a.rotation
    translation = a.rotation.T @ (b.position - a.position)
    norm = np.linalg.norm(translation)
    direction = translation / norm if norm > 1e-12 else np.zeros(3)
    return rotation, direction


def rotation_error_deg(a: np.ndarray, b: np.ndarray) -> float:
    delta = a.T @ b
    cos = (np.trace(delta) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def direction_error_deg(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return float("nan")
    cos = float(np.dot(a, b) / (na * nb))
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def umeyama_similarity(
    source: np.ndarray, target: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    """Best similarity aligning `source` onto `target`.

    Needed because a monocular reconstruction is only ever correct up to a
    similarity -- comparing raw coordinates to ground truth would fail a
    perfectly correct result. Returns (scale, rotation, translation).
    """
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centred = source - source_mean
    target_centred = target - target_mean

    covariance = target_centred.T @ source_centred / len(source)
    u, singular, vt = np.linalg.svd(covariance)
    correction = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        correction[2, 2] = -1.0
    rotation = u @ correction @ vt

    variance = (source_centred**2).sum() / len(source)
    scale = float((singular * np.diag(correction)).sum() / variance)
    translation = target_mean - scale * rotation @ source_mean
    return scale, rotation, translation
