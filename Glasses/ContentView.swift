//
//  ContentView.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import SwiftUI

/// Root view, owner of the app's object graph, and the persistent shell.
///
/// ## The ownership invariant
///
/// `project` stays a `@StateObject` here, on a view that is always in the
/// hierarchy, and deliberately not on `GlassesApp`. A stored property on the
/// `App` struct would be initialised before `GlassesApp.init()` runs
/// `Wearables.configure()`, so `GlassesConnection` would touch the DAT SDK
/// before it is configured.
///
/// Everything else — the cartridge tray, the connection sheet, the developer
/// tools, and now the workspace — is presented *over* or *inside* this view
/// rather than replacing it, so the graph is never torn down.
/// `GlassesConnection.deinit` stops the camera and the device session, which
/// would kill a live stream. `GlassesConnection.init` logs
/// `[Glasses][Init] GlassesConnection created`, and that line must appear
/// exactly once per launch.
///
/// The rule that keeps it true, in one sentence: **`project` is created in
/// exactly one place; every other view receives its *children*; no view below
/// this one ever constructs anything that talks to DAT or the socket.**
///
/// Three things would break it:
/// - moving `project` to `@State` (which constructs eagerly on every `body`
///   re-evaluation, discarding all but the first — each discarded instance
///   having already spawned DAT tasks and then run its `deinit`);
/// - applying `.id(...)` at or above this view;
/// - a second scene. `TARGETED_DEVICE_FAMILY` includes iPad and visionOS, and
///   the app does not disable multiple scenes, so a second window would mean a
///   second `ContentView` identity and therefore a second `GlassesConnection`
///   and Tower socket against one set of glasses. "Once per launch" is really
///   "once per scene" — see the handoff for the build-setting fix, which needs
///   a real build to verify.
///
/// Switching workspaces does neither. The switch happens *below* `project`, so
/// a cartridge change swaps a subtree while the runtime graph — and any live
/// camera session — continues untouched.
struct ContentView: View {
    @StateObject private var project = ProjectManager()

    /// The cartridge whose workspace is open, by id. Empty means Home.
    ///
    /// `@State` on the root view, which is never re-identified, so it survives
    /// every sheet presentation, workspace switch and body re-evaluation —
    /// which is what "persists across ordinary UI navigation" requires.
    ///
    /// Deliberately *not* `@AppStorage`/`@SceneStorage`: restoring a workspace
    /// across process launches would restore a screen for a module the Tower
    /// still cannot run, and it would make "was something running?" ambiguous
    /// at launch. Revisit when a cartridge can actually load on the Tower and
    /// report that it is running.
    @State private var selectedCartridgeID = ""

    /// One sheet state rather than several `isPresented` booleans. Stacking
    /// `.sheet(isPresented:)` modifiers on the same view is unreliable — only
    /// one of them presents.
    private enum Destination: Int, Identifiable {
        case cartridges
        case connections
        #if DEBUG
        case developer
        #endif

        var id: Int { rawValue }
    }

    @State private var destination: Destination?

    /// The single source of truth for which workspace is showing. An id that is
    /// not in the catalog, or that this build has no workspace for, falls back
    /// to Home rather than showing an empty screen.
    private var selectedCartridge: Cartridge? {
        Cartridge.workspaceCartridge(forID: selectedCartridgeID)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    ShellStatusBar(
                        glasses: project.glassesConnection,
                        tower: project.towerClient,
                        onTap: { destination = .connections }
                    )

                    workspace
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
            }
            .background(Color(.systemGroupedBackground))
            .scrollBounceBehavior(.basedOnSize)
            .navigationTitle(selectedCartridge?.name ?? "Glasses")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbar }
            .sheet(item: $destination) { destination in
                sheet(for: destination)
            }
            .modifier(GlassesErrorAlert(glasses: project.glassesConnection))
        }
        // The app's only automatic side effect, in the one place it belongs.
        // `startAutomaticConnections()` is itself idempotent, so a re-run of
        // this task cannot connect twice. It reads camera permission and opens
        // the Tower socket; it does not and cannot start the camera.
        .task {
            project.startAutomaticConnections()
        }
    }

    // MARK: Workspace

    /// The only place a cartridge decides what is on screen.
    ///
    /// A `switch` rather than a workspace protocol or registry: the set of
    /// workspaces is closed and compiled in, so an enum is what fits, and
    /// exhaustiveness checking then *forces* a new case to be handled instead
    /// of silently falling back to Home. The pattern the roadmap warns against
    /// is per-cartridge conditionals scattered through one enormous view; the
    /// cure for that is separate view files, which is what these are.
    ///
    /// Adding a workspace is: one `CartridgeWorkspace` case, one `workspace:`
    /// on a catalog entry, one arm here, one file. No existing workspace is
    /// touched.
    ///
    /// Note there is no `.id(...)` here. The switch already gives each branch
    /// its own structural identity, and an explicit id would be one edit away
    /// from being attached to something above `project`.
    @ViewBuilder
    private var workspace: some View {
        if let workspace = selectedCartridge?.workspace {
            // Switching over the unwrapped value rather than the optional keeps
            // the exhaustiveness check that forces a new case to be handled,
            // without relying on how enum-case patterns match an Optional.
            switch workspace {
            case .worldBuilder:
                WorldBuilderWorkspaceView(
                    glasses: project.glassesConnection,
                    tower: project.towerClient,
                    client: project.cartridgeClients.worldBuilder
                )
            // The three workspaces below receive neither `glasses` nor `tower`,
            // and both omissions are load-bearing rather than incidental.
            //
            // **No `glasses`.** World Builder shows the live viewfinder and
            // owns one of the app's two capture buttons, so it needs the
            // connection. These three show what the Tower knows; none has a
            // session control, and none is handed the object that could start
            // one. The set of places that can reach `startCameraSession()` is
            // therefore still exactly two, and it stayed two while the number
            // of screens went from two to five.
            //
            // **No `tower`.** They need one fact from it — is it reachable —
            // and observing a `TowerClient` to read that would invalidate the
            // subtree at the Tower's ~12 Hz reply rate, on the main actor, for
            // a value that changes almost never. `TowerReachabilityReader` is
            // the smallest thing that has to observe, and it passes the fact
            // down. See its doc comment.
            //
            // The client comes from `project.cartridgeClients` so it outlives
            // the workspace's `@StateObject`, which a cartridge switch
            // destroys.
            case .experimentalCV:
                TowerReachabilityReader(tower: project.towerClient) { isTowerReachable in
                    ExperimentalCVWorkspaceView(
                        isTowerReachable: isTowerReachable,
                        client: project.cartridgeClients.experimentalCV
                    )
                }
            case .documentMemory:
                TowerReachabilityReader(tower: project.towerClient) { isTowerReachable in
                    DocumentMemoryWorkspaceView(
                        isTowerReachable: isTowerReachable,
                        client: project.cartridgeClients.documentMemory
                    )
                }
            case .sceneUnderstanding:
                TowerReachabilityReader(tower: project.towerClient) { isTowerReachable in
                    SceneUnderstandingWorkspaceView(
                        isTowerReachable: isTowerReachable,
                        client: project.cartridgeClients.sceneUnderstanding
                    )
                }
            }
        } else {
            HomeWorkspaceView(
                glasses: project.glassesConnection,
                tower: project.towerClient,
                senderMetrics: project.senderMetrics,
                onOpenConnections: { destination = .connections }
            )
        }
    }

    // MARK: Chrome

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button {
                destination = .cartridges
            } label: {
                Label("Cartridges", systemImage: "square.grid.2x2")
            }
            .accessibilityLabel("Cartridges")
        }

        #if DEBUG
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                destination = .developer
            } label: {
                Label("Developer", systemImage: "wrench.and.screwdriver")
            }
            .accessibilityLabel("Developer tools")
        }
        #endif
    }

    @ViewBuilder
    private func sheet(for destination: Destination) -> some View {
        switch destination {
        case .cartridges:
            CartridgeDrawerView(selectedCartridgeID: $selectedCartridgeID)
                .presentationDetents([.medium, .large])
        case .connections:
            ConnectionSheet(
                glasses: project.glassesConnection,
                tower: project.towerClient
            )
            .presentationDetents([.medium, .large])
        #if DEBUG
        case .developer:
            DeveloperToolsView(
                glasses: project.glassesConnection,
                tower: project.towerClient,
                stream: project.streamManager,
                senderMetrics: project.senderMetrics,
                health: project.deviceHealth
            )
        #endif
        }
    }
}

/// Presents `GlassesConnection.errorMessage` as an alert.
///
/// A modifier owning its own `@ObservedObject` rather than an `.alert` on the
/// root view, because the root no longer re-renders when a child changes:
/// `ProjectManager`'s `objectWillChange` fan-in was removed so the shell would
/// stop re-evaluating at the capture rate. The alert has to observe the object
/// it reads, and this is the smallest thing that does.
private struct GlassesErrorAlert: ViewModifier {
    @ObservedObject var glasses: GlassesConnection

    func body(content: Content) -> some View {
        content.alert(
            "Something went wrong",
            isPresented: Binding(
                get: { glasses.errorMessage != nil },
                set: { isPresented in
                    if !isPresented { glasses.errorMessage = nil }
                }
            )
        ) {
            Button("OK") { glasses.errorMessage = nil }
        } message: {
            Text(glasses.errorMessage ?? "")
        }
    }
}
