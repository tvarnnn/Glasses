//
//  CartridgeResultChannel.swift
//  Glasses
//

import Foundation

/// The Tower's structured result channel, as it actually exists on the wire.
///
/// Contract: `docs/contracts/CARTRIDGE-RESULTS.md`, envelope
/// `cartridge_results.envelope/2026-08-23`. Every type here is a decoding of a
/// message the Tower genuinely sends today — verified against
/// `tower/tower/results/` and `tower/tower/routes/results_ws.py`, not against a
/// summary of them.
///
/// ## Why this is cartridge-blind
///
/// The envelope is generic and the `payload` is not. Nothing in this file knows
/// what a world is; it carries `payload` through as the dictionary the Tower
/// sent, and the cartridge that owns the contract decodes it. That is the same
/// split the Tower enforces on its own side with
/// `test_the_result_channel_core_is_cartridge_blind`, and it is what lets a
/// second cartridge arrive without touching the transport.
///
/// ## Why `[String: Any]` rather than `Codable`
///
/// `TowerClient` already decodes every inbound message with
/// `JSONSerialization`, and the Tower's error messages are deliberately
/// heterogeneous — `result_error` carries different extra keys per `reason`,
/// `result_unsubscribed` carries two keys and no `envelope_contract`, and
/// `frame_result` omits `mean_intensity` rather than nulling it. A strict
/// `Decodable` over that shape is a decoder that fails on messages the Tower
/// considers well-formed. Reading the keys we need and ignoring the rest is the
/// tolerant half of the robustness rule, and the contract's "any field may be
/// null, and null means absent" makes it the correct half.

// MARK: - Capability declaration

/// One cartridge the Tower declares it can report on.
///
/// `available == false` is **not** the same as absent: the Tower is saying it
/// knows this cartridge and cannot serve it right now, and
/// `unavailableReason` is prose for a person explaining which. A cartridge the
/// Tower says nothing about simply does not appear.
struct TowerCartridgeOffer: Equatable, Sendable {
    /// The Tower's name for the cartridge (`"world_builder"`), which is not the
    /// same string as this app's catalog id (`"world-build"`). The mapping
    /// lives in `TowerCapabilities`, in one place.
    let cartridge: String
    let resultType: String
    /// Opaque. Compared for equality only — never parsed, never ordered.
    let contract: String
    let available: Bool
    /// Prose, when `available` is false. Shown verbatim.
    let unavailableReason: String?
    /// Whether every result is a complete snapshot. `true` today, and present
    /// so a future delta mode cannot be mistaken for this one.
    let snapshotOnly: Bool

    init?(json: [String: Any]) {
        guard
            let cartridge = json["cartridge"] as? String,
            let resultType = json["result_type"] as? String,
            let contract = json["contract"] as? String
        else { return nil }
        self.cartridge = cartridge
        self.resultType = resultType
        self.contract = contract
        self.available = json["available"] as? Bool ?? false
        self.unavailableReason = json["unavailable_reason"] as? String
        self.snapshotOnly = json["snapshot_only"] as? Bool ?? true
    }
}

/// The Tower's answer to `{"type":"cartridges"}`.
///
/// `not_offered` is deliberately **not** decoded. The contract states it exists
/// for operators and that presence there must never be read as an offer — and
/// both "listed as not offered" and "absent entirely" mean the same thing to
/// this app: the Tower has declared no contract, so `CartridgeAvailability`
/// resolves `.noContract`. Decoding it would create a second way to ask a
/// question that already has one answer.
struct TowerCartridgeDeclaration: Equatable, Sendable {
    let envelopeContract: String?
    let offers: [TowerCartridgeOffer]

    init(envelopeContract: String?, offers: [TowerCartridgeOffer]) {
        self.envelopeContract = envelopeContract
        self.offers = offers
    }

    init(json: [String: Any]) {
        self.envelopeContract = json["envelope_contract"] as? String
        let raw = json["cartridges"] as? [[String: Any]] ?? []
        // An explicit loop rather than `compactMap(TowerCartridgeOffer.init)`:
        // the target defaults to `MainActor` isolation, and a function
        // reference handed to `compactMap` is called from a nonisolated
        // context. Decoding an offer is pure, but staying inside the isolated
        // caller is simpler than declaring that.
        var decoded: [TowerCartridgeOffer] = []
        for entry in raw {
            if let offer = TowerCartridgeOffer(json: entry) { decoded.append(offer) }
        }
        self.offers = decoded
    }

    func offer(forTowerCartridge name: String) -> TowerCartridgeOffer? {
        offers.first { $0.cartridge == name }
    }
}

// MARK: - Subscription

/// The Tower's acknowledgement of a `result_subscribe`.
///
/// `subscriptionID` is unique **per connection** and restarts at `sub-1` on
/// every new socket, which is why nothing stores it across a reconnect.
struct CartridgeSubscriptionAck: Equatable, Sendable {
    let subscriptionID: String
    let cartridge: String
    let resultType: String
    let contract: String?
    /// `absent`, `matched`, `stale` or `unrecognised`. Advisory only — the
    /// first result is a complete snapshot regardless.
    let cursorStatus: String?

    init?(json: [String: Any]) {
        guard
            let subscriptionID = json["subscription_id"] as? String,
            let cartridge = json["cartridge"] as? String,
            let resultType = json["result_type"] as? String
        else { return nil }
        self.subscriptionID = subscriptionID
        self.cartridge = cartridge
        self.resultType = resultType
        self.contract = json["contract"] as? String
        self.cursorStatus = json["cursor_status"] as? String
    }
}

// MARK: - Result envelope

/// One `cartridge_result`: a complete snapshot, never a delta.
///
/// The `payload` is passed through undecoded. Everything above it is the
/// generic envelope every cartridge shares.
struct CartridgeResultEnvelope {
    let subscriptionID: String?
    let cartridge: String
    let resultType: String
    let contract: String?
    /// Dense per subscription, starting at 1. A gap is corruption, never a
    /// drop — the channel has no queue to drop from.
    let sequence: Int?
    /// Opaque change identity. Equality only.
    let revision: String?
    /// Whether `revision` differs from the one last sent on this subscription.
    /// `false` on the ~2 s heartbeat that refreshes the fields excluded from
    /// the revision hash.
    let revisionChanged: Bool
    /// How many snapshots were superseded in our slot since the last delivery.
    /// `> 0` means we read slowly; it does **not** mean information was lost,
    /// because every snapshot is complete.
    let coalesced: Int
    /// Always `true` today.
    let isSnapshot: Bool
    let payload: [String: Any]

    init?(json: [String: Any]) {
        guard
            let cartridge = json["cartridge"] as? String,
            let resultType = json["result_type"] as? String,
            let payload = json["payload"] as? [String: Any]
        else { return nil }
        self.subscriptionID = json["subscription_id"] as? String
        self.cartridge = cartridge
        self.resultType = resultType
        self.contract = json["contract"] as? String
        self.sequence = json["seq"] as? Int
        self.revision = json["revision"] as? String
        self.revisionChanged = json["revision_changed"] as? Bool ?? true
        self.coalesced = json["coalesced"] as? Int ?? 0
        self.isSnapshot = json["snapshot"] as? Bool ?? true
        self.payload = payload
    }
}

// MARK: - Errors

/// A `result_error`. **None of these close the socket** — the frame path keeps
/// working through every one.
///
/// Every field but `reason` and `message` is optional because the Tower's
/// extras genuinely vary by reason: `unknown_subscription` names only the
/// subscription, `unknown_cartridge` names the cartridge and what is offered,
/// and the two unsolicited errors carry no `envelope_contract` at all.
struct CartridgeResultError: Equatable, Sendable {
    /// One of the ten codes in the contract. Compared as a string rather than
    /// modelled as an enum: an unrecognised code must still be shown to a
    /// person rather than collapsed into "unknown".
    let reason: String
    let message: String
    let subscriptionID: String?
    let cartridge: String?
    let resultType: String?

    init?(json: [String: Any]) {
        guard let reason = json["reason"] as? String else { return nil }
        self.reason = reason
        self.message = json["message"] as? String ?? reason
        self.subscriptionID = json["subscription_id"] as? String
        self.cartridge = json["cartridge"] as? String
        self.resultType = json["result_type"] as? String
    }

    /// The two the Tower sends unsolicited, after which the subscription is
    /// gone and a new `result_subscribe` is the only way to resume.
    var closesSubscription: Bool {
        reason == "consumer_too_slow" || reason == "channel_failed"
    }
}

// MARK: - Events

/// Everything the result channel can deliver, as one stream.
///
/// A single enum rather than five publishers so that ordering between them is
/// preserved: a `result_subscribed` and the `cartridge_result` that
/// immediately follows it must not be observed out of order, and separate
/// subjects would make that a scheduling accident.
enum CartridgeResultEvent {
    case declaration(TowerCartridgeDeclaration)
    case subscribed(CartridgeSubscriptionAck)
    case unsubscribed(subscriptionID: String)
    case result(CartridgeResultEnvelope)
    case failed(CartridgeResultError)
}
