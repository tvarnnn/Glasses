//
//  ObjectMemoryCopy.swift
//  Glasses
//

import Foundation

/// Every sentence the Object Memory workspace can put in front of a person.
///
/// ## Why the copy is a type
///
/// Because the copy *is* the product constraint here, and prose scattered
/// through a `View` cannot be tested. This cartridge knows less than a reader
/// will assume it knows, and almost every natural phrasing of what it holds is
/// a lie:
///
/// | The natural sentence | Why it is false |
/// |---|---|
/// | "Your laptop was seen at 2:31" | It is a **category**. Nothing here can tell the wearer's laptop from anyone else's, and `identity: "category-not-instance"` says so on every record. |
/// | "Last seen in session 22e9d4…" | A session id is a pointer into a *recording*. Rendered as an answer to "where", it reads as a place, and this cartridge does not know where anything is. |
/// | "Your laptop is on the desk" | A record says a category was visible **once**. `claim: "category-was-visible-once"`. It says nothing about now. |
/// | "No laptop found" | An empty answer is `absence_means: "not-observed-by-this-cartridge"` — about what the camera captured, never about what exists. |
///
/// So every user-facing string is produced here, `ObjectMemoryWorkspaceView`
/// writes none of its own, and `ObjectMemoryCopyTests` runs the whole output of
/// `everyString(for:)` through the claims it is forbidden to make. A view that
/// composes its own sentence escapes that test, which is the one thing this
/// file exists to prevent.
///
/// ## The rules the strings obey
///
/// 1. **Indefinite article, always.** "A laptop was visible", never "your
///    laptop" and never "the laptop".
/// 2. **Past tense, always.** "was visible", never "is", never "is still".
/// 3. **A frame reference is labelled as one**, in the same sentence as the
///    identifiers, and is never presented as an answer to "where is it".
/// 4. **An empty answer says whose silence it is.** The cartridge's, not the
///    world's.
/// 5. **`null` is said out loud.** "not recorded" and "not tracked" are shown
///    as themselves; no number stands in for a missing one.
enum ObjectMemoryCopy {

    // MARK: - What the cartridge is

    static let cartridgeName = "Object Memory"

    /// The header. Sets the reader's expectations *down* to what is true,
    /// before any record is shown — the cheapest place to do it.
    static let summary = """
        This records that a category of thing was visible to the camera once, \
        and when. It does not know where anything is, it cannot tell one object \
        from another of the same kind, and no record says anything about now.
        """

    /// What the cartridge could ever have written down, so that a silence about
    /// anything else can be read for what it is.
    static func recordableClasses(_ classes: [String]) -> String {
        guard !classes.isEmpty else {
            return "This Tower's object memory records no categories at all."
        }
        return """
            Categories this memory can record: \(list(classes)). Anything else \
            has never been looked for.
            """
    }

    // MARK: - A record

    /// The headline for one sighting.
    ///
    /// Indefinite article and past tense, and the two together are the whole
    /// point: "A laptop was visible" is exactly as much as a record supports.
    static func sightingHeadline(_ observation: ObjectObservation) -> String {
        "\(indefiniteArticle(for: observation.objectClass).capitalized) \(observation.objectClass) was visible"
    }

    /// When, and on whose clock.
    ///
    /// Never rendered as a shutter time. `time_basis` is `tower-receipt`, and
    /// `Rule 16` forbids conflating when the glasses saw something with when
    /// the Tower received it — so the qualification travels in the same
    /// sentence as the timestamp rather than in a footnote nobody reads.
    static func timeLine(_ observation: ObjectObservation) -> String {
        let when = observation.observedAt.formatted(date: .abbreviated, time: .shortened)
        guard observation.timeBasis == ObjectMemoryContract.towerReceiptBasis else {
            // A basis this build does not recognise is shown uninterpreted. The
            // alternative — assuming it means the same as the one we know — is
            // how a receipt time quietly becomes a capture time.
            return """
                Timestamped \(when), on a basis this app does not recognise \
                (\(observation.timeBasis)), so it is shown without interpretation.
                """
        }
        return """
            The Tower received this frame on \(when). That is the Tower's \
            receipt time, not the moment the shutter fired.
            """
    }

    /// The claim, restated beside every record.
    ///
    /// Repeated per row rather than once at the top because a row is what gets
    /// screenshotted, read out of context, and remembered.
    static func claimLine(_ observation: ObjectObservation) -> String {
        """
        A category was in view once. That is the whole claim: it does not say \
        anything about now, and it cannot tell one \(observation.objectClass) \
        from another.
        """
    }

    /// The frame reference, labelled in the same breath as its identifiers.
    ///
    /// The failure this wording exists to avoid is "Your laptop: last seen in
    /// session 22e9d4…" — which reads as a place, and is the reason
    /// `ObjectMemoryCopyTests` asserts that no string can mention a capture id
    /// without also saying "Frame reference".
    static func frameLine(_ frame: FrameReference) -> String {
        guard frame.pointsAtACapture else {
            return """
                Frame reference: none. This record carries no capture \
                provenance, so there is nothing to point back at.
                """
        }
        var parts: [String] = []
        if let sessionID = frame.sessionID { parts.append("capture \(shortened(sessionID))") }
        if let frameSeq = frame.frameSeq { parts.append("frame \(frameSeq)") }
        parts.append("camera \(frame.camera)")
        return "Frame reference: " + parts.joined(separator: ", ") + "."
    }

    /// Said next to every frame reference, without exception.
    static let frameCaveat = """
        That is a pointer back into a recording, not a place. Nothing in this \
        memory knows where anything is in a room.
        """

    /// The bounding box, as what it is: a position in a picture.
    ///
    /// `nil` when there is no box. Never projected, never drawn over anything
    /// but the frame it came from, and never at the top level of a record — the
    /// Tower nests it inside `where` for exactly this reason.
    static func boxLine(_ frame: FrameReference) -> String? {
        guard let box = frame.boundingBoxNormalized, box.count == 4 else { return nil }
        return """
            Within that picture the detection covered \(percent(box[0])) to \
            \(percent(box[2])) across and \(percent(box[1])) to \(percent(box[3])) \
            down. Those are fractions of the frame, not distances in a room.
            """
    }

    /// What purging this record would and would not reach.
    ///
    /// `nil` when there is no pointer, because then there is nothing to warn
    /// about. Carried from `imagery_retention` rather than assumed, so a Tower
    /// that moved the imagery cannot leave this app repeating the old promise.
    static func imageryLine(_ frame: FrameReference) -> String? {
        guard frame.pointsAtACapture else { return nil }
        guard frame.imageryRetention == ObjectMemoryContract.captureSideImagery else {
            return """
                The frame this points at is kept under a retention this app does \
                not recognise (\(frame.imageryRetention)).
                """
        }
        return """
            The frame it points at is kept capture-side, under a retention this \
            cartridge neither sets nor enforces. Removing this record would not \
            reach that imagery.
            """
    }

    /// The three strength fields, in the order a reader should trust them, with
    /// every missing one said out loud.
    static func confidenceLine(_ observation: ObjectObservation) -> String {
        var sentences: [String] = []
        switch observation.confidence {
        case .unknown:
            sentences.append("The detector's confidence for this sighting was not recorded.")
        case .low, .medium, .high:
            sentences.append("Detector confidence: \(observation.confidence.displayName).")
        }

        if let best = observation.bestScore {
            sentences.append("Strongest score while it stayed in view: \(percent(best)).")
        } else {
            // Never "0%". `null` here means the field did not exist when the
            // record was written, and a zero would be a claim of no evidence.
            sentences.append("The strongest score was not tracked for this record.")
        }

        if let detector = observation.detectorScore {
            sentences.append("Score in the frame above: \(percent(detector)).")
        } else {
            sentences.append("The score in that frame was not recorded.")
        }

        sentences.append("None of these is a calibrated probability; they are detector output.")
        return sentences.joined(separator: " ")
    }

    /// What the record holds, from its own privacy tags. `nil` when it carries
    /// none, rather than a reassurance this app cannot support.
    static func privacyLine(_ observation: ObjectObservation) -> String? {
        guard observation.privacyTags.contains("derived-only") else { return nil }
        return "This record holds a label, a score and a box. No pixels."
    }

    // MARK: - An empty answer

    /// The headline when nothing was found. Never "not found", which reads as a
    /// verdict on the object.
    static func nothingObservedHeadline(objectClass: String?, recordable: Bool) -> String {
        guard recordable else { return "Never looked for" }
        guard let objectClass else { return "Nothing recorded in this window" }
        return "No record of \(indefiniteArticle(for: objectClass)) \(objectClass)"
    }

    /// Whose silence this is.
    ///
    /// The single most load-bearing string in the cartridge. Absence of a
    /// record is not absence of the object, and the sentence has to carry that
    /// on its own — a user reading "no results" will supply the wrong meaning
    /// for free.
    static func nothingObservedExplanation(objectClass: String?, recordable: Bool) -> String {
        guard recordable else {
            let named = objectClass ?? "that"
            return """
                “\(named)” is not a category this memory ever records, so it has \
                never been looked for. Its absence carries no information at all.
                """
        }
        let subject: String
        if let objectClass {
            subject = "\(indefiniteArticle(for: objectClass)) \(objectClass)"
        } else {
            subject = "anything"
        }
        return """
            This memory holds no record of \(subject) within the window it can \
            see. That is a statement about what the camera captured, not about \
            what exists: it may never have been pointed at one, or the detector \
            may not have scored it highly enough to write down. Absence of a \
            record is not absence of the thing.
            """
    }

    // MARK: - Retention

    /// The window the answer came from, and whether the question was narrowed.
    static func retentionLine(_ retention: ObjectMemoryRetention) -> String {
        guard let effective = retention.effectiveDays else {
            return """
                This memory was written without a time limit of its own, so \
                everything it holds is included.
                """
        }
        return """
            Showing what was recorded in the last \(days(effective)). Anything \
            older is not shown, and asking for a longer window cannot recover it.
            """
    }

    /// Shown only when the Tower actually refused a wider window, so a caller
    /// that asked for nothing is never told it was refused something.
    static func clampLine(_ retention: ObjectMemoryRetention) -> String? {
        guard retention.clamped else { return nil }
        guard let requested = retention.requestedDays, let effective = retention.effectiveDays else {
            return "A longer window was asked for than this memory keeps, and the extra was refused."
        }
        return """
            A window of \(days(requested)) was asked for; this memory keeps \
            \(days(effective)), and the difference was refused rather than served.
            """
    }

    // MARK: - Asking

    static func questionLine(_ question: ObjectMemoryQuestion) -> String {
        switch question {
        case .listing(let objectClass):
            guard let objectClass else { return "Everything recorded in the window" }
            return "Every record of \(indefiniteArticle(for: objectClass)) \(objectClass)"
        case .lastSeen(let objectClass):
            return "When \(indefiniteArticle(for: objectClass)) \(objectClass) was last in view"
        }
    }

    /// Why the ask control cannot be used, when it cannot.
    static let towerUnreachable = """
        The Tower is not connected, so its object memory cannot be asked \
        anything. Nothing already shown has changed; it is simply not being \
        refreshed.
        """

    /// The Tower answered 404: it serves no object memory at all.
    ///
    /// A statement about *configuration*, and worded so it cannot be read as a
    /// statement about what the wearer has seen.
    static let noObjectMemoryConfigured = """
        This Tower serves no object memory, so there is nothing to ask it for. \
        That is a fact about how the Tower is configured, not about what the \
        camera has seen.
        """

    static func unsupportedContract(_ identifier: String) -> String {
        """
        The Tower's object memory speaks an agreement this version of the app \
        does not implement (\(identifier)). Nothing is shown rather than \
        something guessed. Updating the app is what resolves this.
        """
    }

    // MARK: - Controls and headings

    /// The chrome, kept here with the prose rather than inline in the view.
    ///
    /// A button label is copy too, and "Find my laptop" is exactly the kind of
    /// sentence that would walk past a test that only looked at record rows.
    static let recordsHeading = "Records"
    static let showEverythingButton = "Show what was recorded"
    static let allCategories = "All categories"

    static func lastInViewButton(_ objectClass: String) -> String {
        "When was \(indefiniteArticle(for: objectClass)) \(objectClass) last in view"
    }

    /// The disclosure that holds the frame reference and the detection detail.
    ///
    /// Not "Where this was", which is the label a reader wants and the one
    /// thing this cartridge cannot supply.
    static let provenanceDisclosure = "Frame reference and detection detail"

    /// How many records the answer carried. Counts what was **served**, which
    /// is what fell inside the clamped window rather than what is on disk.
    static func recordCountLine(_ count: Int) -> String {
        count == 1
            ? "1 record within the window this read may see."
            : "\(count) records within the window this read may see."
    }

    /// Before anything has been asked. Says what asking does, because a person
    /// pressing a button on a memory cartridge deserves to know it reads rather
    /// than records.
    static let nothingAskedYet = """
        Nothing has been asked yet. Asking reads what the Tower already \
        recorded; it records nothing new and deletes nothing.
        """

    /// What this screen will be able to say, for the state panel's optional
    /// forward-looking line. Conditional, never a promise.
    static let futureDescription = """
        This workspace lists what the Tower's object memory recorded: which \
        category was in view, when, how strong the detection was, and which \
        frame of which capture the record points back at. It will never show \
        where something is, because nothing in this cartridge knows.
        """

    // MARK: - The test seam

    /// Every string this cartridge would put on screen for one answer.
    ///
    /// `ObjectMemoryCopyTests` asserts over this, and the view renders from the
    /// same functions, so a sentence cannot reach a person without passing the
    /// test — provided the view keeps writing none of its own. That proviso is
    /// the file's only real weak point and is called out in the handoff.
    static func everyString(
        for answer: ObjectMemoryAnswer, question: ObjectMemoryQuestion? = nil
    ) -> [String] {
        var strings: [String] = [summary, recordableClasses(answer.envelope.recordedClasses)]
        strings.append(retentionLine(answer.envelope.retention))
        if let clamp = clampLine(answer.envelope.retention) { strings.append(clamp) }

        if let question { strings.append(questionLine(question)) }

        switch answer {
        case .listing(let listing):
            strings.append(recordCountLine(listing.observations.count))
            if listing.isEmpty {
                strings.append(
                    nothingObservedHeadline(
                        objectClass: listing.envelope.objectClass,
                        recordable: recordability(of: listing.envelope.objectClass, in: listing.envelope)
                    )
                )
                strings.append(
                    nothingObservedExplanation(
                        objectClass: listing.envelope.objectClass,
                        recordable: recordability(of: listing.envelope.objectClass, in: listing.envelope)
                    )
                )
            }
            for observation in listing.observations {
                strings.append(contentsOf: everyString(for: observation))
            }

        case .lastSeen(let lastSeen):
            if let observation = lastSeen.observation {
                strings.append(contentsOf: everyString(for: observation))
            } else {
                strings.append(
                    nothingObservedHeadline(
                        objectClass: lastSeen.objectClass, recordable: lastSeen.recordable
                    )
                )
                strings.append(
                    nothingObservedExplanation(
                        objectClass: lastSeen.objectClass, recordable: lastSeen.recordable
                    )
                )
            }
        }

        return strings
    }

    /// Every string that does not depend on an answer: chrome, headings, and
    /// the four sentences the workspace can show without one.
    ///
    /// Checked by the same test, because a button label reaches a reader just
    /// as directly as a record row does.
    static let everyStaticString: [String] = [
        summary,
        recordsHeading,
        showEverythingButton,
        allCategories,
        nothingAskedYet,
        futureDescription,
        provenanceDisclosure,
        frameCaveat,
        towerUnreachable,
        noObjectMemoryConfigured,
    ]

    /// Every string shown for one record.
    static func everyString(for observation: ObjectObservation) -> [String] {
        var strings = [
            sightingHeadline(observation),
            timeLine(observation),
            claimLine(observation),
            confidenceLine(observation),
            frameLine(observation.frame),
            frameCaveat,
        ]
        if let box = boxLine(observation.frame) { strings.append(box) }
        if let imagery = imageryLine(observation.frame) { strings.append(imagery) }
        if let privacy = privacyLine(observation) { strings.append(privacy) }
        return strings
    }

    /// An unfiltered listing narrows to no class, so there is no class whose
    /// recordability could be in question — `true` keeps the wording on "this
    /// window holds nothing" rather than "that was never looked for".
    static func recordability(
        of objectClass: String?, in envelope: ObjectMemoryEnvelope
    ) -> Bool {
        guard let objectClass else { return true }
        return envelope.isRecordable(objectClass)
    }

    // MARK: - Small formatting

    /// "a" or "an", by first letter.
    ///
    /// An imperfect rule — English has "an hour" and "a user" — and it runs
    /// over a class list that is currently `laptop` and `cell phone`. It is a
    /// rule rather than a lookup table because a table would have to be edited
    /// every time the Tower widens `PERSISTED_CLASSES`, and a stale table is a
    /// worse failure than a wrong article.
    static func indefiniteArticle(for word: String) -> String {
        let vowels: Set<Character> = ["a", "e", "i", "o", "u"]
        guard let first = word.lowercased().first else { return "a" }
        return vowels.contains(first) ? "an" : "a"
    }

    /// A capture id, shortened for reading. Never shortened to the point of
    /// ambiguity, and always shown behind the "Frame reference" label.
    static func shortened(_ identifier: String) -> String {
        guard identifier.count > 10 else { return identifier }
        return String(identifier.prefix(8)) + "…"
    }

    /// A detector score as a percentage. Scores are floats in 0…1 on this wire.
    static func percent(_ value: Double) -> String {
        "\(Int((value * 100).rounded()))%"
    }

    /// A retention window in days, without a trailing `.0` on a whole number
    /// and without pretending a fractional window is a whole one.
    static func days(_ value: Double) -> String {
        let rounded = (value * 10).rounded() / 10
        let text: String
        if rounded == rounded.rounded() {
            text = String(Int(rounded))
        } else {
            text = String(rounded)
        }
        return rounded == 1 ? "\(text) day" : "\(text) days"
    }

    /// "laptop and cell phone", "a, b and c".
    static func list(_ items: [String]) -> String {
        switch items.count {
        case 0: return ""
        case 1: return items[0]
        case 2: return "\(items[0]) and \(items[1])"
        default:
            let head = items.dropLast().joined(separator: ", ")
            return "\(head) and \(items[items.count - 1])"
        }
    }
}
