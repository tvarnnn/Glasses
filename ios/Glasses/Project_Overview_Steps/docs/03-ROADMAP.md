# Roadmap

The roadmap is intentionally incremental. Complete and verify each milestone before expanding scope.

## Phase 0 — iOS Foundation

### V0.1 — Control Plane Skeleton (Complete)
- SwiftUI dashboard.
- `GlassesConnection` abstraction.
- `StreamManager`.
- `TowerClient`.
- `ProjectManager`.
- Real disconnected/offline/stopped states.
- Clean Xcode build.

Exit criterion: app builds and runs without fake functionality. **Met** — verified with an `xcodebuild` run against the iOS Simulator.

### V0.2 — DAT Development Environment
- Meta Wearables MCP verified.
- Current DAT iOS setup retrieved from official docs.
- Official DAT coding guidance installed if appropriate.
- Mock Device Kit setup understood.
- Required Meta project configuration documented.

Known blocker: the current Xcode bundle identifier (`tv.lloyd-icloud.com.Glasses`) contains a dash. Current DAT documentation (verified via `search_dat_docs`) states the iOS Bundle ID does not support the `-` character. This must be corrected before DAT app registration. See `05-DAT-INTEGRATION.md` — Known Setup Blockers.

Exit criterion: repository is ready to integrate DAT using current official APIs.

### V0.3 — Mock/Device Connection
- Connect through supported DAT flow.
- Expose real connection state through `GlassesConnection`.
- Test with Mock Device Kit when physical glasses are unavailable.

Exit criterion: app can establish a supported wearable session.

### V0.4 — Camera Into Swift
- Receive camera data through DAT.
- Display/inspect real frames.
- Start/stop correctly.

Exit criterion: real or simulated wearable camera frames reach the iOS application.

## Phase 1 — Tower Transport

### V0.5 — Minimal Tower Receiver
- Establish a small server on the Windows tower.
- Initial stack (pinned): Python, FastAPI, WebSockets for real-time frame transport, OpenCV, PyTorch, and CUDA when GPU acceleration is required. Do not introduce gRPC, C++, distributed infrastructure, message brokers, or container orchestration speculatively — revisit only if measurements expose a real limitation.
- LAN-only. No remote/internet exposure at this milestone — see Phase 1.5 for remote access.
- Secure development transport appropriate for a trusted local network (exact mechanism decided during implementation).
- iPhone discovers/connects to configured tower.
- Real online/unavailable state.

### V0.6 — First Frame to Tower
- Send one frame.
- Receive it.
- Process with OpenCV.
- Return a minimal acknowledgement/result.

### V0.7 — Sustained Streaming
Target experiment:
- approximately 504x896;
- approximately 15 FPS;
- 20–30 minute target session.

Measure actual FPS, dropped frames, latency, bandwidth, disconnects, battery behavior, thermal behavior, and tower utilization.

Do not claim targets as achieved until measured.

Backpressure policy: the pipeline must not accumulate an unbounded frame queue. Freshness generally matters more than processing every frame — when the tower/module cannot keep up, stale frames should normally be dropped rather than accumulating latency. Exact queue/drop mechanics are an implementation decision informed by these measurements, not a fixed constant.

Adaptive streaming (IDLE / TRACKING / HIGH_RATE style frame-rate adjustment, as originally sketched in the project brainstorm doc) is a candidate future optimization once V0.7 measurements exist. Do not implement adaptive streaming before this milestone produces real data to design it from.

## Phase 1.5 — Secure Remote Tower Access (Future Milestone)

Remote (non-LAN) tower access is a real project goal, not merely hypothetical — but it is explicitly deferred until the local pipeline (through V0.7) works reliably. This is a placeholder milestone; do not design the full implementation yet.

Target shape:

```text
Glasses -> iPhone -> cellular/remote network -> private secure connection -> home tower
```

Preferred approach: a private overlay/tunnel (e.g., Tailscale or WireGuard) rather than exposing the tower directly to the public internet.

Exit criterion (future): tower reachable from outside the LAN through an authenticated, encrypted, non-public-facing connection, with the same truthful online/unavailable state contract as local access.

## Phase 2 — Module Runtime

Sequencing note: build only the minimal module infrastructure required to run one real module. Generalize into a dynamic registry/discovery system only once a second production module gives real requirements to generalize against. Do not build the full dynamic plugin system speculatively.

### V0.8 — Minimal Module Container ("Registry of One")
- Tower runtime hosts exactly one hardcoded module slot.
- Preserve the module lifecycle abstraction (load/start/process/stop/unload; UNLOADED/LOADING/READY/ACTIVE/STOPPING/FAILED) so a real module can be swapped later without rewriting the runtime.
- No dynamic discovery, no descriptor negotiation protocol, no module registry yet.

Exit criterion: the tower runtime can load, run, and cleanly tear down one module through the full defined lifecycle.

### V0.9 — Experimental CV Lab (Module #1)
- Implement Experimental CV Lab as the module running in the V0.8 container.
- Prove the complete pipeline: DAT connection -> camera frames in Swift -> tower transport -> Experimental CV Lab -> one bounded CV experiment -> measurements.
- Use it as the sandbox for course CV experiments.
- Validate the module lifecycle/descriptor contract against real implementation experience before generalizing it.

Exit criterion: at least one bounded CV experiment runs end-to-end from glasses/mock device input through to measured results.

### V1.0 — Generalize Module Registry (When Justified)
- Triggered only once a second production module (a promoted Experimental CV Lab result, or another module such as Object Memory) creates real, concrete requirements.
- Build dynamic module discovery, the module registry, and descriptor/sensor-profile negotiation generalized from actual usage rather than speculative design.

Exit criterion: two or more modules coexist through the registry; adding a normal tower-only module does not require a new iOS release.

### V1.1 — Module Lifecycle Hardening
- activate / pause / stop / persist / unload / load / initialize / READY-FAILED / resume, exercised across real module switches;
- bounded timeouts on LOADING/STOPPING with a defined FAILED/unavailable transition on timeout (see `01-SYSTEM-ARCHITECTURE.md` — Reliability Policies).

### V1.2 — First Promoted Production Module
- Promote a successful Experimental CV Lab result (or implement Object Memory directly) into a dedicated module per the promotion path documented in `docs/modules/EXPERIMENTAL-CV.md`.

## Phase 3 — Advanced Modules

Candidates, each with its own specification under `docs/modules/`:
- Object Memory — strong bounded candidate for an early production module.
- World Build.
- Accessibility.
- Visual Q&A / Reading — comparatively heavy (STT + OCR/CV + multimodal reasoning + TTS); not an early starter module.
- Environmental / Physical-World Search — highest privacy exposure of the current module set; requires the retention/deletion policy in `06-PRIVACY-DATA.md` to be actually implemented, not just documented, before real data collection begins.

## Future Research

Possible but explicitly outside V1:
- direct glasses-to-tower transport (bypassing the iPhone entirely);
- alternative wearable hardware;
- deeper sensor fusion;
- persistent shared world models;
- custom firmware/reverse engineering.

These must not block the supported DAT-based platform.
