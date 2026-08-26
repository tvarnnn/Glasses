# Object Memory observations — the Tower↔client boundary

**Living document.** It describes the boundary as it exists now.

| | |
|---|---|
| Contract | `object_memory.observations/2026-08-26` |
| Transport | HTTP `GET`, two endpoints. **Read-only** — see §2 |
| Tower adapter | `tower/tower/results/object_memory.py` |
| Tower routes | `tower/tower/routes/observations.py` |
| Store | `tower/tower/object_memory/store.py` |
| CLI (same questions, plus deletion) | `tower/scripts/object_query.py` |
| Tests | `tower/tests/test_object_memory_transport.py` |
| iOS consumer | none yet |

**Status:** Tower half implemented and exercised against the real 55-observation
corpus in `tower/data/object_memory`. No client has been written against it.

The contract identifier is **opaque and dated**. It is compared for equality and
nothing else — never parsed, never split on `/`, never ordered. A newer date is
not "greater than" an older one; it is a different contract.

---

## 1. What this cartridge actually knows, and what it does not

This section is the contract, not a preamble to it. A client that implements the
field tables in §4 while ignoring this section will make claims the sensor cannot
support.

**A record means a category was visible once.** Not that the object is still
there. Not that it will be there later. Every observation carries
`claim: "category-was-visible-once"` so this is a value a decoder can switch on
rather than a sentence in a document.

**A record is about a category, not an instance.** `laptop` means *a* laptop was
in view. It is not "your laptop", and two records of `laptop` are not evidence
about the same object. Every observation carries
`identity: "category-not-instance"`. Persistent identity is forbidden outright by
the cartridge brief (`07-PLATFORM-CONSTRAINTS.md` Core Principle 3); nothing here
re-identifies an object across sightings, and a client must not present it as if
it does.

**Absence of a record is not evidence of absence of the object.** Every payload
carries `absence_means: "not-observed-by-this-cartridge"`. A missing record means
the camera was not pointed at it, or the detector scored it below threshold, or
its class is not one this cartridge ever writes, or its retention window closed.
None of those is "the object is not there". This is why
`GET /object-memory/last-seen/{object_class}` answers **200 with
`observed: false`** and never 404 (§3.2) — a 404 reads as "there is no laptop",
which is a claim about the world.

**"Where" is a frame reference, not a place.** Every observation carries
`spatial_ref: null`. The field is reserved, never populated, and actively nulled
on read: nothing in this cartridge knows where anything is in a room. The `where`
object answers the question as a pointer back into a recording — which capture,
which frame sequence number, which camera — and says so in
`where.kind == "frame-reference"`.

`spatial_ref` travels as an **explicit null** rather than being omitted, at both
the envelope and the record level. An absent key looks like version skew and
invites a client to go looking for the value elsewhere; a null is an answer.

**The only position offered is inside a frame.** `bounding_box_normalized` is
nested **inside** `where`, not beside it. At the top level a box reads as a
position; under `kind: "frame-reference"` it reads as what it is — where in a
picture, not where in a room. A client must not project it into any world frame.

---

## 2. Read-only, and what that protects

Both endpoints are `GET`. There is no write, no delete, and no path by which one
can be added without a test failing.

`ObservationStore` does have `purge()` and `prune_expired()`. **Neither is on the
wire, and neither may go on it.** An unauthenticated HTTP endpoint on a LAN-local
origin that erases a wearer's memory is not a feature. `06-PRIVACY-DATA.md`
requires real deletion, and real deletion stays with
`scripts/object_query.py --purge-all`, where a human types it against a store
they can name.

Two tests hold this:

- `test_the_router_exposes_only_reads` — the router's method set is exactly
  `{"GET"}`.
- `test_no_wire_module_can_reach_purge_or_prune` — an AST scan of both wire
  modules for a call to `purge` or `prune_expired`. An AST scan rather than a
  grep, so a comment explaining why they are absent does not trip the rule.

**What deletion would not reach anyway.** A record's `session_id` + `frame_seq`
resolves into `data/captures/`, where the JPEG it was derived from is still
sitting. Object Memory's retention governs *this store and nothing else*.
Every `where` object therefore carries `imagery_retention: "capture-side"`:
purging every observation here leaves the imagery exactly where it is, and
capture-side retention is not this cartridge's to promise or to give away.

This is also why a record with a frame pointer carries `frame-referenced`
alongside `derived-only` in `privacy_tags`. `derived-only` is a true claim about
the record's *content* — a class label, a score and a box, no pixels — and was
read as a claim about its *reach*, where it was false.

---

## 3. Endpoints

Both handlers are declared `def`, not `async def`. FastAPI runs a sync endpoint
in its threadpool, which keeps the JSONL read off the event loop with no executor
of our own — the same reason `tower/tower/routes/geometry.py` gives for the same
choice, and pinned by
`test_the_handlers_are_sync_so_disk_reads_stay_off_the_event_loop` because it is
the whole mechanism.

Both answer **404** when `TOWER_OBSERVATION_ROOT` is unset. That 404 is a
statement about *configuration* — "this Tower serves no object memory" — and is
never the answer to a query about a class. Unset is the default: a memory of what
a wearer's camera saw does not go on the network because a process happened to
start in a directory that has one.

### 3.1 `GET /object-memory/observations`

Every observation still within the retention window, **newest first** by
`observed_at`.

| Query parameter | Type | Default | Meaning |
|---|---|---|---|
| `object_class` | string | *(none)* | Narrow to one class. Absent means all classes. |
| `retention_days` | float ≥ 0 | *(none)* | Narrow the window this read may see. See §5. |

`retention_days` below 0 is refused with **422** by the route rather than
reaching the store, which raises `ValueError` on a negative window and would
surface as a 500.

### 3.2 `GET /object-memory/last-seen/{object_class}`

When a category was last in view, or an honest silence. Accepts the same
`retention_days` parameter.

`{object_class}` is URL-encoded; classes with spaces (`cell phone`) work.

**Always 200 when a root is configured.** There is no 404 for an unobserved
class — see §1.

---

## 4. Fields

### 4.1 Envelope (both endpoints)

| Field | Type | Notes |
|---|---|---|
| `contract` | string | `object_memory.observations/2026-08-26`. Equality only. |
| `claim` | string | `category-was-visible-once` |
| `identity` | string | `category-not-instance` |
| `absence_means` | string | `not-observed-by-this-cartridge` |
| `spatial_ref` | **always `null`** | Reserved, never populated. Carried so a consumer sees the field exists and is empty. |
| `recorded_classes` | array of string | The universe of what could ever appear. Currently `["laptop", "cell phone"]`. A class outside this list has never been looked for — a weaker silence than "looked for and not seen". |
| `retention` | object | See §5. |
| `object_class` | string \| **null** | The class the request narrowed to. `null` on an unfiltered listing. |

### 4.2 `GET /object-memory/observations` adds

| Field | Type | Notes |
|---|---|---|
| `observation_count` | integer | Length of `observations`. Counts what is **served**, which is what is within the clamped window — not what is on disk. |
| `observations` | array of observation | Newest first by `observed_at`. |

### 4.3 `GET /object-memory/last-seen/{object_class}` adds

| Field | Type | Notes |
|---|---|---|
| `recordable` | **boolean** | Whether this class is one the cartridge ever writes. `false` means its absence carries no information at all. |
| `observed` | **boolean** | `observed`, never `present`. True means a record exists, not that the object is there. |
| `observation` | observation \| **null** | `null` when `observed` is false. |
| `where` | frame reference \| **null** | Hoisted from `observation` because "where did I leave it" is the question a client will bind to this response. `null` when `observed` is false. |

### 4.4 Observation

| Field | Type | Notes |
|---|---|---|
| `object_class` | string | One of `recorded_classes`. |
| `claim` | string | `category-was-visible-once`, repeated per record so a client holding one record out of context still has it. |
| `identity` | string | `category-not-instance`, likewise. |
| `confidence` | string | `low` \| `medium` \| `high`. **The field a consumer should read.** Derived from `best_score` — the claim is "this was in view", and the best look is the best evidence for it. |
| `detector_score` | float \| **null** | **Provenance.** How confident the detector was in the frame that *first* brought the class into view — the one frame `observed_at`, `frame_seq` and the box all describe. Never revised. |
| `best_score` | float \| **null** | **Evidence.** Strongest score while that sighting stayed in view. `null` means *not tracked* — a record written before this field existed. Never `0.0`, which would be a claim of no evidence. |
| `observed_at` | float (epoch seconds) | When the category came into view. Qualified by `time_basis`. |
| `time_basis` | string | `tower-receipt`. This slice can only know Tower-receipt time, never on-glasses capture time; `Rule 16` forbids conflating them. A client must not present this as a shutter time. |
| `recorded_at` | float (epoch seconds) | When *we* stored it. This is the privacy-relevant clock and the one retention filters on (§5). |
| `module_id` | string | `object-memory`. |
| `retention_tag` | string | The record's own retention class. |
| `privacy_tags` | array of string | `derived-only`, plus `frame-referenced` when a frame pointer is present. See §2. |
| `where` | frame reference | See §4.5. |

None of the three strength fields is a calibrated probability. They are detector
output, and an interpretation of detector output.

### 4.5 Frame reference (`where`)

| Field | Type | Notes |
|---|---|---|
| `kind` | string | Always `frame-reference`. **Not a place.** |
| `spatial_ref` | **always `null`** | Reserved, never populated, actively nulled on read. |
| `session_id` | string \| **null** | The capture this frame belongs to. `null` when the record carries no capture provenance. |
| `frame_seq` | integer \| **null** | Sequence number within that capture. |
| `camera` | string | e.g. `glasses-camera`. Renamed from the store's `source`, because "source" invites being read as a provenance system. |
| `bounding_box_normalized` | array of 4 floats \| **null** | Where in the *picture*, in normalised frame coordinates. **Not a world position.** Nested here, never at the top level. |
| `imagery_retention` | string | `capture-side`. This pointer resolves into `data/captures/`, whose lifetime this cartridge neither sets nor enforces. |

---

## 5. Retention — narrowable, never widenable

**This is the sharpest constraint in the contract.**

`retention_days` is a **request, not an authority**. The store records the window
it was *written* under in a manifest beside the data, and clamps every read to
`min(persisted, requested)`. A caller may narrow the window it sees and **nothing
a caller passes can widen it**.

This hole has been found here before. At the CLI layer,
`--retention-days 3650` against a store written under the 30-day default served a
40-day-old record in full, and retention under `06-PRIVACY-DATA.md` stopped being
a promise at all. HTTP is a new layer and therefore a new chance to reintroduce
it. The route adds nothing of its own that could weaken the clamp — it converts
days to seconds and hands them to the store — and
`test_a_reader_cannot_widen_retention_over_the_route` attempts the widening over
the wire against a store holding a genuinely out-of-window record.

`retention_days = 0` means **"no limit of my own"**, matching the CLI. It does
*not* mean "keep forever": it is still clamped to the persisted window.

The clamp is **reported**, not merely applied. A client that asked for 3650 days
and silently received 30 would have no way to learn its question was refused.

| `retention.*` | Type | Notes |
|---|---|---|
| `requested_days` | float \| **null** | What the caller asked for. `null` when the caller asked for nothing. |
| `effective_days` | float \| **null** | What will actually be honoured. `null` is *unbounded*, reachable only when the store itself was written unbounded. **Never `0`** — 0 days would mean "nothing is visible", the opposite claim. |
| `clamped` | **boolean** | `true` only when the caller asked for **more** than it received. A caller that asked for nothing has been refused nothing; a caller that asked for less got what it wanted. |
| `policy` | string | `min(persisted, requested): a reader may narrow this window and can never widen it` |

Filtering is on `recorded_at`, not `observed_at`: retention is about how long
*we* have held the data. The two are equal today and diverge the moment a real
capture timestamp is threaded through.

The store's `include_expired` opt-out is **never** passed from the wire. It
exists for maintenance paths — purge counting what it deletes, an operator
auditing the file — and is never the right answer for anything a wearer will be
shown, which is everything on this transport.

### Observed behaviour against the real corpus

`tower/data/object_memory` holds 55 real observations under a persisted 30-day
window. With one record backdated 40 days in a scratch copy:

| Request | `observation_count` | `effective_days` | `clamped` |
|---|---|---|---|
| *(no parameter)* | 54 | 30.0 | `false` |
| `retention_days=3650` | **54** | **30.0** | `true` |
| `retention_days=0` | **54** | **30.0** | `true` |
| `retention_days=0.5` | 0 | 0.5 | `false` |

The expired record cannot be recovered by asking.

---

## 6. Encoding disciplines

- **`null` means absent — never `0`, never `""`.** A missing `detector_score` or
  `best_score` is `null`. Substituting a number would invent evidence.
- **Booleans are booleans.** `bool` subclasses `int` in Python, and a `1` where a
  client expects `true` fails every Swift `as? Bool` decode. `observed`,
  `recordable` and `retention.clamped` are pinned as real booleans by
  `test_booleans_are_booleans_and_not_ints`.
- **The contract identifier is opaque.** Equality only.
- **Additive fields are not a contract bump.** A field an older decoder ignores
  does not break it. Removing a field, renaming one, or changing what an existing
  one *claims* does — and a change to any of the §1 claim values is the most
  breaking change this contract can carry, because it changes what the data
  means rather than what it contains.

---

## 7. Configuration

| Variable | Default | Effect |
|---|---|---|
| `TOWER_OBSERVATION_ROOT` | *(unset)* | Directory holding `observations.jsonl` and `manifest.json`. Unset ⇒ both endpoints answer 404. |

Read-only to the web process: it never observes and never deletes. The producer
is `scripts/object_memory_session.py`, in its own process; deletion is
`scripts/object_query.py --purge-all`, typed by a human. Startup logs which of
the two states this Tower is in, so a silently dark endpoint is visible in the
log rather than discovered by a client.
