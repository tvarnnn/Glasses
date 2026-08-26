"""Cross-segment registration: the gate, the composition, and the refusals.

The property these tests exist to protect is the one measured in
docs/superpowers/research/2026-08-26-cross-segment-registration.md section 6:
a WRONG Sim3 reprojects beautifully. Segment pair (30,50) on the real walk
fits at 1.62 px with 88% of correspondences under 3 px and is wrong by a
factor of 3.2 in scale. So fit quality cannot be allowed to admit a pair,
and the tests below check that it structurally cannot -- not that some
particular threshold happens to be set high enough today.
"""

import copy
import dataclasses
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from scripts.world_registration import (
    DirectedFit,
    MutualEvidence,
    SegmentGeometry,
    SupportMissingError,
    Thresholds,
    admit,
    compose_tree,
    fit_direction,
    read_segments,
    register,
    report_to_json,
    span_over_depth,
)
from tower.world_builder.store import WorldStore


def _fit(source, target, *, scale, cameras=9, reprojection_px=1.5,
         scale_ambiguity=1.2, correspondences=400, span_over_depth=0.35,
         provenance=None):
    # Provenance defaults to the target's own cameras, which is what a real
    # solve records -- so two fits built by this helper in opposite
    # directions are independent, and two built in the SAME direction are
    # not.
    if provenance is None:
        provenance = frozenset((target, frame) for frame in range(cameras))
    return DirectedFit(
        source=source,
        target=target,
        scale=scale,
        rotation=np.eye(3),
        translation=np.zeros(3),
        cameras=cameras,
        correspondences=correspondences,
        reprojection_px=reprojection_px,
        scale_ambiguity=scale_ambiguity,
        provenance=provenance,
        target_span_over_depth=span_over_depth,
    )


class TestFitQualityCannotAdmit:
    """The (30,50) property, structurally."""

    def test_admit_refuses_a_single_direction_outright(self):
        """A flawless one-way fit is not evidence. It cannot even be typed."""
        flawless = _fit(30, 50, scale=0.0923, reprojection_px=0.1,
                        scale_ambiguity=1.0, cameras=12)

        with pytest.raises(TypeError) as excinfo:
            admit(flawless, Thresholds())

        assert "MutualEvidence" in str(excinfo.value)

    def test_evidence_cannot_be_built_from_one_fit_twice(self):
        """The obvious way to fake agreement: hand over the same solve twice."""
        fit = _fit(30, 50, scale=0.5)

        with pytest.raises(ValueError) as excinfo:
            MutualEvidence(forward=fit, reverse=fit)

        assert "independent" in str(excinfo.value).lower()

    def test_an_algebraically_inverted_copy_is_not_independent(self):
        """The bypass an adversarial review found, and the reason for provenance.

        Relabelling a fit and inverting its scale produces something that
        agrees with itself to 0.0% by construction. It passed the
        label-and-identity checks; it must not pass the provenance one.
        """
        forward = _fit(30, 50, scale=0.0923)

        reverse = dataclasses.replace(
            forward, source=50, target=30, scale=1.0 / forward.scale
        )

        with pytest.raises(ValueError) as excinfo:
            MutualEvidence(forward=forward, reverse=reverse)

        assert "independent" in str(excinfo.value).lower()

    def test_a_deep_copy_is_not_independent_either(self):
        forward = _fit(30, 50, scale=0.0923)
        reverse = copy.deepcopy(forward)
        object.__setattr__(reverse, "source", 50)
        object.__setattr__(reverse, "target", 30)
        object.__setattr__(reverse, "scale", 1.0 / forward.scale)

        with pytest.raises(ValueError):
            MutualEvidence(forward=forward, reverse=reverse)

    def test_genuinely_separate_solves_are_accepted(self):
        """The check must not refuse honest evidence: different cameras posed."""
        evidence = MutualEvidence(
            forward=_fit(4, 5, scale=0.3533),
            reverse=_fit(5, 4, scale=2.8387),
        )

        assert evidence.forward.provenance != evidence.reverse.provenance

    def test_evidence_requires_opposite_directions(self):
        with pytest.raises(ValueError):
            MutualEvidence(forward=_fit(4, 5, scale=0.35),
                           reverse=_fit(4, 32, scale=2.8))

    def test_the_known_bad_pair_is_refused_despite_fitting_well(self):
        """(30,50): 1.62/2.05 px, 88%/75% under 3 px, scale wrong by 3.2x."""
        evidence = MutualEvidence(
            forward=_fit(30, 50, scale=0.0923, reprojection_px=1.62,
                         scale_ambiguity=20.6, cameras=4),
            reverse=_fit(50, 30, scale=3.3697, reprojection_px=2.05,
                         scale_ambiguity=7.1, cameras=4),
        )

        verdict = admit(evidence, Thresholds())

        assert not verdict.registered
        assert verdict.reciprocity == pytest.approx(0.0923 * 3.3697, rel=1e-6)
        assert "disagree" in verdict.reason

    def test_reciprocity_alone_flips_the_verdict(self):
        """Same fit quality on both. Only independent agreement differs."""
        good = MutualEvidence(forward=_fit(4, 5, scale=0.3533),
                              reverse=_fit(5, 4, scale=2.8387))
        bad = MutualEvidence(forward=_fit(4, 5, scale=0.3533),
                             reverse=_fit(5, 4, scale=4.2581))

        assert admit(good, Thresholds()).registered
        assert not admit(bad, Thresholds()).registered

    def test_perfect_reprojection_does_not_rescue_bad_reciprocity(self):
        evidence = MutualEvidence(
            forward=_fit(30, 50, scale=0.0923, reprojection_px=0.01,
                         scale_ambiguity=1.0, cameras=30,
                         correspondences=10_000),
            reverse=_fit(50, 30, scale=3.3697, reprojection_px=0.01,
                         scale_ambiguity=1.0, cameras=30,
                         correspondences=10_000),
        )

        assert not admit(evidence, Thresholds()).registered


class TestGateClauses:
    def test_the_agreeing_pair_passes(self):
        """(4,5) on the real walk: reciprocity 1.0030."""
        evidence = MutualEvidence(
            forward=_fit(4, 5, scale=0.3533, cameras=9, reprojection_px=1.50,
                         scale_ambiguity=2.0),
            reverse=_fit(5, 4, scale=2.8387, cameras=5, reprojection_px=1.44,
                         scale_ambiguity=1.0),
        )

        verdict = admit(evidence, Thresholds())

        assert verdict.registered
        assert verdict.reciprocity == pytest.approx(1.003, abs=5e-4)

    def test_two_cameras_are_not_enough(self):
        """The s = 0.0000 collapses all came from two-camera fits."""
        evidence = MutualEvidence(
            forward=_fit(12, 48, scale=1.0, cameras=2),
            reverse=_fit(48, 12, scale=1.0, cameras=2),
        )

        verdict = admit(evidence, Thresholds())

        assert not verdict.registered
        assert "camera" in verdict.reason

    def test_wide_scale_ambiguity_is_refused(self):
        """Segment 6's self-test: 0.75 px, and scale wrong by 33%."""
        evidence = MutualEvidence(
            forward=_fit(5, 6, scale=1.0, scale_ambiguity=4.1),
            reverse=_fit(6, 5, scale=1.0, scale_ambiguity=5.0),
        )

        verdict = admit(evidence, Thresholds())

        assert not verdict.registered
        assert "ambigu" in verdict.reason

    def test_bad_reprojection_is_refused_too(self):
        """Necessary, nowhere near sufficient."""
        evidence = MutualEvidence(
            forward=_fit(5, 6, scale=1.0, reprojection_px=7.06),
            reverse=_fit(6, 5, scale=1.0, reprojection_px=2.49),
        )

        assert not admit(evidence, Thresholds()).registered

    def test_a_degenerate_scale_is_refused(self):
        evidence = MutualEvidence(forward=_fit(5, 1, scale=0.0),
                                  reverse=_fit(1, 5, scale=0.0))

        assert not admit(evidence, Thresholds()).registered

    def test_a_nan_scale_is_refused(self):
        """The degenerate-scale clause is the ONLY NaN guard in the gate.

        `abs(nan - 1.0) > 0.10` is False, so the reciprocity clause passes a
        NaN straight through. Deleting the degenerate clause therefore
        admits this pair -- which is what a mutation run found, because the
        old test matched the word "scale" in a reason string that the
        reciprocity clause also happens to contain. Assert the verdict.
        """
        evidence = MutualEvidence(
            forward=_fit(5, 1, scale=float("nan")),
            reverse=_fit(1, 5, scale=float("nan")),
        )

        assert not admit(evidence, Thresholds()).registered

    def test_an_infinite_scale_is_refused(self):
        evidence = MutualEvidence(
            forward=_fit(5, 1, scale=float("inf")),
            reverse=_fit(1, 5, scale=0.0),
        )

        assert not admit(evidence, Thresholds()).registered

    def test_both_sides_need_enough_cameras_not_just_one(self):
        """Kills `cameras = max(...)`: 30 on one side cannot cover 2 on the other."""
        evidence = MutualEvidence(
            forward=_fit(4, 5, scale=0.3533, cameras=30),
            reverse=_fit(5, 4, scale=2.8387, cameras=2),
        )

        verdict = admit(evidence, Thresholds())

        assert not verdict.registered
        assert verdict.clauses["cameras"] == 2

    def test_ambiguity_is_judged_on_the_worse_direction(self):
        """Kills `ambiguity = min(...)`: one crisp direction cannot cover a vague one."""
        evidence = MutualEvidence(
            forward=_fit(4, 5, scale=0.3533, scale_ambiguity=1.0),
            reverse=_fit(5, 4, scale=2.8387, scale_ambiguity=20.0),
        )

        verdict = admit(evidence, Thresholds())

        assert not verdict.registered
        assert verdict.clauses["scale_ambiguity"] == 20.0

    def test_reprojection_is_judged_on_the_worse_direction(self):
        evidence = MutualEvidence(
            forward=_fit(4, 5, scale=0.3533, reprojection_px=0.1),
            reverse=_fit(5, 4, scale=2.8387, reprojection_px=9.0),
        )

        verdict = admit(evidence, Thresholds())

        assert not verdict.registered
        assert verdict.clauses["reprojection_px"] == 9.0

    def test_a_segment_without_parallax_is_refused_by_the_gate(self):
        """Kills MIN_SPAN_OVER_DEPTH being decorative.

        It used to appear only inside a reason string, so a pair whose
        target segment had no baseline was admitted on reciprocity alone.
        """
        evidence = MutualEvidence(
            forward=_fit(5, 6, scale=1.0, span_over_depth=0.043),
            reverse=_fit(6, 5, scale=1.0, span_over_depth=0.345),
        )

        verdict = admit(evidence, Thresholds())

        assert not verdict.registered
        assert verdict.clauses["span_over_depth"] == pytest.approx(0.043)
        assert "stood still" in verdict.reason

    def test_parallax_on_both_sides_is_admitted(self):
        """Segment 4 sits at 0.0951, barely over the line. It must still pass."""
        evidence = MutualEvidence(
            forward=_fit(4, 5, scale=0.3533, span_over_depth=0.345),
            reverse=_fit(5, 4, scale=2.8387, span_over_depth=0.0951),
        )

        assert admit(evidence, Thresholds()).registered


class TestSpanOverDepth:
    """The pre-check that makes a refusal explicable rather than opaque."""

    def test_a_walking_segment_has_parallax(self):
        centres = np.array([[0.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0], [3.4, 0, 0]])
        points = np.random.default_rng(0).normal(0, 1, (200, 3)) + [0, 0, 10.0]
        assert span_over_depth(centres, points) > 0.09

    def test_a_standing_segment_has_none(self):
        """Segment 6: 10 cameras, 2639 correspondences, span/depth 0.043."""
        centres = np.array([[0.0, 0, 0], [0.05, 0, 0], [0.04, 0.01, 0]])
        points = np.random.default_rng(0).normal(0, 2, (200, 3)) + [0, 0, 30.0]
        assert span_over_depth(centres, points) < 0.09

    def test_a_single_camera_has_no_span_at_all(self):
        points = np.random.default_rng(0).normal(0, 1, (10, 3)) + [0, 0, 5.0]
        assert span_over_depth(np.zeros((1, 3)), points) == 0.0


def _synthetic_pair(scale=2.5, seed=0):
    """Two segments viewing one scene, related by a KNOWN Sim3.

    Segment A holds the landmarks and the association; segment B holds the
    cameras. `fit_direction(A, B, ...)` must recover the Sim3 that maps B's
    frame into A's.
    """
    rng = np.random.default_rng(seed)
    K = np.array([[440.0, 0, 180.0], [0, 440.0, 320.0], [0, 0, 1.0]])
    world = rng.normal(0, 1.5, (120, 3)) + np.array([0.0, 0.0, 8.0])

    axis = np.array([0.2, 1.0, -0.3])
    axis = axis / np.linalg.norm(axis)
    angle = 0.4
    kx = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]],
                   [-axis[1], axis[0], 0]])
    R_true = np.eye(3) + np.sin(angle) * kx + (1 - np.cos(angle)) * (kx @ kx)
    t_true = np.array([1.3, -0.7, 2.1])

    # X_A = s R X_B + t, so B's frame holds the inverse-mapped scene.
    points_a = world
    points_b = (R_true.T @ (world - t_true).T).T / scale

    poses_b, keypoints_b = {}, []
    for j in range(5):
        centre = np.array([0.35 * j, 0.04 * j, -0.1 * j])
        R_b = np.eye(3)
        t_b = -R_b @ centre
        poses_b[j] = (R_b, t_b)
        cam = (R_b @ points_b.T).T + t_b
        pix = (K[:2, :2] @ (cam[:, :2] / cam[:, 2:3]).T).T + K[:2, 2]
        keypoints_b.append(pix)

    a = SegmentGeometry(
        index=0, keypoints=[np.zeros((len(world), 2))],
        descriptors=[None], points=points_a, poses={0: (np.eye(3), np.zeros(3))},
        observed={(0, k): k for k in range(len(world))}, intrinsics=K,
    )
    b = SegmentGeometry(
        index=1, keypoints=keypoints_b, descriptors=[None] * 5, points=points_b,
        poses=poses_b, observed={}, intrinsics=K,
    )
    matches = [(0, j, [(k, k) for k in range(len(world))]) for j in range(5)]
    return a, b, matches, scale, R_true, t_true


def _synthetic_world(scale=2.5, seed=1):
    """Two segments that BOTH have geometry, related by a known Sim3.

    The one-sided `_synthetic_pair` gives landmarks to one segment and
    cameras to the other, so only one direction can be solved. Independent
    agreement needs both, which needs both segments fully reconstructed --
    which is also exactly the condition the real walk mostly fails to meet.
    """
    rng = np.random.default_rng(seed)
    K = np.array([[440.0, 0, 180.0], [0, 440.0, 320.0], [0, 0, 1.0]])
    world = rng.normal(0, 1.5, (140, 3)) + np.array([0.0, 0.0, 8.0])

    axis = np.array([0.2, 1.0, -0.3])
    axis = axis / np.linalg.norm(axis)
    angle = 0.4
    kx = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]],
                   [-axis[1], axis[0], 0]])
    R_true = np.eye(3) + np.sin(angle) * kx + (1 - np.cos(angle)) * (kx @ kx)
    t_true = np.array([1.3, -0.7, 2.1])

    points_a = world
    points_b = (R_true.T @ (world - t_true).T).T / scale

    def segment(index, points, step):
        poses, keypoints = {}, []
        for j in range(5):
            centre = np.array([step * j, 0.05 * j, -0.08 * j])
            R = np.eye(3)
            t = -R @ centre
            poses[j] = (R, t)
            cam = (R @ points.T).T + t
            keypoints.append((K[:2, :2] @ (cam[:, :2] / cam[:, 2:3]).T).T + K[:2, 2])
        return SegmentGeometry(
            index=index, keypoints=keypoints, descriptors=[None] * 5,
            points=points, poses=poses,
            observed={(j, k): k for j in range(5) for k in range(len(points))},
            intrinsics=K,
        )

    a = segment(0, points_a, 0.9)
    b = segment(1, points_b, 0.9 / scale)
    pairs = [(k, k) for k in range(len(world))]
    forward = [(i, j, pairs) for i in range(5) for j in range(5)]
    reverse = [(j, i, pairs) for j in range(5) for i in range(5)]
    return a, b, forward, reverse, scale


class TestFitDirection:
    def test_it_recovers_a_known_sim3(self):
        a, b, matches, scale, R_true, t_true = _synthetic_pair(scale=2.5)

        fit = fit_direction(a, b, matches)

        assert fit is not None
        assert fit.scale == pytest.approx(scale, rel=0.05)
        assert fit.reprojection_px < 2.0
        angle = np.degrees(np.arccos(
            np.clip((np.trace(R_true.T @ fit.rotation) - 1) / 2, -1, 1)))
        assert angle < 3.0
        assert np.linalg.norm(fit.translation - t_true) < 0.5 * scale

    def test_two_separate_solves_of_one_pair_agree_and_are_admitted(self):
        """Both directions solved for real, from different cameras.

        This replaces a test that built its reverse as
        `scale=1/forward.scale, rotation=forward.rotation.T` -- an
        algebraic inversion that agrees with itself by construction. It
        passed, which meant the file demonstrated the bypass rather than
        the property.
        """
        a, b, forward_matches, reverse_matches, scale = _synthetic_world(2.5)

        forward = fit_direction(a, b, forward_matches)
        reverse = fit_direction(b, a, reverse_matches)

        assert forward is not None and reverse is not None
        assert forward.provenance != reverse.provenance
        assert forward.scale == pytest.approx(scale, rel=0.05)
        assert reverse.scale == pytest.approx(1.0 / scale, rel=0.05)

        verdict = admit(MutualEvidence(forward=forward, reverse=reverse),
                        Thresholds())

        assert verdict.registered
        assert verdict.reciprocity == pytest.approx(1.0, abs=0.05)

    def test_refinement_resolves_scale_finer_than_the_grid(self):
        """Exercises the free-scale Gauss-Newton, not just the grid seeding.

        The scale grid is 45 log-spaced points over 0.02..50, so adjacent
        candidates differ by ~1.19x. A true scale sitting between two of
        them cannot be recovered to 1% by seeding alone; only the final
        unfixed refinement can close that gap.
        """
        grid = np.exp(np.linspace(np.log(0.02), np.log(50.0), 45))
        below = grid[grid < 3.0].max()
        truth = float(below * 1.19 ** 0.5)          # midway between two points
        assert min(abs(np.log(grid / truth))) > 0.07

        a, b, forward_matches, _, _ = _synthetic_world(truth)
        fit = fit_direction(a, b, forward_matches)

        assert fit is not None
        assert fit.scale == pytest.approx(truth, rel=0.01)

    def test_too_few_cameras_returns_none(self):
        a, b, matches, *_ = _synthetic_pair()
        assert fit_direction(a, b, matches[:1]) is None


class TestComposition:
    def test_the_reference_segment_is_the_identity(self):
        placements = compose_tree([], reference=4)

        assert set(placements) == {4}
        assert placements[4].scale == pytest.approx(1.0)
        assert np.allclose(placements[4].rotation, np.eye(3))
        assert np.allclose(placements[4].translation, 0.0)

    def test_it_composes_along_a_path(self):
        """4 <- 5 <- 32, the real walk's registered subgraph."""
        edges = [
            (4, 5, 0.3533, np.eye(3), np.array([1.0, 0.0, 0.0])),
            (5, 32, 4.1242, np.eye(3), np.array([0.0, 2.0, 0.0])),
        ]

        placements = compose_tree(edges, reference=4)

        assert set(placements) == {4, 5, 32}
        assert placements[5].scale == pytest.approx(0.3533)
        assert placements[32].scale == pytest.approx(0.3533 * 4.1242)

    def test_composition_maps_points_the_same_way_as_applying_edges(self):
        rng = np.random.default_rng(3)
        R1 = np.linalg.qr(rng.normal(size=(3, 3)))[0]
        R2 = np.linalg.qr(rng.normal(size=(3, 3)))[0]
        if np.linalg.det(R1) < 0:
            R1[:, 0] *= -1
        if np.linalg.det(R2) < 0:
            R2[:, 0] *= -1
        s1, s2 = 0.35, 4.12
        t1, t2 = rng.normal(size=3), rng.normal(size=3)
        edges = [(4, 5, s1, R1, t1), (5, 32, s2, R2, t2)]

        placements = compose_tree(edges, reference=4)
        x = rng.normal(size=3)
        step = s1 * (R1 @ (s2 * (R2 @ x) + t2)) + t1

        assert np.allclose(placements[32].apply(x), step)

    def test_a_segment_with_no_path_to_the_reference_is_absent(self):
        placements = compose_tree(
            [(4, 5, 1.0, np.eye(3), np.zeros(3))], reference=4)

        assert 32 not in placements


class TestSupportIsRequired:
    def test_a_world_without_support_json_is_refused(self, derived_world):
        store, world_id, session_id = derived_world

        with pytest.raises(SupportMissingError) as excinfo:
            read_segments(store, world_id, session_id)

        assert "support.json" in str(excinfo.value)
        assert "rebuild" in str(excinfo.value).lower()

    def test_the_cli_refuses_it_cleanly(self, derived_world):
        store, world_id, _ = derived_world

        result = subprocess.run(
            [sys.executable, "scripts/world_registration.py",
             "--root", str(store.root), "--world", world_id],
            capture_output=True, text=True,
        )

        assert result.returncode != 0
        assert "support.json" in (result.stdout + result.stderr)


class TestJsonFormat:
    def test_the_report_round_trips(self):
        report = {
            "world_id": "w0",
            "session_id": "s0",
            "reference_segment": 4,
            "segments": [
                {"segment_index": 4, "registered": True,
                 "transform_to_world": {"rotation_wxyz": [1.0, 0.0, 0.0, 0.0],
                                        "translation": [0.0, 0.0, 0.0],
                                        "scale": 1.0},
                 "reason": "reference segment"},
                {"segment_index": 6, "registered": False,
                 "transform_to_world": None,
                 "reason": "the wearer stood still: span/depth 0.043"},
            ],
        }

        encoded = report_to_json(report)

        assert json.loads(json.dumps(encoded)) == encoded

    def test_registered_stays_a_boolean(self):
        """`bool` subclasses `int`, so a naive encoder writes 1 instead of true.

        `registered` is the field the geometry contract declares as a bool
        and a viewer switches on. An integer there is a silent shape change.
        """
        encoded = report_to_json({
            "segments": [{"segment_index": 4, "registered": True},
                         {"segment_index": 6, "registered": False}],
        })

        assert encoded["segments"][0]["registered"] is True
        assert encoded["segments"][1]["registered"] is False
        assert '"registered": true' in json.dumps(encoded)

    def test_the_cli_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "scripts/world_registration.py", "--help"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0


REAL_WORLD = "3dd986b1c2364d4b85de97152f2e39f4"
REAL_ROOT = Path("data/world_builder")


@pytest.fixture(scope="module")
def report():
    """One registration run, shared by the checks below. ~40 s."""
    store = WorldStore(REAL_ROOT)
    if not store.world_path(REAL_WORLD).exists():
        pytest.skip(f"world {REAL_WORLD} is not on this host")
    session_ids = store.list_session_ids(REAL_WORLD)
    try:
        return register(store, REAL_WORLD, session_ids[0])
    except SupportMissingError as error:
        pytest.skip(str(error))


@pytest.mark.slow
class TestTheRealWalk:
    """The real corpus, end to end. ~45 s; the invariants are the point.

    These deliberately assert RELATIONSHIPS, not frozen totals. The world
    on disk was 51 segments and 12,023 points when this was written, and
    `SupportMissingError` tells the reader to rebuild -- but keyframe
    selection has since changed, so rebuilding from the capture yields a
    different segmentation (33 segments, 8,333 points at the time of
    writing). Pinning the old totals would mean that following the error
    message's own instruction breaks the suite. The headline measurement
    lives in the commit message and the research note, which can carry the
    conditions that produced it; a test cannot.

    Skipped when the corpus is absent, or when the world predates
    support.json.
    """

    def test_the_report_is_internally_consistent(self, report):
        assert report["segments_with_geometry"] <= report["segment_count"]
        assert report["segments_registered"] <= report["segments_with_geometry"]
        assert report["points_registered"] <= report["points_total"]
        assert len(report["segments"]) == report["segment_count"]

    def test_a_segment_with_no_points_is_never_registered(self, report):
        """32 of 51 on the world as built: a lone anchor with no structure.

        Segment 0 is one of them -- the link a prior investigation
        highlighted, real as an image match and unusable as a
        registration, because there is no reconstruction to place.
        """
        barren = [r for r in report["segments"] if r["points"] == 0]

        assert barren, "expected at least one segment with no geometry"
        for row in barren:
            assert not row["registered"]
            assert row["transform_to_world"] is None
            assert "no geometry" in row["reason"]

    def test_every_registered_segment_carries_a_usable_transform(self, report):
        registered = [r for r in report["segments"] if r["registered"]]

        for row in registered:
            transform = row["transform_to_world"]
            assert transform is not None
            assert math.isfinite(transform["scale"]) and transform["scale"] > 0
            assert len(transform["rotation_wxyz"]) == 4
            assert len(transform["translation"]) == 3
            assert row["points"] > 0
            assert row["span_over_depth"] >= 0.09

    def test_every_unregistered_segment_says_why(self, report):
        for row in report["segments"]:
            if not row["registered"]:
                assert row["reason"].strip()
                assert row["transform_to_world"] is None

    def test_the_reference_segment_is_placed_at_the_identity(self, report):
        if report["reference_segment"] is None:
            pytest.skip("nothing registered on this build of the world")
        row = next(r for r in report["segments"]
                   if r["segment_index"] == report["reference_segment"])

        assert row["registered"]
        assert row["transform_to_world"]["scale"] == pytest.approx(1.0)
        assert row["transform_to_world"]["translation"] == [0.0, 0.0, 0.0]

    def test_registration_is_exactly_the_admitted_component(self, report):
        """No segment is placed except by a path of admitted pairs."""
        registered = {r["segment_index"] for r in report["segments"]
                      if r["registered"]}
        admitted = {s for pair in report["admitted_pairs"] for s in pair}

        if not admitted:
            assert not registered
        else:
            assert registered == admitted

    def test_every_admitted_pair_passed_every_clause(self, report):
        admitted = {tuple(p) for p in report["admitted_pairs"]}
        for pair in report["pairs"]:
            if tuple(pair["pair"]) not in admitted:
                continue
            assert pair["registered"]
            assert abs(pair["reciprocity"] - 1.0) <= 0.10
            assert pair["clauses"]["cameras"] >= 3
            assert pair["clauses"]["scale_ambiguity"] <= 3.0
            assert pair["clauses"]["reprojection_px"] <= 3.0
            assert pair["clauses"]["span_over_depth"] >= 0.09

    def test_pairs_whose_directions_disagree_are_never_admitted(self, report):
        """The property, over whatever pairs this build of the world has.

        Stated as a rule rather than as "(5,6) and (30,50) are refused",
        so it keeps its meaning when the segmentation changes underneath.
        """
        disagreeing = [
            p for p in report["pairs"]
            if p["reciprocity"] is not None
            and abs(p["reciprocity"] - 1.0) > 0.10
        ]

        assert disagreeing, "expected some pair whose two solves disagree"
        for pair in disagreeing:
            assert not pair["registered"]

    def test_a_segment_that_stood_still_is_named_as_such(self, report):
        still = [r for r in report["segments"]
                 if r["points"] > 0 and r["span_over_depth"] is not None
                 and r["span_over_depth"] < 0.09]

        for row in still:
            assert not row["registered"]
            assert "stood still" in row["reason"]

    def test_the_json_form_round_trips(self, report):
        encoded = report_to_json(report)

        assert json.loads(json.dumps(encoded)) == encoded


# ---------------------------------------------------------------------------
# Rotation reciprocity.
#
# The gate compared the two directions on ONE quantity: forward.scale *
# reverse.scale. It never compared rotations, so a pair agreeing on scale
# to 1% while disagreeing 40 degrees in rotation was admitted -- folding
# one segment's geometry through another's, which the research note
# records as a real failure class (31.9 to 166.0 degrees observed on
# ill-conditioned pairs before refinement).
#
# HONEST STATUS: measured on the real world 3dd986b1, all six solvable
# pairs agree on rotation to within 2.31 degrees, INCLUDING the dangerous
# (30,50) pair that is 3.2x wrong on scale. This clause therefore changes
# no verdict on the corpus available today. It is a guard against a
# documented catastrophic failure, not a fix for an observed one, and the
# distinction is recorded rather than blurred.
# ---------------------------------------------------------------------------


def _fit_rot(source, target, *, scale, rotation):
    """_fit with an explicit rotation, which the base helper hardcodes to I."""
    import dataclasses as _dc

    return _dc.replace(_fit(source, target, scale=scale), rotation=rotation)


def _rotation_about_z(degrees):
    t = math.radians(degrees)
    return np.array(
        [[math.cos(t), -math.sin(t), 0.0],
         [math.sin(t), math.cos(t), 0.0],
         [0.0, 0.0, 1.0]]
    )


def test_a_pair_agreeing_on_scale_but_not_rotation_is_refused():
    """The hole this clause closes. Scale reciprocity is perfect; the two
    directions disagree by 40 degrees about which way the segment faces."""
    rotation = _rotation_about_z(20.0)
    forward = _fit_rot(0, 1, scale=2.0, rotation=rotation)
    # A correct reverse would be rotation.T. This one is off by 40 deg.
    reverse = _fit_rot(1, 0, scale=0.5, rotation=_rotation_about_z(20.0))
    verdict = admit(MutualEvidence(forward=forward, reverse=reverse), Thresholds())
    assert not verdict.registered
    assert "orientation" in verdict.reason.lower()
    assert verdict.clauses["rotation_disagreement_deg"] == pytest.approx(40.0)
    # And the scale clause would have waved it straight through.
    assert abs(verdict.clauses["reciprocity"] - 1.0) < 1e-9


def test_a_pair_agreeing_on_both_is_admitted():
    """Positive control: the clause must not refuse honest agreement."""
    rotation = _rotation_about_z(20.0)
    forward = _fit_rot(0, 1, scale=2.0, rotation=rotation)
    reverse = _fit_rot(1, 0, scale=0.5, rotation=rotation.T)
    verdict = admit(MutualEvidence(forward=forward, reverse=reverse), Thresholds())
    assert verdict.registered, verdict.reason


def test_the_rotation_bound_separates_measured_good_from_measured_bad():
    """The bound is set from measurement, not taste.

    Measured on world 3dd986b1: the worst rotation disagreement among six
    solvable real pairs is 2.31 deg. The research note records wrong
    rotations at 31.9 to 166.0 deg. The bound sits between, with margin on
    both sides -- roughly 6x above the worst honest pair and 2x below the
    mildest catastrophic one.
    """
    assert 2.31 < Thresholds().max_rotation_disagreement_deg < 31.9


def test_rotation_disagreement_is_reported_even_when_it_passes():
    """A consumer of a registered pair should be able to see HOW well the
    two directions agreed, not just that they cleared the bar."""
    rotation = _rotation_about_z(20.0)
    evidence = MutualEvidence(
        forward=_fit_rot(0, 1, scale=2.0, rotation=rotation),
        reverse=_fit_rot(1, 0, scale=0.5, rotation=rotation.T),
    )
    assert evidence.rotation_disagreement_deg < 1e-6
    verdict = admit(evidence, Thresholds())
    assert "rotation_disagreement_deg" in verdict.clauses
