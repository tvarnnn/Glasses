# Scene Understanding and Document Memory — handoff to the Mac/iOS lane

**Written 2026-08-27 by the Tower/cartridges lane**, on branch
`integration/document-scene-cartridges-v1`, from `6e325f8`.

> **This lane holds no Swift toolchain and did not touch `ios/`.** Nothing
> here is a Swift change and nothing here has been compiled. It is a
> specification of what the Tower now serves, written so the Mac lane can
> implement against it without reading Tower source. Where it disagrees
> with `docs/agent-handoffs/IOS-EXECUTION-PLAN.md`, the plan is older and
> this file is what the Tower actually does — but say so rather than
> assuming.
>
> **It supersedes §5.3 of the execution plan**, which says "build no
> Scene Understanding UI". That instruction was correct when the Tower
> offered nothing. It no longer does.

The full field-by-field contract is
`tower/docs/contracts/CARTRIDGE-RESULTS.md` **§14** (Scene Understanding)
and **§15** (Document Memory). This file is the integration view: what to
call, what to expect, what will surprise you, and how to physically test
it.

---

## 0. The one-paragraph version

Two cartridges that iOS previously saw as "the Tower says nothing" now
appear in `/cartridges` with dated contracts. **Both are unavailable
until configured**, which is iOS's third state — "connect" — and not
"update the app". Scene Understanding pushes a small live payload on the
existing result socket and is controlled by five HTTP routes. Document
Memory pushes a small session status on the socket and serves its
documents over HTTP, because document text is the largest and most
sensitive thing this platform could put on a socket that shares its lock
with the frame path.

**Neither has ever met a real subject.** Scene Understanding has never
seen a bystander; Document Memory has never seen a sheet of paper. Both
payloads say so as data. §7 is the physical test that would change that,
and it needs a person wearing the glasses.

---

## 1. Declaration

`GET /cartridges`, and `{"type": "cartridges"}` on the socket, return the
same object byte for byte. Three offers now:

```json
{
  "type": "cartridges",
  "envelope_contract": "cartridge_results.envelope/2026-08-23",
  "cartridges": [
    {"cartridge": "world_builder",       "result_type": "status",
     "contract": "world_builder.status/2026-08-25",       "available": …},
    {"cartridge": "scene_understanding", "result_type": "live",
     "contract": "scene_understanding.live/2026-08-27",   "available": …},
    {"cartridge": "document_memory",     "result_type": "status",
     "contract": "document_memory.status/2026-08-27",     "available": …}
  ],
  "not_offered": [{"cartridge": "experimental_cv", "reason": "…"}]
}
```

`ProductShellTests.testTheTowerDeclaresNoCartridgeContracts` will fail.
That failure is the intended signal to review every consumer.

**Availability is about configuration, never about activity.**

| Environment | `scene_understanding.available` | `document_memory.available` |
|---|---|---|
| nothing set | `false` | `false` |
| `TOWER_SCENE_UNDERSTANDING=true` | `true` | `false` |
| `TOWER_DOCUMENT_ROOT=…` | `false` | `true` |

An unavailable offer's `unavailable_reason` **names the environment
variable**. Render it; it is the only thing that tells a person the
difference between "this Tower cannot" and "nobody switched it on".

A Scene Understanding that is enabled but **stopped** is `available:
true`. Do not treat "no session running" as unavailable.

---

## 2. Scene Understanding

### 2.1 Subscription

```json
{"type": "result_subscribe",
 "cartridge": "scene_understanding",
 "result_type": "live",
 "contract": "scene_understanding.live/2026-08-27"}
```

`result_type` is **`live`**, not `status`. Subscribing with `status`
returns `unknown_result_type`, which is deliberate: the wrong half of a
pair must refuse rather than fall through to the only offer the cartridge
has.

Everything else — ack, `seq`, `revision`, `coalesced`, `cursor_status`,
errors, the 8-subscription cap — is the machinery you already have.

### 2.2 A phone starts it by streaming, and calls nothing

**This is the part most likely to be got wrong, because it is the part
that changed after the first review.** iOS sends nothing when a cartridge
is opened (§6.2), so nothing on the wire could start a session — the
contract was `available: true`, subscribable, and answered
`scene_available: false` forever unless a human curled the Tower.

So the session follows the **stream**:

| Event | Effect |
|---|---|
| `stream_start` | the session starts (model loads, `state: "starting"`) |
| `stream_stop` | the session stops and the scene is discarded |
| disconnect | the same — and this is the normal case for a wearable |

`lifecycle.follows_stream` reports whether that is on.
`TOWER_SCENE_AUTOSTART=false` turns it off for an operator who wants
manual control.

**A stop only ever ends what the stream started.** A connection that
never sent `stream_start` cannot end a session an operator began by hand,
which is the situation a physical test lives in.

Consequence for iOS: open the workspace, subscribe, and stream. Counts
appear a second or two later, once the detector has loaded. There is no
"start" button to build unless you want one — and if you do, it is
`POST /scene/start`.

### 2.3 The lifecycle state machine

```
                    POST /scene/start
   stopped ─────────────────────────────► starting ──► running
      ▲                                      │            │
      │  POST /scene/stop                    │ load fails │ POST /scene/pause
      │  (from ANY state)                    ▼            ▼
      └──────────────────────────────────  failed       paused
                                                          │
                                    POST /scene/resume ───┘
                                    (or /scene/start)
```

`lifecycle.states` carries the closed vocabulary on every payload; pin
against that rather than hard-coding it.

| State | `scene_available` | What to render |
|---|---|---|
| `stopped` | `false` | "Not observing." Never an empty room. |
| `starting` | `false` | "Preparing…" with `loading_seconds`. If `load_overdue` is true, say it is taking longer than expected — **do not** call it a failure; a first-run weight download is slow and still correct. |
| `running` | `true` once a frame has been observed | the scene |
| `paused` | `true`, with `lifecycle.scene_is_current: false` | the scene, **labelled as last known**, with its age announced BEFORE its contents |
| `failed` | `false` | `lifecycle.failure_reason` verbatim |

`lifecycle.session_id` increments on every Start. **Two payloads with
different `session_id` came from different tracking sessions and must not
be compared or accumulated.**

### 2.4 Stop discards the scene, and you must not re-add it

After `POST /scene/stop` the payload carries `scene_available: false`,
`counts: null`, `people: null`, `where: null`. The Tower has thrown the
scene away.

**Do not cache the last scene across a stop.** A scene retained past the
end of a session is a claim about a room the wearer has left. iOS's own
`SceneUnderstandingState` distinguishes `observing` from `lastKnown`; a
stopped session is neither, and the right rendering is the reason string.

### 2.5 What you get, and what you asked for and did not get

| `IOS-to-Tower.md` | Served? |
|---|---|
| §4.1 anonymous track handle | **NO.** Refused, and the refusal is on the wire: `tracks: null`, `tracks_absent_reason`, `refused_entity_fields`. See below. |
| §4.1 person vs object | Yes — `people` is separate from `counts` |
| §4.1 object class label | Yes — `counts` keyed on `reported_classes` |
| §4.1 confidence per track | **NO**, and said so: `confidence: null` with `confidence_absent_reason`. There are no tracks for one to attach to |
| §4.2 orientation, `unknown`/`towardCamera`/… | **Aggregate only** — `people.facing_wearer` is a COUNT or null |
| §4.3 bearing, signed | **NO.** `where` gives side counts for non-person labels only — but it states its convention in `side_convention`, because a left and a right with no stated side is the silent presumption §4.3 warns about |
| §4.3 distance, unit, scale semantics | **NO.** Nothing here knows a distance |
| §4.4 counts | Yes, and every one is a declared lower bound |
| §4.5 no "behind you" | Honoured — there is no bearing at all |
| §4.6 relationships | **Refused**, with reasons, unexpressibly |
| §4.7 staleness | Yes — `observed_at`, `staleness_seconds`, `scene_is_current` |
| §4.8 coalesce before publishing | Yes — 0.5 s poll, 2 s heartbeat, volatile fields excluded from `revision` |
| §4.9 persists nothing | Yes, and enforced by an AST test over the whole wire path |

**The refusal of the track handle is deliberate and it costs you the
entity list.** The reasoning is in §14.5 of the contract and is worth
reading before proposing a change: the phone already has the pixels, so a
count discloses nothing new — but a stable handle plus a timestamp lets a
recipient assemble the per-person dwell timeline the Tower refuses to
keep. Without per-person position (also refused) a handle would carry
nothing but that timeline.

**Concretely: you can render "2 people" and "a chair to your right". You
cannot render "Person 1 / Person 2" rows.** If the product needs those
rows, say so and it becomes a contract change with a new identifier — not
a field quietly populated later.

Decode `tracks_absent_reason` and `refused_entity_fields` and render them
somewhere. A client that shows an empty entity list is saying "nobody is
here"; a client that shows the reason is saying what is true.

### 2.6 Three things that will bite

1. **`people.facing_wearer` is `null`, not `0`, when unmeasured.**
   Orientation is off by default (956 ms per call on CPU). Render null as
   a refusal string — "not measured" — and never as zero. A test on your
   side asserting that is worth having; `facing_answered` is the boolean
   to switch on.
2. **Every count is an undercount.** `count_is_lower_bound` is always
   `true` and `count_limitations` says why: recall 0.306 for `person`
   against an oracle that shares its training data, and effectively blind
   below ~2% of frame area. An undercount rendered without that
   disclosure looks exactly like a quiet room. Put it somewhere a person
   sees.
3. **`people.may_include_wearer` is `true` and `validated` is `false`.**
   Every `person` box in this platform's only real corpus is the wearer's
   own torso. "2 people" may mean "you, and one other" or "you, twice".

### 2.7 Control routes

| Route | Method | 404 when |
|---|---|---|
| `/scene` | GET | not enabled |
| `/scene/start` | POST | not enabled |
| `/scene/pause` | POST | not enabled |
| `/scene/resume` | POST | not enabled |
| `/scene/stop` | POST | not enabled |

Each returns the **full payload**, plus a `contract` key. `GET /scene` is
the same function the socket uses, so the two cannot disagree.

**Recommended UI:** a single Start/Stop control, and a Pause. Show
`frames_skipped` only in a diagnostic view — but do watch it: a sustained
non-zero value means this Tower is overloaded and the counts are less
stable than they look.

---

## 3. Document Memory

### 3.1 The split

**Session progress on the socket. Documents on HTTP.** Do not expect the
documents to arrive on a subscription; they never will.

```json
{"type": "result_subscribe",
 "cartridge": "document_memory",
 "result_type": "status",
 "contract": "document_memory.status/2026-08-27"}
```

The payload has two blocks that must not be confused:

- **`library`** — what is on disk, regardless of whether anything is
  running. `available`, `document_count`, `newest_observed_at`, `bytes`.
- **`session`** — the live capture, or
  `{"state": "unavailable", "reason": "…"}` when
  `TOWER_DOCUMENT_CAPTURE` is off.

**A Tower with a library and no session is normal**, not degraded: it
serves documents recorded elsewhere and records nothing itself.

### 3.2 HTTP routes

| Route | Returns |
|---|---|
| `GET /documents?limit=&retention_days=` | recent documents, newest first, **no text** |
| `GET /documents/search?text=&limit=` | BM25 matches with snippets |
| `GET /documents/around?at=&window_seconds=` | documents observed within a window |
| `GET /documents/{document_id}` | one document **with** its pages and their text |
| `GET /documents-session` | the session status |
| `POST /documents-session/{start,pause,resume,stop}` | control it |

All answer `404` when `TOWER_DOCUMENT_ROOT` is unset — a claim about
**configuration**, never the answer to a query.

`limit` is capped at 200 on the listing and 50 on search.

### 3.3 The three answers — the thing most likely to be got wrong

Every library response carries `answer`:

| `answer` | iOS case | Render |
|---|---|---|
| `matched` | `.matched` | the list |
| `not_found` | `.notFound` | "Nothing matched." |
| `no_observation` | `.noObservation` | "Never observed" — **and state explicitly that this is not the same as the document not existing** |

`no_observation_note` carries the sentence to say. **On this platform
`no_observation` is the normal answer today**, because the page detector
fires on essentially nothing at the delivered geometry. A client that
renders it as "no documents yet" is inviting a person to wait for
something that is not coming.

### 3.4 What a listed document carries

`title` (may be null → "Untitled document", **never** an invented name),
`text_availability` (`unknown` / `not_readable` / `extracted` with a
`character_count`), `confidence`, `observed_at`, `observed_seconds`,
`pages_observed`, `provenance`, `timing`, `privacy_tags`.

**`observed_seconds` is time IN VIEW.** It is not a claim that the wearer
looked at it, noticed it, or read it. Render "In view 45 s"; never
"viewed for" or "read for". `observed_seconds_note` carries that as data.

**`summary` is not in the list.** The stored summary is the document's
first forty words verbatim — an excerpt — and forty words per document
across a list is a bulk transfer of what a wearer read.
`summary_available` says it exists; fetch the document to get it.

**`not_readable` is a real answer**: "we looked and found no readable
text" is a different fact from "we never looked", and the store records
both.

### 3.5 Session lifecycle

**Document Memory does NOT follow the stream by default**, unlike Scene
Understanding, and the asymmetry is deliberate: this cartridge writes to
disk, and a session that persists what a wearer read gets an explicit
start. `TOWER_DOCUMENT_AUTOSTART=true` changes it.
`session.follows_stream` reports which.

The half of this cartridge a phone actually reaches is the library, over
HTTP, and that works whether or not anything is recording.

**The five session routes carry the full envelope**, not a bare status —
`contract`, `claim`, `recording_limitations`, the imagery fields, with
the lifecycle under `session`. A client that polls the session and never
calls a listing would otherwise never learn that an empty library is the
expected result here.

**The session block keeps its shape.** When no session exists every field
is present and `null`, `state` is `"unavailable"`, and `states` carries
the full vocabulary including that value. Decode it strictly.

### 3.6 Session counters

Identical shape to Scene Understanding's, plus `in_dwell`,
`pages_detected`, `documents_recorded`, `last_document_id`,
`retention_days`, `documents_pruned`, `retention_incomplete`,
`library_count`.

**Stop KEEPS what was recorded**, unlike Scene Understanding's Stop. A
dwell in progress is flushed rather than dropped.

`retention_incomplete: true` means a deletion could not be completed — a
locked file, most often. Surface it: a retention promise that quietly
failed looks exactly like one that was kept.

### 3.7 What is refused

| `IOS-to-Tower.md` | Served? |
|---|---|
| §3.1 list, id, title, summary, confidence | Yes, except summary is per-document |
| §3.2 `unknown`/`notReadable`/`extracted(characterCount:)` | Yes, as `text_availability` |
| §3.3 observation time, time in view | Yes — **tower-receipt time only** |
| §3.4 `recent`, `text`, `observedWithin` | Yes |
| §3.4 `semantic` | **NO.** `semantic_retrieval: false`, with a reason. Route a description here and you get a lexical answer |
| §3.5 three answers | Yes |
| §3.6 pagination | **NO.** `limit` is the only bound |
| §3.7 thumbnails | **NO.** No image is served. `imagery_treatment: "raw-ephemeral-not-served"` |
| §3.8 `sessionID` / `worldID` | Partially — `provenance.capture_id` (unvalidated), `world_id`/`world_session_id` null unless supplied |

---

## 4. Imagery and redaction

**Neither cartridge serves an image.** Scene Understanding produces none.
Document Memory can be configured to keep cropped page images on disk,
but that is off by default, must stay off, and no route serves them.

Every Document Memory response carries
`imagery_treatment: "raw-ephemeral-not-served"` and every record carries
`redaction: "none"` — the honest value for imagery this platform cannot
redact. Per `IOS-to-Tower.md` §5, an unstated treatment is handled as
strictly as raw, and there is nothing here to display anyway.

**There is still no artifact fetch contract.** Do not build one against
these routes.

---

## 5. Fixtures — what to decode against

The Tower lane cannot hand you a `.json` fixture directory without
guessing at your test layout, so here is how to generate one against a
real Tower in under a minute. Every payload below is produced by the real
code path.

```bash
# Scene, with the real detector, no phone required.
TOWER_SCENE_UNDERSTANDING=true python -m uvicorn tower.main:app --port 8000
curl -s localhost:8000/cartridges                > cartridges.json
curl -s localhost:8000/scene                     > scene-stopped.json
curl -s -XPOST localhost:8000/scene/start        > scene-starting.json
# …point the glasses at a room, then:
curl -s localhost:8000/scene                     > scene-running.json
curl -s -XPOST localhost:8000/scene/pause        > scene-paused.json
curl -s -XPOST localhost:8000/scene/stop         > scene-stopped-after.json

# Documents, against a store the CLI can populate without hardware.
python scripts/document_memory_session.py --synthetic --root /tmp/docs
TOWER_DOCUMENT_ROOT=/tmp/docs python -m uvicorn tower.main:app --port 8000
curl -s localhost:8000/documents                          > documents-list.json
curl -s "localhost:8000/documents/search?text=the"        > documents-search.json
curl -s localhost:8000/documents/<id>                     > document-one.json
```

An **empty** Tower is the most important fixture and the easiest to
forget:

```bash
TOWER_DOCUMENT_ROOT=/tmp/empty python -m uvicorn tower.main:app --port 8000
curl -s localhost:8000/documents   # answer: "no_observation"
```

**Write the negative decode tests too.** A malformed payload must produce
`CartridgeFailure(kind: .undecodableResponse)`, not a partially populated
snapshot and not a stronger claim than the Tower made. Specifically:

- `facing_wearer: null` must not decode to `0`.
- `counts: null` must not decode to an empty dictionary.
- `answer: "no_observation"` with `documents: []` must not become
  `.notFound`.
- an unknown `lifecycle.state` must fail rather than downgrade.
- `tracks: null` must not decode to an empty entity array. It is a
  refusal, and an empty array reads as "nobody is here".
- `imagery_treatment` is `none-retained` or `raw-persisted`; neither is
  one of iOS's three states, which is why `imagery_ios_state` is carried
  beside it and is always `rawEphemeral`. Map from that field, never from
  the first.
- `library.document_count_unfiltered` and `session.library_count` are
  different quantities. Do not render them as one number.

---

## 6. Polling, cadence and staleness

| | Scene Understanding | Document Memory |
|---|---|---|
| Transport | result socket | result socket (status) + HTTP (documents) |
| Poll | 0.5 s | 0.5 s |
| Heartbeat | 2 s | 2 s |
| Excluded from `revision` | `observed_at`, `staleness_seconds`, all `frames_*` | `session.*` counters, `library.bytes` |

`revision_changed: false` means a heartbeat, not news. Skip the redraw.

**Do not poll the HTTP routes on a timer.** `GET /scene` exists for
operators and physical testing; the socket is the product path and it
coalesces for you. `GET /documents` parses the whole journal on every
call.

`staleness_seconds` is measured from when the **Tower received the
frame**, not when the detector finished with it. Announce the age of a
stale scene before its contents, as §4.7 asks.

---

## 7. Physical validation — what only a person can do

Everything below is blocked on hardware and a human. Neither cartridge
has ever met its subject.

### 7.1 Scene Understanding — the first bystander

**Nobody has ever worn these glasses in a room with another person and
checked what the Tower said.** Every `person` detection in the corpus is
the wearer's own torso.

1. `TOWER_SCENE_UNDERSTANDING=true`, `TOWER_SCENE_TORCH_THREADS=2`.
2. `POST /scene/start`, wait for `lifecycle.state: "running"`.
3. Connect the glasses. Stand in a room with **one** other person, in
   good light, at about 2 m.
4. Read `GET /scene`. **Record `people.count` against the truth.** The
   expected failure is an undercount — recall 0.306 — and the expected
   confound is the wearer's own torso inflating it.
5. Repeat at 4 m and with the person at the edge of view.
6. Walk. Watch `frames_skipped`: if it climbs, this Tower cannot keep up
   and the counts are less stable than they look.
7. `POST /scene/stop` and confirm `scene_available` goes `false`
   immediately, on both the route and the subscription.

**What would falsify the cartridge:** counts that do not track the truth
even loosely at 2 m, or a `person` count that never distinguishes one
bystander from none.

### 7.2 Document Memory — the first page

**No capture on this platform has ever contained a sheet of paper.** The
detector has never been shown a positive it was built for. This is the
single most valuable hour anybody could spend on this cartridge.

1. `TOWER_DOCUMENT_ROOT=…`, `TOWER_DOCUMENT_CAPTURE=true`.
2. `POST /documents-session/start`, wait for `running` (the OCR reader
   takes about 5 s to construct).
3. Connect the glasses. **Hold a printed page square-on at reading
   distance for 10 seconds**, well lit, filling most of the view.
4. `GET /documents-session` — did `session.pages_detected` move? Did
   `session.in_dwell` go true?

   **Expect zero.** Fed 5,204 real corpus frames through the live path,
   this session detected **0 pages and recorded 0 documents** — which is
   what the gate re-derivation predicts and is now confirmed end to end
   rather than only in a sweep. If your printed page moves either
   counter, that is the first positive this cartridge has ever seen and
   is worth writing down.
5. `GET /documents` — is there a document? Is its
   `text_availability.state` `extracted` or `not_readable`?
6. Repeat tilted, at arm's length, and in poor light.
7. Also record the **false positive** case: point at a venetian blind and
   at a backlit keyboard. Both used to fire and must not now.

**What would falsify it:** zero detections on a square-on page at
reading distance. That is the expected outcome at 360×640 and it is why
the measured fix is a high-resolution **still**, not a higher stream —
which needs DAT work this lane cannot do.

**What would validate it:** one document, with legible text, and a
`provenance.capture_id` that resolves to the capture you just recorded.

### 7.3 Coexistence

Run World Builder and Scene Understanding together for ten minutes and
watch `frames_skipped` on both, plus the Tower's own frame-path latency.
A scene session was measured at **1.03 cores with
`TOWER_SCENE_TORCH_THREADS=2`, and 4.12 cores without it**, at identical
throughput. Set it.

**It keeps up — on a machine with room.** Measured twice, on the same
corpus at the delivered 12.0 fps:

| host load | observed | skipped | rate |
|---|---|---|---|
| ~70% | 1,843 / 1,845 | **0.11%** | **11.96 fps** |
| 100% (other lanes) | 3,437 / 5,204 | 34% | 7.91 fps |

Wall-clock service time is ~84 ms against an 83.5 ms interval, so there
is no headroom: this cartridge is the first thing a loaded Tower will
starve, and it degrades by dropping frames rather than by falling behind.

What that costs you when it happens: the tracker's `max_misses` is a
FRAME count derived from a 1.0 s absence at 12 fps, so a session that is
skipping stretches what "1 second of absence" means. Watch
`frames_skipped`. The payload publishes it for exactly this reason.

Resident memory grew **7.8 MB** for Scene and **12.2 MB** for Document
Memory over seven minutes, and **0.55 MB** for Scene over a later 2.5
minute run once the model was warm — warm-up, not a leak. `offer_frame`, which runs on the event loop, cost **0.0099 ms at
the median and 0.035 ms at p95**. The frame path is untouched.

---

## 8. Rollback

Nothing in this work changes an existing contract, an existing route, or
an existing payload. To disable it entirely:

- unset `TOWER_SCENE_UNDERSTANDING` and `TOWER_DOCUMENT_ROOT`. Both
  offers become `available: false` with a reason; no session is
  constructed; no thread starts; no model loads.
- To remove the offers from the declaration altogether, revert
  `tower/tower/results/registry.py` — the two `CartridgeOffer` entries and
  the `NOT_OFFERED` change are the whole surface.

iOS should treat both cartridges as it treats any unavailable offer.

---

## 9. Where the Tower code is

| Concern | File |
|---|---|
| Contract identifiers | `tower/tower/results/contracts.py` |
| Declaration | `tower/tower/results/registry.py` |
| Scene payload | `tower/tower/results/scene_understanding.py` |
| Scene session | `tower/tower/scene/live.py`, `tower/tower/live_session.py` |
| Scene control | `tower/tower/routes/scene.py` |
| Document payloads | `tower/tower/results/document_memory.py` |
| Document session | `tower/tower/document_memory/live.py` |
| Document routes | `tower/tower/routes/documents.py` |
| Live construction | `tower/tower/cartridge_runtime.py` |
| Frame hand-off | `tower/tower/routes/ws.py` (`_offer_to_cartridges`) |

End-to-end tests, which double as executable examples of every payload:
`tower/tests/test_scene_wire_e2e.py`,
`tower/tests/test_documents_wire_e2e.py`.
