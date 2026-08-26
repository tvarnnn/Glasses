//
//  ObjectMemoryTests.swift
//  GlassesTests
//
//  Object Memory's first product surface, tested at the three seams that can
//  actually be wrong on this side of the wire:
//
//  1. **Decoding** — against payloads shaped like the ones the live route
//     produces over the real 55-observation corpus, including the two the
//     contract insists on: an explicit `null` `spatial_ref`, and an empty
//     result set.
//  2. **Transport** — a stubbed `URLProtocol`, so a 404, an unreachable Tower
//     and a contract mismatch are exercised as the three different states they
//     are rather than as one "error".
//  3. **Copy** — the one that matters most. This cartridge knows far less than
//     a reader will assume, and every natural phrasing of what it holds is a
//     claim it cannot support. `ObjectMemoryCopyTests` runs the whole output of
//     `ObjectMemoryCopy` through the sentences it is forbidden to say.
//

import Combine
import Foundation
import XCTest
@testable import Glasses

// MARK: - Fixtures

/// Payloads shaped exactly like the route's.
///
/// Taken from a live dump of `build_observations` / `build_last_seen` against
/// `tower/data/object_memory` — including the values the contract document does
/// not mention, such as `retention_tag: "default"` and the fourth `confidence`
/// word — rather than from the field tables alone.
enum ObjectMemoryFixtures {

    static let contract = "object_memory.observations/2026-08-26"

    static func retention(
        requested: Any = NSNull(), effective: Any = 30.0, clamped: Bool = false
    ) -> [String: Any] {
        [
            "requested_days": requested,
            "effective_days": effective,
            "clamped": clamped,
            "policy": "min(persisted, requested): a reader may narrow this window and can never widen it",
        ]
    }

    static func envelope(
        objectClass: Any = NSNull(),
        retention: [String: Any] = ObjectMemoryFixtures.retention()
    ) -> [String: Any] {
        [
            "contract": contract,
            "claim": "category-was-visible-once",
            "identity": "category-not-instance",
            "absence_means": "not-observed-by-this-cartridge",
            // Explicit null at the envelope, not omitted. The decoder requires
            // the key to be *present and null*, because an absent key looks
            // like version skew and invites a client to go looking for the
            // value somewhere else.
            "spatial_ref": NSNull(),
            "recorded_classes": ["laptop", "cell phone"],
            "retention": retention,
            "object_class": objectClass,
        ]
    }

    static func frame(
        sessionID: Any = "22e9d4289cb440fbb3f14e6da369a136",
        frameSeq: Any = 3410,
        box: Any = [0.33483524322509767, 0.5125146865844726, 0.551875008477105, 0.7734769821166992]
    ) -> [String: Any] {
        [
            "kind": "frame-reference",
            "spatial_ref": NSNull(),
            "session_id": sessionID,
            "frame_seq": frameSeq,
            "camera": "glasses-camera",
            "bounding_box_normalized": box,
            "imagery_retention": "capture-side",
        ]
    }

    /// One record, with every field the route actually sends.
    static func observation(
        objectClass: String = "cell phone",
        confidence: String = "high",
        detectorScore: Any = 0.9320967793464661,
        bestScore: Any = 0.9950999617576599,
        frame: [String: Any] = ObjectMemoryFixtures.frame()
    ) -> [String: Any] {
        [
            "object_class": objectClass,
            "claim": "category-was-visible-once",
            "identity": "category-not-instance",
            "confidence": confidence,
            "detector_score": detectorScore,
            "best_score": bestScore,
            "observed_at": 1787695282.4820995,
            "time_basis": "tower-receipt",
            "recorded_at": 1787730242.226801,
            "module_id": "object-memory",
            "retention_tag": "default",
            "privacy_tags": ["derived-only", "frame-referenced"],
            "where": frame,
        ]
    }

    static func listing(
        observations: [[String: Any]] = [ObjectMemoryFixtures.observation()],
        objectClass: Any = NSNull(),
        count: Int? = nil
    ) -> [String: Any] {
        var payload = envelope(objectClass: objectClass)
        payload["observation_count"] = count ?? observations.count
        payload["observations"] = observations
        return payload
    }

    /// An empty listing.
    ///
    /// `[[String: Any]]()` rather than `[]`. An empty collection literal in an
    /// `Any` slot has no element type to infer and does not compile — a trap
    /// this codebase has already been bitten by once.
    static func emptyListing(objectClass: Any = NSNull()) -> [String: Any] {
        listing(observations: [[String: Any]](), objectClass: objectClass)
    }

    static func lastSeen(
        objectClass: String = "cell phone",
        recordable: Bool = true,
        observed: Bool = true,
        observation: Any? = nil
    ) -> [String: Any] {
        var payload = envelope(objectClass: objectClass)
        payload["recordable"] = recordable
        payload["observed"] = observed
        payload["observation"] = observation ?? (observed ? self.observation() : NSNull())
        payload["where"] = observed ? frame() : NSNull()
        return payload
    }

    /// The silence for a class the cartridge never writes.
    static func neverLookedFor(objectClass: String = "teapot") -> [String: Any] {
        var payload = envelope(objectClass: objectClass)
        payload["recordable"] = false
        payload["observed"] = false
        payload["observation"] = NSNull()
        payload["where"] = NSNull()
        return payload
    }

    static func data(_ json: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: json)
    }
}

// MARK: - Decoding

@MainActor
final class ObjectMemoryDecodingTests: XCTestCase {

    func testAListingDecodesFieldForField() throws {
        let listing = try ObjectMemoryDecoder.listing(from: ObjectMemoryFixtures.listing())

        XCTAssertEqual(listing.envelope.contract, ObjectMemoryContract.identifier)
        XCTAssertEqual(listing.envelope.recordedClasses, ["laptop", "cell phone"])
        XCTAssertNil(listing.envelope.objectClass, "an unfiltered listing narrowed to no class")
        XCTAssertEqual(listing.observations.count, 1)

        let observation = try XCTUnwrap(listing.observations.first)
        XCTAssertEqual(observation.objectClass, "cell phone")
        XCTAssertEqual(observation.confidence, .high)
        XCTAssertEqual(observation.timeBasis, "tower-receipt")
        XCTAssertEqual(observation.moduleID, "object-memory")
        XCTAssertEqual(observation.retentionTag, "default")
        XCTAssertEqual(observation.privacyTags, ["derived-only", "frame-referenced"])
        XCTAssertEqual(observation.frame.sessionID, "22e9d4289cb440fbb3f14e6da369a136")
        XCTAssertEqual(observation.frame.frameSeq, 3410)
        XCTAssertEqual(observation.frame.camera, "glasses-camera")
        XCTAssertEqual(observation.frame.imageryRetention, "capture-side")
        XCTAssertEqual(observation.frame.boundingBoxNormalized?.count, 4)
    }

    /// The retention view is the sharpest constraint in the contract, and the
    /// clamp is *reported* rather than merely applied.
    func testTheRetentionWindowDecodesIncludingTheClamp() throws {
        let payload = ObjectMemoryFixtures.listing()
        let listing = try ObjectMemoryDecoder.listing(from: payload)
        XCTAssertNil(listing.envelope.retention.requestedDays, "nothing was asked for")
        XCTAssertEqual(listing.envelope.retention.effectiveDays, 30.0)
        XCTAssertFalse(listing.envelope.retention.clamped)

        let clampedPayload = ObjectMemoryFixtures.listing()
        var clamped = clampedPayload
        clamped["retention"] = ObjectMemoryFixtures.retention(
            requested: 3650.0, effective: 30.0, clamped: true
        )
        let refused = try ObjectMemoryDecoder.listing(from: clamped)
        XCTAssertEqual(refused.envelope.retention.requestedDays, 3650.0)
        XCTAssertEqual(refused.envelope.retention.effectiveDays, 30.0)
        XCTAssertTrue(refused.envelope.retention.clamped, "a refused widening must be visible")
    }

    /// `effective_days == nil` is **unbounded**, and is never `0` — zero days
    /// would be the opposite claim.
    func testAnUnboundedWindowStaysNilRatherThanBecomingZero() throws {
        var payload = ObjectMemoryFixtures.listing()
        payload["retention"] = ObjectMemoryFixtures.retention(effective: NSNull())
        let listing = try ObjectMemoryDecoder.listing(from: payload)
        XCTAssertNil(listing.envelope.retention.effectiveDays)
    }

    /// The whole point of the cartridge, asserted on the type: `spatial_ref` is
    /// carried as an explicit null and there is nothing to read out of it.
    func testAnExplicitNullSpatialRefIsRequiredAndCarriesNothing() throws {
        let payload = ObjectMemoryFixtures.listing()
        XCTAssertTrue(
            ObjectMemoryDecoder.isExplicitlyNull(payload, key: "spatial_ref"),
            "the fixture must actually carry the null this test is about"
        )
        XCTAssertNoThrow(try ObjectMemoryDecoder.listing(from: payload))
    }

    /// An omitted key is not the same as a null one, and the contract sends the
    /// null deliberately.
    func testAnOmittedSpatialRefIsRefused() {
        var payload = ObjectMemoryFixtures.listing()
        payload.removeValue(forKey: "spatial_ref")
        XCTAssertNil(ObjectMemoryDecoder.envelope(from: payload))
    }

    /// A **populated** `spatial_ref` is refused rather than ignored. It would be
    /// a claim about where something is, and this app has no honest way to show
    /// one — decoding around it is how a reserved field becomes a map pin.
    func testAPopulatedSpatialRefIsRefusedRatherThanIgnored() {
        var frame = ObjectMemoryFixtures.frame()
        frame["spatial_ref"] = ["x": 1.0, "y": 2.0, "z": 3.0]
        XCTAssertNil(ObjectMemoryDecoder.frame(from: frame))

        var payload = ObjectMemoryFixtures.listing()
        payload["spatial_ref"] = ["frame": "world"]
        XCTAssertNil(ObjectMemoryDecoder.envelope(from: payload))
    }

    /// `null` means absent. Never `0`, never `""`.
    func testNullScoresStayNilRatherThanBecomingZero() throws {
        let payload = ObjectMemoryFixtures.listing(observations: [
            ObjectMemoryFixtures.observation(
                confidence: "unknown", detectorScore: NSNull(), bestScore: NSNull()
            )
        ])
        let listing = try ObjectMemoryDecoder.listing(from: payload)
        let observation = try XCTUnwrap(listing.observations.first)

        XCTAssertNil(observation.detectorScore)
        XCTAssertNil(observation.bestScore)
        XCTAssertNotEqual(observation.detectorScore, 0)
        XCTAssertNotEqual(observation.bestScore, 0)
    }

    /// `unknown` is a real fourth value on this wire.
    ///
    /// `docs/contracts/OBJECT-MEMORY.md` §4.4 lists three; `tower/confidence.py`
    /// defines four, and `Confidence.from_score(None)` returns the fourth. A
    /// decoder written from the document alone refuses a real record.
    func testTheFourthConfidenceValueDecodes() throws {
        for word in ["unknown", "low", "medium", "high"] {
            let payload = ObjectMemoryFixtures.listing(observations: [
                ObjectMemoryFixtures.observation(confidence: word)
            ])
            let listing = try ObjectMemoryDecoder.listing(from: payload)
            XCTAssertEqual(listing.observations.first?.confidence.rawValue, word)
        }
    }

    /// An empty result set is an **answer**, decoded like any other.
    func testAnEmptyListingDecodesAsAnAnswerRatherThanAFailure() throws {
        let listing = try ObjectMemoryDecoder.listing(
            from: ObjectMemoryFixtures.emptyListing(objectClass: "laptop")
        )
        XCTAssertTrue(listing.isEmpty)
        XCTAssertEqual(listing.observations.count, 0)
        XCTAssertEqual(listing.envelope.objectClass, "laptop")
        // The universe of classes still arrives, which is what lets an empty
        // answer distinguish "looked for and not seen" from "never looked for".
        XCTAssertEqual(listing.envelope.recordedClasses, ["laptop", "cell phone"])
    }

    /// A count that disagrees with the array is a broken payload, and the safe
    /// direction from a broken payload is a failure — never a smaller number of
    /// records, which reads as "you saw fewer things than you did".
    func testACountThatDisagreesWithTheArrayIsRefused() {
        let payload = ObjectMemoryFixtures.listing(count: 7)
        XCTAssertThrowsError(try ObjectMemoryDecoder.listing(from: payload)) { error in
            XCTAssertEqual((error as? CartridgeFailure)?.kind, .undecodableResponse)
        }
    }

    func testADifferentContractIsNotDecoded() {
        var payload = ObjectMemoryFixtures.listing()
        payload["contract"] = "object_memory.observations/2027-01-01"
        XCTAssertNil(ObjectMemoryDecoder.envelope(from: payload))
        XCTAssertEqual(
            ObjectMemoryDecoder.contractIdentifier(from: payload),
            "object_memory.observations/2027-01-01",
            "the identifier is still readable, so the app can say which one it saw"
        )
    }

    /// A change to any of the three claim values is the most breaking change
    /// this contract can carry: it changes what the data *means*. Rendering
    /// such a payload under the old wording is the worst failure available.
    func testAChangedClaimIsRefused() {
        for key in ["claim", "identity", "absence_means"] {
            var payload = ObjectMemoryFixtures.listing()
            payload[key] = "something-else"
            XCTAssertNil(
                ObjectMemoryDecoder.envelope(from: payload),
                "\(key) changed meaning and the payload still decoded"
            )
        }
        // Per record too, because a record travels out of the context of its
        // envelope the moment it is put in a list row.
        var record = ObjectMemoryFixtures.observation()
        record["identity"] = "instance"
        XCTAssertNil(ObjectMemoryDecoder.observation(from: record))
    }

    func testAWhereThatIsNotAFrameReferenceIsRefused() {
        var frame = ObjectMemoryFixtures.frame()
        frame["kind"] = "world-position"
        XCTAssertNil(ObjectMemoryDecoder.frame(from: frame))
    }

    /// A short box is a broken box, and half a rectangle is worse than none.
    func testAMalformedBoundingBoxIsRefused() {
        let frame = ObjectMemoryFixtures.frame(box: [0.1, 0.2])
        XCTAssertNil(ObjectMemoryDecoder.frame(from: frame))
    }

    /// A record with no capture provenance keeps `nil`, not a zeroth session.
    func testARecordWithoutCaptureProvenanceKeepsNils() throws {
        let frame = ObjectMemoryFixtures.frame(
            sessionID: NSNull(), frameSeq: NSNull(), box: NSNull()
        )
        let decoded = try XCTUnwrap(ObjectMemoryDecoder.frame(from: frame))
        XCTAssertNil(decoded.sessionID)
        XCTAssertNil(decoded.frameSeq)
        XCTAssertNil(decoded.boundingBoxNormalized)
        XCTAssertFalse(decoded.pointsAtACapture)
    }

    func testLastSeenDecodesASighting() throws {
        let answer = try ObjectMemoryDecoder.lastSeen(from: ObjectMemoryFixtures.lastSeen())
        XCTAssertTrue(answer.observed)
        XCTAssertTrue(answer.recordable)
        XCTAssertEqual(answer.objectClass, "cell phone")
        XCTAssertNotNil(answer.observation)
        XCTAssertEqual(answer.frame?.frameSeq, 3410)
    }

    /// The silence, decoded as a silence. 200, not 404 — a 404 would read as
    /// "there is no laptop", which is a claim about the world.
    func testLastSeenDecodesAnHonestSilence() throws {
        let answer = try ObjectMemoryDecoder.lastSeen(
            from: ObjectMemoryFixtures.lastSeen(objectClass: "laptop", observed: false)
        )
        XCTAssertFalse(answer.observed)
        XCTAssertTrue(answer.recordable, "laptop is a class this cartridge does write")
        XCTAssertNil(answer.observation)
        XCTAssertNil(answer.frame)
    }

    /// A class the cartridge never writes is a *weaker* silence, and the
    /// payload distinguishes it.
    func testAClassThatWasNeverLookedForSaysSo() throws {
        let answer = try ObjectMemoryDecoder.lastSeen(from: ObjectMemoryFixtures.neverLookedFor())
        XCTAssertFalse(answer.recordable)
        XCTAssertFalse(answer.observed)
    }

    /// `observed: true` with no record is not a coherent answer. Quietly
    /// rewriting it to "nothing observed" would manufacture a negative
    /// statement about the wearer's memory out of a decode failure.
    func testASightingWithNoRecordIsRefusedRatherThanEmptied() {
        var payload = ObjectMemoryFixtures.lastSeen()
        payload["observation"] = NSNull()
        XCTAssertThrowsError(try ObjectMemoryDecoder.lastSeen(from: payload)) { error in
            XCTAssertEqual((error as? CartridgeFailure)?.kind, .undecodableResponse)
        }
    }

    func testARecordWithNoSightingIsRefused() {
        var payload = ObjectMemoryFixtures.lastSeen()
        payload["observed"] = false
        XCTAssertThrowsError(try ObjectMemoryDecoder.lastSeen(from: payload))
    }
}

// MARK: - Transport

/// Answers HTTP requests without a network.
///
/// Deliberately holds only Foundation types, so it stays outside the app
/// target's default `MainActor` isolation and can be driven from the URL
/// loading system's own threads.
final class ObjectMemoryStubProtocol: URLProtocol {
    /// What to answer, and the requests that were made. Test-only global state,
    /// reset in `setUp`.
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?
    static var requestedURLs: [URL] = []

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        if let url = request.url { ObjectMemoryStubProtocol.requestedURLs.append(url) }
        guard let handler = ObjectMemoryStubProtocol.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

@MainActor
final class ObjectMemoryTransportTests: XCTestCase {

    private let baseURL = URL(string: "http://tower.test")!

    private func makeClient() -> ObjectMemoryHTTPClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ObjectMemoryStubProtocol.self]
        return ObjectMemoryHTTPClient(
            baseURL: baseURL, session: URLSession(configuration: configuration)
        )
    }

    private func respond(_ status: Int, _ json: [String: Any]) {
        ObjectMemoryStubProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil
            )!
            return (response, try JSONSerialization.data(withJSONObject: json))
        }
    }

    override func setUp() {
        super.setUp()
        ObjectMemoryStubProtocol.handler = nil
        ObjectMemoryStubProtocol.requestedURLs = []
    }

    override func tearDown() {
        ObjectMemoryStubProtocol.handler = nil
        ObjectMemoryStubProtocol.requestedURLs = []
        super.tearDown()
    }

    func testAListingIsFetchedAndDecoded() async throws {
        respond(200, ObjectMemoryFixtures.listing())
        let listing = try await makeClient().listing()
        XCTAssertEqual(listing.observations.count, 1)
        XCTAssertEqual(
            ObjectMemoryStubProtocol.requestedURLs.first?.path, "/object-memory/observations"
        )
    }

    func testNarrowingByClassAndWindowTravelsAsQuery() async throws {
        respond(200, ObjectMemoryFixtures.listing(objectClass: "laptop"))
        _ = try await makeClient().listing(objectClass: "laptop", retentionDays: 0.5)

        let url = try XCTUnwrap(ObjectMemoryStubProtocol.requestedURLs.first)
        let components = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false))
        let items = components.queryItems ?? []
        XCTAssertTrue(items.contains(URLQueryItem(name: "object_class", value: "laptop")))
        XCTAssertEqual(items.first { $0.name == "retention_days" }?.value, "0.5")
    }

    /// A class with a space in it is one of the two real ones.
    func testAClassWithASpaceIsPercentEncodedIntoThePath() async throws {
        respond(200, ObjectMemoryFixtures.lastSeen())
        _ = try await makeClient().lastSeen(objectClass: "cell phone")

        let url = try XCTUnwrap(ObjectMemoryStubProtocol.requestedURLs.first)
        XCTAssertEqual(url.path, "/object-memory/last-seen/cell phone")
        XCTAssertTrue(
            url.absoluteString.contains("cell%20phone"),
            "the space must be encoded rather than splitting the path: \(url.absoluteString)"
        )
    }

    /// 404 means **this Tower serves no object memory**. It is a statement
    /// about configuration and must never be reported as an answer about a
    /// class.
    func testAConfigurationFourOhFourIsItsOwnCase() async {
        respond(404, ["detail": "no object memory root is configured"])
        do {
            _ = try await makeClient().listing()
            XCTFail("a 404 decoded as an answer")
        } catch let error as ObjectMemoryFetchError {
            XCTAssertEqual(error, .noObjectMemoryConfigured)
        } catch {
            XCTFail("expected an ObjectMemoryFetchError, got \(error)")
        }
    }

    func testADifferentContractIsReportedRatherThanDecoded() async {
        var payload = ObjectMemoryFixtures.listing()
        payload["contract"] = "object_memory.observations/2027-01-01"
        respond(200, payload)
        do {
            _ = try await makeClient().listing()
            XCTFail("a foreign contract was decoded anyway")
        } catch let error as ObjectMemoryFetchError {
            XCTAssertEqual(
                error, .unsupportedContract(identifier: "object_memory.observations/2027-01-01")
            )
        } catch {
            XCTFail("expected an ObjectMemoryFetchError, got \(error)")
        }
    }

    /// The Tower being unreachable is a first-class state, not a crash and not
    /// an empty answer.
    func testAnUnreachableTowerBecomesATransportFailure() async {
        ObjectMemoryStubProtocol.handler = { _ in throw URLError(.cannotConnectToHost) }
        do {
            _ = try await makeClient().listing()
            XCTFail("an unreachable Tower produced an answer")
        } catch let error as ObjectMemoryFetchError {
            guard case .transport = error else {
                return XCTFail("expected .transport, got \(error)")
            }
        } catch {
            XCTFail("expected an ObjectMemoryFetchError, got \(error)")
        }
    }

    func testAnUnreadableBodyIsUndecodableRatherThanEmpty() async {
        ObjectMemoryStubProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
            )!
            return (response, Data("not json".utf8))
        }
        do {
            _ = try await makeClient().listing()
            XCTFail("garbage decoded as an answer")
        } catch let error as ObjectMemoryFetchError {
            XCTAssertEqual(error, .undecodable)
        } catch {
            XCTFail("expected an ObjectMemoryFetchError, got \(error)")
        }
    }
}

// MARK: - Client state

@MainActor
final class ObjectMemoryClientStateTests: XCTestCase {

    private let baseURL = URL(string: "http://tower.test")!

    private func makeClient() -> TowerObjectMemoryClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ObjectMemoryStubProtocol.self]
        return TowerObjectMemoryClient(
            http: ObjectMemoryHTTPClient(
                baseURL: baseURL, session: URLSession(configuration: configuration)
            )
        )
    }

    override func setUp() {
        super.setUp()
        ObjectMemoryStubProtocol.handler = nil
        ObjectMemoryStubProtocol.requestedURLs = []
    }

    override func tearDown() {
        ObjectMemoryStubProtocol.handler = nil
        super.tearDown()
    }

    private func respond(_ status: Int, _ json: [String: Any]) {
        ObjectMemoryStubProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil
            )!
            return (response, try JSONSerialization.data(withJSONObject: json))
        }
    }

    /// Construction touches nothing. No request until a person asks one.
    func testAFreshClientHasAskedNothing() {
        let client = makeClient()
        XCTAssertEqual(client.state, .idle)
        XCTAssertEqual(client.service, .unprobed)
        XCTAssertTrue(ObjectMemoryStubProtocol.requestedURLs.isEmpty)
    }

    /// The one case the shell's four-word availability vocabulary cannot say:
    /// nothing has been *asked*, which is not the same as nothing having been
    /// *declared*. Hiding the control that would find out is a loop that cannot
    /// terminate, so the workspace reads `knownAvailability` and gets `nil`.
    func testAvailabilityIsUnknownUntilSomethingHasBeenAsked() {
        let client = makeClient()
        XCTAssertNil(client.knownAvailability(isTowerReachable: true))
        // Projected conservatively for anything that needs a total answer.
        XCTAssertEqual(client.availability(isTowerReachable: true), .noContract)
        // With the socket down there is something true to say without asking.
        XCTAssertEqual(client.knownAvailability(isTowerReachable: false), .towerUnreachable)
    }

    func testAnAnswerTeachesTheClientWhichContractTheTowerSpeaks() async {
        respond(200, ObjectMemoryFixtures.listing())
        let client = makeClient()
        await client.ask(.listing(objectClass: nil))

        XCTAssertEqual(client.state.phase, .settled)
        XCTAssertNotNil(client.state.answer)
        XCTAssertEqual(
            client.service,
            .serving(
                CartridgeContract(
                    cartridgeID: "object-memory", identifier: ObjectMemoryContract.identifier
                )
            )
        )
        XCTAssertEqual(
            client.availability(isTowerReachable: true),
            .available(
                CartridgeContract(
                    cartridgeID: "object-memory", identifier: ObjectMemoryContract.identifier
                )
            )
        )
    }

    /// An empty answer is an answer: settled, not failed, and not empty-because
    /// -something-went-wrong.
    func testAnEmptyAnswerSettlesRatherThanFailing() async throws {
        respond(200, ObjectMemoryFixtures.emptyListing(objectClass: "laptop"))
        let client = makeClient()
        await client.ask(.listing(objectClass: "laptop"))

        XCTAssertEqual(client.state.phase, .settled)
        let answer = try XCTUnwrap(client.state.answer)
        XCTAssertFalse(answer.hasRecord, "an empty answer is still an answer")
    }

    /// A Tower with no object memory configured gets its own state, and it is
    /// never reported as a failure or as an empty memory.
    func testATowerWithNoObjectMemoryIsItsOwnState() async {
        respond(404, ["detail": "no object memory root is configured"])
        let client = makeClient()
        await client.ask(.listing(objectClass: nil))

        XCTAssertEqual(client.state, .noObjectMemory)
        XCTAssertEqual(client.state.phase, .unsupported)
        XCTAssertEqual(client.service, .notConfigured)
        XCTAssertEqual(client.availability(isTowerReachable: true), .noContract)
    }

    /// An unreachable Tower is drawn as `.disconnected`, not `.failed`: the
    /// capability exists and could not be reached, which calls for a different
    /// headline and glyph than a broken answer.
    func testAnUnreachableTowerIsADisconnectedStateNotAnError() async {
        ObjectMemoryStubProtocol.handler = { _ in throw URLError(.cannotConnectToHost) }
        let client = makeClient()
        await client.ask(.listing(objectClass: nil))

        XCTAssertEqual(client.state.phase, .disconnected)
        XCTAssertEqual(client.availability(isTowerReachable: true), .towerUnreachable)
        guard case .failed(let failure) = client.state else {
            return XCTFail("expected a failed state carrying the reason")
        }
        XCTAssertEqual(failure.kind, .transport)
        XCTAssertFalse(failure.message.isEmpty)
        XCTAssertNil(client.state.answer, "a phase that may not carry data carried some")
    }

    /// A phase that may not carry data must not carry any. The invariant
    /// `CartridgePhase.mayCarryData` exists to be checked, not assumed.
    func testNoStateCarriesDataItsPhaseForbids() async {
        respond(404, ["detail": "no object memory root is configured"])
        let client = makeClient()
        await client.ask(.listing(objectClass: nil))
        XCTAssertFalse(client.state.phase.mayCarryData)
        XCTAssertNil(client.state.answer)
    }

    /// An unreadable answer says nothing about whether the Tower serves object
    /// memory, so what was already learned is not thrown away.
    func testAnUnreadableAnswerDoesNotForgetTheTower() async {
        respond(200, ObjectMemoryFixtures.listing())
        let client = makeClient()
        await client.ask(.listing(objectClass: nil))

        respond(200, ObjectMemoryFixtures.listing(count: 9))
        await client.ask(.listing(objectClass: nil))

        XCTAssertEqual(client.state.phase, .failed)
        XCTAssertEqual(
            client.service,
            .serving(
                CartridgeContract(
                    cartridgeID: "object-memory", identifier: ObjectMemoryContract.identifier
                )
            ),
            "one bad payload reported the Tower as absent"
        )
    }

    func testTheClientAnswersForItsOwnCartridgeOnly() {
        XCTAssertEqual(makeClient().cartridgeID, "object-memory")
        XCTAssertTrue(Cartridge.catalog.contains { $0.id == "object-memory" })
    }
}

// MARK: - View model

/// A client that reports whatever a test needs, without a network.
@MainActor
final class StubObjectMemoryClient: ObjectMemoryClient {
    let cartridgeID = "object-memory"
    var state: ObjectMemoryState
    var service: ObjectMemoryService
    /// `nil` means "nothing has been asked", exactly as the real client reports
    /// it before a probe.
    var stubbedAvailability: CartridgeAvailability?
    private(set) var asked: [ObjectMemoryQuestion] = []

    private let subject = PassthroughSubject<ObjectMemoryState, Never>()
    var stateUpdates: AnyPublisher<ObjectMemoryState, Never> { subject.eraseToAnyPublisher() }

    init(
        state: ObjectMemoryState = .idle,
        service: ObjectMemoryService = .unprobed,
        availability: CartridgeAvailability? = nil
    ) {
        self.state = state
        self.service = service
        self.stubbedAvailability = availability
    }

    func availability(isTowerReachable: Bool) -> CartridgeAvailability {
        stubbedAvailability ?? .noContract
    }

    func knownAvailability(isTowerReachable: Bool) -> CartridgeAvailability? {
        stubbedAvailability
    }

    func ask(_ question: ObjectMemoryQuestion) async {
        asked.append(question)
    }

    func publish(_ state: ObjectMemoryState) {
        self.state = state
        subject.send(state)
    }
}

@MainActor
final class ObjectMemoryViewModelTests: XCTestCase {

    /// Lets one main-queue turn run.
    ///
    /// The view model subscribes with `.receive(on: DispatchQueue.main)` — which
    /// `TowerWorldBuilderClient` documents as load-bearing rather than
    /// stylistic — so a state published in a test is delivered on the *next*
    /// turn, and a synchronous assertion after `publish` would run first and
    /// see the old value.
    private func settle() async {
        try? await Task.sleep(nanoseconds: 50_000_000)
    }

    func testAnUnaskedWorkspaceIsIdleRatherThanUnsupported() {
        let memory = ObjectMemoryViewModel(client: StubObjectMemoryClient())
        XCTAssertEqual(memory.phase(isTowerReachable: true), .idle)
        XCTAssertTrue(memory.recordableClasses.isEmpty, "the app must not assert the Tower's list")
    }

    /// Availability outranks the client's own state once it is *known*.
    func testAKnownUnavailabilityOutranksTheState() {
        let client = StubObjectMemoryClient(
            state: .idle, service: .notConfigured, availability: .noContract
        )
        let memory = ObjectMemoryViewModel(client: client)
        XCTAssertEqual(memory.phase(isTowerReachable: true), .unsupported)
        XCTAssertEqual(
            memory.unavailableExplanation(isTowerReachable: true),
            ObjectMemoryCopy.noObjectMemoryConfigured,
            "the shared 'has not declared a contract' sentence is wrong for a 404"
        )
    }

    func testTheCategoryListComesFromTheAnswerNotFromThisApp() async throws {
        let listing = try ObjectMemoryDecoder.listing(from: ObjectMemoryFixtures.listing())
        let client = StubObjectMemoryClient()
        let memory = ObjectMemoryViewModel(client: client)
        XCTAssertTrue(memory.recordableClasses.isEmpty)

        client.publish(
            .answered(question: .listing(objectClass: nil), answer: .listing(listing))
        )
        await settle()
        XCTAssertEqual(memory.recordableClasses, ["laptop", "cell phone"])
    }

    func testAskingForOneCategoryCarriesTheSelection() async {
        let client = StubObjectMemoryClient()
        let memory = ObjectMemoryViewModel(client: client)
        memory.selectedClass = "laptop"
        memory.askWhenLastInView()

        // `ask` hops through a `Task`, so the question reaches the client on a
        // later turn rather than inside the call.
        var turns = 0
        while client.asked.isEmpty && turns < 100 {
            await Task.yield()
            turns += 1
        }
        XCTAssertEqual(client.asked, [.lastSeen(objectClass: "laptop")])
    }

    /// "When was it last in view" needs a category. With none selected there is
    /// no question to ask, and asking one anyway would answer about a class
    /// nobody named.
    func testLastInViewWithoutACategoryAsksNothing() {
        let client = StubObjectMemoryClient()
        let memory = ObjectMemoryViewModel(client: client)
        memory.selectedClass = nil
        memory.askWhenLastInView()
        XCTAssertTrue(client.asked.isEmpty)
    }
}

// MARK: - Copy

/// **The test this cartridge exists to pass.**
///
/// Object Memory knows three things: that a category was visible, once, and
/// when. It does not know whose object it was, where it is, or whether it is
/// still anywhere. Every fluent English sentence about "the laptop you saw"
/// claims at least one of those, so the copy is checked rather than trusted.
///
/// It asserts over `ObjectMemoryCopy`'s entire output, which is also the only
/// source the workspace view renders from.
@MainActor
final class ObjectMemoryCopyTests: XCTestCase {

    private func listing() throws -> ObservationListing {
        try ObjectMemoryDecoder.listing(
            from: ObjectMemoryFixtures.listing(observations: [
                ObjectMemoryFixtures.observation(objectClass: "laptop"),
                ObjectMemoryFixtures.observation(
                    objectClass: "cell phone",
                    confidence: "unknown",
                    detectorScore: NSNull(),
                    bestScore: NSNull(),
                    frame: ObjectMemoryFixtures.frame(
                        sessionID: NSNull(), frameSeq: NSNull(), box: NSNull()
                    )
                ),
            ])
        )
    }

    /// Sentences no string may contain, whatever it is describing.
    ///
    /// Two kinds. The class-independent ones are present-tense location and
    /// possession claims; the generated ones close the same door around each
    /// category the Tower can record, because "the laptop is on the desk" is
    /// the exact sentence a reader wants and the exact one that is false.
    private func forbiddenPhrases(classes: [String]) -> [String] {
        var phrases = [
            "still there",
            "is still",
            "right now",
            "at the moment",
            "on the map",
            "last known location",
            "location of",
            "we know where",
            "you left",
            "where you left",
            "go and get",
            "does not exist",
            "there is no ",
            "you have no ",
            "you do not have",
            "found your",
            "no results",
            "last seen in session",
            "seen in session",
        ]
        for objectClass in classes {
            phrases.append(contentsOf: [
                "your \(objectClass)",
                "my \(objectClass)",
                "the \(objectClass) is",
                "\(objectClass) is in",
                "\(objectClass) is at",
                "\(objectClass) is on",
                "\(objectClass) is still",
                "\(objectClass) exists",
            ])
        }
        return phrases
    }

    private func assertNoOverclaim(
        _ strings: [String], classes: [String], file: StaticString = #filePath, line: UInt = #line
    ) {
        let forbidden = forbiddenPhrases(classes: classes)
        for string in strings {
            let lowered = string.lowercased()
            XCTAssertFalse(lowered.isEmpty, "an empty string reached the screen", file: file, line: line)
            for phrase in forbidden {
                XCTAssertFalse(
                    lowered.contains(phrase),
                    "copy claims more than a record supports (\"\(phrase)\") in: \(string)",
                    file: file, line: line
                )
            }
        }
    }

    private let classes = ["laptop", "cell phone"]

    /// Every string shown for an answer that *found* something.
    func testCopyForAFoundRecordClaimsNoPossessionAndNoPlace() throws {
        let strings = ObjectMemoryCopy.everyString(
            for: .listing(try listing()), question: .listing(objectClass: nil)
        )
        XCTAssertFalse(strings.isEmpty)
        assertNoOverclaim(strings, classes: classes)
    }

    /// Every string shown for an answer that found nothing.
    func testCopyForAnEmptyAnswerClaimsNothingAboutTheWorld() throws {
        let empty = try ObjectMemoryDecoder.listing(
            from: ObjectMemoryFixtures.emptyListing(objectClass: "laptop")
        )
        let silence = try ObjectMemoryDecoder.lastSeen(
            from: ObjectMemoryFixtures.lastSeen(objectClass: "laptop", observed: false)
        )
        let neverLookedFor = try ObjectMemoryDecoder.lastSeen(
            from: ObjectMemoryFixtures.neverLookedFor()
        )

        assertNoOverclaim(
            ObjectMemoryCopy.everyString(for: .listing(empty)), classes: classes + ["teapot"]
        )
        assertNoOverclaim(
            ObjectMemoryCopy.everyString(for: .lastSeen(silence)), classes: classes + ["teapot"]
        )
        assertNoOverclaim(
            ObjectMemoryCopy.everyString(for: .lastSeen(neverLookedFor)),
            classes: classes + ["teapot"]
        )
    }

    /// Chrome is copy too. "Find my laptop" on a button would walk straight
    /// past a test that only read record rows.
    func testTheChromeMakesNoClaimEither() {
        assertNoOverclaim(ObjectMemoryCopy.everyStaticString, classes: classes)
        assertNoOverclaim(
            [
                ObjectMemoryCopy.lastInViewButton("laptop"),
                ObjectMemoryCopy.lastInViewButton("cell phone"),
                ObjectMemoryCopy.questionLine(.listing(objectClass: "laptop")),
                ObjectMemoryCopy.questionLine(.lastSeen(objectClass: "cell phone")),
            ],
            classes: classes
        )
    }

    /// A category, not an instance: an indefinite article and the past tense,
    /// every time.
    func testASightingHeadlineIsACategoryInThePastTense() throws {
        let listing = try self.listing()
        for observation in listing.observations {
            let headline = ObjectMemoryCopy.sightingHeadline(observation)
            XCTAssertTrue(
                headline.hasPrefix("A ") || headline.hasPrefix("An "),
                "not an indefinite article: \(headline)"
            )
            XCTAssertTrue(headline.hasSuffix(" was visible"), "not past tense: \(headline)")
            XCTAssertFalse(headline.lowercased().contains("your"))
            XCTAssertFalse(headline.lowercased().contains(" is "))
        }
    }

    /// The failure this whole screen is built against is
    /// *"Your laptop: last seen in session 22e9d4…"*. A capture id may never
    /// appear without the words that say what it is.
    func testACaptureIdentifierNeverAppearsWithoutBeingCalledAFrameReference() throws {
        let listing = try self.listing()
        let observation = try XCTUnwrap(listing.observations.first)
        let sessionID = try XCTUnwrap(observation.frame.sessionID)
        let shortened = ObjectMemoryCopy.shortened(sessionID)

        var sawTheIdentifier = false
        for string in ObjectMemoryCopy.everyString(for: observation) {
            guard string.contains(shortened) || string.contains(sessionID) else { continue }
            sawTheIdentifier = true
            XCTAssertTrue(
                string.contains("Frame reference"),
                "a capture id was shown without saying what it is: \(string)"
            )
        }
        XCTAssertTrue(sawTheIdentifier, "the fixture must actually render its capture id")
    }

    /// The two caveats that carry the contract's claims are not optional
    /// decoration: they must be in what a record renders.
    func testEveryRecordCarriesTheClaimAndTheNotAPlaceCaveat() throws {
        let listing = try self.listing()
        for observation in listing.observations {
            let strings = ObjectMemoryCopy.everyString(for: observation)
            XCTAssertTrue(
                strings.contains { $0.contains("not a place") },
                "a record was rendered without saying a frame reference is not a place"
            )
            XCTAssertTrue(
                strings.contains { $0.contains("does not say anything about now") },
                "a record was rendered without the once-visible claim"
            )
        }
    }

    /// An empty answer must say whose silence it is. "No results" would let a
    /// reader supply "so it is not there" for free.
    func testAnEmptyAnswerSaysWhoseSilenceItIs() {
        let explanation = ObjectMemoryCopy.nothingObservedExplanation(
            objectClass: "laptop", recordable: true
        )
        XCTAssertTrue(explanation.contains("not about what exists"))
        XCTAssertTrue(explanation.contains("Absence of a record is not absence of the thing"))

        let neverLookedFor = ObjectMemoryCopy.nothingObservedExplanation(
            objectClass: "teapot", recordable: false
        )
        XCTAssertTrue(neverLookedFor.contains("never been looked for"))
        XCTAssertTrue(neverLookedFor.contains("no information at all"))
        XCTAssertNotEqual(
            explanation, neverLookedFor,
            "the two silences must not share a sentence"
        )
    }

    /// A missing score is said out loud. Never `0%`, which would be a claim of
    /// no evidence rather than of no measurement.
    func testAMissingScoreIsNamedRatherThanZeroed() throws {
        let listing = try self.listing()
        let untracked = try XCTUnwrap(listing.observations.last)
        XCTAssertNil(untracked.bestScore)

        let line = ObjectMemoryCopy.confidenceLine(untracked)
        XCTAssertTrue(line.contains("not tracked"))
        XCTAssertTrue(line.contains("not recorded"))
        XCTAssertFalse(line.contains("0%"))
    }

    /// A record with no capture provenance says so, rather than pointing at
    /// nothing.
    func testARecordWithNoCaptureSaysThereIsNothingToPointAt() throws {
        let listing = try self.listing()
        let unpointed = try XCTUnwrap(listing.observations.last)
        XCTAssertFalse(unpointed.frame.pointsAtACapture)

        let line = ObjectMemoryCopy.frameLine(unpointed.frame)
        XCTAssertTrue(line.contains("Frame reference: none"))
        XCTAssertNil(ObjectMemoryCopy.boxLine(unpointed.frame))
        XCTAssertNil(
            ObjectMemoryCopy.imageryLine(unpointed.frame),
            "there is no imagery to warn about when nothing is pointed at"
        )
    }

    /// The time is the Tower's receipt time and is never presented as a shutter
    /// time — `Rule 16` forbids conflating them.
    func testTheTimestampIsQualifiedRatherThanPresentedAsACaptureTime() throws {
        let listing = try self.listing()
        let observation = try XCTUnwrap(listing.observations.first)
        let line = ObjectMemoryCopy.timeLine(observation)
        XCTAssertTrue(line.contains("receipt time"))
        XCTAssertTrue(line.contains("not the moment the shutter fired"))
    }

    /// A basis this build does not recognise is shown uninterpreted rather than
    /// being read as the one it does know.
    func testAnUnknownTimeBasisIsNotInterpreted() throws {
        var raw = ObjectMemoryFixtures.observation()
        raw["time_basis"] = "on-glasses-capture"
        let observation = try XCTUnwrap(ObjectMemoryDecoder.observation(from: raw))
        let line = ObjectMemoryCopy.timeLine(observation)
        XCTAssertTrue(line.contains("does not recognise"))
        XCTAssertTrue(line.contains("on-glasses-capture"))
        XCTAssertFalse(line.contains("receipt time"))
    }

    /// The window is stated, and a refused widening is stated separately —
    /// never silently.
    func testTheRetentionWindowIsStatedAndARefusalIsVisible() throws {
        let unclamped = ObjectMemoryRetention(
            requestedDays: nil, effectiveDays: 30, clamped: false, policy: "…"
        )
        XCTAssertTrue(ObjectMemoryCopy.retentionLine(unclamped).contains("30 days"))
        XCTAssertNil(
            ObjectMemoryCopy.clampLine(unclamped),
            "a caller that asked for nothing has been refused nothing"
        )

        let clamped = ObjectMemoryRetention(
            requestedDays: 3650, effectiveDays: 30, clamped: true, policy: "…"
        )
        let line = try XCTUnwrap(ObjectMemoryCopy.clampLine(clamped))
        XCTAssertTrue(line.contains("3650 days"))
        XCTAssertTrue(line.contains("refused"))
    }

    func testTheArticleAgreesWithTheCategory() {
        XCTAssertEqual(ObjectMemoryCopy.indefiniteArticle(for: "laptop"), "a")
        XCTAssertEqual(ObjectMemoryCopy.indefiniteArticle(for: "cell phone"), "a")
        XCTAssertEqual(ObjectMemoryCopy.indefiniteArticle(for: "apple"), "an")
        XCTAssertEqual(ObjectMemoryCopy.indefiniteArticle(for: ""), "a")
    }

    /// The drawer row is the first sentence a person reads about this module,
    /// and it used to promise the one thing the cartridge cannot do.
    func testTheCatalogSummaryDoesNotPromiseALocation() throws {
        let cartridge = try XCTUnwrap(Cartridge.catalog.first { $0.id == "object-memory" })
        assertNoOverclaim([cartridge.summary], classes: classes)
        XCTAssertFalse(cartridge.summary.lowercased().contains("where"))
        XCTAssertEqual(cartridge.workspace, .objectMemory)
        XCTAssertEqual(cartridge.status, .planned, "a screen does not promote a roadmap position")
    }
}
