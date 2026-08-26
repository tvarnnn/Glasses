//
//  CartridgeClients.swift
//  Glasses
//

import Foundation

/// The four cartridge clients, owned above the workspace that uses them.
///
/// ## Why these do not live in the workspace views
///
/// A workspace's `@StateObject` view model is destroyed when the cartridge
/// changes. That is fine for a view model — it holds nothing real. It is
/// **not** fine for a client: a Tower-backed one will hold a subscription to
/// the connection and whatever it has accumulated — a partly-built world, a
/// live set of scene tracks, a query result. Destroying that on a cartridge
/// switch loses work and, worse, tears down a subscription the user did not ask
/// to end.
///
/// The Product Shell V2 handoff §11 states the rule this follows:
///
/// > Anything that must *outlive* the workspace (accumulated geometry, an
/// > object-memory buffer) belongs on `ProjectManager`, not in a view's
/// > `@StateObject`. A workspace-owned `@StateObject` is destroyed when the
/// > switch changes — harmless today because World Builder has no durable
/// > state, and a real bug the moment one does.
///
/// The clients hold nothing durable *today*, so this container costs nothing
/// now. It exists now anyway, because the alternative — a default argument on
/// each view model making `UnavailableFooClient()` constructible at the point
/// of use — would make the wrong wiring the path of least resistance on exactly
/// the day the right wiring starts to matter.
///
/// ## What this is not
///
/// It is not a registry, not a plugin host, and not a lookup by cartridge id.
/// Four `let`s, resolved at compile time. Adding a `client(for: CartridgeWorkspace)`
/// accessor would be the first step toward the dynamic module discovery
/// `docs/04-MODULE-SYSTEM.md` forbids before V1.0.
///
/// ## Runtime ownership
///
/// A container, not a manager. It starts nothing, connects to nothing, and owns
/// no transport — the clients it holds are stateless constants. When a
/// Tower-backed client arrives it will be constructed here with whatever it
/// needs, from the one place that already owns the connection.
@MainActor
final class CartridgeClients {
    let worldBuilder: any WorldBuilderClient
    let experimentalCV: any ExperimentalCVClient
    let documentMemory: any DocumentMemoryClient
    let sceneUnderstanding: any SceneUnderstandingClient
    /// The one client whose default is **not** an unavailable stub.
    ///
    /// Object Memory's Tower half exists and answers over HTTP, and its client
    /// discovers that by asking rather than by being told over the socket — so
    /// there is no declaration to wait for and nothing for a stub to stand in
    /// for. Constructed here rather than in the workspace because an answer
    /// must survive a cartridge switch, which destroys the view's
    /// `@StateObject`.
    ///
    /// It opens nothing on construction. No request is made until a person
    /// asks a question.
    let objectMemory: any ObjectMemoryClient

    /// Defaults are the unavailable clients, which is the whole truth of the
    /// current system for four of the five. Injection points exist so a test
    /// can substitute one without reaching through `ProjectManager`.
    init(
        worldBuilder: (any WorldBuilderClient)? = nil,
        experimentalCV: (any ExperimentalCVClient)? = nil,
        documentMemory: (any DocumentMemoryClient)? = nil,
        sceneUnderstanding: (any SceneUnderstandingClient)? = nil,
        objectMemory: (any ObjectMemoryClient)? = nil
    ) {
        self.worldBuilder = worldBuilder ?? UnavailableWorldBuilderClient()
        self.experimentalCV = experimentalCV ?? UnavailableExperimentalCVClient()
        self.documentMemory = documentMemory ?? UnavailableDocumentMemoryClient()
        self.sceneUnderstanding = sceneUnderstanding ?? UnavailableSceneUnderstandingClient()
        self.objectMemory = objectMemory ?? TowerObjectMemoryClient()
    }
}
