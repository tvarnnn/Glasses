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
