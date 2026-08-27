"""Library and session transport adapter for Document Memory.

Named after its cartridge, for the reason `world_builder.py`,
`world_builder_geometry.py` and `object_memory.py` are: an adapter named
after one cartridge cannot leak that cartridge's assumptions into the
next, because the next one gets its own file.

THIS FILE READS. IT DOES NOT DELETE, AND IT DOES NOT OCR.

`DocumentStore` can `purge()` and `prune_expired()`. Neither is reachable
from here and neither may become reachable -- an unauthenticated HTTP
endpoint that erases what a wearer read is not a feature. Deletion stays
with `scripts/document_query.py --purge`, where a human types it.
`DocumentMemoryEngine` can `observe()`. That is not reachable from here
either, and `test_the_result_channel_never_writes` fails on a call named
`observe` anywhere under `tower/results/`.

THE THREE ANSWERS, AND WHY TWO WOULD BE A LIE

`IOS-to-Tower.md` 3.5 is the sharpest requirement on this cartridge and
the easiest to get wrong:

    matched        documents were found
    notFound       the memory was searched and nothing matched
    noObservation  the memory holds nothing covering what was asked

Collapsing the third into the second lets a gap in what the glasses
happened to see read as a statement about the world. That distinction is
not decoration here -- it is this cartridge's ACTUAL STATE. On 9,199
frames of real first-person footage the page detector fired six times and
was wrong all six, and after `MIN_ROW_TRANSITIONS` was re-derived against
those same frames it fires zero times. A Tower asked "show me the parking
notice" today answers `no_observation`, and that is the truthful answer:
nothing has ever been recorded, and that is a fact about this platform's
camera, not about parking notices.

`RECORDING_LIMITATIONS` carries that on every response. A client that
renders an empty library as "no documents yet" would be inviting a person
to wait for something that is not coming.

THE LIST CARRIES A CHARACTER COUNT, NOT THE TEXT

`IOS-to-Tower.md` 3.2: "The list carries a character count, not the text,
so a list of documents is not also a bulk transfer of every document's
contents onto the phone. Full text is fetched when a person opens one."

That is the manifest/segment split `world_builder_geometry.py` already
uses, applied to the most sensitive data this platform handles.
`text_availability` is the typed form of iOS's `unknown` / `notReadable`
/ `extracted(characterCount:)`, and `not_readable` is a REAL ANSWER: "we
looked and found no readable text" is a different fact from "we never
looked", and the store records both.

NAMES THAT ARE PART OF THE CONTRACT

The duration field is `observed_seconds`, and it must never be renamed to
anything built on the word "viewing". `IOS-to-Tower.md` 3.3 asks for that
by name and gives the reason: "appearing in the camera does not establish
that the wearer looked at it, noticed it, or read it"; a field named for
viewing claims all three. iOS renders it as "In view 45s", never "viewed
for" or "read for". The literal banned spelling is not written out here,
because the vocabulary test in `tests/test_result_channel_isolation.py`
greps every string in this package for it -- docstrings included -- and a
rule that exempted the file explaining the rule is how the word gets back
in. That is also why this paragraph does not quote the test's own name.
"""

from tower.document_memory.records import TIME_BASIS
from tower.document_memory.retrieval import MIN_SCORE, DocumentMemory
from tower.document_memory.store import DocumentStore

# Opaque and dated, in the style of `object_memory.observations/2026-08-26`.
# Compared for equality only: never parsed, never ordered, never used to
# infer that one contract is newer than another.
LIBRARY_CONTRACT = "document_memory.library/2026-08-27"

# The three answers, as values a decoder can switch on.
ANSWER_MATCHED = "matched"
ANSWER_NOT_FOUND = "not_found"
ANSWER_NO_OBSERVATION = "no_observation"
ANSWERS = (ANSWER_MATCHED, ANSWER_NOT_FOUND, ANSWER_NO_OBSERVATION)

# The typed form of iOS's DocumentTextAvailability.
TEXT_UNKNOWN = "unknown"
TEXT_NOT_READABLE = "not_readable"
TEXT_EXTRACTED = "extracted"

DOCUMENT_CLAIM = "a-document-was-in-view-and-was-read"
IDENTITY_SCOPE = "no-document-identity-across-sightings"
ABSENCE_MEANING = "not-recorded-by-this-cartridge"

# The one honest redaction value this platform has. `records.py:36`:
# "'none' is the honest value for imagery this platform cannot redact".
# Carried at the envelope so a client that reads the header and stops
# still learns that no image here may be shown on a persisted surface.
IMAGERY_TREATMENT = "raw-ephemeral-not-served"

RETRIEVAL_KINDS = ("recent", "text", "observed_within")

# What this cartridge cannot do, as data rather than as a document
# somebody has to have read. Every response carries it.
RECORDING_LIMITATIONS = (
    {
        "limitation": "detection-rate",
        "detail": (
            "on 9,199 frames of real first-person footage the page "
            "detector fired 6 times and every one was a false positive (a "
            "venetian blind and a backlit keyboard). After "
            "MIN_ROW_TRANSITIONS was re-derived against those same frames "
            "it fires 0 times. An empty library on this platform is the "
            "expected result, not a sign that nothing was read"
        ),
    },
    {
        "limitation": "no-validated-positive",
        "detail": (
            "no capture on this platform has ever contained a sheet of "
            "paper, so the detector has never been shown a positive it "
            "was built for. The premise is untested rather than disproved"
        ),
    },
    {
        "limitation": "resolution",
        "detail": (
            "at the 360x640 the glasses deliver, EasyOCR returned zero "
            "dictionary words across 919 sampled real frames dense with "
            "screen text, at median confidence 0.056. Word recall on "
            "rendered pages at this geometry is 0.343-1.000 depending on "
            "tilt. A high-resolution still, not a higher stream, is the "
            "measured fix"
        ),
    },
)


def store_from_root(root, *, retention_days: float | None = None, clock=None):
    """Construct a `DocumentStore` for a configured root.

    Lives here, not in `tower/routes/documents.py`, so the route imports
    only this adapter -- the same rule that keeps
    `world_builder_geometry.store_from_root` and
    `object_memory.store_from_root` where they are.

    `retention_days` is accepted and NARROWS ONLY. It reaches the store
    as `retention_seconds`, and the store filters reads to that window.
    Note the asymmetry with Object Memory that a caller must not be
    misled about: `ObservationStore` persists the window it was written
    under and clamps to `min(persisted, requested)`. `DocumentStore`
    persists no such manifest, so it cannot clamp, and a reader asking
    for a wide window gets a wide window. `_retention_view` says exactly
    that rather than implying a guarantee that is not there.
    """
    seconds = None
    if retention_days is not None and retention_days > 0:
        seconds = retention_days * 86400.0
    return DocumentStore(root, retention_seconds=seconds, clock=clock)


def _retention_view(requested_days: float | None) -> dict:
    return {
        "requested_days": requested_days,
        # Honestly unknown, and said so. The store writes no retention
        # manifest, so this read cannot discover the window the WRITER
        # used. Reporting the requested value here would let a reader
        # believe it had learned the producer's promise.
        "writer_window_days": None,
        "writer_window_unavailable_reason": (
            "DocumentStore persists no retention manifest, so a reader "
            "cannot learn the window its writer used. A request here "
            "narrows this read and can never widen what was kept"
        ),
        "policy": "a reader may narrow this read; it cannot widen it",
    }


def _text_availability(document) -> dict:
    """Three states, and the character count that goes with one of them.

    `not_readable` is reachable and is a real answer: a page whose OCR
    returned nothing is still recorded, because "we looked and found no
    readable text" is a different fact from "we never looked".
    """
    characters = len(document.text)
    if not document.pages:
        return {"state": TEXT_UNKNOWN, "character_count": None}
    if characters == 0:
        return {"state": TEXT_NOT_READABLE, "character_count": 0}
    return {"state": TEXT_EXTRACTED, "character_count": characters}


def _provenance(document) -> dict:
    """Where this record came from, as a pointer into a recording.

    Nested under `kind: "frame-reference"` for the reason
    `object_memory._where` gives: at the top level a sequence number
    reads as a position, and under a frame reference it reads as what it
    is -- where in a recording, not where in a room.

    `page_source_seqs` is the sequence number of each frame that was
    actually OCR'd, at most two per document by construction. The other
    frames of the dwell contributed to `frames_considered` and left no
    per-frame trace, which is why both numbers are here.

    `capture_id` is UNVALIDATED and says so. It is the basename of the
    capture directory the session was following; nothing checks that such
    a capture still exists, and a client must not read it as a guarantee
    that the frames are still on disk.
    """
    return {
        "kind": "frame-reference",
        # Reserved, never populated. Document Memory does not know where
        # anything is in a room, and `test_document_memory_does_not_
        # import_another_cartridge` is what keeps it from inventing one.
        "spatial_ref": None,
        "capture_id": document.capture_id,
        "capture_id_validated": False,
        "page_source_seqs": [
            page.source_seq for page in document.pages if page.source_seq is not None
        ],
        "pages_without_source_seq": sum(
            1 for page in document.pages if page.source_seq is None
        ),
        "frames_considered": document.frames_considered,
        "frames_ocred": document.frames_ocred,
        "world_id": document.world_id,
        "world_session_id": document.world_session_id,
        # This pointer resolves into `data/captures/`, whose lifetime this
        # cartridge neither sets nor enforces.
        "imagery_retention": "capture-side",
    }


def _timing(document) -> dict:
    """How the clock that stamped this record was obtained.

    Three states, never collapsed. `assumed-interval` means no frame
    carried a receipt time and a synthetic clock was advanced instead --
    a duration derived that way is a reconstruction, and a client that
    rendered it identically to a measured one would be overclaiming.
    """
    return {
        "time_basis": TIME_BASIS,
        "source": document.timing_source,
        "assumed_frame_interval_s": document.assumed_frame_interval_s,
        "note": (
            "tower-receipt time: when this Tower received the frames, "
            "never when the glasses captured them. There is no capture "
            "timestamp anywhere on this wire"
        ),
    }


def _summary_view(document) -> dict:
    """One document, WITHOUT its text. The list shape.

    `title` may be null and a client must render that as a description of
    the RECORD -- "Untitled document" -- never as an invented name for
    the thing. It is one line, lifted from the document's own first text
    region, and iOS asks for it in the list knowing that.

    `summary` IS NOT HERE, and its absence is the point.

    `DocumentMemoryEngine._summarise` is the document's first forty words
    verbatim. That is an excerpt, not a summary, and forty words per
    document across a list is exactly the bulk transfer of contents that
    `IOS-to-Tower.md` 3.2 exists to prevent -- "a list of documents is
    not also a bulk transfer of every document's contents onto the
    phone". Serving it here would have honoured the letter of "the list
    carries a character count, not the text" while breaking it in fact,
    and the failure would have been invisible: the field is small, and
    nobody reviewing one response would notice that a hundred of them
    add up to the library.

    So the list says a summary EXISTS and where to get it, and
    `/documents/{document_id}` carries it beside the pages it came from.
    A caller that wanted it wanted the document.
    """
    return {
        "document_id": document.document_id,
        "claim": DOCUMENT_CLAIM,
        "identity": IDENTITY_SCOPE,
        "title": document.title,
        "title_is_derived": True,
        "summary_available": bool(document.summary),
        "summary_withheld_reason": (
            "the stored summary is the document's first forty words "
            "verbatim -- an excerpt, not a paraphrase. It is served with "
            "the document, never in a list, so a listing cannot become a "
            "bulk transfer of what a wearer read"
        ),
        "confidence": document.confidence.value,
        "confidence_basis": "the weakest page read in this document",
        "observed_at": document.observed_at,
        "recorded_at": document.recorded_at,
        # NEVER `viewing_duration`. Appearing in the camera does not
        # establish that the wearer looked at it, noticed it, or read it.
        "observed_seconds": document.observed_seconds,
        "observed_seconds_note": (
            "how long the region was in view. This platform cannot "
            "establish that the wearer looked at it or read it"
        ),
        "pages_observed": document.pages_observed,
        "text_availability": _text_availability(document),
        "end_reason": document.end_reason,
        "timing": _timing(document),
        "provenance": _provenance(document),
        "retains_raw_imagery": bool(document.retains_raw_imagery),
        "redaction": document.redaction,
        "imagery_treatment": IMAGERY_TREATMENT,
        "privacy_tags": list(document.privacy_tags),
        "schema_version": document.schema_version,
    }


def _page_view(page) -> dict:
    return {
        "page_index": page.page_index,
        "text": page.text,
        "text_source": page.text_source,
        "region_count": page.region_count,
        "mean_region_confidence": page.mean_region_confidence,
        "min_region_confidence": page.min_region_confidence,
        "confidence": page.confidence.value,
        "sharpness": page.sharpness,
        "squareness": page.squareness,
        "source_seq": page.source_seq,
        "observed_at": page.observed_at,
        # How many separate views of this page were merged into it. Two
        # readings of one page during one dwell is one page with an
        # observation count of two, not two pages.
        "observation_count": page.observation_count,
        # Present and null when no image was kept, which is the default
        # and must stay the default: a document's whole point is to be
        # readable and this platform has no redaction.
        "image_relpath": page.image_relpath,
    }


def _envelope(requested_days: float | None) -> dict:
    return {
        "contract": LIBRARY_CONTRACT,
        "claim": DOCUMENT_CLAIM,
        "identity": IDENTITY_SCOPE,
        "absence_means": ABSENCE_MEANING,
        "time_basis": TIME_BASIS,
        "spatial_ref": None,
        "answers": list(ANSWERS),
        "retrieval_kinds": list(RETRIEVAL_KINDS),
        "semantic_retrieval": False,
        "semantic_retrieval_unavailable_reason": (
            "this cartridge matches literal terms with BM25 and computes "
            "no embedding. Calling it semantic would be an overclaim, and "
            "a client routing a description here will get a lexical answer"
        ),
        "recording_limitations": [dict(entry) for entry in RECORDING_LIMITATIONS],
        "imagery_treatment": IMAGERY_TREATMENT,
        "retention": _retention_view(requested_days),
    }


def _answer_for(total_documents: int, found: int) -> str:
    """Which of the three answers this result is.

    The order matters: an empty MEMORY is `no_observation` whatever was
    asked, because there is nothing that could have matched. Only a
    non-empty memory can produce `not_found`.
    """
    if total_documents == 0:
        return ANSWER_NO_OBSERVATION
    return ANSWER_MATCHED if found else ANSWER_NOT_FOUND


def _no_observation_note(total_documents: int) -> str | None:
    if total_documents:
        return None
    return (
        "this Tower has recorded no documents at all. That is a statement "
        "about what its camera captured, never about what exists -- and on "
        "this platform it is the expected result: see recording_limitations"
    )


def recent_documents(store, *, limit: int = 10, requested_days=None) -> dict:
    """The most recent documents, newest first, without their text."""
    memory = DocumentMemory(store)
    total = store.count()
    documents = memory.recent(limit=limit)

    payload = _envelope(requested_days)
    payload["query"] = {"kind": "recent", "limit": limit}
    payload["answer"] = _answer_for(total, len(documents))
    payload["no_observation_note"] = _no_observation_note(total)
    payload["documents_in_memory"] = total
    payload["document_count"] = len(documents)
    payload["documents"] = [_summary_view(document) for document in documents]
    return payload


def documents_around(
    store, *, when: float, window_seconds: float = 900.0, requested_days=None
) -> dict:
    """Documents observed within a window of an instant.

    A RANGE, not an instant, and the distinction is iOS's: "this morning"
    and "around lunch" are approximate, and answering them exactly answers
    a different question.
    """
    memory = DocumentMemory(store)
    total = store.count()
    documents = memory.around(when, window_seconds=window_seconds)

    payload = _envelope(requested_days)
    payload["query"] = {
        "kind": "observed_within",
        "centre": when,
        "window_seconds": window_seconds,
    }
    payload["answer"] = _answer_for(total, len(documents))
    payload["no_observation_note"] = _no_observation_note(total)
    payload["documents_in_memory"] = total
    payload["document_count"] = len(documents)
    payload["documents"] = [_summary_view(document) for document in documents]
    return payload


def search_documents(
    store, *, text: str, limit: int = 5, min_score: float = MIN_SCORE,
    requested_days=None,
) -> dict:
    """Literal term matching over what was captured.

    Each match carries the snippet the score came from, so an answer is
    always traceable back to text that was actually read rather than to a
    number a client has to trust.
    """
    memory = DocumentMemory(store)
    total = store.count()
    result = memory.search_text(text, limit=limit, min_score=min_score)

    payload = _envelope(requested_days)
    payload["query"] = {"kind": "text", "text": text, "limit": limit}
    payload["answer"] = _answer_for(total, len(result.matches))
    payload["no_observation_note"] = _no_observation_note(total)
    payload["documents_in_memory"] = total
    payload["searched_documents"] = result.searched_documents
    payload["min_score"] = result.min_score
    payload["sufficient_evidence"] = bool(result.sufficient_evidence)
    payload["reason"] = result.reason
    payload["match_kind"] = "lexical"
    payload["document_count"] = len(result.matches)
    payload["documents"] = [
        dict(
            _summary_view(match.document),
            score=round(match.score, 4),
            matched_terms=list(match.matched_terms),
            snippet=match.snippet,
        )
        for match in result.matches
    ]
    return payload


def one_document(store, document_id: str, *, requested_days=None) -> dict | None:
    """One document WITH its pages and their text, or None.

    This is the only route that carries text, and it is per-document by
    design: a list that carried text would be a bulk transfer of
    everything a wearer read onto whatever asked for a list.

    `coverage` rides along because the two questions a person opening a
    document asks -- "what does it say" and "how much of it did you get"
    -- are one round trip, and splitting them invites a client to render
    the first without the second.
    """
    memory = DocumentMemory(store)
    document = store.read_one(document_id)
    if document is None:
        return None

    payload = _envelope(requested_days)
    payload["query"] = {"kind": "document", "document_id": document_id}
    payload["answer"] = ANSWER_MATCHED
    payload["no_observation_note"] = None
    payload["document"] = dict(
        _summary_view(document),
        # The two things a list may not carry, carried here where a
        # person has asked for this document specifically.
        summary=document.summary or None,
        summary_is_model_output=True,
        summary_is_verbatim_excerpt=True,
        pages=[_page_view(page) for page in document.pages],
        word_count=document.word_count,
    )
    payload["coverage"] = memory.coverage(document_id)
    return payload


# -- the session status, which travels on the result channel ------------

# Fields that advance without anything having happened. Excluded from the
# change revision so a heartbeat is distinguishable from news, exactly as
# `world_builder.VOLATILE_PATHS` does for `mapping_seconds`.
STATUS_VOLATILE_PATHS = (
    "session.started_at",
    "session.ready_at",
    "session.loading_seconds",
    "session.frames_offered",
    "session.frames_observed",
    "session.frames_skipped",
    "session.frames_dropped_not_running",
    "session.decode_failures",
    "session.pages_detected",
    "library.bytes",
)

_SESSION_ABSENT = {
    "state": "unavailable",
    "reason": (
        "no document capture session exists on this Tower "
        "(TOWER_DOCUMENT_CAPTURE is off). Documents recorded elsewhere "
        "are still served: this says nothing was recorded HERE"
    ),
}


class DocumentStatusProducer:
    """The session status, polled twice a second, without re-reading a file.

    Stat-gated for the reason `world_builder.py: _FileCache` is, and it
    is a requirement rather than an optimisation: the result hub polls
    every 0.5 s for as long as anyone is subscribed, and every figure in
    the `library` block below comes from parsing `documents.jsonl` end to
    end. Re-parsing an unchanged journal twice a second would make a
    subscription cost more than the capture it is watching, and the cost
    would grow with the library rather than staying flat.

    The gate is `(mtime_ns, size)`. Both, not either: a rewrite that
    preserved the size would slip past a size check, and a filesystem
    with coarse timestamps can produce two writes inside one tick.
    """

    def __init__(self, document_root, session, *, clock=None) -> None:
        self._root = document_root
        self._session = session
        self._clock = clock
        self._stamp = None
        self._summary = None

    def _library(self) -> dict:
        store = store_from_root(self._root, clock=self._clock)
        try:
            stat = store.path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            # No journal is not a failure. It is a Tower that has never
            # recorded a document -- which, on this platform, is the
            # expected state, and it is reported as an EMPTY library
            # rather than an unreadable one. Those are opposite claims.
            return {
                "available": True,
                "document_count": 0,
                "unavailable_reason": None,
                "newest_observed_at": None,
                "bytes": {"journal": 0, "images": 0, "total": 0},
                "location_disclosed": False,
            }
        except Exception:
            stamp = None

        if stamp is not None and stamp == self._stamp and self._summary is not None:
            return dict(self._summary)

        try:
            documents = store.read_all()
            summary = {
                "available": True,
                "document_count": len(documents),
                "unavailable_reason": None,
                "newest_observed_at": (
                    max(document.observed_at for document in documents)
                    if documents
                    else None
                ),
                "bytes": store.bytes_used(),
                # No path, ever. The channel already holds this rule for
                # World Builder and it is the channel's rule, not that
                # cartridge's.
                "location_disclosed": False,
            }
        except Exception:
            return {
                "available": False,
                "document_count": None,
                "unavailable_reason": (
                    "this Tower's document journal could not be read"
                ),
                "newest_observed_at": None,
                "bytes": None,
                "location_disclosed": False,
            }

        self._stamp = stamp
        self._summary = summary
        return dict(summary)

    def payload(self) -> dict:
        """What this Tower is doing about documents, and what it holds.

        Two halves that must not be confused, and the field names keep
        them apart: `session` is a live capture that may not exist at
        all, and `library` is what is on disk regardless of whether
        anything is running. A Tower reprocessing captures offline has a
        library and no session; that is a normal configuration, not a
        degraded one.

        The documents themselves are NOT here. They are bulk, they are
        text, and they belong on HTTP for the same reason World Builder's
        geometry does -- `tower/routes/ws.py` gives the result sender and
        the frame path one shared lock.
        """
        return {
            "contract_note": (
                "session progress only. The documents themselves are on "
                "HTTP: /documents, /documents/{document_id}, "
                "/documents/search"
            ),
            "claim": DOCUMENT_CLAIM,
            "identity": IDENTITY_SCOPE,
            "absence_means": ABSENCE_MEANING,
            "time_basis": TIME_BASIS,
            "library": self._library(),
            "session": (
                dict(_SESSION_ABSENT)
                if self._session is None
                else self._session.status()
            ),
            "recording_limitations": [
                dict(entry) for entry in RECORDING_LIMITATIONS
            ],
            "imagery_treatment": IMAGERY_TREATMENT,
        }


__all__ = [
    "ANSWERS",
    "ANSWER_MATCHED",
    "ANSWER_NOT_FOUND",
    "ANSWER_NO_OBSERVATION",
    "LIBRARY_CONTRACT",
    "RECORDING_LIMITATIONS",
    "STATUS_VOLATILE_PATHS",
    "documents_around",
    "one_document",
    "recent_documents",
    "search_documents",
    "DocumentStatusProducer",
    "store_from_root",
]
