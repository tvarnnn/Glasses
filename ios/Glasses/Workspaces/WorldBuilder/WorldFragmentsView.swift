//
//  WorldFragmentsView.swift
//  Glasses
//

import SwiftUI

/// Layout decisions for the fragment gallery, kept out of the view so they can
/// be tested without rendering.
///
/// ## Why fragments and not a map
///
/// Every segment anchor the Tower produces sits at exactly the origin with
/// identity rotation, and per-segment scale disagrees by up to ~87x on a real
/// walk. Drawing them in one space would superimpose independent
/// reconstructions — geometry that looks like a room and means nothing.
/// `docs/modules/WORLD-BUILD.md` forbids exactly that.
///
/// So each fragment gets its own frame, its own scale, and its own box. When
/// the Tower learns to register segments, `registered` flips, they share a
/// frame, and this model merges them without the view changing.
struct WorldFragmentsModel: Equatable {
    let segments: [WorldSegmentSummary]

    /// Only resolved segments with real bounds can be drawn. A resolved
    /// segment with no bounds is incoherent and is refused rather than framed
    /// by guess.
    var fragments: [WorldSegmentSummary] {
        segments.filter { $0.resolutionState == .resolved && $0.bounds != nil }
    }

    /// Segments that hold keyframes and recovered nothing. Counted, never
    /// placed: we know reconstruction failed, not where.
    var unresolvedCount: Int {
        segments.filter { $0.resolutionState == .unresolved }.count
    }

    /// True once the Tower registers segments into one frame. False today.
    var hasSharedFrame: Bool {
        !segments.isEmpty && segments.allSatisfy(\.registered)
    }

    var headline: String {
        let count = fragments.count
        if count == 0 { return "Nothing mapped yet" }
        if hasSharedFrame { return "1 world" }
        return count == 1
            ? "1 fragment, not yet connected"
            : "\(count) fragments, not yet connected"
    }
}

/// One fragment, drawn top-down in its own frame.
///
/// Top-down `(x, z)` and not 3D because `up_axis` is `"unknown"` — a 3D view
/// would have to guess which way is up. SceneKit earns its weight once a floor
/// plane exists; until then this is both cheaper and more honest.
struct FragmentCanvas: View {
    let summary: WorldSegmentSummary
    let chunk: WorldSegmentChunk?

    var body: some View {
        Canvas { context, size in
            guard let chunk, let bounds = summary.bounds else { return }
            let project = projector(bounds: bounds, size: size)

            for point in chunk.points where point.count == 3 {
                let p = project(point[0], point[2])
                context.fill(
                    Path(ellipseIn: CGRect(x: p.x - 1, y: p.y - 1, width: 2, height: 2)),
                    with: .color(.secondary)
                )
            }

            // The camera path, broken wherever a pose was refused. A line
            // through the gap would assert motion that was never measured.
            var path = Path()
            var pendingMove = true
            for pose in chunk.poses {
                guard let t = pose.translation, t.count == 3 else {
                    pendingMove = true
                    continue
                }
                let p = project(t[0], t[2])
                if pendingMove {
                    path.move(to: p)
                    pendingMove = false
                } else {
                    path.addLine(to: p)
                }
            }
            context.stroke(path, with: .color(.accentColor), lineWidth: 1.5)
        }
        .background(Color.secondary.opacity(0.08))
    }

    /// Each fragment is framed to its OWN bounds. Fragments share no scale,
    /// and pretending otherwise is the fabrication this view exists to avoid.
    private func projector(
        bounds: WorldBounds, size: CGSize
    ) -> (Double, Double) -> CGPoint {
        let spanX = Swift.max(bounds.max[0] - bounds.min[0], 1e-6)
        let spanZ = Swift.max(bounds.max[2] - bounds.min[2], 1e-6)
        let scale = Swift.min(size.width / spanX, size.height / spanZ) * 0.9
        let offsetX = (size.width - spanX * scale) / 2
        let offsetZ = (size.height - spanZ * scale) / 2
        return { x, z in
            CGPoint(
                x: offsetX + (x - bounds.min[0]) * scale,
                y: offsetZ + (z - bounds.min[2]) * scale
            )
        }
    }
}

/// The gallery: known-but-unregistered fragments, plus honest accounts of the
/// two states that have no geometry to draw.
struct WorldFragmentsView: View {
    let model: WorldFragmentsModel
    let chunks: [String: WorldSegmentChunk]

    private let columns = [GridItem(.adaptive(minimum: 140), spacing: 12)]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.headline)
                .font(.headline)

            if model.fragments.isEmpty {
                // UNKNOWN: nothing has been mapped. Not an empty canvas,
                // which would read as an empty room.
                Text("The glasses have not mapped anything here yet.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(model.fragments, id: \.segmentIndex) { segment in
                        VStack(alignment: .leading, spacing: 4) {
                            FragmentCanvas(
                                summary: segment,
                                chunk: chunks[segment.contentHash]
                            )
                            .frame(height: 120)
                            .clipShape(RoundedRectangle(cornerRadius: 8))

                            Text("\(segment.pointCount) points")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            if let chunk = chunks[segment.contentHash], chunk.isSampled {
                                Text("showing \(chunk.pointsSent) of \(chunk.pointsTotal)")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            if model.unresolvedCount > 0 {
                // OBSERVED BUT UNRESOLVED. Deliberately not drawn: we know
                // reconstruction failed, not where it failed, and a region
                // would invent a location.
                Text("\(model.unresolvedCount) areas were seen but could not be reconstructed.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
