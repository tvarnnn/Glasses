//
//  DeveloperToolsView.swift
//  Glasses
//

// Entire file is DEBUG-only. Everything it touches — the Mock Device Kit
// controls, the raw session state, and the Tower counters — is already gated
// that way in the model, so gating the whole file keeps every control on one
// side of the conditional boundary.
#if DEBUG

import SwiftUI

/// Developer surface for the plumbing the product screen deliberately hides.
///
/// The Mock Device Kit controls live here now that the physical glasses work.
/// They are unchanged in behaviour and call exactly the same methods in the
/// same order as before; they are simply no longer part of the primary
/// experience. Mock support remains fully available for development and for
/// working without hardware.
struct DeveloperToolsView: View {
    @ObservedObject var glasses: GlassesConnection
    @ObservedObject var tower: TowerClient
    @ObservedObject var stream: StreamManager

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                mockDeviceSection
                rawStateSection
                towerSection
                placeholderSection
            }
            .navigationTitle("Developer")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            // The root view's alert cannot present while this sheet is up, and
            // the mock controls are the main producers of `errorMessage`
            // ("Pair a mock device first", pairing failures). Without a local
            // alert those errors would be invisible until dismissal — on the
            // one surface built for diagnostics.
            .alert(
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

    // MARK: Mock Device Kit

    private var mockDeviceSection: some View {
        Section {
            Button(glasses.mockDeviceKitEnabled ? "Disable Mock Device Kit" : "Enable Mock Device Kit") {
                glasses.toggleMockDeviceKit()
            }
            Button("Pair Mock Glasses") {
                glasses.pairMockGlasses()
            }
            Button("Configure Mock Camera Feed") {
                glasses.configureMockCameraFeed()
            }
            LabeledContent("Mock Device Paired", value: glasses.isMockDevicePaired ? "Yes" : "No")
        } header: {
            Text("Mock Device Kit")
        } footer: {
            Text("Simulates Ray-Ban Meta glasses using this iPhone's camera. Enable, pair, then configure the feed — in that order — before starting a session.")
        }
    }

    // MARK: Raw state

    private var rawStateSection: some View {
        Section {
            LabeledContent("Registration", value: "\(glasses.registrationState)")
            LabeledContent("Devices", value: "\(glasses.devices.count)")
            LabeledContent("Camera Permission", value: glasses.cameraPermissionStatus.map { "\($0)" } ?? "nil")
            LabeledContent("Active Device", value: glasses.hasActiveDevice ? "Yes" : "No")
            LabeledContent("Device Session", value: "\(glasses.deviceSessionState)")
            LabeledContent("Camera Stream", value: "\(glasses.cameraStreamState)")
            LabeledContent("Frames Received", value: "\(glasses.frameCount)")

            Button("Check Camera Permission") {
                glasses.checkCameraPermission()
            }
        } header: {
            Text("Raw State")
        } footer: {
            Text("Unformatted enum values, as reported by DAT.")
        }
    }

    // MARK: Tower

    private var towerSection: some View {
        Section {
            LabeledContent("Endpoint") {
                Text(TowerConfiguration.webSocketURL.absoluteString)
                    .font(.footnote.monospaced())
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.trailing)
            }
            LabeledContent("Status", value: "\(tower.status)")
            LabeledContent("Streaming To Tower", value: tower.isStreamingToTower ? "Yes" : "No")
            LabeledContent("Frame Results", value: "\(tower.frameResultCount)")
        } header: {
            Text("Tower")
        } footer: {
            Text("The endpoint is compiled in and read-only. A configurable endpoint is a separate task.")
        }
    }

    // MARK: Placeholders

    private var placeholderSection: some View {
        Section {
            LabeledContent("State", value: "\(stream.state)")
            LabeledContent("Metrics", value: stream.metrics.map { "\($0)" } ?? "nil")
        } header: {
            Text("StreamManager")
        } footer: {
            Text("Placeholder type. Never assigned, so these never change. The real streaming state is Camera Stream above. Kept here rather than on the dashboard, where it contradicted the live frame counter.")
        }
    }
}

#endif
