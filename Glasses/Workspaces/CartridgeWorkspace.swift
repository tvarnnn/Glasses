//
//  CartridgeWorkspace.swift
//  Glasses
//

import Foundation

/// A primary workspace this app can present for a cartridge.
///
/// ## Why this is separate from `CartridgeStatus`
///
/// The two answer different questions, about different machines, and conflating
/// them would produce a lie in one direction or the other:
///
/// - `CartridgeStatus` describes a **module's position on the Tower roadmap**
///   — `next`, `planned`, `future`. It is deliberately missing an `available`
///   case, because no module runtime exists on the Tower at all: the module
///   container is V0.8 and the first module V0.9 (docs/03-ROADMAP.md), and
///   `ProductShellTests` fails loudly if that ever silently changes.
///
/// - `CartridgeWorkspace` describes whether **this app has a screen** for the
///   cartridge. That is a fact about the iPhone, and it is true today for World
///   Builder whatever the Tower can or cannot do.
///
/// Keeping them apart is what lets the drawer open a World Builder workspace
/// without any of it implying the Tower is running World Builder. Opening a
/// workspace is local navigation. It sends nothing, selects nothing on the
/// Tower, and changes no Tower state — docs/08-IOS-CARTRIDGE-SHELL.md forbids
/// inventing a module-selection message, and none is invented.
///
/// A cartridge with no workspace stays exactly as it was: an informational row.
enum CartridgeWorkspace: String, Equatable, Sendable {
    case worldBuilder
}

extension Cartridge {
    /// The cartridge whose workspace is currently open, resolved from a stored
    /// identifier.
    ///
    /// Returns `nil` for an unknown id **and** for a cartridge that has no
    /// workspace, so a persisted selection can never resurrect a screen that no
    /// longer exists or was never navigable. That matters across app updates:
    /// a stored id outlives the build that wrote it.
    static func workspaceCartridge(forID id: String?) -> Cartridge? {
        guard let id, !id.isEmpty else { return nil }
        guard let cartridge = catalog.first(where: { $0.id == id }) else { return nil }
        return cartridge.workspace == nil ? nil : cartridge
    }

    /// Every cartridge the drawer may present as openable.
    static var selectable: [Cartridge] {
        catalog.filter { $0.workspace != nil }
    }
}
