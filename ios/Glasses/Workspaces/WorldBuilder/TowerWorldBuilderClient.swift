//
//  TowerWorldBuilderClient.swift
//  Glasses
//

import Combine
import Foundation

// MARK: - The contract this build implements

/// The one World Builder agreement this build was written against.
///
/// Opaque, and compared for equality only. It is dated rather than numbered
/// precisely so that nobody is tempted to compute which is greater: a mismatch
/// means "we are not talking about the same agreement", which is neither newer
/// nor older, and `CartridgeAvailability.unsupportedContract` is the honest
/// rendering of it.
enum WorldBuilderResultContract {
    /// The **Tower's** name for the cartridge. Not this app's catalog id
    /// (`"world-build"`); the two strings are different and the mapping lives
    /// in `TowerCapabilities`.
    static let towerCartridge = "world_builder"
    static let resultType = "status"
    static let identifier = "world_builder.status/2026-08-23"
}

// MARK: - Payload decoding

/// Turns the Tower's `world_builder.status` payload into the types the
/// workspace already had.
///
/// ## Why the mapping is this thin
///
/// Because the Tower does it. `model_state` names a `WorldModelState` case and
/// `world_snapshot` is shaped onto `WorldSnapshot` field for field — deliberately,
/// so that the translation table lives on the machine where changing it is a
/// restart rather than an App Store release. Everything else in the payload is
/// Tower-native evidence for those two values; this decoder reads neither, and
/// a reader looking for where the `lifecycle`/`progress`/`geometry` blocks are
/// consumed will correctly find that they are not.
///
/// ## What it refuses to do
///
/// Absent stays absent. Every optional here is `nil` when the key is missing or
/// null, and nothing is defaulted to zero — the contract is explicit that
/// `null ≠ 0`, and `frames_observed` being genuinely unknowable during a live
/// session is the reason it says so.
enum WorldBuilderResultDecoder {

    /// The state the payload describes, or `nil` when it could not be read as
    /// this contract at all — which the caller renders as a decode failure
    /// rather than as an empty world.
    static func modelState(from payload: [String: Any]) -> WorldModelState? {
        guard let word = payload["model_state"] as? String else { return nil }
        let reason = payload["model_state_reason"] as? String
        // `if let` rather than `Optional.map(snapshot(from:))`, for the reason
        // `TowerCartridgeDeclaration.init` gives: a function reference passed
        // to `map` is called from a nonisolated context under this target's
        // default `MainActor` isolation.
        var snapshot: WorldSnapshot?
        if let raw = payload["world_snapshot"] as? [String: Any] {
            snapshot = self.snapshot(from: raw)
        }

        switch word {
        case "unsupported":
            return .unsupported(reason: reason ?? Self.unexplainedUnsupported)

        case "idle":
            return .idle

        case "receiving":
            // A live session with nothing yet said about a world is exactly
            // what `.awaitingFirstUpdate` means. Substituting an empty
            // snapshot would draw a world panel with every row missing, which
            // reads as a broken world rather than as an early one.
            guard let snapshot else { return .awaitingFirstUpdate }
            return .receiving(snapshot)

        case "finalizing":
            // The Tower's own caveat, carried as-is: this state means "the
            // stored figures are not the final figures", **not** "a process is
            // working right now". Tower cannot observe the latter — the writer
            // lock is released before the build starts — and `WorldModelState`
            // documents `.finalizing` as the case where the world on screen is
            // not yet the world that will be stored, which is the same claim.
            return .finalizing(snapshot ?? WorldSnapshot())

        case "finalized":
            return .finalized(snapshot ?? WorldSnapshot())

        case "failed":
            return .failed(
                CartridgeFailure(
                    kind: .towerReportedFailure,
                    message: reason ?? "The Tower reported that its World Builder session failed."
                )
            )

        default:
            // A `model_state` this build does not know is a contract
            // disagreement discovered on arrival, which is precisely
            // `.undecodableResponse` rather than `.notSupported`.
            return nil
        }
    }

    static let unexplainedUnsupported = """
        This Tower cannot serve World Builder, and did not say why.
        """

    /// `world_snapshot` → `WorldSnapshot`.
    ///
    /// The three nested blocks are always present when `world_snapshot` is, so
    /// their absence here is treated as an empty report rather than as an
    /// error: a snapshot that lost its geometry block still carries a truthful
    /// keyframe count, and refusing the whole thing would show less than the
    /// Tower said.
    static func snapshot(from json: [String: Any]) -> WorldSnapshot {
        let geometry = json["geometry"] as? [String: Any] ?? [:]
        let trajectory = json["trajectory"] as? [String: Any] ?? [:]
        let persistence = json["persistence"] as? [String: Any] ?? [:]

        return WorldSnapshot(
            name: json["name"] as? String,
            worldID: json["world_id"] as? String,
            keyframeCount: json["keyframe_count"] as? Int,
            revision: json["revision"] as? String,
            tracking: tracking(json["tracking"] as? String),
            scale: scale(json["scale"] as? String),
            mappingSeconds: json["mapping_seconds"] as? Double,
            calibration: calibration(json["calibration"] as? String),
            geometry: WorldGeometryReport(
                representation: geometry["representation"] as? String,
                elementCount: geometry["element_count"] as? Int,
                isIncremental: geometry["is_incremental"] as? Bool
            ),
            trajectory: WorldTrajectoryReport(
                poseCount: trajectory["pose_count"] as? Int,
                pathLength: trajectory["path_length"] as? Double,
                pathLengthUnit: trajectory["path_length_unit"] as? String,
                // Carried separately from the snapshot's own scale: a spatial
                // figure travels with its own provenance, and the two can
                // legitimately differ.
                scale: scale(trajectory["scale"] as? String)
            ),
            persistence: self.persistence(
                state: persistence["state"] as? String,
                revision: persistence["revision"] as? String
            )
        )
    }

    /// `limited` is in the Tower's vocabulary nowhere — it would need a
    /// threshold nobody has defined — so it is not produced today. It is still
    /// mapped, because the iOS case exists and silently folding a future
    /// `limited` into `.unavailable` would understate a real report.
    static func tracking(_ word: String?) -> WorldTrackingQuality {
        switch word {
        case "good": return .good
        case "limited": return .limited
        case "lost": return .lost
        default: return .unavailable
        }
    }

    /// The Tower sends **iOS's** scale vocabulary, not its own — `relative`,
    /// `inferredMetric`, `measuredMetric`, `unknown`. The last two have no code
    /// path that produces them on monocular hardware and will not arrive; they
    /// are mapped anyway rather than discarded, because a value that did arrive
    /// and was silently downgraded to `.relative` would understate a metric
    /// claim, and `.unknown` is a strictly weaker claim than `.relative` — it
    /// means the reconstruction has no unit at all.
    static func scale(_ word: String?) -> WorldScaleSemantics {
        switch word {
        case "relative": return .relative
        case "inferredMetric": return .inferredMetric
        case "measuredMetric": return .measuredMetric
        default: return .unknown
        }
    }

    /// `calibrating` is never sent — calibration is an offline procedure run
    /// before a session, so there is no in-session state to be in the middle
    /// of — and there is deliberately no percentage anywhere in the contract.
    static func calibration(_ word: String?) -> WorldCalibrationState {
        switch word {
        case "calibrated": return .calibrated
        case "uncalibrated": return .uncalibrated
        case "calibrating": return .calibrating
        default: return .unknown
        }
    }

    /// `saved` is the only state the Tower reaches — World Builder persists by
    /// construction, which makes `.session` unreachable rather than merely
    /// unused.
    static func persistence(state: String?, revision: String?) -> WorldPersistenceState {
        switch state {
        case "saved": return .saved(revision: revision)
        case "session": return .session
        case "reloading": return .reloading
        default: return .unknown
        }
    }
}

// MARK: - The client

/// The Tower-backed World Builder client.
///
/// ## Where it sits
///
/// ```
/// TowerClient            owns the socket, decodes the envelope, knows no cartridge
///     ↓ cartridgeResults
/// TowerWorldBuilderClient   owns the subscription and the World Builder contract
///     ↓ stateUpdates
/// WorldBuilderViewModel     republishes into SwiftUI
///     ↓
/// WorldCanvasView           renders facts
/// ```
///
/// It is constructed by `ProjectManager` and held in `CartridgeClients`, so it
/// **outlives every workspace switch** — which is the whole reason that
/// container exists. A partly-built world survives closing the cartridge, and
/// nothing here is torn down by SwiftUI.
///
/// ## What it does not own
///
/// No socket. It holds a reference to the one `TowerClient` the app already
/// has and sends three message types over it; it never opens a connection,
/// never reconnects, and never touches the frame path. `GlassesConnection` is
/// not reachable from here at all.
///
/// ## Reconnect
///
/// There is no delta stream, so there is no gap, so a reconnect cannot lose
/// data: subscribe again and the first message is a complete snapshot.
/// `subscriptionID` restarts at `sub-1` on every socket, so it is cleared
/// whenever the connection leaves `.online` and re-earned on the way back.
///
/// The last known state is **not** cleared on a drop. Availability already
/// resolves to `.towerUnreachable` while the socket is down, and
/// `CartridgeAvailability.forcedPhase` makes that outrank any domain state — so
/// the screen says "disconnected" without this client having to fabricate a
/// world that stopped existing. When the socket returns, the next snapshot
/// replaces whatever was held.
@MainActor
final class TowerWorldBuilderClient: WorldBuilderClient {

    let cartridgeID = "world-build"

    private(set) var state: WorldModelState = .idle {
        didSet {
            guard state != oldValue else { return }
            log(state)
            stateSubject.send(state)
        }
    }

    var stateUpdates: AnyPublisher<WorldModelState, Never> {
        stateSubject.eraseToAnyPublisher()
    }

    private let stateSubject = PassthroughSubject<WorldModelState, Never>()
    private let tower: TowerClient
    private var cancellables: Set<AnyCancellable> = []

    /// The open subscription on the **current** socket, or `nil`. Cleared on
    /// every disconnect because the Tower's ids are per connection.
    private var subscriptionID: String?
    /// A `result_subscribe` has been sent and not yet answered. Without this a
    /// declaration republished while the ack is in flight would open a second
    /// subscription for the same cartridge.
    private var isSubscribing = false

    /// Resubscribes spent on the current connection.
    ///
    /// `consumer_too_slow` and `channel_failed` close a subscription and are
    /// recoverable by subscribing again — but a Tower that closes every
    /// subscription immediately would otherwise have this client resubscribing
    /// in a loop for as long as the socket stayed up. Bounded, and refilled by
    /// a new connection, for the same reason `TowerClient`'s reconnect schedule
    /// is bounded: a failure that will not resolve must become visible rather
    /// than stay in motion.
    private var resubscribesUsed = 0
    private static let resubscribeBudget = 3

    init(tower: TowerClient) {
        self.tower = tower

        // `.receive(on:)` on both, and it is load-bearing rather than
        // stylistic. A `@Published` publisher fires from `willSet`, so a sink
        // that reads the property it was notified about sees the value *before*
        // the change — a connection that had just come online still read
        // `.offline`, and a declaration that had just arrived still read `nil`,
        // so nothing ever subscribed. Deferring to the next main-queue turn is
        // what `WorldBuilderViewModel` and `ProjectManager`'s bridges already
        // do, for the same reason.
        tower.$status
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] status in self?.connectionChanged(to: status) }
            .store(in: &cancellables)

        tower.$cartridgeDeclaration
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.subscribeIfPossible() }
            .store(in: &cancellables)

        tower.cartridgeResults
            .sink { [weak self] event in self?.handle(event) }
            .store(in: &cancellables)
    }

    // MARK: Availability

    /// Resolved against the Tower's **live** declaration rather than the static
    /// table in `TowerCapabilities`.
    ///
    /// That table is still the right answer for the three cartridges the Tower
    /// offers no contract for. World Builder is the first one it does, and the
    /// declaration arrives over the socket — so reading a compile-time constant
    /// here would report `.noContract` against a Tower that had just said
    /// otherwise.
    func availability(isTowerReachable: Bool) -> CartridgeAvailability {
        TowerCapabilities.availability(
            for: cartridgeID,
            declaredBy: tower.cartridgeDeclaration,
            isTowerReachable: isTowerReachable
        )
    }

    // MARK: Connection lifecycle

    private func connectionChanged(to status: TowerStatus) {
        guard status == .online else {
            // The subscription belonged to a socket that is gone. Nothing is
            // sent to close it — the Tower treats a closed socket as
            // sufficient cleanup — and nothing about the world is forgotten,
            // because availability already reports the connection truthfully.
            subscriptionID = nil
            isSubscribing = false
            return
        }
        resubscribesUsed = 0
        subscribeIfPossible()
    }

    /// Idempotent by construction: every path back into it is guarded by the
    /// same two flags, so a status change and a republished declaration racing
    /// each other cannot open two subscriptions.
    private func subscribeIfPossible() {
        guard tower.status == .online, subscriptionID == nil, !isSubscribing else { return }
        guard let declaration = tower.cartridgeDeclaration else { return }
        guard let offer = declaration.offer(forTowerCartridge: WorldBuilderResultContract.towerCartridge)
        else {
            // The Tower said nothing about World Builder. Availability already
            // renders that as `.noContract`; there is nothing to subscribe to
            // and nothing for the domain state to add.
            return
        }
        guard TowerCapabilities.supported.contains(offer.contract) else {
            // A contract this build does not implement. `.unsupportedContract`
            // availability already outranks any state, so the state is left
            // where it was rather than being given a second, weaker wording of
            // the same fact.
            return
        }
        guard offer.available else {
            // Offered and unserveable — no world root configured, typically.
            // The Tower's own prose is the only honest explanation available,
            // so it is shown verbatim.
            state = .unsupported(
                reason: offer.unavailableReason ?? WorldBuilderResultDecoder.unexplainedUnsupported
            )
            return
        }

        isSubscribing = true
        state = .awaitingFirstUpdate
        tower.subscribeToResults(
            cartridge: offer.cartridge,
            resultType: offer.resultType,
            contract: offer.contract
        )
    }

    // MARK: Result channel

    private func handle(_ event: CartridgeResultEvent) {
        switch event {
        case .declaration:
            // Handled through `$cartridgeDeclaration` instead, so the cached
            // value and the trigger cannot disagree.
            break

        case .subscribed(let ack):
            guard ack.cartridge == WorldBuilderResultContract.towerCartridge else { return }
            subscriptionID = ack.subscriptionID
            isSubscribing = false

        case .unsubscribed(let id):
            guard id == subscriptionID else { return }
            subscriptionID = nil

        case .result(let envelope):
            guard envelope.cartridge == WorldBuilderResultContract.towerCartridge else { return }
            apply(envelope)

        case .failed(let error):
            guard isOurs(error) else { return }
            apply(error)
        }
    }

    /// Whether an error belongs to this cartridge.
    ///
    /// Matched on either name or subscription id because the Tower's extras are
    /// reason-dependent: `unknown_subscription` names only the subscription,
    /// and the two unsolicited errors name both. An error carrying neither is
    /// not claimed — attributing another cartridge's failure to this one would
    /// be a fabricated report about the Tower.
    private func isOurs(_ error: CartridgeResultError) -> Bool {
        if let cartridge = error.cartridge {
            return cartridge == WorldBuilderResultContract.towerCartridge
        }
        if let id = error.subscriptionID { return id == subscriptionID }
        return false
    }

    private func apply(_ envelope: CartridgeResultEnvelope) {
        guard let next = WorldBuilderResultDecoder.modelState(from: envelope.payload) else {
            state = .failed(
                CartridgeFailure(
                    kind: .undecodableResponse,
                    message: """
                        The Tower sent a World Builder result this build could not read. \
                        It declared contract \(envelope.contract ?? "none"), which this \
                        app implements, so the two disagree about what that contract means.
                        """
                )
            )
            return
        }
        // Assigned unconditionally; the `didSet` publishes only on a real
        // change. That is what keeps the ~2 s heartbeat — which re-sends an
        // unchanged snapshot to refresh the fields excluded from the revision
        // hash — from invalidating the view tree for nothing.
        state = next
    }

    /// One line per **change**, which at the channel's ~2 Hz ceiling and with
    /// the heartbeat already filtered out by the `didSet` guard is roughly one
    /// line per keyframe. It exists for the physical session: on a real walk
    /// this is the only place the mapped state is observable, and "the Tower
    /// sent a result" (which `TowerClient` logs) is a different claim from
    /// "this is what the phone made of it".
    private func log(_ state: WorldModelState) {
        #if DEBUG
        let detail: String
        switch state {
        case .unsupported(let reason):
            detail = "unsupported — \(reason)"
        case .idle:
            detail = "idle"
        case .awaitingFirstUpdate:
            detail = "awaitingFirstUpdate"
        case .receiving(let snapshot), .finalizing(let snapshot), .finalized(let snapshot):
            let name: String
            switch state {
            case .receiving: name = "receiving"
            case .finalizing: name = "finalizing"
            default: name = "finalized"
            }
            detail = "\(name) keyframes=\(snapshot.keyframeCount.map(String.init) ?? "-")"
                + " tracking=\(snapshot.tracking.displayName)"
                + " scale=\(snapshot.scale.displayName)"
                + " calibration=\(snapshot.calibration.displayName)"
                + " geometry=\(snapshot.geometry.elementCount.map(String.init) ?? "-")"
                + " poses=\(snapshot.trajectory.poseCount.map(String.init) ?? "-")"
                + " revision=\(snapshot.revision ?? "-")"
        case .failed(let failure):
            detail = "failed(\(failure.kind.rawValue)) — \(failure.message)"
        }
        print("[Glasses][WorldBuilder] \(detail)")
        #endif
    }

    private func apply(_ error: CartridgeResultError) {
        if error.closesSubscription {
            subscriptionID = nil
            isSubscribing = false
            guard resubscribesUsed < Self.resubscribeBudget else {
                state = .failed(
                    CartridgeFailure(
                        kind: .transport,
                        message: """
                            The Tower closed this world's result subscription \
                            \(Self.resubscribeBudget) times on one connection. \
                            Reconnecting is what resolves it.
                            """
                    )
                )
                return
            }
            resubscribesUsed += 1
            subscribeIfPossible()
            return
        }

        switch error.reason {
        case "cartridge_unavailable":
            // Offered, nothing to serve. The Tower's prose is the explanation.
            state = .unsupported(reason: error.message)
        case "contract_mismatch", "unknown_cartridge", "unknown_result_type":
            state = .failed(CartridgeFailure(kind: .notSupported, message: error.message))
        case "snapshot_failed":
            state = .failed(CartridgeFailure(kind: .towerReportedFailure, message: error.message))
        default:
            state = .failed(CartridgeFailure(kind: .transport, message: error.message))
        }
        isSubscribing = false
    }
}
