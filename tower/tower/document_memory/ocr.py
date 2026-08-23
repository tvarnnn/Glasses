"""Turning a corrected page image into text, behind a seam.

A seam rather than a direct call for two reasons, both practical.

**Cost.** EasyOCR takes ~5 s to construct a reader and ~1.2 s per page on
this CPU. A default test suite that paid that per assertion would be
unusable, and one that downloaded a model would fail on a train. Tests
use `FixedTextRecogniser`; the real engine is exercised by an opt-in
integration test.

**Substitutability.** `docs/superpowers/research/2026-08-20-document-memory-design.md`
surveyed the OCR field and deliberately did not select one, because the
choice should follow measurement. The seam is how a later measurement can
change the answer without touching the pipeline.

Everything here is **model inference, not measured fact**
(`07-PLATFORM-CONSTRAINTS.md` Core Principle 2). Per-region confidence is
carried through so a low-confidence reading cannot silently become a
confident answer.
"""

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from tower.confidence import Confidence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextRegion:
    """One recognised run of text, and where on the page it sat.

    The box is not decoration. A recogniser splits a heading into several
    regions -- "Attention", "Is All You Need" -- so reconstructing a title
    from the first region alone yields one word. Grouping regions that
    share a line needs their vertical position, and only the recogniser
    knows it.
    """

    text: str
    confidence: float
    box: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1

    @property
    def y_centre(self) -> float | None:
        if self.box is None:
            return None
        return (self.box[1] + self.box[3]) / 2.0

    @property
    def height(self) -> float | None:
        if self.box is None:
            return None
        return abs(self.box[3] - self.box[1])


@dataclass(frozen=True)
class OcrResult:
    """What OCR actually returned, with how sure it was.

    An empty result is a real answer -- "we looked and found no readable
    text" -- and is stored as such. It is not the same as never looking,
    and Core Principle 3 forbids collapsing the two.
    """

    text: str
    regions: tuple[TextRegion, ...] = ()

    @property
    def region_count(self) -> int:
        return len(self.regions)

    @property
    def mean_confidence(self) -> float | None:
        if not self.regions:
            return None
        return sum(region.confidence for region in self.regions) / len(self.regions)

    @property
    def min_confidence(self) -> float | None:
        if not self.regions:
            return None
        return min(region.confidence for region in self.regions)

    @property
    def confidence_label(self) -> Confidence:
        """A LABEL, never a stored score.

        Stored as a label so a later threshold change cannot silently
        relabel history (Rule 16). Derived from the MEAN rather than the
        minimum: one hard word in a paragraph should not condemn the page.
        """
        return Confidence.from_score(self.mean_confidence)


@runtime_checkable
class TextRecogniser(Protocol):
    """Anything that can read a corrected page image."""

    name: str

    def read(self, page_gray) -> OcrResult: ...

    def release(self) -> None: ...


class FixedTextRecogniser:
    """Returns text the test chose. The default suite's recogniser.

    Not a mock of EasyOCR's behaviour -- a substitute for it. Tests that
    care about OCR ACCURACY use the real engine behind an opt-in marker;
    tests that care about the pipeline use this, and are therefore fast,
    offline and deterministic.
    """

    name = "fixed"

    def __init__(self, pages=None, confidence: float = 0.9) -> None:
        # Each entry is one page's text. Newlines separate REGIONS, which
        # is the shape a real recogniser returns -- one entry per detected
        # line, joined with spaces into `text`. A fake that returned one
        # undivided blob would let the pipeline depend on structure the
        # real engine never provides.
        self._pages = list(pages or [])
        self._confidence = confidence
        self.calls = 0

    def read(self, page_gray) -> OcrResult:
        self.calls += 1
        if not self._pages:
            return OcrResult(text="")
        raw = self._pages[min(self.calls - 1, len(self._pages) - 1)]
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        # Synthetic boxes, one line per row, so title grouping is
        # exercised by the fake exactly as it is by the real engine.
        regions = tuple(
            TextRegion(
                text=line,
                confidence=self._confidence,
                box=(0.0, index * 40.0, 400.0, index * 40.0 + 30.0),
            )
            for index, line in enumerate(lines)
        )
        return OcrResult(
            text=" ".join(region.text for region in regions), regions=regions
        )

    def release(self) -> None:
        return None


class EasyOcrRecogniser:
    """EasyOCR, loaded lazily and released explicitly.

    Chosen over the alternatives for one disqualifying reason on each of
    them: `pytesseract` needs a system binary that is not present and pip
    cannot install; `rapidocr_onnxruntime` pulls `opencv-python` alongside
    this project's `opencv-python-headless`, and two cv2 distributions in
    one environment is a known breakage. EasyOCR adds no cv2 and reuses
    the torch already in the `ml` extra.

    Measured on a rendered 800x1040 page: reader construction 5.1 s once,
    then 1.19 s per page on CPU, 0.987 sequence similarity against the
    known rendered text.
    """

    name = "easyocr"

    def __init__(self, languages=("en",), gpu: bool = False) -> None:
        self._languages = list(languages)
        self._gpu = gpu
        self._reader = None

    def load(self) -> None:
        # Local import: easyocr is an optional [ocr] extra and nothing
        # outside a document-reading path may require it.
        import easyocr

        self._reader = easyocr.Reader(
            self._languages, gpu=self._gpu, verbose=False
        )

    def read(self, page_gray) -> OcrResult:
        if self._reader is None:
            self.load()
        raw = self._reader.readtext(page_gray)
        regions = tuple(
            TextRegion(
                text=str(entry[1]).strip(),
                confidence=float(entry[2]),
                box=_bounds(entry[0]),
            )
            for entry in raw
            if str(entry[1]).strip()
        )
        return OcrResult(
            text=" ".join(region.text for region in regions), regions=regions
        )

    def release(self) -> None:
        self._reader = None


def _bounds(polygon) -> tuple[float, float, float, float] | None:
    """EasyOCR gives four corner points; reduce them to an axis-aligned box.

    Axis-aligned is enough for the one thing the box is used for -- deciding
    which regions share a line -- and is stable under the small rotations a
    warped page still carries.
    """
    try:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
    except (TypeError, IndexError, ValueError):
        return None
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))
