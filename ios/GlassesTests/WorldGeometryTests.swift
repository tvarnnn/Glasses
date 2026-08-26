import Foundation
import XCTest
import CoreGraphics
import Combine
@testable import Glasses

final class WorldGeometryDecoderTests: XCTestCase {

    private func manifestJSON(upAxis: String = "unknown") -> [String: Any] {
        [
            "contract": "world_builder.geometry/2026-08-25",
            "world_id": "w0", "session_id": "s0",
            "geometry_revision": "abc123",
            "pose_convention": [
                "pose_type": "T_world_camera", "quaternion_order": "wxyz",
                "handedness": "right",
                "camera_axes": "opencv_x_right_y_down_z_forward",
                "translation_units": "world",
                "world_axes_origin": "first_keyframe_camera",
                "up_axis": upAxis, "pose_dtype": "float64",
                "point_dtype": "float32",
            ],
            "scale": ["state": "unknown", "meters_per_unit": NSNull()],
            "segment_count": 2,
            "segments": [
                ["segment_index": 0, "content_hash": "h0", "frame_id": "segment:0",
                 "registered": false, "transform_to_world": NSNull(),
                 "resolution_state": "resolved", "dominant_degeneracy": NSNull(),
                 "keyframe_count": 2, "solved_count": 1, "point_count": 2,
                 "bounds": ["min": [-1.0, 0.0, 3.0], "max": [1.0, 2.0, 5.0]]],
                ["segment_index": 1, "content_hash": "h1", "frame_id": "segment:1",
                 "registered": false, "transform_to_world": NSNull(),
                 "resolution_state": "unresolved",
                 "dominant_degeneracy": "low_parallax",
                 "keyframe_count": 2, "solved_count": 0, "point_count": 0,
                 "bounds": NSNull()],
            ],
        ]
    }

    func testAManifestDecodesFieldForField() {
        let manifest = WorldGeometryDecoder.manifest(from: manifestJSON())
        XCTAssertEqual(manifest?.segments.count, 2)
        XCTAssertEqual(manifest?.segments[0].contentHash, "h0")
        XCTAssertEqual(manifest?.segments[0].pointCount, 2)
    }

    func testAManifestThatIsBehindTheJournalDecodesAsNotCurrent() {
        // The Tower used to answer 404 for geometry that was real but behind,
        // which during a walk meant the whole capture. It now serves it with
        // current: false, and this flag is the only thing separating a
        // partial world from the finished one.
        var json = manifestJSON()
        json["current"] = false

        let manifest = WorldGeometryDecoder.manifest(from: json)
        XCTAssertNotNil(manifest, "behind is served, not refused")
        XCTAssertEqual(manifest?.current, false)
        XCTAssertEqual(manifest?.segments.count, 2, "the geometry is unchanged")
    }

    func testACurrentManifestSaysSo() {
        var json = manifestJSON()
        json["current"] = true
        XCTAssertEqual(WorldGeometryDecoder.manifest(from: json)?.current, true)
    }

    func testAManifestWithoutTheFieldIsTakenAsCurrent() {
        // An older Tower never sends it -- and that Tower hid anything behind
        // the journal behind a 404, so what it did serve was current by
        // construction.
        XCTAssertNil(manifestJSON()["current"])
        XCTAssertEqual(WorldGeometryDecoder.manifest(from: manifestJSON())?.current, true)
    }

    func testAnUnresolvedSegmentKeepsNilBoundsRatherThanAZeroBox() {
        let manifest = WorldGeometryDecoder.manifest(from: manifestJSON())
        let unresolved = manifest?.segments[1]
        XCTAssertNil(unresolved?.bounds)
        XCTAssertEqual(unresolved?.resolutionState, .unresolved)
        XCTAssertEqual(unresolved?.dominantDegeneracy, "low_parallax")
    }

    func testAPoseConventionMismatchIsRefused() {
        // Inverting T_world_camera still draws a plausible map. That was a
        // real shipped bug, so any mismatch refuses rather than renders.
        var json = manifestJSON()
        var convention = json["pose_convention"] as! [String: Any]
        convention["quaternion_order"] = "xyzw"
        json["pose_convention"] = convention

        let manifest = WorldGeometryDecoder.manifest(from: json)
        XCTAssertNotNil(manifest, "a mismatch decodes; it is the RENDER that refuses")
        XCTAssertFalse(manifest!.poseConvention.matchesThisBuild)
    }

    func testTheExpectedConventionIsAcceptedIncludingUnknownUpAxis() {
        let manifest = WorldGeometryDecoder.manifest(from: manifestJSON())
        XCTAssertTrue(manifest!.poseConvention.matchesThisBuild)
    }

    func testAWrongContractIdentifierIsRefused() {
        var json = manifestJSON()
        json["contract"] = "world_builder.geometry/2027-01-01"
        XCTAssertNil(WorldGeometryDecoder.manifest(from: json))
    }

    func testAMalformedSegmentRowDropsTheWholeManifest() {
        // Skipping the bad row would silently shrink the world and the viewer
        // would render a smaller map as if it were complete.
        var json = manifestJSON()
        var segments = json["segments"] as! [[String: Any]]
        segments[1].removeValue(forKey: "content_hash")
        json["segments"] = segments

        XCTAssertNil(WorldGeometryDecoder.manifest(from: json))
    }

    func testARefusedPoseDecodesAsNilTranslationNotZero() {
        let json: [String: Any] = [
            "contract": "world_builder.geometry/2026-08-25",
            "segment_index": 1, "content_hash": "h1", "frame_id": "segment:1",
            "registered": false, "transform_to_world": NSNull(),
            "poses": [
                ["keyframe_id": "s0:1", "status": "anchor", "degeneracy": "",
                 "rotation": [1.0, 0.0, 0.0, 0.0], "translation": [0.0, 0.0, 0.0]],
                ["keyframe_id": "s0:2", "status": "unavailable",
                 "degeneracy": "low_parallax",
                 "rotation": NSNull(), "translation": NSNull()],
            ],
            "points": [], "points_sent": 0, "points_total": 0,
            "point_sampling": "none",
        ]

        let chunk = WorldGeometryDecoder.chunk(from: json)
        XCTAssertNil(chunk?.poses[1].translation)
        XCTAssertNotNil(chunk?.poses[0].translation)
    }

    func testASampledChunkKnowsItIsPartial() {
        let json: [String: Any] = [
            "contract": "world_builder.geometry/2026-08-25",
            "segment_index": 0, "content_hash": "h0", "frame_id": "segment:0",
            "registered": false, "transform_to_world": NSNull(),
            "poses": [], "points": [[1.0, 2.0, 3.0]],
            "points_sent": 1, "points_total": 3000, "point_sampling": "stride",
        ]

        let chunk = WorldGeometryDecoder.chunk(from: json)
        XCTAssertTrue(chunk!.isSampled)
        XCTAssertEqual(chunk?.pointsTotal, 3000)
    }
}

final class WorldGeometryStoreTests: XCTestCase {

    private func chunk(index: Int, hash: String) -> WorldSegmentChunk {
        WorldSegmentChunk(
            segmentIndex: index, contentHash: hash, registered: false,
            poses: [], points: [[0, 0, 0]], pointsSent: 1, pointsTotal: 1,
            pointSampling: "none"
        )
    }

    func testACachedSegmentIsNotRefetched() async {
        // The property the whole design rests on: a closed segment is frozen,
        // so it crosses the wire exactly once.
        let store = WorldGeometryStore()
        await store.insert(chunk(index: 0, hash: "h0"))

        let needed = await store.hashesMissing(from: ["h0", "h1"])
        XCTAssertEqual(needed, ["h1"])
    }

    func testAChangedHashIsRefetched() async {
        let store = WorldGeometryStore()
        await store.insert(chunk(index: 0, hash: "h0"))

        let needed = await store.hashesMissing(from: ["h0-moved"])
        XCTAssertEqual(needed, ["h0-moved"])
    }

    func testTheCacheIsKeyedByHashNotBySegmentIndex() async {
        // A re-solved segment keeps its index and changes its content. Keying
        // on the index would serve stale geometry under a fresh revision.
        let store = WorldGeometryStore()
        await store.insert(chunk(index: 0, hash: "old"))
        await store.insert(chunk(index: 0, hash: "new"))

        let old = await store.chunk(forHash: "old")
        let new = await store.chunk(forHash: "new")
        XCTAssertNotNil(old)
        XCTAssertNotNil(new)
        XCTAssertEqual(new?.contentHash, "new")
    }
}

final class WorldFragmentsModelTests: XCTestCase {

    private func summary(
        index: Int, points: Int, state: WorldSegmentResolution,
        bounds: WorldBounds? = nil
    ) -> WorldSegmentSummary {
        WorldSegmentSummary(
            segmentIndex: index, contentHash: "h\(index)",
            frameID: "segment:\(index)", registered: false,
            resolutionState: state, dominantDegeneracy: "low_parallax",
            keyframeCount: 10, solvedCount: points > 0 ? 5 : 0,
            pointCount: points, bounds: bounds
        )
    }

    private let box = WorldBounds(json: ["min": [-1.0, 0.0, -1.0],
                                         "max": [1.0, 2.0, 1.0]])!

    func testUnregisteredSegmentsAreNeverCompositedIntoOneCanvas() {
        // The load-bearing negative. Segment anchors all sit at the origin and
        // per-segment scale disagrees by up to ~87x on a real walk, so one
        // shared canvas would superimpose independent reconstructions.
        let model = WorldFragmentsModel(segments: [
            summary(index: 0, points: 100, state: .resolved, bounds: box),
            summary(index: 1, points: 200, state: .resolved, bounds: box),
        ])

        XCTAssertEqual(model.fragments.count, 2)
        XCTAssertFalse(model.hasSharedFrame)
    }

    func testAnUnresolvedSegmentIsCountedButNeverGivenAFragment() {
        // We know reconstruction failed. We do not know where. Drawing it as a
        // region would invent a location.
        let model = WorldFragmentsModel(segments: [
            summary(index: 0, points: 100, state: .resolved, bounds: box),
            summary(index: 1, points: 0, state: .unresolved),
            summary(index: 2, points: 0, state: .unresolved),
        ])

        XCTAssertEqual(model.fragments.count, 1)
        XCTAssertEqual(model.unresolvedCount, 2)
    }

    func testTheHeadlineCountsFragmentsNotSegments() {
        let model = WorldFragmentsModel(segments: [
            summary(index: 0, points: 100, state: .resolved, bounds: box),
            summary(index: 1, points: 0, state: .unresolved),
        ])

        XCTAssertEqual(model.headline, "1 fragment, not yet connected")
    }

    func testAnEmptyWorldSaysNothingIsMappedRatherThanShowingAnEmptyCanvas() {
        let model = WorldFragmentsModel(segments: [])
        XCTAssertTrue(model.fragments.isEmpty)
        XCTAssertEqual(model.headline, "Nothing mapped yet")
    }

    func testAWorldStillBeingBuiltSaysSoRatherThanPassingAsFinished() {
        let model = WorldFragmentsModel(
            segments: [summary(index: 0, points: 100, state: .resolved, bounds: box)],
            isCurrent: false
        )

        XCTAssertEqual(model.fragments.count, 1, "behind geometry is still drawn")
        XCTAssertNotNil(model.buildingNote)
        XCTAssertTrue(model.buildingNote!.contains("still building"))
    }

    func testACurrentWorldAddsNoCaveat() {
        let model = WorldFragmentsModel(
            segments: [summary(index: 0, points: 100, state: .resolved, bounds: box)],
            isCurrent: true
        )
        XCTAssertNil(model.buildingNote)
    }

    func testAResolvedSegmentWithoutBoundsIsNotDrawn() {
        // bounds nil with points > 0 is incoherent; refuse rather than guess
        // a frame for it.
        let model = WorldFragmentsModel(segments: [
            summary(index: 0, points: 100, state: .resolved, bounds: nil),
        ])
        XCTAssertTrue(model.fragments.isEmpty)
    }

    func testRegisteredSegmentsWouldShareAFrame() {
        // Forward compatibility: when registration lands, the renderer does
        // not change -- the fragments merge.
        let registered = WorldSegmentSummary(
            segmentIndex: 0, contentHash: "h0", frameID: "world",
            registered: true, resolutionState: .resolved,
            dominantDegeneracy: nil, keyframeCount: 10, solvedCount: 5,
            pointCount: 100, bounds: box
        )
        let model = WorldFragmentsModel(segments: [registered, registered])
        XCTAssertTrue(model.hasSharedFrame)
    }

    func testEachFragmentIsScaledToItsOwnBoundsAndNeverToASharedOne() {
        // The load-bearing guarantee, asserted directly rather than by proxy.
        // Segments share no coordinate frame and their scales disagree by up to
        // ~87x on a real walk, so a shared scale would composite independent
        // reconstructions into one plausible-looking, meaningless map.
        let size = CGSize(width: 100, height: 100)
        let small = WorldBounds(json: ["min": [0.0, 0.0, 0.0],
                                       "max": [1.0, 0.0, 1.0]])!
        let large = WorldBounds(json: ["min": [0.0, 0.0, 0.0],
                                       "max": [100.0, 0.0, 100.0]])!

        let projectSmall = WorldFragmentsModel.projector(bounds: small, size: size)
        let projectLarge = WorldFragmentsModel.projector(bounds: large, size: size)

        // The same world coordinate lands in different places, because each
        // tile is framed to its own extent.
        XCTAssertNotEqual(projectSmall(1.0, 1.0), projectLarge(1.0, 1.0))

        // And each fragment's own far corner lands at the same relative spot.
        XCTAssertEqual(projectSmall(1.0, 1.0).x,
                       projectLarge(100.0, 100.0).x, accuracy: 0.001)
    }
}

// MARK: - The contract this build adopted

/// The status contract moved, and this pins which one is in force.
///
/// It is a whole test class for one string because the move was **not** a
/// version bump for its own sake. Nothing in the encoding changed; one number
/// changed meaning, and a number that quietly means something else is the exact
/// failure a dated identifier exists to make loud.
final class WorldBuilderContractAdoptionTests: XCTestCase {

    /// Moved from `/2026-08-23` because `trajectory.pose_count` changed
    /// **meaning**.
    ///
    /// It used to be `keyframes - poses_refused`, which counted a segment
    /// anchor — identity rotation, zero translation, one per segment,
    /// definitional rather than measured — as a camera position. That is what
    /// displayed "Camera poses: 36" for a world whose own manifest read
    /// `poses_solved: 0, points: 0`. It is now `poses_positioned`: solved poses
    /// plus the anchor of each segment that actually solved something.
    func testTheStatusContractIsTheOneThisTowerServes() {
        XCTAssertEqual(
            WorldBuilderResultContract.identifier,
            "world_builder.status/2026-08-25"
        )
    }

    /// Same date, different agreement.
    ///
    /// The two were adopted together and it would be easy to start treating
    /// "2026-08-25" as one version of one thing. They are two contracts on two
    /// transports — status over the WebSocket, geometry over HTTP — and either
    /// can move without the other.
    func testTheGeometryContractIsSeparateFromTheStatusContract() {
        XCTAssertNotEqual(
            WorldGeometryContract.identifier,
            WorldBuilderResultContract.identifier
        )
    }

    /// The identifier this build subscribes with is the identifier it
    /// implements. A bump that reached one and not the other would leave the
    /// app refusing a Tower that was speaking its own contract.
    func testTheAdoptedContractIsTheOneThisBuildDeclaresItImplements() {
        XCTAssertEqual(
            TowerCapabilities.supported,
            [WorldBuilderResultContract.identifier],
            "the subscribe guard reads `supported`; a bump that missed it stops the subscription"
        )
    }
}

// MARK: - Where the geometry lives

/// Reading the fetch address out of the status payload.
///
/// The address is the one part of the payload outside `world_snapshot` that
/// this build reads at all, so what it refuses matters as much as what it
/// accepts.
final class WorldGeometryCoordinatesTests: XCTestCase {

    /// `nil` for a block means the Tower sent `null` there, which is how the
    /// wire says "absent" — so each parameter defaults to a present block and
    /// is passed `nil` by the test that wants it gone.
    private func payload(
        worldSnapshot: [String: Any]? = ["world_id": "w1", "revision": "snapshot-rev"],
        session: [String: Any]? = ["session_id": "s1"],
        geometry: [String: Any]? = ["revision": "g1"]
    ) -> [String: Any] {
        var json: [String: Any] = [
            "model_state": "receiving",
            "world_snapshot": NSNull(),
            "session": NSNull(),
            "geometry": NSNull(),
        ]
        if let worldSnapshot { json["world_snapshot"] = worldSnapshot }
        if let session { json["session"] = session }
        if let geometry { json["geometry"] = geometry }
        return json
    }

    func testAllThreePartsOfTheAddressAreRead() {
        let coordinates = WorldBuilderResultDecoder.geometryCoordinates(from: payload())
        XCTAssertEqual(coordinates?.worldID, "w1")
        XCTAssertEqual(coordinates?.sessionID, "s1")
        XCTAssertEqual(coordinates?.revision, "g1")
    }

    /// `session_id` is a **required** query parameter on the Tower's manifest
    /// route. A world id on its own therefore addresses nothing, and half an
    /// address must not become a request.
    func testAMissingSessionRefusesTheWholeAddress() {
        XCTAssertNil(
            WorldBuilderResultDecoder.geometryCoordinates(from: payload(session: nil))
        )
    }

    /// `null` is absent, never zero. No build has produced output for this
    /// session, so there is nothing to point at — which is a different thing
    /// from geometry at "revision nothing".
    func testANullGeometryRevisionMeansNothingIsBuiltNotRevisionZero() {
        XCTAssertNil(
            WorldBuilderResultDecoder.geometryCoordinates(
                from: payload(geometry: ["available": false, "revision": NSNull()])
            )
        )
    }

    /// The load-bearing distinction. The snapshot revision changes whenever any
    /// reported field changes — a keyframe count, a tracking state — and most
    /// of those leave the built points exactly where they were. Keying the
    /// fetch on the snapshot's revision would pull a megabyte for a counter.
    func testTheRevisionComesFromTheGeometryBlockAndNotFromTheSnapshot() {
        let coordinates = WorldBuilderResultDecoder.geometryCoordinates(
            from: payload(geometry: ["revision": "geometry-rev"])
        )
        XCTAssertEqual(coordinates?.revision, "geometry-rev")
        XCTAssertNotEqual(coordinates?.revision, "snapshot-rev")
    }

    /// A payload from a Tower with no session and no build — the shape of most
    /// of a session's first seconds — addresses nothing rather than 404ing
    /// every two seconds.
    func testAnIdleTowerAddressesNothing() {
        XCTAssertNil(
            WorldBuilderResultDecoder.geometryCoordinates(
                from: payload(worldSnapshot: nil, session: nil, geometry: nil)
            )
        )
    }
}

@MainActor
final class WorldBuilderViewModelGeometryTests: XCTestCase {

    /// An incomplete address is refused at the view model too, not only at the
    /// decoder, so that a future caller reaching `geometryDidChange` from
    /// somewhere else cannot compose a URL out of what it happened to have.
    func testAnIncompleteAddressFetchesNothing() async {
        let viewModel = WorldBuilderViewModel(client: UnavailableWorldBuilderClient())
        await viewModel.geometryDidChange(worldID: "w1", sessionID: nil, revision: "g1")
        await viewModel.geometryDidChange(worldID: nil, sessionID: "s1", revision: "g1")
        await viewModel.geometryDidChange(worldID: "w1", sessionID: "s1", revision: nil)
        XCTAssertTrue(viewModel.fragmentsModel.segments.isEmpty)
        XCTAssertTrue(viewModel.geometryChunks.isEmpty)
    }

    /// A client with no Tower behind it publishes no geometry address, so a
    /// view model built on one issues no request of any kind. This is the HTTP
    /// half of what
    /// `TowerClientTests.testCartridgeViewModelsSendNothingToTheTower` asserts
    /// about the socket.
    func testAClientWithNoTowerBehindItNeverAddressesGeometry() async {
        let client = UnavailableWorldBuilderClient()
        var received: [WorldGeometryCoordinates] = []
        let cancellable = client.geometryUpdates.sink { received.append($0) }
        try? await Task.sleep(nanoseconds: 50_000_000)
        cancellable.cancel()
        XCTAssertTrue(received.isEmpty)
    }
}

// MARK: - A failed fetch must not wedge the world

/// A stubbed HTTP layer for the geometry routes.
///
/// `URLProtocol` rather than a local server because the thing under test is not
/// the network — it is what `WorldBuilderViewModel` does to its own retry
/// marker when a request fails. A protocol stub can refuse one specific path,
/// count how many times it was asked, and then start succeeding, which is
/// exactly the sequence the sticky-segment bug lives in.
///
/// `WorldGeometryClient` was written with `baseURL` and `session` as defaulted
/// properties; this is what that was for.
final class StubbedGeometryProtocol: URLProtocol {

    /// Request path → (status code, body). A path with no entry fails as a
    /// transport error, which is a third failure shape worth having.
    private static var routes: [String: (Int, String)] = [:]
    private static var paths: [String] = []
    private static let lock = NSLock()

    static func reset(routes: [String: (Int, String)]) {
        lock.lock()
        defer { lock.unlock() }
        self.routes = routes
        paths = []
    }

    static func set(route: String, to response: (Int, String)) {
        lock.lock()
        defer { lock.unlock() }
        routes[route] = response
    }

    /// How many times a path was requested. The assertion that matters is a
    /// *count*, not a boolean: "it was fetched" is true after the first failing
    /// attempt too, and would pass whether or not the retry ever happened.
    static func requestCount(for path: String) -> Int {
        lock.lock()
        defer { lock.unlock() }
        return paths.filter { $0 == path }.count
    }

    /// A session wired to this stub. `.ephemeral` so nothing is cached between
    /// tests — a cached 404 would make the retry look like it never happened.
    static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubbedGeometryProtocol.self]
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        return URLSession(configuration: configuration)
    }

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let path = request.url?.path ?? ""
        StubbedGeometryProtocol.lock.lock()
        StubbedGeometryProtocol.paths.append(path)
        let route = StubbedGeometryProtocol.routes[path]
        StubbedGeometryProtocol.lock.unlock()

        guard let route, let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        let response = HTTPURLResponse(
            url: url, statusCode: route.0, httpVersion: "HTTP/1.1", headerFields: nil
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(route.1.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

@MainActor
final class WorldGeometryRetryTests: XCTestCase {

    private static let host = URL(string: "http://stub.invalid")!
    private static let manifestPath = "/worlds/w1/geometry/manifest"
    private static let segmentPath = "/worlds/w1/geometry/segment/0"

    /// One segment, resolved, with bounds — the shape that gets a drawn tile,
    /// so a missing chunk is a visibly blank fragment and not a non-event.
    private static let manifestBody = """
        {"contract": "world_builder.geometry/2026-08-25",
         "world_id": "w1", "session_id": "s1", "geometry_revision": "g1",
         "pose_convention": {
           "pose_type": "T_world_camera", "quaternion_order": "wxyz",
           "handedness": "right",
           "camera_axes": "opencv_x_right_y_down_z_forward",
           "translation_units": "world",
           "world_axes_origin": "first_keyframe_camera",
           "up_axis": "unknown", "pose_dtype": "float64",
           "point_dtype": "float32"},
         "segment_count": 1,
         "segments": [
           {"segment_index": 0, "content_hash": "h0", "frame_id": "segment:0",
            "registered": false, "transform_to_world": null,
            "resolution_state": "resolved", "dominant_degeneracy": null,
            "keyframe_count": 2, "solved_count": 1, "point_count": 1,
            "bounds": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}}]}
        """

    private static let segmentBody = """
        {"contract": "world_builder.geometry/2026-08-25",
         "segment_index": 0, "content_hash": "h0", "frame_id": "segment:0",
         "registered": false, "transform_to_world": null,
         "poses": [{"keyframe_id": "s1:0", "status": "anchor", "degeneracy": "",
                    "rotation": [1.0, 0.0, 0.0, 0.0],
                    "translation": [0.0, 0.0, 0.0]}],
         "points": [[0.5, 0.5, 0.5]],
         "points_sent": 1, "points_total": 1, "point_sampling": "none"}
        """

    private func makeViewModel() -> WorldBuilderViewModel {
        WorldBuilderViewModel(
            client: UnavailableWorldBuilderClient(),
            geometry: WorldGeometryClient(
                baseURL: Self.host, session: StubbedGeometryProtocol.makeSession()
            )
        )
    }

    /// A refused segment request must not blank a fragment permanently.
    ///
    /// The revision is the only thing that unlocks a refetch, and a
    /// **finalized** world's revision never moves again — so a segment left
    /// unfetched "until the world changes" is a segment left unfetched forever.
    /// One transient blip on a walk that has already ended would cost that
    /// fragment for good.
    func testARefusedSegmentIsRetriedUnderTheSameRevision() async {
        StubbedGeometryProtocol.reset(routes: [
            Self.manifestPath: (200, Self.manifestBody),
            Self.segmentPath: (404, ""),
        ])
        let viewModel = makeViewModel()

        await viewModel.geometryDidChange(worldID: "w1", sessionID: "s1", revision: "g1")

        // What did arrive is on screen: the manifest's segment is drawn, with
        // no chunk behind it. A blank tile is honest; refusing the whole world
        // because one request failed would show less than the Tower said.
        XCTAssertEqual(viewModel.fragmentsModel.segments.count, 1)
        XCTAssertTrue(viewModel.geometryChunks.isEmpty)
        XCTAssertEqual(StubbedGeometryProtocol.requestCount(for: Self.segmentPath), 1)

        // The next report carries the SAME revision — which is all a finalized
        // world will ever carry — and the fetch must be attempted again.
        StubbedGeometryProtocol.set(route: Self.segmentPath, to: (200, Self.segmentBody))
        await viewModel.geometryDidChange(worldID: "w1", sessionID: "s1", revision: "g1")

        XCTAssertEqual(
            StubbedGeometryProtocol.requestCount(for: Self.segmentPath),
            2,
            "a refused segment was never retried; on a finalized world that tile stays blank forever"
        )
        XCTAssertEqual(viewModel.geometryChunks["h0"]?.points.count, 1)
    }

    /// The negative control, and the reason the test above is not vacuous.
    ///
    /// If `geometryDidChange` simply refetched on every call, the retry
    /// assertion would pass without the marker doing anything at all. This pins
    /// the other half: a fetch that fully succeeded is **not** repeated under an
    /// unchanged revision, which is what stops the ~2 s heartbeat from pulling a
    /// megabyte twice a second.
    func testASucceededFetchIsNotRepeatedUnderTheSameRevision() async {
        StubbedGeometryProtocol.reset(routes: [
            Self.manifestPath: (200, Self.manifestBody),
            Self.segmentPath: (200, Self.segmentBody),
        ])
        let viewModel = makeViewModel()

        await viewModel.geometryDidChange(worldID: "w1", sessionID: "s1", revision: "g1")
        await viewModel.geometryDidChange(worldID: "w1", sessionID: "s1", revision: "g1")
        await viewModel.geometryDidChange(worldID: "w1", sessionID: "s1", revision: "g1")

        XCTAssertEqual(
            StubbedGeometryProtocol.requestCount(for: Self.manifestPath),
            1,
            "an unchanged revision refetched; the heartbeat would pull a megabyte every 2 s"
        )
        XCTAssertEqual(StubbedGeometryProtocol.requestCount(for: Self.segmentPath), 1)
        XCTAssertEqual(viewModel.geometryChunks.count, 1)
    }

    /// The manifest path's own escape hatch, which had no test before.
    func testARefusedManifestIsRetriedUnderTheSameRevision() async {
        StubbedGeometryProtocol.reset(routes: [Self.manifestPath: (404, "")])
        let viewModel = makeViewModel()

        await viewModel.geometryDidChange(worldID: "w1", sessionID: "s1", revision: "g1")
        XCTAssertTrue(viewModel.fragmentsModel.segments.isEmpty)

        StubbedGeometryProtocol.set(route: Self.manifestPath, to: (200, Self.manifestBody))
        StubbedGeometryProtocol.set(route: Self.segmentPath, to: (200, Self.segmentBody))
        await viewModel.geometryDidChange(worldID: "w1", sessionID: "s1", revision: "g1")

        XCTAssertEqual(StubbedGeometryProtocol.requestCount(for: Self.manifestPath), 2)
        XCTAssertEqual(viewModel.fragmentsModel.segments.count, 1)
        XCTAssertEqual(viewModel.geometryChunks.count, 1)
    }
}
