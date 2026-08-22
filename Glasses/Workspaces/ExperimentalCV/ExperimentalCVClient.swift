//
//  ExperimentalCVClient.swift
//  Glasses
//

import Combine
import Foundation

/// Supplies `ExperimentalCVState` to the Experimental CV Lab workspace.
///
/// ## A different interaction shape from World Builder's, on purpose
///
/// World Builder's client publishes a state that is always current, because a
/// world is being built continuously. This one has a *command*: an experiment
/// is chosen and started. That difference is why there is no shared
/// `CartridgeDataSource<T>` protocol above both — the shared layer stops at the
/// question all four answer identically (may this be used, and why not), and
/// each cartridge describes its own interaction below that line.
///
/// `run(_:)` is `throws` and returns nothing. It reports the outcome through
/// `state`, because an experiment produces a stream of partial results rather
/// than one return value, and a client that returned a final result would have
/// to hide the running state that this workspace exists to show.
@MainActor
protocol ExperimentalCVClient: CartridgeClient {
    var state: ExperimentalCVState { get }

    /// Every state after the one `state` held when the view model was built.
    /// See `WorldBuilderClient.stateUpdates` for why this is a concrete
    /// `AnyPublisher` rather than an `ObservableObject` conformance.
    var stateUpdates: AnyPublisher<ExperimentalCVState, Never> { get }

    /// Asks the Tower to run an experiment.
    ///
    /// Throws when the request cannot even be made — which is the only failure
    /// today, and the only one that has a truthful answer without a contract.
    func run(_ experiment: CVExperiment) throws
}

extension ExperimentalCVClient {
    var stateUpdates: AnyPublisher<ExperimentalCVState, Never> {
        Empty(completeImmediately: false).eraseToAnyPublisher()
    }
}

/// The only Experimental CV Lab client that exists: the Tower cannot run
/// experiments, and says so.
///
/// It declares **no experiments**. The temptation here is a list of plausible
/// ones — edge detection, optical flow, ORB — drawn from the module spec's
/// candidate list, so the picker has something in it. That list would be an
/// invention: `docs/modules/EXPERIMENTAL-CV.md` calls its candidates
/// "intentionally broad" and does not commit to any, and a populated picker is
/// a claim that those specific experiments exist.
@MainActor
final class UnavailableExperimentalCVClient: ExperimentalCVClient {
    /// Note the boundary this sentence keeps: it describes what the Tower
    /// *replies*, which this app observes on every frame, and says nothing
    /// about what the Tower stores, which this app has no way to know.
    static let reason = """
        The Tower cannot run experiments yet. Experimental CV Lab is Module #1 \
        on the roadmap, but the module container it would run inside does not \
        exist, so the Tower declares no experiments and can accept no request \
        to run one.
        """

    let cartridgeID = "experimental-cv"

    let state: ExperimentalCVState = .unsupported(reason: UnavailableExperimentalCVClient.reason)

    init() {}

    /// Always throws. A silent no-op would leave a button that appears to work,
    /// which is the failure mode this whole cartridge layer exists to prevent —
    /// and `docs/04-MODULE-SYSTEM.md` requires an unsupported request to
    /// "produce a clear degraded/failed state rather than silently pretending"
    /// it was applied.
    ///
    /// `.notSupported`, not `.towerReportedFailure`: the Tower reported
    /// nothing. There may not even be a socket open, and attributing a local
    /// refusal to the other machine is a fabricated claim about it.
    func run(_ experiment: CVExperiment) throws {
        throw CartridgeFailure(kind: .notSupported, message: Self.reason)
    }
}

/// Publishes Experimental CV Lab state into SwiftUI.
///
/// Holds no runtime references — no `GlassesConnection`, no `TowerClient`, no
/// socket — for the same reason `WorldBuilderViewModel` does not: a workspace
/// `@StateObject` is destroyed when the cartridge changes, and destroying
/// something that owns the camera would end the session. Connectivity arrives
/// as a value; the client is injected and owned above this object.
@MainActor
final class ExperimentalCVViewModel: ObservableObject {
    @Published private(set) var state: ExperimentalCVState

    /// The most recent failed attempt to start something, kept separate from
    /// `state` so a rejected request does not erase whatever the workspace was
    /// already showing.
    @Published private(set) var lastRequestFailure: CartridgeFailure?

    private let client: any ExperimentalCVClient
    private var cancellables: Set<AnyCancellable> = []

    /// No default argument — see `WorldBuilderViewModel.init(client:)`.
    init(client: any ExperimentalCVClient) {
        self.client = client
        self.state = client.state

        client.stateUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in self?.state = state }
            .store(in: &cancellables)
    }

    /// Experiments the Tower declared. Empty in every state but `.idle`,
    /// because a list of runnable things is only meaningful when something can
    /// be run.
    var availableExperiments: [CVExperiment] {
        if case .idle(let available) = state { return available }
        return []
    }

    func availability(isTowerReachable: Bool) -> CartridgeAvailability {
        client.availability(isTowerReachable: isTowerReachable)
    }

    func phase(isTowerReachable: Bool) -> CartridgePhase {
        availability(isTowerReachable: isTowerReachable).forcedPhase ?? state.phase
    }

    func unavailableExplanation(isTowerReachable: Bool) -> String {
        availability(isTowerReachable: isTowerReachable)
            .explanation(cartridgeName: "Experimental CV Lab", clientReason: clientReason)
    }

    private var clientReason: String? {
        switch state {
        case .unsupported(let reason): return reason
        case .failed(let failure): return failure.message
        case .idle, .starting, .running, .completed: return nil
        }
    }

    /// Requests a run, and records the refusal when there is one.
    ///
    /// Deliberately does not rethrow. The caller is a SwiftUI button action,
    /// which cannot handle an error usefully; recording it as published state
    /// is what puts the refusal on screen instead of in a log.
    func run(_ experiment: CVExperiment) {
        do {
            try client.run(experiment)
            lastRequestFailure = nil
        } catch {
            lastRequestFailure = CartridgeFailure.wrapping(error)
        }
    }
}
