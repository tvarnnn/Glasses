//
//  ExperimentalCVModel.swift
//  Glasses
//

import Foundation

/// The boundary between the Experimental CV Lab workspace and whatever
/// experiments the Tower eventually runs.
///
/// **Nothing in this file is a Tower protocol**, and this cartridge is the one
/// where that restraint costs the most, because it is the cartridge closest to
/// existing: `docs/03-ROADMAP.md` makes Experimental CV Lab Module #1 (V0.9),
/// and it is the only module the Tower actually runs. The temptation
/// is therefore to guess at its result schema, which would be the most likely
/// of all four to be wrong in detail while looking right in outline.
///
/// So this file hard-codes **no experiment, no algorithm, and no metric name**.
/// `docs/modules/EXPERIMENTAL-CV.md` lists nineteen candidate experiments and
/// says "the list is intentionally broad"; picking any subset here would make
/// the iOS app the place the experiment list is decided, which is exactly
/// backwards. The Tower names its experiments, names its metrics, and names
/// their units; iOS displays those names and never matches on them.
///
/// What iOS *does* own is the discipline the module spec imposes on results:
///
/// > Experiment output (detections, depth estimates, classifications, tracked
/// > poses, etc.) is model inference, not a measured sensor fact, unless the
/// > experiment specifically validates against a ground-truth reference.
/// > Results/logs must distinguish the two.
///
/// and
///
/// > Avoid declaring an approach "better" without a measurement.
///
/// Both are enforced here in the type system rather than left to a view's good
/// intentions — see `CVMetric`.

// MARK: - Experiment identity

/// One experiment the Tower says it can run.
///
/// The Tower is the registry. iOS holds no list of experiments, offers no
/// picker populated from a hardcoded array, and cannot invent one — the
/// `available` array in `ExperimentalCVState.idle` is whatever the Tower
/// declared, and today it is empty because the Tower declares nothing.
struct CVExperiment: Equatable, Identifiable, Sendable {
    /// The Tower's identifier. Opaque: compared for equality, never parsed.
    let id: String
    /// The Tower's own name for it.
    let name: String
    /// What it does, if the Tower says. `nil` renders as no subtitle rather
    /// than as an invented one.
    var summary: String?

    init(id: String, name: String, summary: String? = nil) {
        self.id = id
        self.name = name
        self.summary = summary
    }
}

// MARK: - Results

/// One number an experiment produced.
///
/// ## Why `provenance` is not optional
///
/// Because `docs/modules/EXPERIMENTAL-CV.md` requires results to distinguish
/// model inference from measured fact, and an optional field with a `nil`
/// default is a field that gets skipped at the call site. Requiring it means
/// the question "is this a measurement or a guess?" is answered by whoever
/// decodes the Tower's reply — the only party that can answer it — rather than
/// by a view that has already lost the context.
///
/// ## Why `baseline` exists
///
/// The same document's success criteria require a baseline, and end with
/// "avoid declaring an approach 'better' without a measurement". `comparison`
/// below is the enforcement: with no baseline it returns `nil`, and there is no
/// other property that renders a verdict. A view cannot say "better" without
/// the Tower having supplied something to be better *than*.
struct CVMetric: Equatable, Identifiable, Sendable {
    /// The Tower's label. Displayed verbatim.
    let label: String
    let value: Double
    /// The Tower's unit string, if any. Never assumed — a metric with no unit
    /// is shown as a bare number, which is what an unlabelled quantity is.
    var unit: String?
    /// Whether the Tower measured this or a model produced it.
    let provenance: ObservationProvenance
    /// The reference value this run is being compared against, if the
    /// experiment defined one.
    var baseline: Double?
    /// Whether a larger value is a better result. `nil` when the Tower did not
    /// say, in which case no direction can be claimed — many useful metrics
    /// (latency, error) improve downward and guessing gets it exactly backwards
    /// half the time.
    var higherIsBetter: Bool?

    var id: String { label }

    init(
        label: String,
        value: Double,
        unit: String? = nil,
        provenance: ObservationProvenance,
        baseline: Double? = nil,
        higherIsBetter: Bool? = nil
    ) {
        self.label = label
        self.value = value
        self.unit = unit
        self.provenance = provenance
        self.baseline = baseline
        self.higherIsBetter = higherIsBetter
    }

    /// Formatted for a row. Unit omitted entirely when absent, rather than
    /// substituted.
    var displayValue: String {
        let formatted = Self.format(value)
        guard let unit, !unit.isEmpty else { return formatted }
        return "\(formatted) \(unit)"
    }

    /// How this run compares to its baseline — or `nil`, which is the answer
    /// whenever a comparison would be unfounded.
    ///
    /// Three separate ways to get `nil`, each of them a real gap:
    /// no baseline, no stated direction, or a difference of exactly zero. The
    /// first two are missing information and the third is a genuine tie; none
    /// of them is a verdict, and none may be rendered as one.
    var comparison: Comparison? {
        guard let baseline, let higherIsBetter else { return nil }
        let delta = value - baseline
        guard delta != 0 else { return .unchanged }
        return (delta > 0) == higherIsBetter ? .better(delta: delta) : .worse(delta: delta)
    }

    enum Comparison: Equatable, Sendable {
        case better(delta: Double)
        case worse(delta: Double)
        case unchanged

        var label: String {
            switch self {
            case .better(let delta): return "Better by \(CVMetric.format(abs(delta)))"
            case .worse(let delta): return "Worse by \(CVMetric.format(abs(delta)))"
            case .unchanged: return "Unchanged"
            }
        }
    }

    /// Three significant-ish decimals, trimmed. Chosen so a probability and a
    /// millisecond timing both read sensibly without the Tower having to say
    /// which it sent.
    static func format(_ value: Double) -> String {
        if value == value.rounded() && abs(value) < 1e9 {
            return String(Int(value))
        }
        return String(format: "%.3f", value)
    }
}

/// What an experiment drew on top of a frame, and whether this app may show it.
///
/// The annotation *geometry* is deliberately absent — boxes, masks, keypoints
/// and flow fields each need a schema the Tower has not defined, and a wrong
/// coordinate convention renders confidently in the wrong place. What is here
/// is the count the Tower reports and the state of the rendered image it
/// produced, which is enough for the workspace to be honest about both.
///
/// The artifact carries its own `RedactionState`, so an annotated frame
/// containing a bystander is withheld by the same rule that governs every other
/// stored image (`docs/06-PRIVACY-DATA.md`). An experiment does not get a
/// privacy exemption for being a debug surface.
struct CVAnnotationReport: Equatable, Sendable {
    /// How many things the experiment marked. `nil` when not reported; `0` is a
    /// real result meaning "found nothing", and the two must not merge.
    var count: Int?
    /// The rendered annotated frame, if the Tower produced one.
    var artifact: VisualArtifactState

    init(count: Int? = nil, artifact: VisualArtifactState = .absent) {
        self.count = count
        self.artifact = artifact
    }

    var hasReport: Bool {
        count != nil || artifact != .absent
    }
}

/// Timings for one run, keeping the clocks the platform requires be kept apart.
///
/// `docs/07-PLATFORM-CONSTRAINTS.md` Limitation 9: Tower receipt time must not
/// be treated as camera capture time, and processing time is a third quantity
/// again. `processingMs` is the Tower measuring itself — a genuine measurement,
/// and the only one of the three iOS can trust unreservedly.
///
/// **There is no end-to-end latency field**, and its absence is deliberate. It
/// would have to be computed across the phone's clock and the Tower's, and the
/// DAT frame timestamp's semantics are an open question in that same document
/// ("whether that timestamp reflects on-glasses capture time, phone-side
/// arrival time, or something else" is explicitly unconfirmed). A number
/// computed from two clocks of unknown relationship is not a latency.
struct CVTimings: Equatable, Sendable {
    /// Wall-clock milliseconds the Tower spent on the work, as the Tower
    /// measured it.
    var processingMs: Double?
    /// When the underlying observation happened and when the report arrived.
    var time: ObservationTime

    init(processingMs: Double? = nil, time: ObservationTime = ObservationTime()) {
        self.processingMs = processingMs
        self.time = time
    }
}

/// One execution of one experiment.
struct CVExperimentRun: Equatable, Sendable {
    let experiment: CVExperiment
    var metrics: [CVMetric]
    var annotation: CVAnnotationReport
    var timings: CVTimings
    /// Frames the Tower says it processed in this run.
    var framesProcessed: Int?

    init(
        experiment: CVExperiment,
        metrics: [CVMetric] = [],
        annotation: CVAnnotationReport = CVAnnotationReport(),
        timings: CVTimings = CVTimings(),
        framesProcessed: Int? = nil
    ) {
        self.experiment = experiment
        self.metrics = metrics
        self.annotation = annotation
        self.timings = timings
        self.framesProcessed = framesProcessed
    }

    /// True when at least one metric came from a model rather than a
    /// measurement, which is what obliges the workspace to show the inference
    /// caveat once for the whole run rather than repeating it per row.
    var containsInference: Bool {
        metrics.contains { $0.provenance.isInference }
    }
}

// MARK: - The frame channel

/// The running experiment's own answer for one frame, as the Tower's per-frame
/// reply reports it.
///
/// ## Why this is a separate type instead of a case of `ExperimentalCVState`
///
/// Because it arrives on a different channel from everything above, and keeping
/// the two apart is what lets this workspace show the experiment's real output
/// without weakening the cartridge layer's central invariant.
///
/// `ExperimentalCVState` models the **cartridge channel**: a typed contract the
/// Tower declares on `GET /cartridges`, a run this app asked for, metrics with
/// provenance and baselines attached. The Tower offers none of that for
/// `experimental_cv` — it lists the module under `not_offered` precisely
/// *because* "results already reach the client on `frame_result`" — so that
/// state is correctly `.unsupported`, its phase is `.unsupported`, and
/// `CartridgePhase.mayCarryData` says an `.unsupported` phase carries nothing.
///
/// The per-frame reply is the **frame channel**: the Tower's answer to a frame
/// this app sent, on the socket the frame went out on, with no contract behind
/// it and no provenance attached. Folding it into `ExperimentalCVState` would
/// have meant one of two things — inventing a cartridge state the Tower never
/// offered, or letting `.unsupported` carry a payload. The second is
/// `mayCarryData` reduced to a comment. So this sits *beside* the cartridge
/// state rather than inside it, and the workspace can draw the experiment's
/// actual number while saying, in the same breath and just as truthfully, that
/// there is no contract, no list of experiments, and no way to choose one.
///
/// ## The pair rule
///
/// `result_value` is a bare number whose meaning belongs to the experiment;
/// `result_label` is the experiment's own name for it. Neither is readable
/// alone here — they are held as one `Labelled` or not at all — so no view can
/// render the number under a caption of its own invention. That is the position
/// `CVMetric` already takes on units, one level down.
struct CVFrameReading: Equatable, Sendable {
    /// A number and the Tower's own name for it. There is no way to construct
    /// one without both, which is where the pair rule actually lives.
    struct Labelled: Equatable, Identifiable, Sendable {
        /// What tells one row from another within a single reading.
        ///
        /// **Not the label.** For a measurement it is the Tower's own
        /// dictionary key, kept exactly as sent: keys are unique by
        /// construction, whereas `label` is trimmed, so `{"edges": 1,
        /// " edges": 2}` collapses to one caption. When identity was the
        /// trimmed caption, `ForEach` saw two rows with one id and the sort key
        /// was equal for both — and `sorted(by:)` is not stable, so the pair
        /// could swap places on every reply, which is the twelve-times-a-second
        /// reshuffle the sort was added to prevent.
        let id: String
        /// The Tower's words, shown verbatim and never matched on.
        let label: String
        let value: Double

        /// The only initialiser, and so genuinely the only way to build one.
        ///
        /// It was previously a private static factory beside a synthesised
        /// memberwise `init`, which is not the same thing: the memberwise init
        /// was internal and walked straight past the guards below. Failable
        /// rather than throwing because there is exactly one outcome for every
        /// way of failing — the Tower did not send a usable pair — and nothing
        /// downstream can act differently on which.
        ///
        /// A blank label counts as no label. The wire cannot distinguish an
        /// absent string from an empty one, and a row captioned with whitespace
        /// is a bare number with extra steps.
        ///
        /// - Parameter id: The wire key this came from, when there is one.
        ///   Defaults to the trimmed label, which is right for the headline —
        ///   a reading has at most one.
        init?(id: String? = nil, label: String?, value: Double?) {
            guard let value, let label else { return nil }
            let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return nil }
            self.id = id ?? trimmed
            self.label = trimmed
            self.value = value
        }

        /// Formatted by `CVMetric.format` — this app's single answer to "how do
        /// you print a number whose unit nobody named". Shared with the home
        /// screen's tile, so the two places this one figure is drawn cannot
        /// drift apart on how it reads.
        var displayValue: String { CVMetric.format(value) }
    }

    /// Which frame this answers, matching the `seq` the app sent. Evidence that
    /// a round trip completed rather than a result in itself, which is why it
    /// is deliberately excluded from `hasAnything`.
    let sequence: Int?
    /// The experiment's headline answer, or `nil` when either half of the pair
    /// was missing.
    let headline: Labelled?
    /// Mean pixel intensity, 0...1. `nil` means the experiment reported none,
    /// never that the frame was dark.
    let meanIntensity: Double?
    /// Wall-clock milliseconds the Tower spent on this frame, as the Tower
    /// measured it. "ms" is not an invented unit: the wire field is named
    /// `processing_ms`, so it is the Tower's own declaration.
    let processingMs: Double?
    /// The Tower's additive measurements, each under the name the Tower gave
    /// it. Sorted by that name, because a dictionary has no stable order and a
    /// list of figures that reshuffles itself twelve times a second is
    /// unreadable — and the sort is *total*, breaking a tie between two
    /// captions on the untrimmed wire key, so that two keys differing only in
    /// whitespace cannot leave the order undetermined.
    let measurements: [Labelled]

    /// What this channel says about where its numbers came from: nothing.
    ///
    /// There is no provenance field on `frame_result`, and Rule 16 does not
    /// permit silence to be read as "measured". `.unknown` is the honest
    /// answer, and the caveat it carries is owed wherever these figures are
    /// drawn — which is a real obligation on every call site, not a remark.
    ///
    /// Both sites discharge it, and neither does so per figure: the Experimental
    /// CV Lab states it once under the result card
    /// (`ExperimentalCVWorkspaceView.figures`), and the home screen states it
    /// once under the metric grid, scoped by name to the experiment's tiles
    /// because the rest of that grid is counters the phone measured itself.
    /// Once for a group is enough — repeating it per row turns a caveat into
    /// wallpaper — but *nowhere* is not, and the home screen's tiles are the
    /// harder case rather than the easier one: an unremarked experiment figure
    /// among genuine counters reads as another counter.
    static let provenance: ObservationProvenance = .unknown

    /// Whether the Tower reported anything at all about the frame.
    ///
    /// A reply carrying only a sequence number is a real answer and a different
    /// one from no reply at all: the Tower processed the frame and the
    /// experiment concluded nothing about it. A workspace that showed those two
    /// identically would leave someone waiting for a result that has already
    /// arrived and was empty.
    var hasAnything: Bool {
        headline != nil || meanIntensity != nil || processingMs != nil || !measurements.isEmpty
    }

    /// Projects one Tower reply. Every field is optional on the wire and stays
    /// optional here; nothing is defaulted into existence.
    init(_ result: TowerFrameResult) {
        sequence = result.sequence
        headline = Labelled(label: result.resultLabel, value: result.resultValue)
        meanIntensity = result.meanIntensity
        processingMs = result.processingMs
        measurements = result.metrics
            .compactMap { Labelled(id: $0.key, label: $0.key, value: $0.value) }
            // Ordered on the caption first, because that is what a reader sees,
            // and on the wire key second so the order is total. Dictionary keys
            // are unique, so no two entries can tie on both — which is what
            // makes this order independent of the dictionary's own, and of
            // `sorted(by:)` not being stable.
            .sorted { ($0.label, $0.id) < ($1.label, $1.id) }
    }
}

// MARK: - State

/// What the Experimental CV Lab workspace should be showing.
///
/// `.unsupported` is the only reachable state today: the Tower has no module
/// container (V0.8) and Experimental CV Lab is the module that would run in it
/// (V0.9). Everything else exists so the workspace is written once against the
/// full lifecycle.
enum ExperimentalCVState: Equatable, Sendable {
    /// No Tower-side experiment runner. Carries the reason.
    case unsupported(reason: String)
    /// A runner exists. `available` is what the Tower declared — possibly
    /// empty, which is a different and equally honest answer from "cannot run
    /// experiments at all".
    case idle(available: [CVExperiment])
    /// An experiment has been requested and has not started reporting.
    case starting(CVExperiment)
    /// Running, with whatever partial results have arrived.
    case running(CVExperimentRun)
    /// Finished. Results are final.
    case completed(CVExperimentRun)
    case failed(CartridgeFailure)

    /// The run to draw results from, when there is one.
    var run: CVExperimentRun? {
        switch self {
        case .running(let run), .completed(let run): return run
        case .unsupported, .idle, .starting, .failed: return nil
        }
    }

    /// Whether an experiment is executing on the Tower right now.
    var isRunning: Bool {
        if case .running = self { return true }
        return false
    }

    var phase: CartridgePhase {
        switch self {
        case .unsupported: return .unsupported
        case .idle: return .idle
        case .starting: return .waiting
        case .running: return .live
        case .completed: return .settled
        case .failed: return .failed
        }
    }
}
