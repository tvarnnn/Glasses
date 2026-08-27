"""Engine-level behaviour of solve-chain segmentation.

An adversarial review found the entire feature could be reverted with the
suite still green. The only engine-level test asserted that a CLEAN walk
is not split -- which an implementation that never splits at all also
satisfies. These tests assert the mechanism FIRES, and that each guard
around it does its job.

A scripted backend is used rather than real imagery so a break happens
exactly where the test says it does. Real geometry is covered by the
corpus benchmark, which is where the numbers in the commit come from.
"""

import numpy as np

from tower.world_builder.backend import Extension, GeometryEstimate, PoseEstimate
from tower.world_builder.schema import (
    DEGENERACY_LOW_PARALLAX,
    POSE_STATUS_SOLVED,
    POSE_STATUS_UNAVAILABLE,
)


class _Caps:
    backend_id = "scripted"
    version = "1"
    requires_intrinsics = False
    estimates_intrinsics = False
    produces_dense_geometry = False
    produces_metric_scale = False
    preferred_window = 8
    device = "cpu"


class _ScriptedBackend:
    """A backend that breaks its chain on demand.

    `break_at` is a set of 0-based extend() call indices. A broken chain
    latches, exactly as the real one does, so `chain_broken` is an edge.
    """

    capabilities = _Caps()

    def __init__(self, break_at=(), solve_before_break=True):
        self.break_at = set(break_at)
        self.solve_before_break = solve_before_break
        self.calls = 0
        self.broken = False

    def prepare(self, intrinsics):
        pass

    def begin(self, intrinsics):
        self.broken = False

    def reset(self):
        self.broken = False

    def snapshot(self):
        return GeometryEstimate(poses=())

    def estimate_window(self, window):
        return GeometryEstimate(poses=())

    def extend(self, frame):
        index = self.calls
        self.calls += 1
        if self.broken:
            return Extension(
                pose=PoseEstimate(
                    keyframe_id=frame.keyframe_id,
                    status=POSE_STATUS_UNAVAILABLE,
                    degeneracy=DEGENERACY_LOW_PARALLAX,
                ),
                chain_broken=False,
            )
        if index in self.break_at:
            self.broken = True
            return Extension(
                pose=PoseEstimate(
                    keyframe_id=frame.keyframe_id,
                    status=POSE_STATUS_UNAVAILABLE,
                    degeneracy=DEGENERACY_LOW_PARALLAX,
                ),
                chain_broken=True,
            )
        status = (
            POSE_STATUS_SOLVED
            if self.solve_before_break
            else POSE_STATUS_UNAVAILABLE
        )
        return Extension(
            pose=PoseEstimate(
                keyframe_id=frame.keyframe_id,
                status=status,
                rotation=np.eye(3),
                translation=np.zeros(3),
            ),
            chain_broken=False,
        )


def _drive(monkeypatch, tmp_path, backend, frames=14, stop=True):
    """Accept `frames` keyframes through the real engine.

    The keyframe selector is forced to accept everything so segmentation
    is decided ONLY by the backend -- otherwise a tracking loss could
    supply the split and the test would pass without the feature.
    """
    from tests import synthetic_scene as ss
    from tower.world_builder import engine as engine_mod
    from tower.world_builder.keyframes import KeyframeSelector
    from tower.world_builder.records import CameraIntrinsics
    from tower.world_builder.store import WorldStore

    class _Accept:
        outcome = "accept"
        reason = "parallax"
        accepted = True
        lost = False

    monkeypatch.setattr(
        KeyframeSelector, "evaluate", lambda self, quality, motion: _Accept()
    )

    class _Selection:
        def __init__(self, backend):
            self.backend = backend
            self.downgraded_from = None
            self.downgrade_reason = None

    monkeypatch.setattr(
        engine_mod, "select_backend", lambda *a, **k: _Selection(backend)
    )

    width, height = 320, 240
    camera = ss.camera_matrix(width, height)
    images = ss.render_sequence(
        ss.furnished_room(), ss.strafe(frames, step=0.08), camera, width, height
    )
    store = WorldStore(tmp_path)
    engine = engine_mod.WorldBuilderEngine(store)
    world_id = engine.create_world()
    session_id = engine.start_session(
        world_id,
        intrinsics=CameraIntrinsics(
            source="self_calibrated",
            fx=float(camera[0][0]),
            fy=float(camera[1][1]),
            cx=float(camera[0][2]),
            cy=float(camera[1][2]),
            calibrated_width=width,
            calibrated_height=height,
        ),
        frame_source="synthetic",
        declared_size=(width, height),
    )
    for index, image in enumerate(images):
        engine.observe(ss.encode_jpeg(image), source_seq=index)
    tracker_had_reference = (
        engine._tracker is not None and engine._tracker.has_reference
    )
    if stop:
        engine.stop_session()
    keyframes = list(store.read_keyframes(world_id, session_id))
    return engine, [k.segment_index for k in keyframes], tracker_had_reference


def _world_of(engine):
    return engine._session.world_id


def test_the_engine_actually_splits_on_a_chain_break(monkeypatch, tmp_path):
    """KILLS 'disable the whole feature'.

    The previous engine-level test asserted a clean walk is NOT split,
    which an implementation that never splits also satisfies. This one
    fails if the feature is removed.
    """
    backend = _ScriptedBackend(break_at={5})
    _, segments, _had_ref = _drive(monkeypatch, tmp_path, backend)
    assert len(set(segments)) == 2, (
        f"a chain break must open a new segment; got {segments}"
    )
    assert segments[0] == 0
    assert segments[-1] == 1


def test_a_barren_segment_spends_the_restart_budget(monkeypatch, tmp_path):
    """KILLS raising MAX_BARREN_SEGMENTS without limit.

    Nothing is ever solved here, so the first break may restart and the
    second must not: the segment it would abandon produced nothing, which
    is the evidence that the region is unmappable.
    """
    backend = _ScriptedBackend(break_at={2, 6, 9}, solve_before_break=False)
    _, segments, _had_ref = _drive(monkeypatch, tmp_path, backend)
    assert len(set(segments)) == 2, (
        f"a barren run must stop restarting; got {sorted(set(segments))}"
    )


def test_a_productive_segment_clears_the_barren_count(monkeypatch, tmp_path):
    """The other half of the rule: a segment that solved something
    restarts freely, however many times it breaks."""
    backend = _ScriptedBackend(break_at={3, 7, 11}, solve_before_break=True)
    _, segments, _had_ref = _drive(monkeypatch, tmp_path, backend)
    assert len(set(segments)) == 4, (
        f"segments that produce geometry must keep restarting; got "
        f"{sorted(set(segments))}"
    )


def test_a_new_session_does_not_inherit_the_restart_budget(
    monkeypatch, tmp_path
):
    """KILLS 'never reset the counter'.

    start_session resets every other piece of per-session state; leaving
    these behind let a session inherit a budget the previous one earned.
    """
    backend = _ScriptedBackend(break_at={3, 7, 11}, solve_before_break=True)
    engine, _segments, _ref = _drive(monkeypatch, tmp_path, backend)
    # A SECOND session on the same engine is the real guarantee.
    from tower.world_builder.records import CameraIntrinsics

    engine.start_session(
        engine._store.list_world_ids()[0]
        if hasattr(engine._store, "list_world_ids")
        else _world_of(engine),
        intrinsics=CameraIntrinsics(source="unknown"),
        frame_source="synthetic",
    )
    assert engine._segment_solved == 0, (
        "a new session must not inherit solved-pose state"
    )
    assert engine._barren_segments == 0, (
        "a new session must not inherit the restart budget"
    )


def test_the_tracker_reference_survives_a_solve_break(monkeypatch, tmp_path):
    """KILLS 'reset the tracker at the break'.

    Tracking is healthy when the solve fails; discarding its reference
    costs real reconstruction -- an adversarial review measured a genuine
    discard taking the corpus from 424 to 389 solved poses. The engine's
    comment claims this and the claim was inert, so it is asserted.
    """
    backend = _ScriptedBackend(break_at={5})
    engine, segments, had_reference = _drive(monkeypatch, tmp_path, backend)
    assert len(set(segments)) == 2
    assert had_reference, (
        "a solve break must not reset the tracker -- tracking was fine"
    )
