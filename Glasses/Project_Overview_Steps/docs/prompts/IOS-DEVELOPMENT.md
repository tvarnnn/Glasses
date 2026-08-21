# Claude Prompt — iOS Development

```text
Work on the Glasses iOS control plane.

First read docs/prompts/START-HERE.md and follow it.

iOS responsibilities:
- Meta DAT adapter through GlassesConnection.
- Wearable connection/session state.
- Stream coordination.
- Tower connection state and transport.
- Module discovery/selection (a single fixed module initially; dynamic discovery once the registry is generalized — see `03-ROADMAP.md`).
- Generic module controls.
- Telemetry/status UI.

iOS is NOT the default home for heavy CV, AI inference, world modeling, or module persistence.

Keep SwiftUI views presentation-focused. Do not bury DAT/networking business logic directly inside ContentView or other views.

If this task touches DAT:
- query `search_dat_docs`;
- use current official APIs only;
- keep Meta-specific implementation behind the DAT adapter;
- update docs/05-DAT-INTEGRATION.md only for verified architectural constraints.

If this task touches tower communication:
- expose truthful disconnected/unavailable states;
- do not fabricate server responses;
- do not permanently hardcode the module catalog long-term (a single fixed module during the registry-of-one phase is expected; see `03-ROADMAP.md`);
- treat raw sensor data as local-first per `06-PRIVACY-DATA.md`; iOS does not route sensor data to third-party services.

Before editing, inspect the existing Swift architecture and explain the smallest proposed change. After editing, run the relevant tests and xcodebuild verification and report the exact result.
```
