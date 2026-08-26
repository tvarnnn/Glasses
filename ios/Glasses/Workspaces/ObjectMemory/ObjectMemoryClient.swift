//
//  ObjectMemoryClient.swift
//  Glasses
//

import Combine
import Foundation

// MARK: - Transport failures

/// Why a request to the Tower's object memory did not produce an answer.
///
/// Four cases, and the first two are **not** errors about the wearer's memory:
/// they are facts about the Tower. Collapsing them into "something went wrong"
/// is how a Tower with no object memory configured comes to look like a person
/// who has never seen a laptop.
enum ObjectMemoryFetchError: Error, Equatable {
    /// **404.** `TOWER_OBSERVATION_ROOT` is unset: this Tower serves no object
    /// memory at all.
    ///
    /// A statement about configuration, and never the answer to a question
    /// about a class — the Tower is explicit that an unobserved class is
    /// answered 200 with `observed: false` precisely so that a 404 can keep
    /// meaning only this.
    case noObjectMemoryConfigured
    /// The Tower's object memory speaks a different agreement. Opaque and
    /// compared for equality: not newer, not older, just different.
    case unsupportedContract(identifier: String)
    /// The answer arrived and could not be read as this contract.
    case undecodable
    /// The request did not complete. The Tower is unreachable, or the network
    /// is.
    case transport(String)
}

// MARK: - HTTP

/// The two `GET`s, and nothing else.
///
/// ## Read-only, deliberately and permanently
///
/// `ObservationStore` has `purge()` and `prune_expired()`. **Neither is on the
/// wire**, and the Tower has two tests holding it there. This client has no
/// delete, no write, and no method that could grow into one — real deletion
/// lives with `scripts/object_query.py --purge-all`, where a human types it
/// against a store they can name. An unauthenticated LAN endpoint that erases a
/// wearer's memory is not a feature, and neither is a phone button that calls
/// one.
///
/// ## Why this mirrors `WorldGeometryClient` rather than inventing anything
///
/// Same shape, same `JSONSerialization` decoding, same "a 404 is its own case"
/// handling, same injectable `URLSession`. A second, differently-opinionated
/// networking layer in one app is two places for a timeout policy to be wrong.
///
/// ## Bounded, and uncached
///
/// Every request carries an explicit timeout (Rule 15: bounded operations) and
/// `reloadIgnoringLocalCacheData`. A memory query answered out of a URL cache
/// would show a record as current that the retention window may since have
/// closed over, which is the one kind of staleness this cartridge cannot
/// tolerate.
struct ObjectMemoryHTTPClient {
    var baseURL: URL = TowerConfiguration.httpBaseURL
    var session: URLSession = .shared
    /// Long enough for a Tailscale round trip to a Tower reading a JSONL file,
    /// short enough that a dead Tower becomes a visible state rather than a
    /// spinner nobody can end.
    var timeout: TimeInterval = 10

    /// Every observation still within the retention window, newest first.
    ///
    /// - Parameters:
    ///   - objectClass: narrow to one category, or `nil` for all of them.
    ///   - retentionDays: **narrow** the window this read may see. It cannot
    ///     widen it: the store clamps every read to `min(persisted, requested)`
    ///     and reports the clamp in `retention.clamped`. Passing a large number
    ///     here does not recover an expired record and never will.
    func listing(
        objectClass: String? = nil, retentionDays: Double? = nil
    ) async throws -> ObservationListing {
        var query: [URLQueryItem] = []
        if let objectClass {
            query.append(URLQueryItem(name: "object_class", value: objectClass))
        }
        appendRetention(retentionDays, to: &query)

        let url = baseURL.appendingPathComponent("object-memory/observations")
        let json = try await get(url, query: query)
        try requireThisContract(json)
        return try ObjectMemoryDecoder.listing(from: json)
    }

    /// When a category was last in view, or an honest silence.
    ///
    /// Always 200 when a root is configured — there is no 404 for an unobserved
    /// class, because "not found" reads as "there is no laptop", which is a
    /// claim about the world.
    ///
    /// `objectClass` is appended as its own path component so that a class with
    /// a space in it (`cell phone`, which is one of the two real ones) is
    /// percent-encoded rather than splitting the path.
    func lastSeen(
        objectClass: String, retentionDays: Double? = nil
    ) async throws -> LastSeenAnswer {
        var query: [URLQueryItem] = []
        appendRetention(retentionDays, to: &query)

        let url = baseURL
            .appendingPathComponent("object-memory/last-seen")
            .appendingPathComponent(objectClass)
        let json = try await get(url, query: query)
        try requireThisContract(json)
        return try ObjectMemoryDecoder.lastSeen(from: json)
    }

    /// `0` is a meaningful value on this parameter — "no limit of my own",
    /// still clamped to the persisted window — so it is only omitted when the
    /// caller asked for nothing at all. A negative value is refused here rather
    /// than being sent for the route to answer 422.
    private func appendRetention(_ days: Double?, to query: inout [URLQueryItem]) {
        guard let days, days >= 0 else { return }
        query.append(URLQueryItem(name: "retention_days", value: String(days)))
    }

    /// Equality, and nothing else. A different identifier is surfaced as its
    /// own case so the app can say "update the app" rather than decoding a
    /// payload whose fields may mean something new.
    private func requireThisContract(_ json: [String: Any]) throws {
        guard let identifier = ObjectMemoryDecoder.contractIdentifier(from: json) else {
            throw ObjectMemoryFetchError.undecodable
        }
        guard identifier == ObjectMemoryContract.identifier else {
            throw ObjectMemoryFetchError.unsupportedContract(identifier: identifier)
        }
    }

    private func get(_ url: URL, query: [URLQueryItem]) async throws -> [String: Any] {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw ObjectMemoryFetchError.transport("The Tower address could not be read as a URL.")
        }
        // Empty rather than `[]`: an empty `queryItems` array puts a bare `?`
        // on the URL, and `nil` is what "no query" means.
        components.queryItems = query.isEmpty ? nil : query
        guard let requestURL = components.url else {
            throw ObjectMemoryFetchError.transport("The request URL could not be built.")
        }

        let request = URLRequest(
            url: requestURL,
            cachePolicy: .reloadIgnoringLocalCacheData,
            timeoutInterval: timeout
        )

        do {
            let (data, response) = try await session.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode == 404 {
                throw ObjectMemoryFetchError.noObjectMemoryConfigured
            }
            if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
                throw ObjectMemoryFetchError.transport(
                    "The Tower answered \(http.statusCode)."
                )
            }
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                throw ObjectMemoryFetchError.undecodable
            }
            return json
        } catch let error as ObjectMemoryFetchError {
            throw error
        } catch {
            throw ObjectMemoryFetchError.transport(error.localizedDescription)
        }
    }
}

// MARK: - What this app has learned about the Tower's object memory

/// What a request has taught this app about the other machine.
///
/// ## Why this exists at all, and is not `TowerCapabilities`
///
/// World Builder's contract is **declared** over the socket, before anything is
/// asked for, so `TowerCapabilities` can resolve its availability from a
/// declaration it already holds. Object Memory's is not declared anywhere: it
/// travels in the `contract` field of an answer, so the only way to learn
/// whether this Tower serves object memory — and under which agreement — is to
/// ask it.
///
/// That makes `.unprobed` a real and unavoidable state, and it is the one thing
/// `CartridgeAvailability`'s four cases cannot express: "nothing has been
/// declared" and "nothing has been asked" are different, and only the first is
/// `.noContract`. So the knowledge lives here, `availability(isTowerReachable:)`
/// projects it onto the shared vocabulary for anything that needs the shared
/// vocabulary, and `knownAvailability(isTowerReachable:)` returns `nil` in the
/// one case where the projection would be a claim rather than a fact.
enum ObjectMemoryService: Equatable, Sendable {
    /// Nothing has been asked, so nothing is known. **Not** "unavailable".
    case unprobed
    /// A payload arrived under the contract this build implements.
    case serving(CartridgeContract)
    /// A payload arrived under a different agreement.
    case speaksAnotherContract(CartridgeContract)
    /// The Tower answered 404: it serves no object memory.
    case notConfigured
    /// The request did not complete.
    case unreachable(String)
}

// MARK: - State

/// What the Object Memory workspace should be showing.
///
/// ## Why a failure carries no answer
///
/// `CartridgePhase.mayCarryData` is false for every phase but `.live` and
/// `.settled`, and that invariant is checked across every cartridge at once. So
/// a failed refresh clears the answer rather than leaving the previous one on
/// screen beneath a warning. That is the stricter choice and it is the right
/// one here: a record whose age the reader can no longer trust is exactly what
/// a cartridge about *when something was visible* must not display.
enum ObjectMemoryState: Equatable, Sendable {
    /// Nothing has been asked yet. Not "empty" — nobody has asked a question.
    case idle
    case asking(ObjectMemoryQuestion)
    /// An answer, which may carry no records. **An empty answer is an answer**,
    /// not a failure, and `ObjectMemoryCopy` words it as one.
    case answered(question: ObjectMemoryQuestion, answer: ObjectMemoryAnswer)
    /// The Tower serves no object memory at all.
    case noObjectMemory
    case failed(CartridgeFailure)

    var answer: ObjectMemoryAnswer? {
        if case .answered(_, let answer) = self { return answer }
        return nil
    }

    var question: ObjectMemoryQuestion? {
        switch self {
        case .asking(let question): return question
        case .answered(let question, _): return question
        case .idle, .noObjectMemory, .failed: return nil
        }
    }

    var phase: CartridgePhase {
        switch self {
        case .idle: return .idle
        case .asking: return .waiting
        // Settled even when it carries nothing: the Tower is not still working
        // on it, and a spinner over an honest silence would suggest otherwise.
        case .answered: return .settled
        case .noObjectMemory: return .unsupported
        case .failed(let failure):
            // A transport failure is the shell's `.disconnected`, not its
            // `.failed`: the capability exists and the Tower could not be
            // reached, which is a connection state and calls for a different
            // headline and glyph than a broken answer.
            return failure.kind == .transport ? .disconnected : .failed
        }
    }
}

// MARK: - The client

/// Supplies `ObjectMemoryState` to the Object Memory workspace.
///
/// A fourth interaction shape, after World Builder's continuous push,
/// Experimental CV's bounded job and Document Memory's point query: a
/// **read-only historical query over HTTP**, against a store that exists
/// whether or not a session is running. Nothing here streams, nothing
/// subscribes, and nothing is current.
@MainActor
protocol ObjectMemoryClient: CartridgeClient {
    var state: ObjectMemoryState { get }

    /// Every state after the one `state` held when the view model was built.
    var stateUpdates: AnyPublisher<ObjectMemoryState, Never> { get }

    /// What asking has taught this app about the Tower's object memory.
    var service: ObjectMemoryService { get }

    /// Availability, or `nil` while nothing has been asked and the projection
    /// onto the shared four cases would be a claim rather than a fact. See
    /// `ObjectMemoryService`.
    func knownAvailability(isTowerReachable: Bool) -> CartridgeAvailability?

    /// Asks one question. Never throws: an unreachable Tower, a Tower with no
    /// object memory, and an unreadable answer are all **states**, because all
    /// three are things the screen has to be able to say.
    func ask(_ question: ObjectMemoryQuestion) async
}

/// The Object Memory client, backed by the Tower's two read-only routes.
///
/// ## Runtime ownership
///
/// Owns no socket and touches no frame path. It holds a `URLSession`-backed
/// struct and makes a request when a person asks for one — there is no polling,
/// no subscription, and no timer. It is held in `CartridgeClients` so that an
/// answer survives a workspace switch, which is the whole reason that container
/// exists.
///
/// ## It holds no sample observations
///
/// For the reason `UnavailableDocumentMemoryClient` gives: a handful of
/// plausible rows would be indistinguishable on screen from real records of
/// what the wearer's own camera saw, which is the most misleading fixture this
/// app could ship. Fixtures live in the test target, where they cannot reach a
/// device.
@MainActor
final class TowerObjectMemoryClient: ObjectMemoryClient {

    let cartridgeID = "object-memory"

    private(set) var state: ObjectMemoryState = .idle {
        didSet {
            guard state != oldValue else { return }
            stateSubject.send(state)
        }
    }

    var stateUpdates: AnyPublisher<ObjectMemoryState, Never> {
        stateSubject.eraseToAnyPublisher()
    }

    private(set) var service: ObjectMemoryService = .unprobed

    private let stateSubject = PassthroughSubject<ObjectMemoryState, Never>()
    private let http: ObjectMemoryHTTPClient
    /// One question at a time. A second ask while one is in flight is dropped
    /// rather than queued: they are the same button, and two answers racing
    /// into one screen is a worse outcome than one ignored tap.
    private var isAsking = false

    init(http: ObjectMemoryHTTPClient = ObjectMemoryHTTPClient()) {
        self.http = http
    }

    // MARK: Availability

    /// The learned state of the Tower's object memory, projected onto the
    /// shell's shared four-case vocabulary.
    ///
    /// `.unprobed` with a reachable Tower projects to `.noContract`, which is
    /// the conservative reading — as far as this app has been *told*, nothing
    /// has been declared — and it is why the workspace uses
    /// `knownAvailability(isTowerReachable:)` instead. Hiding the one control
    /// that would find out, on the grounds that nobody has used it yet, is a
    /// loop that cannot terminate.
    func availability(isTowerReachable: Bool) -> CartridgeAvailability {
        switch service {
        // What the Tower can do outranks whether we can reach it, exactly as
        // `CartridgeAvailability.resolve` orders it: an unsupported agreement
        // is not fixed by reconnecting, and a Tower with no object memory is
        // not fixed by reconnecting either.
        case .speaksAnotherContract(let contract):
            return .unsupportedContract(declared: contract)
        case .notConfigured:
            return .noContract
        case .serving(let contract):
            return isTowerReachable ? .available(contract) : .towerUnreachable
        case .unreachable:
            return .towerUnreachable
        case .unprobed:
            return isTowerReachable ? .noContract : .towerUnreachable
        }
    }

    func knownAvailability(isTowerReachable: Bool) -> CartridgeAvailability? {
        if case .unprobed = service, isTowerReachable { return nil }
        return availability(isTowerReachable: isTowerReachable)
    }

    // MARK: Asking

    func ask(_ question: ObjectMemoryQuestion) async {
        guard !isAsking else { return }
        isAsking = true
        state = .asking(question)
        defer { isAsking = false }

        do {
            let answer: ObjectMemoryAnswer
            switch question {
            case .listing(let objectClass):
                answer = .listing(try await http.listing(objectClass: objectClass))
            case .lastSeen(let objectClass):
                answer = .lastSeen(try await http.lastSeen(objectClass: objectClass))
            }
            // Learned from the answer itself, which is the only place this
            // contract is ever declared.
            service = .serving(
                CartridgeContract(
                    cartridgeID: cartridgeID, identifier: answer.envelope.contract
                )
            )
            state = .answered(question: question, answer: answer)
        } catch let error as ObjectMemoryFetchError {
            apply(error)
        } catch {
            // A `CartridgeFailure` thrown by the decoder passes through
            // unchanged; anything else is `.transport`, which is the only
            // honest attribution available without knowing where it came from.
            //
            // `service` is deliberately left where it was. An answer this build
            // could not read says nothing about whether the Tower serves object
            // memory, and downgrading what we know on the strength of one bad
            // payload would report a Tower as absent because we misread it.
            state = .failed(CartridgeFailure.wrapping(error))
        }
    }

    private func apply(_ error: ObjectMemoryFetchError) {
        switch error {
        case .noObjectMemoryConfigured:
            service = .notConfigured
            // Its own state rather than a failure. This Tower serves no object
            // memory; nothing failed, and nothing about the wearer's memory is
            // being reported.
            state = .noObjectMemory

        case .unsupportedContract(let identifier):
            service = .speaksAnotherContract(
                CartridgeContract(cartridgeID: cartridgeID, identifier: identifier)
            )
            state = .failed(
                CartridgeFailure(
                    kind: .notSupported,
                    message: ObjectMemoryCopy.unsupportedContract(identifier)
                )
            )

        case .undecodable:
            // The service is left as it was: an unreadable answer says nothing
            // about whether this Tower serves object memory.
            state = .failed(
                CartridgeFailure(
                    kind: .undecodableResponse,
                    message: """
                        The Tower's object memory answered in a shape this app \
                        does not understand, so nothing is shown rather than \
                        something guessed.
                        """
                )
            )

        case .transport(let description):
            service = .unreachable(description)
            // The message carries only what this app learned, because
            // `CartridgeAvailability.towerUnreachable` already supplies the
            // sentence explaining what an unreachable Tower means — and the
            // two are joined before they reach the screen. Repeating the
            // framing here would print it twice.
            state = .failed(
                CartridgeFailure(
                    kind: .transport, message: "The Tower did not answer: \(description)"
                )
            )
        }
    }
}

// MARK: - View model

/// Publishes Object Memory state into SwiftUI.
///
/// Holds no runtime references, for the reason `WorldBuilderViewModel` gives:
/// it is destroyed and rebuilt on every workspace switch, and anything durable
/// belongs on the client in `CartridgeClients`.
@MainActor
final class ObjectMemoryViewModel: ObservableObject {
    @Published private(set) var state: ObjectMemoryState

    /// The category the next question will narrow to, or `nil` for all of them.
    ///
    /// Owned here rather than in the view so a question can also arrive from
    /// somewhere with no picker — the same seam `DocumentMemoryViewModel`
    /// keeps for an input layer that does not exist yet.
    @Published var selectedClass: String?

    private let client: any ObjectMemoryClient
    private var cancellables: Set<AnyCancellable> = []

    /// No default argument, for the reason `WorldBuilderViewModel.init(client:)`
    /// gives: a default would make constructing a second client at the point of
    /// use the path of least resistance, and this one must be the app's single
    /// long-lived instance.
    init(client: any ObjectMemoryClient) {
        self.client = client
        self.state = client.state

        client.stateUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in self?.state = state }
            .store(in: &cancellables)
    }

    // MARK: What the screen may say

    func availability(isTowerReachable: Bool) -> CartridgeAvailability {
        client.availability(isTowerReachable: isTowerReachable)
    }

    func knownAvailability(isTowerReachable: Bool) -> CartridgeAvailability? {
        client.knownAvailability(isTowerReachable: isTowerReachable)
    }

    /// The phase to draw.
    ///
    /// Availability outranks the client's own state **once it is known** — a
    /// Tower that has told us it serves no object memory must not render as
    /// `.idle`, which would invite a person to press a button that cannot work.
    /// Before anything has been asked there is nothing to outrank it with, and
    /// the state's own `.idle` is the truthful answer.
    func phase(isTowerReachable: Bool) -> CartridgePhase {
        knownAvailability(isTowerReachable: isTowerReachable)?.forcedPhase ?? state.phase
    }

    func unavailableExplanation(isTowerReachable: Bool) -> String {
        guard let availability = knownAvailability(isTowerReachable: isTowerReachable) else {
            return ""
        }
        // `.noContract` reaches this cartridge by a different route than it
        // reaches the others, and the shared sentence — "this Tower has not
        // declared a contract" — would be inaccurate for it. The Tower *did*
        // answer; it answered 404, which is a statement about how it is
        // configured. Its own wording is the honest one, and it stands alone.
        if case .noContract = availability {
            return ObjectMemoryCopy.noObjectMemoryConfigured
        }
        return availability.explanation(
            cartridgeName: ObjectMemoryCopy.cartridgeName, clientReason: clientReason
        )
    }

    private var clientReason: String? {
        switch state {
        case .noObjectMemory: return ObjectMemoryCopy.noObjectMemoryConfigured
        case .failed(let failure): return failure.message
        case .idle, .asking, .answered: return nil
        }
    }

    /// The categories this Tower's object memory can ever record, learned from
    /// the last answer.
    ///
    /// Empty until something has been asked, because until then this app has
    /// not been told — and a hardcoded `["laptop", "cell phone"]` would be this
    /// app asserting what the Tower looks for.
    var recordableClasses: [String] {
        state.answer?.envelope.recordedClasses ?? []
    }

    // MARK: Asking

    func askForEverything() {
        ask(.listing(objectClass: selectedClass))
    }

    func askWhenLastInView() {
        guard let objectClass = selectedClass else { return }
        ask(.lastSeen(objectClass: objectClass))
    }

    func ask(_ question: ObjectMemoryQuestion) {
        Task { await client.ask(question) }
    }
}
