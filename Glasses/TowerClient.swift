//
//  TowerClient.swift
//  Glasses
//
//  Created by Tristan Varner on 8/18/26.
//

import Combine
import Foundation

#if DEBUG
import UIKit
#endif

/// Connection status to the Tower (the project's base-station/hub service).
enum TowerStatus: Equatable {
    case offline
    case connecting
    case online
    case failed(String)
}

/// WebSocket client for the Tower connection. Validates connectivity with an
/// initial ping/pong handshake, then keeps a continuous receive loop running
/// for as long as the connection is online so the client can observe
/// `frame_result` messages and — just as importantly — actually notice when
/// the Tower or the OS closes the socket out from under it. A
/// `URLSessionWebSocketDelegate` close callback is a second, independent
/// signal for the same event. This does not implement reconnect/backoff or
/// the future frame-streaming protocol beyond what's described here.
@MainActor
final class TowerClient: NSObject, ObservableObject {
    @Published private(set) var status: TowerStatus = .offline

    #if DEBUG
    /// How many `frame_result` messages the receive loop has processed — the
    /// only end-to-end proof that the Tower received a frame and replied.
    /// `@Published` so the dashboard can show it live; it is otherwise
    /// unchanged, and nothing reads it to make a decision. It now invalidates
    /// the view tree at the Tower's reply rate (target ~12 Hz), which is the
    /// same order as `GlassesConnection.frameCount` has always done at 24 Hz.
    @Published private(set) var frameResultCount = 0

    /// True between a sent `stream_start` and the matching `stream_stop`.
    /// `sendFrame` will not forward anything while this is false, so a frame
    /// captured in the brief window after `stopCameraSession()` fires (but
    /// before DAT actually tears the stream down) can never reach the Tower.
    /// `@Published` for the developer surface only — the send path still reads
    /// the stored value directly and its semantics are unchanged.
    @Published private(set) var isStreamingToTower = false
    #endif

    /// How many frame sends may be outstanding on the socket at once.
    ///
    /// This is *not* an ACK window. `URLSessionWebSocketTask.send` reports
    /// completion when the message has been written out, not when the Tower
    /// has processed it, so the send path is not round-trip bound and does not
    /// need to be: `frame_result` messages are observed independently by the
    /// receive loop and never gate a send.
    ///
    /// What it does bound is the *local* outbound backlog. Without it, a
    /// pipeline running at the target rate hands URLSession an unbounded
    /// number of ~20 KB messages whenever the uplink cannot keep up, growing
    /// memory and latency without ever dropping anything — the failure mode
    /// docs/03-ROADMAP.md V0.7 explicitly forbids.
    ///
    /// 2 leaves enough headroom that a send completing in well under one
    /// frame interval never blocks the next frame, and is small enough that
    /// whatever is queued is always near-fresh. When the window is full the
    /// *new* frame is dropped rather than an older queued one: a WebSocket
    /// stream cannot be reordered, so declining to add to the queue is the
    /// only way to keep latency bounded.
    let maxFramesInFlight: Int
    private var framesInFlight = 0

    /// Per-frame logging cadence, in send calls. At the target rate this path
    /// runs ~12 times a second and `print` with string interpolation is not
    /// free, so routine success and routine drops are decimated. The
    /// authoritative per-stage counts live in `metrics`.
    private static let frameLogStride = 12
    private var frameLogCounter = 0
    /// Separate budget from `frameLogCounter` so the outbound and inbound
    /// lines cannot crowd each other out — each stays at ~1 Hz.
    private var resultLogCounter = 0

    /// Sender-side instrumentation. Shared with `GlassesConnection` via
    /// `ProjectManager`, which owns both.
    private let metrics: SenderMetrics

    private var session: URLSession?
    private var webSocketTask: URLSessionWebSocketTask?
    private var validationTask: Task<Void, Never>?
    private var receiveTask: Task<Void, Never>?

    override init() {
        self.metrics = SenderMetrics()
        self.maxFramesInFlight = 2
        super.init()
    }

    /// - Parameters:
    ///   - metrics: Shared sender instrumentation.
    ///   - maxFramesInFlight: Overridable so tests can drive the bounded send
    ///     window deterministically.
    init(metrics: SenderMetrics, maxFramesInFlight: Int = 2) {
        self.metrics = metrics
        self.maxFramesInFlight = max(1, maxFramesInFlight)
        super.init()
    }

    /// - Parameter url: The Tower endpoint. Defaults to the real Tower
    ///   (`TowerConfiguration.webSocketURL`); overridable so tests can point
    ///   this at a local mock server instead.
    func connect(to url: URL = TowerConfiguration.webSocketURL) {
        guard status != .connecting else { return }

        if webSocketTask != nil {
            log("connect() called with a previous connection still active — tearing it down first")
        }
        teardownConnection(cancelWith: .normalClosure)

        log("connection attempt: \(url)")
        status = .connecting

        let session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        self.session = session
        let task = session.webSocketTask(with: url)
        webSocketTask = task
        task.resume()
        log("WebSocket opened (resume() called)")

        validationTask = Task { [weak self] in
            await self?.validateConnection(task: task)
        }
    }

    func disconnect() {
        log("disconnect() called")
        teardownConnection(cancelWith: .normalClosure)
        status = .offline
        log("disconnect cleanup complete")
    }

    #if DEBUG
    /// Sends one already-decoded camera frame to the Tower as a JSON text
    /// message over the existing open WebSocket connection — the same
    /// connection/`send` path validated by the ping/pong milestone. No new
    /// networking, no binary framing: this reuses `webSocketTask.send(.string(...))`
    /// exactly as `validateConnection` already does.
    ///
    /// Minimal proof-of-path only: one JPEG-encoded, base64-in-JSON frame at
    /// a time. Not batching, not compressing beyond a fixed JPEG quality, not
    /// adapting rate — see docs/03-ROADMAP.md V0.7 for where that belongs.
    func sendFrame(_ image: UIImage, width: Int, height: Int, sequence: Int) {
        frameLogCounter += 1
        let shouldLog = frameLogCounter % Self.frameLogStride == 1

        guard status == .online, let task = webSocketTask else {
            metrics.recordSessionGateDrop()
            if shouldLog {
                log("frame #\(sequence) not sent — Tower not online (status=\(status))")
            }
            return
        }
        guard isStreamingToTower else {
            metrics.recordSessionGateDrop()
            if shouldLog {
                log("frame #\(sequence) not sent — no stream_start sent yet (or stream_stop already sent)")
            }
            return
        }
        // Checked before encoding, so a frame we are going to drop never costs
        // a JPEG encode.
        guard framesInFlight < maxFramesInFlight else {
            metrics.recordSendWindowDrop()
            if shouldLog {
                log("frame #\(sequence) dropped — \(framesInFlight) sends already in flight (window \(maxFramesInFlight))")
            }
            return
        }

        let encodeStart = MonotonicClock.now
        guard let jpegData = image.jpegData(compressionQuality: 0.5) else {
            metrics.recordEncodeFailure()
            log("frame #\(sequence) failed to encode as JPEG")
            return
        }

        let payload: [String: Any] = [
            "type": "frame",
            "seq": sequence,
            "width": width,
            "height": height,
            "format": "jpeg",
            "data": jpegData.base64EncodedString(),
        ]

        guard
            let jsonData = try? JSONSerialization.data(withJSONObject: payload),
            let jsonText = String(data: jsonData, encoding: .utf8)
        else {
            metrics.recordEncodeFailure()
            log("frame #\(sequence) failed to serialize JSON payload")
            return
        }
        metrics.recordEncode(seconds: MonotonicClock.now - encodeStart)

        framesInFlight += 1
        metrics.recordSendAttempt(wireBytes: jsonData.count)
        if shouldLog {
            log("frame #\(sequence) sending \(jsonData.count) bytes (\(width)x\(height), jpeg \(jpegData.count) bytes)")
        }

        task.send(.string(jsonText)) { [weak self] error in
            Task { @MainActor in
                guard let self else { return }
                // A completion for a socket this client no longer owns:
                // `framesInFlight` was already zeroed by teardown, so
                // decrementing here would drive it negative and permanently
                // widen the window. The outcome is also not this connection's
                // to report — but it still has to be *recorded*, or the frame
                // would look permanently in flight and the accounting
                // invariant would false-alarm after every disconnect.
                guard self.isCurrent(task) else {
                    self.metrics.recordSendAbandoned()
                    return
                }
                self.framesInFlight -= 1

                if let error {
                    self.metrics.recordSendFailure()
                    self.log("frame #\(sequence) send failed: \(error.localizedDescription)")
                    self.fail("Send failed: \(error.localizedDescription)", task: task)
                } else {
                    self.metrics.recordSendSuccess()
                    if shouldLog {
                        self.log("frame #\(sequence) sent")
                    }
                }
            }
        }
    }

    /// Marks the stream as active and sends `{"type":"stream_start"}` once,
    /// over the existing Tower WebSocket, so the Tower knows to expect
    /// frames. Fire-and-forget: no response is awaited or expected. A no-op
    /// if already streaming, so a redundant call (e.g. DAT re-delivering the
    /// `.streaming` state) can't send it twice for the same session.
    func sendStreamStart() {
        guard !isStreamingToTower else {
            log("stream_start suppressed — already streaming")
            return
        }
        // The flag is set only if the marker actually reached a socket.
        // Setting it first meant a start attempted while the Tower was
        // offline left `isStreamingToTower == true` with the Tower never
        // having been told, so every frame of that session was forwarded
        // outside any stream bracket and the eventual `stream_stop` was
        // unmatched.
        guard sendLifecycleMarker(type: "stream_start") else { return }
        isStreamingToTower = true
        // Scoped to one stream bracket so it reads as "replies this session",
        // matching `GlassesConnection.frameCount` next to it on the dashboard.
        // A lifetime-cumulative counter shown beside a per-session one
        // diverges by tens of thousands over a long run and invites reading
        // the pair as a delivery ratio.
        frameResultCount = 0
    }

    /// Marks the stream as inactive and sends `{"type":"stream_stop"}` once.
    /// From this point, `sendFrame` will not forward anything until the next
    /// `sendStreamStart()`. A no-op if not currently streaming.
    func sendStreamStop() {
        guard isStreamingToTower else {
            log("stream_stop suppressed — not currently streaming")
            return
        }
        isStreamingToTower = false
        _ = sendLifecycleMarker(type: "stream_stop")
    }

    /// Shared send path for the two stream lifecycle markers — same
    /// WebSocket, same fire-and-forget `send` used by `sendFrame`, no new
    /// connection, no reply awaited. Deliberately bypasses the frame send
    /// window: markers are two-byte payloads that define session boundaries,
    /// and delaying or dropping one corrupts every frame count on either side
    /// of it.
    ///
    /// - Returns: whether the marker was handed to a socket. Not whether the
    ///   Tower received it — that is still fire-and-forget.
    private func sendLifecycleMarker(type: String) -> Bool {
        guard status == .online, let task = webSocketTask else {
            log("\(type) not sent — Tower not online (status=\(status))")
            return false
        }
        guard
            let jsonData = try? JSONSerialization.data(withJSONObject: ["type": type]),
            let jsonText = String(data: jsonData, encoding: .utf8)
        else {
            log("\(type) failed to serialize JSON payload")
            return false
        }
        task.send(.string(jsonText)) { [weak self] error in
            Task { @MainActor in
                guard let self else { return }
                if let error {
                    self.log("\(type) send failed: \(error.localizedDescription)")
                    self.fail("Send failed: \(error.localizedDescription)", task: task)
                } else {
                    self.log("\(type) sent")
                }
            }
        }
        return true
    }
    #endif

    /// Sends one ping and validates the pong within a bounded timeout. On
    /// success, hands off to the continuous receive loop.
    private func validateConnection(task: URLSessionWebSocketTask) async {
        do {
            let pingPayload = try JSONSerialization.data(withJSONObject: ["type": "ping"])
            guard let pingText = String(data: pingPayload, encoding: .utf8) else {
                fail("Could not encode ping payload", task: task)
                return
            }

            try await task.send(.string(pingText))
            log("ping sent: \(pingText)")

            let message = try await withTimeout(seconds: 6) {
                try await task.receive()
            }
            log("message received: \(message)")

            guard
                case .string(let text) = message,
                let data = text.data(using: .utf8),
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
                json["type"] == "pong"
            else {
                fail("Unexpected/malformed response from Tower", task: task)
                return
            }

            log("pong validated")
            guard !Task.isCancelled, isCurrent(task) else { return }
            status = .online
            startReceiveLoop(task: task)
        } catch is CancellationError {
            // disconnect() was called mid-validation; state already handled there.
        } catch {
            fail("Connection failed: \(error.localizedDescription)", task: task)
        }
    }

    private func startReceiveLoop(task: URLSessionWebSocketTask) {
        receiveTask?.cancel()
        receiveTask = Task { [weak self] in
            await self?.receiveLoop(task: task)
        }
    }

    /// Runs for the lifetime of one connection, continuously draining
    /// inbound messages (chiefly `frame_result`). A `receive()` failure is
    /// the definitive signal that the connection is gone, so it's the one
    /// place (alongside the delegate close callback) responsible for moving
    /// `status` off `.online` truthfully instead of leaving it stale.
    private func receiveLoop(task: URLSessionWebSocketTask) async {
        log("receive loop started")
        while !Task.isCancelled {
            do {
                let message = try await task.receive()
                guard isCurrent(task) else {
                    log("receive loop stopped (superseded connection)")
                    return
                }
                handleInboundMessage(message)
            } catch {
                guard isCurrent(task) else {
                    log("receive loop stopped (superseded connection)")
                    return
                }
                log("receive failed: \(error.localizedDescription)")
                fail("Connection lost: \(error.localizedDescription)", task: task)
                return
            }
        }
        log("receive loop stopped (cancelled)")
    }

    private func handleInboundMessage(_ message: URLSessionWebSocketTask.Message) {
        guard case .string(let text) = message else {
            log("unknown message type: non-text frame received")
            return
        }
        guard
            let data = text.data(using: .utf8),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let type = json["type"] as? String
        else {
            log("unknown message type: undecodable payload")
            return
        }

        switch type {
        case "frame_result":
            // Decimated on the same 1-in-`frameLogStride` cadence as the send
            // path. This arrives once per delivered frame, so at the target
            // rate an unguarded line here is ~12 prints a second — and the
            // string builds two `Optional.map` allocations before `print` even
            // takes its lock. `metrics.frameResults` is the real count.
            resultLogCounter += 1
            if resultLogCounter % Self.frameLogStride == 1 {
                let seq = json["seq"] as? Int
                let meanIntensity = json["mean_intensity"] as? Double
                let processingMs = json["processing_ms"] as? Double
                log(
                    "frame_result received: seq=\(seq.map(String.init) ?? "?")"
                        + " mean_intensity=\(meanIntensity.map { String($0) } ?? "?")"
                        + " processing_ms=\(processingMs.map { String($0) } ?? "?")"
                )
            }
            #if DEBUG
            frameResultCount += 1
            #endif
            metrics.recordFrameResult()
        default:
            log("unknown message type: \(type)")
        }
    }

    /// True only if `task` is still the socket this client currently owns —
    /// used to ignore work (receive-loop errors, validation results) that
    /// belongs to a connection already superseded by a later connect()/
    /// disconnect(), so a stale callback can never clobber current state.
    private func isCurrent(_ task: URLSessionWebSocketTask) -> Bool {
        guard let current = webSocketTask else { return false }
        return current === task
    }

    /// Fails only if `task` is still current; otherwise the failure belongs
    /// to an already-superseded connection and is logged, not acted on.
    private func fail(_ message: String, task: URLSessionWebSocketTask) {
        guard isCurrent(task) else {
            log("ignoring stale failure (superseded connection): \(message)")
            return
        }
        fail(message)
    }

    private func fail(_ message: String) {
        guard status != .offline else { return }
        log("error: \(message)")
        teardownConnection(cancelWith: .abnormalClosure)
        status = .failed(message)
    }

    private func teardownConnection(cancelWith closeCode: URLSessionWebSocketTask.CloseCode) {
        validationTask?.cancel()
        validationTask = nil
        receiveTask?.cancel()
        receiveTask = nil
        webSocketTask?.cancel(with: closeCode, reason: nil)
        webSocketTask = nil
        session = nil

        // The send window belongs to one socket. Any completion handlers still
        // pending for the old task are ignored by their `isCurrent` guard, so
        // zeroing here is the only thing that reopens the window for the next
        // connection — otherwise a dropped connection would permanently leak
        // window slots and eventually stop sending altogether.
        framesInFlight = 0

        #if DEBUG
        // `isStreamingToTower` means "a stream_start has been sent and not yet
        // matched by a stream_stop". No stream_start survives a socket, so
        // leaving this true across a teardown would be a lie, and would let
        // frames flow to a Tower that never received a start for the
        // connection they arrive on. Set directly rather than via
        // `sendStreamStop()`: there is no socket left to send on.
        isStreamingToTower = false
        #endif
    }

    private func log(_ message: String) {
        #if DEBUG
        print("[Glasses][Tower] \(message)")
        #endif
    }
}

extension TowerClient: URLSessionWebSocketDelegate {
    /// Independent, socket-level signal that the Tower (or the OS) closed
    /// the connection — a second detection path alongside the receive
    /// loop's error case, for whichever one notices first. Hops to the main
    /// actor before touching any state, and only acts if the closed task is
    /// still the one this client currently owns, so it can never race a
    /// receive-loop failure (or a newer connection) into a conflicting
    /// status update.
    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        let closedTaskID = ObjectIdentifier(webSocketTask)
        let codeValue = closeCode.rawValue
        let reasonText = reason.flatMap { String(data: $0, encoding: .utf8) }
        Task { @MainActor [weak self] in
            self?.handleDelegateClose(closedTaskID: closedTaskID, codeValue: codeValue, reason: reasonText)
        }
    }

    private func handleDelegateClose(closedTaskID: ObjectIdentifier, codeValue: Int, reason: String?) {
        guard let current = webSocketTask, ObjectIdentifier(current) == closedTaskID else {
            log("delegate close ignored (stale/superseded connection), code=\(codeValue)")
            return
        }
        log("delegate close: code=\(codeValue) reason=\(reason ?? "none")")
        fail("Tower closed the connection (code \(codeValue))")
    }

    #if DEBUG
    /// Test-only hook: invokes the real `didCloseWith` delegate callback for
    /// the current connection, exercising the exact production code path
    /// without requiring a real socket-level close frame from the network.
    func simulateDelegateCloseForTesting(code: URLSessionWebSocketTask.CloseCode) {
        guard let task = webSocketTask else { return }
        urlSession(session ?? URLSession(configuration: .default), webSocketTask: task, didCloseWith: code, reason: nil)
    }
    #endif
}

/// Races an async operation against a timeout, since
/// `URLSessionWebSocketTask.receive()` has no built-in timeout.
private func withTimeout<T: Sendable>(
    seconds: Int,
    operation: @escaping @Sendable () async throws -> T
) async throws -> T {
    try await withThrowingTaskGroup(of: T.self) { group in
        group.addTask { try await operation() }
        group.addTask {
            try await Task.sleep(for: .seconds(seconds))
            throw TowerClientError.timedOut
        }
        guard let result = try await group.next() else {
            throw TowerClientError.timedOut
        }
        group.cancelAll()
        return result
    }
}

private enum TowerClientError: LocalizedError {
    case timedOut

    var errorDescription: String? {
        switch self {
        case .timedOut: return "Timed out waiting for pong"
        }
    }
}
