# Module Concept — Experimental CV Lab

## Status

Module #1 — the first module to be implemented (see `03-ROADMAP.md` V0.8–V0.9). Its role in this phase is to prove the complete glasses -> iPhone -> tower -> CV pipeline, serve as the sandbox for course experiments, and validate the module lifecycle/descriptor contract against real implementation experience before any dynamic registry is built.

## Goal

Provide a controlled place to test computer-vision techniques on first-person glasses data without contaminating production modules or forcing every experiment into the long-term architecture.

This module is especially useful while completing a computer-vision course.

## Philosophy

The experimental module may be messy internally, but its boundaries with the platform must remain clean.

It receives observations through the normal module interface and returns results through the normal module/output path.

It must not bypass:
- the DAT abstraction;
- the tower module manager;
- lifecycle rules;
- resource cleanup;
- privacy/security rules.

## Candidate Experiments

Examples:

- edge detection;
- feature detection;
- SIFT/ORB-style descriptors where appropriate;
- feature matching;
- optical flow;
- background/foreground segmentation;
- object detection;
- instance/semantic segmentation;
- tracking;
- monocular depth estimation;
- camera-motion estimation;
- visual odometry;
- image retrieval;
- clustering;
- novelty detection;
- lightweight relevance classification.

The list is intentionally broad. Only one experiment needs to be active at a time.

## Sensor Profile

The module should expose experiment-specific settings.

Examples:
- FPS;
- resolution;
- whether audio is required;
- frame sampling rate;
- model/algorithm selection;
- visualization/debug-output settings.

## Data Capture

The module may optionally support explicit dataset-recording sessions for course/research purposes.

Dataset capture must:
- be manually started/stopped;
- clearly indicate recording state;
- store data in this module's namespace;
- avoid indefinite background capture;
- include useful metadata such as timestamp/configuration;
- follow the platform data policy in `06-PRIVACY-DATA.md`.

## Experiment Structure

Preferred organization:

```text
experimental_cv/
    experiments/
        optical_flow/
        object_detection/
        depth/
        ...
    data/
    results/
```

Exact structure should follow the tower repository once implemented.

## Promotion Path

An experiment that proves useful should not remain permanently inside the sandbox.

Promotion process:

```text
experiment
   |
measured success
   |
write dedicated module/shared-service spec
   |
implement through normal architecture
```

For example, if relevance classification becomes essential across modules, it may later become a shared service after a separate architecture decision.

## Persistence

Store only experiment-specific datasets/results.

Do not read/write another module's private data without an explicit shared-data design.

## Failure Behavior

An experiment failure must:
- mark the module/experiment failed;
- release GPU/CPU resources;
- leave the persistent tower runtime alive;
- not break module discovery or switching.

## Model Output vs. Measured Fact

Experiment output (detections, depth estimates, classifications, tracked poses, etc.) is model inference, not a measured sensor fact, unless the experiment specifically validates against a ground-truth reference. Results/logs must distinguish the two. See `07-PLATFORM-CONSTRAINTS.md`, particularly Core Principle 2 (Inference ≠ Measurement) and Limitation 5 (Probabilistic ML Output).

## Success Criteria

Every experiment should define:
- hypothesis/question;
- dataset/session;
- metric(s);
- baseline;
- result;
- resource usage where relevant.

Avoid declaring an approach "better" without a measurement.
