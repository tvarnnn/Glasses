"""Finding a document again, and refusing when it cannot be found.

Three questions, matching what a wearer actually asks:

- *"about thirty minutes ago"*  -> a time window;
- *"the one about transformers"* -> content;
- *"what have I read lately"*    -> recent history.

**The content search is LEXICAL, and this module says so in its own
output.** BM25 matches a document containing the word "transformer"; it
does not match a paraphrase that never uses it. Calling that "semantic
retrieval" would be an overclaim of exactly the kind `02-DEVELOPMENT-RULES.md`
Rule 16 exists to prevent, so every result carries `match_kind:
"lexical"` and the API name says `search_text`, not `search_meaning`.

Embeddings are the documented upgrade path, with a named trigger: when a
measured query set shows lexical recall failing on paraphrase. Until then
BM25 is forty lines, needs no dependency, and -- more important here than
ranking finesse -- is **explainable**: every result carries the terms it
matched on and a snippet of the text it matched in, so an answer is always
traceable back to text that was actually captured.

Nothing here ever synthesises an answer. It returns records, or it
returns nothing and says so.
"""

import math
import re
from dataclasses import dataclass, field

from tower.confidence import Confidence
from tower.document_memory.records import DocumentObservation

# Standard BM25 constants. k1 controls term-frequency saturation, b the
# length normalisation. These are the widely used defaults and there is no
# corpus here to tune them against -- tuning on three documents would be
# fitting noise.
BM25_K1 = 1.5
BM25_B = 0.75

# Below this a match is noise. Reported alongside every result so the
# threshold is visible rather than buried, and so it can be moved from
# data once a real query set exists.
MIN_SCORE = 0.10

_TOKEN = re.compile(r"[a-z0-9]+")

# Deliberately tiny. A large stopword list is a language model in
# disguise; these are the words that would otherwise dominate every score
# in English prose.
STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or
    that the this to was were will with""".split()
)


def tokenise(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in STOPWORDS]


@dataclass(frozen=True)
class Match:
    """One retrieved document, and why it was retrieved."""

    document: DocumentObservation
    score: float
    match_kind: str
    matched_terms: tuple[str, ...] = ()
    snippet: str = ""

    @property
    def document_id(self) -> str:
        return self.document.document_id

    def to_json_dict(self) -> dict:
        return {
            "document_id": self.document.document_id,
            "title": self.document.title,
            "observed_at": self.document.observed_at,
            "time_basis": self.document.time_basis,
            "observed_seconds": self.document.observed_seconds,
            "pages_observed": self.document.pages_observed,
            "confidence": self.document.confidence.value,
            "score": round(self.score, 4),
            "match_kind": self.match_kind,
            "matched_terms": list(self.matched_terms),
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class QueryResult:
    """Matches, or an explicit refusal. Never a fabrication.

    `sufficient_evidence` is the field that matters. A query with no
    confident match returns `False` and an empty `matches`, and a caller
    that renders that as "I don't have a record of reading that" is
    telling the truth. Rendering a best guess instead would not be.
    """

    query: str
    matches: tuple[Match, ...] = ()
    sufficient_evidence: bool = False
    reason: str = ""
    searched_documents: int = 0
    min_score: float = MIN_SCORE

    def to_json_dict(self) -> dict:
        return {
            "query": self.query,
            "sufficient_evidence": self.sufficient_evidence,
            "reason": self.reason,
            "searched_documents": self.searched_documents,
            "min_score": self.min_score,
            "matches": [match.to_json_dict() for match in self.matches],
        }


@dataclass
class _Corpus:
    documents: list[DocumentObservation]
    tokens: list[list[str]] = field(default_factory=list)

    def __post_init__(self):
        self.tokens = [tokenise(document.text) for document in self.documents]
        lengths = [len(token_list) for token_list in self.tokens]
        self.average_length = sum(lengths) / len(lengths) if lengths else 0.0
        # How many documents contain each term. A property of (corpus,
        # term) and NOT of the document being scored, which is why it
        # belongs here and not in `_bm25`.
        #
        # It used to be computed inside the per-document loop as
        # `sum(1 for token_list in corpus.tokens if term in set(token_list))`
        # -- so scoring D documents against T query terms rescanned the
        # whole corpus D*T times AND rebuilt a set per document per scan.
        # Exactly quadratic in library size: 25 documents 7.6 ms, 800
        # documents 9,532 ms, with ~99% of the query spent re-deriving a
        # number that never changed. One pass here costs 62 ms at 800.
        #
        # Arithmetically identical, not merely close: `containing` for a
        # given term took the same value on every iteration it was
        # recomputed, so hoisting cannot move a score. Pinned by
        # TestDocumentFrequencyIsCorpusWideAndComputedOnce, which checks
        # this map against the original expression term by term and holds
        # the three ranked scores the old code produced.
        self.document_frequency: dict[str, int] = {}
        for token_list in self.tokens:
            for token in set(token_list):
                self.document_frequency[token] = (
                    self.document_frequency.get(token, 0) + 1
                )


class DocumentMemory:
    """The read side. Read-only by construction -- it cannot write."""

    def __init__(self, store) -> None:
        self._store = store

    def recent(self, limit: int = 10) -> list[DocumentObservation]:
        """The most recently observed documents, newest first."""
        documents = self._store.read_all()
        documents.sort(key=lambda document: document.observed_at, reverse=True)
        return documents[:limit]

    def around(
        self, when: float, window_seconds: float = 900.0
    ) -> list[DocumentObservation]:
        """*"About thirty minutes ago"*, as a window rather than an instant.

        Ordered by how close each observation is to the asked-about time,
        because "about" is the operative word: the nearest document is
        the answer, and the window only bounds how far "about" stretches.

        `observed_at` is `tower-receipt` time, not capture time. Over the
        minutes-scale windows this API is for, the difference is far below
        the resolution of the question -- but a caller rendering an exact
        clock time must still label it as received (Rule 16).
        """
        documents = [
            document
            for document in self._store.read_all()
            if abs(document.observed_at - when) <= window_seconds
        ]
        documents.sort(key=lambda document: abs(document.observed_at - when))
        return documents

    def search_text(
        self, query: str, limit: int = 5, min_score: float = MIN_SCORE
    ) -> QueryResult:
        """Lexical BM25 over stored OCR text. Refuses rather than guesses."""
        documents = self._store.read_all()
        query_terms = tokenise(query)

        if not documents:
            return QueryResult(
                query=query,
                reason="no documents have been observed",
                searched_documents=0,
                min_score=min_score,
            )
        if not query_terms:
            return QueryResult(
                query=query,
                reason="the query contains no searchable terms",
                searched_documents=len(documents),
                min_score=min_score,
            )

        corpus = _Corpus(documents)
        scored = []
        for index, document in enumerate(documents):
            score, matched = _bm25(query_terms, corpus, index)
            if score < min_score:
                continue
            scored.append(
                Match(
                    document=document,
                    score=score,
                    match_kind="lexical",
                    matched_terms=tuple(sorted(matched)),
                    snippet=_snippet(document.text, matched),
                )
            )

        scored.sort(key=lambda match: match.score, reverse=True)
        if not scored:
            return QueryResult(
                query=query,
                reason=(
                    "no observed document contains these terms; this is a "
                    "statement about what was captured, not about what the "
                    "documents say"
                ),
                searched_documents=len(documents),
                min_score=min_score,
            )
        return QueryResult(
            query=query,
            matches=tuple(scored[:limit]),
            sufficient_evidence=True,
            reason="lexical match on stored OCR text",
            searched_documents=len(documents),
            min_score=min_score,
        )

    def coverage(self, document_id: str) -> dict | None:
        """What is known about a document, and what is not.

        Deliberately reports `pages_observed` with no `pages_total`. This
        cartridge cannot know how many pages a physical document has, and
        inventing a denominator would turn "we saw two pages" into "we saw
        two of two pages" -- an observation gap presented as completeness
        (Core Principle 3).
        """
        document = self._store.read_one(document_id)
        if document is None:
            return None
        return {
            "document_id": document.document_id,
            "pages_observed": document.pages_observed,
            "pages_total": None,
            "pages_total_note": (
                "unknown: the system cannot see pages it was never shown"
            ),
            "words_captured": document.word_count,
            "observed_seconds": document.observed_seconds,
            "frames_considered": document.frames_considered,
            "frames_ocred": document.frames_ocred,
            "confidence": document.confidence.value,
            "low_confidence_pages": [
                page.page_index
                for page in document.pages
                if page.confidence in (Confidence.LOW, Confidence.UNKNOWN)
            ],
        }


def _bm25(query_terms, corpus: _Corpus, index: int) -> tuple[float, set[str]]:
    tokens = corpus.tokens[index]
    if not tokens:
        return 0.0, set()

    length = len(tokens)
    total_documents = len(corpus.documents)
    frequencies = {}
    for token in tokens:
        frequencies[token] = frequencies.get(token, 0) + 1

    score = 0.0
    matched = set()
    for term in set(query_terms):
        term_frequency = frequencies.get(term, 0)
        if term_frequency == 0:
            continue
        matched.add(term)
        containing = corpus.document_frequency.get(term, 0)
        # The +0.5/+0.5 smoothing keeps IDF positive on a tiny corpus. On
        # three documents the textbook form goes NEGATIVE for a term that
        # appears in most of them, which would rank a document DOWN for
        # containing the word that was asked for.
        idf = math.log(
            1.0 + (total_documents - containing + 0.5) / (containing + 0.5)
        )
        denominator = term_frequency + BM25_K1 * (
            1 - BM25_B + BM25_B * length / max(corpus.average_length, 1.0)
        )
        score += idf * (term_frequency * (BM25_K1 + 1)) / denominator
    return score, matched


def _snippet(text: str, matched_terms, width: int = 160) -> str:
    """Text around the first matched term, so a match is checkable.

    A score alone asks the reader to trust the ranking. A snippet lets
    them see the words the system actually captured.
    """
    if not text:
        return ""
    lowered = text.lower()
    position = -1
    for term in matched_terms:
        found = lowered.find(term)
        if found != -1 and (position == -1 or found < position):
            position = found
    if position == -1:
        return text[:width]
    start = max(position - width // 3, 0)
    return ("..." if start else "") + text[start : start + width].strip() + "..."
