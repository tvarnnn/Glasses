# Module Concept — Experimental CV Lab

## Status

**CURRENTLY IMPLEMENTED.** The only cartridge that actually runs on the
live frame path today (`tower/modules/experimental_cv.py`, wired in
`tower/main.py`). See "Actual structure" below for how the shipped layout
differs from the one this document originally proposed.

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

## Registered Experiments (V1, 2026-08-22)

What actually exists. Each names one **headline** measurement and may
report others alongside it.

| Experiment | Headline | Cost at 640x360 | State |
|---|---|---|---|
| `baseline` | `mean_intensity` | 1.0 ms | none |
| `edge_detection` | `edge_density` | 1.5 ms | none |
| `frame_quality` | `sharpness_laplacian_var` | 5.6 ms | none |
| `feature_detection` | `keypoint_count` | 4.2 ms | none |
| `redaction_impact` | `region_keypoint_retention` | 4.9 ms | none |
| `optical_flow` | `median_flow_px` | 4.6 ms | previous frame |
| `object_detection` | `detections` | 35.3 ms | model (`[ml]` extra) |
| `depth` | `mean_relative_depth` | 26.0 ms | model (`[ml]` extra) |

Costs are measured on this host with synthetic imagery
(`scripts/cv_lab_benchmark.py`) — real for the code, not a statement
about a real room. Selected with `TOWER_CV_EXPERIMENT`.

**Every experiment must expose useful measurements.** An experiment whose
result nobody can act on is not an experiment, and the headline exists to
force the question: an experiment that cannot name its single most
important number has not decided what it is measuring.

## Result contract

```python
ExperimentResult(
    result_value: float,        # the headline, mandatory
    result_label: str,          # its name, mandatory
    processing_ms: float,
    stage_ms: dict[str, float],
    mean_intensity: float | None = None,   # historical, V0.7-compatible
    metrics: dict[str, float] = {},        # everything else
)
```

`metrics` reaches a client on `frame_result`, and is **omitted entirely
when empty** so a client that has never heard of it is unaffected. It is
deliberately `name -> number`: a **measurement** channel, not a general
result channel. Structured results (a detection list, a geometry delta)
need the module-contract work that is blocked at V1.0/V1.1.

## Experiment protocol

An experiment is anything with `name`, `load(settings)`, `run(bytes)` and
`release()`. The registry holds **factories**, not instances — building a
detector at import time would load model weights in any process that
imported the module.

A stateless experiment is still just a function; `StatelessExperiment`
adapts it. Before this existed, a stateful experiment cost a whole
`Module` subclass, and there were two of them sharing one descriptor id.

`release()` must free whatever `load()` allocated, must be safe to call
twice, and must be safe after a partial load — it runs on the FAILED
transition, which is reachable from anywhere.

## Candidate Experiments (not yet built)

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
- lightweight relevance classification;
- a GPU-accelerated variant of an existing experiment, benchmarked against its CPU baseline (see GPU / Acceleration Benchmarking, below).

The list is intentionally broad. Only one experiment needs to be active at a time.

**Do not turn this into a random collection of models.** Each addition
must answer a question another part of the platform actually has. Several
of the items above were considered for V1 and deliberately left out:
semantic and instance segmentation, tracking-by-detection, image
retrieval and novelty detection all lack a consumer today. Face detection
is not merely unbuilt but **BLOCKED**: this OpenCV 5 build has no
`CascadeClassifier`, `FaceDetectorYN` ships no model, no cascade or ONNX
file exists anywhere on disk, and there is no face imagery to validate
against. `redaction_impact` measures the *consequence* of redaction
without pretending to detect a face.

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

Dataset capture is **not** this module's own mechanism. `tower/capture.py`
is shared infrastructure — the transport arms it, and Object Memory or a
Document cartridge would use the same recorder. Versioning a recording
made by shared transport with one cartridge's schema would let an
unrelated schema bump invalidate it.

Dataset capture must:
- be manually started/stopped;
- clearly indicate recording state (`GET /health` reports it);
- store data under the recorder's own root, not inside a cartridge;
- avoid indefinite background capture;
- include useful metadata such as timestamp/configuration;
- follow the platform data policy in `06-PRIVACY-DATA.md`.

## Experiment Structure

### Proposed structure (historical)

This was the shape proposed before implementation:

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

### Actual structure

The Tower did not adopt it, and the divergence is deliberate rather than
accidental — a per-experiment package directory buys nothing when an
experiment is one module:

```text
tower/experiments/          one module per experiment
tower/modules/experimental_cv.py   the Module that hosts whichever one is selected
scripts/                    benchmark and analysis drivers
```

There is no `data/` or `results/` directory. Recorded datasets live under
the **shared** recorder's root (`tower/capture.py`, armed by
`TOWER_CAPTURE_ROOT`), and measured results live in
`guidelines/docs/reports/`.

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

**The Lab persists nothing.** Its descriptor declares
`persists_data=False` and `retains_raw_imagery=False`, and the descriptor
is what `06-PRIVACY-DATA.md` is enforced against — an experiment that
quietly wrote to disk would make that declaration a lie. A test asserts
that no experiment calls a write primitive.

Measured results live in `guidelines/docs/reports/`. Recorded datasets
live under the shared recorder's root. Neither belongs to an experiment.

Do not read/write another module's private data without an explicit shared-data design.

## Isolation from the cartridges

The Lab must not import `tower.world_builder` or `tower.object_memory`,
and a test enforces it in both directions.

The reason is specific rather than tidiness: the Lab's job is to
**measure** properties — blur rejection, feature yield, apparent motion —
that World Builder also has private opinions about. Importing that
opinion would mean restating a cartridge's answer instead of measuring
the underlying property, and a threshold change on the cartridge side
would silently move a measurement. It would also put a sandbox that may
be thrown away upstream of a persistent world.

The Lab may read a world for visualisation one day. Today it does not,
and it must never write one.

## Failure Behavior

An experiment failure must:
- mark the module/experiment failed;
- release GPU/CPU resources;
- leave the persistent tower runtime alive;
- not break module discovery or switching.

## GPU / Acceleration Benchmarking

Experimental CV Lab is the appropriate place to evaluate whether a GPU-acceleration technology is justified for a given workload, following the correctness -> instrument -> profile -> identify bottlenecks -> accelerate philosophy in `01-SYSTEM-ARCHITECTURE.md` — GPU / Acceleration Strategy. Benchmarking a candidate technology (PyTorch CUDA execution, TensorRT, CV-CUDA, or another) against a measured CPU baseline is itself a valid experiment here and should follow the same Success Criteria (hypothesis, baseline, metric, result) as any other experiment in this module. Do not adopt a GPU-acceleration technology platform-wide based on an unmeasured assumption that it will help — that decision is made from this module's measured results, not in the abstract.

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
