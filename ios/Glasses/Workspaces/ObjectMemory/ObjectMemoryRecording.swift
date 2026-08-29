//
//  ObjectMemoryRecording.swift
//  Glasses
//

import Combine
import Foundation

/// One tap that starts both halves of remembering: the Tower's producer, and
/// the glasses camera.
///
/// ## Why this type exists
///
/// Before it, Object Memory's Start button started the *producer* and nothing
/// else. A person who pressed it on a phone with no capture running got an
/// `active` session with `attached_capture_id: null`, no frames, no records,
/// and no sentence anywhere on the screen explaining that they also had to go
/// to Home and press a second, differently-named button first. The cartridge
/// was not self-contained, and the screen did not say so.
///
/// ## What it owns, and what it very deliberately does not
///
/// It owns **sequencing and honesty**, and no camera code whatsoever. The
/// camera is `GlassesConnection` — still the only type in this app that talks
/// to DAT, still reached through `startCameraSession()` / `stopCameraSession()`
/// and nothing else. The Tower's producer is `CartridgeSessionHTTPClient`
/// behind `ObjectMemoryClient`, unchanged. This composes the two.
///
/// Both are reached through protocols rather than concrete types, and that is
/// not ceremony: `GlassesConnection`'s capture surface is `#if DEBUG`, needs a
/// paired device and a permission grant, and cannot be driven from a test at
/// all. A seam is the only way this sequencing is testable, and untested
/// sequencing is exactly where the race below would live.
///
/// ## The one rule inherited from `ObjectMemorySession.swift`
///
/// **`state` is intent. `following` is fact.** Every phase this type publishes
/// that claims something is being recorded is derived from
/// `snapshot.isFollowingACapture`, and never from `state`. The whole reason
/// `.waitingToBeFollowed` and `.notObserved` are separate cases from
/// `.remembering` is that "we asked" must never be drawn as "it is happening".

// MARK: - The camera seam

/// The half of `GlassesConnection` this cartridge is allowed to reach.
///
/// Five members, all of which already existed or were added for this: there is
/// no camera behaviour here that `GlassesConnection` does not already own, and
/// there is deliberately no `pause`. **DAT exposes no way to pause a stream**
/// — `GlassesConnection` only ever calls `session.start()`, `session.stop()`,
/// `stream.start()` and `camera.stop()` — so a `pauseCapture()` on this
/// protocol would be a method with nothing truthful to call.
@MainActor
protocol ObjectMemoryCaptureOwner: AnyObject {
    /// What claim this app holds on the glasses camera right this moment.
    var captureClaim: CaptureClaim { get }

    /// Every later reading of `captureClaim`. Subscribed rather than polled, so
    /// a capture that ends underneath this screen — glasses folded, Bluetooth
    /// dropped, Stop pressed on Home — reaches the phase without a timer.
    var captureClaimUpdates: AnyPublisher<CaptureClaim, Never> { get }

    /// Why the last `startCameraSession()` did not proceed, or `nil` if it did.
    /// Read immediately after the call; see `CaptureStartRefusal`.
    var lastCaptureStartRefusal: CaptureStartRefusal? { get }

    func startCameraSession()
    func stopCameraSession()
}

#if DEBUG
/// `GlassesConnection` already satisfies every requirement, so the conformance
/// is empty by construction — which is the point. If this extension ever needs
/// a body, a second camera path is being written and the invariant that there
/// is exactly one is being broken.
///
/// `#if DEBUG` because the members it conforms with are: the whole capture
/// surface of `GlassesConnection` is DEBUG-only, exactly as Home's and World
/// Builder's controls are. In a Release build the coordinator below is
/// constructed with no camera at all and says so.
extension GlassesConnection: ObjectMemoryCaptureOwner {}
#endif

// MARK: - What the screen may say about remembering

/// Where a run of remembering has actually got to.
///
/// **Sixteen cases rather than three, and every extra one is a refusal to
/// round.** `starting`, `waitingToBeFollowed`, `notObserved` and `remembering`
/// are four different truths that a single `isRecording: Bool` would collapse
/// into one claim, and three of the four would be false claims. The Tower's own
/// contract makes the distinction unavoidable: a Start answers 200 with
/// `state: "active"` and `attached_capture_id: null` — an honest, successful,
/// documented answer that means *nothing is being recorded yet*.
nonisolated enum ObjectMemoryRecordingPhase: Equatable, Sendable {
    /// Nothing has been asked for from this screen, and nothing has been read.
    case idle

    /// A Start is in flight: the Tower has been asked, or the camera is being
    /// asked. **Not a claim that either succeeded.**
    case starting

    /// The Tower accepted the Start, and no producer has attached to a
    /// recording yet. Legal, expected for the first seconds, and bounded — see
    /// `convergenceBudget`.
    case waitingToBeFollowed

    /// The wait ran out, or a later read found the same thing: the session is
    /// active and `following` is empty.
    ///
    /// **This is the case the whole type exists for.** It is not an error, it
    /// is not "recording", and it is not "stopped". It is *asked for, and not
    /// observed*, and it is what a Start against a Tower whose producer never
    /// attached looks like from here.
    case notObserved

    /// A producer is alive on a recording. The only phase that may be drawn as
    /// recording, and it is read from `following`.
    case remembering

    case pausing
    /// Pause honoured, and nothing is being followed.
    case paused
    case resuming
    case stopping
    /// Stop honoured, and nothing is being followed.
    case stopped

    /// The Tower reported the action as honoured **and** a producer alive on a
    /// recording. The reproduced `SIGTERM` failure; shown loudly, never
    /// reconciled.
    case stillFollowing(after: CartridgeSessionAction)

    /// The session could not be read. **The liveness claim is dropped**, not
    /// held: a screen that keeps saying "remembering" after it stopped being
    /// able to check is asserting something it no longer knows.
    case cannotTell(CartridgeFailure)

    /// A 409. An answer, not a failure — it says which control would have
    /// worked.
    case refused(CartridgeSessionRefusal)

    /// The Tower agreed to remember and the glasses camera did not start.
    /// Carries which of the five reasons it was.
    case cameraRefused(CaptureStartRefusal)

    /// This Tower has no producer to start, or no session surface at all.
    case unsupported

    case failed(CartridgeFailure)

    /// Whether a producer is confirmed alive on a recording.
    ///
    /// `true` for exactly two phases, and both of them were read from
    /// `following`. Every other phase — including `starting`,
    /// `waitingToBeFollowed` and `notObserved`, all three of which follow a
    /// successful Start — is `false`, because a successful Start is not a
    /// recording.
    var isFollowingACapture: Bool {
        switch self {
        case .remembering, .stillFollowing: return true
        case .idle, .starting, .waitingToBeFollowed, .notObserved, .pausing, .paused,
            .resuming, .stopping, .stopped, .cannotTell, .refused, .cameraRefused,
            .unsupported, .failed:
            return false
        }
    }

    /// Whether an action asked for from this screen has not resolved yet.
    var isInFlight: Bool {
        switch self {
        case .starting, .pausing, .resuming, .stopping: return true
        default: return false
        }
    }
}

/// Everything one sentence about remembering has to be written from.
///
/// The phase alone is not enough, and the gap is the honest half: a session can
/// be `paused` while the glasses camera keeps streaming frames to the Tower,
/// because Pause detaches a *producer* and DAT has no pause at all. A reading
/// that carried only the phase would let the screen say "paused" beside a live
/// camera and never mention it.
nonisolated struct ObjectMemoryRecordingReading: Equatable, Sendable {
    let phase: ObjectMemoryRecordingPhase
    /// What this app's claim on the glasses camera is, independently of the
    /// Tower.
    let camera: CaptureClaim
    /// Whether the capture that is running was started by *this* screen. Decides
    /// whether Stop may end it — and decides which sentence is true about what
    /// Stop just did.
    let cameraStartedHere: Bool
    /// Whether this build can start a capture at all. `false` in Release, where
    /// the whole capture surface is compiled out.
    let cameraIsReachable: Bool
}

// MARK: - The coordinator

/// Start, Pause, Resume and Stop for Object Memory, composed over the Tower's
/// producer and the glasses camera.
///
/// ## The start order, and why it is this way round
///
/// 1. **`POST start` first, before any capture exists.** The contract is
///    explicit that this is supported: "Start before the camera is normal. The
///    session goes `active` with `attached_capture_id: null` and the next
///    capture to open finds the gate open." Doing it first is what makes the
///    common case lossless.
///
///    The other order loses frames or loses everything. A producer that
///    attaches to a capture already in progress runs with
///    `--attach-mode from-now` and **does not read back the earlier frames**,
///    so starting the camera first throws away however long the round trip to
///    the Tower took. Worse, if the Start were to fail after the camera came
///    up, a capture would be open against a closed gate with a camera running
///    and nothing remembering.
///
/// 2. **Then the camera, and only if nothing already holds it.** Home and World
///    Builder can each have started it, and `startCameraSession()` refuses when
///    a session exists. Calling it anyway would be asking for a refusal and
///    then having to explain one.
///
/// 3. **Then converge on `following`, with a deadline.** A 200 from Start is
///    intent. Whether a producer actually attached is `following`, and that is
///    read back, repeatedly, until it is true or the budget runs out. If the
///    budget runs out with the session `active` and nothing followed, the
///    screen says exactly that — `notObserved` — rather than claiming a
///    recording that this app has never observed.
///
/// ## Ownership
///
/// Whether *this* screen started the capture is recorded, and Stop honours it.
/// A capture started on Home is left running by Object Memory's Stop, because
/// ending it would silently reach across two other screens and turn off a
/// stream somebody else asked for. The copy says which of the two happened.
@MainActor
final class ObjectMemoryRecordingCoordinator: ObservableObject {

    /// How often `following` is re-read while a Start is converging.
    ///
    /// The same three seconds as `ObjectMemoryViewModel.livenessRefreshInterval`.
    /// Written out rather than read from it because that one is isolated to the
    /// main actor and this default argument is not — so the two are tied
    /// together by `testTheConvergenceCadenceMatchesTheWatchLoop` instead,
    /// which fails the day either moves.
    nonisolated static let convergenceInterval: Duration = .seconds(3)

    /// How long a Start may go unobserved before the screen says so.
    ///
    /// **Bounded, deliberately, and not a timeout in the failure sense**
    /// (Rule 15). Nothing is cancelled when it expires and nothing is reported
    /// as broken: the session stays exactly as the Tower has it, and the only
    /// thing that changes is the sentence on screen, from "waiting" to "asked
    /// for, and not observed". Twelve seconds is four reads at the interval
    /// above — long enough for a producer to spawn and open its first record,
    /// short enough that a person is not left watching a spinner over a
    /// producer that never arrived.
    nonisolated static let convergenceBudget: Duration = .seconds(12)

    /// Where a run of remembering has got to. Never set from a button tap —
    /// only from an answer, or from the absence of one at a deadline.
    @Published private(set) var phase: ObjectMemoryRecordingPhase = .idle

    /// This app's claim on the glasses camera, kept live by a subscription so
    /// that a capture ending underneath this screen is visible here without a
    /// poll.
    @Published private(set) var cameraClaim: CaptureClaim

    /// Whether the capture currently running was started by this screen.
    @Published private(set) var startedTheCamera = false

    /// Whether an action asked for here has not finished yet. Drives the
    /// controls' `disabled`, which is what makes a double tap a no-op rather
    /// than two overlapping sequences.
    @Published private(set) var isActing = false

    /// Called when a run of remembering ends, so the records list below can
    /// show what was just written.
    ///
    /// A closure rather than a call into `ObjectMemoryViewModel`, because the
    /// category the reader narrowed to lives on the view model and re-asking
    /// for everything would silently widen their question. The view supplies
    /// the closure and keeps that decision.
    var refreshRecords: (@MainActor () -> Void)?

    private let client: any ObjectMemoryClient
    private let camera: (any ObjectMemoryCaptureOwner)?
    private let convergenceInterval: Duration
    private let convergenceBudget: Duration
    private var cancellables: Set<AnyCancellable> = []
    /// The action currently in flight. Bounded by `convergenceBudget`, so the
    /// strong reference it holds to this object is bounded too.
    private var work: Task<Void, Never>?

    /// - Parameters:
    ///   - camera: the app's single camera owner, or `nil` in a build or a
    ///     preview that has none. `nil` is a supported state, not a degraded
    ///     one: the Tower half still works and the copy says the camera half
    ///     cannot be reached.
    ///   - client: the Object Memory client, which owns the session transport
    ///     and does the read-back after every action.
    ///   - interval / budget: injectable so a test can converge in
    ///     milliseconds. Nothing else may change them.
    init(
        camera: (any ObjectMemoryCaptureOwner)?,
        client: any ObjectMemoryClient,
        interval: Duration = ObjectMemoryRecordingCoordinator.convergenceInterval,
        budget: Duration = ObjectMemoryRecordingCoordinator.convergenceBudget
    ) {
        self.camera = camera
        self.client = client
        self.convergenceInterval = interval
        self.convergenceBudget = budget
        self.cameraClaim = camera?.captureClaim ?? .unclaimed

        // Same shape as `ObjectMemoryViewModel`'s two subscriptions, and for
        // the same reason: the publisher is the only thing that reports a
        // capture ending for a reason nobody on this screen asked for.
        camera?.captureClaimUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] claim in self?.cameraClaimChanged(claim) }
            .store(in: &cancellables)

        client.sessionUpdates
            .receive(on: DispatchQueue.main)
            .sink { [weak self] session in self?.sessionChanged(session) }
            .store(in: &cancellables)
    }

    deinit { work?.cancel() }

    // MARK: What the screen reads

    /// The whole truth, in one value. See `ObjectMemoryRecordingReading`.
    var reading: ObjectMemoryRecordingReading {
        ObjectMemoryRecordingReading(
            phase: phase,
            camera: cameraClaim,
            cameraStartedHere: startedTheCamera,
            cameraIsReachable: camera != nil
        )
    }

    /// Which verb the primary button sends.
    ///
    /// Start whenever nothing is under way, Stop whenever something is — including
    /// `notObserved`, where a session exists on the Tower even though nothing
    /// has been observed following it. Offering Start there would leave no way
    /// to clear a session that is open and doing nothing.
    var primaryAction: CartridgeSessionAction {
        switch phase {
        case .starting, .waitingToBeFollowed, .notObserved, .remembering, .stillFollowing,
            .pausing, .paused, .resuming, .stopping:
            return .stop
        case .idle, .stopped, .cannotTell, .refused, .cameraRefused, .unsupported, .failed:
            return .start
        }
    }

    // MARK: Asking

    /// Sends one verb through the composed lifecycle.
    ///
    /// The vocabulary is still read off the Tower's own `actions` list by the
    /// view; this is the only place that decides what each verb *does* to the
    /// camera, which is why the view no longer reaches `ObjectMemoryClient.apply`
    /// directly.
    func apply(_ action: CartridgeSessionAction) {
        switch action {
        case .start: start()
        case .pause: pause()
        case .resume: resume()
        case .stop: stop()
        }
    }

    /// Starts remembering: the Tower first, then the camera, then convergence.
    func start() {
        perform { await self.startSequence() }
    }

    /// Stops remembering: the Tower first, then the camera **if this screen
    /// started it**, then a refresh of the records.
    func stop() {
        perform { await self.stopSequence() }
    }

    /// Stops remembering without touching the camera.
    ///
    /// **Pause is a Tower verb only.** There is no way to pause a DAT stream,
    /// so if a capture is running it keeps running and keeps sending frames to
    /// the Tower — they are simply no longer read into this memory. The copy
    /// says that in as many words whenever it is true, because "paused" beside
    /// a live camera is otherwise read as "the camera stopped".
    func pause() {
        perform { await self.towerOnly(.pause, whileAsking: .pausing) }
    }

    /// Resumes remembering. From `stopped` this is a 409, which is an answer —
    /// it says Start is the control that works from there — and is reported as
    /// one rather than as a failure.
    func resume() {
        perform { await self.towerOnly(.resume, whileAsking: .resuming) }
    }

    // MARK: The sequences

    private func startSequence() async {
        phase = .starting

        // 1. The Tower, first and always. See the type's documentation for why
        //    this order is not interchangeable with the one below it.
        await client.apply(.start)
        // A second Start answers 200 with `changed: false`. That is the Tower
        // saying "you already have what you asked for" and it arrives here as
        // `.known`, indistinguishable from the first Start — which is correct,
        // and is why there is no branch on `changed` anywhere in this file.
        if let stopped = refusalOrFailure(client.session) {
            phase = stopped
            return
        }

        // 2. The camera, only if nothing already holds it.
        if let camera {
            // Asked of the camera directly rather than read off the published
            // mirror below. The mirror is a *display* value delivered through a
            // main-queue hop, and deciding whether to start a second capture
            // from a value that is one turn stale is exactly the kind of race
            // this sequencing exists to remove.
            switch camera.captureClaim {
            case .unclaimed:
                camera.startCameraSession()
                if let refusal = camera.lastCaptureStartRefusal {
                    // The Tower is left `active` deliberately. It is a gate,
                    // not a recording, and the next capture to open — from
                    // here, from Home, or from World Builder — finds it open.
                    // Stopping it here would throw away a correct half of the
                    // work because the other half was refused.
                    phase = .cameraRefused(refusal)
                    return
                }
                startedTheCamera = true
                // Kept in step immediately rather than waiting for the
                // publisher's hop, so the sentence drawn on the very next
                // render already describes the capture that was just started.
                cameraClaim = camera.captureClaim
            case .devicePaused:
                // A hardware pause. `startCameraSession()` would refuse this
                // too, and there is nothing this app may call to override it —
                // the glasses resume delivery on their own.
                phase = .cameraRefused(.deviceHasPausedCapture)
                return
            case .running, .ending:
                // Home or World Builder owns it. Ownership is *not* claimed,
                // so Stop below will leave their stream alone.
                startedTheCamera = false
            }
        }

        // 3. Converge on `following`, bounded.
        await converge()
    }

    private func stopSequence() async {
        phase = .stopping

        // The Tower first: `stop` is never refused from any state, and it is
        // what detaches the producer so it can finalise the record it is
        // holding. Killing the frames first would leave the producer to notice
        // the stream ending on its own.
        await client.apply(.stop)

        // Only a camera this screen started. A capture Home started is somebody
        // else's, and ending it from here would reach across two screens.
        if startedTheCamera, let camera {
            camera.stopCameraSession()
            startedTheCamera = false
            cameraClaim = camera.captureClaim
        }

        phase = resting(client.session)

        // The point of stopping is usually to look at what was just written.
        refreshRecords?()
    }

    /// Pause and Resume: the Tower, a read-back, and nothing else.
    private func towerOnly(
        _ action: CartridgeSessionAction, whileAsking asking: ObjectMemoryRecordingPhase
    ) async {
        phase = asking
        await client.apply(action)
        phase = resting(client.session)
    }

    /// Re-reads the session until a producer is observed following a capture,
    /// or until the budget runs out.
    ///
    /// The loop reads what `ObjectMemoryClient.apply` already read back before
    /// asking for anything more, so a Start that attached immediately settles
    /// without a single extra request. Every wait is a real `Task.sleep` with a
    /// deadline above it; there is no unbounded poll and no retry budget that
    /// can be refilled from inside.
    private func converge() async {
        phase = .waitingToBeFollowed
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: convergenceBudget)

        while !Task.isCancelled {
            if let settled = self.settled(client.session) {
                phase = settled
                return
            }
            guard clock.now < deadline else {
                // Asked for, and not observed. Said plainly rather than
                // dressed as an error: the session is exactly where the Tower
                // reports it, and the only thing that has happened is that this
                // app has still never seen a producer following anything.
                phase = .notObserved
                return
            }
            do {
                try await Task.sleep(for: convergenceInterval)
            } catch {
                // Cancellation, which is the only way out of the sleep. The
                // phase is left where it is rather than being given a verdict
                // nothing produced.
                return
            }
            await client.readSession()
        }
    }

    // MARK: Reading a session into a phase

    /// Runs one action at a time.
    ///
    /// **The double-tap guard, and it is a local fact rather than a guess about
    /// the Tower.** A second tap while a sequence is in flight is dropped
    /// entirely — not queued, not sent — because two overlapping Start
    /// sequences would race over `startedTheCamera` and could leave this screen
    /// believing it owns a capture it did not start. A tap *after* a sequence
    /// finishes is sent normally, and the Tower answers a repeated verb 200
    /// with `changed: false`, which is not an error and is never drawn as one.
    private func perform(_ body: @escaping @MainActor () async -> Void) {
        guard !isActing else {
            print("[Glasses][ObjectMemory] an action was already in flight; the second tap was dropped")
            return
        }
        isActing = true
        work = Task { [weak self] in
            await body()
            self?.isActing = false
        }
    }

    /// The phase for a reading that ends a wait, or `nil` while the only honest
    /// answer is "asked for, and nothing observed yet".
    ///
    /// `nil` is returned for exactly one shape — an `active` session with an
    /// empty `following` — and that shape is the reason this function is
    /// separate from `resting`. During a Start it means *keep waiting*; at rest
    /// it means *notObserved*. Same payload, two different true sentences, and
    /// the difference is whether a deadline has passed.
    private func settled(_ session: ObjectMemorySessionState) -> ObjectMemoryRecordingPhase? {
        switch session {
        case .unread, .working:
            return nil
        case .noSessionControl:
            return .unsupported
        case .failed(let failure):
            return .cannotTell(failure)
        case .refused(let refusal):
            return .refused(refusal)
        case .known(let snapshot):
            guard snapshot.supported else { return .unsupported }
            // Liveness, from `following`, and from nothing else.
            if snapshot.isFollowingACapture {
                if snapshot.state == .paused { return .stillFollowing(after: .pause) }
                if snapshot.state == .stopped { return .stillFollowing(after: .stop) }
                return .remembering
            }
            if snapshot.state == .paused { return .paused }
            if snapshot.state == .stopped { return .stopped }
            // `active` with nothing followed, and every state this build does
            // not recognise. Both are "the Tower reports no producer on a
            // recording", which is what `notObserved` says — and the session
            // panel below still prints the raw intent uninterpreted.
            return nil
        }
    }

    /// The phase for a reading with no wait outstanding.
    private func resting(_ session: ObjectMemorySessionState) -> ObjectMemoryRecordingPhase {
        switch session {
        case .unread:
            // Never read. Not `stopped`: silence is not an answer.
            return .idle
        case .working:
            // A request is in flight somewhere. Whatever was last true is still
            // the best thing known, and replacing it would flash a phase that
            // describes nothing.
            return phase
        case .known, .refused, .noSessionControl, .failed:
            return settled(session) ?? .notObserved
        }
    }

    /// The phases that must stop a Start sequence before it touches the camera.
    /// A refusal, a failure, or a Tower with no producer are all answers that
    /// make starting a capture pointless — and starting one anyway would leave
    /// a camera running for a memory that cannot be written into.
    private func refusalOrFailure(
        _ session: ObjectMemorySessionState
    ) -> ObjectMemoryRecordingPhase? {
        switch session {
        case .refused(let refusal): return .refused(refusal)
        case .failed(let failure): return .failed(failure)
        case .noSessionControl: return .unsupported
        case .known(let snapshot): return snapshot.supported ? nil : .unsupported
        case .unread, .working: return nil
        }
    }

    // MARK: Reacting to things nobody on this screen asked for

    /// A session reading that arrived from the workspace's own watch loop.
    ///
    /// This is what makes a producer that dies, a Tower that goes away, and a
    /// Pause honoured by somebody else all reach the phase. In particular a
    /// failed read becomes `cannotTell` and **clears the liveness claim**: a
    /// screen that keeps saying "remembering" after it lost the ability to
    /// check is asserting something it does not know.
    private func sessionChanged(_ session: ObjectMemorySessionState) {
        // While a sequence is in flight it is reading the client directly and
        // in order. A pushed reading here would race that sequence — the
        // `.working` and post-`POST` states both arrive on this publisher —
        // and could put "remembering" back on screen between a Stop's `POST`
        // and its read-back.
        guard !isActing else { return }
        phase = resting(session)
    }

    /// The camera's claim changed underneath this screen.
    ///
    /// Ownership is dropped when the capture ends, whoever ended it. Keeping
    /// `startedTheCamera` true across a capture that Home stopped would make a
    /// later Stop here call `stopCameraSession()` against whatever session
    /// exists by then, which might be one this screen never started.
    private func cameraClaimChanged(_ claim: CaptureClaim) {
        cameraClaim = claim
        if claim == .unclaimed { startedTheCamera = false }
    }
}
