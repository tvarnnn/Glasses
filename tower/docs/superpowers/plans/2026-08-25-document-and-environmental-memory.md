# Document Memory on the wire, and what "this room" can honestly mean

**Status:** RESEARCH + PLAN. Written 2026-08-25 on `main` @ `35214a1`.
Nothing proposed here is implemented. Every claim is marked **EXISTS** or
**PROPOSED**, and every EXISTS carries a citation.

**Two questions, one document, because they share a spine.**

- **A. Document Memory** is the most complete cartridge on the Tower and
  offers no wire contract. What is the smallest honest step that makes it
  useful on the phone? And separately: is the bursty / high-resolution /
  stability-gated capture strategy justified *yet*?
- **B. Environmental Memory.** *"What was in this room earlier?"* — what
  would it take, and what should it not be?

They share a spine because both of them are, underneath, a question about
**when**. Document Memory's whole retrieval surface is a time window
(`retrieval.py:142-162`); Environmental Memory's headline question is
*"earlier"*. And in both cases the tempting second axis — **where** — is
not available on this platform and will not be for some time. Section 1
is the part they share.

**The short answers.**

1. The smallest honest step for Document Memory is **one snapshot result
   type, `document_memory` / `recent`, carrying a bounded list of
   observation records with no document text beyond an extractive
   title.** §3. I agree it is the highest-value next step for this
   cartridge, with one ordering caveat in §3.9.
2. **Bursty capture is not justified yet**, and the reason is not that it
   is wrong — it is that every number behind it came from a renderer.
   §4.1. There are 2,806 real frames on this disk that have never been
   through the detector. §4.
3. **Environmental Memory should not begin.** §5. The honest V1 "place"
   is a **capture lineage plus a time window**, which is a fact about the
   transport and makes no spatial claim at all. §1.3 and §5.5 argue it,
   including the case against.

---

## 1. The spine: time is observable here, and place mostly is not

### 1.1 What is observable about "when" (EXISTS)

Every timestamp this system holds is **Tower-receipt time**, and every
module says so on the record rather than in a comment:

- `TIME_BASIS = "tower-receipt"` — `document_memory/records.py:24`,
  `results/contracts.py:77`, `world_builder` sessions, `capture.json`.
- The reason is that the frame protocol carries no time field at all —
  `results/contracts.py:71-77`, and `IOS-to-Tower.md` §0 lists the whole
  wire vocabulary: `frame` carries `seq`, `width`, `height` and nothing
  else.
- `IOS-to-Tower.md` §0.3 holds `observedAt` and `receivedAt` separately
  and will never substitute one for the other — **but it also sanctions
  the substitution the Tower is forced into**: "until that is resolved
  empirically, the Tower's own observation clock is the only usable one."

Receipt time is good to well under a second, which is far below the
resolution of *"about thirty minutes ago"*. `retrieval.py:150-154` says
exactly this and then says the caller must still label it. That is the
whole of what "when" costs here: a label.

Document Memory goes further than a label and records **how the duration
was arrived at**: `TIMING_CAPTURE_JOURNAL` / `TIMING_ASSUMED_INTERVAL` /
`TIMING_MIXED` (`records.py:55-57`), with `assumed_frame_interval_s`
beside it (`records.py:157`). A directory of loose JPEGs has no
timestamps, so replaying one has to assume a rate, and an assumed
duration must never be readable as a measured one. `"mixed"` exists
because collapsing a part-real stream to either extreme is a lie in one
direction or the other.

**This is the axis both halves of this document stand on.**

### 1.2 What is not observable about "where" (EXISTS)

- **Scale is `unknown` or `relative`, never metric.**
  `SCALE_STATES_ALLOWING_METRES = (SCALE_MEASURED,)`,
  `world_builder/schema.py:85`; `format_distance` refuses,
  `world_builder/records.py:93-95`. Every one of the 14 worlds on this
  disk reads `"scale": {"state": "unknown", ...}` — verified by reading
  `data/world_builder/worlds/*/world.json`.
- **A multi-segment world shares no coordinate frame.** A segment break
  means tracking was lost, so poses either side are not in a common
  frame (`world_builder/records.py:433-436`); a world with more than one
  segment stays `unknown` (`WORLD-BUILDER.md:117-119`).
- **There are no poses at all until the camera is calibrated.** The real
  2026-08-24 walk is on this disk and its manifest is unambiguous:

  ```
  data/world_builder/worlds/4b31766726c648d994a088a7c7b8aa9b/derived/manifest.json
  {"backend_id": "unposed", "keyframes": 155, "poses_solved": 0,
   "poses_refused": 119, "points": 0, "segments": 36,
   "scale_state": "unknown"}
  ```

  and its session records `"intrinsics": {"source": "unknown", "fx": null,
  ...}`. Nothing was reconstructed, because nothing could be.
- **A segment is not a room.** 4 of the 20 segments in the retuned walk
  contain a single keyframe (`WORLD-BUILDER.md:265-266`); segment breaks
  are caused by blur and track decay, not doorways; and the same 1,395
  frames yield 36, 40, 43, 49 or 20 segments depending on three
  constants (`WORLD-BUILDER.md:250-268`). The 2026-08-25 Object Memory
  plan already refuses to call a segment a room, in output, in a field
  name, or in a docstring
  (`docs/superpowers/plans/2026-08-25-object-memory-spatial-context.md:684-685`).

So *"in this room"* is a much weaker claim than it sounds. It is not
weakly supported — **it is unsupported**, and no amount of care in the
wording of a UI recovers it.

### 1.3 The one place-shaped fact that is real: capture lineage (EXISTS, unused offline)

A capture is a contiguous stretch of one socket's frames, with real
receipt times, written by shared transport (`tower/capture.py`). When the
socket drops and the phone reconnects within 90 s, the successor capture
records `continues_capture` in its manifest (`capture.py:60`,
`capture.py:362`), and `CaptureFollower._find_successor` (`capture.py:569-586`)
follows one hop. `tower/capture_workers.py` tracks a whole chain live —
`lineage: list[str]` at `capture_workers.py:75`.

**There is no offline function that reconstructs a lineage from
manifests.** The primitive exists three times, live, and nowhere as a
pure read.

Reconstructing it by hand over `data/captures/` — ten capture manifests
from the 2026-08-24 walk — collapses ten captures into **three
lineages**:

| lineage root | captures | frames | t (s, from first start) | span | delivered fps |
|---|---|---|---|---|---|
| `2e6cff` | 1 | 1395 | 0.0 → 121.9 | 121.9 s | **11.44** |
| `341b0f` | 3 (`341b0f→b058a6→b1ab1d`) | 297 | 226.8 → 272.0 | 45.2 s | 6.57 |
| `79233e` | 6 (`79233e→4fb823→0f0c55→b901bc→1a63a0→854e96`) | 1114 | 272.0 → 435.0 | 163.0 s | 6.83 |

2,806 frames total. Note the **104.9-second hole** between the first
lineage and the second: that gap exceeded the 90 s grace, so it is a new
walk (`WORLD-BUILDER.md:236-243`). Note also that `79233e` starts its own
lineage despite beginning the same second `b1ab1d` ended, because
`resumable_capture()` only offers a capture that ended by *disconnect*
(`capture.py:137-163`).

**Why this matters to both halves of this document.** A capture lineage
is:

- **observable** — it is read off manifests, with no inference;
- **owned by shared transport**, so no cartridge has to know about
  another to use it;
- **temporally bounded by real receipt times**, which is the honest axis;
- and it makes **no spatial claim whatsoever**, which is its whole
  virtue.

It is also the unit that makes *gaps* visible, and §5.4 argues that
making the gaps visible is the single most important property an
Environmental Memory answer can have.

---

## 2. Document Memory: what exists, and the hole in the middle of it

### 2.1 What exists (EXISTS)

`tower/document_memory/` is 1,844 lines across seven modules, with 2,267
lines of test across eight files. The pipeline, per the measured cost
model (`engine.py:1-15`):

```
every frame     decode, detect a page, update dwell        ~2.1-2.6 ms
per dwell       pick the best one or two frames            free
per dwell       warp and OCR those                         ~1.19 s each
```

- **Detection**, three gates: shape, text-likeness, and a glyph gate
  counting dark/light transitions along an inky row
  (`detect.py:71` `MIN_ROW_TRANSITIONS = 8`, chosen from a measured
  distribution where rendered text scores 43–86 and blinds, bricks, tiles,
  a striped shirt and a keyboard all score 0).
- **Dwell**, a state machine requiring both a frame count and a wall-clock
  duration (`dwell.py:42-43`), forward-only elapsed accumulation so a
  clock step cannot destroy a document (`dwell.py:106-116`), and a
  bounded `best` list so a long dwell cannot accumulate imagery
  (`dwell.py:227-229`).
- **OCR** behind a substitutable seam (`ocr.py:98-106`), EasyOCR chosen by
  elimination, with per-region confidence carried through.
- **Records** whose vocabulary is a constraint: `observed_at`,
  `observed_seconds`, `pages_observed`, and nothing named `read` or
  `viewed` (`records.py:1-12`).
- **Store**: append-only JSONL, atomic rewrite for prune and purge, a
  retention window that defaults to 30 days rather than forever, and a
  purge that reports what it could **not** delete (`store.py:170-256`).
- **Retrieval**: BM25, forty lines, labelled `match_kind: "lexical"` in
  its own output, with `sufficient_evidence: False` and a reason string
  when it refuses (`retrieval.py:92-116`).
- **CLI**: `scripts/document_memory_session.py` (observe) and
  `scripts/document_query.py` (ask).

Two facts about the state of this cartridge that should be stated plainly
because they bound everything below:

1. **`data/document_memory/` does not exist on this machine.** No
   document has ever been observed from real footage. Every number in
   `guidelines/docs/reports/2026-08-22-document-memory-v1-report.md` came
   from a renderer, and that report says so in its own §12: "Everything
   is synthetic."
2. **`easyocr` and `torch` are not installed in this venv.** Verified:
   `.venv\Scripts\python.exe -c "import easyocr"` → `ModuleNotFoundError`.
   `cv2` 5.0.0 and `numpy` 2.5.2 are present. This matters to §4's cost
   accounting.

### 2.2 The hole: no wire contract (EXISTS)

`tower/results/registry.py:62-68`:

```python
{
    "cartridge": CARTRIDGE_DOCUMENT_MEMORY,
    "reason": (
        "implemented on Tower and queryable by CLI, but no typed "
        "contract is offered yet; see IOS-to-Tower.md 3"
    ),
},
```

and `docs/contracts/CARTRIDGE-RESULTS.md:415` adds the second half:
"Also gated by the resolution finding in `TOWER-TO-IOS.md` §6.8."

`NOT_OFFERED` is deliberately reported and deliberately kept in a
separate list from the offers, so that an operator can tell "the Tower
does not know what `document_memory` is" from "the Tower knows and is not
serving it yet" (`registry.py:44-52`). iOS keys on `cartridges` and
therefore currently shows **"not built yet"** for the most complete
cartridge in the repository.

Adding a cartridge to the channel costs, per `CARTRIDGE-RESULTS.md:403-425`:

1. `tower/results/<cartridge>.py` producing a `Snapshot` — the only file
   allowed to import that cartridge, enforced by
   `test_the_result_channel_core_is_cartridge_blind`;
2. one branch in `tower/results/__init__.py: make_snapshot_for`
   (currently `__init__.py:45-65`);
3. one `CartridgeOffer` in `registry.py`, and the `NOT_OFFERED` entry
   removed;
4. a new contract identifier.

Nothing in the envelope, publisher, subscription, ordering, coalescing,
reconnect or error machinery changes. **That is the whole reason this is
the highest-value step: the transport is already built and already
tested.**

### 2.3 The one structural mismatch to be honest about (EXISTS)

The result channel is **subscribe-and-snapshot**, not request/response. A
subscription's target key is `(cartridge, result_type, world_id,
session_id)` — `results/publisher.py:163-170` — and the socket handler
validates exactly those two optional filters
(`routes/results_ws.py:93-102`). There is no field in which a client can
put a search string, and every distinct target is polled every 0.5 s for
as long as the subscription is open (`CARTRIDGE-RESULTS.md:355`).

So of iOS's four query kinds (`IOS-to-Tower.md` §3.4):

| iOS query kind | Fits a snapshot subscription? |
|---|---|
| `recent(limit:)` | **Yes.** It is a standing view of the newest N records. |
| `text(String)` | No. Needs a client-supplied predicate. |
| `observedWithin(DateInterval)` | No. Same. |
| `semantic(String)` | No, and Tower cannot serve it at all — retrieval is lexical (`retrieval.py:9-14`). |

**`recent` is the one query kind the existing channel can carry without a
single change to the wire machinery.** That is not a coincidence to be
exploited quietly; it is the reason `recent` is the right first slice,
and §3 states the limitation on the wire rather than letting a consumer
discover it.

---

## 3. PROPOSED — `document_memory` / `recent`

Sketched in the shape of `docs/contracts/CARTRIDGE-RESULTS.md`. Nothing
here is implemented.

### 3.1 Discovery

The offer, added to `registry.declare()` and removed from `NOT_OFFERED`:

```json
{
  "cartridge": "document_memory",
  "result_type": "recent",
  "contract": "document_memory.recent/2026-08-25",
  "available": true,
  "unavailable_reason": null,
  "snapshot_only": true
}
```

**Mint the identifier on the day it ships.** If that is not 2026-08-25,
change the date; identifiers are dated rather than numbered precisely so
that nobody computes which is greater (`results/contracts.py:24-27`).

`available: false` when `TOWER_DOCUMENT_ROOT` is unset, mirroring
`TOWER_WORLD_ROOT` exactly (`registry.py:116-123`), with
`unavailable_reason`: *"no document root is configured on this Tower
(`TOWER_DOCUMENT_ROOT` is unset), so there is no observed-document store
to read"*. **PROPOSED:** `TOWER_DOCUMENT_ROOT` in `tower/config.py:44-59`,
beside `capture_root` and `world_root`.

That third state matters here more than it does for World Builder,
because a Tower that has never had `scripts/document_memory_session.py`
pointed at a capture has an empty store, and "empty" and "not configured"
are different facts calling for different user actions.

### 3.2 Subscribing

```json
{"type": "result_subscribe",
 "cartridge": "document_memory",
 "result_type": "recent",
 "contract": "document_memory.recent/2026-08-25"}
```

`world_id` and `session_id` are **not part of this cartridge's
addressing** and must be omitted. The producer ignores them. See §8 open
question 1 for whether the socket handler should refuse them instead.

### 3.3 The payload

```json
{
  "memory": {
    "schema_version": 1,
    "documents_total": 3,
    "oldest_observed_at": 1787548911.42,
    "newest_observed_at": 1787549102.87,
    "time_basis": "tower-receipt",
    "retention_seconds": 2592000,
    "retention_note": "documents older than this are deleted, page images included",
    "confidence_vocabulary_version": 1,
    "retains_raw_imagery": false,
    "text_redaction": "none",
    "text_redaction_note": "no redaction is applied to document text and none exists on this platform; the text is the payload"
  },
  "answer": "matched",
  "answer_reason": "3 documents have been observed",
  "not_found_ever_reported": false,
  "retrieval_confidence": null,
  "retrieval_confidence_unavailable_reason": "this result type applies no query predicate, so there is nothing for a retrieval confidence to be a confidence in",
  "query_kinds_served": ["recent"],
  "query_kinds_not_served": [
    {"kind": "text", "reason": "lexical search exists on Tower but this channel carries no client predicate"},
    {"kind": "observed_within", "reason": "same"},
    {"kind": "semantic", "reason": "Tower runs no embedding model; retrieval is lexical"}
  ],
  "documents_limit": 10,
  "documents_returned": 3,
  "truncated": false,
  "documents": [ /* … */ ]
}
```

One document row:

```json
{
  "document_id": "9f2c1b7e8a4d4f1e9c3b0a6d5e7f2c81",
  "title": "Ridgeway Clinic — Results Summary",
  "title_provenance": "extractive",
  "title_source": "the first recognised line of the first page, verbatim",
  "observed_at": 1787549102.87,
  "time_basis": "tower-receipt",
  "capture_time_available": false,
  "capture_time_unavailable_reason": "the frame protocol carries no time field",
  "observed_seconds": 12.4,
  "timing_source": "capture-journal",
  "assumed_frame_interval_s": null,
  "end_reason": "region_lost",
  "clock_regressions": 0,
  "text_availability": "extracted",
  "character_count": 843,
  "pages_observed": 2,
  "pages_total": null,
  "pages_total_note": "unknown: the system cannot see pages it was never shown",
  "confidence": "medium",
  "confidence_vocabulary_version": 1,
  "recogniser_id": "easyocr",
  "frames_considered": 41,
  "frames_ocred": 2,
  "read_at_width": 360,
  "read_at_height": 640,
  "warped_width": 231,
  "warped_height": 318,
  "thumbnail": null,
  "thumbnail_unavailable_reason": "page images are off by default; when enabled they carry redaction \"none\", which iOS withholds",
  "retains_raw_imagery": false,
  "redaction": "none",
  "capture_id": "2e6cffa275b24b7d87d68ec1d6a6cfdf",
  "world_id": null,
  "world_session_id": null
}
```

### 3.4 How `IOS-to-Tower.md` §3.5's three answers are honoured

This is the part the brief flagged as most likely to be got wrong, so it
gets its own treatment.

iOS models **three** answers, not two: `matched(confidence:)`,
`notFound`, `noObservation`. The distinction exists because "absence of
observation is not observation of absence", and collapsing `noObservation`
into "no results" lets a gap in what the glasses happened to see read as
a statement about the world.

**The distinction already exists in the retrieval code.** `search_text`
returns three different refusals with three different reasons
(`retrieval.py:171-213`):

| `retrieval.py` | iOS answer |
|---|---|
| `"no documents have been observed"` (`:174`) | `noObservation` |
| `"the query contains no searchable terms"` (`:182`) | neither — a malformed query, not a statement about the memory |
| `"no observed document contains these terms; this is a statement about what was captured, not about what the documents say"` (`:206-210`) | `notFound` |

What is missing is not the distinction. It is that the distinction is
carried as **prose**, and a decoder cannot switch on prose. The contract
therefore promotes it to an enumerated `answer` field with the reason
string kept beside it.

For `result_type: "recent"` the mapping is:

- `store.count() == 0` → **`no_observation`**. The memory holds nothing
  covering what was asked, and iOS renders "Never observed" plus the
  explicit statement that this is not the same as the document not
  existing.
- `store.count() > 0` → **`matched`**, with the list.
- **`not_found` is unreachable for this result type.** `recent` applies
  no predicate, so a non-empty store cannot fail to match.

That last line is the design point, and it follows a pattern already in
the tree rather than inventing one. `_tracking_block` sends
`limited_ever_reported: false` on every payload because "limited" would
require a threshold nobody has defined (`results/world_builder.py:951-979`);
`_calibration_block` sends `calibrating_ever_reported: false` and no
percentage, because a percentage "implies a denominator nobody has
defined" (`results/world_builder.py:1012-1014`). By the same discipline
this payload carries **`not_found_ever_reported: false`**, so a consumer
that never sees the value knows the state is structurally unreachable
here rather than merely rare — and knows that it *becomes* reachable the
day a predicate-bearing result type is added.

**`matched(confidence:)` carries no confidence, and this is deliberate.**
There are three numbers in the neighbourhood and none of them is a
retrieval confidence:

- `Match.score` is a raw BM25 score (`retrieval.py:84`). It is unbounded
  above, corpus-relative, and computed against a smoothed IDF chosen so
  that a three-document corpus does not go negative (`retrieval.py:276-282`).
  Normalising it into 0–1 would require a denominator nobody has defined.
- `MIN_SCORE = 0.10` (`retrieval.py:44`) is a documented threshold, not a
  scale, and the module says it "can be moved from data once a real query
  set exists".
- `DocumentObservation.confidence` is a *label* derived from the mean OCR
  region confidence (`ocr.py:88-95`, `engine.py:525-540`), and it is a
  statement about **how well the text was read**, not about how well the
  record answers a question.

So the payload sends `retrieval_confidence: null` with a reason, and
sends the per-document `confidence` label — which iOS asked for
separately in §3.1 and which Core Principle 4 requires to survive to
display. `confidence_vocabulary_version` travels with it because the
bucket boundaries are declared placeholders that will move
(`tower/confidence.py:11-30`), and a label whose thresholds changed
silently is worse than no label.

**iOS-side note (not Tower's to change):** iOS "refuses to construct a
result that claims `matched` while carrying no documents — it coerces to
`notFound`". This payload cannot produce that combination:
`answer: "matched"` is emitted only when `documents_total > 0`, and
`documents_returned` is then at least 1. Worth a test on both sides.

### 3.5 Text on the wire, and what redaction does not touch

**Constraint, stated because it is the most consequential thing in this
document.** A document is often the most sensitive thing a wearer looks
at — `06-PRIVACY-DATA.md:80` names documents, screens, IDs, financial
information and private communications as a standing risk of the input
modality, and `guidelines/docs/modules/DOCUMENT-MEMORY.md:185-187` says
the same in the module's own words: these appear "as literal readable
text, and a document's whole point is to be read."

Persisted **imagery** on this platform is face-redacted before it is
written — but only World Builder's, and only as a *process* claim:
`faces-detected-and-filled/yunet-2023mar@0.30`, never "redacted",
"anonymised" or "privacy-safe", because YuNet has measured false
negatives past ~60% occlusion and ~90° in-plane rotation
(`world_builder/redaction.py:72-84`). `retains_raw_imagery` stays `true`
after redaction; bodies, clothing, room contents and any undetected face
are still in the image.

**None of that touches a document's text.** Face redaction operates on
pixels; Document Memory persists the text and, by default, no pixels at
all (`engine.py:140-143`, `records.py:162-163`). So:

1. `redaction: "none"` on a `DocumentObservation` means **no pixel
   treatment was applied**, and is only meaningful when
   `retains_raw_imagery` is true. It says nothing about the text, because
   nothing could.
2. There is no such thing as redacted document text on this platform, and
   there is no obvious thing such a redactor would even do: the text is
   the payload, not an incidental bystander in the frame.
3. `IOS-to-Tower.md` §5's rule — "`unknown` (not stated) → handled
   exactly as strictly as raw — withheld" — is a rule about **imagery**.
   A consumer that applied it to text would withhold every document and
   the cartridge would be pointless. The contract must therefore carry a
   *separate, explicit* `text_redaction: "none"` with the note above, so
   the imagery rule is not silently extended or silently ignored.
4. `retains_raw_imagery` is a permanent property of the record. It is
   `false` today because page images are opt-in and off
   (`engine.py:140-143`, `scripts/document_memory_session.py:85-91`), and
   a build that flips the default flips a privacy property of every
   record it writes.

**What this costs on the wire, concretely.** iOS asks for `title` and
`summary` (§3.1) and simultaneously says the list must carry "a character
count, not the text" (§3.2). Both are right; they are about different
things. A title bounded at 90 characters (`engine.py:457`) and a summary
bounded at 40 words (`engine.py:507-522`) are still document text — and a
title is frequently the *most* identifying line a document has. "Blood
Test Results". "Notice to Quit". A list of ten rows would put ~2.5 KB of
the most identifying text the wearer looked at onto the phone.

**PROPOSED, and this is a real decision rather than a restatement: V1
sends `title` and omits `summary`.** A title is the minimum a person
needs to recognise their own record; a 40-word summary is roughly five
times the exposure for no additional identification, and
`06-PRIVACY-DATA.md`'s Data Minimization section asks for exactly this
trade. **Named trigger for adding it:** a real corpus of observed
documents where titles alone do not let a person pick out the record they
meant. That is measurable, and it is not measurable today because zero
real documents exist.

No `snippet`, no page text, no `text` field. Full text is a separate step
— see §8 open question 2.

### 3.6 What is deliberately `null`, and why

Following `CARTRIDGE-RESULTS.md` §10.1's discipline that an unavailable
figure is `null` with a reason, never `0` and never omitted:

| Field | Value | Why |
|---|---|---|
| `pages_total` | `null` + note | The cartridge cannot see pages it was never shown; a denominator would turn an observation gap into a claim of completeness (`retrieval.py:223-241`) |
| `retrieval_confidence` | `null` + reason | §3.4 |
| `thumbnail` | `null` + reason | No artifact fetch contract exists on either side (`IOS-to-Tower.md` §5: "Artifact fetching itself is UNKNOWN"), and when page images *are* enabled they carry `redaction: "none"`, which iOS withholds |
| `world_id`, `world_session_id` | `null` unless supplied | Supplied by a caller or absent; nothing derives them and this module must not import World Builder — pinned by `test_no_spatial_anchor_is_invented` (`tests/test_document_memory_engine.py:176-188`) |
| `assumed_frame_interval_s` | `null` when timing was measured | `engine.py:358-360` |
| `capture_time_available` | `false` + reason | There is no capture timestamp anywhere in the system |

`text_availability` uses iOS's own three-way vocabulary
(`unknown` / `not_readable` / `extracted`), and §3.7 explains why the
record cannot produce all three today.

### 3.7 PROPOSED — three record fields that must land first

These are additive, small, and they are prerequisites rather than
nice-to-haves. Two of them are honesty defects in the current record.

**(a) `PageObservation.recogniser_id`.** Today `text_source` is a
constant `"ocr"` (`records.py:41`, `:73`) and the engine never records
which recogniser produced the text. `FixedTextRecogniser.name == "fixed"`
and `EasyOcrRecogniser.name == "easyocr"` both exist (`ocr.py:118`,
`:169`) and neither reaches the record. That is a direct miss against
`07-PLATFORM-CONSTRAINTS.md` Limitation 15's "which module/model produced
an inference", and against the canonical record shape's
`producing_model_or_method`
(`docs/superpowers/research/2026-08-20-canonical-memory-architecture.md:42-98`).
A store containing pages read by two different engines currently cannot
be told apart.

**(b) A text source meaning "no recogniser ran".** The driver offers
`--ocr none`, described as "honest about having read nothing rather than
pretending" (`scripts/document_memory_session.py:70-77`) — but it is
implemented as a `FixedTextRecogniser` with no pages, which returns
`OcrResult(text="")` and `region_count == 0`, which is **byte-identical
on the record to EasyOCR looking at a page and finding nothing**. Those
are iOS's `unknown` and `notReadable` respectively, and §3.2 makes
`notReadable` a first-class real answer while `unknown` is an absence of
one. The record cannot currently distinguish them, so the wire cannot
either. Fix: a `TEXT_SOURCE_NONE` value set from the recogniser's
identity.

**(c) The resolution a page was read at.** `read_at_width` /
`read_at_height` (the frame) and `warped_width` / `warped_height` (the
page after perspective correction). The capture journal already carries
`width` and `height` per frame (`data/captures/*/frames.jsonl`), and
`warp_page` already computes the warped size (`detect.py:129-146`), so
neither is a new measurement — both are facts being thrown away.

This one is doing double duty. It makes every stored record say at what
resolution it was read, permanently, which is the difference between "a
document with low confidence" and "a document read at 360×640, where the
2026-08-22 ladder puts word recall at 0.429–0.810". And it is the
cheapest available form of `TOWER-TO-IOS.md` §6.8's *second* request —
"a way to learn which rung of the adaptive ladder is currently active, so
a consumer can record that a reading was taken at a resolution too low to
trust rather than storing a bad one silently." **Tower can satisfy that
today with no iOS change at all**, because the frame dimensions are
already on the wire and already in the journal.

**A version note that is not obvious.** `store.read_all()` skips any
record whose `schema_version != SCHEMA_VERSION` (`store.py:129-137`). So
a bump is not a migration — it is a data-loss event for everything
already written. Additive optional fields read with `.get()` defaults do
**not** need a bump and must not get one. Separately: because
`data/document_memory/` does not exist on this machine, right now is the
one free moment to bump if a bump is ever wanted.

### 3.8 Cost, bounds, and the producer

**Bounds.** `CARTRIDGE-RESULTS.md:351` requires fixed arity and a payload
measured under 8 KB, with a test asserting no unbounded list. Ten
document rows at roughly 500 bytes each (no text beyond a ≤90-character
title) plus the `memory` block lands near 5–6 KB. **`documents_limit` is
a contract constant, not a client parameter** — a client-supplied limit
would become part of the subscription target key
(`publisher.py:163-170`) and give a remote party control over how many
distinct targets the Tower polls. `documents_total` and `truncated` sit
beside the list so the bound is visible rather than silent.

**Pagination** is `UNKNOWN` on both sides (`IOS-to-Tower.md` §3.6:
"`DocumentQueryResult` carries no cursor"). A hard limit plus
`documents_total` is the honest answer for a snapshot channel; a cursor
would need somewhere on the phone to accumulate a second page, and there
is nowhere.

**Cost.** The producer calls `store.read_all()`, which parses the whole
JSONL. Measured (`2026-08-22-document-memory-v1-report.md` §11):
`recent` costs 0.16 ms at 10 documents, 1.13 ms at 100, 10.51 ms at
1,000; storage is ~1,063 bytes per document. At the 0.5 s poll interval,
1,000 documents cost ~2% of one worker thread — and snapshot computation
already runs off the event loop via `asyncio.to_thread`
(`publisher.py:564-582`). Cache on the journal's mtime and size, the way
`WorldBuilderStatusProducer` holds a per-target cache
(`results/__init__.py:38-41`).

**Revision.** `compute_revision` hashes the payload with volatile paths
removed (`results/envelope.py:139-155`). This payload has **no volatile
fields**: nothing in it advances on its own, because ages are not
computed here — absolute `observed_at` crosses and iOS subtracts. So
`volatile_fields = ()`, the revision is stable across polls, and
`revision_changed: false` on every heartbeat until a document is actually
written. Worth stating in the contract, because World Builder's
`progress.mapping_seconds` exclusion has trained a reader to expect one.

### 3.9 Do I agree this is the highest-value next step? Yes — with an ordering caveat

**Yes, for the cartridge.** Every alternative is larger and less
valuable:

- *Full-text retrieval* needs a wire mechanism the channel does not have
  (§2.3, §8 Q2).
- *Semantic retrieval* has a named trigger that has not fired — "when a
  measured query set shows lexical recall failing on paraphrase"
  (`retrieval.py:16-18`) — and there is no query set and no corpus.
- *Registering it as a production module* is blocked at the same
  V1.0/V1.1 boundary as World Builder, and 1.2 s of OCR could not sit on
  the event loop even if a slot were free
  (`DOCUMENT-MEMORY.md:231-239`).
- *Thumbnails* need an artifact fetch contract neither side has designed,
  and would arrive with `redaction: "none"`, which iOS withholds.

And the payoff is disproportionate: the transport is built, the tests are
generic, and the change is one new file, one branch, one registry entry
and one identifier.

**The caveat is about ordering, not about the conclusion.** §4's
Experiment 1 costs about ten seconds of CPU and zero installs, and it
answers a question that changes what shipping this contract *means*: does
the detector fire at all on real footage? If 2,806 real frames produce
zero page candidates, then the contract would ship a permanently empty
list, and the cartridge's problem is not the wire. Run Experiment 1
first. It is not a gate on the design — the payload shape above is
correct either way, and a row reading `text_availability:
"not_readable"`, `confidence: "low"`, `read_at: 360×640` is a **true and
useful** thing for a phone to show. It is a gate on knowing what you have
built.

### 3.10 PROPOSED — tests

Mirroring `tests/test_result_channel_{protocol,bounds,truthfulness,isolation}.py`:

| Test | Pins |
|---|---|
| `test_the_declaration_offers_document_memory_recent` | the offer exists and the `NOT_OFFERED` entry is gone |
| `test_the_http_and_socket_declarations_stay_byte_identical` | existing test still passes with a second offer |
| `test_an_empty_store_answers_no_observation` | `answer == "no_observation"`, not `"not_found"`, not an empty `matched` |
| `test_not_found_is_never_reported_by_the_recent_result_type` | `not_found_ever_reported` is `False` and `answer != "not_found"` for every store state |
| `test_no_retrieval_confidence_is_ever_sent` | `retrieval_confidence is None` on every payload |
| `test_the_payload_carries_no_document_text_beyond_the_title` | no `text`, no `snippet`, no `summary`; `title` ≤ 90 chars |
| `test_a_full_list_stays_under_eight_kilobytes` | with `documents_limit` maximal titles |
| `test_the_payload_contains_no_unbounded_list` | mirrors the existing bounds test |
| `test_an_assumed_duration_is_labelled_on_the_wire` | `timing_source` and `assumed_frame_interval_s` survive the hop |
| `test_a_page_with_no_readable_text_is_not_readable_not_absent` | `text_availability == "not_readable"`, `character_count == 0` |
| `test_no_recogniser_is_distinguishable_from_no_text_found` | requires §3.7(b) |
| `test_the_read_resolution_is_recorded_on_every_document` | requires §3.7(c) |
| `test_the_revision_is_stable_across_polls_with_no_new_document` | no volatile fields |
| `test_a_new_document_changes_the_revision` | |
| `test_the_producer_is_the_only_file_importing_document_memory` | extend `test_the_result_channel_core_is_cartridge_blind` (`tests/test_architecture_boundaries.py:79-105`) |
| `test_the_frame_reply_is_unchanged_with_a_document_subscription_open` | mirrors the existing isolation test |
| `test_document_memory_does_not_import_another_cartridge` | existing, `tests/test_architecture_boundaries.py:398` — must still pass |

---

## 4. The evidence test for bursty capture

### 4.1 It is not justified yet, and here is why

The bursty / high-resolution / stability-gated capture idea rests on one
table (`2026-08-22-document-memory-v1-report.md` §3, restated at
`TOWER-TO-IOS.md:698-724`):

| Frame size | Word recall |
|---|---|
| 1280×720 | 0.957 – 1.000 |
| 896×504 | 0.872 – 1.000 |
| 640×480 | 0.905 – 1.000 |
| **640×360** | **0.429 – 0.810** |

Five reasons not to act on it yet.

1. **Every row is a render.** The report's own §12 opens "Everything is
   synthetic. Rendered pages, ideal lighting, no motion blur, no rolling
   shutter, no auto-exposure, no real paper texture." Its §1 sets the
   standing gate: "nothing counts as validation for the platform's own
   camera until it runs on real DAT footage."
2. **Zero real frames have been through OCR, and 2,806 of them are sitting
   on this disk.** `data/captures/`, ten manifests, three lineages,
   360×640, real receipt times (§1.3). The measurement that would settle
   this has not been attempted.
3. **The benchmark never tested the orientation the glasses actually
   deliver.** `FRAME_SIZES = [(640, 360), (640, 480), (896, 504),
   (1280, 720)]` — `scripts/document_memory_benchmark.py:41` — is
   landscape throughout. Every real frame in `data/captures/*/frames.jsonl`
   reads `"width": 360, "height": 640`. Same pixel count, different
   geometry: a landscape-held page across a 360-pixel-wide frame gets
   roughly half the horizontal sampling the 640×360 row measured. The
   real delivered case may be **worse than the worst row in the table**,
   and nobody has checked.
4. **The sender path was measured healthy on real hardware on
   2026-08-24** — ~24 FPS captured, ~12 FPS transmitted, 97 frames in
   8.1 s, and zero drops of every kind: no backpressure drops, no
   rejected frames, no send-window drops, no decode or encode failures.
   That figure is corroborated in-repo: capture `2e6cff` holds 1,395
   frames over 121.9 s = **11.44 fps delivered**, and `854e96` holds 610
   over 55.0 s = 11.09 fps. Proposing a change to a path measured healthy,
   on evidence gathered from a renderer, inverts this project's own
   discipline.
5. **The mechanism is not Tower's to design.** `TOWER-TO-IOS.md:735-739`:
   "Rule 4 still forbids designing a generalised negotiation protocol
   before the real DAT configuration model is known via `search_dat_docs`.
   This section states the requirement and the measurement; the mechanism
   is a Mac-side question."

And there is a cheaper half already available: §6.8's *second* request —
record which rung was active — is satisfiable **today, on Tower, with no
iOS change**, because the frame dimensions are already in the journal.
That is §3.7(c). Do that first, and every future record becomes evidence.

### 4.2 The data that exists

| | |
|---|---|
| Real frames | **2,806** JPEG, all 360×640, `data/captures/*/frames/` |
| Real receipt times | yes, `frames.jsonl`, `time_basis: "tower-receipt"` |
| Ground-truth text | **none** |
| Detector | `tower/document_memory/detect.py`, needs only `cv2` + `numpy`, both installed |
| Recogniser | `EasyOcrRecogniser`, `ocr.py:154` — **`easyocr` and `torch` are not installed in this venv** |
| Recall metric | `word_recall`, `scripts/document_memory_benchmark.py:52-66` — already the right metric, and the report explains why it beats sequence similarity |

### 4.3 Experiment 1 — does the delivered stream produce document observations at all? (runnable now, zero installs)

**Question.** On real footage, at the real resolution and orientation,
does the cheap half of the pipeline fire — and when it does, how big is
the warped page?

**Method.**

1. For each of the nine non-empty captures, read `frames.jsonl` in
   `source_seq` order and feed every frame to `detect_page`
   (`detect.py:203`).
2. Independently, feed each capture through `DocumentMemoryEngine` with a
   recogniser that reads nothing, supplying `received_at` from the journal
   so `timing_source` is `capture-journal`, and `flush()` at the end.
3. Record, per capture and pooled:
   - frames processed; frames with a candidate; the candidate rate;
   - for each candidate: `area_fraction`, `aspect`, `solidity`,
     `text_row_fraction`, `ink_fraction`, `row_transitions`, `sharpness`,
     `squareness` (all already on `PageCandidate`, `detect.py:83-97`);
   - **the warped page size** from `warp_page(gray, candidate.corners)` —
     the number that matters;
   - dwells started, dwells that qualified (`dwell.qualifies`,
     `dwell.py:118-123`), and for each qualifying dwell its
     `frames_seen`, `seconds`, `end_reason`, and the `sharpness` of its
     best frames;
   - the count of frames rejected at each of the three detector gates, so
     a zero-detection result is diagnosable rather than merely
     disappointing.

**Cost.** 2,806 frames × ~2.1–2.6 ms (report §11) ≈ **7 seconds**, plus
JPEG decode. No installs, no downloads, no hardware.

**What each outcome means.**

- **Warped pages cluster well below ~500 px on the long edge** → the
  resolution requirement is confirmed on *real* data without a single
  OCR call, because the 2026-08-22 collapse happened at a ~514×318 warp.
- **Warped pages are comparable to or larger than the synthetic 640×360
  row** → the synthetic ladder is not transferable and Experiment 3 must
  be run before anything is concluded.
- **Near-zero candidates across 2,806 frames** → the headline finding
  changes completely. The three gates were tuned on renders
  (`detect.py:52-71`); real paper on a real desk, with real lighting and
  a real auto-exposure, may not clear them. The report already names two
  plausible causes: "a page on a near-white surface is not detected —
  Canny finds no border where page and desk share an intensity", and "a
  page held very close, filling more than 98% of the frame, is rejected"
  (§12). If detection is the bottleneck, **bursty capture buys nothing**,
  because the expensive path never fires.

**This experiment is the cheapest thing in this document and it can
falsify the whole premise.** Run it first.

### 4.4 Experiment 2 — reference-free OCR quality on real frames (runnable now, one environment change)

**Question.** With no ground truth, is the recogniser reading *text* on
these frames, or reading noise?

**Method.** For a sample of up to 50 qualifying dwells from Experiment 1
(random, seeded, reported), for each of the two best frames:

- **Arm A — native.** OCR the warped page as the pipeline would.
- **Arm B — 2× bicubic upscale.** OCR the same warped page upscaled.
  Upscaling adds no information, so this is a control: it separates "the
  recogniser handles small input badly" from "the pixels are not there".

Record per page: `region_count`, `mean_region_confidence`,
`min_region_confidence`, `confidence_label`, character count, and OCR
wall time.

Then three reference-free measures:

1. **Cross-frame agreement.** `token_overlap` (`engine.py:60-70`) between
   the two best frames' OCR text within one dwell. The dwell tracker has
   already established these are two views of the same region at the same
   size in the same place (`engine.py:74-82`), so they *should* agree.
   **This is pre-registered against a figure already documented in the
   source:** `engine.py:44-46` states that re-OCR of the same page
   "typically [exceeds] 0.85", and that different pages "rarely exceed
   ~0.4" by chance. Real dwells landing near or below 0.4 are reading
   noise; near 0.85 are reading text.
2. **Model confidence distribution.** The mean and minimum region
   confidence, reported as a distribution rather than a single figure,
   and labelled as **model output, not accuracy** — `ocr.py:16-19` is
   explicit that everything there is inference.
3. **Upscale delta.** Median cross-frame agreement and median region
   count, Arm B minus Arm A. A large positive delta indicts the
   recogniser's input handling; a delta near zero indicts the sensor.

**Cost.** Requires `pip install -e .[ocr]` — 10 added packages per the
2026-08-22 report (`easyocr`, `scipy`, `scikit-image`, `imageio`,
`tifffile`, `lazy-loader`, `ninja`, `pyclipper`, `python-bidi`,
`shapely`) plus `torch`, and a first-run model download. Apply the same
discipline that installation used: `pip check` clean before and after,
and the suite's pass count unchanged either side. Runtime: ≤ 50 dwells ×
2 frames × 2 arms × 1.19 s ≈ **4 minutes**, plus ~5 s of reader
construction.

**What it cannot do.** It cannot produce a recall number. Agreement
measures *consistency*, and a recogniser can be consistently wrong. It is
an indictment tool, not an exoneration tool: a bad result is conclusive,
a good result is not.

### 4.5 Experiment 3 — the one that settles it (60 seconds of hardware)

**Question.** What is `word_recall` on real Ray-Ban footage, at 360×640,
against text we know?

**Method.**

1. Print the three existing fixtures — `TRANSFORMER_PAPER`,
   `DEPTH_NOTES`, `RECEIPT` from `tests/document_fixtures.py`, the same
   ones the synthetic ladder used — on ordinary paper. Using the same
   text is the point: it makes the real row directly comparable to the
   four synthetic rows rather than to nothing.
2. Arm the recorder (`TOWER_CAPTURE_ROOT`), wear the glasses, and read
   each page normally for ~10 s in ordinary indoor light, in the way the
   product premise describes: no scanning workflow, no flattening, no
   holding still for the camera.
3. Run `scripts/document_memory_session.py --follow-capture <dir> --ocr
   easyocr` and then `word_recall(truth, document.text)` per document.
4. **Control arm, same session, same pages:** capture the same three
   pages at 1280×720 through whatever path exists, and compute recall
   there too. This arm is what turns "recall is low" into "and a
   higher-resolution still would fix it" — which is the actual claim
   bursty capture rests on, and which no measurement has ever tested
   outside a renderer. If no higher-resolution path exists on the
   hardware, say so and record the arm as **not run**, rather than
   inheriting the synthetic 1280×720 row.
5. Repeat at two distances and two tilts, because the synthetic finding
   was "tilt barely matters; resolution dominates" and that finding is
   itself synthetic.

**Cost.** About a minute of wearing, plus roughly 1.2 s of OCR per page.

### 4.6 The decision rule, stated before the data

Written in advance so the answer is not chosen after the fact. Read the
branches in order.

| Condition | Conclusion |
|---|---|
| **Exp 1: near-zero page candidates on real footage** | Detection is the bottleneck. Bursty capture is **not** justified — the expensive path never fires. Retune the three gates against real footage; nothing else matters until then. |
| **Exp 2: cross-frame agreement median < 0.4** *and* Arm B ≈ Arm A | The pixels are not there. Strong support for the requirement; proceed to Exp 3 to quantify it. |
| **Exp 2: Arm B markedly better than Arm A** | The recogniser's input handling is a factor, not only the sensor. Test a cheap Tower-side upscale before asking iOS for anything. |
| **Exp 3: median word_recall ≥ 0.85 at 360×640** | The delivered stream is sufficient. Bursty capture is **not** justified. Close `TOWER-TO-IOS.md` §6.8's first request and record the correction. |
| **Exp 3: median word_recall in [0.5, 0.85)** | Marginal, and the cheaper fix is on Tower: lexical retrieval only needs a document's *distinctive words* to survive (report §3), so try character n-gram or fuzzy indexing in `retrieval.py` before touching the camera. |
| **Exp 3: median word_recall < 0.5**, *and* the 720p control arm materially better | The requirement stands, on real evidence. `TOWER-TO-IOS.md` §6.8 gets a real row beside its synthetic one, and the mechanism remains a Mac-side question under Rule 4. |
| **Exp 3: recall < 0.5 and the 720p control arm is no better** | Resolution is not the limiter — optics, motion blur or exposure are. Bursty capture would not fix it. This is the outcome the synthetic ladder structurally cannot predict, and it is why the control arm is not optional. |

### 4.7 What would *not* settle it

- Re-running the synthetic benchmark. It has been run.
- Adding 360×640 to `FRAME_SIZES` and re-rendering. That fixes the
  orientation gap (§4.1.3) and is worth doing, but it is still a render.
- Measuring detection cost at higher resolutions. Already measured
  (report §11), and it is not the question.
- Any argument from `mean_region_confidence` alone. It is model output,
  not accuracy (`ocr.py:16-19`).

---

## 5. Environmental Memory: what it would take, and what it must not be

### 5.1 Status (EXISTS)

**PLANNED. No code exists under `tower/`.**
`guidelines/docs/modules/ENVIRONMENTAL-MEMORY.md:3-5`. Its neighbour is
built and the boundary is drawn sharply in that same document:

> Scene Understanding deliberately **persists nothing** — no store, no
> journal, no imagery, enforced by test — precisely so that the decision
> to keep a durable record of the physical world lands here, where the
> retention, purge and privacy policy this document already demands can
> be applied to it. **Do not add a store to Scene Understanding; the day
> one is wanted is the day this module starts.**

And the document names itself the highest privacy exposure of the current
module set, with a hard precondition: it "must not begin real data
collection until the retention/deletion policy in `06-PRIVACY-DATA.md` is
actually implemented for this module, not merely documented"
(`ENVIRONMENTAL-MEMORY.md:20`).

### 5.2 The question, decomposed

*"What was in this room earlier?"* is three claims wearing one sentence.

| Claim | Available? |
|---|---|
| **"earlier"** — a time | **Yes**, exactly, as Tower-receipt time (§1.1) |
| **"was in"** — presence of a thing | **Partially.** Document Memory produces text observations today. Scene Understanding detects and tracks but persists nothing, deliberately. Object Memory has a record type but no producer — Tasks 4–8 are blocked at a user ruling (`2026-08-25-object-memory-spatial-context.md:196-198`) |
| **"this room"** — a place identity | **No.** §1.2. Not weakly; not at all |

The third one is the whole difficulty, and the temptation is to find a
weaker word for it. There is no weaker word that is honest. "Here",
"nearby", "the space you were in" and "this area" all assert a spatial
identity the system cannot establish.

### 5.3 What it should NOT be

Numbered because each is a refusal I would defend individually.

1. **It must not claim to localise.** No room, no place, no location, no
   "here" — not in output, not in a field name, not in a docstring. The
   Object Memory plan already committed to this refusal
   (`2026-08-25-object-memory-spatial-context.md:684-685`) and it applies
   with more force here, because this module's name invites it.

2. **It must not answer `what_changed(location_or_context)`.**
   `ENVIRONMENTAL-MEMORY.md:100` lists it among the candidate retrieval
   interfaces, and it is the single most dangerous API in that list. It
   is a **two-sided claim** — "X was here, and now it is not" — where
   only one side is observable. The module's own Failure Behavior section
   forbids exactly this: "Observation gaps cannot establish absence: if
   this module never observed something, that means unknown, not
   'confirmed not present' or 'confirmed unchanged.'" A system that
   answers *"the whiteboard was erased"* when it merely stopped looking
   has fabricated the more interesting half of its answer. **Refuse it in
   V1**, by name, in the module descriptor.

3. **It must not imply continuous surveillance of a space.** This is the
   failure mode most likely to happen by accident, because it happens
   through *omission*. A phone showing "47 observations in this room
   today" invites a wearer's guest to conclude the room is under
   continuous observation. It is not: on 2026-08-24, 435 seconds of
   walking produced 331 seconds inside a capture lineage and **104.9
   seconds of nothing at all** (§1.3). §5.4 turns this into a data-shape
   requirement rather than a UI-copy request.

4. **It must not be a raw archive.** `06-PRIVACY-DATA.md:37`: continuous
   raw video should not be retained by default.
   `ENVIRONMENTAL-MEMORY.md:33`: "This is not intended to be a raw
   surveillance archive." Note that a `TEXT_SEEN` event for every sign
   the wearer walks past, at ~12 fps, is a surveillance archive with
   better compression. **The relevance/novelty filter is a V1 requirement,
   not a V2 optimisation**, and it needs to be measured rather than
   guessed — the same discipline that set `MIN_ROW_TRANSITIONS = 8` from
   a distribution (`detect.py:52-71`).

5. **It must not be a store bolted onto Scene Understanding.** §5.1, and
   `CARTRIDGE-RESULTS.md:416-419`: giving Scene Understanding a store
   "would pre-empt Environmental Memory's whole reason to exist."

6. **It must not read another cartridge's storage.** Cartridges do not
   import each other — `tests/test_architecture_boundaries.py:398`,
   `:460`, and the corresponding rules for World Builder, Object Memory
   and Scene Understanding. `06-PRIVACY-DATA.md:43`: modules must not
   read another module's data without an explicit shared-data design.

7. **It must not become a shared memory substrate.**
   `2026-08-20-canonical-memory-architecture.md:38` forbids a shared
   service, database, retrieval API or embedding index now, and names the
   promotion trigger: **two** implemented memory modules with a concrete,
   repeated cross-namespace need. One implemented memory module exists.

8. **It must not populate a `spatial_ref`.** The field is reserved and
   nulled: `Keyframe.spatial_ref` is `null` on every one of the 155
   keyframes of the real walk (verified in
   `.../sessions/.../keyframes.jsonl`), and
   `ObjectObservation.spatial_ref` is hardcoded to `None` on read
   (`object_memory/records.py:88`).

9. **It must not persist people.** No biometric identity features
   (`ENVIRONMENTAL-MEMORY.md:167`), and the `person` ruling is already
   open and unresolved on Object Memory
   (`2026-08-25-object-memory-spatial-context.md:689-693`). An
   environmental memory sharpens the stakes rather than softening them:
   "who was around, where, and when" is a materially different privacy
   object than a list of furniture.

10. **It must not offer a wire contract before it has a consumer.**
    Building a transport for a consumer that does not exist is the
    fabricated contract this project refuses
    (`2026-08-25-object-memory-spatial-context.md:621-625`).

### 5.4 Making the gaps visible is a data-shape requirement

Refusal 3 above is the one that cannot be discharged with careful
wording, because the misreading comes from what is *absent* from the
answer. It needs a field.

**PROPOSED.** Every answer to a time-window question carries, beside the
observations:

```
window_seconds            the span asked about
observed_seconds          seconds inside a capture lineage
unobserved_seconds        window_seconds - observed_seconds
coverage_source           "capture manifests"
```

All four are computed from `capture.json` start/end times alone — no
inference, no model, no geometry. On the 2026-08-24 data a 435-second
window yields `observed_seconds: 330.1`, `unobserved_seconds: 104.9`,
and an answer that says "I was not looking for 105 of those 435 seconds"
is a fundamentally different object from one that does not.

This is the same instinct as `pages_total: null` with a note
(`retrieval.py:237-241`) and `frames_observed: null` while live
(`CARTRIDGE-RESULTS.md` §10.1): report the shape of what you did not see,
in the same breath as what you did.

### 5.5 The honest V1 "place": arguing it both ways

**The proposal.** The V1 unit of place is a **capture lineage plus a time
window** — never a room, never a place, never a location. Call it a
*stretch*.

**The case for.**

- It is **observed, not inferred**. A lineage is the transitive closure
  of `continues_capture` over manifests (§1.3). Nothing is estimated.
- It is **owned by shared transport**, so no cartridge needs to know
  about another to use it. `tower/capture.py` already owns
  `continues_capture` (`:362`), `resumable_capture()` (`:137`) and the
  90-second grace (`:60`); `capture_workers.py` already tracks a live
  chain (`:75`). This is the same posture the Object Memory plan settled
  on for `(capture_id, source_seq)`: "two cartridges agreeing on a frame
  identity that a third, shared component defines is not cross-cartridge
  coupling" (`2026-08-25-object-memory-spatial-context.md:236-240`).
- It **makes no spatial claim**, which is its whole virtue. It cannot be
  misread as a room because it is a property of a socket.
- It is **already recorded by the cartridge that would use it**:
  `DocumentObservation.capture_id` exists (`records.py:153`), as does
  `Session.capture_id` on the World Builder side.
- It **survives the reconnect reality**. Ten captures in 435 s collapse
  to three lineages (§1.3). A bare `capture_id` would over-fragment ten
  ways; a lineage over-fragments three.

**The case against, which is real.**

- **A lineage is not a place either.** The 105-second hole between
  lineage A and lineage B was a *network* event, not a doorway. A wearer
  who stayed in one room the whole time still produced three lineages,
  and a wearer who walked through four rooms without a disconnect
  produces one. The correlation between a lineage and a place is
  incidental.
- **A lineage boundary is invisible to the wearer.** Nothing in the
  wearer's experience marks it, so an answer scoped to one will
  occasionally cut a memory in half for no reason the person can perceive.
- **`continues_capture` depends on a 90-second constant** (`capture.py:60`,
  chosen because iOS's reconnect budget is ~45 s). Change it and the
  lineage structure of historical data changes retroactively when
  recomputed — the same instability that made the Object Memory plan
  refuse to *persist* `segment_index`
  (`2026-08-25-object-memory-spatial-context.md:568-578`).
- **The alternative — a bare time window with no place at all — is
  simpler and almost as good.** "What did I see between 14:02 and 14:20"
  needs no lineage, no manifest scan, and no new concept.

**Where I land.** Use the time window as the *query*, and the lineage as
*context reported beside the answer*, never as the query's scope. That
is: the wearer asks about a time; the answer says what was observed, and
adds "in two unbroken stretches of capture, with 105 seconds unobserved
between them." The lineage earns its place by explaining the gaps, not by
defining the boundaries. It is strictly additive, and it degrades to
nothing useful being lost if lineage reconstruction fails.

Consequently: **the lineage must be computed at query time from current
manifests and never persisted into an observation record**, for the same
reason `segment_index` must not be — its referent is unstable under a
constant nobody has finished choosing.

### 5.6 PROPOSED — the smallest honest slice, and it is not a module

Environmental Memory should not start. What should exist instead is the
one primitive it will need, in the place that already owns it, plus a
composition script.

**Part A — `capture_lineage()` in `tower/capture.py`.** A pure read over
manifests:

```
lineage_of(root, capture_id) -> list[str]      # oldest first, whole chain
lineages(root)               -> list[list[str]]
```

built from `continues_capture` and nothing else. It imports no cartridge.
It is the offline counterpart of a primitive that already exists three
times, live (`capture.py:569-586`, `capture_workers.py:75`, `:106`).
Roughly 40 lines and it belongs to transport, not to memory.

**Part B — `scripts/what_was_observed.py`.** A composition layer, in
`scripts/`, which is outside the import rules' scan root
(`tests/test_architecture_boundaries.py:12`) and is the sanctioned place
for a pairing (`2026-08-25-object-memory-spatial-context.md:583-591`). It
may import `tower.capture` and `tower.document_memory.retrieval`, and
later `tower.object_memory`. It:

1. takes a time window (`--since`, `--until`, or `--minutes-ago N
   --window M`, matching `scripts/document_query.py:54-65`);
2. asks Document Memory `around(when, window_seconds)`
   (`retrieval.py:142`) — no new retrieval code;
3. computes coverage from Part A;
4. prints the four coverage fields of §5.4 and the observations, and
   refuses in the module's own voice when there are none: *"No record of
   observing anything in that window. That is a statement about what was
   captured, not about the world."* — the wording
   `scripts/document_query.py:164-165` already uses.

**Data shape.** No new store. No new record type. No new namespace. The
answer is computed and discarded.

**What is deliberately absent:** no `tower/environmental_memory/`
package, no wire contract, no relevance filter (nothing to filter yet),
no novelty detection, no embeddings, no `what_changed`, no place
vocabulary.

**PROPOSED tests.**

| Test | Pins |
|---|---|
| `test_a_lineage_is_the_transitive_closure_of_continues_capture` | three captures chained resolve to one lineage |
| `test_a_capture_that_ended_by_clean_stop_starts_a_new_lineage` | the `79233e` case (`WORLD-BUILDER.md:245-249`) |
| `test_a_capture_with_no_manifest_is_reported_not_guessed` | a partial directory does not silently vanish from a chain |
| `test_capture_lineage_imports_no_cartridge` | Part A stays in transport |
| `test_the_answer_reports_unobserved_seconds_inside_the_window` | §5.4 |
| `test_an_empty_window_says_it_is_about_the_record_not_the_world` | the refusal wording |
| `test_no_output_contains_room_place_location_or_here` | refusal 1, as a string assertion over the rendered output |
| `test_nothing_named_what_changed_exists` | refusal 2, structurally |

### 5.7 What it would actually take to be a module

In dependency order. None of it is close.

| # | Prerequisite | Blocked by |
|---|---|---|
| 1 | **A second observation producer that runs.** Object Memory has records and no producer; Tasks 4–8 sit behind a user ruling | a decision, not code |
| 2 | **The `person` ruling** | escalated and unresolved |
| 3 | **A measured relevance/novelty filter** | needs real observation volume to tune against, which needs 1 |
| 4 | **Retention and purge implemented before any real collection** | `06-PRIVACY-DATA.md:66` makes this explicit for this module by name; Document Memory's store is the working precedent (`store.py:170-256`), including the defect where prune dropped journal records and left the pixels (report §9) |
| 5 | **A module descriptor declaring data behaviour** | `04-MODULE-SYSTEM.md`, required before implementation begins |
| 6 | **An honest place vocabulary** | today that is §5.5's stretch, and nothing better exists before calibration, relocalisation and loop closure — none of which are on any plan |
| 7 | **The canonical-architecture promotion trigger** | two implemented memory modules with a concrete repeated cross-namespace need |

Note the shape of that list: **six of the seven are not engineering.**
They are rulings, measurements and policy implementations. That is the
real answer to "what would it take".

---

## 6. Boundaries, and why they are these

| Boundary | Rule | Where the composition lives |
|---|---|---|
| Document Memory ← result channel | `tower/results/document_memory.py` is the only file allowed to import the cartridge | enforced by `test_the_result_channel_core_is_cartridge_blind` (`tests/test_architecture_boundaries.py:79-105`) |
| Document Memory ↔ World Builder | neither imports the other; spatial fields are supplied or absent | `test_document_memory_does_not_import_another_cartridge` (`:398`), `test_shared_code_does_not_import_document_memory` (`:460`) |
| Capture lineage | belongs to `tower/capture.py`, which already owns `continues_capture` | shared transport, no cartridge |
| Document Memory + capture lineage | a script | `scripts/what_was_observed.py` |
| Environmental Memory | does not exist and should not | — |

**Why a script and not a service.** `2026-08-20-canonical-memory-architecture.md:38`
is unambiguous: no shared memory service, database, retrieval API or
embedding index until two implemented memory modules show a concrete,
repeated need. One exists. A script named after the pairing is the right
size, and the next pairing gets its own file and inherits none of this
one's assumptions.

**Why the lineage function goes in `tower/capture.py` and not in a new
shared package.** Because that file already owns `continues_capture`,
`resumable_capture()` and `RESUME_GRACE_SECONDS`. Putting the offline
read anywhere else would create a second source of truth about what a
lineage is, and the two would disagree the first time the grace window
moves.

**Why Document Memory does not gain a World Builder link.** It already
declined one, with two reasons that both still hold
(`DOCUMENT-MEMORY.md:207-215`): it must not import World Builder, and —
the better reason — "World Builder's blur and motion gates would reject
exactly the frames this cartridge wants. A held-still, high-detail view
of a page has near-zero parallax and is `insufficient_motion` to a
mapper. This cartridge inverts World Builder's signal."

---

## 7. Ordering

| # | Step | Blocked by | Cost |
|---|---|---|---|
| 0 | **Experiment 1** (§4.3) — detector over 2,806 real frames | nothing | ~10 s of CPU, zero installs |
| 1 | §3.7(c) — record `read_at_*` and `warped_*` on every page | nothing | small; satisfies half of `TOWER-TO-IOS.md` §6.8 with no iOS change |
| 2 | §3.7(a)(b) — `recogniser_id`, and a text source meaning "none" | nothing | small; both are honesty defects |
| 3 | `TOWER_DOCUMENT_ROOT` in `tower/config.py` | nothing | trivial |
| 4 | `tower/results/document_memory.py` + registry entry + contract id (§3) | 1–3, because the payload references those fields | one file, one branch, one entry |
| 5 | Add `(360, 640)` to `FRAME_SIZES` and re-run the synthetic ladder | nothing | minutes; closes the orientation gap in §4.1.3 |
| 6 | **Experiment 2** (§4.4) | an `[ocr]` install | ~4 min of compute |
| 7 | **Experiment 3** (§4.5) | 60 s of hardware and three printed pages | the only step that settles §4 |
| 8 | `capture_lineage()` + `scripts/what_was_observed.py` (§5.6) | nothing | ~40 + ~120 lines |
| 9 | Anything named Environmental Memory | §5.7, six of seven items | not now |

Steps 0–5 and 8 need no hardware, no models and no rulings.

---

## 8. Open questions I could not resolve from the repository

1. **Should the socket handler refuse a non-null `world_id` /
   `session_id` on a `document_memory` subscription?** The validation
   path accepts both for any cartridge (`routes/results_ws.py:93-102`),
   and refusing would put cartridge-specific knowledge in a
   cartridge-blind file. Ignoring them silently is the alternative and is
   also imperfect. The offer could carry an `addressed_by` list; that is
   a channel-wide design decision, not this cartridge's.

2. **How does full document text ever cross?** iOS's shape is explicit —
   the list carries a character count, full text is fetched when a person
   opens one (§3.2) — and the channel has no request/response. Three
   candidates, none obviously right: a `document` result type addressed
   by a new `document_id` field on subscribe (adds a field to a shared
   path and makes every open document a polled target); a new message
   pair outside the result channel; or an HTTP route, which iOS cannot
   use because it "owns exactly one WebSocket and has no HTTP client"
   (`CARTRIDGE-RESULTS.md:49-51`). **This is the second-largest decision
   in this document and I did not settle it.**

3. **Do the three detector gates fire on real paper?** Unmeasured.
   Experiment 1 answers it and nothing else does.

4. **Is 360×640 portrait materially worse than 640×360 landscape for a
   page?** Same pixel count, different sampling of the page's long edge.
   Unmeasured; step 5 of §7 answers it synthetically and Experiment 3
   answers it for real.

5. **Is there any path to a higher-resolution still on this hardware at
   all?** §4.5's control arm depends on it, and `TOWER-TO-IOS.md:735-739`
   says the mechanism is a Mac-side question under Rule 4. If the answer
   is no, the entire bursty-capture branch is moot regardless of what
   recall measures.

6. **Can two `CaptureFollower`s tail one capture concurrently?** Document
   Memory and World Builder would both want to. Following is read-only,
   so it ought to work, but nothing tests it and nothing documents it.
   Carried over unresolved from
   `2026-08-25-object-memory-spatial-context.md:713-716`.

7. **Should `DocumentObservation` record the capture lineage root
   alongside `capture_id`?** §5.5 argues the lineage must be computed at
   query time because the 90-second grace is not settled. But
   `capture_id` is already persisted, and the lineage is derivable from
   it, so the question is only about caching. I lean no.

8. **What retention window is right for document text?** 30 days is the
   driver's default (`scripts/document_memory_session.py:79-83`) and it
   was chosen so that "forever" had to be selected rather than inherited
   (`store.py:47-53`). It has never been reviewed against what a person
   would actually want for the most sensitive class of data on the
   platform, and it should be, before the first real document is stored.

9. **Where is the 2026-08-24 sender-health run recorded?** The figures
   given for it — ~24 FPS captured, ~12 FPS transmitted, 97 frames in
   8.1 s, zero drops of every kind — do not appear in any document under
   `tower/docs/` or `ios/docs/`. The delivered rate is corroborated
   independently by `data/captures/` (§4.1.4), but the run itself should
   be written down somewhere, because §4's whole argument leans on it.
