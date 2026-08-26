//
//  CartridgeDrawerView.swift
//  Glasses
//

import SwiftUI

/// The cartridge tray: the shell's workspace picker.
///
/// ## What selecting a cartridge does, and does not do
///
/// Choosing a cartridge here changes **which workspace this app shows**. It
/// sends nothing to the Tower, selects no module there, and changes no Tower
/// state — there is no module-selection message in the protocol, and inventing
/// one is forbidden (docs/08-IOS-CARTRIDGE-SHELL.md). The Tower's vocabulary is
/// still exactly `ping`, `pong`, `frame`, `frame_result`, `stream_start`,
/// `stream_stop`.
///
/// That is why a row can be tappable while its badge still reads "Future".
/// The badge describes the *module's* position on the Tower roadmap; being
/// tappable describes whether *this app* ships a screen for it. Only cartridges
/// with a workspace are tappable — the rest stay exactly as they were, with no
/// `Button`, no `NavigationLink` and no tap target, because for them there
/// genuinely is nothing to open.
///
/// When the Tower can run modules, the active cartridge must be driven by what
/// the Tower reports is running, not by what was tapped here.
struct CartridgeDrawerView: View {
    @Binding var selectedCartridgeID: String

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button {
                        selectedCartridgeID = ""
                        dismiss()
                    } label: {
                        HomeRow(isSelected: selectedCartridgeID.isEmpty)
                    }
                    .buttonStyle(.plain)
                }

                Section {
                    ForEach(Cartridge.catalog) { cartridge in
                        if cartridge.workspace != nil {
                            Button {
                                selectedCartridgeID = cartridge.id
                                dismiss()
                            } label: {
                                CartridgeRow(
                                    cartridge: cartridge,
                                    isSelected: selectedCartridgeID == cartridge.id
                                )
                            }
                            .buttonStyle(.plain)
                        } else {
                            CartridgeRow(cartridge: cartridge, isSelected: false)
                        }
                    }
                } header: {
                    Text("Modules")
                } footer: {
                    Text("Opening a cartridge changes this app's workspace. It does not start anything on the Tower — the Tower chooses what it runs at startup and this app cannot ask it for anything else, so every badge below still reflects the roadmap rather than something you can run.")
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

private struct HomeRow: View {
    let isSelected: Bool

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Home")
                    .font(.body.weight(.medium))
                Text("Infrastructure status and a plain capture session.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            if isSelected {
                Image(systemName: "checkmark")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(.tint)
                    .accessibilityHidden(true)
            }
        }
        .padding(.vertical, 4)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
        // Only `.isSelected`. The row is already wrapped in a `Button`, which
        // supplies the button trait; adding it here makes VoiceOver say it twice.
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

private struct CartridgeRow: View {
    let cartridge: Cartridge
    let isSelected: Bool

    private var isOpenable: Bool { cartridge.workspace != nil }

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

            VStack(alignment: .trailing, spacing: 6) {
                Text(cartridge.status.badge)
                    .font(.caption2.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color(.tertiarySystemFill), in: .capsule)
                    .foregroundStyle(.secondary)

                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.body.weight(.semibold))
                        .foregroundStyle(.tint)
                        .accessibilityHidden(true)
                }
            }
        }
        .padding(.vertical, 4)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
        // Two different truths, so two different hints. An unopenable row is
        // informational exactly as it always was.
        .accessibilityHint(isOpenable ? "Opens this workspace" : "No workspace in this app yet")
        // An openable row is already inside a `Button`, so only selection needs
        // stating. A row without a workspace gets no traits at all, which is
        // what makes it read as informational rather than actionable.
        .accessibilityAddTraits(isOpenable && isSelected ? .isSelected : [])
    }
}

#Preview {
    CartridgeDrawerView(selectedCartridgeID: .constant(""))
}
