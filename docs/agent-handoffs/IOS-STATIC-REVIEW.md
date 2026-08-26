# iOS static review — `integration/world-builder-lifecycle-v1`

> **iOS ENTRY POINT IS `docs/agent-handoffs/IOS-EXECUTION-PLAN.md`.**
> This file is **REFERENCE**: deeper detail, still accurate except where
> the plan says otherwise. Read the plan first — it says what to do now,
> what is already settled, and what the Tower has measured and refused.
> Where the two disagree, the plan wins.

Compiler's-eye read of the 18 changed Swift files (4,383 lines) plus the
unchanged files they depend on for types and signatures. **No Swift toolchain
was available**: nothing here was compiled. Everything below is either a
grep-checkable claim (CERTAIN) or a reasoned inference with the build setting
it depends on named (SUSPECTED).

**Build settings that matter** (`ios/Glasses.xcodeproj/project.pbxproj`):

| Setting | Glasses (app) | GlassesTests |
|---|---|---|
| `SWIFT_VERSION` | 5.0 | 5.0 |
| `SWIFT_DEFAULT_ACTOR_ISOLATION` | `MainActor` (lines 427, 471) | **not set** |
| `SWIFT_APPROACHABLE_CONCURRENCY` | YES | not set |
| `SWIFT_UPCOMING_FEATURE_MEMBER_IMPORT_VISIBILITY` | YES (429, 473) | **not set** |
| `SWIFT_STRICT_CONCURRENCY` | not set (⇒ `minimal`) | not set |
| `IPHONEOS_DEPLOYMENT_TARGET` | 26.5 | 26.5 |

Swift 5 language mode with minimal strict concurrency means most Sendable /
global-actor-conversion complaints are **warnings**, not errors. That single
fact is what keeps this report short.

---

## CERTAIN

### C1. Empty collection literals in an `Any` value position
`ios/GlassesTests/WorldGeometryTests.swift:131` and `:145`

```swift
let json: [String: Any] = [
    ...
    "points": [], "points_sent": 0, "points_total": 0,   // :131
]
let json: [String: Any] = [
    ...
    "poses": [], "points": [[1.0, 2.0, 3.0]],            // :145
]
```

The value slot of a `[String: Any]` literal gives the element expression a
contextual type of `Any`. `Any` is not `ExpressibleByArrayLiteral`, so the
literal's element type is a free type variable with nothing to default it to.
Expected diagnostic: **`error: empty collection literal requires an explicit
type`**.

Minimal fix — annotate at the literal, matching the type the decoder casts to:

```swift
"points": [[Double]](),          // :131
"poses":  [[String: Any]](),     // :145
```

(`[] as [[Double]]` works equally well.) These are the only two occurrences in
the branch, and there is **no precedent for the construct on `main`** — every
other collection literal in an `Any` position is non-empty or explicitly typed.
The annotation is correct whether or not the diagnostic fires, so it is cheap to
apply.

Confidence: high. This is the one finding a compiler could contradict; if it
compiles anyway, the fix costs nothing.

---

## SUSPECTED

### S1. Five new test classes are not `@MainActor`, in a target that does not default to it
`ios/GlassesTests/WorldGeometryTests.swift:7, 155, 198, 330, 380`

`WorldGeometryDecoderTests`, `WorldGeometryStoreTests`, `WorldFragmentsModelTests`,
`WorldBuilderContractAdoptionTests` and `WorldGeometryCoordinatesTests` are plain
`XCTestCase` subclasses. The **app** module compiles with
`SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`; the **test** target does not. If
that setting isolates the app's unannotated types (`WorldGeometryDecoder`,
`WorldBounds`, `WorldSegmentSummary`, `WorldFragmentsModel`,
`WorldBuilderResultDecoder`, `TowerCapabilities`), then every call from these
five classes is a MainActor call from a nonisolated synchronous context — an
error even in Swift 5 mode.

The sharpest instance is a **stored-property default**, which no amount of
`await` can fix:

```swift
// WorldGeometryTests.swift:213, inside non-@MainActor WorldFragmentsModelTests
private let box = WorldBounds(json: ["min": [-1.0, 0.0, -1.0],
                                     "max": [1.0, 2.0, 1.0]])!
```

**Why this is not CERTAIN.** Two pre-existing non-`@MainActor` test classes on
`main` do the same thing and evidently compile —
`ProductShellTests.swift:34 CartridgeCatalogTests` (`Cartridge.catalog`,
`cartridge.status.badge`) and `:75 StateDisplayTests`
(`StateDisplay.cameraPermission(_:)`, `TowerStatus.failed(_:)`). Neither
`Cartridge` nor `StateDisplay` is `Sendable` or `nonisolated`. So either the
default-isolation inference does not reach these declarations, or it does not
produce errors under Swift 5 mode. Either way, **the new code follows existing
precedent and introduces no new class of risk.**

If the Mac build does complain, the fix is one line per class: add `@MainActor`
above each of the five, matching the 20 pre-existing test classes that already
carry it. `WorldGeometryStoreTests` needs nothing further — its methods are
`async` and its `await store.…` calls are actor calls, correct either way.

Settled by: the first `xcodebuild` of the test target.

### S2. `snapshot ?? NSNull()` in an `Any` slot
`ios/GlassesTests/WorldBuilderIntegrationTests.swift:35`

```swift
"world_snapshot": snapshot ?? NSNull(),   // snapshot: [String: Any]?
```

`??` is `<T>(T?, @autoclosure () throws -> T) -> T`. The solver's first
candidate for `T` is `[String: Any]` (from the left operand), under which
`NSNull()` does not convert. It has to backtrack to `T == Any`, which requires
the covariant `Optional<[String: Any]> → Optional<Any>` conversion. That
conversion exists and this is a common JSON-building idiom, so I expect it to
solve — but it is exactly the shape that yields `cannot convert value of type
'NSNull' to expected argument type '[String : Any]'` when the solver commits
early.

Minimal fix if it does: `(snapshot as Any?) ?? NSNull()`.

### S3. `WorldFragmentsView.swift` imports only SwiftUI but calls CoreGraphics initializers
`ios/Glasses/Workspaces/WorldBuilder/WorldFragmentsView.swift:6, 77–88, 109`

`CGSize`, `CGPoint(x:y:)` and `CGRect(x:y:width:height:)` are used with `import
SwiftUI` alone. This is the **only** file in the app target that imports SwiftUI
without also importing Foundation, UIKit or CoreGraphics while calling a `CG*`
initializer, and the app target sets
`SWIFT_UPCOMING_FEATURE_MEMBER_IMPORT_VISIBILITY = YES` — the same feature the
author already had to work around in `WorldBuilderWorkspaceView.swift:9–16` with
an explicit `import MWDATCamera`.

**Counter-evidence, and why confidence is low:** the pre-existing
`WorldCanvasView.swift` (Foundation + SwiftUI only) uses
`Color(.secondarySystemGroupedBackground)` — a *UIKit* member — and compiles. So
Apple SDK modules appear to reach through and only the SPM module actually bit.
Probably fine.

Minimal fix if it fires: add `import CoreGraphics` (or `import Foundation`,
matching `WorldCanvasView.swift`).

### S4. Warnings-only, listed so they are not mistaken for errors
- `WorldGeometryTests.swift:497–499` — `private static var routes / paths` on
  `StubbedGeometryProtocol` are mutable statics. Warning in Swift 5, error in
  Swift 6. Guarded by an `NSLock`, so behaviourally sound.
- `recorder.all.compactMap(decode)` / `compactMap(self.decode)` in both test
  files converts a `@MainActor` function reference to a nonisolated one ("loses
  global actor"). **Pre-existing on `main`** at 12 sites in
  `TowerClientTests.swift`, so at most a warning here.
- Heterogeneous dictionary literals (`WorldGeometryTests.swift:12–36`) may draw
  "heterogeneous collection literal could only be inferred to `[String : Any]`".
  Warning.

---

## Categories that are clean

**1. Type / signature mismatches across files — clean.** Every cross-file call
site was checked against its declaration:

- `TowerCapabilities.availability(for:declaredBy:isTowerReachable:)`,
  `declaredContract(for:in:)`, `supported`, `towerCartridgeNames` — all exist
  with the labels used by `TowerWorldBuilderClient.swift:429–433` and
  `ProductShellTests.swift`.
- `TowerClient.cartridgeResults`, `.cartridgeDeclaration`,
  `.subscribeToResults(cartridge:resultType:contract:)`,
  `.requestCartridgeDeclaration()`, `.unsubscribeFromResults(subscriptionID:)`
  — all declared, all used with matching labels.
- `TowerCartridgeDeclaration.offer(forTowerCartridge:)`,
  `TowerCartridgeDeclaration(envelopeContract:offers:)`,
  `TowerCartridgeOffer(json:)`, `CartridgeSubscriptionAck(json:)`,
  `CartridgeResultEnvelope(json:)`, `CartridgeResultError(json:)` — all present.
- `CartridgeResultEvent` pattern matches in `TowerWorldBuilderClient.handle(_:)`
  cover all five cases; `.unsubscribed(let id)` correctly omits the
  `subscriptionID:` label, which is legal in a pattern.
- `CartridgePhase.disconnected` / `.mayCarryData` / `.showsProgress`,
  `ReportedFigure.format(_:unit:)`, `WorldScaleSemantics.isEstimate /
  .explanation / .displayName`,
  `CartridgeStatePanel(title:phase:explanation:futureDescription:)`,
  `SectionLabel`, `HelperText`, `ViewfinderCard`,
  `ScriptedWearables(permissionResults:)`, `GlassesConnection(wearables:)` — all
  exist as used.
- `ProjectManager.init` accepts `glassesConnection:` alone
  (`WorldBuilderIntegrationTests.swift:978`); every other parameter defaults.
- `WorldBuilderWorkspaceView.init(glasses:tower:client:)` is **unchanged** on
  this branch, so `ContentView.swift:145` — which is not in the diff — still
  matches.
- `MessageRecorder` was correctly promoted from `private final class` to
  `final class` (`TowerClientTests.swift:1714`) for the cross-file use in
  `WorldBuilderIntegrationTests.swift`.
- No duplicate type names across either target.

**2. Initializer availability — clean, and deliberately so.** Exactly one struct
in the new code declares an `init` in its body: `WorldBounds`
(`WorldGeometry.swift:86`), which therefore has **no memberwise initializer**.
It is never memberwise-constructed — all four construction sites
(`WorldGeometry.swift:142`, `WorldGeometryTests.swift:213, 304, 306`) use
`WorldBounds(json:)`. Every other JSON initializer (`WorldPoseConvention`,
`WorldSegmentSummary`, `WorldPose`) is deliberately placed in an `extension` so
the memberwise init survives, and each memberwise call site matches declaration
order label-for-label:

| Type | Memberwise call site | Order |
|---|---|---|
| `WorldSegmentSummary` (10 params) | `WorldGeometryTests.swift:204`, `:288` | matches |
| `WorldSegmentChunk` (8) | `WorldGeometry.swift:266`, `WorldGeometryTests.swift:158` | matches |
| `WorldGeometryManifest` (6) | `WorldGeometry.swift:235` | matches |
| `WorldGeometryCoordinates` (3) | `TowerWorldBuilderClient.swift:186` | matches |
| `WorldFragmentsModel` (`let segments`, `var isCurrent = true`) | 6 sites | matches (default supplied) |
| `WorldGeometryClient` (`baseURL`, `session`, both defaulted) | `WorldGeometryTests.swift:603` | matches |
| `WorldCanvasView` (3 `let` + 3 defaulted `var`) | `WorldBuilderWorkspaceView.swift:109`, `WorldCanvasView.swift:326` | matches |

**3. Optionality and `Codable` — clean, and the wire contract matches field for
field.** Nothing here uses `Codable`; decoding is `[String: Any]` +
`JSONSerialization`, so there is no `CodingKeys` surface to get wrong. The Swift
decoders were checked against `docs/contracts/WORLD-BUILDER-GEOMETRY.md` **and
against the Tower producer** (`tower/tower/results/world_builder_geometry.py`,
`tower/tower/world_builder/schema.py:41`,
`tower/tower/routes/geometry.py:33,45`,
`tower/tower/results/world_builder.py:737,1058,1306`):

- All nine `pose_convention` keys the Tower emits are read; the five compared in
  `matchesThisBuild` (`WorldGeometry.swift:41–47`) match the Tower's
  `POSE_CONVENTION` values exactly — `T_world_camera` / `wxyz` / `right` /
  `opencv_x_right_y_down_z_forward` / `world`. `up_axis` is excluded, as §5
  rule 1 requires.
- Every field the Swift `guard`s on is non-nullable on the wire. Every field the
  wire can null (`bounds`, `transform_to_world`, `dominant_degeneracy`,
  `rotation`, `translation`, `scale.meters_per_unit`, `geometry.revision`) is
  either optional in Swift or not read at all. **No non-optional Swift property
  is fed by a nullable wire field.**
- `WorldBuilderResultDecoder.geometryCoordinates` reads
  `world_snapshot.world_id`, `session.session_id` and `geometry.revision` — all
  three exist at exactly those paths in the Tower payload, and
  `geometry.revision` is `None` precisely when `_geometry_unavailable` fires,
  which the Swift correctly reads as "no address, do not fetch".
- Routes are mounted with no prefix (`tower/tower/main.py:199`), so
  `WorldGeometryClient`'s `baseURL + "worlds/{id}/geometry/manifest"` is right.
- `keyframe_id` is `str` on the Tower (`records.py:421`), matching the Swift
  `as? String` guard — a mismatch there would have nil'd every pose and blanked
  every tile.
- Integer-valued JSON numbers (`0` in a points triple, bounds components) bridge
  through `NSNumber` to `Double`, so `as? [[Double]]` and `as? [Double]` hold.

Two **runtime-only** observations, neither a decode failure:

- `WorldSegmentChunk` does not carry `current`, which §4 says "rides on both
  payloads on purpose … a client that holds a cached chunk and never re-reads
  the manifest would otherwise have no way to know". iOS is safe by a different
  route — `WorldBuilderViewModel.geometryDidChange` always re-fetches the
  manifest before publishing, and `WorldFragmentsModel.isCurrent` comes from
  there — but the chunk's own flag is discarded, so that safety is incidental
  rather than structural.
- `WorldPose.degeneracy` is a non-optional `String` defaulting to `""` for a
  wire `null` (`WorldGeometry.swift:193`), conflating "no reason recorded" with
  "empty reason". Nothing reads it today.

**4. Concurrency — no errors found beyond S1/S4.** `TowerWorldBuilderClient`,
`WorldBuilderViewModel`, `TowerClient`, `CartridgeClients` and both client
protocols are `@MainActor`; `WorldGeometryStore` is an `actor` and every call to
it is `await`ed. `Task { [weak self] in await self?.geometryDidChange(…) }`
(`WorldBuilderClient.swift:260`) inherits MainActor via `Task`'s
`@_inheritActorContext`, and `weak self` on a MainActor class is a legal Sendable
capture. The nested `Task { @MainActor [weak self] in … }` inside the
`URLSessionWebSocketTask.send` completion (`TowerClient.swift:778`) matches three
pre-existing sites in the same file. `MockTowerServer.onText` is
`(@Sendable (String) -> Void)?`, so the closure assigned at
`WorldBuilderIntegrationTests.swift:472` is `@Sendable` and does **not** inherit
MainActor — everything it captures (`MockTowerServer`, `MessageRecorder`, both
`@unchecked Sendable`, plus value types) is Sendable. `cartridgeResults` is
published from `TowerClient.handleInboundMessage`, which is already MainActor, so
the un-`receive(on:)`'d sink in `TowerWorldBuilderClient.init` is on the right
actor.

**5. Test-target reachability — clean.** Both new test files carry `@testable
import Glasses`, and both are registered in the test target's Sources phase:
`project.pbxproj:255` (`WorldBuilderIntegrationTests.swift`) and `:256`
(`WorldGeometryTests.swift`), with matching `PBXFileReference` entries at `:33`
and `:34`. The app target uses a `PBXFileSystemSynchronizedRootGroup`
(`project.pbxproj:54–63`), so the eight new/changed app sources are picked up
automatically and need no project edit. `MessageRecorder` and `ScriptedWearables`
are `internal` and reachable across test files.

**6. Availability / API surface — clean.** Deployment target is 26.5 on every
target. `Canvas`, `LazyVGrid`, `GridItem(.adaptive:)`, `#Preview`,
`.foregroundStyle`, `.background(_:in:)` and `URLSession.data(from:)` all require
far less. Nothing in the diff is newer than the floor.

---

## Behavioural read (not compile issues)

The resubscribe-budget arithmetic in
`testAClosedSubscriptionIsRetriedAndThenReportedRatherThanLooping` is right:
1 initial subscribe + 3 budgeted retries = the asserted 4, and errors 5 and 6
land on an already-`.failed` state. The lifecycle test's expected phase sequence
`[.waiting, .live, .live, .live, .settled]` matches `WorldModelState.phase` for
`awaitingFirstUpdate → receiving → receiving → finalizing → finalized`. The
retry tests' marker arithmetic (`lastGeometryRevision` cleared on manifest
failure and on any segment failure, each clear guarded against a newer in-flight
fetch) is self-consistent, and
`testASucceededFetchIsNotRepeatedUnderTheSameRevision` is a genuine negative
control rather than a restatement.

`WorldGeometryStore.hashesMissing(from:)` is exercised only by tests — no
production caller. Harmless, but it is API that does not yet carry weight.

`testTheAppGraphOwnsOneTowerBackedWorldBuilderClient`
(`WorldBuilderIntegrationTests.swift:977`) constructs a real `ProjectManager`,
which constructs a real `TowerClient(autoReconnect: true)`. It never connects, so
nothing should reach the network — but it is the one test in the suite that
instantiates the production graph, and worth watching for cross-test
interference on the first run.

---

## Verdict

**Close to compiling.** One likely-hard error (C1), in test code, with a two-line
fix. Everything structural — the memberwise-initializer trap that has bitten this
codebase before, the cross-file signatures, the wire contract, the project
registration — is correct, and visibly correct *on purpose*: the JSON
initializers sit in extensions with comments explaining why, and the one struct
that does declare an in-body `init` is never memberwise-constructed. The wire
side was checked against the Tower's actual producer, not only the contract
document, and matches field for field.

The residual risk is concentrated in one place: whether
`SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` on the app target forces `@MainActor`
onto the five new un-annotated test classes (S1). That is the finding most likely
to produce a wall of errors — and also the one with the strongest
counter-evidence on `main`, and the cheapest fix if it fires.

---

## Controller verification, 2026-08-26

Checked by the controller rather than accepted from the report.

**CERTAIN #1 — confirmed and FIXED** (`153792c`). The distinction the
report drew is the real one: every empty literal on `main` sits in a
*typed* slot (`accessibilityAddTraits` takes an OptionSet, `supported:`
a typed array), so Swift infers the element type. The two new ones sit
in `[String: Any]` value slots, where nothing constrains it.

**SUSPECTED #3 — applied** (`153792c`), as a type annotation only. It is
semantically identical at runtime.

**SUSPECTED #2 (`@MainActor`) — deliberately NOT applied.** The report
supplied its own counter-evidence: non-`@MainActor` test classes on
`main` do the same thing and compile, so the test target does not
inherit the app target's `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`.
Adding the annotation would change actor isolation semantics on a guess,
with no compiler to check it. **If `xcodebuild` does raise isolation
errors here, the one-line-per-class fix in the report above is correct** —
apply it then, not now.

**Runtime note on `WorldPose.degeneracy` — closed, benign.** The report
flagged `null -> ""`. Traced to the producer: `records.py:557` types the
field `degeneracy: str = DEGENERACY_NONE`, and `schema.py:67` defines
`DEGENERACY_NONE = ""`. Tower therefore never emits `null` for it, and
the sentinel for "no degeneracy" **is** the empty string, so Swift's
`?? ""` lands on the same value. No `null`-versus-empty conflation, and
no conflict with the project's absent-is-never-zero rule. `dominant_degeneracy`
is separately and correctly optional on both sides.

---

## Build settings, read directly — 2026-08-26

Two flagged risks are retired by the project file rather than by opinion.
Read off `XCBuildConfiguration` blocks in `ios/Glasses.xcodeproj/project.pbxproj`:

| target | `SWIFT_VERSION` | `SWIFT_DEFAULT_ACTOR_ISOLATION` |
|---|---|---|
| `com.tristanvarner.Glasses` (app) | **5.0** | **MainActor** |
| `com.tristanvarner.GlassesTests` | **5.0** | **none** |

**1. The `@MainActor` finding does not fire, and the refusal above was
right.** The test target does not set `SWIFT_DEFAULT_ACTOR_ISOLATION` at
all, so it does not inherit the app target's MainActor default. This is
now settled from build settings, not merely from the precedent of
non-annotated classes on `main`.

**2. The `URLProtocol` stubs' mutable `static var` state is not a compile
error.** It would be one under Swift 6 language mode — *"not
concurrency-safe because it is nonisolated global shared mutable state"*
— but both targets are **Swift 5.0**, and `SWIFT_STRICT_CONCURRENCY` is
not set anywhere in the project, so checking is `minimal` and this is at
most a warning. This applies to both `StubbedGeometryProtocol`
(`WorldGeometryTests.swift`) and `ObjectMemoryStubProtocol`
(`ObjectMemoryTests.swift`), and it retires the risk named as the most
likely first failure by three separate sources: this review, deferred
finding #20 in `plans/2026-08-25-geometry-transport-followups.md`, and
the agent that wrote the Object Memory surface.

The related note there — `protocolClasses` relying on array-literal
coercion to `[AnyClass]` — is left alone deliberately.
`configuration.protocolClasses = [Stub.self]` is the idiomatic form and
takes its element type from context; annotating it would be cargo cult,
unlike the `[String: Any]` case fixed above, where the `Any` slot gave
the compiler nothing to infer from.

**What this does NOT say.** These two rules will not reject this code. No
compiler has run. Everything in `WORLD-BUILDER-STATUS.md` P1/P2 stands.
