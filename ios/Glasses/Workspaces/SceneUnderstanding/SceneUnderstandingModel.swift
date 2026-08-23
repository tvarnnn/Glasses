//
//  SceneUnderstandingModel.swift
//  Glasses
//

import Foundation

/// The boundary between the Scene Understanding workspace and whatever
/// structured scene state the Tower eventually produces.
///
/// **Nothing in this file is a Tower protocol.** No detector, no class
/// vocabulary, no message, and no world-geometry convention. See
/// `docs/modules/SCENE-UNDERSTANDING.md` for how this cartridge's scope was
/// drawn from `docs/modules/OBJECT-MEMORY.md` and the platform limitations.
///
/// There is **one** convention stated here and it is stated on purpose:
/// `ScenePosition.bearingDegrees` is signed positive-to-the-right. A bearing
/// has to be signed *somehow* to be usable at all, and a silent presumption is
/// the dangerous version — a Tower that signs the other way would put every
/// person on the wrong side of the wearer, rendering confidently and wrongly.
/// So the convention is declared, the decode site is required to convert into
/// it, and `docs/agent-handoffs/IOS-TO-TOWER.md` §4.3 asks the Tower to state
/// its own. This is the opposite of the geometry and pose cases, where a wrong
/// guess is unrecoverable and no convention is offered at all.
///
/// ## Four refusals, and none of them is negotiable
///
/// **No identity.** There is no name, no face descriptor, no re-identification
/// handle, and no field that could carry one. `docs/07-PLATFORM-CONSTRAINTS.md`
/// Limitation 6 distinguishes "black backpack detected" from "likely the same
/// black backpack previously observed"; for *people*,
/// `docs/modules/ENVIRONMENTAL-MEMORY.md` goes further and says to "avoid
/// biometric identity features unless a future use case explicitly justifies
/// them". A tracked person here is an anonymous track and nothing else.
///
/// That guarantee is **structural, not tested**: `SceneEntityKind.person` has
/// no associated value, so there is nowhere to put a name without changing the
/// type — and no runtime test can assert the absence of a field. What the tests
/// do cover is the consequence: that nothing identity-bearing reaches the
/// display.
///
/// **No gaze.** `SceneFacing` describes body/head orientation, and the labels
/// say "facing your direction" — never "looking at you". Limitation 8 is
/// explicit that camera presence establishes nothing about attention, and its
/// mitigation is classified REQUIRES FUTURE HARDWARE/API: there is no eye
/// tracking on the target glasses, so there is no gaze to report, at any
/// confidence.
///
/// **No absence claims.** A count of zero means zero *currently tracked in the
/// camera's field of view*, which is a statement about the camera and not about
/// the room. Core Principle 3.
///
/// **No unlabelled distances.** Any distance to an entity carries
/// `WorldScaleSemantics`, because monocular RGB produces inferred depth and
/// `docs/modules/WORLD-BUILD.md` forbids presenting inference as measurement
/// anywhere it is displayed.

// MARK: - Track identity

/// An anonymous handle for one thing the Tower is following.
///
/// ## Session-scoped by contract, and why that is the whole design
///
/// This is deliberately **not** a durable identity. It distinguishes "the
/// person on the left" from "the person on the right" *within one tracking
/// session*, which is what a live scene view needs, and it is meaningless
/// afterwards. A handle that survived sessions would be a re-identification
/// key — a biometric identifier by function regardless of what it is made of —
/// and nothing in this app may persist one.
///
/// A wrapper type rather than a bare `String` so that its rules can be written
/// down where they cannot be missed, and so a plain string identifier from
/// somewhere durable cannot be passed here by accident.
struct SceneTrackID: Equatable, Hashable, Sendable {
    /// The Tower's within-session handle. Opaque; never parsed.
    let rawValue: String

    init(_ rawValue: String) {
        self.rawValue = rawValue
    }

    /// What to call this track on screen.
    ///
    /// Positional and generic on purpose. The Tower's raw handle is not shown:
    /// a stable-looking string next to a person's outline invites a reader to
    /// treat it as an identity, which is precisely the reading this type
    /// exists to prevent.
    func displayName(index: Int, kind: SceneEntityKind) -> String {
        switch kind {
        case .person: return "Person \(index + 1)"
        case .object(let label): return label ?? "Object \(index + 1)"
        }
    }
}

/// What kind of thing a track is.
///
/// `.person` carries **nothing**. Not a label, not an attribute, not a
/// descriptor. There is no field to add one to, which is what makes anonymity a
/// property of the type rather than a policy someone has to remember.
///
/// `.object` carries the Tower's class label — "chair", "laptop" — which is a
/// category and not an identity. Limitation 6's distinction, encoded: a class
/// label may be shown, an identity claim may not be made, and there is nowhere
/// to put one.
enum SceneEntityKind: Equatable, Sendable {
    case person
    case object(label: String?)

    var isPerson: Bool {
        if case .person = self { return true }
        return false
    }
}

// MARK: - Orientation

/// Which way a tracked person or object is oriented, relative to the wearer.
///
/// ## The wording is the feature
///
/// `docs/07-PLATFORM-CONSTRAINTS.md` Limitation 8:
///
/// > Something appearing in the glasses camera does not prove the user looked
/// > directly at it, noticed it, read it, understood it, or interacted with it.
///
/// and its mitigation is "purely linguistic/labeling discipline, not a
/// technical fix", classified REQUIRES FUTURE HARDWARE/API. The same holds in
/// the other direction: a person's body facing the camera does not establish
/// that they are looking at the wearer, and the glasses have no sensor that
/// could establish it.
///
/// So `.towardCamera` reads **"Facing your direction"**. It does not read
/// "Looking at you", "Watching you", "Making eye contact", or any softened
/// version of those. A test asserts none of those words can appear in these
/// labels, because this is exactly the sort of copy that gets "improved" later
/// by someone who does not know why it is worded this way.
enum SceneFacing: Equatable, Sendable, CaseIterable {
    /// The Tower did not report orientation.
    case unknown
    /// Oriented toward the camera.
    case towardCamera
    /// Oriented away from the camera.
    case awayFromCamera
    /// Oriented across the camera's view.
    case acrossView

    var displayName: String {
        switch self {
        case .unknown: return "Orientation unknown"
        case .towardCamera: return "Facing your direction"
        case .awayFromCamera: return "Facing away"
        case .acrossView: return "Facing across"
        }
    }

    /// The caveat any surface showing orientation owes the reader.
    ///
    /// A single shared constant rather than per-case prose, so it cannot be
    /// dropped from one case and kept in another.
    static let gazeCaveat =
        "Body orientation only. The glasses have no eye tracking and cannot tell where anyone is looking."
}

// MARK: - Position

/// Which frame a position is expressed in.
///
/// The distinction matters to a reader, not just to a renderer: a bearing
/// relative to the camera changes when the wearer turns their head, and a
/// world-relative position does not. Presenting one as the other produces a
/// position that is stale the instant the wearer moves.
enum SceneFrameOfReference: Equatable, Sendable {
    /// Relative to where the camera is pointing right now.
    case cameraRelative
    /// Relative to a world the Tower built. Carries the world's identifier so
    /// the claim is checkable, and so a position cannot silently drift onto a
    /// different world.
    case worldRelative(worldID: String?)

    var displayName: String {
        switch self {
        case .cameraRelative: return "Relative to the camera"
        case .worldRelative: return "Relative to the world"
        }
    }
}

/// Where a track is, as far as the Tower can say.
///
/// Both figures are optional, and `distance` is gated by `scale` exactly as
/// World Builder's path length is: on monocular RGB the honest answer is
/// usually that a distance cannot be shown as metres at all.
struct ScenePosition: Equatable, Sendable {
    var frame: SceneFrameOfReference
    /// Degrees from straight ahead, **positive to the right** — the one stated
    /// convention in this file; see the file's header for why it is declared
    /// rather than presumed. Not gated by scale: a bearing is an angle, which
    /// multi-view geometry gives directly and which needs no depth to be true.
    var bearingDegrees: Double?
    /// Distance from the camera, in the unit the Tower names below.
    var distance: Double?
    /// The Tower's unit string for `distance`, if it gave one.
    ///
    /// **Never assumed to be metres.** `WorldScaleSemantics.inferredMetric`
    /// says a figure is *metric in kind*; it does not say what unit it is
    /// counted in, and the Tower has named none. `CVMetric.unit` takes the same
    /// position for the same reason — an unlabelled quantity is shown as a bare
    /// number, because that is what it is.
    var distanceUnit: String?
    /// How `distance` was arrived at.
    var scale: WorldScaleSemantics

    init(
        frame: SceneFrameOfReference,
        bearingDegrees: Double? = nil,
        distance: Double? = nil,
        distanceUnit: String? = nil,
        scale: WorldScaleSemantics = .unknown
    ) {
        self.frame = frame
        self.bearingDegrees = bearingDegrees
        self.distance = distance
        self.distanceUnit = distanceUnit
        self.scale = scale
    }

    /// Whether `distance` may be shown as a physical distance.
    var distanceDisplayable: Bool {
        guard distance != nil else { return false }
        switch scale {
        case .inferredMetric, .measuredMetric: return true
        case .relative, .unknown: return false
        }
    }

    /// A bearing in words.
    ///
    /// Coarse on purpose — "37.4° right" implies an angular precision that a
    /// bounding-box centre does not support.
    ///
    /// ## Why there is no "behind you"
    ///
    /// An earlier version said "Beside you, left" past 60° and "Behind you,
    /// right" past 120°. The glasses observe a **forward cone**. A tracked
    /// entity at 150° cannot be a camera observation, so those phrases would
    /// have told the wearer the system had detected someone behind them —
    /// which it cannot do, and which is precisely the awareness
    /// `docs/modules/SCENE-UNDERSTANDING.md` disclaims:
    ///
    /// > Field of view is narrower than human awareness, and a wearer looking
    /// > at a desk has most of the room behind the camera.
    ///
    /// So the vocabulary is capped at what a forward camera can support. A
    /// bearing beyond the plausible field of view is reported as being at its
    /// edge rather than given a direction the sensor cannot justify.
    var bearingDescription: String? {
        guard let bearingDegrees else { return nil }
        let magnitude = abs(bearingDegrees)
        if magnitude < 15 { return "Ahead" }
        let side = bearingDegrees > 0 ? "right" : "left"
        if magnitude < 45 { return "To your \(side)" }
        return "At the edge of view, \(side)"
    }
}

// MARK: - Entity

/// One thing the Tower is tracking right now.
struct SceneEntity: Equatable, Identifiable, Sendable {
    let trackID: SceneTrackID
    let kind: SceneEntityKind
    var position: ScenePosition?
    var facing: SceneFacing
    /// How the Tower arrived at this track. In practice always `.inferred`;
    /// required rather than defaulted so the decoder has to say.
    var provenance: ObservationProvenance
    /// When it was observed and when this app heard, kept apart.
    var time: ObservationTime
    /// How long it has been in the camera's view. Not attention.
    var observedDuration: ObservedDuration?

    var id: SceneTrackID { trackID }

    init(
        trackID: SceneTrackID,
        kind: SceneEntityKind,
        position: ScenePosition? = nil,
        facing: SceneFacing = .unknown,
        provenance: ObservationProvenance,
        time: ObservationTime = ObservationTime(),
        observedDuration: ObservedDuration? = nil
    ) {
        self.trackID = trackID
        self.kind = kind
        self.position = position
        self.facing = facing
        self.provenance = provenance
        self.time = time
        self.observedDuration = observedDuration
    }
}

// MARK: - Relationships

/// A relation the Tower reports between two tracks.
///
/// The predicate is an **opaque string the Tower chooses** — "next to",
/// "holding", "seated at". iOS displays it and never matches on it, for the
/// same reason `WorldGeometryReport.representation` is opaque: a fixed
/// vocabulary here would make the phone the place the Tower's semantics are
/// decided, and any term missing from the enum would have to be dropped or
/// mangled.
///
/// Confidence is required, because a relation is an inference about two
/// inferences and is therefore the least certain thing on the screen.
struct SceneRelationship: Equatable, Identifiable, Sendable {
    let subject: SceneTrackID
    /// The Tower's own word for the relation. Displayed verbatim.
    let predicate: String
    let object: SceneTrackID
    let provenance: ObservationProvenance

    var id: String { "\(subject.rawValue)|\(predicate)|\(object.rawValue)" }

    init(
        subject: SceneTrackID,
        predicate: String,
        object: SceneTrackID,
        provenance: ObservationProvenance
    ) {
        self.subject = subject
        self.predicate = predicate
        self.object = object
        self.provenance = provenance
    }
}

// MARK: - Snapshot

/// The scene as the Tower currently understands it.
struct SceneSnapshot: Equatable, Sendable {
    var entities: [SceneEntity]
    var relationships: [SceneRelationship]
    var time: ObservationTime

    init(
        entities: [SceneEntity] = [],
        relationships: [SceneRelationship] = [],
        time: ObservationTime = ObservationTime()
    ) {
        self.entities = entities
        self.relationships = relationships
        self.time = time
    }

    /// People currently tracked **in the camera's field of view**.
    ///
    /// Derived from `entities` rather than taken as a separate number from the
    /// Tower, so the count and the list can never disagree — a header saying
    /// "3 people" above two rows is the kind of small lie that costs a user's
    /// trust in everything else on the screen.
    var personCount: Int { entities.filter { $0.kind.isPerson }.count }

    var objectCount: Int { entities.count - personCount }

    /// The sentence that must accompany any count.
    ///
    /// Core Principle 3: the camera not seeing someone is not evidence that
    /// nobody is there. A bare "0 people" invites exactly that reading.
    static let countCaveat =
        "Counts what the camera can currently see. People outside its view are not counted and not ruled out."

    var isEmpty: Bool { entities.isEmpty && relationships.isEmpty }
}

// MARK: - State

/// What the Scene Understanding workspace should be showing.
///
/// `.unsupported` is the only reachable state today.
enum SceneUnderstandingState: Equatable, Sendable {
    case unsupported(reason: String)
    /// The Tower can understand scenes but nothing is being observed.
    case idle
    /// Observing, and the Tower has not reported a scene yet.
    case awaitingFirstScene
    /// A live scene. The only state in which the entity list is current.
    case observing(SceneSnapshot)
    /// Observation stopped; this is the last scene reported.
    ///
    /// The snapshot's `time.observedAt` is what lets the view say *when*. A
    /// last-known scene rendered without its age is a stale observation
    /// presented as a current fact, which is precisely Limitation 7 — so the
    /// workspace states the age, or states that the age is unknown.
    case lastKnown(SceneSnapshot)
    case failed(CartridgeFailure)

    var snapshot: SceneSnapshot? {
        switch self {
        case .observing(let snapshot), .lastKnown(let snapshot): return snapshot
        case .unsupported, .idle, .awaitingFirstScene, .failed: return nil
        }
    }

    /// Whether the scene on screen is current. False for `.lastKnown`, which is
    /// the whole reason that case is separate.
    var isCurrent: Bool {
        if case .observing = self { return true }
        return false
    }

    var phase: CartridgePhase {
        switch self {
        case .unsupported: return .unsupported
        case .idle: return .idle
        case .awaitingFirstScene: return .waiting
        case .observing: return .live
        case .lastKnown: return .settled
        case .failed: return .failed
        }
    }
}
