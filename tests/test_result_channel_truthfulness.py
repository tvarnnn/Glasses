"""Does the wire tell the truth about what World Builder actually did?

Checked against INDEPENDENT truth wherever possible: the numbers the
engine returned, or the files on disk, read separately from the code
under test. A test that asserted the payload matched the producer's own
view of the world would pass for a producer that fabricated everything.
"""

import json

import pytest

from tests.result_channel_fixtures import (  # noqa: F401
    _close_result_channel_clients,
    build_world,
    drain,
    make_client,
    start_live_world,
    subscribe,
)
from tower.results.world_builder import WorldBuilderStatusProducer
from tower.world_builder.store import WorldStore


def _payload(monkeypatch, root, **overrides):
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws, **overrides)
        return drain(ws, expect="cartridge_result")["payload"]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("truth")
    world_id, session_id = build_world(root, frames=10)
    return root, world_id, session_id


# -- the live-session trap ---------------------------------------------


def test_a_live_keyframe_count_comes_from_the_journal_not_session_json(
    monkeypatch, tmp_path
):
    """The single most dangerous fabrication available here.

    session.json is written at start_session with keyframes_accepted=0 and
    is not rewritten until stop_session. So a producer that read the
    obvious field would report ZERO while keyframes were being accepted --
    and zero looks like a measurement, not like a gap.

    Independent truth: the number of lines in keyframes.jsonl, and the
    engine's own in-memory count.
    """
    root = tmp_path / "worlds"
    world_id, session_id, engine = start_live_world(root, frames=10)
    try:
        store = WorldStore(root)
        on_disk = json.loads(
            store.session_path(world_id, session_id).read_text(encoding="utf-8")
        )
        truth = len(store.read_keyframes(world_id, session_id))

        assert on_disk["keyframes_accepted"] == 0, (
            "precondition: session.json really does still hold zero"
        )
        assert truth > 0, "precondition: keyframes really were accepted"

        payload = _payload(monkeypatch, root)
        assert payload["lifecycle"]["state"] == "receiving"
        assert payload["progress"]["keyframes_accepted"] == truth
    finally:
        engine.stop_session()


def test_frames_observed_is_null_while_live_with_its_reason(monkeypatch, tmp_path):
    """Not knowable yet, so not reported. nil and 0 are different claims.

    An ordinary rejected frame writes no journal event -- only a malformed
    one does -- so there is genuinely no live source for this count. A
    producer that reported session.json's zero would be claiming the Tower
    had observed nothing.
    """
    root = tmp_path / "worlds"
    world_id, session_id, engine = start_live_world(root, frames=10)
    try:
        payload = _payload(monkeypatch, root)
        progress = payload["progress"]

        assert progress["frames_observed"] is None
        assert "only known once the session stops" in (
            progress["frames_observed_unavailable_reason"]
        )
        assert progress["rejected_by_reason"] is None
    finally:
        engine.stop_session()


def test_frames_observed_appears_once_the_session_stops(monkeypatch, tmp_path):
    root = tmp_path / "worlds"
    world_id, session_id, engine = start_live_world(root, frames=10)
    summary = engine.stop_session()

    payload = _payload(monkeypatch, root)
    progress = payload["progress"]

    assert progress["frames_observed"] == summary.frames_observed
    assert progress["keyframes_accepted"] == summary.keyframes_accepted
    assert progress["frames_observed_unavailable_reason"] is None


# -- lifecycle ----------------------------------------------------------


def test_a_live_session_is_receiving_on_the_evidence_of_the_lock(
    monkeypatch, tmp_path
):
    """The signal iOS 1.1 asks for: distinct from "frames are arriving".

    The writer lock is held for the lifetime of a mapping session and by
    nothing else, so it answers exactly that question.
    """
    root = tmp_path / "worlds"
    world_id, _, engine = start_live_world(root, frames=6)
    try:
        payload = _payload(monkeypatch, root)
        assert payload["lifecycle"]["state"] == "receiving"
        assert "writer lock" in payload["lifecycle"]["evidence"]
        assert payload["lifecycle"]["build_in_progress"] is False
    finally:
        engine.stop_session()


def test_a_dead_builder_is_reported_as_failed_not_as_receiving(
    monkeypatch, tmp_path
):
    """A stale lock is a real, visible failure and must not read as health.

    Reporting `receiving` forever would be a stale observation presented
    as current state.
    """
    root = tmp_path / "worlds"
    world_id, _, engine = start_live_world(root, frames=6)
    try:
        store = WorldStore(root)
        # A pid that is genuinely not running, found rather than assumed:
        # on Windows pid 0 IS alive (the System Idle Process), so the
        # obvious choice would silently test nothing.
        import psutil

        dead = next(
            pid for pid in range(100_000, 200_000) if not psutil.pid_exists(pid)
        )
        store.lock_path(world_id).write_text(
            json.dumps({"pid": dead}), encoding="utf-8"
        )

        payload = _payload(monkeypatch, root)
        assert payload["lifecycle"]["state"] == "failed"
        assert "no longer running" in payload["lifecycle"]["evidence"]
    finally:
        engine.stop_session()


def test_a_stopped_unbuilt_session_never_claims_a_build_is_running(
    monkeypatch, tmp_path
):
    """`finalizing` would assert something the Tower cannot observe.

    While build() runs, the files are byte-identical to "stopped and never
    built" and to "stopped and the build crashed". So the state is named
    for what is visible, and `build_in_progress` is NULL -- not false,
    which would be a claim that no build is running.
    """
    root = tmp_path / "worlds"
    world_id, session_id, engine = start_live_world(root, frames=8)
    engine.stop_session()

    payload = _payload(monkeypatch, root)
    lifecycle = payload["lifecycle"]

    assert lifecycle["state"] == "stopped_unbuilt"
    assert lifecycle["build_in_progress"] is None
    assert "indistinguishable" in lifecycle["build_in_progress_unavailable_reason"]
    assert payload["geometry"]["available"] is False


def test_a_built_session_is_ready(monkeypatch, built):
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    assert payload["lifecycle"]["state"] == "ready"


# -- geometry and trajectory -------------------------------------------


def test_geometry_matches_the_manifest_the_build_wrote(monkeypatch, built):
    """Independent truth: the manifest on disk, read directly."""
    root, world_id, session_id = built
    manifest = WorldStore(root).read_derived_manifest(world_id)

    payload = _payload(monkeypatch, root)
    geometry = payload["geometry"]

    assert geometry["available"] is True
    assert geometry["element_count"] == manifest["points"]
    assert geometry["backend_id"] == manifest["backend_id"]
    assert geometry["representation"] == "sparse point cloud"
    assert geometry["is_incremental"] is False
    assert geometry["provenance"] == "inferred"


def test_pose_count_is_not_poses_solved_and_not_the_keyframe_count(
    monkeypatch, built
):
    """An anchor has a position and is counted as neither solved nor refused.

    engine.build increments poses_solved only for SOLVED, so reporting it
    as "the number of poses" drops the first keyframe of every segment.
    Reporting the keyframe count instead would claim a position for
    keyframes the backend refused. The trajectory is neither.
    """
    root, world_id, _ = built
    manifest = WorldStore(root).read_derived_manifest(world_id)

    payload = _payload(monkeypatch, root)
    trajectory = payload["trajectory"]

    assert trajectory["pose_count"] == manifest["keyframes"] - manifest["poses_refused"]
    assert trajectory["poses_solved"] == manifest["poses_solved"]
    assert trajectory["pose_count"] >= trajectory["poses_solved"]


def test_no_pose_array_is_sent(monkeypatch, built):
    """IOS-to-Tower.md 1.4 marks a pose array NOT REQUESTED.

    A pose schema needs position, rotation convention, handedness, frame
    and units -- five Tower decisions, each of which renders plausibly and
    wrongly if guessed. Sending a summary is the whole point.
    """
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    encoded = json.dumps(payload)

    # Pose DATA, not the word "pose": `poses_solved` is a count and is
    # exactly what iOS asked for instead of an array.
    for banned in ("translation", "rotation", "quaternion", "wxyz", "xyz"):
        assert banned not in encoded, f"the payload leaked {banned!r}"

    def _no_numeric_arrays(node, path="payload"):
        if isinstance(node, list):
            assert not any(
                isinstance(item, (int, float, list)) for item in node
            ), f"{path} looks like coordinate data"
        elif isinstance(node, dict):
            for key, value in node.items():
                _no_numeric_arrays(value, f"{path}.{key}")

    _no_numeric_arrays(payload)


def test_a_path_length_carries_its_unit_and_scale_semantics(monkeypatch, built):
    """IOS-to-Tower.md 0.5 and 1.5: never a bare number, never metres."""
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    path = payload["trajectory"]["path_length"]

    assert path["available"] is True
    assert path["unit"] == "world units"
    assert path["scale_semantics"] == "relative"
    assert path["provenance"] == "inferred"
    assert "m" != path["display"][-1], "a relative length must not render as metres"
    assert "world units" in path["display"]


def test_a_path_length_is_refused_when_poses_have_gaps(monkeypatch, tmp_path):
    """A refused pose is a HOLE in the path, not a shorter path.

    Summing across it draws a straight line between the keyframes either
    side and calls that distance walked.
    """
    root = tmp_path / "worlds"
    # No intrinsics -> the backend refuses poses, so gaps are guaranteed.
    from tests import synthetic_scene as ss
    from tower.world_builder.engine import WorldBuilderEngine

    engine = WorldBuilderEngine(WorldStore(root))
    world_id = engine.create_world("Uncalibrated")
    session_id = engine.start_session(world_id, frame_source="synthetic")
    scene = ss.furnished_room()
    matrix = ss.camera_matrix(480, 360)
    for index, image in enumerate(
        ss.render_sequence(scene, ss.strafe(8, step=0.09), matrix, 480, 360)
    ):
        engine.observe(ss.encode_jpeg(image), source_seq=index)
    engine.stop_session()
    engine.build(world_id, session_id)

    payload = _payload(monkeypatch, root)
    trajectory = payload["trajectory"]
    if trajectory["available"]:
        path = trajectory["path_length"]
        assert path["available"] is False
        assert "reason" in path


def test_geometry_built_mid_session_is_reported_as_real_but_behind(
    monkeypatch, tmp_path
):
    """The "watch it build" case, and the reason it needed fixing.

    With --rebuild-every, a build finishes and the very next keyframe
    makes its output stale. An earlier version reported anything not
    matching the current keyframes as simply unavailable, so a walk that
    was genuinely producing geometry every few keyframes reported NONE AT
    ALL until it stopped -- the channel hid the exact thing
    --rebuild-every exists to show.

    A build over the first N keyframes is a correct answer to an older
    question, not a wrong answer. It is reported, with `current: false`
    and both counts, so a viewer can show real progress while knowing
    exactly how far behind it is.
    """
    from tests import synthetic_scene as ss
    from tower.world_builder.engine import WorldBuilderEngine
    from tower.world_builder.records import CameraIntrinsics

    root = tmp_path / "worlds"
    matrix = ss.camera_matrix(480, 360)
    engine = WorldBuilderEngine(WorldStore(root))
    world_id = engine.create_world("Growing")
    session_id = engine.start_session(
        world_id,
        intrinsics=CameraIntrinsics(
            source="self_calibrated", model="pinhole",
            fx=float(matrix[0, 0]), fy=float(matrix[1, 1]),
            cx=float(matrix[0, 2]), cy=float(matrix[1, 2]),
            calibrated_width=480, calibrated_height=360,
        ),
        frame_source="synthetic",
        declared_size=(480, 360),
    )
    images = ss.render_sequence(
        ss.furnished_room(), ss.strafe(14, step=0.09), matrix, 480, 360
    )
    accepted = 0
    for index, image in enumerate(images):
        outcome = engine.observe(ss.encode_jpeg(image), source_seq=index)
        if outcome.keyframe_id is not None:
            accepted += 1
            if accepted == 3:
                engine.build(world_id, session_id)
                built_at_keyframes = accepted
    try:
        assert accepted > built_at_keyframes, (
            "precondition: keyframes must have been accepted AFTER the build"
        )
        payload = _payload(monkeypatch, root)
        geometry = payload["geometry"]

        assert geometry["available"] is True, "real geometry must not be hidden"
        assert geometry["current"] is False
        assert geometry["element_count"] > 0
        assert geometry["built_from_keyframes"] == built_at_keyframes
        assert geometry["keyframes_now"] == accepted
        assert geometry["keyframes_now"] > geometry["built_from_keyframes"]
        assert "not the final world" in geometry["stale_reason"]
    finally:
        engine.stop_session()


def test_geometry_and_trajectory_keys_do_not_change_shape(monkeypatch, built):
    """A strict decoder must not choke when a field becomes unavailable.

    Every branch of these two blocks emits the SAME key set; only values
    change. A key that appeared and disappeared would force every consumer
    into optional-chaining for reasons it could not see.
    """
    root, _, _ = built
    available = _payload(monkeypatch, root)
    absent = _payload(monkeypatch, root, world_id="not-a-real-world")

    assert absent["geometry"] is None, "an unresolvable target sends nulls"

    from tower.results.world_builder import (
        _geometry_block,
        _geometry_unavailable,
        _trajectory_unavailable,
    )

    manifest = WorldStore(root).read_derived_manifest(built[1])
    assert set(_geometry_block(manifest, True, 4)) == set(
        _geometry_unavailable("x")
    )
    assert set(available["geometry"]) == set(_geometry_unavailable("x"))
    assert set(available["trajectory"]) == set(_trajectory_unavailable("x"))


# -- scale, calibration, tracking --------------------------------------


def test_scale_is_relative_and_never_licenses_metres(monkeypatch, built):
    """`measured` is unreachable in V1, so no figure may ever be metric."""
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    scale = payload["scale"]

    assert scale["state"] == "relative"
    assert scale["semantics"] == "relative"
    assert scale["allows_metres"] is False
    assert scale["meters_per_unit"] is None
    assert scale["unit"] == "world units"


def test_an_uncalibrated_session_says_so(monkeypatch, tmp_path):
    """Mapped on is_known, not on `source` alone.

    Intrinsics that are present but physically impossible report
    is_known False while source says self_calibrated; mapping on source
    would render a broken calibration as `calibrated`.
    """
    root = tmp_path / "worlds"
    from tower.world_builder.engine import WorldBuilderEngine

    engine = WorldBuilderEngine(WorldStore(root))
    world_id = engine.create_world("No calibration")
    engine.start_session(world_id, frame_source="synthetic")
    try:
        payload = _payload(monkeypatch, root)
        calibration = payload["calibration"]
        assert calibration["state"] == "uncalibrated"
        assert calibration["scope"] == "session"
        assert calibration["calibrating_ever_reported"] is False
    finally:
        engine.stop_session()


def test_a_calibrated_session_says_so(monkeypatch, built):
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    assert payload["calibration"]["state"] == "calibrated"


def test_tracking_never_reports_limited(monkeypatch, built):
    """`limited` would need a threshold nobody has defined.

    The nearest candidate in the code is documented as an untuned
    placeholder, and is not emitted as an event at all -- so it is not
    even available live.
    """
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    tracking = payload["tracking"]

    assert tracking["state"] in ("good", "lost", "unknown")
    assert tracking["state"] != "limited"
    assert tracking["limited_ever_reported"] is False


# -- imagery and privacy ------------------------------------------------


def test_keyframe_imagery_is_reported_present_but_never_fetchable(
    monkeypatch, built
):
    """IOS-to-Tower.md 5: an unstated treatment is not a treatment.

    World Builder keyframes are written with redaction "none" -- raw
    first-person frames. So they are declared, and declared unfetchable,
    and no id or URL is minted. iOS holds no id format, and inventing one
    would be the fabricated contract that document refuses.
    """
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    images = payload["artifacts"]["keyframe_images"]

    assert images["present"] is True
    assert images["count"] > 0
    assert images["redaction"] == "none"
    assert images["fetchable"] is False
    assert "id" not in images and "url" not in images
    assert "no artifact transfer contract exists" in images["reason"]


def test_no_filesystem_path_reaches_the_client(monkeypatch, built):
    """A Tower path is useless to a phone and names a machine's layout."""
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    encoded = json.dumps(payload)

    assert str(root) not in encoded
    assert "C:\\\\" not in encoded and "/tmp/" not in encoded
    assert payload["persistence"]["location_disclosed"] is False


def test_images_purged_is_reported_as_a_declaration_not_a_deletion(
    monkeypatch, built
):
    """The flag deletes nothing; it makes rebuilds refuse.

    Reporting it as "the imagery is gone" would be the false assurance
    06-PRIVACY-DATA forbids.
    """
    root, _, _ = built
    payload = _payload(monkeypatch, root)
    artifacts = payload["artifacts"]

    assert artifacts["images_purged_declared"] is False
    assert artifacts["images_purged_verified"] is None
    assert "not a verified deletion" in artifacts["images_purged_meaning"]


# -- unavailable stays unavailable -------------------------------------


def test_an_absent_world_is_unavailable_with_a_reason(monkeypatch, tmp_path):
    payload = _payload(monkeypatch, tmp_path / "empty")
    assert payload["lifecycle"]["state"] == "unavailable"
    assert payload["world"] is None
    assert payload["geometry"] is None
    assert payload["progress"] is None


def test_naming_a_world_that_does_not_exist_is_unavailable_not_a_guess(
    monkeypatch, built
):
    """Inspection mode must not silently fall back to some other world."""
    root, world_id, _ = built
    payload = _payload(monkeypatch, root, world_id="not-a-real-world")

    assert payload["lifecycle"]["state"] == "unavailable"
    assert "not-a-real-world" in payload["lifecycle"]["reason"]


def test_a_world_with_no_geometry_says_unavailable_never_zero(
    monkeypatch, tmp_path
):
    """"we never built" and "the build found nothing" must not both be 0."""
    root = tmp_path / "worlds"
    world_id, session_id, engine = start_live_world(root, frames=6)
    engine.stop_session()

    payload = _payload(monkeypatch, root)
    geometry = payload["geometry"]

    assert geometry["available"] is False
    assert geometry["element_count"] is None, "a missing count must not be zero"
    assert geometry["representation"] is None
    assert geometry["unavailable_reason"]


def test_geometry_from_another_session_is_not_attributed_to_this_one(
    monkeypatch, tmp_path
):
    """The manifest is per-WORLD but describes one session.

    A world with two built sessions has one manifest, describing whichever
    built last. Attributing it to the other session would report one
    session's geometry as another's.
    """
    root = tmp_path / "worlds"
    world_id, first_session = build_world(root, frames=8, name="Two sessions")

    # A second session in the SAME world, built after the first.
    from tests import synthetic_scene as ss
    from tower.world_builder.engine import WorldBuilderEngine
    from tower.world_builder.records import CameraIntrinsics

    matrix = ss.camera_matrix(480, 360)
    engine = WorldBuilderEngine(WorldStore(root))
    second_session = engine.start_session(
        world_id,
        intrinsics=CameraIntrinsics(
            source="self_calibrated",
            model="pinhole",
            fx=float(matrix[0, 0]),
            fy=float(matrix[1, 1]),
            cx=float(matrix[0, 2]),
            cy=float(matrix[1, 2]),
            calibrated_width=480,
            calibrated_height=360,
        ),
        frame_source="synthetic",
        declared_size=(480, 360),
    )
    for index, image in enumerate(
        ss.render_sequence(ss.furnished_room(), ss.strafe(8, step=0.09), matrix, 480, 360)
    ):
        engine.observe(ss.encode_jpeg(image), source_seq=index)
    engine.stop_session()
    engine.build(world_id, second_session)

    manifest = WorldStore(root).read_derived_manifest(world_id)
    assert manifest["session_id"] == second_session, "precondition"

    first = _payload(monkeypatch, root, world_id=world_id, session_id=first_session)
    second = _payload(monkeypatch, root, world_id=world_id, session_id=second_session)

    assert first["geometry"]["available"] is False
    assert first["geometry"]["element_count"] is None
    assert second["geometry"]["available"] is True
    assert second["geometry"]["element_count"] == manifest["points"]


# -- the producer itself ------------------------------------------------


def test_the_producer_never_reads_an_unchanged_file_twice(built):
    """Stat-gating, which is a measured necessity rather than an optimisation.

    read_events parses the WHOLE journal on every call -- 26.6 ms at 10k
    events against a 1.98 ms average frame reply -- so a poll loop that
    re-read an unchanged file would spend more time parsing than the Tower
    spends answering frames.
    """
    root, world_id, session_id = built
    calls = {"events": 0, "keyframes": 0}
    original_events = WorldStore.read_events
    original_keyframes = WorldStore.read_keyframes

    def _events(self, *args, **kwargs):
        calls["events"] += 1
        return original_events(self, *args, **kwargs)

    def _keyframes(self, *args, **kwargs):
        calls["keyframes"] += 1
        return original_keyframes(self, *args, **kwargs)

    WorldStore.read_events = _events
    WorldStore.read_keyframes = _keyframes
    try:
        producer = WorldBuilderStatusProducer(root, lambda: 0.0)
        producer.snapshot(world_id, session_id)
        first_pass = dict(calls)
        calls["events"] = calls["keyframes"] = 0
        for _ in range(5):
            producer.snapshot(world_id, session_id)
        steady_state = dict(calls)
    finally:
        WorldStore.read_events = original_events
        WorldStore.read_keyframes = original_keyframes

    assert first_pass["events"] == 1
    # Two on the first pass: once for the keyframe digest, and once inside
    # read_derived's own staleness check while the path length is
    # computed. Both are gated afterwards -- what matters is that five
    # further passes over an unchanged world parse nothing at all.
    assert first_pass["keyframes"] == 2
    assert steady_state == {"events": 0, "keyframes": 0}, (
        f"an unchanged world was re-parsed: {steady_state}"
    )
