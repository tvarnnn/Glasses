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

import numpy as np
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


class TestWaitIdleOrdering:
    def test_a_verdict_is_published_before_the_queue_reports_itself_idle(self):
        """`wait_idle` then `drain` must never miss an answer already paid for.

        The in-flight count used to drop in a `finally` block that ran
        BEFORE the verdict reached the done queue, so there was a window
        in which nothing was queued, nothing was in flight, and the
        verdict had not been published. A caller that waited and then
        drained discarded it.

        Fifty rounds, because the window was small.
        """
        queue = VerificationQueue(
            ScriptedVerifier({"remote"}, delay_seconds=0.001), workers=1
        )
        queue.start()
        try:
            for _ in range(50):
                queue.submit(_Sighting(), crop=None)
                assert queue.wait_idle(timeout=5.0)
                assert len(queue.drain()) == 1
        finally:
            queue.stop(timeout=5.0)


class TestOwlV2Verifier:
    """The only verifier this build actually offers, and it had no tests.

    None of these loads a model. What is under test is the DECISION,
    which is where a verifier can be wrong in a way that reaches a
    wearer's memory -- and which is exactly the part that does not need
    600 MB of weights to exercise.
    """

    def _verifier(self, ranking, *, min_score=0.45):
        """An OwlV2Verifier with its two model calls replaced by a script.

        The processor and the model are substituted, not the verifier, so
        the scoring, the ranking and the threshold are the shipped code
        paths.
        """
        from tower.object_memory.verification import OwlV2Verifier

        vocabulary = tuple(ranking)

        class Column(list):
            def tolist(self):
                return list(self)

        class FakeProcessor:
            def __call__(self, text=None, images=None, return_tensors=None):
                class Batch(dict):
                    def to(self, device):
                        return self

                return Batch()

            def post_process_grounded_object_detection(
                self, outputs, threshold=0.0, target_sizes=None
            ):
                return [
                    {
                        "labels": Column(range(len(vocabulary))),
                        "scores": Column(ranking[name] for name in vocabulary),
                    }
                ]

        verifier = OwlV2Verifier(
            device="cpu",
            min_score=min_score,
            vocabulary=vocabulary,
            prompt_for=lambda name: {"remote": "remote control"}.get(name, name),
        )
        verifier._processor = FakeProcessor()
        verifier._model = lambda **kwargs: None
        return verifier

    def _crop(self):
        return np.full((64, 64, 3), 120, np.uint8)

    def test_it_agrees_when_the_proposed_label_ranks_first_and_scores_enough(
        self,
    ):
        verifier = self._verifier(
            {"remote control": 0.8, "computer keyboard": 0.2, "laptop": 0.1}
        )

        verdict = verifier.verify(self._crop(), "remote")

        assert verdict.agrees is True
        assert verdict.label == "remote control"
        assert verdict.reason == "ranked-first"
        assert verdict.model == "owlv2-base-patch16-ensemble"

    def test_it_refuses_when_something_else_ranks_first(self):
        """The measured failure this exists for.

        The three highest-scoring `remote` sightings in the real corpus
        are all laptop keyboards.
        """
        verifier = self._verifier(
            {"remote control": 0.3, "computer keyboard": 0.7, "laptop": 0.1}
        )

        verdict = verifier.verify(self._crop(), "remote")

        assert verdict.agrees is False
        assert verdict.label == "computer keyboard"
        assert verdict.reason == "outranked"

    def test_it_refuses_a_first_place_that_is_too_weak(self):
        """Every false reject in the benchmark was a small crop scoring
        low even when it was right. The threshold is what keeps those out
        rather than in."""
        verifier = self._verifier(
            {"remote control": 0.3, "computer keyboard": 0.1, "laptop": 0.05}
        )

        verdict = verifier.verify(self._crop(), "remote")

        assert verdict.agrees is False
        assert verdict.reason == "below-threshold"

    def test_the_threshold_is_the_swept_one(self):
        from tower.object_memory.verification import OWLV2_MIN_SCORE

        assert OWLV2_MIN_SCORE == 0.45

    def test_a_class_the_vocabulary_cannot_express_is_refused(self):
        """The shape a policy change would take if it added a class and
        forgot the prompt. Refusing is the only honest answer, and also
        the safe one."""
        verifier = self._verifier({"laptop": 0.9})

        verdict = verifier.verify(self._crop(), "harmonica")

        assert verdict.agrees is False
        assert verdict.reason == "not-in-verifier-vocabulary"

    def test_the_verdict_records_what_it_would_have_called_it(self):
        """Recorded and NOT used to relabel: relabelling would let a model
        move a record between classes the tables gate separately."""
        verifier = self._verifier(
            {"remote control": 0.2, "computer keyboard": 0.9, "laptop": 0.1}
        )

        verdict = verifier.verify(self._crop(), "remote")

        assert verdict.proposed == "remote"
        assert verdict.label == "computer keyboard"

    def test_the_shipped_vocabulary_can_express_every_persistable_class(self):
        """A verify-tier class with no prompt can never be confirmed,
        however good the model is."""
        from tower.object_memory.classes import (
            PERSISTABLE_CLASSES,
            prompt_for,
            verifier_vocabulary,
        )

        vocabulary = set(verifier_vocabulary())
        missing = [
            name
            for name in PERSISTABLE_CLASSES
            if prompt_for(name) not in vocabulary
        ]

        assert missing == []

    def test_the_shipped_vocabulary_offers_the_measured_confusers(self):
        """A verifier given only the proposed name says yes; there is
        nothing else to say. The alternatives are what make the answer
        mean something, and these are the ones the detector was measured
        confusing."""
        from tower.object_memory.classes import verifier_vocabulary

        vocabulary = set(verifier_vocabulary())

        for confuser in ("ceiling fan", "door", "computer keyboard", "human hand"):
            assert confuser in vocabulary, confuser

    def test_the_vocabulary_never_offers_person(self):
        """`human hand` is a distractor; `person` is an exclusion.

        The class table's exclusion is not something a prompt list should
        be able to work around, and no score against any prompt here is
        ever stored.
        """
        from tower.object_memory.classes import verifier_vocabulary

        assert "person" not in verifier_vocabulary()


# -- what the SECOND review found, including in the first round's fixes --


class TestOutstandingAccounting:
    """`wait_idle` reads one counter, because two conditions had two gaps.

    It was "the queue is empty and nothing is in flight". `_in_flight`
    was incremented *after* `_pending.get()` returned, so a job could be
    off the queue and not yet counted -- and a reviewer reproduced
    `wait_idle()` returning True with a verdict still to come. Moving the
    decrement past `_done.put` closed the tail of that window and left
    the head open.
    """

    def test_a_submitted_job_is_outstanding_before_a_worker_touches_it(self):
        blocked = threading.Event()
        started = threading.Event()

        class BlockingVerifier:
            name = "blocking"

            def load(self):
                return None

            def verify(self, crop, proposed_class):
                started.set()
                blocked.wait(timeout=5.0)
                return Verdict(True, proposed_class, proposed_class, 1.0, "b", "ok")

            def release(self):
                return None

        queue = VerificationQueue(BlockingVerifier(), workers=1)
        queue.start()
        try:
            queue.submit(_Sighting(), crop=None)
            assert started.wait(timeout=5.0)

            # The job is off the queue and inside the verifier. Under the
            # old two-condition check this is exactly the window.
            assert queue.wait_idle(timeout=0.2) is False

            blocked.set()
            assert queue.wait_idle(timeout=5.0) is True
            assert len(queue.drain()) == 1
        finally:
            blocked.set()
            queue.stop(timeout=5.0)

    def test_the_counter_never_goes_negative_in_synchronous_mode(self):
        """It did, and seven engine tests then sat out a 30-second
        timeout apiece: the synchronous path skipped the increment while
        `_run_one` decremented in a `finally`."""
        queue = VerificationQueue(ScriptedVerifier({"remote"}), workers=0)
        queue.start()

        for _ in range(5):
            queue.submit(_Sighting(), crop=None)

        assert queue.wait_idle(timeout=1.0) is True
        queue.stop()

    def test_a_dropped_job_stops_being_outstanding(self):
        """A job evicted by the backlog will never publish a verdict, so
        it must stop being counted or `wait_idle` waits for one forever."""
        blocked = threading.Event()

        class BlockingVerifier:
            name = "blocking"

            def load(self):
                return None

            def verify(self, crop, proposed_class):
                blocked.wait(timeout=5.0)
                return Verdict(False, proposed_class, None, None, "b", "held")

            def release(self):
                return None

        queue = VerificationQueue(BlockingVerifier(), max_pending=2, workers=1)
        queue.start()
        try:
            for _ in range(10):
                queue.submit(_Sighting(), crop=None)
            assert queue.dropped_backlog > 0
            blocked.set()

            assert queue.wait_idle(timeout=5.0) is True
        finally:
            blocked.set()
            queue.stop(timeout=5.0)

    def test_a_base_exception_does_not_leak_the_counter(self):
        """The `finally` is not optional.

        An earlier version dropped it to publish before decrementing, and
        that leaked forever on a `KeyboardInterrupt` inside the model --
        `wait_idle` could then never return True again.
        """

        class ExplodingVerifier:
            name = "exploding"

            def load(self):
                return None

            def verify(self, crop, proposed_class):
                raise KeyboardInterrupt("from inside the model")

            def release(self):
                return None

        queue = VerificationQueue(ExplodingVerifier(), workers=0)
        queue.start()

        with pytest.raises(KeyboardInterrupt):
            queue.submit(_Sighting(), crop=None)

        assert queue.wait_idle(timeout=1.0) is True
