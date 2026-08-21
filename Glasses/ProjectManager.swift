//
//  ProjectManager.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import Combine
import Foundation

/// Root app-level state container. Owns the connection, stream, and tower
/// managers so the dashboard has a single source of truth to observe.
@MainActor
final class ProjectManager: ObservableObject {
    let glassesConnection: GlassesConnection
    let streamManager: StreamManager
    let towerClient: TowerClient

    /// Retains the subscriptions that forward each child's `objectWillChange`
    /// into this object's own publisher. Without this, `@StateObject`/
    /// `@ObservedObject` callers observing `ProjectManager` never re-render
    /// when a child's `@Published` properties change, since `ProjectManager`
    /// itself has no `@Published` properties to trigger its own publisher.
    private var cancellables: Set<AnyCancellable> = []

    init(
        glassesConnection: GlassesConnection? = nil,
        streamManager: StreamManager? = nil,
        towerClient: TowerClient? = nil
    ) {
        self.glassesConnection = glassesConnection ?? GlassesConnection()
        self.streamManager = streamManager ?? StreamManager()
        self.towerClient = towerClient ?? TowerClient()

        for child in [self.glassesConnection.objectWillChange.eraseToAnyPublisher(),
                      self.streamManager.objectWillChange.eraseToAnyPublisher(),
                      self.towerClient.objectWillChange.eraseToAnyPublisher()] {
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
            }
            .store(in: &cancellables)

        self.glassesConnection.cameraStreamDidStop
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.towerClient.sendStreamStop()
            }
            .store(in: &cancellables)
        #endif
    }
}
