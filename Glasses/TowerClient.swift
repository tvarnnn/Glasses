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
    /// unchanged, and nothing reads it to make a decision. Note the render
    /// cost is bounded by the 1-in-30 frame throttle in `GlassesConnection`:
    /// if that throttle is ever relaxed, this invalidates the view tree at the
    /// full frame rate rather than ~1 Hz.
    @Published private(set) var frameResultCount = 0

    /// True between a sent `stream_start` and the matching `stream_stop`.
    /// `sendFrame` will not forward anything while this is false, so a frame
    /// captured in the brief window after `stopCameraSession()` fires (but
    /// before DAT actually tears the stream down) can never reach the Tower.
    /// `@Published` for the developer surface only — the send path still reads
    /// the stored value directly and its semantics are unchanged.
    @Published private(set) var isStreamingToTower = false
    #endif

    private var session: URLSession?
    private var webSocketTask: URLSessionWebSocketTask?
    private var validationTask: Task<Void, Never>?
    private var receiveTask: Task<Void, Never>?

    override init() {
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
        guard status == .online, let task = webSocketTask else {
            log("frame #\(sequence) not sent — Tower not online (status=\(status))")
            return
        }
        guard isStreamingToTower else {
            log("frame #\(sequence) not sent — no stream_start sent yet (or stream_stop already sent)")
            return
        }
        guard let jpegData = image.jpegData(compressionQuality: 0.5) else {
            log("frame #\(sequence) failed to encode as JPEG")
            return
        }
        log("frame #\(sequence) encoded (\(jpegData.count) bytes, \(width)x\(height))")

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
            log("frame #\(sequence) failed to serialize JSON payload")
            return
        }

        task.send(.string(jsonText)) { [weak self] error in
            Task { @MainActor in
                guard let self else { return }
                if let error {
                    self.log("frame #\(sequence) send failed: \(error.localizedDescription)")
                    self.fail("Send failed: \(error.localizedDescription)", task: task)
                } else {
                    self.log("frame #\(sequence) sent (\(jsonText.utf8.count) bytes over the wire)")
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
        isStreamingToTower = true
        sendLifecycleMarker(type: "stream_start")
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
        sendLifecycleMarker(type: "stream_stop")
    }

    /// Shared send path for the two stream lifecycle markers — same
    /// WebSocket, same fire-and-forget `send` used by `sendFrame`, no new
    /// connection, no reply awaited.
    private func sendLifecycleMarker(type: String) {
        guard status == .online, let task = webSocketTask else {
            log("\(type) not sent — Tower not online (status=\(status))")
            return
        }
        guard
            let jsonData = try? JSONSerialization.data(withJSONObject: ["type": type]),
            let jsonText = String(data: jsonData, encoding: .utf8)
        else {
            log("\(type) failed to serialize JSON payload")
            return
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
            let seq = json["seq"] as? Int
            let meanIntensity = json["mean_intensity"] as? Double
            let processingMs = json["processing_ms"] as? Double
            log(
                "frame_result received: seq=\(seq.map(String.init) ?? "?")"
                    + " mean_intensity=\(meanIntensity.map { String($0) } ?? "?")"
                    + " processing_ms=\(processingMs.map { String($0) } ?? "?")"
            )
            #if DEBUG
            frameResultCount += 1
            #endif
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
