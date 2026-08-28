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

    /// The `imagery` block, byte for byte as the live route emits it.
    ///
    /// **Templates, not URLs.** The Tower does not know what host a phone
    /// reached it on, so it hands out paths with `{observation_id}` in them and
    /// the client resolves them against the base URL it already holds.
    static func imageryRoutes(
        contract: Any = "object_memory.imagery/2026-08-27",
        claim: Any = "frame-from-the-recording-this-record-was-derived-from",
        filterMeans: Any = "applied-on-read-the-stored-frame-is-unchanged",
        view: Any = "/object-memory/observations/{observation_id}/imagery",
        frame: Any = "/object-memory/observations/{observation_id}/frame",
        crop: Any = "/object-memory/observations/{observation_id}/crop"
    ) -> [String: Any] {
        [
            "contract": contract,
            "claim": claim,
            "filter_means": filterMeans,
            "view": view,
            "frame": frame,
            "crop": crop,
        ]
    }

    static func envelope(
        objectClass: Any = NSNull(),
        retention: [String: Any] = ObjectMemoryFixtures.retention(),
        imagery: Any = ObjectMemoryFixtures.imageryRoutes()
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
            // Present on every real payload since 2026-08-27, and **dropped on
            // decode** until this build — which is why iOS showed a wearer a
            // capture id and a frame number and never the frame.
            "imagery": imagery,
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
    ///
    /// `observation_id` is the handle the three imagery routes take: 16 hex
    /// characters, **derived** from `session_id`, `object_class` and
    /// `observed_at` rather than minted, so a record written before the field
    /// existed has one too.
    static func observation(
        objectClass: String = "cell phone",
        confidence: String = "high",
        detectorScore: Any = 0.9320967793464661,
        bestScore: Any = 0.9950999617576599,
        frame: [String: Any] = ObjectMemoryFixtures.frame(),
        observationID: Any = "9f2c41b7ad0e6538",
        lastSeenAt: Any = 1787695291.118,
        frameCount: Any = 47,
        tier: Any = "remembered",
        verification: Any = NSNull()
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
            "observation_id": observationID,
            "last_seen_at": lastSeenAt,
            "frame_count": frameCount,
            "tier": tier,
            "verification": verification,
        ]
    }

    /// What a second opinion said. Absent on a default Tower — the verifier
    /// ships **off** — so this is only ever used deliberately.
    static func verification(
        agrees: Bool = true,
        label: Any = "mouse",
        score: Any = 0.2871,
        model: Any = "google/owlv2-base-patch16-ensemble"
    ) -> [String: Any] {
        [
            "agrees": agrees,
            "proposed": "mouse",
            "label": label,
            "score": score,
            "model": model,
            "reason": "above-threshold",
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

    // MARK: The session

    /// A session reading, byte for byte as the live route emits it — including
    /// `cartridge` and `worker`, which are on the wire and absent from the
    /// contract document's field table.
    static func session(
        state: Any = "stopped",
        supported: Bool = true,
        sessionID: Any = NSNull(),
        startedAt: Any = NSNull(),
        following: Any = [String](),
        captures: Any = [String](),
        contract: Any = "cartridge_session.control/2026-08-27",
        stateMeans: Any = "intent-not-liveness",
        actions: Any = ["start", "pause", "resume", "stop"]
    ) -> [String: Any] {
        [
            "cartridge": "object_memory",
            "worker": "object-memory-session",
            "supported": supported,
            "state": state,
            "session_id": sessionID,
            "started_at": startedAt,
            "changed_at": 1787832967.312166,
            "following": following,
            "captures": captures,
            "contract": contract,
            "state_means": stateMeans,
            "states": ["stopped", "active", "paused"],
            "actions": actions,
        ]
    }

    /// The same, with the three fields a `POST` adds.
    static func sessionAction(
        state: Any = "active",
        changed: Bool = true,
        attachedCaptureID: Any = NSNull(),
        sessionID: Any = "61a78a9b32284cd2a89583d9a8cc8702",
        startedAt: Any = 1787833925.6521091,
        following: Any = [String]()
    ) -> [String: Any] {
        var payload = session(
            state: state, sessionID: sessionID, startedAt: startedAt, following: following
        )
        payload["accepted"] = true
        payload["changed"] = changed
        payload["attached_capture_id"] = attachedCaptureID
        return payload
    }

    /// A 409 body, **inside FastAPI's `detail` wrapper** exactly as it arrives.
    ///
    /// `reason` is a parameter with no default worth calling safe, because the
    /// contract document and the running Tower disagree about which word a
    /// `resume` from `stopped` carries — the document says `not-active`, the
    /// wire says `not-paused` — and every test here exercises both.
    static func sessionRefusal(
        reason: String,
        message: String = "there is no paused session to resume; this cartridge is stopped",
        state: Any = "stopped"
    ) -> [String: Any] {
        var body = session(state: state)
        body["accepted"] = false
        body["reason"] = reason
        body["message"] = message
        return ["detail": body]
    }

    // MARK: The pictures

    /// An `/imagery` description. Defaults to a served picture.
    static func imagery(
        observationID: Any = "9f2c41b7ad0e6538",
        objectClass: Any = "laptop",
        available: Bool = true,
        reason: Any = NSNull(),
        memoryRetained: Bool = true,
        filter: Any = "display-filter/yunet-2023mar@0.30",
        regionsFilled: Any = 0,
        subjectObscured: Any = 0.0,
        box: Any = [0.1120081901550293, 0.6517109870910645, 0.44075003729926215, 0.9019964218139649],
        contract: Any = "object_memory.imagery/2026-08-27",
        claim: Any = "frame-from-the-recording-this-record-was-derived-from",
        filterMeans: Any = "applied-on-read-the-stored-frame-is-unchanged"
    ) -> [String: Any] {
        [
            "contract": contract,
            "observation_id": observationID,
            "object_class": objectClass,
            "claim": claim,
            "available": available,
            "reason": reason,
            "memory_retained": memoryRetained,
            "filter": filter,
            "filter_means": filterMeans,
            "regions_filled": regionsFilled,
            "subject_obscured": subjectObscured,
            "bounding_box_normalized": box,
            "imagery_retention": "capture-side",
        ]
    }

    /// **The 410.** The pointer is intact and the picture is gone.
    ///
    /// `memory_retained: true` with `available: false` is the entire reason the
    /// payload has this shape, and `filter` is null because nothing was served
    /// and therefore nothing was filtered.
    static func imageryGone() -> [String: Any] {
        [
            "detail": imagery(
                available: false,
                reason: "imagery-no-longer-available",
                memoryRetained: true,
                filter: NSNull()
            )
        ]
    }

    /// A 503: this Tower serves no picture at all. **There is no lenient
    /// default here, because the lenient default is a raw first-person frame.**
    static func imageryRefused(reason: String) -> [String: Any] {
        [
            "detail": imagery(
                available: false, reason: reason, memoryRetained: true, filter: NSNull()
            )
        ]
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
    /// The whole request, not just its URL.
    ///
    /// A URL alone cannot answer "did the request that actually ran carry the
    /// deadline the client claims to set?", and a test that reads the client's
    /// own `timeout` property back instead is reading the literal it was
    /// initialised with — it stays green when the `timeoutInterval` is dropped
    /// from the `URLRequest` and the call silently inherits `URLSession`'s
    /// 60-second default.
    static var requestedRequests: [URLRequest] = []

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        if let url = request.url { ObjectMemoryStubProtocol.requestedURLs.append(url) }
        ObjectMemoryStubProtocol.requestedRequests.append(request)
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
        ObjectMemoryStubProtocol.requestedRequests = []
    }

    override func tearDown() {
        ObjectMemoryStubProtocol.handler = nil
        ObjectMemoryStubProtocol.requestedURLs = []
        ObjectMemoryStubProtocol.requestedRequests = []
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

    /// The session half. Same discipline: whatever a test needs, with the
    /// verbs it was sent recorded so a test can assert what the workspace
    /// actually did rather than what it displayed afterwards.
    var session: ObjectMemorySessionState
    private(set) var applied: [CartridgeSessionAction] = []
    private(set) var sessionReads = 0
    /// What the next `readSession` should report. Lets a test model the
    /// producer that ignored `SIGTERM`: a Pause that answers `paused` and a
    /// read-back that still names the capture.
    var sessionAfterRead: ObjectMemorySessionState?

    /// The imagery half, and what was asked for.
    var stubbedImagery: ObjectMemoryImageryAnswer = .routesUnknown
    var stubbedPicture: ObjectMemoryPictureAnswer = .routesUnknown
    private(set) var imageryAsked: [String] = []
    private(set) var picturesAsked: [(String, ObjectMemoryImageryKind)] = []

    private let subject = PassthroughSubject<ObjectMemoryState, Never>()
    var stateUpdates: AnyPublisher<ObjectMemoryState, Never> { subject.eraseToAnyPublisher() }

    private let sessionSubject = PassthroughSubject<ObjectMemorySessionState, Never>()
    var sessionUpdates: AnyPublisher<ObjectMemorySessionState, Never> {
        sessionSubject.eraseToAnyPublisher()
    }

    init(
        state: ObjectMemoryState = .idle,
        service: ObjectMemoryService = .unprobed,
        availability: CartridgeAvailability? = nil,
        session: ObjectMemorySessionState = .unread
    ) {
        self.state = state
        self.service = service
        self.stubbedAvailability = availability
        self.session = session
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

    func readSession() async {
        sessionReads += 1
        if let next = sessionAfterRead { publish(next) }
    }

    func apply(_ action: CartridgeSessionAction) async {
        applied.append(action)
        if let next = sessionAfterRead { publish(next) }
    }

    func imageryDescription(for observationID: String) async -> ObjectMemoryImageryAnswer {
        imageryAsked.append(observationID)
        return stubbedImagery
    }

    func picture(
        for observationID: String, kind: ObjectMemoryImageryKind
    ) async -> ObjectMemoryPictureAnswer {
        picturesAsked.append((observationID, kind))
        return stubbedPicture
    }

    func publish(_ state: ObjectMemoryState) {
        self.state = state
        subject.send(state)
    }

    func publish(_ session: ObjectMemorySessionState) {
        self.session = session
        sessionSubject.send(session)
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
        // Was `.planned`, asserted as "a screen does not promote a roadmap
        // position" — true while the badge answered a roadmap question. It no
        // longer does. `CartridgeStatus` now answers what a person can do in
        // this build, and Object Memory has two live HTTP routes and a decoder
        // pinned against a real Tower's bytes further down this very file.
        //
        // The live Tower answering 404 (`no object memory root is configured`)
        // does not change this: that is one Tower's configuration, and the
        // workspace renders it truthfully — see the tests above.
        XCTAssertEqual(cartridge.status, .readyToTest)
    }
}

// MARK: - Pinned against a real Tower

/// The three branches, decoded from **bytes taken verbatim off a running
/// Tower** rather than from a reading of its contract.
///
/// The composed fixtures above prove the decoder reads what this build
/// expects. These prove the Tower sends it — and in particular that all three
/// arrive as HTTP 200 with the same envelope, which is the single most likely
/// functional bug here: absence is not a 404, and the two silences are not the
/// same silence.
final class ObjectMemoryRealTowerTests: XCTestCase {

    private func answer(_ text: String) throws -> LastSeenAnswer {
        let json = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any]
        )
        return try ObjectMemoryDecoder.lastSeen(from: json)
    }

    /// Recordable, and seen inside the window.
    func testARealSeenAnswerDecodesFieldForField() throws {
        let seen = try answer(Self.seenFromTower)

        XCTAssertEqual(seen.envelope.contract, "object_memory.observations/2026-08-26")
        XCTAssertEqual(seen.envelope.claim, "category-was-visible-once")
        XCTAssertEqual(seen.envelope.identity, "category-not-instance")
        XCTAssertEqual(seen.envelope.absenceMeans, "not-observed-by-this-cartridge")
        XCTAssertEqual(seen.envelope.recordedClasses, ["laptop", "cell phone"])

        XCTAssertTrue(seen.recordable)
        XCTAssertTrue(seen.observed)
        let observation = try XCTUnwrap(seen.observation)

        // "Where" is a pointer back into a recording, never a place. The Tower
        // nulls `spatial_ref` on read, and this build must carry that through
        // rather than inventing a location from the frame reference.
        XCTAssertEqual(observation.frame.camera, "glasses-camera")
        XCTAssertEqual(observation.frame.imageryRetention, "capture-side")
        XCTAssertEqual(observation.frame.frameSeq, 3214)
        XCTAssertEqual(observation.privacyTags, ["derived-only", "frame-referenced"])
    }

    /// Recordable, and **nothing inside the window** — a real statement about
    /// what the camera captured.
    func testARealUnobservedAnswerIsARecordableClassWithNoRecord() throws {
        let narrowed = try answer(Self.narrowedFromTower)

        XCTAssertTrue(narrowed.recordable, "the class is one the cartridge writes")
        XCTAssertFalse(narrowed.observed)
        XCTAssertNil(narrowed.observation, "absent, not an empty observation")
    }

    /// **Never looked for.** Carries no information at all, and must not read
    /// to a person the way the case above does.
    func testARealNeverLookedForAnswerIsTheWeakerSilence() throws {
        let never = try answer(Self.neverFromTower)

        XCTAssertFalse(never.recordable, "person is not in the whitelist")
        XCTAssertFalse(never.observed)
        XCTAssertNil(never.observation)

        // The distinction the whole screen turns on: both say "no record", and
        // only one of them is a statement about the world.
        let narrowed = try answer(Self.narrowedFromTower)
        XCTAssertNotEqual(
            never.recordable, narrowed.recordable,
            "the two silences must stay tellable apart after decoding"
        )
    }

    /// `GET /object-memory/last-seen/laptop`, verbatim.
    private static let seenFromTower = """
        {"contract":"object_memory.observations/2026-08-26","claim":"category-was-visible-once","identity":"category-not-instance","absence_means":"not-observed-by-this-cartridge","spatial_ref":null,"recorded_classes":["laptop","cell phone"],"retention":{"requested_days":null,"effective_days":30.0,"clamped":false,"policy":"min(persisted, requested): a reader may narrow this window and can never widen it"},"object_class":"laptop","recordable":true,"observed":true,"observation":{"object_class":"laptop","claim":"category-was-visible-once","identity":"category-not-instance","confidence":"high","detector_score":0.5121034979820251,"best_score":0.9853731989860535,"observed_at":1787695274.3187459,"time_basis":"tower-receipt","recorded_at":1787730238.1640532,"module_id":"object-memory","retention_tag":"default","privacy_tags":["derived-only","frame-referenced"],"where":{"kind":"frame-reference","spatial_ref":null,"session_id":"22e9d4289cb440fbb3f14e6da369a136","frame_seq":3214,"camera":"glasses-camera","bounding_box_normalized":[0.1120081901550293,0.6517109870910645,0.44075003729926215,0.9019964218139649],"imagery_retention":"capture-side"}},"where":{"kind":"frame-reference","spatial_ref":null,"session_id":"22e9d4289cb440fbb3f14e6da369a136","frame_seq":3214,"camera":"glasses-camera","bounding_box_normalized":[0.1120081901550293,0.6517109870910645,0.44075003729926215,0.9019964218139649],"imagery_retention":"capture-side"}}
        """

    /// `GET /object-memory/last-seen/laptop?retention_days=1e-07`, verbatim.
    /// A window narrowed past every record. `clamped` is false because the
    /// reader narrowed rather than tried to widen.
    private static let narrowedFromTower = """
        {"contract":"object_memory.observations/2026-08-26","claim":"category-was-visible-once","identity":"category-not-instance","absence_means":"not-observed-by-this-cartridge","spatial_ref":null,"recorded_classes":["laptop","cell phone"],"retention":{"requested_days":1e-7,"effective_days":1e-7,"clamped":false,"policy":"min(persisted, requested): a reader may narrow this window and can never widen it"},"object_class":"laptop","recordable":true,"observed":false,"observation":null,"where":null}
        """

    /// `GET /object-memory/last-seen/person`, verbatim. The corpus holds zero
    /// `person` observations and `person` is not a recordable class, so this is
    /// the third branch and it is still HTTP 200.
    private static let neverFromTower = """
        {"contract":"object_memory.observations/2026-08-26","claim":"category-was-visible-once","identity":"category-not-instance","absence_means":"not-observed-by-this-cartridge","spatial_ref":null,"recorded_classes":["laptop","cell phone"],"retention":{"requested_days":null,"effective_days":30.0,"clamped":false,"policy":"min(persisted, requested): a reader may narrow this window and can never widen it"},"object_class":"person","recordable":false,"observed":false,"observation":null,"where":null}
        """
}

// MARK: - Session decoding

/// The generic Start/Pause/Resume/Stop surface, decoded from the shapes the
/// running Tower emits.
///
/// The payload carries two fields that describe the same session and mean
/// different things, and getting them the wrong way round is the one failure
/// this whole surface exists to prevent. Every test here that touches
/// `following` is about that.
final class CartridgeSessionDecodingTests: XCTestCase {

    func testASessionReadingDecodesFieldForField() throws {
        let snapshot = try XCTUnwrap(
            CartridgeSessionDecoder.snapshot(from: ObjectMemoryFixtures.session())
        )

        XCTAssertEqual(snapshot.contract, "cartridge_session.control/2026-08-27")
        XCTAssertEqual(snapshot.cartridge, "object_memory")
        XCTAssertEqual(snapshot.worker, "object-memory-session")
        XCTAssertTrue(snapshot.supported)
        XCTAssertEqual(snapshot.state, .stopped)
        XCTAssertEqual(snapshot.stateMeans, "intent-not-liveness")
        XCTAssertEqual(snapshot.states, [.stopped, .active, .paused])
        XCTAssertEqual(snapshot.offeredActions, [.start, .pause, .resume, .stop])
        XCTAssertTrue(snapshot.unofferedActions.isEmpty)
        XCTAssertNil(snapshot.sessionID)
        XCTAssertNil(snapshot.startedAt)
        XCTAssertTrue(snapshot.following.isEmpty)

        // A read, not an action. `nil` rather than `false`, because "this was a
        // refresh" and "this action changed nothing" are different facts and a
        // `false` here would report every refresh as a double tap.
        XCTAssertNil(snapshot.accepted)
        XCTAssertNil(snapshot.changed)
        XCTAssertNil(snapshot.wasAnIdempotentNoOp)
    }

    /// The contract identifier is opaque and compared for equality. A different
    /// date is a different agreement, not a newer one.
    func testADifferentSessionContractIsNotDecoded() {
        XCTAssertNil(
            CartridgeSessionDecoder.snapshot(
                from: ObjectMemoryFixtures.session(
                    contract: "cartridge_session.control/2027-01-01"
                )
            )
        )
    }

    /// `state_means` is the Tower saying that `state` is not liveness. A
    /// payload that stopped saying it means something this build's entire
    /// rendering assumes, so it is refused rather than decoded on the old
    /// assumption.
    func testAChangedStateMeaningIsRefusedRatherThanIgnored() {
        XCTAssertNil(
            CartridgeSessionDecoder.snapshot(
                from: ObjectMemoryFixtures.session(stateMeans: "liveness")
            )
        )
    }

    /// A fourth state must arrive **as itself**. Failing the decode would take
    /// the controls off screen; folding it into `stopped` would tell somebody
    /// nothing is running when the Tower did not say that.
    func testAnUnrecognisedStateSurvivesRatherThanBecomingStopped() throws {
        let snapshot = try XCTUnwrap(
            CartridgeSessionDecoder.snapshot(
                from: ObjectMemoryFixtures.session(state: "draining")
            )
        )
        XCTAssertEqual(snapshot.state.rawValue, "draining")
        XCTAssertFalse(snapshot.state.isRecognised)
        XCTAssertNotEqual(snapshot.state, .stopped)
    }

    /// A verb the Tower offers and this build has no button for is reported
    /// rather than dropped: a control surface that silently hides half its
    /// vocabulary looks complete and is not.
    func testAVerbThisBuildCannotSendIsReportedRatherThanHidden() throws {
        let snapshot = try XCTUnwrap(
            CartridgeSessionDecoder.snapshot(
                from: ObjectMemoryFixtures.session(
                    actions: ["start", "pause", "resume", "stop", "flush"]
                )
            )
        )
        XCTAssertEqual(snapshot.offeredActions, [.start, .pause, .resume, .stop])
        XCTAssertEqual(snapshot.unofferedActions, ["flush"])
    }

    /// A `POST` adds three fields, and `changed: false` is **not an error**.
    func testAnIdempotentNoOpDecodesAsHonouredAndUnmoved() throws {
        let snapshot = try XCTUnwrap(
            CartridgeSessionDecoder.snapshot(
                from: ObjectMemoryFixtures.sessionAction(changed: false)
            )
        )
        XCTAssertEqual(snapshot.accepted, true)
        XCTAssertEqual(snapshot.changed, false)
        XCTAssertEqual(snapshot.wasAnIdempotentNoOp, true)
    }

    /// Starting before the camera is running is legal, and the payload says so
    /// with an `active` state and a null capture. A decoder that treated the
    /// null as a failure would refuse the normal case.
    func testStartingBeforeTheCameraIsLegalAndCarriesNoCapture() throws {
        let snapshot = try XCTUnwrap(
            CartridgeSessionDecoder.snapshot(from: ObjectMemoryFixtures.sessionAction())
        )
        XCTAssertEqual(snapshot.state, .active)
        XCTAssertNil(snapshot.attachedCaptureID)
        XCTAssertTrue(snapshot.following.isEmpty)
    }

    /// Both words the two Towers use for the same refusal decode, and both keep
    /// the state that was actually reached.
    func testBothRefusalWordsDecodeAndCarryTheStateActuallyReached() throws {
        for reason in CartridgeSessionRefusalReason.interchangeableStateRefusals {
            let body = try XCTUnwrap(
                ObjectMemoryFixtures.sessionRefusal(reason: reason.rawValue)["detail"]
                    as? [String: Any]
            )
            let refusal = try XCTUnwrap(
                CartridgeSessionDecoder.refusal(from: body, action: .resume)
            )
            XCTAssertEqual(refusal.reason, reason)
            XCTAssertEqual(refusal.action, .resume)
            XCTAssertEqual(refusal.snapshot.state, .stopped)
        }
    }
}

// MARK: - Liveness

/// **The invariant this cartridge is most likely to get wrong, pinned.**
///
/// `state` is intent. `following` is fact. A Pause whose producer ignores
/// `SIGTERM` answers 200 with `state: "paused"` and `changed: true` — a
/// positive claim that the action took effect — while `following` still names
/// the capture and the process is still recording. A Pause button keyed on
/// `state` tells a person they stopped being recorded when they did not.
///
/// These tests exist so that a future refactor which "simplifies" liveness into
/// `state == .active` fails here rather than on somebody's head.
final class ObjectMemoryLivenessTests: XCTestCase {

    private func snapshot(
        state: String, following: [String]
    ) throws -> CartridgeSessionSnapshot {
        try XCTUnwrap(
            CartridgeSessionDecoder.snapshot(
                from: ObjectMemoryFixtures.session(state: state, following: following)
            )
        )
    }

    /// **The reproduced failure.** Paused, and still recording.
    func testAPausedSessionStillFollowingACaptureIsStillRecording() throws {
        let paused = try snapshot(state: "paused", following: ["22e9d4289cb440fb"])

        XCTAssertEqual(paused.state, .paused, "intent says the pause was honoured")
        XCTAssertTrue(
            paused.isFollowingACapture,
            """
            liveness comes from `following`, and a producer that ignored SIGTERM \
            is still writing — reading `state` here is what tells a person they \
            stopped being recorded when they did not
            """
        )
        XCTAssertTrue(paused.intentContradictsLiveness)
    }

    /// A Stop that did not stop is the same failure one step further on, and
    /// must be reported the same way rather than trusted because Stop is never
    /// refused.
    func testAStoppedSessionStillFollowingACaptureIsStillRecording() throws {
        let stopped = try snapshot(state: "stopped", following: ["22e9d4289cb440fb"])
        XCTAssertTrue(stopped.isFollowingACapture)
        XCTAssertTrue(stopped.intentContradictsLiveness)
    }

    /// **Active with nothing followed is legal, and must not be reported as a
    /// contradiction.** Start before the camera is running looks exactly like
    /// this, and so does a producer that died — one payload cannot tell them
    /// apart, so this app says what it knows instead of guessing which.
    func testAnActiveSessionFollowingNothingIsNotClaimedAsAFailure() throws {
        let active = try snapshot(state: "active", following: [])
        XCTAssertFalse(active.isFollowingACapture, "nothing is being written into")
        XCTAssertFalse(
            active.intentContradictsLiveness,
            "starting before the camera is legal and is not a producer that died"
        )
    }

    /// An unrecognised state makes no contradiction claim either way, and
    /// liveness still reads correctly off `following`.
    func testAnUnrecognisedStateStillYieldsLivenessFromFollowing() throws {
        let odd = try snapshot(state: "draining", following: ["22e9d4289cb440fb"])
        XCTAssertTrue(odd.isFollowingACapture)
        XCTAssertFalse(
            odd.intentContradictsLiveness,
            "this app cannot say a state it does not understand contradicts anything"
        )
    }

    /// `captures` is a history and `following` is not. A recording the producer
    /// has finished with must never light the live indicator.
    func testAFinishedCaptureInTheHistoryIsNotLiveness() throws {
        let snapshot = try XCTUnwrap(
            CartridgeSessionDecoder.snapshot(
                from: ObjectMemoryFixtures.session(
                    state: "active", following: [], captures: ["22e9d4289cb440fb"]
                )
            )
        )
        XCTAssertFalse(snapshot.isFollowingACapture)
        XCTAssertEqual(snapshot.captures.count, 1)
    }

    /// The copy obeys the same rule as the model, because the model being right
    /// buys nothing if the sentence is written from the other field.
    func testTheLivenessSentenceIsWrittenFromFollowingNotFromState() throws {
        let pausedAndRecording = try snapshot(
            state: "paused", following: ["22e9d4289cb440fb"]
        )
        let activeAndIdle = try snapshot(state: "active", following: [])

        XCTAssertNotEqual(
            ObjectMemoryCopy.livenessLine(pausedAndRecording),
            ObjectMemoryCopy.livenessLine(activeAndIdle),
            "two sessions with opposite `following` must not read the same"
        )
        // And the pairing is the *opposite* of what `state` would give: the
        // paused one is the one being written into.
        XCTAssertEqual(
            ObjectMemoryCopy.livenessLine(pausedAndRecording),
            ObjectMemoryCopy.livenessLine(
                try snapshot(state: "active", following: ["22e9d4289cb440fb"])
            ),
            "the sentence must depend on `following` alone, not on `state`"
        )
        XCTAssertNotNil(
            ObjectMemoryCopy.livenessContradictsIntentLine(pausedAndRecording),
            "the harmful contradiction has to be said out loud"
        )
        XCTAssertNil(ObjectMemoryCopy.livenessContradictsIntentLine(activeAndIdle))
    }

    /// The view model's own liveness accessor, which is what the screen binds
    /// to. `nil` before anything is read — not `false`, which would be a claim.
    @MainActor
    func testTheWorkspaceHasNoLivenessClaimBeforeItHasRead() async throws {
        let client = StubObjectMemoryClient()
        let memory = ObjectMemoryViewModel(client: client)
        XCTAssertNil(memory.liveness, "\"we have not asked\" is not \"nothing is recording\"")

        client.publish(
            ObjectMemorySessionState.known(
                try snapshot(state: "paused", following: ["22e9d4289cb440fb"])
            )
        )
        try await Task.sleep(nanoseconds: 30_000_000)
        XCTAssertEqual(memory.liveness, true)
        XCTAssertTrue(memory.intentContradictsLiveness)
    }
}

// MARK: - Session transport

@MainActor
final class CartridgeSessionTransportTests: XCTestCase {

    private let baseURL = URL(string: "http://tower.test")!

    private func makeClient() -> CartridgeSessionHTTPClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ObjectMemoryStubProtocol.self]
        return CartridgeSessionHTTPClient(
            baseURL: baseURL, session: URLSession(configuration: configuration)
        )
    }

    private func respond(_ status: Int, _ json: Any) {
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
        ObjectMemoryStubProtocol.requestedRequests = []
    }

    override func tearDown() {
        ObjectMemoryStubProtocol.handler = nil
        ObjectMemoryStubProtocol.requestedURLs = []
        ObjectMemoryStubProtocol.requestedRequests = []
        super.tearDown()
    }

    func testTheSessionIsReadFromTheCartridgeKeyedPath() async throws {
        respond(200, ObjectMemoryFixtures.session())
        _ = try await makeClient().read()

        let url = try XCTUnwrap(ObjectMemoryStubProtocol.requestedURLs.first)
        XCTAssertEqual(url.path, "/cartridges/object_memory/session")
        XCTAssertEqual(ObjectMemoryStubProtocol.requestedRequests.first?.httpMethod, "GET")
    }

    func testEachVerbPostsToItsOwnPath() async throws {
        for action in CartridgeSessionAction.allCases {
            ObjectMemoryStubProtocol.requestedURLs = []
            ObjectMemoryStubProtocol.requestedRequests = []
            respond(200, ObjectMemoryFixtures.sessionAction())
            _ = try await makeClient().apply(action)

            let url = try XCTUnwrap(ObjectMemoryStubProtocol.requestedURLs.first)
            XCTAssertEqual(url.path, "/cartridges/object_memory/session/\(action.rawValue)")
            XCTAssertEqual(ObjectMemoryStubProtocol.requestedRequests.first?.httpMethod, "POST")
        }
    }

    /// **A second start is 200 with `changed: false`, and that is not an
    /// error.** It reaches the caller as `.honoured`, not as a refusal, and
    /// nothing downstream may draw it under an error glyph.
    func testASecondStartIsHonouredAndNotAnError() async throws {
        respond(200, ObjectMemoryFixtures.sessionAction(changed: false))
        let outcome = try await makeClient().apply(.start)

        guard case .honoured(let snapshot) = outcome else {
            return XCTFail("an idempotent start decoded as a refusal: \(outcome)")
        }
        XCTAssertEqual(snapshot.wasAnIdempotentNoOp, true)
        XCTAssertEqual(snapshot.state, .active)
    }

    /// **Stop is never refused from any state**, and a Stop from `stopped`
    /// arrives the same way a second start does.
    func testStopFromStoppedIsHonouredAndUnmoved() async throws {
        respond(
            200,
            ObjectMemoryFixtures.sessionAction(
                state: "stopped", changed: false, sessionID: NSNull(), startedAt: NSNull()
            )
        )
        let outcome = try await makeClient().apply(.stop)
        guard case .honoured(let snapshot) = outcome else {
            return XCTFail("stop was refused, which this surface never does: \(outcome)")
        }
        XCTAssertEqual(snapshot.wasAnIdempotentNoOp, true)
    }

    /// **A 409 is an outcome, not a throw.** "Resume continues a paused
    /// session; this one is stopped" is a true and actionable sentence, and
    /// pushing it through the same channel as an unreachable Tower would put it
    /// under the wrong glyph.
    ///
    /// Runs over **both** words, because the contract document says
    /// `not-active` and the running Tower says `not-paused`.
    func testAResumeFromStoppedIsARefusalUnderEitherWord() async throws {
        for reason in CartridgeSessionRefusalReason.interchangeableStateRefusals {
            respond(409, ObjectMemoryFixtures.sessionRefusal(reason: reason.rawValue))
            let outcome = try await makeClient().apply(.resume)

            guard case .refused(let refusal) = outcome else {
                return XCTFail("a 409 did not arrive as a refusal: \(outcome)")
            }
            XCTAssertEqual(refusal.reason, reason)
            XCTAssertEqual(refusal.snapshot.state, .stopped)
            // The sentence is written from the action and the reached state, so
            // it must not vary with which of the two words arrived.
            XCTAssertEqual(
                ObjectMemoryCopy.refusalLine(refusal),
                ObjectMemoryCopy.refusalLine(
                    CartridgeSessionRefusal(
                        action: .resume,
                        reason: .notActive,
                        message: refusal.message,
                        snapshot: refusal.snapshot
                    )
                ),
                "the wire and the document disagree about this word; the copy must not"
            )
        }
    }

    /// A 404 is a **configuration** answer — this Tower has no controllable
    /// session — and is never the answer to "may I start", which is a 409.
    func testAFourOhFourIsAConfigurationAnswerAndNotARefusal() async {
        respond(404, ["detail": "this Tower has no controllable session for 'object_memory'"])
        do {
            _ = try await makeClient().read()
            XCTFail("a 404 decoded as a reading")
        } catch let error as CartridgeSessionFetchError {
            XCTAssertEqual(error, .noSuchCartridgeSession)
        } catch {
            XCTFail("expected a CartridgeSessionFetchError, got \(error)")
        }
    }

    /// A status this surface does not define must not become a transport
    /// failure: the Tower was reached, and telling somebody to check a network
    /// about a machine that answered is the failure this build removed.
    func testAnUndefinedStatusIsNotReportedAsAnUnreachableTower() async {
        respond(500, ["detail": "boom"])
        do {
            _ = try await makeClient().read()
            XCTFail("a 500 decoded as a reading")
        } catch let error as CartridgeSessionFetchError {
            XCTAssertEqual(error, .undecodable)
            if case .transport = error {
                XCTFail("a Tower that answered was reported as unreachable")
            }
        } catch {
            XCTFail("expected a CartridgeSessionFetchError, got \(error)")
        }
    }

    /// Nothing here may be answered out of a URL cache: a session state read
    /// from a stale copy is a claim about a running producer.
    func testSessionRequestsRefuseCachedAnswers() async throws {
        respond(200, ObjectMemoryFixtures.session())
        _ = try await makeClient().read()
        let request = try XCTUnwrap(ObjectMemoryStubProtocol.requestedRequests.first)
        XCTAssertEqual(request.cachePolicy, .reloadIgnoringLocalAndRemoteCacheData)
        XCTAssertEqual(request.timeoutInterval, 10)
    }
}

// MARK: - The client's session state

@MainActor
final class ObjectMemorySessionClientTests: XCTestCase {

    private func makeClient() -> TowerObjectMemoryClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ObjectMemoryStubProtocol.self]
        let session = URLSession(configuration: configuration)
        return TowerObjectMemoryClient(
            http: ObjectMemoryHTTPClient(
                baseURL: URL(string: "http://tower.test")!, session: session
            ),
            control: CartridgeSessionHTTPClient(
                baseURL: URL(string: "http://tower.test")!, session: session
            ),
            pictures: ObjectMemoryImageryHTTPClient(
                baseURL: URL(string: "http://tower.test")!, session: session
            )
        )
    }

    private func respond(_ status: Int, _ json: Any) {
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
        ObjectMemoryStubProtocol.requestedRequests = []
    }

    override func tearDown() {
        ObjectMemoryStubProtocol.handler = nil
        ObjectMemoryStubProtocol.requestedURLs = []
        ObjectMemoryStubProtocol.requestedRequests = []
        super.tearDown()
    }

    /// Nothing is claimed about a session until one has been read. **Not
    /// `stopped`** — a Tower that has not been asked has not said it is
    /// stopped, and a Stopped badge drawn from silence is the same error as a
    /// recording badge drawn from `state`.
    func testAFreshClientClaimsNothingAboutTheSession() {
        let client = makeClient()
        XCTAssertEqual(client.session, .unread)
        XCTAssertNil(client.session.isFollowingACapture)
    }

    /// **An action is followed by a read**, because a `POST` answers with
    /// intent and only a read reports `following`. A Stop that did not stop is
    /// exactly the case that a trusted `POST` body would hide.
    func testAnActionIsFollowedByAReadRatherThanTrusted() async throws {
        var responses: [(Int, Any)] = [
            // The POST: paused, honoured, changed.
            (200, ObjectMemoryFixtures.sessionAction(state: "paused")),
            // The read-back: still following. The producer ignored SIGTERM.
            (
                200,
                ObjectMemoryFixtures.session(
                    state: "paused",
                    sessionID: "61a78a9b32284cd2a89583d9a8cc8702",
                    following: ["22e9d4289cb440fb"]
                )
            ),
        ]
        ObjectMemoryStubProtocol.handler = { request in
            let (status, json) = responses.isEmpty ? (200, [:] as Any) : responses.removeFirst()
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil
            )!
            return (response, try JSONSerialization.data(withJSONObject: json))
        }

        let client = makeClient()
        await client.apply(.pause)

        XCTAssertEqual(
            ObjectMemoryStubProtocol.requestedRequests.count, 2,
            "the POST alone is intent; the read-back is what reports liveness"
        )
        XCTAssertEqual(
            client.session.isFollowingACapture, true,
            "the read-back must win over the POST's claim that the pause took effect"
        )
        XCTAssertTrue(client.session.snapshot?.intentContradictsLiveness == true)
    }

    /// A 409 is a state, not a failure, and its explanation **survives the
    /// read-back** — otherwise the sentence that says which control would have
    /// worked flashes and vanishes behind the refresh.
    func testARefusalSurvivesTheReadBackThatFollowsIt() async {
        // What the real Tower does: 409 to the POST, 200 to the GET after it.
        var responses: [(Int, Any)] = [
            (409, ObjectMemoryFixtures.sessionRefusal(reason: "not-paused")),
            (200, ObjectMemoryFixtures.session(state: "stopped")),
        ]
        ObjectMemoryStubProtocol.handler = { request in
            let (status, json) = responses.isEmpty ? (200, [:] as Any) : responses.removeFirst()
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil
            )!
            return (response, try JSONSerialization.data(withJSONObject: json))
        }

        let client = makeClient()
        await client.apply(.resume)

        guard case .refused(let refusal) = client.session else {
            return XCTFail("a refusal became something else: \(client.session)")
        }
        XCTAssertEqual(refusal.action, .resume)
        XCTAssertEqual(refusal.reason, .notPaused)
        XCTAssertEqual(client.session.snapshot?.state, .stopped)
        XCTAssertEqual(client.session.isFollowingACapture, false)
    }

    /// **A 409 on a read is not an unreachable Tower.**
    ///
    /// Nothing was asked for on a `GET`, so nothing can have been refused — but
    /// the refusal that a `POST` legitimately produces travels as its own error
    /// type, and letting it escape a read would wrap it as `.transport` and
    /// report a Tower that answered as one that could not be reached. That is
    /// the same defect class this change removed from the imagery path, and it
    /// was found here by a test rather than by a wearer.
    func testARefusalOnAReadIsNotReportedAsAnUnreachableTower() async {
        respond(409, ObjectMemoryFixtures.sessionRefusal(reason: "not-paused"))
        let client = makeClient()
        await client.readSession()

        guard case .failed(let failure) = client.session else {
            return XCTFail("a 409 on a read became something else: \(client.session)")
        }
        XCTAssertEqual(failure.kind, .undecodableResponse)
        XCTAssertNotEqual(
            failure.kind, .transport,
            "the Tower answered; calling that unreachable is a false claim about it"
        )
    }

    /// A Tower with no controllable session is a configuration state, not an
    /// error: it can still be asked what it already recorded.
    func testNoControllableSessionIsItsOwnState() async {
        respond(404, ["detail": "this Tower has no controllable session for 'object_memory'"])
        let client = makeClient()
        await client.readSession()
        XCTAssertEqual(client.session, .noSessionControl)
    }
}

// MARK: - Imagery

/// The three imagery routes, and the four things that can come back.
///
/// **The 410 is the one to watch.** It means the pointer is intact and the
/// picture is gone, `memory_retained: true` is in the body, and it must never
/// render as a broken image, an empty row, or a connection error. Before this
/// build it rendered as the third of those.
final class ObjectMemoryImageryDecodingTests: XCTestCase {

    private let baseURL = URL(string: "http://tower.test")!

    private func routes() throws -> ObjectMemoryImageryRoutes {
        try XCTUnwrap(
            ObjectMemoryImageryDecoder.routes(from: ObjectMemoryFixtures.imageryRoutes())
        )
    }

    /// The envelope's `imagery` block was **dropped on decode** until this
    /// build, which is why a wearer saw a capture id and never a frame.
    func testTheEnvelopeCarriesTheImageryRoutes() throws {
        let listing = try ObjectMemoryDecoder.listing(from: ObjectMemoryFixtures.listing())
        let imagery = try XCTUnwrap(
            listing.envelope.imagery, "the imagery block must survive the decode"
        )
        XCTAssertEqual(imagery.contract, "object_memory.imagery/2026-08-27")
        XCTAssertEqual(
            imagery.frameTemplate, "/object-memory/observations/{observation_id}/frame"
        )
    }

    /// A Tower that predates the imagery routes sends no block. That is a
    /// missing feature, not a broken payload, and taking the whole listing off
    /// screen over it would show a wearer nothing to protect them from a
    /// missing thumbnail.
    func testAnEnvelopeWithoutAnImageryBlockStillDecodes() throws {
        var payload = ObjectMemoryFixtures.listing()
        payload.removeValue(forKey: "imagery")
        let listing = try ObjectMemoryDecoder.listing(from: payload)
        XCTAssertNil(listing.envelope.imagery)
        XCTAssertEqual(listing.observations.count, 1)
    }

    /// A changed `filter_means` would mean the filter no longer runs on read
    /// and the stored frame is no longer unchanged — which is what every
    /// sentence this app writes about the filter is licensed by.
    func testAChangedFilterMeaningIsRefused() {
        XCTAssertNil(
            ObjectMemoryImageryDecoder.routes(
                from: ObjectMemoryFixtures.imageryRoutes(filterMeans: "applied-before-storage")
            )
        )
    }

    /// A template that lost its placeholder would resolve to one shared URL,
    /// and every row would show the same picture — a photograph attributed to
    /// the wrong record. Refusing is the only safe direction.
    func testATemplateWithoutItsPlaceholderIsRefusedRatherThanShared() throws {
        let broken = try XCTUnwrap(
            ObjectMemoryImageryDecoder.routes(
                from: ObjectMemoryFixtures.imageryRoutes(
                    frame: "/object-memory/observations/frame"
                )
            )
        )
        XCTAssertNil(broken.path(for: .frame, observationID: "9f2c41b7ad0e6538"))
        XCTAssertNotNil(broken.path(for: .crop, observationID: "9f2c41b7ad0e6538"))
    }

    func testAHandleIsSubstitutedIntoTheTemplate() throws {
        let url = try XCTUnwrap(
            routes().url(
                for: .crop, observationID: "9f2c41b7ad0e6538", relativeTo: baseURL
            )
        )
        XCTAssertEqual(
            url.absoluteString,
            "http://tower.test/object-memory/observations/9f2c41b7ad0e6538/crop"
        )
    }

    /// A served picture.
    func testAServedPictureDescribesItselfAndTheFilterThatRan() throws {
        let description = try XCTUnwrap(
            ObjectMemoryImageryDecoder.description(
                from: ObjectMemoryFixtures.imagery(), statusCode: 200
            )
        )
        XCTAssertEqual(description.situation, .aPicture)
        XCTAssertTrue(description.available)
        XCTAssertNil(description.reason)
        XCTAssertEqual(description.filter, "display-filter/yunet-2023mar@0.30")
        XCTAssertEqual(
            description.filterMeans, "applied-on-read-the-stored-frame-is-unchanged"
        )
        XCTAssertFalse(description.subjectIsBehindAFill)
        XCTAssertEqual(description.preferredKind, .crop)
    }

    /// **The 410**, decoded out of FastAPI's `detail` wrapper.
    func testTheMemoryIsKeptAndThePictureIsGone() throws {
        let description = try XCTUnwrap(
            ObjectMemoryImageryDecoder.descriptionUnwrapping(
                ObjectMemoryFixtures.imageryGone(), statusCode: 410
            )
        )
        XCTAssertEqual(description.situation, .thePictureIsGone)
        XCTAssertFalse(description.available)
        XCTAssertTrue(
            description.memoryRetained,
            "the record is still here; only the picture is gone"
        )
        XCTAssertEqual(description.reason, .imageryNoLongerAvailable)
        XCTAssertEqual(description.statusCode, 410)
    }

    /// The three 503 reasons are a claim about the **Tower**, not about the
    /// record, and are grouped so the copy cannot tell somebody their memory
    /// lost a picture when in fact no weights are installed.
    func testTheFiveOhThreeFamilyIsAboutTheTowerAndNotTheRecord() throws {
        for reason in ObjectMemoryImageryReason.towerCannotServeAny {
            let description = try XCTUnwrap(
                ObjectMemoryImageryDecoder.descriptionUnwrapping(
                    ObjectMemoryFixtures.imageryRefused(reason: reason.rawValue),
                    statusCode: 503
                )
            )
            XCTAssertEqual(description.situation, .theTowerServesNoPictures(reason))
            XCTAssertTrue(
                description.memoryRetained, "a Tower that cannot serve has not lost a record"
            )
        }
    }

    /// The two 404 reasons stay apart: "nothing under this handle" and "this
    /// record never had a pointer" are different facts.
    func testTheTwoFourOhFourReasonsStayApart() throws {
        let unknown = try XCTUnwrap(
            ObjectMemoryImageryDecoder.descriptionUnwrapping(
                ["detail": ObjectMemoryFixtures.imagery(
                    objectClass: NSNull(),
                    available: false,
                    reason: "no-such-observation",
                    memoryRetained: false,
                    filter: NSNull()
                )],
                statusCode: 404
            )
        )
        XCTAssertEqual(unknown.situation, .noSuchRecord)
        XCTAssertFalse(unknown.memoryRetained)

        let noPointer = try XCTUnwrap(
            ObjectMemoryImageryDecoder.descriptionUnwrapping(
                ["detail": ObjectMemoryFixtures.imagery(
                    available: false,
                    reason: "record-has-no-frame-reference",
                    memoryRetained: true,
                    filter: NSNull()
                )],
                statusCode: 404
            )
        )
        XCTAssertEqual(noPointer.situation, .theRecordNeverPointedAtAFrame)
        XCTAssertTrue(noPointer.memoryRetained)
    }

    /// A reason this build does not implement arrives as itself rather than
    /// failing the parse — which is what would send it back down the
    /// connection-failure path this build removed.
    func testAnUnrecognisedReasonSurvivesRatherThanFailingTheParse() throws {
        let description = try XCTUnwrap(
            ObjectMemoryImageryDecoder.descriptionUnwrapping(
                ObjectMemoryFixtures.imageryRefused(reason: "weather"), statusCode: 503
            )
        )
        guard case .anUnrecognisedRefusal(let reason) = description.situation else {
            return XCTFail("an unknown reason was folded into a known one: \(description.situation)")
        }
        XCTAssertEqual(reason.rawValue, "weather")
    }

    /// **`regions_filled: 0` means nothing was detected**, not that there was
    /// nothing there, and the sentence has to carry that on its own.
    func testZeroFilledRegionsIsNotAnAllClear() throws {
        let description = try XCTUnwrap(
            ObjectMemoryImageryDecoder.description(
                from: ObjectMemoryFixtures.imagery(regionsFilled: 0), statusCode: 200
            )
        )
        let line = ObjectMemoryCopy.regionsFilledLine(description).lowercased()
        XCTAssertTrue(
            line.contains("detected nothing"),
            "zero must be said as \"detected nothing\": \(line)"
        )
        XCTAssertFalse(line.contains("no faces were present"))
    }

    /// **`subject_obscured > 0` falls back to the whole frame**, because the
    /// crop is the picture the fill is sitting on. The filter is not weakened
    /// to get a nicer thumbnail — a face-detection threshold is not a
    /// picture-quality knob.
    func testAnObscuredSubjectFallsBackToTheWholeFrame() throws {
        let description = try XCTUnwrap(
            ObjectMemoryImageryDecoder.description(
                from: ObjectMemoryFixtures.imagery(regionsFilled: 2, subjectObscured: 0.1266),
                statusCode: 200
            )
        )
        XCTAssertTrue(description.subjectIsBehindAFill)
        XCTAssertEqual(description.preferredKind, .frame)
        XCTAssertNotNil(
            ObjectMemoryCopy.subjectObscuredLine(description, kind: .frame),
            "the fill has to be said as well as worked around"
        )
        XCTAssertNil(
            ObjectMemoryCopy.subjectObscuredLine(
                try XCTUnwrap(
                    ObjectMemoryImageryDecoder.description(
                        from: ObjectMemoryFixtures.imagery(), statusCode: 200
                    )
                ),
                kind: .crop
            ),
            "nothing overlapping means nothing to say"
        )
    }

    /// A malformed box is refused rather than half-drawn over a photograph.
    func testAMalformedBoxIsRefused() {
        XCTAssertNil(
            ObjectMemoryImageryDecoder.description(
                from: ObjectMemoryFixtures.imagery(box: [0.1, 0.2]), statusCode: 200
            )
        )
    }
}

// MARK: - Imagery transport

@MainActor
final class ObjectMemoryImageryTransportTests: XCTestCase {

    private let baseURL = URL(string: "http://tower.test")!

    private func makeClient() -> ObjectMemoryImageryHTTPClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ObjectMemoryStubProtocol.self]
        return ObjectMemoryImageryHTTPClient(
            baseURL: baseURL, session: URLSession(configuration: configuration)
        )
    }

    private func routes() throws -> ObjectMemoryImageryRoutes {
        try XCTUnwrap(
            ObjectMemoryImageryDecoder.routes(from: ObjectMemoryFixtures.imageryRoutes())
        )
    }

    private func respond(_ status: Int, json: Any) {
        ObjectMemoryStubProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil
            )!
            return (response, try JSONSerialization.data(withJSONObject: json))
        }
    }

    private func respond(_ status: Int, bytes: Data) {
        ObjectMemoryStubProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: status,
                httpVersion: nil,
                // The header the Tower actually sends, so a test that ever
                // starts asserting on it has it to assert on.
                headerFields: ["Cache-Control": "no-store", "Content-Type": "image/jpeg"]
            )!
            return (response, bytes)
        }
    }

    override func setUp() {
        super.setUp()
        ObjectMemoryStubProtocol.handler = nil
        ObjectMemoryStubProtocol.requestedURLs = []
        ObjectMemoryStubProtocol.requestedRequests = []
    }

    override func tearDown() {
        ObjectMemoryStubProtocol.handler = nil
        ObjectMemoryStubProtocol.requestedURLs = []
        ObjectMemoryStubProtocol.requestedRequests = []
        super.tearDown()
    }

    func testAServedPictureComesBackAsBytes() async throws {
        let jpeg = Data([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10])
        respond(200, bytes: jpeg)
        let answer = await makeClient().picture(
            for: "9f2c41b7ad0e6538", kind: .crop, routes: try routes()
        )
        XCTAssertEqual(answer, .picture(jpeg))
    }

    /// **The defect this file exists to prove is gone.**
    ///
    /// A 410 used to become `.transport("The Tower answered 410.")`, which the
    /// workspace maps to `.disconnected` — so a wearer was told their Tower was
    /// unreachable when it had answered clearly that capture-side retention had
    /// taken the picture and kept the memory. Worse than a broken image,
    /// because it sends someone to check a network cable.
    func testAGoneImageIsARenderedSentenceAndNotAConnectionFailure() async throws {
        respond(410, json: ObjectMemoryFixtures.imageryGone())
        let answer = await makeClient().picture(
            for: "9f2c41b7ad0e6538", kind: .crop, routes: try routes()
        )

        guard case .refused(let description) = answer else {
            return XCTFail("a 410 did not arrive as a described refusal: \(answer)")
        }
        if case .unreachable = answer { XCTFail("a 410 was reported as an unreachable Tower") }
        XCTAssertEqual(description.situation, .thePictureIsGone)
        XCTAssertTrue(description.memoryRetained)

        // And the sentence a person reads says both halves.
        let headline = ObjectMemoryCopy.noPictureHeadline(description).lowercased()
        XCTAssertTrue(headline.contains("memory is kept"), headline)
        XCTAssertTrue(headline.contains("picture is gone"), headline)
    }

    /// A 503 is a refusal to serve, described. **This app does not work around
    /// it**, because the lenient default here is a raw first-person frame.
    func testAFilterlessTowerRefusesAndThisAppDoesNotRetry() async throws {
        respond(503, json: ObjectMemoryFixtures.imageryRefused(reason: "display-filter-unavailable"))
        let answer = await makeClient().picture(
            for: "9f2c41b7ad0e6538", kind: .frame, routes: try routes()
        )

        guard case .refused(let description) = answer else {
            return XCTFail("a 503 did not arrive as a described refusal: \(answer)")
        }
        XCTAssertEqual(
            description.situation, .theTowerServesNoPictures(.displayFilterUnavailable)
        )
        XCTAssertEqual(
            ObjectMemoryStubProtocol.requestedRequests.count, 1,
            "a 503 must not be retried into a second request for the same bytes"
        )
    }

    /// `/imagery` answers **200 even when there is no picture**; only an
    /// unknown handle is a real 404 there.
    func testTheDescriptionRouteAnswersEvenWhenThereIsNoPicture() async throws {
        respond(
            200,
            json: ObjectMemoryFixtures.imagery(
                available: false,
                reason: "record-has-no-frame-reference",
                memoryRetained: true,
                filter: NSNull()
            )
        )
        let answer = await makeClient().description(
            for: "9f2c41b7ad0e6538", routes: try routes()
        )
        guard case .described(let description) = answer else {
            return XCTFail("a 200 with no picture did not arrive as a description: \(answer)")
        }
        XCTAssertFalse(description.available)
        XCTAssertEqual(description.statusCode, 200)
    }

    /// **The bytes are never answered out of a cache.** Both binary routes send
    /// `Cache-Control: no-store`, and a copy anybody holds is a second store
    /// nobody chose and nobody's retention governs.
    func testPictureRequestsRefuseEveryCache() async throws {
        respond(200, bytes: Data([0xFF, 0xD8]))
        _ = await makeClient().picture(
            for: "9f2c41b7ad0e6538", kind: .crop, routes: try routes()
        )
        let request = try XCTUnwrap(ObjectMemoryStubProtocol.requestedRequests.first)
        XCTAssertEqual(request.cachePolicy, .reloadIgnoringLocalAndRemoteCacheData)
    }

    /// And when no session is injected, the one this client builds for itself
    /// has no URL cache at all — so honouring `no-store` does not depend on
    /// which session a caller happened to pass in.
    func testTheDefaultImagerySessionKeepsNoCache() {
        let session = ObjectMemoryImageryHTTPClient.uncachedSession()
        XCTAssertNil(session.configuration.urlCache)
        XCTAssertEqual(
            session.configuration.requestCachePolicy, .reloadIgnoringLocalAndRemoteCacheData
        )
    }

    /// A 200 with an empty body is not a picture. Handing `UIImage` bytes it
    /// will silently fail on leaves a blank rectangle, which on this screen
    /// reads as "there was nothing there".
    func testEmptyBytesAreRefusedRatherThanDrawnAsABlank() async throws {
        respond(200, bytes: Data())
        let answer = await makeClient().picture(
            for: "9f2c41b7ad0e6538", kind: .crop, routes: try routes()
        )
        XCTAssertEqual(answer, .undecodable)
    }

    /// The `view` route is JSON and has no bytes to hand back; asking it for a
    /// picture is a programming error and is refused rather than fetched.
    func testTheDescriptionRouteIsNeverFetchedAsAPicture() async throws {
        let answer = await makeClient().picture(
            for: "9f2c41b7ad0e6538", kind: .view, routes: try routes()
        )
        XCTAssertEqual(answer, .routesUnknown)
        XCTAssertTrue(ObjectMemoryStubProtocol.requestedRequests.isEmpty)
    }
}

// MARK: - The picture loader

@MainActor
final class ObjectMemoryPictureLoaderTests: XCTestCase {

    private func description(
        available: Bool = true, reason: Any = NSNull(), subjectObscured: Any = 0.0
    ) throws -> ObjectMemoryImageryDescription {
        try XCTUnwrap(
            ObjectMemoryImageryDecoder.description(
                from: ObjectMemoryFixtures.imagery(
                    available: available, reason: reason, subjectObscured: subjectObscured
                ),
                statusCode: available ? 200 : 410
            )
        )
    }

    private func settle() async throws {
        try await Task.sleep(nanoseconds: 50_000_000)
    }

    /// The description is fetched **before** the bytes, which is what lets a
    /// 410 be a sentence rather than a failed image load.
    func testTheDescriptionIsFetchedBeforeAnyBytes() async throws {
        let client = StubObjectMemoryClient()
        client.stubbedImagery = .described(try description())
        client.stubbedPicture = .picture(Data([0xFF, 0xD8]))

        let loader = ObjectMemoryPictureLoader(client: client, observationID: "9f2c41b7ad0e6538")
        loader.load()
        try await settle()

        XCTAssertEqual(client.imageryAsked, ["9f2c41b7ad0e6538"])
        XCTAssertEqual(client.picturesAsked.count, 1)
        guard case .picture = loader.phase else {
            return XCTFail("a served picture did not arrive: \(loader.phase)")
        }
    }

    /// **A 410 becomes a rendered sentence, never a failure.**
    func testAGoneImageDoesNotReachTheFailedPhase() async throws {
        let client = StubObjectMemoryClient()
        client.stubbedImagery = .described(
            try description(available: false, reason: "imagery-no-longer-available")
        )

        let loader = ObjectMemoryPictureLoader(client: client, observationID: "9f2c41b7ad0e6538")
        loader.load()
        try await settle()

        guard case .noPicture(let description) = loader.phase else {
            return XCTFail("a 410 reached the wrong phase: \(loader.phase)")
        }
        XCTAssertEqual(description.situation, .thePictureIsGone)
        XCTAssertTrue(
            client.picturesAsked.isEmpty,
            "there is no reason to ask for bytes the Tower already said are gone"
        )
    }

    /// The 503 family too: nothing is fetched, and nothing renders as an error.
    func testAFilterlessTowerNeverReachesTheBytes() async throws {
        let client = StubObjectMemoryClient()
        client.stubbedImagery = .described(
            try description(available: false, reason: "display-filter-unavailable")
        )

        let loader = ObjectMemoryPictureLoader(client: client, observationID: "9f2c41b7ad0e6538")
        loader.load()
        try await settle()

        guard case .noPicture = loader.phase else {
            return XCTFail("a 503 reached the wrong phase: \(loader.phase)")
        }
        XCTAssertTrue(client.picturesAsked.isEmpty)
    }

    /// An obscured subject fetches the **whole frame** rather than the crop the
    /// fill is sitting on.
    func testAnObscuredSubjectFetchesTheFrameInsteadOfTheCrop() async throws {
        let client = StubObjectMemoryClient()
        client.stubbedImagery = .described(try description(subjectObscured: 0.42))
        client.stubbedPicture = .picture(Data([0xFF, 0xD8]))

        let loader = ObjectMemoryPictureLoader(client: client, observationID: "9f2c41b7ad0e6538")
        loader.load()
        try await settle()

        XCTAssertEqual(client.picturesAsked.first?.1, .frame)
        XCTAssertEqual(loader.kind, .frame)
    }

    /// The race: the description said available and the bytes came back gone,
    /// because capture-side retention closed between the two requests. It ends
    /// in the same sentence rather than a broken image.
    func testARetentionRaceEndsInTheSameSentence() async throws {
        let client = StubObjectMemoryClient()
        client.stubbedImagery = .described(try description())
        client.stubbedPicture = .refused(
            try description(available: false, reason: "imagery-no-longer-available")
        )

        let loader = ObjectMemoryPictureLoader(client: client, observationID: "9f2c41b7ad0e6538")
        loader.load()
        try await settle()

        guard case .noPicture(let description) = loader.phase else {
            return XCTFail("a mid-flight expiry reached the wrong phase: \(loader.phase)")
        }
        XCTAssertEqual(description.situation, .thePictureIsGone)
    }

    /// **Nothing is kept.** `forget()` drops the bytes rather than waiting for
    /// deallocation, because a row leaving the screen is exactly when this app
    /// should stop holding a photograph of somebody's home.
    func testForgettingDropsTheBytes() async throws {
        let client = StubObjectMemoryClient()
        client.stubbedImagery = .described(try description())
        client.stubbedPicture = .picture(Data([0xFF, 0xD8]))

        let loader = ObjectMemoryPictureLoader(client: client, observationID: "9f2c41b7ad0e6538")
        loader.load()
        try await settle()
        guard case .picture = loader.phase else { return XCTFail("no picture to forget") }

        loader.forget()
        XCTAssertEqual(loader.phase, .unasked, "the bytes must not survive the row")
    }

    /// A Tower with no imagery block offers no pictures, and that is a fact
    /// about the Tower rather than a failure.
    func testATowerThatOffersNoPicturesSaysSoRatherThanFailing() async throws {
        let client = StubObjectMemoryClient()
        client.stubbedImagery = .routesUnknown

        let loader = ObjectMemoryPictureLoader(client: client, observationID: "9f2c41b7ad0e6538")
        loader.load()
        try await settle()
        XCTAssertEqual(loader.phase, .noPicturesOffered)
    }
}

// MARK: - Copy for the session and the pictures

/// The same forbidden-phrase discipline `ObjectMemoryCopyTests` applies to
/// records, applied to the two surfaces added on 2026-08-27.
///
/// The picture half matters most. **A picture is a much stronger location cue
/// than a sentence, and no string test can catch it** — every rule the record
/// copy enforces can be undone by a photograph of a desk with a weak line under
/// it. What a test *can* do is hold the line that the caption exists, says what
/// the picture is and is not, and never uses the words this cartridge is
/// forbidden to use about its filter.
@MainActor
final class ObjectMemorySessionAndPictureCopyTests: XCTestCase {

    private let classes = ["laptop", "cell phone"]

    /// The same list `ObjectMemoryCopyTests` uses, kept in one place by being
    /// re-derived rather than by being shared: these two suites test different
    /// surfaces and a change to one list should be a deliberate change to both.
    private func forbiddenPhrases() -> [String] {
        var phrases = [
            "still there", "is still", "right now", "at the moment", "on the map",
            "last known location", "location of", "we know where", "you left",
            "where you left", "go and get", "does not exist", "there is no ",
            "you have no ", "you do not have", "found your", "no results",
            "last seen in session", "seen in session",
        ]
        for objectClass in classes {
            phrases.append(contentsOf: [
                "your \(objectClass)", "my \(objectClass)", "the \(objectClass) is",
                "\(objectClass) is in", "\(objectClass) is at", "\(objectClass) is on",
                "\(objectClass) is still", "\(objectClass) exists",
            ])
        }
        return phrases
    }

    /// **The words this cartridge may never use about its display filter.**
    ///
    /// The Tower's own privacy transformation runs before persistence, at the
    /// one choke point every persisted pixel passes, and earns those names.
    /// This one runs on **read**: the raw frame stays exactly where it was and
    /// the capture manifests record `redaction: "none"`. Calling it the other
    /// thing would tell a wearer their recordings are altered when they are
    /// not.
    private let forbiddenFilterWords = [
        "redact", "anonymis", "anonymiz", "privacy-safe", "privacy safe",
        "de-identif", "deidentif", "scrubbed", "sanitis", "sanitiz",
    ]

    private func assertNoOverclaim(
        _ strings: [String], file: StaticString = #filePath, line: UInt = #line
    ) {
        for string in strings {
            let lowered = string.lowercased()
            XCTAssertFalse(lowered.isEmpty, "an empty string reached the screen", file: file, line: line)
            for phrase in forbiddenPhrases() {
                XCTAssertFalse(
                    lowered.contains(phrase),
                    "copy claims more than the sensor supports (\"\(phrase)\") in: \(string)",
                    file: file, line: line
                )
            }
            for word in forbiddenFilterWords {
                XCTAssertFalse(
                    lowered.contains(word),
                    "the display filter must never be called \"\(word)\" in: \(string)",
                    file: file, line: line
                )
            }
        }
    }

    private func snapshot(
        state: String = "active", following: [String] = []
    ) throws -> CartridgeSessionSnapshot {
        try XCTUnwrap(
            CartridgeSessionDecoder.snapshot(
                from: ObjectMemoryFixtures.session(
                    state: state,
                    sessionID: "61a78a9b32284cd2a89583d9a8cc8702",
                    startedAt: 1787833925.6521091,
                    following: following,
                    captures: following
                )
            )
        )
    }

    private func description(
        available: Bool = true, reason: Any = NSNull(), subjectObscured: Any = 0.0,
        regionsFilled: Any = 0
    ) throws -> ObjectMemoryImageryDescription {
        try XCTUnwrap(
            ObjectMemoryImageryDecoder.description(
                from: ObjectMemoryFixtures.imagery(
                    available: available,
                    reason: reason,
                    regionsFilled: regionsFilled,
                    subjectObscured: subjectObscured
                ),
                statusCode: 200
            )
        )
    }

    func testEverySessionSentenceMakesNoClaimItCannotSupport() throws {
        for state in ["stopped", "active", "paused", "draining"] {
            for following in [[], ["22e9d4289cb440fb"]] {
                assertNoOverclaim(
                    ObjectMemoryCopy.everyString(
                        for: try snapshot(state: state, following: following)
                    )
                )
            }
        }
    }

    func testEveryRefusalSentenceMakesNoClaimEither() throws {
        let stopped = try snapshot(state: "stopped")
        for action in CartridgeSessionAction.allCases {
            for reason in [
                CartridgeSessionRefusalReason.notActive, .notPaused, .unsupported,
                .unknownAction, CartridgeSessionRefusalReason(rawValue: "weather"),
            ] {
                assertNoOverclaim(
                    ObjectMemoryCopy.everyString(
                        for: CartridgeSessionRefusal(
                            action: action,
                            reason: reason,
                            message: "there is nothing to pause; this cartridge is stopped",
                            snapshot: stopped
                        )
                    )
                )
            }
        }
    }

    func testEveryPictureSentenceMakesNoClaimEither() throws {
        let cases: [(Bool, Any, Any, Any)] = [
            (true, NSNull(), 0.0, 0),
            (true, NSNull(), 0.42, 2),
            (false, "imagery-no-longer-available", 0.0, 0),
            (false, "record-has-no-frame-reference", 0.0, 0),
            (false, "no-such-observation", 0.0, 0),
            (false, "display-filter-unavailable", 0.0, 0),
            (false, "no-capture-root-configured", 0.0, 0),
            (false, "frame-unreadable", 0.0, 0),
            (false, "weather", 0.0, 0),
        ]
        for (available, reason, obscured, filled) in cases {
            let description = try self.description(
                available: available,
                reason: reason,
                subjectObscured: obscured,
                regionsFilled: filled
            )
            for kind in ObjectMemoryImageryKind.allCases {
                assertNoOverclaim(
                    ObjectMemoryCopy.everyString(for: description, kind: kind)
                )
            }
        }
    }

    /// **The caption carries the whole burden**, so it has to say all three
    /// things: what was observed, what the picture is, and what it is not.
    func testTheCaptionSaysWhatThePictureIsAndWhatItIsNot() {
        for kind in ObjectMemoryImageryKind.allCases {
            let caption = ObjectMemoryCopy
                .pictureCaption(objectClass: "laptop", kind: kind).lowercased()
            XCTAssertTrue(caption.contains("a laptop was visible"), caption)
            XCTAssertTrue(caption.contains("recording"), caption)
            XCTAssertTrue(caption.contains("not a place"), caption)
            XCTAssertTrue(caption.contains("anything about now"), caption)
            XCTAssertFalse(caption.contains("your laptop"), caption)
        }
    }

    /// The filter is described by what **ran**, with its blind spots named. A
    /// filter described only by what it catches reads as a guarantee.
    func testTheFilterIsDescribedByWhatRanAndByWhatIsStillInThePicture() throws {
        let line = ObjectMemoryCopy.filterLine(try description()).lowercased()
        XCTAssertTrue(line.contains("display filter"), line)
        XCTAssertTrue(line.contains("display-filter/yunet-2023mar@0.30"), line)
        XCTAssertTrue(line.contains("stored frame is unchanged"), line)
        XCTAssertTrue(
            line.contains("still in the picture"),
            "bodies, clothing, screens and undetected faces are all still there: \(line)"
        )
    }

    /// The 410's two halves have to arrive in the same breath. Either one alone
    /// is misleading.
    func testTheGoneSentenceSaysBothHalves() throws {
        let gone = try XCTUnwrap(
            ObjectMemoryImageryDecoder.descriptionUnwrapping(
                ObjectMemoryFixtures.imageryGone(), statusCode: 410
            )
        )
        let headline = ObjectMemoryCopy.noPictureHeadline(gone).lowercased()
        let explanation = ObjectMemoryCopy.noPictureExplanation(gone).lowercased()
        XCTAssertTrue(headline.contains("memory is kept"), headline)
        XCTAssertTrue(headline.contains("picture is gone"), headline)
        XCTAssertTrue(explanation.contains("untouched"), explanation)
        // Worded as the correct outcome it is, rather than as an error. The
        // sentence contains the word "failed" on purpose — "nothing failed" —
        // so the check is for the phrasings that would make it *read* as a
        // failure, not for the substring.
        XCTAssertTrue(explanation.contains("nothing failed"), explanation)
        for misreading in [
            "something went wrong", "could not be reached", "try again",
            "unavailable", "unreachable", "we were unable",
        ] {
            XCTAssertFalse(
                explanation.contains(misreading),
                "a 410 is capture-side retention working, not a failure: \(explanation)"
            )
        }
    }

    /// A 503 is a claim about the **Tower**, not about the record, and the
    /// sentence must say so — otherwise somebody is told their memory lost a
    /// picture when in fact no weights are installed.
    func testAFilterlessTowerIsDescribedAsTheTowerAndNotAsTheRecord() throws {
        let refused = try XCTUnwrap(
            ObjectMemoryImageryDecoder.descriptionUnwrapping(
                ObjectMemoryFixtures.imageryRefused(reason: "display-filter-unavailable"),
                statusCode: 503
            )
        )
        let explanation = ObjectMemoryCopy.noPictureExplanation(refused).lowercased()
        XCTAssertTrue(explanation.contains("this tower"), explanation)
        XCTAssertTrue(
            explanation.contains("records themselves are unaffected"),
            explanation
        )
        XCTAssertTrue(
            explanation.contains("refuses") || explanation.contains("unfiltered"),
            "the refusal is the correct behaviour and is stated as such: \(explanation)"
        )
    }

    /// The idempotent no-op is worded as success, because it is one.
    func testAnIdempotentNoOpReadsAsSuccessRatherThanAsAnError() {
        for action in CartridgeSessionAction.allCases {
            let line = ObjectMemoryCopy.idempotentNoOpLine(action).lowercased()
            XCTAssertFalse(line.contains("error"), line)
            XCTAssertFalse(line.contains("failed"), line)
            XCTAssertFalse(line.contains("could not"), line)
            XCTAssertTrue(line.contains("nothing needed to change"), line)
        }
    }

    /// The session id is not a capture id and is never shown as one — the same
    /// discipline `frameLine` applies for the same reason.
    func testTheSessionIdentifierIsNeverShownAsARecording() throws {
        let line = ObjectMemoryCopy.sessionProvenanceLine(try snapshot()).lowercased()
        XCTAssertTrue(line.contains("not a recording"), line)
        XCTAssertTrue(line.contains("not a place"), line)
    }

    /// Late attachment is a consent decision, and it is stated where the button
    /// is: a wearer who starts remembering at 15:03 has not asked for the 15:00
    /// part of the walk.
    func testStartSaysItDoesNotReachBackwards() {
        let line = ObjectMemoryCopy.startMeaningLine.lowercased()
        XCTAssertTrue(line.contains("does not reach back"), line)
    }

    /// What this app was told, including what it was **not** told. A screen
    /// that stayed quiet about the unknown detector would let a reader assume
    /// the app knows and is choosing not to say.
    func testTheConfigSummaryNamesOnlyWhatThePayloadCarried() throws {
        let listing = try ObjectMemoryDecoder.listing(from: ObjectMemoryFixtures.listing())
        let summary = ObjectMemoryCopy.whatThisTowerReports(.listing(listing))
        assertNoOverclaim([summary])
        XCTAssertTrue(summary.lowercased().contains("laptop and cell phone"), summary)
        XCTAssertTrue(
            summary.lowercased().contains("does not report which detector"),
            "the app must say it was not told, rather than imply it knows: \(summary)"
        )

        let verified = try ObjectMemoryDecoder.listing(
            from: ObjectMemoryFixtures.listing(observations: [
                ObjectMemoryFixtures.observation(
                    tier: "verify", verification: ObjectMemoryFixtures.verification()
                )
            ])
        )
        let verifiedSummary = ObjectMemoryCopy.whatThisTowerReports(.listing(verified))
        XCTAssertTrue(
            verifiedSummary.contains("google/owlv2-base-patch16-ensemble"),
            "a verifier that ran is named from the payload: \(verifiedSummary)"
        )
    }

    /// A verifier's similarity is not a calibrated probability and is never
    /// presented as one.
    func testAVerificationScoreIsNotPresentedAsAProbability() throws {
        let listing = try ObjectMemoryDecoder.listing(
            from: ObjectMemoryFixtures.listing(observations: [
                ObjectMemoryFixtures.observation(
                    tier: "verify", verification: ObjectMemoryFixtures.verification()
                )
            ])
        )
        let observation = try XCTUnwrap(listing.observations.first)
        let line = try XCTUnwrap(ObjectMemoryCopy.verificationLine(observation))
        assertNoOverclaim([line])
        XCTAssertTrue(line.contains("google/owlv2-base-patch16-ensemble"), line)
        XCTAssertTrue(line.lowercased().contains("not a calibrated probability"), line)
        XCTAssertTrue(
            line.lowercased().contains("94 crops"),
            "the threshold's provenance travels with the number: \(line)"
        )
    }
}

// MARK: - The additive record fields

final class ObjectMemoryAdditiveFieldTests: XCTestCase {

    /// The handle the imagery routes take, off the payload.
    func testARecordCarriesItsImageryHandle() throws {
        let listing = try ObjectMemoryDecoder.listing(from: ObjectMemoryFixtures.listing())
        let observation = try XCTUnwrap(listing.observations.first)
        XCTAssertEqual(observation.observationID, "9f2c41b7ad0e6538")
        XCTAssertEqual(
            observation.id, "9f2c41b7ad0e6538",
            "the row identity and the imagery handle are the same string when there is one"
        )
    }

    /// A record without a handle keeps its composed row identity and simply
    /// gets no picture. Refusing the whole listing over one such record would
    /// take a wearer's memory off screen to protect them from a missing
    /// thumbnail.
    func testARecordWithoutAHandleStillDecodesAndKeepsARowIdentity() throws {
        let listing = try ObjectMemoryDecoder.listing(
            from: ObjectMemoryFixtures.listing(observations: [
                ObjectMemoryFixtures.observation(observationID: NSNull())
            ])
        )
        let observation = try XCTUnwrap(listing.observations.first)
        XCTAssertNil(observation.observationID)
        XCTAssertTrue(observation.id.contains("cell phone"))
    }

    /// `null` stays `nil` and never becomes a number: a `frame_count` of 0
    /// would claim a sighting that spanned no frames.
    func testMissingSightingFieldsStayNilRatherThanBecomingZero() throws {
        let listing = try ObjectMemoryDecoder.listing(
            from: ObjectMemoryFixtures.listing(observations: [
                ObjectMemoryFixtures.observation(
                    lastSeenAt: NSNull(), frameCount: NSNull(), tier: NSNull()
                )
            ])
        )
        let observation = try XCTUnwrap(listing.observations.first)
        XCTAssertNil(observation.lastSeenAt)
        XCTAssertNil(observation.frameCount)
        XCTAssertNil(observation.tier)
        XCTAssertNil(ObjectMemoryCopy.durationLine(observation))
        XCTAssertNil(ObjectMemoryCopy.tierLine(observation))
    }

    /// A verification block that cannot be read reports **nothing was asked**,
    /// which is the weaker and safer of the two things it could say.
    func testAnUnreadableVerificationReportsNothingRatherThanGuessing() throws {
        let listing = try ObjectMemoryDecoder.listing(
            from: ObjectMemoryFixtures.listing(observations: [
                ObjectMemoryFixtures.observation(verification: ["model": "something"])
            ])
        )
        let observation = try XCTUnwrap(listing.observations.first)
        XCTAssertNil(observation.verification)
        XCTAssertNil(ObjectMemoryCopy.verificationLine(observation))
    }
}

// MARK: - The status-code defect

@MainActor
final class ObjectMemoryStatusCodeTests: XCTestCase {

    private func makeClient() -> TowerObjectMemoryClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ObjectMemoryStubProtocol.self]
        return TowerObjectMemoryClient(
            http: ObjectMemoryHTTPClient(
                baseURL: URL(string: "http://tower.test")!,
                session: URLSession(configuration: configuration)
            )
        )
    }

    override func setUp() {
        super.setUp()
        ObjectMemoryStubProtocol.handler = nil
    }

    override func tearDown() {
        ObjectMemoryStubProtocol.handler = nil
        super.tearDown()
    }

    /// **A Tower that answered must never be reported as unreachable.**
    ///
    /// Every non-404 non-2xx used to become `.transport("The Tower answered
    /// N.")`, which `ObjectMemoryState.phase` maps to `.disconnected` — so a
    /// clear answer from a working machine was presented as a connection
    /// failure, sending a person to check a network cable.
    func testAnUnusableStatusIsAFailureAndNotADisconnection() async {
        ObjectMemoryStubProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 410, httpVersion: nil, headerFields: nil
            )!
            return (response, Data("{}".utf8))
        }

        let client = makeClient()
        await client.ask(.listing(objectClass: nil))

        guard case .failed(let failure) = client.state else {
            return XCTFail("an unusable status did not fail: \(client.state)")
        }
        XCTAssertEqual(failure.kind, .towerReportedFailure)
        XCTAssertNotEqual(
            failure.kind, .transport,
            "the Tower answered; calling that a transport failure is a false claim about it"
        )
        XCTAssertEqual(
            client.state.phase, .failed,
            "and it must not reach the screen under the disconnected glyph"
        )
    }

    /// A 404 keeps meaning what it meant: this Tower serves no object memory.
    func testTheConfigurationFourOhFourIsUnaffected() async {
        ObjectMemoryStubProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: request.url!, statusCode: 404, httpVersion: nil, headerFields: nil
            )!
            return (response, Data("{\"detail\":\"no object memory root is configured\"}".utf8))
        }
        let client = makeClient()
        await client.ask(.listing(objectClass: nil))
        XCTAssertEqual(client.state, .noObjectMemory)
    }
}

// MARK: - Session, pinned against a real Tower

/// Session payloads taken **verbatim off the running Tower** on 2026-08-27,
/// rather than from a reading of §9 of its contract.
///
/// This is where the wire/document disagreement was found: §4.1 of
/// `TOWER-UNIFIED-CARTRIDGES.md` records `resume` from `stopped` as
/// `not-active`; the bytes below say `not-paused`. Both are in §10's
/// vocabulary and both are truthful, so neither is a bug — but a client that
/// switched on one of them would be wrong against the other Tower. Hence the
/// copy is written from the action and the state, and both words are pinned
/// here so a change to either is a test failure rather than a surprise.
final class CartridgeSessionRealTowerTests: XCTestCase {

    private func json(_ text: String) throws -> [String: Any] {
        try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any]
        )
    }

    private func snapshot(_ text: String) throws -> CartridgeSessionSnapshot {
        try XCTUnwrap(CartridgeSessionDecoder.snapshot(from: try json(text)))
    }

    func testARealStoppedSessionDecodes() throws {
        let stopped = try snapshot(Self.stoppedFromTower)
        XCTAssertEqual(stopped.contract, "cartridge_session.control/2026-08-27")
        XCTAssertEqual(stopped.state, .stopped)
        XCTAssertEqual(stopped.stateMeans, "intent-not-liveness")
        XCTAssertTrue(stopped.supported)
        XCTAssertNil(stopped.sessionID)
        XCTAssertFalse(stopped.isFollowingACapture)
        XCTAssertEqual(stopped.offeredActions, [.start, .pause, .resume, .stop])
    }

    /// **Start before the camera is running is legal**, and this is what it
    /// looks like: `active`, a session id, and `attached_capture_id: null`.
    func testARealStartBeforeTheCameraIsActiveWithNothingAttached() throws {
        let started = try snapshot(Self.startFromTower)
        XCTAssertEqual(started.state, .active)
        XCTAssertEqual(started.sessionID, "61a78a9b32284cd2a89583d9a8cc8702")
        XCTAssertNil(started.attachedCaptureID)
        XCTAssertEqual(started.changed, true)
        XCTAssertFalse(
            started.isFollowingACapture,
            "an intent to remember is not a producer writing anything"
        )
    }

    /// **A second start is 200 with `changed: false`** — honoured, nothing
    /// moved. The session id does not move either.
    func testARealSecondStartIsHonouredAndUnmoved() throws {
        let first = try snapshot(Self.startFromTower)
        let second = try snapshot(Self.secondStartFromTower)
        XCTAssertEqual(second.changed, false)
        XCTAssertEqual(second.wasAnIdempotentNoOp, true)
        XCTAssertEqual(second.state, .active)
        XCTAssertEqual(second.sessionID, first.sessionID)
    }

    /// **Stop is never refused.** From `stopped` it is 200 with
    /// `changed: false`, and the session id is already cleared.
    func testARealStopFromStoppedIsHonoured() throws {
        let stopped = try snapshot(Self.stopFromStoppedFromTower)
        XCTAssertEqual(stopped.changed, false)
        XCTAssertEqual(stopped.accepted, true)
        XCTAssertNil(stopped.sessionID)
    }

    /// **The disagreement, pinned.** The wire says `not-paused` where the
    /// contract document says `not-active`.
    func testARealResumeFromStoppedIsRefusedWithTheWireWord() throws {
        let body = try XCTUnwrap(
            try json(Self.resumeRefusedFromTower)["detail"] as? [String: Any]
        )
        let refusal = try XCTUnwrap(
            CartridgeSessionDecoder.refusal(from: body, action: .resume)
        )
        XCTAssertEqual(
            refusal.reason, .notPaused,
            """
            the running Tower answers `not-paused` here; §4.1 of the unified \
            contract says `not-active`, and this build must handle both
            """
        )
        XCTAssertTrue(
            CartridgeSessionRefusalReason.interchangeableStateRefusals.contains(refusal.reason)
        )
        XCTAssertEqual(refusal.snapshot.state, .stopped)
        XCTAssertEqual(refusal.snapshot.accepted, false)
    }

    /// And `pause` from `stopped` is the **other** word, on the same Tower, for
    /// the neighbouring situation — which is why neither word can be treated as
    /// the one that means "wrong state".
    func testARealPauseFromStoppedUsesTheOtherWord() throws {
        let body = try XCTUnwrap(
            try json(Self.pauseRefusedFromTower)["detail"] as? [String: Any]
        )
        let refusal = try XCTUnwrap(
            CartridgeSessionDecoder.refusal(from: body, action: .pause)
        )
        XCTAssertEqual(refusal.reason, .notActive)
    }

    func testARealUnknownVerbIsRefusedWithoutChangingAnything() throws {
        let body = try XCTUnwrap(
            try json(Self.unknownActionFromTower)["detail"] as? [String: Any]
        )
        let refusal = try XCTUnwrap(
            CartridgeSessionDecoder.refusal(from: body, action: .start)
        )
        XCTAssertEqual(refusal.reason, .unknownAction)
        XCTAssertEqual(refusal.snapshot.state, .stopped)
    }

    /// The `imagery` block, and the 404 body, taken off the same Tower.
    func testTheRealEnvelopeCarriesTheImageryTemplates() throws {
        let listing = try ObjectMemoryDecoder.listing(from: try json(Self.envelopeFromTower))
        let imagery = try XCTUnwrap(listing.envelope.imagery)
        XCTAssertEqual(imagery.contract, "object_memory.imagery/2026-08-27")
        XCTAssertEqual(
            imagery.viewTemplate, "/object-memory/observations/{observation_id}/imagery"
        )
        XCTAssertEqual(
            imagery.url(
                for: .crop,
                observationID: "9f2c41b7ad0e6538",
                relativeTo: URL(string: "http://127.0.0.1:8765")!
            )?.absoluteString,
            "http://127.0.0.1:8765/object-memory/observations/9f2c41b7ad0e6538/crop"
        )
    }

    /// **Only an unknown handle is a real 404 on `/imagery`**, and this is what
    /// one looks like: `filter` is null because nothing was served, and
    /// `memory_retained` is false because there is no record to retain.
    func testARealUnknownHandleIsTheOneRealFourOhFour() throws {
        let description = try XCTUnwrap(
            ObjectMemoryImageryDecoder.descriptionUnwrapping(
                try json(Self.imageryNotFoundFromTower), statusCode: 404
            )
        )
        XCTAssertEqual(description.situation, .noSuchRecord)
        XCTAssertFalse(description.memoryRetained)
        XCTAssertNil(description.filter)
        XCTAssertNil(description.objectClass)
        XCTAssertEqual(description.regionsFilled, 0)
        XCTAssertEqual(description.subjectObscured, 0.0)
    }

    /// `GET /cartridges/object_memory/session`, verbatim.
    private static let stoppedFromTower = """
        {"cartridge":"object_memory","worker":"object-memory-session","supported":true,"state":"stopped","session_id":null,"started_at":null,"changed_at":1787832967.312166,"following":[],"captures":[],"contract":"cartridge_session.control/2026-08-27","state_means":"intent-not-liveness","states":["stopped","active","paused"],"actions":["start","pause","resume","stop"]}
        """

    /// `POST …/start` from `stopped`, with no camera running.
    private static let startFromTower = """
        {"cartridge":"object_memory","worker":"object-memory-session","supported":true,"state":"active","session_id":"61a78a9b32284cd2a89583d9a8cc8702","started_at":1787833925.6521091,"changed_at":1787833925.6521118,"following":[],"captures":[],"changed":true,"attached_capture_id":null,"accepted":true,"contract":"cartridge_session.control/2026-08-27","state_means":"intent-not-liveness","states":["stopped","active","paused"],"actions":["start","pause","resume","stop"]}
        """

    /// `POST …/start` again. **200, `changed: false`. Not an error.**
    private static let secondStartFromTower = """
        {"cartridge":"object_memory","worker":"object-memory-session","supported":true,"state":"active","session_id":"61a78a9b32284cd2a89583d9a8cc8702","started_at":1787833925.6521091,"changed_at":1787833925.6521118,"following":[],"captures":[],"changed":false,"attached_capture_id":null,"accepted":true,"contract":"cartridge_session.control/2026-08-27","state_means":"intent-not-liveness","states":["stopped","active","paused"],"actions":["start","pause","resume","stop"]}
        """

    /// `POST …/stop` from `stopped`. Never refused.
    private static let stopFromStoppedFromTower = """
        {"cartridge":"object_memory","worker":"object-memory-session","supported":true,"state":"stopped","session_id":null,"started_at":null,"changed_at":1787832967.312166,"following":[],"captures":[],"changed":false,"attached_capture_id":null,"accepted":true,"contract":"cartridge_session.control/2026-08-27","state_means":"intent-not-liveness","states":["stopped","active","paused"],"actions":["start","pause","resume","stop"]}
        """

    /// `POST …/resume` from `stopped`. **409, and the word is `not-paused`.**
    private static let resumeRefusedFromTower = """
        {"detail":{"accepted":false,"reason":"not-paused","message":"there is no paused session to resume; this cartridge is stopped","cartridge":"object_memory","worker":"object-memory-session","supported":true,"state":"stopped","session_id":null,"started_at":null,"changed_at":1787832967.312166,"following":[],"captures":[],"contract":"cartridge_session.control/2026-08-27","state_means":"intent-not-liveness","states":["stopped","active","paused"],"actions":["start","pause","resume","stop"]}}
        """

    /// `POST …/pause` from `stopped`. 409, and the word is `not-active`.
    private static let pauseRefusedFromTower = """
        {"detail":{"accepted":false,"reason":"not-active","message":"there is nothing to pause; this cartridge is stopped","cartridge":"object_memory","worker":"object-memory-session","supported":true,"state":"stopped","session_id":null,"started_at":null,"changed_at":1787832967.312166,"following":[],"captures":[],"contract":"cartridge_session.control/2026-08-27","state_means":"intent-not-liveness","states":["stopped","active","paused"],"actions":["start","pause","resume","stop"]}}
        """

    /// `POST …/wiggle`.
    private static let unknownActionFromTower = """
        {"detail":{"accepted":false,"reason":"unknown-action","message":"'wiggle' is not an action; expected one of start, pause, resume, stop","cartridge":"object_memory","worker":"object-memory-session","supported":true,"state":"stopped","session_id":null,"started_at":null,"changed_at":1787833925.690068,"following":[],"captures":[],"contract":"cartridge_session.control/2026-08-27","state_means":"intent-not-liveness","states":["stopped","active","paused"],"actions":["start","pause","resume","stop"]}}
        """

    /// `GET /object-memory/observations`, verbatim, on a Tower whose store is
    /// empty and whose window was written unbounded — which is why
    /// `effective_days` is null rather than 30.
    private static let envelopeFromTower = """
        {"contract":"object_memory.observations/2026-08-26","claim":"category-was-visible-once","identity":"category-not-instance","absence_means":"not-observed-by-this-cartridge","spatial_ref":null,"recorded_classes":["laptop","cell phone"],"imagery":{"contract":"object_memory.imagery/2026-08-27","claim":"frame-from-the-recording-this-record-was-derived-from","filter_means":"applied-on-read-the-stored-frame-is-unchanged","view":"/object-memory/observations/{observation_id}/imagery","frame":"/object-memory/observations/{observation_id}/frame","crop":"/object-memory/observations/{observation_id}/crop"},"retention":{"requested_days":null,"effective_days":null,"clamped":false,"policy":"min(persisted, requested): a reader may narrow this window and can never widen it"},"object_class":null,"observation_count":0,"observations":[]}
        """

    /// `GET /object-memory/observations/0123456789abcdef/imagery`, verbatim.
    private static let imageryNotFoundFromTower = """
        {"detail":{"contract":"object_memory.imagery/2026-08-27","observation_id":"0123456789abcdef","object_class":null,"claim":"frame-from-the-recording-this-record-was-derived-from","available":false,"reason":"no-such-observation","memory_retained":false,"filter":null,"filter_means":"applied-on-read-the-stored-frame-is-unchanged","regions_filled":0,"subject_obscured":0.0,"bounding_box_normalized":null,"imagery_retention":"capture-side"}}
        """
}
