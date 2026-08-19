# Meta DAT Integration Boundary

## Rule

This file documents architectural expectations and verified DAT constraints. It is not a substitute for current Meta documentation.

Before writing DAT code, query the Meta Wearables MCP using `search_dat_docs`.

## Supported Architecture

DAT is the V1 interface between the custom iOS app and supported Meta wearable hardware.

```text
Module requirements
      |
Tower / iOS control logic
      |
GlassesConnection abstraction
      |
DAT adapter
      |
Meta wearable
```

Only the DAT adapter should understand Meta-specific APIs.

## Current Development Assumptions

Based on the project's August 2026 setup research:
- iOS is the chosen mobile platform.
- Development uses Xcode/Swift.
- Developer Mode permits unpublished development integrations.
- Physical Ray-Ban Meta Gen 2 hardware will be used later.
- Meta provides a Mock Device Kit for development/testing without physical hardware.
- The Meta Wearables MCP is configured for this repository.

Verify all version/API-specific details before implementation.

## Configuration Responsibilities

Keep distinct:
- Apple/iPhone Developer Mode and signing;
- Meta AI Developer Mode;
- Meta Wearables developer project configuration;
- DAT SDK/application integration;
- tower networking.

## Sensor Configuration

Modules may request sensor characteristics, but DAT configuration is applied by the DAT adapter/stream layer only after checking current supported values.

Do not hardcode assumed FPS/resolution/device capabilities into generic module code.

Do not design a generalized sensor-negotiation protocol before the actual supported DAT camera/stream configuration model is known — determine it via `search_dat_docs` first, then design the concrete mechanism against real constraints.

## Session Changes

Preferred behavior during module switches is to keep the wearable connection alive and pause processing. If current official DAT behavior requires restarting a stream/session to apply new settings, the adapter may do so.

The module should not know whether DAT paused, restarted a stream, or re-established a session.

## Documentation Update Procedure

When DAT implementation work reveals a stable constraint:
1. Verify with `search_dat_docs`.
2. Implement behind the DAT boundary.
3. Add a concise dated note here if it affects architecture or development workflow.
4. Avoid copying large portions of Meta documentation into this repository.

## Known Setup Blockers

- **Bundle ID.** The current Xcode bundle identifier (`tv.lloyd-icloud.com.Glasses`) contains a dash. Current DAT documentation (verified via `search_dat_docs`) states the iOS Bundle ID does not support the `-` character. This must be corrected before DAT app registration (V0.2). Not yet changed as of this documentation pass — see `03-ROADMAP.md` V0.2.

## Do Not

- Invent DAT API names.
- Spread Meta SDK calls throughout SwiftUI views.
- Put DAT code into tower modules.
- Treat current undocumented behavior as guaranteed.
- Make custom firmware a dependency of V1.
