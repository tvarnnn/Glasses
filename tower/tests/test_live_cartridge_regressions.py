"""Five defects an adversarial review found, each pinned by the case that found it.

Every test here failed before its fix and passes after. They are together
in one file rather than scattered because they share a shape: each is a
property that looked true from the code and was false when a second
thread, or a second capture, or a real clock got involved.

Written after the fixes rather than before them, which is worth saying
plainly -- these are regression tests, not the specification the code was
written from. Each was verified to fail against the pre-fix behaviour, by
restoring the old ordering and watching it go red.
"""

import threading

import pytest

from tests import document_fixtures as fx
from tower.document_memory.dwell import DwellPolicy
from tower.document_memory.live import DocumentLive
from tower.document_memory.ocr import FixedTextRecogniser
from tower.document_memory.records import DocumentObservation, PageObservation
from tower.document_memory.store import DocumentStore
from tower.results import document_memory as adapter
from tower.scene.live import SceneLive

POLICY = DwellPolicy(min_frames=3, min_seconds=0.6)


def _await(predicate, timeout=15.0) -> bool:
    deadline = threading.Event()
    timer = threading.Timer(timeout, deadline.set)
    timer.start()
    try:
        while not deadline.is_set():
            if predicate():
                return True
            deadline.wait(0.005)
        return False
    finally:
        timer.cancel()


def _document(document_id: str, *, recorded_at: float) -> DocumentObservation:
    return DocumentObservation(
        document_id=document_id,
        observed_at=recorded_at,
        recorded_at=recorded_at,
        observed_seconds=5.0,
        pages=(PageObservation(page_index=0, text="a secret"),),
    )


class TestRetentionNarrowsReadsAndSaysSoTruthfully:
    """`?retention_days=` reported success and did nothing.

    Until 2026-08-27 `DocumentStore.read_all` ignored `retention_seconds`
    entirely -- the window was consumed only by the two deletion paths --
    while the payload asserted, in three separate strings, that a read
    had been narrowed to it. A privacy control that reports success is a
    false assurance, and this is the cartridge whose own header calls its
    contents "the most sensitive data this platform handles".

    The identical bug had already been found and fixed one cartridge
    over, in `tower/object_memory/store.py`.
    """

    def test_a_narrowed_read_does_not_serve_an_older_document(self, tmp_path):
        DocumentStore(tmp_path).append(_document("ancient", recorded_at=0.0))
        store = adapter.store_from_root(
            tmp_path, retention_days=1.0, clock=lambda: 400 * 86400.0
        )

        listing = adapter.recent_documents(store, requested_days=1.0)
        search = adapter.search_documents(store, text="secret", requested_days=1.0)

        assert listing["documents"] == []
        assert search["documents"] == []
        assert adapter.one_document(store, "ancient") is None

    def test_the_same_document_is_served_without_a_window(self, tmp_path):
        """The other half: the filter must not simply hide everything."""
        DocumentStore(tmp_path).append(_document("ancient", recorded_at=0.0))
        store = adapter.store_from_root(tmp_path, clock=lambda: 400 * 86400.0)

        assert len(adapter.recent_documents(store)["documents"]) == 1
        assert adapter.one_document(store, "ancient") is not None

    def test_a_narrowed_empty_read_is_no_observation_not_not_found(self, tmp_path):
        """Consistency between the filter and the three answers.

        A window that hides every record leaves a memory holding nothing
        that could have matched, which is `no_observation` -- the same
        answer an empty store gives. `not_found` would be a claim that
        the memory was searched and the document was not in it.
        """
        DocumentStore(tmp_path).append(_document("ancient", recorded_at=0.0))
        store = adapter.store_from_root(
            tmp_path, retention_days=1.0, clock=lambda: 400 * 86400.0
        )

        result = adapter.search_documents(store, text="secret", requested_days=1.0)

        assert result["answer"] == "no_observation"

    def test_pruning_can_still_see_what_reads_now_hide(self, tmp_path):
        """The failure mode the fix could easily have introduced.

        `prune_expired` collects the doomed page images through
        `read_all`. Had that read started filtering without an opt-out,
        the prune would have reported `documents_removed: 0` and left
        every expired image on disk -- retention that deletes nothing,
        silently.
        """
        store = DocumentStore(
            tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
        )
        store.append(_document("old", recorded_at=0.0))
        store.append(_document("new", recorded_at=950.0))

        assert store.prune_expired(now=1000.0)["documents_removed"] == 1
        assert "old" not in store.path.read_text(encoding="utf-8")


class TestStopClosesTheDoorBeforeItFlushes:
    """One page became two documents, because Stop flushed first.

    `stop()` used to call the flush hook while the state was still
    `running`, so for the whole duration of that flush -- OCR, 1.19 s a
    page, up to two pages -- `offer_frame` kept accepting frames and the
    worker kept calling `observe()` on the same engine. Two threads, one
    `DwellTracker`, no lock. The visible damage was two document memories
    of one page with overlapping observation windows and nothing linking
    them, because dedup only works within a dwell.
    """

    def test_no_frame_is_observed_once_stop_has_been_called(self, tmp_path):
        entered = threading.Event()
        release = threading.Event()
        observed_after_stop = []
        stopped = threading.Event()

        class SlowFlush(DocumentLive):
            def _on_pause(self, engine):
                entered.set()
                release.wait(timeout=10.0)
                super()._on_pause(engine)

            def _consume(self, engine, raw_bytes, received_at, source_seq):
                if stopped.is_set():
                    observed_after_stop.append(received_at)
                return super()._consume(engine, raw_bytes, received_at, source_seq)

        session = SlowFlush(
            tmp_path,
            policy=POLICY,
            recogniser_factory=lambda: FixedTextRecogniser(
                pages=[fx.page_regions(fx.TRANSFORMER_PAPER)]
            ),
        )
        frames = list(fx.document_frames(fx.TRANSFORMER_PAPER, 6))
        try:
            session.start()
            assert _await(lambda: session.state == "running")
            for index, raw in enumerate(frames[:3]):
                session.offer_frame(raw, source_seq=index)
                assert _await(lambda: session.status()["frames_observed"] > index)
                threading.Event().wait(0.25)

            stopper = threading.Thread(target=session.stop, daemon=True)
            stopper.start()
            assert entered.wait(timeout=10.0), "the flush hook never ran"
            stopped.set()
            # The door must already be shut: these must not reach the
            # engine the flush is inside.
            for index, raw in enumerate(frames[3:], start=3):
                session.offer_frame(raw, source_seq=index)
            release.set()
            stopper.join(timeout=15.0)
        finally:
            release.set()
            session.stop()

        assert observed_after_stop == []
        assert session.status()["state"] == "stopped"

    def test_one_held_page_produces_one_document_across_a_stop(self, tmp_path):
        """The damage, rather than the mechanism.

        A wearer holding one page while an operator presses Stop must
        leave one memory of it, not two.
        """
        session = DocumentLive(
            tmp_path,
            policy=POLICY,
            recogniser_factory=lambda: FixedTextRecogniser(
                pages=[fx.page_regions(fx.TRANSFORMER_PAPER)]
            ),
        )
        try:
            session.start()
            assert _await(lambda: session.state == "running")
            for index, raw in enumerate(fx.document_frames(fx.TRANSFORMER_PAPER, 8)):
                session.offer_frame(raw, source_seq=index)
                assert _await(lambda: session.status()["frames_observed"] > index)
                threading.Event().wait(0.1)
            session.stop()
        finally:
            session.stop()

        documents = DocumentStore(tmp_path).read_all()
        assert len(documents) == 1, [d.document_id for d in documents]

    def test_a_document_written_during_a_stop_is_still_counted(self, tmp_path):
        """Counters that disagree with the disk are the worst outcome.

        `engine.observe()` writes the document before the session sees
        the result, so declining to publish a late result does not
        unwrite it -- it only hides it. The measured symptom was two
        documents on disk and `documents_recorded: 1`.
        """
        session = DocumentLive(
            tmp_path,
            policy=POLICY,
            recogniser_factory=lambda: FixedTextRecogniser(
                pages=[fx.page_regions(fx.TRANSFORMER_PAPER)]
            ),
        )
        try:
            session.start()
            assert _await(lambda: session.state == "running")
            for index, raw in enumerate(fx.document_frames(fx.TRANSFORMER_PAPER, 8)):
                session.offer_frame(raw, source_seq=index)
                assert _await(lambda: session.status()["frames_observed"] > index)
                threading.Event().wait(0.1)
            status = session.stop()
        finally:
            session.stop()

        on_disk = len(DocumentStore(tmp_path).read_all())
        assert on_disk == status["documents_recorded"], (
            "the session reported a different number of documents than it wrote"
        )


class TestTheEngineIsNotTornDownUnderALiveCall:
    """Release used to happen before the join.

    `LoadInvalidation` covers a worker stuck in `_create()`. It does
    nothing for a worker inside `_consume()`, so a Stop during a busy
    frame called `release()` on a model that was mid-forward-pass --
    `torch.cuda.empty_cache()` racing a live allocation on CUDA, and
    `EasyOcrRecogniser._reader = None` inside `read()`.
    """

    def test_release_happens_after_the_worker_leaves_consume(self):
        order = []
        inside = threading.Event()
        finish = threading.Event()

        class SlowEngine:
            def __init__(self):
                self.released = False
                self._detector = type("D", (), {"name": "slow"})()

            def load(self):
                pass

            def release(self):
                order.append("release")
                self.released = True

            def observe(self, frame, *, received_at=None):
                order.append("observe-enter")
                inside.set()
                finish.wait(timeout=10.0)
                order.append("observe-exit")
                return ("state", received_at)

        engine = SlowEngine()
        session = SceneLive(lambda: engine, decode=lambda raw: raw)
        try:
            session.start()
            assert _await(lambda: session.state == "running")
            session.offer_frame(b"frame", received_at=1.0)
            assert inside.wait(timeout=10.0)

            stopper = threading.Thread(target=session.stop, daemon=True)
            stopper.start()
            # Give stop() a moment to reach its join. If it released
            # first, "release" lands here, before "observe-exit".
            threading.Event().wait(0.2)
            finish.set()
            stopper.join(timeout=15.0)
        finally:
            finish.set()
            session.stop()

        assert "release" in order, order
        assert order.index("observe-exit") < order.index("release"), order


class TestProvenanceBelongsToTheDwellThatEarnedIt:
    """A capture id read at record time pointed at the wrong recording.

    `_record` used to stamp `self._capture_id` -- whatever the field held
    when the dwell ENDED. A `stream_start` arriving mid-dwell (a phone
    reconnect re-arms the recorder) moved the whole reading onto a
    capture it did not come from, and the published `page_source_seqs`
    then resolved into that capture's journal, naming completely
    different frames. A pointer that resolves to the wrong frame is worse
    than no pointer at all.

    The `stream_stop` case was the commoner one: the id was nulled while
    the dwell stayed open, so a document arrived with real frame
    sequence numbers and no recording to resolve them against.
    """

    def _session(self, tmp_path):
        return DocumentLive(
            tmp_path,
            policy=POLICY,
            recogniser_factory=lambda: FixedTextRecogniser(
                pages=[fx.page_regions(fx.TRANSFORMER_PAPER)]
            ),
        )

    def _read_one_page(self, session, frames, *, midway=None):
        for index, raw in enumerate(frames):
            if midway is not None and index == 3:
                midway()
            session.offer_frame(raw, source_seq=index)
            assert _await(lambda: session.status()["frames_observed"] > index)
            threading.Event().wait(0.1)

    def test_a_capture_that_opens_mid_dwell_does_not_claim_the_reading(
        self, tmp_path
    ):
        session = self._session(tmp_path)
        frames = list(fx.document_frames(fx.TRANSFORMER_PAPER, 8))
        try:
            session.start()
            assert _await(lambda: session.state == "running")
            session.capture_started("capture-AAAA")
            self._read_one_page(
                session,
                frames,
                midway=lambda: session.capture_started("capture-BBBB"),
            )
            session.stop()
        finally:
            session.stop()

        documents = DocumentStore(tmp_path).read_all()
        assert len(documents) == 1
        assert documents[0].capture_id == "capture-AAAA"

    def test_a_capture_that_closes_mid_dwell_does_not_erase_the_lineage(
        self, tmp_path
    ):
        session = self._session(tmp_path)
        frames = list(fx.document_frames(fx.TRANSFORMER_PAPER, 8))
        try:
            session.start()
            assert _await(lambda: session.state == "running")
            session.capture_started("capture-AAAA")
            self._read_one_page(
                session,
                frames,
                midway=lambda: session.capture_stopped("capture-AAAA"),
            )
            session.stop()
        finally:
            session.stop()

        documents = DocumentStore(tmp_path).read_all()
        assert len(documents) == 1
        assert documents[0].capture_id == "capture-AAAA"
        assert [page.source_seq for page in documents[0].pages]

    def test_a_dwell_that_starts_after_the_switch_gets_the_new_capture(
        self, tmp_path
    ):
        """The other direction, so the fix is not just 'freeze forever'."""
        session = self._session(tmp_path)
        try:
            session.start()
            assert _await(lambda: session.state == "running")
            session.capture_started("capture-AAAA")
            self._read_one_page(
                session, list(fx.document_frames(fx.TRANSFORMER_PAPER, 8))
            )
            # A gap long enough to end the dwell, then a new capture.
            session.capture_started("capture-BBBB")
            for index in range(4):
                session.offer_frame(fx.encode(fx.no_page_frame()), source_seq=100 + index)
                assert _await(
                    lambda: session.status()["frames_observed"] > 8 + index
                )
            self._read_one_page(
                session, list(fx.document_frames(fx.DEPTH_NOTES, 8))
            )
            session.stop()
        finally:
            session.stop()

        captures = {d.capture_id for d in DocumentStore(tmp_path).read_all()}
        assert captures == {"capture-AAAA", "capture-BBBB"}, captures


@pytest.mark.parametrize("recorded_at", (None, "not-a-number", True))
def test_a_record_with_no_usable_timestamp_is_treated_as_expired(
    tmp_path, recorded_at
):
    """The direction a malformed record must fail in.

    A record whose `recorded_at` cannot be read cannot be shown to be
    within the window. Defaulting it to "keep" would make a malformed
    record permanently readable, which is the wrong direction for a
    window whose whole job is to remove things. `True` is in the list
    because `bool` is an `int` subclass in Python and would otherwise
    read as the timestamp 1.
    """
    from tower.document_memory.store import DocumentStore as Store

    assert Store._is_within_retention({"recorded_at": recorded_at}, 100.0) is False
    assert Store._is_within_retention({"recorded_at": recorded_at}, None) is True
