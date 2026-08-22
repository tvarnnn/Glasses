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
/// The Tower has no module container, so it runs no experiments and declares
/// none. This workspace therefore shows an empty experiment list and says why —
/// it does not show a list of plausible experiments greyed out, because a greyed
/// row still asserts that the thing exists.
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
    /// A value, not the connection. This workspace has no capture control and
    /// nothing to send, so observing `TowerClient` here would invalidate this
    /// subtree at the Tower's reply rate to read something that changes almost
    /// never — see `TowerReachabilityReader`, which supplies this.
    let isTowerReachable: Bool

    @StateObject private var lab: ExperimentalCVViewModel

    /// The client is injected and owned by `ProjectManager`; see
    /// `CartridgeClients`.
    init(isTowerReachable: Bool, client: any ExperimentalCVClient) {
        self.isTowerReachable = isTowerReachable
        _lab = StateObject(wrappedValue: ExperimentalCVViewModel(client: client))
    }

    var body: some View {
        VStack(spacing: 16) {
            header

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
            Text("A place to run vision experiments on the glasses feed and compare their measurements. The Tower runs none yet.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private static let futureDescription = """
        When the Tower can run experiments, this workspace will list the ones it \
        declares, start one, and show its metrics, timings and annotated frames \
        — each labelled as a measurement or a model estimate. None of that \
        exists yet.
        """

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
                // The Tower measuring its own work. The only timing here,
                // because it is the only one with an unambiguous meaning —
                // see `CVTimings`.
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
