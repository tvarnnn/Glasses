"""Turning detections into observations, with a substitute detector.

`FixedDetector` rather than the real weights, for the same reason
Document Memory's `--ocr none` exists: a default suite that downloaded a
model would fail on a train, and these cases are about the record the
producer writes, not about whether torchvision can find a laptop.

The unit changed since this file was first written. A record used to be
"the first detection of a class, then nothing for thirty seconds". It is
now a SIGHTING -- a run of frames in which a class stayed in view -- and
most of what is asserted below is about that: when it starts, when it
ends, what it accumulates, and what it costs the store.
"""

import cv2
import numpy as np
import pytest

from tower.object_memory.detector import Detection, FixedDetector
from tower.object_memory.engine import ObjectMemoryEngine
from tower.object_memory.records import Confidence, observation_id_for
from tower.object_memory.relevance import RelevancePolicy
from tower.object_memory.store import ObservationStore
from tower.object_memory.verification import ScriptedVerifier, VerificationQueue

WIDTH, HEIGHT = 360, 640


def _frame() -> bytes:
    image = np.full((HEIGHT, WIDTH, 3), 120, np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


def _detection(label="laptop", score=0.81, box=(36.0, 64.0, 180.0, 320.0)):
    return Detection(label=label, score=score, box=box)


def _engine(tmp_path, frames, *, policy=None, clock=None, **kwargs):
    store = ObservationStore(tmp_path, retention_seconds=None)
    engine = ObjectMemoryEngine(
        store,
        FixedDetector(frames),
        policy=policy or RelevancePolicy(),
        clock=clock or (lambda: 1000.0),
        **kwargs,
    )
    engine.load()
    return store, engine


def _walk(engine, count, *, start=900.0, step=0.1, seq=0):
    """Feed `count` frames a tenth of a second apart, as the camera would."""
    for index in range(count):
        engine.observe(
            _frame(),
            received_at=start + index * step,
            source_seq=seq + index,
            relpath=f"frames/{seq + index:08d}.jpg",
        )


# -- the record a sighting produces ------------------------------------


class TestTheRecord:
    def test_a_mature_sighting_becomes_a_persisted_observation(self, tmp_path):
        store, engine = _engine(tmp_path, [[_detection()]], session_id="cap-1")

        _walk(engine, 3, seq=7)

        (observation,) = store.all_observations()
        assert observation.object_class == "laptop"
        assert observation.detector_score == pytest.approx(0.81)
        assert observation.confidence is Confidence.HIGH
        assert observation.session_id == "cap-1"
        assert observation.privacy_tags == ("derived-only", "frame-referenced")
        assert observation.spatial_ref is None

    def test_the_record_is_stamped_with_the_first_frame_of_the_sighting(
        self, tmp_path
    ):
        """`observed_at` means "when it came into view", not "when it was written".

        The record is written on the third frame, and still describes the
        first. Otherwise a sighting's timestamp would depend on the
        maturity threshold, which is a tuning constant.
        """
        store, engine = _engine(tmp_path, [[_detection()]])

        _walk(engine, 5, start=900.0, step=0.1, seq=7)

        (observation,) = store.all_observations()
        assert observation.observed_at == pytest.approx(900.0)
        assert observation.frame_seq == 7

    def test_a_flicker_is_never_written(self, tmp_path):
        """Two frames is a detector twitch, not a sighting.

        264 of the 763 sightings in the real corpus are one or two frames
        long. Writing them would make a third of the memory noise.
        """
        store, engine = _engine(tmp_path, [[_detection()]])

        _walk(engine, 2)

        assert store.all_observations() == []

    def test_the_record_carries_a_stable_handle(self, tmp_path):
        store, engine = _engine(tmp_path, [[_detection()]], session_id="cap-1")

        _walk(engine, 3)

        (observation,) = store.all_observations()
        assert observation.observation_id == observation_id_for(
            "cap-1", "laptop", observation.observed_at
        )
        # Derived, so it survives a reload rather than being reminted.
        assert store.all_observations()[0].observation_id == (
            observation.observation_id
        )

    def test_the_record_names_the_tier_that_admitted_it(self, tmp_path):
        store, engine = _engine(tmp_path, [[_detection()]])

        _walk(engine, 3)

        assert store.all_observations()[0].tier == "remembered"


# -- what a sighting accumulates ---------------------------------------


class TestSightingProgress:
    def test_one_continuous_look_is_one_record_however_long_it_lasts(
        self, tmp_path
    ):
        """The 30-second window's replacement, asserted directly.

        A laptop watched for a minute produced two records under a
        30-second resample window and produces one here, because one
        thing happened.
        """
        store, engine = _engine(tmp_path, [[_detection()]])

        _walk(engine, 600, step=0.1)

        assert len(store.all_observations()) == 1

    def test_a_gap_longer_than_the_window_starts_a_second_sighting(
        self, tmp_path
    ):
        store, engine = _engine(tmp_path, [[_detection()]])

        _walk(engine, 3, start=900.0)
        _walk(engine, 3, start=910.0)

        assert len(store.all_observations()) == 2

    def test_a_gap_shorter_than_the_window_does_not(self, tmp_path):
        """A head turned away and back is one sighting, not two."""
        store, engine = _engine(tmp_path, [[_detection()]])

        _walk(engine, 3, start=900.0)
        _walk(engine, 3, start=902.0)

        assert len(store.all_observations()) == 1

    def test_a_stronger_look_raises_the_best_score_in_place(self, tmp_path):
        store, engine = _engine(
            tmp_path,
            [[_detection(score=0.55)]] * 3 + [[_detection(score=0.97)]],
        )

        _walk(engine, 4)

        (observation,) = store.all_observations()
        assert observation.detector_score == pytest.approx(0.55)
        assert observation.best_score == pytest.approx(0.97)

    def test_a_weaker_look_never_lowers_the_best(self, tmp_path):
        store, engine = _engine(
            tmp_path,
            [[_detection(score=0.97)]] * 3 + [[_detection(score=0.42)]],
        )

        _walk(engine, 4)

        assert store.all_observations()[0].best_score == pytest.approx(0.97)

    def test_confidence_is_reinterpreted_from_the_best_look(self, tmp_path):
        """The field a consumer reads follows the best evidence.

        Not the tautology the resample review warned about: the label
        follows evidence actually observed, so a sighting the detector
        never saw clearly keeps its honest label.
        """
        store, engine = _engine(
            tmp_path,
            [[_detection(score=0.55)]] * 3 + [[_detection(score=0.97)]],
        )

        _walk(engine, 4)

        assert store.all_observations()[0].confidence is Confidence.HIGH

    def test_a_weak_sighting_that_never_improves_stays_weak(self, tmp_path):
        store, engine = _engine(tmp_path, [[_detection(score=0.55)]])

        _walk(engine, 4)

        assert store.all_observations()[0].confidence is Confidence.MEDIUM

    def test_the_ended_sighting_records_how_long_it_lasted(self, tmp_path):
        store, engine = _engine(tmp_path, [[_detection()]])

        _walk(engine, 10, start=900.0, step=0.1)
        engine.finish()

        (observation,) = store.all_observations()
        assert observation.frame_count == 10
        assert observation.last_seen_at == pytest.approx(900.9)

    def test_the_representative_frame_is_the_strongest_look(self, tmp_path):
        """`frame_seq` is the frame the record describes; this is the one to show.

        They are usually different frames, and a person shown the first
        frame of a sighting is being shown the worst view of it.
        """
        store, engine = _engine(
            tmp_path,
            [[_detection(score=0.55)]] * 3 + [[_detection(score=0.99)]],
        )

        _walk(engine, 4, seq=100)
        engine.finish()

        (observation,) = store.all_observations()
        assert observation.frame_seq == 100
        assert observation.best_frame_seq == 103
        assert observation.best_relpath == "frames/00000103.jpg"


# -- what is refused ---------------------------------------------------


class TestRefusals:
    def test_a_person_detection_is_never_persisted(self, tmp_path):
        # The detector still reports it; the producer refuses to write
        # it. See object_memory/classes.py for why that is not
        # squeamishness.
        store, engine = _engine(
            tmp_path, [[_detection(label="person", score=0.99), _detection()]]
        )

        _walk(engine, 3)

        assert [o.object_class for o in store.all_observations()] == ["laptop"]

    def test_a_verify_class_is_not_written_without_a_verifier(self, tmp_path):
        """The behaviour of the Tower that shipped, kept exactly.

        `remote` is a class this cartridge wants and the detector cannot
        name: its three highest-scoring sightings in the real corpus are
        all laptop keyboards.
        """
        store, engine = _engine(tmp_path, [[_detection(label="remote", score=0.9)]])

        _walk(engine, 5)
        engine.finish()

        assert store.all_observations() == []
        assert engine.dropped["unverified"] > 0

    def test_a_context_class_is_counted_under_its_own_reason(self, tmp_path):
        store, engine = _engine(tmp_path, [[_detection(label="bed", score=0.95)]])

        _walk(engine, 3)

        assert store.all_observations() == []
        assert engine.dropped["context-only"] == 3
        assert engine.dropped["not-whitelisted"] == 0

    def test_the_refusal_counters_are_reported_not_discarded(self, tmp_path):
        _, engine = _engine(
            tmp_path,
            [[_detection(label="person"), _detection(label="bed"), _detection()]],
        )

        _walk(engine, 3)

        counters = engine.counters()
        assert counters["declined"]["excluded"] == 3
        assert counters["declined"]["context-only"] == 3
        assert counters["observations_recorded"] == 1


# -- verification ------------------------------------------------------


class TestVerification:
    def _verified(self, tmp_path, frames, agrees_with=()):
        verifier = ScriptedVerifier(agrees_with)
        store = ObservationStore(tmp_path, retention_seconds=None)
        engine = ObjectMemoryEngine(
            store,
            FixedDetector(frames),
            policy=RelevancePolicy(verification_available=True),
            verification=VerificationQueue(verifier, workers=0),
            clock=lambda: 1000.0,
        )
        engine.load()
        return store, engine, verifier

    def test_a_verifier_that_agrees_admits_the_class(self, tmp_path):
        store, engine, _ = self._verified(
            tmp_path, [[_detection(label="remote", score=0.9)]], agrees_with={"remote"}
        )

        _walk(engine, 5)
        engine.finish()

        assert [o.object_class for o in store.all_observations()] == ["remote"]

    def test_a_verifier_that_disagrees_keeps_it_out(self, tmp_path):
        store, engine, _ = self._verified(
            tmp_path, [[_detection(label="remote", score=0.9)]]
        )

        _walk(engine, 5)
        engine.finish()

        assert store.all_observations() == []

    def test_the_verdict_travels_onto_the_record(self, tmp_path):
        """A memory admitted by a model says which model, and how strongly.

        A record that merely said "verified" would be a claim with no way
        to audit it and no way to re-evaluate it when the model changes.
        """
        store, engine, _ = self._verified(
            tmp_path, [[_detection(label="remote", score=0.9)]], agrees_with={"remote"}
        )

        _walk(engine, 5)
        engine.finish()

        verification = store.all_observations()[0].verification
        assert verification["agrees"] is True
        assert verification["model"] == "scripted"

    def test_a_verifier_is_asked_once_per_sighting_not_once_per_frame(
        self, tmp_path
    ):
        """The whole economics of the funnel, asserted.

        The physical run produced 4,287 detections in 150 seconds. A
        semantic model on each of them is not a design; it is the thing
        this structure exists to avoid.
        """
        _, engine, verifier = self._verified(
            tmp_path, [[_detection(label="remote", score=0.9)]]
        )

        _walk(engine, 200)
        engine.finish()

        assert verifier.calls == ["remote"]

    def test_a_remembered_class_is_never_sent_to_the_verifier(self, tmp_path):
        _, engine, verifier = self._verified(tmp_path, [[_detection()]])

        _walk(engine, 20)
        engine.finish()

        assert verifier.calls == []

    def test_a_verifier_that_raises_refuses_rather_than_admits(self, tmp_path):
        """"Said nothing" must resolve the same way as "said no".

        Otherwise a broken model becomes a way to widen the policy.
        """

        class BrokenVerifier:
            name = "broken"

            def load(self):
                return None

            def verify(self, crop, proposed_class):
                raise RuntimeError("no")

            def release(self):
                return None

        store = ObservationStore(tmp_path, retention_seconds=None)
        queue = VerificationQueue(BrokenVerifier(), workers=0)
        engine = ObjectMemoryEngine(
            store,
            FixedDetector([[_detection(label="remote", score=0.9)]]),
            policy=RelevancePolicy(verification_available=True),
            verification=queue,
            clock=lambda: 1000.0,
        )
        engine.load()

        _walk(engine, 5)
        engine.finish()

        assert store.all_observations() == []
        assert queue.failed == 1


# -- cost --------------------------------------------------------------


class TestCost:
    def test_the_store_is_not_rewritten_once_per_frame(self, tmp_path):
        """Every update rewrites the whole JSONL file.

        Refreshing per frame would make the store O(n) per frame for a
        result nobody can observe -- the sighting's end writes the final
        figures regardless.
        """
        store, engine = _engine(tmp_path, [[_detection()]])
        rewrites = []
        original = store.update_sighting
        store.update_sighting = lambda *a, **k: (
            rewrites.append(1) or original(*a, **k)
        )

        _walk(engine, 300, step=0.1)
        engine.finish()

        # 300 frames spanning 30 seconds: three ten-second ticks, plus
        # the close. Nowhere near one per frame.
        assert len(rewrites) <= 8, len(rewrites)

    def test_a_long_session_does_not_accumulate_sightings(self, tmp_path):
        """Rule 15: bounded by construction, not by hope.

        Closed sightings are dropped, and with them the only imagery this
        cartridge ever holds.
        """
        _, engine = _engine(tmp_path, [[_detection()]])

        for block in range(20):
            _walk(engine, 4, start=900.0 + block * 10.0)

        assert len(engine._tracker.open_sightings) <= 1

    def test_a_closed_sighting_releases_its_crop(self, tmp_path):
        store = ObservationStore(tmp_path, retention_seconds=None)
        verifier = ScriptedVerifier()
        engine = ObjectMemoryEngine(
            store,
            FixedDetector([[_detection(label="remote", score=0.9)]]),
            policy=RelevancePolicy(verification_available=True),
            verification=VerificationQueue(verifier, workers=0),
            clock=lambda: 1000.0,
        )
        engine.load()

        _walk(engine, 5)
        held = list(engine._tracker.open_sightings.values())
        assert held and held[0].best_crop is not None
        engine.finish()

        assert held[0].best_crop is None


# -- failure -----------------------------------------------------------


class TestFailure:
    def test_an_undecodable_frame_does_not_end_the_session(self, tmp_path):
        store, engine = _engine(tmp_path, [[_detection()]])

        engine.observe(b"not a jpeg", received_at=900.0, source_seq=0)
        _walk(engine, 3, start=901.0)

        assert engine.frames_undecodable == 1
        assert len(store.all_observations()) == 1

    def test_a_write_that_fails_is_counted_and_retried(self, tmp_path):
        """The producer must not believe it wrote what never reached disk.

        `recorded` stays False, so the next frame retries instead of the
        sighting being silently lost.
        """
        store, engine = _engine(tmp_path, [[_detection()]])
        failures = {"left": 1}

        original = store.append

        def flaky(observation):
            if failures["left"]:
                failures["left"] -= 1
                raise OSError("disk full")
            return original(observation)

        store.append = flaky

        _walk(engine, 5)

        assert engine.write_failures == 1
        assert len(store.all_observations()) == 1


class TestLateVerdicts:
    """A verdict that lands after its sighting ended must still count.

    It cannot happen at the measured rate -- 128 ms verdicts against a
    three-second gap window -- but a verifier on CPU measures 2.5 seconds
    a crop, and that is a supported configuration. "Supported but
    silently lossy" is not a state worth shipping.
    """

    def _threaded(self, tmp_path, delay):
        verifier = ScriptedVerifier({"remote"}, delay_seconds=delay)
        store = ObservationStore(tmp_path, retention_seconds=None)
        engine = ObjectMemoryEngine(
            store,
            FixedDetector([[_detection(label="remote", score=0.9)]]),
            policy=RelevancePolicy(verification_available=True),
            verification=VerificationQueue(verifier, workers=1),
            clock=lambda: 1000.0,
        )
        engine.load()
        return store, engine

    def test_a_sighting_that_ends_mid_verification_is_not_lost(self, tmp_path):
        store, engine = self._threaded(tmp_path, delay=0.4)

        # Three frames to mature it and request a verdict, then a jump
        # past the gap window so the sighting closes while the verifier
        # is still working.
        _walk(engine, 3, start=900.0, step=0.1)
        engine.observe(_frame(), received_at=910.0, source_seq=99)
        engine.finish()

        assert [o.object_class for o in store.all_observations()] == ["remote"]

    def test_a_verdict_that_never_arrives_still_settles_the_sighting(
        self, tmp_path
    ):
        """Parked is not the same as leaked.

        A sighting whose verdict was dropped by a full queue must end up
        refused and counted, not held forever.
        """

        class SilentVerifier:
            name = "silent"

            def load(self):
                return None

            def verify(self, crop, proposed_class):
                raise RuntimeError("never answers")

            def release(self):
                return None

        store = ObservationStore(tmp_path, retention_seconds=None)
        engine = ObjectMemoryEngine(
            store,
            FixedDetector([[_detection(label="remote", score=0.9)]]),
            policy=RelevancePolicy(verification_available=True),
            verification=VerificationQueue(SilentVerifier(), workers=0),
            clock=lambda: 1000.0,
        )
        engine.load()

        _walk(engine, 5)
        engine.finish()

        assert store.all_observations() == []
        assert engine._awaiting_verdict == []


class TestPartsAtTheEndOfASighting:
    """The suppression must survive the sighting it applies to.

    `_settle` runs AFTER the sighting has been removed from the tracker,
    and so has everything that was open beside it -- so a live check at
    that moment saw an empty set, the part-of rule evaporated, and the
    duplicate it exists to prevent was written at the end of every
    sighting. A reviewer reproduced it.
    """

    def _agreed(self, engine):
        for sighting in engine._tracker.open_sightings.values():
            sighting.verdict = {"agrees": True, "model": "scripted"}

    def test_a_keyboard_seen_only_with_a_laptop_is_not_written_at_the_end(
        self, tmp_path
    ):
        store, engine = _engine(
            tmp_path,
            [[_detection(label="laptop"), _detection(label="keyboard", score=0.9)]],
            policy=RelevancePolicy(verification_available=True),
        )

        _walk(engine, 5)
        # Pre-agreed, so verification is not what is under test here.
        self._agreed(engine)
        _walk(engine, 2, start=900.5)
        engine.finish()

        assert [o.object_class for o in store.all_observations()] == ["laptop"]

    def test_a_keyboard_seen_on_its_own_is_still_written_at_the_end(
        self, tmp_path
    ):
        """The reason the rule is concurrent rather than blanket.

        A lit mechanical keyboard at a desk with no laptop near it is a
        real thing to go looking for, and the corpus has one.
        """
        store, engine = _engine(
            tmp_path,
            [[_detection(label="keyboard", score=0.9)]],
            policy=RelevancePolicy(verification_available=True),
        )

        _walk(engine, 5)
        self._agreed(engine)
        _walk(engine, 2, start=900.5)
        engine.finish()

        assert [o.object_class for o in store.all_observations()] == ["keyboard"]
