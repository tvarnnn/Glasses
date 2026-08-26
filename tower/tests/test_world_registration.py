"""Cross-segment registration: the gate, the composition, and the refusals.

The property these tests exist to protect is the one measured in
docs/superpowers/research/2026-08-26-cross-segment-registration.md section 6:
a WRONG Sim3 reprojects beautifully. Segment pair (30,50) on the real walk
fits at 1.62 px with 88% of correspondences under 3 px and is wrong by a
factor of 3.2 in scale. So fit quality cannot be allowed to admit a pair,
and the tests below check that it structurally cannot -- not that some
particular threshold happens to be set high enough today.
"""

import json
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
         scale_ambiguity=1.2, correspondences=400):
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

        verdict = admit(evidence, Thresholds())

        assert not verdict.registered
        assert "scale" in verdict.reason


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
        index=0, keyframe_ids=["a0"], keypoints=[np.zeros((len(world), 2))],
        descriptors=[None], points=points_a, poses={0: (np.eye(3), np.zeros(3))},
        observed={(0, k): k for k in range(len(world))}, intrinsics=K,
    )
    b = SegmentGeometry(
        index=1, keyframe_ids=[f"b{j}" for j in range(5)],
        keypoints=keypoints_b, descriptors=[None] * 5, points=points_b,
        poses=poses_b, observed={}, intrinsics=K,
    )
    matches = [(0, j, [(k, k) for k in range(len(world))]) for j in range(5)]
    return a, b, matches, scale, R_true, t_true


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

    def test_a_recovered_pair_is_admitted_and_agrees_with_itself(self):
        a, b, matches, scale, _, _ = _synthetic_pair(scale=2.5)
        forward = fit_direction(a, b, matches)
        assert forward is not None
        # The synthetic reverse: the exact inverse scale, which is what an
        # independent solve would find if both directions were honest.
        reverse = DirectedFit(
            source=b.index, target=a.index, scale=1.0 / forward.scale,
            rotation=forward.rotation.T, translation=np.zeros(3),
            cameras=forward.cameras, correspondences=forward.correspondences,
            reprojection_px=forward.reprojection_px,
            scale_ambiguity=forward.scale_ambiguity,
        )

        verdict = admit(MutualEvidence(forward=forward, reverse=reverse),
                        Thresholds())

        assert verdict.registered

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
    """The 51-segment walk, end to end. ~45 s; the numbers are the point.

    Skipped when the corpus is absent, because this is a measurement
    against one specific reconstruction rather than a property that holds
    everywhere. It needs a world built AFTER support.json existed.
    """

    def test_only_nineteen_of_fiftyone_segments_have_geometry(self, report):
        assert report["segment_count"] == 51
        assert report["segments_with_geometry"] == 19

    def test_segment_zero_is_refused_for_having_no_geometry(self, report):
        """The prior investigation's flagship link, and it cannot be used.

        Segment 0 matched segments 45, 47, 48 and 50 as IMAGES. It has no
        triangulated point, so there is no reconstruction to place.
        """
        row = next(r for r in report["segments"] if r["segment_index"] == 0)

        assert not row["registered"]
        assert row["points"] == 0
        assert "no geometry" in row["reason"]

    def test_three_segments_register(self, report):
        registered = sorted(
            r["segment_index"] for r in report["segments"] if r["registered"]
        )

        assert registered == [4, 5, 32]
        assert report["admitted_pairs"] == [[4, 5], [5, 32]]

    def test_they_carry_a_third_of_the_reconstructed_points(self, report):
        assert report["points_total"] == 12023
        assert report["points_registered"] == 3739

    def test_the_known_bad_pairs_are_refused_on_disagreement(self, report):
        pairs = {tuple(p["pair"]): p for p in report["pairs"]}

        for pair in ((5, 6), (30, 50)):
            assert not pairs[pair]["registered"]
            assert abs(pairs[pair]["reciprocity"] - 1.0) > 0.10

    def test_standing_still_is_named_as_the_reason(self, report):
        """Segment 6: 1115 points, 10 cameras, and unregisterable."""
        row = next(r for r in report["segments"] if r["segment_index"] == 6)

        assert not row["registered"]
        assert row["span_over_depth"] < 0.09
        assert "stood still" in row["reason"]
