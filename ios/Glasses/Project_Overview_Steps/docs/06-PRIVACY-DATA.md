# Privacy & Data Policy

## Purpose

This document defines platform-level principles for how the Glasses platform captures, processes, stores, and disposes of sensor data and derived data. It is referenced by `02-DEVELOPMENT-RULES.md` Rule 12 and required by every module descriptor's data-behavior declaration (`04-MODULE-SYSTEM.md`).

This document states engineering policy. It does not provide jurisdiction-specific legal conclusions. Real-world capture must independently comply with applicable law and location/institution policy.

## Core Principle: Local-First

Raw sensor data (camera frames, audio) is local-first by default:

```text
Glasses -> iPhone -> private tower
```

Raw or sensitive sensor data must not be sent to third-party AI/cloud services by default. Tower-hosted/local models are the preferred processing path for normal module development.

An exception requires all of the following, documented explicitly per feature:
- clear justification for why local processing is insufficient;
- explicit user opt-in;
- disclosure of exactly what data leaves the local system;
- data-minimization applied before transmission;
- a retention/privacy review of the third-party destination.

This is a real, usable exception process — not a permanent prohibition — but it must never be the silent default.

## Real-World Capture

- Capture must comply with applicable law and location/institution policy. Requirements vary by jurisdiction, location, audio/video context, reasonable expectation of privacy, institutional policy, and use; this repository does not encode jurisdiction-specific conclusions.
- Avoid privacy-sensitive/private environments during development unless specifically appropriate for the task.
- The technical ability to capture data does not imply unrestricted permission to capture it.
- Make recording/capture state clear during controlled testing where appropriate.

## Raw Frame/Audio Retention

- Continuous raw video/audio should not be retained by default.
- Prefer processing raw frames in memory and persisting only derived/structured data (detections, embeddings, OCR text, events) unless a specific feature has an explicit, justified need to retain raw imagery.
- Where raw imagery/audio genuinely must be retained (e.g., a manually started dataset-recording session), it is retained under the Explicit Dataset-Recording Sessions rules below, not as an incidental side effect of normal operation.

## Module-Owned Persistent Data

- Each module owns its own data namespace (see `04-MODULE-SYSTEM.md`). Modules must not read/write another module's data without an explicit shared-data design.
- Every module descriptor must declare, at minimum:
  - what data it persists;
  - whether raw imagery/audio is persisted or only derived/structured data;
  - retention behavior;
  - whether it supports clearing/purging its own data;
  - whether any of its data leaves the local system, and under what conditions.
- The exact interface for these capabilities (e.g., a `purge()` method or equivalent) is an implementation detail to be defined once the tower module contract is implemented. This document requires the capability; it does not lock in a method signature.

## Explicit Dataset-Recording Sessions

Some modules (notably Experimental CV Lab) support deliberate dataset capture for course/research purposes. Any such capture must:
- be manually started/stopped, never implicit background capture;
- clearly indicate recording state while active;
- store data within the owning module's namespace;
- avoid indefinite/unbounded background capture;
- include useful metadata (timestamp, configuration);
- follow the Real-World Capture principles above.

## Deletion / Clear-Memory Behavior

- Users must have a way to clear a module's stored data (a purge capability), particularly for modules that accumulate history over time (Object Memory, Environmental Memory).
- Deletion should be real deletion of the module's stored artifacts, not merely hiding data from a query interface.
- Modules with long-lived history (Environmental Memory in particular) must implement working retention/deletion behavior before they are used to collect real data — documenting the principle here is not a substitute for implementing it.

## Configurable Retention

- Where a module's purpose justifies persistent history, retention should be configurable (e.g., a retention window) rather than hardcoded to "forever" by default.
- Exact configuration mechanism is an implementation decision; the requirement is that unbounded, non-configurable indefinite retention is not the unexamined default for history-accumulating modules.

## Third-Party Data Transmission

- Governed by the Core Principle above: local-first by default, explicit documented exception required to send data externally.
- This applies to raw sensor data and to derived data that could reveal sensitive information (e.g., OCR'd document contents, recognized faces/identities, location history).

## Sensitive Visual Information

- Documents, screens, IDs, financial information, private communications, and bystanders may appear in any camera frame. This is treated as a standing risk of the input modality, not an edge case.
- Selected crops or "reduced" imagery are not inherently safe: a cropped image can still contain a bystander's face, a private room, or a document. Treat any stored image/crop as potentially sensitive, regardless of size or selection method.
- Prefer structured metadata/embeddings over stored imagery whenever the feature's actual requirement can be satisfied without pixels.

## Logs / Telemetry

- Logs and telemetry should avoid embedding raw sensor payloads (frames, audio) by default; prefer structured, non-sensitive metadata (timings, state transitions, error codes).
- Treat log/telemetry retention with the same minimization principle as module data: keep what is useful for debugging/measurement, not indefinitely by default.

## Development Datasets

- Datasets captured for course/research purposes fall under the Explicit Dataset-Recording Sessions rules above.
- Development datasets are not exempt from the real-world capture or retention principles simply because they are "just for testing."

## Data Minimization

- Across the platform: collect the minimum data required for the feature to work, retain it for the minimum useful duration, and prefer derived/structured representations over raw sensor payloads whenever the feature's actual requirement allows it.
