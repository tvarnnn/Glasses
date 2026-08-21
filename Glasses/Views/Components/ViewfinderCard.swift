//
//  ViewfinderCard.swift
//  Glasses
//

// `CapturedFrame` and the whole camera path are DEBUG-only in the model
// (Glasses/GlassesConnection.swift). This entire file is gated to match, so no
// control ever crosses the conditional boundary.
#if DEBUG

import SwiftUI

/// Shows the most recent frame decoded from the glasses.
///
/// This renders `GlassesConnection.latestCapturedFrame`, which the model
/// samples down to `FrameRateGate.towerTargetFPS` — the same frames that go to
/// the Tower, so what you see is what was sent. It deliberately does not open
/// its own camera feed or change that cadence.
///
/// A new `UIImage` identity per frame defeats SwiftUI's image caching, so each
/// update is a fresh decode composited under two `.ultraThinMaterial`
/// overlays. That is ordinary video-preview cost at this rate, but it is the
/// first thing to simplify if the send rate is raised much further.
struct ViewfinderCard: View {
    let frame: CapturedFrame?
    let isStreaming: Bool
    /// Why there is nothing to show yet, in plain language.
    let placeholderReason: String

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 18)
                .fill(Color(.secondarySystemGroupedBackground))

            if let frame {
                Image(uiImage: frame.image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .accessibilityLabel("Latest frame from the glasses camera")
            } else {
                placeholder
            }
        }
        // Compact until there is something to look at, so an idle dashboard
        // isn't dominated by an empty rectangle.
        .frame(height: frame == nil ? 150 : 260)
        .clipShape(.rect(cornerRadius: 18))
        .overlay(alignment: .topLeading) {
            if isStreaming { liveBadge.padding(12) }
        }
        .overlay(alignment: .bottomTrailing) {
            if let frame {
                Text("\(frame.width) × \(frame.height)")
                    .font(.caption2.weight(.medium).monospacedDigit())
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(.ultraThinMaterial, in: .capsule)
                    .padding(12)
            }
        }
    }

    private var placeholder: some View {
        VStack(spacing: 10) {
            Image(systemName: "eyeglasses")
                .font(.system(size: 40))
                .foregroundStyle(.tertiary)
            Text(placeholderReason)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
        .accessibilityElement(children: .combine)
    }

    private var liveBadge: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(.red)
                .frame(width: 7, height: 7)
                .opacity(reduceMotion ? 1 : 0.9)
            Text("LIVE")
                .font(.caption2.weight(.bold))
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(.ultraThinMaterial, in: .capsule)
        .accessibilityLabel("Live")
    }
}

#Preview("Empty") {
    ViewfinderCard(
        frame: nil,
        isStreaming: false,
        placeholderReason: "Start a session to see what the glasses see."
    )
    .padding()
}

#endif
