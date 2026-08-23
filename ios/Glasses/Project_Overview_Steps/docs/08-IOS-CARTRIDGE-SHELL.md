# 08 — iOS Cartridge Shell

Status: **visual shell only.** No module selection protocol exists, on either
side. This document records what the shell is for and what it is deliberately
not, so the next person does not mistake it for an unfinished feature.

## What exists today

`Glasses/Cartridges/Cartridge.swift` holds a static catalog of the modules
described in `docs/modules/`. `Glasses/Views/CartridgeDrawerView.swift`
renders it as a read-only tray, reachable from the dashboard toolbar.

Every row is informational. There is no `Button`, no `NavigationLink`, and no
tap target, because there is nothing to select:

- The Tower has no module container yet (V0.8, `03-ROADMAP.md`).
- The first module does not exist yet (V0.9).
- The iOS app must not render a *dynamic* module list before V1.0
  (`04-MODULE-SYSTEM.md`), and must not build discovery speculatively.

`CartridgeStatus` therefore has no `available` or `active` case. Adding one
before the runtime exists would violate Rule 3, Truthful State Only
(`02-DEVELOPMENT-RULES.md`). `GlassesTests/ProductShellTests.swift` asserts
this, so the constraint fails loudly rather than drifting.

(Rows are no longer uniformly unselectable — see "Two axes" below — but the
constraint this paragraph describes is unchanged.)

## The intended future relationship

```
iOS cartridge tray
    │  user selects a cartridge
    ▼
cartridge selection command      ← does not exist yet
    │  over the existing WebSocket
    ▼
Tower
    │
    ▼
ModuleContainer                  ← V0.8
    │  routes frames to exactly one active module
    ▼
selected Tower module            ← V0.9 onward
```

Heavy CV/AI work stays Tower-side. The iPhone remains the glasses interface,
the cartridge selector, the session controller, and the diagnostics surface.
There is no iOS module execution framework and should not be one.

## Two axes, added with Product Shell V2

The rule above — no selectable rows — was written when selecting a cartridge
could only have meant "run this module on the Tower". That is still forbidden.
But it conflated two different facts about two different machines, and the shell
now keeps them apart:

| | Question | Where it lives | Today |
|---|---|---|---|
| **`CartridgeStatus`** | Where is this *module* on the Tower roadmap? | `Cartridge.status` | `next` / `planned` / `future`. Still **no** `available` or `active` case. |
| **`CartridgeWorkspace`** | Does *this app* ship a screen for it? | `Cartridge.workspace` | `worldBuilder`, `experimentalCV`, `documentMemory`, `sceneUnderstanding`. |

A row is tappable if and only if it has a workspace. Tapping changes which
workspace this app draws — local navigation, nothing more. It sends no message,
selects no module, and changes no Tower state. A cartridge with no workspace
keeps exactly its previous presentation: no `Button`, no `NavigationLink`, no
tap target.

As of the cartridge-integration pass there are **four** workspaces — World
Builder, Experimental CV Lab, Document Memory, Scene Understanding — and the
rule is unchanged. Four openable rows still select nothing on the Tower, because
there is still no message with which to select anything.

This is why the World Builder row can be tappable while its badge still reads
"Future". The badge is about the Tower and remains true;
`ProductShellTests.testNoCartridgeClaimsToBeAvailable` is untouched and still
passing, and a test asserts that having a workspace never promotes a cartridge's
status.

That test was **strengthened** during the cartridge-integration pass rather than
relaxed. It used to assert, among other things, that the `.next` cartridge had no
workspace — which held only because Experimental CV Lab happened to be the one
cartridge with a roadmap position and no screen. It now pins the *entire*
catalog's id-to-status map against `03-ROADMAP.md`, which catches a drift on any
cartridge rather than on one, and fails loudly if a cartridge is added without a
deliberate decision about its status.

The workspace itself then carries the burden of saying what is not real. World
Builder's does: the Tower cannot build a world, so its world panel says so and
its primary control is labelled for what it actually does.

**A button may use a module's verb only once the Tower can perform that verb.**
"Start capture" is honest today because frames really do stream. "Start mapping"
would not be, because nothing maps. A verb-labelled primary button is the
strongest readiness claim a UI can make, and it must not outrun the runtime.
When mapping exists, the label changes — and that change is the announcement.

## The client layer, added with cartridge integration

Workspaces now sit on a small shared client layer in
`Glasses/Cartridges/Integration/`. It exists because four screens with almost
nothing in common turned out to share exactly one question — *may this cartridge
be used, and if not, why not* — and answering it four times would produce four
answers that drift.

```text
App shell (ContentView)
    │  one switch over CartridgeWorkspace
    ▼
Workspace view                     ← its own file, its own layout
    │  @StateObject, holds no runtime references
    ▼
Cartridge view model               ← publishes state, records refusals
    │
    ▼
Cartridge client protocol          ← cartridge-specific interaction shape
    │  + CartridgeClient           ← the one shared question
    ▼
TowerCapabilities                  ← what the Tower has declared: nothing
```

What is shared, and why each earns its place:

| Type | Shared because |
|---|---|
| `CartridgePhase` | a payload-free projection of each cartridge's own state, so one panel and one table-driven test cover all four |
| `CartridgeAvailability` | all four have the same four answers, and the *precedence* between them must be decided once |
| `CartridgeContract` | an opaque identifier; equality only, no version ordering assumed |
| `CartridgeFailure` | all four fail the same ways, and Rule 3 requires failure to be reachable |
| `CartridgeClient` / `TowerCapabilities` | "the Tower declares nothing" is one fact and belongs in one file |
| `WorldScaleSemantics`, `ObservationProvenance`, `ObservationTime`, `ObservedDuration` | platform-wide epistemic rules (Rule 16), needed by 2+ cartridges each |
| `RedactionState` / `VisualArtifactState` | the privacy display rule, needed wherever imagery is shown |
| `CartridgeStatePanel` | one wording for the one fact all four currently report |

What is **not** shared, deliberately: the workspaces themselves, the domain
models, and the interaction shape. World Builder pushes a continuously current
state; Experimental CV Lab takes a command and reports progress; Document Memory
answers point queries; Scene Understanding publishes a changing set. A generic
`fetch<Request, Response>` over those four would be the plugin framework
`04-MODULE-SYSTEM.md` and Rule 10 exist to prevent.

**The clients are not transport.** None of them holds a socket, and none can
send anything — `TowerClientTests.testCartridgeViewModelsSendNothingToTheTower`
asserts that against a real connection.

## What must NOT be done preemptively

- Do not invent a wire message for module selection. The protocol today is
  exactly `ping`, `pong`, `frame`, `frame_result`, `stream_start`,
  `stream_stop`. Adding keys to `stream_start` breaks
  `TowerClientTests.testStreamStartSendsExactPayloadOnce`.
- Do not add a module registry fetch to the iOS app. `TowerCapabilities.declared`
  is a **local table that is empty**, not a request that returns empty. It
  becomes a cache of a real declaration when one exists; it must not become a
  discovery call before V1.0.
- Do not let a cartridge row's *selection* imply anything about the Tower. A row
  may open a workspace this app ships (see "Two axes"), but until the Tower can
  honour a selection and report back which module is running, the active
  cartridge is a fact about the phone only, and nothing may present it
  otherwise.

## When the runtime arrives

The tray becomes the picker without needing to be re-laid out: add the real
status case, make the row a `Button`, and drive the active cartridge from
Tower-reported state rather than from local `@State`. Selection must reflect
what the Tower says is running, not what the phone last requested — a request
that the Tower rejects or has not yet applied must show as such.
