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

import Combine
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

    /// `XCTAssertTrue(await waitUntil { … })` does not compile — an autoclosure
    /// cannot carry an `await` — so the assertion is wrapped rather than
    /// hoisted at every call site. `#filePath`/`#line` default arguments keep
    /// the failure pointing at the test rather than at this helper.
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

    /// Waits for the connection's own capability request to land.
    ///
    /// `TowerClient` sends `{"type":"cartridges"}` once per connection, right
    /// after the pong. Tests that assert "nothing else reached the wire" have
    /// to take their baseline *after* it, or they are racing the handshake
    /// rather than measuring what they claim to measure.
    private func waitForDiscovery(_ recorder: MessageRecorder) async -> Bool {
        await waitUntil {
            recorder.all.compactMap(self.decode).contains { $0["type"] as? String == "cartridges" }
        }
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

    // MARK: - 18. Automatic connection

    /// The invariant the whole auto-connect design rests on: bringing the Tower
    /// up at launch must not put a single frame on the wire.
    ///
    /// It holds structurally rather than by convention — `sendFrame` requires a
    /// `stream_start` bracket as well as an online socket, and only a live
    /// camera stream opens one — but that is exactly the kind of guarantee that
    /// quietly stops being true, so it is pinned here.
    func testAutomaticConnectOpensTheSocketButSendsNothing() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(metrics: metrics)
        client.connectIfIdle(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        metrics.begin()
        XCTAssertFalse(client.isStreamingToTower, "an automatic connect must not open a stream bracket")

        // A frame offered without a bracket must be refused, not sent.
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 1)
        XCTAssertEqual(metrics.currentSnapshot.sendAttempts, 0)
        XCTAssertEqual(metrics.currentSnapshot.sessionGateDrops, 1)

        let frames = recorder.all.compactMap(decode).filter { $0["type"] as? String == "frame" }
        XCTAssertTrue(frames.isEmpty, "no frame may reach the Tower from an automatic connect")

        client.disconnect()
    }

    /// `connectIfIdle` is called from a SwiftUI `.task`, which can run more than
    /// once. A second call must not punch a hole in a live connection —
    /// `connect()` in that situation tears the socket down, which would close
    /// the stream bracket mid-session and drop frames.
    func testAutomaticConnectLeavesAHealthyConnectionAlone() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        XCTAssertTrue(client.isStreamingToTower)

        client.connectIfIdle(to: url(port: port))

        // Teardown would have cleared the bracket, so this is the precise
        // observable difference between "did nothing" and "reconnected".
        XCTAssertTrue(client.isStreamingToTower, "an automatic connect tore down a live connection")
        XCTAssertEqual(client.status, .online)

        client.disconnect()
    }

    /// A Tower that has failed must stay visibly failed. Automation retrying on
    /// its own is how an app ends up looking like it is still trying after it
    /// has given up — and it would bypass the bounded backoff that exists to
    /// stop exactly that.
    func testAutomaticConnectDoesNotRetryAFailedConnection() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.simulateDelegateCloseForTesting(code: .abnormalClosure)
        let failed = await waitUntil { client.status != .online }
        XCTAssertTrue(failed)

        client.connectIfIdle(to: url(port: port))
        try? await Task.sleep(nanoseconds: 400_000_000)

        guard case .failed = client.status else {
            XCTFail("automatic connect resurrected a failed connection: \(client.status)")
            return
        }
    }

    /// After a deliberate disconnect the client is `.offline`, and automation
    /// may bring it back — that is the state auto-connect exists for. Pinned so
    /// the `.offline` guard is not mistaken for "never reconnect".
    func testAutomaticConnectDoesConnectWhenOffline() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        XCTAssertEqual(client.status, .offline)

        client.connectIfIdle(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline, "automatic connect must work from the idle state")

        client.disconnect()
    }

    // MARK: - 19. The Tower's own reply, surfaced

    /// `mean_intensity` was decoded for a log line and discarded. It is the only
    /// thing the Tower says about a frame's *content*, and a workspace that
    /// shows it is describing what the Tower really does instead of a
    /// capability it does not have.
    func testTheLatestFrameResultIsSurfacedNotJustCounted() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        XCTAssertNil(client.latestFrameResult, "nothing has been reported yet")

        server.send(text: #"{"type":"frame_result","seq":7,"mean_intensity":0.42,"processing_ms":8.5}"#)
        let arrived = await waitUntil { client.latestFrameResult != nil }
        XCTAssertTrue(arrived)

        XCTAssertEqual(client.latestFrameResult?.sequence, 7)
        XCTAssertEqual(client.latestFrameResult?.meanIntensity ?? -1, 0.42, accuracy: 0.0001)
        XCTAssertEqual(client.latestFrameResult?.processingMs ?? -1, 8.5, accuracy: 0.0001)

        client.disconnect()
    }

    /// Captured for *every* reply, not only the one-in-twelve that gets logged.
    /// The decode used to sit inside the log gate; a surfaced value that
    /// updates at a twelfth of the reply rate would be stale on screen.
    func testEveryReplyUpdatesTheSurfacedResultNotJustLoggedOnes() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        // Two consecutive replies: the second is not on the logging stride, so
        // under the old decode-inside-the-log-gate arrangement it would be lost.
        server.send(text: #"{"type":"frame_result","seq":1,"mean_intensity":0.10,"processing_ms":1.0}"#)
        let first = await waitUntil { client.latestFrameResult?.sequence == 1 }
        XCTAssertTrue(first)

        server.send(text: #"{"type":"frame_result","seq":2,"mean_intensity":0.90,"processing_ms":1.0}"#)
        let second = await waitUntil { client.latestFrameResult?.sequence == 2 }
        XCTAssertTrue(second, "a reply between log lines was not surfaced")
        XCTAssertEqual(client.latestFrameResult?.meanIntensity ?? -1, 0.90, accuracy: 0.0001)

        client.disconnect()
    }

    /// Scoped to the stream bracket, like `frameResultCount` beside it: a
    /// reading from the previous bracket shown against a fresh one is a stale
    /// claim about the current session.
    func testTheSurfacedResultResetsWithTheStreamBracket() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        server.send(text: #"{"type":"frame_result","seq":1,"mean_intensity":0.5,"processing_ms":1.0}"#)
        let arrived = await waitUntil { client.latestFrameResult != nil }
        XCTAssertTrue(arrived)

        client.sendStreamStop()
        client.sendStreamStart()
        XCTAssertNil(client.latestFrameResult, "a new bracket must not inherit the previous one's reply")

        client.disconnect()
    }

    /// The Tower's per-frame vocabulary is six keys, not three.
    ///
    /// `tower/tower/routes/ws.py:148-155` builds every `frame_result` with
    /// `seq`, `processing_ms`, **`result_value`, `result_label` and
    /// `stage_ms`** — all five unconditional — then adds `mean_intensity` and
    /// `metrics` only when the experiment produced them. `ExperimentResult`
    /// (`tower/tower/experiments/__init__.py:106-117`) is where those fields
    /// come from.
    ///
    /// This app decoded three of them and dropped the rest, and the doc
    /// comment on `TowerFrameResult` asserted that three *was* the whole
    /// vocabulary. `result_label` is the experiment's own headline answer, so
    /// what was being discarded was the only thing the Tower says about what
    /// it *concluded*, as opposed to how long it took.
    func testTheWholeFrameResultVocabularyIsDecodedNotJustTheTimings() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        // Shaped exactly as `ws.py` builds it, including the optional pair.
        server.send(text: #"{"type":"frame_result","seq":11,"processing_ms":8.5,"result_value":0.73,"result_label":"baseline","stage_ms":{"decode":2.0,"infer":6.5},"mean_intensity":0.42,"metrics":{"edges":1024.0}}"#)

        let arrived = await waitUntil { client.latestFrameResult?.sequence == 11 }
        XCTAssertTrue(arrived)

        let result = try XCTUnwrap(client.latestFrameResult)
        XCTAssertEqual(result.processingMs ?? -1, 8.5, accuracy: 0.0001)
        XCTAssertEqual(result.meanIntensity ?? -1, 0.42, accuracy: 0.0001)

        XCTAssertEqual(result.resultValue ?? -1, 0.73, accuracy: 0.0001,
                       "the experiment's headline number was dropped")
        XCTAssertEqual(result.resultLabel, "baseline",
                       "the experiment's own name for its answer was dropped")
        XCTAssertEqual(result.stageMs, ["decode": 2.0, "infer": 6.5],
                       "the per-stage timings were dropped")
        XCTAssertEqual(result.metrics, ["edges": 1024.0],
                       "the additive measurement channel was dropped")

        client.disconnect()
    }

    /// The two optional keys are genuinely optional, and their absence must
    /// not be read as zero.
    ///
    /// `ws.py:156-165` omits `mean_intensity` when the experiment reported
    /// none and omits `metrics` entirely when empty — "an experiment whose
    /// headline says everything does not pay for an empty object on every
    /// frame". Absent is not `0.0`.
    func testTheOptionalHalfOfAFrameResultIsAbsentRatherThanZero() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        server.send(text: #"{"type":"frame_result","seq":3,"processing_ms":1.0,"result_value":2.0,"result_label":"edges","stage_ms":{}}"#)
        let arrived = await waitUntil { client.latestFrameResult?.sequence == 3 }
        XCTAssertTrue(arrived)

        let result = try XCTUnwrap(client.latestFrameResult)
        XCTAssertNil(result.meanIntensity, "an omitted intensity is unknown, not dark")
        XCTAssertTrue(result.metrics.isEmpty)
        XCTAssertTrue(result.stageMs.isEmpty)
        XCTAssertEqual(result.resultLabel, "edges")

        client.disconnect()
    }

    /// A reply belongs to the socket that carried it.
    ///
    /// `teardownConnection` already clears everything else scoped to one
    /// connection — the send window, `lastSendFrameAt`, `isStreamingToTower` —
    /// and says of the last of those that leaving it set across a teardown
    /// "would be a lie". `latestFrameResult` was cleared only by
    /// `sendStreamStart`/`sendStreamStop`, so a socket that dropped mid-capture
    /// left the dead connection's reading on screen under the caption "latest
    /// Tower reply" (`HomeWorkspaceView.swift`) — for the whole outage, and
    /// permanently once the reconnect budget is spent.
    func testAFrameResultDoesNotOutliveTheSocketThatCarriedIt() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        // Mid-capture: a bracket is open, so nothing else would clear this.
        client.sendStreamStart()
        server.send(text: #"{"type":"frame_result","seq":5,"processing_ms":1.0,"result_value":1.0,"result_label":"baseline","stage_ms":{},"mean_intensity":0.5}"#)
        let arrived = await waitUntil { client.latestFrameResult != nil }
        XCTAssertTrue(arrived)

        // The socket drops under it. `autoReconnect` is off by default, so this
        // settles rather than racing a retry.
        server.stop()
        let dropped = await waitUntil { client.status != .online }
        XCTAssertTrue(dropped, "the client did not notice the socket close")

        XCTAssertNil(
            client.latestFrameResult,
            "a reading from a dead socket was still being offered as the latest Tower reply"
        )

        client.disconnect()
    }

    // MARK: - Cartridge integration: runtime ownership

    /// Building and discarding every cartridge view model must not disturb the
    /// runtime.
    ///
    /// ## What this proves, and — precisely — what it does not
    ///
    /// A workspace's `@StateObject` view model is destroyed when the cartridge
    /// changes. If one of them held the `TowerClient` or the `GlassesConnection`,
    /// destroying it could close the socket or stop the camera — and a stream
    /// bracket that closes mid-session silently discards every frame after it.
    ///
    /// So this constructs and releases all four view models repeatedly while a
    /// real socket is open with a live stream bracket, then asserts the
    /// connection is untouched and nothing new reached the wire. It would fail
    /// if any view model retained a runtime object, opened one, or sent
    /// anything.
    ///
    /// **It does not switch cartridges.** No workspace is installed, no view is
    /// mounted, and `ContentView` is not involved — this is a unit test of what
    /// the view models own, which is the half of a cartridge switch that can be
    /// tested without a view hierarchy. The other half (SwiftUI actually tearing
    /// a workspace down, and the camera surviving it) needs DAT and a device,
    /// and no mock `WearablesInterface` exists. The structural argument stands
    /// in for it — no view model is handed a `GlassesConnection`, and
    /// `ContentView` passes one to World Builder only — and it is a
    /// Simulator/device check.
    func testDiscardingCartridgeViewModelsDoesNotDisturbALiveStream() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let metrics = SenderMetrics()
        let client = TowerClient(metrics: metrics)
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline)

        client.sendStreamStart()
        XCTAssertTrue(client.isStreamingToTower, "the test needs a live bracket to be meaningful")

        // Wait for the bracket to actually reach the server before snapshotting
        // the wire. Counting before it lands would make the later "nothing new
        // was sent" assertion race against this send rather than against the
        // view models.
        let bracketLanded = await waitUntil {
            recorder.all.compactMap(self.decode).contains { $0["type"] as? String == "stream_start" }
        }
        XCTAssertTrue(bracketLanded)
        let discovered = await waitForDiscovery(recorder)
        XCTAssertTrue(discovered, "the connection's own discovery never landed")

        let baseline = recorder.all.count

        // Three rounds of constructing and releasing every cartridge view
        // model — the object-lifetime half of what a cartridge switch does to
        // them.
        for _ in 0..<3 {
            _ = WorldBuilderViewModel(client: UnavailableWorldBuilderClient())
            _ = ExperimentalCVViewModel(client: UnavailableExperimentalCVClient())
            _ = DocumentMemoryViewModel(client: UnavailableDocumentMemoryClient())
            _ = SceneUnderstandingViewModel(client: UnavailableSceneUnderstandingClient())
        }

        XCTAssertEqual(client.status, .online, "a workspace teardown closed the Tower connection")
        XCTAssertTrue(
            client.isStreamingToTower,
            "a workspace teardown closed the stream bracket; every later frame would be dropped"
        )
        XCTAssertEqual(
            recorder.all.count,
            baseline,
            "a cartridge view model put something on the wire"
        )

        // The bracket still works after all that, which is the property a
        // silently-closed socket would break without changing `status`.
        client.sendFrame(makeTestImage(), width: 2, height: 2, sequence: 1)
        let frameArrived = await waitUntil {
            recorder.all.compactMap(self.decode).contains { $0["type"] as? String == "frame" }
        }
        XCTAssertTrue(frameArrived, "the sender stopped working after cartridge switching")

        client.sendStreamStop()
        client.disconnect()
    }

    /// A cartridge view model must not be able to reach the Tower at all.
    ///
    /// Constructing every one of them against a live, idle connection and then
    /// asserting the wire is silent is the observable form of "these hold no
    /// runtime references": a view model that opened its own socket, sent a
    /// module-selection message, or asked the Tower anything would show up here.
    ///
    /// `docs/08-IOS-CARTRIDGE-SHELL.md` forbids inventing a module-selection
    /// message. This is that prohibition as a test rather than as a promise.
    func testCartridgeViewModelsSendNothingToTheTower() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline, "expected .online, got \(client.status)")
        let discovered = await waitForDiscovery(recorder)
        XCTAssertTrue(discovered, "the connection's own discovery never landed")

        let baseline = recorder.all.count

        let world = WorldBuilderViewModel(client: UnavailableWorldBuilderClient())
        let lab = ExperimentalCVViewModel(client: UnavailableExperimentalCVClient())
        let memory = DocumentMemoryViewModel(client: UnavailableDocumentMemoryClient())
        let scene = SceneUnderstandingViewModel(client: UnavailableSceneUnderstandingClient())

        // Every request surface any of them exposes, exercised. Each must be
        // refused locally rather than reaching the socket.
        lab.run(CVExperiment(id: "anything", name: "Anything"))
        memory.queryText = "anything"
        memory.submitTypedQuery()
        memory.submit(.recent(limit: 3), origin: .externalIntent)

        // Give anything asynchronous a chance to have escaped to the wire.
        try? await Task.sleep(nanoseconds: 200_000_000)

        XCTAssertEqual(
            recorder.all.count,
            baseline,
            "a cartridge view model sent a message the Tower protocol does not contain"
        )
        XCTAssertFalse(client.isStreamingToTower, "a view model opened a stream bracket")
        XCTAssertEqual(client.status, .online)

        // And each of them still reports the truth rather than a state invented
        // from a request that went nowhere.
        XCTAssertEqual(world.phase(isTowerReachable: true), .unsupported)
        XCTAssertEqual(lab.phase(isTowerReachable: true), .unsupported)
        XCTAssertEqual(memory.phase(isTowerReachable: true), .unsupported)
        XCTAssertEqual(scene.phase(isTowerReachable: true), .unsupported)
        XCTAssertNotNil(lab.lastRequestFailure, "the refusal was swallowed instead of surfaced")
        XCTAssertNotNil(memory.lastRequestFailure)

        client.disconnect()
    }

    /// A connected Tower does not make any cartridge available.
    ///
    /// The counterpart to `testNoCartridgeIsAvailableWhetherOrNotTheTowerIsReachable`
    /// in `ProductShellTests`, asserted against a genuinely open socket rather
    /// than a boolean — because "reachable" being passed as a parameter is
    /// exactly the sort of thing that can be wired to the wrong value.
    func testAnOnlineTowerStillDeclaresNoCartridgeContracts() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        let becameOnline = await waitUntil { client.status == .online }
        XCTAssertTrue(becameOnline, "expected .online, got \(client.status)")

        let isReachable = client.status == .online
        XCTAssertTrue(isReachable)

        for cartridge in Cartridge.catalog {
            XCTAssertEqual(
                TowerCapabilities.availability(for: cartridge.id, isTowerReachable: isReachable),
                .noContract,
                "\(cartridge.name) became available merely because the socket opened"
            )
        }

        client.disconnect()
    }

    // MARK: - 20. The result channel

    private static let worldBuilderContract = "world_builder.status/2026-08-25"

    private var declarationJSON: String {
        """
        {"type":"cartridges",
         "envelope_contract":"cartridge_results.envelope/2026-08-23",
         "cartridges":[{"cartridge":"world_builder","result_type":"status",
                        "contract":"\(Self.worldBuilderContract)",
                        "available":true,"unavailable_reason":null,
                        "snapshot_only":true}],
         "not_offered":[{"cartridge":"document_memory","reason":"no contract offered"}]}
        """
    }

    /// A `cartridge_result` carrying a live world, shaped exactly as the Tower's
    /// `_attach_ios_projection` builds it.
    private func resultJSON(
        seq: Int,
        revision: String,
        revisionChanged: Bool = true,
        modelState: String = "receiving",
        keyframes: Int = 4
    ) -> String {
        """
        {"type":"cartridge_result",
         "envelope_contract":"cartridge_results.envelope/2026-08-23",
         "subscription_id":"sub-1","cartridge":"world_builder","result_type":"status",
         "contract":"\(Self.worldBuilderContract)",
         "seq":\(seq),"revision":"\(revision)","revision_changed":\(revisionChanged),
         "coalesced":0,"cursor_status":null,"snapshot":true,
         "tower_sent_at":1787463092.958,"time_basis":"tower-receipt",
         "payload":{"model_state":"\(modelState)","model_state_reason":null,
           "world_snapshot":{"name":"Probe Room","world_id":"be5076",
             "keyframe_count":\(keyframes),"revision":"\(revision)",
             "tracking":"good","scale":"relative","mapping_seconds":0.0789,
             "calibration":"calibrated",
             "geometry":{"representation":"sparse point cloud","element_count":1360,
                         "is_incremental":false},
             "trajectory":{"pose_count":\(keyframes),"path_length":2.853,
                           "path_length_unit":"world units","scale":"relative"},
             "persistence":{"state":"saved","revision":"67ccaee7"}}}}
        """
    }

    /// Collects result-channel events off the client's publisher.
    private func collectEvents(_ client: TowerClient) -> EventRecorder {
        let recorder = EventRecorder()
        recorder.cancellable = client.cartridgeResults.sink { recorder.record($0) }
        return recorder
    }

    /// Discovery must follow the pong, never precede it.
    ///
    /// The Tower never speaks first, so nothing can arrive early — but a client
    /// that asked for capabilities before validating would read its own reply
    /// into the handshake, which is the one ordering the contract calls out.
    func testCapabilityDiscoveryIsSentOnceAndOnlyAfterThePong() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        await expect { client.status == .online }
        let discovered = await waitForDiscovery(recorder)
        XCTAssertTrue(discovered)

        let types = recorder.all.compactMap(decode).compactMap { $0["type"] as? String }
        XCTAssertEqual(types.first, "ping", "something reached the Tower before the handshake")
        XCTAssertEqual(
            types.filter { $0 == "cartridges" }.count,
            1,
            "capability discovery was sent more than once for one connection"
        )

        client.disconnect()
    }

    /// The declaration is cached, and it is cached as what the Tower said —
    /// not reduced to a boolean on the way in.
    func testTheCartridgeDeclarationIsDecodedAndCached() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        await expect { client.status == .online }

        server.send(text: declarationJSON)
        await expect { client.cartridgeDeclaration != nil }

        let offer = client.cartridgeDeclaration?.offer(forTowerCartridge: "world_builder")
        XCTAssertEqual(offer?.contract, Self.worldBuilderContract)
        XCTAssertEqual(offer?.resultType, "status")
        XCTAssertEqual(offer?.available, true)
        XCTAssertEqual(offer?.snapshotOnly, true)
        XCTAssertNil(offer?.unavailableReason)
        XCTAssertEqual(
            client.cartridgeDeclaration?.envelopeContract,
            "cartridge_results.envelope/2026-08-23"
        )
        // `not_offered` is for operators. Reading presence there as an offer is
        // the mistake the contract names, so it is not decoded at all.
        XCTAssertNil(client.cartridgeDeclaration?.offer(forTowerCartridge: "document_memory"))

        client.disconnect()
    }

    /// What the Tower can do is a property of the Tower's build, not of this
    /// socket. Clearing the cache on a drop would turn every blip into "this
    /// will never work" when the truthful reading is "not reachable".
    func testTheDeclarationSurvivesADisconnect() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        await expect { client.status == .online }
        server.send(text: declarationJSON)
        await expect { client.cartridgeDeclaration != nil }

        client.disconnect()
        XCTAssertNotNil(client.cartridgeDeclaration)
        XCTAssertEqual(
            TowerCapabilities.availability(
                for: "world-build",
                declaredBy: client.cartridgeDeclaration,
                isTowerReachable: false
            ),
            .towerUnreachable
        )
    }

    /// The envelope decodes, and the ordering between the ack and the snapshot
    /// that follows it is preserved — which is why they share one stream.
    func testTheResultChannelDeliversAckThenSnapshotInOrder() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        let events = collectEvents(client)
        client.connect(to: url(port: port))
        await expect { client.status == .online }

        server.send(text: """
            {"type":"result_subscribed","envelope_contract":"cartridge_results.envelope/2026-08-23",
             "subscription_id":"sub-1","cartridge":"world_builder","result_type":"status",
             "contract":"\(Self.worldBuilderContract)","snapshot_only":true,
             "world_id":null,"session_id":null,"cursor_status":"absent"}
            """)
        server.send(text: resultJSON(seq: 1, revision: "e252f739c1cdedab"))

        await expect { events.all.count >= 2 }

        guard case .subscribed(let ack) = events.all[0] else {
            return XCTFail("expected the ack first, got \(events.all[0])")
        }
        XCTAssertEqual(ack.subscriptionID, "sub-1")
        XCTAssertEqual(ack.cursorStatus, "absent")

        guard case .result(let envelope) = events.all[1] else {
            return XCTFail("expected the snapshot second, got \(events.all[1])")
        }
        XCTAssertEqual(envelope.sequence, 1)
        XCTAssertEqual(envelope.revision, "e252f739c1cdedab")
        XCTAssertTrue(envelope.revisionChanged)
        XCTAssertEqual(envelope.coalesced, 0)
        XCTAssertTrue(envelope.isSnapshot)
        XCTAssertEqual(envelope.payload["model_state"] as? String, "receiving")

        client.disconnect()
    }

    /// Every `result_error` is non-fatal on this socket, including the two the
    /// Tower sends unsolicited — which carry no `envelope_contract` at all, and
    /// would fail a decoder that required one.
    func testEveryResultErrorLeavesTheFramePathWorking() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        let events = collectEvents(client)
        client.connect(to: url(port: port))
        await expect { client.status == .online }

        // Solicited, with reason-specific extras.
        server.send(text: """
            {"type":"result_error","envelope_contract":"cartridge_results.envelope/2026-08-23",
             "reason":"unknown_cartridge","message":"no such cartridge",
             "cartridge":"nope","result_type":"status","offered":["world_builder"]}
            """)
        // Unsolicited, and deliberately without `envelope_contract`.
        server.send(text: """
            {"type":"result_error","reason":"consumer_too_slow","subscription_id":"sub-1",
             "cartridge":"world_builder","result_type":"status","message":"closed"}
            """)
        // Two keys and nothing else.
        server.send(text: #"{"type":"result_unsubscribed","subscription_id":"sub-1"}"#)
        // The Tower saying it does not implement something we sent.
        server.send(text: """
            {"type":"protocol_error","reason":"unknown_message_type",
             "message_type":42,"message":"this Tower does not implement that message type"}
            """)

        await expect { events.all.count >= 3 }

        let errors = events.all.compactMap { event -> CartridgeResultError? in
            if case .failed(let error) = event { return error }
            return nil
        }
        XCTAssertEqual(errors.map(\.reason), ["unknown_cartridge", "consumer_too_slow"])
        XCTAssertFalse(errors[0].closesSubscription)
        XCTAssertTrue(errors[1].closesSubscription)
        XCTAssertEqual(errors[1].subscriptionID, "sub-1")

        // The whole point: the connection and the frame path are untouched.
        server.send(text: #"{"type":"frame_result","seq":7,"mean_intensity":0.3,"processing_ms":3.2}"#)
        await expect { client.frameResultCount >= 1 }
        XCTAssertEqual(client.status, .online)

        client.disconnect()
    }

    /// `frame_result` must be field-for-field what it always was while results
    /// share the socket. One TCP stream, two message families, demultiplexed by
    /// `type` and nothing else.
    func testFrameResultIsUnaffectedByResultTrafficOnTheSameSocket() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        await expect { client.status == .online }

        server.send(text: declarationJSON)
        server.send(text: #"{"type":"frame_result","seq":1,"mean_intensity":0.42,"processing_ms":8.5}"#)
        server.send(text: resultJSON(seq: 1, revision: "aaaa"))
        server.send(text: #"{"type":"frame_result","seq":2,"mean_intensity":0.51,"processing_ms":3.1}"#)

        await expect { client.frameResultCount >= 2 }
        XCTAssertEqual(client.latestFrameResult?.sequence, 2)
        XCTAssertEqual(client.latestFrameResult?.meanIntensity, 0.51)
        XCTAssertEqual(client.latestFrameResult?.processingMs, 3.1)
        XCTAssertEqual(client.status, .online)

        client.disconnect()
    }

    /// A malformed result message is dropped, not escalated. It must not be
    /// published as an event and must not disturb anything else.
    func testAnUndecodableResultMessageIsDroppedRatherThanPublished() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        let events = collectEvents(client)
        client.connect(to: url(port: port))
        await expect { client.status == .online }

        // No `payload`, so there is no result to publish.
        server.send(text: #"{"type":"cartridge_result","cartridge":"world_builder","result_type":"status"}"#)
        // No `reason`, so there is no error to publish.
        server.send(text: #"{"type":"result_error","message":"?"}"#)
        server.send(text: #"{"type":"frame_result","seq":1,"mean_intensity":0.1,"processing_ms":1.0}"#)

        await expect { client.frameResultCount >= 1 }
        XCTAssertTrue(events.all.isEmpty, "an undecodable message was published as an event")
        XCTAssertEqual(client.status, .online)

        client.disconnect()
    }

    /// A subscribe request is exactly the four fields the Tower validates, and
    /// the contract is included so a disagreement is refused rather than
    /// misinterpreted.
    func testSubscribeSendsTheContractSoAMismatchIsRefused() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        let recorder = attachRecorder(server)
        defer { server.stop() }

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        await expect { client.status == .online }

        client.subscribeToResults(
            cartridge: "world_builder",
            resultType: "status",
            contract: Self.worldBuilderContract
        )
        let landed = await waitUntil {
            recorder.all.compactMap(self.decode).contains { $0["type"] as? String == "result_subscribe" }
        }
        XCTAssertTrue(landed)

        let request = recorder.all.compactMap(decode)
            .first { $0["type"] as? String == "result_subscribe" }
        XCTAssertEqual(request?["cartridge"] as? String, "world_builder")
        XCTAssertEqual(request?["result_type"] as? String, "status")
        XCTAssertEqual(request?["contract"] as? String, Self.worldBuilderContract)

        client.disconnect()
    }

    /// A result-channel send that fails must not fail the connection.
    ///
    /// The contract promises the result channel cannot affect the frame path,
    /// and tearing down the socket the camera is streaming over because a
    /// capability query did not land would break exactly that promise. The
    /// lifecycle markers deliberately do the opposite, because losing one
    /// corrupts a frame bracket.
    func testAFailedResultSendIsNotEscalatedToTheConnection() async throws {
        let server = try MockTowerServer()
        let port = try await server.start()
        respondToPing(server)

        let client = TowerClient(metrics: SenderMetrics())
        client.connect(to: url(port: port))
        await expect { client.status == .online }

        // The server goes away without a close frame, so the next send fails
        // at the socket rather than being refused by the `status` guard.
        server.dropConnection()
        server.stop()
        client.subscribeToResults(
            cartridge: "world_builder",
            resultType: "status",
            contract: Self.worldBuilderContract
        )

        // The receive loop will still notice the dead link on its own terms —
        // what must not happen is this client reaching `.failed` *because of
        // the subscribe*. Give the send's completion time to run and assert the
        // failure, if any, did not come from here.
        try? await Task.sleep(nanoseconds: 150_000_000)
        if case .failed(let message) = client.status {
            XCTAssertFalse(
                message.contains("result_subscribe"),
                "a result-channel send failure was escalated to the connection"
            )
        }

        client.disconnect()
    }
}

/// Thread-safe capture of every text message a MockTowerServer receives, so
/// tests can assert on the exact sequence/content sent over the wire.
///
/// Not `private`: `WorldBuilderIntegrationTests` asserts on the wire for the
/// same reason this file does — "the client sent exactly one subscribe" is only
/// checkable against what actually left the socket — and a second copy of this
/// would be two things that could disagree about what was recorded.
final class MessageRecorder: @unchecked Sendable {
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


/// Collects result-channel events in arrival order.
///
/// A class rather than an array so a `sink` can append to it from the escaping
/// closure, and `@MainActor` because that is where `TowerClient` publishes.
@MainActor
final class EventRecorder {
    private(set) var all: [CartridgeResultEvent] = []
    var cancellable: AnyCancellable?

    func record(_ event: CartridgeResultEvent) { all.append(event) }
}
