# Glasses — Project Vision

## Mission

Build a modular wearable AI platform where Ray-Ban Meta glasses act primarily as a first-person sensor/output endpoint, a custom Swift iPhone app acts as the control plane and network bridge, and a persistent Windows tower runtime performs compute-intensive computer vision and AI workloads.

The goal is not one glasses app. The goal is a reusable platform capable of hosting a growing library of interchangeable wearable applications.

## Core Model

```text
Ray-Ban Meta Glasses
camera / microphone / supported input-output
        |
        v
Meta DAT
        |
        v
Custom Swift iPhone App
control plane + transport bridge
        |
   Wi-Fi / cellular
        |
        v
Persistent Tower Runtime
shared infrastructure + GPU compute
        |
        v
One Active Module
        |
        v
Results / feedback
        |
        v
iPhone -> Glasses -> User
```

## Responsibilities

### Glasses
The glasses are treated as the wearable I/O layer. Do not assume they perform project-specific AI computation.

### iPhone
The iPhone app should remain lightweight. Its primary responsibilities are DAT integration, connection/session management, transport to the tower, module selection, telemetry, and user controls.

### Tower
The tower is the primary compute environment. It owns module execution, GPU workloads, CV/AI models, module-specific persistence, and resource management.

### Modules
Applications such as World Build and Accessibility are modules loaded by the persistent tower runtime. Only one major module is active at a time in V1.

## Long-Term Properties

- New modules should not require rewriting the glasses integration.
- New tower modules should be discoverable by the iPhone dynamically.
- Heavy models should not run on the iPhone unless a future requirement justifies it.
- Module-specific data belongs to the module by default.
- Shared services should exist only when multiple modules demonstrably need them.
- Meta-specific APIs must remain behind a boundary so the rest of the platform does not depend directly on DAT.
- The architecture should permit a future alternative sensor transport without rewriting application modules.

## Current Scope

V0.x is foundation work. Do not prematurely build SLAM, multimodal agents, accessibility navigation, custom firmware, or other advanced functionality before the end-to-end sensor-to-tower pipeline works.

The first meaningful platform proof is:

```text
Glasses / Mock Device -> DAT -> Swift -> Network -> Tower -> OpenCV
```

Everything else grows from that.
