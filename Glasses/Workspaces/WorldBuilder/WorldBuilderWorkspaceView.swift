//
//  WorldBuilderWorkspaceView.swift
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

/// The World Builder workspace: what the glasses see, and what the Tower builds
/// from it.
///
/// ## What this screen may and may not claim
///
/// Those two halves are in completely different states, and the whole design of
/// this view follows from saying so plainly.
///
/// **The capture half is real.** The iPhone can start the glasses camera, and
/// frames genuinely reach the Tower — that is the V0.7 pipeline, measured and
/// working.
///
/// **The world half does not exist.** The Tower runs one fixed frame handler.
/// It has no module container (V0.8) and no module (V0.9), so it cannot build a
/// spatial model of anything. Opening this workspace is local navigation on the
/// phone; it sends nothing to the Tower and selects nothing there.
///
/// Three consequences, each of which is a deliberate refusal:
///
/// - **No "Start Mapping" button.** A verb-labelled primary button is the
///   strongest readiness claim a UI can make, and mapping will not happen. The
///   control says what it does — it starts a capture session — and the world
///   panel says what does not happen. When the Tower can map, the label
///   changes, and its arrival is the announcement.
/// - **No placeholder metrics.** Keyframes, tracking quality and scale all
///   render as "—" today, and six redacted values read as *broken* rather than
///   as *early*. The one line of prose in the world panel carries the same
///   information without pretending there are numbers behind it.
/// - **No fabricated geometry.** No point cloud, no mesh, no spinner. A spinner
///   in particular would claim something is in progress when nothing is.
///
/// The live preview presents `GlassesConnection.latestCapturedFrame` through
/// the same `ViewfinderCard` the Home workspace uses. It does not open a second
/// camera session; there is exactly one stream and one owner.
struct WorldBuilderWorkspaceView: View {
    @ObservedObject var glasses: GlassesConnection
    @ObservedObject var tower: TowerClient

    /// The world-model boundary. `UnavailableWorldBuilderClient` is the only
    /// implementation that exists, and it reports exactly one thing: the Tower
    /// cannot do this yet.
    ///
    /// A `@StateObject` so it is constructed once per workspace installation
    /// rather than on every render. It holds no runtime resources — no camera,
    /// no socket, no DAT reference — so losing it when the cartridge is
    /// deselected loses nothing real. Anything that must outlive the workspace
    /// belongs on `ProjectManager`, not here.
    @StateObject private var world: WorldBuilderViewModel

    /// The client is injected rather than constructed here, and owned by
    /// `ProjectManager`. See `CartridgeClients` for why: this `@StateObject` is
    /// destroyed on every cartridge switch, and a Tower-backed client holding a
    /// subscription and a partly-built world must not be.
    init(glasses: GlassesConnection, tower: TowerClient, client: any WorldBuilderClient) {
        self.glasses = glasses
        self.tower = tower
        _world = StateObject(wrappedValue: WorldBuilderViewModel(client: client))
    }

    /// Connectivity reaches the view model as a value, never as an object.
    ///
    /// This view genuinely needs `tower`: the capture control warns when the
    /// Tower is offline, because a `stream_start` sent while it is down is
    /// dropped and every frame after it is then suppressed for the whole
    /// session. So the observation is not a dead dependency here, and reading
    /// the status costs nothing extra — passing the *fact* rather than the
    /// client is what keeps the view model free of a reference it could act on.
    ///
    /// The three cartridge workspaces that have no capture control receive this
    /// `Bool` from `TowerReachabilityReader` instead, and do not observe the
    /// connection at all.
    private var isTowerReachable: Bool { tower.status == .online }

    var body: some View {
        VStack(spacing: 16) {
            header

            #if DEBUG
            glassesPanel
            #endif

            WorldCanvasView(
                state: world.state,
                availability: world.availability(isTowerReachable: isTowerReachable),
                explanation: world.unavailableExplanation(isTowerReachable: isTowerReachable),
                inspection: world.inspection
            )

            #if DEBUG
            captureControl
            #else
            HelperText("Capture is not available in this build.")
            #endif
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("World Builder")
                .font(.title2.weight(.semibold))
            Text("The workspace this module will use. The Tower cannot build a world yet, so nothing here is a map.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

// MARK: - DEBUG-only capture surface

// The camera path is DEBUG-only in the model, so the capture half of this
// workspace is gated to match. In Release the workspace still exists and still
// tells the truth about the world half — it simply has no capture controls,
// exactly as no other screen in the app does.
#if DEBUG
private extension WorldBuilderWorkspaceView {

    var isStreaming: Bool { glasses.cameraStreamState == .streaming }

    var isRunning: Bool {
        switch glasses.cameraStreamState {
        case .streaming, .starting, .waitingForDevice: return true
        default: return false
        }
    }

    /// What the wearer currently sees.
    @ViewBuilder
    var glassesPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("What the glasses see")
            ViewfinderCard(
                frame: glasses.latestCapturedFrame,
                isStreaming: isStreaming,
                placeholderReason: placeholder
            )
        }
    }

    var placeholder: String {
        if !glasses.hasActiveDevice { return "Waiting for the glasses to become active." }
        if glasses.cameraPermissionStatus != .granted {
            return "Camera access is needed before a session can stream."
        }
        return "Start a capture session to see what the glasses see."
    }

    /// Labelled for what it actually does. See the type's doc comment for why
    /// this is not "Start Mapping".
    @ViewBuilder
    var captureControl: some View {
        VStack(spacing: 8) {
            if isRunning {
                Button {
                    glasses.stopCameraSession()
                } label: {
                    Label("Stop capture", systemImage: "stop.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                }
                .buttonStyle(.bordered)
                .disabled(glasses.cameraStreamState == .stopping)
            } else {
                Button {
                    glasses.startCameraSession()
                } label: {
                    Label("Start capture", systemImage: "play.fill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!glasses.hasActiveDevice)
            }

            HelperText(
                isRunning
                    ? "Frames are streaming to the Tower. No world is being built."
                    : "Streams frames to the Tower. No world is built."
            )

            if !glasses.hasActiveDevice && !isRunning {
                HelperText("Waiting for the glasses to become active.")
            } else if tower.status != .online {
                // The Tower must be online *before* capture starts: a
                // `stream_start` sent while it is offline is dropped, and every
                // frame after it is then suppressed for the whole session.
                // Advice rather than a new `.disabled` condition, so the
                // control's semantics stay what they were.
                HelperText("The Tower is not connected. Frames from this session would not reach it.")
            }
        }
    }
}
#endif
