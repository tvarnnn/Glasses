# Document Memory V1 — Implementation Report

Status: **IMPLEMENTED AND MEASURED ON SYNTHETIC PAGES; BLOCKED ON
DELIVERED CAMERA RESOLUTION.** Branch
`cartridge/experimental-cv-lab-v1`.

Every number below is a real measurement of this code on this machine.
The pages are **rendered**, so a *cost* is useful guidance and a *recall*
number describes clean printed text under ideal lighting — an upper bound
on what real footage will do, never a prediction of it. The standing
acceptance gate is unchanged: nothing counts as validation for the
platform's own camera until it runs on real DAT footage.

---

## 1. The product, and one correction to how it was asked for

The brief asked the system to recognise *"sustained document attention"*.

**It cannot, and V1 does not claim to.**
`07-PLATFORM-CONSTRAINTS.md` Limitation 8 is explicit: something
appearing in the glasses camera does not prove the user looked at it,
noticed it, read it, or understood it. There is no eye tracking on this
hardware and none is planned.

What the system can detect is **a page-like region persistently present
in the camera view, held steadily, long enough to be worth reading**.
That is a good proxy for reading and a poor synonym for it, and the
difference survives into every name: the record is
`DocumentObservation`, the fields are `observed_at`, `observed_seconds`,
`pages_observed`, and the CLI prints **OBSERVED, NOT READ**. Nothing in
the module is named `read` or `viewed`.

This is not pedantry about wording. The moment a stored record says
"read", every downstream answer inherits a claim the sensor cannot
support.

---

## 2. The measurement that shaped the architecture

**OCR costs ~1.2 s per page on this CPU.** Page detection costs **2.6 ms**
per frame at the delivered resolution. That is a ratio of roughly **400×**,
and it decides the whole design: the pipeline exists to make the expensive
stage *rare*, not to make it fast.

```
every frame     decode, detect a page, update dwell        ~2.6 ms
per dwell       pick the best one or two frames            free
per dwell       warp and OCR only those                    ~1.2 s each
```

A test pins it: twenty frames of a page in view produce **at most two**
OCR calls.

---

## 3. The finding that matters most, and it is not a Tower problem

Word recall — the fraction of a page's rendered words that OCR actually
captured, which is what makes a document findable at all:

| Frame size | Warped page | Word recall |
|---|---|---|
| 1280×720 | ~1026×636 | **0.957 – 1.000** |
| 896×504 | ~718×444 | 0.872 – 1.000 |
| 640×480 | ~514×424 | 0.905 – 1.000 |
| **640×360 — what the glasses deliver today** | ~514×318 | **0.429 – 0.810** |

**Tilt barely matters; resolution dominates.** Across a full range of
viewing angles at 640×480 the spread is only 0.905–1.000, which is the
evidence that perspective correction is doing its job. Pixels are the
problem: a page inside a 640×360 frame warps to roughly 500×320, putting
ordinary body text at about 10 px.

**Page detection still works at 640×360.** Only recognition is starved,
which narrows the requirement usefully — the cheap per-frame machinery is
fine, and only the one or two frames that get read need to be better.

`CARTRIDGE-GROUNDWORK.md` predicted this before a line of the cartridge
existed: *"Text/Document ... Missing: resolution negotiation. DAT's
adaptive ladder drops resolution first and cannot be overridden."* The
numbers turn a prediction into a requirement, recorded in
`docs/agent-handoffs/TOWER-TO-IOS.md` §6.8 with what iOS would need to
provide.

Why word recall rather than character similarity: OCR returns a receipt's
columns with the whitespace runs collapsed and occasionally a word
reordered (measured: *"days"* migrating to the end of a line). Sequence
similarity scores that as a failure. Lexical retrieval does not notice it,
because a document is findable if its distinctive **words** survived.

---

## 4. The OCR decision, with the disqualifier for each alternative

No OCR engine existed on this host: no `pytesseract`, no Tesseract
binary, no `easyocr`, no `paddleocr`, no `doctr`, no `onnxruntime`, no
`cv2.text`. `cv2.dnn_TextDetectionModel_DB` and
`cv2.dnn_TextRecognitionModel` exist as APIs but ship **no models**, and a
search of the installed `cv2` package finds zero `.onnx`, `.xml`,
`.caffemodel` or `.pb` files.

OCR is this cartridge's core, so a dependency earns its cost. Which one
was decided by elimination, not preference:

| Candidate | Verdict |
|---|---|
| `pytesseract` | **Rejected.** Needs the Tesseract *system binary*, which pip cannot install and which is not present |
| `rapidocr_onnxruntime` | **Rejected, and this is the one worth recording.** `pip install --dry-run` showed it pulls **`opencv-python` 5.0.0.93** alongside this project's `opencv-python-headless`. Two cv2 distributions in one environment is a known breakage, and the brief forbids destroying the working Tower environment |
| `doctr` | Rejected: heavier surface, no measured advantage on clean printed text |
| **`easyocr`** | **Chosen.** Dry-run showed 10 added packages and **no cv2 conflict** — it reuses the headless build and the torch already in the `ml` extra. Apache-2.0 |

Verified before designing around it: **1.19 s** per page, mean confidence
0.793, **0.987 sequence similarity** against known rendered text.

Environment change, recorded exactly: `easyocr`, `scipy`,
`scikit-image`, `imageio`, `tifffile`, `lazy-loader`, `ninja`,
`pyclipper`, `python-bidi`, `shapely`. `pip check` clean before and
after; suite unchanged at 583 passed either side. Declared as an optional
`[ocr]` extra, and a test asserts the Tower still imports without it.

---

## 5. Detection: two gates, because one is not enough

A closed laptop lid, a picture frame, a monitor bezel and a blank
whiteboard are all page-shaped. **Rectangle detection alone would call
every one of them a document.**

1. **Shape** — contour → `approxPolyDP` → a convex quadrilateral of
   plausible area, aspect and solidity.
2. **Text-likeness** — inside the warped quad, the fraction of *rows*
   whose ink stands out against the median row. Lines of text produce
   that structure; a blank sheet and a photograph do not. Measuring the
   fraction of *rows* rather than total darkness is what separates a page
   of text from a dark photograph.

Measured: a rendered page is found at tilts of 0.0, 0.5 and 1.0 with a
recovered-corner error under 6 px against the corners the fixture chose.
A blank page, a photograph filling the frame, and a textured scene with
no page are all correctly refused.

---

## 6. Retrieval is lexical, and says so everywhere

BM25 over stored OCR text, about forty lines, no dependency.

It matches a document containing the word "transformer". It does **not**
match a paraphrase that never uses the word. Every result carries
`match_kind: "lexical"`, the terms it matched on, and a snippet of the
captured text — so an answer is always traceable to text that was
actually captured. Calling this "semantic retrieval" would be the
overclaim Rule 16 exists to prevent.

One implementation note worth keeping: the textbook BM25 IDF goes
**negative** for a term appearing in most documents, which on a
three-document corpus would rank a document *down* for containing the
word that was asked for. The smoothed form is used and a test pins the
behaviour.

**Upgrade trigger, named:** when a measured query set shows lexical
recall failing on paraphrase, embeddings become justified.

**Scaling trigger, measured:** search recomputes the corpus per query —
0.32 ms over 10 documents, 4.63 ms over 100, **252 ms over 1000**. An
index becomes justified in the high hundreds. Storage is ~1.06 KB per
document, so a thousand documents is about a megabyte.

---

## 7. Anti-hallucination, as data rather than convention

- Every page stores the text OCR **actually returned**, with per-region
  confidence and region count.
- A page whose OCR found nothing is **still recorded**. "We looked and
  found no readable text" is a different fact from "we never looked".
- A query with no confident match returns `sufficient_evidence: False`
  and states that the refusal is about **what was captured, not about the
  world** (Core Principle 3).
- `coverage()` reports `pages_observed` with **`pages_total: None`**. The
  system cannot see pages it was never shown, and inventing a denominator
  would turn an observation gap into a claim of completeness.
- Document confidence is the **weakest** page's, not the average — a
  document is only as trustworthy as its worst-read page.
- Titles and summaries are **extractive**. A generated summary of
  partially-captured text would read as authoritative while describing
  pages nobody observed, and there is no local LLM path anyway.

---

## 8. Timing provenance

There is still no capture timestamp on the wire, so every timestamp is
`tower-receipt` time and says so.

A directory of loose jpegs carries **no timestamps at all**, so replaying
one must assume a frame interval to produce a duration. Rather than
hiding that in a driver, every document produced that way is stamped
`timing_source: "assumed-interval"` with the interval used. Frames from a
capture journal carry real receipt times and are stamped
`"capture-journal"`. An assumed duration can never be read as a measured
one.

---

## 9. Privacy

- **Derived text is persisted; page images are not, by default.** Keeping
  the corrected page image is opt-in and off. When enabled the record
  says `redaction: "none"` — because no redaction exists on this platform
  and, per `06-PRIVACY-DATA.md`, a crop is not inherently safe.
- **Raw frames are never persisted.** They live in memory for the dwell
  window and are dropped. A long dwell retains only the one or two frames
  that will actually be read.
- **Retention is a window**, defaulting to 30 days rather than forever.
- **Real purge**, per document and whole-store, reporting what it could
  not delete.

**One defect found here and fixed, by checking the claim rather than
trusting it.** `prune_expired()` dropped the journal record and nothing
else, so a document past its retention window was reported gone while the
image of it stayed on disk indefinitely — and because it returned a bare
count, a caller had no way to find out. It now deletes the pixels too and
returns purge's full report shape. Both paths share one deletion helper
so they cannot drift apart again.

---

## 10. What was deliberately not built

| Not built | Why |
|---|---|
| Embedding / semantic retrieval | No corpus to justify it, and BM25's explainability matters more while an answer must be traceable to captured text. Trigger named in §6 |
| An LLM summary | No local serving path, and an abstractive summary of partially-captured text is the exact fabrication the anti-hallucination requirement forbids |
| Voice queries | The brief says V1 does not require them. Building the voice layer first would have made the memory untestable |
| Cross-session document re-identification | "This is the same physical paper I read three weeks ago" needs appearance re-identification this cartridge has no evidence for |
| Multi-column reading order, handwriting, non-Latin scripts | Out of scope for a bounded V1, and unmeasurable without real footage |
| Any spatial anchor | The brief forbids fabricating one, and this cartridge cannot see a world |
| Registration as a production module | Same V1.0/V1.1 boundary as World Builder, plus 1.2 s of OCR could not sit on the event loop even if a slot were free |

---

## 11. Measured costs

Detection, which runs on **every** frame:

| Resolution | With a page | No page |
|---|---|---|
| 640×360 | 2.62 ms | 2.11 ms |
| 640×480 | 3.16 ms | 2.72 ms |
| 896×504 | 7.10 ms | 4.21 ms |
| 1280×720 | 14.73 ms | 8.94 ms |

The no-page column is the one that matters for a day of wearing: it is
the common case, and at the delivered resolution it costs 2.1 ms against
a ~300 ms frame interval — a 0.7% duty cycle.

Retrieval, and storage growth:

| Documents | `search_text` | `recent` | Bytes/document |
|---|---|---|---|
| 10 | 0.32 ms | 0.16 ms | 1072 |
| 100 | 4.63 ms | 1.13 ms | 1063 |
| 1000 | 252.25 ms | 10.51 ms | 1063 |

---

## 12. Limitations

- **Everything is synthetic.** Rendered pages, ideal lighting, no motion
  blur, no rolling shutter, no auto-exposure, no real paper texture.
- **Reading at the delivered resolution does not work** (§3). This is the
  blocker, and it is not a Tower one.
- **Retrieval is lexical**, so a paraphrase that shares no words with the
  document will not find it.
- **No page-order reconstruction.** Pages within one dwell are recorded in
  the order observed; nothing establishes that page 2 follows page 1 in
  the physical document.
- **A new dwell starting inside the same region is a new document.** Two
  documents read back-to-back without the camera moving would merge; the
  region test is the only separator.
- **Search recomputes the corpus per query** (§6).
- **Nothing validates that the wearer read anything.** By construction,
  and permanently, on this hardware.
