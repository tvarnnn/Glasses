//
//  CartridgeClient.swift
//  Glasses
//

import Foundation

/// What the Tower has told this app it can do, per cartridge.
///
/// ## The single place the answer "nothing" is written down
///
/// The Tower declares no cartridge contracts, because it has no module runtime
/// to declare them for. That is one fact, and it belongs in one file rather
/// than restated in four clients where it would rot at different rates.
///
/// It is written as a lookup rather than as four hardcoded `.noContract`
/// literals so that the arrival of a real contract is an edit *here* plus a
/// client that can decode it — not a hunt through every cartridge for the place
/// its unavailability was hardcoded.
///
/// **Nothing in this type is a wire contract.** There is no discovery message,
/// no registry fetch, and no route. `docs/04-MODULE-SYSTEM.md` forbids the iOS
/// app from building dynamic discovery speculatively, and
/// `docs/08-IOS-CARTRIDGE-SHELL.md` forbids adding a module-selection message —
/// so `declared` is a local table that is empty, not a request that returns
/// empty. When the Tower can genuinely declare capabilities, this becomes the
/// place its declaration is cached, and the shape of every consumer is
/// unchanged.
enum TowerCapabilities {

    /// Contracts the Tower has declared. **Empty, and that is the whole truth
    /// of the current system**, not a placeholder awaiting fixtures.
    ///
    /// A test asserts this is empty; when the first real contract lands, that
    /// test failing is the intended signal to review every consumer rather than
    /// a nuisance to delete.
    static let declared: [String: CartridgeContract] = [:]

    /// Contract identifiers this build implements. Empty for the same reason:
    /// there is nothing to implement against.
    ///
    /// Kept separate from `declared` because they answer different questions
    /// about different machines, and because their disagreement is exactly what
    /// `CartridgeAvailability.unsupportedContract` exists to represent.
    static let supported: Set<String> = []

    static func declaredContract(for cartridgeID: String) -> CartridgeContract? {
        declared[cartridgeID]
    }

    /// Availability for one cartridge, given the current connection.
    ///
    /// The only entry point clients use, so the precedence rules in
    /// `CartridgeAvailability.resolve` apply uniformly and no cartridge can
    /// quietly decide it is available on different grounds.
    static func availability(for cartridgeID: String, isTowerReachable: Bool) -> CartridgeAvailability {
        CartridgeAvailability.resolve(
            declared: declaredContract(for: cartridgeID),
            supported: supported,
            isTowerReachable: isTowerReachable
        )
    }
}

/// The seam every cartridge's Tower client sits behind.
///
/// ## What it is for, and what it deliberately is not
///
/// This is the *shared* half of a cartridge client: which cartridge it serves,
/// and whether it can serve it. Everything else — what it fetches, what it
/// returns, what its lifecycle looks like — belongs to the cartridge's own
/// protocol, because those four things have nothing in common. World Builder
/// pushes a continuous stream; Document Memory answers point queries;
/// Experimental CV Lab runs a bounded job; Scene Understanding publishes a
/// changing set of tracks. Forcing one `fetch<T>()` over all four would be a
/// plugin framework wearing a protocol's clothes, and
/// docs/02-DEVELOPMENT-RULES.md Rule 10 exists to stop exactly that.
///
/// So: no `associatedtype`, no generic request/response, no transport. A
/// cartridge client conforms to this *and* to its own protocol, and the second
/// one is where the real work is described.
///
/// `@MainActor` and `AnyObject` to match `TowerClient` and `GlassesConnection`:
/// a real implementation will hold a subscription and publish into SwiftUI on
/// the main actor, as those already do.
@MainActor
protocol CartridgeClient: AnyObject {
    /// The catalog id from `Cartridge.catalog`. Used to look the cartridge's
    /// contract up, and asserted in tests so a client cannot answer for a
    /// cartridge that is not its own.
    var cartridgeID: String { get }

    /// Whether this client can currently reach a Tower capability, and if not,
    /// why. Recomputed rather than stored, so it cannot go stale against a
    /// connection that changed underneath it.
    func availability(isTowerReachable: Bool) -> CartridgeAvailability
}

extension CartridgeClient {
    /// The default every client uses today, and the reason `TowerCapabilities`
    /// is a lookup: a client does not get to decide it is available.
    func availability(isTowerReachable: Bool) -> CartridgeAvailability {
        TowerCapabilities.availability(for: cartridgeID, isTowerReachable: isTowerReachable)
    }
}
