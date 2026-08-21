//
//  ContentView.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import SwiftUI

/// Root view and owner of the app's object graph.
///
/// `project` stays a `@StateObject` here, on a view that is always in the
/// hierarchy, and deliberately not on `GlassesApp`. A stored property on the
/// `App` struct would be initialised before `GlassesApp.init()` runs
/// `Wearables.configure()`, so `GlassesConnection` would touch the DAT SDK
/// before it is configured. Everything else — the cartridge tray, the
/// developer tools — is presented *over* this view rather than replacing it,
/// so the graph is never torn down. `GlassesConnection.deinit` stops the
/// camera and the device session, which would kill a live stream.
struct ContentView: View {
    @StateObject private var project = ProjectManager()

    /// One sheet state rather than two `isPresented` booleans. Stacking two
    /// `.sheet(isPresented:)` modifiers on the same view is unreliable — only
    /// one of them presents.
    private enum Destination: Int, Identifiable {
        case cartridges
        #if DEBUG
        case developer
        #endif

        var id: Int { rawValue }
    }

    @State private var destination: Destination?

    var body: some View {
        NavigationStack {
            SessionView(
                glasses: project.glassesConnection,
                tower: project.towerClient
            )
            .navigationTitle("Glasses")
            .toolbar {
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
            .sheet(item: $destination) { destination in
                switch destination {
                case .cartridges:
                    CartridgeDrawerView()
                        .presentationDetents([.medium, .large])
                #if DEBUG
                case .developer:
                    DeveloperToolsView(
                        glasses: project.glassesConnection,
                        tower: project.towerClient,
                        stream: project.streamManager
                    )
                #endif
                }
            }
            .alert(
                "Something went wrong",
                isPresented: Binding(
                    get: { project.glassesConnection.errorMessage != nil },
                    set: { isPresented in
                        if !isPresented { project.glassesConnection.errorMessage = nil }
                    }
                )
            ) {
                Button("OK") { project.glassesConnection.errorMessage = nil }
            } message: {
                Text(project.glassesConnection.errorMessage ?? "")
            }
        }
    }
}

#Preview {
    ContentView()
}
