//
//  SceneUnderstandingWorkspaceView.swift
//  Glasses
//

import Foundation
import SwiftUI

/// The Scene Understanding workspace: who and what the Tower can currently see,
/// stated as carefully as the platform's limitations require.
///
/// ## What this screen may and may not claim
///
/// The Tower analyses nothing, so the workspace shows no entities and says why.
/// When it can, this screen is bound by three rules that are enforced in the
/// model types and restated here because they are display rules:
///
/// - people are **anonymous positional tracks**, never named or identified;
/// - orientation is body-facing, never gaze — "facing your direction", never
///   "looking at you" (`docs/07-PLATFORM-CONSTRAINTS.md` Limitation 8);
/// - a count is a statement about the camera's field of view, never about the
///   room (Core Principle 3), and carries `SceneSnapshot.countCaveat`.
///
/// ## No camera controls
///
/// As with Experimental CV Lab and Document Memory: the app's session controls
/// stay on Home and World Builder, so the set of places that can start the
/// camera does not grow.
struct SceneUnderstandingWorkspaceView: View {
    /// A value, not the connection — see `TowerReachabilityReader`.
    let isTowerReachable: Bool

    @StateObject private var scene: SceneUnderstandingViewModel

    /// The client is injected and owned by `ProjectManager`; see
    /// `CartridgeClients`.
    init(isTowerReachable: Bool, client: any SceneUnderstandingClient) {
        self.isTowerReachable = isTowerReachable
        _scene = StateObject(wrappedValue: SceneUnderstandingViewModel(client: client))
    }

    private var availability: CartridgeAvailability {
        scene.availability(isTowerReachable: isTowerReachable)
    }

    var body: some View {
        VStack(spacing: 16) {
            header

            if let forcedPhase = availability.forcedPhase {
                CartridgeStatePanel(
                    title: "The scene",
                    phase: forcedPhase,
                    explanation: scene.unavailableExplanation(isTowerReachable: isTowerReachable),
                    futureDescription: Self.futureDescription
                )
            } else {
                scenePanel
            }
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Scene Understanding")
                .font(.title2.weight(.semibold))
            Text("An anonymous read of what the camera can see — how many people and objects are in front of you, and roughly where. The Tower analyses nothing yet.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private static let futureDescription = """
        When the Tower can read a scene, this panel will show anonymous tracks — \
        how many people and objects are in view, roughly where each one is, and \
        which way it is facing. Nobody is identified, and nothing here can tell \
        where anyone is looking. None of it exists yet.
        """

    // MARK: The panel for a Tower that can actually see

    /// Unreachable today.
    @ViewBuilder
    private var scenePanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("The scene")

            VStack(alignment: .leading, spacing: 12) {
                switch scene.state {
                case .unsupported(let reason):
                    Text(reason)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                case .idle:
                    Text("Nothing is being observed.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                case .awaitingFirstScene:
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Waiting for the Tower's first reading…")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

                case .observing(let snapshot):
                    SceneSummaryView(snapshot: snapshot, isCurrent: true)

                case .lastKnown(let snapshot):
                    SceneSummaryView(snapshot: snapshot, isCurrent: false)

                case .failed(let failure):
                    Label("Scene reading failed", systemImage: "exclamationmark.triangle.fill")
                        .font(.headline)
                    Text(failure.message)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 18))
        }
    }
}

/// Renders one scene reading.
///
/// Unreachable today — no client produces a snapshot.
struct SceneSummaryView: View {
    let snapshot: SceneSnapshot
    /// False when this is the last thing seen rather than what is seen now.
    let isCurrent: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !isCurrent {
                // A stale scene must announce its staleness before its
                // contents, not after — Limitation 7. When the Tower did not
                // report an observation time, that is said outright rather
                // than filled in from the phone's clock.
                Label(staleHeadline, systemImage: "clock.arrow.circlepath")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.secondary)
            }

            counts

            ForEach(Array(snapshot.entities.enumerated()), id: \.element.id) { index, entity in
                entityRow(entity, index: index)
            }

            if !snapshot.relationships.isEmpty {
                relationshipRows
            }

            Text(SceneSnapshot.countCaveat)
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)

            if snapshot.entities.contains(where: { $0.facing != .unknown }) {
                Text(SceneFacing.gazeCaveat)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            // `ObservedDuration.attentionCaveat` is documented as the footnote
            // *any* surface showing a duration owes the reader. It was being
            // shown on the Document Memory rows and not here — and this is the
            // surface where "In view 12s" beside a person most invites the
            // reading Limitation 8 forbids.
            if snapshot.entities.contains(where: { $0.observedDuration != nil }) {
                Text(ObservedDuration.attentionCaveat)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var staleHeadline: String {
        guard let observed = snapshot.time.displayableObservationTime else {
            return "Last reading. The Tower did not say when."
        }
        return "Last reading, \(observed.formatted(date: .abbreviated, time: .shortened))"
    }

    private var counts: some View {
        HStack(spacing: 16) {
            countPill("\(snapshot.personCount)", label: snapshot.personCount == 1 ? "person" : "people")
            countPill("\(snapshot.objectCount)", label: snapshot.objectCount == 1 ? "object" : "objects")
        }
        .accessibilityElement(children: .combine)
    }

    private func countPill(_ value: String, label: String) -> some View {
        HStack(spacing: 4) {
            Text(value)
                .font(.title3.weight(.semibold))
                .monospacedDigit()
            Text(label)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    /// One anonymous track.
    ///
    /// The row is built from position, orientation and duration — never from an
    /// identifier. `SceneTrackID.displayName(index:kind:)` produces "Person 1"
    /// from the row's ordinal, so nothing on screen carries the Tower's handle
    /// or anything that could be mistaken for a persistent identity.
    private func entityRow(_ entity: SceneEntity, index: Int) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(entity.trackID.displayName(index: index, kind: entity.kind))
                    .font(.body.weight(.medium))
                Spacer(minLength: 12)
                if let bearing = entity.position?.bearingDescription {
                    Text(bearing)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 10) {
                if entity.facing != .unknown {
                    Text(entity.facing.displayName)
                }
                if let position = entity.position, position.distanceDisplayable,
                   let distance = position.distance {
                    Text(ReportedFigure.format(distance, unit: position.distanceUnit))
                    if position.scale.isEstimate {
                        Text("estimated")
                    }
                }
                // Labelled. A bare "70%" in a caption row is a confidence that
                // survived the whole pipeline (Core Principle 4) and was then
                // rendered unreadable at the last inch.
                if let confidence = entity.provenance.confidence {
                    Text("\(ObservationProvenance.percent(confidence)) confident")
                }
                if let duration = entity.observedDuration {
                    Text(duration.label)
                }
            }
            .font(.caption)
            .foregroundStyle(.tertiary)
        }
        .accessibilityElement(children: .combine)
    }

    /// Relations, with the Tower's predicate quoted verbatim and its confidence
    /// alongside — a relation is an inference about two inferences and is the
    /// least certain thing here.
    private var relationshipRows: some View {
        VStack(alignment: .leading, spacing: 4) {
            SectionLabel("Between them")
            ForEach(snapshot.relationships) { relationship in
                HStack {
                    Text(relationshipText(relationship))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 8)
                    if let confidence = relationship.provenance.confidence {
                        Text("\(ObservationProvenance.percent(confidence)) confident")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
        }
    }

    private func relationshipText(_ relationship: SceneRelationship) -> String {
        let subject = label(for: relationship.subject)
        let object = label(for: relationship.object)
        return "\(subject) \(relationship.predicate) \(object)"
    }

    /// Resolves a track handle back to the positional name the list is using,
    /// so a relation refers to the same "Person 2" the reader can see above it.
    private func label(for trackID: SceneTrackID) -> String {
        guard let index = snapshot.entities.firstIndex(where: { $0.trackID == trackID }) else {
            // A relation naming a track that is not in the list. Said plainly
            // rather than dropped: a missing half of a relation is information.
            return "an untracked thing"
        }
        return trackID.displayName(index: index, kind: snapshot.entities[index].kind)
    }
}
