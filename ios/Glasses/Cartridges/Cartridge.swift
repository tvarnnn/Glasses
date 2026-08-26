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
nonisolated enum CartridgeStatus: Equatable {
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

/// A module the platform intends to host.
///
/// Static catalog data. `status` describes the module's position on the *Tower*
/// roadmap and carries no runtime behaviour; `workspace` describes whether
/// *this app* has a screen for it. See `CartridgeWorkspace` for why those are
/// deliberately independent.
struct Cartridge: Identifiable, Equatable {
    let id: String
    let name: String
    let summary: String
    let status: CartridgeStatus
    /// Where this module is defined, so the drawer can cite a real source.
    let specPath: String
    /// The workspace this app can open for the cartridge, or `nil` if the app
    /// has no screen for it — in which case its drawer row stays informational,
    /// exactly as every row was before workspaces existed.
    var workspace: CartridgeWorkspace? = nil
}

extension Cartridge {
    /// Names, ordering, and status are taken from the module specs in
    /// docs/modules/ and the roadmap phases in docs/03-ROADMAP.md. Nothing
    /// here is aspirational copy — if a module's spec says "future", it says
    /// "future".
    static let catalog: [Cartridge] = [
        // Module #1 on the roadmap, and now also a workspace. Its `status`
        // stays `.next` — the workspace is a screen this app ships, and the
        // Tower still has neither the module container (V0.8) nor the module
        // (V0.9). `CartridgeWorkspaceTests` pins every status in this catalog
        // against the roadmap precisely so that gaining a screen cannot drift
        // one of them.
        Cartridge(
            id: "experimental-cv",
            name: "Experimental CV Lab",
            summary: "A sandbox for running and comparing vision models on the glasses feed.",
            status: .next,
            specPath: "docs/modules/EXPERIMENTAL-CV.md",
            workspace: .experimentalCV
        ),
        // The summary used to read "Remembers where objects were last seen",
        // which is the claim the cartridge's own contract spends four sections
        // refusing. `spatial_ref` is null in every payload it can produce and
        // is actively nulled on read: nothing here knows where anything is.
        // The drawer row is the first sentence a person reads about this
        // module, so it is the first place the overclaim had to go.
        //
        // `status` stays `.planned`. The Tower serving two read-only routes is
        // not the module runtime arriving, and having a screen never promotes a
        // roadmap position — see `CartridgeWorkspace`.
        Cartridge(
            id: "object-memory",
            name: "Object Memory",
            summary: "Records that a category of thing was visible to the camera, and when.",
            status: .planned,
            specPath: "docs/modules/OBJECT-MEMORY.md",
            workspace: .objectMemory
        ),
        Cartridge(
            id: "visual-qa",
            name: "Visual Q&A",
            summary: "Answers questions about what the camera can see, including reading text.",
            status: .planned,
            specPath: "docs/modules/VISUAL-QA.md"
        ),
        // `status` stays `.future` even though this app ships a workspace,
        // because that is still where the *module* sits on the Tower roadmap —
        // the spec file is a concept seed and no Tower module runtime exists.
        // Having a workspace does not promote it, and the badge must keep
        // saying so.
        //
        // Named "World Builder" here, while the spec file it cites is titled
        // "World Build". Same module; the product surface and the Tower work
        // both use the longer name, and two names for one thing on screen would
        // be worse than the small mismatch with the document title.
        Cartridge(
            id: "world-build",
            name: "World Builder",
            summary: "Reconstructs a persistent spatial model of a space over time.",
            status: .future,
            specPath: "docs/modules/WORLD-BUILD.md",
            workspace: .worldBuilder
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
        // The two entries below are narrower first versions of modules already
        // in this catalog, not new ambitions. Environmental Memory's own spec
        // asks a first version to "choose one constrained memory type, such as
        // […] searchable OCR history", and Object Memory's pipeline produces
        // the live tracks Scene Understanding reads. Each cites its own concept
        // seed, which says what it takes from its parent and what it leaves
        // behind.
        //
        // Both are `.future`, like the modules they narrow: **the Tower has not
        // adopted either scope.** They exist in this catalog because this app
        // ships a workspace for each, which is a fact about the phone — the
        // same two-axis rule that lets World Builder be openable while its
        // badge reads "Future". docs/agent-handoffs/IOS-TO-TOWER.md is where
        // that distinction is put to the Tower explicitly.
        Cartridge(
            id: "document-memory",
            name: "Document Memory",
            summary: "Documents you passed, kept as text and summaries rather than as pictures.",
            status: .future,
            specPath: "docs/modules/DOCUMENT-MEMORY.md",
            workspace: .documentMemory
        ),
        Cartridge(
            id: "scene-understanding",
            name: "Scene Understanding",
            summary: "An anonymous read of how many people and objects the camera can see, and roughly where.",
            status: .future,
            specPath: "docs/modules/SCENE-UNDERSTANDING.md",
            workspace: .sceneUnderstanding
        ),
    ]
}
