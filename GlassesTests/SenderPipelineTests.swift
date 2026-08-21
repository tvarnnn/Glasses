//
//  SenderPipelineTests.swift
//  GlassesTests
//
//  Covers the two pieces that decide, and then account for, how many captured
//  frames reach the Tower: `FrameRateGate` (the sampling cadence that replaced
//  the fixed 1-in-30 stride) and `SenderMetrics` (the per-stage counters that
//  make a shortfall attributable instead of mysterious).
//
//  Both are pure enough to drive with synthetic arrival times, so these tests
//  assert exact cadence rather than sleeping and hoping.
//

import XCTest

@testable import Glasses

@MainActor
final class FrameRateGateTests: XCTestCase {

    /// Runs `frameCount` arrivals spaced at `sourceFPS` through a gate and
    /// returns the arrival indices it admitted.
    private func selectedIndices(
        sourceFPS: Double,
        targetFPS: Double,
        frameCount: Int,
        startTime: TimeInterval = 0
    ) -> [Int] {
        var gate = FrameRateGate(targetFPS: targetFPS)
        var selected: [Int] = []
        for index in 0..<frameCount {
            let now = startTime + Double(index) / sourceFPS
            if gate.shouldSelect(at: now) { selected.append(index) }
        }
        return selected
    }

    // MARK: Cadence

    /// The exact case the old code got wrong: a 24 fps source and a 12 fps
    /// target must admit every other frame, not every 30th (0.8 fps) and not
    /// every third (the aliasing failure a naive elapsed-time check produces).
    func testTwentyFourFPSSourceAtTwelveFPSTargetAdmitsEveryOtherFrame() {
        let selected = selectedIndices(sourceFPS: 24, targetFPS: 12, frameCount: 48)
        XCTAssertEqual(selected, Array(stride(from: 0, to: 48, by: 2)))
    }

    /// The regression guard for the actual bug: whatever the mechanism, one
    /// second of a 24 fps source must not yield 0.8 frames.
    func testDeliveredRateIsNoLongerOnePerThirtyFrames() {
        let selected = selectedIndices(sourceFPS: 24, targetFPS: 12, frameCount: 24)
        XCTAssertEqual(selected.count, 12, "one second of 24 fps must yield ~12 selections, not 1")
    }

    /// DAT's adaptive ladder can settle anywhere in 15...30 fps
    /// (docs/07-PLATFORM-CONSTRAINTS.md). A fixed stride of 2 would deliver
    /// 7.5 fps at the 15 fps floor — below the 10–15 fps target. A rate target
    /// must hold across the whole range.
    func testTargetRateIsHeldAcrossEverySourceRateTheLadderCanProduce() {
        for sourceFPS in [15.0, 24.0, 30.0] {
            let seconds = 60.0
            let selected = selectedIndices(
                sourceFPS: sourceFPS,
                targetFPS: 12,
                frameCount: Int(sourceFPS * seconds)
            )
            let measured = Double(selected.count) / seconds
            // Tight on purpose: the deadline accumulates rather than resetting
            // to "now", so the mean is exact rather than approximate. A loose
            // tolerance here would hide the aliasing this design exists to
            // prevent.
            XCTAssertEqual(
                measured,
                12,
                accuracy: 0.05,
                "a \(sourceFPS) fps source produced \(measured) fps"
            )
        }
    }

    /// The roadmap's V0.7 figure is ~15 fps, which does not divide 24 evenly.
    /// Proving the mechanism holds it exactly is what makes raising
    /// `towerTargetFPS` a one-constant change rather than a redesign — the
    /// shipped 12 is a headroom decision, not a limit of the gate.
    func testTargetIsHeldAtTheRoadmapFifteenFPS() {
        for sourceFPS in [24.0, 30.0] {
            let seconds = 60.0
            let selected = selectedIndices(
                sourceFPS: sourceFPS,
                targetFPS: 15,
                frameCount: Int(sourceFPS * seconds)
            )
            let measured = Double(selected.count) / seconds
            XCTAssertEqual(measured, 15, accuracy: 0.05, "a \(sourceFPS) fps source produced \(measured) fps")
        }
    }

    /// A gate can only reject. Asking for more than the source provides must
    /// pass everything through rather than inventing or duplicating frames.
    func testSourceSlowerThanTargetAdmitsEveryFrame() {
        let selected = selectedIndices(sourceFPS: 7, targetFPS: 12, frameCount: 21)
        XCTAssertEqual(selected, Array(0..<21))
    }

    /// Jitter around the deadline is why the gate uses a tolerance instead of
    /// a bare elapsed-time comparison. With arrivals landing a hair *early*,
    /// a bare comparison halves the rate.
    func testJitteredArrivalsStillHoldTheTargetRate() {
        var gate = FrameRateGate(targetFPS: 12)
        // 24 fps arrivals, each nudged by a deterministic sub-millisecond
        // amount that straddles the exact 12 fps boundary.
        let jitter: [Double] = [0, -0.0004, 0.0006, -0.0009, 0.0002]
        var count = 0
        for index in 0..<240 {
            let now = Double(index) / 24 + jitter[index % jitter.count]
            if gate.shouldSelect(at: now) { count += 1 }
        }
        let measured = Double(count) / 10.0
        XCTAssertEqual(measured, 12, accuracy: 1.0, "jitter dropped the rate to \(measured) fps")
    }

    // MARK: Freshness

    /// After a stall the gate must resume at the target rate, not admit a
    /// burst of catch-up frames — freshness over completeness.
    func testStallDoesNotProduceACatchUpBurst() {
        var gate = FrameRateGate(targetFPS: 12)
        XCTAssertTrue(gate.shouldSelect(at: 0))

        // Nothing arrives for two seconds (24 missed deadlines).
        XCTAssertTrue(gate.shouldSelect(at: 2.0), "the first frame after a stall is fresh; admit it")

        // The backlog then drains in one main-actor turn: many frames with
        // near-identical timestamps. Exactly one may pass.
        var admittedFromBacklog = 0
        for offset in 0..<20 {
            if gate.shouldSelect(at: 2.0 + Double(offset) * 0.0001) { admittedFromBacklog += 1 }
        }
        XCTAssertEqual(admittedFromBacklog, 0, "a drained backlog must not all pass the gate")
    }

    /// The property that makes the gate safe to consult after the main-actor
    /// hop: because eligibility is measured in wall time, a congested main
    /// actor cannot cause more expensive work than the target rate, no matter
    /// how many frames are queued behind it.
    func testCongestionCannotExceedTheTargetRate() {
        var gate = FrameRateGate(targetFPS: 12)
        var count = 0
        // 240 frames all delivered within a single 100 ms window.
        for index in 0..<240 {
            if gate.shouldSelect(at: Double(index) * 0.1 / 240) { count += 1 }
        }
        XCTAssertLessThanOrEqual(count, 3, "100 ms of arrivals admitted \(count) frames at a 12 fps target")
    }

    // MARK: Lifecycle

    func testResetMakesTheNextFrameTheFirstOfASession() {
        var gate = FrameRateGate(targetFPS: 12)
        XCTAssertTrue(gate.shouldSelect(at: 100))
        XCTAssertFalse(gate.shouldSelect(at: 100.01))

        gate.reset()
        XCTAssertTrue(
            gate.shouldSelect(at: 100.02),
            "after reset the next frame is the first of a new session and must be admitted"
        )
    }

    func testNonPositiveTargetIsClampedRatherThanStallingThePipeline() {
        var gate = FrameRateGate(targetFPS: 0)
        XCTAssertGreaterThan(gate.targetFPS, 0)
        XCTAssertTrue(gate.shouldSelect(at: 0))
        XCTAssertTrue(gate.interval.isFinite, "an infinite interval would admit one frame and stall forever")
    }

    /// Guards the shipped constant against the band this change is being
    /// measured against (10–15 fps delivered), and against the rate it
    /// replaced. Not a tautology in one direction that matters: if someone
    /// re-derives the target from a source-rate stride and lands back near
    /// 0.8, this fails.
    func testConfiguredTowerTargetSitsInsideTheMeasurementBand() {
        XCTAssertGreaterThanOrEqual(FrameRateGate.towerTargetFPS, 10)
        XCTAssertLessThanOrEqual(FrameRateGate.towerTargetFPS, 15)

        // The gate must actually deliver the configured target from the
        // configured 24 fps stream, not merely store a plausible number.
        let seconds = 60.0
        let selected = selectedIndices(
            sourceFPS: 24,
            targetFPS: FrameRateGate.towerTargetFPS,
            frameCount: Int(24 * seconds)
        )
        XCTAssertEqual(
            Double(selected.count) / seconds,
            FrameRateGate.towerTargetFPS,
            accuracy: 0.05
        )
    }
}

@MainActor
final class SenderMetricsTests: XCTestCase {

    func testBeginClearsThePreviousSession() {
        let metrics = SenderMetrics()
        metrics.begin()
        metrics.recordCapture(sequence: 1)
        metrics.recordSelection()
        metrics.recordSendAttempt(wireBytes: 100)
        metrics.recordSendSuccess()
        XCTAssertEqual(metrics.currentSnapshot.framesCaptured, 1)

        metrics.begin()
        let snapshot = metrics.currentSnapshot
        XCTAssertEqual(snapshot.framesCaptured, 0)
        XCTAssertEqual(snapshot.framesSelected, 0)
        XCTAssertEqual(snapshot.sendSuccesses, 0)
        XCTAssertEqual(snapshot.wireBytes, 0)
    }

    func testFinishPublishesTheFinalCountersRatherThanClearingThem() {
        let metrics = SenderMetrics()
        metrics.begin()
        metrics.recordCapture(sequence: 1)
        metrics.recordSelection()
        metrics.finish()

        XCTAssertEqual(metrics.snapshot.framesCaptured, 1, "Stop must leave the session's numbers readable")
        XCTAssertEqual(metrics.snapshot.framesSelected, 1)
    }

    /// Recording must not publish on every increment — at the capture rate
    /// that would invalidate the SwiftUI view tree 24 times a second purely to
    /// show a counter.
    func testRecordingIsRateLimitedRatherThanPublishingPerFrame() {
        let metrics = SenderMetrics()
        metrics.begin()
        let publishedAtBegin = metrics.snapshot.framesCaptured

        for sequence in 1...200 {
            metrics.recordCapture(sequence: sequence)
        }

        XCTAssertEqual(
            metrics.snapshot.framesCaptured,
            publishedAtBegin,
            "200 increments inside one publish interval must not republish"
        )
        XCTAssertEqual(metrics.currentSnapshot.framesCaptured, 200, "the counters themselves must still be exact")
    }

    // MARK: Session clock

    /// `startCameraSession()` calls `begin()` seconds before DAT delivers a
    /// frame — creating the session, starting it, adding the camera, starting
    /// the stream. Counting that dead time would understate every rate and
    /// send someone hunting a shortfall that does not exist.
    func testClockDoesNotRunBeforeTheFirstFrameArrives() async throws {
        let metrics = SenderMetrics()
        metrics.begin()
        // Deliberately much longer than the post-frame wait below, so the two
        // hypotheses (clock starts at begin vs. at first frame) are separated
        // by ~400 ms and the assertion cannot flake on a loaded machine.
        try? await Task.sleep(nanoseconds: 500_000_000)

        XCTAssertEqual(metrics.currentSnapshot.duration, 0, "a session with no frames has no measurable duration")
        XCTAssertNil(metrics.currentSnapshot.captureFPS)

        metrics.recordCapture(sequence: 1)
        try? await Task.sleep(nanoseconds: 50_000_000)
        XCTAssertGreaterThan(metrics.currentSnapshot.duration, 0, "the first frame starts the clock")
        XCTAssertLessThan(
            metrics.currentSnapshot.duration,
            0.3,
            "the clock must start at the first frame, not at begin()"
        )
    }

    /// Frames still in flight at Stop, and `frame_result` replies for them,
    /// land after `finish()`. If the clock kept running, every displayed rate
    /// would visibly decay once the session ended.
    func testFinishFreezesTheElapsedTimeSoFinalRatesStopMoving() async throws {
        let metrics = SenderMetrics()
        metrics.begin()
        metrics.recordCapture(sequence: 1)
        metrics.recordSelection()
        try? await Task.sleep(nanoseconds: 60_000_000)
        metrics.finish()

        let frozen = metrics.snapshot.duration
        XCTAssertGreaterThan(frozen, 0)

        try? await Task.sleep(nanoseconds: 120_000_000)
        // A late reply for a frame that was in flight at Stop.
        metrics.recordFrameResult()

        XCTAssertEqual(metrics.currentSnapshot.duration, frozen, accuracy: 0.0001)
        XCTAssertEqual(metrics.currentSnapshot.frameResults, 1, "the late reply is still counted — it really arrived")
    }

    func testBeginRestartsTheClockAfterAFinishedSession() async throws {
        let metrics = SenderMetrics()
        metrics.begin()
        metrics.recordCapture(sequence: 1)
        try? await Task.sleep(nanoseconds: 60_000_000)
        metrics.finish()
        XCTAssertGreaterThan(metrics.snapshot.duration, 0)

        metrics.begin()
        XCTAssertEqual(metrics.currentSnapshot.duration, 0, "a new session must not inherit the old clock")
        metrics.recordCapture(sequence: 1)
        try? await Task.sleep(nanoseconds: 30_000_000)
        XCTAssertGreaterThan(metrics.currentSnapshot.duration, 0, "and must start ticking again")
    }

    // MARK: Rates

    func testRatesAreNilUntilThereIsEnoughElapsedTimeToDivideBy() {
        var snapshot = SenderMetricsSnapshot()
        snapshot.framesCaptured = 3
        snapshot.sendSuccesses = 2
        snapshot.duration = 0.05

        XCTAssertNil(snapshot.captureFPS, "3 frames in 50 ms is not a measured rate")
        XCTAssertNil(snapshot.successfulSendFPS)
    }

    func testRatesAreComputedOverTheSessionDuration() {
        var snapshot = SenderMetricsSnapshot()
        snapshot.duration = 10
        snapshot.framesCaptured = 240
        snapshot.framesSelected = 120
        snapshot.sendAttempts = 120
        snapshot.sendSuccesses = 118
        snapshot.frameResults = 117
        snapshot.wireBytes = 2_048_000

        XCTAssertEqual(snapshot.captureFPS ?? 0, 24, accuracy: 0.001)
        XCTAssertEqual(snapshot.selectedFPS ?? 0, 12, accuracy: 0.001)
        XCTAssertEqual(snapshot.sendAttemptFPS ?? 0, 12, accuracy: 0.001)
        XCTAssertEqual(snapshot.successfulSendFPS ?? 0, 11.8, accuracy: 0.001)
        XCTAssertEqual(snapshot.towerResultFPS ?? 0, 11.7, accuracy: 0.001)
        XCTAssertEqual(snapshot.wireBytesPerSecond ?? 0, 204_800, accuracy: 0.001)
    }

    /// The single number that makes the before/after comparison legible: the
    /// 0.8 fps baseline was delivering ~1 frame in 30.
    func testDeliveredFractionReproducesTheBaselineRatio() {
        var baseline = SenderMetricsSnapshot()
        baseline.duration = 79
        baseline.framesCaptured = 1860
        baseline.sendSuccesses = 63
        XCTAssertEqual(baseline.deliveredFraction ?? 0, 1.0 / 29.5, accuracy: 0.002)

        var target = SenderMetricsSnapshot()
        target.duration = 79
        target.framesCaptured = 1896
        target.sendSuccesses = 948
        XCTAssertEqual(target.deliveredFraction ?? 0, 0.5, accuracy: 0.001)
    }

    func testEncodeTimingTracksAverageAndWorstCase() {
        let metrics = SenderMetrics()
        metrics.begin()
        metrics.recordEncode(seconds: 0.004)
        metrics.recordEncode(seconds: 0.010)
        metrics.recordEncode(seconds: 0.006)

        let snapshot = metrics.currentSnapshot
        XCTAssertEqual(snapshot.framesEncoded, 3)
        XCTAssertEqual(snapshot.encodeMsAverage ?? 0, 20.0 / 3, accuracy: 0.001)
        XCTAssertEqual(snapshot.encodeMsMax ?? 0, 10, accuracy: 0.001)
    }

    func testEncodeTimingIsNilRatherThanZeroBeforeAnyEncode() {
        XCTAssertNil(SenderMetricsSnapshot().encodeMsAverage)
        XCTAssertNil(SenderMetricsSnapshot().encodeMsMax)
        XCTAssertNil(SenderMetricsSnapshot().deliveredFraction)
    }

    // MARK: Invariants

    /// Sequence numbers are DAT callback ordinals. If this ever stops holding,
    /// the Tower's seq-gap arithmetic — the evidence that found this bug — is
    /// no longer readable.
    func testSequenceInvariantHoldsWhenEveryCallbackIncrementsTheSequence() {
        let metrics = SenderMetrics()
        metrics.begin()
        for sequence in 1...50 {
            metrics.recordCapture(sequence: sequence)
        }
        XCTAssertTrue(metrics.currentSnapshot.sequenceInvariantHolds)
    }

    func testSequenceInvariantFailsWhenSequencesSkip() {
        let metrics = SenderMetrics()
        metrics.begin()
        metrics.recordCapture(sequence: 1)
        metrics.recordCapture(sequence: 3)
        XCTAssertFalse(
            metrics.currentSnapshot.sequenceInvariantHolds,
            "a gap between callbacks and sequences must be visible, not silently averaged away"
        )
    }

    /// Every selected frame must reach a terminal bucket or be in flight;
    /// anything else is backlog. Each of the six fates must clear the count.
    func testBacklogClearsForEveryTerminalOutcome() {
        let metrics = SenderMetrics()
        metrics.begin()

        for _ in 0..<10 { metrics.recordSelection() }
        XCTAssertEqual(metrics.currentSnapshot.framesUnaccounted, 10, "nothing resolved yet")

        metrics.recordDecodeFailure()
        metrics.recordEncodeFailure()
        metrics.recordSendWindowDrop()
        metrics.recordSessionGateDrop()
        for _ in 0..<6 {
            metrics.recordSendAttempt(wireBytes: 20_000)
        }
        for _ in 0..<5 { metrics.recordSendSuccess() }
        // The sixth send is still in flight — attempted, so not backlog.
        XCTAssertEqual(
            metrics.currentSnapshot.framesUnaccounted,
            0,
            "an outstanding send is accounted for, not backlog"
        )

        metrics.recordSendFailure()
        XCTAssertEqual(metrics.currentSnapshot.framesUnaccounted, 0, "and once it completes")
    }

    /// A send whose socket is torn down mid-flight completes on neither the
    /// success nor the failure path. Without its own bucket it would count as
    /// permanently in flight, quietly masking real backlog from then on.
    func testSendAbandonedByTeardownIsATerminalOutcome() {
        let metrics = SenderMetrics()
        metrics.begin()
        metrics.recordSelection()
        metrics.recordSendAttempt(wireBytes: 20_000)
        XCTAssertEqual(metrics.currentSnapshot.framesUnaccounted, 0)

        metrics.recordSendAbandoned()
        XCTAssertEqual(metrics.currentSnapshot.framesUnaccounted, 0)
        XCTAssertEqual(metrics.currentSnapshot.sendSuccesses, 0, "it must not be counted as delivered")
    }

    /// The signature this metric exists to expose: selections outrunning
    /// outcomes means frames are queueing rather than being dropped.
    func testBacklogCountsFramesThatWentNowhere() {
        let metrics = SenderMetrics()
        metrics.begin()
        for _ in 0..<5 { metrics.recordSelection() }
        metrics.recordSendAttempt(wireBytes: 1)
        metrics.recordSendSuccess()

        XCTAssertEqual(
            metrics.currentSnapshot.framesUnaccounted,
            4,
            "four selected frames reached no outcome and must be visible as backlog"
        )
    }
}
