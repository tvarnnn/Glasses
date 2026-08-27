# Mac / iOS handoff — the unified cartridges, 2026-08-27

**Branch:** `ios/unified-cartridges-v1`
**Start commit (pre-Tower iOS HEAD):** `1b6913c`
**Tower merge point:** `715bf18`
**End commit:** `0f00b1e`
**Tower consumed:** `e2ca9b2` on `integration/tower-unified-cartridges-v1`
**Tree:** clean. **Push:** see §12.

Four Tower lanes were unified on 2026-08-27 and the Tower went from
declaring **one** contract to declaring **four**, with `not_offered` empty.
This is the iOS half. Three of the five cartridges had no networking at all
before this run — a stub client, a constant `.unsupported`, and a method
that always threw — so most of this is new construction rather than
adaptation.

---

## 0. The five-minute version

| | |
|---|---|
| Contracts implemented | **11 of 11** the Tower states (was 3) |
| Tests | **662 passed, 0 failures** (was 441) |
| Debug build | ✅ |
| Release build | ✅ — **and still not a readiness signal, see §9.1** |
| Contract drift vs a live Tower | **AGREEMENT** |
| Tower's own smoke, run on this Mac | **56/56** |
| Physically validated | **nothing** — see §10 |

**The one thing to read if you read nothing else:** §9.1. A Release build
still contains no camera. I did not fix it, I tried, and §9.1 says exactly
why and what it costs.

---

## 1. What made this run different: a real Tower on the Mac

I built a venv in a scratch directory and ran the unified Tower locally on
this Mac at `127.0.0.1:8765`, with `TOWER_WORLD_ROOT`,
`TOWER_DOCUMENT_ROOT`, `TOWER_DOCUMENT_CAPTURE` and
`TOWER_SCENE_UNDERSTANDING` all set. Its own end-to-end smoke reports **all
56 checks passed** on this machine.

That changed the character of the work. Every decoder in this branch was
written against bytes curled off a running Tower rather than against a
document, both reviewers probed the live wire, and the Document/Scene lane
ran **118 assertions against live bytes** through a `swiftc` harness before
any of it reached XCTest.

It also caught things a document read never would — §11 lists four contract
findings for the Tower lane, every one verified against the running build.

**The `ml` extra is not installed** (it is CUDA/Windows-pinned). So this
Tower has no `torch` and no `easyocr`: Scene Understanding cannot reach
`running` here and the Document recorder fails on start. Both are Tower-host
tasks, not iOS ones, and both gate a morning test — see §10.

---

## 2. Contracts integrated

All eleven the Tower states. Verified by `ios/scripts/contract-drift-check.py`
against the live Tower: **AGREEMENT**.

| Identifier | Surface | Where iOS implements it |
|---|---|---|
| `world_builder.status/2026-08-25` | socket | `TowerWorldBuilderClient` |
| `world_builder.geometry/2026-08-25` | HTTP | `WorldGeometry.swift` |
| `experimental_cv.status/2026-08-27` | socket + HTTP | `ExperimentalCVContract` |
| `experimental_cv.control/2026-08-27` | socket | `ExperimentalCVContract` |
| `experimental_cv.frame_result/2026-08-27` | frame path | `ExperimentalCVContract` |
| `scene_understanding.live/2026-08-27` | socket | `SceneUnderstandingContract` |
| `document_memory.status/2026-08-27` | socket | `DocumentMemoryContract` |
| `document_memory.library/2026-08-27` | HTTP | `DocumentMemoryContract` |
| `object_memory.observations/2026-08-26` | HTTP | `ObjectMemoryModel` |
| `object_memory.imagery/2026-08-27` | HTTP | `ObjectMemoryImagery` |
| `cartridge_session.control/2026-08-27` | HTTP | `ObjectMemorySession` |

`cartridge_results.envelope/2026-08-23` is decoded but deliberately not
pinned to a constant.

### 2.1 Object Memory is still undeclared on the socket, and that was left alone

The Tower's §8 records this as **a decision for a human** and asks that an
integrator not close it by noticing the asymmetry. **It was not closed.**
Object Memory is reached entirely over HTTP and learns nothing from the
declaration, exactly as the contract instructs.

What *did* change is that the iOS half of the blocker is gone. The pinned
test that would have broken has been widened, and a new test —
`testObjectMemoryIsReachedWithoutADeclaration` — now asserts the absence
**as the intended design**, so it fails loudly if someone declares it
without the ruling. The Tower side remains about four lines whenever you
decide.

---

## 3. What each cartridge gained

**World Builder.** `transform_to_world` is decoded as a Sim3 into a new
`WorldTransform`. A **non-unit quaternion is refused, not normalised** —
normalising folds the error into `scale`, where nothing can see it.
Tolerance 1e-3, matched to the Tower's 5-decimal serialisation (1e-6
rejects the Tower's own valid output). `transform_to_world: null` is never
identity, differing `reference_segment`s are never composited, and the
`pose_convention` key-by-key refusal is intact.

The geometry cache is now keyed on `(content_hash, placement_hash)` at
every call site — including two in `WorldFragmentsView` that were beyond
the brief; fixing only the store would have left the view reading the old
key. `placement_hash` decodes as **optional** deliberately: the Tower added
it without moving the identifier and the existing verbatim fixtures predate
it (§11 F4).

**Object Memory.** Gained the whole `cartridge_session.control` surface
(Start/Pause/Resume/Stop), the three imagery routes, and real
frame/thumbnail display. **A 410 no longer renders as a connection
failure** — it fetches `/imagery` before requesting any bytes, so *"the
memory is kept, the picture is gone"* becomes a rendered sentence, and the
race where `/imagery` says available and `/frame` then 410s is handled.
Liveness comes from `following` and nothing else.

**Experimental CV Lab.** Went from a stub to the full socket control
vocabulary, the eight refusal reasons with terminal/retryable told apart,
`frame_error` decoded (it was landing in `default:` and being discarded),
and run-scoped provenance. **Deleted rather than left dormant:** the
better/worse verdict renderer, because `baseline`, `higher_is_better` and
`confidence` are null on every metric, always. Results are ordered by
`result_seq`, not the wire `seq`, which is the phone's capture index and
skips by design.

**Document Memory.** Six HTTP routes, the closed `matched` / `not_found` /
`no_observation` vocabulary, the typed session, and
`recording_limitations` **rendered** — it appeared zero times before. An
empty library renders as *"An empty memory is what this platform produces
today"*, never "no documents yet". Stop **keeps**.

**Scene Understanding.** Typed live scene with every key non-optional,
because the contract guarantees presence and modelling them as optional
loses "zero of these" versus "this Tower did not say". Stop **discards**,
enforced by construction: `.lastKnown` is gated on a predicate true for
`paused` alone, so a payload arriving `stopped` *with* a scene still lands
in `.idle` with no observation. `count_is_lower_bound` is rendered where a
person sees it.

**Removed, and worth stating plainly:** `SceneEntity`, `SceneTrackID`,
`SceneRelationship`, `ScenePosition`, `SceneSnapshot`. They modelled
per-entity rows with track handles. The contract says no key on the wire
could carry one, and a stable track id plus a timestamp is exactly the
joinable pair this cartridge refuses to hand anyone. Modelling the shape is
the first half of laundering persists-nothing onto the consumer.

---

## 4. Three shipped strings that had become false

Deleted, not softened. Each was true when written:

- **Scene:** *"The Tower does not analyse scenes yet… nothing about anyone
  the glasses pass ever reaches this app."* Every clause false.
- **Document:** *"The Tower keeps no document memory, so there is nothing
  to search."* A claim about what the Tower stores — the exact category an
  existing test exists to forbid. It slipped through because the blocklist
  had `"keeps nothing"` and not `"keeps no"`.
- **CV Lab:** *"…no way to list the experiments, request one, or read a
  result with provenance attached."* All three exist.

---

## 5. UI and state changes

Badges: Document Memory and Scene Understanding moved `.awaitingTower` →
`.readyToTest`. **`.awaitingTower` now has no members**, which is the honest
state; the case is kept because it is the right answer the next time a lane
finishes an engine before its contract.

`http_contracts` is decoded (it was silently dropped), availability
resolves through it for fetch-only cartridges, and the contract's **third
state** — *"present, contract this build cannot read"* → **"update the
app"** — is now expressible and pinned. iOS previously collapsed it into
"not built", which is the opposite instruction to a person.

---

## 6. Reviewer findings

Three reviewers. **All ten of the contract's §12 display obligations hold.**

### 6.1 Correctness / lifecycle — three defects invisible from any screen

**The CV Lab's run gate could not see a run it did not start.** The gate was
fed only by `cv_lab_status`, and the Tower sends that **only in reply to a
command on the same connection**. The Lab has one slot shared by every
connection, last start wins — so a run started by anyone else arrived only
on the subscription, which fed nothing. Every following `frame_result` was
then discarded as stale: the counter the product screen reads froze while
frames were being answered normally, and the card kept showing the
**previous experiment's figures under the new experiment's name, with a
live badge over it**. Precisely the outcome the gate exists to prevent,
produced by the gate. Reproduced against the running Tower. Fixed, with a
regression test **confirmed to fail without the fix**.

**`isSubscribing` leaked `true` on any refused subscribe**, and the retry
guards on it — so Scene, Document and CV Lab never retried for the life of
the connection. Reachable on a *transient*: the Tower sends
`snapshot_failed` **instead of** an ack when the first snapshot raises.
World Builder had a watchdog; the three clients that copied its shape did
not inherit it. Fixed in all three.

**A URL-keyed cache sat in front of the placement-keyed one.**
`WorldGeometryClient` was the only HTTP client not opting out of
`URLSession.shared`'s cache — on the one route whose URL does **not** change
when a segment gains a placement, which is the exact case the tuple key
exists for. The Tower sends no validators, so freshness fell to a
heuristic, and the test harness disabled the layer production left on.
Fixed, along with two force-unwraps on wire-derived URLs.

### 6.2 Privacy / truthfulness

Six sentences had outlived the facts they described. The sharpest:
**Document Memory's screen said "Recording what is read"** while this app's
own decoder **refuses a Tower** whose `claim` says a document was read. The
build declined the claim on the wire and then made it in its own voice.

Also fixed: the drawer told a person that opening a cartridge *"does not
start anything on the Tower"* on a build that now sends three kinds of
start — the sentence someone reads before deciding whether opening a screen
can begin recording; Home asserted *"The Tower did not say whether this was
measured or estimated"* while holding the provenance it had decoded; World
Builder drew a **spinner** asserting the Tower was working, from a field the
Tower explicitly says it cannot observe; the CV Lab claimed frames were
arriving from a cumulative counter that never falls; and it described a
1-in-30 sender stride that had been deleted.

The reviewer's structural note is worth keeping: the cartridge directories
are disciplined, and the copy **outside** them has no owner.

### 6.3 A crash class

`min(max(v, 0), 1)` does **not** clamp NaN — every comparison with NaN is
false — so the "clamped" percentage formatter trapped, on a path including
Object Memory's **required** `subject_obscured`. Same for ±∞ and anything
past `Int.max`. Guarded, along with Scene's side-count sums on the push
path.

### 6.4 Final whole-app review — two SEV-1s, one of them mine

Verdict: **shippable, with the two SEV-1s landing before anyone puts glasses
on.** Both landed (`6f74c53`). Neither was a crash or data loss; both put a
false statement on a screen.

**The F2 fix above was half-done, and it re-opened F1.** Scene, Document and
the CV Lab inherited World Builder's flag clear and **not its resume**.
Nothing retries a subscription mid-connection, so after `channel_failed` or
`consumer_too_slow` the cartridge went permanently silent on a socket that
was still up and still feeding World Builder perfectly. `consumer_too_slow`
is routine — it fires when the phone does not accept a result inside the
send timeout, which is a backgrounded or thermally-throttled phone on a
walk.

The two fixes then interacted: because the run gate is now fed *only* by the
subscription for runs this phone did not start, a dead subscription freezes
the watched run id and every later `frame_result` is discarded — F1 in full,
through the door F2 left open — while the CV Lab kept a **`live` badge over
frozen figures**, both halves of its LIVE gate stuck at their last values.
Neither earlier reviewer could have seen this, because they looked at F1 and
F2 separately.

**A cold launch told four workspaces the Tower had never heard of them.**
`resolve` tested `declared == nil` before reachability, and those four learn
`declared` only from the socket declaration — so `.towerUnreachable` was
unreachable on a first run, and the shipped string says, wrongly and in so
many words, *"That is a statement about what the Tower offers, not about
this connection."* This was the first thing anyone would see with the Tower
not yet up.

**Two regressions I had introduced in `0f00b1e`,** both caught here: the
`"stopped"` headline claimed *"Stop was requested"* on a session that died
from a missing Python module — which is exactly what the bench Tower reports
— and the `days()` sentinel read *"in the last an unreported window"*.

Also fixed: Document's library ignored the `available` flag it had decoded,
so an unconfigured Tower offered a search box that 404s while the Tower's
own sentence naming the variable went unshown; and the drift check was blind
to a **second** nested identifier (§8).

Three fixes were narrowed after the tests pushed back, and the narrowing is
the point in each case:

- Making every undeclared cartridge report `.towerUnreachable` was **too
  broad**. For Visual Q&A, which has no Tower code anywhere, that is its own
  false story — reconnecting cannot help. Gated on the Tower-name mapping:
  can this build ever *receive* a declaration?
- Routing a stopped-with-failure Scene session to `.failed` **weakened the
  stop-discards invariant to fix a copy problem**, and the Tower keeps
  `failure_reason` across a stop, so a session that failed, recovered and
  stopped normally would report a failure it had recovered from. Corrected
  in the *sentence*; the state stays `.idle` and the scene is still
  discarded.
- That sentence fix then had to be narrowed to `stopped` alone, because an
  `unrecognised` state must still reach the screen as the Tower's own words.

**Its remaining findings are open and recorded here rather than fixed:**

| # | Sev | Finding |
|---|---|---|
| R6 | 2 | `0f00b1e` fixed four defect classes and shipped one test. F2, F3 and every F7 guard have **no coverage**; `TowerSceneUnderstandingClient` and `TowerDocumentMemoryClient` are named nowhere in the test target. The F3 revert is *masked* by the harness, which sets `urlCache = nil` at the session level. |
| R8 | 3 | One `channel_failed` produces four different presentations across four cartridges. |
| R10 | 3 | `CartridgePhase.mayCarryData` has **zero production call sites** despite its doc calling it "the load-bearing half of this type" — the invariant holds because tests say so, not because any screen is prevented from violating it. `ExperimentalCVContract.frameResult` is the one contract identifier declared and never compared, and it governs the block feeding the F1 gate. `unsubscribeFromResults` is fully dead. ~60 decoded-and-never-rendered fields in `DocumentMemoryLibrary.swift` alone. |
| R11 | 3 | Home asserts *"The Tower returns a measurement for each frame"*; a Lab that is idle/paused answers `frame_error` instead, and that has one reader app-wide. |
| R12 | 4 | Four tests pass for the wrong reason (tautology, hardcoded `.absent`, `?? 0` making an assertion unfalsifiable, one whose assertion inverts its stated intent). |
| R13 | 4 | Post-`sendStreamStart` heartbeat blanks the reading card once (<100 ms) and leaves a ≤2 s ungated window. Needs hardware to observe. |
| R14 | 4 | Tower-side: `failure_reason` and `loading_seconds` survive a stop (26,362 s observed on a stopped session). |

**R6 is the one to act on first.** The gap it names is real: this run fixed
more than it tested.

---

## 7. Tests and builds

| Gate | Result |
|---|---|
| Full XCTest, iPhone 17 Pro sim, Debug | **662 passed, 0 failures** |
| Debug build | ✅ |
| Release build | ✅ |
| `build-for-testing` | ✅ |
| Contract drift vs live Tower | **AGREEMENT**, exit 0 |
| Tower unified smoke on this Mac | **56/56** |
| Signed device build | ❌ **not run** — needs a device |

Counts by area: ProductShell 153, Object Memory 141, TowerClient 80,
WorldGeometry 78, SenderPipeline 51, WorldBuilder 50, Document 47, Scene 33,
CV Lab 29.

**Two tests were on disk and had never executed.** `DocumentMemoryTests` and
`SceneUnderstandingTests` were not registered in the project — `GlassesTests`
is a plain group, not a file-system-synchronized one — so they compiled
nothing and still reported success. Registering them is most of the jump
from 441 to 662. **Converting that target to a synchronized group would
remove this whole class of silent loss and is recommended.**

`-only-testing:GlassesTests/<FileName>` names a *file*, not a class: it runs
**zero tests and prints `TEST SUCCEEDED`**. Use the bare target.

### 7.1 Two known flakes

1. `TowerClientTests.testSendWindowIsClearedByReconnectSoSendingResumes` —
   pre-existing, timing-bound, documented in the previous run.
2. `CameraReadinessTests.testReadinessIsNotReReadOnceItIsKnown` — **new
   observation, not a new defect.** Failed once in a full run; passed 5/5
   in isolation and on two consecutive full runs afterwards. Unrelated to
   this work. Recorded rather than buried; if it fails on a quiet machine
   that is a real signal.

---

## 8. Verification that a gate can fail

Two things in this run were checked by breaking them on purpose, because a
gate only ever observed passing is not a gate:

- **The placement cache regression test** was written *before* the fix,
  confirmed red without it, and paired with a negative control that stays
  green under the reverted keying — so the pair discriminates the fix
  rather than rewarding "always refetch".
- **The contract drift check** was found blind to the entire new
  `http_contracts` block: it would have reported AGREEMENT while
  `document_memory.library` drifted. Fixed, then verified by changing the
  iOS identifier and confirming **DRIFT, exit 1**, then restoring.

---

## 9. Known limitations

### 9.1 A Release build still has no camera — I tried to fix this and stopped

`GlassesConnection.swift` and `ProjectManager.swift` put the camera path
inside `#if DEBUG` with no `#else`. **A Release binary contains no camera
session and sends no frames.** "Release builds, 0 errors" is true and means
less than it looks: it compiles cleanly partly *because* it excludes half
the app.

I started the split and backed it out. The function-level separation is
clean — of the eleven functions in that block exactly three touch
MockDeviceKit, and the real camera path references it once, in an error
string. **But the state is gated too:** `deviceSessionState`,
`cameraStreamState`, `latestCapturedFrame`, `captureResolution`, the
`CapturedFrame` type, and the `CoreMedia` / `MWDATCamera` / `UIKit`
imports. Ungating the path means ungating all of it across **11 files and
42 `#if DEBUG` blocks**, every one a UI surface reading camera state
conditionally.

That is a real refactor whose only meaningful verification is a signed
build on a phone with real glasses — which is exactly the physical testing
this run was told to queue rather than perform. Landing it compile-verified
and calling the Release gate meaningful would have been a stronger claim
than I could back. **The inventory above is the useful artifact; do it as
its own piece of work with a device in hand.**

The Tower's contract §6.5 scopes this out explicitly: *"That predates this
work and is not fixed by it."*

### 9.2 Other limits

- **Nothing is physically validated.** Not one line of this branch has seen
  real glasses.
- **This Tower has no `torch` or `easyocr`**, so Scene cannot reach
  `running` and the Document recorder fails on start, on this host. The
  `running`/`paused` Scene fixtures are assembled from the Tower's own
  payload builders and are **labelled as such** — they are not live bytes.
- **The Object Memory store is empty** here, so a real 200 picture, a real
  410 and a real 503 were never exercised end to end. Those fixtures come
  from the Tower's own constants; the 404 and the envelope are verbatim.
- **The Document library is empty**, which is the contract's own expected
  result. Empty rendering is tested; populated is not.
- **`WorldTransform.apply` and `pointsInReferenceFrame` have no production
  callers.** The Sim3 is decoded and refused correctly, but nothing
  composites yet — so §5.2's "sits in the wrong place, permanently" cannot
  currently happen, and the visible symptom of a cache miss is a blank
  tile.
- **`distanceDisplayable` has zero call sites.** The enforced gate is
  `labelledFigureDisplayable`, which is contract-correct today — but if a
  Tower ever named a unit `"m"`, nothing would consult the obligation-1
  flag.
- **The `.awaitingTower` badge case now has no members.**

---

## 10. Morning physical test order

Ordered by what can be **falsified**, not by convenience. **1 and 2 first.**

### PT-1 — World Builder lateral-translation walk *(worth more than the rest combined)*

One walk, 2–4 minutes, in a room already walked so content is comparable.

- Move **sideways** past furniture. Strafing creates baseline; turning your
  head creates none.
- Keep roughly constant distance from what you are looking at.
- Re-enter the same area **twice, ≥60 s apart**, for a genuine revisit.
- Avoid: standing still and panning; walking straight at a wall (the epipole
  sits in the image and parallax collapses); fast head turns.
- **Rule of thumb: the camera should travel at least its own distance to
  what it is looking at.** Table 2 m away → move 2 m.

Measure (read-only): `world_registration.py --root <data>/world_builder
--world <id> --format json`. Keep `segments_registered`,
`points_registered`, `candidate_pairs`, `admitted_pairs`, and the full
refusal histogram.

**PASS:** `segments_registered` rises well above the current 3 of 51; the
`span_over_depth` share falls from 96% of refusals; median span/depth clears
**0.05**.
**FALSIFIED:** span/depth stays in 0.02–0.06 despite a deliberate strafing
walk — a far more serious finding, and it would justify reopening whether
monocular-only can ever register on this hardware.

**PT-4 rides on the same footage and is the real product bar:** render the
registered geometry and, without being told which is which, identify **at
least three distinct pieces of furniture or architecture from the point
cloud alone**. "Points appeared" is not the bar.

### 2. Document Memory — the real-paper test

**Blocked until `easyocr` is installed on the Tower host.**

1. `TOWER_DOCUMENT_ROOT=…`, `TOWER_DOCUMENT_CAPTURE=true`.
2. `POST /documents-session/start`; wait for `running` (~5 s).
3. **Hold a printed page square-on at reading distance for 10 s**, well lit,
   filling most of the view.
4. `GET /documents-session` — did `pages_detected` move? `in_dwell` true?
   **Expect zero.** 5,204 real corpus frames detected 0 pages. **If your
   printed page moves either counter, that is the first positive this
   cartridge has ever seen and is worth writing down.**
5. `GET /documents` — is `text_availability.state` `extracted` or
   `not_readable`?
6. Repeat tilted, at arm's length, in poor light.
7. **Record the false-positive case:** point at a venetian blind and a
   backlit keyboard. Both used to fire and must not now.

### 3. CV Lab — baseline + edge-density smoke

Debug build (Release sends no frames — §9.1). Start `baseline`, confirm a
`frame_result` with a `cv_lab` block and `provenance`. Then
`cv_lab_start edge_detection` and confirm the **run id changes and the
previous experiment's figures leave the screen**. Confirm LIVE appears only
when this build is streaming *and* `source.receiving_frames` is true.
**Then the F1 case:** start a different experiment from a second client and
confirm this phone adopts it — that was the critical defect.

### 4. Scene Understanding — real object / real person

**Blocked until `torch` is installed. Set `TOWER_SCENE_TORCH_THREADS=2`**
(measured 1.03 cores against 4.12 at identical throughput; it is
process-global and also affects the CV Lab).

> Nobody has ever worn these glasses in a room with another person and
> checked what the Tower said. Every `person` in the corpus is the wearer's
> own torso.

One other person, good light, **~2 m**. Record `people.count` against the
truth; expect an undercount and expect the wearer's torso to inflate it.
Repeat at 4 m and at the edge of view. Walk, and watch `frames_skipped`.
Then `POST /scene/stop` and **confirm `scene_available` goes false
immediately on both the route and the subscription.**

### 5. Object Memory — image / model / resolution

Show a laptop and a phone (the two default `recorded_classes`). Then the
screen shown **cold to a person**: if the word "where" comes back, the
caption has failed. Confirm a 410 renders as *"the memory is kept, the
picture is gone"* and not as an error.

**The 720×1280 still** is one measurement upstream of a lot of model work.
It stays a **still**, not a stream: 720p is measured as actively harmful to
World Builder tracking (73.3% of frames fall below `min_sharpness`).

### 6–8. Coexistence soak (World Builder + Scene, ten minutes), PT-2 / PT-3.

---

## 11. For the Tower lane — four findings, all verified on the running build

**F1. §9.1 documents a `limit` parameter that does not exist.** The route
declares only `object_class` and `retention_days` (checked via
`/openapi.json`). `?limit=1` is **silently ignored**. `/documents` and
`/documents/search` genuinely have it, so this is specific to Object Memory.
Implement it or strike it from §9.1.

**F2. §4.1's refusal table disagrees with the wire.** `resume` from
`stopped` is documented as 409 `not-active`; the wire answers 409
`not-paused`. iOS keys its copy on action + reached state rather than the
reason word, so it is correct against either — but the table is not what
shipped.

**F3. Every refusal body is wrapped in FastAPI's `detail`, and no contract
says so.** 409 / 404 / 410 / 503 all arrive as `{"detail": {…}}` rather than
the flat object the field tables imply. One sentence in §10 would fix it.

**F4. `world_builder.geometry/2026-08-25` gained fields without moving.**
`placement_hash`, `registration_state` and `registration_refusal_reason` are
emitted unconditionally and the identifier did not change. Additive, so
decode does not break — but **the identifier is the only signal a client
gets**, and a client caching on `content_hash` alone is now wrong with no
way to learn it. The Tower's own comment says the content hash stays valid
*"which is safe only because placement_hash exists to change instead"* —
and that safety is a property of the **client**, which the wire currently
cannot ask for. Either bump the identifier or state in the contract that
`placement_hash` is required from this date. iOS decodes it as optional for
exactly this reason.

---

## 12. Tree and push status

Working tree **clean**. Four commits on `ios/unified-cartridges-v1` since
the Tower merge:

```
0f00b1e  fix(ios): three defects the reviewers found that no screen would show
9682b70  fix(ios): the drift check could not see the surface it was guarding
98e5c08  feat(ios): two badges stop waiting for a Tower that already answered
a58f32d  feat(ios): four cartridges stop refusing, and the wire is decoded
715bf18  (Tower merge — integration/tower-unified-cartridges-v1 @ e2ca9b2)
```

`tower/` was **not modified**. The one Tower-adjacent change worth naming is
that a scratch venv and a scratch Tower data root live outside the repo, in
the session scratchpad; nothing was written into `tower/`.

**Push status:** recorded at the end of the run — see the final report. The
branch is local unless that says otherwise.

---

## 13. Recommended next steps

1. **Run PT-1 and the real-paper test.** They are the two that can falsify
   something.
2. **Install `torch` and `easyocr` on the Tower host**, with
   `TOWER_SCENE_TORCH_THREADS=2`. Two of the five morning tests are blocked
   without them.
3. **Rule on Object Memory's socket declaration** (§2.1). The iOS half is
   done; the Tower side is four lines.
4. **Take the camera path out of `#if DEBUG` as its own piece of work**,
   with a device (§9.1) — or stop citing the Release gate as readiness.
   Today it is both.
5. **Convert `GlassesTests` to a file-system-synchronized group**, so a test
   file can never again exist on disk and silently run nothing.
6. **Give the copy outside the cartridge directories an owner.**
   `ObjectMemoryCopy` solved this by making copy a testable type; the
   drawer, Home, the shell and the catalog summaries have no equivalent, and
   every stale claim this run found was in one of those.
7. **Send the Tower lane §11.**
