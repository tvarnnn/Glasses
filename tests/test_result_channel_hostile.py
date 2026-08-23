"""Corrupt, truncated and impossible world state on the wire.

The question every one of these asks is the same: when the data on disk is
broken, does the channel say so, or does it produce a confident wrong
answer? A crash is an acceptable answer here only if it is contained; a
plausible number is never one.
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
from tower.world_builder.store import WorldStore


def _payload(monkeypatch, root, **overrides):
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        reply = subscribe(ws, **overrides)
        if reply["type"] != "result_subscribed":
            return reply
        return drain(ws, expect="cartridge_result")["payload"]


@pytest.fixture
def world(tmp_path):
    root = tmp_path / "worlds"
    world_id, session_id = build_world(root, frames=10)
    return root, world_id, session_id


def _assert_no_fabrication(payload):
    """Whatever else happened, nothing may claim geometry it does not have."""
    if payload.get("geometry") is None:
        return
    geometry = payload["geometry"]
    if not geometry["available"]:
        assert geometry["element_count"] is None, "an absent count must not be 0"
        assert geometry["representation"] is None
    trajectory = payload.get("trajectory") or {}
    if trajectory and not trajectory.get("available"):
        assert trajectory["pose_count"] is None
        assert trajectory["path_length"] is None


def test_a_torn_last_journal_line_is_survived(monkeypatch, world):
    """A journal is appended without fsync, so a reader can arrive mid-line.

    The torn record is skipped, not treated as corruption -- the next poll
    sees it whole.
    """
    root, world_id, session_id = world
    events = WorldStore(root).events_path(world_id, session_id)
    events.write_text(
        events.read_text(encoding="utf-8") + '{"schema_version": 1, "kin',
        encoding="utf-8",
    )

    payload = _payload(monkeypatch, root)
    assert payload["lifecycle"]["state"] in ("ready", "stopped_unbuilt", "idle")
    assert payload["progress"]["keyframes_accepted"] >= 0
    _assert_no_fabrication(payload)


def test_a_truncated_keyframe_journal_does_not_fabricate_geometry(
    monkeypatch, world
):
    """Fewer keyframes than the build consumed must not read as "current".

    The digest changes, so the geometry is correctly reported as behind
    rather than as describing the truncated set.
    """
    root, world_id, session_id = world
    keyframes = WorldStore(root).keyframes_path(world_id, session_id)
    lines = keyframes.read_text(encoding="utf-8").splitlines()
    keyframes.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    payload = _payload(monkeypatch, root)
    geometry = payload["geometry"]
    assert geometry["current"] is False, (
        "geometry built from more keyframes than exist must not read as current"
    )
    _assert_no_fabrication(payload)


def test_a_manifest_from_another_schema_is_refused(monkeypatch, world):
    root, world_id, _ = world
    store = WorldStore(root)
    path = store.derived_manifest_path(world_id)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 999
    path.write_text(json.dumps(manifest), encoding="utf-8")

    payload = _payload(monkeypatch, root)
    assert payload["geometry"]["available"] is False
    _assert_no_fabrication(payload)


def test_a_manifest_missing_keys_is_not_evidence_of_geometry(monkeypatch, world):
    """A manifest that carries no figures does not mean "we have geometry".

    Gating on "the file exists" produced `available: true` with every
    figure null -- a claim asserted with nothing to show for it -- and a
    refusal sentence reading "None of this session's poses were refused,
    so the path has gaps". Both found by adversarial review.
    """
    root, world_id, _ = world
    store = WorldStore(root)
    path = store.derived_manifest_path(world_id)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for key in ("points", "poses_solved", "poses_refused", "keyframes", "segments"):
        manifest.pop(key, None)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    payload = _payload(monkeypatch, root)
    geometry = payload["geometry"]
    trajectory = payload["trajectory"]

    assert geometry["available"] is False, (
        "a manifest with no figures must not assert geometry"
    )
    assert geometry["element_count"] is None
    assert geometry["representation"] is None
    assert trajectory["available"] is False
    assert trajectory["pose_count"] is None
    assert trajectory["path_length"] is None
    # And the scale it never earned is not attributed to it either.
    assert payload["scale"]["state"] == "unknown"
    assert payload["scale"]["unit"] is None


def test_an_unreadable_manifest_is_survived(monkeypatch, world):
    root, world_id, _ = world
    WorldStore(root).derived_manifest_path(world_id).write_text(
        "{not json at all", encoding="utf-8"
    )

    payload = _payload(monkeypatch, root)
    assert payload["geometry"]["available"] is False
    _assert_no_fabrication(payload)


def test_an_unknown_pose_convention_is_refused_not_guessed(monkeypatch, world):
    """A bare [x, y, z] under the wrong convention is plausible and wrong.

    The store refuses rather than interpreting; the channel must turn that
    refusal into an honest `unavailable`, not a crash and not a guess.
    """
    root, world_id, _ = world
    store = WorldStore(root)
    path = store.world_path(world_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pose_convention"]["pose_type"] = "T_camera_world"
    path.write_text(json.dumps(data), encoding="utf-8")

    # Both selection paths, because they refuse in different places.
    # Auto-selection skips a world it cannot read and finds nothing left;
    # naming it explicitly carries the store's own refusal outward. Either
    # way the answer is `unavailable` and no coordinate is interpreted.
    auto = _payload(monkeypatch, root)
    assert auto["lifecycle"]["state"] == "unavailable"
    assert auto["world"] is None
    assert auto["lifecycle"]["reason"] == "no world could be read"

    named = _payload(monkeypatch, root, world_id=world_id)
    assert named["lifecycle"]["state"] == "unavailable"
    assert named["world"] is None
    assert "could not be read" in named["lifecycle"]["reason"]
    assert "pose convention" in named["lifecycle"]["reason"]


def test_an_unknown_world_schema_is_refused(monkeypatch, world):
    root, world_id, _ = world
    path = WorldStore(root).world_path(world_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")

    payload = _payload(monkeypatch, root)
    assert payload["lifecycle"]["state"] == "unavailable"


@pytest.mark.parametrize(
    "lock_body",
    ["not json", '{"pid": "seventeen"}', '{"pid": null}', "{}", ""],
)
def test_a_garbage_lock_file_never_claims_a_live_session(
    monkeypatch, world, lock_body
):
    """An unreadable lock means "no evidence of a live writer", not "live".

    Reporting `receiving` from a lock nobody can parse would be a stale
    observation presented as current state.
    """
    root, world_id, _ = world
    WorldStore(root).lock_path(world_id).write_text(lock_body, encoding="utf-8")

    payload = _payload(monkeypatch, root)
    assert payload["lifecycle"]["state"] != "receiving"
    _assert_no_fabrication(payload)


def test_impossible_intrinsics_are_not_reported_as_calibrated(
    monkeypatch, tmp_path
):
    """fx=0 satisfies "is not None" and is not a camera.

    Mapping calibration state on `source` alone would render a broken
    calibration as `calibrated`.
    """
    root = tmp_path / "worlds"
    world_id, session_id, engine = start_live_world(root, frames=6)
    engine.stop_session()

    store = WorldStore(root)
    path = store.session_path(world_id, session_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["intrinsics"]["fx"] = 0.0
    path.write_text(json.dumps(data), encoding="utf-8")

    payload = _payload(monkeypatch, root)
    assert payload["calibration"]["state"] != "calibrated"


def test_a_backward_clock_never_produces_a_negative_mapping_time(
    monkeypatch, tmp_path
):
    """An NTP step backwards must not make a session look un-started."""
    root = tmp_path / "worlds"
    world_id, session_id, engine = start_live_world(root, frames=6)
    try:
        store = WorldStore(root)
        path = store.session_path(world_id, session_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["started_at"] = data["started_at"] + 10_000.0
        path.write_text(json.dumps(data), encoding="utf-8")

        payload = _payload(monkeypatch, root)
        progress = payload["progress"]
        # UNKNOWN, not clamped to zero. A session mapping for five minutes
        # must not become indistinguishable from one that just started --
        # and because this field is excluded from the revision, a
        # plausible zero would arrive with `revision_changed: false`,
        # telling the client to skip the redraw.
        assert progress["mapping_seconds"] is None
        assert "backwards" in progress["mapping_seconds_unavailable_reason"]
    finally:
        engine.stop_session()


def test_a_world_directory_with_no_session_files_is_idle_not_broken(
    monkeypatch, tmp_path
):
    root = tmp_path / "worlds"
    from tower.world_builder.engine import WorldBuilderEngine

    engine = WorldBuilderEngine(WorldStore(root))
    engine.create_world("Empty")

    payload = _payload(monkeypatch, root)
    assert payload["lifecycle"]["state"] == "idle"
    assert payload["session"] is None
    _assert_no_fabrication(payload)


def test_a_hostile_world_id_cannot_escape_the_world_root(monkeypatch, world):
    """A path-traversal attempt must be refused by the id check, not the OS."""
    root, _, _ = world
    for hostile in ("../../etc/passwd", "..\\..\\windows", "a/b/c", ""):
        payload = _payload(monkeypatch, root, world_id=hostile)
        assert payload["lifecycle"]["state"] == "unavailable"


def test_the_channel_survives_the_world_vanishing_mid_subscription(
    monkeypatch, world
):
    """Files can be deleted while a subscriber is watching.

    Deliberately NOT via `shutil.rmtree(ignore_errors=True)`: on Windows
    that partially succeeds against open handles, so the world survives in
    pieces and the outcome depends on which files happened to go. An
    earlier version of this test used it and passed or failed by luck.
    Unlinking `world.json` is deterministic and is the stronger case
    anyway -- the world becomes unreadable while the subscription is live.
    """
    from tests.result_channel_fixtures import pump

    root, world_id, _ = world
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        first = drain(ws, expect="cartridge_result")
        assert first["payload"]["lifecycle"]["state"] == "ready"

        WorldStore(root).world_path(world_id).unlink()

        pump(client)
        later = drain(ws, expect="cartridge_result")

    assert later["payload"]["lifecycle"]["state"] == "unavailable"
    assert later["payload"]["world"] is None
    _assert_no_fabrication(later["payload"])
    assert later["seq"] == 2, "the subscription survives and keeps its sequence"


def test_a_partially_deleted_world_reports_honestly_and_does_not_crash(
    monkeypatch, world
):
    """Deleting only the derived tree must degrade, not fabricate.

    This is the state a purge or an interrupted rebuild leaves behind: the
    journals survive and the geometry does not.
    """
    import shutil

    from tests.result_channel_fixtures import pump

    root, world_id, _ = world
    shutil.rmtree(WorldStore(root).derived_dir(world_id), ignore_errors=True)

    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        payload = drain(ws, expect="cartridge_result")["payload"]
        pump(client)
        drain(ws, expect="cartridge_result")

    assert payload["lifecycle"]["state"] == "stopped_unbuilt"
    assert payload["geometry"]["available"] is False
    assert payload["progress"]["keyframes_accepted"] > 0, (
        "the journals survived, so the counts must too"
    )
    _assert_no_fabrication(payload)
