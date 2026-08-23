//
//  StatusPill.swift
//  Glasses
//

import SwiftUI

/// The health of one stage of the pipeline.
///
/// Every case pairs a tint with a distinct SF Symbol so status is never
/// communicated by colour alone.
enum StatusLevel {
    case ok
    case working
    case idle
    case problem

    var tint: Color {
        switch self {
        case .ok: return .green
        case .working: return .orange
        case .idle: return .secondary
        case .problem: return .red
        }
    }

    var symbol: String {
        switch self {
        case .ok: return "checkmark.circle.fill"
        case .working: return "clock.fill"
        case .idle: return "circle.dashed"
        case .problem: return "exclamationmark.triangle.fill"
        }
    }
}

/// One stage of the Glasses → Phone → Tower pipeline.
struct StatusPill: View {
    let title: String
    let value: String
    let level: StatusLevel

    @Environment(\.accessibilityDifferentiateWithoutColor) private var differentiateWithoutColor

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: level.symbol)
                .font(.title3)
                .foregroundStyle(differentiateWithoutColor ? Color.primary : level.tint)
                .symbolRenderingMode(.hierarchical)

            Text(title)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)

            Text(value)
                .font(.footnote.weight(.semibold))
                .multilineTextAlignment(.center)
                .minimumScaleFactor(0.8)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 14)
        .padding(.horizontal, 8)
        // Paired with the grouped page background so the pill reads as a
        // raised card in light mode and an elevated surface in dark mode.
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 14))
        .accessibilityElement(children: .combine)
        .accessibilityLabel(title)
        .accessibilityValue(value)
    }
}

#Preview {
    HStack(spacing: 10) {
        StatusPill(title: "Glasses", value: "Registered", level: .ok)
        StatusPill(title: "Camera", value: "Streaming", level: .ok)
        StatusPill(title: "Tower", value: "Offline", level: .idle)
    }
    .padding()
}
