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
/// ## No camera controls, and what the Start button is instead
///
/// Like the other read-only workspaces, this one is handed no
/// `GlassesConnection`, so the number of places in the app that can start a
/// **capture** stays at two. The controls this screen grew on 2026-08-27 start
/// and stop the Tower's **producer** — the process that reads a recording and
/// writes observations — and they reach a different router that cannot touch
/// the store at all. It still cannot delete: the query transport is two `GET`s,
/// and real deletion lives on the Tower where a human types it against a store
/// they can name.
///
/// Those controls exist because the alternative was measured. The 2026-08-26
/// physical run remembered 64 real observations and **every one of them
/// required a person to find a capture directory and start a producer in a
/// second terminal.** That is not a product.
///
/// ## The one rule this screen cannot get wrong
///
/// **Liveness is drawn from `following`, never from `state`.** The session
/// payload says so itself. A Pause whose producer ignores `SIGTERM` answers 200
/// with `state: "paused"` while the process keeps recording, so a Pause button
/// keyed on `state` tells a person they stopped being recorded when they did
/// not. Every liveness affordance below reads `memory.liveness`, which reads
/// `following`, and the contradiction between the two is shown loudly rather
/// than reconciled.
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
            // Above the query controls deliberately. Whether this memory is
            // being written into right now outranks what it already holds:
            // somebody who opens this screen to check they are not being
            // recorded should not have to scroll past a list of records to
            // find out.
            ObjectMemorySessionPanel(memory: memory)
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
        // Liveness has a shelf life: `following` names what a producer is alive
        // on now, and a value read once when the screen opened is a claim about
        // a process that may have died since. Bounded by cancellation on
        // disappear rather than running for the life of the app.
        .onAppear { memory.startWatchingSession() }
        .onDisappear { memory.stopWatchingSession() }
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
                    ObjectMemoryAnswerView(
                        question: question, answer: answer, memory: memory
                    )

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
    /// Held so a row can make its own picture loader. The row never touches a
    /// client itself — see `ObjectMemoryViewModel.pictureLoader(for:)`.
    @ObservedObject var memory: ObjectMemoryViewModel

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
                        ObjectObservationRow(observation: observation, memory: memory)
                    }
                }

            case .lastSeen(let lastSeen):
                if let observation = lastSeen.observation {
                    ObjectObservationRow(observation: observation, memory: memory)
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

            // What the Tower actually reported about itself, composed only
            // from what the payload carried — including the fact that it does
            // not name a detector, which this app must not fill in.
            Text(ObjectMemoryCopy.whatThisTowerReports(answer))
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
    @ObservedObject var memory: ObjectMemoryViewModel

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

            // Only when this Tower offered imagery routes **and** the record
            // carries a handle. Neither is assumed: the routes are read off the
            // envelope, and a record with no handle simply gets no picture
            // rather than taking the row down with it.
            if memory.offersPictures, let observationID = observation.observationID {
                ObjectMemoryPictureView(
                    objectClass: observation.objectClass,
                    loader: memory.pictureLoader(for: observationID)
                )
            }

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

                    // How long the sighting lasted, which policy tier admitted
                    // the record, and what — if anything — agreed with it. All
                    // three are `nil` on a record that does not carry them, and
                    // none of them is invented for one that does not.
                    ForEach(
                        [
                            ObjectMemoryCopy.durationLine(observation),
                            ObjectMemoryCopy.tierLine(observation),
                            ObjectMemoryCopy.verificationLine(observation),
                        ].compactMap { $0 },
                        id: \.self
                    ) { line in
                        Text(line)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

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

// MARK: - The session

/// Start, Pause, Resume and Stop — and, above them, whether this memory is
/// being written into.
///
/// ## The ordering is the argument
///
/// The **liveness** line comes first and is drawn from `following`. The
/// **intent** line comes second and is drawn from `state`, labelled as what was
/// asked for. That is the opposite of the order a control panel usually takes,
/// and it is deliberate: a person looking at this panel wants to know whether
/// they are being recorded, and `state` cannot answer that question. It answers
/// a different one that looks identical.
///
/// When the two contradict each other in the harmful direction — the Tower
/// reporting a Pause as honoured while a producer is still alive on a recording
/// — the contradiction is shown in a warning role above everything else. That
/// case was reproduced during the 2026-08-27 integration and is the reason this
/// whole surface exists.
///
/// ## This view writes no prose either
///
/// Same rule as the workspace: every sentence comes from `ObjectMemoryCopy`,
/// including the button labels, and `ObjectMemoryCopyTests` asserts over that
/// type's whole output.
struct ObjectMemorySessionPanel: View {
    @ObservedObject var memory: ObjectMemoryViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel(ObjectMemoryCopy.sessionHeading)

            VStack(alignment: .leading, spacing: 10) {
                switch memory.session {
                case .unread:
                    caption(ObjectMemoryCopy.sessionUnread)

                case .working:
                    HStack(spacing: 10) {
                        ProgressView()
                        caption(ObjectMemoryCopy.sessionUnread)
                    }

                case .known(let snapshot):
                    reading(snapshot, refusal: nil)

                case .refused(let refusal):
                    reading(refusal.snapshot, refusal: refusal)

                case .noSessionControl:
                    caption(ObjectMemoryCopy.noSessionControl)

                case .failed(let failure):
                    caption(failure.message)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 18))
        }
    }

    /// One reading, with the liveness claim above the intent claim.
    @ViewBuilder
    private func reading(
        _ snapshot: CartridgeSessionSnapshot, refusal: CartridgeSessionRefusal?
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            // The harmful contradiction, first and in the warning role. Not a
            // caption and not tertiary: this is the one sentence on the screen
            // that corrects a false belief a person may already be holding.
            if let contradiction = ObjectMemoryCopy.livenessContradictsIntentLine(snapshot) {
                Label(contradiction, systemImage: "exclamationmark.triangle.fill")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }

            // Liveness, from `following`. The glyph is filled only when a
            // producer is actually alive on a recording — never when `state`
            // merely says `active`.
            Label(
                ObjectMemoryCopy.livenessLine(snapshot),
                systemImage: snapshot.isFollowingACapture
                    ? "record.circle.fill" : "record.circle"
            )
            .font(.subheadline)
            .foregroundStyle(snapshot.isFollowingACapture ? .primary : .secondary)
            .fixedSize(horizontal: false, vertical: true)

            // Intent, second and labelled as intent by its own sentence.
            caption(ObjectMemoryCopy.intentLine(snapshot))

            if let refusal {
                // A refusal is information, not an error banner: it says which
                // control would have worked. An idempotent no-op never reaches
                // here at all — that is a 200 and lands in `.known`.
                VStack(alignment: .leading, spacing: 4) {
                    Text(ObjectMemoryCopy.refusalLine(refusal))
                        .font(.subheadline)
                        .fixedSize(horizontal: false, vertical: true)
                    caption(ObjectMemoryCopy.refusalProvenanceLine(refusal))
                }
            }

            controls(snapshot)

            if !snapshot.supported {
                caption(ObjectMemoryCopy.sessionUnsupported)
            }
            caption(ObjectMemoryCopy.sessionProvenanceLine(snapshot))
            if let captures = ObjectMemoryCopy.capturesLine(snapshot) {
                caption(captures)
            }
            caption(ObjectMemoryCopy.startMeaningLine)
            caption(ObjectMemoryCopy.sessionNotPersistedLine)
        }
    }

    /// The verbs, read off the Tower's own `actions` list rather than
    /// hard-coded — which is what the field is for, and what lets a Tower that
    /// grows a fifth verb be noticed rather than silently half-rendered.
    ///
    /// Nothing is hidden by state. `start` from `active` is a legal idempotent
    /// no-op, `stop` is never refused, and disabling a control on this app's
    /// guess about what the Tower will accept would make this app's model of
    /// the state machine authoritative over the Tower's.
    private func controls(_ snapshot: CartridgeSessionSnapshot) -> some View {
        HStack(spacing: 10) {
            ForEach(snapshot.offeredActions, id: \.rawValue) { action in
                // Written out rather than picked with a ternary: `buttonStyle`
                // is generic over its argument, so the two concrete styles have
                // no common type to choose between without erasing one, and an
                // erasing wrapper here would be more machinery than the branch
                // it replaces.
                if action == .start {
                    Button(ObjectMemoryCopy.actionButton(action)) {
                        memory.apply(action)
                    }
                    .buttonStyle(.borderedProminent)
                } else {
                    Button(ObjectMemoryCopy.actionButton(action)) {
                        memory.apply(action)
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
        .disabled(!snapshot.supported)
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: - A record's picture

/// The picture behind one record, or the sentence explaining why there is not
/// one.
///
/// ## Every branch here is a sentence, and none of them is a broken image
///
/// The four things that can come back are a picture, "the memory is kept and
/// the picture is gone" (410), "this Tower is serving no pictures" (503) and
/// "nothing under this handle" (404). Three of those used to arrive as
/// `.transport` and render as *the Tower is unreachable* — which is worse than
/// a broken image, because it sends a person to check a network cable about a
/// machine that answered them clearly and truthfully.
///
/// ## The caption is not optional
///
/// A picture is a much stronger location cue than a sentence, and no string
/// test can catch it. `ObjectMemoryCopy.pictureCaption` appears under **every**
/// picture this view draws, unconditionally, in the same way `frameCaveat`
/// appears under every frame reference. The filter line and the fill lines go
/// with it, because a filtered picture described only by what the filter
/// catches reads as a guarantee.
///
/// ## Nothing is kept
///
/// Bytes live on the loader, the loader is this view's `@StateObject`, and
/// `onDisappear` drops them rather than waiting for deallocation. There is no
/// shared image cache keyed by observation id anywhere in this app, and adding
/// one would undo the `Cache-Control: no-store` the Tower sends.
struct ObjectMemoryPictureView: View {
    let objectClass: String
    @StateObject var loader: ObjectMemoryPictureLoader

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            switch loader.phase {
            case .unasked:
                // Not fetched until the row appears, and drawn as a control
                // rather than as an empty box: a person should be able to see
                // that a picture exists to be asked for.
                Button(ObjectMemoryCopy.showThePictureButton) { loader.load() }
                    .font(.caption)
                    .buttonStyle(.bordered)

            case .loading:
                ProgressView()

            case .picture(let data, let description):
                picture(data, description)

            case .noPicture(let description):
                noPicture(description)

            case .noPicturesOffered:
                caption(ObjectMemoryCopy.noPicturesOffered)

            case .failed(let failure):
                caption(failure.message)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onAppear { loader.load() }
        // The row leaving the screen is exactly when this app should stop
        // holding a photograph of somebody's home.
        .onDisappear { loader.forget() }
    }

    @ViewBuilder
    private func picture(
        _ data: Data, _ description: ObjectMemoryImageryDescription
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if let image = UIImage(data: data) {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxWidth: .infinity)
                    .clipShape(.rect(cornerRadius: 12))
                    // The caption is the accessibility label too. A
                    // screen-reader user reaching an unlabelled image gets the
                    // weakest possible version of this screen.
                    .accessibilityLabel(
                        ObjectMemoryCopy.pictureCaption(
                            objectClass: description.objectClass ?? objectClass,
                            kind: loader.kind
                        )
                    )
            } else {
                // Bytes that will not decode. Said out loud rather than left as
                // the blank rectangle `Image` would otherwise draw, which on
                // this screen would read as "there was nothing there".
                caption(ObjectMemoryCopy.unreadableImageryAnswer)
            }

            // Unconditional, and directly under the picture. This is the whole
            // burden — see the type's documentation.
            Text(
                ObjectMemoryCopy.pictureCaption(
                    objectClass: description.objectClass ?? objectClass, kind: loader.kind
                )
            )
            .font(.caption)
            .fixedSize(horizontal: false, vertical: true)

            if let obscured = ObjectMemoryCopy.subjectObscuredLine(
                description, kind: loader.kind
            ) {
                caption(obscured)
            }
            caption(ObjectMemoryCopy.filterLine(description))
            caption(ObjectMemoryCopy.regionsFilledLine(description))
            caption(ObjectMemoryCopy.pictureRetentionLine)

            // The other route, so a person who wants the context or the detail
            // can have it. Both come with the same caption.
            Button(
                loader.kind == .crop
                    ? ObjectMemoryCopy.showTheWholeFrameButton
                    : ObjectMemoryCopy.showTheDetectionButton
            ) {
                loader.show(loader.kind == .crop ? .frame : .crop)
            }
            .font(.caption)
            .buttonStyle(.bordered)
        }
    }

    /// A refusal, rendered as the sentence it is.
    ///
    /// A neutral glyph, never a warning triangle and never a broken-image
    /// symbol: a 410 here is a **correct** outcome of capture-side retention
    /// doing what it is supposed to do, and dressing it as a failure would tell
    /// a person something went wrong when nothing did.
    private func noPicture(_ description: ObjectMemoryImageryDescription) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(
                ObjectMemoryCopy.noPictureHeadline(description),
                systemImage: "photo.on.rectangle.angled"
            )
            .font(.subheadline.weight(.medium))
            .fixedSize(horizontal: false, vertical: true)

            Text(ObjectMemoryCopy.noPictureExplanation(description))
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(.caption2)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}
