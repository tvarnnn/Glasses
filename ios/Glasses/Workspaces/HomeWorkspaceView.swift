//
//  HomeWorkspaceView.swift
//  Glasses
//

import MWDATCore
import SwiftUI

// `MWDATCamera` is imported for `StreamState`'s cases specifically. The target
// builds with `SWIFT_UPCOMING_FEATURE_MEMBER_IMPORT_VISIBILITY`, under which a
// type's members are only visible where the defining module is imported — so
// `== .streaming` does not resolve through `GlassesConnection` alone. Gated to
// match the property it reads.
#if DEBUG
import MWDATCamera
#endif

/// The workspace shown when no cartridge is loaded.
///
/// Replaces the old dashboard. The difference is what it does when everything
/// is fine: the dashboard showed a three-row setup checklist permanently, so a
/// fully working system looked like unfinished configuration. This shows one
/// sentence about what the system can do, one primary action, and — only while
/// a session is actually running — the handful of numbers that are genuinely
/// measured.
///
/// It observes `glasses`, `tower` and `senderMetrics` directly. Nothing in the
/// app observes `ProjectManager`, and nothing should: it owns objects that
/// change at the 24 Hz capture rate, and a view that re-rendered with them
/// would spend main-actor time the sender needs — send-window slots are
/// released on that actor, and the achievable rate is capacity divided by how
/// long a slot is held.
struct HomeWorkspaceView: View {
    @ObservedObject var glasses: GlassesConnection
    @ObservedObject var tower: TowerClient
    /// Publishes at 2 Hz regardless of frame rate, so reading it does not tie
    /// this view's refresh rate to the send rate.
    @ObservedObject var senderMetrics: SenderMetrics
    let onOpenConnections: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            if let banner = failureBanner {
                FailureBanner(
                    text: banner,
                    actionTitle: "Connections",
                    action: onOpenConnections
                )
            }

            readiness

            #if DEBUG
            if glasses.cameraStreamState == .streaming || glasses.frameCount > 0 {
                ViewfinderCard(
                    frame: glasses.latestCapturedFrame,
                    isStreaming: glasses.cameraStreamState == .streaming,
                    placeholderReason: viewfinderPlaceholder
                )
                liveNumbers
            }
            sessionControl
            #else
            // Mirrors the World Builder workspace. The whole session surface is
            // DEBUG-only, so a Release build must not imply a control it does
            // not have.
            HelperText("Capture is not available in this build.")
            #endif
        }
    }

    // MARK: Readiness

    /// One card: what the system is, and what is blocking it if anything.
    ///
    /// Only ever names a *single* blocking step, in dependency order. Listing
    /// every unmet prerequisite at once is how a product surface turns back
    /// into a checklist.
    private var readiness: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(headline)
                .font(.title3.weight(.semibold))

            Text(detail)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if let blocker {
                Button(blocker.actionTitle, action: blocker.action)
                    .font(.subheadline.weight(.medium))
                    .buttonStyle(.bordered)
                    .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 16))
        .accessibilityElement(children: .contain)
    }

    private var headline: String {
        if blocker != nil { return "Not ready" }
        return "Ready"
    }

    /// Describes the system truthfully in both directions: what is connected,
    /// and — crucially — what the Tower will and will not do with the frames.
    /// Saying it here, once, is what makes it unnecessary for any workspace to
    /// carry a dead "coming soon" panel to make the same point.
    private var detail: String {
        if let blocker { return blocker.reason }
        return """
            Glasses and Tower are connected. The camera is off until you start a session.

            While a session runs, frames stream to the Tower at a \
            \(Int(FrameRateGate.towerTargetFPS)) fps target — the rate actually \
            reached is in the session numbers. The Tower returns a measurement \
            for each frame, which is the running module's own result.
            """
    }

    /// The one thing standing in the way, or `nil` when nothing is.
    private var blocker: Blocker? {
        switch glasses.registrationState {
        case .registered:
            break
        case .unavailable:
            return Blocker(
                reason: "Meta AI is unavailable on this device, so the glasses cannot be reached.",
                actionTitle: "Open connections",
                action: onOpenConnections
            )
        default:
            return Blocker(
                reason: "The glasses are not registered with Meta AI yet.",
                actionTitle: "Register",
                action: { glasses.connect() }
            )
        }

        if tower.status != .online {
            return Blocker(
                reason: "The Tower is not connected, so frames from a session would not reach it.",
                actionTitle: "Open connections",
                action: onOpenConnections
            )
        }
        return nil
    }

    private struct Blocker {
        let reason: String
        let actionTitle: String
        let action: () -> Void
    }

    /// The Tower's failure detail, which is otherwise easy to miss. Glasses
    /// errors still surface through the root alert.
    private var failureBanner: String? {
        StateDisplay.towerFailureDetail(tower.status).map { "Tower: \($0)" }
    }
}

// MARK: - DEBUG-only session surface

// The camera path — `startCameraSession`, `latestCapturedFrame`,
// `cameraStreamState`, `frameCount` — is DEBUG-only in the model, so every
// control that touches it is gated to match. In a Release build this workspace
// is the readiness card alone.
#if DEBUG
private extension HomeWorkspaceView {

    var canStart: Bool { glasses.hasActiveDevice }

    var isStopping: Bool { glasses.cameraStreamState == .stopping }

    /// Includes the device-session states, not just the stream's. See
    /// `GlassesConnection.isCaptureEngaged` — deriving this from the stream
    /// alone left a window in which a session existed but the control still
    /// read "Start", and a tap in it did nothing observable.
    var isRunning: Bool { glasses.isCaptureEngaged }

    @ViewBuilder
    var sessionControl: some View {
        VStack(spacing: 10) {
            if isRunning {
                Button {
                    glasses.stopCameraSession()
                } label: {
                    Label("Stop session", systemImage: "stop.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                }
                .buttonStyle(.bordered)
                .disabled(isStopping)
            } else {
                Button {
                    glasses.startCameraSession()
                } label: {
                    Label("Start session", systemImage: "play.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canStart)
            }

            if !canStart && !isRunning {
                HelperText("Waiting for the glasses to become active.")
            } else if glasses.cameraPermissionStatus == .denied && !isRunning {
                // Stated rather than enforced with `.disabled`. A start that
                // is refused now reports why and leaves the session clean, so
                // an out-of-date reading here costs a tap and an explanation
                // — where gating the control on it would silently withhold
                // the button, which is the failure this task exists to fix.
                HelperText("Camera access is not granted. Allow it under Connections, then start a session.")
            }
        }
    }

    /// Only values the pipeline actually measured. Rendered while a session is
    /// live or has just ended, never as an idle grid of zeroes.
    var liveNumbers: some View {
        // Plain `return` rather than `@ViewBuilder`, matching
        // `DeveloperToolsView.senderSection`: the snapshot is read once into a
        // local so every tile below is drawn from the same instant, and a
        // result builder is not the place to lean on local declarations.
        let snapshot = senderMetrics.snapshot
        return LazyVGrid(
            columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)],
            spacing: 10
        ) {
            MetricTile(caption: "Frames from glasses", value: glasses.frameCount.formatted())
            MetricTile(
                caption: "Sent to Tower",
                value: Self.fps(snapshot.successfulSendFPS),
                footnote: "frames per second"
            )
            MetricTile(
                caption: "Tower replies",
                value: snapshot.frameResults.formatted(),
                footnote: "frames processed"
            )
            // The Tower's own reading of the most recent frame. The only thing
            // it currently reports about a frame's *content*, and real.
            if let intensity = tower.latestFrameResult?.meanIntensity {
                MetricTile(
                    caption: "Mean intensity",
                    value: String(format: "%.2f", intensity),
                    footnote: "latest Tower reply"
                )
            }
        }
    }

    /// A `nil` rate means "not measurable yet", not "zero", so it must not
    /// render as 0.0 — see `SenderMetricsSnapshot.rate`.
    static func fps(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%.1f", value)
    }

    var viewfinderPlaceholder: String {
        if !glasses.hasActiveDevice {
            return "Waiting for the glasses to become active."
        }
        if glasses.cameraPermissionStatus != .granted {
            return "Camera access is needed before a session can stream."
        }
        return "Start a session to see what the glasses see."
    }
}
#endif
