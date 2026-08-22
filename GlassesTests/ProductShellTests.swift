//
//  ProductShellTests.swift
//  GlassesTests
//
//  Guards the truthfulness invariants of the product shell and of the cartridge
//  integration layer built on it. Rule 3 (Truthful State Only) and Rule 16
//  (Epistemic Honesty) in docs/02-DEVELOPMENT-RULES.md, plus the display rules
//  in docs/06-PRIVACY-DATA.md and docs/07-PLATFORM-CONSTRAINTS.md.
//
//  In rough order: the cartridge catalog and its roadmap statuses; workspace
//  selection; the shared availability/phase layer; the four cartridge clients
//  and view models; redaction; provenance and observation time; and the four
//  cartridges' own domain rules.
//
//  Everything here lives in one file because GlassesTests is NOT a
//  filesystem-synchronized group — its members are listed explicitly in
//  project.pbxproj — so adding a test file means hand-editing that file, which
//  was judged the worse risk. New suites are appended rather than split out.
//

import Combine
import MWDATCore
import XCTest

@testable import Glasses

// `Combine` is imported for the cartridge client protocols' `stateUpdates`
// requirement, whose type is `AnyPublisher`. The test doubles below satisfy it
// through the protocol extensions' default rather than implementing it, so this
// import is belt-and-braces — but the target enables
// SWIFT_UPCOMING_FEATURE_MEMBER_IMPORT_VISIBILITY, and being explicit about a
// module whose types appear in a conformance costs nothing.

final class CartridgeCatalogTests: XCTestCase {

    func testCatalogIsNotEmpty() {
        XCTAssertFalse(Cartridge.catalog.isEmpty)
    }

    func testCartridgeIdentifiersAreUnique() {
        let ids = Cartridge.catalog.map(\.id)
        XCTAssertEqual(ids.count, Set(ids).count, "Duplicate cartridge id would break ForEach identity")
    }

    /// The whole point of the shell: nothing is runnable yet. If a future
    /// change adds an "available"/"active" status, this test should fail and
    /// force a deliberate decision about whether the Tower actually supports
    /// it (module container is V0.8, first module V0.9).
    func testNoCartridgeClaimsToBeAvailable() {
        let honestBadges: Set<String> = ["Up next", "Planned", "Future"]
        for cartridge in Cartridge.catalog {
            XCTAssertTrue(
                honestBadges.contains(cartridge.status.badge),
                "\(cartridge.name) advertises status '\(cartridge.status.badge)', which implies a runtime that does not exist"
            )
        }
    }

    func testExactlyOneCartridgeIsMarkedNext() {
        let next = Cartridge.catalog.filter { $0.status == .next }
        XCTAssertEqual(next.count, 1, "Roadmap defines a single Module #1")
        XCTAssertEqual(next.first?.name, "Experimental CV Lab")
    }

    func testEveryCartridgeCitesASpec() {
        for cartridge in Cartridge.catalog {
            XCTAssertTrue(
                cartridge.specPath.hasPrefix("docs/modules/"),
                "\(cartridge.name) must point at a real spec file"
            )
        }
    }
}

final class StateDisplayTests: XCTestCase {

    /// `PermissionStatus` has no `notDetermined` case, so a nil value means
    /// "not asked yet" — it must never render as denied or unknown.
    func testUncheckedCameraPermissionIsDistinctFromDenied() {
        XCTAssertEqual(StateDisplay.cameraPermission(nil), "Not checked yet")
        XCTAssertEqual(StateDisplay.cameraPermission(.denied), "Denied")
        XCTAssertEqual(StateDisplay.cameraPermission(.granted), "Allowed")
    }

    func testRegistrationStatesAreHumanReadable() {
        XCTAssertEqual(StateDisplay.registration(.registered), "Registered")
        XCTAssertEqual(StateDisplay.registration(.registering), "Registering…")
        XCTAssertEqual(StateDisplay.registration(.available), "Not registered")
        XCTAssertEqual(StateDisplay.registration(.unavailable), "Meta AI unavailable")
    }

    /// A failed Tower status carries a URLSession message that can run to a
    /// full sentence. The pill shows a fixed short string; the detail is
    /// routed to the banner instead.
    func testTowerFailureDetailIsSeparatedFromTheStatusLabel() {
        let status = TowerStatus.failed("Connection lost: The network connection was lost.")
        XCTAssertEqual(StateDisplay.tower(status), "Disconnected")
        XCTAssertEqual(
            StateDisplay.towerFailureDetail(status),
            "Connection lost: The network connection was lost."
        )
    }

    func testTowerFailureDetailIsNilWhenHealthy() {
        XCTAssertNil(StateDisplay.towerFailureDetail(.online))
        XCTAssertNil(StateDisplay.towerFailureDetail(.offline))
        XCTAssertNil(StateDisplay.towerFailureDetail(.connecting))
    }

    func testTowerStatusLabels() {
        XCTAssertEqual(StateDisplay.tower(.offline), "Offline")
        XCTAssertEqual(StateDisplay.tower(.connecting), "Connecting…")
        XCTAssertEqual(StateDisplay.tower(.online), "Connected")
    }
}

// MARK: - Workspaces

/// Guards the separation that lets a World Builder workspace exist without any
/// of it claiming the Tower can build a world.
@MainActor
final class CartridgeWorkspaceTests: XCTestCase {

    /// The load-bearing invariant of the whole Product Shell V2 design. Giving
    /// a cartridge a workspace is a statement about *this app*; `status` is a
    /// statement about the *Tower's* roadmap. If having a screen ever silently
    /// promoted a module's status, the drawer would start advertising a runtime
    /// that still does not exist.
    func testHavingAWorkspaceDoesNotPromoteACartridgesStatus() {
        let withWorkspaces = Cartridge.catalog.filter { $0.workspace != nil }
        XCTAssertFalse(withWorkspaces.isEmpty, "this test is vacuous if nothing has a workspace")

        // Every status in the catalog, pinned against docs/03-ROADMAP.md and
        // the module specs — not merely "not promoted to next".
        //
        // ## Why this replaced a narrower assertion
        //
        // Product Shell V2 asserted two things: that World Builder was still
        // `.future`, and that the `.next` cartridge had no workspace at all.
        // The second held only because Experimental CV Lab was the one
        // cartridge with a roadmap position and no screen — an accident of the
        // ordering in which workspaces were built, not the invariant.
        // Experimental CV Lab has a workspace now, and that assertion would
        // fail while nothing it was protecting had gone wrong.
        //
        // The invariant it was protecting is "a screen never changes a
        // roadmap position", and the honest way to state that is the whole
        // map. This is strictly stronger than what it replaced: it catches a
        // drift on *any* cartridge, workspace or not, and a new cartridge
        // added without a deliberate decision about its status fails here
        // rather than passing silently.
        let expected: [String: CartridgeStatus] = [
            "experimental-cv": .next,        // Module #1, V0.9
            "object-memory": .planned,
            "visual-qa": .planned,
            "world-build": .future,
            "accessibility": .future,
            "environmental-memory": .future,
            "document-memory": .future,      // concept seed, Tower has not adopted it
            "scene-understanding": .future,  // concept seed, Tower has not adopted it
        ]
        XCTAssertEqual(
            Set(Cartridge.catalog.map(\.id)),
            Set(expected.keys),
            "a cartridge was added or removed without updating this roadmap pin"
        )
        for cartridge in Cartridge.catalog {
            XCTAssertEqual(
                cartridge.status,
                expected[cartridge.id],
                "\(cartridge.name)'s roadmap status drifted"
            )
        }

        // Restated positively: Module #1 is still exactly one cartridge, and
        // shipping screens for four of them did not create a second.
        XCTAssertEqual(Cartridge.catalog.filter { $0.status == .next }.count, 1)
    }

    /// The availability guard, asserted rather than implied.
    ///
    /// `testNoCartridgeClaimsToBeAvailable` and
    /// `testWorkspacesDidNotIntroduceAnAvailabilityClaim` both compare
    /// `status.badge` against `["Up next", "Planned", "Future"]` — which is the
    /// **exhaustive** set of badges `CartridgeStatus` can currently emit. Neither
    /// can fail while the enum has three cases, and a new `.available` case
    /// whose badge happened to read "Planned" would sail through both. The
    /// invariant they advertise — that no `available`/`active` case exists — was
    /// never actually asserted.
    ///
    /// This asserts it directly, via an exhaustive switch. A new case makes the
    /// switch non-exhaustive and the compiler stops the build, which is a louder
    /// failure than a red test and exactly the deliberate decision point
    /// `08-IOS-CARTRIDGE-SHELL.md` wants.
    ///
    /// The two pre-existing tests are left untouched. They were Mac-validated,
    /// they are not wrong, and they still guard the badge strings.
    func testCartridgeStatusHasNoRunnableCase() {
        for status in [CartridgeStatus.next, .planned, .future] {
            switch status {
            case .next, .planned, .future:
                continue
            // Any case added here makes this switch non-exhaustive. If that case
            // means "the Tower can run this", stop: the Tower has no module
            // container (V0.8) and no module (V0.9), and the drawer would begin
            // advertising a runtime that does not exist.
            }
        }
        XCTAssertEqual(
            Set([CartridgeStatus.next.badge, CartridgeStatus.planned.badge, CartridgeStatus.future.badge]).count,
            3,
            "two statuses render the same badge, so the drawer cannot distinguish them"
        )
    }

    /// Every cartridge cites a spec path this repository actually contains.
    ///
    /// `testEveryCartridgeCitesASpec` asserts only the `docs/modules/` **prefix**,
    /// so it passes for `docs/modules/DOES-NOT-EXIST.md`. A test bundle cannot
    /// stat the repository, so the honest substitute is to pin the exact set —
    /// which catches a typo in a new entry and forces a deliberate edit when a
    /// spec is genuinely added.
    func testEveryCartridgeCitesASpecThatExists() {
        let known: Set<String> = [
            "docs/modules/EXPERIMENTAL-CV.md",
            "docs/modules/OBJECT-MEMORY.md",
            "docs/modules/VISUAL-QA.md",
            "docs/modules/WORLD-BUILD.md",
            "docs/modules/ACCESSIBILITY.md",
            "docs/modules/ENVIRONMENTAL-MEMORY.md",
            "docs/modules/DOCUMENT-MEMORY.md",
            "docs/modules/SCENE-UNDERSTANDING.md",
        ]
        for cartridge in Cartridge.catalog {
            XCTAssertTrue(
                known.contains(cartridge.specPath),
                "\(cartridge.name) cites \(cartridge.specPath), which is not a spec file in this repository"
            )
        }
    }

    /// Every workspace this app compiles must belong to a cartridge, or it is
    /// unreachable code that no drawer row can open.
    ///
    /// The reason `CartridgeWorkspace` is `CaseIterable`: without iterating the
    /// cases, a workspace added to the enum and to `ContentView` but never
    /// attached to a catalog entry compiles, passes every other test, and can
    /// never be opened.
    func testEveryWorkspaceIsReachableFromTheCatalog() {
        let attached = Set(Cartridge.catalog.compactMap(\.workspace))
        for workspace in CartridgeWorkspace.allCases {
            XCTAssertTrue(
                attached.contains(workspace),
                "\(workspace) has no cartridge, so nothing can open it"
            )
        }
    }

    /// The existing availability guard must keep holding after workspaces were
    /// introduced — stated here too, because this is the change most likely to
    /// have quietly broken it.
    func testWorkspacesDidNotIntroduceAnAvailabilityClaim() {
        let honestBadges: Set<String> = ["Up next", "Planned", "Future"]
        for cartridge in Cartridge.selectable {
            XCTAssertTrue(
                honestBadges.contains(cartridge.status.badge),
                "\(cartridge.name) is openable and advertises '\(cartridge.status.badge)'"
            )
        }
    }

    func testExactlyTheCartridgesWithWorkspacesAreSelectable() {
        let expected = Cartridge.catalog.filter { $0.workspace != nil }.map(\.id)
        XCTAssertEqual(Cartridge.selectable.map(\.id), expected)
        XCTAssertFalse(Cartridge.selectable.isEmpty)
    }

    func testWorldBuilderIsTheWorkspaceThatExists() {
        let worldBuilder = Cartridge.catalog.first { $0.workspace == .worldBuilder }
        XCTAssertNotNil(worldBuilder)
        XCTAssertEqual(worldBuilder?.id, "world-build")
    }

    // MARK: Restoring a persisted selection

    func testAStoredIdentifierResolvesToItsCartridge() {
        let resolved = Cartridge.workspaceCartridge(forID: "world-build")
        XCTAssertEqual(resolved?.workspace, .worldBuilder)
    }

    func testAnUnknownStoredIdentifierResolvesToNothing() {
        XCTAssertNil(Cartridge.workspaceCartridge(forID: "not-a-cartridge"))
        XCTAssertNil(Cartridge.workspaceCartridge(forID: ""))
        XCTAssertNil(Cartridge.workspaceCartridge(forID: nil))
    }

    /// A stored identifier outlives the build that wrote it. If a cartridge
    /// loses its workspace in a later release, a persisted selection must not
    /// resurrect a screen that no longer exists — it must fall back to Home.
    func testAStoredCartridgeWithoutAWorkspaceDoesNotReopen() throws {
        // Unwrapped rather than optional-chained: if every cartridge gained a
        // workspace this test would otherwise pass while asserting nothing.
        let withoutWorkspace = try XCTUnwrap(
            Cartridge.catalog.first { $0.workspace == nil },
            "no workspace-less cartridge left to test the fallback with"
        )
        XCTAssertNil(Cartridge.workspaceCartridge(forID: withoutWorkspace.id))
    }
}

// MARK: - World model boundary

/// The Tower has no world builder. These tests pin what the app is allowed to
/// say about that, and pin the display rule `docs/modules/WORLD-BUILD.md`
/// imposes on any spatial figure the Tower eventually sends.
@MainActor
final class WorldModelTests: XCTestCase {

    // MARK: Scale provenance

    /// The monocular-depth rule, as a test. WORLD-BUILD.md forbids ever
    /// presenting inferred depth as ground truth, so exactly one case may be
    /// rendered as an estimate and the others must not be silently folded into
    /// it.
    func testOnlyInferredDepthIsMarkedAsAnEstimate() {
        XCTAssertTrue(WorldScaleSemantics.inferredMetric.isEstimate)
        XCTAssertFalse(WorldScaleSemantics.relative.isEstimate)
        XCTAssertFalse(WorldScaleSemantics.measuredMetric.isEstimate)
        XCTAssertFalse(WorldScaleSemantics.unknown.isEstimate)
    }

    /// Every provenance has to be sayable. A missing string would leave a view
    /// to compose its own explanation, which is how an inferred figure ends up
    /// described as measured.
    func testEveryScaleCanBeExplainedToAPerson() {
        // `allCases`, not a hand-written list: a future case would otherwise
        // slip past this unnoticed, which is the one thing the display rule
        // cannot tolerate.
        XCTAssertGreaterThanOrEqual(WorldScaleSemantics.allCases.count, 4)
        for scale in WorldScaleSemantics.allCases {
            XCTAssertFalse(scale.displayName.isEmpty, "\(scale) has no label")
            XCTAssertFalse(scale.explanation.isEmpty, "\(scale) has no explanation")
        }
    }

    /// Unknown scale must read as unknown, never as a benign-looking default.
    func testUnknownScaleIsNotDressedUpAsRelative() {
        XCTAssertNotEqual(WorldScaleSemantics.unknown.displayName, WorldScaleSemantics.relative.displayName)
        XCTAssertEqual(WorldScaleSemantics.unknown.displayName, "Unknown")
    }

    // MARK: State

    /// The three states that must never imply a world exists. `.unsupported` is
    /// today's only reachable state; `.awaitingFirstUpdate` is the one most
    /// likely to be misdrawn later as "a world is appearing".
    func testStatesWithoutAWorldDoNotClaimOne() {
        let empty: [WorldModelState] = [
            .unsupported(reason: "no Tower support"),
            .idle,
            .awaitingFirstUpdate,
            .failed(CartridgeFailure(kind: .transport, message: "boom")),
        ]
        for state in empty {
            XCTAssertFalse(state.hasWorld, "\(state) claims a world")
            XCTAssertFalse(state.isReceivingUpdates, "\(state) claims live updates")
            XCTAssertNil(state.snapshot, "\(state) produced a snapshot from nothing")
        }
    }

    func testOnlyReceivingCountsAsLive() {
        let snapshot = WorldSnapshot(keyframeCount: 12)
        XCTAssertTrue(WorldModelState.receiving(snapshot).isReceivingUpdates)
        XCTAssertFalse(
            WorldModelState.finalized(snapshot).isReceivingUpdates,
            "a finished world is inspectable, not live"
        )
    }

    func testAWorldSurvivesFinalisationSoItStaysInspectable() {
        let snapshot = WorldSnapshot(name: "Bedroom", keyframeCount: 37)
        XCTAssertTrue(WorldModelState.finalized(snapshot).hasWorld)
        XCTAssertEqual(WorldModelState.finalized(snapshot).snapshot, snapshot)
    }

    // MARK: Snapshot emptiness

    /// A Tower that reports nothing must not be rendered as a world with zeroes
    /// in it. `nil` and `0` are different claims: one is "not reported", the
    /// other is "reported as none".
    func testADefaultSnapshotReportsNothingRatherThanZero() {
        let snapshot = WorldSnapshot()
        XCTAssertTrue(snapshot.isEmpty)
        XCTAssertNil(snapshot.keyframeCount)
        XCTAssertNil(snapshot.mappingSeconds)
        XCTAssertEqual(snapshot.tracking, .unavailable)
        XCTAssertEqual(snapshot.scale, .unknown)
    }

    func testASnapshotWithAnyRealFieldIsNotEmpty() {
        XCTAssertFalse(WorldSnapshot(keyframeCount: 0).isEmpty, "zero keyframes is still a report")
        XCTAssertFalse(WorldSnapshot(name: "Bedroom").isEmpty)
        XCTAssertFalse(WorldSnapshot(tracking: .lost).isEmpty)
        XCTAssertFalse(WorldSnapshot(scale: .relative).isEmpty)
    }

    // MARK: The only source that exists

    /// Today's whole truth: there is no Tower world builder, and the app says
    /// exactly that and nothing more.
    ///
    /// `UnavailableWorldModelSource` was renamed `UnavailableWorldBuilderClient`
    /// so all four cartridges name this layer the same way. The contract is
    /// unchanged.
    func testTheOnlyClientReportsTheCapabilityIsAbsent() {
        let client = UnavailableWorldBuilderClient()
        guard case .unsupported(let reason) = client.state else {
            return XCTFail("expected .unsupported, got \(client.state)")
        }
        XCTAssertFalse(reason.isEmpty, "an unsupported state must explain itself")
        XCTAssertFalse(client.state.hasWorld)
        XCTAssertFalse(client.state.isReceivingUpdates)
    }
}

// MARK: - Shared cartridge integration layer

/// Guards the small shared layer the four cartridges sit on: what the Tower has
/// declared (nothing), how availability is resolved from that, and the rule that
/// a phase without data may not carry data.
///
/// These are the tests that would notice if a future change made the app *look*
/// integrated before the Tower was.
@MainActor
final class CartridgeIntegrationTests: XCTestCase {

    // MARK: What the Tower has declared

    /// The whole current state of Tower integration, asserted rather than
    /// assumed. When the first real contract lands this test fails, and that
    /// failure is the intended signal to review every consumer — it is not a
    /// nuisance to delete.
    func testTheTowerDeclaresNoCartridgeContracts() {
        XCTAssertTrue(
            TowerCapabilities.declared.isEmpty,
            "a Tower contract appeared; every cartridge's client must be reviewed"
        )
        XCTAssertTrue(
            TowerCapabilities.supported.isEmpty,
            "this build claims to implement a contract that does not exist"
        )
    }

    /// No cartridge becomes usable by connecting. Connectivity is not the thing
    /// that is missing, and a UI that suggested otherwise would send a user
    /// round a loop that cannot terminate.
    func testNoCartridgeIsAvailableWhetherOrNotTheTowerIsReachable() {
        for cartridge in Cartridge.catalog {
            for reachable in [true, false] {
                let availability = TowerCapabilities.availability(
                    for: cartridge.id,
                    isTowerReachable: reachable
                )
                XCTAssertEqual(
                    availability,
                    .noContract,
                    "\(cartridge.name) claimed availability with reachable=\(reachable)"
                )
                XCTAssertFalse(availability.isAvailable)
                XCTAssertEqual(availability.forcedPhase, .unsupported)
            }
        }
    }

    // MARK: Contract resolution

    /// A Tower speaking a contract this build does not implement must produce an
    /// explicit unsupported state — not a silent empty screen, and not an
    /// attempt to decode it anyway.
    func testAnUnknownContractIsExplicitlyUnsupported() {
        let declared = CartridgeContract(cartridgeID: "world-build", identifier: "v99")
        let availability = CartridgeAvailability.resolve(
            declared: declared,
            supported: [],
            isTowerReachable: true
        )
        XCTAssertEqual(availability, .unsupportedContract(declared: declared))
        XCTAssertFalse(availability.isAvailable)
        XCTAssertEqual(availability.forcedPhase, .unsupported)
    }

    /// The precedence rule. A contract mismatch is not fixed by reconnecting,
    /// so it must outrank an unreachable Tower — otherwise the UI advises a
    /// reconnect that cannot help, forever.
    func testAContractMismatchOutranksAnUnreachableTower() {
        let declared = CartridgeContract(cartridgeID: "world-build", identifier: "v99")
        XCTAssertEqual(
            CartridgeAvailability.resolve(declared: declared, supported: [], isTowerReachable: false),
            .unsupportedContract(declared: declared),
            "an unreachable Tower masked a contract this build cannot speak"
        )
    }

    /// An implemented contract still needs a reachable Tower — and that is a
    /// connection state, not an error.
    func testAnImplementedContractStillNeedsAReachableTower() {
        let declared = CartridgeContract(cartridgeID: "world-build", identifier: "v1")
        XCTAssertEqual(
            CartridgeAvailability.resolve(declared: declared, supported: ["v1"], isTowerReachable: false),
            .towerUnreachable
        )
        XCTAssertEqual(
            CartridgeAvailability.resolve(declared: declared, supported: ["v1"], isTowerReachable: true),
            .available(declared)
        )
    }

    /// Availability stops forcing a phase exactly when the cartridge is usable,
    /// and not before. This is what lets a cartridge's own state show through
    /// only once there is something behind it.
    func testOnlyAnAvailableCartridgeLetsItsOwnStateThrough() {
        let declared = CartridgeContract(cartridgeID: "x", identifier: "v1")
        XCTAssertNil(CartridgeAvailability.available(declared).forcedPhase)
        XCTAssertEqual(CartridgeAvailability.noContract.forcedPhase, .unsupported)
        // `.disconnected`, not `.unsupported`. A Tower that is merely
        // unreachable may well be able to do this, and the shared panel now
        // says so in its headline and glyph rather than only in its prose.
        XCTAssertEqual(CartridgeAvailability.towerUnreachable.forcedPhase, .disconnected)
        XCTAssertEqual(
            CartridgeAvailability.unsupportedContract(declared: declared).forcedPhase,
            .unsupported
        )
    }

    // MARK: Explanations

    /// Every unavailable state has to be sayable, and an available one must not
    /// produce a reassuring sentence a caller might show by accident.
    func testEveryUnavailableStateExplainsItselfAndAnAvailableOneDoesNot() {
        let declared = CartridgeContract(cartridgeID: "x", identifier: "v9")
        let unavailable: [CartridgeAvailability] = [
            .noContract,
            .unsupportedContract(declared: declared),
            .towerUnreachable,
        ]
        for availability in unavailable {
            let explanation = availability.explanation(cartridgeName: "Test Cartridge")
            XCTAssertNotNil(explanation, "\(availability) cannot be explained")
            XCTAssertFalse(explanation?.isEmpty ?? true)
            XCTAssertTrue(
                explanation?.contains("Test Cartridge") ?? false,
                "an explanation that does not name the cartridge is not actionable"
            )
        }
        XCTAssertNil(CartridgeAvailability.available(declared).explanation(cartridgeName: "Test Cartridge"))
    }

    /// The unsupported-contract explanation must name the contract. Without it,
    /// "update the app" is advice with nothing behind it and nothing to report.
    func testAnUnsupportedContractExplanationNamesTheContract() {
        let declared = CartridgeContract(cartridgeID: "x", identifier: "world-v3")
        let explanation = CartridgeAvailability.unsupportedContract(declared: declared)
            .explanation(cartridgeName: "World Builder")
        XCTAssertTrue(explanation?.contains("world-v3") ?? false)
    }

    // MARK: The joined explanation

    /// The two-sentence join, decided once here rather than restated in four
    /// workspaces.
    ///
    /// The ordering matters: the shared sentence about the Tower comes first,
    /// then whatever the cartridge adds about itself. Either may be absent, and
    /// a blank paragraph between them reads as a missing string — which is how
    /// a reader starts to distrust the rest of the panel.
    func testTheSharedAndClientSentencesAreJoinedInOrder() {
        let shared = CartridgeAvailability.noContract
            .explanation(cartridgeName: "World Builder") ?? ""
        XCTAssertFalse(shared.isEmpty)

        let joined = CartridgeAvailability.noContract.explanation(
            cartridgeName: "World Builder",
            clientReason: "And here is the cartridge speaking."
        )
        XCTAssertTrue(joined.hasPrefix(shared), "the shared sentence must come first")
        XCTAssertTrue(joined.hasSuffix("And here is the cartridge speaking."))
        XCTAssertFalse(joined.contains("\n\n\n"), "a blank paragraph opened between the two sentences")
    }

    /// An absent client sentence leaves the shared one intact and adds no
    /// trailing whitespace.
    func testAnAbsentClientSentenceLeavesNoGap() {
        let shared = CartridgeAvailability.noContract
            .explanation(cartridgeName: "World Builder") ?? ""
        for reason in [nil, ""] as [String?] {
            XCTAssertEqual(
                CartridgeAvailability.noContract
                    .explanation(cartridgeName: "World Builder", clientReason: reason),
                shared
            )
        }
    }

    /// An available cartridge has no shared sentence, so the client stands
    /// alone rather than being prefixed by an empty one.
    func testAnAvailableCartridgeShowsOnlyTheClientSentence() {
        let contract = CartridgeContract(cartridgeID: "x", identifier: "v1")
        XCTAssertEqual(
            CartridgeAvailability.available(contract)
                .explanation(cartridgeName: "X", clientReason: "Only this."),
            "Only this."
        )
        XCTAssertEqual(
            CartridgeAvailability.available(contract)
                .explanation(cartridgeName: "X", clientReason: nil),
            ""
        )
    }

    // MARK: Failure wrapping

    /// A cartridge failure passes through unchanged; anything else becomes
    /// `.transport`, which is the only honest attribution available without
    /// knowing where an unrecognised error came from.
    func testWrappingPreservesACartridgeFailureAndClassifiesAnythingElse() {
        let original = CartridgeFailure(kind: .notSupported, message: "no contract")
        XCTAssertEqual(CartridgeFailure.wrapping(original), original)

        struct Other: Error {}
        let wrapped = CartridgeFailure.wrapping(Other())
        XCTAssertEqual(wrapped.kind, .transport)
        XCTAssertFalse(wrapped.message.isEmpty)
    }

    // MARK: Phases

    /// The load-bearing property of `CartridgePhase`, stated once here and
    /// applied to every cartridge's own state in `testNoClientProducesTowerData`.
    func testOnlyLiveAndSettledPhasesMayCarryData() {
        XCTAssertTrue(CartridgePhase.live.mayCarryData)
        XCTAssertTrue(CartridgePhase.settled.mayCarryData)
        for phase in [CartridgePhase.unsupported, .disconnected, .idle, .waiting, .failed] {
            XCTAssertFalse(phase.mayCarryData, "\(phase) is permitted to carry data")
        }
        // Restated over `allCases` so a future phase cannot be added on the
        // permissive side of this line without being noticed.
        for phase in CartridgePhase.allCases where phase != .live && phase != .settled {
            XCTAssertFalse(phase.mayCarryData, "\(phase) is permitted to carry data")
        }
    }

    /// A spinner is only ever honest in one phase.
    ///
    /// Asserted case by case rather than as `showsProgress == (phase ==
    /// .waiting)`. That formula is the implementation verbatim, so it would
    /// have re-derived its own expectation from any change to the definition
    /// and passed regardless — a mirror, not a test.
    func testProgressIsOnlyHonestWhileWaiting() {
        XCTAssertTrue(CartridgePhase.waiting.showsProgress)
        // `.unsupported` matters most: nothing is underway and nothing will be
        // without a Tower change, so a spinner there is the most convincing and
        // least true indicator the app could draw.
        XCTAssertFalse(CartridgePhase.unsupported.showsProgress)
        XCTAssertFalse(CartridgePhase.disconnected.showsProgress)
        XCTAssertFalse(CartridgePhase.idle.showsProgress)
        XCTAssertFalse(CartridgePhase.live.showsProgress)
        XCTAssertFalse(CartridgePhase.settled.showsProgress)
        XCTAssertFalse(CartridgePhase.failed.showsProgress)
        XCTAssertEqual(CartridgePhase.allCases.count, 7, "a phase was added without a decision here")
    }

    /// An unreachable Tower and an absent capability are different situations
    /// with opposite remedies, and must stay different phases.
    func testAnUnreachableTowerIsNotAMissingCapability() {
        XCTAssertNotEqual(CartridgePhase.disconnected, CartridgePhase.unsupported)
        XCTAssertFalse(CartridgePhase.disconnected.mayCarryData)
    }

    // MARK: Failures

    /// A failure with no message renders as a blank panel attached to nothing.
    /// The substitution keeps the guarantee absolute rather than by convention.
    func testAFailureAlwaysCarriesAnExplanation() {
        for kind in CartridgeFailure.Kind.allCases {
            let failure = CartridgeFailure(kind: kind, message: "")
            XCTAssertFalse(failure.message.isEmpty, "\(kind) produced a blank failure")
        }
        XCTAssertEqual(
            CartridgeFailure(kind: .transport, message: "socket closed").message,
            "socket closed",
            "a real message must survive untouched"
        )
    }
}

// MARK: - The four cartridge clients

/// One table, four cartridges, one invariant: **nothing in this app produces
/// Tower data, because the Tower produces none.**
///
/// Written as a table rather than four suites so that a fifth cartridge added
/// without a truthful client fails here rather than passing by omission.
@MainActor
final class CartridgeClientTests: XCTestCase {

    /// Every client, paired with the catalog id it must answer for and whether
    /// it is exposing any Tower data at all.
    private struct ClientCase {
        let cartridgeID: String
        let phase: CartridgePhase
        let reason: String
        let hasData: Bool
    }

    private func allClients() -> [ClientCase] {
        let world = UnavailableWorldBuilderClient()
        let cv = UnavailableExperimentalCVClient()
        let documents = UnavailableDocumentMemoryClient()
        let scene = UnavailableSceneUnderstandingClient()

        return [
            ClientCase(
                cartridgeID: world.cartridgeID,
                phase: world.state.phase,
                reason: UnavailableWorldBuilderClient.reason,
                hasData: world.state.snapshot != nil || world.state.hasWorld
            ),
            ClientCase(
                cartridgeID: cv.cartridgeID,
                phase: cv.state.phase,
                reason: UnavailableExperimentalCVClient.reason,
                hasData: cv.state.run != nil
            ),
            ClientCase(
                cartridgeID: documents.cartridgeID,
                phase: documents.state.phase,
                reason: UnavailableDocumentMemoryClient.reason,
                hasData: documents.state.result != nil
            ),
            ClientCase(
                cartridgeID: scene.cartridgeID,
                phase: scene.state.phase,
                reason: UnavailableSceneUnderstandingClient.reason,
                hasData: scene.state.snapshot != nil
            ),
        ]
    }

    /// The single most important assertion in this file.
    func testNoClientProducesTowerData() {
        let cases = allClients()
        XCTAssertEqual(cases.count, 4, "a cartridge client was added without being covered here")
        for client in cases {
            XCTAssertEqual(
                client.phase,
                .unsupported,
                "\(client.cartridgeID) is not in the unsupported phase"
            )
            XCTAssertFalse(
                client.phase.mayCarryData,
                "\(client.cartridgeID)'s phase permits data it cannot have"
            )
            XCTAssertFalse(
                client.hasData,
                "\(client.cartridgeID) produced Tower data from a Tower that produces none"
            )
        }
    }

    /// An unsupported state that does not explain itself becomes a blank screen
    /// the user reads as a bug.
    func testEveryClientExplainsWhyItHasNothing() {
        for client in allClients() {
            XCTAssertFalse(client.reason.isEmpty, "\(client.cartridgeID) gives no reason")
        }
    }

    /// **No client may make a claim about what the Tower stores.**
    ///
    /// This app has no channel through which it could know that. It sends
    /// frames over a transport `07-PLATFORM-CONSTRAINTS.md` Limitation 11
    /// describes as unauthenticated and unencrypted, and the protocol says
    /// nothing about storage in either direction — so "the Tower keeps none of
    /// this" is not a conservative guess, it is a fabrication (Rule 3), and it
    /// is worst on Scene Understanding, whose subject is bystanders.
    ///
    /// A length check would not have caught it. The offending sentence was
    /// long, fluent, and wrong.
    func testNoClientClaimsToKnowWhatTheTowerStores() {
        let forbidden = [
            "stores nothing",
            "store nothing",
            "keeps nothing",
            "is not stored",
            "are not stored",
            "never stored",
            "nothing is stored",
        ]
        for client in allClients() {
            let reason = client.reason.lowercased()
            for phrase in forbidden {
                XCTAssertFalse(
                    reason.contains(phrase),
                    "\(client.cartridgeID) claims to know what the Tower stores: \"\(phrase)\""
                )
            }
        }
    }

    /// Cartridge isolation, as far as a runtime test can reach it: a client
    /// answers for exactly one cartridge, that cartridge is in the catalog, and
    /// no two clients answer for the same one.
    func testEachClientAnswersForExactlyItsOwnCartridge() {
        let ids = allClients().map(\.cartridgeID)
        XCTAssertEqual(ids.count, Set(ids).count, "two clients claim the same cartridge")

        let catalogIDs = Set(Cartridge.catalog.map(\.id))
        for id in ids {
            XCTAssertTrue(catalogIDs.contains(id), "\(id) is not a cartridge in the catalog")
        }

        // Stated exactly, so a copy-paste that leaves the wrong id in a new
        // client is caught rather than merely being "some catalog id".
        XCTAssertEqual(
            Set(ids),
            ["world-build", "experimental-cv", "document-memory", "scene-understanding"]
        )
    }

    /// Every workspace-bearing cartridge has a client. A screen with no client
    /// would have to invent its own state, which is where fabricated data
    /// enters an app.
    func testEveryOpenableCartridgeHasAClient() {
        let clientIDs = Set(allClients().map(\.cartridgeID))
        for cartridge in Cartridge.selectable {
            XCTAssertTrue(
                clientIDs.contains(cartridge.id),
                "\(cartridge.name) has a workspace but no client"
            )
        }
    }

    // MARK: Requests are refused, not swallowed

    /// A silent no-op leaves a control that appears to work. Both cartridges
    /// that accept a request must refuse it audibly — docs/04-MODULE-SYSTEM.md
    /// requires an unsupported request to "produce a clear degraded/failed
    /// state rather than silently pretending" it applied.
    func testRunningAnExperimentIsRefusedRatherThanIgnored() {
        let client = UnavailableExperimentalCVClient()
        XCTAssertThrowsError(
            try client.run(CVExperiment(id: "any", name: "Any"))
        ) { error in
            guard let failure = error as? CartridgeFailure else {
                return XCTFail("expected a CartridgeFailure, got \(error)")
            }
            XCTAssertFalse(failure.message.isEmpty)
            // Not `.towerReportedFailure`. The Tower reported nothing — there
            // may not even be a socket open — and attributing a local refusal
            // to the other machine is a fabricated claim about it that a later
            // log or telemetry consumer would read back as fact.
            XCTAssertEqual(failure.kind, .notSupported)
        }
    }

    func testSearchingDocumentsIsRefusedRatherThanReturningEmpty() {
        let client = UnavailableDocumentMemoryClient()
        XCTAssertThrowsError(
            try client.search(.recent(limit: 10), origin: .appText)
        ) { error in
            guard let failure = error as? CartridgeFailure else {
                return XCTFail("expected a CartridgeFailure, got \(error)")
            }
            // The distinction this protects: an empty result would read as
            // "you have no documents", which is a false statement about the
            // user's own memory rather than about the Tower.
            XCTAssertFalse(failure.message.isEmpty)
            XCTAssertEqual(failure.kind, .notSupported)
        }
    }

    /// The Experimental CV client declares no experiments. A populated picker —
    /// even of plausible ones from the module spec's candidate list — would be
    /// the app asserting those experiments exist.
    func testNoExperimentsAreDeclared() {
        // Through the view model, which is the only thing that ever reads the
        // list. Pattern-matching the client's `let` state for `.idle` could
        // never match and made the test unable to fail for the reason it names.
        let lab = ExperimentalCVViewModel(client: UnavailableExperimentalCVClient())
        XCTAssertTrue(
            lab.availableExperiments.isEmpty,
            "the app is offering experiments the Tower has not declared"
        )
        XCTAssertNil(lab.state.run)
        XCTAssertEqual(lab.state.phase, .unsupported)
    }
}

// MARK: - View models

/// Guards what the four workspace view models may own and may do.
///
/// The runtime-ownership half of this — that constructing them opens no socket
/// and disturbs no live stream — is in `TowerClientTests`, where a real socket
/// and a mock server are available to prove it against.
@MainActor
final class CartridgeViewModelTests: XCTestCase {

    func testEveryViewModelReportsUnsupportedWhetherOrNotTheTowerIsReachable() {
        for reachable in [true, false] {
            XCTAssertEqual(WorldBuilderViewModel(client: UnavailableWorldBuilderClient()).phase(isTowerReachable: reachable), .unsupported)
            XCTAssertEqual(ExperimentalCVViewModel(client: UnavailableExperimentalCVClient()).phase(isTowerReachable: reachable), .unsupported)
            XCTAssertEqual(DocumentMemoryViewModel(client: UnavailableDocumentMemoryClient()).phase(isTowerReachable: reachable), .unsupported)
            XCTAssertEqual(SceneUnderstandingViewModel(client: UnavailableSceneUnderstandingClient()).phase(isTowerReachable: reachable), .unsupported)
        }
    }

    /// Availability must outrank the client's own state, or a cartridge whose
    /// Tower cannot serve it would render `.idle` and invite a user to start
    /// something that cannot run.
    func testAvailabilityOutranksTheClientState() {
        let lab = ExperimentalCVViewModel(client: IdleExperimentalCVClient())
        XCTAssertEqual(lab.state.phase, .idle, "the double must actually report idle")
        XCTAssertEqual(
            lab.phase(isTowerReachable: true),
            .unsupported,
            "an idle client showed through a Tower that declares no contract"
        )
    }

    /// A refused request has to reach the screen. Swallowing it is how a button
    /// comes to look like it works.
    func testARefusedExperimentIsSurfacedRatherThanSwallowed() {
        let lab = ExperimentalCVViewModel(client: UnavailableExperimentalCVClient())
        XCTAssertNil(lab.lastRequestFailure)
        lab.run(CVExperiment(id: "any", name: "Any"))
        XCTAssertNotNil(lab.lastRequestFailure, "a refusal vanished")
        XCTAssertFalse(lab.lastRequestFailure?.message.isEmpty ?? true)
        // The refusal must not invent a state transition either.
        XCTAssertEqual(lab.state.phase, .unsupported)
    }

    func testARefusedSearchIsSurfacedRatherThanSwallowed() {
        let memory = DocumentMemoryViewModel(client: UnavailableDocumentMemoryClient())
        memory.queryText = "the parking notice"
        memory.submitTypedQuery()
        XCTAssertNotNil(memory.lastRequestFailure)
        XCTAssertEqual(memory.state.phase, .unsupported)
    }

    /// Whitespace is not a question. Submitting it would produce a "nothing
    /// found" answer to a query nobody asked.
    func testAnEmptyOrBlankQueryIsNotSubmitted() {
        let client = RecordingDocumentMemoryClient()
        let memory = DocumentMemoryViewModel(client: client)

        memory.queryText = ""
        memory.submitTypedQuery()
        memory.queryText = "   \n  "
        memory.submitTypedQuery()

        XCTAssertTrue(client.searches.isEmpty, "a blank query was submitted")
    }

    /// Typed text becomes a semantic query from the app, and the origin is
    /// carried rather than assumed — that parameter is the seam a Siri intent
    /// or wake-word layer would submit through without this cartridge growing a
    /// dependency on speech.
    func testTypedTextBecomesASemanticQueryTaggedAsAppInput() {
        let client = RecordingDocumentMemoryClient()
        let memory = DocumentMemoryViewModel(client: client)

        memory.queryText = "  the parking notice  "
        memory.submitTypedQuery()

        XCTAssertEqual(client.searches.count, 1)
        XCTAssertEqual(client.searches.first?.query, .semantic("the parking notice"))
        XCTAssertEqual(client.searches.first?.origin, .appText)
    }

    /// An input layer that is not this app can submit the same query type. No
    /// such layer exists; this asserts the seam is usable without one.
    func testAQueryCanArriveFromOutsideTheApp() {
        let client = RecordingDocumentMemoryClient()
        let memory = DocumentMemoryViewModel(client: client)

        memory.submit(.recent(limit: 5), origin: .externalIntent)

        XCTAssertEqual(client.searches.first?.origin, .externalIntent)
        XCTAssertEqual(client.searches.first?.query, .recent(limit: 5))
        XCTAssertTrue(memory.queryText.isEmpty, "an external query must not need the text field")
    }

    /// The available-experiment list is empty in every state but `.idle`.
    func testAvailableExperimentsAreOnlyListedWhenSomethingCanBeRun() {
        XCTAssertTrue(ExperimentalCVViewModel(client: UnavailableExperimentalCVClient()).availableExperiments.isEmpty)
        let idle = ExperimentalCVViewModel(client: IdleExperimentalCVClient())
        XCTAssertEqual(idle.availableExperiments.map(\.id), ["fixture"])
    }
}

// MARK: Test doubles

/// Reports `.idle` so tests can prove availability outranks a client's state.
/// Lives in the test target, where it can never reach a device.
@MainActor
private final class IdleExperimentalCVClient: ExperimentalCVClient {
    let cartridgeID = "experimental-cv"
    let state: ExperimentalCVState = .idle(
        available: [CVExperiment(id: "fixture", name: "Fixture")]
    )
    func run(_ experiment: CVExperiment) throws {}
}

/// Records what it was asked, so query routing can be asserted without a Tower.
@MainActor
private final class RecordingDocumentMemoryClient: DocumentMemoryClient {
    struct Search: Equatable {
        let query: DocumentQuery
        let origin: DocumentQueryOrigin
    }

    let cartridgeID = "document-memory"
    let state: DocumentMemoryState = .idle
    private(set) var searches: [Search] = []

    func search(_ query: DocumentQuery, origin: DocumentQueryOrigin) throws {
        searches.append(Search(query: query, origin: origin))
    }
}

// MARK: - Privacy: redaction and artifacts

/// Guards the last link in the privacy pipeline:
///
/// ```text
/// raw sensor data → ephemeral perception → derived structured state
///                 → redaction → persistence / display
/// ```
///
/// iOS applies no redaction and cannot. What it can do — and what these pin —
/// is refuse to display anything whose producer did not state that it was
/// treated, and say which is which.
@MainActor
final class ArtifactRedactionTests: XCTestCase {

    /// The single decision this whole area exists to make.
    func testOnlyRedactedImageryMayBeShownOnAPersistedSurface() {
        XCTAssertTrue(RedactionState.redacted.isDisplayableWhenPersisted)
        XCTAssertFalse(RedactionState.rawEphemeral.isDisplayableWhenPersisted)
        XCTAssertFalse(RedactionState.unknown.isDisplayableWhenPersisted)
    }

    /// An unstated treatment is not a treatment. `.unknown` must be handled
    /// exactly as strictly as raw — a lenient default here is how untreated
    /// imagery reaches a screen.
    func testAnUnstatedTreatmentIsAsStrictAsRaw() {
        XCTAssertEqual(
            RedactionState.unknown.isDisplayableWhenPersisted,
            RedactionState.rawEphemeral.isDisplayableWhenPersisted
        )
        XCTAssertFalse(VisualArtifactState.available(.unknown).isDisplayable)
        XCTAssertFalse(VisualArtifactState.available(.rawEphemeral).isDisplayable)
        XCTAssertTrue(VisualArtifactState.available(.redacted).isDisplayable)
    }

    /// Arriving is not the same as being showable. Both conditions are
    /// required, and a test that only covered the redacted case would not have
    /// noticed if the fetch state were dropped from the check.
    func testAnArtifactMustBothArriveAndBeRedacted() {
        XCTAssertFalse(VisualArtifactState.notFetched(.redacted).isDisplayable)
        XCTAssertFalse(VisualArtifactState.fetching(.redacted).isDisplayable)
        XCTAssertFalse(VisualArtifactState.absent.isDisplayable)
        XCTAssertFalse(
            VisualArtifactState.failed(CartridgeFailure(kind: .transport, message: "x")).isDisplayable
        )
    }

    /// A withheld image must say why, or it renders as a blank square the user
    /// reads as a bug rather than as a deliberate refusal.
    func testWithheldImageryExplainsItself() {
        XCTAssertNotNil(VisualArtifactState.available(.rawEphemeral).withheldReason)
        XCTAssertNotNil(VisualArtifactState.available(.unknown).withheldReason)
        XCTAssertNotNil(
            VisualArtifactState.failed(CartridgeFailure(kind: .transport, message: "dropped")).withheldReason
        )
        // Nothing to explain in the two cases where nothing is being withheld.
        XCTAssertNil(VisualArtifactState.available(.redacted).withheldReason)
        XCTAssertNil(VisualArtifactState.absent.withheldReason)
    }

    /// The redaction state has to survive the fetch. Losing it between "arrived"
    /// and "rendered" is exactly how an untreated image gets drawn.
    func testRedactionTravelsWithTheArtifactThroughEveryState() {
        XCTAssertEqual(VisualArtifactState.notFetched(.redacted).redaction, .redacted)
        XCTAssertEqual(VisualArtifactState.fetching(.unknown).redaction, .unknown)
        XCTAssertEqual(VisualArtifactState.available(.rawEphemeral).redaction, .rawEphemeral)
        XCTAssertNil(VisualArtifactState.absent.redaction)
    }

    /// Every treatment must be sayable.
    func testEveryRedactionStateCanBeDescribed() {
        for state in RedactionState.allCases {
            XCTAssertFalse(state.explanation.isEmpty, "\(state) has no explanation")
        }
    }

    /// The redacted explanation must attribute the claim to whoever made it.
    ///
    /// It read "People in this image were obscured before it was stored" — a
    /// specific, checkable privacy guarantee about a step **no Tower contract
    /// defines**. Redaction could be face masking, text masking, or the
    /// producer's own definition of the word. Stating what was removed turns
    /// an opaque flag into exactly the assurance the Tower cannot honour.
    func testTheRedactedExplanationAttributesItsClaimRatherThanDescribingIt() {
        let explanation = RedactionState.redacted.explanation
        XCTAssertTrue(
            explanation.contains("producer"),
            "the redaction claim is stated as fact rather than attributed: \(explanation)"
        )
        XCTAssertFalse(
            explanation.lowercased().contains("people in this image"),
            "the app described what redaction removed, which no contract defines"
        )
    }
}

// MARK: - Provenance and time

/// Guards Core Principles 2, 4 and 5 from `07-PLATFORM-CONSTRAINTS.md` at the
/// point they are most easily lost: display.
@MainActor
final class ObservationProvenanceTests: XCTestCase {

    /// A measurement carries no model confidence, and a model output carries one
    /// or explicitly carries none — which is a worse state than a low
    /// confidence, not a better one.
    func testConfidenceBelongsOnlyToInference() {
        XCTAssertNil(ObservationProvenance.measured.confidence)
        XCTAssertNil(ObservationProvenance.unknown.confidence)
        XCTAssertEqual(ObservationProvenance.inferred(confidence: 0.8).confidence, 0.8)
        XCTAssertNil(ObservationProvenance.inferred(confidence: nil).confidence)
    }

    /// An inference owes the reader a caveat; a measurement owes none. A caveat
    /// on everything is noise, and noise gets ignored.
    func testOnlyUncertainValuesCarryACaveat() {
        XCTAssertNil(ObservationProvenance.measured.caveat)
        XCTAssertNotNil(ObservationProvenance.inferred(confidence: 0.9).caveat)
        XCTAssertNotNil(ObservationProvenance.unknown.caveat)
    }

    /// An inference with no reported confidence must not read as certainty, and
    /// must not read as zero either — neither is what the Tower said.
    func testAnInferenceWithoutAConfidenceSaysSo() {
        let caveat = ObservationProvenance.inferred(confidence: nil).caveat ?? ""
        XCTAssertTrue(caveat.contains("did not report"), "got: \(caveat)")
        XCTAssertFalse(caveat.contains("0%"), "a missing confidence rendered as zero")
    }

    func testOnlyInferenceIsMarkedAsInference() {
        XCTAssertTrue(ObservationProvenance.inferred(confidence: nil).isInference)
        XCTAssertFalse(ObservationProvenance.measured.isInference)
        XCTAssertFalse(ObservationProvenance.unknown.isInference)
    }

    /// A malformed confidence from the Tower must not render as "170%". Clamping
    /// is display hygiene, not a fix — the decode site is where an out-of-range
    /// value should be noticed.
    func testConfidenceIsClampedForDisplay() {
        XCTAssertEqual(ObservationProvenance.percent(1.7), "100%")
        XCTAssertEqual(ObservationProvenance.percent(-0.5), "0%")
        XCTAssertEqual(ObservationProvenance.percent(0.5), "50%")
    }
}

@MainActor
final class ObservationTimeTests: XCTestCase {

    /// Core Principle 5. Arrival time must never be promoted to observation
    /// time, because a view labelling one as the other is the whole failure the
    /// principle names.
    func testArrivalTimeIsNeverShownAsObservationTime() {
        let arrivalOnly = ObservationTime(observedAt: nil, receivedAt: Date())
        XCTAssertNil(arrivalOnly.displayableObservationTime)
        XCTAssertTrue(arrivalOnly.isObservationTimeUnknown)
    }

    func testAReportedObservationTimeIsUsed() {
        let observed = Date(timeIntervalSince1970: 1_000)
        let time = ObservationTime(observedAt: observed, receivedAt: Date())
        XCTAssertEqual(time.displayableObservationTime, observed)
        XCTAssertFalse(time.isObservationTimeUnknown)
    }

    /// A default carries neither, which is the honest starting point.
    func testADefaultTimeClaimsNothing() {
        let time = ObservationTime()
        XCTAssertNil(time.displayableObservationTime)
        XCTAssertNil(time.receivedAt)
        XCTAssertTrue(time.isObservationTimeUnknown)
    }
}

/// Limitation 8 — camera FOV is not attention — enforced as a naming rule.
@MainActor
final class ObservedDurationTests: XCTestCase {

    /// The label must describe the camera, not the wearer. "Viewed", "read" and
    /// "looked" are all claims the platform cannot support at any confidence.
    func testTheLabelDescribesTheCameraAndNotTheWearer() {
        let labels = [
            ObservedDuration(seconds: 4).label,
            ObservedDuration(seconds: 65).label,
            ObservedDuration(seconds: 120).label,
        ]
        for label in labels {
            XCTAssertTrue(label.hasPrefix("In view"), "got: \(label)")
            let lowered = label.lowercased()
            for forbidden in ["viewed", "read", "looked", "watched", "seen"] {
                XCTAssertFalse(lowered.contains(forbidden), "\(label) claims attention")
            }
        }
    }

    func testDurationsAreFormattedForPeople() {
        XCTAssertEqual(ObservedDuration(seconds: 4).label, "In view 4s")
        XCTAssertEqual(ObservedDuration(seconds: 120).label, "In view 2m")
        XCTAssertEqual(ObservedDuration(seconds: 65).label, "In view 1m 5s")
    }

    /// A negative duration is meaningless and would render as "In view -3s".
    func testANegativeDurationIsFloored() {
        XCTAssertEqual(ObservedDuration(seconds: -3).seconds, 0)
    }

    /// The caveat must say what the glasses cannot do, not merely soften what
    /// they can.
    func testTheCaveatDeniesAttentionOutright() {
        let caveat = ObservedDuration.attentionCaveat.lowercased()
        XCTAssertTrue(caveat.contains("cannot tell"), "got: \(ObservedDuration.attentionCaveat)")
    }
}

// MARK: - World Builder additions

/// The fields Product Shell V2 did not have: calibration, geometry, trajectory,
/// persistence, and the `.finalizing` state.
@MainActor
final class WorldModelIntegrationTests: XCTestCase {

    // MARK: Finalizing

    /// `.finalizing` exists because the Tower working is not the same as the
    /// Tower observing. A live badge while the camera is off is a lie about the
    /// sensor, whatever the compute is doing.
    func testFinalizingIsWorkButNotLiveObservation() {
        let state = WorldModelState.finalizing(WorldSnapshot(keyframeCount: 9))
        XCTAssertFalse(state.isReceivingUpdates, "finalizing claimed live observation")
        XCTAssertTrue(state.hasWorld)
        XCTAssertNotNil(state.snapshot)
        XCTAssertEqual(state.phase, .live, "finalizing is the Tower working")
    }

    /// Every state's coarse phase, pinned. A drift here would let a shared
    /// panel draw a spinner over a world that is finished, or a live badge over
    /// one that is not being observed.
    func testEveryWorldStateMapsToTheRightPhase() {
        let snapshot = WorldSnapshot(keyframeCount: 1)
        let expected: [(WorldModelState, CartridgePhase)] = [
            (.unsupported(reason: "x"), .unsupported),
            (.idle, .idle),
            (.awaitingFirstUpdate, .waiting),
            (.receiving(snapshot), .live),
            (.finalizing(snapshot), .live),
            (.finalized(snapshot), .settled),
            (.failed(CartridgeFailure(kind: .transport, message: "x")), .failed),
        ]
        for (state, phase) in expected {
            XCTAssertEqual(state.phase, phase, "\(state) mapped to the wrong phase")
        }
    }

    /// Restated for the states that must never carry data — the invariant the
    /// shared `CartridgePhase` exists to make checkable.
    func testStatesWithoutAWorldStillCarryNoData() {
        let empty: [WorldModelState] = [
            .unsupported(reason: "x"), .idle, .awaitingFirstUpdate,
            .failed(CartridgeFailure(kind: .transport, message: "x")),
        ]
        for state in empty {
            XCTAssertFalse(state.phase.mayCarryData)
            XCTAssertNil(state.snapshot)
            XCTAssertFalse(state.hasWorld)
        }
    }

    // MARK: Calibration and metric display

    /// Both gates, together. An uncalibrated figure is not a rough figure, it is
    /// an unanchored one; and a relative figure is not a distance at all.
    func testAMetricFigureNeedsBothCalibrationAndMetricScale() {
        XCTAssertTrue(
            WorldSnapshot(scale: .inferredMetric, calibration: .calibrated).permitsMetricDisplay
        )
        XCTAssertFalse(
            WorldSnapshot(scale: .inferredMetric, calibration: .calibrating).permitsMetricDisplay,
            "an uncalibrated pipeline produced a displayable distance"
        )
        XCTAssertFalse(
            WorldSnapshot(scale: .relative, calibration: .calibrated).permitsMetricDisplay,
            "a relative figure was treated as a distance"
        )
        XCTAssertFalse(
            WorldSnapshot(scale: .unknown, calibration: .calibrated).permitsMetricDisplay
        )
    }

    /// Only a calibrated pipeline permits spatial figures, and "not reported" is
    /// not a permission.
    func testOnlyCalibratedPermitsSpatialFigures() {
        XCTAssertTrue(WorldCalibrationState.calibrated.permitsSpatialFigures)
        for state in [WorldCalibrationState.unknown, .uncalibrated, .calibrating] {
            XCTAssertFalse(state.permitsSpatialFigures, "\(state) permitted a spatial figure")
        }
    }

    /// Silence and a report are different claims and must read differently.
    func testUnknownCalibrationIsNotDressedUpAsUncalibrated() {
        XCTAssertNotEqual(
            WorldCalibrationState.unknown.displayName,
            WorldCalibrationState.uncalibrated.displayName
        )
        for state in WorldCalibrationState.allCases {
            XCTAssertFalse(state.displayName.isEmpty)
        }
    }

    // MARK: Geometry

    /// The representation is opaque: whatever the Tower calls it survives
    /// untouched. Nothing in this app matches on it, so nothing can drop a name
    /// it does not recognise.
    func testAnyGeometryRepresentationSurvivesVerbatim() {
        for name in ["point_cloud", "pose_graph", "gaussian splats", "something-new"] {
            let report = WorldGeometryReport(representation: name, elementCount: 12)
            XCTAssertEqual(report.representation, name)
            XCTAssertTrue(report.hasReport)
        }
    }

    /// A count alone is still a report — it just cannot be labelled, and the
    /// view is what decides how to present it.
    func testGeometryWithOnlyACountIsStillAReport() {
        XCTAssertTrue(WorldGeometryReport(elementCount: 5).hasReport)
        XCTAssertTrue(WorldGeometryReport(representation: "mesh").hasReport)
        XCTAssertFalse(WorldGeometryReport().hasReport)
        XCTAssertFalse(
            WorldGeometryReport(isIncremental: true).hasReport,
            "an update mode is not geometry"
        )
    }

    // MARK: Trajectory

    /// A path length under relative scale is a number in arbitrary units.
    /// Printing it as metres would be the fabrication WORLD-BUILD.md names.
    func testPathLengthIsWithheldUnlessTheScaleClaimsMetres() {
        XCTAssertTrue(
            WorldTrajectoryReport(pathLength: 14.2, scale: .inferredMetric).distanceDisplayable
        )
        XCTAssertTrue(
            WorldTrajectoryReport(pathLength: 14.2, scale: .measuredMetric).distanceDisplayable
        )
        XCTAssertFalse(
            WorldTrajectoryReport(pathLength: 14.2, scale: .relative).distanceDisplayable,
            "a relative path length was offered as a distance"
        )
        XCTAssertFalse(
            WorldTrajectoryReport(pathLength: 14.2, scale: .unknown).distanceDisplayable
        )
        XCTAssertFalse(
            WorldTrajectoryReport(poseCount: 40, scale: .inferredMetric).distanceDisplayable,
            "a distance was claimed with no length reported"
        )
    }

    func testAPoseCountIsAReportWithoutADistance() {
        XCTAssertTrue(WorldTrajectoryReport(poseCount: 40).hasReport)
        XCTAssertFalse(WorldTrajectoryReport().hasReport)
    }

    // MARK: Emptiness, extended

    /// The new fields must participate in emptiness, or a snapshot carrying only
    /// a geometry report would claim to be empty and be omitted from the UI.
    func testEmptinessAccountsForEveryNewField() {
        XCTAssertTrue(WorldSnapshot().isEmpty)
        XCTAssertFalse(WorldSnapshot(calibration: .calibrating).isEmpty)
        XCTAssertFalse(WorldSnapshot(geometry: WorldGeometryReport(elementCount: 0)).isEmpty)
        XCTAssertFalse(WorldSnapshot(trajectory: WorldTrajectoryReport(poseCount: 0)).isEmpty)
        XCTAssertFalse(WorldSnapshot(persistence: .session).isEmpty)
    }

    /// Silence about storage is not a promise that the world is discarded.
    func testUnknownPersistenceIsNotSessionOnly() {
        XCTAssertNotEqual(
            WorldPersistenceState.unknown.displayName,
            WorldPersistenceState.session.displayName
        )
    }

    /// Inspecting a stored world is a different mode from watching one being
    /// built, and the identifier travels with it so the claim stays checkable.
    func testInspectionModeDistinguishesAStoredWorld() {
        XCTAssertFalse(WorldInspectionMode.live.isInspecting)
        XCTAssertTrue(WorldInspectionMode.inspecting(worldID: "abc").isInspecting)
        XCTAssertNotEqual(
            WorldInspectionMode.inspecting(worldID: "abc"),
            WorldInspectionMode.inspecting(worldID: "def")
        )
    }
}

// MARK: - Experimental CV Lab

/// Guards the two rules `docs/modules/EXPERIMENTAL-CV.md` puts on results:
/// inference must be distinguishable from measurement, and nothing may be called
/// "better" without a baseline to be better than.
@MainActor
final class ExperimentalCVModelTests: XCTestCase {

    private func metric(
        _ value: Double,
        baseline: Double? = nil,
        higherIsBetter: Bool? = nil
    ) -> CVMetric {
        CVMetric(
            label: "accuracy",
            value: value,
            provenance: .inferred(confidence: nil),
            baseline: baseline,
            higherIsBetter: higherIsBetter
        )
    }

    /// "Avoid declaring an approach 'better' without a measurement", enforced.
    func testNoVerdictWithoutABaseline() {
        XCTAssertNil(metric(0.9, higherIsBetter: true).comparison)
    }

    /// A metric with no stated direction cannot be judged either: latency and
    /// error improve downward, and guessing gets it backwards half the time.
    func testNoVerdictWithoutAStatedDirection() {
        XCTAssertNil(metric(0.9, baseline: 0.5).comparison)
    }

    /// Integral values on purpose: this asserts the *direction* logic, and a
    /// binary-float delta would make the test about `Double` equality instead.
    func testAVerdictRespectsTheStatedDirection() {
        XCTAssertEqual(
            metric(90, baseline: 50, higherIsBetter: true).comparison,
            .better(delta: 40)
        )
        // The same movement, on a metric where lower is better.
        XCTAssertEqual(
            metric(90, baseline: 50, higherIsBetter: false).comparison,
            .worse(delta: 40)
        )
        XCTAssertEqual(
            metric(20, baseline: 50, higherIsBetter: false).comparison,
            .better(delta: -30)
        )
    }

    /// A tie is a real result and must not round into a win.
    func testMatchingTheBaselineIsUnchanged() {
        XCTAssertEqual(metric(0.5, baseline: 0.5, higherIsBetter: true).comparison, .unchanged)
        XCTAssertEqual(CVMetric.Comparison.unchanged.label, "Unchanged")
    }

    /// A unit the Tower did not send is omitted, not substituted.
    func testAMissingUnitIsOmittedRatherThanInvented() {
        let bare = CVMetric(label: "count", value: 12, provenance: .measured)
        XCTAssertEqual(bare.displayValue, "12")
        let withUnit = CVMetric(label: "latency", value: 12, unit: "ms", provenance: .measured)
        XCTAssertEqual(withUnit.displayValue, "12 ms")
    }

    /// The run-level caveat has to fire whenever any single metric is an
    /// inference — one measured metric in the set must not suppress it.
    func testARunKnowsWhenAnyOfItsMetricsIsAnInference() {
        let experiment = CVExperiment(id: "x", name: "X")
        let measured = CVMetric(label: "frames", value: 30, provenance: .measured)
        let inferred = CVMetric(label: "depth", value: 1.2, provenance: .inferred(confidence: 0.6))

        XCTAssertFalse(CVExperimentRun(experiment: experiment, metrics: [measured]).containsInference)
        XCTAssertTrue(
            CVExperimentRun(experiment: experiment, metrics: [measured, inferred]).containsInference
        )
        XCTAssertFalse(CVExperimentRun(experiment: experiment).containsInference)
    }

    /// Zero annotations is a result — "found nothing" — and must not merge with
    /// "did not say".
    func testZeroAnnotationsIsAReportAndSilenceIsNot() {
        XCTAssertTrue(CVAnnotationReport(count: 0).hasReport)
        XCTAssertFalse(CVAnnotationReport().hasReport)
        XCTAssertTrue(CVAnnotationReport(artifact: .available(.redacted)).hasReport)
    }

    /// An annotated frame gets no privacy exemption for being a debug surface.
    func testAnUnredactedAnnotatedFrameIsWithheld() {
        let report = CVAnnotationReport(count: 3, artifact: .available(.rawEphemeral))
        XCTAssertFalse(report.artifact.isDisplayable)
        XCTAssertNotNil(report.artifact.withheldReason)
    }

    func testEveryCVStateMapsToTheRightPhase() {
        let experiment = CVExperiment(id: "x", name: "X")
        let run = CVExperimentRun(experiment: experiment)
        let expected: [(ExperimentalCVState, CartridgePhase)] = [
            (.unsupported(reason: "x"), .unsupported),
            (.idle(available: []), .idle),
            (.starting(experiment), .waiting),
            (.running(run), .live),
            (.completed(run), .settled),
            (.failed(CartridgeFailure(kind: .timedOut, message: "x")), .failed),
        ]
        for (state, phase) in expected {
            XCTAssertEqual(state.phase, phase, "\(state) mapped to the wrong phase")
        }
        XCTAssertTrue(ExperimentalCVState.running(run).isRunning)
        XCTAssertFalse(ExperimentalCVState.completed(run).isRunning)
    }
}

// MARK: - Document Memory

/// Guards the retrieval-truthfulness rules from `ENVIRONMENTAL-MEMORY.md` and
/// Core Principle 3.
@MainActor
final class DocumentMemoryModelTests: XCTestCase {

    /// "Nothing matched" and "never observed" are different answers about
    /// different things, and merging them lets a gap in what the glasses
    /// happened to see read as a statement about the world.
    func testNothingMatchedAndNeverObservedAreDifferentAnswers() {
        XCTAssertNotEqual(DocumentQueryEvidence.notFound, .noObservation)
        XCTAssertNotEqual(
            DocumentQueryEvidence.notFound.explanation,
            DocumentQueryEvidence.noObservation.explanation
        )
        XCTAssertTrue(
            DocumentQueryEvidence.noObservation.explanation.contains("not the same"),
            "a never-observed answer failed to disclaim absence"
        )
    }

    /// A result cannot claim a match while carrying nothing — and the safe
    /// direction from that is a failure, never a stronger claim.
    ///
    /// An earlier version quietly rewrote it to `.notFound`, whose user-facing
    /// sentence is "Nothing in the Tower's document memory matched." That is a
    /// **definite negative statement about the user's own memory, manufactured
    /// from a decode failure**, with the Tower's confidence discarded on the
    /// way — Core Principle 3 in exactly the forbidden direction.
    func testAMatchWithNoDocumentsIsUndecodableRatherThanNotFound() {
        XCTAssertThrowsError(
            try DocumentQueryResult(
                query: .text("parking"),
                origin: .appText,
                documents: [],
                evidence: .matched(confidence: 0.9)
            )
        ) { error in
            guard let failure = error as? CartridgeFailure else {
                return XCTFail("expected a CartridgeFailure, got \(error)")
            }
            XCTAssertEqual(failure.kind, .undecodableResponse)
        }
    }

    /// The confidence must survive when the match is genuine — Core Principle 4.
    func testAGenuineMatchKeepsItsConfidence() throws {
        let result = try DocumentQueryResult(
            query: .text("parking"),
            origin: .appText,
            documents: [RememberedDocument(id: "1")],
            evidence: .matched(confidence: 0.42)
        )
        XCTAssertEqual(result.evidence, .matched(confidence: 0.42))
        XCTAssertTrue(result.evidence.explanation.contains("42%"))
    }

    /// A never-observed answer must not be turned into a match by the coercion
    /// above, in either direction.
    func testAnEmptyNeverObservedAnswerIsPreserved() throws {
        let result = try DocumentQueryResult(
            query: .observedWithin(DateInterval(start: Date(timeIntervalSince1970: 0), duration: 60)),
            origin: .appText,
            documents: [],
            evidence: .noObservation
        )
        XCTAssertEqual(result.evidence, .noObservation)
    }

    /// A record with no title is described, not named. An invented title is a
    /// claim about the document's contents.
    func testADocumentWithoutATitleIsDescribedRatherThanNamed() {
        XCTAssertEqual(RememberedDocument(id: "1").displayTitle, "Untitled document")
        XCTAssertEqual(RememberedDocument(id: "1", title: "Parking notice").displayTitle, "Parking notice")
    }

    /// Silence about text and a verdict of unreadable are different claims.
    func testUnknownTextIsNotAVerdictOfUnreadable() {
        XCTAssertNotEqual(
            DocumentTextAvailability.unknown.displayName,
            DocumentTextAvailability.notReadable.displayName
        )
        XCTAssertFalse(DocumentTextAvailability.unknown.hasText)
        XCTAssertFalse(DocumentTextAvailability.notReadable.hasText)
        XCTAssertTrue(DocumentTextAvailability.extracted(characterCount: nil).hasText)
    }

    /// The list carries a count, never the text. A list of documents must not
    /// also be a bulk transfer of every document's contents into the phone.
    func testExtractedTextIsReportedAsACountNotAsContent() {
        XCTAssertEqual(
            DocumentTextAvailability.extracted(characterCount: 1_200).displayName,
            "1200 characters"
        )
        XCTAssertEqual(
            DocumentTextAvailability.extracted(characterCount: nil).displayName,
            "Text available"
        )
    }

    /// A document's thumbnail obeys the same rule as every other stored image.
    func testAnUnredactedThumbnailIsWithheld() {
        let raw = RememberedDocument(id: "1", thumbnail: .available(.rawEphemeral))
        XCTAssertFalse(raw.isThumbnailDisplayable)
        let redacted = RememberedDocument(id: "1", thumbnail: .available(.redacted))
        XCTAssertTrue(redacted.isThumbnailDisplayable)
    }

    /// Observation time never falls back to arrival time, at the document level.
    func testADocumentWithNoObservationTimeSaysSo() {
        let document = RememberedDocument(
            id: "1",
            time: ObservationTime(observedAt: nil, receivedAt: Date())
        )
        XCTAssertNil(document.time.displayableObservationTime)
        XCTAssertTrue(document.time.isObservationTimeUnknown)
    }

    /// Time queries are ranges. "This morning" is not an instant, and answering
    /// it as one answers a different question.
    func testTimeQueriesAreRangesRatherThanInstants() {
        let interval = DateInterval(start: Date(timeIntervalSince1970: 0), duration: 3_600)
        XCTAssertEqual(DocumentQuery.observedWithin(interval), .observedWithin(interval))
        XCTAssertNotEqual(
            DocumentQuery.observedWithin(interval),
            .observedWithin(DateInterval(start: Date(timeIntervalSince1970: 0), duration: 60))
        )
    }

    /// The origin exists so a future input layer needs no new path. No such
    /// layer exists; this asserts the seam does.
    func testAnInputSourceBeyondTheAppIsRepresentable() {
        XCTAssertEqual(DocumentQueryOrigin.allCases.count, 2)
        XCTAssertTrue(DocumentQueryOrigin.allCases.contains(.externalIntent))
    }

    func testEveryDocumentStateMapsToTheRightPhase() throws {
        let result = try DocumentQueryResult(
            query: .recent(limit: 5), origin: .appText, evidence: .notFound
        )
        let expected: [(DocumentMemoryState, CartridgePhase)] = [
            (.unsupported(reason: "x"), .unsupported),
            (.idle, .idle),
            (.searching(.recent(limit: 5)), .waiting),
            (.results(result), .settled),
            (.failed(CartridgeFailure(kind: .transport, message: "x")), .failed),
        ]
        for (state, phase) in expected {
            XCTAssertEqual(state.phase, phase, "\(state) mapped to the wrong phase")
        }
    }
}

// MARK: - Scene Understanding

/// The anonymity and no-gaze rules, as tests. These are the assertions most
/// likely to be tripped by a future well-meaning copy edit, which is exactly why
/// they are here rather than in a comment.
@MainActor
final class SceneUnderstandingModelTests: XCTestCase {

    private func person(_ id: String, facing: SceneFacing = .unknown) -> SceneEntity {
        SceneEntity(
            trackID: SceneTrackID(id),
            kind: .person,
            facing: facing,
            provenance: .inferred(confidence: 0.7)
        )
    }

    // MARK: Anonymity

    /// A person on screen is a positional label and nothing else. The Tower's
    /// track handle never reaches the display, because a stable-looking string
    /// beside a person's outline invites a reader to treat it as an identity.
    func testAPersonIsNamedPositionallyAndNeverByTheirTrackHandle() {
        let handle = SceneTrackID("track-7f3a-9b21")
        let name = handle.displayName(index: 0, kind: .person)
        XCTAssertEqual(name, "Person 1")
        XCTAssertFalse(name.contains(handle.rawValue), "a track handle reached the display")
    }

    /// An object may carry a class label — "chair" — which is a category, not an
    /// identity. Limitation 6's distinction, preserved.
    func testAnObjectMayCarryAClassLabelButNeverAnIdentity() {
        let handle = SceneTrackID("track-2")
        XCTAssertEqual(handle.displayName(index: 1, kind: .object(label: "chair")), "chair")
        XCTAssertEqual(handle.displayName(index: 1, kind: .object(label: nil)), "Object 2")
    }

    /// Two tracked people differ only by their handle — never by anything the
    /// system claims to know *about* them.
    ///
    /// The anonymity guarantee itself is structural: `SceneEntityKind.person`
    /// has no associated value, so there is nowhere to put a name, and no
    /// runtime test can assert the absence of a field. What is testable is the
    /// consequence, which is what this checks. An earlier version asserted
    /// `SceneEntityKind.person == SceneEntityKind.person`, a tautology that
    /// would keep passing if someone added `case identifiedPerson(name:)`
    /// beside it.
    func testTwoTrackedPeopleDifferOnlyByTheirHandle() {
        let a = person("track-a")
        let b = person("track-b")
        XCTAssertNotEqual(a.trackID, b.trackID)
        XCTAssertEqual(a.kind, b.kind, "the system distinguished two people by something about them")
        XCTAssertFalse(SceneEntityKind.object(label: "person").isPerson)

        // And the display of each is positional, so even the handle that does
        // distinguish them never reaches the screen.
        XCTAssertEqual(a.trackID.displayName(index: 0, kind: a.kind), "Person 1")
        XCTAssertEqual(b.trackID.displayName(index: 1, kind: b.kind), "Person 2")
    }

    // MARK: Gaze

    /// The wording rule from Limitation 8. `.towardCamera` is body orientation
    /// and reads as such; every phrasing that would claim attention is absent.
    func testOrientationLabelsNeverClaimGaze() {
        XCTAssertEqual(SceneFacing.towardCamera.displayName, "Facing your direction")
        let forbidden = ["look", "watch", "eye", "gaze", "stare", "notice", "see you"]
        for facing in SceneFacing.allCases {
            let lowered = facing.displayName.lowercased()
            for word in forbidden {
                XCTAssertFalse(
                    lowered.contains(word),
                    "\(facing.displayName) claims attention the glasses cannot observe"
                )
            }
            XCTAssertFalse(facing.displayName.isEmpty)
        }
    }

    /// The caveat must name the missing hardware, not merely hedge. A softened
    /// version invites the reading it exists to prevent.
    func testTheGazeCaveatNamesTheMissingCapability() {
        let caveat = SceneFacing.gazeCaveat.lowercased()
        XCTAssertTrue(caveat.contains("no eye tracking"), "got: \(SceneFacing.gazeCaveat)")
        XCTAssertTrue(caveat.contains("cannot"))
    }

    /// "Not reported" is its own answer and must not collapse into a direction.
    func testUnknownOrientationIsItsOwnAnswer() {
        XCTAssertEqual(SceneFacing.unknown.displayName, "Orientation unknown")
        XCTAssertNotEqual(SceneFacing.unknown.displayName, SceneFacing.acrossView.displayName)
    }

    // MARK: Counts

    /// Derived from the list, so a header can never disagree with the rows
    /// beneath it.
    func testCountsAreDerivedFromTheEntityListItself() {
        let snapshot = SceneSnapshot(entities: [
            person("a"),
            person("b"),
            SceneEntity(trackID: SceneTrackID("c"), kind: .object(label: "chair"), provenance: .measured),
        ])
        XCTAssertEqual(snapshot.personCount, 2)
        XCTAssertEqual(snapshot.objectCount, 1)
        XCTAssertEqual(snapshot.personCount + snapshot.objectCount, snapshot.entities.count)
    }

    func testAnEmptySceneCountsZeroOfEach() {
        let snapshot = SceneSnapshot()
        XCTAssertEqual(snapshot.personCount, 0)
        XCTAssertEqual(snapshot.objectCount, 0)
        XCTAssertTrue(snapshot.isEmpty)
    }

    /// Core Principle 3. A bare "0 people" invites the reading that nobody is
    /// there; the caveat is what prevents it, so it must actually disclaim
    /// absence rather than merely describe the camera.
    func testTheCountCaveatDisclaimsAbsenceRatherThanJustDescribingTheCamera() {
        let caveat = SceneSnapshot.countCaveat.lowercased()
        XCTAssertTrue(caveat.contains("not ruled out"), "got: \(SceneSnapshot.countCaveat)")
        XCTAssertTrue(caveat.contains("camera"))
    }

    // MARK: Positions

    /// The same monocular-depth rule World Builder obeys, applied to a distance
    /// to a person.
    func testADistanceToAnEntityIsWithheldWithoutMetricScale() {
        let relative = ScenePosition(frame: .cameraRelative, distance: 2.5, scale: .relative)
        XCTAssertFalse(relative.distanceDisplayable)

        let inferred = ScenePosition(frame: .cameraRelative, distance: 2.5, scale: .inferredMetric)
        XCTAssertTrue(inferred.distanceDisplayable)
        XCTAssertTrue(inferred.scale.isEstimate, "an inferred distance must be labelled an estimate")

        let unknown = ScenePosition(frame: .cameraRelative, distance: 2.5, scale: .unknown)
        XCTAssertFalse(unknown.distanceDisplayable)
    }

    /// A bearing is an angle and needs no depth, so it is not subject to the
    /// scale rule — treating it as if it were would discard information the
    /// system genuinely has.
    func testABearingIsAvailableWithoutAnyScale() {
        let position = ScenePosition(frame: .cameraRelative, bearingDegrees: -30, scale: .unknown)
        XCTAssertEqual(position.bearingDescription, "To your left")
        XCTAssertFalse(position.distanceDisplayable)
    }

    /// Coarse on purpose: a bounding-box centre does not support "37.4° right".
    func testBearingsAreDescribedCoarsely() {
        XCTAssertEqual(ScenePosition(frame: .cameraRelative, bearingDegrees: 5).bearingDescription, "Ahead")
        XCTAssertEqual(ScenePosition(frame: .cameraRelative, bearingDegrees: 30).bearingDescription, "To your right")
        XCTAssertEqual(ScenePosition(frame: .cameraRelative, bearingDegrees: -30).bearingDescription, "To your left")
        XCTAssertNil(ScenePosition(frame: .cameraRelative).bearingDescription)
    }

    /// **The camera sees a forward cone.**
    ///
    /// An earlier version said "Beside you, left" past 60° and "Behind you,
    /// right" past 120° — telling the wearer the system had detected someone
    /// behind them, which no forward-facing camera can do.
    /// `docs/modules/SCENE-UNDERSTANDING.md` says so itself: a wearer looking
    /// at a desk has most of the room behind the camera.
    ///
    /// The previous test enshrined the 150° case rather than catching it, which
    /// is what a test asserting the implementation back to itself does.
    func testNoBearingClaimsAnObservationBehindTheWearer() {
        for degrees in stride(from: -180.0, through: 180.0, by: 5.0) {
            let description = ScenePosition(
                frame: .cameraRelative,
                bearingDegrees: degrees
            ).bearingDescription ?? ""
            let lowered = description.lowercased()
            XCTAssertFalse(
                lowered.contains("behind"),
                "a bearing of \(degrees)° claimed an observation behind the wearer"
            )
            XCTAssertFalse(
                lowered.contains("beside"),
                "a bearing of \(degrees)° claimed an observation outside the camera cone"
            )
            XCTAssertFalse(description.isEmpty, "a bearing of \(degrees)° could not be described")
        }
        // Past the plausible field of view it says so, rather than picking a
        // direction the sensor cannot justify.
        XCTAssertEqual(
            ScenePosition(frame: .cameraRelative, bearingDegrees: 150).bearingDescription,
            "At the edge of view, right"
        )
    }

    /// Camera-relative and world-relative are different claims: one changes when
    /// the wearer turns their head and the other does not.
    func testFramesOfReferenceAreDistinguishable() {
        XCTAssertNotEqual(
            SceneFrameOfReference.cameraRelative,
            SceneFrameOfReference.worldRelative(worldID: nil)
        )
        XCTAssertNotEqual(
            SceneFrameOfReference.worldRelative(worldID: "a"),
            SceneFrameOfReference.worldRelative(worldID: "b")
        )
    }

    // MARK: Relationships and staleness

    /// A relation is an inference about two inferences and carries its own
    /// confidence; the predicate is the Tower's word, kept verbatim.
    func testARelationshipKeepsItsPredicateAndItsConfidence() {
        let relationship = SceneRelationship(
            subject: SceneTrackID("a"),
            predicate: "seated at",
            object: SceneTrackID("b"),
            provenance: .inferred(confidence: 0.3)
        )
        XCTAssertEqual(relationship.predicate, "seated at")
        XCTAssertEqual(relationship.provenance.confidence, 0.3)
        XCTAssertTrue(relationship.id.contains("seated at"))
    }

    /// Limitation 7: a last-known scene is not a current one, and the states
    /// must be distinguishable so the view can say which it is drawing.
    func testALastKnownSceneIsNotCurrent() {
        let snapshot = SceneSnapshot(entities: [person("a")])
        XCTAssertTrue(SceneUnderstandingState.observing(snapshot).isCurrent)
        XCTAssertFalse(SceneUnderstandingState.lastKnown(snapshot).isCurrent)
        XCTAssertEqual(SceneUnderstandingState.lastKnown(snapshot).phase, .settled)
    }

    func testEverySceneStateMapsToTheRightPhase() {
        let snapshot = SceneSnapshot()
        let expected: [(SceneUnderstandingState, CartridgePhase)] = [
            (.unsupported(reason: "x"), .unsupported),
            (.idle, .idle),
            (.awaitingFirstScene, .waiting),
            (.observing(snapshot), .live),
            (.lastKnown(snapshot), .settled),
            (.failed(CartridgeFailure(kind: .transport, message: "x")), .failed),
        ]
        for (state, phase) in expected {
            XCTAssertEqual(state.phase, phase, "\(state) mapped to the wrong phase")
        }
        for state in expected where !state.1.mayCarryData {
            XCTAssertNil(state.0.snapshot, "\(state.0) carried a scene it may not have")
        }
    }
}
