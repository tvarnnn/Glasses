//
//  WorldCanvasView.swift
//  Glasses
//

import SwiftUI

/// The world-visualization container: the place a spatial model will eventually
/// be drawn, and today the place the app explains that there is not one.
///
/// It renders `WorldModelState` and nothing else, so it cannot show geometry
/// the Tower did not send. Today the only reachable state is `.unsupported`,
/// because `UnavailableWorldModelSource` is the only source that exists.
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
struct WorldCanvasView: View {
    let state: WorldModelState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("What the Tower builds")

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

        case .finalized(let snapshot):
            headline(snapshot.name ?? "World", systemImage: "cube.fill")
            WorldSummaryView(snapshot: snapshot, isLive: false)

        case .failed(let reason):
            headline("World building failed", systemImage: "exclamationmark.triangle.fill")
            detailText(reason)
        }
    }

    /// The state that is actually reachable today.
    @ViewBuilder
    private func unsupported(_ reason: String) -> some View {
        headline("Nothing yet", systemImage: "cube.transparent")
        detailText(reason)
        // One sentence instead of a grid of empty metric tiles. It teaches the
        // product concept and creates no dead UI to explain away later.
        Text("When the Tower can build worlds, this panel will show the model it is assembling, how well it is tracking, and whether its scale is relative or estimated. None of those exist yet.")
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
/// Unreachable today — no source produces a snapshot — but written now so the
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
            if snapshot.scale != .unknown {
                row("Scale", snapshot.scale.displayName)
                // The monocular-depth rule from docs/modules/WORLD-BUILD.md,
                // enforced at the point of display: an inferred figure is never
                // shown without saying it is an estimate.
                if snapshot.scale.isEstimate {
                    Text(snapshot.scale.explanation)
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if !isLive {
                Text("Capture has ended. This world is final.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func row(_ caption: String, _ value: String) -> some View {
        HStack {
            Text(caption)
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
    WorldCanvasView(state: .unsupported(reason: UnavailableWorldModelSource.reason))
        .padding()
}
