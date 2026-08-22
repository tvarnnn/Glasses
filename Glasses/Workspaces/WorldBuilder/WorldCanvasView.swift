//
//  WorldCanvasView.swift
//  Glasses
//

import Foundation
import SwiftUI

/// The world-visualization container: the place a spatial model will eventually
/// be drawn, and today the place the app explains that there is not one.
///
/// It renders `WorldModelState` and nothing else, so it cannot show geometry
/// the Tower did not send. Today the only reachable state is `.unsupported`,
/// because `UnavailableWorldBuilderClient` is the only client that exists.
///
/// Deliberately absent, and each for a reason:
///
/// - **No 3D framework.** SceneKit, RealityKit and Metal would all be weight
///   in exchange for nothing to render. When a representation exists — point
///   cloud, sparse landmarks, trajectory, or whatever the Tower chooses — it
///   is added behind `.receiving`/`.finalized` without disturbing anything
///   here. Nothing in this view assumes which one it will be.
/// - **No animated placeholder.** A drifting point cloud would look like
///   progress and be a fabrication.
/// - **No spinner in the unsupported state.** A spinner claims work is
///   underway; nothing is underway.
///
/// ## Availability outranks state
///
/// The `availability` parameter is consulted *before* the domain state. If the
/// Tower cannot serve this cartridge — no contract, a contract this build does
/// not implement, or an unreachable Tower — then no `WorldModelState` is worth
/// drawing, and the shared `CartridgeStatePanel` says which of those three it
/// is. That ordering lives in one place (`CartridgeAvailability.forcedPhase`)
/// so all four cartridges obey it identically.
struct WorldCanvasView: View {
    let state: WorldModelState
    let availability: CartridgeAvailability
    /// Composed by `WorldBuilderViewModel`, not here — so the shared layer owns
    /// the ordering of the two sentences and all four cartridges join them the
    /// same way.
    ///
    /// **This is not a performance fix, and it should not be read as one.** This
    /// view sits under `WorldBuilderWorkspaceView`, which observes
    /// `GlassesConnection` because it draws the viewfinder, so that body runs at
    /// the 24 Hz capture rate during a session — and it evaluates this argument
    /// on every one of those. The composition moved up a level; it did not
    /// disappear. Two small string allocations per body, against frame encoding
    /// happening in the same window, is not obviously worth caching, but it is
    /// worth *measuring* on the Mac rather than assuming either way.
    ///
    /// What genuinely was removed is the three other workspaces' invalidation at
    /// the Tower's reply rate — see `TowerReachabilityReader`. That one was a
    /// dead dependency, so removing it cost nothing.
    let explanation: String
    var inspection: WorldInspectionMode = .live

    var body: some View {
        if let forcedPhase = availability.forcedPhase {
            CartridgeStatePanel(
                title: "What the Tower builds",
                phase: forcedPhase,
                explanation: explanation,
                futureDescription: Self.futureDescription
            )
        } else {
            worldPanel
        }
    }

    private static let futureDescription = """
        When the Tower can build worlds, this panel will show the model it is \
        assembling, how well it is tracking, whether its scale is relative or \
        estimated, and how far the camera travelled. None of those exist yet.
        """

    // MARK: The panel for a Tower that can actually answer

    private var worldPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel(inspection.isInspecting ? "Saved world" : "What the Tower builds")

            VStack(alignment: .leading, spacing: 12) {
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 18))
        }
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .unsupported(let reason):
            unsupported(reason)

        case .idle:
            headline("Not started", systemImage: "cube.transparent")
            detailText("Start a capture session to begin building a world.")

        case .awaitingFirstUpdate:
            // The one honest use of a progress indicator: frames really are
            // going out and the Tower really has not answered yet.
            HStack(spacing: 10) {
                ProgressView()
                Text("Waiting for the Tower's first world update…")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

        case .receiving(let snapshot):
            headline(snapshot.name ?? "Building", systemImage: "cube")
            WorldSummaryView(snapshot: snapshot, isLive: true)

        case .finalizing(let snapshot):
            // Progress is honest here — the Tower is genuinely working — but
            // the badge must not say "live", because no new observations are
            // arriving and the camera may already be off.
            HStack(spacing: 10) {
                ProgressView()
                Text(snapshot.name.map { "Finishing \($0)…" } ?? "Finishing the world…")
                    .font(.headline)
            }
            WorldSummaryView(snapshot: snapshot, isLive: false)
            detailText("Capture has ended. The Tower is still working, so these figures may still change.")

        case .finalized(let snapshot):
            headline(snapshot.name ?? "World", systemImage: "cube.fill")
            WorldSummaryView(snapshot: snapshot, isLive: false)

        case .failed(let failure):
            headline("World building failed", systemImage: "exclamationmark.triangle.fill")
            detailText(failure.message)
        }
    }

    /// The state that is actually reachable today.
    @ViewBuilder
    private func unsupported(_ reason: String) -> some View {
        headline("Nothing yet", systemImage: "cube.transparent")
        detailText(reason)
        // One sentence instead of a grid of empty metric tiles. It teaches the
        // product concept and creates no dead UI to explain away later.
        Text(Self.futureDescription)
            .font(.footnote)
            .foregroundStyle(.tertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func headline(_ text: String, systemImage: String) -> some View {
        Label(text, systemImage: systemImage)
            .font(.headline)
    }

    /// Named `detailText` rather than `body` on purpose: a method sharing the
    /// base name of the `View` protocol's own `body` requirement is legal but
    /// invites confusion at exactly the place a reader is looking for the real
    /// one.
    private func detailText(_ text: String) -> some View {
        Text(text)
            .font(.subheadline)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// Renders only the fields the Tower actually reported.
///
/// Every value is optional and an absent one is simply not drawn, rather than
/// drawn as "—". That is the difference between a panel that is early and a
/// panel that looks broken.
///
/// Unreachable today — no client produces a snapshot — but written now so the
/// display rule below lands with the data rather than after it.
struct WorldSummaryView: View {
    let snapshot: WorldSnapshot
    let isLive: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let keyframes = snapshot.keyframeCount {
                row("Keyframes", "\(keyframes)")
            }
            if snapshot.tracking != .unavailable {
                row("Tracking", snapshot.tracking.displayName)
            }
            if snapshot.calibration != .unknown {
                row("Calibration", snapshot.calibration.displayName)
            }
            if snapshot.scale != .unknown {
                row("Scale", snapshot.scale.displayName)
                // The monocular-depth rule from docs/modules/WORLD-BUILD.md,
                // enforced at the point of display: an inferred figure is never
                // shown without saying it is an estimate.
                if snapshot.scale.isEstimate {
                    caption(snapshot.scale.explanation)
                }
            }

            geometryRows
            trajectoryRows

            if snapshot.persistence != .unknown {
                row("Storage", snapshot.persistence.displayName)
            }

            if !isLive {
                Text("Capture has ended.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// The Tower's representation, quoted rather than interpreted.
    ///
    /// The count is never shown on its own. "18,432" beside the word
    /// "Geometry" invites a reader to supply their own unit — points, faces,
    /// landmarks — and the Tower has not said which. Shown next to the label it
    /// chose, the number means whatever that label means, which is the only
    /// true reading available.
    @ViewBuilder
    private var geometryRows: some View {
        if snapshot.geometry.hasReport {
            row("Geometry", geometryValue)
            caption("This build cannot draw the Tower's world representation yet.")
        }
    }

    /// Composed outside the `@ViewBuilder` above rather than with a local `let`
    /// inside it — the pattern this codebase settled on after a result-builder
    /// block with a binding in it caused trouble in Product Shell V2.
    private var geometryValue: String {
        let name = snapshot.geometry.representation ?? "Unnamed representation"
        guard let count = snapshot.geometry.elementCount else { return name }
        return "\(count) · \(name)"
    }

    /// Path length is shown only where the scale permits it to mean a distance.
    @ViewBuilder
    private var trajectoryRows: some View {
        if let poses = snapshot.trajectory.poseCount {
            row("Camera poses", "\(poses)")
        }
        if snapshot.trajectory.distanceDisplayable, let length = snapshot.trajectory.pathLength {
            // The Tower's unit, or none. See `ReportedFigure`.
            row("Path length", ReportedFigure.format(length, unit: snapshot.trajectory.pathLengthUnit))
            if snapshot.trajectory.scale.isEstimate {
                caption(snapshot.trajectory.scale.explanation)
            }
        }
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.tertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Spacer(minLength: 12)
            Text(value)
                .font(.subheadline.weight(.medium))
                .monospacedDigit()
        }
        .accessibilityElement(children: .combine)
    }
}

#Preview("Unsupported") {
    WorldCanvasView(
        state: .unsupported(reason: UnavailableWorldBuilderClient.reason),
        availability: .noContract,
        explanation: UnavailableWorldBuilderClient.reason
    )
    .padding()
}
