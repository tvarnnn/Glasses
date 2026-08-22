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
/// signal for the same event — though note that callback only fires for a real
/// close *frame*, so the receive loop is the one that catches a dropped link.
///
/// A dropped or wedged connection is re-established automatically when
/// `autoReconnect` is set, on a bounded backoff. This does not implement the
/// future frame-streaming protocol beyond what's described here.
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

    /// How much outbound latency a frame may carry before the window that
    /// admitted it is considered oversized.
    ///
    /// The send window's capacity is `targetFPS * this` (see
    /// `SendWindow.capacity(forTargetFPS:latencyBudget:)`), so this constant —
    /// not a frame count — is the reviewable decision. At the 12 fps target it
    /// yields a capacity of 4.
    ///
    /// 1/3 s is chosen against the physical baseline, where the measured send
    /// completion time was ~290 ms early in a run. A capacity of 2 against a
    /// 290 ms slot lifetime admits 6.9 fps, which is what that run delivered;
    /// covering that latency at the target rate needs 4 slots. It is
    /// deliberately not larger: at 12 fps every extra slot is another 83 ms a
    /// frame can be stale before it is even written.
    static let outboundLatencyBudget: TimeInterval = 1.0 / 3.0

    /// How long a *full* send window may go without a single completion before
    /// the socket is treated as wedged and replaced.
    ///
    /// `URLSessionWebSocketTask` cannot cancel or time out one outstanding
    /// `send`, so the only lever is the connection itself — which makes this a
    /// deliberately reluctant threshold rather than a latency target. 2 s is
    /// long enough that ordinary congestion, a cellular handover or a Tailscale
    /// path change is ridden out rather than answered with a reconnect, and
    /// short enough that the 52-second peer stall the physical baseline
    /// recorded is cut to about 4% of its cost.
    ///
    /// Anything above this is unrecoverable staleness regardless: a frame
    /// written 2 s after it was captured is not a real-time frame, so nothing
    /// is lost by abandoning it.
    static let sendStallTimeout: TimeInterval = 2.0

    /// The longest gap between consecutive `sendFrame` calls that still counts
    /// as "the main actor was running normally".
    ///
    /// This exists because a send window slot is held from `reserve` until the
    /// completion handler's hop *back onto the main actor* has run — so a slot
    /// that looks old may be a slow network **or** a busy main actor, and those
    /// are exactly the two diagnoses the rest of this file works to keep apart.
    /// Tearing down a perfectly healthy socket because the main thread hitched
    /// would be the worst possible reading of the evidence.
    ///
    /// A main-actor stall is directly observable here: `sendFrame` is called at
    /// the selection rate (~83 ms apart at 12 fps), so a gap far larger than
    /// that means this actor was not running. When that happens the stall
    /// verdict is skipped for one frame, by which time the completion hops
    /// queued during the hitch have run and released their slots.
    ///
    /// 1 s is ~12 missed frames — far beyond any normal scheduling jitter, and
    /// well under `sendStallTimeout`, so a genuine transport stall is still
    /// caught on the very next frame.
    static let mainActorGapAllowance: TimeInterval = 1.0

    /// The bounded set of sends outstanding on the current socket, and the
    /// pipeline's actual rate limiter. See `SendWindow` for why its capacity is
    /// derived from a latency budget rather than picked.
    private var sendWindow: SendWindow

    /// When `sendFrame` last ran, used only to tell a wedged socket from a
    /// wedged main actor. See `mainActorGapAllowance`. Cleared on teardown, so
    /// the first frame of a new connection never inherits the old one's pulse.
    private var lastSendFrameAt: TimeInterval?

    /// Capacity of the send window, exposed so the developer surface can show
    /// the `capacity / slotLifetime` arithmetic that explains the send rate,
    /// and so tests can assert the derived sizing.
    var maxFramesInFlight: Int { sendWindow.capacity }

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

    // MARK: Reconnect

    /// Whether a connection that drops or stalls is re-established
    /// automatically.
    ///
    /// Defaults to `false` — and the production graph in `ProjectManager`
    /// passes `true`. Off by default because reconnect makes `status` a
    /// *sequence* rather than a settled value, and every existing test that
    /// asserts "a dropped connection ends at `.failed`" is asserting about the
    /// settled value. Opting in explicitly keeps those assertions meaningful
    /// instead of racing a reconnect.
    private let autoReconnect: Bool

    /// Endpoint to return to. Set on every `openConnection(to:)` and cleared
    /// by `disconnect()`, so a user-initiated disconnect is never undone by a
    /// reconnect scheduled moments earlier.
    private var reconnectURL: URL?
    private var reconnectTask: Task<Void, Never>?
    /// Failed attempts since the last connection that *held*. Drives the
    /// backoff and the give-up point.
    private var reconnectAttempt = 0

    /// When the current connection reached `.online`, or `nil` if it has not.
    ///
    /// The budget is refilled from this on the way *down* rather than the way
    /// up, because reaching `.online` proves only that the socket opened and
    /// the Tower answered one ping. A Tower that accepts a connection and then
    /// immediately wedges would otherwise reset the counter on every lap and
    /// reconnect forever — a flap loop the bounded schedule exists to prevent.
    private var becameOnlineAt: TimeInterval?

    /// How long a connection must survive before it counts as healthy enough
    /// to earn a fresh reconnect budget. Comfortably longer than one full
    /// backoff schedule, so a flapping Tower always exhausts the schedule and
    /// stops, while a session that runs for minutes and then drops is treated
    /// as the isolated blip it is.
    private static let reconnectBudgetRefillAfter: TimeInterval = 30

    /// Backoff schedule, in seconds. Bounded on purpose: a Tower that is
    /// simply not running must end at a visible `.failed` rather than retrying
    /// forever behind a pill that never settles, and the app has a manual
    /// Connect control for the deliberate retry.
    ///
    /// The delays total 15.5 s, but each attempt also carries up to the 6 s
    /// pong timeout in `validateConnection`, so giving up against a dead
    /// endpoint takes up to ~45 s.
    private static let reconnectBackoff: [TimeInterval] = [0.5, 1, 2, 4, 8]

    /// The shipped send-window capacity, as the arithmetic that justifies it
    /// rather than as a literal.
    static var defaultMaxFramesInFlight: Int {
        SendWindow.capacity(
            forTargetFPS: FrameRateGate.towerTargetFPS,
            latencyBudget: outboundLatencyBudget
        )
    }

    override init() {
        self.metrics = SenderMetrics()
        self.sendWindow = SendWindow(
            capacity: Self.defaultMaxFramesInFlight,
            stallTimeout: Self.sendStallTimeout
        )
        self.autoReconnect = false
        super.init()
    }

    /// - Parameters:
    ///   - metrics: Shared sender instrumentation.
    ///   - maxFramesInFlight: Overridable so tests can drive the bounded send
    ///     window deterministically. `nil` uses the latency-budgeted capacity
    ///     described on `outboundLatencyBudget`.
    ///   - stallTimeout: Overridable so tests can trip stall detection without
    ///     waiting `sendStallTimeout` seconds. `nil` uses the shipped value.
    ///   - autoReconnect: See the property of the same name.
    ///
    /// Both overrides are `nil`-defaulted and resolved in the body rather than
    /// being computed default arguments: default arguments are evaluated
    /// outside this type's actor, and `defaultMaxFramesInFlight` reads
    /// main-actor-isolated configuration. `GlassesConnection.init` avoids the
    /// same trap for the same reason.
    init(
        metrics: SenderMetrics,
        maxFramesInFlight: Int? = nil,
        stallTimeout: TimeInterval? = nil,
        autoReconnect: Bool = false
    ) {
        self.metrics = metrics
        self.sendWindow = SendWindow(
            capacity: maxFramesInFlight ?? Self.defaultMaxFramesInFlight,
            stallTimeout: stallTimeout ?? Self.sendStallTimeout
        )
        self.autoReconnect = autoReconnect
        super.init()
    }

    /// - Parameter url: The Tower endpoint. Defaults to the real Tower
    ///   (`TowerConfiguration.webSocketURL`); overridable so tests can point
    ///   this at a local mock server instead.
    ///
    /// A caller-initiated connect also refills the reconnect budget: an
    /// exhausted schedule is how the client says "I have stopped trying", and
    /// a deliberate tap on Connect is the user saying to try again.
    func connect(to url: URL = TowerConfiguration.webSocketURL) {
        reconnectAttempt = 0
        openConnection(to: url)
    }

    /// The connect path itself, without refilling the reconnect budget — so a
    /// scheduled reconnect advances through the backoff rather than resetting
    /// it and retrying forever.
    private func openConnection(to url: URL) {
        // Recorded before the in-flight guard below, so that a connect made
        // while one is already under way still retargets a later reconnect. Do
        // not move this after the guard: a pending reconnect would then quietly
        // return to the *previous* endpoint.
        reconnectURL = url

        guard status != .connecting else { return }

        // A caller-initiated connect supersedes any pending reconnect, so the
        // two cannot both open a socket. The reconnect path clears this itself
        // before calling in, so this is a no-op there rather than
        // self-cancellation.
        reconnectTask?.cancel()
        reconnectTask = nil

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
        // Cleared before teardown, so a failure observed on the way down
        // cannot schedule a reconnect the user just asked to stop. `fail()`
        // also refuses to act once `status` is `.offline`, but that is set
        // after teardown — this is what closes the window between the two.
        cancelReconnect()
        teardownConnection(cancelWith: .normalClosure)
        status = .offline
        log("disconnect cleanup complete")
    }

    private func cancelReconnect() {
        reconnectTask?.cancel()
        reconnectTask = nil
        reconnectURL = nil
        reconnectAttempt = 0
        becameOnlineAt = nil
    }

    /// Queues one delayed reconnect attempt, if automatic reconnect is enabled
    /// and the schedule has not been exhausted.
    ///
    /// Reconnect is not an optimisation here — it is what makes stall recovery
    /// possible at all. Tearing down a wedged socket without restoring one
    /// would trade a stalled pipeline for a dead one.
    private func scheduleReconnect() {
        guard autoReconnect, let url = reconnectURL else { return }
        guard reconnectTask == nil else { return }

        // Refill the budget only for a connection that actually held. Reading
        // it here, at the point of failure, is what makes "it worked for a
        // while" mean something — see `becameOnlineAt`.
        if let onlineAt = becameOnlineAt,
           MonotonicClock.now - onlineAt >= Self.reconnectBudgetRefillAfter {
            reconnectAttempt = 0
        }
        becameOnlineAt = nil

        guard reconnectAttempt < Self.reconnectBackoff.count else {
            log("reconnect given up after \(reconnectAttempt) attempts — use Connect to retry")
            return
        }

        let delay = Self.reconnectBackoff[reconnectAttempt]
        reconnectAttempt += 1
        let attempt = reconnectAttempt
        log("reconnect attempt \(attempt) scheduled in \(delay)s")

        reconnectTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            guard let self else { return }
            // Cleared before `connect(to:)` so that call's own
            // supersede-any-pending-reconnect step does not cancel the task it
            // is currently running on.
            self.reconnectTask = nil
            guard self.reconnectURL == url else {
                self.log("reconnect attempt \(attempt) abandoned — endpoint changed or disconnected")
                return
            }
            self.log("reconnect attempt \(attempt) starting")
            self.openConnection(to: url)
        }
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
        let now = MonotonicClock.now

        // How long since the previous frame was offered. This is the main
        // actor's own pulse, and it is what stops a main-actor hitch from
        // being misread as a wedged socket — see `mainActorGapAllowance`.
        let sinceLastFrame = lastSendFrameAt.map { now - $0 }
        lastSendFrameAt = now

        // A full window that has not returned a single slot within
        // `stallTimeout` is a socket that is not draining. There is no way to
        // cancel the outstanding sends individually, so the connection is the
        // unit of recovery — and without this the pipeline simply reports
        // send-window drops for as long as the peer takes to resume, which in
        // the physical baseline was 52 seconds.
        //
        // Checked here, on the send path, rather than from a timer: this runs
        // at the selection rate whenever there are frames to send, which is
        // exactly when a stall costs something. With no frames arriving there
        // is no throughput to lose, and the next frame detects it immediately.
        //
        // The gap test is the false-positive guard. A slot's age includes the
        // completion handler's hop back to this actor, so if this actor has
        // itself been stalled, every slot looks old through no fault of the
        // socket. Requiring that the previous frame was offered recently means
        // the verdict is only ever reached while the main actor is demonstrably
        // running — and one frame later, the hops queued during the hitch have
        // drained. A first frame (`nil`) is treated as a gap, since there is no
        // pulse to judge yet.
        let mainActorWasResponsive = (sinceLastFrame ?? .infinity) <= Self.mainActorGapAllowance
        if mainActorWasResponsive, sendWindow.isStalled(at: now) {
            let age = sendWindow.oldestAge(at: now) ?? 0
            log("send window stalled — \(sendWindow.inFlight) sends outstanding, oldest \(String(format: "%.1f", age))s; replacing the connection")
            // This frame still has to reach a terminal outcome, or every stall
            // would leave one selected frame permanently unaccounted for and
            // `framesUnaccounted` would drift upwards — the one number that
            // exists to prove frames are not quietly queueing. A window drop is
            // the honest label: `isStalled` implies `isFull`, so the frame was
            // dropped for a full window, exactly like the ones before it.
            metrics.recordSendWindowDrop()
            // Recorded after the teardown it describes, so the counter can only
            // ever report recoveries that actually happened.
            fail("Send stalled for \(String(format: "%.1f", age))s", task: task)
            metrics.recordStallRecovery()
            return
        }

        // Checked before encoding, so a frame we are going to drop never costs
        // a JPEG encode.
        guard !sendWindow.isFull else {
            metrics.recordSendWindowDrop()
            if shouldLog {
                log("frame #\(sequence) dropped — \(sendWindow.inFlight) sends already in flight (window \(sendWindow.capacity))")
            }
            return
        }

        // Read again rather than reusing `now`, so the encode figure covers the
        // encode and nothing else — `now` was taken before the stall and
        // window checks above.
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
        let reservedAt = MonotonicClock.now
        metrics.recordEncode(seconds: reservedAt - encodeStart)

        // Cannot fail: the window was checked not-full a few lines above and
        // nothing else can reserve in between — `sendFrame` is main-actor
        // isolated and contains no suspension point. Handled rather than
        // force-unwrapped so a future edit that breaks that property loses a
        // frame instead of trapping in the user's hands.
        guard let token = sendWindow.reserve(at: reservedAt) else {
            metrics.recordSendWindowDrop()
            log("frame #\(sequence) dropped — send window closed between check and reserve")
            return
        }
        metrics.recordSendAttempt(wireBytes: jsonData.count)
        if shouldLog {
            log("frame #\(sequence) sending \(jsonData.count) bytes (\(width)x\(height), jpeg \(jpegData.count) bytes)")
        }

        task.send(.string(jsonText)) { [weak self] error in
            // Sampled here, in the transport's own completion handler, before
            // the main-actor hop. That is the whole point: the difference
            // between this instant and the one measured after the hop
            // separates "the network is slow" from "the main actor is busy",
            // which are opposite diagnoses and were previously folded into a
            // single unmeasured number.
            let completedAt = MonotonicClock.now
            Task { @MainActor in
                guard let self else { return }
                // A completion for a socket this client no longer owns: its
                // reservation was already cleared by teardown, so `release`
                // returns nil and the slot count is left alone — otherwise
                // this would credit a slot on the *next* connection and
                // permanently widen its window. The outcome is also not this
                // connection's to report — but it still has to be *recorded*,
                // or the frame would look permanently in flight and the
                // accounting invariant would false-alarm after every
                // disconnect.
                let releasedAt = MonotonicClock.now
                guard
                    self.isCurrent(task),
                    let slotLifetime = self.sendWindow.release(token, at: releasedAt)
                else {
                    self.metrics.recordSendAbandoned()
                    return
                }
                self.metrics.recordSlotTiming(
                    sendLatency: completedAt - reservedAt,
                    slotLifetime: slotLifetime
                )

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
        // Scoped to one stream bracket, which is a narrower thing than a
        // camera session now that a dropped connection reopens the bracket on
        // its own. The product screen therefore reads
        // `SenderMetrics.frameResults` instead; this counter stays per-bracket
        // and is shown only on the developer surface, where "replies on the
        // current bracket" is the useful reading. A lifetime-cumulative
        // counter would diverge by tens of thousands over a long run and
        // invite reading the pair as a delivery ratio.
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
            // Deliberately does *not* refill the reconnect budget yet — see
            // `becameOnlineAt`. Reaching `.online` is not evidence of a working
            // connection; staying there is.
            becameOnlineAt = MonotonicClock.now
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
        // After the status is settled, so an observer that reacts to `.failed`
        // sees a consistent client. Documented URLSession behaviour is that
        // one send error fails *all* outstanding work on the task, so the
        // sibling completions arriving next are already stale by `isCurrent`
        // and cannot schedule a second reconnect.
        scheduleReconnect()
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
        // clearing here is the only thing that reopens the window for the next
        // connection — otherwise a dropped connection would permanently leak
        // window slots and eventually stop sending altogether. `SendWindow`
        // does not rewind its token counter, so those late completions cannot
        // release a slot belonging to the *next* connection either.
        sendWindow.reset()
        // Belongs to the socket that is going away: the next connection's
        // first frame must not be judged against the old one's pulse.
        lastSendFrameAt = nil

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
