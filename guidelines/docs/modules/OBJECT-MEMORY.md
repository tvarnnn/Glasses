# Module Concept — Object Memory

## Status

**PARTIALLY IMPLEMENTED, then BLOCKED.** Still a strong candidate for an
early project — it is bounded enough to build incrementally while
exercising detection, tracking, temporal reasoning, relevance filtering
and persistence — but it is no longer entirely unbuilt, and it is stopped
at a named gate rather than merely unstarted.

| Part | Status |
|---|---|
| Observation record schema, relevance filtering, observation store (append, read, `last_seen`, retention pruning, real `purge`) | **CURRENTLY IMPLEMENTED** — `tower/object_memory/{records,relevance,store}.py`, tested |
| A detector producing observations | **BLOCKED** |
| A `Module` subclass, wiring, any HTTP/WS surface | **BLOCKED** |
| Spatial anchors against a World Builder world | **PLANNED** — the contract is written down but no anchor exists yet |

**The blocker, precisely.** Task 4 requires the module's `_do_load()` to
load a detector synchronously, which reproduces the unbounded-blocking
lifecycle gap `DepthEstimationModule` already has (see
`01-SYSTEM-ARCHITECTURE.md` — Reliability Policies, Known exception).
Four costed options are written up in
`docs/superpowers/plans/2026-08-20-object-memory-first-slice.md`; the
Master Guide classifies choosing between them as needing user judgement,
so an agent must not resolve it autonomously.

Nothing currently produces an observation: `Module.process()` receives
raw JPEG bytes and no timestamp, sequence number or session id, so even a
working detector could not populate the fields the schema already has.

**Before the first anchor is ever written**, add `anchor_keyframe_id` and
`position_in_anchor_frame` to the anchor schema. Without them the first
loop closure permanently and undetectably invalidates every earlier
anchor, because a submap re-anchor is not a global similarity and cannot
be composed forward. See `CARTRIDGE-GROUNDWORK.md` §4.

## Goal

Maintain a searchable history of where objects were observed over time so the user can ask questions such as:

- Where did I last see my keys?
- Have I seen my backpack today?
- When was my charger last visible?
- What room did I leave my water bottle in?

The module should reason from observations rather than continuously storing every raw frame.

## Intended Inputs

Primary:
- camera frames;
- frame timestamps;
- module/session metadata.

Possible future inputs:
- user voice queries;
- spatial/map context from another explicitly shared service if the architecture later supports it.

Do not assume cross-module data sharing exists in V1.

## Initial Sensor Profile Hypothesis

Early experiments may target:

- camera enabled;
- approximately 5–15 FPS;
- microphone optional and only enabled for voice-query interaction;
- audio output enabled when spoken responses are desired;
- moderate resolution sufficient for object detection/tracking.

Exact values must be verified against current DAT support and measured performance.

## Core CV Pipeline

Possible first implementation:

```text
camera frame
    |
object detector
    |
multi-object tracker
    |
observation builder
    |
relevance / state-change filter
    |
persistent object history
```

An observation may eventually contain fields equivalent to:

```text
objectClass
trackId
timestamp
confidence
boundingBox
sessionId
locationContext
visualEmbedding
eventType
```

The exact schema should be defined when implementation begins.

## Relevance

The module should not save every detection from every frame.

High-value events may include:

- newly observed object;
- object picked up or moved;
- object disappears after sustained visibility;
- object reappears in a new context;
- meaningful change in location;
- high-confidence observation useful for later retrieval.

Low-value repeated detections should be sampled, merged, summarized, or discarded.

## Identity vs. Category

Distinguishing "a backpack" from "my backpack" is harder than generic object detection.

Potential future techniques:
- visual embeddings;
- instance re-identification;
- user confirmation;
- object-specific enrollment/reference images.

Do not claim unique-object identity unless the implementation actually supports it.

## Persistence

Object Memory owns its own observation store.

Potential stored artifacts:
- object events;
- timestamps;
- selected keyframes/crops;
- embeddings;
- session metadata;
- confidence scores.

Avoid storing complete continuous video by default.

## Query Layer

The module may eventually support queries such as:

```text
last_seen("keys")
seen_today("backpack")
history("charger")
recent_objects()
```

A language model may translate natural-language questions into structured queries, but the underlying object-history data should remain queryable independently of an LLM.

## Output

Possible responses:

- "Your keys were last seen on the kitchen counter at 4:18 PM."
- "I last saw your backpack during the previous session."
- "I do not have a confident recent observation of your charger."

The system must expose uncertainty rather than inventing locations. Report "last observed at X," never "is currently at X" — an unobserved object is unknown, not confirmed absent or confirmed stationary. See `07-PLATFORM-CONSTRAINTS.md` Limitation 7 (Environmental Memory / Observational Gaps, which explicitly also covers Object Memory) and Core Principle 3 (Absence of Observation ≠ Observation of Absence).

## Failure Behavior

If the tracker/detector loses confidence:
- record uncertainty;
- avoid overwriting a strong previous observation with a weak one;
- never present a guessed location as fact.

If the tower is unavailable:
- module is unavailable;
- no false memory updates occur.

## Privacy

Object Memory may inadvertently capture sensitive surroundings. Prefer structured metadata/embeddings over stored imagery when they satisfy the feature. Selected object crops reduce data volume but are not inherently safe — a crop can still contain a bystander's face, a private room, a screen, or a document in the background. Treat any stored crop as potentially sensitive imagery, subject to the same retention/deletion requirements as full frames. See `06-PRIVACY-DATA.md`.

## First-Version Success Criteria

A bounded V1 should demonstrate:

1. stable first-person object detection;
2. basic temporal tracking;
3. meaningful observation persistence;
4. retrieval of the most recent reliable observation;
5. measured precision/recall or task-specific retrieval accuracy;
6. measured resource usage and latency.

Do not require full spatial mapping for the first version.
