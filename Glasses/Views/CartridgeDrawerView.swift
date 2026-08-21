//
//  CartridgeDrawerView.swift
//  Glasses
//

import SwiftUI

/// The cartridge tray: the visual shell for the module system.
///
/// Presentation only. Nothing here is selectable, because nothing is
/// selectable yet — the Tower has no module container (V0.8) and no module
/// (V0.9), and the iOS app must not render a dynamic module list before V1.0
/// (docs/04-MODULE-SYSTEM.md). When module selection becomes real, this view
/// becomes the picker without needing to be re-laid out.
struct CartridgeDrawerView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(Cartridge.catalog) { cartridge in
                        CartridgeRow(cartridge: cartridge)
                    }
                } header: {
                    Text("Modules")
                } footer: {
                    Text("No module runtime exists yet. The Tower currently runs a fixed frame handler, so none of these can be selected. The first module arrives with the Tower's module container.")
                        .padding(.top, 4)
                }
            }
            .navigationTitle("Cartridges")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

private struct CartridgeRow: View {
    let cartridge: Cartridge

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(cartridge.name)
                    .font(.body.weight(.medium))
                Text(cartridge.summary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 8)

            Text(cartridge.status.badge)
                .font(.caption2.weight(.semibold))
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color(.tertiarySystemFill), in: .capsule)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
        // Unselectable by construction: no Button, no NavigationLink, no tap
        // target. The row is informational until a real module runtime exists.
        .accessibilityElement(children: .combine)
        .accessibilityHint("Not yet available")
    }
}

#Preview {
    CartridgeDrawerView()
}
