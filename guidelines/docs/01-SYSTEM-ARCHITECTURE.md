# System Architecture

## Top-Level Architecture

```text
[Ray-Ban Meta]
      |
     DAT
      |
[iOS Control Plane]
      |
 authenticated network transport
      |
[Persistent Tower Runtime]
      |
[Module Manager]
      |
[Exactly One Active Module]
```

## iOS Control Plane

The Swift app owns:
- DAT integration through a `GlassesConnection` abstraction.
- Stream/session coordination.
- Tower connectivity.
- Module discovery (a single fixed module initially; dynamic discovery once the registry is generalized — see `03-ROADMAP.md`).
- Module activation requests.
- Status and telemetry presentation.
- Generic module controls by default.
- Optional module-specific UI only when genuinely required.

It does not own heavy CV/AI processing.

## Tower Runtime

One server/runtime remains running while modules are swapped. Shared runtime responsibilities may include:
- transport/session endpoint;
- module container (a single hardcoded module slot initially; a dynamic module registry once a second module justifies it — see `03-ROADMAP.md`);
- module lifecycle manager;
- logging and telemetry;
- model/resource manager when sharing is justified.

Module-specific state should not automatically become global state.

### Initial Tower Stack

Pinned for the first implementation: Python, FastAPI, WebSockets for real-time frame transport, OpenCV, PyTorch, and CUDA when GPU acceleration is required. Do not introduce gRPC, C++, distributed infrastructure, message brokers, or container orchestration speculatively. Revisit only if measurements expose a real limitation.

## Module Switching

V1 permits one active major module.

Required lifecycle:

```text
User selects module
        |
Pause forwarding frames to processing
        |
Stop current module
        |
Persist module state if needed
        |
Release module-specific CPU/GPU resources
        |
Load selected module
        |
Initialize models/config/storage
        |
Apply requested sensor profile where supported
        |
Module reports READY
        |
Resume forwarding
```

The glasses connection should remain alive during a normal switch when DAT permits it. If current DAT behavior requires a session restart for a configuration change, the transport layer may perform that restart. Modules must not contain DAT-specific logic.

No sensor observations may be processed by a module while it is STARTING, STOPPING, FAILED, or otherwise not READY.

## Reliability Policies

These are architectural requirements; exact timing constants are an implementation/measurement decision, not fixed here.

**Lifecycle timeouts.** No lifecycle operation (LOADING, STOPPING, or equivalent) may block indefinitely. Each requires a bounded timeout. On timeout, the module transitions to a defined FAILED/unavailable state rather than hanging. A module timeout must not crash the persistent tower runtime.

**Reconnection.** Automatic reconnection (glasses session or tower connection) must use bounded/exponential backoff rather than a tight retry loop. Exact retry timing is an implementation decision.

**Backpressure.** The real-time perception pipeline must not grow an unbounded frame queue. Freshness generally matters more than processing every frame; when the tower/module cannot keep up, stale frames should normally be dropped rather than accumulating latency. Exact queue/drop strategy should be set from the measurements taken in `03-ROADMAP.md` V0.7, not decided in the abstract.

**Adaptive streaming (future).** Conceptually allow future operating states such as IDLE / TRACKING / HIGH_RATE frame-rate adjustment (see the original brainstorm doc for the shape). This is a future optimization to be designed from V0.7 measurements — do not implement it before those measurements exist.

## Tower Failure

If the tower becomes unreachable:
- iOS reports `Tower: Unavailable`.
- Active module is presented as unavailable.
- Processing stream is paused.
- Do not fabricate results.
- Do not buffer large amounts of video by default.
- The glasses connection may remain alive.
- Reconnection may occur automatically, using bounded/exponential backoff (see Reliability Policies above).
- After reconnection, refresh module state/registry before resuming.

## Remote Tower Access (Future Milestone)

Remote (non-LAN) tower access is a real project goal but is explicitly out of scope until the local pipeline (through Roadmap V0.7) works reliably. See `03-ROADMAP.md` Phase 1.5.

Target shape:

```text
Glasses -> iPhone -> cellular/remote network -> private secure connection -> home tower
```

Preferred approach: a private overlay/tunnel (e.g., Tailscale or WireGuard) rather than exposing the tower directly to the public internet. Do not design the full remote-access implementation before this milestone is reached.

## Dynamic Discovery

The iPhone must eventually obtain the available module catalog from the tower. The production module list must not be permanently hardcoded into Swift long-term.

Sequencing: the first tower implementation hosts exactly one module (a "registry of one," see `03-ROADMAP.md` V0.8–V0.9). The iPhone may treat the single module as effectively fixed during this phase. Full dynamic discovery is built only once a second production module creates real requirements to generalize against — do not build the general discovery protocol speculatively.

Conceptual interaction (target shape once generalized):

```text
iPhone -> request module registry
Tower  -> module descriptors
iPhone -> activate module ID
Tower  -> lifecycle transition
Tower  -> READY / FAILED
```

Exact protocol/API choices belong to that later milestone.

## Privacy & Data Handling

Raw sensor data (camera/audio) is local-first by default: it stays within Glasses -> iPhone -> tower and is not sent to third-party AI/cloud services unless an explicit, documented exception is made. See `06-PRIVACY-DATA.md` for the full policy and `02-DEVELOPMENT-RULES.md` Rule 12.

## Platform Constraints & Epistemic Rules

The platform's sensors and models produce evidence, not ground truth: monocular depth is inferred, ML outputs are probabilistic, sessions can be interrupted, the Tower is not always reachable, and camera visibility does not imply user attention. `07-PLATFORM-CONSTRAINTS.md` is the canonical, cross-module record of these limitations and their engineering mitigations, and defines the platform's epistemic rules (observation ≠ fact, inference ≠ measurement, absence of observation ≠ observation of absence, confidence must survive the pipeline, timestamps represent observation time). Every module must respect it; see `02-DEVELOPMENT-RULES.md` Rule 16.
