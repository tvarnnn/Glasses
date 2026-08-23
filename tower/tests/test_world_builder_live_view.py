"""Watching a world build while it is still being built.

SYNTHETIC, NOT PHYSICAL.

V1 shipped *Start -> Walk -> Stop -> the world appears*. The product
ruling asks for *the world builds incrementally*, and the gap was never
the storage design -- the append-only journal has always been an
incremental update stream. What was missing was a cursor to read it from
and a driver that consumes frames while they are still arriving.

Neither piece touches the blocked module lifecycle. Both are additive
reads and an offline driver, which is why they could be built now while
production cartridge registration stays stopped at its boundary.
"""

import json

import pytest

from tower.world_builder.engine import WorldBuilderEngine
from tower.world_builder.inspect import WorldView
from tower.world_builder.store import WorldStore
from tests import synthetic_scene as ss


def _walk(count: int, width: int = 160, height: int = 120) -> list[bytes]:
    scene = ss.furnished_room()
    poses = ss.strafe(count, step=0.09)
    images = ss.render_sequence(
        scene, poses, ss.camera_matrix(width, height), width, height
    )
    return [ss.encode_jpeg(image) for image in images]


@pytest.fixture
def store(tmp_path) -> WorldStore:
    return WorldStore(tmp_path)


@pytest.fixture
def session_with_events(store):
    """A session that emitted a known, ordered run of events."""
    engine = WorldBuilderEngine(store)
    world_id = engine.create_world("live")
    session_id = engine.start_session(world_id, frame_source="test")
    jpegs = _walk(4)
    for index, jpeg in enumerate(jpegs):
        engine.observe(jpeg, source_seq=index)
    engine.stop_session()
    return world_id, session_id


class TestEventCursor:
    def test_no_cursor_returns_every_event(self, store, session_with_events):
        world_id, session_id = session_with_events

        events = store.read_events(world_id, session_id)

        assert [event["event_id"] for event in events] == list(range(len(events)))
        assert events[0]["kind"] == "session_started"
        assert events[-1]["kind"] == "session_stopped"

    def test_a_cursor_returns_only_strictly_newer_events(
        self, store, session_with_events
    ):
        world_id, session_id = session_with_events
        everything = store.read_events(world_id, session_id)
        assert len(everything) >= 3

        tail = store.read_events(world_id, session_id, after_event_id=0)

        assert [event["event_id"] for event in tail] == [
            event["event_id"] for event in everything[1:]
        ]

    def test_a_cursor_at_the_end_returns_nothing(self, store, session_with_events):
        world_id, session_id = session_with_events
        everything = store.read_events(world_id, session_id)
        last = everything[-1]["event_id"]

        assert store.read_events(world_id, session_id, after_event_id=last) == []

    def test_a_cursor_beyond_the_end_returns_nothing(
        self, store, session_with_events
    ):
        """A reader that somehow ran ahead must get silence, not a replay."""
        world_id, session_id = session_with_events

        assert store.read_events(world_id, session_id, after_event_id=10_000) == []

    def test_a_record_without_an_event_id_is_skipped_rather_than_replayed(
        self, store, session_with_events
    ):
        """A malformed line must not be handed back on every single poll.

        Without an id there is no way to advance past it, so a cursor
        reader that returned it would return it forever and a live viewer
        would show the same event on a loop.
        """
        world_id, session_id = session_with_events
        path = store.events_path(world_id, session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "keyframe_accepted"}) + "\n")

        tail = store.read_events(world_id, session_id, after_event_id=0)

        assert all("event_id" in event for event in tail)

    def test_events_are_readable_while_the_session_is_still_open(self, store):
        """The whole point: no stop, no build, and the stream already reads.

        Asserted from a SECOND store over the same directory, because a
        live viewer is a different process and must not depend on any
        in-memory state the writer happens to hold.
        """
        engine = WorldBuilderEngine(store)
        world_id = engine.create_world("open")
        session_id = engine.start_session(world_id, frame_source="test")

        reader = WorldStore(store.root)
        assert [event["kind"] for event in reader.read_events(world_id, session_id)] == [
            "session_started"
        ]

        jpegs = _walk(3)
        for index, jpeg in enumerate(jpegs):
            engine.observe(jpeg, source_seq=index)

        during = reader.read_events(world_id, session_id, after_event_id=0)

        assert during, "a session in progress must emit readable events"
        assert not any(event["kind"] == "session_stopped" for event in during)


class TestWorldViewEvents:
    def test_the_view_exposes_the_same_cursor(self, store, session_with_events):
        world_id, session_id = session_with_events
        view = WorldView(store, world_id)

        everything = view.events(session_id)
        tail = view.events(session_id, after_event_id=everything[0]["event_id"])

        assert [event["event_id"] for event in tail] == [
            event["event_id"] for event in everything[1:]
        ]

    def test_the_view_lists_a_session_that_has_not_stopped(self, store):
        """A live viewer must be able to find the session to follow."""
        engine = WorldBuilderEngine(store)
        world_id = engine.create_world("open")
        session_id = engine.start_session(world_id, frame_source="test")

        assert WorldView(WorldStore(store.root), world_id).session_ids() == [
            session_id
        ]
