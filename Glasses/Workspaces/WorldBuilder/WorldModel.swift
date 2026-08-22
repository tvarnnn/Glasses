//
//  WorldModel.swift
//  Glasses
//

import Foundation

/// The boundary between the World Builder workspace and whatever the Tower
/// eventually builds.
///
/// **Nothing in this file is a Tower protocol.** The Tower's World Builder is
/// being designed independently and its wire contract does not exist yet, so
/// inventing one here would guarantee a rewrite and — worse — would let the UI
/// display shapes the Tower never agreed to produce. What this file does
/// instead is state the *presentation's* requirements: the smallest set of
/// facts the workspace needs in order to draw something honest.
///
/// Read the types below as a question addressed to the Tower — "can you tell us
/// these things, and in what units?" — not as an answer. When the real contract
/// lands, the reconciliation is one new `WorldModelSource` implementation plus
/// whatever mapping it needs; no view changes.
///
/// See docs/agent-handoffs/product-shell-v2-handoff.md for the list of contract
/// details still needed.

// MARK: - Scale

/// How a spatial figure was arrived at.
///
/// This is not presentation garnish. `docs/modules/WORLD-BUILD.md` makes it a
/// hard requirement: the target glasses are **monocular RGB only**, with no
/// LiDAR and no stereo, so any distance the system produces is inferred rather
/// than measured. That document's rule is absolute —
///
/// > World Build must never represent monocularly inferred depth as ground-truth
/// > physical distance. Any distance figure derived from monocular inference
/// > must be identifiable as an estimate wherever it is stored, *displayed*, or
/// > consumed by another module.
///
/// "Displayed" is this layer. Encoding provenance in the type is what stops a
/// future view from rendering an inferred number as though it were measured:
/// there is no way to show a figure without also having said where it came
/// from.
enum WorldScaleSemantics: Equatable, Sendable, CaseIterable {
    /// Structure and layout without any claimed absolute scale. The honest
    /// default for multi-view geometry on monocular input.
    case relative
    /// A distance estimate from ML monocular depth or geometric inference.
    /// Carries model uncertainty and must always be labelled as an estimate.
    case inferredMetric
    /// Depth from dedicated depth-sensing hardware. **Unreachable on the
    /// current target glasses** — kept because WORLD-BUILD.md requires the
    /// model to accommodate a future measured-depth source without rewriting
    /// the representation, and because its absence is what makes the other
    /// cases meaningful.
    case measuredMetric
    /// The Tower has not said, or has not established scale yet.
    case unknown

    /// Short label for a metric row.
    var displayName: String {
        switch self {
        case .relative: return "Relative"
        case .inferredMetric: return "Estimated"
        case .measuredMetric: return "Measured"
        case .unknown: return "Unknown"
        }
    }

    /// Whether a figure carrying this provenance must be presented as an
    /// estimate rather than as a fact. Views must consult this before rendering
    /// any distance.
    var isEstimate: Bool {
        switch self {
        case .inferredMetric: return true
        case .relative, .measuredMetric, .unknown: return false
        }
    }

    /// One sentence a person can act on, for a detail row or accessibility
    /// value.
    var explanation: String {
        switch self {
        case .relative:
            return "Shape and layout only. No real-world distances are claimed."
        case .inferredMetric:
            return "Distances are estimated from a single camera. Treat them as approximate, not measured."
        case .measuredMetric:
            return "Distances come from depth-sensing hardware."
        case .unknown:
            return "Scale has not been established."
        }
    }
}

// MARK: - Tracking

/// How well the Tower believes it is following the camera through space.
///
/// Deliberately coarse. A percentage would imply a calibrated confidence model
/// that neither side has defined.
enum WorldTrackingQuality: Equatable, Sendable {
    case good
    case limited
    case lost
    /// The Tower does not report tracking, or is not tracking at all.
    case unavailable

    var displayName: String {
        switch self {
        case .good: return "Good"
        case .limited: return "Limited"
        case .lost: return "Lost"
        case .unavailable: return "—"
        }
    }
}

// MARK: - Snapshot

/// One observation of the world the Tower is building.
///
/// Every field is optional, and that is the point: a Tower that reports only a
/// keyframe count must not force the UI to invent a world name, a tracking
/// verdict, or a scale. Absent means absent, and the views render it as such
/// (docs/02-DEVELOPMENT-RULES.md Rule 3).
struct WorldSnapshot: Equatable, Sendable {
    /// Human-readable name, if the Tower names worlds at all.
    var name: String?
    /// Stable identifier for the world being built, if it has one.
    var worldID: String?
    /// Keyframes accepted into the reconstruction.
    var keyframeCount: Int?
    /// Monotonic revision, so the UI can tell "new data" from "same data".
    var revision: Int?
    var tracking: WorldTrackingQuality
    var scale: WorldScaleSemantics
    /// Seconds of mapping the Tower has accumulated, if it keeps that clock.
    /// Deliberately not derived from an iOS timer: the iPhone's idea of elapsed
    /// time is not the Tower's idea of mapping time, and showing one as the
    /// other would be a fabrication.
    var mappingSeconds: TimeInterval?

    init(
        name: String? = nil,
        worldID: String? = nil,
        keyframeCount: Int? = nil,
        revision: Int? = nil,
        tracking: WorldTrackingQuality = .unavailable,
        scale: WorldScaleSemantics = .unknown,
        mappingSeconds: TimeInterval? = nil
    ) {
        self.name = name
        self.worldID = worldID
        self.keyframeCount = keyframeCount
        self.revision = revision
        self.tracking = tracking
        self.scale = scale
        self.mappingSeconds = mappingSeconds
    }

    /// True when the Tower has told us nothing beyond "a world exists".
    var isEmpty: Bool {
        name == nil
            && worldID == nil
            && keyframeCount == nil
            && revision == nil
            && mappingSeconds == nil
            && tracking == .unavailable
            && scale == .unknown
    }
}

// MARK: - State

/// What the world-visualization container should be showing.
///
/// The case that matters today is `.unsupported`. The Tower cannot build a
/// world at all yet — `docs/03-ROADMAP.md` puts the module container at V0.8
/// and the first module at V0.9, and neither exists — so that is the only state
/// the app can currently reach, and the only one it may claim.
///
/// The remaining cases are the shape the container must be able to take, so the
/// view is written once against the full lifecycle instead of being rebuilt
/// when the contract lands. They are unreachable today by construction: the
/// only `WorldModelSource` that exists returns `.unsupported` and nothing else.
enum WorldModelState: Equatable, Sendable {
    /// No Tower-side world builder exists. Carries the reason so the view never
    /// has to compose an explanation of its own.
    case unsupported(reason: String)
    /// A world builder exists, but this session has not begun feeding it.
    case idle
    /// Capture is running; the Tower has not yet returned anything about a
    /// world. Distinct from `.receiving` so "we are sending frames" is never
    /// drawn as "a world is appearing".
    case awaitingFirstUpdate
    /// The Tower is actively reporting world updates.
    case receiving(WorldSnapshot)
    /// Capture ended and the world is final and inspectable.
    case finalized(WorldSnapshot)
    case failed(reason: String)

    /// The snapshot to draw metrics from, when there is one.
    var snapshot: WorldSnapshot? {
        switch self {
        case .receiving(let snapshot), .finalized(let snapshot):
            return snapshot
        case .unsupported, .idle, .awaitingFirstUpdate, .failed:
            return nil
        }
    }

    /// Whether the Tower is currently contributing to a world. Drives the
    /// "live" affordance, and must be false in every state where the app would
    /// otherwise be implying activity it cannot verify.
    var isReceivingUpdates: Bool {
        if case .receiving = self { return true }
        return false
    }

    /// Whether a world exists to look at, mapped or finished.
    var hasWorld: Bool {
        switch self {
        case .receiving, .finalized: return true
        case .unsupported, .idle, .awaitingFirstUpdate, .failed: return false
        }
    }
}

// MARK: - Source

/// Supplies `WorldModelState` to the workspace.
///
/// The seam. One conformer exists today and it reports only that the capability
/// is absent; the Tower-backed conformer is tomorrow's work, once the real
/// contract is known.
///
/// `AnyObject`-constrained and `@MainActor` because the eventual implementation
/// will hold a subscription to the Tower connection and publish into SwiftUI,
/// matching how `TowerClient` and `GlassesConnection` already behave.
@MainActor
protocol WorldModelSource: AnyObject {
    var state: WorldModelState { get }
}

/// The only source that exists: the Tower has no world builder, and says so.
///
/// Not a stub in the pejorative sense — it is the correct and complete
/// implementation of the current situation. Replacing it later is an addition,
/// not a correction.
@MainActor
final class UnavailableWorldModelSource: WorldModelSource {
    /// Written for a person, not a log. The workspace shows this verbatim, so
    /// it has to explain the situation without implying either that something
    /// is broken or that a world is coming imminently.
    static let reason = """
        The Tower does not build worlds yet. Frames captured here reach the \
        Tower and are processed by its current fixed handler, which returns a \
        simple per-frame result — not a spatial model.
        """

    let state: WorldModelState = .unsupported(reason: UnavailableWorldModelSource.reason)

    init() {}
}
