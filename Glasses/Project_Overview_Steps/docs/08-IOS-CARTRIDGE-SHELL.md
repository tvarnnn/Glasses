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

## What must NOT be done preemptively

- Do not invent a wire message for module selection. The protocol today is
  exactly `ping`, `pong`, `frame`, `frame_result`, `stream_start`,
  `stream_stop`. Adding keys to `stream_start` breaks
  `TowerClientTests.testStreamStartSendsExactPayloadOnce`.
- Do not add a module registry fetch to the iOS app.
- Do not make a cartridge row selectable until the Tower can actually honour
  the selection and report back which module is running.

## When the runtime arrives

The tray becomes the picker without needing to be re-laid out: add the real
status case, make the row a `Button`, and drive the active cartridge from
Tower-reported state rather than from local `@State`. Selection must reflect
what the Tower says is running, not what the phone last requested — a request
that the Tower rejects or has not yet applied must show as such.
