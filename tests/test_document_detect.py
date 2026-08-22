"""Does the cheap gate find a page, and refuse everything that is not one?

SYNTHETIC, NOT PHYSICAL.

Every assertion is against something the fixture chose: the corners a page
was placed at, the fact that a frame contains no page at all, the fact
that a page is blank. The detector's own output is never the yardstick.

The second gate is the one worth testing hardest. A closed laptop lid, a
picture frame and a blank whiteboard are all page-shaped, and a detector
that only found rectangles would call every one of them a document.
"""

import cv2
import numpy as np
import pytest

from tower.document_memory.detect import (
    MIN_ROW_TRANSITIONS,
    MIN_TEXT_ROW_FRACTION,
    detect_page,
    measure_text_likeness,
    order_corners,
    warp_page,
)
from tests import document_fixtures as fx


def _gray(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


class TestItFindsAPage:
    @pytest.mark.parametrize("tilt", [0.0, 0.5, 1.0])
    def test_a_page_in_view_is_detected_at_several_angles(self, tilt):
        """The passive-operation premise: the wearer does not square up."""
        frame, _ = fx.place_page(fx.render_page(fx.TRANSFORMER_PAPER), tilt=tilt)

        assert detect_page(_gray(frame)) is not None

    def test_the_recovered_corners_match_where_the_page_was_placed(self):
        """The fixture chose the corners, so they are independent truth."""
        frame, truth = fx.place_page(fx.render_page(fx.TRANSFORMER_PAPER))

        candidate = detect_page(_gray(frame))

        assert candidate is not None
        error = np.linalg.norm(candidate.corners - truth, axis=1)
        assert error.max() < 6.0, f"corner error {error}"

    def test_squareness_falls_as_the_page_tilts(self):
        """Ordering, not thresholds: a steeper view must score lower."""
        square = detect_page(_gray(fx.place_page(fx.render_page(fx.RECEIPT))[0]))
        tilted = detect_page(
            _gray(fx.place_page(fx.render_page(fx.RECEIPT), tilt=1.0)[0])
        )

        assert square is not None and tilted is not None
        assert square.squareness > tilted.squareness

    def test_sharpness_collapses_on_a_blurred_frame(self):
        """This is what best-frame selection inside a dwell runs on."""
        frame, _ = fx.place_page(fx.render_page(fx.TRANSFORMER_PAPER))

        sharp = detect_page(_gray(frame))
        blurred = detect_page(_gray(fx.blur(frame)))

        assert sharp is not None and blurred is not None
        assert blurred.sharpness < sharp.sharpness / 10


class TestItRefusesWhatIsNotADocument:
    def test_a_scene_with_no_page_yields_nothing(self):
        assert detect_page(_gray(fx.no_page_frame())) is None

    def test_a_page_shaped_region_with_no_text_is_not_a_document(self):
        """The second gate, and the reason it exists.

        A blank sheet, a closed laptop lid and a picture frame are all
        rectangles. Without a text-likeness test, "document detected"
        would mean "rectangle detected".
        """
        assert detect_page(_gray(fx.blank_page_frame())) is None

    def test_a_photograph_filling_a_frame_is_not_a_document(self):
        """Dark everywhere, but with no line structure."""
        rng = np.random.default_rng(2)
        photo = rng.integers(0, 90, (fx.PAGE_SIZE[1], fx.PAGE_SIZE[0], 3), np.uint8)
        frame, _ = fx.place_page(photo)

        assert detect_page(_gray(frame)) is None

    def test_a_tiny_page_far_away_is_ignored(self):
        """Too small to warp into anything readable."""
        page = fx.render_page(fx.RECEIPT)
        corners = np.array(
            [[300, 220], [360, 220], [360, 280], [300, 280]], dtype=np.float32
        )
        frame, _ = fx.place_page(page, corners=corners)

        assert detect_page(_gray(frame)) is None

    @pytest.mark.parametrize("size", [(8, 8), (16, 16), (31, 31)])
    def test_a_frame_too_small_to_hold_a_page_is_refused(self, size):
        assert detect_page(np.full(size, 200, np.uint8)) is None

    def test_an_empty_array_is_refused_rather_than_crashing(self):
        assert detect_page(np.zeros((0, 0), np.uint8)) is None
        assert detect_page(None) is None


class TestTextLikeness:
    def test_a_rendered_page_scores_above_every_gate(self):
        page = cv2.cvtColor(fx.render_page(fx.TRANSFORMER_PAPER), cv2.COLOR_BGR2GRAY)

        rows, ink, transitions = measure_text_likeness(page)

        assert rows > MIN_TEXT_ROW_FRACTION
        assert 0.0 < ink < 0.6
        assert transitions > MIN_ROW_TRANSITIONS

    def test_a_blank_page_scores_below_it(self):
        blank = np.full((1040, 800), 250, np.uint8)

        rows, ink, _ = measure_text_likeness(blank)

        assert rows < MIN_TEXT_ROW_FRACTION or ink < 0.004

    def test_an_empty_image_returns_zeros_rather_than_raising(self):
        assert measure_text_likeness(np.zeros((0, 0), np.uint8)) == (0.0, 0.0, 0.0)


class TestCornerOrdering:
    def test_corners_come_back_clockwise_from_top_left(self):
        """A mis-ordered quad warps to a mirrored or rotated page.

        Fed deliberately shuffled input, because the contour finder does
        not promise an order.
        """
        square = np.array(
            [[10, 10], [110, 10], [110, 90], [10, 90]], dtype=np.float32
        )
        shuffled = square[[2, 0, 3, 1]]

        assert np.allclose(order_corners(shuffled), square)

    def test_warping_a_known_quad_recovers_the_page_upright(self):
        """End to end: place a page, detect it, warp it, and the text rows
        must come back -- which they cannot if the warp is upside down."""
        frame, _ = fx.place_page(fx.render_page(fx.TRANSFORMER_PAPER), tilt=0.6)
        candidate = detect_page(_gray(frame))
        assert candidate is not None

        page = warp_page(_gray(frame), candidate.corners)
        top_half_ink = np.count_nonzero(page[: page.shape[0] // 2] < 128)
        bottom_half_ink = np.count_nonzero(page[page.shape[0] // 2 :] < 128)

        # The fixture puts a title and dense paragraph at the top and
        # whitespace at the bottom, so an upside-down warp inverts this.
        assert top_half_ink > bottom_half_ink
