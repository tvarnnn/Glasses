# Module Concept — World Build

## Status

Future module. This is a concept/specification seed, not authorization to implement the entire system now.

## Goal

Use first-person wearable camera observations to incrementally construct a spatial representation of environments the user traverses.

## Intended Inputs

Primary:
- camera frames.

Possible future inputs, only if DAT/hardware exposes useful supported data:
- motion/inertial information;
- timestamps;
- additional sensor metadata.

Do not assume unavailable sensors.

## Initial Sensor Profile Hypothesis

For early experiments:
- camera enabled;
- approximately 15 FPS target;
- moderate supported resolution such as approximately 504x896 if current DAT supports it;
- microphone off unless a later feature requires it;
- minimal audio feedback.

These are experimental targets, not guaranteed device capabilities. Verify through current DAT documentation and benchmarks.

## Hardware Reality: Monocular RGB Only

The current target Meta glasses provide a monocular RGB camera. They do not provide direct metric depth sensing such as LiDAR or stereo depth. World Build's design must treat this as a hard constraint, not an implementation detail to work around later.

World Build must therefore distinguish, in its data model and in anything it ever surfaces, between three distinct kinds of spatial information:
- **relative spatial geometry** — structure, layout, and relationships derived from multi-view geometry, without a claimed absolute physical scale;
- **inferred metric depth** — a distance estimate produced by ML monocular depth estimation or geometric inference, carrying model/method uncertainty;
- **directly measured metric depth** — depth from dedicated depth-sensing hardware (LiDAR, stereo). Not available on the current target hardware.

**World Build must never represent monocularly inferred depth as ground-truth physical distance.** Any distance figure derived from monocular inference must be identifiable as an estimate wherever it is stored, displayed, or consumed by another module.

This module is the primary case behind `07-PLATFORM-CONSTRAINTS.md` Limitation 1 (Monocular Depth / Scale) and Core Principle 2 (Inference ≠ Measurement); see that document for the full mitigation classification and confirmed DAT camera-configuration constraints this pipeline must work within.

## Candidate Pipeline (Hybrid, Not a Single Technique)

World Build should use a hybrid spatial-reconstruction pipeline rather than relying on one depth-estimation technique:

```text
RGB camera frames
    |
keyframe selection
    |
visual SLAM / Structure-from-Motion
    |
ML monocular depth estimation
    |
semantic/object understanding
    |
spatial fusion
    |
persistent world representation
```

Potential sources of spatial constraints to fuse, none authoritative alone:
- multi-view geometry across camera motion;
- ML monocular depth estimates;
- recognized objects with approximately known dimensions;
- floor/wall/ceiling plane estimation;
- estimated camera/head height where appropriate;
- temporal consistency across observations;
- future IMU/motion data, if DAT exposes suitable sensor access.

Do not adopt every technique by default. Select the smallest pipeline that satisfies the project's actual course/research objective. Do not choose or implement a specific ML depth model as part of this documentation decision — that remains a later, separate decision.

## ML Depth Estimation

Machine-learning monocular depth estimation is intended to partially compensate for the lack of dedicated depth hardware, not to stand in as an equivalent of it.

- Prefer metric-depth-capable models where practical over relative-depth-only models, since metric output is more useful to fuse with other constraints.
- ML-derived distance remains an estimate. It must not be treated as equivalent to LiDAR/depth-sensor measurement anywhere in the system, including in later modules that consume World Build's output.
- The Tower GPU should perform this computationally expensive depth/reconstruction work rather than the glasses or iPhone, whenever practical — consistent with the platform's existing lightweight-phone / compute-on-Tower principle.

## Confidence / Uncertainty

Spatial observations should eventually carry confidence/uncertainty information rather than being presented as uniformly reliable. Illustrative levels:
- **high confidence**: repeatedly observed geometry supported by multiple viewpoints;
- **medium confidence**: ML depth supported by some geometric constraints;
- **low confidence**: single-frame inference, reflective surfaces, low light, motion blur, textureless regions, or conflicting estimates.

World Build should prefer repeated observations and multi-view consistency over a single-frame depth prediction. The exact confidence representation/schema is not decided here — this section records the requirement that one must exist, not its implementation.

## Real-Time vs. Asynchronous Processing

World Build does not need to perform full high-quality reconstruction synchronously. A future architecture may split live, lightweight work from heavier asynchronous Tower work:

```text
Live (glasses/iPhone):
camera -> lightweight tracking / pose estimation -> keyframe selection

Asynchronous (Tower):
keyframes -> depth estimation -> SfM/SLAM refinement -> map optimization -> persistent reconstruction
```

This keeps expensive reconstruction workloads on Tower hardware rather than making the glasses/iPhone responsible for heavy computation, consistent with the platform's existing architecture.

## Candidate CV Techniques

Techniques the pipeline above may draw on, to evaluate as the CV course progresses:
- feature detection/description;
- feature matching;
- optical flow;
- visual odometry;
- keyframe selection;
- monocular depth;
- Structure from Motion;
- visual SLAM;
- point-cloud reconstruction;
- later reconstruction/rendering techniques.

## Persistence

World Build owns its mapping artifacts, which may eventually include:
- keyframes;
- features/descriptors;
- camera pose estimates;
- reconstruction data;
- map metadata;
- experiment metrics;
- per-observation confidence/uncertainty metadata (see Confidence / Uncertainty above).

Storage format is intentionally undecided until the implemented pipeline requires one.

## Relevance

Continuous video is highly redundant. World Build may eventually use keyframe/relevance selection so only observations that improve the map receive expensive processing or long-term storage.

## Output

Possible outputs:
- map/reconstruction status;
- mapping quality metrics;
- reconstructed environment artifacts;
- minimal audio/status feedback.

Any output that includes a distance/measurement must be labeled according to the relative / inferred-metric / measured-metric distinction above — never presented as measured when it is inferred.

## Hardware Suitability

Given the monocular-RGB-only constraint, the current glasses should be considered suitable for:
- relative spatial mapping;
- place recognition;
- rough environmental reconstruction;
- semantic mapping;
- approximate depth.

They should **not** be considered authoritative for:
- centimeter-accurate measurements;
- safety-critical distance estimation;
- precise obstacle dimensions;
- other applications requiring measured metric depth.

Any future feature (in World Build or elsewhere, e.g. Accessibility) that would need one of the disallowed capabilities above must not rely on this module's monocular inference to provide it.

## Future Hardware / Sensors

Recorded here as a future architectural direction only — not authorization to implement, and not a reason to move World Build earlier in the roadmap.

- If future DAT versions expose useful synchronized IMU/motion data, evaluate visual-inertial odometry (VIO) as an enhancement.
- If future glasses hardware exposes stereo/depth/LiDAR sensing, World Build should be designed so those measurements can augment or replace inferred monocular depth **without rewriting the higher-level world representation** — i.e., the relative/inferred/measured distinction and the fusion/confidence model above should already accommodate a future measured-depth input as just another, higher-confidence source.

## Success Criteria for First Version

Define these when the CV course requirements are known. The first version should prove one bounded spatial-CV capability rather than attempting city-scale reconstruction.

## Safety / Privacy

First-person mapping may capture bystanders, private spaces, screens, documents, and location-revealing imagery. Data collection/storage policies must be deliberate before real-world large-scale capture. See `06-PRIVACY-DATA.md` for the platform-level policy this module's data behavior must satisfy.
