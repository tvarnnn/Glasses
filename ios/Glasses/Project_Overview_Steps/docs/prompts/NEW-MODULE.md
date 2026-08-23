# Claude Prompt — Create a New Module

```text
Design or implement a new Glasses tower module.

First read:
- docs/prompts/START-HERE.md
- docs/04-MODULE-SYSTEM.md
- docs/06-PRIVACY-DATA.md
- the module's specification under docs/modules/

If no module specification exists, do not jump directly into implementation. Create/propose a focused specification covering:
- purpose and user outcome;
- required sensor inputs;
- preferred sensor profile;
- processing pipeline;
- required models/resources;
- outputs/feedback;
- module-owned persistence;
- settings;
- failure behavior;
- measurable success criteria;
- privacy/safety considerations;
- data behavior declaration (what is persisted, raw vs. derived data, retention, purge capability, third-party transmission — per `06-PRIVACY-DATA.md` and `04-MODULE-SYSTEM.md`).

The module must not:
- call Meta DAT directly;
- assume it owns the iPhone UI;
- assume another major module runs concurrently;
- write unrelated data into another module;
- process observations before READY;
- retain GPU resources after unload without an explicit shared-cache design.

A normal tower-only module must be discoverable through the tower registry without requiring a new iOS build.

Before coding, identify the module contract currently implemented in the repository and conform to it. If the docs and code differ, report the conflict rather than inventing a third interface.

After implementation, test module lifecycle, resource cleanup, persistence behavior, and failure states relevant to the change.
```
