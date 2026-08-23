//
//  TowerConfiguration.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import Foundation

/// Single source of truth for the development Tower endpoint. The Tower is
/// currently remote, reached over Tailscale; this hardcoded address is
/// expected to change across sessions/networks until a discovery or
/// configuration mechanism is designed.
enum TowerConfiguration {
    static let webSocketURL = URL(string: "ws://100.110.156.55:8000/ws")!
}
