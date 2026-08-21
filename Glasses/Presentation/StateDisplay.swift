//
//  StateDisplay.swift
//  Glasses
//

import Foundation
import MWDATCore

#if DEBUG
import MWDATCamera
#endif

/// Human-readable presentation strings for runtime state the app already
/// tracks.
///
/// The dashboard used to interpolate DAT enums directly (`"\(registrationState)"`),
/// which rendered raw Swift case names like `waitingForDevice` at the user and
/// read poorly under VoiceOver. Mapping lives here rather than in a view so it
/// is testable and so no screen invents a state that the model cannot report.
enum StateDisplay {

    // MARK: Glasses

    static func registration(_ state: RegistrationState) -> String {
        switch state {
        case .unavailable: return "Meta AI unavailable"
        case .available: return "Not registered"
        case .registering: return "Registering…"
        case .registered: return "Registered"
        @unknown default: return "Unknown"
        }
    }

    /// `nil` is meaningful: `PermissionStatus` has no `notDetermined` case, so
    /// an absent value means the app has not asked DAT yet.
    static func cameraPermission(_ status: PermissionStatus?) -> String {
        guard let status else { return "Not checked yet" }
        switch status {
        case .granted: return "Allowed"
        case .denied: return "Denied"
        @unknown default: return "Unknown"
        }
    }

    // MARK: Tower

    static func tower(_ status: TowerStatus) -> String {
        switch status {
        case .offline: return "Offline"
        case .connecting: return "Connecting…"
        case .online: return "Connected"
        case .failed: return "Disconnected"
        }
    }

    /// The full failure text, for the error banner. Separate from `tower(_:)`
    /// so a long URLSession message never widens a status pill.
    static func towerFailureDetail(_ status: TowerStatus) -> String? {
        if case .failed(let message) = status { return message }
        return nil
    }

    #if DEBUG

    // MARK: Session (DEBUG-only, mirroring the model's own gating)

    static func deviceSession(_ state: DeviceSessionState) -> String {
        switch state {
        case .idle: return "Idle"
        case .starting: return "Starting…"
        case .started: return "Started"
        case .paused: return "Paused"
        case .stopping: return "Stopping…"
        case .stopped: return "Stopped"
        @unknown default: return "Unknown"
        }
    }

    static func cameraStream(_ state: MWDATCamera.StreamState) -> String {
        switch state {
        case .stopped: return "Stopped"
        case .waitingForDevice: return "Waiting for glasses"
        case .starting: return "Starting…"
        case .streaming: return "Streaming"
        case .paused: return "Paused"
        case .stopping: return "Stopping…"
        @unknown default: return "Unknown"
        }
    }

    #endif
}
