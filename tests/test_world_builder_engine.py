"""End-to-end engine: create, map, stop, persist, restart, reload, inspect.

SYNTHETIC, NOT PHYSICAL.
"""

import json

import pytest

from tests import synthetic_scene as ss
from tower.object_memory.records import Confidence
from tower.world_builder.backends import BACKEND_CLASSICAL, BACKEND_UNPOSED
from tower.world_builder.engine import (
    ImagesPurgedError,
    SessionNotActiveError,
    WorldBuilderEngine,
)
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.schema import (
    END_REASON_STOP,
    INTRINSICS_SOURCE_SELF_CALIBRATED,
    POSE_STATUS_ANCHOR,
    POSE_STATUS_SOLVED,
    SCALE_RELATIVE,
    SCALE_UNKNOWN,
)
from tower.world_builder.store import WorldStore

WIDTH, HEIGHT = 480, 360


@pytest.fixture(scope="module")
def scene():
    return ss.furnished_room()


@pytest.fixture(scope="module")
def camera_matrix():
    return ss.camera_matrix(WIDTH, HEIGHT)


@pytest.fixture(scope="module")
def intrinsics(camera_matrix):
    return CameraIntrinsics(
        source=INTRINSICS_SOURCE_SELF_CALIBRATED,
        model="pinhole",
        fx=float(camera_matrix[0, 0]),
        fy=float(camera_matrix[1, 1]),
        cx=float(camera_matrix[0, 2]),
        cy=float(camera_matrix[1, 2]),
        calibrated_width=WIDTH,
        calibrated_height=HEIGHT,
    )


@pytest.fixture(scope="module")
def walk_jpegs(scene, camera_matrix):
    """A short sideways walk, encoded exactly as the wire would deliver."""
    poses = ss.strafe(14, step=0.09)
    images = ss.render_sequence(scene, poses, camera_matrix, WIDTH, HEIGHT)
    return [ss.encode_jpeg(image) for image in images]


def _map_session(store, walk_jpegs, intrinsics, backend=BACKEND_CLASSICAL):
    engine = WorldBuilderEngine(store, backend_name=backend)
    world_id = engine.create_world("Test Room")
    session_id = engine.start_session(
        world_id,
        intrinsics=intrinsics,
        frame_source="synthetic",
        declared_size=(WIDTH, HEIGHT),
    )
    for index, payload in enumerate(walk_jpegs):
        engine.observe(payload, source_seq=index * 7, wire_seq=index)
    summary = engine.stop_session(END_REASON_STOP)
    return engine, world_id, session_id, summary


class TestSessionLifecycle:
    def test_a_full_session_produces_keyframes_and_a_clean_stop(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        store = WorldStore(tmp_path)

        _, world_id, session_id, summary = _map_session(
            store, walk_jpegs, intrinsics
        )

        assert summary.frames_observed == len(walk_jpegs)
        assert 1 < summary.keyframes_accepted < len(walk_jpegs)
        assert summary.end_reason == END_REASON_STOP
        session = store.read_session(world_id, session_id)
        assert session.ended_at is not None

    def test_rejections_are_counted_by_reason(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """The histogram is the only tuning instrument before real footage."""
        store = WorldStore(tmp_path)

        _, _, _, summary = _map_session(store, walk_jpegs, intrinsics)

        assert summary.rejected_by_reason
        assert sum(summary.rejected_by_reason.values()) + summary.keyframes_accepted == (
            summary.frames_observed
        )

    def test_observe_without_a_session_is_refused(self, tmp_path):
        engine = WorldBuilderEngine(WorldStore(tmp_path))

        with pytest.raises(SessionNotActiveError):
            engine.observe(b"x", source_seq=0)

    def test_a_malformed_frame_does_not_end_the_session(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """One bad frame is frame-scoped, never session-scoped."""
        store = WorldStore(tmp_path)
        engine = WorldBuilderEngine(store)
        world_id = engine.create_world()
        engine.start_session(world_id, intrinsics=intrinsics)

        engine.observe(walk_jpegs[0], source_seq=0)
        bad = engine.observe(b"definitely not a jpeg", source_seq=1)
        good = engine.observe(walk_jpegs[5], source_seq=2)

        assert bad.reason == "malformed_frame"
        assert good.frames_observed == 3
        engine.stop_session()

    def test_the_writer_lock_is_released_on_stop(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        store = WorldStore(tmp_path)

        _, world_id, _, _ = _map_session(store, walk_jpegs, intrinsics)

        assert not store.lock_path(world_id).exists()

    def test_keyframe_images_are_written_next_to_their_journal(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        store = WorldStore(tmp_path)

        _, world_id, session_id, _ = _map_session(store, walk_jpegs, intrinsics)

        keyframes = store.read_keyframes(world_id, session_id)
        session_dir = store.session_dir(world_id, session_id)
        for keyframe in keyframes:
            assert (session_dir / keyframe.image_relpath).exists()

    def test_events_are_journalled_with_dense_ids(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """A gap in event_id means a real drop, not a skipped number."""
        store = WorldStore(tmp_path)

        _, world_id, session_id, _ = _map_session(store, walk_jpegs, intrinsics)

        events = store.read_events(world_id, session_id)
        assert [event["event_id"] for event in events] == list(range(len(events)))
        assert events[0]["kind"] == "session_started"
        assert events[-1]["kind"] == "session_stopped"

    def test_the_journal_is_the_incremental_update_stream(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """Updates are exposed as they happen, not only at stop."""
        store = WorldStore(tmp_path)
        engine = WorldBuilderEngine(store)
        world_id = engine.create_world()
        session_id = engine.start_session(world_id, intrinsics=intrinsics)

        for index, payload in enumerate(walk_jpegs[:6]):
            engine.observe(payload, source_seq=index * 7)
            # Readable mid-session, from the same process or another one.
            assert store.read_events(world_id, session_id)

        engine.stop_session()


class TestBuildAndReload:
    def test_build_produces_poses_and_points(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )

        result = engine.build(world_id, session_id)

        assert result.poses_solved >= 1
        assert result.points > 100
        assert result.backend_id == "classical-sfm"

    def test_a_solved_build_declares_relative_scale_never_metric(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """Internally consistent, arbitrary unit. Not a metre."""
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )

        result = engine.build(world_id, session_id)

        assert result.scale_state == SCALE_RELATIVE
        world = store.read_world(world_id)
        assert world.scale.meters_per_unit is None
        assert not world.scale.allows_metres

    def test_an_uncalibrated_build_yields_no_poses_and_unknown_scale(
        self, tmp_path, walk_jpegs
    ):
        """The honest real-Ray-Ban path today."""
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, CameraIntrinsics.unknown(), backend=BACKEND_UNPOSED
        )

        result = engine.build(world_id, session_id)

        assert result.poses_solved == 0
        assert result.points == 0
        assert result.scale_state == SCALE_UNKNOWN

    def test_a_downgrade_is_recorded_on_the_session(
        self, tmp_path, walk_jpegs
    ):
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, CameraIntrinsics.unknown(), backend=BACKEND_CLASSICAL
        )

        engine.build(world_id, session_id)

        session = store.read_session(world_id, session_id)
        assert session.backend_downgraded_from == BACKEND_CLASSICAL
        assert "intrinsics" in session.backend_downgrade_reason

    def test_edges_record_measurements_even_when_a_pose_is_refused(
        self, tmp_path, walk_jpegs
    ):
        """An empty map that explains itself beats one that does not."""
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, CameraIntrinsics.unknown(), backend=BACKEND_UNPOSED
        )

        engine.build(world_id, session_id)

        edges = store.read_edges(world_id, session_id)
        assert edges
        assert all(edge.pose_status != POSE_STATUS_SOLVED for edge in edges)
        assert any(edge.matches > 0 for edge in edges)

    def test_a_world_survives_process_restart_and_reloads(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """The definition-of-done item that everything else serves."""
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )
        engine.build(world_id, session_id)

        # Simulate a cold process: brand-new store over the same directory.
        reloaded = WorldStore(tmp_path)
        world = reloaded.read_world(world_id)
        keyframes = reloaded.read_keyframes(world_id, session_id)
        derived = reloaded.read_derived(world_id, session_id)

        assert world.world_id == world_id
        assert len(keyframes) > 1
        assert derived is not None
        assert len(derived["poses"]) == len(keyframes)
        assert len(derived["points"]) > 100

    def test_the_first_pose_is_the_anchor(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )
        engine.build(world_id, session_id)

        poses = store.read_derived(world_id, session_id)["poses"]

        assert poses[0]["status"] == POSE_STATUS_ANCHOR
        assert poses[0]["translation"] == [0.0, 0.0, 0.0]

    def test_deleting_derived_leaves_the_world_valid_and_rebuildable(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """The authoritative/derived split, enforced rather than asserted."""
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )
        first = engine.build(world_id, session_id)

        store.clear_derived(world_id)
        assert store.read_derived(world_id, session_id) is None

        second = engine.build(world_id, session_id)

        assert store.read_world(world_id).world_id == world_id
        assert second.keyframes == first.keyframes
        assert second.poses_solved == first.poses_solved

    def test_the_manifest_records_the_input_digest(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """Staleness is detected rather than trusted."""
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )
        engine.build(world_id, session_id)

        manifest = store.read_derived_manifest(world_id)

        assert manifest["input_digest"]
        assert store.derived_is_current(world_id, manifest["input_digest"])
        assert not store.derived_is_current(world_id, "some-other-digest")

    def test_rebuilding_a_purged_world_fails_loudly(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """Silently returning nothing would read as a mapping failure
        rather than the consequence of a deliberate privacy action."""
        from dataclasses import replace

        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )
        store.write_world(replace(store.read_world(world_id), images_purged=True))

        with pytest.raises(ImagesPurgedError):
            engine.build(world_id, session_id)


class TestPrivacyPosture:
    def test_a_session_truthfully_declares_that_it_retains_imagery(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """Unlike every module shipped so far, which declares False."""
        store = WorldStore(tmp_path)
        _, world_id, session_id, _ = _map_session(store, walk_jpegs, intrinsics)

        session = store.read_session(world_id, session_id)

        assert session.retains_raw_imagery is True
        assert "raw-imagery" in session.privacy_tags

    def test_redaction_provenance_is_recorded_as_none(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        """The un-retrofittable half of any future redaction work.

        Without this field, the day redaction ships there is no way to
        tell whether an older session's images were filtered, so every
        historical session must be assumed unredacted forever.
        """
        store = WorldStore(tmp_path)
        _, world_id, session_id, _ = _map_session(store, walk_jpegs, intrinsics)

        session = store.read_session(world_id, session_id)
        raw = json.loads(store.session_path(world_id, session_id).read_text())

        assert session.redaction == "none"
        assert raw["redaction"] == "none"

    def test_purging_a_world_removes_every_keyframe_image(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        store = WorldStore(tmp_path)
        _, world_id, session_id, _ = _map_session(store, walk_jpegs, intrinsics)
        assert list(store.images_dir(world_id, session_id).glob("*.jpg"))

        report = store.purge_world(world_id)

        assert report.complete
        assert not store.world_dir(world_id).exists()


class TestStorageObservability:
    """Growth must be observable even though it is not capped.

    A hard cap that stopped mapping mid-session would trade a storage
    problem for a silently truncated world, which is worse -- an
    incomplete map with no sign it was cut short.
    """

    def test_world_bytes_reports_by_tier(self, tmp_path, walk_jpegs, intrinsics):
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )
        engine.build(world_id, session_id)

        totals = store.world_bytes(world_id)

        assert totals["images"] > 0
        assert totals["journals"] > 0
        assert totals["derived"] > 0
        assert totals["total"] >= (
            totals["images"] + totals["journals"] + totals["derived"]
        )

    def test_the_derived_tier_is_the_reclaimable_half(
        self, tmp_path, walk_jpegs, intrinsics
    ):
        store = WorldStore(tmp_path)
        engine, world_id, session_id, _ = _map_session(
            store, walk_jpegs, intrinsics
        )
        engine.build(world_id, session_id)
        before = store.world_bytes(world_id)

        store.clear_derived(world_id)
        after = store.world_bytes(world_id)

        assert after["derived"] == 0
        assert after["images"] == before["images"]
        assert after["total"] < before["total"]

    def test_a_missing_world_reports_zero_rather_than_raising(self, tmp_path):
        assert WorldStore(tmp_path).world_bytes("nope")["total"] == 0
