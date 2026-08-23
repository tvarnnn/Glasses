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
    @ObservedObject var senderMetrics: SenderMetrics
    @ObservedObject var health: DeviceHealth

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                senderSection
                deviceHealthSection
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

    // MARK: Sender pipeline

    /// One row per place a frame can stop travelling, so a rate below target
    /// can be attributed instead of guessed at. Reads a snapshot republished
    /// at 2 Hz rather than the live counters, so opening this sheet does not
    /// re-diff the `List` at the capture rate.
    private var senderSection: some View {
        let s = senderMetrics.snapshot
        return Section {
            LabeledContent("Session", value: Self.seconds(s.duration))

            LabeledContent("Captured", value: "\(s.framesCaptured)  \(Self.fps(s.captureFPS))")
            LabeledContent("Selected", value: "\(s.framesSelected)  \(Self.fps(s.selectedFPS))")
            LabeledContent("Skipped by gate", value: "\(s.framesSkipped)")
            LabeledContent("Send attempts", value: "\(s.sendAttempts)  \(Self.fps(s.sendAttemptFPS))")
            LabeledContent("Sent OK", value: "\(s.sendSuccesses)  \(Self.fps(s.successfulSendFPS))")
            LabeledContent("Tower replies", value: "\(s.frameResults)  \(Self.fps(s.towerResultFPS))")

            LabeledContent("Send-window drops", value: "\(s.sendWindowDrops)")
            LabeledContent("Session-gate drops", value: "\(s.sessionGateDrops)")
            LabeledContent("Decode failures", value: "\(s.decodeFailures)")
            LabeledContent("Encode failures", value: "\(s.encodeFailures)")
            LabeledContent("Send failures", value: "\(s.sendFailures)")
            LabeledContent("Abandoned by teardown", value: "\(s.sendAbandoned)")

            LabeledContent("Encode ms", value: "\(Self.ms(s.encodeMsAverage)) avg / \(Self.ms(s.encodeMsMax)) max")
            LabeledContent("Uplink", value: Self.bytesPerSecond(s.wireBytesPerSecond))
            LabeledContent("Delivered", value: Self.percent(s.deliveredFraction))

            // The rate arithmetic, spelled out. "Sent OK" above cannot exceed
            // "Window limit", so whenever it falls short of the target these
            // rows say whether the cause is the network (send ms), the main
            // actor (hop ms), or the window being too small for the measured
            // latency.
            LabeledContent("Send ms", value: "\(Self.ms(s.sendLatencyMsAverage)) avg / \(Self.ms(s.sendLatencyMsMax)) max")
            LabeledContent("Slot ms", value: "\(Self.ms(s.slotLifetimeMsAverage)) avg / \(Self.ms(s.slotLifetimeMsMax)) max")
            LabeledContent("Main-actor hop ms", value: Self.ms(s.completionHopMsAverage))
            LabeledContent(
                "Window limit",
                value: "\(Self.fps(s.windowLimitedFPS(capacity: tower.maxFramesInFlight)))  (\(tower.maxFramesInFlight) slots)"
            )
            LabeledContent("Stall recoveries", value: "\(s.stallRecoveries)")

            // Health checks rather than measurements. "Backlog" is a count,
            // not a verdict: a small steady number is the main-queue hop plus
            // the send window; a climbing one is queue growth. The healthy
            // ceiling scales with the window, so it is stated in the footer
            // rather than left for the reader to infer.
            LabeledContent("Backlog", value: "\(s.framesUnaccounted)")
            LabeledContent("Sequence 1:1", value: s.sequenceInvariantHolds ? "yes" : "NO")
        } header: {
            Text("Sender Pipeline")
        } footer: {
            Text("Counts and rates for one camera session, from DAT callback to Tower reply. Target send rate is \(String(format: "%.0f", FrameRateGate.towerTargetFPS)) fps. \"Window limit\" is slots ÷ slot ms — the ceiling on \"Sent OK\" regardless of how many frames the gate selects. \"Backlog\" is healthy up to about \(tower.maxFramesInFlight + 1); what matters is that it does not climb. Debug build with per-frame logging — treat rates as a floor.")
        }
    }

    private static func fps(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%.1f/s", value)
    }

    private static func ms(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%.2f", value)
    }

    private static func seconds(_ value: TimeInterval) -> String {
        String(format: "%.1fs", value)
    }

    private static func percent(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%.1f%%", value * 100)
    }

    private static func bytesPerSecond(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%.0f KB/s", value / 1024)
    }

    // MARK: Device health

    /// Thermal, power and battery telemetry for both ends of the link.
    ///
    /// Present because a five-minute physical run left the glasses warm to the
    /// touch and the sender rate decayed over the same minutes, and there was
    /// no way to tell whether those facts were related. Every row is a value
    /// the OS or the SDK actually reports; nothing here is estimated.
    private var deviceHealthSection: some View {
        Section {
            LabeledContent("Glasses thermal", value: glassesThermalText)
            LabeledContent("iPhone thermal", value: phoneThermalText)
            LabeledContent("iPhone battery", value: batteryText)
            LabeledContent("Low Power Mode", value: health.isLowPowerModeEnabled ? "On" : "Off")
        } header: {
            Text("Device Health")
        } footer: {
            Text("Glasses thermal is DAT's ThermalLevel — the only device-health value the pinned 0.9.0 SDK exposes. Glasses battery, charging state and any numeric temperature are not in that API, so they are absent rather than estimated. \"iPhone thermal\" at Serious or above means the system is throttling, which shows up in the sender rows above as encode and hop times growing.")
        }
    }

    /// Spells out the consequence rather than leaving the reader to know which
    /// `ThermalState` cases mean the system has started shedding performance.
    private var phoneThermalText: String {
        let name = health.thermalState.displayName
        return health.thermalState.isThrottling ? "\(name) — throttling" : name
    }

    /// `nil` — no active device, or the stream has not yielded yet — is shown
    /// as unavailable rather than as a benign-looking level.
    private var glassesThermalText: String {
        guard let level = glasses.glassesThermalLevel else { return "—" }
        return "\(level)"
    }

    private var batteryText: String {
        guard let level = health.batteryLevel else { return health.batteryState.displayName }
        return "\(Int((level * 100).rounded()))%  \(health.batteryState.displayName)"
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
            // Labelled as per-bracket on purpose. It counts replies since the
            // last `stream_start`, and a reconnect reopens the bracket — so
            // after one it will read lower than the per-session "Tower replies"
            // on the Sender Pipeline section above. That difference is
            // information here, not a discrepancy, but only if the label says
            // which is which.
            LabeledContent("Frame Results (this bracket)", value: "\(tower.frameResultCount)")
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
