# Module Concept — Document Memory (Research Seed)

## Status

Research/design-seed proposal, not an approved module spec. This document is written in the style of `docs/modules/*.md` so it can be reviewed against that bar, but it lives under `docs/superpowers/research/` deliberately — it has not been promoted into `guidelines/docs/modules/` and nothing here authorizes implementation. "Document Memory" does not exist anywhere else in this repository's docs or code as of this writing; this is the first specification pass for the concept.

Like `docs/modules/WORLD-BUILD.md` and `docs/modules/OBJECT-MEMORY.md`, this is a concept seed to be revised once real implementation experience exists, not a mandate (`02-DEVELOPMENT-RULES.md` Rule 17).

## Goal

Let the wearer read a document naturally — no "scan this document" workflow, no flattening it on a table, no holding it still for the camera — and later ask questions that can only be answered from what was actually read, grounded in the text the system actually captured. This mirrors World Build's Passive Operation Requirement: a system that requires scanner-operator behavior from the wearer has failed the platform's premise that the glasses are a normal-use device, not a capture tool.

Example questions a working Document Memory should answer:

- What did that paper I read last week say about transformer attention?
- Did the syllabus mention a make-up exam policy?
- What was the return policy on that receipt I looked at?
- Summarize the third page of the handout from Tuesday's lecture.
- Have I read anything about depth estimation before?
- What did that whiteboard-adjacent handout say about the assignment deadline? (a boundary case with Environmental Memory — see Relationship to Other Modules, below)

And, just as important, questions it must correctly refuse:

- What did page 7 say? (if page 7 was never observed)
- Summarize the whole paper (if only three of eight pages were ever in frame)

## Intended Inputs

Primary:
- camera frames;
- frame timestamps;
- module/session metadata.

Possible future inputs:
- user voice queries ("what did that paper say about...");
- explicit "forget this document" / "pause Document Memory" commands;
- spatial/map context from another explicitly shared service, only if the architecture later supports it (do not assume cross-module data sharing exists — `docs/modules/OBJECT-MEMORY.md` states this same constraint and it applies identically here).

## Initial Sensor Profile Hypothesis

Document legibility depends far more on resolution than on frame rate — unlike Object Memory's tracking problem, a document is usually stationary relative to the wearer's head during a reading dwell. Early experiments may target:

- camera enabled;
- prefer the highest supported resolution over high frame rate (e.g., DAT's `high` 720x1280 tier, per `07-PLATFORM-CONSTRAINTS.md` Limitation 2's confirmed resolution ladder) at a modest frame rate (e.g., 7-15 FPS) rather than `medium`/`low` resolution at 30 FPS — this is a domain-specific tradeoff, not a general platform default;
- microphone optional, enabled only for voice-query interaction, same as Object Memory;
- audio output enabled when spoken responses/summaries are desired;
- `storagePolicy` should reflect that this module persists derived text/structured data, not raw frames, by default.

DAT's adaptive ladder degrades resolution before frame rate under bandwidth pressure (Limitation 2) — a degraded-resolution frame should lower OCR confidence expectations, not be treated as equivalent to a full-quality frame. Exact values must be verified against current DAT support and measured performance, per the same caveat `docs/modules/OBJECT-MEMORY.md` states for its own sensor profile.

## Candidate Pipeline

```text
camera frames
    |
document/page detection          (is a page-like rectangular region in view?)
    |
useful-frame selection            (dwell + stability + sharpness, not every frame)
    |
stabilization / perspective correction   (homography from detected page quad)
    |
OCR                                (candidate approaches surveyed below)
    |
page/document reconstruction       (assemble page -> document, track known page order)
    |
deduplication                      (same page seen again ≠ a new page)
    |
metadata extraction                (title, headings, page numbers, dates where present)
    |
provenance tagging                 (per `07-PLATFORM-CONSTRAINTS.md` Limitation 15)
    |
chunking                           (page/section-level chunks for retrieval)
    |
embeddings / indexing
    |
durable memory (module-owned store)
    |
retrieval
    |
grounded answer
```

This mirrors the shape of World Build's hybrid pipeline and Environmental Memory's `sensor stream -> perception -> relevance -> event extraction -> store -> retrieval` shape — deliberately, since Document Memory is architecturally a specialized case of "structured memory of something observed," not a new pipeline archetype. No specific model is selected at any stage below as part of this documentation pass; per the same discipline `docs/modules/WORLD-BUILD.md` and `docs/modules/VISUAL-QA.md` already use, model selection remains a later, separate, measurement-driven decision.

### OCR stage — candidate approaches (comparative judgment, not a selection)

Two broad families exist for local/offline OCR usable on a Windows Tower with an RTX 5070:

**Classical detection+recognition pipelines:**

- **Tesseract** — CPU-only friendly, ~10MB footprint, sub-second per page on clean scans. Strongest accuracy-to-speed balance for clean printed text (roughly 97-99% character accuracy on clean printed English, comparable to the others on this narrow case) but weakest on handwriting (~45% in independent benchmarks) and weak table/layout reconstruction. Apache 2.0 license. Lowest integration cost — no GPU, no model download, mature Python bindings.
- **EasyOCR** — easier install/use than Tesseract, better handwriting and mixed-script handling (~62% handwriting accuracy in the same class of benchmark), but roughly 3x slower and a ~500MB model footprint. Apache 2.0 license. GPU-capable but not GPU-required.
- **PaddleOCR** — the most feature-complete traditional pipeline: detection, recognition, table extraction, and layout analysis (PP-Structure) in one codebase. Best handwriting accuracy of the classical options (~73%) and best structured/table extraction (~79% row-level accuracy on multi-page tables vs. Tesseract's ~64%). A newer variant, PaddleOCR-VL-1.5 (released January 2026), reports 94.5% on the OmniDocBench v1.5 document-understanding benchmark, blurring the line with the VLM family below. Apache 2.0 license. Moderate integration cost (heavier dependency surface, PyTorch/Paddle runtime).
- **docTR** — tunable accuracy/latency tradeoff, Apache 2.0, moderate integration cost; a reasonable middle ground when neither Tesseract's speed nor PaddleOCR's feature breadth is the deciding factor.

**VLM-based document reading (single multimodal pass instead of detect-then-recognize):** models such as Qwen2.5-VL/Qwen3-VL, Surya, olmOCR, GOT-OCR2, and smaller purpose-built models (e.g., Nanonets-OCR2, Granite-Docling) read the whole page image and produce structured text/markup directly, rather than stitching together per-region recognition. Published benchmarks show these models handling handwriting, mixed layout, and in-context document understanding (e.g., "what does this table mean") meaningfully better than classical pipelines, at the cost of materially higher latency and GPU memory. A locally-hostable mid-size variant (e.g., a quantized 7B-class Qwen-VL model) is plausible on a 12GB-class RTX 5070, but a large flagship variant (70B+) is not. License terms vary by model/size and must be checked per model before adoption — some Qwen variants ship Apache 2.0, others carry more restrictive terms at larger sizes.

**Comparative judgment for this platform, without locking a selection:**

| Axis | Classical (Tesseract/EasyOCR/docTR) | PaddleOCR | Local VLM (Qwen-VL class, etc.) |
|---|---|---|---|
| Accuracy on clean printed text | High, comparable across all three | High | High |
| Accuracy on handwriting/mixed layout | Weak (Tesseract) to moderate (EasyOCR) | Best of the classical group | Best overall, per published benchmarks |
| Latency | Lowest (Tesseract), moderate (EasyOCR/docTR) | Moderate | Highest — full model forward pass per page |
| GPU/VRAM cost | None to low | Low to moderate | Moderate to high; must fit the Tower's actual available VRAM alongside any other loaded module models (`04-MODULE-SYSTEM.md` Model Resources) |
| Integration cost | Lowest (Tesseract) | Moderate | Highest — model serving, quantization, prompt/output-format design |
| License | Apache 2.0 (all three) | Apache 2.0 | Varies by model and size — verify per candidate |
| Structured layout/table support | Weak to none | Strong (PP-Structure) | Strong, but as free-form generation rather than a guaranteed schema |

A reasonable starting hypothesis for a bounded V1 (a single clean printed document, read normally, not photographed edge-on under poor lighting) is that a classical pipeline — Tesseract for speed or PaddleOCR for better structure/table handling — is sufficient and far cheaper to integrate and validate than standing up a local VLM serving path. The VLM family becomes more attractive once handwriting, complex multi-column academic layouts, or in-context table/diagram understanding become an actual requirement, not a hypothetical one. This is a hypothesis for the eventual measurement-driven decision, not the decision itself.

## Page-Turn Detection, Deduplication, and "Enough of a Page"

This is a real, bounded CV/heuristic problem, not a research programme. A concrete first-version approach:

1. **Page-quad detection.** Run a lightweight document-boundary/quad detector (a classical contour-based rectangle detector is a reasonable starting point, matching the "start classical, escalate only if insufficient" pattern already used in `docs/superpowers/research/2026-08-20-world-builder-foundations.md` for World Build's feature-matching stage) on a sampled subset of frames, not every frame. A "page-like" detection is a roughly rectangular, sufficiently large, plausibly fronto-parallel region.
2. **Dwell/stability gate.** Only treat a page as a genuine reading candidate once the quad is detected with low frame-to-frame motion (e.g., structural-similarity or simple pixel-delta threshold) for a minimum consecutive-frame/time window (e.g., roughly 1-2 seconds). A single-frame glance at a page-shaped object is not a reading event.
3. **Best-frame selection within the dwell window.** Rather than OCR every frame in the dwell window, score frames on sharpness (blur estimate) and fronto-parallel-ness (skew of the detected quad) and keep only the best one or two for the expensive OCR path — the same "keyframe, not continuous" principle World Build and Environmental Memory already apply to their own redundant-frame problems.
4. **Perspective correction.** Warp the selected frame(s) using a homography derived from the quad's corners before OCR, rather than asking the wearer to hold the page flat/frontal (that would violate the passive-operation premise).
5. **Completeness check.** "Enough of a page has been captured" is evaluated, not assumed: OCR text-region coverage over the detected quad area must exceed a threshold (e.g., a minimum fraction of expected text lines recognized above a confidence floor), OR a bounded max-dwell timeout is reached — whichever comes first. Whatever was actually captured is stored and tagged with its coverage/confidence estimate; a partial capture is stored as partial, never silently treated as a complete page (this is the Document Memory instance of Core Principle 4 — confidence must survive the pipeline).
6. **Page-turn event.** A page turn is inferred when the stable quad detection is lost (motion blur spike, quad leaves frame, or a large scene change) and a new stable quad subsequently appears with materially different OCR'd content. This increments a page counter within the current document/session.
7. **Deduplication.** Before storing a newly OCR'd page as new, compare it (via cheap text similarity — token overlap or embedding cosine — over the corrected page image or its OCR text) against the most recently stored pages in the current document/session. High similarity means "same page, re-observed" (e.g., the wearer glanced back at page 3), not a new page — merge/refresh confidence on the existing record rather than duplicating it. This is analogous to Object Memory's "low-value repeated detections should be sampled, merged, or discarded" relevance rule, applied to pages instead of tracked objects.

This is deliberately bounded: it does not attempt general document layout understanding, multi-column reading order, or cross-session document re-identification (recognizing "this is the same physical paper I read three weeks ago" from appearance alone) in the first version. Those are candidate V2+ extensions, not V1 requirements.

## Passive Capture Signals and the Explicit-Control Balance

The core product idea explicitly requires passive operation — the wearer does not say "remember this document" every time they read something, any more than World Build asks them to say "start scanning." At the same time, `06-PRIVACY-DATA.md`'s Core Principle (local-first, minimize raw retention, explicit dataset-recording-session discipline for anything closer to continuous capture) and the platform's general Sensitive Visual Information guidance (documents routinely contain sensitive/private content — financial statements, IDs, private correspondence, medical information) both argue against treating every document-shaped glance as worth remembering.

**Candidate passive signals**, in increasing order of confidence that a genuine reading event (not an incidental glance) is occurring:
- a page-like region detected in frame at all (lowest confidence — this alone should trigger nothing persistent);
- dwell time on a stable page-like region exceeding a threshold;
- text-region density within the detected quad consistent with an actual page of readable text, not a blank surface or a photo;
- sequential page progression (page 1, then page 2, then page 3 in order) — a strong signal of sustained reading rather than a single glance;
- repeated viewing of the same page/document across a session or across sessions — a strong signal the content matters to the wearer.

**Recommended stance: default passive-but-conservative, not default explicit-command-only.** Reasoning:
- An explicit-command-only default ("say 'remember this' every time") directly contradicts the product's stated premise — the wearer does not know weeks in advance which document they will later want to recall, so requiring an in-the-moment command defeats the feature's entire value proposition, exactly as World Build's Passive Operation Requirement argues a mandatory scan-command would defeat its value proposition.
- However, "passive" here must specifically mean the *dwell/stability/completeness heuristic above decides when a reading event is confident enough to persist*, not "OCR and store everything document-shaped in frame at all times." The heuristic in the Page-Turn Detection section already does this filtering — nothing is persisted from a single ambiguous glance.
- Raw frames should never be the thing persisted by this default-passive behavior: frames are held in memory only for the duration of the dwell/best-frame-selection window and discarded once the OCR/dedup decision is made, consistent with `06-PRIVACY-DATA.md`'s Raw Frame/Audio Retention section. This is what keeps "passive by default" compatible with "minimize raw retention by default" — the passivity applies to *triggering derived-data capture*, not to *retaining raw imagery*, which stays off by default regardless of the trigger.
- `06-PRIVACY-DATA.md`'s Explicit Dataset-Recording Sessions rules (manually started/stopped, clearly indicated while active) govern deliberate *raw* capture; they do not, by their own text, require every module's ordinary derived-data collection to be manually started per instance — Object Memory and Environmental Memory already operate this way (automatic relevance-filtered persistence of structured events, not raw video, without a per-object "remember this" command). Document Memory should follow the same pattern, not a stricter one, provided its relevance/completeness gate is at least as conservative as those modules' event filters — arguably more conservative, given documents' higher default sensitivity.
- The module should still expose: a clear, easily discoverable on/off toggle for the whole module (not merely a per-document opt-out, which would itself require noticing and reacting to captures as they happen — impractical for a passive feature); a visible indicator that Document Memory is the active module and processing frames, consistent with the platform's truthful-state discipline (`02-DEVELOPMENT-RULES.md` Rule 3); and a fast, discoverable "forget the last document" / "forget everything" action, alongside the full purge capability required below.

## Anti-Hallucination Requirement

**The system must know precisely which content was actually OCR'd/observed versus not, and this must be architecturally enforced, not merely a prompting convention.** This is Document Memory's instance of World Build's "unknown space must remain unknown" requirement, applied to text instead of geometry:

- Every stored page/chunk record must carry the OCR text actually recognized, per-region/line confidence, and which page number (if determinable) it corresponds to within the document.
- A document's record must explicitly track which pages/sections are known (actually captured) versus unknown (never observed) — never silently treat "not captured" the same as "captured and found nothing relevant" or "confirmed the document doesn't cover this." This is Core Principle 3 (absence of observation ≠ observation of absence) applied specifically to documents: "the paper doesn't mention X" is only assertable if the relevant section was actually observed and does not mention X; if that section was never seen, the only correct answer is "I don't have a record of reading that part of the document."
- The retrieval/answer stage must be strictly grounded in retrieved, actually-stored OCR text (a retrieval-augmented pattern, not a model paraphrasing from a title, genre, or general knowledge about what such a document probably says). If retrieval returns no sufficiently confident match for a query, the module must return an explicit "insufficient evidence" response — the same first-class status `docs/modules/VISUAL-QA.md` already requires — rather than a plausible-sounding fabrication.
- Confidence must survive from OCR through chunking, embedding, and retrieval to the final answer (Core Principle 4): a low-confidence OCR region should not silently become a confidently-stated answer.

## Persistence, Retention, Purge, and Third-Party Transmission

Document Memory owns its own data namespace (e.g., `modules/document_memory/data/`), per `04-MODULE-SYSTEM.md` Persistence and `06-PRIVACY-DATA.md` Module-Owned Persistent Data.

**What is persisted:**
- OCR'd text per page, with per-region/line confidence and page-order metadata;
- document-level metadata: title/headings where extractable, known-page count vs. total-page count (if determinable), first/last-observed timestamps, session identifiers;
- embeddings for retrieval;
- provenance fields per `07-PLATFORM-CONSTRAINTS.md` Limitation 15 (which sensor/model produced this, when observed, OCR confidence at creation time, whether/how it was later deduplicated or merged).

**What is not persisted by default:**
- continuous raw video;
- raw camera frames beyond the in-memory dwell/best-frame-selection window (see above);
- the corrected page image itself, unless a specific future feature (e.g., "show me the original page") explicitly justifies retaining it — and if so, that image is treated with the same sensitivity as any stored crop under `06-PRIVACY-DATA.md`'s Sensitive Visual Information section ("selected crops... are not inherently safe"), not as a lower-risk derivative.

**Retention:** configurable, not indefinite-by-default. Given documents' elevated default sensitivity (financial, medical, identity, and private-communication content are all plausible), Document Memory's default retention window should be at least as conservative as Environmental Memory's, and its retention/deletion behavior must be actually implemented — not merely documented — before it is used to collect real data, mirroring the requirement `docs/modules/ENVIRONMENTAL-MEMORY.md` states for itself.

**Purge:** a real, verifiable deletion capability (per-document and whole-module) is required, not merely hiding data from the query interface (`06-PRIVACY-DATA.md` Deletion / Clear-Memory Behavior).

**Third-party transmission:** none by default. OCR, embedding, indexing, retrieval, and answer synthesis all run on the local Tower, following `docs/modules/VISUAL-QA.md`'s Local AI precedent — this module is, if anything, a *stronger* case for that stance than Visual Q&A, since it persists document content rather than only processing it transiently. Any exception requires the full documented process in `06-PRIVACY-DATA.md` (justification, explicit opt-in, disclosure, minimization, retention review) — never a silent default.

## Relationship to Other Modules

Following the discipline `docs/modules/ENVIRONMENTAL-MEMORY.md` already applies to its own relationship with Object Memory and World Build: do not merge, do not assume a dependency, and treat any future shared service as an explicit architecture evolution triggered by real, concrete requirements, not something adopted in advance.

- **Object Memory.** Object Memory tracks physical objects (including, potentially, a "book" or "folder" as a physical object with a last-seen location). Document Memory owns the *textual content* of what was read, independent of the physical object's location history. These are genuinely different concerns — one module's confidence signal is spatial/appearance re-identification, the other's is OCR/text-retrieval confidence. Do not merge them. If a future query like "where is the physical copy of the paper I read about X" is wanted, that requires an explicit cross-module association between an Object Memory record and a Document Memory record — a future integration, not an assumed one.
- **Environmental Memory.** Environmental Memory's `TEXT_SEEN` event type already covers generic OCR'd text encountered in the environment (signs, whiteboards, storefronts) as single, relatively shallow observations. Document Memory is a deeper, specialized case: multi-page reconstruction, page-order tracking, deduplication across a reading session, and retrieval-grounded question answering over accumulated text — closer to reading comprehension than to environmental novelty detection. Do not fold Document Memory into Environmental Memory's event model. If both modules eventually need the same low-level OCR/text-detection component, that shared component can be promoted explicitly once duplication is a measured cost, exactly as `docs/modules/ENVIRONMENTAL-MEMORY.md` already reserves for its own relationship with Object Memory.
- **Visual Q&A.** Visual Q&A answers an in-the-moment question about the current camera view, including reading text right now (its `READ_TEXT` task-routing path). Document Memory answers a *later* query about something read previously. They are temporally distinct: Visual Q&A is synchronous/interactive, Document Memory is retrieval-over-history. A future integration could let Visual Q&A consult Document Memory as a lookup source ("does this look like something I've read before"), or let Document Memory reuse a shared OCR component if Visual Q&A's OCR path is already validated and stable — again, an explicit future integration, not an assumed coupling in either module's first version.
- **Canonical/cross-module memory substrate.** See the companion document, `docs/superpowers/research/2026-08-20-canonical-memory-architecture.md`. Document Memory should be designed and built as a fully self-contained module now, per `02-DEVELOPMENT-RULES.md` Rule 6 (modules own their data) and `04-MODULE-SYSTEM.md` Persistence ("storage technology may differ by module. Do not impose a universal database prematurely"). It should integrate with a shared memory substrate only if/when that companion document's trigger condition actually fires — not in anticipation of it.

## Failure Behavior

If OCR/page-detection confidence is low:
- record the low confidence, do not silently discard it or overwrite a prior stronger observation of the same page;
- never present a low-confidence or partial OCR result as if it were a complete, confident reading of the page.

If retrieval finds no sufficiently confident match for a query:
- return "insufficient evidence" / "I don't have a record of reading that," per the Anti-Hallucination Requirement above — never fabricate content to satisfy the question, and never create a memory record retroactively to satisfy a query (the same rule `docs/modules/ENVIRONMENTAL-MEMORY.md` states for itself).

If the tower is unavailable:
- the module is unavailable;
- no false memory updates occur, and no query is answered from a stale or partial local cache presented as current.

## Privacy

Documents are one of the platform's clearest cases of the standing risk `06-PRIVACY-DATA.md`'s Sensitive Visual Information section describes generically: financial statements, medical information, IDs, private correspondence, and confidential material routinely appear as literal readable text, not merely as background context. Unlike a bystander's face incidentally in a wide shot, a document's entire point is to be read — Document Memory's core function is exactly the thing the platform's privacy policy is most cautious about. This argues for:
- preferring structured OCR text/embeddings over retained page imagery whenever the feature's actual requirement allows it (per `06-PRIVACY-DATA.md` Data Minimization), even more strictly than Object/Environmental Memory's already-similar guidance;
- a retention default at least as conservative as Environmental Memory's, not merely matching it;
- treating any retained page image, if a future feature genuinely requires one, as no safer than a full frame — the same "a crop is not inherently safe" principle `docs/modules/OBJECT-MEMORY.md` and `06-PRIVACY-DATA.md` both state;
- real, working purge/retention behavior implemented before this module is used to collect data from real documents, not merely documented as a future intention.

## First-Version Success Criteria

A bounded, credible V1 is single-document, single-session OCR-and-retrieve — not general document understanding, not cross-document reasoning, not real-time reading assistance. Concretely:

1. reliable page-quad detection and page-turn event detection on real handheld, first-person document footage (measured precision/recall on page-boundary events against a labeled test session);
2. working deduplication — re-viewing the same page during the same session does not create a duplicate page record;
3. OCR accuracy measured against a ground-truth transcript for a small test document (clean, printed, single-column — not handwriting, not a complex multi-column layout);
4. correct retrieval and grounded answers to a small labeled set of test questions about that document, including at least one question deliberately targeting an unread page, correctly answered as "not observed" rather than fabricated;
5. a working, verifiable purge for that document's stored data;
6. measured end-to-end latency and resource usage for the OCR/indexing pipeline.

Explicitly out of scope for V1: multi-document cross-referencing, cross-session physical-document re-identification, handwriting, non-Latin scripts, complex academic multi-column layout preservation, and real-time "reading companion" assistance while the wearer is still reading. These are candidate future extensions once the bounded V1 above is demonstrated, per the same "do not require full [X] for the first version" discipline `docs/modules/OBJECT-MEMORY.md` and `docs/modules/ENVIRONMENTAL-MEMORY.md` both apply to their own first versions.
