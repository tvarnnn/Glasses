# Research — Canonical Glasses Memory Architecture

## Status

Research/design recommendation. Not an implementation plan and not authorization to build a shared memory service. This document exists to answer one question ahead of Document Memory's design (see the companion document, `2026-08-20-document-memory-design.md`): should Document Memory, Object Memory, and Environmental Memory share a common memory substrate, and if so, how much of one, right now?

As of this writing, **zero** memory-accumulating modules have been implemented. Object Memory and Environmental Memory are specs only (`guidelines/docs/modules/OBJECT-MEMORY.md`, `guidelines/docs/modules/ENVIRONMENTAL-MEMORY.md`); Document Memory has no spec until this pass creates one. There is no real cross-module evidence yet about what a shared substrate would actually need to do.

## Governing Principles This Recommendation Must Respect

- **Rule 6 (Modules Own Their Data)** — `guidelines/docs/02-DEVELOPMENT-RULES.md`: "Module-specific persistence stays inside the module by default. Promote data to a shared service only when a concrete cross-module requirement exists."
- **Rule 10 (No Premature Scope Expansion)** — do not implement future roadmap features while completing an earlier milestone unless required for it.
- **04-MODULE-SYSTEM.md — Persistence**: "Each module owns a data directory/storage namespace... Storage technology may differ by module. Do not impose a universal database prematurely."
- **03-ROADMAP.md's "generalize only when justified" sequencing**: the module registry itself is not generalized until "a second production module creates real, concrete requirements" (V1.0). The same discipline should govern memory infrastructure — arguably more so, since memory schemas are harder to migrate later than a registry API.
- **07-PLATFORM-CONSTRAINTS.md Limitation 15 (Sensor Authority / Provenance)** already states, as a general architectural requirement, that future observation data should be able to answer: which sensor produced this, when was it observed, was it measured or inferred, which module/model produced an inference, what confidence existed at creation, was it later fused with other evidence. This is the direct ancestor of the "observation record" shape recommended below — it is not a new idea, it is this existing requirement made concrete enough for three memory modules to actually use it.
- **06-PRIVACY-DATA.md** — module-owned data namespaces, per-module purge/retention requirements, "selected crops are not inherently safe," prefer structured/derived data over raw imagery.

The conclusion these principles point to is not "no shared design" — Limitation 15 already commits the platform to *some* common provenance discipline — but "no shared *service*." A shared conceptual record shape that each module implements independently, inside its own storage, costs nothing to adopt now and creates no coupling. A shared *database*, *retrieval API*, or *cross-module access layer* would be exactly the kind of premature generalization Rule 10 and the roadmap's sequencing exist to prevent, especially with zero real modules built to validate the requirements.

## What Future Memory Modules Have in Common (Surveyed)

Reading the existing specs and this document's Document Memory companion side by side:

| Concern | Document Memory | Object Memory | Environmental Memory | World Build (future spatial) |
|---|---|---|---|---|
| Observes | document/page content via OCR | tracked physical objects | text, scenes, landmarks, events | 3D structure/geometry |
| Core question answered | "what did X say" | "where/when was X last seen" | "what changed/what did I see" | "what does the space look like" |
| Identity problem | same document across sessions | same object instance vs. class (Limitation 6) | place revisited vs. new place | same physical region re-observed |
| Confidence problem | OCR/extraction confidence, retrieval relevance | detection/tracking confidence, re-ID confidence | detection/OCR/novelty confidence | geometric/depth confidence (Limitation 1) |
| Staleness problem | "did I actually read this" vs. inferred | "last seen" ≠ "currently at" (Limitation 7) | "not observed" ≠ "confirmed unchanged" (Limitation 7) | unobserved region ≠ empty region |
| Privacy exposure | financial docs, bystander material, screens | bystander backgrounds in crops | highest of current module set — bystanders, private spaces, locations | bystanders, private spaces, location |
| Storage shape | text/chunks + embeddings + provenance | events + embeddings + crops (optional) | events + text index + embeddings | keyframes + geometry + confidence |

The genuinely common thread is not the *content* (text vs. object track vs. event vs. geometry — these are irreducibly different) — it's the **wrapper**: every one of these modules needs a way to say "here is a piece of information, this is where it came from, this is when it was true, this is how sure I am, and this is how sensitive it might be." That wrapper is exactly what Limitation 15 already asks for. The content payload inside the wrapper should stay module-specific.

## Recommendation

**Do not build a shared memory service, shared database, shared retrieval API, or shared embedding index now.** Each of Document Memory, Object Memory, and Environmental Memory keeps its own storage namespace and its own query interface, per Rule 6 and `04-MODULE-SYSTEM.md`.

**Do adopt a common conceptual "observation record" shape now**, informally, inside each module's own storage — no coordination, no shared code required, no new infrastructure. This costs nothing today and pays off in two ways: (1) it operationalizes the provenance requirement `07-PLATFORM-CONSTRAINTS.md` already imposes, instead of leaving it as an unenforced aspiration each module reinvents differently; (2) if a second and third memory module later demonstrate a real, concrete need for cross-module retrieval or a shared substrate, the migration is a schema mapping, not an archaeology project across three incompatible ad hoc designs.

### The Recommended Observation Record Shape (Conceptual — Not a Schema)

This is a set of fields each module should be able to answer for anything it persists, not a table definition, not a required storage technology, and not a mandated field name. Each module implements this however fits its own storage choice (a table, a JSON document, a set of columns — `04-MODULE-SYSTEM.md` explicitly leaves storage technology to the module).

```text
observation_id            — unique within the owning module's namespace
owning_module             — which module created/owns this record (redundant with
                             namespace, but explicit — useful once/if anything ever
                             crosses namespaces)
observation_timestamp     — when the thing was actually observed/true (capture time,
                             not arrival/processing time — Core Principle 5)
record_created_timestamp  — when the module wrote this record (kept distinct from
                             observation_timestamp per Core Principle 5 / Limitation 9)
source_type               — camera_frame | ocr_text | audio | user_explicit_input |
                             derived_from_other_observation | ... (module-defined enum)
measurement_or_inference  — was this measured directly or produced by ML inference
                             (Core Principle 2) — most module data will be "inference"
confidence                — numeric or categorical, including an explicit UNKNOWN /
                             not-yet-evaluated state (Core Principle 4) — must be
                             preserved through any later fusion, summarization, or
                             cross-module consumption, not silently dropped
producing_model_or_method — what algorithm/model (+ version, where practical)
                             produced this, satisfying Limitation 15's "which
                             module/model produced an inference"
content_ref                — pointer to the module-specific payload (text, crop,
                             embedding, event data) — the payload itself is NOT part
                             of this shared shape; each module defines its own
external_refs (optional)  — loose, non-enforced references to related observations
                             in another module's namespace, e.g. {module: "object_memory",
                             observation_id: "..."} — present so a future cross-module
                             link doesn't require a schema migration, but nothing
                             reads or enforces this field today
spatial_ref (optional)     — nullable/absent today; reserved exactly the way
                             ENVIRONMENTAL-MEMORY.md already reserves it for a future
                             World Build shared spatial service ("may optionally
                             reference spatial locations... an explicit architecture
                             evolution, not an assumed dependency")
privacy_tags               — lightweight, module-defined tags describing sensitivity
                             (e.g. "may_contain_bystander", "may_contain_financial_info",
                             "may_contain_document_text") — cheap to add, useful for
                             future retention/audit tooling, not a classifier
                             requirement for v1
retention_tag              — module-defined retention/expiry hint (supports
                             06-PRIVACY-DATA.md's "configurable retention" requirement)
deleted / tombstone         — supports real deletion (06-PRIVACY-DATA.md: deletion must
                             be real deletion of stored artifacts, not hiding from a
                             query interface)
```

Notes on what is deliberately **not** in this shape:

- **No embedding field.** Object Memory needs visual/appearance embeddings for re-identification; Document Memory needs text embeddings for semantic search; Environmental Memory may need scene embeddings. These are different vector spaces produced by different models for different purposes — forcing them into one shared "embedding" slot would either be meaningless (incompatible vector spaces sharing a column) or would quietly become the first piece of a shared vector-search service nobody has justified yet. Each module owns its own embedding choice inside its own `content_ref` payload.
- **No structured-metadata schema.** "Structured metadata" varies enormously by module (a bounding box vs. a document's page count vs. a scene's landmark type). The shape above only requires that *something* module-specific hangs off `content_ref`; it does not standardize its contents.
- **No retrieval API.** Object Memory's `last_seen()/seen_today()/history()`, Environmental Memory's `search_text()/search_events()/what_changed()`, and Document Memory's future `find_in_document()`-style calls (see companion doc) are legitimately different query shapes. A shared retrieval API would either be a lowest-common-denominator that satisfies none of them well, or would need real usage evidence from at least two implemented modules to design correctly — exactly the roadmap's "generalize only when justified" trigger, not yet met.
- **No module-to-module access mechanism.** Rule 6's default is that modules do not read each other's data without an explicit shared-data design. The one concrete near-term candidate is Visual Q&A consuming Document Memory's retrieval output (see the companion document's Relationship to Visual Q&A section) — even that should be a narrow, explicit call into Document Memory's own query interface, not general read access to Document Memory's storage, and it does not require any shared substrate to work.
- **No agent-access broker.** A future agent that could query across Document Memory, Object Memory, and Environmental Memory simultaneously is a materially larger privacy exposure than any single module's own data (it could reconstruct "what did the user read, where were they, what objects were nearby" as one composite picture) and would need its own explicit privacy review under `06-PRIVACY-DATA.md`'s exception process before being built — not something to wire up incidentally as a side effect of three modules sharing a record shape. Flagged here as a real future direction worth documenting, not something this pass designs.

### Promotion Trigger

Per the roadmap's existing "generalize only when justified" pattern (mirrored exactly from V1.0's module-registry generalization trigger — "triggered only once a second production module... creates real, concrete requirements"): revisit this recommendation once **two** memory modules are actually implemented and show a concrete, repeated need for one of the deferred items above (a real query that needs to join across namespaces, a real embedding reused by two modules, a real agent-access requirement with its privacy review already done). Until then, three independent modules each internally following the same conceptual record shape — with zero shared code, zero shared service, zero coordination overhead — is the right amount of "canonical."

## Summary

| Dimension | Recommend now (cheap, no coordination) | Defer until 2nd/3rd module shows real need |
|---|---|---|
| Provenance (source, producing model) | Yes — already required by Limitation 15 | — |
| Timestamps (observation vs. record-created) | Yes | Wire-protocol-level capture/arrival split (Limitation 9) — separate, transport-layer concern |
| Confidence | Yes, incl. explicit UNKNOWN state | — |
| Source type | Yes, as a module-defined enum | Cross-module standardized taxonomy |
| Module ownership | Yes (namespace + explicit field) | — |
| Semantic/cross-module links | Reserve an unused `external_refs` field | Actual linking logic, enforcement, or indexing |
| Embeddings | Each module owns its own, internally | Shared embedding space/index/service |
| Structured metadata | Yes, freeform, module-defined | Shared schema |
| Spatial references | Reserve a nullable field, mirroring ENVIRONMENTAL-MEMORY.md's existing pattern | Populate only if World Build exposes a shared spatial service |
| Retention policy | Yes, per-record tag/hint | Shared retention-enforcement service |
| Deletion | Yes — real deletion, required per 06-PRIVACY-DATA.md regardless | Shared purge orchestration across modules |
| Privacy classification | Yes, lightweight tags | Automated classifier, shared policy engine |
| Retrieval APIs | No — module-specific query interfaces | Shared retrieval layer |
| Module-to-module access | No — narrow explicit calls only where a concrete need exists (Document Memory → Visual Q&A) | General cross-module access mechanism |
| Agent access | No | Requires its own future privacy review before any design work |
