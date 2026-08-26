# Document Memory V1 — implementation plan

**Status:** PLAN. Written 2026-08-22 on `cartridge/experimental-cv-lab-v1`
@ `8dc8e52`. Cartridge 2 of the sequential run.

**Reconciles:** `docs/superpowers/research/2026-08-20-document-memory-design.md`,
a 215-line design seed written before World Builder V1, before shared
capture infrastructure, and before the Lab had a measurement channel.

---

## 1. The product goal, stated honestly

The wearer reads a document normally. Later they ask *"what was that
document I looked at about thirty minutes ago?"* and get an answer
grounded in text the system actually captured.

**One correction to the brief's language, and it is not pedantry.**
`07-PLATFORM-CONSTRAINTS.md` Limitation 8: something appearing in the
glasses camera does not prove the user looked at it, noticed it, read it,
or understood it. There is no eye tracking on this hardware and none is
planned. So this cartridge cannot detect *attention*, and V1 will not
claim to.

What it can detect is **a page-like region persistently present in the
camera view, held steadily, for long enough to be worth reading**. That is
a good proxy and a poor synonym. Every field name, every log line and
every answer says *observed*, never *read* or *looked at*. The record
type is `DocumentObservation`, not `DocumentReading`.

---

## 2. What already exists that this must reuse

| Asset | Where | Use |
|---|---|---|
| Raw dataset recorder, armable in production | `tower/capture.py`, `TOWER_CAPTURE_ROOT` | The frame source |
| `CaptureFollower` | `tower/capture.py` | Process a session **as it is recorded**, in a separate process |
| `Confidence` label vocabulary | `tower/confidence.py` | Stored as a label, never a recomputed score |
| Append-only JSONL + atomic rewrite + real purge | `tower/object_memory/store.py`, `tower/world_builder/store.py` | The store shape two modules already converged on |
| `time_basis` discipline | both | There is still no capture timestamp on the wire |
| Synthetic ground-truth harness | `tests/synthetic_scene.py` | Rendering a page at a known pose, with known text |

**And what it must NOT reuse.** `CARTRIDGE-GROUNDWORK.md` is explicit that
World Builder's blur and motion gates would reject exactly the frames this
cartridge wants: a held-still, high-detail view of a page has near-zero
parallax and is `insufficient_motion` to a mapper. Document Memory
inverts World Builder's signal. It must not import it, and a test will
enforce that.

---

## 3. The OCR decision

No OCR engine existed on this host: no `pytesseract`, no Tesseract binary,
no `easyocr`, no `paddleocr`, no `doctr`, no `onnxruntime`, no `cv2.text`.
`cv2.dnn_TextDetectionModel_DB` and `cv2.dnn_TextRecognitionModel` exist
as APIs but ship no models, and a search of the installed `cv2` package
finds zero `.onnx`/`.xml`/`.caffemodel`/`.pb` files.

OCR is this cartridge's core, so a dependency clearly earns its cost. The
question is which one.

| Candidate | Verdict |
|---|---|
| `pytesseract` | **Rejected.** Needs the Tesseract *system binary*, which pip cannot install and which is not present |
| `rapidocr_onnxruntime` | **Rejected, and this is the important one.** A `pip install --dry-run` showed it pulls **`opencv-python` 5.0.0.93** alongside the project's existing `opencv-python-headless`. Two cv2 distributions in one environment is a known breakage, and the brief forbids destroying the working Tower environment |
| `doctr` | Rejected: heavier surface for no measured advantage on clean printed text |
| **`easyocr`** | **Chosen.** Dry-run shows 10 added packages and **no opencv conflict** — it reuses the headless build and the torch already in the `ml` extra. Apache-2.0 |

**Verified before designing around it**, on a rendered 800×1000 page:
`readtext` in **1.19 s** on CPU, mean confidence 0.793, and **0.987
sequence similarity against the known ground-truth text**. Reader init
5.1 s, paid once.

Environment change recorded exactly: `easyocr`, `scipy`,
`scikit-image`, `imageio`, `tifffile`, `lazy-loader`, `ninja`,
`pyclipper`, `python-bidi`, `shapely`. `pip check` clean before and
after; full suite 583 passed before and after. Declared as an optional
`ocr` extra, so a Tower that never reads a document never installs it.

**1.19 s per page is the whole reason for the architecture below.** OCR
cannot run per frame at any frame rate. It runs on a handful of selected
frames per document, which is exactly what the brief demands.

---

## 4. Pipeline

```
frames (from a capture, live or recorded)
   |
[cheap, every frame]   page-quad detection + text-likeness      ~2-4 ms
   |
[cheap, every frame]   dwell / stability tracking                 ~0 ms
   |
   +-- not a page, or not held --> discarded, nothing persisted
   |
[on dwell confirmed]   best-frame selection (sharpness, squareness)
   |
[a few per document]   perspective correction from the quad
   |
[a few per document]   OCR                                       ~1.2 s
   |
                       page assembly, dedup against recent pages
   |
                       extractive summary + metadata
   |
                       persist: text, confidence, timing, coverage
   |
                       retrieval: by time, by text, by recency
```

### 4.1 Detection — classical, not learned

A page is a bright, roughly rectangular, roughly convex region. Contour +
`approxPolyDP` finds it. The research seed already argued for starting
classical and escalating only if insufficient; nothing here needs a model.

**Text-likeness is a separate gate and it matters.** A closed laptop lid,
a picture frame and a blank whiteboard are all page-shaped. Requiring
gradient/edge density inside the quad consistent with lines of text
prevents "document detected" from meaning "rectangle detected".

### 4.2 Dwell — presence, not attention

A quad must be present, of stable size and position, for a minimum number
of consecutive frames **and** a minimum wall-clock duration. Both, because
frame rate is not fixed: at ~3.3 fps, "10 frames" is three seconds; at
12 fps it is under one.

> **Correction, 2026-08-26.** The delivered rate is **11.97 fps
> (83.5 ms)**, measured over 9,199 real frames — not the ~3.3 fps this
> paragraph called "delivered". **The design is unaffected, and that is
> the point.** Requiring a frame count *and* a wall-clock duration was
> chosen here precisely because the rate was not trusted, and
> `dwell.py:118-123` implements both, so a dwell means the same thing at
> either rate. Scene Understanding assumed the same wrong number and
> expressed its constants in frames alone; `max_misses = 5` was
> documented as 1.5 s and was really 0.42 s, which recounted people. See
> `research/2026-08-26-tracker-retune.md`.

A dwell ends when the quad is lost for a few consecutive frames — a page
turn, a glance away, or the wearer moving on.

### 4.3 Selection and OCR

Within a dwell, score frames by sharpness and how fronto-parallel the quad
is, and OCR only the best one or two. Warp with a homography from the
quad's corners first, so the wearer never has to hold a page flat to the
camera.

### 4.4 Dedup

Re-observing the same page must refresh a record, not create a second
one. Compared by normalised token overlap against the pages already stored
in the same session.

### 4.5 Retrieval — lexical, and labelled as such

Three queries, matching the brief:

- **by approximate time** — "about thirty minutes ago", as a window;
- **by content** — BM25 over the stored OCR text;
- **recent history** — the last N documents.

**BM25 is lexical, not semantic, and V1 will say so.** It matches a
document containing the word "transformer"; it does not match a paraphrase
that never uses the word. Calling that "semantic retrieval" would be the
kind of overclaim this project's rules exist to prevent. Embeddings are
the documented upgrade, with a named trigger: when a measured query set
shows lexical recall failing on paraphrase.

No new dependency for BM25 — it is about forty lines and it is
explainable, which matters more here than ranking finesse, because a
retrieval answer must be traceable to the text it came from.

### 4.6 Summary — extractive, not generated

Title candidate (the largest text region near the top), first lines, and
top distinguishing terms. **No LLM.** An abstractive summary of text the
system may have captured only partially is precisely the fabrication the
anti-hallucination requirement forbids, and there is no local LLM serving
path anyway.

---

## 5. Anti-hallucination, architecturally

The research seed's strongest requirement, and V1 implements it as data
rather than as a convention:

- every stored page carries the OCR text **actually recognised**, its
  per-region confidence, and the region count;
- a document records how many pages were **observed**, and never implies
  it saw a page it did not;
- retrieval returns matched text **with the record it came from**, so an
  answer is always traceable;
- a query with no sufficiently confident match returns an explicit
  **insufficient evidence** result, not a best guess;
- confidence survives from OCR to the answer as a **label**.

*"The paper doesn't mention X"* is not assertable from an observation gap
(Core Principle 3). The retrieval API returns "no matching record",
which is a statement about the store, not about the document.

---

## 6. Privacy

Documents are the clearest case of `06-PRIVACY-DATA.md`'s Sensitive
Visual Information: financial, medical, identity and private
correspondence appear as literal readable text, and a document's whole
point is to be read.

- **Derived text is persisted; page images are not, by default.** Storing
  the corrected page image is opt-in, off, and when enabled the record
  says `redaction: "none"` because no redaction exists on this platform.
  A crop is not inherently safe.
- **Raw frames are never persisted by this cartridge.** They live in
  memory for the dwell window and are dropped.
- **Real purge**, per document and whole-store, reporting what it could
  not delete.
- **Configurable retention**, defaulting to a bounded window rather than
  forever.
- **No third-party transmission.** OCR, indexing and retrieval are local.
- The descriptor declares `persists_data=True`,
  `retains_raw_imagery=False`, `supports_purge=True`.

---

## 7. Spatial context — the thing not to fabricate

The brief: *do not fabricate spatial anchors if World Builder cannot
provide them.*

`DocumentObservation` carries optional `world_id`, `world_session_id` and
`frame_revision` that a **caller may supply**. Nothing in this cartridge
derives them, and it must not import World Builder. Absent, they stay
`None` — which means unknown, not "nowhere".

---

## 8. Integration boundary

Same boundary as World Builder, for the same reasons: the module contract
is a registry of one with a scalar-shaped result, and 1.2 s of OCR could
not run on the event loop regardless. Document Memory V1 is an **engine
plus an offline/live driver**, consuming a capture through
`CaptureFollower` — the infrastructure the World Builder closeout built.

A test will pin non-registration, as World Builder's does.

---

## 9. Deliverables

1. `tower/document_memory/` — records, store, detector, dwell tracker,
   OCR seam, engine, retrieval.
2. An OCR seam with a **fake** implementation for tests, so the default
   suite neither downloads a model nor takes 1.2 s per assertion.
3. `scripts/document_memory_session.py` — drive a capture, live or
   recorded.
4. `scripts/document_query.py` — the query interface, independent of any
   future voice path.
5. A fixture document renderer with **known text**, so OCR and retrieval
   are evaluated against ground truth.
6. Benchmarks: detection cost per frame, OCR cost per page, retrieval
   latency, storage growth per document.
7. Architecture-boundary tests.
8. `guidelines/docs/modules/DOCUMENT-MEMORY.md` and a measured report.

## 10. Definition of done

Full suite green; new tests assert against independent truth (known
rendered text, known page counts, known query answers); OCR and retrieval
benchmarked; persistence and privacy semantics explicit and tested;
purge real; no fabricated spatial anchors; retrieval refuses rather than
guesses; adversarial review completed and findings fixed; docs updated;
committed clean.
