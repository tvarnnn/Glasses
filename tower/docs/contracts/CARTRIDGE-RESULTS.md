# Cartridge Results — the Tower → iOS structured result channel

**Status: IMPLEMENTED**, on branch `integration/cartridge-result-channel-v1`.
Everything in this document exists in code and is covered by tests. Where
something does not exist, it says so and says why.

**Envelope contract:** `cartridge_results.envelope/2026-08-23`
**Producers offered:** World Builder `status`, contract
`world_builder.status/2026-08-23`. Nothing else. See §9.

**Audience.** Whoever implements the iOS consumer. You should be able to
write it from this document without reading Tower's Python. If you find
yourself guessing, that is a defect in this document — say so rather than
guessing.

---

## 1. What this channel is, and what it is not

It is a **read-only reporting surface**. The Tower web process reports what
another process has already persisted. It does not run World Builder, does
not start builds, does not touch frames, and never writes.

That matters for what you can expect from it:

- Results are **snapshots**, never deltas. Each one is complete and
  supersedes every earlier one.
- Results are **coalesced**. If you read slowly you get the newest state,
  not a backlog.
- Nothing here is **live in the sensor sense**. World Builder runs in its
  own process, writing to disk; this channel polls those files. Latency is
  a poll interval, not a frame time.

`TOWER-TO-IOS.md` §6.1 previously declared "any World Builder transport at
all" BLOCKED. That entry conflated two separable things — a World Builder
**transport**, and World Builder as a **live in-process module**. All four
of its blockers (a `bytes`-only synchronous `process()`, a scalar
`ExperimentResult`, a registry of one module, a lifecycle timeout too short
for a build) are properties of the second. None of them bear on a reader
that never joins the frame path. §6.1 is now resolved for the transport;
the live-module half remains blocked and is not what this is.

---

## 2. Discovery — do this first

### On the socket: `{"type": "cartridges"}`

**This is the path for the phone.** iOS owns exactly one WebSocket and has
no HTTP client, no REST layer and no second transport — so discovery
happens on the socket already open. Send `{"type":"cartridges"}`, receive
the declaration below. **Cache it**; it changes only when the Tower build
changes.

Send it only **after** the ping/pong handshake has completed. The Tower
never speaks first, so nothing here can arrive before the pong — but a
client that asked for capabilities before validating would be reading its
own reply into the handshake.

### `GET /cartridges` — the same object, for operators

An HTTP route returning byte-identical output, for curl, dashboards and
anything that is not the phone. Both surfaces call one function and a test
asserts they cannot drift. **The phone does not need it.**

```json
{
  "type": "cartridges",
  "envelope_contract": "cartridge_results.envelope/2026-08-23",
  "cartridges": [
    {
      "cartridge": "world_builder",
      "result_type": "status",
      "contract": "world_builder.status/2026-08-23",
      "available": true,
      "unavailable_reason": null,
      "snapshot_only": true
    }
  ],
  "not_offered": [
    {"cartridge": "experimental_cv", "reason": "..."},
    {"cartridge": "document_memory", "reason": "..."},
    {"cartridge": "scene_understanding", "reason": "..."}
  ]
}
```

Both surfaces call one function; a test asserts they are byte-identical.

### The three states, and how to tell them apart

`IOS-to-Tower.md` §0.1 requires these to stay distinct because they call
for opposite user responses.

| You observe | State | Show |
|---|---|---|
| the cartridge appears in `not_offered`, or in neither list | the Tower says nothing about it | "not built yet" |
| it appears in `cartridges` with a `contract` your build does not implement | contract you do not speak | "update the app" |
| it appears in `cartridges`, contract matches, `available: false` | offered but unreachable | the `unavailable_reason`, and an action to connect/configure |
| it appears in `cartridges`, contract matches, `available: true` | ready | subscribe |

**`not_offered` is for humans.** Do not decode against it, and never read
presence there as an offer. It exists so an operator can tell "the Tower
does not know what `document_memory` is" from "the Tower knows and is not
serving it yet".

### Contract identifiers are opaque

Compare for **equality only**. Do not parse them, do not order them, do not
infer compatibility. They are dated rather than numbered precisely so that
nobody is tempted to compute which is greater. A mismatch means "we are not
talking about the same agreement" — nothing more, nothing less.

This is deliberately different from `schema_version` inside the World
Builder payload, which is an integer describing Tower's own on-disk format.
That one is Tower's business; ignore it unless you are debugging.

---

## 3. Subscribing

All result messages travel on the **existing `/ws` socket**. No new
connection, no new port. `ping`/`pong`, `frame`/`frame_result`,
`stream_start`/`stream_stop` are entirely unaffected and unchanged — a test
asserts `frame_result` is field-for-field identical with and without a
subscription open.

### Request

```json
{
  "type": "result_subscribe",
  "cartridge": "world_builder",
  "result_type": "status",
  "contract": "world_builder.status/2026-08-23",
  "world_id": null,
  "session_id": null,
  "since_revision": null
}
```

| Field | Required | Meaning |
|---|---|---|
| `cartridge` | yes | string, from the declaration |
| `result_type` | yes | string, from the declaration |
| `contract` | no | if present, must equal the offered contract, or the subscribe is refused |
| `world_id` | no | inspection mode: report on this specific world. Omit to follow the live/most-recent one |
| `session_id` | no | a specific session within that world. Omit for the latest |
| `since_revision` | no | the `revision` you last held. Affects only `cursor_status` — see §6 |

Omitting `world_id` selects a world holding a live writer lock if one
exists, otherwise the most recently updated. Supplying it is
`WorldInspectionMode.inspecting(worldID:)`: it pins the target, and a
counter that moved would be a bug.

### Reply

```json
{
  "type": "result_subscribed",
  "envelope_contract": "cartridge_results.envelope/2026-08-23",
  "subscription_id": "sub-1",
  "cartridge": "world_builder",
  "result_type": "status",
  "contract": "world_builder.status/2026-08-23",
  "snapshot_only": true,
  "world_id": null,
  "session_id": null,
  "cursor_status": "absent"
}
```

**Immediately followed by a `cartridge_result` with `seq: 1`.** A
subscription always begins with a complete snapshot, unconditionally,
whatever `since_revision` you sent.

`subscription_id` is unique **per connection** and starts at `sub-1` on
each new socket. Two connections will both see `sub-1`; that is correct and
they are entirely independent.

### Unsubscribing

```json
{"type": "result_unsubscribe", "subscription_id": "sub-1"}
```
→ `{"type": "result_unsubscribed", "subscription_id": "sub-1"}`

Unsubscribing an id that is not open returns `result_error` with reason
`unknown_subscription`. **Disconnecting is sufficient cleanup** — you do not
need to unsubscribe before closing the socket.

---

## 4. The envelope

Every result arrives in this shape. The `payload` is the only
cartridge-specific part.

```json
{
  "type": "cartridge_result",
  "envelope_contract": "cartridge_results.envelope/2026-08-23",
  "subscription_id": "sub-1",
  "cartridge": "world_builder",
  "result_type": "status",
  "contract": "world_builder.status/2026-08-23",
  "seq": 4,
  "revision": "e252f739c1cdedab",
  "revision_changed": true,
  "coalesced": 0,
  "cursor_status": null,
  "snapshot": true,
  "tower_sent_at": 1787463092.958,
  "time_basis": "tower-receipt",
  "payload": { }
}
```

| Field | Type | Meaning |
|---|---|---|
| `seq` | int | **Dense per subscription**, starting at 1, assigned at send time. Ordering guarantee. A gap means corruption, never a drop |
| `revision` | string | **Opaque.** Compare for equality only. Changes if and only if the reported state changed |
| `revision_changed` | bool | Whether `revision` differs from the one you were last sent on this subscription |
| `coalesced` | int | How many snapshots were superseded in your slot since your last delivery. `0` normally. `>0` means you read slowly and skipped intermediate **states** — you did not miss information, because this snapshot is complete |
| `cursor_status` | string or null | Only on the first result of a subscription. Null afterwards |
| `snapshot` | bool | Always `true` today. Present so a future delta mode cannot be mistaken for this one |
| `tower_sent_at` | float | Unix epoch seconds, **Tower's clock** |
| `time_basis` | string | Always `"tower-receipt"` |

### `seq` and `coalesced`, and why they are two fields

A single gappy sequence number would conflate "you missed data" with "you
were sent less data because you did not need it", and only the first
deserves alarm. `seq` stays dense so a gap is unambiguously a bug;
`coalesced` reports slowness separately.

### Every timestamp is Tower-receipt time

There is **no capture timestamp anywhere in this system** — the frame
protocol carries no time field. So `tower_sent_at`, `started_at`,
`ended_at`, `built_at` and `mapping_seconds` are all Tower's clock.

`IOS-to-Tower.md` §0.3 holds `observedAt` and `receivedAt` separately and
will never substitute one for the other. Nothing here is an observation
time in the sensor sense. Render capture time as **unknown**.

---

## 5. Ordering and revision semantics

- **`seq` is monotonic and dense within one subscription.** It is not
  global, not per cartridge, and not comparable across subscriptions or
  connections.
- **`revision` is an opaque change identity**, computed by hashing the
  payload with volatile fields removed. It is *not* a counter and carries
  no ordering. Two different revisions mean the state differs; equal
  revisions mean it does not.
- **`progress.mapping_seconds` is excluded from `revision`.** It advances
  continuously while a session is live, and including it would make every
  poll look like a change — the exact failure `IOS-to-Tower.md` §1.2
  describes.
- Because that field is excluded, it is refreshed by a **heartbeat**: an
  unchanged snapshot is re-sent about every 2 s while you are subscribed,
  carrying `revision_changed: false`. Use that flag to skip redraws.
- `geometry.revision` and `trajectory.revision` are separate opaque
  identities for those sections, so you can tell *what* changed without
  diffing.

**`geometry.revision` includes the build timestamp deliberately.** The
build's own input digest covers only which keyframes went in, so a rebuild
with a different backend or code version can produce different geometry
under an identical digest. Between a revision that occasionally reports a
change when nothing changed, and one that can stay silent while geometry
moves under a viewer, only the first is safe.

---

## 6. Reconnect and cursor semantics

**There is no delta stream, therefore there is no gap, therefore a cursor
cannot lose data.** This is the single most important property of the
design and it is why reconnection is simple:

> To reconnect, open the socket and subscribe again. You will receive a
> complete snapshot with `seq: 1`. You are fully caught up.

`since_revision` is **advisory only**. It never changes what you are sent —
only `cursor_status`, which tells you whether a redraw is needed:

| `cursor_status` | Meaning | Suggested action |
|---|---|---|
| `absent` | you sent no cursor | render the snapshot |
| `matched` | your revision is the current one | nothing changed while you were away; you may skip the redraw |
| `stale` | a real-looking revision that is not current | the world moved; redraw |
| `unrecognised` | not a usable revision (empty, wrong type) | treat your cache as worthless; redraw |

A stale or nonsense cursor is **never an error**. Refusing would deny a
client correct data over a field that cannot affect correctness.

Note that `revision` values do not survive a Tower restart in any
meaningful sense beyond content equality — they are content hashes, so the
same state produces the same revision. That is a feature: a cached
revision remains comparable across restarts.

---

## 7. Errors

All are `{"type": "result_error", "reason": <code>, "message": <prose>, ...}`
plus the fields noted. **None of them close the socket** — the frame path
keeps working through every one.

| `reason` | When | Extra fields |
|---|---|---|
| `malformed_request` | missing or wrong-typed `cartridge`/`result_type`/`world_id`/`session_id`/`subscription_id` | — |
| `unknown_cartridge` | this Tower offers no contract for that cartridge | `offered` (array of names) |
| `unknown_result_type` | the cartridge is offered but not that result type | `cartridge`, `result_type` |
| `contract_mismatch` | you sent a `contract` that is not the one offered | `offered_contract`, `requested_contract` |
| `cartridge_unavailable` | offered, but nothing to serve (e.g. no world root configured) | `contract` |
| `too_many_subscriptions` | more than 8 open on one connection | — |
| `unknown_subscription` | unsubscribing an id that is not open | `subscription_id` |
| `snapshot_failed` | the first snapshot could not be built | `cartridge`, `result_type`, `contract` |
| `consumer_too_slow` | a result was not accepted within the send timeout; **this subscription is now closed** — subscribe again to resume | `subscription_id`, `cartridge`, `result_type` |
| `channel_failed` | the Tower's shared reader died; **this subscription is now closed** | `subscription_id`, `cartridge`, `result_type` |

Every `result_error` also carries `envelope_contract`.

`channel_failed` and `consumer_too_slow` are the two that arrive
unsolicited. On receiving it,
that subscription is gone — re-subscribe to resume. It exists because a
dead channel that still looks alive is worse than a crash: nothing anywhere
reports it.

There is also a **non-result** error you will now see on this socket:

```json
{"type": "protocol_error", "reason": "unknown_message_type",
 "message_type": "...", "message": "..."}
```

Previously an unrecognised message produced only a server-side log line, so
"not implemented" and "lost in flight" were indistinguishable from the
phone. This is additive; the six existing message types never trigger it.

---

## 8. Limits, bounds and backpressure

| Bound | Value | Why |
|---|---|---|
| Subscriptions per connection | **8** | a remote party must not grow a server-side dict at will |
| Pending snapshots per subscription | **1** | there is no queue. A new snapshot replaces the pending one |
| Snapshot size | fixed arity, measured **< 8 KB** | a test asserts the payload contains no unbounded list |
| Send timeout | **2 s** | a consumer that does not accept a result within this has its subscription closed. It is also the longest a `frame_result` can queue behind a result send, because both take the connection's send lock — which is why it is 2 and not 5 |
| Lock wait | **2 s** | bounded separately from the send, so a slow frame send cannot consume a result's budget and cause a spurious drop |
| Poll interval | **0.5 s** | how often the Tower re-reads disk |
| Heartbeat | **2 s** | how often an unchanged snapshot is re-sent |

### Measured cost

All on this host (Windows 11, CPU-only), so treat them as shape rather
than as a spec.

| What | Figure |
|---|---|
| One snapshot, 7-event journal | **0.75 ms** |
| One snapshot, 50,000-event journal | **0.73 ms** — flat, because the journal is summarised once per change and the summary is three scalars |
| The same, without caching | 0.98 ms → **117 ms**, i.e. linear in session length |
| Frame reply, no subscription | median **3.224 ms**, p95 3.873 ms |
| Frame reply, one subscription open | median **3.220 ms**, p95 3.817 ms |
| Cost of the channel to the frame path | **−0.004 ms (−0.1%)** — noise, over 400 frames per condition in 5 alternating reps |

Over a simulated 30-minute session (3,600 polls, journal growing
throughout, one subscriber): traced memory went 5.7 KiB → **34.3 KiB and
plateaued**, and the payload stayed **byte-constant at 3,173 bytes**. Your
memory cost per subscriber does not grow with how long the Tower has been
mapping.

Snapshot computation runs in a worker thread, never on the event loop.

**Client responsibilities**

1. **Read the socket.** One WebSocket is one TCP stream: if you stop
   reading, you block your own `frame_result`s too, and after 5 s your
   subscription is dropped.
2. **Throttle rendering yourself.** `IOS-to-Tower.md` §4.8 is right that
   the receiving side needs its own throttle. Tower coalesces, but you
   should still not put a list diff on the main actor per message.
3. **Unsubscribe when a workspace closes** if the connection outlives it.
4. **Treat `revision` as opaque** and `contract` as opaque.

**Tower responsibilities**

1. Never send a partial payload; every result is complete.
2. Never let a slow consumer accumulate memory: one slot, newest wins.
3. Never let the result channel affect the frame path, capture, or any
   cartridge's state.
4. Stop all polling when the last subscriber goes.
5. Tell you when the channel dies rather than going quiet.

---

## 9. Cross-cartridge extension

The envelope is generic; payloads are not. To add a cartridge:

1. Write `tower/results/<cartridge>.py` producing a `Snapshot`. It is the
   **only** file allowed to import that cartridge — enforced by
   `test_the_result_channel_core_is_cartridge_blind`.
2. Wire it in `tower/results/__init__.py: make_snapshot_for`.
3. Add a `CartridgeOffer` in `tower/results/registry.py` and move the entry
   out of `NOT_OFFERED`.
4. Mint a new contract identifier. Do not reuse another cartridge's.

Nothing in the envelope, publisher, registry or routes changes. The
subscription, ordering, coalescing, reconnect and error machinery is
already generic and already tested.

**Why the other three are not offered yet**

| Cartridge | Reason |
|---|---|
| Experimental CV Lab | its per-frame results already reach the client on `frame_result`. A typed contract wants the experiment registry, provenance and baseline work in `IOS-to-Tower.md` §2.1–2.3, which is a design decision, not a transport one |
| Document Memory | implemented and queryable by CLI, but no contract is offered. Also gated by the resolution finding in `TOWER-TO-IOS.md` §6.8 |
| Scene Understanding | implemented as a **live in-process state that persists nothing**. There is no file for this channel to read, and giving it one would pre-empt Environmental Memory's whole reason to exist. It needs the live-module path, not this one |

---

## 10. World Builder `status` payload

Contract: `world_builder.status/2026-08-23`.

### 10.0 If you implement nothing else, implement this

The payload has two halves. **`model_state` and `world_snapshot` are the
half you decode.** Everything else is Tower-native evidence for those
values — useful when something looks wrong, not required to render.

They are shaped to drop straight into the iOS types that already exist:
`world_snapshot` maps 1:1 onto `WorldSnapshot`, and `model_state` names a
`WorldModelState` case. Tower does that mapping deliberately — the
alternative would put the translation table on the phone, where changing
it is an App Store release rather than a Tower restart.

```json
"model_state": "finalized",
"model_state_reason": null,
"world_snapshot": {
  "name": "Probe Room",
  "world_id": "be5076514e0d4727ab06f2ad1df5a5bf",
  "keyframe_count": 4,
  "revision": "b00bfe85819804da",
  "tracking": "good",
  "scale": "relative",
  "mapping_seconds": 0.0789,
  "calibration": "calibrated",
  "geometry": {
    "representation": "sparse point cloud",
    "element_count": 1360,
    "is_incremental": false
  },
  "trajectory": {
    "pose_count": 4,
    "path_length": 2.853251890377782,
    "path_length_unit": "world units",
    "scale": "relative"
  },
  "persistence": {"state": "saved", "revision": "67ccaee79f212c8d"}
}
```

**`model_state`** — one of `unsupported`, `idle`, `receiving`,
`finalizing`, `finalized`, `failed`. `model_state_reason` is prose for a
person, or null.

| Tower sends | Meaning | Note |
|---|---|---|
| `unsupported` | this Tower cannot serve World Builder at all | e.g. no world root configured. Do not invite the user to wait |
| `idle` | Tower is fine, there is nothing to show yet | no worlds, or a world with no sessions |
| `receiving` | a mapping session is live | a process holds the world's writer lock |
| `finalizing` | capture ended; the stored figures are **not** the final figures | see the caveat under `lifecycle` below — Tower cannot see whether a build is *running* |
| `finalized` | capture ended and the stored geometry matches the keyframes | |
| `failed` | the builder died, or the session recorded an error | `model_state_reason` says which |

**`awaiting_first_update` is never sent**, deliberately. It means "frames
are going out and the Tower has said nothing yet" — a fact about the
phone's own situation, which only the phone can know, and which it reaches
by not having received a snapshot.

**`world_snapshot` field notes**

- `revision` is the **same opaque string** the envelope carries. Compare
  for equality; never parse or order it.
- `tracking` — `good` / `lost` / `unavailable`. **`limited` is never
  sent**: it would need a threshold nobody has defined.
- `calibration` — `unknown` / `uncalibrated` / `calibrated`.
  **`calibrating` is never sent**: there is no in-session calibration
  procedure to be in the middle of.
- `scale` — `relative` or `unknown` in V1. **`inferredMetric` and
  `measuredMetric` are unreachable** on monocular hardware and will not
  arrive. Never render any figure from this channel in metres.
- `mapping_seconds` — the **Tower's** clock. Null if the Tower's wall
  clock stepped backwards.
- `geometry.is_incremental` is always `false` and never null: a build
  replaces the whole derived tree, so every snapshot is a whole world.
- `trajectory.scale` is carried **separately** from the snapshot's scale,
  because a spatial figure travels with its own. When `path_length` is
  null so is `path_length_unit`.
- `persistence.state` is `saved` whenever a world exists — World Builder
  persists by construction, so `session` is unreachable.
- Any field may be `null`, and null means **absent**, never zero.

**Nothing else in the payload is required.** Read on only if you want the
evidence behind these values.

### 10.1 Field reference

**`world`** — or `null` when nothing could be resolved.

| Field | Type | Notes |
|---|---|---|
| `world_id` | string | opaque, stable across sessions |
| `display_name` | string or **null** | operator-supplied. **Null means unnamed.** Do not derive a name |
| `schema_version` | int | Tower's on-disk format. Not the contract |
| `created_at`, `updated_at` | float | Tower clock |

**`session`** — or `null` when the world has no sessions.

| Field | Type | Notes |
|---|---|---|
| `session_id` | string | opaque |
| `started_at` | float | Tower clock |
| `ended_at` | float or null | null while live |
| `end_reason` | string or null | `"stop"`, `"disconnect"`, `"bounded_limit"` |
| `frame_source` | string | `"synthetic"`, `"recorded-capture"`, `"live-capture"`, `"unknown"` |
| `capture_id` | string or null | links to a capture directory, if any |
| `retains_raw_imagery` | bool | always `true` for World Builder, and stated on the record |

**`lifecycle`**

| `state` | Means | Evidence |
|---|---|---|
| `receiving` | a mapping session is live | a live pid holds the writer lock |
| `stopped_unbuilt` | capture ended; stored geometry is not current with the keyframes | no manifest, or a stale one |
| `ready` | capture ended; stored geometry matches the keyframes | manifest current |
| `failed` | the builder died, or the session recorded an error | a lock held by a dead pid |
| `idle` | a world with no live session and no stop event | — |
| `unavailable` | nothing could be read | see `reason` |

`evidence` is prose naming what was observed. `reason` is prose for a
person, or null.

> **There is deliberately no `finalizing`.** A build *does* rewrite several
> files before its manifest lands, so the directory changes while it runs —
> but those writes are indistinguishable from a build that made them and
> then **died**. The writer lock is already released by then and no event
> is written, so nothing on disk says "a process is working right now". The
> Tower cannot observe that work is continuing, and a state named
> `finalizing` would assert exactly that.
>
> `lifecycle.build_in_progress` is **`null`** in every stopped state — not
> `false`, which would be a claim that no build is running.
> `build_in_progress_unavailable_reason` carries the explanation. It is
> `false` only while `receiving`, where the lock proves no build has begun.
>
> If you want to render `.finalizing`, `stopped_unbuilt` is the state to
> map it from — but do so knowing Tower is telling you "the stored figures
> are not the final figures", not "a process is working right now".

**`progress`** — or `null` with no session.

| Field | Type | Notes |
|---|---|---|
| `keyframes_accepted` | int | **the count the Tower actually keeps.** While live it is counted from the event journal, not from the session record, which still holds the zero written at session start |
| `keyframes_accepted_provenance` | `"measured"` | counted, not inferred |
| `keyframes_accepted_source` | string | `"event journal"` or `"session record"`. The journal is used until the session is stopped AND its record finalised — including when it `failed`, because a crashed session's record still holds the zeros written at start |
| `frames_observed` | int or **null** | **null while live.** An ordinary rejected frame writes no journal event, so this is genuinely not knowable until the session stops. `null ≠ 0` |
| `frames_observed_unavailable_reason` | string or null | why, when null |
| `rejected_by_reason` | object or null | histogram, available only after stop |
| `journal_corrupt_lines` | int | Unparseable lines in the event journal. **1 at the tail is routine** — a journal is appended without fsync, so a reader can arrive mid-write. More than that, or a count that does not clear, means corruption, and the keyframe count beside it is correspondingly low |
| `mapping_seconds` | float or **null** | **on the Tower's clock.** Do not derive this from a phone timer. **Null** if the Tower's wall clock moved backwards during the session — reported as unknown rather than clamped to `0.0`, because a plausible zero is worse than an absent value |
| `mapping_seconds_unavailable_reason` | string or null | why, when null |
| `mapping_clock` | `"tower"` | |

**`tracking`**

| `state` | Means |
|---|---|
| `good` | the most recent tracking event was a keyframe acceptance |
| `lost` | the most recent tracking event was a tracking loss |
| `unknown` | no keyframe accepted and no loss recorded |

**`limited` is never sent**, and `limited_ever_reported` is permanently
`false`. The nearest candidate threshold in Tower is documented in its own
source as an untuned placeholder and is not emitted as an event at all.
Emitting `limited` from it would present an unmeasured placeholder as a
calibrated judgment.

**`calibration`** — scope is **`"session"`**, always.

| `state` | Condition |
|---|---|
| `calibrated` | intrinsics present, finite, and physically possible |
| `uncalibrated` | no intrinsics were supplied |
| `unknown` | a source is declared but the numbers do not survive validation |

**`calibrating` is never sent** (`calibrating_ever_reported: false`).
Calibration is an offline procedure run before a session; there is no
in-session state to be in the middle of. There is deliberately **no
percentage** — a denominator nobody has defined.

Calibration is per **session**, not per world: intrinsics are
resolution-keyed, and two sessions of one world can legitimately differ. A
world-level calibration state would be a fabrication.

**`scale`**

| Field | Notes |
|---|---|
| `state` | Tower's vocabulary: `unknown` or `relative` in V1 |
| `unavailable_reason` | Set when this **session** has no build of its own. Scale lives on the world record and is earned by a build, so a session that was never built reports `unknown` rather than inheriting a scale another session earned |
| `semantics` | iOS's vocabulary: `"relative"`, or **`null`** when state is `unknown` |
| `unit` | `"world units"`, or **null** when there is no unit at all |
| `meters_per_unit` | always `null` in V1 |
| `allows_metres` | always `false` in V1 |

**`inferredMetric` and `measuredMetric` are unreachable in V1** and will
never arrive. `estimated` and `measured` have no code path that produces
them. **Never render any figure from this channel as metres.**

`state: "unknown"` means the reconstruction has **no unit at all** — a
strictly weaker claim than "internally consistent with an arbitrary unit".
Do not map it to `.relative`. When it is `unknown`, no distance figure is
sent at all.

**`geometry`**

| Field | Notes |
|---|---|
| `available` | true once **any** build has produced output for this session — including one that is now behind |
| `current` | whether that output reflects **every** keyframe accepted so far. **`false` is normal during a session that rebuilds as it goes** |
| `built_from_keyframes` / `keyframes_now` | how many keyframes the build consumed, and how many exist now. When they differ, the figures are correct for the first number |
| `stale_reason` | prose, when `current` is false; null otherwise |
| `representation` | **`"sparse point cloud"`** — Tower's own word. Display verbatim; never parse or match it |
| `element_count` | number of points, or **null**. Never `0` for "we did not build" |
| `element_name` | `"point"` |
| `is_incremental` | **`false`.** A build replaces the whole derived tree; it never emits a delta |
| `revision` | opaque; see §5 |
| `provenance` | `"inferred"` |
| `confidence` | **`null`.** Tower keeps per-keyframe and per-edge confidence but has never defined an aggregate for a whole reconstruction. A number here would be one nobody specified |
| `backend_id`, `built_at` | diagnostic |
| `unavailable_reason` | prose, when unavailable |

A manifest missing any of `input_digest`, `session_id`, `keyframes`,
`points`, `poses_solved`, `poses_refused` or `segments` is treated as
**absent**, not as geometry with null figures. "We have geometry" is not
asserted without the figures to show for it.

**`trajectory`** — a summary. **No pose array is sent**, per
`IOS-to-Tower.md` §1.4.

| Field | Notes |
|---|---|
| `current`, `built_from_keyframes`, `keyframes_now`, `stale_reason` | as for geometry |
| `pose_count` | poses carrying a position = keyframes minus refused. **Not** `poses_solved`: an anchor has a position and is counted as neither solved nor refused |
| `poses_solved`, `poses_refused`, `keyframes`, `segments` | the underlying figures |
| `path_length` | see below |
| `provenance` | `"inferred"` |

**`path_length`** is either

```json
{"available": true, "value": 2.853, "unit": "world units",
 "scale_semantics": "relative", "display": "2.853 world units",
 "provenance": "inferred"}
```

or `{"available": false, "reason": "..."}`. It is **refused** when:

- **any pose was refused** — a refused pose is a hole in the path, not a
  shorter path. Summing across it draws a straight line between the
  keyframes either side and calls that distance walked;
- **the session has more than one segment** — a segment break means
  tracking was lost, and poses either side share no coordinate frame. A
  total would sum incomparable distances;
- **the scale state is `unknown`** — the figure could not be labelled, so
  it is not renderable;
- the derived poses are unreadable.

Always render `display`, or `value` **with** `unit`. Never bare.

**`persistence`**

`state` is always `"saved"` — World Builder persists everything by
construction. `revision` is an opaque world identity. `location_disclosed`
is `false`: **no filesystem path is ever sent.** A Tower path is useless to
a phone and names a machine's layout to a remote consumer.

**`artifacts`**

`present` is **tri-state**: `true`, `false`, or **`null`** for "not
established" (the images directory could not be read). It is never `false`
merely because `images_purged_declared` is true — that flag makes rebuilds
refuse and deletes nothing, so it cannot support a claim that the imagery
is absent.

```json
{"keyframe_images": {"present": true, "count": 4, "redaction": "none",
                     "fetchable": false, "reason": "..."},
 "images_purged_declared": false,
 "images_purged_verified": null,
 "images_purged_meaning": "..."}
```

**No imagery is offered, and none will be under this contract.** Since
2026-08-23 keyframes are **face-redacted before they are written**, and
`redaction` reports what the session recorded — e.g.
`faces-detected-and-filled/yunet-2023mar@0.30`, naming the detector and
its threshold. That is a **process** claim ("this detector's hits were
filled"), never an outcome claim: the detector has measured false
negatives on heavily occluded and ~90°-rotated faces. Sessions captured
before that date keep `none` forever.

They stay unfetchable regardless. A best-effort filter is not grounds to
start shipping first-person imagery. `IOS-to-Tower.md` §5 requires an image whose treatment is not
`redacted` to be **withheld**, with no lenient default. So the channel
declares that the images exist and that they are not fetchable, and mints
**no id and no URL** — inventing a fetch scheme would be exactly the
fabricated contract that document refuses.

`images_purged_declared` is a **flag, reported as a flag**. It makes
rebuilds refuse; it does **not** delete anything, and a world carrying it
was verified to still have every JPEG on disk. `images_purged_verified` is
`null` because Tower cannot verify it. Never render this as "the imagery is
gone".

### 10.2 Real examples

These are actual payloads, captured from the implementation.

**Live session, `receiving`:**

```json
{
  "world": {"world_id": "eb9fe5739a2941ef95336696fc352e76",
            "display_name": "Live Room", "schema_version": 1,
            "created_at": 1787463092.883, "updated_at": 1787463092.890},
  "session": {"session_id": "45e21a3a6f6042adaced831b22eee530",
              "started_at": 1787463092.889, "ended_at": null,
              "end_reason": null, "frame_source": "synthetic",
              "capture_id": null, "retains_raw_imagery": true},
  "lifecycle": {"state": "receiving",
                "evidence": "a live process (pid 21280) holds the writer lock",
                "reason": null, "build_in_progress": false,
                "build_in_progress_unavailable_reason": null},
  "progress": {"keyframes_accepted": 3,
               "keyframes_accepted_provenance": "measured",
               "frames_observed": null,
               "frames_observed_unavailable_reason": "no event is written for an ordinary rejected frame, so this count is only known once the session stops",
               "rejected_by_reason": null,
               "mapping_seconds": 0.069, "mapping_clock": "tower",
               "time_basis": "tower-receipt"},
  "tracking": {"state": "good",
               "evidence": "the most recent tracking event was keyframe_accepted",
               "limited_ever_reported": false},
  "calibration": {"state": "calibrated", "source": "self_calibrated",
                  "calibrated_width": 480, "calibrated_height": 360,
                  "reprojection_rms_px": null, "view_count": null,
                  "calibrating_ever_reported": false, "scope": "session"},
  "scale": {"state": "unknown", "semantics": null, "meters_per_unit": null,
            "method": null, "confidence": "unknown", "unit": null,
            "allows_metres": false},
  "geometry": {"available": false, "current": false,
               "built_from_keyframes": null, "keyframes_now": null,
               "stale_reason": null, "representation": null,
               "element_count": null, "element_name": null,
               "is_incremental": false, "revision": null, "provenance": null,
               "confidence": null, "backend_id": null, "built_at": null,
               "time_basis": "tower-receipt",
               "unavailable_reason": "no build has run for this session, so no geometry exists"},
  "trajectory": {"available": false, "current": false,
                 "built_from_keyframes": null, "keyframes_now": null,
                 "stale_reason": null, "pose_count": null, "poses_solved": null,
                 "poses_refused": null, "keyframes": null, "segments": null,
                 "path_length": null, "revision": null, "provenance": null,
                 "confidence": null,
                 "unavailable_reason": "no build has run for this session, so no poses exist"},
  "persistence": {"state": "saved", "revision": "c1e7c6a8857045d0",
                  "images_purged": false, "location_disclosed": false},
  "artifacts": {"keyframe_images": {"present": true, "count": 3,
                                    "redaction": "none", "fetchable": false,
                                    "reason": "these are unredacted first-person frames and no artifact transfer contract exists; a consumer must withhold imagery whose treatment is not stated"},
                "images_purged_declared": false,
                "images_purged_verified": null,
                "images_purged_meaning": "a declaration that rebuilds are refused for this world, not a verified deletion of the imagery"},
  "time_basis": "tower-receipt"
}
```

Note what a live session does **not** know: `frames_observed` is null, and
`scale` is `unknown` because no build has run.

**After stop, before build — `stopped_unbuilt`:** identical except

```json
"session": {"ended_at": 1787463092.958, "end_reason": "stop", "...": "..."},
"lifecycle": {"state": "stopped_unbuilt",
              "evidence": "capture ended and no build output exists for this session",
              "reason": "no geometry has been built for this session yet",
              "build_in_progress": null,
              "build_in_progress_unavailable_reason": "the writer lock is released before build() is called, and build() emits no event and writes nothing until it finishes, so a build in progress is indistinguishable on disk from one that never started and from one that crashed"},
"progress": {"frames_observed": 8,
             "frames_observed_unavailable_reason": null,
             "rejected_by_reason": {"insufficient_motion": 5}, "...": "..."}
```

`frames_observed` and the rejection histogram appear here and only here.

**After build — `ready`:**

```json
"lifecycle": {"state": "ready",
              "evidence": "capture ended and the stored geometry matches the keyframes",
              "reason": null, "build_in_progress": null,
              "build_in_progress_unavailable_reason": "..."},
"scale": {"state": "relative", "semantics": "relative",
          "meters_per_unit": null, "method": null, "confidence": "unknown",
          "unit": "world units", "allows_metres": false},
"geometry": {"available": true, "current": true,
             "built_from_keyframes": 4, "keyframes_now": 4,
             "representation": "sparse point cloud",
             "element_count": 1360, "element_name": "point",
             "is_incremental": false, "revision": "ecb09a6f0c3f3cdf",
             "provenance": "inferred", "confidence": null,
             "backend_id": "classical-sfm", "built_at": 1787464196.020,
             "time_basis": "tower-receipt", "unavailable_reason": null,
             "stale_reason": null},
"trajectory": {"available": true, "current": true,
               "built_from_keyframes": 4, "keyframes_now": 4,
               "stale_reason": null,
               "pose_count": 4, "poses_solved": 3,
               "poses_refused": 0, "keyframes": 4, "segments": 1,
               "path_length": {"available": true, "value": 2.853251890377782,
                               "unit": "world units",
                               "scale_semantics": "relative",
                               "display": "2.853 world units",
                               "provenance": "inferred"},
               "revision": "e0787672c4faee47", "provenance": "inferred",
               "confidence": null, "unavailable_reason": null}
```

`pose_count: 4` with `poses_solved: 3` is not an inconsistency — the fourth
is the anchor, which has a position and is counted as neither solved nor
refused.

### 10.3 What becomes available only after Stop, and after build

| Available | Live | After stop | After build |
|---|:--:|:--:|:--:|
| world id, session id, display name | ✅ | ✅ | ✅ |
| lifecycle, tracking, calibration | ✅ | ✅ | ✅ |
| `keyframes_accepted`, `mapping_seconds` | ✅ | ✅ | ✅ |
| `frames_observed`, `rejected_by_reason` | ❌ null | ✅ | ✅ |
| `scale.state` beyond `unknown` | ❌ | ❌ | ✅ |
| geometry: representation, element count | ⚠️ | ❌ | ✅ |
| trajectory: pose count | ⚠️ | ❌ | ✅ |
| trajectory: path length | ❌ | ❌ | ✅ |

⚠️ = available **only** with `world_build_session.py --rebuild-every N`,
and then always with `current: false` — see below.

### "Watch it build", concretely

With `--rebuild-every N`, geometry appears *during* the walk and grows.
A real run, 28 synthetic frames, `--rebuild-every 2`, sampled through this
channel:

| lifecycle | `keyframes_now` | `element_count` | `current` | `built_from_keyframes` |
|---|---|---|---|---|
| `unavailable` | — | — | — | — |
| `receiving` | 2 | null | false | null |
| `receiving` | 6 | **1360** | false | 4 |
| `receiving` | 10 | **2336** | false | 8 |
| `ready` | 10 | **2712** | true | 10 |

Point count grows monotonically and lands on the final figure. **Every
mid-walk row carries `current: false`**, because the next keyframe lands
before the viewer sees the build — that is not a defect, it is the normal
and permanent condition of a world being built, and the two keyframe
counts say exactly how far behind the figures are.

`path_length` stays unavailable throughout a live session even with
`--rebuild-every`: it reads the actual poses, and the store refuses a
derived tree that no longer matches its inputs. The counts come from the
build's own manifest and are correct for that build; the path length would
have to trust pose files that may be mid-rewrite, so it honestly refuses.

**Without `--rebuild-every`, geometry does not exist until after Stop**,
and `Start → Walk → Stop → the world appears` is the honest description.

---

## 11. Known limitations

1. **Polling latency.** Up to one poll interval (0.5 s) plus the builder's
   own write. Not a frame-rate signal.
2. **No `finalizing`** — see §10.1. Not observable.
3. **No error reason for a crashed session.** `end_reason: "error"` exists
   in Tower's vocabulary but no code path writes it. A crashed builder is
   detected via the stale lock instead.
4. **`frames_observed` has no live source.** Fixing it would mean World
   Builder emitting a per-frame event, which would turn a bounded journal
   into a per-frame one.
5. **No imagery, and no artifact fetch contract.** §10.1.
6. **Nothing has been validated on physical footage.** Every figure in this
   document came from synthetic renders.
7. **`build_completed` is unreachable** in Tower's event vocabulary and is
   not exposed. Do not wait for it.

---

## 12. Where the code is

| Concern | File |
|---|---|
| Contract identifiers | `tower/results/contracts.py` |
| Envelope, revision hashing | `tower/results/envelope.py` |
| Capability declaration | `tower/results/registry.py` |
| Fan-out, coalescing, bounds | `tower/results/publisher.py` |
| World Builder producer | `tower/results/world_builder.py` |
| WebSocket protocol | `tower/routes/results_ws.py` |
| `GET /cartridges` | `tower/routes/cartridges.py` |
| Wiring | `tower/main.py`, `tower/config.py` (`TOWER_WORLD_ROOT`) |

Tests: `tests/test_result_channel_{protocol,bounds,truthfulness,isolation}.py`
and `tests/result_channel_fixtures.py`.
