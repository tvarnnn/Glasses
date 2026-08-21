//
//  Cartridge.swift
//  Glasses
//

import Foundation

/// How close a cartridge is to actually existing.
///
/// There is deliberately no `.available` / `.active` case. No module runtime
/// exists on either side yet: the Tower's module container is V0.8 and the
/// first module is V0.9 (docs/03-ROADMAP.md), and the iOS app is explicitly
/// forbidden from rendering a dynamic module list before V1.0
/// (docs/04-MODULE-SYSTEM.md). Adding an "available" state here before the
/// runtime exists would violate Rule 3, Truthful State Only
/// (docs/02-DEVELOPMENT-RULES.md).
enum CartridgeStatus: Equatable {
    /// First in line for implementation.
    case next
    /// Specified and scheduled, but not started.
    case planned
    /// A concept/specification seed only.
    case future

    var badge: String {
        switch self {
        case .next: return "Up next"
        case .planned: return "Planned"
        case .future: return "Future"
        }
    }
}

/// A module the platform intends to host. Static catalog data only — this type
/// carries no runtime behaviour and selecting one does nothing yet.
struct Cartridge: Identifiable, Equatable {
    let id: String
    let name: String
    let summary: String
    let status: CartridgeStatus
    /// Where this module is defined, so the drawer can cite a real source.
    let specPath: String
}

extension Cartridge {
    /// Names, ordering, and status are taken from the module specs in
    /// docs/modules/ and the roadmap phases in docs/03-ROADMAP.md. Nothing
    /// here is aspirational copy — if a module's spec says "future", it says
    /// "future".
    static let catalog: [Cartridge] = [
        Cartridge(
            id: "experimental-cv",
            name: "Experimental CV Lab",
            summary: "A sandbox for running and comparing vision models on the glasses feed.",
            status: .next,
            specPath: "docs/modules/EXPERIMENTAL-CV.md"
        ),
        Cartridge(
            id: "object-memory",
            name: "Object Memory",
            summary: "Remembers where objects were last seen.",
            status: .planned,
            specPath: "docs/modules/OBJECT-MEMORY.md"
        ),
        Cartridge(
            id: "visual-qa",
            name: "Visual Q&A",
            summary: "Answers questions about what you are looking at, including reading text.",
            status: .planned,
            specPath: "docs/modules/VISUAL-QA.md"
        ),
        Cartridge(
            id: "world-build",
            name: "World Build",
            summary: "Reconstructs a persistent spatial model of a space over time.",
            status: .future,
            specPath: "docs/modules/WORLD-BUILD.md"
        ),
        Cartridge(
            id: "accessibility",
            name: "Accessibility",
            summary: "Experimental assistive descriptions. Not a safety or navigation device.",
            status: .future,
            specPath: "docs/modules/ACCESSIBILITY.md"
        ),
        Cartridge(
            id: "environmental-memory",
            name: "Environmental Memory",
            summary: "Search the physical world you have already walked through.",
            status: .future,
            specPath: "docs/modules/ENVIRONMENTAL-MEMORY.md"
        ),
    ]
}
