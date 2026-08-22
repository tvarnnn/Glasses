//
//  TowerClientTests.swift
//  GlassesTests
//
//  Exercises the WebSocket observability/liveness behavior added to
//  TowerClient: the continuous receive loop, delegate close observation,
//  send-path truthfulness, and connect/disconnect lifecycle cleanliness.
//  Runs against a real local WebSocket server (MockTowerServer) rather than
//  the actual Tower.
//

import UIKit
import XCTest

@testable import Glasses

@MainActor
final class TowerClientTests: XCTestCase {

    private func url(port: UInt16) -> URL {
        URL(string: "ws://127.0.0.1:\(port)/")!
    }

    /// Responds to the client's initial ping with a pong, exactly like the
    /// real Tower's handshake.
    private func respondToPing(_ server: MockTowerServer) {
        server.onText = { text in
            guard
                let data = text.data(using: .utf8),
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
                json["type"] == "ping"
            else { return }
            server.send(text: #"{"type":"pong"}"#)
        }
    }

    /// Same as `respondToPing`, but also records every text message the
    /// server receives (pings included) for later inspection.
    private func attachRecorder(_ server: MockTowerServer) -> MessageRecorder {
        let recorder = MessageRecorder()
        server.onText = { text in
            recorder.record(text)
            guard
                let data = text.data(using: .utf8),
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
                json["type"] == "ping"
            else { return }
            server.send(text: #"{"type":"pong"}"#)
        }
        return recorder
    }

    /// Decodes a recorded text message's top-level JSON object.
    private func decode(_ text: String) -> [String: Any]? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
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

    private func makeTestImage() -> UIImage {
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 2, height: 2))
        return renderer.image { context in
            UIColor.red.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 2, height: 2))
        }
    }

    // MARK: - 1. Initial ping/pong still works

    func testInitialPingPongStillWorks() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))

        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline, "expected .online, got \(client.status)")

        client.disconnect()
    }

    // MARK: - 2. Receive loop handles multiple frame_result messages

    func testReceiveLoopHandlesMultipleFrameResultMessages() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        for seq in 1...3 {
            server.send(text: #"{"type":"frame_result","seq":\#(seq),"mean_intensity":0.42,"processing_ms":8.5}"#)
        }

        let receivedAll = await waitUntil { client.frameResultCount >= 3 }
        XCTAssertTrue(receivedAll, "expected 3 frame_result messages processed, got \(client.frameResultCount)")
        XCTAssertEqual(client.status, .online, "processing frame_result must not affect connection status")

        client.disconnect()
    }

    // MARK: - 3. Unknown inbound message does not kill the connection

    func testUnknownInboundMessageDoesNotKillConnection() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        server.send(text: #"{"type":"something_unexpected","foo":"bar"}"#)
        // Prove the connection survived the unknown message by sending a
        // real frame_result right after and confirming it's still processed.
        server.send(text: #"{"type":"frame_result","seq":1,"mean_intensity":0.1,"processing_ms":1.0}"#)

        let stillHealthy = await waitUntil { client.frameResultCount >= 1 }
        XCTAssertTrue(stillHealthy)
        XCTAssertEqual(client.status, .online)

        client.disconnect()
    }

    // MARK: - 4. Receive failure changes status away from .online

    func testReceiveFailureChangesStatusAwayFromOnline() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        server.dropConnection()
        server.stop()

        let leftOnline = await waitUntil { client.status != .online }
        XCTAssertTrue(leftOnline, "status is stuck at .online after the connection was dropped")
        guard case .failed = client.status else {
            XCTFail("expected .failed after a receive failure, got \(client.status)")
            return
        }
    }

    // MARK: - 5. Delegate close changes status appropriately

    func testDelegateCloseChangesStatusAppropriately() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.simulateDelegateCloseForTesting(code: .normalClosure)

        let leftOnline = await waitUntil { client.status != .online }
        XCTAssertTrue(leftOnline, "status did not change after a delegate close callback")
        guard case .failed = client.status else {
            XCTFail("expected .failed after delegate close, got \(client.status)")
            return
        }
    }

    // MARK: - 6. disconnect() cancels the receive loop cleanly

    func testDisconnectCancelsReceiveLoopCleanly() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.disconnect()
        XCTAssertEqual(client.status, .offline)

        // A message sent after disconnect() must never be observed — proves
        // the receive loop actually stopped rather than lingering.
        server.send(text: #"{"type":"frame_result","seq":99,"mean_intensity":0,"processing_ms":0}"#)
        try? await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertEqual(client.frameResultCount, 0)
        XCTAssertEqual(client.status, .offline)
    }

    // MARK: - 7. Repeated connect/disconnect does not leave duplicate listeners

    func testRepeatedConnectDisconnectDoesNotLeaveDuplicateListeners() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient()

        client.connect(to: url(port: port))
        var becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)
        client.disconnect()
        XCTAssertEqual(client.status, .offline)

        client.connect(to: url(port: port))
        becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        server.send(text: #"{"type":"frame_result","seq":1,"mean_intensity":0,"processing_ms":0}"#)
        let received = await waitUntil { client.frameResultCount == 1 }
        XCTAssertTrue(
            received,
            "expected exactly 1 frame_result, got \(client.frameResultCount) — a leaked prior receive loop would double-count or misbehave"
        )

        client.disconnect()
    }

    // MARK: - 8. Send failure does not leave stale .online state

    func testSendFailureDoesNotLeaveStaleOnlineState() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        // The stream bracket has to be opened *before* the drop, or sendFrame
        // returns at the isStreamingToTower guard and never reaches
        // `task.send` — in which case this test would pass on the receive
        // loop alone and prove nothing about the send path it is named for.
        client.sendStreamStart()
        XCTAssertTrue(client.isStreamingToTower, "stream_start must succeed while online")

        server.dropConnection()
        server.stop()

        // Either the concurrent receive loop or this send's completion
        // handler may be the one to observe the drop first; the guarantee
        // under test is the outcome (status leaves .online), not which path
        // wins that race.
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 1)

        let leftOnline = await waitUntil { client.status != .online }
        XCTAssertTrue(leftOnline, "status is stuck at .online after a confirmed send/receive failure")
    }

    // MARK: - 9. stream_start is sent exactly once, with the exact payload

    func testStreamStartSendsExactPayloadOnce() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        client.sendStreamStart() // redundant call — must not send a second time
        try? await Task.sleep(nanoseconds: 200_000_000)

        let streamStarts = recorder.all.compactMap(decode).filter { $0["type"] as? String == "stream_start" }
        XCTAssertEqual(streamStarts.count, 1, "expected exactly one stream_start, got \(streamStarts.count)")
        XCTAssertEqual(streamStarts.first?.keys.sorted(), ["type"], "stream_start payload must contain exactly {\"type\":\"stream_start\"}")

        client.disconnect()
    }

    // MARK: - 10. stream_stop is sent exactly once, with the exact payload

    func testStreamStopSendsExactPayloadOnce() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        client.sendStreamStop()
        client.sendStreamStop() // redundant call — must not send a second time
        try? await Task.sleep(nanoseconds: 200_000_000)

        let streamStops = recorder.all.compactMap(decode).filter { $0["type"] as? String == "stream_stop" }
        XCTAssertEqual(streamStops.count, 1, "expected exactly one stream_stop, got \(streamStops.count)")
        XCTAssertEqual(streamStops.first?.keys.sorted(), ["type"], "stream_stop payload must contain exactly {\"type\":\"stream_stop\"}")

        client.disconnect()
    }

    // MARK: - 11. Frames are suppressed after stream_stop until the next stream_start

    func testFramesSuppressedAfterStreamStopUntilNextStreamStart() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        func frameCount() -> Int {
            recorder.all.compactMap(decode).filter { $0["type"] as? String == "frame" }.count
        }

        // Before any stream_start: frames must not be forwarded.
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 1)
        try? await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertEqual(frameCount(), 0, "frame sent before any stream_start")

        client.sendStreamStart()
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 2)
        let sawFirstFrame = await waitUntil { frameCount() == 1 }
        XCTAssertTrue(sawFirstFrame, "frame not sent while streaming was active")

        client.sendStreamStop()
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 3)
        try? await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertEqual(frameCount(), 1, "a frame was sent after stream_stop, before the next stream_start")

        client.sendStreamStart()
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 4)
        let sawSecondFrame = await waitUntil { frameCount() == 2 }
        XCTAssertTrue(sawSecondFrame, "frame not sent again after a fresh stream_start")

        client.disconnect()
    }

    // MARK: - 12. Multiple start/stop cycles on one Tower connection work

    func testMultipleStartStopCyclesOnOneConnection() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        for _ in 0..<3 {
            client.sendStreamStart()
            client.sendStreamStop()
        }
        try? await Task.sleep(nanoseconds: 200_000_000)

        let types = recorder.all.compactMap(decode).compactMap { $0["type"] as? String }
        let starts = types.filter { $0 == "stream_start" }.count
        let stops = types.filter { $0 == "stream_stop" }.count
        XCTAssertEqual(starts, 3, "expected 3 stream_start messages across 3 cycles, got \(starts)")
        XCTAssertEqual(stops, 3, "expected 3 stream_stop messages across 3 cycles, got \(stops)")
        // Same connection throughout — no reconnect was ever triggered.
        XCTAssertEqual(client.status, .online)

        client.disconnect()
    }

    // MARK: - 13. The bounded send window drops the newest frame when full

    /// The window exists so a slow uplink sheds frames instead of queueing
    /// them. Driven synchronously: `sendFrame` hands the message to
    /// URLSession and the completion hops back through
    /// `Task { @MainActor }`, so consecutive calls with no suspension point
    /// between them cannot have had a completion processed yet. That makes the
    /// drop deterministic rather than timing-dependent.
    func testSendWindowDropsFramesWhileEarlierSendsAreStillInFlight() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(metrics: metrics, maxFramesInFlight: 2)
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        client.sendStreamStart()

        // Five frames, no await between them.
        let image = makeTestImage()
        for sequence in 1...5 {
            client.sendFrame(image, width: 2, height: 2, sequence: sequence)
        }

        XCTAssertEqual(
            metrics.currentSnapshot.sendAttempts,
            2,
            "only the window's worth of frames may be handed to the socket"
        )
        XCTAssertEqual(
            metrics.currentSnapshot.sendWindowDrops,
            3,
            "the three frames past the window must be dropped, not queued"
        )
        // Dropped frames must not have been encoded — the drop check comes
        // first precisely so a doomed frame costs nothing.
        XCTAssertEqual(metrics.currentSnapshot.framesEncoded, 2)

        let arrived = await waitUntil {
            recorder.all.compactMap(self.decode).filter { $0["type"] as? String == "frame" }.count == 2
        }
        XCTAssertTrue(arrived, "exactly the two admitted frames must reach the server")

        client.disconnect()
    }

    /// Once earlier sends complete the window must reopen, or the pipeline
    /// would send `maxFramesInFlight` frames and then stop forever.
    func testSendWindowReopensAfterSendsComplete() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(metrics: metrics, maxFramesInFlight: 1)
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        client.sendStreamStart()

        let image = makeTestImage()
        func frameCount() -> Int {
            recorder.all.compactMap(decode).filter { $0["type"] as? String == "frame" }.count
        }

        for sequence in 1...4 {
            client.sendFrame(image, width: 2, height: 2, sequence: sequence)
            let delivered = await waitUntil { metrics.currentSnapshot.sendSuccesses == sequence }
            XCTAssertTrue(delivered, "send \(sequence) never completed, so the window never reopened")
        }

        XCTAssertEqual(metrics.currentSnapshot.sendWindowDrops, 0, "no drop should occur when sends are awaited")
        let allArrived = await waitUntil { frameCount() == 4 }
        XCTAssertTrue(allArrived)

        client.disconnect()
    }

    /// A dropped connection leaves completion handlers pending. If teardown
    /// did not clear the window, those slots would never be returned and the
    /// next connection could never send anything.
    func testSendWindowIsClearedByReconnectSoSendingResumes() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(metrics: metrics, maxFramesInFlight: 1)
        client.connect(to: url(port: port))
        var becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        client.sendStreamStart()
        // Fill the window, then tear the connection down before the send can
        // complete, so a slot is outstanding at teardown time.
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 1)
        // Without this the test would pass even if sendStreamStart() had
        // silently failed and the frame never occupied a window slot at all —
        // proving nothing about the leak it is named for.
        XCTAssertEqual(
            metrics.currentSnapshot.sendAttempts,
            1,
            "frame 1 must actually have consumed the only window slot"
        )
        client.disconnect()

        client.connect(to: url(port: port))
        becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        let before = metrics.currentSnapshot.sendWindowDrops
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 2)
        XCTAssertEqual(
            metrics.currentSnapshot.sendWindowDrops,
            before,
            "the window was still full after reconnect — a leaked in-flight slot"
        )

        let arrived = await waitUntil {
            recorder.all.compactMap(self.decode)
                .contains { $0["type"] as? String == "frame" && $0["seq"] as? Int == 2 }
        }
        XCTAssertTrue(arrived, "the frame after reconnect never reached the server")

        client.disconnect()
    }

    // MARK: - 14. Stream bracket truthfulness

    /// `isStreamingToTower` claims a `stream_start` is outstanding. A start
    /// attempted while offline reaches no socket, so claiming it would let a
    /// whole session's frames be forwarded outside any bracket.
    func testStreamStartWhileOfflineDoesNotClaimToBeStreaming() {
        let client = TowerClient()
        XCTAssertEqual(client.status, .offline)

        client.sendStreamStart()

        XCTAssertFalse(
            client.isStreamingToTower,
            "a stream_start that reached no socket must not mark the stream open"
        )
    }

    /// No `stream_start` survives a socket, so the flag must not either —
    /// otherwise frames flow onto a connection the Tower never saw a start on.
    func testDisconnectClearsTheStreamBracket() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        XCTAssertTrue(client.isStreamingToTower)

        client.disconnect()
        XCTAssertFalse(client.isStreamingToTower, "the stream bracket outlived the socket it was opened on")
    }

    /// Clearing the bracket on teardown is only safe because it can be
    /// reopened: `ProjectManager` re-sends `stream_start` when the Tower comes
    /// back online during a live camera stream. If a fresh `stream_start`
    /// could not restore frame flow after a reconnect, a single mid-session
    /// network blip would silently discard every remaining frame.
    func testStreamBracketCanBeReopenedAfterAReconnect() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        var becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        client.disconnect()
        XCTAssertFalse(client.isStreamingToTower)

        // What ProjectManager now does when status returns to .online.
        client.connect(to: url(port: port))
        becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)
        client.sendStreamStart()
        XCTAssertTrue(client.isStreamingToTower, "the bracket must be reopenable on the new socket")

        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 7)
        let arrived = await waitUntil {
            recorder.all.compactMap(self.decode)
                .contains { $0["type"] as? String == "frame" && $0["seq"] as? Int == 7 }
        }
        XCTAssertTrue(arrived, "frames must flow again after the bracket is reopened")

        client.disconnect()
    }

    /// The counter sits beside the per-session `frameCount` on the dashboard,
    /// so it has to reset on the same boundary rather than accumulating for
    /// the app's lifetime.
    func testFrameResultCountResetsPerStreamBracket() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient()
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        for seq in 1...2 {
            server.send(text: #"{"type":"frame_result","seq":\#(seq),"mean_intensity":0.1,"processing_ms":1.0}"#)
        }
        let counted = await waitUntil { client.frameResultCount == 2 }
        XCTAssertTrue(counted, "expected 2 replies, got \(client.frameResultCount)")

        client.sendStreamStop()
        client.sendStreamStart()
        XCTAssertEqual(client.frameResultCount, 0, "a new stream bracket must start from zero replies")

        client.disconnect()
    }

    // MARK: - 15. Send window sizing and slot instrumentation

    /// The window's capacity is derived from a latency budget rather than
    /// picked, so the shipped number and the arithmetic that justifies it must
    /// not be able to drift apart.
    func testDefaultWindowCapacityIsTheLatencyBudgetedOne() {
        let client = TowerClient(metrics: SenderMetrics())
        XCTAssertEqual(client.maxFramesInFlight, TowerClient.defaultMaxFramesInFlight)
        XCTAssertEqual(
            TowerClient.defaultMaxFramesInFlight,
            SendWindow.capacity(
                forTargetFPS: FrameRateGate.towerTargetFPS,
                latencyBudget: TowerClient.outboundLatencyBudget
            )
        )
        XCTAssertGreaterThan(
            client.maxFramesInFlight,
            2,
            "the baseline capacity of 2 is what held the physical run to 3.4 fps"
        )
    }

    /// Every completed send must contribute a timing sample, or the
    /// `capacity / slotLifetime` diagnosis has nothing to divide.
    func testACompletedSendRecordsItsSlotTimings() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(metrics: metrics, maxFramesInFlight: 2)
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        client.sendStreamStart()
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 1)

        let completed = await waitUntil { metrics.currentSnapshot.sendSuccesses == 1 }
        XCTAssertTrue(completed)

        let snapshot = metrics.currentSnapshot
        XCTAssertEqual(snapshot.slotSamples, 1, "a completed send must report a slot lifetime")
        let latency = try XCTUnwrap(snapshot.sendLatencyMsAverage)
        let lifetime = try XCTUnwrap(snapshot.slotLifetimeMsAverage)
        XCTAssertGreaterThanOrEqual(
            lifetime,
            latency,
            "the slot is held until the main actor returns it, so it cannot outlive its own transport time"
        )
        XCTAssertNotNil(snapshot.windowLimitedFPS(capacity: client.maxFramesInFlight))

        client.disconnect()
    }

    /// A send abandoned by teardown has no slot left to time. It must still be
    /// accounted as a terminal outcome, but it must not contribute a sample —
    /// a teardown-length "slot lifetime" would poison the average that the
    /// window is sized against.
    func testAnAbandonedSendContributesNoTimingSample() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(metrics: metrics, maxFramesInFlight: 1)
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        client.sendStreamStart()
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 1)
        XCTAssertEqual(metrics.currentSnapshot.sendAttempts, 1)
        client.disconnect()

        let settled = await waitUntil { metrics.currentSnapshot.sendAbandoned == 1 }
        XCTAssertTrue(settled, "the outstanding send never reached a terminal outcome")
        XCTAssertEqual(metrics.currentSnapshot.slotSamples, 0)
        XCTAssertNil(metrics.currentSnapshot.slotLifetimeMsAverage)
    }

    /// Stall detection must not fire on ordinary backpressure. A full window
    /// that is still draining is the mechanism working, and answering it with
    /// a reconnect would turn a shed frame into a dropped connection.
    func testOrdinaryWindowDropsDoNotTripStallDetection() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(metrics: metrics, maxFramesInFlight: 2)
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        client.sendStreamStart()
        let image = makeTestImage()
        for sequence in 1...8 {
            client.sendFrame(image, width: 2, height: 2, sequence: sequence)
        }

        XCTAssertGreaterThan(metrics.currentSnapshot.sendWindowDrops, 0, "the window must actually have filled")
        XCTAssertEqual(metrics.currentSnapshot.stallRecoveries, 0)
        XCTAssertEqual(client.status, .online, "a full window is not a broken connection")

        client.disconnect()
    }

    // MARK: - 16. Automatic reconnect

    /// A mid-session drop on a remote Tailscale path is the expected case, and
    /// until now nothing in the app re-established the connection: the Tower
    /// pill went red and stayed red until someone tapped Connect. The
    /// stream-bracket reopening in `ProjectManager` was written for a
    /// reconnect that could not happen.
    func testADroppedConnectionIsReestablishedAutomatically() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics(), autoReconnect: true)
        client.connect(to: url(port: port))
        var becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.simulateDelegateCloseForTesting(code: .abnormalClosure)

        // Waiting for the drop to actually land first is what makes the second
        // wait meaningful. The delegate callback hops to the main actor, so
        // polling for `.online` straight away would observe the *pre-drop*
        // state and pass without a reconnect ever happening.
        let leftOnline = await waitUntil { client.status != .online }
        XCTAssertTrue(leftOnline, "the simulated close never took effect")

        becameOnline = await waitUntil(timeout: 6) { client.status == .online }
        XCTAssertTrue(becameOnline, "the connection was never re-established")

        client.disconnect()
    }

    /// Reconnect must never override the user. A deliberate disconnect that
    /// silently came back would make the control a lie.
    func testDisconnectIsNotUndoneByAPendingReconnect() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics(), autoReconnect: true)
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        // The reconnect has to be genuinely scheduled before it can be
        // genuinely countermanded: `disconnect()` called in the same actor turn
        // as the simulated close would tear the socket down first, and the
        // close would then be discarded as stale without ever scheduling
        // anything. Waiting for `.failed` is what makes this test about
        // cancellation rather than about ordering.
        client.simulateDelegateCloseForTesting(code: .abnormalClosure)
        let failed = await waitUntil { client.status != .online }
        XCTAssertTrue(failed, "a reconnect must have been scheduled for this test to mean anything")

        client.disconnect()

        // Comfortably past the first backoff step.
        try? await Task.sleep(nanoseconds: 1_500_000_000)
        XCTAssertEqual(client.status, .offline, "a cancelled reconnect must not resurrect the connection")
    }

    /// Reconnect is opt-in precisely so that the failure-path tests above keep
    /// asserting about a settled status. This pins that default.
    func testReconnectIsOffUnlessAskedFor() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.simulateDelegateCloseForTesting(code: .abnormalClosure)
        let leftOnline = await waitUntil { client.status != .online }
        XCTAssertTrue(leftOnline)

        try? await Task.sleep(nanoseconds: 1_500_000_000)
        guard case .failed = client.status else {
            XCTFail("expected the connection to stay failed, got \(client.status)")
            return
        }
    }

    // MARK: - 17. Stall detection end to end

    /// Occupies the whole send window and then holds the main actor without
    /// yielding, so the outstanding send's completion cannot hop back to
    /// release its slot.
    ///
    /// A busy-wait rather than `Task.sleep`, deliberately: sleeping yields the
    /// actor, the queued completion runs, the slot comes back and there is no
    /// stall left to detect. Blocking is the only way to hold a window open
    /// against a loopback server that answers instantly, and it makes the test
    /// deterministic rather than timing-dependent.
    private func fillWindowAndHoldMainActor(
        _ client: TowerClient,
        seconds: TimeInterval
    ) {
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 1)
        let holdUntil = MonotonicClock.now + seconds
        while MonotonicClock.now < holdUntil {
            // Intentionally empty: the point is to not suspend.
        }
    }

    /// The path that exists because `URLSessionWebSocketTask` cannot cancel or
    /// time out one outstanding send: a window that stops draining has to be
    /// answered at connection granularity or the pipeline simply reports drops
    /// for as long as the peer stays wedged — 52 seconds, in the physical
    /// baseline.
    func testAWedgedSendWindowReplacesTheConnection() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(
            metrics: metrics,
            maxFramesInFlight: 1,
            stallTimeout: 0.05,
            autoReconnect: true
        )
        client.connect(to: url(port: port))
        var becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        client.sendStreamStart()

        // 0.2 s is past `stallTimeout` but well inside `mainActorGapAllowance`,
        // so the next frame is offered by a demonstrably responsive actor and
        // the verdict is reached rather than deferred.
        fillWindowAndHoldMainActor(client, seconds: 0.2)
        XCTAssertEqual(metrics.currentSnapshot.sendAttempts, 1, "the window must actually be occupied")

        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 2)

        XCTAssertEqual(metrics.currentSnapshot.stallRecoveries, 1, "the wedged window was not detected")
        XCTAssertNotEqual(client.status, .online, "a wedged socket must be torn down, not kept")
        // The frame that triggered the teardown still has to reach a terminal
        // outcome, or `framesUnaccounted` would drift by one per stall.
        XCTAssertGreaterThan(metrics.currentSnapshot.sendWindowDrops, 0)

        becameOnline = await waitUntil(timeout: 6) { client.status == .online }
        XCTAssertTrue(becameOnline, "the replacement connection never came up")

        client.disconnect()
    }

    /// The false-positive guard, and the reason `mainActorGapAllowance` exists.
    ///
    /// A slot is held until the completion handler's hop back to the main actor
    /// runs, so if *this actor* stalls, every slot looks old through no fault of
    /// the socket. Tearing down a healthy connection because the main thread
    /// hitched would invert the very diagnosis the slot-timing instrumentation
    /// was added to make possible.
    func testAStalledMainActorIsNotMistakenForAWedgedSocket() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(
            metrics: metrics,
            maxFramesInFlight: 1,
            stallTimeout: 0.05
        )
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        client.sendStreamStart()

        // Same setup as above, but the actor is held past
        // `mainActorGapAllowance` — which is exactly what a main-actor stall
        // looks like from here.
        fillWindowAndHoldMainActor(client, seconds: TowerClient.mainActorGapAllowance + 0.1)
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 2)

        XCTAssertEqual(
            metrics.currentSnapshot.stallRecoveries,
            0,
            "a main-actor stall must not be blamed on the socket"
        )
        XCTAssertEqual(client.status, .online, "the connection was healthy and must be kept")

        client.disconnect()
    }
}

/// Thread-safe capture of every text message a MockTowerServer receives, so
/// tests can assert on the exact sequence/content sent over the wire.
private final class MessageRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var messages: [String] = []

    func record(_ text: String) {
        lock.lock()
        messages.append(text)
        lock.unlock()
    }

    var all: [String] {
        lock.lock()
        defer { lock.unlock() }
        return messages
    }
}
