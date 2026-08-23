# Tower → iOS Cartridge Result Channel — 2026-08-23

**Branch:** `integration/cartridge-result-channel-v1`, off
`cartridge/experimental-cv-lab-v1 @ a383c0d`. Not merged.

**Suite:** 849 passed / 30 skipped before → **929 passed / 30 skipped** after.
78 of the new tests are the channel's own; 6 consecutive runs, 0 failures.

The standing blocker was recorded as *"no structured result channel, so no
cartridge's real output can reach iOS."* This closes it for persisted
state, with World Builder as the first producer.

---

## 1. The gap, proven rather than assumed

Driven over the real wire before anything was written:

- `/health` and `/ws` are the only surfaces. `/health` carries **zero**
  world or cartridge keys.
- Every plausible request for cartridge state — `world_state`,
  `subscribe`, `get_world`, `capabilities`, `cartridges` — was met with
  **silence**. Not an error. A `ping` sent afterwards returned `pong`
  first, proving nothing was queued.
- `frame_result` carries scalars plus two `name -> number` bags. No
  structure, and no way to carry a refusal.

That silence was itself a defect, and one iOS names explicitly: *"iOS
never lets a request silently no-op"*. An unrecognised message now returns
`protocol_error`.

---

## 2. The insight that unblocked it

`TOWER-TO-IOS.md` §6.1 declared "any World Builder transport at all"
BLOCKED behind four V1.0/V1.1 blockers. Re-read against the iOS
requirements, §6.1 had **conflated two separable things**:

| | |
|---|---|
| a World Builder **transport** | achievable now |
| World Builder as a **live in-process module** | still blocked |

All four blockers — a `bytes`-only synchronous `process()`, a scalar
`ExperimentResult`, a registry of one module, a lifecycle timeout too
short for a build — are properties of the *second*. None of them bear on
a **reader** that never joins the frame path: one that polls what
`world_build_session.py` has already persisted and reports it.

That is what was built. It calls no engine method, starts no build,
touches no frame, and never writes.

---

## 3. Three measured findings that changed the design

### 3.1 A reader breaks the writer — and the reader is not the one that fails

Windows refuses `Path.replace()` onto a destination any handle has open.
The web process reading world state therefore breaks
`world_build_session.py`'s atomic writes. **The status channel would crash
the mapping session it exists to report on.**

| Reader | Writer failures, 400 atomic writes |
|---|---|
| none | 0 / 400 |
| ordinary, unthrottled | **223 / 400 (55.8%)** |
| ordinary, stat-gated | 62 / 400 (15.5%) |
| **with the shipped retry** | **0 / 400** |

`FILE_SHARE_DELETE` was tried first and **measured not to work** —
`MOVEFILE_REPLACE_EXISTING` fails against a share-delete handle too. That
code was deleted rather than shipped on a plausible-sounding claim.

The fix is a bounded retry in `tower/storage.py::_replace_with_retry`.
Retrying a rename is safe in a way retrying most IO is not: the operation
is atomic, so it either happened or it did not — no partial state, no
possibility of writing twice.

`tower/world_builder/store.py`'s docstring could previously say *"V1 also
has no concurrent reader"*. This channel is that reader; the assumption is
void, and the retry is what makes it safe.

### 3.2 The journal read had to be gated, then summarised

`read_events()` reads and JSON-parses the **whole** journal on every call
— the `after_event_id` cursor filters *after* the read, so it buys
nothing. Against a measured frame reply of ~2 ms, that is not affordable.

Per snapshot:

| Journal events | No cache | Stat-gated | Summary cached |
|---|---|---|---|
| 7 | 0.98 ms | 0.69 ms | 0.75 ms |
| 1,000 | 2.69 ms | 0.82 ms | 0.76 ms |
| 10,000 | 19.84 ms | 1.75 ms | 0.81 ms |
| 50,000 | 117.35 ms | 9.26 ms | **0.73 ms** |

Stat-gating on `(size, mtime_ns)` stopped the re-*parsing*. It did not
stop the re-*scanning* — every block that consumed the journal walked it
— so cost stayed linear in session length until the journal was reduced
to a three-scalar summary at read time. That also fixed a memory problem
nobody had noticed: caching the parsed list would have held every event
dict for as long as anyone was subscribed.

Poll cost is now **flat in session length**.

### 3.3 `session.json` holds stale zeros for the whole session

Written at `start_session()` with `frames_observed: 0` and
`keyframes_accepted: 0`, and **not rewritten until `stop_session()`**.

A producer reading the obvious field would report **0 keyframes** while
keyframes were being accepted — and zero looks like a measurement, not
like a gap. The live count comes from the event journal instead.

`frames_observed` has **no live source at all**: an ordinary rejected
frame writes no event. It is reported `null` with its reason, and appears
with the full rejection histogram once the session stops. That is
`nil ≠ 0` producing a real null on the wire.

---

## 4. What "watch it build" actually looks like

The headline product claim, exercised end to end rather than reasoned
about — and it failed the first time.

With `--rebuild-every N`, a build finishes and the very next keyframe
makes its output stale. The first implementation reported anything not
matching the current keyframes as simply unavailable, so a walk that was
genuinely producing geometry every few keyframes reported **none at all**
until it stopped. The channel was hiding the exact thing
`--rebuild-every` exists to show, and no test caught it because every
test built a world and *then* looked at it.

A build over the first N keyframes is a correct answer to an older
question, not a wrong answer. After the fix, sampled through the channel
(28 frames, `--rebuild-every 2`):

| lifecycle | `keyframes_now` | `element_count` | `current` | `built_from` |
|---|---|---|---|---|
| `unavailable` | — | — | — | — |
| `receiving` | 2 | null | false | null |
| `receiving` | 6 | **1360** | false | 4 |
| `receiving` | 10 | **2336** | false | 8 |
| `ready` | 10 | **2712** | true | 10 |

Monotonic, landing on the final figure. Every mid-walk row carries
`current: false` with both keyframe counts, so a viewer shows real
progress while knowing exactly how far behind it is. Hiding it discarded
true information; reporting it without the flags would have let a viewer
mistake it for the finished world.

---

## 5. The design, and what was rejected

| Decision | Why |
|---|---|
| **Snapshots, never deltas** | The state is recomputed from files that are themselves the durable record. Nothing is lost by discarding an older snapshot |
| **One slot per subscription, not a queue** | A bounded queue of N is worse than either extreme here: it drops the *newest* update once full, which is backwards for a freshness-first channel, and costs N× the memory to deliver a stale backlog |
| **New messages on the existing `/ws`** | iOS already holds it open, and a second socket would add connection management on both sides for nothing |
| **One shared reader, per app** | Ten subscribers watching one world cost one disk read per interval, not ten. It stops entirely when the last subscriber leaves |
| **Opaque contract identifiers, compared for equality** | iOS's explicit requirement, and correct: a phone in the App Store cannot know anything about an identifier minted after it shipped. Deliberately unlike `SCHEMA_VERSION`, which governs whether *this build* can read a file *this project* wrote |
| **A dense `seq` plus a separate `coalesced`** | One gappy sequence would conflate "you missed data" with "you were sent less data because you did not need it". Only the first deserves alarm |
| **HTTP discovery as well as a socket message** | iOS's third state is "offered but unreachable → connect". A client that can only learn the contract set by connecting cannot distinguish that from "not built yet" |

**Rejected:**

| Rejected | Why |
|---|---|
| `FILE_SHARE_DELETE` on the reader | Measured not to work. Deleted rather than shipped |
| A cursor over the raw event journal | Would couple iOS to World Builder's internal event vocabulary, and four of its nine event kinds are never emitted |
| Sending poses, points or keyframes | iOS marked a pose array NOT REQUESTED; a pose schema needs five conventions that each render plausibly and wrongly if guessed |
| Offering keyframe imagery | It is unredacted raw first-person frames. An unstated treatment means withhold, with no lenient default |
| A `finalizing` lifecycle state | Not observable. While a build runs the files are byte-identical to "never built" and to "build crashed" |
| A `limited` tracking state | Would require inventing a threshold from a value the code itself documents as untuned |
| Reporting `calibrating` | No code path can produce it |
| A per-connection poller | Would multiply the disk read by the number of connections |

---

## 6. What the channel costs the frame path

Interleaved A/B, 400 frames per condition over 5 alternating reps:

| | median | p95 |
|---|---|---|
| No subscription | 3.224 ms | 3.873 ms |
| One subscription open | 3.220 ms | 3.817 ms |
| **Delta** | **−0.004 ms (−0.1%)** | — |

The frame path now takes a per-connection send lock, which became a
correctness requirement once a second sender existed: Starlette applies no
send-side serialisation, and an interleaved close from a push task makes
the *frame* path raise `RuntimeError`. Uncontended, it costs nothing
measurable — and a connection with no subscription never contends, because
no second sender exists.

Also asserted by test: `frame_result` is field-for-field identical with
and without a subscription; a capture records the same frames either way;
and the module container's state does not move.

---

## 7. Privacy posture

- **No imagery crosses the wire.** World Builder keyframes carry
  `redaction: "none"`. They are declared present and **not fetchable**,
  with no id and no URL minted — inventing a fetch scheme would be the
  fabricated contract this work refuses.
- **No filesystem path** is ever sent (asserted by test). A Tower path is
  useless to a phone and names a machine's layout to a remote consumer.
- **`images_purged` is reported as a declaration, not a deletion.** The
  flag makes rebuilds refuse; it deletes nothing, and a world carrying it
  was verified to still have every JPEG on disk.
- The gaze/identity vocabulary ban now covers the channel too.

---

## 8. Known limitations

1. **Nothing validated on physical footage.** Every figure is synthetic.
2. **Polling latency**, up to one poll interval plus the builder's write.
3. **No `finalizing`** — not observable; see §5.
4. **No error reason for a crashed session.** `end_reason: "error"` exists
   in Tower's vocabulary but no code path writes it. A dead builder is
   detected via its stale lock instead.
5. **`path_length` refuses during a live session**, because it reads pose
   files the store declares stale. The counts still grow.
6. **Only World Builder publishes.** Scene Understanding cannot use this
   channel at all — it persists nothing, deliberately.
