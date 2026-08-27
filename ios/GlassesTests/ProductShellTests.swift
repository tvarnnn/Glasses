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

    // MARK: One answer to "is this cartridge openable?"

    /// `Cartridge.selectable` is documented as "every cartridge the drawer may
    /// present as openable", but for most of this shell's life the drawer did
    /// not consult it — or anything derived from it. It iterated
    /// `Cartridge.catalog` and re-derived openability inline as
    /// `cartridge.workspace != nil`, twice: once to decide whether to wrap the
    /// row in a `Button`, and once inside the row to pick the accessibility
    /// hint. `selectable`'s only callers were in this file.
    ///
    /// Two code paths answering one question agreed only by coincidence of
    /// implementation. Nothing made them agree, so nothing would have caught
    /// them diverging — a cartridge could have been openable to the drawer and
    /// absent from `selectable`, and every test here would still have passed
    /// while asserting the wrong list.
    ///
    /// `Cartridge.drawerRows` is now the single answer. The drawer renders it;
    /// `selectable` is defined as the openable rows of it. These tests pin that
    /// definition, so the identity below is not a coincidence being observed —
    /// it is the construction being checked.
    func testTheDrawerRendersEveryCatalogEntryInCatalogOrder() {
        XCTAssertEqual(
            Cartridge.drawerRows.map(\.cartridge.id),
            Cartridge.catalog.map(\.id),
            "the drawer shows all catalog entries, openable or not — dropping the informational rows would hide three modules"
        )
    }

    func testTheDrawersOpenableRowsAreExactlyTheSelectableCartridges() {
        let openable = Cartridge.drawerRows.filter(\.isOpenable).map(\.cartridge.id)
        XCTAssertEqual(
            openable,
            Cartridge.selectable.map(\.id),
            "the drawer and Cartridge.selectable disagree about which cartridges may be opened"
        )
        XCTAssertFalse(openable.isEmpty, "this test is vacuous if nothing is openable")
    }

    /// The other half of the same guarantee: a row is openable **if and only
    /// if** its cartridge has a workspace. The `.openable` case carries a
    /// non-optional `CartridgeWorkspace`, so the compiler already forbids an
    /// openable row with nothing to open; this pins the converse, that a
    /// cartridge with a workspace cannot be filed as informational.
    func testARowIsOpenableExactlyWhenItsCartridgeHasAWorkspace() {
        for row in Cartridge.drawerRows {
            switch row {
            case .openable(let cartridge, let workspace):
                XCTAssertEqual(
                    cartridge.workspace,
                    workspace,
                    "\(cartridge.name) opens a workspace that is not its own"
                )
            case .informational(let cartridge):
                XCTAssertNil(
                    cartridge.workspace,
                    "\(cartridge.name) has a workspace but the drawer renders it as informational"
                )
            }
        }
    }

    /// The three rows with no workspace, named. `testAStoredCartridgeWithout…`
    /// only needs one of them to exist; this pins which three, so a cartridge
    /// silently losing its workspace fails here rather than quietly becoming an
    /// informational row in a shipped build.
    func testTheThreeCartridgesWithoutAWorkspaceStayInformational() {
        let informational = Cartridge.drawerRows.filter { !$0.isOpenable }.map(\.cartridge.id)
        XCTAssertEqual(informational, ["visual-qa", "accessibility", "environmental-memory"])
    }

    /// Both hint strings, pinned to the same decision that decides tappability.
    ///
    /// These are the only two sentences VoiceOver reads that state whether a
    /// row does anything. If the hint and the `Button` were ever derived
    /// separately, one of them would eventually say a row opens something it
    /// cannot open — a lie told only to the users who cannot see that nothing
    /// happened (Rule 3, Truthful State Only).
    func testTheAccessibilityHintFollowsTheSameOpenabilityDecision() {
        for row in Cartridge.drawerRows {
            XCTAssertEqual(
                row.accessibilityHint,
                row.isOpenable ? "Opens this workspace" : "No workspace in this app yet",
                "\(row.cartridge.name)'s hint does not match its openability"
            )
        }
        XCTAssertEqual(
            Set(Cartridge.drawerRows.map(\.accessibilityHint)),
            ["Opens this workspace", "No workspace in this app yet"],
            "both hints must still be reachable — a drawer with one hint has stopped distinguishing the two kinds of row"
        )
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

    /// The state of Tower integration, asserted rather than assumed.
    ///
    /// This test used to assert both tables were empty, and its own comment
    /// said that the first real contract landing should make it fail as a
    /// signal to review every consumer. That happened: the Tower now declares
    /// `world_builder.status/2026-08-25` over the socket, and every consumer
    /// was reviewed. What it pins now is the same property in its new form —
    /// **exactly one contract is implemented, and it is that one** — so a
    /// second one appearing is still a review and not a silent widening.
    func testTheTowerDeclaresOnlyTheWorldBuilderContract() {
        XCTAssertEqual(
            TowerCapabilities.supported,
            [WorldBuilderResultContract.identifier],
            "this build's implemented contracts changed; every cartridge's client must be reviewed"
        )
        XCTAssertTrue(
            TowerCapabilities.declared.isEmpty,
            """
            a contract was hardcoded into the local table. World Builder's arrives \
            over the socket, and a compile-time copy is a second answer that can \
            disagree with the Tower's.
            """
        )
    }

    /// The Tower's name for a cartridge is not this app's, and exactly one
    /// cartridge has both.
    func testTheCartridgeNameMappingCoversOnlyWorldBuilder() {
        XCTAssertEqual(
            TowerCapabilities.towerCartridgeNames,
            ["world-build": "world_builder"]
        )
        for cartridge in Cartridge.catalog where cartridge.id != "world-build" {
            XCTAssertNil(
                TowerCapabilities.towerCartridgeNames[cartridge.id],
                "\(cartridge.name) gained a Tower name without a client to use it"
            )
        }
    }

    // MARK: Availability against a live declaration

    private func declaration(
        cartridge: String = "world_builder",
        contract: String = WorldBuilderResultContract.identifier,
        available: Bool = true,
        reason: String? = nil
    ) -> TowerCartridgeDeclaration {
        TowerCartridgeDeclaration(
            envelopeContract: "cartridge_results.envelope/2026-08-23",
            offers: [
                TowerCartridgeOffer(
                    json: [
                        "cartridge": cartridge,
                        "result_type": "status",
                        "contract": contract,
                        "available": available,
                        "unavailable_reason": reason as Any,
                        "snapshot_only": true,
                    ]
                )!
            ]
        )
    }

    /// A Tower that has declared nothing is indistinguishable from one that
    /// never will — which is correct, because from here it is.
    func testWorldBuilderIsUnavailableUntilTheTowerDeclaresIt() {
        XCTAssertEqual(
            TowerCapabilities.availability(
                for: "world-build",
                declaredBy: nil,
                isTowerReachable: true
            ),
            .noContract
        )
    }

    /// The declaration is what makes it available, and connectivity is the
    /// second gate rather than the first.
    func testADeclaredWorldBuilderContractBecomesAvailableWhenReachable() {
        let declared = declaration()
        XCTAssertEqual(
            TowerCapabilities.availability(
                for: "world-build",
                declaredBy: declared,
                isTowerReachable: true
            ),
            .available(
                CartridgeContract(
                    cartridgeID: "world-build",
                    identifier: WorldBuilderResultContract.identifier
                )
            )
        )
        XCTAssertEqual(
            TowerCapabilities.availability(
                for: "world-build",
                declaredBy: declared,
                isTowerReachable: false
            ),
            .towerUnreachable,
            "a declared contract must read as disconnected, not as absent, while the socket is down"
        )
    }

    /// A Tower speaking a different dated contract is a disagreement, not a
    /// version to compare. It must reach `.unsupportedContract`, which tells a
    /// person to update the app rather than to reconnect.
    func testAnUndatedOrLaterContractIsNotDecodedOnAGuess() {
        for identifier in ["world_builder.status/2027-01-01", "world_builder.status/2026-01-01", "v2"] {
            XCTAssertEqual(
                TowerCapabilities.availability(
                    for: "world-build",
                    declaredBy: declaration(contract: identifier),
                    isTowerReachable: true
                ),
                .unsupportedContract(
                    declared: CartridgeContract(cartridgeID: "world-build", identifier: identifier)
                ),
                "contract \(identifier) was treated as compatible"
            )
        }
    }

    /// `available: false` is an offer, not silence. Collapsing it to
    /// `.noContract` would render "no world root is configured" as "this Tower
    /// will never do this" — a different and wrong claim, calling for a
    /// different response from a person.
    func testAnUnavailableOfferIsStillAnOffer() {
        XCTAssertEqual(
            TowerCapabilities.availability(
                for: "world-build",
                declaredBy: declaration(available: false, reason: "no world root is configured"),
                isTowerReachable: true
            ),
            .available(
                CartridgeContract(
                    cartridgeID: "world-build",
                    identifier: WorldBuilderResultContract.identifier
                )
            )
        )
    }

    /// A declaration naming some other cartridge must not make World Builder
    /// available, and must not make that other cartridge available either —
    /// this build has no client for it.
    func testADeclarationForAnotherCartridgeChangesNothing() {
        let other = declaration(cartridge: "scene_understanding", contract: "scene.v1")
        XCTAssertEqual(
            TowerCapabilities.availability(
                for: "world-build",
                declaredBy: other,
                isTowerReachable: true
            ),
            .noContract
        )
        XCTAssertEqual(
            TowerCapabilities.availability(
                for: "scene-understanding",
                declaredBy: other,
                isTowerReachable: true
            ),
            .noContract,
            "a cartridge with no name mapping and no client became available"
        )
    }

    /// No cartridge becomes usable by connecting **alone**. Connectivity is the
    /// second gate, never the first: a declaration has to arrive as well, and
    /// a UI that suggested reconnecting would fix a missing contract would send
    /// a user round a loop that cannot terminate.
    ///
    /// Asserted through the no-declaration entry point, which is still the
    /// whole truth for the three cartridges the Tower lists under
    /// `not_offered`.
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
        // `.needsUpdate`, not `.unsupported`. The Tower *declared* this
        // cartridge — it can do it — and this build is the half that cannot
        // read the agreement. That is the one empty state on this screen a
        // person can end themselves, and "Nothing yet" told them a feature
        // did not exist when they were one update away from it.
        XCTAssertEqual(availability.forcedPhase, .needsUpdate)
        XCTAssertNotEqual(availability.forcedPhase, .unsupported)
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
        // `.needsUpdate`, not `.unsupported`, for the same reason `.disconnected`
        // is not `.unsupported`: opposite responses. Nothing fixes `.noContract`
        // but a Tower change; this one is fixed by updating the app.
        XCTAssertEqual(
            CartridgeAvailability.unsupportedContract(declared: declared).forcedPhase,
            .needsUpdate
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
        // Decided: nothing is in flight while the app is the thing that is
        // behind, so a spinner would be as untrue here as in `.unsupported`.
        XCTAssertFalse(CartridgePhase.needsUpdate.showsProgress)
        XCTAssertEqual(CartridgePhase.allCases.count, 8, "a phase was added without a decision here")
    }

    /// An unreachable Tower and an absent capability are different situations
    /// with opposite remedies, and must stay different phases.
    func testAnUnreachableTowerIsNotAMissingCapability() {
        XCTAssertNotEqual(CartridgePhase.disconnected, CartridgePhase.unsupported)
        XCTAssertFalse(CartridgePhase.disconnected.mayCarryData)
    }

    /// The third member of the same family. All four empty phases mean "there
    /// is nothing to show", and each one implies a different next move: wait
    /// for the Tower to gain the capability, wait for the network, update the
    /// app, or press the button. Collapsing any two of them hands a person the
    /// wrong instruction.
    func testTheFourEmptyPhasesAreDistinctBecauseTheirRemediesAre() {
        let empty: [CartridgePhase] = [.unsupported, .disconnected, .needsUpdate, .idle]
        XCTAssertEqual(Set(empty).count, empty.count, "two empty phases collapsed into one")
        for phase in empty {
            XCTAssertFalse(phase.mayCarryData, "\(phase) must not carry data")
            XCTAssertFalse(phase.showsProgress, "\(phase) must not claim work is underway")
        }
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

// MARK: - The four unavailable cartridge clients

/// One table, four cartridges, one invariant: **these four clients produce no
/// Tower data, because the Tower produces none for them.**
///
/// Written as a table rather than four suites so that a cartridge added without
/// a truthful client fails here rather than passing by omission.
///
/// ## Why Object Memory is not in the table
///
/// It is the fifth cartridge and the first whose Tower half genuinely answers:
/// two read-only HTTP routes, serving a real store. Its client therefore
/// *should* be able to reach `.settled` with records in it, which is precisely
/// what `testNoClientProducesTowerData` forbids — the invariant here is "no
/// data from a Tower that produces none", and for Object Memory the premise is
/// false.
///
/// So it is covered by `ObjectMemoryTests` instead, which asserts the stronger
/// property that actually applies to it: that what it produces is decoded from
/// what the Tower sent, and that nothing it says about a record overclaims.
/// `testEveryOpenableCartridgeHasAClient` below still includes it, because
/// "every screen has a client" is true of all five.
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
        // The four unavailable clients, plus Object Memory's — which is not in
        // `allClients()` because the invariant that table asserts does not
        // apply to it. Read off `CartridgeClients` rather than hardcoded, so a
        // sixth cartridge cannot be satisfied by a string in this file.
        let clients = CartridgeClients()
        var clientIDs = Set(allClients().map(\.cartridgeID))
        clientIDs.insert(clients.objectMemory.cartridgeID)

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

/// The rule that "metric" is not "metres", as a test.
///
/// `ReportedFigure` was extracted because two screens were rendering
/// `String(format: "%.1f m", …)` from a bare `Double` — inventing the unit —
/// while `CVMetric.unit` two files away had already taken the correct position
/// ("never assumed"). It is the smallest shared helper in the change and it was
/// the only one with no coverage, which is a poor combination for something
/// whose entire job is a display rule.
@MainActor
final class ReportedFigureTests: XCTestCase {

    /// A figure with no unit renders bare. That is not a degraded rendering —
    /// it is the honest one, because an unlabelled quantity is what the Tower
    /// sent.
    func testAFigureWithNoUnitRendersBare() {
        XCTAssertEqual(ReportedFigure.format(14.2, unit: nil), "14.2")
        XCTAssertEqual(ReportedFigure.format(3, unit: nil), "3")
    }

    /// An empty unit string is treated as no unit, not as a trailing space.
    func testAnEmptyUnitIsTreatedAsNoUnit() {
        XCTAssertEqual(ReportedFigure.format(14.2, unit: ""), "14.2")
    }

    /// The Tower's unit is used verbatim — never translated, never normalised.
    /// iOS does not know that "cm" and "m" are related, and must not act as
    /// though it does.
    func testTheTowerUnitIsUsedVerbatim() {
        XCTAssertEqual(ReportedFigure.format(14.2, unit: "m"), "14.2 m")
        XCTAssertEqual(ReportedFigure.format(1420, unit: "cm"), "1420 cm")
        XCTAssertEqual(ReportedFigure.format(7, unit: "keyframes"), "7 keyframes")
    }

    /// A whole number renders without a decimal point, so a count does not read
    /// as a measurement.
    func testWholeNumbersDoNotGrowADecimalPoint() {
        XCTAssertEqual(ReportedFigure.format(40, unit: nil), "40")
        XCTAssertEqual(ReportedFigure.format(-3, unit: nil), "-3")
        XCTAssertEqual(ReportedFigure.format(0, unit: nil), "0")
    }

    /// **The regression this exists to prevent.** No output may contain a unit
    /// the caller did not supply — in particular not the metres two screens
    /// used to print from a scale that only ever claimed to be metric *in
    /// kind*.
    func testNoUnitIsEverInvented() {
        for value in [0.0, 1.0, 14.2, -7.5, 1_000.0] {
            let rendered = ReportedFigure.format(value, unit: nil)
            for invented in ["m", "cm", "metre", "meter", "ft"] {
                XCTAssertFalse(
                    rendered.contains(invented),
                    "\(rendered) carries a unit nobody supplied"
                )
            }
        }
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

// MARK: - Camera readiness

/// A scriptable `WearablesInterface`, the seam this suite has not had before.
///
/// It exists for one question the rest of the file cannot ask: what happens to
/// camera readiness when DAT answers a permission query *before* it has
/// discovered a device. On real hardware that is not an edge case — it is what
/// happens on every cold launch, and it is what
/// `GlassesConnection.refreshCameraPermissionForAvailableDevice()` repairs.
///
/// Two DAT types cannot be faked: `Device` and `DeviceSession` both carry
/// `@_hasMissingDesignatedInitializers`. So `deviceForIdentifier` returns nil
/// (the link-state trigger is therefore device-only, and is covered physically
/// rather than here) and `createSession` throws — which is enough to assert the
/// property that matters most, that nothing automatic ever asks for a session.
final class ScriptedWearables: WearablesInterface, @unchecked Sendable {
    struct Token: AnyListenerToken {
        func cancel() async {}
    }

    private let lock = NSLock()
    private var _devices: [DeviceIdentifier] = []
    private var _permissionResults: [Result<PermissionStatus, PermissionError>]
    private var _permissionCheckCount = 0
    private var _createSessionCount = 0
    private var devicesContinuation: AsyncStream<[DeviceIdentifier]>.Continuation?
    private var _isSubscribed = false

    /// Results for successive `checkPermissionStatus` calls; the final entry
    /// repeats once the script is exhausted.
    init(permissionResults: [Result<PermissionStatus, PermissionError>]) {
        _permissionResults = permissionResults
    }

    /// Whether `devicesStream()` has been subscribed. `GlassesConnection`
    /// subscribes from a `Task` in `init`, so a test that emits immediately
    /// after construction would otherwise race the subscription and lose.
    var isSubscribed: Bool { lock.withLock { _isSubscribed } }
    var permissionCheckCount: Int { lock.withLock { _permissionCheckCount } }
    var createSessionCount: Int { lock.withLock { _createSessionCount } }

    /// Publishes a new device list, as `devicesStream()` would.
    func emitDevices(_ devices: [DeviceIdentifier]) {
        let continuation: AsyncStream<[DeviceIdentifier]>.Continuation? = lock.withLock {
            _devices = devices
            return devicesContinuation
        }
        continuation?.yield(devices)
    }

    var registrationState: RegistrationState { .registered }
    var devices: [DeviceIdentifier] { lock.withLock { _devices } }

    /// Replays the current list on subscription, as DAT's own stream does —
    /// which is also what makes a warm launch (devices already known before
    /// anyone subscribes) reproducible here.
    func devicesStream() -> AsyncStream<[DeviceIdentifier]> {
        AsyncStream { continuation in
            let current: [DeviceIdentifier] = lock.withLock {
                devicesContinuation = continuation
                _isSubscribed = true
                return _devices
            }
            if !current.isEmpty { continuation.yield(current) }
        }
    }

    func checkPermissionStatus(_ permission: Permission) async throws(PermissionError) -> PermissionStatus {
        let result: Result<PermissionStatus, PermissionError> = lock.withLock {
            _permissionCheckCount += 1
            let next = _permissionResults.first ?? .failure(.internalError)
            if _permissionResults.count > 1 { _permissionResults.removeFirst() }
            return next
        }
        switch result {
        case .success(let status): return status
        case .failure(let error): throw error
        }
    }

    func createSession(deviceSelector: any DeviceSelector) throws(DeviceSessionError) -> DeviceSession {
        lock.withLock { _createSessionCount += 1 }
        throw .noEligibleDevice
    }

    // Unused by these tests, but required by the protocol.
    func addRegistrationStateListener(_ listener: @escaping @Sendable (RegistrationState) -> Void) -> any AnyListenerToken { Token() }
    func addDevicesListener(_ listener: @escaping @Sendable ([DeviceIdentifier]) -> Void) -> any AnyListenerToken { Token() }
    func deviceForIdentifier(_ identifier: DeviceIdentifier) -> Device? { nil }
    func deviceStateStream(for identifier: DeviceIdentifier) -> AsyncStream<DeviceState> {
        AsyncStream { $0.finish() }
    }
    func requestPermission(_ permission: Permission) async throws(PermissionError) -> PermissionStatus { .granted }
    func startRegistration() async throws(RegistrationError) {}
    func startUnregistration() async throws(UnregistrationError) {}
    func handleUrl(_ url: URL) async throws(WearablesHandleURLError) -> Bool { false }
    func openFirmwareUpdate() async throws(NavigationError) {}
    func openDATGlassesAppUpdate() async throws(NavigationError) {}
}

/// The regression this suite exists for.
///
/// Physically observed on an iPhone 16 Pro with Ray-Ban Meta glasses: the
/// launch permission read threw `No wearable devices have been discovered or
/// registered`, the glasses arrived a moment later, and `cameraPermissionStatus`
/// stayed `nil` for the rest of the process — so every capture session was
/// refused for a permission that had in fact been granted.
@MainActor
final class CameraReadinessTests: XCTestCase {

    /// Polls rather than sleeps a fixed interval: the refresh is driven by a
    /// `Task` hop off the `devicesStream` loop, not by a known delay.
    private func waitUntil(
        _ condition: @MainActor () -> Bool,
        timeout: TimeInterval = 2
    ) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return true }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        return condition()
    }

    /// The regression itself. A permission read that fails because DAT has no
    /// device yet must not leave readiness permanently unknown.
    func testAPermissionCheckBeforeDiscoveryDoesNotPoisonLaterReadiness() async {
        let wearables = ScriptedWearables(permissionResults: [
            .failure(.noDevice),
            .success(.granted),
        ])
        let connection = GlassesConnection(wearables: wearables)

        // The launch read, as `ProjectManager.startAutomaticConnections()`
        // makes it: no devices yet, so DAT refuses to answer.
        connection.checkCameraPermission(reportErrors: false)
        let refused = await waitUntil { wearables.permissionCheckCount >= 1 }
        XCTAssertTrue(refused, "the launch read should have been attempted")
        XCTAssertNil(
            connection.cameraPermissionStatus,
            "a failed read must leave the status unknown rather than guessing"
        )
        XCTAssertNil(
            connection.errorMessage,
            "the automatic read must not raise an alert nobody's action caused"
        )

        // The glasses arrive.
        wearables.emitDevices(["device-1"])

        let recovered = await waitUntil { connection.cameraPermissionStatus == .granted }
        XCTAssertTrue(
            recovered,
            "device arrival must make readiness truthful again; it stayed \(String(describing: connection.cameraPermissionStatus))"
        )
    }

    /// Auto-connect != auto-camera. The whole point of refreshing readiness on
    /// device arrival is that it must buy nothing else.
    func testDeviceArrivalRefreshesReadinessButNeverStartsTheCamera() async {
        let wearables = ScriptedWearables(permissionResults: [
            .failure(.noDevice),
            .success(.granted),
        ])
        let connection = GlassesConnection(wearables: wearables)
        connection.checkCameraPermission(reportErrors: false)
        _ = await waitUntil { wearables.permissionCheckCount >= 1 }

        wearables.emitDevices(["device-1"])
        _ = await waitUntil { connection.cameraPermissionStatus == .granted }

        XCTAssertEqual(
            wearables.createSessionCount, 0,
            "a device becoming available must not create a capture session"
        )
        #if DEBUG
        XCTAssertEqual(connection.cameraStreamState, .stopped, "the camera must stay off")
        XCTAssertEqual(connection.frameCount, 0, "no frames may be captured without an explicit start")
        #endif
    }

    /// The refresh is bounded by the unknown status, not by an edge, so it must
    /// stop asking the moment it has an answer — otherwise device churn turns
    /// into an unbounded query loop.
    func testReadinessIsNotReReadOnceItIsKnown() async {
        let wearables = ScriptedWearables(permissionResults: [.success(.granted)])
        let connection = GlassesConnection(wearables: wearables)
        _ = await waitUntil { wearables.isSubscribed }

        wearables.emitDevices(["device-1"])
        let known = await waitUntil { connection.cameraPermissionStatus == .granted }
        XCTAssertTrue(known)
        let afterFirstAnswer = wearables.permissionCheckCount

        // Repeated arrivals and departures, as glasses reconnecting would.
        for _ in 0..<5 {
            wearables.emitDevices([])
            wearables.emitDevices(["device-1"])
        }
        try? await Task.sleep(nanoseconds: 200_000_000)

        XCTAssertEqual(
            wearables.permissionCheckCount, afterFirstAnswer,
            "a known permission must not be re-read on every device change"
        )
        XCTAssertEqual(connection.cameraPermissionStatus, .granted)
    }

    /// A warm relaunch: `init` seeds `devices` from `wearables.devices`, so the
    /// first stream yield is not an empty->non-empty transition. An
    /// edge-triggered refresh would never fire here.
    func testReadinessIsRefreshedWhenDevicesWereAlreadyKnownAtLaunch() async {
        let wearables = ScriptedWearables(permissionResults: [.success(.granted)])
        wearables.emitDevices(["device-1"])
        let connection = GlassesConnection(wearables: wearables)
        XCTAssertEqual(connection.devices, ["device-1"], "the fixture must reproduce a warm launch")

        // No new emission: the only yield is the stream replaying a list that
        // was already known. An empty->non-empty edge never occurs here.
        let known = await waitUntil { connection.cameraPermissionStatus == .granted }
        XCTAssertTrue(known, "a pre-seeded device list must still produce a readiness read")
    }

    /// A permission that is genuinely denied is a truthful answer, and must be
    /// recorded as one rather than retried into an alert loop.
    func testADeniedPermissionIsRecordedAndNotRetried() async {
        let wearables = ScriptedWearables(permissionResults: [.success(.denied)])
        let connection = GlassesConnection(wearables: wearables)
        _ = await waitUntil { wearables.isSubscribed }

        wearables.emitDevices(["device-1"])
        let settled = await waitUntil { connection.cameraPermissionStatus == .denied }
        XCTAssertTrue(settled)
        let afterAnswer = wearables.permissionCheckCount

        wearables.emitDevices([])
        wearables.emitDevices(["device-1"])
        try? await Task.sleep(nanoseconds: 200_000_000)

        XCTAssertEqual(wearables.permissionCheckCount, afterAnswer)
        XCTAssertNil(connection.errorMessage, "an automatic read must never raise an alert")
    }
}

// MARK: - Connection lifetime

@MainActor
final class ConnectionLifetimeTests: XCTestCase {

    /// The retain cycle, made a failing test rather than an argument.
    ///
    /// `GlassesConnection` stores the three `Task`s it creates in `init`. If a
    /// task body holds `self` strongly for the life of an unbounded
    /// `for await` — which `guard let self else { return }` placed *outside*
    /// the loop does — then the object owns the task and the task owns the
    /// object, and the `isolated deinit` that stops the camera and the device
    /// session can never run.
    ///
    /// Written after the fix, and verified against the code before it: this
    /// test fails on the old shape and passes on the new one. Without it
    /// nothing in the suite would notice the cycle being reintroduced, and the
    /// pattern is idiomatic enough to come back by accident.
    func testGlassesConnectionDeallocatesWhenReleased() async {
        weak var weakConnection: GlassesConnection?
        do {
            let wearables = ScriptedWearables(permissionResults: [.success(.granted)])
            let connection = GlassesConnection(wearables: wearables)
            weakConnection = connection
            // The `init` tasks subscribe asynchronously, and the probe only
            // means anything once they are actually suspended on their
            // streams — that suspension is where the strong reference would
            // be held. Asserted rather than merely waited for, so this fails
            // loudly instead of passing over streams that were never live.
            for _ in 0..<20 where !wearables.isSubscribed {
                try? await Task.sleep(nanoseconds: 10_000_000)
            }
            XCTAssertTrue(wearables.isSubscribed, "the probe needs live streams to be meaningful")
            withExtendedLifetime(connection) {}
        }
        // Deallocation follows task cancellation in `deinit`, which is not
        // synchronous with the scope exit.
        for _ in 0..<50 {
            if weakConnection == nil { break }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertNil(
            weakConnection,
            "GlassesConnection outlived its last strong reference — isolated deinit never ran"
        )
    }
}

// MARK: - Capture resolution

/// Pins the DEBUG-only capture-resolution control.
///
/// The control exists because the rung was a hardcoded `.low` and Document
/// Memory's premise cannot be tested at 360x640 — its measured word recall is
/// 0.429-0.810 there against 0.957-1.000 at 1280x720. What these tests actually
/// guard is the *other* side of that: World Builder's path is physically proven
/// at `.low`, so the default must not move, and the label must not invent a
/// size DAT did not declare.
///
/// DEBUG-only because `CaptureResolutionPreference` is, and because
/// `MWDATCamera` is imported under `#if DEBUG` in `GlassesConnection.swift`.
#if DEBUG
final class CaptureResolutionPreferenceTests: XCTestCase {

    /// The rung every existing measurement was taken at, including the P3 clean
    /// walk. If this moves, every prior figure silently stops being comparable
    /// and World Builder's proven path changes underneath it.
    func testTheDefaultIsLow() {
        XCTAssertEqual(CaptureResolutionPreference.default, .low)
    }

    /// A fresh connection starts at the default rather than at whatever the
    /// picker last showed — there is no persistence here and there should not
    /// be one, because a rung silently surviving a relaunch is how a walk gets
    /// recorded at the wrong resolution without anyone choosing that.
    @MainActor
    func testAFreshConnectionStartsAtTheDefault() {
        let connection = GlassesConnection(wearables: ScriptedWearables(permissionResults: []))
        XCTAssertEqual(connection.captureResolution, .default)
    }

    /// Three rungs, each mapping to a distinct `StreamingResolution`. A
    /// collapsed mapping would make the picker move while the stream did not.
    func testEachRungMapsToADistinctStreamingResolution() {
        let all = CaptureResolutionPreference.allCases
        XCTAssertEqual(all.count, 3)
        XCTAssertEqual(Set(all.map(\.id)).count, 3, "rung ids must be unique")

        let resolutions = all.map(\.streamingResolution)
        XCTAssertEqual(resolutions.count, 3)
        for (index, lhs) in resolutions.enumerated() {
            for rhs in resolutions[(index + 1)...] {
                XCTAssertNotEqual(lhs, rhs, "two rungs collapsed onto one StreamingResolution")
            }
        }
    }

    /// The displayed size must come from DAT, not from a literal in this app.
    ///
    /// Asserted against `StreamingResolution.videoFrameSize` rather than
    /// against the string "360x640", so that if the SDK ever changes a rung the
    /// label follows it instead of quietly going stale — which is the whole
    /// reason `declaredSizeDescription` reads the SDK at all.
    func testTheDeclaredSizeIsReadFromDATRatherThanHardcoded() {
        for rung in CaptureResolutionPreference.allCases {
            let size = rung.streamingResolution.videoFrameSize
            XCTAssertEqual(
                rung.declaredSizeDescription,
                "\(size.width)x\(size.height)",
                "\(rung.rawValue) must render the size DAT declares"
            )
        }
    }

    /// Ties the default rung to the physical evidence. The P3 clean walk
    /// recorded 108 frames, every one 360x640
    /// (`docs/evidence/2026-08-26-p3-clean-walk-console.txt`). If DAT's `.low`
    /// ever stops meaning that, the corpus and every figure derived from it
    /// stop being comparable, and this test is the tripwire.
    func testLowIsStillTheRungTheWalkWasMeasuredAt() {
        XCTAssertEqual(CaptureResolutionPreference.low.declaredSizeDescription, "360x640")
    }

    /// Every rung needs a picker segment. An empty label renders as a blank
    /// segment the user cannot identify.
    func testEveryRungHasANonEmptyShortLabel() {
        for rung in CaptureResolutionPreference.allCases {
            XCTAssertFalse(rung.shortLabel.isEmpty, "\(rung.rawValue) has no label")
        }
    }
}
#endif
