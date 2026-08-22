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
///
/// ## Four cases, and still an enum
///
/// Product Shell V2 had one case and argued that a `switch` beat a workspace
/// registry. Four is the number at which that argument is usually abandoned in
/// favour of a protocol and a lookup table, so it is worth restating why it
/// holds better now than it did then, not worse:
///
/// - the set is still **closed and compiled in**. A workspace is a SwiftUI view
///   in this binary; there is no dynamic module list to render
///   (`docs/04-MODULE-SYSTEM.md` forbids building one before V1.0), so nothing
///   can appear here that was not compiled;
/// - exhaustiveness is the feature. Adding a case makes the compiler demand the
///   arm in `ContentView`, where a registry would silently fall back to Home;
/// - the anti-pattern the roadmap warns about is per-cartridge *conditionals
///   scattered through one enormous view*. There is exactly one `switch`, in
///   one place, whose arms are one-line constructor calls into separate files.
///
/// What did change is that the four workspaces now share a *client* layer —
/// `CartridgeClient`, `CartridgeAvailability`, `CartridgePhase` — because that
/// is where the genuine commonality turned out to be. The screens have almost
/// nothing in common; the question "may this be used, and why not" is identical
/// for all four.
enum CartridgeWorkspace: String, Equatable, Sendable, CaseIterable {
    case worldBuilder
    case experimentalCV
    case documentMemory
    case sceneUnderstanding
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
