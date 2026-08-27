# Mac / iOS integration — final report

**Lane:** Mac/iOS · **Branch:** `ios/world-builder-integration`
**Date:** 2026-08-26
**Supersedes nothing.** It sits alongside `MAC-INTEGRATION-STATUS.md` (still the
best narrative of the wave before this one) and reports what this run changed.

---

# Executive Summary

**The task as briefed was to consume the completed Mega Prompt branch and wire
its cartridges into the iOS product. The first finding is that the premise did
not hold, and the evidence is unambiguous.**

1. **There was nothing to consume.**
   `origin/integration/world-builder-lifecycle-v1` @ `25eb794` is already an
   ancestor of this branch's HEAD. `git merge-base --is-ancestor` returns true
   and `git rev-list --count origin/integration/world-builder-lifecycle-v1 ^HEAD`
   returns **0**. The Mega branch was fully merged by commit `9e1b216` before
   this run began. No sync, no rebase, no merge was needed or performed.

2. **There is no broad backend awaiting a UI.** Of the nine cartridges in the
   programme documents, a live Tower probed during this run offers **exactly
   one** typed contract. Four of the nine have **zero code in `tower/tower/`** —
   Visual Q&A, Accessibility, Environmental Memory and Translator exist only as
   design documents, and two of the Translator plans are stamped
   *DO NOT IMPLEMENT*. Three more are implemented on the Tower but are listed
   by the Tower itself under `not_offered`, with reasons that are **Tower-side
   decisions, not iOS gaps**.

   Building UI for those cartridges would mean rendering data no backend
   produces. This project's Rule 3 (*Truthful State Only*) forbids it, and the
   iOS stub clients that refuse rather than fabricate are therefore **correct,
   not unfinished**.

3. **What was genuinely left undone was smaller, and it has been done.** Four
   changes, each independently reviewed, plus a handoff closing three debts this
   lane owed the Tower lane and had never sent.

**The most valuable output of this run is arguably not code.** It is the
verified finding that the Tower already receives, on every single frame, the
resolution information its own contract document asks iOS to provide — and that
the "adaptive ladder" its design defends against does not exist on this
hardware path. See *Backend Follow-Ups*.

---

# Exact Git State

| | |
|---|---|
| **Mac branch** | `ios/world-builder-integration` |
| **HEAD at start of run** | `2dce88d` |
| **Mega integration HEAD consumed** | `25eb794` (`origin/integration/world-builder-lifecycle-v1`) — **already an ancestor of HEAD before this run**; 0 commits outstanding |
| **World Builder specialist HEAD** | `c4d9ad6` (`origin/world-builder/next-generation`) — **inspected, deliberately NOT consumed**; see below |
| **Working tree** | clean at start; clean at end |
| **Force pushes** | none |
| **Merges to `main`** | none |

### On `world-builder/next-generation`

`MAC-INTEGRATION-STATUS.md` records that this branch *"does not exist on
`origin`"*. **That is now stale** — it exists, with 22 commits, and its tip
commit is a Mac-facing handoff.

It was read in full. Its handoff
(`docs/agent-handoffs/WORLD-BUILDER-NEXT-GENERATION-MAC.md`) declares
**"NO IOS CHANGE REQUIRED"**, and that declaration was independently verified
rather than trusted:

- It warns that a new event kind `solve_chain_broken` joins a closed set and
  that *"if anything on your side switches exhaustively on event kind, it needs
  to tolerate this one."* **Verified: iOS consumes no event kinds at all.** A
  repo-wide grep for `tracking_lost`, `solve_chain_broken`, `event_kind` and
  `eventKind` across `ios/` returns nothing. The risk does not exist here.
- It states `GEOMETRY_CONTRACT` is unchanged at `world_builder.geometry/2026-08-25`.
  **Verified:** `git diff 25eb794 origin/world-builder/next-generation -- docs/contracts/`
  is empty.

So the branch is handoff-ready and correctly requires nothing. It was not
merged, because merging Tower-side work into the iOS lane is not this lane's
job and nothing here depends on it.

---

# Cartridge Integration Matrix

Status vocabulary is kept deliberately separate: **IMPLEMENTED** ≠ **TESTED** ≠
**DEVICE-VALIDATED** ≠ **PHYSICALLY VALIDATED**.

| Cartridge | Tower implementation | Contract / version | iOS code | UI | Lifecycle | Tests | Fixtures | Offered on live Tower | Physical validation | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| **World Builder** | complete (`tower/tower/world_builder/`, 13 modules) | `world_builder.status/2026-08-25` + `world_builder.geometry/2026-08-25` | 9 files, ~3.2k lines | canvas, fragments grid, DEBUG capture | full — subscribe/resubscribe, 10 s ack bound, 3-resubscribe budget, HTTP geometry | heavy (88 methods) | yes, real-Tower bytes | **yes** — the only offer | **DONE** (P3 walk) | **DEVICE-VALIDATED** |
| **Object Memory** | complete (`tower/tower/object_memory/`) | `object_memory.observations/2026-08-26` | 4 files, ~2.1k lines | picker + query buttons + records | pull-only by design; 10 s timeout, single-flight | heavy (58 methods) | yes, real-Tower bytes | **HTTP only — absent from `/cartridges` entirely** | pending real data | **TESTED**; live Tower returns 404 (no root configured), rendered truthfully |
| **Experimental CV Lab** | complete and **the only live Tower module** (8 experiments) | none offered | 3 files, 746 lines | workspace + result surface | none — cannot list/choose/start | model-level | no decode fixtures | `not_offered`; results arrive on `frame_result` | pending | **IMPLEMENTED** — output now surfaced in its own workspace |
| **Document Memory** | complete engine + CLI (`tower/tower/document_memory/`) | none offered | 3 files, 781 lines | search field (inert) | none | 37 cases, model-level | no | `not_offered` — CLI only | **BLOCKED on resolution** | **BACKEND FOLLOW-UP REQUIRED** |
| **Scene Understanding** | complete engine, **persists nothing by design** (`tower/tower/scene/`) | none offered | 3 files, 846 lines | display-only, zero controls | none | model-level | no | `not_offered` — no route exists, test-enforced | n/a | **BACKEND FOLLOW-UP REQUIRED** |
| **Visual Q&A** | **none** | — | catalog row only | informational row | — | catalog pin | — | no Tower code at all | n/a | **NOT INTEGRATED**, correctly |
| **Accessibility** | **none** | — | catalog row only | informational row | — | catalog pin | — | no Tower code at all | n/a | **NOT INTEGRATED**, correctly |
| **Environmental Memory** | **none** — its own design says *do not begin* | — | catalog row only | informational row | — | catalog pin | — | no Tower code at all | n/a | **NOT INTEGRATED**, correctly |
| **Translator** | **none** — two plans, both stamped *DO NOT IMPLEMENT* | — | **absent entirely** | none | — | none | — | no Tower code at all | n/a | **NOT INTEGRATED**, correctly |

**Four different counts, all correct for what they describe:** nine cartridges
in the programme docs, eight rows in the iOS catalog, four ids in Tower's
`contracts.py`, one contract offered on the wire.

### Live wire truth, probed this run

```
GET /health      module_state: "active"   module_id: "experimental-cv"
GET /cartridges
  cartridges:  world_builder / status / world_builder.status/2026-08-25
               available=true, snapshot_only=true
  not_offered: experimental_cv, document_memory, scene_understanding
GET /object-memory/observations   404 {"detail":"no object memory root is configured"}
```

Only six HTTP routes exist. `ios/scripts/contract-drift-check.py` was run
against this Tower and reports **AGREEMENT — every contract the Tower stated is
implemented by this build.**

---

# UI Work Completed

Four surfaces changed. None invents a screen the product does not need, and
none renders anything the Tower did not send.

### 1. World Builder fragments grid — ranked
The grid had no ordering; manifest order is capture order, which says when a
segment was walked through and nothing about whether anything was recovered
from it. Cards are now ordered by `point_count` descending, tie-broken on
`segmentIndex`.

Requested by name in the World Builder lane's own handoff, and it gates
something for them: they are holding back a segmentation variant measured at
**poses 346 → 863, points 47k → 107k**, released only because it produces ~470
segments *"which is unusable in an unranked grid."*

Membership and order are deliberately two separate expressions: the
resolved-with-bounds filter is unchanged and `unresolvedCount` is asserted
unchanged, because the Tower's handoff says that if that number moves,
something is wrong.

### 2. Experimental CV Lab — its own output, in its own workspace
The Tower's only live module is the CV Lab. Its answer arrives on **every
frame** in `frame_result` and was rendered **only on Home** — so a user opening
"Experimental CV Lab" saw "Nothing yet" while the Lab's actual live answer sat
on the previous screen. That is now fixed.

The design point that matters: the reading is modelled as `CVFrameReading`, a
projection of one `TowerFrameResult` held **beside** `ExperimentalCVState`,
never inside it. The frame channel is not the cartridge result channel, and
collapsing them would have weakened `CartridgePhase.mayCarryData` — the
invariant that only `.live`/`.settled` may carry data. That invariant is
byte-identical and its test untouched. The cartridge still resolves to
`.unsupported`, `run(_:)` still refuses, and nothing was added to
`TowerCapabilities`.

`result_value` is now **unreachable without `result_label`**: the pair rule
lives in a private factory on the type that returns `nil` unless both are
present, so both screens go through it and neither can render a bare number
whose unit belongs to an experiment. The copy states plainly what cannot be
done — the Tower chose the experiment at its own startup, and this app cannot
list, choose, start or stop one — and adds that `result_label` names *the
number*, not the experiment, so the screen never claims to know which of the
eight is running.

### 3. Developer Tools — capture resolution
`StreamingResolution.low` was a hardcoded literal, which is why Document
Memory's premise has never been testable: its word recall is **0.429–0.810 at
360×640 against 0.957–1.000 at 720p**, and raising the rung required an edit and
a rebuild. A DEBUG-only picker now selects the rung for the next session.

It is a **developer control, not a product setting**, and deliberately so: 720p
is *actively harmful* to World Builder tracking — `min_sharpness = 25.0` is
absolute and **73.3%** of 720p frames are rejected as blurred. Those two facts
do not reconcile at one rung and the choice is not iOS's to make alone.

The default stays `.low` and the preference is deliberately **not persisted**,
so a raised rung cannot silently survive a relaunch into a walk nobody meant to
record at 720p.

### 4. Developer Tools — the Tower's real capture state
`GET /health` has reported the Tower's dataset-recorder state since
2026-08-22, and the Tower's own contract says iOS *"can now display the real
state truthfully"* — arming it from iOS is BLOCKED, showing it is not.
**Nothing in `ios/` read `/health` at all.** So "is the Tower writing my frames
to disk right now?" was unanswerable from the app, which matters because when
the recorder is armed those frames are persisted **unredacted**.

A Developer Tools panel now fetches it on an explicit button — no polling, no
timer. It renders `armed`, `recording`, `frames_written`, `bytes_written`, the
capture id, and the worker state, with **four distinguishable states**: not
checked, checking, fetched, and could-not-be-read (which further distinguishes
"the Tower did not answer" from "the Tower answered and the answer could not be
read").

**The design point, and it is a correction to the brief this lane wrote.** The
brief assumed the Tower might omit the `capture` key. It does not:
`tower/tower/routes/health.py:22` always emits it and sends **`null`** when no
recorder is registered, and its own docstring says `null` *"means no recorder is
registered at all, which is different from a registered recorder that is idle."*
So the implementer used a four-case `TowerReported<Value>` —
`unreported` / `absent` / `present` / `unreadable` — because **"the Tower did
not say" and "the Tower says there is no recorder" are different facts**, and
only the second means the frames are definitely not being kept. Both are
decoded, both are rendered differently, and both are tested. That is a better
answer than was asked for.

No arm/disarm control exists anywhere on the panel, because iOS cannot arm the
recorder and a control implying otherwise would be a fabricated capability.

### 6. The drawer badges now say what you can use, not what is planned
**Raised by the user, and it was a truthfulness defect rather than a cosmetic
one.** Every badge read as a roadmap position — "Up next" / "Planned" /
"Future" — on a product surface where a person reads it as *"can I use this?"*

The badge set was actively **inverted**: **Visual Q&A read "Planned"** — the
readier-sounding word — **with zero Tower code anywhere, while World Builder
read "Future"** despite being the one contract on the wire and the only
cartridge with a device-validated walk behind it.

`CartridgeStatus`'s own doc explained why there was deliberately no
`.available` case: *"no module runtime exists on either side yet: the Tower's
module container is V0.8 and the first module is V0.9."* **That premise is
refuted by the wire** — `module_state: "active"`, `module_id:
"experimental-cv"`, and `world_builder.status/2026-08-25` offered with
`available: true`. This was the **third** instance of the same stale belief
found in this run, after `CartridgeAvailability` and `CartridgePhase`.

New vocabulary, each value justified by evidence recorded beside it:

| Status | Badge | Cartridges | Evidence |
|---|---|---|---|
| `.readyToTest` | **Ready to test** | World Builder, Object Memory, Experimental CV Lab | offered on the wire / two live HTTP routes with a real-Tower-pinned decoder / the Tower's only running module |
| `.awaitingTower` | **Awaiting Tower** | Document Memory, Scene Understanding | full Tower pipeline exists, listed `not_offered` — one Tower decision away |
| `.notBuilt` | **Not built** | Visual Q&A, Accessibility, Environmental Memory | zero Tower code |

`.awaitingTower` is kept distinct from `.notBuilt` deliberately: **they call for
opposite responses.** One is waiting on a Tower decision that is already
costed; the other is waiting on a backend nobody has written. Collapsing them
would tell a reader the same thing about very different situations — the same
argument the codebase already made when it split `.disconnected` from
`.unsupported`, and again for `.needsUpdate`.

**The badge is a fact about this build, not a live claim about the Tower you
are connected to.** Per-connection availability is still resolved by
`CartridgeAvailability.resolve` and rendered inside each workspace, so "Ready to
test" beside a workspace saying "Nothing yet" is not a contradiction — the app
is ready and that Tower is not. A test pins that the badge consults nothing at
runtime, because a badge that flickered with the network would stop being a
stable answer to "what is in this build".

Exactly one status is tinted, so the drawer answers *"which can I try?"* in a
glance rather than after reading eight identical capsules. Colour is not the
only carrier — the badge still spells the status out.

**Four tripwires fired, and all four were answered rather than silenced.** The
old suite deliberately guarded this: *"If a future change adds an
'available'/'active' status, this test should fail and force a deliberate
decision about whether the Tower actually supports it."* It fired, the Tower
does support it, and the decision is recorded at the test. What replaces those
guards is the invariant still worth defending — **a badge may not claim more
than the app can open** — asserted in both directions, plus a compile-time
exhaustive switch so a new case stops the build rather than reddening a test.
The compiler then found two further sites pinning the old vocabulary, including
one in `ObjectMemoryTests`.

Two user-visible strings and three doc comments were stale in the same way and
were corrected — notably the drawer footer, which still told the reader *"every
badge below still reflects the roadmap rather than something you can run."*

### 5. Cartridge drawer — one answer to one question
`workspace != nil` was written out in four independent places, and
`Cartridge.selectable` — the type documenting itself as the drawer's authority
— was used **only by tests**. `CartridgeDrawerRow` is now the single unwrap,
`selectable` is defined downstream of it, and the openable case carries a
**non-optional** workspace so "openable with nothing to open" stops being a
state anyone can write down.

All eight rows, their order, their badges, both accessibility hint strings, and
the three non-tappable informational rows are byte-identical. This was a
correctness fix, not a redesign.

---

# Architecture / Contract Changes

**No contract changed.** No wire message, field, or version was added, removed
or altered on either side. `ios/scripts/contract-drift-check.py` reports
AGREEMENT against the live Tower before and after this run.

Three internal shapes changed, all narrowing rather than widening:

| Change | Shape |
|---|---|
| `CartridgeDrawerRow` | A two-case enum replacing four independent `workspace != nil` derivations. The openable case carries a non-optional `CartridgeWorkspace`. **No id-keyed registry** — `docs/04-MODULE-SYSTEM.md` forbids dynamic module discovery before V1.0, and this is a `map` over the compiled-in catalog with the compiler still forcing exhaustiveness. |
| `CVFrameReading` | A projection of `TowerFrameResult` held beside `ExperimentalCVState`, not inside it — so the frame channel and the cartridge result channel stay separate types and `mayCarryData` is not weakened. |
| `CaptureResolutionPreference` | A DEBUG-only enum over DAT's `StreamingResolution`, reading `videoFrameSize` from the SDK rather than hardcoding pixel sizes. |

---

# Defects Found

Every fix below is covered by a test that was **proven to fail without it** —
the exact pre-fix failure output was captured in each case, not assumed.

### 1. The capture-rung picker unlocked during `.paused` and `.stopping`

**Symptom.** The picker was gated on `isCaptureEngaged`. Both DAT enums have a
`.paused` case and a `.stopping` case, and that predicate's allow-lists cover
**neither** — `DeviceSessionState` is `{idle, starting, started, paused,
stopping, stopped}` and `StreamState` is `{stopping, stopped, waitingForDevice,
starting, streaming, paused}`.

**Root cause.** `isCaptureEngaged` answers *"should the primary button read
Stop?"* — a question about whether capture is actively **running**. The picker
needs *"is a `DeviceSession` still **held**?"* Those are different predicates
and they diverge in exactly the two states that matter.

`.paused` is not hypothetical: `07-PLATFORM-CONSTRAINTS.md` §146 records it as
device-initiated — a cap-touch or thermal pause keeps the connection alive,
stops delivery, and resumes to `.started` on its own. On that resume
`beginCameraStream` returns immediately at its `guard camera == nil`, so a
`StreamConfiguration` chosen while paused is **never read**, and no log line
records that it was dropped. The panel goes on displaying a rung that was never
requested — precisely the Rule 3 violation the control's own doc comment said
it existed to prevent.

**Fix.** A distinct `isCaptureSessionClaimed`, with **exhaustive** switches over
both frozen enums rather than `default`-terminated ones — writing every case out
is what makes a future reader confront `.paused` instead of inheriting a
`default` that swallowed it, which is how the defect arose.

**Regression test.** `CaptureSessionClaimTests`, four cases. The decision was
lifted into a `nonisolated static func` so a synchronous test can call it — a
real `GlassesConnection` cannot be driven into `.paused`, and `.paused` is the
whole point. It exercises **every one of the 36 combinations**, because the
defect was exactly a case nobody thought to enumerate.
`testTheClaimPredicateIsStrictlyBroaderThanTheEngagedPredicate` is a tripwire:
it fails if the two predicates are ever collapsed back together.

**Found by:** independent adversarial review. **Commit:** see index.

### 2. A doc comment that inverted the truth about refresh stability

**Symptom.** The ranking doc justified its tie-break by claiming it prevented
*"cards visibly swapping places under the reader's finger."*

**Root cause.** True within one manifest, and misleading across manifests. The
manifest is refetched every time the revision moves — **67 times during the
two-minute P3 walk** — and the Tower re-solves segments in place, so
`point_count` for an existing segment changes between polls and the primary sort
key changes with it. Ranking removes a small hypothetical shuffle and introduces
a real one. The feature is still right; the comment would have led the next
engineer to believe the opposite.

**Fix.** The comment now states the cost plainly, says the trade is accepted
deliberately, and names the two remedies if a wearer finds the movement
distracting — rank only once the world stops changing, or animate the reorder —
while saying neither is worth building before someone reports it.

**Found by:** independent adversarial review.

### 3. Two tests that did not pin what they claimed

**Symptom.** `XCTAssertEqual(model.fragments, model.fragments)`, commented as
proving *"the order is a function of the manifest, not of how the sort happened
to run."* `ranked` is a pure function, so that assertion holds for **any**
implementation — including an unstable sort and including identity. And
`testRankingAnEmptyOrSingleFragmentWorldIsANoOp` passes unchanged if `ranked` is
reverted to identity, while its name claims ranking coverage.

**Fix.** The tautology is replaced by feeding the *same* segments in a
*different* arrival order and demanding identical output — the assertion that
actually discriminates. The degenerate test is renamed
`testAnEmptyOrSingleFragmentWorldSurvivesBeingOrdered` and its comment now says
outright that it passes either way and is kept as a crash guard, not as
coverage.

**Found by:** independent adversarial review.

### 4. The capture-resolution control omitted the axis that mattered most

**Symptom.** The footer, the section doc, the type doc, the tests and the Tower
handoff all presented the rung as an OCR-versus-tracking engineering trade-off.
**None mentioned bystanders, faces, redaction, or the Tower's recorder.**

**Root cause.** Raising the rung is not only an image-quality dial.
`TowerClient.sendFrame` sends frames at full captured size with **no downscale
anywhere**, and when the Tower's dataset recorder is armed it fsyncs those bytes
to disk verbatim — its own manifest declares `retains_raw_imagery: true`,
`redaction: "none"`, `privacy_tags: ["raw-imagery", "first-person",
"dataset-recording"]`. `.high` is **four times the pixels** of the default. So
the control raises the fidelity of unredacted first-person imagery of bystanders
in a recording that persists. A developer read a complete-sounding account that
omitted the one axis they would most want to know about.

**Fix.** Copy change, no new machinery. The footer now says it in plain words,
and the type doc records both the consequence and the fact that the first draft
omitted it.

**Found by:** dedicated privacy review.

---

# Reviewer Findings

Reviewers were treated as producing **evidence, not commands**. Every finding
below was independently verified in the code before anything was changed, and
two were rejected on that basis.

### Accepted

| # | Finding | Verification performed | Outcome |
|---|---|---|---|
| R1 | Picker unlocks during `.paused`/`.stopping` | Read both DAT `.swiftinterface` files and confirmed `.paused` exists in both enums and is absent from both allow-lists; traced `beginCameraStream`'s `guard camera == nil` | **Fixed** — Defect 1 |
| R2 | Ranking doc comment inverts refresh stability | Confirmed `fragmentsModel` republishes per geometry revision (`WorldBuilderClient.swift:401`) and that the Tower re-solves segments in place | **Fixed** — Defect 2 |
| R3 | `XCTAssertEqual(model.fragments, model.fragments)` cannot fail | Confirmed `ranked` is pure, so the assertion is a tautology | **Fixed** — Defect 3 |
| R4 | One new test passes on identity while its name claims ranking coverage | Traced each of the four new tests against a hypothetical `ranked = { $0 }` | **Fixed** — Defect 3 |
| R5 | Resolution control's copy omits the privacy axis | Traced the frame path to `capture.py`'s fsync and read the recorder manifest's own privacy tags | **Fixed** — Defect 4 |
| R6 | The Tower's capture-recorder state is never surfaced | Confirmed nothing in `ios/` reads `/health`; confirmed §2.7 sanctions displaying it | **Implemented** — see UI Work §4 |

### Rejected, with reasoning

| # | Finding | Why it was not acted on |
|---|---|---|
| R7 | `captureResolution` is not persisted, and nothing on screen says it is volatile | **Half accepted, half rejected.** Non-persistence is *deliberate* and pinned by a test — a rung silently surviving a relaunch is how a walk gets recorded at 720p without anyone choosing that, which is the more dangerous failure. The reviewer's real point was that the volatility was undocumented, so the footer now says "resets to Low when the app relaunches." The behaviour was not changed. |
| R8 | `fragments` is now O(n log n) and evaluated three times per body pass | **Rejected as a defect, recorded as a note.** Verified: three reads per body evaluation. This is a constant-factor change on a path that was already O(n) filtering three times — not a new cost class. At the ~470-segment worst case it is ~12,600 comparisons per render, microseconds. Optimising it now would be speculative. |

### Second review round — the two newest surfaces

A second adversarial review covered the CV Lab surfacing and the Tower health
panel. **It found a user-visible falsehood that all four gates had passed
over**, which is the clearest argument in this report for why the reviewer rule
exists.

| # | Finding | Severity | Outcome |
|---|---|---|---|
| R9 | **The CV Lab workspace contradicts itself in Release.** `latestFrameResult` is DEBUG-gated, so the "Latest result" panel correctly says *"nothing to show here"* — while three other strings on the same screen say the answer *"is shown above"*. Only one string had been made configuration-aware | **High** | **Fixed** |
| R10 | **`capture_id: null` rendered as "The Tower did not say."** The Tower always sends the key when the capture object is present; `null` is a positive statement that no recording has been opened. The panel reported it as withheld | **High** | **Fixed** |
| R11 | A health reading taken yesterday renders identically to one taken five minutes ago — the timestamp omits the date and nothing ever clears the state | Medium | **Fixed** |
| R12 | Four tests do not pin what they claim: the refused-fetch test passes with the HTTP status guard deleted; the "bounded" test passes with the timeout removed from the request; the frame-reading invariant test passes if the invariant is broken; `TowerReported.unreadable` is untested | Medium | **Fixed** |
| R13 | `refreshHealth()` cancellation leaves the button permanently disabled, and its comment claims the opposite | Low (unreachable today) | **Fixed** |
| R14 | `Labelled`'s synthesised memberwise init bypasses the whitespace guard its doc calls "the only way"; trimmed metric labels can collide into duplicate `ForEach` ids | Low | **Fixed** |
| R15 | Home omits the provenance caveat that `CVFrameReading.provenance`'s own doc says is owed wherever the figures are drawn | Low | **Fixed** |
| R16 | Per-render `Date.formatted`/`ByteCountFormatter` on the Developer Tools sheet at ~12 Hz while open | Note | **Deferred** — DEBUG-only sheet, only while open, not measured as harmful. Recorded rather than optimised speculatively |

**Both R9 and R10 were verified by the lead against the source before any fix
was commissioned** — `ContentView.swift`'s `.experimentalCV` arm and
`ProjectManager.startAutomaticConnections()` are both ungated, so Release really
does reach that screen; and `tower/tower/routes/health.py:70-84` really does
always send `capture_id` when the capture object is present.

R10 is worth dwelling on: it is the **`unreported`-vs-`absent` conflation
reproduced one level down at the field**, inside the very change whose central
design idea was keeping those two apart. A type-level distinction does not
enforce itself at the render site.

### On the World Builder lane's handoff
Its declaration of "NO IOS CHANGE REQUIRED" was **verified, not trusted**. Its
one flagged risk — a new `solve_chain_broken` event kind breaking an exhaustive
switch — was checked by grepping `ios/` for every event-kind identifier and
finding that **iOS consumes no event kinds at all**. Its claim that the geometry
contract is unchanged was checked with `git diff` over `docs/contracts/`, which
is empty. Both hold.

---

# Privacy Review

A dedicated privacy reviewer audited every change against
`06-PRIVACY-DATA.md`, the contract docs, and the Tower's actual persistence
code. One mitigation was required (Defect 4). Everything else was verified
intact.

### Guarantees checked and INTACT

| Guarantee | Evidence |
|---|---|
| Object Memory cannot persist people | `PERSISTED_CLASSES = ("laptop", "cell phone")`, enforced **twice** — in the relevance filter and again in the store, with a comment recording that the double enforcement exists because a refactor once wrote `person` straight through |
| No identity vocabulary on iOS | Repo-wide grep for `person_id`/`face_id`/`looking_at`/`gaze_direction` yields exactly one hit — the sentence in `IOS-TO-TOWER.md` asking Tower *not* to send them |
| No imagery fetchable from the Tower | `"fetchable": False`, no id and no URL minted; a Tower test asserts it and bans filesystem paths from the payload |
| No face recognition or identity inference | The only face code in the repo is detection-for-filling. No descriptors, no embeddings, no matching. Its label is a **process** claim (`faces-detected-and-filled/yunet-2023mar@0.30`), never "redacted" or "privacy-safe" |
| No UI implies identity where only an anonymous track exists | Scene Understanding is anonymous positional tracks throughout; Object Memory is category-not-instance |
| Release cannot reach the resolution control | Verified structurally, not nominally: Release does not define `DEBUG`, and the enum, the property, the entire camera session, the frame send path, the view and its sheet destination all compile out. **A Release build has no camera capture at all**, so it can reach neither the control nor the frames |
| Fragment ranking is geometry-only | `WorldSegmentSummary` carries counts, hashes and bounds — no imagery, no URL, no person-bearing field. Grep for `Image(`/`AsyncImage`/`thumbnail` across the World Builder workspace returns nothing |
| The CV Lab surface renders no imagery | Only scalar measurements and a withheld-reason string; the rendered annotated frame is never drawn |

### A finding for the Tower lane, not for iOS
The review established that **face redaction now exists on the Tower** —
`tower/tower/world_builder/redaction.py`, YuNet weights vendored, applied inside
`_persist_keyframe` — but covers **only the World Builder keyframe corpus**. The
dataset recorder's copy is written upstream of it and is never redacted, so both
copies coexist on disk.

This makes `IOS-TO-TOWER-RECONCILIATION.md` §0.4/§5 (*"No redaction is
implemented anywhere in Tower"*) **stale in both directions at once** — it
understates World Builder and overstates the recorder's exposure being
universal. It is written up in the Tower handoff §3a, along with the fact that
`redact()` **fails open** (on any exception it persists the original bytes and
records the label `none`), so "redaction is implemented" and "this frame was
redacted" are different claims and only the per-frame label settles it.

**Also flagged as unverified rather than assumed:** the redactor's constants
(`CONFIDENCE 0.30`, `UPSCALE 2`, `HEAD_DILATION 1.6`) were all tuned at 640×360
and nothing has measured them at 720×1280. That matters now that a raised rung
is reachable, and it is in the handoff.

---

# Backend Follow-Ups

Grouped by responsible lane. The full, executable versions are in
**`docs/agent-handoffs/TOWER-LANE-HANDOFF-FROM-MAC.md`**, written this run —
because the answers to two of these had been sitting in Mac-facing documents and
commit messages for days and were never handed back. That was this lane's
process defect and it is now closed.

## Tower / Windows lane

### T1 — Capture timestamp: their blocking prerequisite is ANSWERED (§8.1)
`IOS-TO-TOWER-RECONCILIATION.md` §0.3 carries this as **BLOCKED** pending
empirical proof that `CMSampleBuffer`'s PTS is capture time. **It was proved,
and the proof was never delivered.**

1,084 frames off the real Ray-Bans over 45 s, sampled on DAT's callback thread
before the main-actor hop. The argument is the jitter, not the offset:
`residual_sd / d_host_sd = **1.003**` (the residual is entirely arrival jitter;
the PTS carries none of it) and `d_pts_sd / d_host_sd = **0.141**` (a tight
1/24 s grid against arrivals scattering from 2.5 ms bursts to 120 ms stalls).

Their named blocking prerequisite — does the epoch survive a reconnect — is
also answered. **Neither persistent nor reset:**

| Event | wall gap | clock advanced | ratio |
|---|---|---|---|
| pause → resume | 39.165 s | 39.165 s | **100.0 %** |
| **stop → start** | **25.95 s** | **7.19 s** | **28 %** |
| **stop → start** | **192.70 s** | **~10.95 s** | **5.7 %** |

The two stop rows are the finding: gaps differing **7.4×** advance the clock by
nearly the same amount, so what survives a stop is a fixed teardown tail, **not
elapsed time**. It stays monotonic throughout, which is what makes it dangerous.

**Binding rule they must adopt:** carry an epoch identity alongside the capture
timestamp, or treat capture times as **incomparable** across a
`stream_stop`/`stream_start` boundary. Otherwise a consumer deriving a duration
across a lineage reconnect reports a five-minute outage as about ten seconds.

Drift bounded at **~5 ppm**. Still open and deliberately not guessed: whether
the clock survives the glasses powering off.

### T2 — Resolution: they already have it, and there is no ladder (§8.2)
Their contract asks iOS for *"a way to learn which rung of the adaptive ladder is
active"* and §1.5 asserts *"DAT's ladder changes resolution mid-stream."*
**Both are wrong, and Document Memory's blocker is misstated because of them.**

- iOS has **always** sent `width`/`height` on every frame, from the decoded
  buffer's format description — not from the requested setting. The Tower reads
  them, and reads them **twice** (`declared_*` and `decoded_*`).
- `StreamingResolution` is a fixed three-case enum chosen **once**, at
  `addCamera(config:)`. Nothing in DAT renegotiates it. Measured on hardware:
  the P3 walk recorded **108 frames, all 360×640, zero variation**.

So resolution-keyed intrinsics are defending against something that does not
happen on this path. Harmless as future-proofing; it should not be described as
responding to observed behaviour, and no other decision should rest on it.

**The real gap** is a way to *request* a rung, and the genuine conflict behind
it — 720p helps Document Memory (recall 0.429–0.810 → 0.957–1.000) and hurts
World Builder (73.3% of frames rejected as blurred) — is a cross-cartridge
product decision Tower should make. Three options are laid out in the handoff.

### T3 — Object Memory and World Builder geometry are undiscoverable
Both are real, live, contract-bearing capabilities served over HTTP. Neither
appears in `/cartridges`, in **either** list. `object_memory` has **no cartridge
constant at all**. A client therefore cannot discover them, and iOS hardcodes
the routes and contract ids — exactly the coupling `/cartridges` was built to
remove. Either declare HTTP-transport contracts, or state in the declaration
that it is scoped to the WS channel and say where HTTP contracts live. Silence
is indistinguishable from "does not exist."

### T4 — Their redaction claim is stale in both directions
See *Privacy Review*. Face redaction exists for World Builder keyframes and not
for the dataset recorder; the contract doc says it exists nowhere.

### T5 — Bearing sign convention
Unchanged and not blocking. iOS's declared convention (degrees from straight
ahead, positive to the right) stands; nothing needs to happen until Scene
Understanding has a transport.

## World Builder specialist lane (`world-builder/next-generation`)
**Nothing is owed.** Their handoff declares no iOS change required and that was
independently verified. Their two optional follow-ups: `points_discarded` on the
HTTP manifest (a one-line addition on their side, which iOS would then render as
*"N measurements were too uncertain to place"* — deliberately **not** merged with
the existing unresolved count, which answers a different question); and fragment
ranking, **which this run implemented**, unblocking their held-back segmentation
variant.

**The trap they recorded, restated so it is not lost:** when registration lands,
`content_hash` excludes `transform_to_world`, so a segment gaining a placement
without its points changing moves no hash iOS watches — and iOS would keep
drawing the cached, unplaced version. iOS will need to decode
`transform_to_world` and key its cache on `(content_hash, placement_hash)`. That
is a **breaking client-side change and must be planned, not retrofitted.**

---

# Physical Validation Completed

**During this run: none.** No hardware test was performed, because none was
needed to land this work and the user was deliberately unavailable. Everything
below is queued rather than claimed.

**Inherited, and still standing** — the P3 clean walk of 2026-08-26, on the
previous HEAD:

- zero reconnects, zero stalls, one bracket, tracking Good in 129/129 samples
- **67 geometry manifests, 88 segment fetches, 1,043 served from cache (92.2%)**
- **7,086 points drawn across 28 segments while the wearer was still moving**
- zero manifest failures, zero segment fetch failures, zero pose-convention refusals
- 2,546 DAT ordinals, 1,343 frames written, 12 fps gate with no frame loss

Nothing in this run touches the geometry transport, the subscribe path, the
reconnect logic, or the frame path, so that evidence carries forward. What this
run changed is **the order fragments are drawn in**, **which screen the CV Lab's
answer appears on**, **a DEBUG-only picker**, **a DEBUG-only status panel**, and
**comments**.

---

# Physical Validation Still Required

Ordered by value. **Tests 1–4 are one ~15-minute session** — same build, same
Tower, one donning of the glasses. Test 5 is separate because it needs a
different Tower branch. Test 6 is separate because it deliberately misconfigures
the rung.

Common prerequisites for all: iPhone 16 Pro, Ray-Ban Meta paired and donned,
Tower reachable at `100.110.156.55:8000`, **Debug** build (Release has no camera
path at all).

> **Verify instrumentation at runtime, not from the install succeeding.** A
> previous session installed a build and the phone kept running the old one; it
> was only visible because the new build logs handshake timing. Baseline
> handshake on this link is **7 ms** — read any reconnect against it.

### BATCH A — one session, ~15 minutes

#### A1. Fragment ranking on a real walk
- **Cartridge:** World Builder · **Branch/commit:** this branch, final HEAD
- **Tower:** any; a world must build
- **Do:** Start capture. Walk a room 60–90 s, preferring **lateral translation
  and arcs around objects** over pure head rotation. Stop. Open World Builder →
  fragments grid.
- **Expected UI:** the fragment with the most points is **first**. Cards are in
  non-increasing point order. The unresolved sentence is unchanged.
- **Pass:** ordering is non-increasing by point count; `unresolvedCount` matches
  what the same walk would have produced before.
- **Failure signatures:** cards in capture order → ranking not applied. **Cards
  visibly reshuffling mid-walk** → expected and documented, but note how
  distracting it is; the remedies are named in `WorldFragmentsView.swift`. A
  changed unresolved count → ranking leaked into membership; that is a defect.

#### A2. The CV Lab shows its own answer
- **Cartridge:** Experimental CV Lab · **Tower:** must report
  `module_state: "active"` on `/health`
- **Do:** With capture running, open Cartridges → Experimental CV Lab.
- **Expected UI:** a panel naming the Tower's own `result_label` and its latest
  value, plus copy saying the Tower chose the experiment at startup and this app
  cannot list, choose, start or stop one.
- **Pass:** a labelled figure appears and updates as frames flow; the same
  figure also appears on Home.
- **Failure signatures:** a bare number with no label → the pair rule is broken
  (it should be structurally impossible). "Nothing yet" while Home shows a
  figure → the reading is not reaching this screen. A `0` where the Tower sent
  nothing → absence collapsed into zero.

#### A3. The Tower's real capture state
- **Do:** Developer Tools → Tower section → refresh.
- **Expected UI:** the Tower's actual `armed`/`recording`/`frames_written`. With
  a recorder configured, `frames_written` climbs while capture runs.
- **Pass:** the numbers match what `curl http://100.110.156.55:8000/health`
  reports at the same moment.
- **Failure signatures:** `false`/`0` shown when the Tower omitted `capture`
  entirely → absence collapsed into a confident wrong answer, which is the
  specific failure this surface was built to avoid. A silent blank on a failed
  fetch → failure is not a visible state.

#### A4. The paused-session regression *(this is the one only hardware can do)*
- **Do:** Start capture. Open Developer Tools → Capture Resolution; confirm the
  picker is **disabled**. Now trigger a device pause — **cap-touch the glasses**,
  or let a thermal pause occur — and while paused, look at the picker again.
- **Expected UI:** the picker stays **disabled** throughout, and the footer says
  a session is still held **including while paused or stopping**.
- **Pass:** at no point during pause or resume is the picker interactive.
- **Failure signature:** **the picker becomes tappable while paused.** That is
  the exact defect fixed this run; if it reappears, `isCaptureSessionClaimed` is
  not being consulted. Worse signature: change it while paused, resume, and see
  Developer Tools claim a rung the console never logged as requested.

### BATCH B — separate, needs a different Tower

#### B1. World Builder point quality and solve-chain segmentation
- **Owner:** the World Builder lane's acceptance criteria, reproduced from their
  handoff. **No iOS change is under test** — this validates *their* work through
  the iOS surface.
- **Tower:** `world-builder/next-generation` @ `97dfdfd` or later
- **Do:** a normal room scan, 60–90 s, favouring lateral translation and arcs.
- **Preserve:** the world id, `derived/manifest.json` (for `points_discarded`),
  and a screenshot of the fragments grid.
- **Expected:** fragment cards show recognisable structure spread across the
  card rather than a dot plus specks. Segments that previously rendered
  near-empty — the ones with the most points — improve most; **that inversion is
  the tell.** `segment_count` **rises ~11%**, `solved_count` ~22%, `point_count`
  ~24%. **`keyframes` must be invariant.**
- **Failure signatures:** fragments now *empty* rather than tighter → the gate
  over-refuses; capture `points_discarded` and send it back. `keyframes` moved →
  the change leaked into tracking, which must not happen. Stale geometry after a
  rebuild → cache invalidation.
- **Note:** ranking (A1) and this change interact — more segments make the grid
  ordering matter more. Run A1 first on the current Tower so the two are not
  confounded.

### BATCH C — separate, deliberately misconfigured

#### C1. Document Memory at a raised rung — the premise test
- **Cartridge:** Document Memory. **This is the test the whole resolution
  control exists to make possible.** Its premise has never been tested on this
  hardware.
- **Do:** With **no session running**, Developer Tools → Capture Resolution →
  **High**. Confirm the footer's privacy sentence is understood: frames are not
  downscaled, and while the Tower's recorder is armed every frame is written to
  disk **unredacted**. Start capture. Hold a page of ordinary printed text, or a
  laptop screen, in view for ~30 s at a comfortable reading distance. Stop. Set
  the picker back to **Low**.
- **Then, on the Tower:** run the document-memory CLI over that capture and
  compare word recall against the 360×640 baseline (0.429–0.810).
- **Pass:** recall at 720p approaches the measured 0.957–1.000, which would
  confirm resolution — not the OCR engine — is Document Memory's blocker.
- **Expect and do not treat as failure:** **the walk may reconstruct no world at
  all.** `_require_matching_resolution` raises `IntrinsicsResolutionMismatchError`
  at build time when keyframes do not match the calibrated size. That is the
  Tower's guard working. Do not expect a world and a document reading from the
  same session.
- **Also expect:** far more frames rejected as blurred (73.3% at 720p under
  `min_sharpness = 25.0`).
- **Privacy:** prefer a room with no bystanders. This produces the
  highest-fidelity unredacted first-person recording the system can make.

---

# Test Results

All four gates run on this Mac from this working tree at the end of the run.
Xcode 26.6, Swift 6.3.3, iOS SDK 26.5.

| Gate | Result |
|---|---|
| **XCTest** | **441 passed, 0 failed** (baseline at run start: 398) |
| **Debug (Simulator)** | **0 errors, 0 warnings** |
| **Release (Simulator)** | **0 errors, 0 warnings** |
| **Signed device build** | **0 errors, 0 warnings** — `Apple Development: tv.lloyd@icloud.com (FV94VKA54U)`, iPhone 16 Pro (`iPhone17,1`) |
| **Contract drift check** | **AGREEMENT** — every contract the live Tower states is implemented by this build |

**+43 tests over the run**, all of them pinning behaviour that was previously
unpinned, and every fix in *Defects Found* was proven to fail before it passed.

### Reading the logs correctly, twice over
Two traps, both already documented by this lane and both re-encountered:

- **`warning:` without anchoring on ` warning: `** picks up
  `appintentsmetadataprocessor` notices, which are a tool notice that the target
  declares no `AppIntents.framework` dependency — **not compiler warnings**. All
  counts above filter them.
- **` error: ` matches app log output.** A green run of this suite contains ~13
  lines like `[Glasses][Tower] error: Tower closed the connection (code 1006)`
  — those are tests deliberately exercising failure paths, and counting them as
  build errors would report a clean build as broken.

### The one flake, recorded rather than hidden
`TowerClientTests.testSendWindowIsClearedByReconnectSoSendingResumes` failed
once, mid-run, with four assertions. It was **reproduced-in-isolation before
being dismissed**: 3/3 passes alone, and green on every subsequent full run. The
discriminating evidence is wall time — the failing run took **28.5 s against
19.4 s** for a green one, i.e. heavy CPU contention from concurrent agents. It
drives a real local WebSocket server and is timing-bound. **On a quiet machine a
failure here is a real signal, not noise.**

---

# Device Validation

**A signed device build was produced and verified this run. No hardware
*behaviour* test was run** — see *Physical Validation Still Required*, which
queues them in three batches.

**The build was deliberately not installed on the phone.** Installing replaces
whatever build is currently on the user's device, and the user was away; the
stated gate is a signed build, and the install is the first step of Batch A
anyway. Doing it then also avoids repeating the trap this lane hit last wave —
the phone kept running the previous build and "installed" was true of the wrong
one, visible only because the new build logs handshake timing. **Verify
instrumentation at runtime, not from the install succeeding.**

Device-side evidence carried forward from the previous wave, still valid because
nothing this run touches the frame path, the subscribe path, the geometry
transport, or reconnect:

- App installed and running on physical iPhone 16 Pro (`com.tristanvarner.Glasses`)
- DAT registration works; glasses discovery works; live Tower connection works
- Baseline handshake on this link: **7 ms**
- P3 clean walk: 67 manifests, 88 segment fetches, **92.2% cache hit rate**,
  7,086 live points across 28 segments, zero transport failures

---

# Performance / Resource Findings

Nothing required profiling; two items were measured or reasoned rather than
assumed, and one review finding was rejected on the numbers.

| Item | Finding |
|---|---|
| `WorldFragmentsModel.fragments` now sorts | Read **three times per body evaluation** (headline, `isEmpty`, `ForEach`). A constant-factor change on a path that already filtered three times — not a new cost class. At the ~470-segment worst case, ~12,600 comparisons per render. **Rejected as a defect**; optimising would be speculative. |
| CV Lab panel observation | The workspace takes `tower` as a plain `let`; only the leaf panel observes, so a 12 Hz reply invalidates one small panel instead of re-running the workspace body. This preserves `TowerReachabilityReader`'s behaviour rather than trading it away. |
| Tower health fetch | Explicit button only — **no polling, no timer**. Bounded at 10 s with `reloadIgnoringLocalCacheData`, mirroring `ObjectMemoryHTTPClient`. A second tap while in flight is dropped. It cannot touch the frame path. |
| Main-actor discipline | `isCaptureSessionClaimed` was made `nonisolated` — it is a pure function of two arguments — which is also what made it testable. |
| Retain cycles | The wave before this one fixed three (`guard let self` outside an unbounded `for await` promotes a weak capture to strong for the task's life). The new health task deliberately places `guard let self` **after** the await so the strong capture lasts only the hop back. |

---

# Known Limitations

1. **Release builds are not a readiness signal, and this run did not change
   that.** `GlassesConnection.swift` and `ProjectManager.swift` put the entire
   camera path inside `#if DEBUG` with no `#else`. A Release build contains no
   camera session and **sends no frames to the Tower** — verified against the
   binaries with `nm`, not read from the source. "Release builds, 0 errors" is
   true and means less than it looks: it compiles cleanly partly *because* it
   excludes half the app. Do not treat it as evidence of product function until
   the camera path leaves `#if DEBUG`.

2. **Fragment cards can move mid-walk.** Ranking is a pure function of one
   manifest, but the manifest is refetched on every revision change — 67 times
   during the P3 walk — and point counts change between rebuilds. Documented
   at the code, with two named remedies, neither built because no wearer has yet
   said it is a problem.

3. **`.high` capture and World Builder are mutually exclusive in one session.**
   Intrinsics are calibrated per resolution and the Tower refuses mismatched
   keyframes at build time. A raised-rung session should not be expected to
   produce a world.

4. **The CV Lab cannot say *which* experiment is running.** `result_label` names
   the *number*, not the experiment. The Tower has a registry of eight and
   exposes it nowhere on the wire, so the screen deliberately does not guess. It
   says so.

5. **Object Memory shows an empty state against the current Tower** because that
   Tower has no object-memory root configured and returns 404. That is rendered
   truthfully and by test; it is a Tower configuration state, not an iOS defect.

6. **One known flaky test.**
   `TowerClientTests.testSendWindowIsClearedByReconnectSoSendingResumes` drives a
   real local WebSocket server and is timing-bound. It failed once during this
   run under heavy concurrent CPU load (**28.5 s wall against 19.4 s on a green
   run**) and passed 3/3 in isolation and on every subsequent full run. Recorded
   rather than hidden. If it fails on a quiet machine, that is a real signal.

7. **Four cartridges cannot be built at all**, and no amount of iOS work changes
   that: Visual Q&A, Accessibility, Environmental Memory and Translator have
   **zero Tower code**. Translator additionally has no audio path anywhere in the
   system — `frames.py` accepts JPEG only and `Module.process()` takes one still
   image. Building that is a subsystem, not a feature.

---

# Deferred Work

Only items with a real reason to be deferred.

| Item | Why deferred, honestly |
|---|---|
| **Reopening a saved world** | The Tower **supports** it — `world_id`/`session_id` on `result_subscribe` — and iOS **models and renders** it (`WorldInspectionMode.inspecting`, the canvas draws a "Saved world" heading). Nothing can set it. It was not built because **there is no endpoint that lists worlds**, so the only reachable world id is one already on screen, and the resulting feature would be "pin to the world you are already looking at." That is worth building *after* Tower offers a world list, and it would perturb a physically-proven subscribe path for little gain today. **Recorded as the clearest remaining instance of an implemented backend capability iOS cannot reach.** |
| **`unsubscribeFromResults` has no caller** | Fully implemented and never invoked. Checked rather than assumed: the resubscribe budget is 3 per connection against a Tower cap of 8 subscriptions, so **no leak is reachable**, and the Tower treats a closed socket as sufficient cleanup. Wiring it now would add a message the system does not need. |
| **`points_discarded` in the fragments view** | Blocked on Tower — it is on the build manifest, not the HTTP manifest. The World Builder lane says it is a one-line addition on their side "say the word". Worth asking for; the copy is already drafted in their handoff. |
| **Surfacing capture state to the *wearer*** | The new panel is in Developer Tools, which is DEBUG-only. Whether a wearer should see "the Tower is recording" in the product surface is a genuine product decision with privacy weight, not an engineering one, and it is not iOS's alone to make. |
| **`StreamManager`** | Inert placeholder — `state` and `metrics` are never assigned. Left alone deliberately: real streaming state lives on `GlassesConnection`, and this is labelled as a placeholder in the one DEBUG surface that shows it. |

---

# Recommended Next Steps

In priority order. The top two are not iOS work, which is the honest shape of
this programme right now.

1. **Deliver the Tower handoff and get T1 acted on.** The capture-timestamp
   measurement unblocks their §6.5 wire addition, which every cartridge's
   timestamps depend on. It has been sitting undelivered for days. **This is the
   single highest-value item in the programme and it costs a read.**

2. **Tower decides the resolution question (T2).** 720p helps Document Memory
   and hurts World Builder, one stream cannot serve both, and the three options
   are laid out. Until someone chooses, Document Memory cannot progress and the
   new picker is only an experiment tool. Note their premise is wrong twice
   over — they already receive the resolution, and there is no ladder.

3. **Run BATCH A** (~15 min, one donning). It validates four surfaces at once,
   and **A4 is the only way to confirm the paused-session fix** — no test can
   produce a cap-touch.

4. **Run BATCH C** — the Document Memory premise test. It is the first
   opportunity this programme has ever had to test that cartridge's central
   claim, and the control that makes it possible landed this run.

5. **Ask the World Builder lane for `points_discarded` on the HTTP manifest.**
   One line on their side; iOS then renders a truthful *"N measurements were too
   uncertain to place"* — a better statement than the existing unresolved count,
   and **deliberately not merged with it**, because they answer different
   questions.

6. **Plan the registration cache-key change before registration ships.** When a
   segment gains a placement without its points changing, nothing iOS currently
   watches moves, and it would keep drawing the cached unplaced version. iOS
   needs to decode `transform_to_world` and key on
   `(content_hash, placement_hash)`. **Breaking, and must be planned rather than
   retrofitted.**

7. **Take the camera path out of `#if DEBUG`,** or stop citing the Release gate
   as readiness. Today it is both.

8. **Ask Tower for a world-list endpoint,** which would make reopening a saved
   world worth building — the clearest remaining backend capability iOS cannot
   reach.

9. **Do not start** Environmental Memory (its own design says so), Translator,
   or the voice halves of Visual Q&A and Accessibility. There is no audio path
   anywhere in the system and building one is a subsystem, not a feature.


---

# Commit Index

| Commit | What it carries |
|---|---|
| `32ea0ee` | **feat(ios): the rung stops being a constant, and the grid gets an order** — World Builder fragment ranking; the DEBUG capture-resolution control; `CartridgeDrawerRow` unifying the four `workspace != nil` derivations; the stale doc comments the live Tower contradicts; and `TOWER-LANE-HANDOFF-FROM-MAC.md` |
| `fea8e71` | **feat(ios): the badges stop describing a roadmap, and the Lab shows its answer** — the `CartridgeStatus` vocabulary change; the Experimental CV Lab surfacing its own output; the Tower capture-state panel; every fix from both adversarial reviews and the privacy review; and this report |

Base of the run: `2dce88d`. Neither commit rewrote history; nothing was
force-pushed; `main` was not touched.

---

# Closing note — what this run actually establishes

The task assumed a large backend waiting to be wired into a UI. **The
measurable finding is that the Mega branch was already fully consumed and that
the Tower offers exactly one typed contract**, with four of the nine cartridges
having no backend code at all. Building screens for those would have meant
rendering data no backend produces.

So the work that remained was smaller than briefed, and most of the value in
this report is not the code:

- **Three claims in the Tower's own contract document are stale**, and one of
  them — the capture-timestamp prerequisite — was **answered by this lane days
  ago and never handed back**. That handoff is the highest-value artifact here.
- **The same stale belief** — "no module runtime exists yet" — was found in
  **three separate places** in the iOS source, most visibly as a drawer badge
  telling a person that a device-validated cartridge was a "Future" concept.
- **Both adversarial reviews found real defects in this run's own work**, one of
  which was a user-visible falsehood in Release that all four green gates
  passed over. That is the argument for the reviewer rule, stated as evidence
  rather than as policy.

Nothing here was validated on hardware. **Batch A is four tests in a single
~15-minute donning, and A4 is the only way to confirm the paused-session fix,
because no test can produce a cap-touch.**
