//
//  DocumentMemoryWorkspaceView.swift
//  Glasses
//

import Foundation
import SwiftUI

/// The Document Memory workspace: documents the Tower observed, and a way to
/// ask about them.
///
/// ## The search field is present and disabled, on purpose
///
/// The alternatives were both worse. Hiding it entirely would leave a workspace
/// that cannot show what it is *for*, and the query seam would go unexercised
/// until the day it has to work. Leaving it enabled would let a person type a
/// question, press return, and get nothing back — which reads as "I have no
/// documents about that", a false statement about their own memory, rather than
/// as "this is not built".
///
/// Disabled with the reason underneath says the true thing: the field is how
/// this will be asked, and it cannot be asked yet.
///
/// ## No camera controls
///
/// Same as Experimental CV Lab: this workspace has no session controls, so the
/// number of places that can start the camera stays at two — see that file for
/// why that number matters.
struct DocumentMemoryWorkspaceView: View {
    /// A value, not the connection — see `TowerReachabilityReader`.
    let isTowerReachable: Bool

    @StateObject private var memory: DocumentMemoryViewModel

    /// The client is injected and owned by `ProjectManager`; see
    /// `CartridgeClients`.
    init(isTowerReachable: Bool, client: any DocumentMemoryClient) {
        self.isTowerReachable = isTowerReachable
        _memory = StateObject(wrappedValue: DocumentMemoryViewModel(client: client))
    }

    private var availability: CartridgeAvailability {
        memory.availability(isTowerReachable: isTowerReachable)
    }

    var body: some View {
        VStack(spacing: 16) {
            header
            searchField

            if let forcedPhase = availability.forcedPhase {
                CartridgeStatePanel(
                    title: "Documents",
                    phase: forcedPhase,
                    explanation: memory.unavailableExplanation(isTowerReachable: isTowerReachable),
                    futureDescription: Self.futureDescription
                )
            } else {
                resultsPanel
            }

            if let failure = memory.lastRequestFailure {
                FailureBanner(text: failure.message)
            }
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Document Memory")
                .font(.title2.weight(.semibold))
            Text("Documents the glasses passed, kept as text and summaries rather than as pictures. The Tower keeps none yet.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private static let futureDescription = """
        When the Tower keeps a document memory, this workspace will list what it \
        observed, when, and for how long it was in view, with its summary and \
        whether text was readable. Searching by words or by roughly when \
        something was seen happens on the Tower. None of that exists yet.
        """

    // MARK: Query input

    @ViewBuilder
    private var searchField: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
                TextField("Ask about a document you passed", text: $memory.queryText)
                    .textFieldStyle(.plain)
                    .submitLabel(.search)
                    .onSubmit { memory.submitTypedQuery() }
                    .disabled(!availability.isAvailable)
            }
            .padding(12)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 12))

            if !availability.isAvailable {
                Text("Searching needs a Tower that keeps a document memory. Nothing typed here is sent anywhere.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .contain)
    }

    // MARK: Results

    /// Unreachable today. Written now so the display rules land with the data.
    @ViewBuilder
    private var resultsPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("Documents")

            VStack(alignment: .leading, spacing: 12) {
                switch memory.state {
                case .unsupported(let reason):
                    Text(reason)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                case .idle:
                    Text("Ask a question above, or nothing has been asked yet.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                case .searching(let query):
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Searching for \(query.displayText)…")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

                case .results(let result):
                    DocumentResultsView(result: result)

                case .failed(let failure):
                    Label("Search failed", systemImage: "exclamationmark.triangle.fill")
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
}

/// Renders one query's answer, including the two answers that are not lists.
struct DocumentResultsView: View {
    let result: DocumentQueryResult

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch result.evidence {
            case .matched:
                ForEach(result.documents) { document in
                    DocumentRow(document: document)
                }
                if !result.evidence.explanation.isEmpty {
                    Text(result.evidence.explanation)
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }

            case .notFound, .noObservation:
                // Two different sentences for two different facts. Collapsing
                // them into "No results" would let a gap in what the glasses
                // happened to see read as a statement about the world —
                // Core Principle 3.
                Label(
                    result.evidence == .notFound ? "Nothing matched" : "Never observed",
                    systemImage: "questionmark.circle"
                )
                .font(.headline)
                Text(result.evidence.explanation)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// One document.
///
/// The thumbnail is drawn only when the artifact says it may be — which today
/// and for the foreseeable future means only when the producer redacted it.
/// When it may not be, the row says why rather than leaving a blank square.
struct DocumentRow: View {
    let document: RememberedDocument

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(document.displayTitle)
                .font(.body.weight(.medium))

            if let summary = document.summary {
                Text(summary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                // Not gated on `isInference` — `caveat` is already nil for a
                // measurement, and the extra gate hid the `.unknown` caveat,
                // drawing an unstated provenance as though it were measured.
                if let caveat = document.provenance.caveat {
                    Text(caveat)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            HStack(spacing: 10) {
                Text(observedLabel)
                if let duration = document.observedDuration {
                    Text(duration.label)
                }
                Text(document.text.displayName)
            }
            .font(.caption2)
            .foregroundStyle(.tertiary)

            if document.observedDuration != nil {
                Text(ObservedDuration.attentionCaveat)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let withheld = document.thumbnail.withheldReason {
                Text(withheld)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    /// Observation time, or an explicit statement that it is unknown.
    ///
    /// Never falls back to `receivedAt`. When the glasses saw something and
    /// when the phone heard about it are different facts, and substituting one
    /// for the other is the conflation Core Principle 5 forbids.
    private var observedLabel: String {
        guard let observed = document.time.displayableObservationTime else {
            return "Time unknown"
        }
        return observed.formatted(date: .abbreviated, time: .shortened)
    }
}
