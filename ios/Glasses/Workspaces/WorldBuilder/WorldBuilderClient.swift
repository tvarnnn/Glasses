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

    /// Where the world's geometry can be fetched from, each time the Tower
    /// reports an address for it.
    ///
    /// A second publisher rather than a field inside `WorldModelState`, because
    /// the two answer different questions. The state says what to *draw*; this
    /// says where to *fetch*, and the fetch does not happen over the socket the
    /// state arrived on. Folding a session id and a transport revision into
    /// `WorldSnapshot` would put addressing inside a presentation type and
    /// would break that type's standing promise to map field for field onto the
    /// payload's `world_snapshot` block — which carries neither value.
    ///
    /// Emits nothing at all for a client with no Tower behind it, which is the
    /// correct and complete behaviour rather than an omission.
    var geometryUpdates: AnyPublisher<WorldGeometryCoordinates, Never> { get }
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

    /// Never emits, for the same reason and in the same shape. A client with no
    /// Tower behind it has no geometry to address, and an open-but-silent
    /// stream says exactly that.
    var geometryUpdates: AnyPublisher<WorldGeometryCoordinates, Never> {
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
/// ## It does make HTTP requests, and that is not a contradiction
///
/// Geometry is fetched here, over HTTP, from the address the client hands it.
/// That is deliberate on both counts. **Over HTTP** because the Tower gives its
/// result sender and its frame path one shared lock, and a megabyte of points
/// down the WebSocket would starve `frame_result`. **From here** rather than
/// from the client because the fetch has no lifecycle: a request in flight when
/// this object is destroyed resolves into a `[weak self]` that is gone, and
/// nothing is left open. `URLSession.shared` is the app's, not this object's;
/// `WorldGeometryStore` is an actor holding a dictionary. Neither is a
/// connection, neither is torn down, and the wire this type still may not touch
/// — the socket — it still does not.
///
/// `TowerClientTests.testCartridgeViewModelsSendNothingToTheTower` remains the
/// enforcement of that, and remains true: it holds the socket to account, and
/// the client it is given publishes no geometry address to fetch from.
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

    /// The segments the Tower's manifest currently names, in the shape the
    /// gallery draws them.
    ///
    /// Empty until a manifest arrives, and emptied again when one arrives under
    /// a pose convention this build does not implement — an empty gallery says
    /// "nothing mapped", which is a true thing to say about geometry that
    /// cannot be read, whereas drawing it under the wrong convention would look
    /// like a room and mean nothing.
    @Published private(set) var fragmentsModel = WorldFragmentsModel(segments: [])

    /// The points and poses for those segments, keyed by content hash.
    ///
    /// Keyed by hash and not by index so that a segment re-solved under the
    /// same index cannot be drawn from the previous solve's points. A segment
    /// whose chunk failed to fetch is simply absent here, and `FragmentCanvas`
    /// draws an empty tile for it rather than guessing.
    @Published private(set) var geometryChunks: [String: WorldSegmentChunk] = [:]

    private let client: any WorldBuilderClient
    private var cancellables: Set<AnyCancellable> = []

    /// Geometry transport. A `struct` and an `actor`, neither of which holds a
    /// connection: `URLSession.shared` is the app's, and the store is a
    /// dictionary. So the claim in this type's doc comment — that it holds no
    /// runtime references and tears nothing down — still stands.
    private let geometry = WorldGeometryClient()
    private let geometryStore = WorldGeometryStore()

    /// The `geometry.revision` whose manifest is currently on screen, or `nil`
    /// when there is none — including after a fetch that failed, so the next
    /// report retries rather than being locked out.
    private var lastGeometryRevision: String?

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

        client.stateUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in self?.state = state }
            .store(in: &cancellables)

        client.geometryUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] coordinates in self?.fetchGeometry(at: coordinates) }
            .store(in: &cancellables)
    }

    /// The synchronous half of the fetch: start it, and return.
    ///
    /// The `sink` closure must not block — it runs on the main queue, on the
    /// same turn the Tower's snapshot arrived — so the work goes into a `Task`
    /// and this returns immediately. `[weak self]` because the task outlives
    /// the sink call: a cartridge switch during a fetch leaves the request to
    /// resolve into a `self` that is gone, which drops it and opens nothing.
    private func fetchGeometry(at coordinates: WorldGeometryCoordinates) {
        Task { [weak self] in
            await self?.geometryDidChange(
                worldID: coordinates.worldID,
                sessionID: coordinates.sessionID,
                revision: coordinates.revision
            )
        }
    }

    /// Fetch the geometry the Tower has just named, unless it is the geometry
    /// already on screen.
    ///
    /// **Keyed on the revision, never on arrival.** The status channel
    /// heartbeats an unchanged snapshot about every two seconds, so a fetch
    /// triggered by a message rather than by a *changed* identity would pull a
    /// megabyte of points twice a second for a world that is standing still.
    ///
    /// Optional parameters, though `WorldGeometryCoordinates` carries none, so
    /// that the guard reads as one statement and so a future caller reaching
    /// this from a partially-known address is refused here rather than
    /// composing a URL out of what it happened to have.
    func geometryDidChange(worldID: String?, sessionID: String?, revision: String?) async {
        guard
            let worldID, let sessionID, let revision,
            revision != lastGeometryRevision
        else { return }
        lastGeometryRevision = revision

        guard let manifest = try? await geometry.manifest(
            worldID: worldID, sessionID: sessionID
        ) else {
            // Cleared rather than kept. A manifest that failed once — a 404
            // from a world root that was not configured yet, a request that
            // raced a rebuild — would otherwise be locked out until the world
            // happened to change again, and a *finalized* world never changes
            // again. The retry costs one small request on the next report.
            //
            // Guarded, because a newer call may already have claimed the
            // marker: clearing it then would make that newer fetch's own
            // result look superseded and be refetched from scratch.
            if revision == lastGeometryRevision { lastGeometryRevision = nil }
            return
        }

        // A newer report may have started its own fetch while this one was in
        // flight — likely on a live walk, where the revision moves about as
        // often as a fetch takes. The last writer must be the newest report and
        // not the slowest request, so a superseded fetch publishes nothing and
        // simply ends here.
        guard revision == lastGeometryRevision else { return }

        // A convention this build does not implement renders plausibly and
        // wrongly, so it renders not at all.
        guard manifest.poseConvention.matchesThisBuild else {
            fragmentsModel = WorldFragmentsModel(segments: [])
            geometryChunks = [:]
            return
        }

        // Everything the manifest still names is kept and everything else is
        // dropped, so a long walk does not accumulate superseded segments
        // forever. The cache and the published copy are rebuilt from the same
        // list in the same pass: a hash held by one and not the other would
        // either refetch what is already in hand or draw what is already gone.
        await geometryStore.retainOnly(Set(manifest.segments.map(\.contentHash)))

        var chunks: [String: WorldSegmentChunk] = [:]
        for summary in manifest.segments {
            if let cached = await geometryStore.chunk(forHash: summary.contentHash) {
                chunks[summary.contentHash] = cached
                continue
            }
            guard let chunk = try? await geometry.segment(
                worldID: worldID, sessionID: sessionID, index: summary.segmentIndex
            ) else { continue }
            await geometryStore.insert(chunk)
            // Filed under the chunk's OWN hash, not the summary's. A rebuild
            // between the two requests returns different geometry under the
            // same segment index, and filing it under the hash we asked for
            // would draw the new points inside the old segment's bounds. Filed
            // under its own, it simply does not match and is not drawn — which
            // is the honest outcome, and the next manifest resolves it.
            chunks[chunk.contentHash] = chunk
        }

        // Checked again, for the same reason: the segment fetches above are the
        // slow part, and a newer manifest may have landed during them.
        guard revision == lastGeometryRevision else { return }
        geometryChunks = chunks
        fragmentsModel = WorldFragmentsModel(segments: manifest.segments)
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
