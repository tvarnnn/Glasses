# Glasses iOS — Product Shell V2 Autonomous Implementation Mission

> **HISTORICAL BRIEF — this mission has been carried out and superseded.**
> Kept as the record of what was asked for and under what constraints; it is not
> a live contract and its branch revisions are no longer current.
>
> Where it stands now: Product Shell V2 shipped as `319a23b`/`6a2d114` on
> `ios/product-shell-v2`, **which does not compile** — see that branch's handoff.
> The cartridge integration work on `ios/cartridge-integration` repaired it and
> built on top. Both, plus the sender line's Mac-validation commit `97aa79c`,
> are reconciled on **`ios/integration-candidate`**, which a Mac has validated:
> Debug and Release build, 225/225 tests pass across five runs with no flakes,
> and the Simulator smoke test passes. Physical hardware validation is still
> outstanding.
>
> The revisions named below (`ui/product-shell @ d9e513d`,
> `ios/send-window-investigation @ 7508db1`) were current when this was written.
> `ios/send-window-investigation` has since advanced to `97aa79c`, a docs-only
> commit recording that Mac validation. Resolve branch state from Git, as this
> document itself instructs, rather than from these lines.

You are the iOS/Mac-side engineering agent for the Glasses project.

You are CURRENTLY RUNNING ON WINDOWS.

There is NO Xcode compiler, Simulator, XCTest runtime, iOS SDK runtime, or
physical Apple/Meta hardware available on this machine.

You ARE authorized to:

INVESTIGATE
→ PLAN
→ USE SUBAGENTS
→ CHALLENGE THE DESIGN
→ IMPLEMENT SWIFT
→ WRITE TESTS
→ SOURCE-REVIEW
→ DOCUMENT
→ COMMIT
→ PUSH

You are NOT authorized to claim:

- Xcode compilation success
- XCTest execution success
- Simulator success
- physical iPhone success
- physical Ray-Ban success
- runtime DAT success

A separate Claude on the real Mac is the authoritative validation gate.

Do not attempt to install/emulate/build a macOS or Xcode environment on Windows.

==================================================
1. MISSION
==================================================

Build PRODUCT SHELL V2 for the Glasses iOS application.

The product is evolving from:

"a camera/debug dashboard"

into:

"a cartridge-driven operating shell for wearable capabilities."

The main application shell should remain stable.

Loading a cartridge changes the PRIMARY WORKSPACE.

Conceptually:

AppShell
│
├── persistent system state
│   ├── Glasses
│   ├── Tower
│   └── Camera
│
├── Cartridge Drawer
│
└── Active Workspace
    ├── HomeWorkspace
    ├── WorldBuilderWorkspace
    ├── ObjectMemoryWorkspace (future)
    ├── VisualQAWorkspace (future)
    ├── AccessibilityWorkspace (future)
    └── other future cartridge workspaces

The exact implementation does NOT need to match those names.

Challenge the architecture and improve it if there is a simpler or stronger
SwiftUI design.

==================================================
2. RECOVER CURRENT STATE FIRST
==================================================

Before changing anything:

1. git status
2. git branch --show-current
3. git log --oneline --decorate -15
4. inspect remotes
5. inspect branches
6. inspect staged/unstaged/untracked work
7. read relevant iOS architecture/docs
8. inspect current product-shell implementation
9. inspect cartridge models/drawer
10. inspect current connection/session ownership
11. inspect the Mac validation handoff
12. inspect existing tests

Do not rely on this prompt for facts the repository can establish.

Expected relevant history includes:

Known-good product-shell base:

ui/product-shell @ d9e513d

Sender candidate:

ios/send-window-investigation @ 7508db1

That sender candidate has subsequently been validated on a REAL MAC through:

- MetaWearablesDAT pinned exactly 0.9.0
- Debug BUILD SUCCEEDED
- Release BUILD SUCCEEDED
- 89/89 tests passing
- six repeated full-suite runs with zero flakes
- DAT thermal APIs compiling against real 0.9.0
- no new warnings relative to d9e513d

Physical Ray-Ban sender-performance validation is STILL outstanding.

Locate the updated handoff/commit rather than assuming 7508db1 remains HEAD.

DO NOT overwrite or regress the sender work.

==================================================
3. BRANCHING
==================================================

Do NOT work directly on:

main
ui/product-shell

Do NOT destroy:

ios/send-window-investigation

Determine the latest validated sender branch state from Git.

Create a new Product Shell V2 feature branch FROM the appropriate validated
sender state.

A reasonable name would be:

ios/product-shell-v2

but follow existing branch conventions if a better one exists.

The goal is for Product Shell V2 to include the validated sender implementation
rather than creating a parallel history that later requires painful
reconciliation.

Document the exact base commit.

==================================================
4. PRODUCT EXPERIENCE
==================================================

The desired startup experience is approximately:

LAUNCH APP
→ app begins establishing infrastructure connections
→ Glasses become Connected/Ready when possible
→ Tower becomes Connected/Ready when possible
→ Camera remains READY but INACTIVE
→ user chooses a cartridge
→ cartridge workspace loads
→ user explicitly starts that cartridge

The desired product should NOT require the user to manually perform a long
debug-style connection ritual every normal launch.

Investigate what can safely and truthfully be automated using existing runtime
APIs.

Do not invent capabilities.

==================================================
5. AUTO-CONNECTION
==================================================

Investigate and implement safe automatic connection behavior where existing
runtime contracts support it.

Desired direction:

APP LAUNCH
→ attempt/restore glasses readiness
→ attempt Tower connection
→ expose truthful connection state

Important:

AUTO-CONNECT DOES NOT MEAN AUTO-STREAM.

Launching the app must NOT automatically:

- start camera capture
- start Tower frame streaming
- activate a cartridge
- turn on the glasses camera merely because the app opened
- fabricate a connected state

Preserve user control and truthful state.

Connection failures must remain recoverable through UI controls.

Manual retry/disconnect should remain possible where appropriate.

Do not create reconnect loops that hammer services indefinitely.

Reuse existing reconnect/runtime behavior where possible rather than creating
competing connection managers.

==================================================
6. READY != ACTIVE
==================================================

This distinction is fundamental.

Possible conceptual states:

UNAVAILABLE
CONNECTING
READY
LOADED
ACTIVE
PAUSED
ERROR

Do not force these exact enum cases if existing state models differ.

But preserve the semantics:

CONNECTED != CAMERA ACTIVE

CARTRIDGE SELECTED != CARTRIDGE RUNNING

WORLD BUILDER LOADED != WORLD BUILDER MAPPING

The user should be able to browse/select a cartridge without activating the
camera.

Explicit user action should start camera-dependent cartridge behavior.

==================================================
7. HOME WORKSPACE
==================================================

When no cartridge is loaded, show a clean general Home workspace.

The Home workspace should communicate infrastructure readiness rather than
looking like an engineering dashboard.

Potential information:

- Glasses status
- Tower status
- Camera readiness
- currently loaded cartridge: none
- system/device health where truthful
- basic live preview ONLY when the camera is actually active for a legitimate
  reason

Do not fabricate metrics.

Do not show permanently dead panels.

Developer/debug controls must not dominate the product surface.

==================================================
8. CARTRIDGE DRAWER
==================================================

The existing cartridge drawer is currently primarily/read-only presentation.

Evolve it into the navigation/selection mechanism for cartridge workspaces.

The user should be able to:

open drawer
→ inspect cartridges
→ select an available/selectable cartridge
→ dismiss drawer
→ see the main workspace transform for that cartridge

Unavailable/future cartridges must remain truthful.

Do not make every planned cartridge appear functional.

Statuses such as:

planned
future
coming soon
experimental
available

should reflect actual project state.

Do not fabricate availability.

==================================================
9. WORLD BUILDER IS THE FIRST REAL WORKSPACE
==================================================

Tower Claude is concurrently implementing World Builder V1.

The desired future experience is:

select WORLD BUILDER
→ main UI transforms into World Builder workspace
→ World Builder is LOADED but not ACTIVE
→ user taps START MAPPING
→ camera activates
→ mapping session starts
→ user sees glasses imagery
→ user sees the virtual world building
→ user stops mapping
→ world remains inspectable/persisted

Tonight you are building the iOS PRESENTATION/WORKSPACE SIDE.

Do NOT invent Tower World Builder APIs that do not yet exist.

Tower Claude is independently determining:

- world/session model
- incremental update contract
- geometry representation
- persistence contract
- graph representation
- scale/calibration semantics

Therefore create a CLEAN ADAPTER/VIEW-MODEL BOUNDARY.

Use placeholder/unavailable state where backend contracts do not yet exist.

Do NOT create fake networking messages merely to make the UI appear complete.

==================================================
10. WORLD BUILDER WORKSPACE — VISUAL CONCEPT
==================================================

The World Builder workspace should make the product concept immediately
understandable.

The user should be able to see TWO complementary realities:

A. WHAT THE GLASSES SEE

B. WHAT THE TOWER IS BUILDING

Design a strong responsive layout around those ideas.

Potential conceptual structure:

WORLD BUILDER
[Ready / Mapping / Stopped / Error]

┌──────────────────────────────┐
│      GLASSES LIVE VIEW       │
│                              │
│ what the wearer currently    │
│ sees                         │
└──────────────────────────────┘

┌──────────────────────────────┐
│       VIRTUAL WORLD          │
│                              │
│ incremental spatial model    │
│ / geometry visualization     │
└──────────────────────────────┘

World:
Bedroom / Untitled World

Tracking:
Good / Limited / Lost / Unavailable

Keyframes:
37

Scale:
Relative / Metric / Uncalibrated / Unknown

Mapping:
Active

[ STOP MAPPING ]

This is conceptual.

Do not mechanically reproduce it if a better mobile layout exists.

Use SwiftUI-native interaction patterns.

==================================================
11. WORLD VISUALIZATION CONTAINER
==================================================

Create a clean presentation boundary capable of hosting the future live spatial
representation.

It must NOT pretend that geometry exists tonight if Tower has not supplied it.

The container should support states such as:

- unavailable
- waiting for Tower
- initializing
- receiving world updates
- rendering
- stopped/finalized
- error

If the existing platform already contains an appropriate rendering technology,
evaluate it.

Do not introduce a massive 3D framework without justification.

Do not build a fake animated point cloud simply to look impressive.

The UI architecture should be ready to accept a real future representation such
as:

- point cloud
- sparse landmarks
- trajectory
- graph-derived geometry
- another representation selected by Tower

Do not hard-code the UI to point clouds if Tower may choose something else.

==================================================
12. WORLD BUILDER METRICS
==================================================

World Builder should eventually display cartridge-specific information.

Candidate metrics:

- mapping state
- world name/ID
- mapping duration
- keyframes
- tracking quality
- coverage
- scale semantics
- calibration state
- world revision
- frame/source health
- geometry update status

ONLY expose metrics the current contracts can truthfully support.

For unavailable future values:

use explicit unavailable/waiting states.

Never invent numbers.

==================================================
13. CARTRIDGE-SPECIFIC WORKSPACES
==================================================

Design the presentation architecture so future cartridges can provide their own
workspace without turning SessionView/AppShell into a giant conditional.

AVOID architecture like:

if worldBuilder { ... }
else if objectMemory { ... }
else if accessibility { ... }
else if visualQA { ... }

spread throughout one enormous view.

Prefer clean composition.

A future cartridge should be able to provide:

- identity
- status
- workspace presentation
- primary controls
- cartridge-specific metrics/state
- potentially sensor requirements

without destabilizing unrelated cartridges.

Do not over-generalize before we have multiple real implementations.

==================================================
14. FUTURE EXAMPLES — DESIGN FOR, DO NOT IMPLEMENT
==================================================

Think through whether the workspace architecture can eventually support:

OBJECT MEMORY

Live view
Recent observations
Recognized objects
Last-seen information
Memory/search controls

ACCESSIBILITY

Live view
Scene interpretation
Immediate hazards
Spoken/visual guidance
Low-latency status

VISUAL Q&A

Current observation
Question input
Answer
Relevant visual context

ENVIRONMENTAL MEMORY

Scene changes
Location/context history
Temporal observations

These examples exist only to challenge the workspace abstraction.

DO NOT implement these cartridges.

==================================================
15. CARTRIDGE-SPECIFIC SENSOR BEHAVIOR
==================================================

Preserve the architecture principle:

each cartridge may consume the camera differently.

Do not globally encode assumptions such as:

- every cartridge wants 12 FPS
- every cartridge wants continuous capture
- every cartridge wants the same resolution
- every cartridge wants every selected frame
- every cartridge wants the same preprocessing

Future examples:

World Builder:
tracking + information-based keyframes

Accessibility:
freshness + minimum latency

Visual Q&A:
current high-quality observation

Object Memory:
semantic-change-driven observations

Tonight you do NOT need to solve full sensor-profile negotiation unless it is
clearly required.

But do not make UI/runtime decisions that prevent it.

==================================================
16. CAMERA PRIVACY / USER CONTROL
==================================================

Camera activation must remain explicit and truthful.

Selecting a cartridge must NOT secretly activate the camera.

Opening World Builder should result in something like:

WORLD BUILDER
READY

[ START MAPPING ]

Only START MAPPING should eventually trigger the active camera/mapping
lifecycle.

Likewise:

STOP MAPPING

must represent an actual stop request once backend wiring exists.

Do not fake successful stops/starts when no runtime contract exists.

==================================================
17. WORLD BUILDER STOPPED STATE
==================================================

After mapping stops, the World Builder workspace should conceptually transition
from:

LIVE MAPPING

to:

WORLD INSPECTION

The camera may stop while the generated world remains visible.

Design the workspace so the same cartridge can eventually support:

READY
→ MAPPING
→ FINALIZING
→ INSPECTING

without requiring a completely separate app screen.

Do not invent finalization behavior Tower has not implemented.

==================================================
18. PRODUCT SHELL PERSISTENCE
==================================================

Investigate whether cartridge selection should persist across ordinary UI
navigation/re-rendering.

Do not automatically reactivate a camera-dependent cartridge after process
launch merely because it was previously selected.

Safe conceptual behavior:

remember selected cartridge if appropriate

BUT

restore as LOADED/READY

NOT automatically ACTIVE.

User should explicitly resume camera-dependent behavior.

==================================================
19. DEVELOPER TOOLS
==================================================

Preserve existing MockDeviceKit/developer functionality.

It should remain outside the normal product surface.

Do not regress:

- required mock setup order
- local error alerts
- Debug-only behavior
- existing developer controls

Do not move debug functionality back onto Home.

==================================================
20. CURRENT LIVE VIEW
==================================================

The current product shell already supports live glasses imagery.

Preserve it.

Do not duplicate the underlying stream ownership merely because World Builder
also needs a preview.

There should be one coherent runtime source of truth.

World Builder's live preview should PRESENT the existing camera stream rather
than creating a second camera session.

==================================================
21. OBJECT GRAPH / SWIFTUI LIFETIME SAFETY
==================================================

Previous product-shell work specifically guarded against SwiftUI navigation or
sheet changes recreating runtime objects and killing the stream.

Preserve this invariant.

Critical runtime objects must NOT be recreated when:

- opening cartridge drawer
- selecting cartridge
- opening Developer Tools
- changing workspace
- navigating within a cartridge
- rendering live world updates

Review object ownership carefully.

The previous physical smoke-test requirement was:

GlassesConnection.init logs once per launch.

Do not introduce architecture that threatens this.

==================================================
22. EXISTING SENDER WORK
==================================================

Do not regress the recently validated sender implementation.

Known design includes:

- bounded send window
- latency-budget-derived capacity
- stall detection
- reconnect behavior
- sender telemetry
- device health

The physical FPS hypothesis is still awaiting real Ray-Ban validation.

UI changes must not alter sender semantics merely for presentation convenience.

If new UI requires runtime behavior changes:

keep them minimal,
justify them,
test them,
and flag them prominently for Mac validation.

==================================================
23. DEVICE HEALTH
==================================================

Existing work established that DAT 0.9.0 exposes glasses thermal information
but not glasses battery through the investigated API.

Do not fabricate battery.

Use truthful health information where useful.

Do not clutter every cartridge workspace with system telemetry.

Global device health belongs at the shell level unless a cartridge has a
specific reason to surface it.

==================================================
24. DESIGN QUALITY
==================================================

This should feel like a PRODUCT.

Not:

- a debug dashboard
- a raw list of enums
- a settings page
- a wall of metrics
- a developer console

Prioritize:

- clear hierarchy
- immediate understanding
- strong primary action
- truthful state
- minimal clutter
- smooth cartridge switching
- clear active/inactive distinction
- room for cartridge personality without fragmenting the app

Do not sacrifice architectural correctness for visual polish.

==================================================
25. CHALLENGE OUR UI IDEA
==================================================

The proposed model is:

persistent shell
+
cartridge-specific workspace.

This is a hypothesis.

Challenge it.

If there is a simpler or more idiomatic SwiftUI architecture that preserves:

- cartridge isolation
- persistent runtime ownership
- workspace specialization
- future extensibility
- privacy semantics

use it.

Likewise challenge:

- drawer interaction
- workspace switching
- layout
- metrics
- connection UX
- automatic startup behavior

Do not preserve a design merely because this prompt proposed it.

==================================================
26. SIMPLICITY RULE
==================================================

COMPLEXITY MUST EARN ITS PLACE.

Do not build a giant plugin UI framework for six cartridges that do not yet
exist.

We currently need:

HOME

and:

WORLD BUILDER

with enough architectural evidence that another workspace can be added cleanly.

If two clean concrete workspaces are sufficient to prove the pattern:

stop there.

Prefer SwiftUI composition over elaborate abstraction machinery.

==================================================
27. SUBAGENTS
==================================================

Use focused subagents where useful.

Suggested independent tracks:

A — PRODUCT/UX

Challenge the interaction model:
startup, drawer, loaded-vs-active, workspace transformation.

B — SWIFTUI ARCHITECTURE

Review:
state ownership, view composition, object lifetime, extensibility.

C — RUNTIME SAFETY

Audit:
auto-connect, stream ownership, camera privacy, sender invariants, reconnect
interactions.

D — TEST DESIGN

Identify:
state-machine, selection, persistence, connection, and regression tests that can
be written without physical hardware.

E — ADVERSARIAL REVIEW

After implementation, try to break:
object lifetime, privacy semantics, cartridge isolation, truthful state.

Do not create unnecessary agent swarms.

Do not let multiple agents concurrently edit the same files without
coordination.

Main agent reconciles all findings.

==================================================
28. TEST-DRIVEN IMPLEMENTATION
==================================================

Write tests where appropriate BEFORE or alongside implementation.

You cannot run Xcode tests on Windows.

That does NOT mean tests should not be written.

Prioritize testable presentation/state logic outside deeply coupled SwiftUI
rendering where reasonable.

Potential invariants:

- no cartridge selected → Home workspace
- selecting World Builder → World Builder loaded
- selecting does not imply active
- loaded World Builder can request Start
- stop returns to non-active World Builder state
- switching workspaces does not recreate runtime ownership
- unavailable cartridges cannot activate
- auto-connect does not auto-stream
- restored cartridge selection does not auto-activate
- connection failures remain recoverable
- future workspace addition does not require modifying unrelated workspace
  internals

Do not write fake tests that pass without exercising behavior.

==================================================
29. WINDOWS VERIFICATION
==================================================

You may perform:

- source inspection
- Git verification
- structural checks
- grep/static analysis
- documentation checks
- non-Xcode tests if genuinely executable and relevant

You may NOT claim:

BUILD SUCCEEDED

XCTEST PASSED

SIMULATOR VERIFIED

PHYSICAL DEVICE VERIFIED

Those belong to real Mac Claude.

==================================================
30. DO NOT INVENT WORLD BUILDER BACKEND CONTRACTS
==================================================

This is critical.

Tower Claude is concurrently implementing World Builder.

Do NOT assume message shapes like:

world_update
point_cloud
tracking_state

unless the current repository already defines them.

Instead create an adapter/protocol/view-model boundary representing the UI's
needs.

Document those needs.

Tomorrow we will reconcile:

Tower's ACTUAL contract

with:

iOS's presentation requirements.

The UI should be easy to wire once the real contract exists.

==================================================
31. HANDOFF DOCUMENT
==================================================

Create:

docs/agent-handoffs/product-shell-v2-handoff.md

or follow the repository's established handoff location/naming convention.

It must include:

- starting Git state
- branch/base
- mission
- recovered architecture
- UX decisions
- auto-connect design
- loaded-vs-active semantics
- cartridge selection architecture
- workspace architecture
- Home workspace
- World Builder workspace
- world visualization boundary
- backend assumptions deliberately NOT made
- shared state ownership
- camera ownership
- privacy semantics
- sender invariants preserved
- Developer Tools preservation
- files changed
- tests written
- tests NOT run
- expected compile risks
- exact Mac validation procedure
- exact physical regression procedure
- exact Tower contract information needed for final World Builder wiring
- known limitations
- future cartridge extension pattern

A fresh Mac Claude must be able to continue without this conversation.

==================================================
32. INDEPENDENT REVIEW
==================================================

Before finalizing, dispatch independent review.

Review specifically for:

- accidental camera auto-start
- cartridge selection accidentally implying activation
- duplicate stream ownership
- SwiftUI object recreation
- giant conditional workspace architecture
- premature abstractions
- fake World Builder data
- fabricated backend contracts
- broken Developer Tools
- sender regressions
- reconnection conflicts
- inaccessible manual recovery controls
- state that looks connected when it is not
- Release/Debug boundary mistakes

Fix justified findings.

==================================================
33. DEFINITION OF DONE ON WINDOWS
==================================================

This Windows implementation run is complete when:

1. Product Shell V2 architecture exists.

2. Home workspace exists.

3. Cartridge selection is functional at the presentation/state level.

4. Selecting World Builder changes the primary workspace.

5. Selection does NOT activate camera/mapping.

6. World Builder workspace has explicit Ready/Active/etc presentation semantics.

7. Existing live glasses preview can be presented in the World Builder
   workspace without duplicating stream ownership.

8. A truthful world-visualization container/boundary exists.

9. No fake Tower World Builder API was created.

10. Startup connection automation is implemented where safely supported.

11. Auto-connect does NOT auto-stream.

12. Manual recovery controls remain available.

13. Developer Tools remain isolated and preserved.

14. Runtime object ownership remains stable by design.

15. Sender behavior is not intentionally changed.

16. Tests for important new state logic are written.

17. Independent review is complete.

18. Justified review findings are fixed.

19. Documentation/handoff is complete.

20. Feature branch is pushed.

21. Working tree is clean.

==================================================
34. MAC VALIDATION REQUIRED AFTERWARD
==================================================

The real Mac Claude must later perform:

- inspect diff
- resolve packages
- Debug build
- run ALL pre-existing + new tests
- Release build
- inspect warnings against validated base
- Simulator UI smoke test
- verify Home
- verify cartridge drawer
- verify World Builder selection
- verify loaded != active
- verify Developer Tools
- verify object ownership
- physical iPhone test
- physical Ray-Ban test
- confirm auto-connect behavior
- confirm camera remains inactive until explicit Start
- confirm existing live view still works
- confirm sender telemetry still works
- confirm Stop works
- confirm navigation/workspace changes do not recreate GlassesConnection

Do not claim any of these tonight.

==================================================
35. HARD STOP
==================================================

After Product Shell V2 is implemented, reviewed, documented, committed, and
pushed:

STOP.

Do NOT:

- implement Tower World Builder
- invent Tower protocol messages
- implement Object Memory UI beyond generic extension groundwork
- implement Accessibility
- implement Visual Q&A
- redesign the entire app again
- alter the sender algorithm
- change the global 12 FPS policy
- start unrelated roadmap work

Leave us:

ONE strong cartridge-driven iOS shell

PLUS:

ONE strong World Builder workspace ready for the real Tower contract.

==================================================
36. FINAL REPORT
==================================================

Report:

1. Starting Git state
2. Base commit
3. Feature branch
4. Subagents used
5. UX architecture
6. Auto-connect behavior
7. Camera/privacy behavior
8. Loaded-vs-active semantics
9. Cartridge selection implementation
10. Workspace architecture
11. Home workspace
12. World Builder workspace
13. World visualization boundary
14. Existing live-view reuse
15. Runtime object ownership
16. Shared infrastructure introduced
17. Simpler alternatives considered
18. Decisions changed after review
19. Backend assumptions deliberately avoided
20. Developer Tools status
21. Sender invariants
22. Files changed
23. Tests written
24. What was actually verified on Windows
25. What was NOT verified
26. Review findings
27. Fixes
28. Known compile risks
29. Handoff path
30. Commit(s)
31. Final Git state
32. Exact MAC CLAUDE START HERE instructions

End with this exact truth:

"Product Shell V2 was implemented on Windows without Xcode and has NOT yet
been compiler-, Simulator-, or physical-device-validated."

Then STOP.