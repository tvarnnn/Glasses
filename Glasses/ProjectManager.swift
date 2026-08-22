//
//  ProjectManager.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import Combine
import Foundation

#if DEBUG
// For `MWDATCamera.StreamState`, read when deciding whether a returning Tower
// connection needs its stream bracket reopened.
import MWDATCamera
#endif

/// Root app-level state container. Owns the connection, stream, and tower
/// managers so the dashboard has a single source of truth to observe.
@MainActor
final class ProjectManager: ObservableObject {
    let glassesConnection: GlassesConnection
    let streamManager: StreamManager
    let towerClient: TowerClient

    /// Sender-side instrumentation for the whole capture → transmit path.
    /// `ProjectManager` owns it and hands the same instance to both halves,
    /// which is what makes end-to-end counts (captured vs. selected vs. sent
    /// vs. replied) comparable within one session.
    let senderMetrics: SenderMetrics

    /// iPhone-side thermal, power and battery telemetry, so a rate that decays
    /// over a long run can be attributed to the device throttling rather than
    /// only to the network. The glasses' own thermal level comes from
    /// `glassesConnection.glassesThermalLevel`, which keeps DAT behind its
    /// boundary (docs/02-DEVELOPMENT-RULES.md Rule 1).
    let deviceHealth: DeviceHealth

    /// Retains the subscriptions that forward each child's `objectWillChange`
    /// into this object's own publisher. Without this, `@StateObject`/
    /// `@ObservedObject` callers observing `ProjectManager` never re-render
    /// when a child's `@Published` properties change, since `ProjectManager`
    /// itself has no `@Published` properties to trigger its own publisher.
    private var cancellables: Set<AnyCancellable> = []

    /// Injected children keep whatever `SenderMetrics` instance they were
    /// built with, so a test can wire its own; the default graph shares one.
    init(
        glassesConnection: GlassesConnection? = nil,
        streamManager: StreamManager? = nil,
        towerClient: TowerClient? = nil,
        senderMetrics: SenderMetrics? = nil
    ) {
        let metrics = senderMetrics ?? SenderMetrics()
        self.senderMetrics = metrics
        self.glassesConnection = glassesConnection ?? GlassesConnection(metrics: metrics)
        self.streamManager = streamManager ?? StreamManager()
        // `autoReconnect` is opted into here rather than defaulted on inside
        // `TowerClient`, so that unit tests asserting "a dropped connection
        // settles at .failed" keep asserting about a settled value. In the app
        // the opposite is wanted: a mid-session drop on a remote Tailscale
        // path is the expected case, and until now it ended Tower delivery for
        // good — nothing in the app called `connect()` again except the
        // developer's own button. The stream-bracket reopening wired up below
        // was already written for a reconnect that could not happen.
        self.towerClient = towerClient ?? TowerClient(metrics: metrics, autoReconnect: true)

        let health = DeviceHealth()
        self.deviceHealth = health

        for child in [self.glassesConnection.objectWillChange.eraseToAnyPublisher(),
                      self.streamManager.objectWillChange.eraseToAnyPublisher(),
                      self.towerClient.objectWillChange.eraseToAnyPublisher(),
                      health.objectWillChange.eraseToAnyPublisher()] {
            child
                .receive(on: DispatchQueue.main)
                .sink { [weak self] _ in self?.objectWillChange.send() }
                .store(in: &cancellables)
        }

        #if DEBUG
        // Bridges captured camera frames to the Tower. GlassesConnection and
        // TowerClient never reference each other directly — ProjectManager,
        // which already owns both, is the integration point. Preserves the
        // boundary in docs/02-DEVELOPMENT-RULES.md Rule 1.
        self.glassesConnection.$latestCapturedFrame
            .compactMap { $0 }
            .receive(on: DispatchQueue.main)
            .sink { [weak self] frame in
                self?.towerClient.sendFrame(
                    frame.image,
                    width: frame.width,
                    height: frame.height,
                    sequence: frame.sequence
                )
            }
            .store(in: &cancellables)

        // Bridges the V0.7 stream lifecycle markers the same way.
        self.glassesConnection.cameraStreamDidStart
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.towerClient.sendStreamStart()
                // Battery notifications fire at most once a minute, so without
                // an explicit read the health figures shown against a session
                // can predate it.
                self?.deviceHealth.refresh()
            }
            .store(in: &cancellables)

        self.glassesConnection.cameraStreamDidStop
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.towerClient.sendStreamStop()
            }
            .store(in: &cancellables)

        // Re-opens the stream bracket after the Tower connection is replaced.
        //
        // `cameraStreamDidStart` fires once per *camera* session, but the
        // Tower socket has a shorter life: a drop tears it down and
        // `stream_start` does not survive it. Without this, a single
        // mid-session blip — the expected case on a remote Tailscale path —
        // would leave the Tower pill green while every remaining frame was
        // silently discarded for want of a bracket, recoverable only by
        // stopping and restarting the camera. `sendStreamStart()` is a no-op
        // when a bracket is already open, so an ordinary connect during an
        // idle camera is unaffected.
        self.towerClient.$status
            .filter { $0 == .online }
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                guard let self, self.glassesConnection.cameraStreamState == .streaming else { return }
                self.towerClient.sendStreamStart()
            }
            .store(in: &cancellables)
        #endif
    }
}
