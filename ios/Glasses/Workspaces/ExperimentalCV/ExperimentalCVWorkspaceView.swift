//
//  ExperimentalCVWorkspaceView.swift
//  Glasses
//

import Foundation
import SwiftUI

/// The Experimental CV Lab workspace: a measurement surface for experiments the
/// Tower runs.
///
/// ## What this screen may and may not claim
///
/// The Tower runs exactly one experiment, and it chose which one when it
/// started. This app can read that experiment's answer — it arrives with every
/// per-frame reply — and can do nothing else with it: there is no message to
/// list the experiments, pick a different one, or start or stop the one that is
/// running. The reply names the *number*, not the experiment, so this screen
/// cannot even say which one produced it.
///
/// So the workspace shows two things that used to be one, and the split is the
/// point:
///
/// 1. **The latest result**, from the frame channel, which is real and is drawn
///    exactly as the Tower sent it — see `CVFrameReading`.
/// 2. **The experiment list**, from the cartridge channel, which is empty and
///    says why. Not a greyed-out list of plausible experiments: a greyed row
///    still asserts that the thing exists.
///
/// Before this, only the second existed here, and the first was on the home
/// screen — so someone opening the Experimental CV Lab was told the Tower could
/// not run experiments while its answer sat on the previous screen.
///
/// Everything above is a description of a **Debug** build. This screen is not
/// gated out of Release, and in Release there is no frame channel at all: the
/// frame path is `#if DEBUG` and no frames are sent, so nothing arrives to
/// draw. Four strings on this screen therefore exist in two versions — see the
/// note above `headerSubtitle` — and the refusals are unchanged between them,
/// because those are facts about the protocol rather than about the build.
///
/// ## No capture controls here, deliberately
///
/// Home and World Builder carry the app's session controls; this workspace adds
/// none. Two reasons, and the second is the important one:
///
/// 1. There is nothing for a session to feed. An experiment cannot run.
/// 2. Every additional `startCameraSession()` call site is another place the
///    "the app never starts the camera on its own" invariant has to be
///    re-verified. That invariant is currently a *structural* property — one
///    button per workspace that has one, no `.onAppear` anywhere — and it stays
///    cheap to check by keeping the number of call sites small.
///
/// When the Tower can run an experiment, the control that starts one belongs
/// here and will be labelled for what the Tower can then actually do.
struct ExperimentalCVWorkspaceView: View {
    /// A value, not the connection. Reachability changes almost never, and
    /// `TowerReachabilityReader` — which supplies this — exists so a workspace
    /// does not observe a 12 Hz object to learn it.
    let isTowerReachable: Bool

    /// Held as a plain reference and **not** `@ObservedObject`, which is the
    /// whole trick that lets this workspace show a live figure without paying
    /// for it everywhere.
    ///
    /// `TowerClient` republishes once per reply, at the ~12 Hz target rate while
    /// a session streams. Observing it here would re-evaluate this entire body
    /// at that rate — the experiment panel, the unavailable panel, all of it —
    /// on the main actor the frame sender needs. Instead the reference is passed
    /// down to `CVFrameReadingPanel`, a leaf that holds nothing else, and only
    /// that leaf is invalidated when a reply lands. SwiftUI compares this stored
    /// reference by identity, so a reply does not re-run this body at all.
    let tower: TowerClient

    @StateObject private var lab: ExperimentalCVViewModel

    /// The client is injected and owned by `ProjectManager`; see
    /// `CartridgeClients`.
    init(isTowerReachable: Bool, tower: TowerClient, client: any ExperimentalCVClient) {
        self.isTowerReachable = isTowerReachable
        self.tower = tower
        _lab = StateObject(wrappedValue: ExperimentalCVViewModel(client: client))
    }

    var body: some View {
        VStack(spacing: 16) {
            header

            // Above the experiment list, deliberately. This is the answer the
            // Tower is actually producing; the panel below explains what cannot
            // be asked of it. Showing the absence first and the substance second
            // is how the old screen read as empty.
            CVFrameReadingPanel(tower: tower, isTowerReachable: isTowerReachable)

            if let forcedPhase = lab.availability(isTowerReachable: isTowerReachable).forcedPhase {
                CartridgeStatePanel(
                    title: "Experiments",
                    phase: forcedPhase,
                    explanation: lab.unavailableExplanation(isTowerReachable: isTowerReachable),
                    futureDescription: Self.futureDescription
                )
            } else {
                experimentPanel
            }

            if let failure = lab.lastRequestFailure {
                FailureBanner(text: failure.message)
            }
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Experimental CV Lab")
                .font(.title2.weight(.semibold))
            Text(Self.headerSubtitle)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    // MARK: The sentences that are only true in one configuration
    //
    // ## Why copy on this screen is compiled twice
    //
    // The frame path is `#if DEBUG` (`ProjectManager`) and `TowerClient` does
    // not declare `latestFrameResult` outside DEBUG, so a Release build sends
    // the Tower nothing and receives no per-frame reply. This screen, however,
    // is **not** DEBUG-gated — `ContentView`'s `.experimentalCV` arm is
    // unconditional and `ProjectManager.startAutomaticConnections()` calls
    // `connectIfIdle()` ungated — so a signed Release build against a reachable
    // Tower renders it in full.
    //
    // In that build `CVFrameReadingPanel.nothingYet` correctly says there is
    // nothing to show, while three other sentences on the same screen asserted
    // that the app reads the running experiment's answer. One screen, saying
    // both. Gating the workspace out of Release would be the wrong repair: the
    // screen is fine and every refusal on it is still true — it is these
    // sentences that were wrong. So each is compiled per configuration, exactly
    // as `nothingYet` already is, and the third
    // (`UnavailableExperimentalCVClient.reason`, which reaches
    // `CartridgeStatePanel`) is fixed the same way where it lives.
    //
    // None of this is a claim about what a Release build *could* do. It is a
    // statement about what this one does, which is what Rule 3 asks of a screen.

    #if DEBUG
    private static let headerSubtitle = """
        A place to run vision experiments on the glasses feed and compare their \
        measurements. The Tower is running one, chosen when it started, and \
        this app can read its answer but not change it.
        """
    #else
    private static let headerSubtitle = """
        A place to run vision experiments on the glasses feed and compare their \
        measurements. The Tower is running one, chosen when it started. This \
        build sends it no frames, so there is no answer here to read — and \
        there is no way to change which experiment runs.
        """
    #endif

    #if DEBUG
    private static let futureDescription = """
        When the Tower offers an agreement for this module, this workspace will \
        list the experiments it declares, start one, and show its metrics, \
        timings and annotated frames — each labelled as a measurement or a \
        model estimate. What arrives with every frame today, above, is the \
        running experiment's answer with none of that labelling behind it.
        """
    #else
    private static let futureDescription = """
        When the Tower offers an agreement for this module, this workspace will \
        list the experiments it declares, start one, and show its metrics, \
        timings and annotated frames — each labelled as a measurement or a \
        model estimate. The running experiment's own answer arrives with every \
        frame the Tower is sent, and this build sends none, so that is not on \
        screen above either.
        """
    #endif

    // MARK: The panel for a Tower that can actually run something

    /// Unreachable today. Written now so the display rules for provenance and
    /// baselines land with the data rather than after it.
    @ViewBuilder
    private var experimentPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("Experiments")

            VStack(alignment: .leading, spacing: 12) {
                switch lab.state {
                case .unsupported(let reason):
                    Text(reason)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                case .idle(let available):
                    if available.isEmpty {
                        // A connected Tower that declares nothing is a real and
                        // different answer from a Tower that cannot be asked,
                        // and it gets its own sentence rather than the shared
                        // unavailable panel.
                        Text("The Tower is connected and declares no experiments.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(available) { experiment in
                            experimentRow(experiment)
                        }
                    }

                case .starting(let experiment):
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Starting \(experiment.name)…")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

                case .running(let run):
                    Label("\(run.experiment.name) · running", systemImage: "dot.radiowaves.left.and.right")
                        .font(.headline)
                    CVRunSummaryView(run: run, isFinal: false)

                case .completed(let run):
                    Label(run.experiment.name, systemImage: "checkmark.circle")
                        .font(.headline)
                    CVRunSummaryView(run: run, isFinal: true)

                case .failed(let failure):
                    Label("Experiment failed", systemImage: "exclamationmark.triangle.fill")
                        .font(.headline)
                    Text(failure.message)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 18))
        }
    }

    private func experimentRow(_ experiment: CVExperiment) -> some View {
        Button {
            lab.run(experiment)
        } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(experiment.name)
                    .font(.body.weight(.medium))
                if let summary = experiment.summary {
                    Text(summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityHint("Runs this experiment on the Tower")
    }
}

/// The running experiment's answer for the most recent frame the Tower replied
/// to — the one thing on this screen that is real today.
///
/// ## Why this observes `TowerClient` when the workspace above it does not
///
/// `TowerReachabilityReader` exists because the quiet cartridge workspaces
/// needed one rarely-changing fact from an object that republishes at the
/// Tower's reply rate, and observing it for that was a dead dependency with a
/// real main-actor cost.
///
/// This panel is the opposite case. The value it draws *is* the thing that
/// changes at reply rate, and a stale rendering of it is the defect rather than
/// the saving. So it observes — and it is a leaf holding nothing else, so the
/// invalidation stops here instead of taking the rest of the workspace with it.
///
/// ## Runtime ownership
///
/// Observes. Owns nothing, constructs nothing, sends nothing. It cannot start a
/// session and is not handed anything that could.
private struct CVFrameReadingPanel: View {
    @ObservedObject var tower: TowerClient
    let isTowerReachable: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("Latest result")

            VStack(alignment: .leading, spacing: 10) {
                if let reading, reading.hasAnything {
                    figures(reading)
                } else if reading != nil {
                    // A reply that carried nothing is a real answer and a
                    // different one from no reply: the Tower processed the frame
                    // and the experiment concluded nothing about it. Drawing
                    // this as "waiting" would leave someone waiting for a result
                    // that has already arrived and was empty.
                    Text("The Tower answered the most recent frame and reported no result for it.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    // No spinner and no zeroes. Nothing is in flight, so a
                    // progress indicator would be the most convincing untrue
                    // thing this screen could draw.
                    Text(nothingYet)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Text(Self.whatCannotBeAsked)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 18))
        }
    }

    /// Every figure the Tower actually sent, and no other.
    @ViewBuilder
    private func figures(_ reading: CVFrameReading) -> some View {
        // The headline pair, drawn under the Tower's own name for it or not at
        // all. `CVFrameReading` will not hand over one half without the other,
        // so there is no way to caption this number with a word this app chose.
        if let headline = reading.headline {
            CVFigureRow(caption: headline.label, value: headline.displayValue)
        }
        // Optional on the wire. Its absence is "the experiment said nothing
        // about intensity", not "the frame was dark", so the row disappears
        // rather than showing a zero.
        if let intensity = reading.meanIntensity {
            CVFigureRow(caption: "Mean intensity", value: CVMetric.format(intensity))
        }
        // "ms" is the Tower's own declaration — the wire field is named
        // `processing_ms` — not this app's assumption. Same reasoning as
        // `CVRunSummaryView`, and the same wording, because it is the same
        // quantity.
        if let processing = reading.processingMs {
            CVFigureRow(caption: "Tower processing", value: "\(CVMetric.format(processing)) ms")
        }
        // The Tower's additive measurements, each under the name the Tower gave
        // it. `stage_ms` is deliberately not drawn here: it is a breakdown of
        // the processing time already shown, and putting both on one card
        // invites arithmetic the Tower never promised would add up.
        ForEach(reading.measurements) { measurement in
            CVFigureRow(caption: measurement.label, value: measurement.displayValue)
        }

        if let sequence = reading.sequence {
            // Which frame these figures belong to. "Latest" is otherwise
            // unanchored, and during a stall the difference between a fresh
            // answer and an old one is the whole story.
            Text("From frame \(sequence).")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }

        // Rule 16. `frame_result` carries no provenance field, and silence must
        // not be read as "measured" — so the caveat for `.unknown` is stated
        // once for the card, the way `CVRunSummaryView` states its inference
        // caveat once for a run.
        if let caveat = CVFrameReading.provenance.caveat {
            Text(caveat)
                .font(.caption)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// `nil` when the Tower has not answered a frame at all.
    ///
    /// In a Release build there is nothing to read: the frame path is
    /// `#if DEBUG` (`ProjectManager`), no frames are sent, and `TowerClient`
    /// does not declare `latestFrameResult` outside DEBUG. This therefore
    /// degrades to the same empty card a Debug build shows before a session
    /// starts, with `nothingYet` saying the Release-specific reason — never a
    /// spinner, never a zero.
    ///
    /// A closure rather than `map(CVFrameReading.init)`: the target builds with
    /// main-actor default isolation, and an unapplied initializer reference
    /// does not inherit the caller's isolation the way a closure literal does.
    private var reading: CVFrameReading? {
        #if DEBUG
        return tower.latestFrameResult.map { CVFrameReading($0) }
        #else
        return nil
        #endif
    }

    /// Why there is nothing, in the words that fit the actual reason.
    private var nothingYet: String {
        #if DEBUG
        if !isTowerReachable {
            return "The Tower is not connected, so it has not answered a frame."
        }
        return """
            No frame has been answered yet. The Tower replies to every frame a \
            session sends, and the answer for the most recent one appears here.
            """
        #else
        return """
            This build does not send frames to the Tower, so there is nothing \
            for the experiment to answer and nothing to show here.
            """
        #endif
    }

    /// Said whether or not there is a result, because it is true either way and
    /// it is the thing a person will otherwise assume they can do.
    private static let whatCannotBeAsked = """
        The Tower chose this experiment when it started. This app cannot list \
        the experiments it has, pick a different one, or start or stop the one \
        it is running — and the reply names the number, not the experiment, so \
        this screen cannot say which one produced it.
        """
}

/// One caption-and-figure line.
///
/// Shared by the two result panels in this file so a live reading and a
/// completed run read identically. Not an abstraction over cartridges — it is
/// eight points of layout that were about to exist twice in one file.
private struct CVFigureRow: View {
    let caption: String
    let value: String

    var body: some View {
        HStack {
            Text(caption)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Spacer(minLength: 12)
            Text(value)
                .font(.subheadline.weight(.medium))
                .monospacedDigit()
        }
    }
}

/// Renders one run's results, honouring the two rules
/// `docs/modules/EXPERIMENTAL-CV.md` imposes on them.
///
/// Unreachable today — no client produces a run.
struct CVRunSummaryView: View {
    let run: CVExperimentRun
    let isFinal: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(run.metrics) { metric in
                metricRow(metric)
            }

            if let frames = run.framesProcessed {
                row("Frames processed", "\(frames)")
            }
            if let processing = run.timings.processingMs {
                // The Tower measuring its own work — the only timing here,
                // because it is the only one with an unambiguous meaning (see
                // `CVTimings`). And "ms" is not an invented unit, unlike the
                // metres `ReportedFigure` exists to prevent: the field is named
                // `processing_ms` on the wire, so milliseconds is the Tower's
                // own declaration rather than this app's assumption.
                row("Tower processing", "\(CVMetric.format(processing)) ms")
            }

            annotationRows

            if !isFinal {
                Text("Running. These figures may still change.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if run.containsInference {
                // Stated once for the run rather than repeated per row, so it
                // reads as a property of the results instead of as noise.
                Text("Values marked as estimates are model output, not measurements.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func metricRow(_ metric: CVMetric) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            row(metric.label, metric.displayValue)
            HStack(spacing: 8) {
                if metric.provenance.isInference {
                    Text("Estimate")
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color(.tertiarySystemFill), in: .capsule)
                }
                // Only rendered when `comparison` produced one, which requires
                // both a baseline and a stated direction. There is no other
                // path to a verdict on this screen.
                if let comparison = metric.comparison {
                    Text(comparison.label)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            // Not gated on `isInference`. `caveat` is already nil for
            // `.measured`, and gating additionally on inference hid the
            // `.unknown` caveat entirely — drawing a value whose provenance the
            // Tower never stated as though it were a measurement, which is Rule
            // 16 exactly backwards.
            if let caveat = metric.provenance.caveat {
                Text(caveat)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
    }

    /// The annotated frame, shown only if it was redacted — the same rule every
    /// other stored image obeys. A debug surface gets no exemption.
    @ViewBuilder
    private var annotationRows: some View {
        if run.annotation.hasReport {
            if let count = run.annotation.count {
                row("Annotations", "\(count)")
            }
            if let withheld = run.annotation.artifact.withheldReason {
                Text(withheld)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func row(_ caption: String, _ value: String) -> some View {
        CVFigureRow(caption: caption, value: value)
    }
}
