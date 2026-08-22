# Module Concept — Document Memory

## Status

**PARTIALLY IMPLEMENTED** as of 2026-08-22. Promoted from the research
seed at `docs/superpowers/research/2026-08-20-document-memory-design.md`,
which remains the fuller survey of alternatives.

| Part | Status |
|---|---|
| Page detection, dwell tracking, best-frame selection, perspective correction | **CURRENTLY IMPLEMENTED** (`tower/document_memory/`) |
| OCR via EasyOCR, behind a substitutable seam | **CURRENTLY IMPLEMENTED** (optional `[ocr]` extra) |
| Persistence, retention window, real purge | **CURRENTLY IMPLEMENTED** |
| Retrieval by time, by content (lexical), by recency | **CURRENTLY IMPLEMENTED** |
| Query interface | **CURRENTLY IMPLEMENTED** as a CLI + Python API |
| Reading a page at the resolution the glasses deliver | **BLOCKED** — see Resolution below. This is the headline limitation |
| Semantic (embedding) retrieval | **PLANNED**, with a named trigger |
| Registration as a production module | **BLOCKED** at the same V1.0/V1.1 boundary as World Builder |
| Voice queries | **PLANNED**, deliberately out of V1 |
| Validation on real footage | **BLOCKED** on hardware |

Report: `reports/2026-08-22-document-memory-v1-report.md`.

## Goal

The wearer reads a document normally — no "scan this" workflow, no
flattening it on a table, no holding it still for the camera. Later they
ask *"what was that document I looked at about thirty minutes ago?"* and
get an answer grounded in text the system actually captured.

## What this module can and cannot know

**It cannot detect attention.** `07-PLATFORM-CONSTRAINTS.md` Limitation 8
is explicit: something appearing in the glasses camera does not prove the
user looked at it, noticed it, read it, or understood it. There is no eye
tracking on this hardware and none is planned.

What it detects is **a page-like region persistently present in the
camera view, held steadily, for long enough to be worth reading**. That is
a good proxy for reading and a poor synonym for it.

This governs the vocabulary, and the vocabulary is not decoration. The
record is `DocumentObservation`; the fields are `observed_at`,
`observed_seconds`, `pages_observed`; the CLI prints **OBSERVED, NOT
READ**. Nothing in this module is named `read` or `viewed`, and nothing
may be.

## Pipeline

```
frames (live capture or recorded)
   |
[every frame]  page-quad detection + text-likeness      ~2.6 ms
   |
[every frame]  dwell / stability tracking                 ~0 ms
   |
   +-- not a page, or not held --> discarded, nothing persisted
   |
[per dwell]    best-frame selection (sharpness x squareness)
   |
[per dwell]    perspective correction from the quad
   |
[1-2 per doc]  OCR                                       ~1.2 s
   |
               page assembly, dedup, extractive summary
   |
               persist derived text (not pixels)
   |
               retrieval: by time, by content, by recency
```

**The 400× cost ratio between detection and OCR is the whole design.**
The pipeline exists to make the expensive stage rare, not fast.

## The binding constraint: resolution

Measured word recall against known rendered text:

| Frame size | Word recall |
|---|---|
| 1280×720 | 0.957 – 1.000 |
| 640×480 | 0.905 – 1.000 |
| **640×360 — what the glasses deliver today** | **0.429 – 0.810** |

**Tilt barely matters once the page is warped; resolution dominates.** A
page inside a 640×360 frame warps to roughly 500×320, which puts a 34 px
rendered font at about 10 px — below what the recogniser needs.

Detection still works at that resolution. Only recognition is starved.

This is not a Tower problem and no Tower work fixes it.
`CARTRIDGE-GROUNDWORK.md` predicted it — *"Text/Document ... Missing:
resolution negotiation. DAT's adaptive ladder drops resolution first and
cannot be overridden"* — and the numbers above turn that prediction into
a requirement on the iOS/DAT side. It is recorded in
`docs/agent-handoffs/TOWER-TO-IOS.md`.

## Detection: three gates, not one

A closed laptop lid, a picture frame, a monitor bezel and a blank
whiteboard are all page-shaped. Rectangle detection alone would call every
one of them a document.

1. **Shape.** Contour → `approxPolyDP` → a convex quadrilateral of
   plausible area, aspect and solidity.
2. **Text-likeness.** Inside the warped quad, the fraction of ROWS whose
   ink content stands out against the median row. Lines of text produce
   that structure; a blank sheet and a photograph do not.
3. **Glyphs.** The median number of dark/light transitions ALONG an inky
   row. Gate 2 is necessary and badly insufficient on its own: venetian
   blinds, brick courses, floor tiles and a striped shirt all have rows of
   dark pixels, and an adversarial review drove a brick wall through
   detection, dwell, OCR and persistence. Text is many short runs per row;
   a slat is one. Measured — text 43–86, every structure above 0 —
   threshold 8.

### Known false negatives

The gates that keep a brick wall out are the same gates that keep these
out, so each is a trade-off rather than an oversight:

- **Sparse pages** — a title-only note or a business card falls below the
  text-row gate. A six-line receipt passes, so the boundary is narrow.
- **A page on a near-white desk** — Canny finds no border where page and
  surface share an intensity.
- **A page held closer than 98% of frame area** — rejected by
  `MAX_AREA_FRACTION`, which does contradict "the wearer reads normally"
  for anyone who holds reading material close.

Dark and dim pages are fine: Otsu adapts down to about 25% brightness.

## Retrieval is lexical, and says so

BM25 over stored OCR text. It matches a document containing the word
"transformer"; it does **not** match a paraphrase that never uses the
word. Every result carries `match_kind: "lexical"`, the terms it matched
on, and a snippet of the captured text, so an answer is always traceable.

Calling this "semantic retrieval" would be the overclaim Rule 16 exists to
prevent.

**Upgrade trigger, named rather than vague:** when a measured query set
shows lexical recall failing on paraphrase. Embeddings then become
justified; until then BM25 is forty lines, needs no dependency, and is
explainable — which matters more here, because a retrieval answer must be
traceable to text that was actually captured.

**Scaling trigger:** search recomputes the corpus per query. Measured at
0.3 ms over 10 documents, 4.6 ms over 100, **252 ms over 1000**. An index
becomes justified in the high hundreds.

## Anti-hallucination, as data rather than convention

- Every page stores the text OCR **actually returned**, its per-region
  confidence and its region count.
- A page whose OCR found nothing is still recorded. *"We looked and found
  no readable text"* is a different fact from *"we never looked"*.
- Retrieval returns matched text with the record it came from.
- A query with no confident match returns `sufficient_evidence: False`
  and states that the refusal is about **what was captured, not about the
  world** (Core Principle 3).
- `coverage()` reports `pages_observed` with **`pages_total: None`**. The
  system cannot see pages it was never shown, and inventing a denominator
  would turn an observation gap into a claim of completeness.
- Document confidence is the **weakest** page's, not the average: a
  document is only as trustworthy as its worst-read page.
- Titles and summaries are **extractive**. There is no LLM, and a
  generated summary of partially-captured text would read as
  authoritative while describing pages nobody observed.

## Timing provenance

There is still no capture timestamp on the wire, so every timestamp is
`tower-receipt` time and says so.

A directory of loose jpegs carries no timestamps at all, so replaying one
has to assume a frame interval. Every document produced that way is
stamped `timing_source: "assumed-interval"` with the interval used, so an
assumed duration can never be read as a measured one. Frames from a
capture journal carry real receipt times and are stamped
`"capture-journal"`.

## Privacy

Documents are the platform's clearest case of `06-PRIVACY-DATA.md`'s
Sensitive Visual Information: financial, medical, identity and private
correspondence appear as literal readable text, and a document's whole
point is to be read.

- **Derived text is persisted. Page images are not, by default.** Keeping
  the corrected page image is opt-in and off. When enabled the record
  says `redaction: "none"`, because no redaction exists on this platform
  and a crop is not inherently safe.
- **Raw frames are never persisted by this cartridge.** They live in
  memory for the dwell window and are dropped.
- **Real purge**, per document and whole-store, reporting what it could
  **not** delete. A purge that cannot remove everything must never be
  presented as success.
- **Retention is a window**, defaulting to 30 days rather than forever.
- **No third-party transmission.** OCR, indexing and retrieval are local.

## Spatial context

`world_id`, `world_session_id` and `frame_revision` are **supplied by a
caller or absent**. Nothing in this module derives them, and it must not
import World Builder — a test enforces that in both directions. Absent
means unknown, which is not the same as "nowhere".

The import ban has a second reason worth stating: **World Builder's blur
and motion gates would reject exactly the frames this cartridge wants.** A
held-still, high-detail view of a page has near-zero parallax and is
`insufficient_motion` to a mapper. This cartridge inverts World Builder's
signal, so sharing that code would mean sharing an assumption that is
wrong here.

## Query interface

Deliberately independent of any voice path. `scripts/document_query.py`
and the `DocumentMemory` Python API answer three questions:

```
--recent 5                      what have I looked at lately
--minutes-ago 30 --window 15    the one from about half an hour ago
--text "return policy"          the one about the return policy
```

A future Siri shortcut, custom wake word or iOS screen would sit **above**
this. None is required for the feature to work, and building the voice
layer first would have made the memory untestable.

## Integration boundary

Not a registered production module, for the same reason World Builder is
not: the module contract is a registry of one with a scalar-shaped result.
Additionally, 1.2 s of OCR could not sit on the event loop even if a slot
were free. A test pins non-registration.

It runs as an engine plus a driver, in a **separate process** from the
Tower, consuming a capture through `CaptureFollower` — live or recorded.

## Out of scope for V1

Named so nobody assumes otherwise: multi-document cross-referencing,
cross-session physical-document re-identification, handwriting,
non-Latin scripts, multi-column reading-order preservation, real-time
reading assistance, and any generated (as opposed to extracted) summary.
