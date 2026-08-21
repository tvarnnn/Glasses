//
//  ContentView.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import SwiftUI

struct ContentView: View {
    @StateObject private var project = ProjectManager()

    var body: some View {
        NavigationStack {
            List {
                Section("Glasses") {
                    StatusRow(
                        label: "Registration",
                        value: "\(project.glassesConnection.registrationState)"
                    )
                    StatusRow(
                        label: "Devices",
                        value: "\(project.glassesConnection.devices.count)"
                    )
                    StatusRow(
                        label: "Camera Permission",
                        value: project.glassesConnection.cameraPermissionStatus.map { "\($0)" } ?? "Unknown"
                    )

                    Button("Connect") {
                        project.glassesConnection.connect()
                    }
                    Button("Disconnect") {
                        project.glassesConnection.disconnect()
                    }
                    Button("Check Camera Permission") {
                        project.glassesConnection.checkCameraPermission()
                    }
                    Button("Request Camera Permission") {
                        project.glassesConnection.requestCameraPermission()
                    }

                    #if DEBUG
                    Button(
                        project.glassesConnection.mockDeviceKitEnabled
                            ? "Disable Mock Device Kit"
                            : "Enable Mock Device Kit"
                    ) {
                        project.glassesConnection.toggleMockDeviceKit()
                    }
                    Button("Pair Mock Glasses") {
                        project.glassesConnection.pairMockGlasses()
                    }
                    StatusRow(
                        label: "Mock Device Paired",
                        value: project.glassesConnection.isMockDevicePaired ? "Yes" : "No"
                    )

                    Button("Configure Mock Camera Feed") {
                        project.glassesConnection.configureMockCameraFeed()
                    }
                    StatusRow(
                        label: "Active Device",
                        value: project.glassesConnection.hasActiveDevice ? "Yes" : "No"
                    )
                    Button("Start Camera Session") {
                        project.glassesConnection.startCameraSession()
                    }
                    .disabled(!project.glassesConnection.hasActiveDevice)
                    Button("Stop Camera Session") {
                        project.glassesConnection.stopCameraSession()
                    }
                    StatusRow(
                        label: "Device Session",
                        value: "\(project.glassesConnection.deviceSessionState)"
                    )
                    StatusRow(
                        label: "Camera Stream",
                        value: "\(project.glassesConnection.cameraStreamState)"
                    )
                    StatusRow(
                        label: "Frames Received",
                        value: "\(project.glassesConnection.frameCount)"
                    )
                    #endif
                }

                Section("Tower") {
                    StatusRow(
                        label: "Status",
                        value: project.towerClient.status.displayText
                    )
                    Button("Connect Tower") {
                        project.towerClient.connect()
                    }
                    Button("Disconnect Tower") {
                        project.towerClient.disconnect()
                    }
                }

                Section("Stream") {
                    StatusRow(
                        label: "State",
                        value: project.streamManager.state.displayText
                    )
                    StatusRow(
                        label: "Metrics",
                        value: project.streamManager.metrics?.displayText ?? "Unavailable"
                    )
                }
            }
            .navigationTitle("Dashboard")
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

private struct StatusRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
            Spacer()
            Text(value)
                .foregroundStyle(.secondary)
        }
    }
}

private extension TowerStatus {
    var displayText: String {
        switch self {
        case .offline: return "Offline"
        case .connecting: return "Connecting…"
        case .online: return "Online"
        case .failed(let message): return "Error: \(message)"
        }
    }
}

private extension StreamState {
    var displayText: String {
        switch self {
        case .stopped: return "Stopped"
        case .starting: return "Starting…"
        case .streaming: return "Streaming"
        }
    }
}

private extension StreamMetrics {
    var displayText: String {
        "\(framesReceived) frames @ \(String(format: "%.1f", frameRate)) fps"
    }
}

#Preview {
    ContentView()
}
