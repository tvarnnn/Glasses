"""A SceneState must describe the moment it is stamped with, forever.

`SceneState.at` says when the scene was observed and `to_json_dict()`
renders it. Between those two moments, on any live wire path, the engine
keeps running: a publisher polls on its own cadence, and the state it
holds was produced several frames ago.

The tracker's `Track` is a MUTABLE dataclass and `Tracker.update` writes
`box`, `score`, `last_seen_at`, `hits`, `streak`, `misses` and
`is_confirmed` in place. So a state that merely *references* the
tracker's track objects is not a snapshot at all -- it is a live view
wearing a timestamp, and serialising it later emits old scalars beside
new track values.

That is not a hypothetical. Before this file existed, a state stamped
`at: 0.6` with `frames_observed: 3` serialised `hits: 8` and
`age_seconds: 2.1` after five more frames had gone by. Every one of
those numbers is defensible on its own; together they are a scene that
never happened.

There is no test for this in the tracker's own suite because nothing in
the CLI ever held two states at once -- `scripts/scene_session.py` keeps
only the last. The wire path is the first consumer that does.
"""

import numpy as np
import pytest

from tower.scene.detect import FixedDetector
from tower.scene.engine import SceneEngine
from tower.scene.records import BoundingBox, Detection
from tower.scene.tracking import TrackerPolicy

FRAME = np.zeros((360, 640, 3), np.uint8)
POLICY = TrackerPolicy(min_iou=0.25, min_hits=3, max_misses=5)


def _person(box, score=0.9) -> Detection:
    return Detection(label="person", score=score, box=BoundingBox(*box))


def _walk(frames=8, step=0.3):
    """One person drifting right, one state kept per frame."""
    per_frame = [[_person((100 + i * 2, 100, 200 + i * 2, 300))] for i in range(frames)]
    engine = SceneEngine(FixedDetector(per_frame), POLICY, clock=lambda: 0.0)
    engine.load()
    return engine, [engine.observe(FRAME, received_at=i * step) for i in range(frames)]


class TestAStateDoesNotChangeUnderneathItsHolder:
    def test_a_held_state_serialises_the_same_json_twice(self):
        """The single assertion that catches every aliasing route.

        Deliberately compares a state against ITSELF across an interval
        in which the engine ran, rather than against expected values: it
        cannot go stale as the payload grows, and it cannot be satisfied
        by freezing only the fields someone remembered.
        """
        engine, states = _walk()
        early = states[2]
        before = early.to_json_dict()

        for index in range(8, 16):
            engine.observe(FRAME, received_at=index * 0.3)

        assert early.to_json_dict() == before

    def test_a_held_state_does_not_share_track_objects_with_a_later_one(self):
        """Identity, not just equality.

        Equal-looking payloads could still be aliased if the later frames
        happened not to move anything. This pins the structural property
        the payload equality depends on.
        """
        _, states = _walk()

        assert states[2].tracks
        assert states[2].tracks[0] is not states[-1].tracks[0]

    def test_the_hit_count_a_state_reports_matches_the_frame_it_was_taken_on(self):
        """The concrete failure this file was written for.

        A track cannot have been seen more times than the scene has
        observed frames. Aliasing broke exactly that: `frames_observed: 3`
        alongside `hits: 8`.
        """
        _, states = _walk()
        early = states[2]

        payload = early.to_json_dict()
        assert payload["frames_observed"] == 3
        for track in payload["tracks"]:
            assert track["hits"] <= payload["frames_observed"]

    def test_the_track_ids_are_still_the_tracker_s_own(self):
        """Copying must not renumber anything.

        A snapshot that minted fresh ids would break the one thing
        `track_id` is for -- saying "the same blob as last frame" within a
        session -- and would do it invisibly.
        """
        _, states = _walk()

        assert [t.track_id for t in states[2].tracks] == [
            t.track_id for t in states[-1].tracks
        ]


class TestTheSnapshotIsFaithful:
    @pytest.mark.parametrize(
        "field",
        (
            "track_id",
            "label",
            "box",
            "score",
            "first_seen_at",
            "last_seen_at",
            "hits",
            "misses",
            "streak",
            "is_confirmed",
            "facing",
            "facing_estimated_at",
        ),
    )
    def test_every_field_survives_the_copy(self, field):
        """A copy that silently drops a field is worse than an alias.

        Parametrised over the field list rather than asserting a handful,
        so a field added to `Track` and forgotten by the copy fails here
        instead of going missing on the wire.
        """
        engine, states = _walk(frames=6)
        live = engine._tracker.confirmed()
        assert live, "the walk should have confirmed a track"

        snapshot = states[-1].tracks[0]
        assert getattr(snapshot, field) == getattr(live[0], field)
