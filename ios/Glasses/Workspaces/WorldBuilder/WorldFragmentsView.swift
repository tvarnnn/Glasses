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

    /// Whether the Tower's geometry reflects every keyframe it has accepted.
    ///
    /// A `var` with a default so the memberwise initialiser keeps working for
    /// the empty and cleared cases, which have no manifest to ask.
    var isCurrent: Bool = true

    /// Only resolved segments with real bounds can be drawn. A resolved
    /// segment with no bounds is incoherent and is refused rather than framed
    /// by guess.
    ///
    /// The filter decides membership; `ranked` decides only the order they are
    /// read in. The two are kept separate on purpose — see `ranked` — so that
    /// a change to display order can never quietly change which fragments the
    /// grid shows, or what `unresolvedCount` says about the rest.
    var fragments: [WorldSegmentSummary] {
        Self.ranked(
            segments.filter { $0.resolutionState == .resolved && $0.bounds != nil }
        )
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

    /// Said out loud when the fragments on screen are real but behind. Not a
    /// warning and not an error state: the world is still being built, and
    /// this is what "still building" looks like from here.
    var buildingNote: String? {
        if isCurrent { return nil }
        return "The Tower is still building this world, so these fragments "
            + "may be behind the newest frames."
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

extension WorldFragmentsModel {
    /// Puts the most-mapped fragments first, and does it totally.
    ///
    /// ## Why the grid needs an order at all
    ///
    /// Manifest order is capture order, which says when a segment was walked
    /// through and nothing about whether anything was recovered from it. That
    /// was survivable while a walk produced tens of segments. It stops being
    /// survivable as the Tower's segmentation gets finer — an unrestricted
    /// version of it takes a real walk to hundreds of segments — because then
    /// the parts of the room that actually reconstructed are scattered among
    /// the parts that were barely seen, and the reader has to scan the whole
    /// grid to find them.
    ///
    /// `point_count` is the Tower's own count of the points a segment
    /// recovered, so ordering by it puts the fragments with the most recovered
    /// geometry at the top. That is a statement about QUANTITY and nothing
    /// else: a fragment above another has more points in it, not a better or
    /// more trustworthy reconstruction. Nothing here, and nothing in the view,
    /// may say otherwise.
    ///
    /// ## Why the tie-break is not optional
    ///
    /// `sorted(by:)` is not documented as stable, so two segments with equal
    /// point counts could come back in either order — including a different
    /// order on the next refresh, which in a `ForEach` is cards visibly
    /// swapping places under the reader's finger for no reason they can see.
    /// `segmentIndex` is unique within a manifest, so breaking ties on it
    /// makes the order total: one manifest has exactly one display order.
    static func ranked(_ fragments: [WorldSegmentSummary]) -> [WorldSegmentSummary] {
        fragments.sorted { lhs, rhs in
            if lhs.pointCount != rhs.pointCount {
                return lhs.pointCount > rhs.pointCount
            }
            return lhs.segmentIndex < rhs.segmentIndex
        }
    }

    /// Maps a segment-local `(x, z)` into that segment's OWN tile.
    ///
    /// Lifted off the view deliberately: this is the single place a shared
    /// scale could leak in and composite two fragments that share no
    /// coordinate frame, so it is the one piece of layout that must be
    /// directly testable rather than merely structurally correct.
    static func projector(
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
            let project = WorldFragmentsModel.projector(bounds: bounds, size: size)

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
}

/// The gallery: known-but-unregistered fragments, plus honest accounts of the
/// two states that have no geometry to draw.
struct WorldFragmentsView: View {
    let model: WorldFragmentsModel
    let chunks: [String: WorldSegmentChunk]

    private var columns: [GridItem] { [GridItem(.adaptive(minimum: 140), spacing: 12)] }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.headline)
                .font(.headline)

            if let note = model.buildingNote {
                Text(note)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

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
