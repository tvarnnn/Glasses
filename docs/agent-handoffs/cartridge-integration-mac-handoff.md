# Cartridge Integration — cross-machine handoff

**Status:** source-level implementation complete. **Never compiled. Never run.
No test in this document has been executed.**

Produced on Windows: no Xcode, no Swift compiler, no Simulator, no iPhone, no
Meta DAT hardware. Every claim here is a statement about source, an argument, or
a labelled hypothesis. The Mac is the authoritative validation gate.

A fresh Mac Claude should be able to continue from this document alone.

---

## MAC CLAUDE START HERE

```bash
git fetch origin
git checkout ios/cartridge-integration
git log --oneline -6      # expect 4 commits on top of 6a2d114
```

Then, in order:

1. **§11** — the Xcode validation sequence. Debug build, 220 tests, Release
   build, warning comparison against `6a2d114`.
2. **§10** — read *before* fixing the first compile error. It ranks where errors
   are most likely and records two candidate errors that were investigated and
   dismissed, so you do not re-derive them.
3. **§12** — the Simulator smoke test. The single most important line in it is
   that `[Glasses][Init] GlassesConnection created` appears **exactly once per
   launch** after visiting all five workspaces.
4. **§13.1** — the physical cartridge-switching check. This is the one thing the
   automated tests approximate but cannot make: that switching cartridges during
   a live session leaves the camera running.
5. **§16** — merge / revise / revert criteria before you decide.

Three things to know before you start:

- **Nothing here has been compiled.** Expect compile errors; that is the
  anticipated outcome, not a failure of the change.
- **`project.pbxproj` was not touched**, and does not need to be. The 18 new app
  sources compile via the synchronized group; no new *test* file was added.
- **Two decisions in this change are product questions, not engineering ones** —
  §6 (two module concept seeds written from the iOS side) and the last part of
  §17 (Rule 10 scope). Both belong to whoever owns the roadmap. Neither blocks
  compilation or merge.

---

## 1. Git state

| | |
|---|---|
| Branch created | `ios/cartridge-integration` |
| Base commit | `6a2d114` — "Record the review outcomes in the Product Shell V2 handoff", the head of `ios/product-shell-v2` |
| Product Shell V2 | `ios/product-shell-v2` @ `6a2d114` (untouched) |
| Sender branch | `ios/send-window-investigation` (untouched) |
| `ui/product-shell` | `d9e513d` (untouched) |
| `main` | `645e57d` (untouched) |

`git fetch origin` was run at the start. **One remote change since Product Shell
V2 was written:** `origin/ios/send-window-investigation` has moved from `7508db1`
to `97aa79c`, "Record the Mac compile and test validation in the handoff". That
is the Mac documentation commit the Product Shell V2 handoff §1 said was missing.
It touches **only** `docs/agent-handoffs/ios-send-window-handoff.md` (+174/−26)
and records that at `7508db1` the Debug and Release builds succeeded, 89/89 tests
passed six consecutive times, and the five clean-build warnings match `d9e513d`
exactly — so the base of this work is Mac-validated after all, and no compile
fixes were needed there.

It has **not** been merged into `ios/product-shell-v2` or into this branch.
Merging it is a pure documentation merge and should be trivial; it is left as a
deliberate decision for whoever reconciles the branches.

Working tree at start: clean.

---

## 2. What this task was for

Make the iOS app structurally ready to consume real Tower contracts for four
cartridges — World Builder, Experimental CV Lab, Document Memory, Scene
Understanding — **without inventing any Tower contract**.

The hard constraint throughout: Tower Claude is concurrently designing the real
contracts. Any message name, route, JSON payload, or geometry schema invented
here would (a) guarantee a rewrite and (b) let the UI display shapes the Tower
never agreed to produce. So the rule was: **build the iOS seam, leave the wire
binding explicitly unresolved.**

Product Shell V2's principles are carried forward unchanged: persistent shell,
loaded ≠ active, auto-connect ≠ auto-stream, camera inactive until an explicit
user action, Developer Tools isolated, single-owner runtime.

---

## 3. Architecture

```text
ContentView                         ← @StateObject ProjectManager (still the only one)
 │                                    owns CartridgeClients (the 4 clients)
 └ workspace  (one switch)          ← the ONLY per-cartridge dispatch point
    ├ HomeWorkspaceView                       (nothing selected)
    ├ WorldBuilderWorkspaceView               ← glasses + tower + client
    └ TowerReachabilityReader(tower:)         ← the ONLY observer of TowerClient
       │                                        for the three below
       ├ ExperimentalCVWorkspaceView          ← Bool + client
       ├ DocumentMemoryWorkspaceView          ← Bool + client
       └ SceneUnderstandingWorkspaceView      ← Bool + client
                    │
                    ▼
        <Cartridge>ViewModel        ← @StateObject, ObservableObject
                    │                  holds NO runtime references, no deinit;
                    │                  subscribes to its injected client
                    ▼
        <Cartridge>Client protocol  ← cartridge-specific interaction shape
                    │  : CartridgeClient   ← the one shared question
                    │  + stateUpdates      ← the announce half
                    ▼
        TowerCapabilities           ← what the Tower has declared: nothing
```

### 3.1 Why a switch and not a registry, at four cases

Product Shell V2 argued for a `switch` with one case. Four is usually where that
argument is abandoned. It holds better now, not worse:

- the set is still closed and compiled in — a workspace is a SwiftUI view in this
  binary, and `04-MODULE-SYSTEM.md` forbids dynamic module discovery before V1.0,
  so nothing can appear that was not compiled;
- exhaustiveness is the feature. A new case makes the compiler demand the arm;
  a registry would silently fall back to Home;
- the anti-pattern the roadmap warns about is per-cartridge conditionals
  scattered through one enormous view. There is exactly one switch, in one place,
  whose arms are one-line constructor calls into separate files.

What *did* emerge as genuinely shared is the **client** layer, not the view
layer — see §4.

### 3.2 The asymmetry in what each workspace receives

`WorldBuilderWorkspaceView` takes `glasses` **and** `tower`; the other three take
`tower` only. This is load-bearing rather than incidental: World Builder shows
the viewfinder and owns one of the app's two capture buttons. The other three
show what the Tower knows, have no session control, and **are not handed the
object that could start one**.

The number of places that can reach `startCameraSession()` is therefore still
exactly **two** (Home and World Builder), while the number of screens went from
two to five.

### 3.3 Connectivity is passed as a value, never as an object

Every view model exposes `availability(isTowerReachable: Bool)` and
`phase(isTowerReachable: Bool)` rather than storing a `TowerClient`. Passing the
*fact* rather than the client is what keeps a view model free of a runtime
reference it could act on.

**Only World Builder observes `TowerClient` directly**, and it has a reason to:
its capture control warns when the Tower is offline, because a `stream_start`
sent while it is down is dropped and every frame after it is suppressed for the
whole session.

The other three go through `TowerReachabilityReader`. That is not tidiness — it
is a re-render fix. `TowerClient` publishes `frameResultCount` and
`latestFrameResult` **once per reply** (~12 Hz while streaming), so any view
observing it is invalidated at that rate. Leaving a workspace does not stop
capture (Product Shell V2 §8, deliberate), so "start capture in World Builder,
then look at Scene Understanding" is an ordinary path. Three workspaces would
have been re-evaluating at reply rate to read a `Bool` that changes almost
never — on the main actor, which is the actor the sender's send-window
completions hop back to in order to release their slots. That is the same defect
class §12 of the Product Shell V2 handoff was written about, and its review
caught a dead `tower` dependency once already.

### 3.4 The clients live on `ProjectManager`, not in the workspaces

`CartridgeClients` holds the four, and `ProjectManager` holds it. A workspace
`@StateObject` is destroyed on every cartridge switch; a Tower-backed client will
hold a subscription and whatever it has accumulated, and destroying that loses
work and tears down a subscription nobody asked to end. Product Shell V2 §11
states the rule.

The clients that exist today are stateless constants, so this costs nothing now.
It is here now anyway because the alternative — a default argument letting
`UnavailableFooClient()` be constructed at the point of use — makes the wrong
wiring the path of least resistance on exactly the day the right wiring starts to
matter. The view model initialisers therefore have **no default argument**.

### 3.5 `stateUpdates`: the half that was missing

A `var state { get }` can be read; it cannot announce. Each cartridge protocol
also requires `stateUpdates: AnyPublisher<State, Never>`, defaulted to a
never-emitting `Empty`, and each view model subscribes in `init`. Without it, a
Tower-backed client changing its state would have had no path to the view
model's `@Published` property — and the claim that wiring one in is "an
injection, not a change of shape" would have been false in all four cartridges.

`AnyPublisher` rather than an `ObservableObject` conformance because
`ObservableObject` has an associated type, which would have forced every holder
of `any FooClient` to become generic. The subscription is cancelled by
`Set<AnyCancellable>` deallocating, so there is still no `deinit` anywhere.

---

## 4. The shared layer, and why each piece earns its place

`Glasses/Cartridges/Integration/` — five files, no generics over cartridges, no
plugin framework.

| Type | File | Justification (the rule: 2+ cartridges must plausibly need it) |
|---|---|---|
| `CartridgePhase` | `CartridgePhase.swift` | A **payload-free** projection of each cartridge's own state. Used by one shared panel and by one table-driven test that asserts, over all four at once, that a phase without data carries no data. Each cartridge keeps every one of its own domain cases. |
| `CartridgeAvailability` | `CartridgeAvailability.swift` | All four have the same four answers, and the *precedence* between them (contract mismatch outranks unreachable Tower) must be decided once or a user is sent round a loop that cannot terminate. |
| `CartridgeContract` | same | An opaque identifier compared for equality only. Deliberately not an integer version — that would assume ordering and backward compatibility, neither of which is ours to decide. |
| `CartridgeFailure` | same | All four fail the same ways, and Rule 3 makes a truthful failure state mandatory. |
| `CartridgeClient` / `TowerCapabilities` | `CartridgeClient.swift` | "The Tower declares nothing" is **one fact**; four hardcoded copies would rot at four rates. |
| `WorldScaleSemantics` | `Observation.swift` | Moved verbatim from `WorldModel.swift`. World Builder and Scene Understanding both report distances; two copies of a rule this load-bearing is how two copies come to disagree. |
| `ObservationProvenance` | same | Experimental CV Lab, Scene Understanding, Document Memory. |
| `ObservationTime` | same | Document Memory, Scene Understanding, Experimental CV timings. |
| `ObservedDuration` | same | Document Memory, Scene Understanding. |
| `RedactionState` / `VisualArtifactState` | `VisualArtifact.swift` | Document Memory thumbnails, Experimental CV annotated frames; Scene Understanding if it ever shows a crop. |
| `CartridgeStatePanel` | `Views/Components/` | One wording for the one fact all four currently report. Four hand-written versions would drift into four explanations of the same thing. |

**Deliberately NOT built:** a `CartridgeDataState<Value>` generic that would
replace the four domain state enums, and a generic
`fetch<Request, Response>` on `CartridgeClient`. The four cartridges have four
genuinely different interaction shapes — World Builder publishes a continuously
current state, Experimental CV Lab takes a command and reports progress, Document
Memory answers point queries, Scene Understanding publishes a changing set — and
one abstraction over those is a plugin SDK wearing a protocol's clothes.

**Also removed during self-review:** a `CartridgePhaseReporting` protocol that
nothing used generically. It was documentation pretending to be code, and under
`SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` an unannotated protocol would have
been MainActor-isolated, which the nonisolated `Sendable` state enums could not
conform to. Deleted rather than annotated.

---

## 5. The four cartridge seams

Each is: a domain model file, a client + view model file, and a workspace view
file. Each client's only implementation today reports that the Tower cannot do
it, and each says so in a sentence written for a person.

### 5.1 World Builder — extended, not rewritten

`WorldModel.swift` keeps `WorldModelState`, `WorldSnapshot`,
`WorldTrackingQuality` and gains:

- **`.finalizing(WorldSnapshot)`** — capture ended, Tower still working. Separate
  from `.receiving` (no new observations) *and* from `.finalized` (the figures
  are not yet the ones that will be stored). `isReceivingUpdates` is **false**
  here: a "live" badge while the camera is off is a lie about the sensor even
  while the compute is real.
- **`WorldCalibrationState`** — `unknown` / `uncalibrated` / `calibrating` /
  `calibrated`. Coarse, because the calibration *procedure* is the Tower's to
  design. Deliberately **no** percentage.
- **`WorldGeometryReport`** — the file's most important refusal. `representation`
  is an **opaque string the Tower chooses**; iOS stores it, shows it verbatim, and
  never branches on it. No enum of point-cloud / mesh / landmarks exists, because
  that would prejudge a Tower decision and leave a rendering path expecting the
  wrong shape. `elementCount` is never shown alone — a bare number invites the
  reader to supply their own unit.
- **`WorldTrajectoryReport`** — pose count and path length. **No pose array**: a
  pose schema needs coordinate frame, rotation convention, handedness and units,
  each of which renders plausibly and wrongly if guessed.
- **`WorldPersistenceState`** and **`WorldInspectionMode`** — saved-world reload
  and inspection, with "did not say" kept distinct from "session only".
- **`WorldSnapshot.permitsMetricDisplay`** — both gates in one place: calibration
  established **and** metric scale provenance.

Renamed for consistency with the three new cartridges (contract unchanged):
`WorldModelSource` → `WorldBuilderClient`, `UnavailableWorldModelSource` →
`UnavailableWorldBuilderClient`, `ObservableWorldModelSource` →
`WorldBuilderViewModel`.

### 5.2 Experimental CV Lab

`ExperimentalCVModel.swift`. Declares **no experiment, no algorithm, no metric
name**. The module spec lists nineteen candidates and calls the list
"intentionally broad"; a hardcoded subset would make the phone the place the
experiment list is decided.

Two rules from `docs/modules/EXPERIMENTAL-CV.md` are enforced in the type system:

- **provenance is a required field** on `CVMetric`, not an optional with a
  default — "results must distinguish [inference from measurement]", and an
  optional field with a default is a field that gets skipped;
- **`CVMetric.comparison` returns `nil` without both a baseline and a stated
  direction**, and there is no other property that renders a verdict. "Avoid
  declaring an approach 'better' without a measurement", as a compile-time
  property rather than a review comment. `higherIsBetter` is required because
  latency and error improve *downward*, and guessing gets it backwards half the
  time.

`CVTimings` deliberately has **no end-to-end latency field** — it would be
computed across two clocks whose relationship is an open question in
`07-PLATFORM-CONSTRAINTS.md`.

### 5.3 Document Memory

`DocumentMemoryModel.swift`. Three refusals:

- **No OCR on iOS.** `DocumentTextAvailability` reports whether the *Tower*
  extracted text, and `.extracted` carries a **character count, not the text**, so
  a document list is not also a bulk transfer of every document's contents onto
  the phone.
- **No "viewing" anything.** `ObservedDuration` labels read "In view 45s". A test
  asserts the words "viewed", "read", "looked", "watched" and "seen" cannot
  appear.
- **No thumbnail unless it was redacted.**

Retrieval models three answers, not two: `matched(confidence:)`, `notFound`, and
**`noObservation`** — "the memory holds nothing covering that, which is not the
same as it not existing" (Core Principle 3). `DocumentQueryResult.init` coerces a
`matched` result carrying no documents into `notFound`, so a future decoder
cannot produce that combination by accident.

`DocumentQueryOrigin` (`appText` / `externalIntent`) is separate from the query,
so a future Siri intent or wake-word layer submits through the same path. **No
voice input is implemented, required, or assumed.**

The search field is **present and disabled** with the reason underneath. Hiding
it would leave a workspace that cannot show what it is for; leaving it enabled
would let a person type a question and get nothing back, which reads as "I have
no documents about that" — a false statement about their own memory.

### 5.4 Scene Understanding

`SceneUnderstandingModel.swift`. Four refusals, each enforced by a test:

- **No identity.** `SceneEntityKind.person` carries **no payload at all** — no
  label, no attribute, no descriptor — so there is nowhere for identity to be
  added without changing the type. `SceneTrackID` is documented as session-scoped
  and is **never displayed**; rows are labelled positionally ("Person 1"), because
  a stable-looking string beside a person's outline invites a reader to treat it
  as an identity.
- **No gaze.** `.towardCamera` reads "Facing your direction". A test asserts no
  label can contain "look", "watch", "eye", "gaze", "stare", "notice" or
  "see you", at any confidence. `SceneFacing.gazeCaveat` must name the missing
  hardware, and a test asserts it says "no eye tracking".
- **No absence claims.** Counts are derived from the entity list (so a header can
  never disagree with the rows), and `SceneSnapshot.countCaveat` must contain
  "not ruled out" — asserted, because a caveat that only describes the camera
  without disclaiming absence would not do the job.
- **No unlabelled distances.** `ScenePosition.distance` is gated by
  `WorldScaleSemantics` exactly as World Builder's figures are. **Bearing is
  not** gated — an angle needs no depth — and is rendered coarsely ("to your
  left") because a bounding-box centre does not support "37.4° right".

Relation predicates are **opaque Tower strings**, displayed verbatim, with a
required confidence.

---

## 6. Two new module concept seeds — read this before merging

`Glasses/Project_Overview_Steps/docs/modules/DOCUMENT-MEMORY.md` and
`SCENE-UNDERSTANDING.md` were **written by this task**, from the iOS side, so the
two new cartridges could cite a real specification instead of an invented one.

Both are labelled, in their own Status sections and in the catalog comment and in
`IOS-TO-TOWER.md`: **the Tower has not adopted either scope.** Both are `.future`.
Neither is a new ambition:

- Document Memory is `ENVIRONMENTAL-MEMORY.md`'s own stated first version
  ("searchable OCR history") narrowed to documents, with `VISUAL-QA.md`'s reading
  path behind it;
- Scene Understanding is the *live* half of `OBJECT-MEMORY.md`'s
  detector/tracker pipeline, with no persistence layer at all.

**This is the one product decision in this change that is worth putting to
whoever owns the roadmap.** Writing module specs from the iOS side is unusual;
the alternative was inventing spec paths that pointed at nothing, or mapping the
workspaces onto Environmental Memory and Object Memory under names that did not
match what the screens do. Both alternatives seemed worse. If the roadmap
prefers to implement the parent modules whole, these two iOS surfaces should be
folded in rather than kept alongside — that is stated in both documents.

---

## 7. Runtime ownership — what was preserved and how it is checked

Unchanged: one `ProjectManager`, created in exactly one place; one
`GlassesConnection`; one `TowerClient`; one camera stream; no per-workspace
connection manager; no view below `ContentView` constructs anything that talks to
DAT or the socket.

Every cartridge view model:

- holds **no** `GlassesConnection`, **no** `TowerClient`, **no** socket, **no**
  DAT reference;
- has **no** `deinit`;
- receives connectivity as a `Bool` parameter.

So losing one when a cartridge is deselected loses nothing real. The rule from
Product Shell V2 still stands: **anything that must outlive the workspace belongs
on `ProjectManager`, not in a view's `@StateObject`.**

`ProjectManager`'s `objectWillChange` fan-in is still absent and nothing new
observes it — the 24 Hz re-render regression it caused is not reintroduced.

Checked by two tests in `TowerClientTests` against a **real socket**:

- `testSwitchingCartridgesDoesNotDisturbALiveStream` — opens a connection, opens
  a stream bracket, builds and discards all four view models three times, then
  asserts the status is still `.online`, the bracket is still open, **nothing new
  reached the wire**, and a frame still gets through afterwards.
- `testCartridgeViewModelsSendNothingToTheTower` — constructs all four against a
  live idle connection, exercises every request surface they expose, and asserts
  the wire stays silent. This is `08-IOS-CARTRIDGE-SHELL.md`'s prohibition on
  inventing a module-selection message, as a test rather than as a promise.

**What these cannot prove:** that the camera is untouched. That needs DAT and no
mock `WearablesInterface` exists. The structural argument stands in for it (no
view model is handed a `GlassesConnection`; `ContentView` passes one to World
Builder only), and it is a Simulator/device check — §12.

---

## 8. Files changed

### New — app target (18)

| File | Purpose |
|---|---|
| `Glasses/Cartridges/Integration/CartridgePhase.swift` | The six truthful phases; `mayCarryData` is the load-bearing property |
| `Glasses/Cartridges/Integration/CartridgeAvailability.swift` | Availability, contract identity, failure |
| `Glasses/Cartridges/Integration/CartridgeClient.swift` | The shared client question + `TowerCapabilities` |
| `Glasses/Cartridges/Integration/Observation.swift` | `WorldScaleSemantics` (moved), provenance, time, observed duration |
| `Glasses/Cartridges/Integration/VisualArtifact.swift` | Redaction and artifact-fetch state |
| `Glasses/Cartridges/Integration/CartridgeClients.swift` | The four clients, owned above the workspaces |
| `Glasses/Views/Components/TowerReachabilityReader.swift` | The only observer of `TowerClient` for the three new workspaces |
| `Glasses/Views/Components/CartridgeStatePanel.swift` | The shared "nothing yet" panel |
| `Glasses/Workspaces/WorldBuilder/WorldBuilderClient.swift` | World Builder seam + view model |
| `Glasses/Workspaces/ExperimentalCV/ExperimentalCVModel.swift` | CV domain types |
| `Glasses/Workspaces/ExperimentalCV/ExperimentalCVClient.swift` | CV seam + view model |
| `Glasses/Workspaces/ExperimentalCV/ExperimentalCVWorkspaceView.swift` | CV workspace |
| `Glasses/Workspaces/DocumentMemory/DocumentMemoryModel.swift` | Document domain types |
| `Glasses/Workspaces/DocumentMemory/DocumentMemoryClient.swift` | Document seam + view model |
| `Glasses/Workspaces/DocumentMemory/DocumentMemoryWorkspaceView.swift` | Document workspace |
| `Glasses/Workspaces/SceneUnderstanding/SceneUnderstandingModel.swift` | Scene domain types |
| `Glasses/Workspaces/SceneUnderstanding/SceneUnderstandingClient.swift` | Scene seam + view model |
| `Glasses/Workspaces/SceneUnderstanding/SceneUnderstandingWorkspaceView.swift` | Scene workspace |

### Modified — app target

- `Glasses/ContentView.swift` — three new switch arms, each wrapped in `TowerReachabilityReader`
- `Glasses/ProjectManager.swift` — owns `CartridgeClients`; nothing else changed
- `Glasses/Cartridges/Cartridge.swift` — `workspace:` on Experimental CV Lab; two new catalog entries
- `Glasses/Workspaces/CartridgeWorkspace.swift` — three cases, `CaseIterable` restored (now used by a test)
- `Glasses/Workspaces/WorldBuilder/WorldModel.swift` — new fields and `.finalizing`; `WorldScaleSemantics` moved out; client/source types moved out
- `Glasses/Workspaces/WorldBuilder/WorldBuilderWorkspaceView.swift` — uses `WorldBuilderViewModel`, passes availability
- `Glasses/Workspaces/WorldBuilder/WorldCanvasView.swift` — availability gate, `.finalizing`, new summary rows

### New — docs

- `docs/agent-handoffs/IOS-TO-TOWER.md` — **the primary deliverable for Tower Claude**
- `docs/agent-handoffs/cartridge-integration-mac-handoff.md` — this file
- `Glasses/Project_Overview_Steps/docs/modules/DOCUMENT-MEMORY.md`
- `Glasses/Project_Overview_Steps/docs/modules/SCENE-UNDERSTANDING.md`

### Modified — docs

- `Glasses/Project_Overview_Steps/docs/08-IOS-CARTRIDGE-SHELL.md` — four workspaces, the client layer, the strengthened test

### Modified — tests

- `GlassesTests/ProductShellTests.swift` — +96 tests
- `GlassesTests/TowerClientTests.swift` — +3 tests

### NOT modified

**`Glasses.xcodeproj/project.pbxproj` was NOT touched.** `Glasses/` is a
filesystem-synchronized group, so the 16 new app sources compile automatically.
`GlassesTests/` is **not** — its files are listed explicitly — so **no new test
file was added**; all new tests were appended to the two existing files. Adding a
test file requires hand-editing `project.pbxproj`, which was judged a worse risk
than two large test files.

`Info.plist` untouched. The multiple-scenes hazard from Product Shell V2 §11 is
**still open and still not fixed** — see §14.

Sender, camera, DAT, `TowerClient` transport, `GlassesConnection`,
`ProjectManager`, `StreamManager`, `SenderMetrics`, `SendWindow`,
`FrameRateGate`, `DeviceHealth`, Developer Tools: **all unchanged.**

---

## 9. Tests

**220 total: 112 pre-existing (Mac-validated at `7508db1`) + 108 new.
EVERY NEW TEST IS UNRUN — NOT RUN ON WINDOWS.**

| File | Base | Now | Added |
|---|---|---|---|
| `ProductShellTests.swift` | 26 | 131 | +105 |
| `TowerClientTests.swift` | 35 | 38 | +3 |
| `SenderPipelineTests.swift` | 51 | 51 | 0 |

New suites in `ProductShellTests.swift`:

- `CartridgeIntegrationTests` — the Tower declares nothing; contract resolution
  and its precedence; explanations; phase invariants; failures always explain
  themselves.
- `CartridgeClientTests` — **table-driven over all four cartridges**: none
  produces Tower data; each explains itself; each answers for exactly its own
  cartridge; every openable cartridge has a client; requests are refused rather
  than silently ignored.
- `CartridgeViewModelTests` — availability outranks client state; refusals are
  surfaced not swallowed; blank queries are not submitted; query routing and
  origin.
- `ArtifactRedactionTests` — only redacted imagery is displayable; unknown is as
  strict as raw; withheld imagery explains itself; redaction survives the fetch.
- `ObservationProvenanceTests`, `ObservationTimeTests`, `ObservedDurationTests` —
  Core Principles 2, 4, 5 and Limitation 8 at the display layer.
- `WorldModelIntegrationTests` — `.finalizing` is work but not live observation;
  every state's phase; metric display needs calibration **and** metric scale;
  geometry representations survive verbatim; path length withheld without metric
  scale; emptiness accounts for the new fields.
- `ExperimentalCVModelTests` — no verdict without a baseline; no verdict without
  a direction; direction is respected; a tie is not a win; missing units omitted.
- `DocumentMemoryModelTests` — the three retrieval answers; a match with no
  documents becomes not-found; confidence survives; untitled is described not
  named.
- `SceneUnderstandingModelTests` — anonymity; the gaze wording rule; derived
  counts; the absence caveat; distance gating; bearing independence.

New in `TowerClientTests.swift`: the two runtime-ownership tests in §7, plus
`testAnOnlineTowerStillDeclaresNoCartridgeContracts`.

### Deliberately not covered

SwiftUI rendering, workspace switching in the view hierarchy, drawer selection
wiring, and anything requiring DAT — no mock `WearablesInterface` exists. Those
are §12–13 checks.

### One existing test was rewritten — read this

`CartridgeWorkspaceTests.testHavingAWorkspaceDoesNotPromoteACartridgesStatus`.

It used to assert two things: that World Builder was still `.future`, **and that
the `.next` cartridge had no workspace**. The second held only because
Experimental CV Lab happened to be the one cartridge with a roadmap position and
no screen — an accident of build order, not the invariant. Experimental CV Lab
has a workspace now, so that line would fail while nothing it protected had gone
wrong.

The invariant it protected is "a screen never changes a roadmap position". It now
pins the **entire** catalog's id→status map against `03-ROADMAP.md`. This is
strictly stronger: it catches drift on any cartridge rather than one, and a
cartridge added without a deliberate status decision fails here rather than
passing silently.

### And one more, mechanically

`WorldModelTests.testStatesWithoutAWorldDoNotClaimOne` lists World Builder's
states, and `WorldModelState.failed` now carries a `CartridgeFailure` instead of
a bare `reason: String` — so the literal in that list changed shape. The
assertion is unchanged. World Builder was the one cartridge of four that could
not distinguish a dropped socket from an undecodable payload from a Tower-reported
module failure, which is the entire point of `CartridgeFailure.Kind`.

**No other pre-existing test was modified.** In particular
`testNoCartridgeClaimsToBeAvailable` and
`testStreamStartSendsExactPayloadOnce` are untouched, and the 51 sender tests are
untouched. **Any regression in the 112 pre-existing tests is a defect in this
change, not a test to update.**

---

## 10. Expected compile risks, ranked

1. **Member-import visibility.** The target enables
   `SWIFT_UPCOMING_FEATURE_MEMBER_IMPORT_VISIBILITY` (verified at
   `project.pbxproj:421`/`:465` by the previous session). Under it, extension
   members resolve only where the defining module is imported. `String(format:)`
   and `Date.formatted(date:time:)` are Foundation extension members, so
   `import Foundation` was added explicitly to all four workspace views and
   `WorldCanvasView` even though they import SwiftUI. **If a new file uses a
   Foundation or DAT member, check its imports first.**
2. **Actor isolation** under `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`. All new
   client protocols and view models are explicitly `@MainActor`; all new domain
   types are nonisolated `Sendable` value types; **all new test classes are
   `@MainActor`**, matching the existing convention. The `CartridgePhaseReporting`
   protocol was deleted specifically because of this.
3. **Non-exhaustive switches** after `WorldModelState` gained `.finalizing`.
   `WorldCanvasView.content` and `WorldCanvasView.unavailableExplanation` were
   updated; the compiler will find any that were not.
4. **`VisualArtifactState.absent`** — originally named `.none`, renamed to avoid
   `Optional` shadowing warnings. If any call site still says `.none`, it will
   fail or warn.
5. **Result builders.** `WorldSummaryView.geometryValue` was extracted
   specifically so no `let` binding sits inside a `@ViewBuilder` — the pattern
   Product Shell V2's review settled on. Watch for others.
6. **Synthesised conformances.** The new value types rely on synthesised
   `Equatable`/`Hashable`; `DocumentQuery` contains a `DateInterval`,
   `WorldPersistenceState` contains an `Int?`.
7. **Test-target `private` types.** `IdleExperimentalCVClient` and
   `RecordingDocumentMemoryClient` are `private` at file scope in
   `ProductShellTests.swift` and used only there.
8. **Combine in the view models.** Four `Set<AnyCancellable>` and four `.sink`s
   are new. Standard, and the same pattern `ProjectManager` already uses — but
   they are the only concurrency-adjacent addition.

### Two candidate risks that were investigated and dismissed

Recorded so the Mac session does not re-derive them.

- **`CartridgeCatalogTests` and `StateDisplayTests` lack `@MainActor`** while
  calling `CartridgeStatus.badge` and `StateDisplay`'s static methods, which are
  MainActor-isolated under `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`. This looks
  like a hard error. **It is not, empirically:** both classes exist unchanged at
  `7508db1` in exactly that form, `project.pbxproj` has not been modified since,
  and the Mac compiled that commit and ran 89/89 green six times. Swift 5 language
  mode is doing the work. Left alone.
- **Hand-written `id` witnesses for `Identifiable`** on `CVMetric`,
  `SceneEntity` and `SceneRelationship` are MainActor-isolated under the same
  setting, while the protocol requirement is nonisolated. `ContentView.Destination`
  (`var id: Int { rawValue }`) is the same shape, pre-existing, and compiles. If
  it does bite, the remedy the codebase already uses elsewhere is `nonisolated
  var id`. Not applied pre-emptively, because a redundant `nonisolated` risks a
  new warning and the bar is no new warnings.

---

## 11. Xcode validation sequence

```bash
git fetch origin
git checkout ios/cartridge-integration
git log --oneline -6
```

1. **Resolve packages.** Confirm `meta-wearables-dat-ios` pins to exactly 0.9.0.
2. **Debug build** (`xcodebuild -scheme Glasses -configuration Debug -sdk iphonesimulator build`).
   Fix compile errors; §10 ranks where they are most likely. The 16 new app
   sources should appear automatically via the synchronized group — **confirm
   they did** before concluding anything about warnings.
3. **Run all tests.** Expect **220**. The **112 pre-existing must still pass** —
   any regression there is a defect in this change.
4. **Release build**
   (`xcodebuild -scheme Glasses -configuration Release -sdk iphoneos build`).
   This is the gate §14 exists for. The three new workspaces contain **no**
   `#if DEBUG` at all and reference no camera symbols, so they should build
   unchanged in Release — that claim is exactly what this step tests.
5. **Compare warnings against `6a2d114`.** The bar is **no new warnings**. The
   send-window handoff records five clean-build warnings at `d9e513d`, unchanged
   through `7508db1`; expect the same five.
6. **Simulator UI smoke test** — §12.
7. **Physical iPhone + Ray-Ban** — §13.

---

## 12. Simulator smoke test

**Object lifetime first.** Watch the console for
`[Glasses][Init] GlassesConnection created`. It must appear **exactly once per
launch**. Then, without relaunching, open every cartridge in turn — World
Builder, Experimental CV Lab, Document Memory, Scene Understanding — return to
Home between each, open and dismiss Connections and Developer Tools, and rotate
the device. **No second init line may appear.** This is the single most important
check in this document.

**Every workspace renders.** Each of the four should show its header and an
honest "nothing yet" panel naming the cartridge. None should show a spinner, a
metric grid, a dash, an empty list styled as data, or any sample content.

**Document Memory's search field** is visible, **disabled**, and carries the
explanation underneath. Typing into it should be impossible; the field must not
accept input and then appear to search.

**Experimental CV Lab** shows no experiment list — not an empty list with a
header implying one, and not greyed-out plausible experiments.

**Scene Understanding** shows no people, no counts, and no entity rows.

**Availability text.** With the Tower **offline**, each workspace should still
say the Tower does not run that cartridge — **not** "Not connected".
Connectivity is not what is missing, and if a workspace blames the connection the
precedence in `CartridgeAvailability.resolve` is wired backwards.

The `.disconnected` phase ("Not connected", `wifi.slash`) exists for a Tower that
*could* serve a cartridge but is unreachable. It is **not reachable today** and
must not appear on any screen — seeing it means a contract was declared
somewhere it should not have been.

**Loaded ≠ active, still.** Selecting any of the three new cartridges must leave
the camera pill reading **Off** and start nothing. Only World Builder and Home
have capture controls at all.

**Wire silence.** With a Tower connected, switch between all five workspaces
repeatedly and confirm in the Tower's own log that **no message** is sent beyond
the ping/pong keepalive. Opening a cartridge sends nothing.

---

## 13. Physical device regression checklist

Everything in Product Shell V2 §18 still applies unchanged. Additionally:

1. **Cartridge switching during a live session.** Start capture from World
   Builder. While streaming, switch to Experimental CV Lab, then Document Memory,
   then Scene Understanding, then Home, then back to World Builder. Throughout:
   - the camera pill must stay **On**;
   - frames must keep flowing (Developer Tools' sender rows keep moving);
   - the Tower must receive no `stream_stop` and no reconnect;
   - no second `GlassesConnection created` line;
   - the viewfinder must still be live when you return to World Builder.

   **This is the check the two new socket tests approximate but cannot make** —
   they cover the Tower half, not the camera half.
2. **Sender rate.** Compare the achieved fps in Developer Tools against a run on
   `6a2d114` with the same Tower and network. The bar is **no regression**. Three
   new SwiftUI subtrees exist, but only one is mounted at a time and none
   observes `ProjectManager`, so no change is expected — which is exactly why a
   change would be worth investigating rather than accepting.
3. **Release build on device.** Confirm the three new workspaces render (they
   have no camera-dependent regions) and that Home and World Builder degrade as
   Product Shell V2 §16 describes.
4. **Rotation and iPad.** If a second scene is opened, expect the multiple-scenes
   hazard below.

---

## 14. Known limitations and open hazards

**Carried forward, not fixed:**

- **Multiple scenes.** `TARGETED_DEVICE_FAMILY` is `"1,2,7"`; a second window
  means a second `ContentView`, a second `ProjectManager`, a second
  `GlassesConnection` and a second Tower socket. Product Shell V2 §11 has the
  full analysis and the build-setting fix (set
  `INFOPLIST_KEY_UIApplicationSceneManifest_Generation` to `NO` for both
  `iphoneos*` and `iphonesimulator*`, add the manifest to `Info.plist`, then
  **verify against the built product** with `plutil -extract`). Still needs a
  real build; still untouched here because it edits `project.pbxproj`.
- **The camera path is DEBUG-only**, so "product shell" still describes a screen
  that only fully exists in Debug builds. Product Shell V2 flagged this as
  deserving to be the next task; it still is, and adding three Release-safe
  workspaces has made the asymmetry more visible rather than less.
- The latent `GlassesConnection` bugs listed in Product Shell V2 §19 are all
  still unfixed and still out of scope.

**New to this change:**

- **Every state but `.unsupported` is unreachable** in all four cartridges. They
  exist so each workspace is written once against the full lifecycle. Unreachable
  **by construction** — the only clients that exist return `.unsupported` — not by
  convention.
- **No cross-launch persistence** of the selected cartridge, unchanged and
  deliberate.
- **No dataset-recording surface** for Experimental CV Lab, deliberately: a
  recording indicator the Tower cannot drive would be the worst kind of privacy
  control.
- **`ProductShellTests.testTheTowerDeclaresNoCartridgeContracts` will fail the
  day a real contract lands.** That is intentional. It is the review trigger, not
  a nuisance.

---

## 15. What to do when a Tower contract arrives

The change is bounded and identical for every cartridge:

1. Add the contract identifier to `TowerCapabilities.declared` **and**
   `TowerCapabilities.supported`.
2. Write a Tower-backed client conforming to that cartridge's existing client
   protocol, mapping the wire payload onto the existing domain types.
3. Pass it to the view model in the workspace view.
   **No view changes** — every view already renders the full lifecycle.
4. Add decode tests including the negative ones: a malformed payload must produce
   `CartridgeFailure(kind: .undecodableResponse)`, never a partially populated
   snapshot.

If the real contract does not fit that shape, `IOS-TO-TOWER.md` guessed wrong
somewhere and that is worth saying out loud rather than working around.

Specific reconciliation points, per cartridge:

| Cartridge | Where the real contract lands |
|---|---|
| World Builder | Map onto `WorldSnapshot`; put the Tower's representation name into `WorldGeometryReport.representation`; **only then** add a renderer, chosen for the representation the Tower actually picked |
| Experimental CV Lab | Populate `.idle(available:)` from the Tower's declared experiments; map results onto `CVMetric` with **real** provenance |
| Document Memory | Map onto `RememberedDocument`; make sure `noObservation` is distinguishable from `notFound` at the decode site, because the wire is where that distinction is most likely to be lost |
| Scene Understanding | Map onto `SceneEntity`; **reject any durable person identifier at the decode boundary** rather than storing and ignoring it |

---

## 16. Merge / revise / revert criteria

**Merge** when: Debug and Release build clean; all 220 tests pass; no new
warnings against `6a2d114`; the Simulator smoke test in §12 passes; and the
physical cartridge-switching check in §13.1 shows an uninterrupted stream and a
single `GlassesConnection created` line.

**Revise** if: compile errors are confined to imports, isolation annotations, or
switch exhaustiveness (all expected, all local); or a test fails in a way that
reveals a wrong assertion rather than wrong behaviour — in which case fix the
assertion and say so, but **not** for any of the 112 pre-existing tests.

**Revert** if: the sender rate regresses on hardware and the cause is traced to
this change; or a second `GlassesConnection` appears on cartridge switching; or
the camera stops on a workspace change. Those are the invariants this change
exists to preserve, and none of them is worth trading for four screens that
currently say "nothing yet".

Revert is cheap: the branch touches no runtime file. Dropping the three new
workspace arms from `ContentView` and the two new catalog entries restores
Product Shell V2 behaviour exactly.

---

## 17. Independent review, and what it changed

Three independent agents were run against the finished tree: one on Swift/SwiftUI
compile risk, one adversarial on truthfulness and privacy, one on architecture
and object lifetime. All three were given the governing documents rather than a
summary of them.

The truthfulness review is the one worth reading in full if any of this is being
re-derived. Its finding was that **the epistemic architecture held and the
failures were almost all at the last inch** — strings a user actually reads, and
boolean gates that stopped good types from reaching the screen.

### Fixed — the privacy and truthfulness findings

**BLOCKER.** `UnavailableSceneUnderstandingClient.reason` ended "…and **stores
nothing** about anyone the glasses pass." That is a privacy assurance about
bystanders, on the one screen whose subject is bystanders, and **this app cannot
know whether it is true**: it has no channel through which to inspect what the
Tower writes to disk, and Limitation 11 describes the current transport as
unauthenticated and unencrypted. Rewritten to say only what the protocol
establishes — the Tower's only reply is a brightness figure, so nothing about
anyone reaches this app. A test now forbids the phrase class outright across all
four clients, because a length check passed the original: it was long, fluent,
and wrong.

**MAJOR.** Document Memory made the same storage claim, plus a technically-true,
materially-false one: "no document *text* has ever left this app's frame
pipeline" is true only because no OCR runs — while the **frames containing those
documents leave in full**. On a screen about documents a reader takes that as
reassurance about the documents. Rewritten to say plainly what leaves.

**MAJOR.** `RedactionState.redacted.explanation` said "People in this image were
obscured before it was stored" — telling the user what redaction *did*, when no
Tower contract defines it. That converts an opaque flag into a checkable
guarantee, which the same file's own doc comment calls worse than no guarantee.
Now attributes the claim to the producer instead of describing the result, and a
test asserts the attribution survives future copy edits.

**MAJOR.** `ObservationProvenance.unknown.caveat` was dead. Both call sites gated
on `... .isInference`, which is `false` for `.unknown`, so a value whose
provenance the Tower never stated rendered bare — indistinguishable from a
measurement, which is Rule 16 exactly backwards. `caveat` is already `nil` for
`.measured`; the extra gate is removed from both.

**MAJOR.** "Beside you, left" past 60° and "Behind you, right" past 120° told the
wearer the system had detected someone behind them. The glasses see a forward
cone. Vocabulary capped at `Ahead` / `To your left` / `To your right` / `At the
edge of view`. The old test *enshrined* the 150° case; the new one sweeps −180°
to 180° and fails on any description claiming an observation outside the cone.

**MAJOR.** `String(format: "%.1f m", …)` in two places invented **metres**.
`inferredMetric` says a figure is metric *in kind*, not what unit it counts in —
and `CVMetric.unit` had already taken the correct position ("never assumed") two
files away. `ReportedFigure` now renders the Tower's unit or a bare number, and
`WorldTrajectoryReport` and `ScenePosition` carry a unit string.

**MAJOR.** `DocumentQueryResult.init` silently rewrote a "matched, no documents"
answer to `.notFound` — a definite negative statement about the user's own memory
manufactured from a decode failure, with the Tower's confidence discarded. It now
throws `CartridgeFailure(kind: .undecodableResponse)`. The safe direction from a
broken payload is a failure, never a stronger claim than the Tower made.

**MAJOR.** Local refusals were thrown as `.towerReportedFailure` when the Tower
had reported nothing and there may have been no socket open. New
`CartridgeFailure.Kind.notSupported`, used at all four sites, asserted in tests.

**MAJOR.** The bearing sign convention was presumed silently while the file's own
header claimed no coordinate convention. It is now **declared** — positive to the
right, decode site converts into it — the header corrected, and
`IOS-TO-TOWER.md` §4.3 asks the Tower to state its own. This is deliberately
different from the geometry and pose cases, where a wrong guess is unrecoverable
and no convention is offered at all.

**MAJOR.** Scene rows showed `In view 12s` beside a person with no attention
caveat, while `ObservedDuration.attentionCaveat` documents itself as owed by
*any* surface showing it — and it was rendered on Document Memory only. Added.
Confidences rendered as a bare `70%` are now labelled.

**MINOR, fixed:** a stale scene timestamped without a date (reads as today, which
is the whole failure `.lastKnown` exists to prevent); `RedactionState.rawEphemeral`
promising "It is not stored" (a guarantee the enum cannot enforce about the
Tower) now says what *this app* does; "what is around you" in two places, now
"what the camera can see"; `WorldSnapshot.revision` changed from `Int?` to an
opaque `String?`, since inequality is the entire requirement and an integer
presumed a monotonic counter; a doc comment claiming a test enforced anonymity
when the guarantee is structural.

**Pre-existing, fixed while the drawer was open:** the Visual Q&A catalog
summary read "Answers questions about what **you are looking at**" — squarely
Limitation 8, and shipping in the drawer today.

### Fixed — the architecture findings

**MAJOR.** The three new workspaces observed `TowerClient` for a value that
provably could not change, re-rendering at reply rate on the sender's actor.
`TowerReachabilityReader` — §3.3.

**MAJOR.** `WorldCanvasView` rebuilt its explanation string inside `body`, on the
one workspace whose body runs at the 24 Hz capture rate. The composition moved to
the view model and the shared layer; the view takes a `String`.

**MAJOR.** No client update could reach a view model — `stateUpdates`, §3.5.

**MAJOR.** The client construction site was the workspace `@StateObject`, which
is where §11 of the Product Shell V2 handoff says a real one must not live.
`CartridgeClients` on `ProjectManager`, and no default arguments — §3.4.

**MINOR.** An unreachable Tower rendered with the same headline and glyph as a
missing capability, so the distinction lived only in the prose. New
`CartridgePhase.disconnected`, "Not connected" and `wifi.slash`.

**MINOR.** The four identical explanation joins collapsed into
`CartridgeAvailability.explanation(cartridgeName:clientReason:)`; the two
identical catch ladders into `CartridgeFailure.wrapping(_:)`.

**MINOR.** `WorldModelState.failed(reason: String)` → `.failed(CartridgeFailure)`,
matching the other three.

**MINOR.** Dead code deleted: `CartridgePhase.isLive` (documented as gating every
live affordance; gated nothing) and `RedactionState.badge` (no view draws an
artifact, so there is no badge). `CartridgePhaseReporting` had already been
deleted in self-review for the same reason.

### Fixed — weak tests the reviews caught

Six assertions were green on guarantees the code did not deliver, or could not
fail for the reason they were named:

- an explanation checked by **length**, passing the BLOCKER above → now checks
  the claim;
- `if case .idle` over a `let` constant `.unsupported` → could never match;
- `SceneEntityKind.person == SceneEntityKind.person` → a tautology that would
  survive `case identifiedPerson(name:)` being added beside it;
- `showsProgress == (phase == .waiting)` → the implementation asserting itself;
- the 150° bearing case → enshrined rather than caught;
- badge-set checks that cannot fail while `CartridgeStatus` has three cases →
  a new test asserts the case set via an exhaustive switch, so a `.available`
  case breaks the **build** rather than a test. The two pre-existing badge tests
  are left untouched.

Also added: a test that `docs/modules/` spec paths are the exact set that exists,
since the pre-existing one asserted only the prefix and would pass for a file
that is not there.

### Not taken

**Deleting the contract-negotiation layer.** The architecture review argued that
`CartridgeContract`, `TowerCapabilities.supported` and `resolve` have zero
production callers, that only `.noContract` is producible, and that choosing an
equality-matched opaque token is *still a choice about a protocol that does not
exist* — roughly 90 lines and 8 tests for nothing the app does.

That is a fair reading and it was overruled deliberately. This task's brief names
"Tower contract version mismatch produces explicit unsupported state" as a
required invariant, and the three unavailable states it distinguishes call for
genuinely different user responses — wait for the Tower, update the app,
reconnect. An equality-compared token is the smallest commitment that supports
that: it assumes only that the Tower can *name* what it offers, which any
contract scheme must do. **It is worth re-examining if the Tower's real
capability model turns out not to be per-cartridge or not to be named.**

**Adding `.equatable()` to the workspace views.** Suggested as a re-render fix.
Not applied: it is not certain whether `EquatableView` also gates
`@StateObject`-driven invalidation, and a workspace that silently stopped
updating when its view model changed would be a worse bug than the one being
fixed. Removing the dead dependency achieves the same thing without the
uncertainty.

**The four `phase(isTowerReachable:)` one-liners.** Left duplicated. Removing
them needs a protocol over four unrelated state types with an `associatedtype`
or an existential — the plugin framework this design refuses, bought for four
lines.

### Open, and worth putting to the roadmap owner

The truthfulness review raised Rule 10 (*"do not implement future roadmap
features while completing an earlier milestone"*): four workspaces, four client
protocols, two module specs and a shared integration layer now exist for a
runtime at V0.8-not-started, with `.unsupported` the only reachable state on
every screen. Product Shell V2 §20 recorded a version of this argument and
overruled it on brief; the scope has since quadrupled, also on brief. **It is a
roadmap-owner question, not a code defect**, and it belongs beside the module-seed
question in §6.

---

**This implementation was produced on Windows without Xcode and has NOT yet been
compiler-, Simulator-, or physical-device-validated.**
