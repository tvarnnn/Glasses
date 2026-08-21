//
//  SessionView.swift
//  Glasses
//

import MWDATCore
import SwiftUI

#if DEBUG
import MWDATCamera
#endif

/// The product screen: what the glasses see, whether the pipeline is healthy,
/// and the one control that matters.
///
/// Observes `GlassesConnection` and `TowerClient` directly rather than
/// `ProjectManager`. `ProjectManager` has no `@Published` properties of its
/// own and only re-broadcasts its children's `objectWillChange`, so a subview
/// holding a plain `let project` would read live values but never re-render.
struct SessionView: View {
    @ObservedObject var glasses: GlassesConnection
    @ObservedObject var tower: TowerClient

    @State private var isConfirmingUnregister = false

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                if let banner = failureBanner {
                    FailureBanner(text: banner)
                }

                #if DEBUG
                ViewfinderCard(
                    frame: glasses.latestCapturedFrame,
                    isStreaming: glasses.cameraStreamState == .streaming,
                    placeholderReason: viewfinderPlaceholder
                )
                #endif

                pipeline

                #if DEBUG
                sessionControls
                if glasses.frameCount > 0 { metrics }
                #endif

                setup
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 24)
        }
        .background(Color(.systemGroupedBackground))
        .scrollBounceBehavior(.basedOnSize)
    }

    // MARK: Pipeline

    private var pipeline: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("Status")
            HStack(spacing: 10) {
                StatusPill(
                    title: "Glasses",
                    value: StateDisplay.registration(glasses.registrationState),
                    level: glassesLevel
                )
                #if DEBUG
                StatusPill(
                    title: "Camera",
                    value: StateDisplay.cameraStream(glasses.cameraStreamState),
                    level: cameraLevel
                )
                #endif
                StatusPill(
                    title: "Tower",
                    value: StateDisplay.tower(tower.status),
                    level: towerLevel
                )
            }
        }
    }

    private var glassesLevel: StatusLevel {
        switch glasses.registrationState {
        case .registered: return .ok
        case .registering: return .working
        case .unavailable: return .problem
        default: return .idle
        }
    }

    private var towerLevel: StatusLevel {
        switch tower.status {
        case .online: return .ok
        case .connecting: return .working
        case .failed: return .problem
        case .offline: return .idle
        }
    }

    // MARK: Setup

    private var setup: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("Setup")

            // Every row keeps its action reachable in every state. The
            // baseline dashboard's buttons were all unconditionally tappable,
            // so hiding one when a step "looks done" would be new gating on a
            // control the redesign was required to leave alone.
            VStack(spacing: 0) {
                SetupRow(
                    title: "Meta AI",
                    detail: StateDisplay.registration(glasses.registrationState),
                    isComplete: glasses.registrationState == .registered,
                    actionTitle: glasses.registrationState == .registered ? "Re-register" : "Register",
                    action: { glasses.connect() }
                )
                Divider().padding(.leading, 16)

                // `checkCameraPermission()` must stay reachable outside DEBUG:
                // `cameraPermissionStatus` starts nil and nothing populates it
                // automatically, so without this there is no way to observe an
                // already-granted permission without re-requesting it.
                SetupRow(
                    title: "Camera access",
                    detail: StateDisplay.cameraPermission(glasses.cameraPermissionStatus),
                    isComplete: glasses.cameraPermissionStatus == .granted,
                    actionTitle: cameraActionTitle,
                    action: {
                        if glasses.cameraPermissionStatus == .denied {
                            glasses.requestCameraPermission()
                        } else {
                            glasses.checkCameraPermission()
                        }
                    }
                )
                Divider().padding(.leading, 16)

                // Disconnect stays available while `.connecting`, not just
                // while `.online`. `connect()` is a no-op in that state, so
                // without an explicit teardown a hung connect would strand the
                // user until URLSession's own timeout expired.
                SetupRow(
                    title: "Tower",
                    detail: StateDisplay.tower(tower.status),
                    isComplete: tower.status == .online,
                    actionTitle: towerActionTitle,
                    action: {
                        switch tower.status {
                        case .online, .connecting: tower.disconnect()
                        case .offline, .failed: tower.connect()
                        }
                    }
                )
            }
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 14))

            Button("Unregister from Meta AI", role: .destructive) {
                isConfirmingUnregister = true
            }
            .font(.footnote)
            .padding(.top, 4)
            .padding(.horizontal, 4)
            .confirmationDialog(
                "Unregister from Meta AI?",
                isPresented: $isConfirmingUnregister,
                titleVisibility: .visible
            ) {
                Button("Unregister", role: .destructive) { glasses.disconnect() }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("You will have to complete the full pairing flow again before the glasses can be used.")
            }
        }
    }

    private var cameraActionTitle: String {
        switch glasses.cameraPermissionStatus {
        case .none: return "Check"
        case .denied: return "Allow"
        default: return "Re-check"
        }
    }

    private var towerActionTitle: String {
        switch tower.status {
        case .online: return "Disconnect"
        case .connecting: return "Cancel"
        case .offline, .failed: return "Connect"
        }
    }

    // MARK: Failure banner

    /// Glasses errors still use the alert on the root view. This surfaces the
    /// Tower failure detail, which previously appeared only as a truncated
    /// grey status row that was easy to miss.
    private var failureBanner: String? {
        StateDisplay.towerFailureDetail(tower.status).map { "Tower: \($0)" }
    }
}

// MARK: - DEBUG-only session surface

#if DEBUG
private extension SessionView {

    var cameraLevel: StatusLevel {
        switch glasses.cameraStreamState {
        case .streaming: return .ok
        case .starting, .stopping, .waitingForDevice: return .working
        case .paused: return .idle
        case .stopped: return .idle
        @unknown default: return .idle
        }
    }

    var viewfinderPlaceholder: String {
        if !glasses.hasActiveDevice {
            return "Waiting for glasses to become active."
        }
        if glasses.cameraPermissionStatus != .granted {
            return "Camera access is needed before a session can stream."
        }
        return "Start a session to see what the glasses see."
    }

    /// The Tower must be online *before* a session starts: `stream_start` is
    /// dropped while offline, and every frame after it is then suppressed for
    /// the whole session. Surfaced as advice rather than as a new `.disabled`
    /// condition, so the existing control semantics are unchanged.
    var shouldWarnTowerOffline: Bool {
        glasses.hasActiveDevice && tower.status != .online && glasses.frameCount == 0
    }

    @ViewBuilder
    var sessionControls: some View {
        VStack(spacing: 10) {
            Button {
                glasses.startCameraSession()
            } label: {
                Label("Start Session", systemImage: "play.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .disabled(!glasses.hasActiveDevice)

            Button {
                glasses.stopCameraSession()
            } label: {
                Label("Stop", systemImage: "stop.fill")
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 2)
            }
            .buttonStyle(.bordered)

            if !glasses.hasActiveDevice {
                HelperText("Waiting for glasses to become active.")
            } else if shouldWarnTowerOffline {
                HelperText("Connect the Tower first, or this session's frames will not reach it.")
            }
        }
        .padding(.top, 4)
    }

    @ViewBuilder
    var metrics: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("This session")
            LazyVGrid(
                columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)],
                spacing: 10
            ) {
                MetricTile(
                    caption: "Frames from glasses",
                    value: glasses.frameCount.formatted()
                )
                MetricTile(
                    caption: "Tower replies",
                    value: tower.frameResultCount.formatted(),
                    footnote: "frames processed"
                )
                if let frame = glasses.latestCapturedFrame {
                    MetricTile(
                        caption: "Resolution",
                        value: "\(frame.width) × \(frame.height)"
                    )
                    MetricTile(
                        caption: "Latest frame",
                        value: "#\(frame.sequence)"
                    )
                }
            }
        }
    }
}
#endif

// MARK: - Small shared pieces

private struct SectionLabel: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text.uppercased())
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .tracking(0.6)
            .padding(.leading, 4)
    }
}

private struct HelperText: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
    }
}

/// Completion is shown as a leading checkmark rather than by replacing the
/// action, so the underlying call stays reachable in every state.
private struct SetupRow: View {
    let title: String
    let detail: String
    let isComplete: Bool
    let actionTitle: String
    let action: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: isComplete ? "checkmark.circle.fill" : "circle.dashed")
                .foregroundStyle(isComplete ? Color.green : Color.secondary)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 8)

            Button(actionTitle, action: action)
                .font(.subheadline.weight(.medium))
                .buttonStyle(.borderless)
                .accessibilityLabel("\(actionTitle) \(title)")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .accessibilityElement(children: .contain)
        .accessibilityValue(isComplete ? "Done. \(detail)" : detail)
    }
}

private struct FailureBanner: View {
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            Text(text)
                .font(.footnote)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 12))
        .accessibilityElement(children: .combine)
    }
}
