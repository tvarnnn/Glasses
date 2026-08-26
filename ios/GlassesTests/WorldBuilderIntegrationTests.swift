//
//  WorldBuilderIntegrationTests.swift
//  GlassesTests
//
//  The Tower-backed World Builder client, against a real local WebSocket
//  server speaking the payloads `tower/tower/results/world_builder.py`
//  actually produces. Every fixture below was written from that file and from
//  `docs/contracts/CARTRIDGE-RESULTS.md` §10, not from a summary of either.
//

import Combine
import XCTest

@testable import Glasses

// MARK: - Payload decoding

/// The decode half, with no socket in it. These are the assertions that would
/// notice a field being renamed, defaulted to zero, or quietly upgraded.
@MainActor
final class WorldBuilderPayloadTests: XCTestCase {

    /// The complete payload the Tower builds for a live session, trimmed to the
    /// two halves iOS decodes. The Tower-native evidence blocks are omitted
    /// deliberately: this build reads neither, and a test that fed them in
    /// would imply otherwise.
    private func payload(
        modelState: String = "receiving",
        reason: Any = NSNull(),
        snapshot: [String: Any]? = nil
    ) -> [String: Any] {
        [
            "model_state": modelState,
            "model_state_reason": reason,
            "world_snapshot": snapshot ?? NSNull(),
        ]
    }

    private func fullSnapshot(
        overrides: [String: Any] = [:]
    ) -> [String: Any] {
        var snapshot: [String: Any] = [
            "name": "Probe Room",
            "world_id": "be5076514e0d4727ab06f2ad1df5a5bf",
            "keyframe_count": 4,
            "revision": "b00bfe85819804da",
            "tracking": "good",
            "scale": "relative",
            "mapping_seconds": 0.0789,
            "calibration": "calibrated",
            "geometry": [
                "representation": "sparse point cloud",
                "element_count": 1360,
                "is_incremental": false,
            ],
            "trajectory": [
                "pose_count": 4,
                "path_length": 2.853251890377782,
                "path_length_unit": "world units",
                "scale": "relative",
            ],
            "persistence": ["state": "saved", "revision": "67ccaee79f212c8d"],
        ]
        for (key, value) in overrides { snapshot[key] = value }
        return snapshot
    }

    // MARK: The six states

    func testEveryModelStateTheTowerSendsMapsToAWorldModelState() {
        XCTAssertEqual(
            WorldBuilderResultDecoder.modelState(from: payload(modelState: "idle")),
            .idle
        )

        let receiving = WorldBuilderResultDecoder.modelState(
            from: payload(modelState: "receiving", snapshot: fullSnapshot())
        )
        XCTAssertTrue(receiving?.isReceivingUpdates ?? false)
        XCTAssertEqual(receiving?.snapshot?.keyframeCount, 4)

        guard
            case .finalizing(let finalizing)? = WorldBuilderResultDecoder.modelState(
                from: payload(modelState: "finalizing", snapshot: fullSnapshot())
            )
        else { return XCTFail("finalizing did not decode") }
        XCTAssertEqual(finalizing.keyframeCount, 4)

        guard
            case .finalized(let finalized)? = WorldBuilderResultDecoder.modelState(
                from: payload(modelState: "finalized", snapshot: fullSnapshot())
            )
        else { return XCTFail("finalized did not decode") }
        XCTAssertEqual(finalized.worldID, "be5076514e0d4727ab06f2ad1df5a5bf")
    }

    /// `unsupported` is the Tower saying it cannot serve World Builder at all —
    /// "do not invite the user to wait". It must carry the Tower's own words.
    func testUnsupportedCarriesTheTowersOwnExplanation() {
        guard
            case .unsupported(let reason)? = WorldBuilderResultDecoder.modelState(
                from: payload(modelState: "unsupported", reason: "no world root is configured")
            )
        else { return XCTFail("unsupported did not decode") }
        XCTAssertEqual(reason, "no world root is configured")

        // And when it explains nothing, the app still must not render a blank.
        guard
            case .unsupported(let fallback)? = WorldBuilderResultDecoder.modelState(
                from: payload(modelState: "unsupported")
            )
        else { return XCTFail("unsupported without a reason did not decode") }
        XCTAssertFalse(fallback.isEmpty)
    }

    /// A failure the Tower reported is `.towerReportedFailure` and nothing
    /// else. Attributing it to transport, or to a local refusal, would be a
    /// fabricated claim about which machine failed.
    func testAFailedSessionIsAttributedToTheTower() {
        guard
            case .failed(let failure)? = WorldBuilderResultDecoder.modelState(
                from: payload(modelState: "failed", reason: "the builder died")
            )
        else { return XCTFail("failed did not decode") }
        XCTAssertEqual(failure.kind, .towerReportedFailure)
        XCTAssertEqual(failure.message, "the builder died")
    }

    /// `awaiting_first_update` is never sent — it is a fact about the phone's
    /// own situation — and a state word this build does not know is a contract
    /// disagreement rather than an empty world.
    func testAnUnknownModelStateIsARefusalNotAnEmptyWorld() {
        XCTAssertNil(WorldBuilderResultDecoder.modelState(from: payload(modelState: "mapping")))
        XCTAssertNil(
            WorldBuilderResultDecoder.modelState(from: payload(modelState: "awaiting_first_update"))
        )
        XCTAssertNil(WorldBuilderResultDecoder.modelState(from: [:]))
    }

    /// A live session with no world yet is the one honest use of
    /// `.awaitingFirstUpdate`: frames are going out and the Tower has said
    /// nothing about a world.
    func testReceivingWithoutASnapshotIsAwaitingRatherThanAnEmptyWorld() {
        XCTAssertEqual(
            WorldBuilderResultDecoder.modelState(from: payload(modelState: "receiving")),
            .awaitingFirstUpdate
        )
    }

    // MARK: Field-level truthfulness

    func testEveryWorldSnapshotFieldSurvivesTheWire() {
        let snapshot = WorldBuilderResultDecoder.snapshot(from: fullSnapshot())

        XCTAssertEqual(snapshot.name, "Probe Room")
        XCTAssertEqual(snapshot.worldID, "be5076514e0d4727ab06f2ad1df5a5bf")
        XCTAssertEqual(snapshot.keyframeCount, 4)
        XCTAssertEqual(snapshot.revision, "b00bfe85819804da")
        XCTAssertEqual(snapshot.tracking, .good)
        XCTAssertEqual(snapshot.scale, .relative)
        XCTAssertEqual(snapshot.mappingSeconds, 0.0789)
        XCTAssertEqual(snapshot.calibration, .calibrated)
        XCTAssertEqual(snapshot.geometry.representation, "sparse point cloud")
        XCTAssertEqual(snapshot.geometry.elementCount, 1360)
        XCTAssertEqual(snapshot.geometry.isIncremental, false)
        XCTAssertEqual(snapshot.trajectory.poseCount, 4)
        XCTAssertEqual(snapshot.trajectory.pathLength, 2.853251890377782)
        XCTAssertEqual(snapshot.trajectory.pathLengthUnit, "world units")
        XCTAssertEqual(snapshot.trajectory.scale, .relative)
        XCTAssertEqual(snapshot.persistence, .saved(revision: "67ccaee79f212c8d"))
    }

    /// Null means absent, never zero. `frames_observed` being genuinely
    /// unknowable during a live session is why the contract says so, and a
    /// keyframe count defaulted to `0` would report a world that had accepted
    /// nothing when the truth is that nobody counted.
    func testAbsentFieldsStayAbsentRatherThanBecomingZero() {
        let sparse: [String: Any] = [
            "name": NSNull(),
            "world_id": "w1",
            "keyframe_count": NSNull(),
            "revision": NSNull(),
            "tracking": "unavailable",
            "scale": "unknown",
            "mapping_seconds": NSNull(),
            "calibration": "unknown",
            "geometry": [
                "representation": NSNull(),
                "element_count": NSNull(),
                "is_incremental": false,
            ],
            "trajectory": [
                "pose_count": NSNull(),
                "path_length": NSNull(),
                "path_length_unit": NSNull(),
                "scale": "unknown",
            ],
            "persistence": ["state": "saved", "revision": NSNull()],
        ]
        let snapshot = WorldBuilderResultDecoder.snapshot(from: sparse)

        XCTAssertNil(snapshot.name)
        XCTAssertNil(snapshot.keyframeCount)
        XCTAssertNil(snapshot.mappingSeconds)
        XCTAssertNil(snapshot.geometry.elementCount)
        XCTAssertNil(snapshot.geometry.representation)
        XCTAssertNil(snapshot.trajectory.poseCount)
        XCTAssertNil(snapshot.trajectory.pathLength)
        XCTAssertFalse(snapshot.geometry.hasReport)
        XCTAssertFalse(snapshot.trajectory.hasReport)
        // A world id is still a report, so the snapshot is not empty.
        XCTAssertFalse(snapshot.isEmpty)
        XCTAssertEqual(snapshot.persistence, .saved(revision: nil))
    }

    // MARK: Scale

    /// **The load-bearing refusal.** `relative` is internally consistent with an
    /// arbitrary unit; it is not metric, and no figure carrying it may be shown
    /// as one. Both `inferredMetric` and `measuredMetric` are unreachable on
    /// this hardware and neither will arrive.
    func testRelativeScaleIsNeverRenderableAsMetres() {
        let snapshot = WorldBuilderResultDecoder.snapshot(from: fullSnapshot())
        XCTAssertEqual(snapshot.scale, .relative)
        XCTAssertFalse(snapshot.permitsMetricDisplay, "a relative world claimed metric display")
        XCTAssertFalse(
            snapshot.trajectory.distanceDisplayable,
            "a relative path length claimed to be a distance"
        )
        XCTAssertFalse(snapshot.scale.isEstimate, "relative is not an estimate of metres")
    }

    /// It is still a labelled figure, and the Tower names its unit precisely so
    /// it can be shown. "2.9 world units" is not a distance claim; a bare "2.9"
    /// would be, because a reader supplies metres.
    func testARelativePathLengthIsShownWithTheTowersOwnUnit() {
        let snapshot = WorldBuilderResultDecoder.snapshot(from: fullSnapshot())
        XCTAssertTrue(snapshot.trajectory.labelledFigureDisplayable)
        XCTAssertEqual(
            ReportedFigure.format(
                snapshot.trajectory.pathLength ?? 0,
                unit: snapshot.trajectory.pathLengthUnit
            ),
            "2.9 world units"
        )
    }

    /// The Tower refuses a path length outright when it could not be labelled —
    /// a refused pose, more than one segment, or an unknown scale. iOS must
    /// refuse to render the resulting `null` rather than printing a bare zero.
    func testAWithheldPathLengthIsNotRenderedAtAll() {
        let withheld = fullSnapshot(overrides: [
            "trajectory": [
                "pose_count": 12,
                "path_length": NSNull(),
                "path_length_unit": NSNull(),
                "scale": "unknown",
            ]
        ])
        let snapshot = WorldBuilderResultDecoder.snapshot(from: withheld)
        XCTAssertEqual(snapshot.trajectory.poseCount, 12, "the pose count is still a report")
        XCTAssertFalse(snapshot.trajectory.labelledFigureDisplayable)
        XCTAssertFalse(snapshot.trajectory.distanceDisplayable)
    }

    /// An unlabelled figure is refused even when a scale is present: the unit
    /// is the gate, because without one the reader supplies metres.
    func testAFigureWithNoUnitIsRefused() {
        let unlabelled = WorldTrajectoryReport(pathLength: 2.8, pathLengthUnit: nil, scale: .relative)
        XCTAssertFalse(unlabelled.labelledFigureDisplayable)
        XCTAssertFalse(WorldTrajectoryReport(pathLength: 2.8, pathLengthUnit: "", scale: .relative)
            .labelledFigureDisplayable)
    }

    /// `unknown` is a strictly weaker claim than `relative` — the
    /// reconstruction has no unit at all — and must not be mapped to it.
    func testUnknownScaleIsNotUpgradedToRelative() {
        XCTAssertEqual(WorldBuilderResultDecoder.scale(nil), .unknown)
        XCTAssertEqual(WorldBuilderResultDecoder.scale("unknown"), .unknown)
        XCTAssertEqual(WorldBuilderResultDecoder.scale("nonsense"), .unknown)
        XCTAssertEqual(WorldBuilderResultDecoder.scale("relative"), .relative)
    }

    /// The two the Tower cannot reach today are still mapped rather than
    /// discarded — silently downgrading an arriving metric claim to `.relative`
    /// would understate it, and `inferredMetric` must stay labelled as an
    /// estimate wherever it is shown.
    func testAnInferredMetricFigureWouldStayLabelledAsAnEstimate() {
        XCTAssertEqual(WorldBuilderResultDecoder.scale("inferredMetric"), .inferredMetric)
        XCTAssertEqual(WorldBuilderResultDecoder.scale("measuredMetric"), .measuredMetric)
        XCTAssertTrue(WorldScaleSemantics.inferredMetric.isEstimate)
        XCTAssertEqual(WorldScaleSemantics.inferredMetric.displayName, "Estimated")
    }

    // MARK: The vocabularies the Tower never sends

    /// `limited` needs a threshold nobody has defined and is not emitted;
    /// `calibrating` has no in-session procedure to be in the middle of. Both
    /// are mapped anyway, so that one arriving later is not silently folded
    /// into a weaker state.
    func testTheStatesTheTowerNeverSendsStillMapCorrectly() {
        XCTAssertEqual(WorldBuilderResultDecoder.tracking("good"), .good)
        XCTAssertEqual(WorldBuilderResultDecoder.tracking("lost"), .lost)
        XCTAssertEqual(WorldBuilderResultDecoder.tracking("unavailable"), .unavailable)
        XCTAssertEqual(WorldBuilderResultDecoder.tracking(nil), .unavailable)
        XCTAssertEqual(WorldBuilderResultDecoder.tracking("limited"), .limited)

        XCTAssertEqual(WorldBuilderResultDecoder.calibration("calibrated"), .calibrated)
        XCTAssertEqual(WorldBuilderResultDecoder.calibration("uncalibrated"), .uncalibrated)
        XCTAssertEqual(WorldBuilderResultDecoder.calibration("unknown"), .unknown)
        XCTAssertEqual(WorldBuilderResultDecoder.calibration(nil), .unknown)
        XCTAssertEqual(WorldBuilderResultDecoder.calibration("calibrating"), .calibrating)
    }

    /// `saved` is the only state the Tower reaches, and silence is not a
    /// promise that the world is discarded.
    func testPersistenceSilenceIsNotSessionOnly() {
        XCTAssertEqual(WorldBuilderResultDecoder.persistence(state: nil, revision: nil), .unknown)
        XCTAssertEqual(
            WorldBuilderResultDecoder.persistence(state: "saved", revision: "r1"),
            .saved(revision: "r1")
        )
        XCTAssertNotEqual(
            WorldBuilderResultDecoder.persistence(state: nil, revision: nil),
            .session
        )
    }

    // MARK: Against the real Tower's bytes

    /// **A payload captured verbatim from a running Tower**, not composed here.
    ///
    /// Every other fixture in this file was written from
    /// `tower/tower/results/world_builder.py` and could therefore be wrong in
    /// the same way the reading of that file was wrong. This one was taken off
    /// the wire on 2026-08-24 from `tower.main:app` at
    /// `world_builder.status/2026-08-23`, after a build that produced 8
    /// keyframes, 2336 points and 7 solved poses.
    ///
    /// The world it describes is **synthetic** — rendered, not photographed —
    /// which is a fact about the reconstruction and not about the wire. What
    /// this pins is the encoding: the key names, the nesting, the types, and
    /// which fields carry `null`.
    private static let capturedFromTower = """
        {
          "name": "Wire Check (synthetic)",
          "world_id": "d53fa2781dc94339b1c8640ceb50d6a3",
          "keyframe_count": 8,
          "revision": "05576f31fec4fb79",
          "tracking": "good",
          "scale": "relative",
          "mapping_seconds": 0.2812764644622803,
          "calibration": "calibrated",
          "geometry": {
            "representation": "sparse point cloud",
            "element_count": 2336,
            "is_incremental": false
          },
          "trajectory": {
            "pose_count": 8,
            "path_length": 6.626530639332543,
            "path_length_unit": "world units",
            "scale": "relative"
          },
          "persistence": {
            "state": "saved",
            "revision": "a8ae1778a260e976"
          }
        }
        """

    func testARealTowerSnapshotDecodesFieldForField() throws {
        let data = Data(Self.capturedFromTower.utf8)
        let json = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        let snapshot = WorldBuilderResultDecoder.snapshot(from: json)

        XCTAssertEqual(snapshot.name, "Wire Check (synthetic)")
        XCTAssertEqual(snapshot.worldID, "d53fa2781dc94339b1c8640ceb50d6a3")
        XCTAssertEqual(snapshot.keyframeCount, 8)
        XCTAssertEqual(snapshot.revision, "05576f31fec4fb79")
        XCTAssertEqual(snapshot.tracking, .good)
        XCTAssertEqual(snapshot.scale, .relative)
        XCTAssertEqual(snapshot.calibration, .calibrated)
        XCTAssertEqual(snapshot.geometry.elementCount, 2336)
        XCTAssertEqual(snapshot.geometry.representation, "sparse point cloud")
        XCTAssertEqual(snapshot.trajectory.poseCount, 8)
        XCTAssertEqual(snapshot.persistence, .saved(revision: "a8ae1778a260e976"))
        XCTAssertFalse(snapshot.isEmpty)

        // And what a person would actually be shown, which is the assertion
        // that would catch a decode that "worked" into an unrenderable state.
        XCTAssertFalse(snapshot.permitsMetricDisplay, "a synthetic relative world claimed metres")
        XCTAssertTrue(snapshot.trajectory.labelledFigureDisplayable)
        XCTAssertEqual(
            ReportedFigure.format(
                snapshot.trajectory.pathLength ?? 0,
                unit: snapshot.trajectory.pathLengthUnit
            ),
            "6.6 world units"
        )
    }

    /// The Tower with no worlds yet, also captured verbatim. `world_snapshot`
    /// is `null` and `model_state_reason` explains why — and `.idle` must not
    /// be confused for a world with every field missing.
    func testARealIdleTowerDecodesToIdleWithNoWorld() throws {
        let raw = """
            {"model_state": "idle",
             "model_state_reason": "no worlds exist under this Tower's world root",
             "world_snapshot": null}
            """
        let json = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(raw.utf8)) as? [String: Any]
        )
        let state = WorldBuilderResultDecoder.modelState(from: json)
        XCTAssertEqual(state, .idle)
        XCTAssertNil(state?.snapshot)
        XCTAssertFalse(state?.hasWorld ?? true)
        XCTAssertFalse(state?.phase.mayCarryData ?? true)
    }

    // MARK: Revisions

    /// A revision is an opaque change identity, and a snapshot supersedes every
    /// earlier one. Two revisions differing means the state differs; nothing
    /// orders them.
    func testANewRevisionSupersedesTheSnapshotBeforeIt() {
        let first = WorldBuilderResultDecoder.snapshot(from: fullSnapshot())
        let second = WorldBuilderResultDecoder.snapshot(
            from: fullSnapshot(overrides: ["revision": "ffff0000", "keyframe_count": 9])
        )
        XCTAssertNotEqual(first, second)
        XCTAssertEqual(second.revision, "ffff0000")
        XCTAssertEqual(second.keyframeCount, 9)
    }
}

// MARK: - The client, against a socket

/// The Tower-backed client end to end: discovery, subscription, lifecycle, and
/// what a reconnect does to all three.
@MainActor
final class TowerWorldBuilderClientTests: XCTestCase {

    private static let contract = "world_builder.status/2026-08-23"

    private func url(port: UInt16) -> URL { URL(string: "ws://127.0.0.1:\(port)/")! }

    /// A server that answers the handshake, answers `{"type":"cartridges"}`
    /// with a declaration, and acknowledges a subscribe — the three exchanges
    /// the real Tower performs before the first snapshot.
    private func serve(
        _ server: MockTowerServer,
        available: Bool = true,
        unavailableReason: String? = nil,
        contract: String = TowerWorldBuilderClientTests.contract,
        recorder: MessageRecorder? = nil
    ) {
        let reason = unavailableReason.map { "\"\($0)\"" } ?? "null"
        server.onText = { text in
            recorder?.record(text)
            guard
                let data = text.data(using: .utf8),
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let type = json["type"] as? String
            else { return }
            switch type {
            case "ping":
                server.send(text: #"{"type":"pong"}"#)
            case "cartridges":
                server.send(text: """
                    {"type":"cartridges",
                     "envelope_contract":"cartridge_results.envelope/2026-08-23",
                     "cartridges":[{"cartridge":"world_builder","result_type":"status",
                        "contract":"\(contract)","available":\(available),
                        "unavailable_reason":\(reason),"snapshot_only":true}],
                     "not_offered":[]}
                    """)
            case "result_subscribe":
                server.send(text: """
                    {"type":"result_subscribed",
                     "envelope_contract":"cartridge_results.envelope/2026-08-23",
                     "subscription_id":"sub-1","cartridge":"world_builder",
                     "result_type":"status","contract":"\(contract)",
                     "snapshot_only":true,"world_id":null,"session_id":null,
                     "cursor_status":"absent"}
                    """)
            default:
                break
            }
        }
    }

    private func snapshotMessage(
        seq: Int,
        modelState: String,
        keyframes: Int,
        revision: String,
        revisionChanged: Bool = true,
        tracking: String = "good"
    ) -> String {
        """
        {"type":"cartridge_result",
         "envelope_contract":"cartridge_results.envelope/2026-08-23",
         "subscription_id":"sub-1","cartridge":"world_builder","result_type":"status",
         "contract":"\(Self.contract)","seq":\(seq),"revision":"\(revision)",
         "revision_changed":\(revisionChanged),"coalesced":0,"cursor_status":null,
         "snapshot":true,"tower_sent_at":1787463092.9,"time_basis":"tower-receipt",
         "payload":{"model_state":"\(modelState)","model_state_reason":null,
           "world_snapshot":{"name":"Probe Room","world_id":"w1",
             "keyframe_count":\(keyframes),"revision":"\(revision)",
             "tracking":"\(tracking)","scale":"relative","mapping_seconds":12.5,
             "calibration":"calibrated",
             "geometry":{"representation":"sparse point cloud","element_count":1360,
                         "is_incremental":false},
             "trajectory":{"pose_count":\(keyframes),"path_length":2.85,
                           "path_length_unit":"world units","scale":"relative"},
             "persistence":{"state":"saved","revision":"p1"}}}}
        """
    }

    /// See `TowerClientTests.expect` — an autoclosure cannot carry an `await`,
    /// so the assertion is wrapped rather than hoisted at every call site.
    private func expect(
        _ message: @autoclosure () -> String = "the condition was never met",
        timeout: TimeInterval = 3,
        file: StaticString = #filePath,
        line: UInt = #line,
        _ condition: @MainActor () -> Bool
    ) async {
        let met = await waitUntil(timeout: timeout, condition)
        XCTAssertTrue(met, message(), file: file, line: line)
    }

    private func waitUntil(
        timeout: TimeInterval = 3,
        _ condition: @MainActor () -> Bool
    ) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return true }
            try? await Task.sleep(nanoseconds: 25_000_000)
        }
        return condition()
    }

    private func decode(_ text: String) -> [String: Any]? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    }

    // MARK: The lifecycle

    /// The whole sequence, driven by the Tower's own `model_state` values:
    /// idle → awaitingFirstUpdate → receiving → finalizing → finalized.
    ///
    /// `awaitingFirstUpdate` is the one the Tower never sends. It is reached by
    /// the phone having subscribed and not yet been answered, which is the only
    /// machine that can know it.
    func testTheWorldBuilderLifecycleRunsEndToEnd() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        serve(server)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        var seen: [CartridgePhase] = []
        let cancellable = client.stateUpdates.sink { seen.append($0.phase) }
        defer { cancellable.cancel() }

        XCTAssertEqual(client.state, .idle, "the client claimed something before connecting")

        tower.connect(to: url(port: port))
        await expect { client.state == .awaitingFirstUpdate }
        XCTAssertEqual(client.state.phase, .waiting, "a spinner is only honest while waiting")

        server.send(text: snapshotMessage(seq: 1, modelState: "receiving", keyframes: 4, revision: "r1"))
        await expect { client.state.isReceivingUpdates }
        XCTAssertEqual(client.state.snapshot?.keyframeCount, 4)

        server.send(text: snapshotMessage(seq: 2, modelState: "receiving", keyframes: 17, revision: "r2"))
        await expect { client.state.snapshot?.keyframeCount == 17 }

        server.send(text: snapshotMessage(seq: 3, modelState: "finalizing", keyframes: 17, revision: "r3"))
        await expect {
            if case .finalizing = client.state { return true }
            return false
        }
        XCTAssertFalse(
            client.state.isReceivingUpdates,
            "finalizing claimed to be live; no new observations are arriving"
        )

        server.send(text: snapshotMessage(seq: 4, modelState: "finalized", keyframes: 17, revision: "r4"))
        await expect {
            if case .finalized = client.state { return true }
            return false
        }
        XCTAssertEqual(client.state.phase, .settled)
        XCTAssertTrue(client.state.hasWorld)

        XCTAssertEqual(
            seen,
            [.waiting, .live, .live, .live, .settled],
            "the lifecycle did not pass through the phases in order: \(seen)"
        )

        tower.disconnect()
    }

    /// The ~2 s heartbeat re-sends an unchanged snapshot to refresh the fields
    /// excluded from the revision hash. A republish for one of those would put
    /// a list diff on the main actor for nothing.
    func testAnUnchangedHeartbeatDoesNotRepublish() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        serve(server)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))
        await expect { client.state == .awaitingFirstUpdate }

        var publishes = 0
        let cancellable = client.stateUpdates.sink { _ in publishes += 1 }
        defer { cancellable.cancel() }

        server.send(text: snapshotMessage(seq: 1, modelState: "receiving", keyframes: 4, revision: "r1"))
        await expect { publishes == 1 }

        // Three heartbeats: same revision, same everything.
        for seq in 2...4 {
            server.send(text: snapshotMessage(
                seq: seq, modelState: "receiving", keyframes: 4,
                revision: "r1", revisionChanged: false
            ))
        }
        try? await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertEqual(publishes, 1, "an unchanged snapshot invalidated the view tree")

        // A real change still gets through.
        server.send(text: snapshotMessage(seq: 5, modelState: "receiving", keyframes: 5, revision: "r2"))
        await expect { publishes == 2 }

        tower.disconnect()
    }

    // MARK: Availability

    /// The client resolves availability against the **live** declaration. A
    /// Tower that has said nothing is `.noContract`; one that has declared and
    /// is reachable is `.available`.
    func testAvailabilityFollowsTheLiveDeclaration() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        serve(server)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        XCTAssertEqual(client.availability(isTowerReachable: false), .noContract)

        tower.connect(to: url(port: port))
        await expect { tower.cartridgeDeclaration != nil }
        XCTAssertTrue(client.availability(isTowerReachable: true).isAvailable)
        XCTAssertNil(
            client.availability(isTowerReachable: true).forcedPhase,
            "an available cartridge must let its own state through"
        )

        tower.disconnect()
    }

    /// Offered and unserveable is not the same as never offered. The Tower's
    /// own prose is the only honest explanation, and the app shows it verbatim
    /// rather than composing one.
    func testAnUnavailableOfferShowsTheTowersReasonAndDoesNotSubscribe() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = MessageRecorder()
        serve(
            server,
            available: false,
            unavailableReason: "no world root is configured on this Tower",
            recorder: recorder
        )
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))

        await expect {
            if case .unsupported = client.state { return true }
            return false
        }
        guard case .unsupported(let reason) = client.state else {
            return XCTFail("expected .unsupported, got \(client.state)")
        }
        XCTAssertEqual(reason, "no world root is configured on this Tower")

        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertFalse(
            recorder.all.compactMap(decode).contains { $0["type"] as? String == "result_subscribe" },
            "the client subscribed to a cartridge the Tower said it could not serve"
        )

        tower.disconnect()
    }

    /// A contract this build does not implement must not be decoded on a guess.
    /// `.unsupportedContract` tells a person to update the app; subscribing
    /// anyway would produce a payload nothing here was written against.
    func testAnUnknownContractIsNeitherSubscribedToNorDecoded() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = MessageRecorder()
        serve(server, contract: "world_builder.status/2027-06-01", recorder: recorder)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))
        await expect { tower.cartridgeDeclaration != nil }

        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertFalse(
            recorder.all.compactMap(decode).contains { $0["type"] as? String == "result_subscribe" },
            "the client subscribed against a contract it does not implement"
        )
        XCTAssertEqual(
            client.availability(isTowerReachable: true).forcedPhase,
            .unsupported
        )

        tower.disconnect()
    }

    // MARK: Reconnect

    /// The reconnect property the whole design rests on: **there is no delta
    /// stream, so a reconnect cannot lose data.** Subscribe again and the first
    /// message is a complete snapshot.
    ///
    /// One client object throughout, one subscription per socket, and the world
    /// that was on screen is not forgotten on the way down — availability
    /// reports the connection, so the client does not have to fabricate one.
    func testAReconnectResubscribesExactlyOnceAndDoesNotDuplicateTheClient() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = MessageRecorder()
        serve(server, recorder: recorder)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics(), autoReconnect: true)
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))
        await expect { client.state == .awaitingFirstUpdate }

        server.send(text: snapshotMessage(seq: 1, modelState: "receiving", keyframes: 30, revision: "r1"))
        await expect { client.state.snapshot?.keyframeCount == 30 }

        let subscribesBefore = recorder.all.compactMap(decode)
            .filter { $0["type"] as? String == "result_subscribe" }.count
        XCTAssertEqual(subscribesBefore, 1)

        // The socket dies without a close frame, exactly like a WiFi drop.
        server.dropConnection()
        await expect { tower.status != .online }

        // Nothing about the world is forgotten on the way down; the connection
        // is what changed, and availability is where that is reported.
        XCTAssertEqual(client.state.snapshot?.keyframeCount, 30)
        XCTAssertEqual(
            client.availability(isTowerReachable: false).forcedPhase,
            .disconnected,
            "a dropped socket must read as disconnected, not as unsupported"
        )

        await expect(timeout: 8) { tower.status == .online }
        await expect(timeout: 5) {
            recorder.all.compactMap(self.decode)
                .filter { $0["type"] as? String == "result_subscribe" }.count == 2
        }
        XCTAssertEqual(
            recorder.all.compactMap(decode).filter { $0["type"] as? String == "result_subscribe" }.count,
            2,
            "the reconnect opened more than one subscription"
        )

        // The keyframe count continues from the Tower's figure, which is the
        // one that survived — the capture lineage is the Tower's to keep.
        server.send(text: snapshotMessage(seq: 1, modelState: "receiving", keyframes: 41, revision: "r9"))
        await expect { client.state.snapshot?.keyframeCount == 41 }

        tower.disconnect()
    }

    /// A declaration republished while a subscribe is still in flight must not
    /// open a second subscription. Both paths into `subscribeIfPossible` are
    /// guarded by the same flags, and this is that guarantee as a test.
    func testARepublishedDeclarationDoesNotOpenASecondSubscription() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = MessageRecorder()
        serve(server, recorder: recorder)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))
        await expect { client.state == .awaitingFirstUpdate }

        // Three more declarations on the same socket, as a Tower restarting its
        // own declaration cache would produce.
        for _ in 0..<3 { tower.requestCartridgeDeclaration() }
        try? await Task.sleep(nanoseconds: 400_000_000)

        XCTAssertEqual(
            recorder.all.compactMap(decode).filter { $0["type"] as? String == "result_subscribe" }.count,
            1,
            "a republished declaration opened another subscription"
        )

        tower.disconnect()
    }

    // MARK: Errors

    /// `consumer_too_slow` and `channel_failed` close a subscription and are
    /// recoverable by subscribing again — but only a bounded number of times,
    /// so a Tower that closes every subscription becomes visible rather than
    /// staying in motion.
    func testAClosedSubscriptionIsRetriedAndThenReportedRatherThanLooping() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = MessageRecorder()
        serve(server, recorder: recorder)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))
        await expect { client.state == .awaitingFirstUpdate }

        for _ in 0..<6 {
            server.send(text: """
                {"type":"result_error","reason":"channel_failed","subscription_id":"sub-1",
                 "cartridge":"world_builder","result_type":"status","message":"the reader died"}
                """)
            try? await Task.sleep(nanoseconds: 120_000_000)
        }

        guard case .failed(let failure) = client.state else {
            return XCTFail("expected .failed after an unrecoverable channel, got \(client.state)")
        }
        XCTAssertEqual(failure.kind, .transport)

        let subscribes = recorder.all.compactMap(decode)
            .filter { $0["type"] as? String == "result_subscribe" }.count
        XCTAssertEqual(subscribes, 4, "the resubscribe budget was not bounded: \(subscribes) attempts")
        XCTAssertEqual(tower.status, .online, "a result-channel failure took the connection down")

        tower.disconnect()
    }

    /// An error naming another cartridge is not this client's to claim.
    /// Attributing it here would be a fabricated report about the Tower.
    func testAnErrorForAnotherCartridgeIsNotClaimed() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        serve(server)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))
        await expect { client.state == .awaitingFirstUpdate }

        server.send(text: snapshotMessage(seq: 1, modelState: "receiving", keyframes: 4, revision: "r1"))
        await expect { client.state.isReceivingUpdates }

        server.send(text: """
            {"type":"result_error","envelope_contract":"cartridge_results.envelope/2026-08-23",
             "reason":"unknown_cartridge","message":"no such cartridge",
             "cartridge":"document_memory","result_type":"status","offered":["world_builder"]}
            """)
        try? await Task.sleep(nanoseconds: 250_000_000)

        XCTAssertTrue(
            client.state.isReceivingUpdates,
            "another cartridge's failure was rendered as this one's"
        )

        tower.disconnect()
    }

    /// A payload this build cannot read is `.undecodableResponse` — a
    /// disagreement discovered on arrival — and not an empty world.
    func testAnUnreadablePayloadIsAFailureNotAnEmptyWorld() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        serve(server)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))
        await expect { client.state == .awaitingFirstUpdate }

        server.send(text: """
            {"type":"cartridge_result","envelope_contract":"cartridge_results.envelope/2026-08-23",
             "subscription_id":"sub-1","cartridge":"world_builder","result_type":"status",
             "contract":"\(Self.contract)","seq":1,"revision":"r1","revision_changed":true,
             "coalesced":0,"cursor_status":null,"snapshot":true,
             "tower_sent_at":1.0,"time_basis":"tower-receipt",
             "payload":{"model_state":"reticulating_splines","world_snapshot":null}}
            """)

        await expect {
            if case .failed = client.state { return true }
            return false
        }
        guard case .failed(let failure) = client.state else { return XCTFail("no failure") }
        XCTAssertEqual(failure.kind, .undecodableResponse)
        XCTAssertFalse(client.state.hasWorld)

        tower.disconnect()
    }

    // MARK: Ownership

    /// The client is owned above the workspace, so a cartridge switch — which
    /// constructs and releases view models — cannot cost it its subscription or
    /// its accumulated world.
    func testAWorkspaceSwitchDoesNotDisturbTheClientOrItsSubscription() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = MessageRecorder()
        serve(server, recorder: recorder)
        defer { server.stop() }

        let tower = TowerClient(metrics: SenderMetrics())
        let client = TowerWorldBuilderClient(tower: tower)
        tower.connect(to: url(port: port))
        await expect { client.state == .awaitingFirstUpdate }
        server.send(text: snapshotMessage(seq: 1, modelState: "receiving", keyframes: 12, revision: "r1"))
        await expect { client.state.snapshot?.keyframeCount == 12 }

        let wireBefore = recorder.all.count
        for _ in 0..<5 {
            let viewModel = WorldBuilderViewModel(client: client)
            XCTAssertEqual(
                viewModel.state.snapshot?.keyframeCount,
                12,
                "a fresh view model did not see the world the client already held"
            )
        }
        try? await Task.sleep(nanoseconds: 200_000_000)

        XCTAssertEqual(recorder.all.count, wireBefore, "a view model put something on the wire")
        XCTAssertEqual(client.state.snapshot?.keyframeCount, 12)

        // And the client is still live: the next snapshot still lands.
        server.send(text: snapshotMessage(seq: 2, modelState: "receiving", keyframes: 13, revision: "r2"))
        await expect { client.state.snapshot?.keyframeCount == 13 }

        tower.disconnect()
    }

    /// The app graph builds exactly one Tower-backed client, and it is the one
    /// the workspace is handed — the failure this would catch is a second
    /// client constructed at the point of use, holding its own subscription
    /// and dying on every cartridge switch.
    ///
    /// `GlassesConnection` is given a scripted `WearablesInterface` rather than
    /// the real one. Constructing the true production graph here would subscribe
    /// to live DAT streams from a unit test, which is both a camera-owning
    /// object nobody asked for and a source of interference for every other
    /// test in the run. What is under test is the *wiring*, and the wiring is
    /// unaffected by which `WearablesInterface` is underneath.
    func testTheAppGraphOwnsOneTowerBackedWorldBuilderClient() {
        let project = ProjectManager(
            glassesConnection: GlassesConnection(wearables: ScriptedWearables(permissionResults: []))
        )
        XCTAssertTrue(
            project.cartridgeClients.worldBuilder is TowerWorldBuilderClient,
            "the app graph is not wiring the Tower-backed client"
        )
        XCTAssertTrue(
            project.cartridgeClients.worldBuilder === project.cartridgeClients.worldBuilder,
            "the container is handing out a new client per access"
        )
        XCTAssertEqual(project.cartridgeClients.worldBuilder.cartridgeID, "world-build")

        // And the client is wired to the graph's one connection, not to a
        // second `TowerClient` it made for itself: asking the connection what
        // it has declared is the only way this client answers at all.
        XCTAssertEqual(
            project.cartridgeClients.worldBuilder.availability(isTowerReachable: false),
            .noContract,
            "the client answered from something other than the graph's connection"
        )
    }
}
