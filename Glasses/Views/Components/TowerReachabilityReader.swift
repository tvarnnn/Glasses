//
//  TowerReachabilityReader.swift
//  Glasses
//

import SwiftUI

/// Observes the Tower connection and hands a workspace one `Bool`.
///
/// ## The dependency this exists to remove
///
/// A cartridge workspace needs to know whether the Tower is reachable. The
/// obvious way to give it that is an `@ObservedObject var tower: TowerClient` —
/// and that is a dead dependency with a real cost.
///
/// `TowerClient` publishes `frameResultCount` and `latestFrameResult` **once per
/// reply**, at the ~12 Hz target rate while a session is streaming. Any view
/// observing it is invalidated at that rate. And leaving a workspace does not
/// stop capture (that is deliberate — see the Product Shell V2 handoff §8), so
/// "start capture in World Builder, then look at Scene Understanding" is an
/// ordinary path, not a corner case. The three cartridge workspaces with no
/// capture control would have been re-evaluating at reply rate to read a value
/// that changes almost never — and that cost lands on the main actor, which is
/// the actor the sender's send-window completions hop back to in order to
/// release their slots.
///
/// Product Shell V2 removed `ProjectManager`'s `objectWillChange` fan-in for
/// exactly this reason, and its own review caught a dead `tower` dependency
/// once already. This is the same defect, and the same fix: observe the object
/// in the smallest thing that has to, and pass the *fact* down.
///
/// The workspace below receives a `Bool`. When only `frameResultCount` changed,
/// that `Bool` is unchanged, and SwiftUI can skip re-running the workspace's
/// body rather than being unable to tell.
///
/// ## Runtime ownership
///
/// Observes. Owns nothing, constructs nothing, sends nothing.
struct TowerReachabilityReader<Content: View>: View {
    @ObservedObject var tower: TowerClient

    /// Receives `true` only for a genuinely open connection. `.connecting` is
    /// not reachable — a cartridge that treated it as reachable would make a
    /// request that cannot be sent.
    @ViewBuilder var content: (Bool) -> Content

    var body: some View {
        content(tower.status == .online)
    }
}
