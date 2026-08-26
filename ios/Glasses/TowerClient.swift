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

/// One `frame_result` message, as the Tower actually sends it today.
///
/// Not a guess at a future protocol — every field here is one the Tower
/// builds in `tower/tower/routes/ws.py:148-165`, and every one is optional (or
/// empty-by-default) because the decoder must not fabricate a value the
/// message omitted.
///
/// ## The earlier version of this comment was wrong, and it cost a cartridge
///
/// It read: *"The Tower's whole per-frame vocabulary is `seq`,
/// `mean_intensity` and `processing_ms` — it runs one fixed handler and has no
/// module runtime."* Both halves were false. `ws.py` sends **five keys
/// unconditionally** — `seq`, `processing_ms`, `result_value`, `result_label`
/// and `stage_ms` — and adds `mean_intensity` and `metrics` when the
/// experiment produced them. The Tower does have a module runtime:
/// `tower/tower/main.py` builds a `ModuleContainer` around a live
/// `ExperimentalCVModule`, and a running Tower reports `module_state: active`
/// on `/health`.
///
/// So `result_value` and `result_label` — the experiment's own answer, the
/// only thing the Tower says about what it *concluded* rather than how long it
/// took — were arriving on every single frame and being dropped on the floor,
/// while the Experimental CV Lab workspace told the wearer the Tower "cannot
/// run experiments yet".
///
/// The Tower's registry says the same thing from its side: `experimental_cv`
/// is `not_offered` on the result channel because *"results already reach the
/// client on `frame_result`"*. They do. This type is now the shape of what
/// actually arrives.
struct TowerFrameResult: Equatable, Sendable {
    /// The frame this result answers, matching the `seq` the app sent.
    let sequence: Int?
    /// Mean pixel intensity, 0...1. Present only when the experiment reported
    /// one — `nil` means the experiment said nothing, never that the frame was
    /// dark.
    let meanIntensity: Double?
    /// How long the Tower spent on the frame.
    let processingMs: Double?
    /// The experiment's headline number. Its meaning is the experiment's, not
    /// this app's: it is paired with `resultLabel` and must never be rendered
    /// without it, because a bare number implies a unit nobody promised.
    let resultValue: Double?
    /// The experiment's own name for what it measured. The one piece of
    /// provenance on this channel.
    let resultLabel: String?
    /// Per-stage timings inside the Tower's own processing, name -> ms.
    /// Empty when the Tower sent an empty object; there is no distinction on
    /// the wire between empty and absent, and none is invented here.
    let stageMs: [String: Double]
    /// Additive measurements, name -> number, omitted entirely when empty.
    /// Deliberately numbers only: `ws.py` calls this "a MEASUREMENT channel,
    /// not the structured result channel", and the structured one is blocked
    /// on module-contract work this app must not pre-empt.
    let metrics: [String: Double]
}

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

    /// The most recent `frame_result` the Tower returned.
    ///
    /// The Tower's reply already carries a `mean_intensity`, and until now it
    /// was formatted into a decimated log line and thrown away. It is the only
    /// thing the Tower currently says *about a frame's content*, which makes it
    /// the one piece of real evidence the app can show that the round trip is
    /// doing something rather than merely completing. Surfacing it is what lets
    /// a workspace describe what the Tower actually does today without
    /// inventing a capability it does not have.
    ///
    /// Republished at the reply rate, like `frameResultCount` beside it.
    @Published private(set) var latestFrameResult: TowerFrameResult?

    #endif

    /// True between a sent `stream_start` and the matching `stream_stop`.
    /// `sendFrame` will not forward anything while this is false, so a frame
    /// captured in the brief window after `stopCameraSession()` fires (but
    /// before DAT actually tears the stream down) can never reach the Tower.
    ///
    /// **Not `#if DEBUG`, while everything that writes it is.** The two
    /// functions that set it — `sendStreamStart()` and `sendStreamStop()` —
    /// live in the DEBUG-only frame path, so in a Release build this is
    /// permanently `false`, which is the truth about a build with no capture
    /// control on any screen.
    ///
    /// It is readable in both configurations because `TowerWorldBuilderClient`
    /// needs it: "this phone has a capture open" is a fact about the phone's
    /// own situation, and it is what `WorldSessionGate` compares the Tower's
    /// session against. A Release build asks the same question and correctly
    /// gets "no", rather than the question being unaskable there.
    @Published private(set) var isStreamingToTower = false

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

    // MARK: Result channel

    /// The Tower's most recent capability declaration, cached.
    ///
    /// Requested once per connection, immediately after the pong — the contract
    /// requires discovery to follow handshake validation, and asking earlier
    /// would read our own reply into the handshake.
    ///
    /// **Deliberately not cleared on teardown.** What the Tower can do is a
    /// property of the Tower's build, not of this socket. Clearing it would
    /// turn every dropped connection into `.noContract` — "this will never
    /// work" — when the truthful reading is `.towerUnreachable`, and those two
    /// call for opposite responses from a person.
    @Published private(set) var cartridgeDeclaration: TowerCartridgeDeclaration?

    /// Every result-channel message, in arrival order.
    ///
    /// A subject rather than four `@Published` properties because ordering
    /// between them is load-bearing: `result_subscribed` is followed
    /// immediately by the first `cartridge_result`, and a consumer that saw
    /// them out of order would file the snapshot against no subscription.
    private let resultEvents = PassthroughSubject<CartridgeResultEvent, Never>()

    /// The result channel, for whoever owns a cartridge's contract.
    ///
    /// `TowerClient` decodes the envelope and nothing else. It does not know
    /// what a world is, does not subscribe on anyone's behalf, and holds no
    /// cartridge state — the cartridge client owned by `ProjectManager` does
    /// all three. That split is what keeps this file cartridge-blind.
    var cartridgeResults: AnyPublisher<CartridgeResultEvent, Never> {
        resultEvents.eraseToAnyPublisher()
    }

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

    /// - Parameter url: The Tower endpoint. `nil` uses the real Tower
    ///   (`TowerConfiguration.webSocketURL`); overridable so tests can point
    ///   this at a local mock server instead. `nil`-defaulted and resolved in
    ///   the body for the reason `init` gives: a default argument is evaluated
    ///   outside this type's actor, and `webSocketURL` is main-actor isolated.
    ///
    /// A caller-initiated connect also refills the reconnect budget: an
    /// exhausted schedule is how the client says "I have stopped trying", and
    /// a deliberate tap on Connect is the user saying to try again.
    func connect(to url: URL? = nil) {
        let url = url ?? TowerConfiguration.webSocketURL
        // Refilled only when this call is actually going to open a socket. It
        // used to be reset unconditionally, before `openConnection`'s
        // `.connecting` guard — so a redundant tap during an in-flight connect
        // did nothing visible while silently resurrecting an exhausted
        // schedule. The budget is meant to say "I have stopped trying"; a
        // no-op must not undo that.
        if status != .connecting { reconnectAttempt = 0 }
        openConnection(to: url)
    }

    /// Connects only if nothing is connected or in flight, and **without**
    /// refilling the reconnect budget.
    ///
    /// The entry point for automation — app launch, specifically. It is
    /// deliberately not `connect()`: that call means "the user asked to try
    /// again", which is why it refills the budget and why it is allowed to
    /// replace a live connection. Neither is true of code running on its own
    /// initiative, and routing automation through the same door would dissolve
    /// the bound that stops a dead Tower from being retried forever.
    ///
    /// Guarding on `.offline` also makes this safe to call more than once: it
    /// will not disturb a healthy connection, cancel a pending reconnect, or
    /// restart a schedule that has already given up. A Tower that has failed
    /// stays failed and visible until the user acts.
    func connectIfIdle(to url: URL? = nil) {
        let url = url ?? TowerConfiguration.webSocketURL
        guard status == .offline else {
            log("automatic connect skipped — status is \(status)")
            return
        }
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
            // `[weak self]` on the Task itself, not inherited from the send
            // completion's capture. A weak capture is a mutable binding, and
            // reading the enclosing closure's copy from concurrently-executing
            // code is an error under the Swift 6 language mode. Re-capturing
            // here is evaluated when the Task is created, which is allowed,
            // and keeps the lifetime semantics identical.
            Task { @MainActor [weak self] in
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
        // Scoped to the bracket for the same reason as the count above: a reply
        // from the previous bracket displayed against a fresh one is a stale
        // claim about the current session.
        latestFrameResult = nil
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
        // Cleared with the bracket it belongs to. The tile that shows it is
        // captioned "latest Tower reply", and after a stop there is no current
        // reply - leaving the last one on screen would date it silently.
        latestFrameResult = nil
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
            // Re-captured weakly here for the same reason as in `sendFrame`.
            Task { @MainActor [weak self] in
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

    // MARK: - Result channel: outbound

    /// Asks the Tower what it can report on.
    ///
    /// Sent once per connection, from `validateConnection` after the pong has
    /// been read — never before. Not `#if DEBUG`: the result channel is
    /// read-only and says nothing about frames, so a Release build that cannot
    /// stream is still entitled to a truthful answer about what the Tower can
    /// do.
    func requestCartridgeDeclaration() {
        sendResultMessage(["type": "cartridges"], label: "cartridges")
    }

    /// Opens a subscription. The reply is a `result_subscribed` followed
    /// immediately by a complete snapshot, whatever cursor was sent.
    ///
    /// `contract` is included so the Tower refuses outright rather than
    /// serving a payload this build was not written against — a
    /// `contract_mismatch` error is a better outcome than a silent
    /// misinterpretation.
    func subscribeToResults(cartridge: String, resultType: String, contract: String) {
        sendResultMessage(
            [
                "type": "result_subscribe",
                "cartridge": cartridge,
                "result_type": resultType,
                "contract": contract,
            ],
            label: "result_subscribe(\(cartridge))"
        )
    }

    /// Closes a subscription. Not required before disconnecting — the Tower
    /// treats a closed socket as sufficient cleanup — so this exists for the
    /// case where the connection outlives the reason to be subscribed.
    func unsubscribeFromResults(subscriptionID: String) {
        sendResultMessage(
            ["type": "result_unsubscribe", "subscription_id": subscriptionID],
            label: "result_unsubscribe(\(subscriptionID))"
        )
    }

    /// Shared send path for the three result-channel messages.
    ///
    /// **A send failure here is logged and not escalated**, which is the one
    /// way this differs from `sendLifecycleMarker`. A lifecycle marker defines
    /// a frame bracket and losing one corrupts the counts on both sides, so
    /// that path fails the connection; a subscribe is a request for a report,
    /// and tearing down the socket the camera is streaming over because a
    /// capability query did not land would let the result channel do the one
    /// thing the contract promises it cannot — affect the frame path. If the
    /// socket really is gone, the receive loop notices it on its own terms.
    private func sendResultMessage(_ object: [String: Any], label: String) {
        guard status == .online, let task = webSocketTask else {
            log("\(label) not sent — Tower not online (status=\(status))")
            return
        }
        guard
            let jsonData = try? JSONSerialization.data(withJSONObject: object),
            let jsonText = String(data: jsonData, encoding: .utf8)
        else {
            log("\(label) failed to serialize JSON payload")
            return
        }
        task.send(.string(jsonText)) { [weak self] error in
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let error {
                    self.log("\(label) send failed (not escalated): \(error.localizedDescription)")
                } else {
                    self.log("\(label) sent")
                }
            }
        }
    }

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
            // After the pong, never before. The Tower never speaks first, so
            // nothing could have arrived early — but asking before validating
            // would mean reading our own reply into the handshake, which is
            // the failure the contract warns about. The receive loop is
            // already running, so the answer has somewhere to land.
            requestCartridgeDeclaration()
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
            let seq = json["seq"] as? Int
            let meanIntensity = json["mean_intensity"] as? Double
            let processingMs = json["processing_ms"] as? Double
            let resultValue = json["result_value"] as? Double
            let resultLabel = json["result_label"] as? String
            // `?? [:]` rather than an optional: the Tower sends `stage_ms`
            // unconditionally but may send it empty, and `metrics` is omitted
            // when empty. Both mean "no stages/measurements to report", so
            // collapsing absent and empty here loses nothing.
            let stageMs = json["stage_ms"] as? [String: Double] ?? [:]
            // Not `metrics`: that name is this client's `SenderMetrics`, and
            // shadowing it here silently rebinds every use below.
            let extraMetrics = json["metrics"] as? [String: Double] ?? [:]

            resultLogCounter += 1
            if resultLogCounter % Self.frameLogStride == 1 {
                log(
                    "frame_result received: seq=\(seq.map(String.init) ?? "?")"
                        + " mean_intensity=\(meanIntensity.map { String($0) } ?? "?")"
                        + " processing_ms=\(processingMs.map { String($0) } ?? "?")"
                )
            }
            #if DEBUG
            frameResultCount += 1
            // Decoding moved above the log gate so the value is kept for every
            // reply rather than only for the one-in-twelve that gets logged —
            // the counters were always exact and the surfaced value has to be
            // too. It is three optional casts on an existing dictionary, at the
            // reply rate; the publish that follows is the only real cost, and
            // it is the same order as `frameResultCount` next to it.
            latestFrameResult = TowerFrameResult(
                sequence: seq,
                meanIntensity: meanIntensity,
                processingMs: processingMs,
                resultValue: resultValue,
                resultLabel: resultLabel,
                stageMs: stageMs,
                metrics: extraMetrics
            )
            #endif
            metrics.recordFrameResult()

        // MARK: Result channel
        //
        // Every case below is additive and none of them can affect the frame
        // path: they decode, publish, and return. Nothing here touches
        // `status`, the send window, or the stream bracket — which is the iOS
        // half of the guarantee the contract makes on the Tower side.

        case "cartridges":
            let declaration = TowerCartridgeDeclaration(json: json)
            log(
                "cartridges declared: "
                    + declaration.offers
                    .map { "\($0.cartridge)/\($0.resultType) available=\($0.available)" }
                    .joined(separator: ", ")
            )
            cartridgeDeclaration = declaration
            resultEvents.send(.declaration(declaration))

        case "result_subscribed":
            guard let ack = CartridgeSubscriptionAck(json: json) else {
                log("result_subscribed could not be decoded")
                return
            }
            log("result_subscribed: \(ack.subscriptionID) \(ack.cartridge)/\(ack.resultType)")
            resultEvents.send(.subscribed(ack))

        case "result_unsubscribed":
            guard let id = json["subscription_id"] as? String else { return }
            log("result_unsubscribed: \(id)")
            resultEvents.send(.unsubscribed(subscriptionID: id))

        case "cartridge_result":
            guard let envelope = CartridgeResultEnvelope(json: json) else {
                log("cartridge_result could not be decoded")
                return
            }
            // Decimated like `frame_result`, and for a weaker reason: this
            // arrives at most twice a second. One line per change rather than
            // one per heartbeat is still the useful reading.
            if envelope.revisionChanged {
                log(
                    "cartridge_result: \(envelope.cartridge)/\(envelope.resultType)"
                        + " seq=\(envelope.sequence.map(String.init) ?? "?")"
                        + " revision=\(envelope.revision ?? "?")"
                        + " coalesced=\(envelope.coalesced)"
                )
            }
            resultEvents.send(.result(envelope))

        case "result_error":
            guard let error = CartridgeResultError(json: json) else {
                log("result_error could not be decoded")
                return
            }
            log("result_error: \(error.reason) — \(error.message)")
            resultEvents.send(.failed(error))

        case "protocol_error":
            // The Tower telling us it does not implement something we sent.
            // Additive on its side and non-fatal on ours: previously an
            // unrecognised message produced only a server-side log line, so
            // "not implemented" and "lost in flight" were indistinguishable
            // from here.
            let messageType = json["message_type"].map { String(describing: $0) } ?? "nil"
            log("protocol_error from Tower: \(json["reason"] as? String ?? "?") for \(messageType)")

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
        // `URLSession` retains its delegate — this object — until it is
        // invalidated. Dropping the reference is not enough: without this, the
        // session, its delegate queue and this client all outlive every
        // teardown, once per connect. That was survivable when connecting was
        // something the user did by tapping; it is not now that `autoReconnect`
        // re-opens on a schedule whose budget refills after every 30s of
        // healthy connection, which is once per drop on exactly the flaky link
        // this client was built for.
        //
        // `invalidateAndCancel` rather than `finishTasksAndInvalidate`: the
        // only task was cancelled on the line above, so there is nothing left
        // to finish, and waiting would keep the session alive past the point
        // this method promises it is gone. Late delegate callbacks from the
        // invalidated session are already ignored — `webSocketTask` is nil by
        // then, so `handleDelegateClose`'s identity guard drops them.
        session?.invalidateAndCancel()
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
        // Scoped to the socket that carried it, for the same reason as the
        // line above. `HomeWorkspaceView` renders this under the caption
        // "latest Tower reply", and a reading from a connection that is gone
        // is not the latest anything. It was cleared only by the stream
        // bracket, so a socket that dropped mid-capture left the dead
        // connection's number on screen for the whole outage — and forever
        // once the reconnect budget is spent, because no `stream_stop` is
        // ever sent for a socket that is not there.
        latestFrameResult = nil
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
