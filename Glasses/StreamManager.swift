//
//  StreamManager.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import Combine
import Foundation

/// Whether a media stream from the glasses is active.
///
/// This is a placeholder for future DAT camera streaming
/// (`MWDATCamera`, `Session.addCamera`). No streaming implementation
/// exists yet, so this type stays stopped with no metrics.
enum StreamState: Equatable {
    case stopped
    case starting
    case streaming
}

struct StreamMetrics: Equatable {
    let framesReceived: Int
    let frameRate: Double
}

@MainActor
final class StreamManager: ObservableObject {
    @Published private(set) var state: StreamState = .stopped
    @Published private(set) var metrics: StreamMetrics? = nil

    init() {}
}
