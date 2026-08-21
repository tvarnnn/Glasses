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
