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
| **`CartridgeWorkspace`** | Does *this app* ship a screen for it? | `Cartridge.workspace` | `worldBuilder` only; every other cartridge is `nil`. |

A row is tappable if and only if it has a workspace. Tapping changes which
workspace this app draws — local navigation, nothing more. It sends no message,
selects no module, and changes no Tower state. A cartridge with no workspace
keeps exactly its previous presentation: no `Button`, no `NavigationLink`, no
tap target.

This is why the World Builder row can be tappable while its badge still reads
"Future". The badge is about the Tower and remains true;
`ProductShellTests.testNoCartridgeClaimsToBeAvailable` is untouched and still
passing, and a new test asserts that having a workspace never promotes a
cartridge's status.

The workspace itself then carries the burden of saying what is not real. World
Builder's does: the Tower cannot build a world, so its world panel says so and
its primary control is labelled for what it actually does.

**A button may use a module's verb only once the Tower can perform that verb.**
"Start capture" is honest today because frames really do stream. "Start mapping"
would not be, because nothing maps. A verb-labelled primary button is the
strongest readiness claim a UI can make, and it must not outrun the runtime.
When mapping exists, the label changes — and that change is the announcement.

## What must NOT be done preemptively

- Do not invent a wire message for module selection. The protocol today is
  exactly `ping`, `pong`, `frame`, `frame_result`, `stream_start`,
  `stream_stop`. Adding keys to `stream_start` breaks
  `TowerClientTests.testStreamStartSendsExactPayloadOnce`.
- Do not add a module registry fetch to the iOS app.
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
