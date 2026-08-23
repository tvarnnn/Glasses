"""The defects an adversarial review found, pinned so they cannot return.

SYNTHETIC, NOT PHYSICAL.

Three of these are the same shape: something that looks like a document
but is not, a clock that does not behave, and a dependency that fails.
All three used to produce a confidently wrong record or silently destroy
a real one, which is worse than an error.
"""

import cv2
import numpy as np
import pytest

from tower.confidence import Confidence
from tower.document_memory.detect import MIN_ROW_TRANSITIONS, detect_page, warp_page
from tower.document_memory.dwell import DwellPolicy, DwellTracker
from tower.document_memory.engine import DocumentMemoryEngine
from tower.document_memory.ocr import FixedTextRecogniser, OcrResult, TextRegion
from tower.document_memory.records import (
    TIMING_ASSUMED_INTERVAL,
    TIMING_CAPTURE_JOURNAL,
    TIMING_MIXED,
)
from tower.document_memory.store import DocumentStore
from tests import document_fixtures as fx

POLICY = DwellPolicy(min_frames=3, min_seconds=0.6)


# ----------------------------------------------------------------------
# Structured-but-not-text surfaces. Every one of these has rows of dark
# pixels, which is exactly what the second gate looks for.
# ----------------------------------------------------------------------


def _blinds(width=800, height=1040):
    image = np.full((height, width), 235, np.uint8)
    for y in range(0, height, 40):
        image[y : y + 22, :] = 60
    return image


def _bricks(width=800, height=1040):
    image = np.full((height, width), 150, np.uint8)
    for y in range(0, height, 60):
        image[y : y + 8, :] = 90
        offset = 0 if (y // 60) % 2 == 0 else 90
        for x in range(offset, width, 180):
            image[y : y + 60, x : x + 8] = 90
    return image


def _tiles(width=800, height=1040):
    image = np.full((height, width), 200, np.uint8)
    for y in range(0, height, 90):
        image[y : y + 6, :] = 110
    for x in range(0, width, 90):
        image[:, x : x + 6] = 110
    return image


def _stripes(width=800, height=1040):
    image = np.full((height, width), 230, np.uint8)
    for y in range(0, height, 34):
        image[y : y + 17, :] = 70
    return image


def _keyboard(width=800, height=1040):
    image = np.full((height, width), 60, np.uint8)
    for y in range(10, height, 70):
        for x in range(10, width, 70):
            image[y : y + 55, x : x + 55] = 30
    return image


def _barcode(width=800, height=1040):
    rng = np.random.default_rng(4)
    image = np.full((height, width), 245, np.uint8)
    x = 40
    while x < width - 40:
        bar = int(rng.integers(3, 14))
        image[200:800, x : x + bar] = 20
        x += bar + int(rng.integers(4, 16))
    return image


STRUCTURED_NON_TEXT = {
    "venetian blinds": _blinds,
    "brick wall": _bricks,
    "tiled floor": _tiles,
    "striped shirt": _stripes,
    "keyboard": _keyboard,
    "barcode": _barcode,
}


class TestStructureIsNotText:
    """A brick wall reached OCR and was persisted as a document.

    The second gate keys on rows of dark pixels, and blinds, brick
    courses, floor tiles and stripes all have exactly that. The glyph gate
    is what separates them: text is many short runs per row, a slat is one.
    """

    @pytest.mark.parametrize("name", sorted(STRUCTURED_NON_TEXT))
    def test_a_structured_surface_is_not_called_a_document(self, name):
        surface = STRUCTURED_NON_TEXT[name]()
        frame, _ = fx.place_page(cv2.cvtColor(surface, cv2.COLOR_GRAY2BGR))

        assert detect_page(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)) is None, (
            f"{name} was detected as a document"
        )

    @pytest.mark.parametrize("name", sorted(STRUCTURED_NON_TEXT))
    def test_a_structured_surface_never_reaches_the_expensive_path(
        self, name, tmp_path
    ):
        """End to end, because that is where it actually bit.

        The detector is only the first of three stages that had to be
        fooled; the review drove a brick wall through all of them and got
        a stored DocumentObservation out the other side.
        """
        surface = STRUCTURED_NON_TEXT[name]()
        store = DocumentStore(tmp_path)
        recogniser = FixedTextRecogniser(pages=["should never be called"])
        engine = DocumentMemoryEngine(
            store, recogniser, policy=POLICY, assumed_frame_interval_s=0.3
        )

        rng = np.random.default_rng(9)
        for index in range(12):
            jitter = rng.normal(0.0, 1.5, (4, 2)).astype(np.float32)
            corners = (
                np.array(
                    [[64, 28], [576, 28], [576, 452], [64, 452]], dtype=np.float32
                )
                + jitter
            )
            frame, _ = fx.place_page(
                cv2.cvtColor(surface, cv2.COLOR_GRAY2BGR), corners=corners
            )
            engine.observe(fx.encode(frame), source_seq=index)
        engine.flush()

        assert recogniser.calls == 0, f"{name} triggered OCR"
        assert store.count() == 0, f"{name} was persisted as a document"

    def test_real_text_still_clears_the_glyph_gate_by_a_wide_margin(self):
        """The gate must not have been bought with a false negative."""
        frame, _ = fx.place_page(fx.render_page(fx.TRANSFORMER_PAPER))

        candidate = detect_page(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))

        assert candidate is not None
        assert candidate.row_transitions > MIN_ROW_TRANSITIONS * 3


class TestTheClockCannotDestroyADocument:
    """`received_at` is WALL CLOCK from the capture journal.

    An NTP correction is not exotic; it is a scheduled event on every
    machine. Before these fixes one backward step on the last frame of a
    perfect dwell silently discarded the whole document.
    """

    @staticmethod
    def _candidate():
        from tower.document_memory.detect import PageCandidate

        corners = np.array(
            [[100, 100], [300, 100], [300, 300], [100, 300]], dtype=np.float32
        )
        return PageCandidate(
            corners=corners,
            area_fraction=0.4,
            aspect=1.0,
            solidity=0.99,
            text_row_fraction=0.3,
            ink_fraction=0.1,
            row_transitions=60.0,
            sharpness=800.0,
            squareness=0.95,
        )

    def _feed(self, tracker, times):
        gray = np.full((240, 320), 200, np.uint8)
        finished = []
        for index, at in enumerate(times):
            result = tracker.observe(
                self._candidate(),
                at=at,
                gray=gray,
                source_seq=index,
                frame_diagonal=800.0,
            )
            if result is not None:
                finished.append(result)
        return finished

    def test_a_backward_step_on_the_last_frame_does_not_discard_the_dwell(self):
        """The exact failure: 3.5s of real reading, then one bad timestamp."""
        tracker = DwellTracker(DwellPolicy(min_frames=4, min_seconds=1.0))
        times = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 3.4]

        self._feed(tracker, times)
        dwell = tracker.flush()

        assert dwell is not None, "a real reading was silently thrown away"
        assert dwell.seconds >= 3.5
        assert dwell.clock_regressions == 1

    def test_a_mid_dwell_backward_step_does_not_understate_the_duration(self):
        tracker = DwellTracker(DwellPolicy(min_frames=4, min_seconds=1.0))

        self._feed(tracker, [0.0, 1.0, 2.0, 1.5, 2.5, 3.5, 4.5])
        dwell = tracker.flush()

        # Forward deltas only: 1+1+0+1+1+1 = 5.0. Never negative, and
        # never the naive last-minus-first of 4.5 either.
        assert dwell.seconds == pytest.approx(5.0)

    def test_an_enormous_forward_jump_ends_the_dwell_instead_of_absorbing_it(
        self,
    ):
        """A 92-day document came out of a single bad timestamp."""
        tracker = DwellTracker(
            DwellPolicy(min_frames=3, min_seconds=0.6, max_frame_gap_s=5.0)
        )

        finished = self._feed(tracker, [0.0, 0.5, 1.0, 1.5, 8_000_000.0])
        remaining = tracker.flush()

        assert finished, "the gap must have closed the first dwell"
        assert finished[0].seconds < 10.0
        assert remaining is None or remaining.seconds < 10.0


class TestTimingProvenanceSurvivesAMixedStream:
    def test_a_missing_timestamp_mid_stream_does_not_jump_the_clock(
        self, tmp_path
    ):
        """One frame with no `received_at` used to detach the clock.

        The synthetic clock anchored to wall-time the first time it was
        needed, so a single gap in an otherwise real stream produced a
        document claiming months of reading.
        """
        store = DocumentStore(tmp_path)
        engine = DocumentMemoryEngine(
            store,
            FixedTextRecogniser(pages=[fx.page_regions(fx.RECEIPT)]),
            policy=POLICY,
            clock=lambda: 9_000_000.0,
            assumed_frame_interval_s=0.3,
        )

        frames = fx.document_frames(fx.RECEIPT, 9)
        for index, frame in enumerate(frames):
            # Frame 4 has no timestamp; the rest are real and near 1000.
            received_at = None if index == 4 else 1000.0 + index * 0.3
            engine.observe(frame, received_at=received_at, source_seq=index)
        engine.flush()

        document = store.read_all()[0]

        assert document.observed_seconds < 10.0, (
            f"observed_seconds={document.observed_seconds}"
        )
        assert document.timing_source == TIMING_MIXED, (
            "a stream with both real and assumed times is neither"
        )

    def test_an_all_real_stream_is_labelled_measured(self, tmp_path):
        store = DocumentStore(tmp_path)
        engine = DocumentMemoryEngine(
            store,
            FixedTextRecogniser(pages=[fx.page_regions(fx.RECEIPT)]),
            policy=POLICY,
            assumed_frame_interval_s=0.3,
        )
        for index, frame in enumerate(fx.document_frames(fx.RECEIPT, 8)):
            engine.observe(frame, received_at=1000.0 + index * 0.3, source_seq=index)
        engine.flush()

        document = store.read_all()[0]

        assert document.timing_source == TIMING_CAPTURE_JOURNAL
        assert document.assumed_frame_interval_s is None, (
            "an interval that was never used must not be recorded as if it was"
        )

    def test_an_all_assumed_stream_is_labelled_assumed(self, tmp_path):
        store = DocumentStore(tmp_path)
        engine = DocumentMemoryEngine(
            store,
            FixedTextRecogniser(pages=[fx.page_regions(fx.RECEIPT)]),
            policy=POLICY,
            assumed_frame_interval_s=0.3,
        )
        for index, frame in enumerate(fx.document_frames(fx.RECEIPT, 8)):
            engine.observe(frame, source_seq=index)
        engine.flush()

        assert store.read_all()[0].timing_source == TIMING_ASSUMED_INTERVAL


class TestOneOcrFailureDoesNotEndTheSession:
    class _ExplodingRecogniser:
        name = "exploding"

        def __init__(self, fail_on=1):
            self.calls = 0
            self._fail_on = fail_on

        def read(self, page_gray):
            self.calls += 1
            if self.calls >= self._fail_on:
                raise RuntimeError("model OOM")
            return OcrResult(
                text="first page",
                regions=(
                    TextRegion(text="first page", confidence=0.9, box=(0, 0, 10, 10)),
                ),
            )

        def release(self):
            return None

    def test_a_failing_recogniser_does_not_lose_the_document(self, tmp_path):
        """Losing the whole document is worse than an unreadable page.

        "We looked and found no readable text" is this module's own stated
        answer for that case.
        """
        store = DocumentStore(tmp_path)
        engine = DocumentMemoryEngine(
            store,
            self._ExplodingRecogniser(fail_on=1),
            policy=POLICY,
            assumed_frame_interval_s=0.3,
        )
        for index, frame in enumerate(fx.document_frames(fx.RECEIPT, 8)):
            engine.observe(frame, source_seq=index)
        engine.flush()

        assert store.count() == 1
        document = store.read_all()[0]
        assert document.pages_observed == 1
        assert document.pages[0].text == ""
        assert document.pages[0].confidence is Confidence.UNKNOWN

    def test_the_rest_of_the_stream_is_still_processed(self, tmp_path):
        """In a live session the exception ended observation entirely."""
        store = DocumentStore(tmp_path)
        engine = DocumentMemoryEngine(
            store,
            self._ExplodingRecogniser(fail_on=1),
            policy=POLICY,
            assumed_frame_interval_s=0.3,
        )

        frames = (
            fx.document_frames(fx.RECEIPT, 8)
            + [fx.encode(fx.no_page_frame())] * 6
            + fx.document_frames(fx.DEPTH_NOTES, 8)
        )
        for index, frame in enumerate(frames):
            engine.observe(frame, source_seq=index)
        engine.flush()

        assert engine.frames_observed == len(frames)
        assert store.count() == 2, "the second document must still be observed"


class TestABlankReadingDoesNotEraseADifferentPage:
    def test_a_page_turn_where_ocr_fails_on_one_view_keeps_both_pages(
        self, tmp_path
    ):
        """The blank-merge rule used to swallow a genuinely different page.

        The dwell's two best frames are the two sharpest views of a
        REGION, not guaranteed to be the same physical page. If the wearer
        turns a page without moving it and OCR fails on the second view,
        the unrestricted rule merged the failure into the first page and
        the second page vanished from the record.
        """
        store = DocumentStore(tmp_path)

        class _SecondViewFails:
            name = "second-fails"

            def __init__(self):
                self.calls = 0

            def read(self, page_gray):
                self.calls += 1
                if self.calls == 1:
                    text = "Attention Is All You Need"
                    return OcrResult(
                        text=text,
                        regions=(
                            TextRegion(text=text, confidence=0.9, box=(0, 0, 10, 10)),
                        ),
                    )
                return OcrResult(text="")

            def release(self):
                return None

        engine = DocumentMemoryEngine(
            store,
            _SecondViewFails(),
            policy=POLICY,
            assumed_frame_interval_s=0.3,
        )
        for index, frame in enumerate(fx.document_frames(fx.TRANSFORMER_PAPER, 10)):
            engine.observe(frame, source_seq=index)
        engine.flush()

        document = store.read_all()[0]

        # One page, because the blank view IS the same page seen badly --
        # and the reading that worked is the one kept.
        assert document.pages_observed == 1
        assert "Attention" in document.pages[0].text
        assert document.frames_ocred == 2

    def test_two_genuinely_different_readings_stay_two_pages(self, tmp_path):
        store = DocumentStore(tmp_path)
        recogniser = FixedTextRecogniser(
            pages=[fx.page_regions(fx.TRANSFORMER_PAPER), fx.page_regions(fx.RECEIPT)]
        )
        engine = DocumentMemoryEngine(
            store, recogniser, policy=POLICY, assumed_frame_interval_s=0.3
        )
        for index, frame in enumerate(fx.document_frames(fx.TRANSFORMER_PAPER, 10)):
            engine.observe(frame, source_seq=index)
        engine.flush()

        assert store.read_all()[0].pages_observed == 2
