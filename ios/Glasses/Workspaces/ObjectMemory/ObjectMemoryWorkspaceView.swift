//
//  ObjectMemoryWorkspaceView.swift
//  Glasses
//

import Foundation
import SwiftUI

/// The Object Memory workspace: what the Tower recorded as visible, and when.
///
/// ## This view writes no prose
///
/// Every sentence on screen comes from `ObjectMemoryCopy`, including button
/// labels and section headings, and `ObjectMemoryCopyTests` asserts over that
/// type's whole output. A `Text("…")` literal added here would escape the test
/// that exists to stop this screen from claiming more than the sensor can
/// support — so the rule is absolute rather than stylistic: **no user-facing
/// string literal in this file.**
///
/// ## What the layout is arguing
///
/// A row leads with what a record actually says — *a laptop was visible*, and
/// when — and keeps the claim caveat beside it rather than in a disclosure. The
/// frame reference goes **inside** the disclosure, because it is the field a
/// reader most wants to misread as a place, and it is never shown without
/// `frameCaveat` immediately under it.
///
/// The bounding box is drawn as text, not as a rectangle over anything. There
/// is no map, no floor plan, and no marker: this cartridge has `spatial_ref:
/// null` in every payload and knows where nothing is.
///
/// ## No camera controls
///
/// Like the other read-only workspaces, this one is handed no
/// `GlassesConnection`, so the number of places in the app that can start a
/// capture session stays at two. It also cannot delete: the transport is two
/// `GET`s, and real deletion lives on the Tower where a human types it.
struct ObjectMemoryWorkspaceView: View {
    /// A value, not the connection — see `TowerReachabilityReader`.
    let isTowerReachable: Bool

    @StateObject private var memory: ObjectMemoryViewModel

    /// The client is injected and owned by `ProjectManager`; see
    /// `CartridgeClients`. It outlives this view, so an answer survives a
    /// workspace switch.
    init(isTowerReachable: Bool, client: any ObjectMemoryClient) {
        self.isTowerReachable = isTowerReachable
        _memory = StateObject(wrappedValue: ObjectMemoryViewModel(client: client))
    }

    private var forcedPhase: CartridgePhase? {
        memory.knownAvailability(isTowerReachable: isTowerReachable)?.forcedPhase
    }

    var body: some View {
        VStack(spacing: 16) {
            header
            controls

            if let forcedPhase {
                CartridgeStatePanel(
                    title: ObjectMemoryCopy.recordsHeading,
                    phase: forcedPhase,
                    explanation: memory.unavailableExplanation(isTowerReachable: isTowerReachable),
                    futureDescription: ObjectMemoryCopy.futureDescription
                )
            } else {
                recordsPanel
            }
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(ObjectMemoryCopy.cartridgeName)
                .font(.title2.weight(.semibold))
            Text(ObjectMemoryCopy.summary)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    // MARK: Controls

    /// Two questions and a category picker.
    ///
    /// The picker's options come from the last answer's `recorded_classes`
    /// rather than from a constant in this app. Hardcoding `laptop` and
    /// `cell phone` would be the phone asserting what the Tower looks for, and
    /// it would go stale silently the day the Tower's list changes.
    @ViewBuilder
    private var controls: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !memory.recordableClasses.isEmpty {
                Picker(ObjectMemoryCopy.allCategories, selection: $memory.selectedClass) {
                    Text(ObjectMemoryCopy.allCategories).tag(String?.none)
                    ForEach(memory.recordableClasses, id: \.self) { objectClass in
                        Text(objectClass).tag(String?.some(objectClass))
                    }
                }
                .pickerStyle(.segmented)
            }

            HStack(spacing: 10) {
                Button(ObjectMemoryCopy.showEverythingButton) {
                    memory.askForEverything()
                }
                .buttonStyle(.borderedProminent)

                if let objectClass = memory.selectedClass {
                    Button(ObjectMemoryCopy.lastInViewButton(objectClass)) {
                        memory.askWhenLastInView()
                    }
                    .buttonStyle(.bordered)
                }
            }
            .disabled(memory.state.phase == .waiting)

            // Shown rather than disabling the buttons. Reachability here is the
            // *socket's*, and object memory travels over HTTP — refusing to ask
            // on the strength of a different transport's state would hide a
            // request that might well succeed. So the caveat is stated and the
            // control stays live; a request that does fail lands in
            // `.failed(.transport)`, which the shell already draws as
            // disconnected rather than as an error.
            if !isTowerReachable {
                Text(ObjectMemoryCopy.towerUnreachable)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
    }

    // MARK: Records

    @ViewBuilder
    private var recordsPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel(ObjectMemoryCopy.recordsHeading)

            VStack(alignment: .leading, spacing: 12) {
                switch memory.state {
                case .idle:
                    Text(ObjectMemoryCopy.nothingAskedYet)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                case .asking(let question):
                    HStack(spacing: 10) {
                        ProgressView()
                        Text(ObjectMemoryCopy.questionLine(question))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

                case .answered(let question, let answer):
                    ObjectMemoryAnswerView(question: question, answer: answer)

                case .noObjectMemory:
                    // Unreachable while `forcedPhase` is consulted above, and
                    // written anyway: the day this state stops forcing a phase,
                    // the panel must not fall through to a blank box.
                    Text(ObjectMemoryCopy.noObjectMemoryConfigured)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                case .failed(let failure):
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

/// One answer: what was asked, what window it came from, and the records — or
/// the honest silence.
struct ObjectMemoryAnswerView: View {
    let question: ObjectMemoryQuestion
    let answer: ObjectMemoryAnswer

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(ObjectMemoryCopy.questionLine(question))
                    .font(.subheadline.weight(.medium))
                Text(ObjectMemoryCopy.retentionLine(answer.envelope.retention))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let clamp = ObjectMemoryCopy.clampLine(answer.envelope.retention) {
                    Text(clamp)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            switch answer {
            case .listing(let listing):
                if listing.isEmpty {
                    // `ObjectMemoryCopy.recordability` rather than an inline
                    // `.map(envelope.isRecordable)`: a method reference handed
                    // to `map` is called from a nonisolated context under this
                    // target's default `MainActor` isolation, which is the same
                    // trap `WorldBuilderResultDecoder` documents.
                    ObjectMemoryEmptyView(
                        objectClass: listing.envelope.objectClass,
                        recordable: ObjectMemoryCopy.recordability(
                            of: listing.envelope.objectClass, in: listing.envelope
                        )
                    )
                } else {
                    Text(ObjectMemoryCopy.recordCountLine(listing.observations.count))
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                    ForEach(listing.observations) { observation in
                        ObjectObservationRow(observation: observation)
                    }
                }

            case .lastSeen(let lastSeen):
                if let observation = lastSeen.observation {
                    ObjectObservationRow(observation: observation)
                } else {
                    ObjectMemoryEmptyView(
                        objectClass: lastSeen.objectClass, recordable: lastSeen.recordable
                    )
                }
            }

            Text(ObjectMemoryCopy.recordableClasses(answer.envelope.recordedClasses))
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// An answer that carries no record.
///
/// **Not an error, and not "no results".** A missing record means the camera
/// was not pointed at one, or the detector scored it below threshold, or the
/// class is not one this cartridge ever writes, or the retention window closed.
/// None of those is "the object is not there", and the two wordings this view
/// chooses between are the two different silences.
struct ObjectMemoryEmptyView: View {
    let objectClass: String?
    let recordable: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(
                ObjectMemoryCopy.nothingObservedHeadline(
                    objectClass: objectClass, recordable: recordable
                ),
                systemImage: "questionmark.circle"
            )
            .font(.headline)

            Text(
                ObjectMemoryCopy.nothingObservedExplanation(
                    objectClass: objectClass, recordable: recordable
                )
            )
            .font(.subheadline)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

/// One record.
///
/// The headline and the claim are always visible; the frame reference and the
/// detection numbers sit behind a disclosure. That ordering is the argument:
/// what the record *says* comes first, and the identifiers a reader would
/// mistake for a location are one deliberate tap away and never appear without
/// `frameCaveat` under them.
struct ObjectObservationRow: View {
    let observation: ObjectObservation

    /// Collapsed by default. Expanded state is per-row and not persisted:
    /// nothing about which rows a person opened is worth keeping.
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(ObjectMemoryCopy.sightingHeadline(observation))
                .font(.body.weight(.medium))

            Text(ObjectMemoryCopy.timeLine(observation))
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            Text(ObjectMemoryCopy.claimLine(observation))
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)

            DisclosureGroup(isExpanded: $isExpanded) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(ObjectMemoryCopy.frameLine(observation.frame))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    // Never conditional. A frame reference without its caveat
                    // is the failure mode this whole screen is built against.
                    Text(ObjectMemoryCopy.frameCaveat)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .fixedSize(horizontal: false, vertical: true)

                    if let box = ObjectMemoryCopy.boxLine(observation.frame) {
                        Text(box)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    if let imagery = ObjectMemoryCopy.imageryLine(observation.frame) {
                        Text(imagery)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Text(ObjectMemoryCopy.confidenceLine(observation))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .fixedSize(horizontal: false, vertical: true)

                    if let privacy = ObjectMemoryCopy.privacyLine(observation) {
                        Text(privacy)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 4)
            } label: {
                Text(ObjectMemoryCopy.provenanceDisclosure)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 4)
        .accessibilityElement(children: .contain)
    }
}
