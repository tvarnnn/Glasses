import XCTest
import CoreGraphics
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
