"""The semantic stage: bounded, off the frame path, and unable to widen policy.

Three properties are worth more than the rest and each has a test that
fails loudly without it:

  * the backlog is BOUNDED, and a full one drops rather than grows. An
    unbounded queue on a fifteen-minute walk is a memory leak with a
    model attached to it.
  * a verifier that raises REFUSES. "Said nothing" and "said no" must
    resolve the same way, or a broken model becomes a way to widen the
    policy.
  * the counters are real. A funnel whose narrowing is not measured is a
    funnel that has quietly stopped narrowing.
"""

import threading
import time

import pytest

from tower.object_memory.sightings import (
    GAP_SECONDS,
    MIN_FRAMES,
    Look,
    SightingTracker,
    summarise,
)
from tower.object_memory.verification import (
    RefusingVerifier,
    ScriptedVerifier,
    VerificationQueue,
    Verdict,
    Verifier,
)


def _look(score=0.9, at=100.0, seq=1):
    return Look(score=score, box=(0.1, 0.1, 0.4, 0.4), at=at, frame_seq=seq)


class _Sighting:
    """The smallest thing the queue actually touches."""

    def __init__(self, object_class="remote"):
        self.object_class = object_class


# -- the sighting tracker ----------------------------------------------


class TestSightingTracker:
    def test_consecutive_frames_are_one_sighting(self):
        tracker = SightingTracker()

        first, opened_a = tracker.observe("laptop", _look(at=100.0))
        second, opened_b = tracker.observe("laptop", _look(at=100.1))

        assert opened_a is True
        assert opened_b is False
        assert first is second
        assert second.frame_count == 2

    def test_a_gap_longer_than_the_window_starts_a_new_sighting(self):
        tracker = SightingTracker()

        tracker.observe("laptop", _look(at=100.0))
        _, opened = tracker.observe("laptop", _look(at=100.0 + GAP_SECONDS + 0.01))

        assert opened is True

    def test_a_gap_exactly_at_the_window_does_not(self):
        """The boundary, pinned, because a strict inequality here would
        turn a head-turn of exactly the grace length into two memories."""
        tracker = SightingTracker()

        tracker.observe("laptop", _look(at=100.0))
        _, opened = tracker.observe("laptop", _look(at=100.0 + GAP_SECONDS))

        assert opened is False

    def test_two_classes_are_tracked_independently(self):
        tracker = SightingTracker()

        tracker.observe("laptop", _look(at=100.0))
        tracker.observe("cell phone", _look(at=100.0))

        assert set(tracker.open_sightings) == {"laptop", "cell phone"}

    def test_the_best_look_is_the_strongest_one(self):
        tracker = SightingTracker()

        tracker.observe("laptop", _look(score=0.6, at=100.0, seq=1))
        sighting, _ = tracker.observe("laptop", _look(score=0.95, at=100.1, seq=2))
        tracker.observe("laptop", _look(score=0.7, at=100.2, seq=3))

        assert sighting.best.score == pytest.approx(0.95)
        assert sighting.best.frame_seq == 2
        assert sighting.first.frame_seq == 1
        assert sighting.last.frame_seq == 3

    def test_the_crop_moves_with_the_look_it_belongs_to(self):
        """Cropping the current frame with the best frame's box would hand
        a model a picture of something else entirely."""
        tracker = SightingTracker()

        tracker.observe("remote", _look(score=0.6, at=100.0), crop="weak")
        sighting, _ = tracker.observe("remote", _look(score=0.9, at=100.1), crop="strong")
        tracker.observe("remote", _look(score=0.7, at=100.2), crop="middling")

        assert sighting.best_crop == "strong"

    def test_closing_stale_uses_the_callers_clock(self):
        """A replay must close sightings at the times the RECORDING
        implies, not at the times the replay happens to run."""
        tracker = SightingTracker()
        tracker.observe("laptop", _look(at=100.0))

        assert tracker.close_stale(100.5) == []
        stale = tracker.close_stale(100.0 + GAP_SECONDS + 0.01)

        assert [s.object_class for s in stale] == ["laptop"]
        assert stale[0].closed is True
        assert tracker.open_sightings == {}

    def test_close_all_ends_the_session(self):
        tracker = SightingTracker()
        tracker.observe("laptop", _look())
        tracker.observe("cell phone", _look())

        assert len(tracker.close_all()) == 2
        assert tracker.open_sightings == {}

    def test_maturity_is_the_measured_threshold(self):
        tracker = SightingTracker()
        sighting = None
        for index in range(MIN_FRAMES):
            sighting, _ = tracker.observe("laptop", _look(at=100.0 + index * 0.1))

        assert sighting.mature is True

    def test_a_summary_says_what_happened_and_nothing_more(self):
        tracker = SightingTracker()
        tracker.observe("laptop", _look(score=0.6, at=100.0))
        sighting, _ = tracker.observe("laptop", _look(score=0.9, at=102.0))

        summary = summarise(sighting)

        assert summary["frame_count"] == 2
        assert summary["duration_seconds"] == pytest.approx(2.0)
        assert summary["best_score"] == pytest.approx(0.9)
        assert summary["first_score"] == pytest.approx(0.6)


# -- the verifiers themselves ------------------------------------------


class TestVerifiers:
    def test_the_default_verifier_agrees_with_nothing(self):
        verdict = RefusingVerifier().verify(None, "remote")

        assert verdict.agrees is False
        assert verdict.reason == "no-verifier-configured"

    def test_a_refusal_is_not_silence(self):
        """The reason travels, so a record's absence is explicable."""
        assert RefusingVerifier().verify(None, "remote").model == "none"

    def test_both_stand_ins_satisfy_the_protocol(self):
        assert isinstance(RefusingVerifier(), Verifier)
        assert isinstance(ScriptedVerifier(), Verifier)

    def test_a_verdict_serialises_to_plain_json_types(self):
        """It is persisted onto a record, so it must survive a JSON round
        trip without a numpy scalar or a bool-shaped int in it."""
        payload = Verdict(
            agrees=True,
            proposed="remote",
            label="remote control",
            score=0.8,
            model="m",
            reason="r",
        ).to_json_dict()

        assert payload["agrees"] is True
        assert set(payload) == {
            "agrees",
            "proposed",
            "label",
            "score",
            "model",
            "reason",
        }


# -- the queue ---------------------------------------------------------


class TestQueue:
    def test_a_synchronous_queue_answers_before_it_returns(self):
        queue = VerificationQueue(ScriptedVerifier({"remote"}), workers=0)
        queue.start()
        sighting = _Sighting()

        queue.submit(sighting, crop=None)

        assert [v.agrees for _, v in queue.drain()] == [True]
        queue.stop()

    def test_a_threaded_queue_keeps_the_caller_moving(self):
        """The whole reason it is a queue.

        A 200 ms verifier on the frame path is two dropped frames every
        time it is asked. Here `submit` returns immediately and the
        verdict is collected later.
        """
        queue = VerificationQueue(
            ScriptedVerifier({"remote"}, delay_seconds=0.2), workers=1
        )
        queue.start()

        began = time.perf_counter()
        queue.submit(_Sighting(), crop=None)
        submitted_in = time.perf_counter() - began

        assert submitted_in < 0.1
        assert queue.wait_idle(timeout=5.0)
        assert len(queue.drain()) == 1
        queue.stop()

    def test_a_full_backlog_drops_the_oldest_rather_than_growing(self):
        """Rule 15: bounded by construction.

        Dropping the OLDEST is deliberate. A backlog means the verifier
        is behind the walk, and the sighting most likely to still matter
        is the newest -- the wearer is looking at it now.
        """
        blocked = threading.Event()

        class BlockingVerifier:
            name = "blocking"

            def load(self):
                return None

            def verify(self, crop, proposed_class):
                blocked.wait(timeout=5.0)
                return Verdict(False, proposed_class, None, None, self.name, "held")

            def release(self):
                return None

        queue = VerificationQueue(BlockingVerifier(), max_pending=2, workers=1)
        queue.start()
        try:
            for _ in range(10):
                queue.submit(_Sighting(), crop=None)

            assert queue.dropped_backlog > 0
            assert queue.peak_pending <= 2
        finally:
            blocked.set()
            queue.stop(timeout=5.0)

    def test_a_verifier_that_raises_produces_a_refusal_not_an_exception(self):
        class BrokenVerifier:
            name = "broken"

            def load(self):
                return None

            def verify(self, crop, proposed_class):
                raise RuntimeError("no")

            def release(self):
                return None

        queue = VerificationQueue(BrokenVerifier(), workers=0)
        queue.start()

        queue.submit(_Sighting(), crop=None)

        (_, verdict), = queue.drain()
        assert verdict.agrees is False
        assert verdict.reason == "verifier-failed"
        assert queue.failed == 1
        queue.stop()

    def test_the_counters_report_the_rate_and_the_backlog(self):
        queue = VerificationQueue(ScriptedVerifier({"remote"}), workers=0)
        queue.start()
        queue.submit(_Sighting("remote"), crop=None)
        queue.submit(_Sighting("book"), crop=None)

        counters = queue.counters()

        assert counters["submitted"] == 2
        assert counters["completed"] == 2
        assert counters["agreed"] == 1
        assert counters["refused"] == 1
        assert counters["dropped_backlog"] == 0
        assert counters["verifier"] == "scripted"
        queue.stop()

    def test_a_stopping_queue_accepts_no_more_work(self):
        """A verdict that arrives after the producer has exited is a
        sighting silently not written; taking new work at that point
        would guarantee some."""
        queue = VerificationQueue(ScriptedVerifier(), workers=0)
        queue.start()
        queue.stop()

        assert queue.submit(_Sighting(), crop=None) is False

    def test_stopping_releases_the_model(self):
        class Tracked(RefusingVerifier):
            released = False

            def release(self):
                Tracked.released = True

        queue = VerificationQueue(Tracked(), workers=1)
        queue.start()
        queue.stop(timeout=5.0)

        assert Tracked.released is True
