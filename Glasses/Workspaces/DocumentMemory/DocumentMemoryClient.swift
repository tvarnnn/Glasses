//
//  DocumentMemoryClient.swift
//  Glasses
//

import Combine
import Foundation

/// Supplies `DocumentMemoryState` to the Document Memory workspace.
///
/// ## A third interaction shape
///
/// World Builder pushes a continuously current state. Experimental CV Lab takes
/// a command and reports progress. This one answers point queries: nothing is
/// current, everything is in response to a question. Three cartridges, three
/// shapes — which is the concrete evidence that a generic
/// `CartridgeDataSource<Request, Response>` above all of them would be an
/// abstraction over things that are not alike.
///
/// `search(_:origin:)` carries the origin so a future Siri intent or wake-word
/// layer submits through this same method rather than needing its own path.
@MainActor
protocol DocumentMemoryClient: CartridgeClient {
    var state: DocumentMemoryState { get }

    /// Every state after the one `state` held when the view model was built.
    /// See `WorldBuilderClient.stateUpdates`.
    var stateUpdates: AnyPublisher<DocumentMemoryState, Never> { get }

    /// Asks the Tower's document memory a question.
    ///
    /// Throws when the request cannot be made at all. A query that runs and
    /// matches nothing is **not** a throw — that is a `DocumentQueryResult`
    /// with `.notFound` or `.noObservation` evidence, and conflating an empty
    /// answer with a failure is how "we have no record" turns into "something
    /// went wrong".
    func search(_ query: DocumentQuery, origin: DocumentQueryOrigin) throws
}

extension DocumentMemoryClient {
    var stateUpdates: AnyPublisher<DocumentMemoryState, Never> {
        Empty(completeImmediately: false).eraseToAnyPublisher()
    }
}

/// The only Document Memory client that exists: the Tower keeps no document
/// memory, and says so.
///
/// It holds **no sample documents**. A handful of plausible rows would make the
/// workspace look finished and would be indistinguishable, on screen, from real
/// memories of the wearer's own documents — the single most misleading fixture
/// this app could ship. Test fixtures live in the test target, where they can
/// never reach a device.
@MainActor
final class UnavailableDocumentMemoryClient: DocumentMemoryClient {
    /// ## What this sentence is careful not to claim
    ///
    /// It says nothing about what the Tower **stores**. This app has no channel
    /// through which it could know that, so a reassurance would be a fabricated
    /// claim about the other machine (Rule 3).
    ///
    /// It is also careful about the frames. Saying "no document text has left
    /// this app" is true — no OCR runs here — but on a screen about documents a
    /// reader takes it to mean the *documents* stayed on the phone, and they do
    /// not: full camera frames go to the Tower, and
    /// `docs/06-PRIVACY-DATA.md` treats a document appearing in frame as "a
    /// standing risk of the input modality, not an edge case". So the sentence
    /// says plainly what leaves.
    static let reason = """
        The Tower keeps no document memory, so there is nothing to search. This \
        app sends camera frames to the Tower while a session is running; it \
        reads no text from them and receives none back.
        """

    let cartridgeID = "document-memory"

    let state: DocumentMemoryState = .unsupported(reason: UnavailableDocumentMemoryClient.reason)

    init() {}

    /// Always throws, for the same reason the Experimental CV client does: a
    /// silent no-op leaves a search field that appears to work and returns
    /// nothing, which a person reads as "I have no documents" rather than as
    /// "this is not built".
    func search(_ query: DocumentQuery, origin: DocumentQueryOrigin) throws {
        throw CartridgeFailure(kind: .notSupported, message: Self.reason)
    }
}

/// Publishes Document Memory state into SwiftUI.
///
/// Holds no runtime references, for the reason given on `WorldBuilderViewModel`.
@MainActor
final class DocumentMemoryViewModel: ObservableObject {
    @Published private(set) var state: DocumentMemoryState

    /// What the person has typed. Owned here rather than in the view so a query
    /// can also arrive from somewhere that has no text field — the origin
    /// parameter on `submit` is the seam a Siri intent would use.
    @Published var queryText: String = ""

    @Published private(set) var lastRequestFailure: CartridgeFailure?

    private let client: any DocumentMemoryClient
    private var cancellables: Set<AnyCancellable> = []

    /// No default argument — see `WorldBuilderViewModel.init(client:)`.
    init(client: any DocumentMemoryClient) {
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
            .explanation(cartridgeName: "Document Memory", clientReason: clientReason)
    }

    private var clientReason: String? {
        switch state {
        case .unsupported(let reason): return reason
        case .failed(let failure): return failure.message
        case .idle, .searching, .results: return nil
        }
    }

    /// Submits whatever is in `queryText`.
    ///
    /// Typed text becomes a `.semantic` query rather than a `.text` one: a
    /// person asking "the parking notice from this morning" is describing a
    /// document, not quoting it, and routing that through substring matching
    /// would return nothing and look like an empty memory. Which of the two the
    /// Tower can actually serve is its decision — this states what the user
    /// meant, not how to satisfy it.
    func submitTypedQuery() {
        let trimmed = queryText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        submit(.semantic(trimmed), origin: .appText)
    }

    /// The entry point any input layer uses.
    func submit(_ query: DocumentQuery, origin: DocumentQueryOrigin) {
        do {
            try client.search(query, origin: origin)
            lastRequestFailure = nil
        } catch {
            lastRequestFailure = CartridgeFailure.wrapping(error)
        }
    }
}
