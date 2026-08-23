//
//  SceneUnderstandingClient.swift
//  Glasses
//

import Combine
import Foundation

/// Supplies `SceneUnderstandingState` to the Scene Understanding workspace.
///
/// The fourth interaction shape: a continuously changing *set*. World Builder
/// pushes one accumulating artefact, Experimental CV Lab runs a bounded job,
/// Document Memory answers point queries, and this publishes a scene that is
/// replaced wholesale many times a second. All four sit behind
/// `CartridgeClient` for the one question they share and behind their own
/// protocol for everything else — which is what keeps the shared layer at a
/// handful of small files instead of a framework.
@MainActor
protocol SceneUnderstandingClient: CartridgeClient {
    var state: SceneUnderstandingState { get }

    /// Every scene after the one `state` held when the view model was built.
    ///
    /// **This is the cartridge whose real client will emit fastest**, so
    /// whatever conforms to it should coalesce before it publishes: a scene
    /// replaced at frame rate, republished straight into a `@Published`
    /// property with a `ForEach` under it, would put a list diff on the main
    /// actor at frame rate — and the main actor is where the sender releases
    /// its send-window slots. See `docs/agent-handoffs/IOS-TO-TOWER.md` §4.6.
    var stateUpdates: AnyPublisher<SceneUnderstandingState, Never> { get }
}

extension SceneUnderstandingClient {
    var stateUpdates: AnyPublisher<SceneUnderstandingState, Never> {
        Empty(completeImmediately: false).eraseToAnyPublisher()
    }
}

/// The only Scene Understanding client that exists: the Tower does not
/// understand scenes, and says so.
///
/// It produces **no sample entities**. A demo scene with two anonymous people
/// in it would be indistinguishable on screen from a real observation of
/// whoever is actually in the room, and it would be the app asserting that the
/// glasses had detected people. That is the single most consequential fake
/// datum in this whole codebase, and it is not shipped, not behind a flag, and
/// not in `#if DEBUG`.
@MainActor
final class UnavailableSceneUnderstandingClient: SceneUnderstandingClient {
    /// ## The line this sentence must not cross
    ///
    /// An earlier draft ended "…and stores nothing about anyone the glasses
    /// pass." That is a **privacy assurance about bystanders, on the one screen
    /// whose subject is bystanders**, and this app cannot know whether it is
    /// true: it has no channel through which to inspect what the Tower writes
    /// to disk, and `docs/07-PLATFORM-CONSTRAINTS.md` Limitation 11 describes
    /// the current transport as unauthenticated and unencrypted.
    ///
    /// What this app *can* observe is what comes back — one brightness figure
    /// per frame — and what it sends. So the sentence is confined to those two
    /// facts. Rule 3: unknown values remain unavailable, and a reassurance is
    /// not a safer guess than silence.
    static let reason = """
        The Tower does not analyse scenes yet. Its only reply to a frame is a \
        single brightness measurement, so nothing about anyone the glasses pass \
        ever reaches this app.
        """

    let cartridgeID = "scene-understanding"

    let state: SceneUnderstandingState =
        .unsupported(reason: UnavailableSceneUnderstandingClient.reason)

    init() {}
}

/// Publishes Scene Understanding state into SwiftUI.
///
/// Holds no runtime references, for the reason given on `WorldBuilderViewModel`.
/// That matters more here than anywhere else: a view model that held the
/// camera and was destroyed on a cartridge switch would end a live session, and
/// this is the cartridge whose subject matter most invites someone to wire it
/// straight to the frame stream.
@MainActor
final class SceneUnderstandingViewModel: ObservableObject {
    @Published private(set) var state: SceneUnderstandingState

    private let client: any SceneUnderstandingClient
    private var cancellables: Set<AnyCancellable> = []

    /// No default argument — see `WorldBuilderViewModel.init(client:)`.
    init(client: any SceneUnderstandingClient) {
        self.client = client
        self.state = client.state

        client.stateUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in self?.state = state }
            .store(in: &cancellables)
    }

    func availability(isTowerReachable: Bool) -> CartridgeAvailability {
        client.availability(isTowerReachable: isTowerReachable)
    }

    func phase(isTowerReachable: Bool) -> CartridgePhase {
        availability(isTowerReachable: isTowerReachable).forcedPhase ?? state.phase
    }

    func unavailableExplanation(isTowerReachable: Bool) -> String {
        availability(isTowerReachable: isTowerReachable)
            .explanation(cartridgeName: "Scene Understanding", clientReason: clientReason)
    }

    private var clientReason: String? {
        switch state {
        case .unsupported(let reason): return reason
        case .failed(let failure): return failure.message
        case .idle, .awaitingFirstScene, .observing, .lastKnown: return nil
        }
    }
}
