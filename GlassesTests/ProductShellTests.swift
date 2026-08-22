//
//  ProductShellTests.swift
//  GlassesTests
//
//  Guards the two truthfulness invariants the product shell introduced:
//  the cartridge catalog must not advertise a module as usable before a
//  module runtime exists, and no user-facing string may leak a raw DAT enum
//  case name. Both are Rule 3 (Truthful State Only) in
//  docs/02-DEVELOPMENT-RULES.md.
//

import MWDATCore
import XCTest

@testable import Glasses

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

        // The exact status, not merely "not promoted to next". World Build is a
        // concept seed in docs/modules/WORLD-BUILD.md and the Tower has no
        // module runtime, so `.future` is the truth; drifting it to `.planned`
        // because the app grew a screen is precisely the silent promotion this
        // test exists to catch, and `!= .next` would not have noticed.
        let worldBuilder = Cartridge.catalog.first { $0.workspace == .worldBuilder }
        XCTAssertEqual(
            worldBuilder?.status,
            .future,
            "having a workspace promoted World Builder's roadmap status"
        )

        // Restated positively against the roadmap: Module #1 is still the
        // Experimental CV Lab, which has no workspace at all.
        let next = Cartridge.catalog.filter { $0.status == .next }
        XCTAssertEqual(next.first?.workspace, nil)
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
            .failed(reason: "boom"),
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
    func testTheOnlySourceReportsTheCapabilityIsAbsent() {
        let source = UnavailableWorldModelSource()
        guard case .unsupported(let reason) = source.state else {
            return XCTFail("expected .unsupported, got \(source.state)")
        }
        XCTAssertFalse(reason.isEmpty, "an unsupported state must explain itself")
        XCTAssertFalse(source.state.hasWorld)
        XCTAssertFalse(source.state.isReceivingUpdates)
    }
}
