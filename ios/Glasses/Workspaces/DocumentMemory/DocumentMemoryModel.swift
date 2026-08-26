//
//  DocumentMemoryModel.swift
//  Glasses
//

import Foundation

/// The boundary between the Document Memory workspace and whatever document
/// memory the Tower eventually keeps.
///
/// **Nothing in this file is a Tower protocol.** There is no retrieval route,
/// no query wire format, and no document schema — those are the Tower's to
/// define, and `docs/modules/ENVIRONMENTAL-MEMORY.md` deliberately leaves its
/// own retrieval interface at the level of illustrative examples
/// (`search_text(…)`, `last_seen(…)`) rather than a specification.
///
/// ## What this cartridge is, in terms of the existing module set
///
/// It is the "one constrained memory type" that ENVIRONMENTAL-MEMORY.md's
/// first-version success criteria asks for — searchable text-document history —
/// with the reading path from `docs/modules/VISUAL-QA.md` behind it. See
/// `docs/modules/DOCUMENT-MEMORY.md` for how the scope was drawn and what it
/// deliberately excludes.
///
/// ## Three refusals, each load-bearing
///
/// **No OCR on iOS.** Not a single character of text in this file is produced
/// on the phone. `docs/02-DEVELOPMENT-RULES.md` Rule 5 keeps heavy CV on the
/// Tower, and Rule 12 plus `docs/06-PRIVACY-DATA.md` make document contents
/// among the most sensitive data the platform touches. `DocumentTextAvailability`
/// reports whether the *Tower* extracted text; iOS never extracts, and cannot.
///
/// **No "viewing" anything.** `docs/07-PLATFORM-CONSTRAINTS.md` Limitation 8:
/// appearing in the camera does not prove the wearer looked at it, and the
/// mitigation is classified REQUIRES FUTURE HARDWARE/API. So a document was
/// *observed*, for an `ObservedDuration`, and every label says so.
///
/// **No thumbnail unless it was redacted.** A document photographed in the
/// world routinely contains a bystander, a screen, or a second document
/// (`docs/06-PRIVACY-DATA.md`, Sensitive Visual Information). The redaction
/// decision belongs to whoever produced the image, and this app withholds
/// anything that does not carry it.

// MARK: - Extracted text

/// Whether the Tower has text for a document, without this app ever producing
/// any.
///
/// The `.extracted` case carries a character count and **not the text**. The
/// count is what a list row needs in order to say the document is readable;
/// the text itself is fetched when a person opens one, so a list of documents
/// is not also a bulk transfer of every document's contents into the phone's
/// memory. `docs/06-PRIVACY-DATA.md` Data Minimization, applied at the point it
/// is cheapest to apply.
enum DocumentTextAvailability: Equatable, Sendable {
    /// The Tower has no text and did not say why. Distinct from `.notReadable`:
    /// silence is not a verdict.
    case unknown
    /// The Tower tried and found nothing legible. A real result — VISUAL-QA.md
    /// requires "insufficient visual evidence" to be a first-class answer
    /// rather than an edge case.
    case notReadable
    /// The Tower has text. `characterCount` is `nil` when it did not say how
    /// much.
    case extracted(characterCount: Int?)

    var hasText: Bool {
        if case .extracted = self { return true }
        return false
    }

    var displayName: String {
        switch self {
        case .unknown: return "Not reported"
        case .notReadable: return "No readable text"
        case .extracted(let count):
            guard let count else { return "Text available" }
            return "\(count) characters"
        }
    }
}

// MARK: - Source context

/// Where a document came from, when the Tower can say.
///
/// `worldID` is present because `docs/modules/ENVIRONMENTAL-MEMORY.md` allows
/// environmental observations to *optionally* reference spatial locations if
/// World Build later exposes a shared spatial service — and is explicit that
/// this "must be an explicit architecture evolution, not an assumed
/// dependency". So it is optional here, nothing requires it, and no view
/// degrades without it. Document Memory does not depend on World Builder.
struct DocumentSourceContext: Equatable, Sendable {
    /// The Tower's session identifier, opaque.
    var sessionID: String?
    /// The world this observation belongs to, if a world existed and the Tower
    /// chose to link them.
    var worldID: String?

    init(sessionID: String? = nil, worldID: String? = nil) {
        self.sessionID = sessionID
        self.worldID = worldID
    }

    var isEmpty: Bool { sessionID == nil && worldID == nil }
}

// MARK: - Document

/// One document the Tower observed.
///
/// Every descriptive field is optional. A Tower that reports an identifier and
/// a timestamp and nothing else must not force the UI to invent a title, and a
/// row for such a document is a short row rather than a row full of dashes.
struct RememberedDocument: Equatable, Identifiable, Sendable {
    /// The Tower's identifier, opaque.
    let id: String
    /// A title the Tower derived. `nil` renders as "Untitled document", which
    /// is a description of the record rather than an invented name for the
    /// thing.
    var title: String?
    /// A summary the Tower produced. Model output, hence the provenance below.
    var summary: String?
    /// Whether the Tower has the document's text, and how much.
    var text: DocumentTextAvailability
    /// When it was observed, and when this app heard about it — kept apart.
    var time: ObservationTime
    /// How long it was in the camera's field of view. Not attention.
    var observedDuration: ObservedDuration?
    /// How the Tower arrived at its title/summary/text. `.inferred` for
    /// anything a model wrote, which in practice is all of it.
    var provenance: ObservationProvenance
    /// A keyframe of the document, and whether it may be shown.
    var thumbnail: VisualArtifactState
    var source: DocumentSourceContext

    init(
        id: String,
        title: String? = nil,
        summary: String? = nil,
        text: DocumentTextAvailability = .unknown,
        time: ObservationTime = ObservationTime(),
        observedDuration: ObservedDuration? = nil,
        provenance: ObservationProvenance = .unknown,
        thumbnail: VisualArtifactState = .absent,
        source: DocumentSourceContext = DocumentSourceContext()
    ) {
        self.id = id
        self.title = title
        self.summary = summary
        self.text = text
        self.time = time
        self.observedDuration = observedDuration
        self.provenance = provenance
        self.thumbnail = thumbnail
        self.source = source
    }

    /// What to put on a row. Never an invented name — "Untitled document"
    /// describes the record, which is all this app knows.
    var displayTitle: String { title ?? "Untitled document" }

    /// Whether the thumbnail may be drawn. Delegates entirely to the artifact,
    /// so the rule lives in one place for every cartridge that shows an image.
    var isThumbnailDisplayable: Bool { thumbnail.isDisplayable }
}

// MARK: - Queries

/// A request for documents.
///
/// ## Why the input source is separate from the query
///
/// The query says *what* is being asked; `DocumentQueryOrigin` says *where the
/// words came from*. Keeping them apart is what lets a future Siri intent, a
/// custom wake word, or any other input layer submit the same query type
/// without this cartridge growing a dependency on speech, and without a text
/// field being the only way in.
///
/// **No voice input is implemented, required, or assumed.** The origin exists
/// so that adding one later is a new case and a new call site, not a redesign.
nonisolated enum DocumentQuery: Equatable, Sendable {
    /// The most recently observed documents.
    case recent(limit: Int)
    /// Documents whose text contains this, by whatever matching the Tower does.
    case text(String)
    /// Documents observed in a period. Deliberately an interval rather than an
    /// instant: "this morning" and "around lunch" are ranges, and collapsing
    /// them to a point is how an approximate question gets an exact and wrong
    /// answer.
    case observedWithin(DateInterval)
    /// A meaning-based query, resolved entirely on the Tower. iOS computes no
    /// embedding and runs no model — Rule 5.
    case semantic(String)

    /// What the user asked, for echoing back above the results.
    var displayText: String {
        switch self {
        case .recent: return "Recent documents"
        case .text(let text): return "Text: \(text)"
        case .observedWithin: return "By time observed"
        case .semantic(let text): return text
        }
    }
}

/// Where a query's words came from.
///
/// Recorded rather than ignored because a spoken query and a typed one may
/// deserve different confidence treatment later — a transcription is itself an
/// inference — and because a result set should be able to say how it was asked
/// for. Only `.appText` is reachable today.
enum DocumentQueryOrigin: String, Equatable, Sendable, CaseIterable {
    /// Typed in this app.
    case appText
    /// Submitted by another input layer on the device — a Siri intent, a
    /// shortcut, a wake word. **No such layer exists**; the case exists so that
    /// building one does not require changing this type.
    case externalIntent
}

/// How strongly the Tower's answer is supported.
///
/// `docs/modules/ENVIRONMENTAL-MEMORY.md`:
///
/// > If retrieval evidence is weak: return "not found" or uncertainty; never
/// > create a memory event retroactively to satisfy a query.
///
/// and `docs/07-PLATFORM-CONSTRAINTS.md` Core Principle 3: absence of
/// observation is not observation of absence. `.noObservation` and
/// `.notFound` are therefore different answers and are worded differently on
/// screen — one means the memory has nothing from that time or place at all,
/// the other means it looked and matched nothing.
enum DocumentQueryEvidence: Equatable, Sendable {
    /// Matches, with the Tower's own confidence if it reported one.
    case matched(confidence: Double?)
    /// The memory was searched and nothing matched.
    case notFound
    /// The memory holds nothing covering what was asked, so the question cannot
    /// be answered either way. **Never rendered as "no".**
    case noObservation

    var explanation: String {
        switch self {
        case .matched(let confidence):
            guard let confidence else { return "" }
            return "Match confidence \(ObservationProvenance.percent(confidence))."
        case .notFound:
            return "Nothing in the Tower's document memory matched."
        case .noObservation:
            return """
                The Tower has no observations covering that. That is not the \
                same as the document not existing — the glasses may simply \
                never have seen it.
                """
        }
    }
}

/// One answer to one query.
struct DocumentQueryResult: Equatable, Sendable {
    let query: DocumentQuery
    let origin: DocumentQueryOrigin
    var documents: [RememberedDocument]
    var evidence: DocumentQueryEvidence

    /// Throws when the Tower's answer is internally inconsistent.
    ///
    /// ## Why this throws rather than coercing
    ///
    /// A result that claims `matched` while carrying no documents is not a
    /// coherent answer — a truncated payload, a partial decode, a contract this
    /// build half-understands. An earlier version quietly rewrote that to
    /// `.notFound`, whose user-facing sentence is *"Nothing in the Tower's
    /// document memory matched."*
    ///
    /// That is a **definite negative statement about the user's own memory,
    /// manufactured from a decode failure**, with the Tower's own confidence
    /// discarded on the way. Core Principle 3 forbids exactly that direction of
    /// travel: a gap in what we could read is not evidence about the world.
    /// The safe direction from a broken payload is a failure, not a stronger
    /// claim than the Tower made — and `CartridgeFailure.Kind.undecodableResponse`
    /// exists for it.
    ///
    /// Throwing also puts the decision where it belongs: at the decode site,
    /// which is the only place that knows a payload was involved.
    init(
        query: DocumentQuery,
        origin: DocumentQueryOrigin,
        documents: [RememberedDocument] = [],
        evidence: DocumentQueryEvidence
    ) throws {
        if documents.isEmpty, case .matched = evidence {
            throw CartridgeFailure(
                kind: .undecodableResponse,
                message: "The Tower reported a match but sent no documents, so the answer could not be read."
            )
        }
        self.query = query
        self.origin = origin
        self.documents = documents
        self.evidence = evidence
    }
}

// MARK: - State

/// What the Document Memory workspace should be showing.
///
/// `.unsupported` is the only reachable state today.
enum DocumentMemoryState: Equatable, Sendable {
    case unsupported(reason: String)
    /// A memory exists and nothing has been asked of it.
    case idle
    /// A query is in flight.
    case searching(DocumentQuery)
    /// A query returned. Carries the whole result, including the "nothing
    /// found" and "never observed" answers, which are results and not failures.
    case results(DocumentQueryResult)
    case failed(CartridgeFailure)

    var result: DocumentQueryResult? {
        if case .results(let result) = self { return result }
        return nil
    }

    var phase: CartridgePhase {
        switch self {
        case .unsupported: return .unsupported
        case .idle: return .idle
        case .searching: return .waiting
        // A returned answer is settled even when it is empty: the Tower is not
        // still working on it, and a spinner over "nothing found" would suggest
        // otherwise.
        case .results: return .settled
        case .failed: return .failed
        }
    }
}
