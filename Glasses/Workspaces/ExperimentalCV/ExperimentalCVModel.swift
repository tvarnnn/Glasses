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
/// and it is the only cartridge whose catalog status is `.next`. The temptation
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
