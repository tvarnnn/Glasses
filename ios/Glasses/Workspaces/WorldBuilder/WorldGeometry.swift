//
//  WorldGeometry.swift
//  Glasses
//

import Foundation

/// The geometry agreement this build implements. Separate from the status
/// contract so either may move without the other, and opaque: compared for
/// equality only.
enum WorldGeometryContract {
    static let identifier = "world_builder.geometry/2026-08-25"
}

/// The nine keys that decide what a pose means.
///
/// Every one of them renders plausibly and wrongly if guessed — inverting
/// `T_world_camera` still produces a map that looks like a map, and that was a
/// real shipped bug. So the convention travels on the wire, and this build
/// compares the five keys that change how a pose is interpreted
/// (`poseType`, `quaternionOrder`, `handedness`, `cameraAxes`,
/// `translationUnits`) before drawing anything. `upAxis` is deliberately
/// excluded — see `matchesThisBuild` below — because the 2D top-down view
/// does not depend on which way is up.
struct WorldPoseConvention: Equatable, Sendable {
    let poseType: String
    let quaternionOrder: String
    let handedness: String
    let cameraAxes: String
    let translationUnits: String
    let worldAxesOrigin: String
    /// `"unknown"` today. It becomes a real axis when a floor plane exists,
    /// which is the signal a 3D renderer needs to stop guessing which way is up.
    let upAxis: String
    let poseDtype: String
    let pointDtype: String

    /// What this build knows how to draw. `upAxis` is deliberately absent:
    /// the 2D top-down view does not depend on it, so an unknown up-axis is
    /// not a mismatch.
    var matchesThisBuild: Bool {
        poseType == "T_world_camera"
            && quaternionOrder == "wxyz"
            && handedness == "right"
            && cameraAxes == "opencv_x_right_y_down_z_forward"
            && translationUnits == "world"
    }
}

// In an extension so the memberwise initialiser survives, as above.
extension WorldPoseConvention {
    init?(json: [String: Any]) {
        guard
            let poseType = json["pose_type"] as? String,
            let quaternionOrder = json["quaternion_order"] as? String,
            let handedness = json["handedness"] as? String,
            let cameraAxes = json["camera_axes"] as? String,
            let translationUnits = json["translation_units"] as? String,
            let worldAxesOrigin = json["world_axes_origin"] as? String,
            let upAxis = json["up_axis"] as? String,
            let poseDtype = json["pose_dtype"] as? String,
            let pointDtype = json["point_dtype"] as? String
        else { return nil }
        self.poseType = poseType
        self.quaternionOrder = quaternionOrder
        self.handedness = handedness
        self.cameraAxes = cameraAxes
        self.translationUnits = translationUnits
        self.worldAxesOrigin = worldAxesOrigin
        self.upAxis = upAxis
        self.poseDtype = poseDtype
        self.pointDtype = pointDtype
    }
}

/// Whether a segment produced geometry, or produced nothing while looking.
enum WorldSegmentResolution: String, Equatable, Sendable {
    case resolved
    case unresolved
}

struct WorldBounds: Equatable, Sendable {
    let min: [Double]
    let max: [Double]

    init?(json: Any?) {
        guard
            let dict = json as? [String: Any],
            let min = dict["min"] as? [Double], min.count == 3,
            let max = dict["max"] as? [Double], max.count == 3
        else { return nil }
        self.min = min
        self.max = max
    }
}

struct WorldSegmentSummary: Equatable, Sendable {
    let segmentIndex: Int
    let contentHash: String
    let frameID: String
    /// False for every segment today. Two unregistered segments may never be
    /// drawn in one space — they share no coordinate frame and their scales
    /// disagree by up to ~87x on a real walk.
    let registered: Bool
    let resolutionState: WorldSegmentResolution
    /// Why this segment's refused poses were refused. Genuinely actionable:
    /// `low_parallax` means move sideways rather than turning on the spot.
    let dominantDegeneracy: String?
    let keyframeCount: Int
    let solvedCount: Int
    let pointCount: Int
    /// `nil` when the segment resolved to nothing. Never a zero-size box —
    /// absent and empty are different claims.
    let bounds: WorldBounds?
}

// The JSON initialiser lives in an extension ON PURPOSE. Declaring an `init`
// inside the struct body suppresses Swift's memberwise initialiser, and the
// tests build these values directly rather than from JSON.
extension WorldSegmentSummary {
    init?(json: [String: Any]) {
        guard
            let segmentIndex = json["segment_index"] as? Int,
            let contentHash = json["content_hash"] as? String,
            let frameID = json["frame_id"] as? String,
            let registered = json["registered"] as? Bool,
            let stateWord = json["resolution_state"] as? String,
            let state = WorldSegmentResolution(rawValue: stateWord),
            let keyframeCount = json["keyframe_count"] as? Int,
            let solvedCount = json["solved_count"] as? Int,
            let pointCount = json["point_count"] as? Int
        else { return nil }
        self.segmentIndex = segmentIndex
        self.contentHash = contentHash
        self.frameID = frameID
        self.registered = registered
        self.resolutionState = state
        self.dominantDegeneracy = json["dominant_degeneracy"] as? String
        self.keyframeCount = keyframeCount
        self.solvedCount = solvedCount
        self.pointCount = pointCount
        self.bounds = WorldBounds(json: json["bounds"])
    }
}

struct WorldGeometryManifest: Equatable, Sendable {
    let worldID: String
    let sessionID: String
    let geometryRevision: String
    let poseConvention: WorldPoseConvention
    let segments: [WorldSegmentSummary]

    var resolvedSegments: [WorldSegmentSummary] {
        segments.filter { $0.resolutionState == .resolved }
    }

    /// Segments that hold keyframes and recovered nothing. On the real walk
    /// this was 32 of 51. They are counted, never placed: we know
    /// reconstruction failed, not where it failed.
    var unresolvedSegments: [WorldSegmentSummary] {
        segments.filter { $0.resolutionState == .unresolved }
    }
}

struct WorldPose: Equatable, Sendable {
    let keyframeID: String
    let status: String
    let degeneracy: String
    let rotation: [Double]?
    /// `nil` means the pose was refused. The renderer draws a break here, not
    /// a line through the gap, and never substitutes zero.
    let translation: [Double]?
}

// In an extension so the memberwise initialiser survives, as above.
extension WorldPose {
    init?(json: [String: Any]) {
        guard
            let keyframeID = json["keyframe_id"] as? String,
            let status = json["status"] as? String
        else { return nil }
        self.keyframeID = keyframeID
        self.status = status
        self.degeneracy = json["degeneracy"] as? String ?? ""
        self.rotation = json["rotation"] as? [Double]
        self.translation = json["translation"] as? [Double]
    }
}

struct WorldSegmentChunk: Equatable, Sendable {
    let segmentIndex: Int
    let contentHash: String
    let registered: Bool
    let poses: [WorldPose]
    let points: [[Double]]
    let pointsSent: Int
    let pointsTotal: Int
    let pointSampling: String

    /// True when the cloud on screen is not the whole cloud. The UI must say
    /// so rather than let a coarse world read as a complete one.
    var isSampled: Bool { pointsSent < pointsTotal }
}

enum WorldGeometryDecoder {

    static func manifest(from json: [String: Any]) -> WorldGeometryManifest? {
        guard
            json["contract"] as? String == WorldGeometryContract.identifier,
            let worldID = json["world_id"] as? String,
            let sessionID = json["session_id"] as? String,
            let revision = json["geometry_revision"] as? String,
            let conventionJSON = json["pose_convention"] as? [String: Any],
            let convention = WorldPoseConvention(json: conventionJSON),
            let rawSegments = json["segments"] as? [[String: Any]]
        else { return nil }

        // A row that will not decode drops the whole manifest rather than
        // silently shrinking the world.
        var segments: [WorldSegmentSummary] = []
        for raw in rawSegments {
            guard let segment = WorldSegmentSummary(json: raw) else { return nil }
            segments.append(segment)
        }

        return WorldGeometryManifest(
            worldID: worldID, sessionID: sessionID, geometryRevision: revision,
            poseConvention: convention, segments: segments
        )
    }

    static func chunk(from json: [String: Any]) -> WorldSegmentChunk? {
        guard
            json["contract"] as? String == WorldGeometryContract.identifier,
            let segmentIndex = json["segment_index"] as? Int,
            let contentHash = json["content_hash"] as? String,
            let registered = json["registered"] as? Bool,
            let rawPoses = json["poses"] as? [[String: Any]],
            let points = json["points"] as? [[Double]],
            let sent = json["points_sent"] as? Int,
            let total = json["points_total"] as? Int,
            let sampling = json["point_sampling"] as? String
        else { return nil }

        var poses: [WorldPose] = []
        for raw in rawPoses {
            guard let pose = WorldPose(json: raw) else { return nil }
            poses.append(pose)
        }

        return WorldSegmentChunk(
            segmentIndex: segmentIndex, contentHash: contentHash,
            registered: registered, poses: poses, points: points,
            pointsSent: sent, pointsTotal: total, pointSampling: sampling
        )
    }
}
