//
//  GlassesConnection.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import Combine
import Foundation
import MWDATCore

#if DEBUG
import CoreMedia
import MWDATCamera
import MWDATMockDevice
import UIKit
#endif

/// Wraps the Meta Wearables DAT `WearablesInterface` and exposes registration
/// and device-availability state to the rest of the app. This is the only
/// type in the app that talks to DAT directly — the boundary described in
/// docs/05-DAT-INTEGRATION.md.
///
/// Scope is intentionally limited to registration/connection state. Camera
/// streaming is not implemented here.
#if DEBUG
/// One decoded frame, ready for Tower transmission. Carries dimensions
/// derived directly from the `CMSampleBuffer` format description (the same
/// source used for the confirmed on-screen frame-dimension logging), not
/// re-derived from `UIImage.size`, to avoid any scale-factor ambiguity.
struct CapturedFrame {
    let image: UIImage
    let sequence: Int
    let width: Int
    let height: Int
}
#endif

@MainActor
final class GlassesConnection: ObservableObject {
    @Published private(set) var registrationState: RegistrationState
    @Published private(set) var devices: [DeviceIdentifier]
    @Published private(set) var cameraPermissionStatus: PermissionStatus?
    @Published var errorMessage: String?

    #if DEBUG
    /// Mirrors `MockDeviceKit.shared.isEnabled` — read back from the SDK
    /// after every call, not toggled optimistically.
    @Published private(set) var mockDeviceKitEnabled = false
    /// Mirrors `MockDeviceKit.shared.pairedDevices.isEmpty == false`.
    @Published private(set) var isMockDevicePaired = false
    /// The device returned by `pairGlasses(model:)`, retained so we can
    /// power it on and don it, matching the official sample's flow.
    private var pairedMockDevice: MockGlasses?

    // MARK: Camera session (proof-of-path milestone; DEBUG-only for now)

    @Published private(set) var deviceSessionState: DeviceSessionState = .idle
    // Explicitly qualified: this app already declares its own `StreamState`
    // (Glasses/StreamManager.swift, unrelated to DAT) which would otherwise
    // shadow MWDATCamera's type of the same name.
    @Published private(set) var cameraStreamState: MWDATCamera.StreamState = .stopped
    @Published private(set) var frameCount: Int = 0
    /// The most recent frame decoded for Tower transmission, sampled down to
    /// `FrameRateGate.towerTargetFPS` by `frameRateGate` — not every frame,
    /// per the backpressure policy in docs/03-ROADMAP.md V0.7.
    /// `ProjectManager` observes this and forwards it to `TowerClient`;
    /// `GlassesConnection` never talks to `TowerClient` directly, preserving
    /// the boundary in docs/02-DEVELOPMENT-RULES.md Rule 1.
    @Published private(set) var latestCapturedFrame: CapturedFrame?
    /// True once `AutoDeviceSelector.activeDeviceStream()` has yielded a
    /// non-nil device. `startCameraSession()` must not call `createSession`
    /// before this is true, per Meta's documented `AutoDeviceSelector`
    /// guidance — calling earlier throws `DeviceSessionError.noEligibleDevice`.
    @Published private(set) var hasActiveDevice = false

    /// Fires once when the camera stream is confirmed live (`StreamState
    /// .streaming`) — the earliest point it's true that a session "has
    /// successfully started and is about to begin forwarding frames".
    /// `ProjectManager` observes this and calls `TowerClient.sendStreamStart()`;
    /// `GlassesConnection` never talks to `TowerClient` directly, preserving
    /// the boundary in docs/02-DEVELOPMENT-RULES.md Rule 1.
    let cameraStreamDidStart = PassthroughSubject<Void, Never>()
    /// Fires once when `stopCameraSession()` is invoked for an active camera
    /// stream — the point the current streaming session is ending.
    let cameraStreamDidStop = PassthroughSubject<Void, Never>()

    private var deviceSession: DeviceSession?
    private var camera: MWDATCamera.Camera?
    /// Created once, in `init()`, and retained for the object's lifetime —
    /// it must observe `devicesStream()` continuously, not just at the
    /// moment a session is requested. Matches the official sample's
    /// `CameraViewModel`, which does the same.
    private var deviceSelector: AutoDeviceSelector?
    private var activeDeviceTask: Task<Void, Never>?
    private let sessionTokenBag = ListenerTokenBag()
    private let streamTokenBag = ListenerTokenBag()

    /// Decides which captured frames are forwarded for transmission. Reset at
    /// the start of every session so cadence never carries across sessions.
    private var frameRateGate = FrameRateGate(targetFPS: FrameRateGate.towerTargetFPS)

    /// Console-logging cadence, independent of transmission: until this task
    /// the same `% 30` condition governed both, which is what held Tower
    /// delivery at 24/30 ≈ 0.8 fps. Logging stays at ~1 Hz per category
    /// because `print` on the main actor is not free at 24 Hz; the
    /// authoritative per-stage counts live in `metrics`.
    ///
    /// Time-based rather than every Nth sequence number, because a sequence
    /// stride aliases against the rate gate. At a 24 fps source the gate
    /// admits every other frame, so sequences 1, 3, 5, … are selected and
    /// 2, 4, 6, … are skipped — and an even stride like the old 30 therefore
    /// lands *only* on skipped frames. The selected-frame line, the one
    /// carrying the frame dimensions that proved the physical path works,
    /// would never print again after frame #1.
    private static let logInterval: TimeInterval = 1.0
    private var lastSelectedLogAt: TimeInterval = -.infinity
    private var lastSkippedLogAt: TimeInterval = -.infinity
    #endif

    private let wearables: WearablesInterface
    /// Sender-side instrumentation. Shared with `TowerClient` via
    /// `ProjectManager`, which owns both.
    private let metrics: SenderMetrics
    private var registrationTask: Task<Void, Never>?
    private var deviceStreamTask: Task<Void, Never>?

    /// - Parameter metrics: Shared sender instrumentation. Defaults to a
    ///   private instance so callers that don't care (tests, previews) need not
    ///   supply one. Built in the body rather than as a default argument
    ///   because default arguments are evaluated outside this type's actor.
    init(
        wearables: WearablesInterface = Wearables.shared,
        metrics: SenderMetrics? = nil
    ) {
        self.wearables = wearables
        self.metrics = metrics ?? SenderMetrics()
        self.registrationState = wearables.registrationState
        self.devices = wearables.devices

        #if DEBUG
        mockDeviceKitEnabled = MockDeviceKit.shared.isEnabled
        isMockDevicePaired = !MockDeviceKit.shared.pairedDevices.isEmpty

        // Created early, per Meta's documented AutoDeviceSelector guidance:
        // "Create it before the user taps the [session] action ... otherwise
        // createSession can throw DeviceSessionError.noEligibleDevice."
        let selector = AutoDeviceSelector(wearables: wearables)
        deviceSelector = selector
        activeDeviceTask = Task { [weak self] in
            guard let self else { return }
            for await activeDeviceId in selector.activeDeviceStream() {
                self.hasActiveDevice = activeDeviceId != nil
                print("[Glasses][Camera] activeDeviceStream changed: \(String(describing: activeDeviceId)) (hasActiveDevice=\(self.hasActiveDevice))")
            }
        }
        #endif

        registrationTask = Task { [weak self] in
            guard let self else { return }
            for await state in wearables.registrationStateStream() {
                self.registrationState = state
                #if DEBUG
                print("[Glasses][Registration] state changed: \(state)")
                #endif
            }
        }

        deviceStreamTask = Task { [weak self] in
            guard let self else { return }
            for await devices in wearables.devicesStream() {
                self.devices = devices
                #if DEBUG
                print("[Glasses][Devices] devicesStream changed: count=\(devices.count) ids=\(devices)")
                #endif
            }
        }
    }

    isolated deinit {
        registrationTask?.cancel()
        deviceStreamTask?.cancel()
        #if DEBUG
        activeDeviceTask?.cancel()
        camera?.stop()
        deviceSession?.stop()
        #endif
    }

    func connect() {
        guard registrationState != .registering else { return }
        Task {
            do {
                try await wearables.startRegistration()
            } catch let error as RegistrationError {
                errorMessage = error.description
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func disconnect() {
        Task {
            do {
                try await wearables.startUnregistration()
            } catch let error as UnregistrationError {
                errorMessage = error.description
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func checkCameraPermission() {
        Task {
            do {
                cameraPermissionStatus = try await wearables.checkPermissionStatus(.camera)
                #if DEBUG
                print("[Glasses][CameraPermission] checkPermissionStatus -> \(String(describing: cameraPermissionStatus))")
                #endif
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func requestCameraPermission() {
        Task {
            do {
                cameraPermissionStatus = try await wearables.requestPermission(.camera)
                #if DEBUG
                print("[Glasses][CameraPermission] requestPermission -> \(String(describing: cameraPermissionStatus))")
                #endif
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func nameForDevice(_ id: DeviceIdentifier) -> String {
        wearables.deviceForIdentifier(id)?.nameOrId() ?? "Unknown device"
    }

    #if DEBUG
    func toggleMockDeviceKit() {
        print("[Glasses][MockDeviceKit] toggle tapped (currently enabled=\(mockDeviceKitEnabled))")
        if mockDeviceKitEnabled {
            MockDeviceKit.shared.disable()
            print("[Glasses][MockDeviceKit] disable() called")
            pairedMockDevice = nil
            isMockDevicePaired = false
        } else {
            MockDeviceKit.shared.enable()
            print("[Glasses][MockDeviceKit] enable() called")
        }
        mockDeviceKitEnabled = MockDeviceKit.shared.isEnabled
        print("[Glasses][MockDeviceKit] authoritative isEnabled after call: \(mockDeviceKitEnabled)")
    }

    /// Pairs one mock Ray-Ban Meta device, then powers it on and dons it —
    /// the same two follow-up steps the official CameraAccess sample's
    /// MockDeviceCardViewModel performs before a mock device is usable.
    /// Does not configure a camera feed — streaming is not implemented here.
    func pairMockGlasses() {
        print("[Glasses][MockDeviceKit] pairGlasses(model: .rayBanMeta) called")
        do {
            let device = try MockDeviceKit.shared.pairGlasses(model: .rayBanMeta)
            print("[Glasses][MockDeviceKit] pairGlasses succeeded, deviceIdentifier=\(device.deviceIdentifier)")

            pairedMockDevice = device
            isMockDevicePaired = !MockDeviceKit.shared.pairedDevices.isEmpty
            print("[Glasses][MockDeviceKit] pairedDevices count: \(MockDeviceKit.shared.pairedDevices.count)")

            device.powerOn()
            print("[Glasses][MockDeviceKit] powerOn() called/completed")

            device.don()
            print("[Glasses][MockDeviceKit] don() called/completed")
        } catch {
            print("[Glasses][MockDeviceKit] pairGlasses failed: \(error.localizedDescription)")
            errorMessage = error.localizedDescription
        }
    }

    // MARK: Camera session (proof-of-path milestone)

    /// Points the paired mock device's simulated camera at the iPhone's own
    /// back camera, so DAT delivers real live frames through the same
    /// Camera/Stream API a physical glasses camera would use.
    func configureMockCameraFeed() {
        print("[Glasses][Camera][Diag] --- Configure Mock Camera Feed tapped ---")
        print("[Glasses][Camera][Diag] MockDeviceKit.shared.isEnabled = \(MockDeviceKit.shared.isEnabled)")
        let paired = MockDeviceKit.shared.pairedDevices
        print("[Glasses][Camera][Diag] MockDeviceKit.shared.pairedDevices.count = \(paired.count)")
        for device in paired {
            print("[Glasses][Camera][Diag]   pairedDevice.deviceIdentifier = \(device.deviceIdentifier)")
        }
        print("[Glasses][Camera][Diag]   power/don state: not exposed as a readable property on MockGlasses/MockDevice in any confirmed source; only write-only powerOn()/don() actions exist")
        print("[Glasses][Camera][Diag] pairedMockDevice (our retained ref) = \(String(describing: pairedMockDevice?.deviceIdentifier))")
        print("[Glasses][Camera][Diag] wearables.devices.count = \(wearables.devices.count) ids=\(wearables.devices)")
        print("[Glasses][Camera][Diag] self.devices (last devicesStream value) = \(devices.count) ids=\(devices)")
        print("[Glasses][Camera][Diag] registrationState = \(registrationState)")
        print("[Glasses][Camera][Diag] cameraPermissionStatus = \(String(describing: cameraPermissionStatus))")
        print("[Glasses][Camera][Diag] current errorMessage at tap time (may be stale from a prior action) = \(String(describing: errorMessage))")

        guard let device = pairedMockDevice else {
            print("[Glasses][Camera] configureMockCameraFeed called with no paired mock device")
            errorMessage = "Pair a mock device first"
            return
        }
        device.services.camera.setCameraFeed(cameraFacing: .back)
        print("[Glasses][Camera] mock camera feed configured: back camera")
    }

    /// Creates and starts a `DeviceSession` via `AutoDeviceSelector`. Once the
    /// session reaches `.started`, the state observer starts the camera
    /// stream automatically — this is the only entry point the UI needs.
    ///
    /// Requires `hasActiveDevice` to already be true (i.e. `deviceSelector`'s
    /// `activeDeviceStream()` has yielded a device). Calling `createSession`
    /// before that is confirmed to throw `DeviceSessionError.noEligibleDevice`
    /// per Meta's documented AutoDeviceSelector guidance.
    func startCameraSession() {
        // Scope out any stale error from a prior attempt so it can't be
        // misattributed to whatever the user does next.
        errorMessage = nil
        print("[Glasses][Camera] startCameraSession called (hasActiveDevice=\(hasActiveDevice))")

        guard deviceSession == nil else {
            print("[Glasses][Camera] startCameraSession called while a session already exists")
            return
        }
        guard hasActiveDevice, let deviceSelector else {
            print("[Glasses][Camera] startCameraSession refused: no active eligible device yet")
            errorMessage = "No eligible glasses device yet. Make sure Mock Device Kit is enabled, paired, powered on, and donned, then wait a moment for the device to become active."
            return
        }

        frameCount = 0
        // Otherwise the viewfinder and the "Latest frame #N" tile keep showing
        // the previous session's image and sequence, while `frameCount` has
        // already restarted at 0 — two contradictory claims on screen at once.
        latestCapturedFrame = nil
        frameRateGate.reset()
        // So the first frame of every session logs, even one started within a
        // second of the last one ending.
        lastSelectedLogAt = -.infinity
        lastSkippedLogAt = -.infinity
        metrics.begin()
        print("[Glasses][Camera] creating session via AutoDeviceSelector (active device confirmed)")

        do {
            let session = try wearables.createSession(deviceSelector: deviceSelector)
            deviceSession = session
            observeSession(session)
            deviceSessionState = .starting
            try session.start()
            print("[Glasses][Camera] session.start() called — createSession succeeded with an eligible device present")
        } catch let error as DeviceSessionError {
            print("[Glasses][Camera] session creation/start failed: \(error.localizedDescription)")
            errorMessage = error.localizedDescription
            deviceSession = nil
            deviceSessionState = .idle
        }
    }

    /// Stops the camera/stream (if any) and the device session, following the
    /// official 0.9.0 teardown: `camera.stop()` for the stream, then
    /// `deviceSession.stop()` for the full session.
    func stopCameraSession() {
        print("[Glasses][Camera] stopCameraSession called")
        if let camera {
            cameraStreamState = .stopping
            camera.stop()
            cameraStreamDidStop.send(())
            // Freezes the session's final counters so they stay readable
            // after Stop rather than being wiped or left mid-interval.
            metrics.finish()
        }
        if let deviceSession {
            deviceSessionState = .stopping
            deviceSession.stop()
        }
    }

    private func observeSession(_ session: DeviceSession) {
        session.statePublisher.listen { [weak self] state in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.deviceSessionState = state
                print("[Glasses][Camera] DeviceSessionState changed: \(state)")
                if state == .started {
                    self.beginCameraStream(on: session)
                } else if state == .stopped {
                    self.cleanupCameraSession()
                }
            }
        }.store(in: sessionTokenBag)

        session.errorPublisher.listen { [weak self] error in
            Task { @MainActor [weak self] in
                print("[Glasses][Camera] session error: \(error.localizedDescription)")
                self?.errorMessage = error.localizedDescription
            }
        }.store(in: sessionTokenBag)
    }

    /// Adds the camera capability and starts its stream. Requires camera
    /// permission already granted via the existing check/request controls —
    /// this milestone does not trigger the permission redirect itself.
    private func beginCameraStream(on session: DeviceSession) {
        guard camera == nil else { return }
        guard cameraPermissionStatus == .granted else {
            print("[Glasses][Camera] camera permission not granted (\(String(describing: cameraPermissionStatus))); not starting stream")
            errorMessage = "Camera permission not granted. Use Check/Request Camera Permission first."
            return
        }

        let config = StreamConfiguration(
            videoCodec: VideoCodec.raw,
            resolution: StreamingResolution.low,
            frameRate: 24
        )

        do {
            guard let newCamera = try session.addCamera(config: config) else {
                print("[Glasses][Camera] addCamera returned nil")
                errorMessage = "Could not create camera"
                return
            }
            camera = newCamera
            print("[Glasses][Camera] addCamera succeeded")
            setupStreamListeners(for: newCamera.stream)
            cameraStreamState = .starting
            newCamera.stream.start()
            print("[Glasses][Camera] stream.start() called")
        } catch {
            print("[Glasses][Camera] addCamera failed: \(error.localizedDescription)")
            errorMessage = error.localizedDescription
            camera = nil
        }
    }

    private func setupStreamListeners(for stream: MWDATCamera.Stream) {
        stream.statePublisher.listen { [weak self] state in
            Task { @MainActor [weak self] in
                self?.cameraStreamState = state
                print("[Glasses][Camera] StreamState changed: \(state)")
                if case .streaming = state {
                    self?.cameraStreamDidStart.send(())
                }
            }
        }.store(in: streamTokenBag)

        stream.videoFramePublisher.listen { [weak self] frame in
            Task { @MainActor [weak self] in
                guard let self else { return }
                // One clock read serves both the gate and the log budgets.
                let now = MonotonicClock.now

                // Sequence numbers are DAT callback ordinals: every delivered
                // frame gets one, whether or not it is transmitted. That is
                // what lets the Tower compute the source rate from `seq` gaps,
                // and it is deliberately unchanged.
                self.frameCount += 1
                let sequence = self.frameCount
                self.metrics.recordCapture(sequence: sequence)

                guard self.frameRateGate.shouldSelect(at: now) else {
                    self.metrics.recordSkip()
                    if now - self.lastSkippedLogAt >= Self.logInterval {
                        self.lastSkippedLogAt = now
                        print("[Glasses][Camera] frame #\(sequence) skipped by the \(FrameRateGate.towerTargetFPS) fps gate")
                    }
                    return
                }
                self.metrics.recordSelection()

                // Selected frames get their own budget, so this line cannot be
                // crowded out by the skipped-frame line above.
                let shouldLog = now - self.lastSelectedLogAt >= Self.logInterval
                if shouldLog { self.lastSelectedLogAt = now }

                // Both conversions happen only for selected frames, so the
                // cost scales with the send rate rather than the capture rate.
                guard let dimensions = Self.pixelDimensions(for: frame) else {
                    self.metrics.recordDecodeFailure()
                    // Failures are counted unconditionally but logged on the
                    // same cadence as everything else: at the target rate an
                    // unguarded print here would flood the console 12 times a
                    // second. `metrics.decodeFailures` is the real record.
                    if shouldLog {
                        print("[Glasses][Camera] frame received #\(sequence) dimensions=unknown")
                    }
                    return
                }
                guard let image = frame.makeUIImage() else {
                    self.metrics.recordDecodeFailure()
                    if shouldLog {
                        print("[Glasses][Camera] frame #\(sequence) makeUIImage() returned nil")
                    }
                    return
                }
                if shouldLog {
                    print("[Glasses][Camera] frame received #\(sequence) dimensions=\(dimensions.width)x\(dimensions.height)")
                }

                self.latestCapturedFrame = CapturedFrame(
                    image: image,
                    sequence: sequence,
                    width: dimensions.width,
                    height: dimensions.height
                )
            }
        }.store(in: streamTokenBag)

        stream.errorPublisher.listen { [weak self] error in
            Task { @MainActor [weak self] in
                print("[Glasses][Camera] stream error: \(error.localizedDescription)")
                self?.errorMessage = error.localizedDescription
            }
        }.store(in: streamTokenBag)
    }

    private func cleanupCameraSession() {
        print("[Glasses][Camera] session cleanup")
        let hadCamera = camera != nil
        sessionTokenBag.clear()
        streamTokenBag.clear()
        deviceSession = nil
        camera = nil

        // A DAT-initiated stop — glasses folded or doffed, Bluetooth lost, a
        // stream error — arrives here without ever passing through
        // `stopCameraSession()`, which until now was the only place
        // `cameraStreamDidStop` fired. That left the Tower's stream bracket
        // open, which then suppressed the *next* session's `stream_start`
        // while `frameCount` restarted at 0 — the Tower would see sequence
        // numbers rewind inside what it still considered one session, making
        // its own seq-gap and FPS figures unreadable. `sendStreamStop()` is
        // idempotent, so the ordinary Stop path reaching here second is a
        // no-op.
        if hadCamera {
            cameraStreamDidStop.send(())
        }
        // A session that ends without stopCameraSession() (a device drop, an
        // error) must still leave truthful final counters, and must not leave
        // the gate mid-cadence for the next session.
        metrics.finish()
        frameRateGate.reset()
        // deviceSelector is intentionally NOT cleared here — it's created
        // once in init() and must keep observing activeDeviceStream() for
        // the object's lifetime, independent of individual session cycles.
        cameraStreamState = .stopped
    }

    private static func pixelDimensions(for frame: VideoFrame) -> (width: Int, height: Int)? {
        guard let formatDescription = CMSampleBufferGetFormatDescription(frame.sampleBuffer) else {
            return nil
        }
        let dimensions = CMVideoFormatDescriptionGetDimensions(formatDescription)
        return (Int(dimensions.width), Int(dimensions.height))
    }
    #endif
}
