"""Frames in, observed documents out.

The whole shape of this file follows from one measurement: OCR costs
~1.2 s per page. That is roughly 400x the per-frame detection cost, so
the pipeline is built to make the expensive stage rare rather than fast.

    every frame     decode, detect a page, update dwell     ~3 ms
    per dwell       pick the best one or two frames         free
    per dwell       warp and OCR those                      ~1.2 s each

Nothing here runs on the Tower event loop. Like World Builder, this is an
engine plus an offline/live driver, because the module contract is a
registry of one with a scalar-shaped result and 1.2 s of OCR could not
sit on the frame path regardless.
"""

import logging
import re
import time
from dataclasses import dataclass

import cv2
import numpy as np

from tower.confidence import Confidence
from tower.document_memory.detect import detect_page, warp_page
from tower.document_memory.dwell import DwellPolicy, DwellTracker
from tower.document_memory.ocr import TextRecogniser
from tower.document_memory.records import (
    END_REASON_STOPPED,
    REDACTION_NONE,
    TIMING_ASSUMED_INTERVAL,
    TIMING_CAPTURE_JOURNAL,
    DocumentObservation,
    PageObservation,
)
from tower.storage import new_id

logger = logging.getLogger(__name__)

# Two pages whose text overlaps this much are the same page seen twice,
# not two pages. Chosen above the level ordinary prose shares by chance
# (common words alone rarely exceed ~0.4 between different pages) and
# below what re-OCR of the same page reaches (typically >0.85, since OCR
# is not deterministic across slightly different frames).
SAME_PAGE_TOKEN_OVERLAP = 0.65

# A page whose OCR produced fewer words than this is not a page worth
# remembering as text. It is still counted as observed.
MIN_WORDS_FOR_TEXT = 3

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenise(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def token_overlap(left: str, right: str) -> float:
    """Jaccard overlap of token SETS.

    Sets, not counts: a page re-observed produces the same vocabulary but
    not the same word frequencies, because OCR splits and merges words
    differently on each view.
    """
    a, b = set(tokenise(left)), set(tokenise(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_same_page(existing: str, incoming: str) -> bool:
    """Are these two OCR views of the same physical page?

    Only ever asked WITHIN one dwell, which matters: the dwell tracker has
    already established that both frames show the same region of the same
    size in the same place. So the only way they are different pages is
    that the page TURNED while the wearer held position -- which shows up
    as the same rectangle carrying different words.

    **Two views that both recognised NO text are the same page**, and this
    is the case worth spelling out. Overlap between two empty strings is
    zero, so a plain similarity test splits them into two pages and the
    record then claims two pages were observed when nothing at all was
    read. That is an observation gap reported as content.
    """
    existing_blank = not existing.strip()
    incoming_blank = not incoming.strip()
    if existing_blank and incoming_blank:
        return True
    if existing_blank != incoming_blank:
        # One view read text and the other did not. Same page, badly seen
        # once -- merging keeps the reading that succeeded.
        return True
    return token_overlap(existing, incoming) >= SAME_PAGE_TOKEN_OVERLAP


@dataclass(frozen=True)
class ObserveResult:
    """What happened to one frame. Cheap to produce, cheap to log."""

    outcome: str  # "no_page" | "dwelling" | "document"
    document_id: str | None = None
    in_dwell: bool = False
    page_detected: bool = False
    sharpness: float | None = None


class DocumentMemoryEngine:
    """Observes documents. Never claims anyone read one.

    `world_id` / `world_session_id` are **supplied by the caller or
    absent**. Nothing here derives them, and this module does not import
    World Builder -- a test enforces that. Absent means unknown, which is
    not the same as "nowhere".
    """

    def __init__(
        self,
        store,
        recogniser: TextRecogniser,
        policy: DwellPolicy | None = None,
        clock=time.time,
        *,
        capture_id: str | None = None,
        world_id: str | None = None,
        world_session_id: str | None = None,
        keep_page_images: bool = False,
        assumed_frame_interval_s: float | None = None,
    ) -> None:
        self._store = store
        self._recogniser = recogniser
        self._policy = policy or DwellPolicy()
        self._tracker = DwellTracker(self._policy)
        self._clock = clock
        self._capture_id = capture_id
        self._world_id = world_id
        self._world_session_id = world_session_id
        # OFF by default and it must stay that way. A document's whole
        # point is to be readable, this platform has no redaction, and
        # 06-PRIVACY-DATA is explicit that a crop is not inherently safe.
        self._keep_page_images = keep_page_images
        # A directory of loose jpegs carries no timestamps. Replaying one
        # has to assume a frame interval, and the assumption is recorded
        # on every document it produces rather than hidden here.
        self._assumed_interval = assumed_frame_interval_s
        self._synthetic_now: float | None = None
        self._frames_observed = 0
        self._documents_recorded = 0

    @property
    def frames_observed(self) -> int:
        return self._frames_observed

    @property
    def documents_recorded(self) -> int:
        return self._documents_recorded

    @property
    def in_dwell(self) -> bool:
        return self._tracker.in_dwell

    def observe(
        self,
        raw_bytes: bytes,
        *,
        received_at: float | None = None,
        source_seq: int | None = None,
    ) -> ObserveResult:
        """The cheap per-frame path. Raw pixels never leave this method."""
        at = self._timestamp(received_at)
        self._frames_observed += 1

        gray = _decode_gray(raw_bytes)
        if gray is None:
            # A bad frame is a missing frame, not a lost document: a
            # single undecodable frame in the middle of a dwell must not
            # discard the reading in progress.
            finished = self._tracker.observe(None, at=at)
            return self._resolve(finished, page_detected=False)

        candidate = detect_page(gray)
        diagonal = float(np.hypot(*gray.shape[:2]))
        finished = self._tracker.observe(
            candidate,
            at=at,
            gray=gray if candidate is not None else None,
            source_seq=source_seq,
            frame_diagonal=diagonal,
        )
        return self._resolve(
            finished,
            page_detected=candidate is not None,
            sharpness=None if candidate is None else candidate.sharpness,
        )

    def flush(self, reason: str = END_REASON_STOPPED) -> str | None:
        """End an open dwell because the stream ended.

        A wearer who is still reading when the session stops has still
        read; discarding that observation would lose exactly the document
        they were most engaged with.
        """
        finished = self._tracker.flush(reason)
        if finished is None:
            return None
        return self._record(finished)

    def release(self) -> None:
        self._recogniser.release()

    def _timestamp(self, received_at: float | None) -> float:
        """Real receipt time, or a stated assumption -- never a guess.

        With `assumed_frame_interval_s` set, frames advance a synthetic
        clock at that rate. That is the only way a batch of undated jpegs
        can produce a dwell duration at all, and every document it
        produces is stamped `timing_source: "assumed-interval"` so the
        duration can never be read as measured.
        """
        if received_at is not None:
            return received_at
        if self._assumed_interval is None:
            return self._clock()
        if self._synthetic_now is None:
            self._synthetic_now = self._clock()
        else:
            self._synthetic_now += self._assumed_interval
        return self._synthetic_now

    # -- internals -----------------------------------------------------

    def _resolve(self, finished, *, page_detected, sharpness=None) -> ObserveResult:
        if finished is not None:
            document_id = self._record(finished)
            return ObserveResult(
                outcome="document",
                document_id=document_id,
                in_dwell=self._tracker.in_dwell,
                page_detected=page_detected,
                sharpness=sharpness,
            )
        return ObserveResult(
            outcome="dwelling" if self._tracker.in_dwell else "no_page",
            in_dwell=self._tracker.in_dwell,
            page_detected=page_detected,
            sharpness=sharpness,
        )

    def _record(self, dwell) -> str:
        """The expensive path: warp, OCR, dedup, summarise, persist."""
        document_id = new_id()
        pages: list[PageObservation] = []
        # OCR returns one region per detected line, so the first region of
        # the first page IS the title line. Reconstructing a title by
        # splitting the joined text would be guessing at structure the
        # recogniser already gave us.
        title_candidate: str | None = None

        for index, frame in enumerate(dwell.best):
            page_image = warp_page(frame.gray, frame.candidate.corners)
            result = self._recogniser.read(page_image)

            duplicate = next(
                (page for page in pages if is_same_page(page.text, result.text)),
                None,
            )
            if duplicate is not None:
                # The same page seen twice within one dwell -- which is the
                # NORMAL case, since best-frame selection deliberately picks
                # two views of one page. Merge rather than duplicate, and
                # keep the higher-confidence reading.
                pages[pages.index(duplicate)] = _merge(duplicate, result, frame)
                continue

            if title_candidate is None:
                title_candidate = _title_from_regions(result.regions)

            relpath = None
            if self._keep_page_images:
                relpath = self._persist_page_image(document_id, index, page_image)

            pages.append(
                PageObservation(
                    page_index=len(pages),
                    text=result.text if result.region_count else "",
                    region_count=result.region_count,
                    mean_region_confidence=result.mean_confidence,
                    min_region_confidence=result.min_confidence,
                    confidence=result.confidence_label,
                    sharpness=frame.candidate.sharpness,
                    squareness=frame.candidate.squareness,
                    source_seq=frame.source_seq,
                    observed_at=frame.at,
                    image_relpath=relpath,
                )
            )

        document = DocumentObservation(
            document_id=document_id,
            observed_at=dwell.started_at,
            recorded_at=self._clock(),
            observed_seconds=dwell.seconds,
            pages=tuple(pages),
            title=title_candidate or _title_of(pages),
            summary=_summarise(pages),
            frames_considered=dwell.frames_considered,
            frames_ocred=len(dwell.best),
            end_reason=dwell.end_reason,
            confidence=_document_confidence(pages),
            capture_id=self._capture_id,
            timing_source=(
                TIMING_ASSUMED_INTERVAL
                if self._assumed_interval is not None
                else TIMING_CAPTURE_JOURNAL
            ),
            assumed_frame_interval_s=self._assumed_interval,
            world_id=self._world_id,
            world_session_id=self._world_session_id,
            retains_raw_imagery=self._keep_page_images,
            redaction=REDACTION_NONE,
        )
        self._store.append(document)
        self._documents_recorded += 1
        return document_id

    def _persist_page_image(self, document_id, index, page_image) -> str | None:
        ok, buffer = cv2.imencode(
            ".jpg", page_image, [int(cv2.IMWRITE_JPEG_QUALITY), 88]
        )
        if not ok:
            logger.warning("document memory: could not encode page image")
            return None
        filename = f"{document_id}-{index:02d}.jpg"
        self._store.write_page_image(filename, buffer.tobytes())
        from tower.document_memory.store import IMAGES_DIRNAME

        return f"{IMAGES_DIRNAME}/{filename}"


def _decode_gray(raw_bytes: bytes):
    """Decode, or return None. Never raises for bad input.

    Unlike the Lab, a bad frame here is not even a frame-scoped error --
    it is a missing observation in a sequence, and the dwell state machine
    already knows what to do with one of those.
    """
    if not raw_bytes:
        return None
    try:
        array = np.frombuffer(raw_bytes, dtype=np.uint8)
        return cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
    except cv2.error:
        return None


def _merge(page: PageObservation, result, frame) -> PageObservation:
    """Keep the better reading of the same page, and count both views."""
    from dataclasses import replace

    incoming_confidence = result.mean_confidence or 0.0
    existing_confidence = page.mean_region_confidence or 0.0
    if incoming_confidence <= existing_confidence:
        return replace(page, observation_count=page.observation_count + 1)
    return replace(
        page,
        text=result.text if result.region_count else page.text,
        region_count=result.region_count,
        mean_region_confidence=result.mean_confidence,
        min_region_confidence=result.min_confidence,
        confidence=result.confidence_label,
        sharpness=frame.candidate.sharpness,
        squareness=frame.candidate.squareness,
        observation_count=page.observation_count + 1,
    )


TITLE_MAX_CHARS = 90


def _title_from_regions(regions) -> str | None:
    """The document's first LINE, assembled from the regions that share it.

    A recogniser splits a heading across several regions -- "Attention",
    "Is All You Need" -- so taking the first region alone yields a
    one-word title. Regions arrive in reading order, so the title is the
    leading run whose vertical centre stays within half a line height of
    the first one.

    Extractive throughout. A GENERATED title for text that may have been
    captured only partially would read as a description of the document
    rather than of what was observed, which is the fabrication the
    anti-hallucination requirement forbids.
    """
    if not regions:
        return None
    first = regions[0]
    if first.y_centre is None or not first.height:
        return first.text.strip()[:TITLE_MAX_CHARS] or None

    tolerance = max(first.height * 0.6, 1.0)
    parts = []
    for region in regions:
        centre = region.y_centre
        if centre is None or abs(centre - first.y_centre) > tolerance:
            break
        parts.append(region.text.strip())
    title = " ".join(part for part in parts if part)
    return title[:TITLE_MAX_CHARS] or None


def _title_of(pages) -> str | None:
    """Fallback title when OCR returned no region structure.

    Extractive, always. A GENERATED title for text that may have been
    captured only partially is precisely the fabrication the
    anti-hallucination requirement forbids -- it would read as a
    description of the document rather than of what was observed.
    """
    for page in pages:
        words = page.text.split()
        if len(words) >= 2:
            title = " ".join(words)[:TITLE_MAX_CHARS]
            return title.rsplit(" ", 1)[0] if len(title) == TITLE_MAX_CHARS else title
    return None


def _summarise(pages) -> str:
    """The opening of what was actually captured. Extractive, always.

    Deliberately NOT an LLM summary. There is no local serving path, and
    more importantly a generated summary of partially-captured text would
    read as authoritative while describing pages nobody observed.
    """
    words = []
    for page in pages:
        words.extend(page.text.split())
        if len(words) >= 40:
            break
    if not words:
        return ""
    summary = " ".join(words[:40])
    return summary + ("..." if len(words) > 40 else "")


def _document_confidence(pages) -> Confidence:
    """The WEAKEST page's confidence, not the average.

    A document is only as trustworthy as its worst-read page, and
    averaging would let one crisp page hide one that was barely legible.
    """
    labels = [page.confidence for page in pages if page.text]
    if not labels:
        return Confidence.UNKNOWN
    order = [
        Confidence.UNKNOWN,
        Confidence.LOW,
        Confidence.MEDIUM,
        Confidence.HIGH,
    ]
    return min(labels, key=order.index)
