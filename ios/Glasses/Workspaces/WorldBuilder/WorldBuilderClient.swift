//
//  WorldBuilderClient.swift
//  Glasses
//

import Combine
import Foundation

/// Supplies `WorldModelState` to the World Builder workspace.
///
/// The seam. One conformer exists today and it reports only that the capability
/// is absent; the Tower-backed conformer is a later pass, once the real contract
/// is known.
///
/// ## What the shared half buys, and where it stops
///
/// `CartridgeClient` contributes the two questions every cartridge answers the
/// same way — which cartridge is this, and may it be used — so that
/// `TowerCapabilities` decides availability once for all four rather than each
/// client deciding for itself. Everything below that line is World Builder's
/// own: a *continuously changing* `state` is the right shape here and the wrong
/// shape for Document Memory, which answers point queries and would be
/// misdescribed by a property that is always current.
///
/// That is the whole reason there is no generic `fetch<Request, Response>` in
/// the shared layer. Four cartridges, four genuinely different interaction
/// shapes, one shared question.
///
/// ## `stateUpdates` exists because `state` alone is a dead end
///
/// A `{ get }` property can be *read*; it cannot *announce*. A Tower-backed
/// client whose world changes would have no way to tell the view model, and the
/// view model's `@Published state` would hold whatever `init` happened to see.
/// The publisher is the missing half, and it is a concrete `AnyPublisher` rather
/// than an `ObservableObject` conformance so `any WorldBuilderClient` stays a
/// usable existential — `ObservableObject` has an associated type and would force
/// every holder to become generic.
///
/// The default implementation never emits, which is the correct and complete
/// behaviour for a client whose state is a constant.
///
/// ## Renamed from `WorldModelSource`
///
/// Product Shell V2 called this `WorldModelSource` and its implementation
/// `UnavailableWorldModelSource`. Nothing about the contract changed — the
/// names now match the three cartridge clients added alongside it, so a reader
/// finds the same word (`…Client`, `Unavailable…Client`, `…ViewModel`) at the
/// same layer in all four.
@MainActor
protocol WorldBuilderClient: CartridgeClient {
    var state: WorldModelState { get }

    /// Every state after the one `state` held when the view model was built.
    var stateUpdates: AnyPublisher<WorldModelState, Never> { get }

    /// What this client has established about whether the world it is
    /// reporting belongs to the capture the phone currently has open.
    ///
    /// Paired with `state` rather than folded into it because the two answer
    /// different questions and change on different clocks. `state` is *what to
    /// draw*; this is *why*, and a client with no transport under it honestly
    /// has nothing to say about either — hence the `.none` default.
    var sessionBinding: WorldSessionBinding { get }

    /// Every binding after the one `sessionBinding` held when the view model
    /// was built.
    var bindingUpdates: AnyPublisher<WorldSessionBinding, Never> { get }
}

extension WorldBuilderClient {
    /// Never emits. `Empty(completeImmediately: false)` rather than
    /// `completeImmediately: true` so a subscriber sees an open stream that
    /// happens to be silent, not a finished one — the difference matters the
    /// day a real client replaces this and a completed publisher would have
    /// already torn the subscription down.
    var stateUpdates: AnyPublisher<WorldModelState, Never> {
        Empty(completeImmediately: false).eraseToAnyPublisher()
    }

    /// A client that is not watching a capture cannot be looking at the wrong
    /// one. `.none` is the correct constant for every client with no transport,
    /// and for a Release build, which has no capture control at all.
    var sessionBinding: WorldSessionBinding { .none }

    var bindingUpdates: AnyPublisher<WorldSessionBinding, Never> {
        Empty(completeImmediately: false).eraseToAnyPublisher()
    }
}

/// A World Builder client with no Tower behind it.
///
/// **No longer the only one.** `TowerWorldBuilderClient` is what the app graph
/// builds, and this is what remains when there is deliberately no connection to
/// build it from — the `CartridgeClients` default, and the client a test
/// substitutes when it wants a workspace with no transport underneath it.
///
/// Kept rather than deleted because "this build has no Tower-backed client for
/// this cartridge" is still a state the other three cartridges are in, and
/// because the shape of a client that reports one constant is the thing the
/// protocol's default `stateUpdates` was written for.
@MainActor
final class UnavailableWorldBuilderClient: WorldBuilderClient {
    /// Written for a person, not a log. The workspace shows this verbatim, so
    /// it has to explain the situation without implying either that something
    /// is broken or that a world is coming imminently.
    ///
    /// Note what it does **not** say: anything about what the Tower can or
    /// cannot do. This client has no channel through which it could know —
    /// that is precisely what makes it this client — and describing the other
    /// machine from here would be a fabricated report about it (Rule 3).
    static let reason = """
        This screen is not connected to a world builder. Nothing is being \
        asked of the Tower and nothing it may have built is being read.
        """

    let cartridgeID = "world-build"

    let state: WorldModelState = .unsupported(reason: UnavailableWorldBuilderClient.reason)

    init() {}
}

/// Publishes World Builder state into SwiftUI.
///
/// Separate from the client protocol because the protocol describes *supplying*
/// state, while this describes *publishing* it. When a Tower-backed client
/// exists it replaces the injected client, and this type starts republishing
/// real updates without any view changing.
///
/// ## Runtime ownership
///
/// **Holds no runtime references.** No `GlassesConnection`, no `TowerClient`,
/// no DAT object, no socket, and no `deinit` — so being destroyed when the
/// cartridge is deselected loses nothing real and tears nothing down. That is
/// what makes it safe as a workspace-owned `@StateObject`.
///
/// It holds a *subscription to its client*, which is a different thing: the
/// client is owned by `ProjectManager` and outlives the workspace, so a client
/// that has accumulated a partly-built world still has it when the cartridge is
/// reopened. The subscription is cancelled by `Set<AnyCancellable>`'s own
/// deallocation, which is why there is still no `deinit`.
///
/// Connectivity reaches it as a parameter (`isTowerReachable`), never as an
/// object it could act on. `CartridgeIntegrationTests` and
/// `TowerClientTests.testCartridgeViewModelsSendNothingToTheTower` check that
/// rather than leaving it to inspection.
@MainActor
final class WorldBuilderViewModel: ObservableObject {
    /// Seeded from the client and republished from `stateUpdates`. Nothing
    /// republishes it yet — the only client reports a constant — but the path
    /// exists, which is what makes "wiring a Tower-backed client is an
    /// injection, not a change of shape" a true statement rather than an
    /// aspiration.
    @Published private(set) var state: WorldModelState

    /// Live vs. stored-world inspection. Nothing can change it yet because
    /// there is no stored world to open.
    @Published private(set) var inspection: WorldInspectionMode = .live

    /// Whether the world on screen belongs to the capture the phone has open.
    ///
    /// Republished rather than derived, for the reason `state` is: the client
    /// owns the judgment, and a view model that recomputed it would be a second
    /// answer able to disagree with the one the state was gated on.
    @Published private(set) var sessionBinding: WorldSessionBinding

    private let client: any WorldBuilderClient
    private var cancellables: Set<AnyCancellable> = []

    /// No default argument, deliberately.
    ///
    /// A default would make "swap the unavailable client for a Tower-backed one
    /// right here in the workspace view" the path of least resistance — and
    /// that client would hold a socket subscription and accumulated world
    /// state inside an object destroyed on every cartridge switch. The Product
    /// Shell V2 handoff §11 names that exact failure. Requiring injection means
    /// the correct wiring is the only wiring available.
    init(client: any WorldBuilderClient) {
        self.client = client
        self.state = client.state
        self.sessionBinding = client.sessionBinding

        client.stateUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in self?.state = state }
            .store(in: &cancellables)

        client.bindingUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] binding in self?.sessionBinding = binding }
            .store(in: &cancellables)
    }

    /// Why the cartridge is or is not usable, given the current connection.
    ///
    /// A function of the caller's connectivity rather than a stored property,
    /// so this object never holds a `TowerClient` and never answers from a
    /// stale copy of the connection state.
    func availability(isTowerReachable: Bool) -> CartridgeAvailability {
        client.availability(isTowerReachable: isTowerReachable)
    }

    /// The phase to draw, once availability has had its say.
    ///
    /// Availability outranks the client's own state: a Tower that cannot serve
    /// this cartridge makes every domain state moot, and letting `.idle` show
    /// through would invite a user to start something that cannot run.
    func phase(isTowerReachable: Bool) -> CartridgePhase {
        availability(isTowerReachable: isTowerReachable).forcedPhase ?? state.phase
    }

    /// The full explanation for the unavailable panel: the shared sentence about
    /// the Tower, plus whatever this cartridge's own state adds.
    func unavailableExplanation(isTowerReachable: Bool) -> String {
        availability(isTowerReachable: isTowerReachable)
            .explanation(cartridgeName: "World Builder", clientReason: clientReason)
    }

    /// The client's own words, when its state carries any.
    private var clientReason: String? {
        switch state {
        case .unsupported(let reason): return reason
        case .failed(let failure): return failure.message
        case .idle, .awaitingFirstUpdate, .receiving, .finalizing, .finalized: return nil
        }
    }
}
