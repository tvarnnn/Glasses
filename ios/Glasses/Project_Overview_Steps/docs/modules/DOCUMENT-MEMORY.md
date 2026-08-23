# Module Concept — Document Memory

## Status

**Concept seed, and a narrowing of an existing module rather than a new one.**
Future. The Tower has not adopted this scope, has not agreed to build it, and
declares no contract for it. It appears in the iOS cartridge catalog because the
iOS app ships a workspace for it — a fact about the phone, not about the Tower
(see `08-IOS-CARTRIDGE-SHELL.md`, "Two axes").

This document was written from the iOS side while preparing the cartridge
integration layer, so that the workspace could cite a real specification instead
of an invented one. It is a proposal to whoever owns the roadmap, not a decision
already taken. `docs/agent-handoffs/IOS-TO-TOWER.md` states what iOS would need
from the Tower if this scope is adopted.

## Relationship to existing modules

This is not a new ambition. `ENVIRONMENTAL-MEMORY.md`'s first-version success
criteria say:

> A first version should choose one constrained memory type, such as:
> - searchable OCR history; or
> - scene/event novelty memory.
>
> Do not attempt universal physical-world memory in the first implementation.

Document Memory **is** the first of those two, scoped down further to documents
specifically — pages, signs, notices, whiteboards, screens — rather than all
text everywhere. It uses the reading path sketched in `VISUAL-QA.md`
(`frame -> text detection -> OCR -> cleanup`) without that module's speech,
multimodal reasoning, or spoken-response requirements.

What it takes:
- Environmental Memory's `TEXT_SEEN` event shape and its relevance/novelty
  filtering;
- Visual Q&A's OCR/reading pipeline.

What it leaves behind:
- speech-to-text, text-to-speech, and multimodal question answering (Visual Q&A);
- places, landmarks, scene change, and object events (Environmental Memory);
- any claim to be a general physical-world archive.

If Environmental Memory is later implemented in full, this should be folded into
it rather than kept alongside it.

## Goal

Let a person find a document the glasses passed, without the platform storing
photographs of it.

Example questions:

- What did that parking notice say?
- The handout from the seminar this morning — what was the reading list?
- Did I walk past a fire-safety notice in that stairwell?

## Intended Inputs

Potential:
- selected camera observations, chosen by relevance rather than continuously;
- OCR text;
- observation timestamps;
- session context;
- optional spatial context if World Build later exposes a shared spatial
  service. `ENVIRONMENTAL-MEMORY.md` requires that to be "an explicit
  architecture evolution, not an assumed dependency" — so it is optional here
  and nothing depends on it.

## Core Architecture

```text
sensor stream
    |
document/text detection
    |
relevance + novelty filter        (most frames of a page are the same page)
    |
OCR + cleanup
    |
title/summary derivation
    |
document memory store
    |
retrieval / search
```

Heavy work is Tower-side, per Rule 5. **No OCR runs on the iPhone**, and the iOS
app holds no extracted text beyond what a person opened.

## Retention and Imagery

Governed by `06-PRIVACY-DATA.md`, which this module is one of the reasons for.

- Store structured text and metadata; do not retain the frames.
- A stored keyframe is optional and, if kept, must be redacted by its producer
  before it is offered for display. `06-PRIVACY-DATA.md` is explicit that a crop
  is not inherently safe — a photographed page routinely contains a bystander, a
  second document, or a screen.
- Document contents are among the most sensitive data the platform touches and
  are covered by the local-first rule without exception.
- Retention must be configurable and purgeable before any real collection
  begins, not merely documented.

## Observation, Not Attention

`07-PLATFORM-CONSTRAINTS.md` Limitation 8 applies in full: a document appearing
in frame does not establish that the wearer read it, noticed it, or understood
it, and no current hardware can establish that.

Every duration this module records is **time in the camera's field of view**.
Nothing in it may be labelled reading time, viewing time, or attention.

## Retrieval

Potential query kinds:

```text
recent(limit)
text(substring)
observed_within(time range)
semantic(natural-language description)
```

Time queries must be **ranges**, not instants: "this morning" and "around lunch"
are approximate, and answering them exactly is answering a different question.

## Failure Behavior

Three outcomes, and they are different answers that must not be merged:

- **matched** — with a confidence, per Core Principle 4;
- **nothing matched** — the memory was searched and held no match;
- **never observed** — the memory holds nothing covering that time or place, so
  the question cannot be answered either way.

The third is not a negative result. Core Principle 3: absence of observation is
not observation of absence. Never create a memory event retroactively to satisfy
a query, and never present a summary as the document's contents.

## First-Version Success Criteria

A bounded V1 should demonstrate:

1. reliable detection that a document is in frame;
2. OCR quality measured on real first-person imagery, with a stated metric;
3. relevance filtering that stores one record per document rather than per frame;
4. retrieval of a document by its text and by approximate time;
5. a working purge, before any real collection begins.
