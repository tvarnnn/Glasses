//
//  CartridgeAvailability.swift
//  Glasses
//

import Foundation

// MARK: - Contract identity

/// The Tower's declaration that it can serve a particular cartridge, and which
/// revision of that agreement it is offering.
///
/// ## What this deliberately does not decide
///
/// The Tower's contracts do not exist yet. Every field below is therefore
/// **opaque to this app**: the identifier is a token the Tower chooses and iOS
/// only ever compares for equality, never parses, orders, or ranges over.
///
/// That opacity is the point. A `version: Int` with a `>=` comparison would
/// have baked in three assumptions the Tower has not agreed to — that contracts
/// are versioned by integer, that versions are totally ordered, and that a
/// newer Tower contract is backward compatible with an older client. All three
/// are plausible and none is ours to decide. Equality against a set of
/// identifiers this build was written against assumes only that the Tower can
/// name the thing it is offering, which any contract scheme must do.
///
/// **There is no wire format here.** No message name, no route, no key. This
/// says only "if and when the Tower tells us which contract it speaks, this is
/// the shape of the answer we will hold onto".
struct CartridgeContract: Equatable, Hashable, Sendable {
    /// Which cartridge the contract is for, using this app's catalog id.
    let cartridgeID: String
    /// An opaque token naming the agreement. Compared for equality only.
    let identifier: String

    init(cartridgeID: String, identifier: String) {
        self.cartridgeID = cartridgeID
        self.identifier = identifier
    }
}

// MARK: - Availability

/// Why a cartridge's Tower backing is, or is not, usable right now.
///
/// Four cartridges need this and they need exactly the same four answers, which
/// is what justifies it being shared rather than restated per cartridge. It is
/// resolved by `resolve(declared:supported:towerStatus:)` below, so the ordering
/// of the checks — which failure wins when several apply — is decided once
/// instead of four times.
enum CartridgeAvailability: Equatable, Sendable {
    /// The Tower has not declared a contract for this cartridge at all. Today
    /// this is the answer for every cartridge, and it is a statement about the
    /// Tower's roadmap rather than about this connection: the module container
    /// is V0.8 and the first module V0.9 (docs/03-ROADMAP.md), so there is
    /// nothing to declare.
    case noContract
    /// The Tower declared a contract this build does not implement. Kept
    /// separate from `noContract` because they call for opposite responses:
    /// one waits for the Tower, the other waits for an app update, and telling
    /// a user to reconnect when they need a new build wastes their time.
    case unsupportedContract(declared: CartridgeContract)
    /// The contract is supported, but the Tower is not reachable, so nothing
    /// can be asked of it. Not an error — a connection state.
    case towerUnreachable
    /// The Tower speaks a contract this build implements and is reachable.
    /// **Unreachable today**, by construction: `TowerCapabilities` declares no
    /// contracts and this build supports none.
    case available(CartridgeContract)

    /// Whether a request may be made at all.
    var isAvailable: Bool {
        if case .available = self { return true }
        return false
    }

    /// One sentence for a person, written so a view never has to compose an
    /// explanation of its own — that is how "not yet built" turns into
    /// "something went wrong" on screen.
    ///
    /// `nil` when available: there is nothing to explain, and a caller that
    /// forgets to handle the available case gets no string rather than a
    /// reassuring one.
    func explanation(cartridgeName: String) -> String? {
        switch self {
        case .noContract:
            return """
                The Tower does not run \(cartridgeName) yet. It has no module \
                runtime at all — frames sent from this app reach its current \
                fixed handler, which returns a simple per-frame result and \
                nothing else.
                """
        case .unsupportedContract(let contract):
            return """
                The Tower offers a \(cartridgeName) contract this version of \
                the app does not understand (\(contract.identifier)). Nothing \
                is shown rather than something guessed. Updating the app is \
                what resolves this.
                """
        case .towerUnreachable:
            return "The Tower is not connected, so \(cartridgeName) has nothing to report."
        case .available:
            return nil
        }
    }

    /// The phase a cartridge is in *because of* its availability, when
    /// availability alone settles the question.
    ///
    /// `nil` means availability does not settle it — the cartridge is usable
    /// and its own state decides. Keeping this here rather than in each
    /// cartridge is what stops one of them from rendering an unreachable Tower
    /// as `idle`, which would invite a user to press a button that cannot work.
    var forcedPhase: CartridgePhase? {
        switch self {
        case .noContract, .unsupportedContract: return .unsupported
        // Not `.unsupported`. A Tower that is merely unreachable may well be
        // able to do this, and drawing it with the same headline and glyph as
        // "will never do this" is the half of the distinction a person actually
        // reads — the explanation string was carrying it alone.
        case .towerUnreachable: return .disconnected
        case .available: return nil
        }
    }

    /// The unavailable explanation, joined with whatever the cartridge's own
    /// client had to add.
    ///
    /// Extracted because all four workspaces were restating the same join —
    /// which of the two sentences comes first, and what happens when either is
    /// absent. The per-cartridge part (which of its own states yields a reason)
    /// stays in the cartridge, where it belongs; the ordering is a shared
    /// invariant and belongs here.
    ///
    /// Joined rather than concatenated: a stray blank paragraph in a panel
    /// reads as a missing string, which is how a reader starts to distrust the
    /// rest of it.
    func explanation(cartridgeName: String, clientReason: String?) -> String {
        let shared = explanation(cartridgeName: cartridgeName)
        let client = (clientReason?.isEmpty ?? true) ? nil : clientReason
        switch (shared, client) {
        case (nil, nil): return ""
        case (let shared?, nil): return shared
        case (nil, let client?): return client
        case (let shared?, let client?): return shared + "\n\n" + client
        }
    }

    // MARK: Resolution

    /// Decides availability from the three facts that determine it.
    ///
    /// Pure, so the decision is testable without a socket, and written once so
    /// the precedence is uniform: **what the Tower can do outranks whether we
    /// can currently reach it.** A cartridge the Tower will never serve should
    /// say so even while connected, and an unsupported contract is not fixed by
    /// reconnecting — reporting `towerUnreachable` first would send a user
    /// round a loop that cannot terminate.
    ///
    /// - Parameters:
    ///   - declared: what the Tower says it offers for this cartridge, or `nil`
    ///     if it has said nothing. Today always `nil`.
    ///   - supported: the contract identifiers this build implements. Today
    ///     always empty.
    ///   - isTowerReachable: whether the connection is currently up.
    static func resolve(
        declared: CartridgeContract?,
        supported: Set<String>,
        isTowerReachable: Bool
    ) -> CartridgeAvailability {
        guard let declared else { return .noContract }
        guard supported.contains(declared.identifier) else {
            return .unsupportedContract(declared: declared)
        }
        return isTowerReachable ? .available(declared) : .towerUnreachable
    }
}

// MARK: - Failure

/// A cartridge-level failure, stated so a view can show it without inventing
/// wording and a test can assert what it is without matching prose.
///
/// Shared because all four cartridges fail the same ways, and because Rule 3
/// (Truthful State Only, docs/02-DEVELOPMENT-RULES.md) makes "the backend
/// failed" a state the UI must be able to reach — a cartridge that can only
/// render success and emptiness will render a failure as emptiness.
struct CartridgeFailure: Equatable, Sendable, Error {
    enum Kind: String, Equatable, Sendable, CaseIterable {
        /// This app refused locally, because the Tower has no contract for the
        /// thing being asked for.
        ///
        /// Deliberately **not** `towerReportedFailure`. The Tower reported
        /// nothing — there may not even be a socket open — and attributing a
        /// local refusal to the other machine is a fabricated claim about it
        /// (Rule 3), which is exactly what a later log or telemetry consumer
        /// would read back as fact.
        case notSupported
        /// The Tower reported that the module itself failed
        /// (docs/04-MODULE-SYSTEM.md — Failure).
        case towerReportedFailure
        /// The connection dropped or the request never completed.
        case transport
        /// The Tower's answer could not be understood as the contract this
        /// build implements. Distinct from `unsupportedContract` availability:
        /// that is a disagreement known in advance, this is one discovered on
        /// arrival.
        case undecodableResponse
        /// A bounded operation ran out of time (Rule 15, Bounded Operations).
        case timedOut
    }

    let kind: Kind
    /// What to show a person. Required, and non-empty by construction below —
    /// an error with no explanation is how "something went wrong" ends up on
    /// screen attached to nothing.
    let message: String

    init(kind: Kind, message: String) {
        self.kind = kind
        // An empty message would render as a blank failure panel. Substituting
        // the kind is worse than prose but strictly better than nothing, and it
        // keeps the type's guarantee absolute rather than by convention.
        self.message = message.isEmpty ? "The \(kind.rawValue) step failed." : message
    }

    /// Wraps an arbitrary error, passing a `CartridgeFailure` through unchanged.
    ///
    /// The two clients that accept a request were each restating this ladder;
    /// deciding once means a future third cannot decide differently. An error
    /// that is not already a cartridge failure is `.transport` — it came from
    /// somewhere below this layer, and that is the only honest attribution
    /// available without knowing where.
    static func wrapping(_ error: Error) -> CartridgeFailure {
        if let failure = error as? CartridgeFailure { return failure }
        return CartridgeFailure(kind: .transport, message: error.localizedDescription)
    }
}
