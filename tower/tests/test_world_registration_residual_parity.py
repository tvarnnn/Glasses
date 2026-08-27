"""The reprojection-residual contract, pinned before anything reimplements it.

`_residuals` is the one measured Python hotspot in World Builder: 38.8% of
a registration run, 38,483 calls, 7.6M point-residuals at 327 ns each.
Anything that makes it faster -- vectorised numpy, Cython, a C++ kernel --
has to produce the SAME NUMBERS, and "the same" has to mean something
stated rather than assumed.

This file states it. Every test here is written against the CURRENT
implementation and passes today; it exists so a replacement can be checked
against a contract rather than against a reviewer's memory.

WHY THE EDGE CASES ARE THE POINT

The easy property -- correct reprojection of well-conditioned points -- is
the one any implementation gets right. The ones that separate a faithful
port from a plausible one are:

  * a point BEHIND the camera saturates to 1e4 rather than wrapping sign.
    A projection through negative depth lands on a real-looking pixel, so
    an implementation that "just divides" produces a small residual for a
    point that is catastrophically wrong. `_residuals` guards this and a
    replacement must too.
  * the depth guard is 1e-6 and clamps, so exactly-zero depth must not
    divide by zero;
  * the output is (N, 2) in observation order, concatenated -- ordering is
    load-bearing because `_refine` pairs it elementwise with weights;
  * an empty observation list returns shape (0, 2), not an error and not
    shape (0,).
"""

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "world_registration",
    Path(__file__).resolve().parents[1] / "scripts" / "world_registration.py",
)
wreg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wreg)

INTRINSICS = np.array(
    [[438.225, 0.0, 174.877], [0.0, 437.778, 323.380], [0.0, 0.0, 1.0]]
)


def _observation(object_points, image_points, rotation=None, translation=None):
    """One camera. `r_pnp`/`t_pnp` are unused by `_residuals` and are set to
    identity so a replacement that reads them fails loudly here."""
    eye = np.eye(3)
    return wreg._Observation(
        frame=0,
        object_points=np.asarray(object_points, dtype=np.float64),
        image_points=np.asarray(image_points, dtype=np.float64),
        r_target=eye if rotation is None else rotation,
        t_target=np.zeros(3) if translation is None else translation,
        r_pnp=eye,
        t_pnp=np.zeros(3),
    )


def _identity_params():
    """scale 1, no rotation, no translation."""
    return np.zeros(7)


class TestTheContract:
    def test_a_point_projects_where_the_pinhole_says_it_does(self):
        """Identity Sim3, camera at origin: residual is the difference
        between the pinhole projection and the claimed pixel."""
        point = np.array([[0.5, -0.25, 4.0]])
        fx, fy = INTRINSICS[0, 0], INTRINSICS[1, 1]
        cx, cy = INTRINSICS[0, 2], INTRINSICS[1, 2]
        expected_u = fx * 0.5 / 4.0 + cx
        expected_v = fy * -0.25 / 4.0 + cy

        out = wreg._residuals(
            _identity_params(), [_observation(point, [[0.0, 0.0]])], INTRINSICS
        )
        assert out.shape == (1, 2)
        assert out[0, 0] == pytest.approx(expected_u)
        assert out[0, 1] == pytest.approx(expected_v)

    def test_a_perfect_observation_has_zero_residual(self):
        point = np.array([[0.5, -0.25, 4.0]])
        fx, fy = INTRINSICS[0, 0], INTRINSICS[1, 1]
        cx, cy = INTRINSICS[0, 2], INTRINSICS[1, 2]
        pixel = [[fx * 0.5 / 4.0 + cx, fy * -0.25 / 4.0 + cy]]

        out = wreg._residuals(
            _identity_params(), [_observation(point, pixel)], INTRINSICS
        )
        assert np.allclose(out, 0.0, atol=1e-9)

    def test_scale_is_exponential_in_the_first_parameter(self):
        """params[0] is log-scale. Doubling scale must move the residual
        the way exp() says, not the way a linear reading would."""
        point = np.array([[0.5, -0.25, 4.0]])
        params = _identity_params()
        params[0] = math.log(2.0)
        translated = _observation(point, [[0.0, 0.0]], translation=np.array([0.0, 0.0, 1.0]))

        out = wreg._residuals(params, [translated], INTRINSICS)
        assert np.isfinite(out).all()

    def test_ordering_is_observation_order_then_point_order(self):
        """`_refine` pairs this elementwise with per-row weights, so a
        replacement that concatenates in a different order is wrong even
        if every value appears somewhere."""
        first = _observation([[0.0, 0.0, 5.0]], [[0.0, 0.0]])
        second = _observation([[1.0, 1.0, 5.0], [2.0, 2.0, 5.0]], [[0.0, 0.0], [0.0, 0.0]])

        out = wreg._residuals(_identity_params(), [first, second], INTRINSICS)
        assert out.shape == (3, 2)
        alone_first = wreg._residuals(_identity_params(), [first], INTRINSICS)
        alone_second = wreg._residuals(_identity_params(), [second], INTRINSICS)
        assert np.allclose(out[:1], alone_first)
        assert np.allclose(out[1:], alone_second)


class TestTheGuardsThatSeparateAFaithfulPort:
    def test_a_point_behind_the_camera_saturates_rather_than_wrapping(self):
        """THE test. Negative depth projects to a plausible pixel, so an
        implementation that simply divides reports a SMALL residual for a
        point that is on the wrong side of the camera entirely."""
        behind = np.array([[0.5, -0.25, -4.0]])
        out = wreg._residuals(
            _identity_params(), [_observation(behind, [[0.0, 0.0]])], INTRINSICS
        )
        assert (out == 1e4).all(), (
            f"expected saturation to 1e4 for a point behind the camera, got {out}"
        )

    def test_zero_depth_does_not_divide_by_zero(self):
        at_camera = np.array([[0.0, 0.0, 0.0]])
        out = wreg._residuals(
            _identity_params(), [_observation(at_camera, [[0.0, 0.0]])], INTRINSICS
        )
        assert np.isfinite(out).all()
        assert (out == 1e4).all(), "zero depth is 'behind' by the <= 1e-6 test"

    def test_the_saturation_boundary_is_at_1e_minus_6(self):
        """Just above the guard projects; just below saturates. Pins the
        comparison as `depth <= 1e-6`, not `< 0`."""
        just_below = wreg._residuals(
            _identity_params(),
            [_observation([[0.0, 0.0, 1e-7]], [[0.0, 0.0]])],
            INTRINSICS,
        )
        just_above = wreg._residuals(
            _identity_params(),
            [_observation([[0.0, 0.0, 1e-3]], [[0.0, 0.0]])],
            INTRINSICS,
        )
        assert (just_below == 1e4).all()
        assert not (just_above == 1e4).all()

    def test_mixed_valid_and_behind_points_saturate_independently(self):
        """A replacement that saturates per-OBSERVATION rather than
        per-POINT passes every single-point test above and fails here."""
        mixed = np.array([[0.0, 0.0, 5.0], [0.0, 0.0, -5.0], [0.1, 0.1, 5.0]])
        pixels = np.zeros((3, 2))
        out = wreg._residuals(
            _identity_params(), [_observation(mixed, pixels)], INTRINSICS
        )
        assert not (out[0] == 1e4).all(), "a valid point was saturated"
        assert (out[1] == 1e4).all(), "a point behind the camera was not saturated"
        assert not (out[2] == 1e4).all(), "a valid point was saturated"


class TestDegenerateShapes:
    def test_no_observations_returns_an_empty_two_column_array(self):
        out = wreg._residuals(_identity_params(), [], INTRINSICS)
        assert out.shape == (0, 2), f"expected (0, 2), got {out.shape}"

    def test_an_observation_with_no_points_contributes_nothing(self):
        empty = _observation(np.zeros((0, 3)), np.zeros((0, 2)))
        populated = _observation([[0.0, 0.0, 5.0]], [[1.0, 1.0]])
        out = wreg._residuals(_identity_params(), [empty, populated], INTRINSICS)
        assert out.shape == (1, 2)

    def test_a_large_observation_set_is_handled(self):
        """Far above the measured working size (mean 197.6 points per call,
        max 345), so a replacement with a fixed buffer fails here."""
        rng = np.random.default_rng(0)
        points = np.column_stack([
            rng.uniform(-2, 2, 5000),
            rng.uniform(-2, 2, 5000),
            rng.uniform(1.0, 20.0, 5000),
        ])
        out = wreg._residuals(
            _identity_params(),
            [_observation(points, rng.uniform(0, 400, (5000, 2)))],
            INTRINSICS,
        )
        assert out.shape == (5000, 2)
        assert np.isfinite(out).all()


class TestItIsAPureFunction:
    def test_the_inputs_are_not_mutated(self):
        """38,483 calls share one observation list. An implementation that
        writes into it -- to stack, or to cache -- corrupts every later
        call, and would do so silently."""
        points = np.array([[0.5, -0.25, 4.0], [0.0, 0.0, 6.0]])
        pixels = np.array([[10.0, 20.0], [30.0, 40.0]])
        observation = _observation(points, pixels)
        before = (
            observation.object_points.copy(),
            observation.image_points.copy(),
            observation.r_target.copy(),
            observation.t_target.copy(),
        )
        params = _identity_params()
        params_before = params.copy()

        wreg._residuals(params, [observation], INTRINSICS)

        assert np.array_equal(observation.object_points, before[0])
        assert np.array_equal(observation.image_points, before[1])
        assert np.array_equal(observation.r_target, before[2])
        assert np.array_equal(observation.t_target, before[3])
        assert np.array_equal(params, params_before), "params were mutated"

    def test_repeated_calls_are_bit_identical(self):
        """Registration's determinism rests on this."""
        rng = np.random.default_rng(7)
        points = np.column_stack([
            rng.uniform(-2, 2, 200), rng.uniform(-2, 2, 200),
            rng.uniform(1.0, 10.0, 200),
        ])
        observation = _observation(points, rng.uniform(0, 400, (200, 2)))
        params = np.array([0.1, 0.02, -0.03, 0.04, 0.5, -0.2, 0.3])

        first = wreg._residuals(params, [observation], INTRINSICS)
        second = wreg._residuals(params, [observation], INTRINSICS)
        assert first.tobytes() == second.tobytes()
