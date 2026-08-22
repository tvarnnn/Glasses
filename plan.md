You are now GREENLIT to autonomously build WORLD BUILDER V1 for the Glasses
project.

This is a LARGE AUTONOMOUS ENGINEERING RUN.

You have broad authority to:

RECOVER CONTEXT
→ INVESTIGATE
→ CHALLENGE ASSUMPTIONS
→ RESEARCH
→ PLAN
→ REVIEW THE PLAN
→ IMPLEMENT
→ TEST
→ BENCHMARK
→ DEBUG
→ REFACTOR WHEN JUSTIFIED
→ ADVERSARIALLY REVIEW
→ FIX
→ DOCUMENT
→ COMMIT

Use focused subagents extensively when they materially improve quality,
parallelism, research depth, implementation, testing, or review.

You do NOT need routine user approval between these stages.

Work autonomously until:

A. World Builder V1 reaches the bounded definition of completion below,

OR

B. you encounter a genuine product/privacy/architecture/hardware decision that
cannot safely be resolved from existing project evidence.

Do not stop for ordinary engineering decisions.

Do not stop merely because the implementation is large.

Do not repeatedly ask the user for permission.

==================================================
0. FIRST PRINCIPLE — YOU MAY CHALLENGE EVERYTHING
==================================================

The existing readiness report and the architecture described below are the best
current hypotheses.

They are NOT commandments.

You are explicitly authorized to discover that:

- our algorithm choice is wrong
- our ML choice is wrong
- our classical CV choice is wrong
- our persistence model is unnecessarily complicated
- our keyframe strategy is wrong
- our geometry representation is wrong
- a mature existing system solves the problem better
- an apparently sophisticated component is unnecessary
- a simpler architecture performs equally well
- a more complex architecture is justified by measured improvement

If so:

CHANGE COURSE.

Document why.

The goal is not to implement our favorite architecture.

The goal is to build the strongest technically honest World Builder that fits
our real hardware, software, and product constraints.

==================================================
1. STARTING STATE
==================================================

Expected Tower state:

master @ b591e30

working tree:
clean

latest verified suite:

214 passed
3 skipped

VERIFY THIS YOURSELF.

The previous World Builder readiness/research mission is COMPLETE.

DO NOT redo it.

Locate and read the readiness report produced by that run.

It contains approximately 1,217 lines of recovered experiments, architecture
research, intrinsics findings, GPU findings, persistence research, and
recommendations.

Treat it as primary evidence.

Also read the relevant repository sources of truth:

- project vision
- architecture
- development rules
- roadmap
- module system
- World Build documentation
- Experimental CV documentation
- existing experiment reports
- persistence contracts
- module contracts
- relevant README material

Recover actual filenames from the repository.

Do not assume filenames from this prompt.

==================================================
2. GIT SAFETY
==================================================

DO NOT implement directly on master.

Start from:

master @ b591e30

Create an appropriately named feature branch such as:

world-builder/v1

Use the repository's established engineering workflow.

Worktrees may be used ONLY if import resolution is proven correct.

Previous project work discovered that editable-install sys.path/import behavior
could cause worktree tests to silently execute code from the main repository.

VERIFY import resolution before trusting a worktree.

If uncertain:

use a normal feature branch.

Commit coherent milestones.

Do not force-push master.

Do not merge into master automatically unless every repository rule and gate
explicitly permits it.

Prefer leaving a reviewed implementation branch ready for inspection.

==================================================
3. PRODUCT RULING — WORLD BUILDER V1
==================================================

The intended World Builder V1 experience is explicitly:

START WORLD BUILDER
→ WALK NATURALLY AROUND A ROOM
→ WORLD BUILDS INCREMENTALLY
→ STOP
→ WORLD PERSISTS ON TOWER
→ REOPEN WORLD
→ PAN / ROTATE / ZOOM / INSPECT IT

For V1:

deliberate Start → Walk → Stop mapping IS World Builder.

An older WORLD-BUILD document apparently states that a deliberate capture
action is a different feature.

That historical statement must NOT be silently erased.

This prompt constitutes a deliberate product decision changing that behavior.

Update the appropriate source-of-truth documentation and record the decision.

==================================================
4. WORLD BUILDER IS A CARTRIDGE — CAMERA IS INFRASTRUCTURE
==================================================

World Builder must NOT permanently define global camera behavior.

The camera/transport layer is shared sensor infrastructure.

Each cartridge must eventually be able to consume camera information according
to its own needs.

Examples:

WORLD BUILDER may care about:

- temporal tracking
- parallax
- keyframes
- image quality
- geometric information gain

OBJECT MEMORY may care about:

- object changes
- semantic observations
- occasional high-value frames

VISUAL Q&A may care about:

- freshest current observation
- potentially higher-quality snapshots

ACCESSIBILITY may care about:

- minimum latency
- continuous inference
- immediate warnings

TEXT / DOCUMENT functionality may care about:

- high resolution
- deliberate still-like observations
- OCR quality

Therefore:

DO NOT hard-code World Builder-specific assumptions into generic camera
infrastructure.

The current iOS ~12 FPS selection policy is a CURRENT transport/default policy.

It is NOT a permanent cartridge-independent law.

World Builder should consume the available frame stream and make its own
decisions.

==================================================
5. SHARED INFRASTRUCTURE / FUTURE CARTRIDGE GROUNDWORK
==================================================

World Builder is the first major cartridge allowed to seriously pressure-test
the platform architecture.

While implementing World Builder:

IF you discover a capability that is genuinely generic and clearly useful to
multiple cartridges, you MAY design or implement it as shared infrastructure.

Examples MAY include:

- generic frame-consumer interfaces
- cartridge-specific sensor/capture requirements
- frame metadata
- timestamps and sequence semantics
- generic artifact persistence
- bounded event streams
- health telemetry contracts
- GPU/model-service boundaries
- lifecycle-safe processing primitives
- generic observation/event contracts
- cartridge resource declarations
- reusable confidence/quality primitives

BUT:

DO NOT generalize prematurely.

Before extracting something from World Builder into shared infrastructure, ask:

1. Is this actually useful to another known cartridge?
2. Is the abstraction understood from at least two plausible consumers?
3. Does extracting it reduce future duplication?
4. Does it preserve cartridge isolation?
5. Does it introduce unnecessary complexity today?

If the answer is unclear:

KEEP IT LOCAL TO WORLD BUILDER.

==================================================
6. DO NOT BUILD THE OTHER CARTRIDGES TONIGHT
==================================================

Do NOT implement:

- Accessibility
- Visual Q&A
- Environmental Memory
- additional Object Memory behavior
- unrelated Experimental CV features
- future semantic cartridges

Do NOT wire Object Memory into World Builder tonight.

However:

LAY GROUNDWORK where justified.

Create durable documentation describing for each planned cartridge:

- likely shared infrastructure it can reuse
- likely camera/sensor consumption pattern
- extension points World Builder created
- infrastructure still missing
- assumptions that must NOT be globally hard-coded

This should be architecture groundwork, not implementation.

World Builder must remain isolated enough that another cartridge can later use
a completely different CV/ML strategy.

==================================================
7. CONCURRENT IOS WORK
==================================================

A separate iOS effort is validating a sender candidate.

Known candidate:

branch:
ios/send-window-investigation

commit:
7508db1

known-good base:
ui/product-shell @ d9e513d

That candidate is being compiled/tested independently on the real Mac.

DO NOT modify the iOS repository.

DO NOT wait for it.

The readiness report concluded that World Builder experimentation is NOT gated
on achieving 10–12 FPS transport.

Current physical Tower delivery is approximately:

3.3 FPS

which gives approximately:

300 ms temporal spacing

and may already provide useful parallax.

World Builder must tolerate variable FPS.

Never assume constant frame spacing.

Use actual timestamps and sequence information where appropriate.

==================================================
8. SENSOR REALITY
==================================================

The physical glasses sensor must currently be treated as:

MONOCULAR RGB.

Meta DAT 0.9 investigation found VideoFrame essentially exposes:

- sampleBuffer
- makeUIImage()

and did NOT expose legitimate:

- camera intrinsics
- camera pose
- IMU
- LiDAR
- stereo depth
- hardware depth
- calibration data

Do not invent these.

Do not use Project Aria calibration.

Project Aria is a different product.

==================================================
9. THE NO-LIDAR / MONOCULAR SPATIAL PROBLEM
==================================================

The Ray-Ban Meta does NOT give us LiDAR.

Therefore recovering spatial structure from monocular RGB is one of the central
engineering problems of World Builder.

Explicitly investigate and implement the best justified combination of:

- learned monocular depth
- learned feed-forward geometry
- multi-view correspondence
- classical feature matching
- learned feature matching
- visual odometry
- relative camera motion
- keyframe graphs
- temporal consistency
- multi-view depth consistency
- graph optimization
- camera calibration
- relative-scale estimation
- scale-drift detection/correction
- confidence-weighted fusion
- loop closure foundations

Use subagents to challenge which combination is actually necessary.

Do NOT equate:

RELATIVE GEOMETRY

with:

METRIC SCALE.

Determine which components can establish:

- topology
- relative geometry
- relative depth
- camera relationships
- relative scale

versus:

- actual metric distance

Research legitimate ways metric scale might eventually be constrained through:

- calibrated camera parameters
- learned metric-depth models
- known-size references
- scene constraints
- multi-view optimization
- another evidence-supported method

Do NOT fabricate metric scale.

If true metric scale cannot yet be established:

World Builder MUST remain operational in an explicitly labeled RELATIVE-SCALE
coordinate system.

Persist enough information that a world can potentially be upgraded later when
better calibration or scale evidence becomes available.

==================================================
10. CAMERA CALIBRATION
==================================================

The readiness investigation established that OpenCV 5.0.0 already provides:

- CharucoBoard
- CharucoDetector
- calibrateCamera

with no additional dependency required.

The architecture must accept real camera calibration later.

You MAY implement Tower-side calibration tooling now if useful.

Calibration should be:

- versioned
- resolution-aware
- device/source-aware
- persisted independently from individual worlds where appropriate

Never invent Ray-Ban intrinsics.

If physical calibration is required, produce an exact future procedure for:

Ray-Ban
→ calibration target
→ captured frames
→ OpenCV calibration
→ validation
→ persisted calibration profile

==================================================
11. ARCHITECTURE DIRECTION FROM READINESS WORK
==================================================

The readiness investigation rejected the simplistic architecture:

frames
→ one-frame monocular depth
→ permanently fuse into authoritative point cloud

Do not resurrect it without evidence.

Preferred working direction:

incoming RGB
→ frame quality / tracking analysis
→ information-based keyframe decision
→ authoritative KEYFRAME GRAPH
→ pairwise / multi-view relationships
→ trajectory / pose relationships
→ graph refinement
→ future loop closure
→ DERIVED geometry
→ persistent world
→ visualization

The GRAPH / WORLD MODEL should remain authoritative.

A point cloud or other rendered geometry should generally be DERIVED.

Reason:

future loop closure or graph correction must be able to improve previously
estimated geometry.

Do not permanently bake early errors into an immutable spatial representation.

==================================================
12. POINT CLOUD IS NOT SACRED
==================================================

Point cloud is currently a convenient candidate visualization.

It is NOT mandatory.

Explicitly consider whether another representation better satisfies V1.

If you find a representation that is:

- easier
- more stable
- more correct
- more revisable
- more efficient

use it.

Possible representations may include:

- sparse landmarks
- keyframe graph
- surfels
- depth-backed keyframes
- voxel representation
- derived point cloud
- another justified representation

Do not introduce representation complexity without benefit.

==================================================
13. TWO-RATE ARCHITECTURE
==================================================

FRAME RATE and MAPPING RATE are different concepts.

Not every received frame should become a permanent observation.

Intermediate frames may support:

- tracking
- motion estimation
- quality scoring

Keyframes should be selected based on INFORMATION.

Candidate signals include:

- translation
- parallax
- rotation
- new coverage
- track survival
- match quality
- inlier ratio
- geometric conditioning
- image sharpness
- blur
- exposure
- tracking confidence
- elapsed time as fallback

Do not simply persist every Nth frame unless justified as a fallback.

==================================================
14. IMAGE PREPROCESSING / LINEAR FILTERING
==================================================

Explicitly investigate whether lightweight classical image-processing
techniques materially improve World Builder input quality.

Candidate techniques include:

- Gaussian / linear smoothing
- Sobel gradients
- Scharr gradients
- Laplacian operators
- Laplacian-based sharpness measurement
- blur detection
- controlled sharpening
- anti-alias filtering during resizing/downsampling
- other justified convolution kernels

Do NOT assume filtering helps.

Filtering may destroy exactly the high-frequency texture/corners needed for
tracking.

Sharpening may create artificial structure.

Benchmark:

RAW

versus:

PREPROCESSED

using downstream metrics such as:

- usable feature count
- track survival
- match count
- inlier ratio
- reprojection error
- blur rejection
- pose stability
- keyframe quality
- processing cost

In particular:

investigate whether cheap gradient/Laplacian-based quality measurements can
reject motion-blurred or low-information frames BEFORE expensive ML/geometry
processing.

Prefer:

CHEAP EARLY REJECTION

when it reliably prevents expensive bad work.

Do not permanently preprocess every frame unless measurements justify it.

==================================================
15. DEPTH / LEARNED GEOMETRY
==================================================

Previous project measurements found the earlier monocular depth path had
approximately:

6–8% temporal flicker

and unresolved scale limitations.

Therefore:

A SINGLE DEPTH PREDICTION IS EVIDENCE.

IT IS NOT GROUND TRUTH.

Learned depth/geometry may support:

- relative structure
- visualization
- initialization
- geometry proposals
- correspondence
- confidence-weighted evidence
- metric-scale hypotheses if legitimately supported by a model

Repeated observations from different viewpoints should refine, validate, or
reject individual predictions.

MULTI-VIEW CONSISTENCY should generally outrank one-frame confidence.

==================================================
16. MODEL / SLAM RESEARCH ALREADY COMPLETED
==================================================

The readiness run already researched candidate systems.

Do not repeat broad research.

Its practical recommendation favored a feed-forward/keyframe-graph direction.

DA3 was ranked highly because investigation found:

- Apache-2.0 checkpoints
- pip-installable
- <12 GB target
- no custom compilation

MASt3R-SLAM was technically attractive but operationally worse on the current
machine because it requires custom CUDA kernels and the host currently lacks a
working C++/CUDA compiler toolchain.

However:

DO NOT blindly choose DA3.

If implementation evidence shows:

- another model is simpler
- another model is more stable
- classical CV is sufficient
- a maintained existing package solves the problem
- a learned geometry model eliminates redundant stages

change course.

Document why.

==================================================
17. SIMPLICITY / COMPLEXITY CHALLENGE
==================================================

COMPLEXITY IS A COST.

Continuously challenge the architecture for unnecessary complexity.

If an approach provides equivalent or better:

- reconstruction quality
- robustness
- latency
- maintainability
- observability

with fewer:

- models
- processing stages
- dependencies
- GPU requirements
- calibration requirements
- state transitions
- persistence concepts
- custom algorithms

PREFER THE SIMPLER APPROACH.

Every major component must justify itself through:

1. measured improvement,
2. necessary correctness,
3. necessary architectural capability,
4. or strong evidence that it solves a known failure mode.

Examples:

If learned geometry makes a separate depth model redundant:

REMOVE THE REDUNDANT MODEL.

If a learned matcher replaces several fragile stages with equal/better
performance:

consider it.

If ORB/classical CV performs equally well at dramatically lower cost:

prefer classical CV.

If a Laplacian blur score eliminates bad frames before GPU inference:

prefer cheap rejection.

If an existing maintained library reliably solves a difficult problem:

strongly consider using it.

If a simpler persistence model preserves graph correction, future
multi-session mapping, and Object Memory integration:

prefer it.

Do NOT simplify by hiding uncertainty or producing geometrically dishonest
output.

==================================================
18. REQUIRED SIMPLICITY SUBAGENT
==================================================

Assign at least one independent reviewer/subagent to specifically ask:

"What can we delete?"

It should identify:

- redundant models
- unnecessary processing
- duplicate representations
- premature abstractions
- unnecessary ML
- unnecessary classical CV
- unnecessary persistence layers
- dependencies whose operational cost exceeds their value

Require explicit justification for complexity that remains.

==================================================
19. GPU ENVIRONMENT
==================================================

Hardware:

RTX 5070
12 GB VRAM

Intel i9
32 GB RAM

Readiness investigation found approximately:

10.5 GB GPU memory available.

Current environment:

torch 2.13.0+cpu

Historical project evidence:

torch 2.13.0+cu132 successfully used this RTX 5070 during previous CUDA depth
experiments.

Current host does NOT have a useful C++/CUDA compilation toolchain.

Do not install a giant compiler environment merely to support one algorithm.

You MAY restore a known-compatible CUDA PyTorch environment if necessary.

Prefer isolation.

Do not destroy the currently functioning Tower environment.

Document exact environment changes.

==================================================
20. WORLD BUILDER V1 FUNCTIONAL TARGET
==================================================

Build the strongest technically honest World Builder possible with current
evidence.

Target:

1. Create a world.

2. Start a mapping session.

3. Receive frames through existing Tower infrastructure.

4. Evaluate frames.

5. Reject useless/bad frames.

6. Select meaningful keyframes.

7. Maintain persistent keyframe/world state.

8. Maintain spatial/trajectory relationships where technically supportable.

9. Generate inspectable derived geometry/spatial representation.

10. Update world incrementally while mapping.

11. Expose incremental updates.

12. Stop cleanly.

13. Persist world.

14. Restart process/session.

15. Reload world.

16. Inspect reconstructed representation without original live session.

==================================================
21. PERSISTENCE
==================================================

A WORLD is a first-class Tower artifact.

It is NOT equivalent to a WebSocket session.

Expected conceptual entities:

WORLD

- stable world ID
- metadata/name
- schema version
- creation/update time
- coordinate semantics
- scale semantics
- calibration reference
- graph revision
- sessions

SESSION

- stable session ID
- timestamps
- source metadata
- keyframe membership

KEYFRAME

- stable keyframe ID
- source sequence
- timestamp
- image reference
- quality metadata
- graph relationships
- pose/transform when supported
- confidence

GEOMETRY

- derived representation
- revision
- source graph revision
- confidence/coverage

Design for future:

- loop closure
- graph correction
- relocalization
- multi-session refinement
- semantic anchors
- Object Memory

Do not over-engineer unused features.

==================================================
22. RETENTION
==================================================

Do NOT permanently store every frame by default.

Prefer intentional storage.

Likely persistent:

- world metadata
- session metadata
- selected keyframes
- graph
- trajectory/relationships
- calibration reference
- derived geometry
- confidence

Likely temporary/optional:

- rejected frames
- every raw frame
- intermediate depth
- debug artifacts

Storage growth must be bounded/observable.

==================================================
23. MULTI-SESSION FUTURE
==================================================

Full multi-session relocalization is NOT required tonight.

But V1 must preserve the ability to add it.

Use stable:

- world IDs
- session IDs
- keyframe IDs
- coordinate definitions
- graph revisions
- schema versions

Future desired behavior:

DAY 1:
map bedroom

DAY 2:
load bedroom

DAY 2:
relocalize into existing world

DAY 2 observations:
refine world

Do not implement all of that unless naturally justified.

==================================================
24. OBJECT MEMORY FUTURE CONTRACT
==================================================

Do NOT wire Object Memory tonight.

Future concept:

WORLD BUILDER = WHERE

OBJECT MEMORY = WHAT / WHEN

Potential future observation:

object identity
+ timestamp
+ world ID
+ spatial anchor
+ confidence

Preserve enough stable spatial identity to make this possible.

Do not decide unresolved bystander/person policy.

==================================================
25. LIVE OUTPUT / VIEWING
==================================================

World Builder should expose an incremental representation suitable for a future
viewer.

You are Tower-side.

DO NOT build the production iOS viewer tonight.

Design a clean event/API/artifact contract.

Provide a lightweight Windows/debug inspection mechanism if useful.

Possible outputs:

- point cloud
- trajectory
- graph
- HTML/WebGL viewer
- another appropriate visualization

Do not spend disproportionate effort on frontend polish.

==================================================
26. GEOMETRIC HONESTY
==================================================

Never claim accuracy the data cannot support.

Explicitly represent:

- calibrated
- uncalibrated
- metric
- relative-scale
- estimated
- low-confidence
- unknown

If the map is relative-scale:

say so.

If trajectory is non-metric:

say so.

If geometry is approximate:

say so.

A rough honest reconstruction is better than a beautiful fake one.

==================================================
27. FAILURE HANDLING
==================================================

Design for:

- insufficient features
- pure rotation
- motion blur
- textureless walls
- repeated patterns
- moving people
- reflections
- tracking loss
- missing frames
- variable FPS
- reconnect
- malformed image
- bad keyframe
- model failure
- GPU unavailable
- corrupted state
- interrupted writes
- process restart

One bad frame must not silently corrupt the world.

Prefer recoverable state transitions.

==================================================
28. MODULE CONTRACT / ROADMAP BOUNDARY
==================================================

The readiness report found:

- the current module contract cannot cleanly express World Builder geometry
- V1.1 lifecycle architecture remains deliberately BLOCKED

Therefore:

YOU MAY IMPLEMENT:

- complete World Builder engine
- storage
- processing
- experiments
- runtime
- APIs
- tests
- benchmarks
- live update contracts
- debug viewing
- generic shared infrastructure where justified

YOU MAY integrate with existing Tower frame flow where doing so does not violate
the blocked lifecycle contract.

BUT:

DO NOT silently rewrite the central lifecycle architecture simply to force
World Builder into production cartridge registration.

If production registration crosses that boundary:

STOP AT THE INTEGRATION BOUNDARY.

Leave a complete engine behind a clean interface.

Document the exact blocker.

That blocker does NOT prevent implementation of the engine.

==================================================
29. SUBAGENTS — GO USE THEM
==================================================

Use focused subagents aggressively but intelligently.

Potential tracks:

ARCHITECTURE
- convert readiness report into implementation slices
- challenge architecture

GEOMETRY
- keyframes
- graph
- correspondences
- pose
- scale
- loop-closure foundations

ML
- depth
- feed-forward geometry
- learned matching
- model selection

CLASSICAL CV
- ORB/features
- RANSAC
- optical flow
- linear filtering
- blur/quality
- calibration

GPU
- CUDA PyTorch
- performance
- VRAM

PERSISTENCE
- world/session/keyframe schema
- crash safety
- storage growth

RUNTIME
- frame ingestion
- mapping lifecycle
- incremental updates

TESTING
- correctness
- persistence
- failure cases
- mutation testing

SIMPLICITY
- identify unnecessary complexity
- propose deletions

ADVERSARIAL REVIEW
- try to break everything

Parallelize independent work.

Do not allow agents to blindly edit the same files concurrently.

Main agent owns architectural reconciliation.

==================================================
30. RESEARCH AUTHORITY
==================================================

Subagents MAY perform additional targeted research where implementation reveals
a genuine unknown.

Do not redo the entire readiness investigation.

Research should answer specific implementation questions.

Examples:

- Does library X actually support uncalibrated input?
- Does model Y produce metric or relative depth?
- Is dependency Z compatible with sm_120?
- Is algorithm A robust to pure rotation?
- What license does checkpoint B actually use?

Verify consequential claims.

==================================================
31. TESTING
==================================================

Establish baseline first.

Expected:

214 passed
3 skipped

Continuously test implementation slices.

Before completion:

run full Tower suite.

Add tests for important invariants including as applicable:

- world creation
- world persistence
- world reload
- session lifecycle
- keyframe identity
- keyframe selection
- graph persistence
- graph revision
- coordinate semantics
- scale semantics
- geometry derivation
- retention
- corruption
- interrupted writes
- variable timing
- missing frames
- malformed images
- tracking loss
- model unavailable
- GPU fallback
- deterministic persistence
- concurrency
- deletion
- schema evolution
- shared infrastructure isolation

Do not game test counts.

Use mutation/adversarial testing for critical persistence behavior where useful.

==================================================
32. BENCHMARKING
==================================================

Existing readiness work measured approximately:

ORB:
5.31 ms at 360×640

Do not erase existing evidence.

Benchmark meaningful stages:

- preprocessing
- blur/quality analysis
- tracking
- matching
- keyframe decision
- learned inference
- graph update
- geometry generation
- persistence
- total latency
- CPU
- GPU
- VRAM
- storage growth

Compare alternatives when the result can affect architecture.

Do not optimize before measuring.

==================================================
33. PHYSICAL DATA LIMITATION
==================================================

The readiness run found no stored real Ray-Ban footage on Tower.

Therefore:

DO NOT claim real physical reconstruction success tonight unless actual
physical data becomes available.

Synthetic/test/sample data is allowed where project rules permit it.

Clearly label:

SYNTHETIC

versus:

PHYSICAL.

Eventually real glasses footage is authoritative.

==================================================
34. DOCUMENTATION
==================================================

Leave durable documentation.

A fresh Claude session with no access to this conversation should understand:

- World Builder architecture
- why it was chosen
- rejected alternatives
- sensor assumptions
- no-LiDAR strategy
- depth/scale semantics
- calibration
- keyframes
- graph
- geometry
- ML
- classical CV
- preprocessing
- persistence
- confidence
- failure handling
- APIs
- shared infrastructure
- cartridge boundaries
- tests
- benchmarks
- limitations
- physical validation procedure
- future multi-session work
- future Object Memory integration
- future cartridge extension points

==================================================
35. FUTURE CARTRIDGE GROUNDWORK REPORT
==================================================

Create a durable document describing what this implementation means for future
cartridges.

For each planned cartridge, identify:

- reusable infrastructure now available
- likely camera-consumption style
- likely Tower-processing style
- infrastructure still missing
- which World Builder assumptions MUST NOT leak into it

Do not implement those cartridges.

==================================================
36. AUTONOMOUS DECISION AUTHORITY
==================================================

You may independently decide ordinary engineering matters such as:

- class structure
- filenames
- schemas
- internal APIs
- algorithms
- thresholds
- caches
- retention limits
- test structure
- fallback behavior
- model choice
- classical-vs-ML choice

Record consequential rulings.

STOP AND ASK only if necessary to:

- violate explicit architecture contracts
- decide unresolved privacy policy
- destructively migrate existing user data
- fundamentally change product experience
- introduce meaningful external recurring cost
- require unsupported hardware
- weaken a deliberate safety/privacy guarantee

==================================================
WORLD BUILDER V1 — ADDITIONAL PRODUCT REQUIREMENTS / STRETCH GOALS
==================================================

The following requirements were added after implementation began.

They are compatible with the current World Builder product direction, but they
must NOT destabilize or delay the core mapping engine unnecessarily.

Priority order:

1. calibration / fiducial groundwork
2. privacy-safe persisted/viewed imagery
3. recorded-path first-person inspection
4. true free-roam first-person only if geometry genuinely supports it

Core World Builder correctness remains more important than stretch-goal quantity.

==================================================
A. FIDUCIALS / CALIBRATION / METRIC EVALUATION
==================================================

The current implementation has already adopted calibration-gated geometry.

Continue that direction.

ChArUco should be supported as the primary development path for obtaining real
camera intrinsics from the Ray-Ban video stream.

Calibration must remain:

- device/source aware
- resolution aware
- versioned
- explicitly validated
- separate from fabricated/default intrinsics

Additionally investigate support for known-size environmental fiducials such as
AprilTag or ArUco markers.

IMPORTANT:

Environmental markers must NOT become a required dependency of World Builder.

Normal World Builder should remain capable of operating in honest
relative-scale / uncalibrated modes where necessary.

Initially prefer environmental markers for:

- ground-truth evaluation
- scale estimation experiments
- reconstruction accuracy measurement
- pose/geometry validation

rather than directly controlling the authoritative map.

A single marker detection must NEVER be allowed to arbitrarily rescale or
distort the world.

If marker-derived scale constraints are implemented, require evidence such as:

- valid marker identity
- sufficient image size
- complete/unoccluded corners
- low reprojection error
- multiple observations
- cross-frame consistency
- agreement with existing world evidence

Prefer:

relative world geometry
+
separate scale estimate / confidence

over allowing one observation to mutate the underlying graph.

The system should be able to expose states such as:

Scale: Relative
Scale calibration: Acquiring
Scale calibration: Metric / Locked
Scale confidence: Low / Medium / High
Scale calibration: Uncertain

Do not claim metric scale without legitimate evidence.

==================================================
B. PRIVACY — FACE REDACTION BEFORE PERSISTENCE / DISPLAY
==================================================

World Builder deals with wearable-camera imagery and must establish a strong
privacy boundary.

Preferred principle:

RAW FRAME
→ ephemeral perception / tracking / geometry
→ privacy filtering
→ persistence / user-facing imagery

If raw face pixels are useful for temporary CV operations such as:

- feature tracking
- geometry
- anonymous person tracking
- coarse head/face orientation

they may be processed transiently in memory where technically necessary.

However, persisted or user-facing imagery should blur/redact detected faces by
default whenever practical.

Do NOT persist identity merely because a face was detected.

Do NOT introduce face recognition as part of World Builder V1.

Derived non-identifying structured information may later include:

- anonymous track ID
- position
- coarse orientation
- confidence

but persistent human identity is outside this mission.

If face redaction is implemented, strongly prefer a reusable privacy boundary
that future cartridges can consume rather than embedding privacy behavior deep
inside World Builder-specific geometry code.

However:

do not create an oversized generic privacy framework tonight.

Keep it small and evidence-driven.

If reliable redaction cannot be implemented without threatening core World
Builder completion, document the integration boundary and make it the first
post-V1 privacy task.

==================================================
C. FIRST-PERSON WORLD INSPECTION
==================================================

A major desired World Builder viewing experience is first-person inspection.

There are TWO distinct levels.

LEVEL 1 — RECORDED-PATH FIRST-PERSON REPLAY

This is the preferred V1/stretch implementation.

Because World Builder already maintains keyframes and camera/keyframe
relationships, preserve enough information so a viewer can:

- display the reconstructed world in overview
- display the recorded camera trajectory
- select a position/keyframe along that trajectory
- enter the original wearer perspective from that observation
- step forward/backward through neighboring keyframes
- return to overview

This mode may use the original persisted redacted keyframe imagery plus the
estimated camera pose/relationship information.

It must remain honest about pose/scale/calibration quality.

LEVEL 2 — TRUE FREE-ROAM FIRST PERSON

Only implement this if the actual derived geometry is sufficiently coherent.

This would allow a virtual camera to move independently through the
reconstructed space.

Do NOT implement fake free-roam merely because a 3D camera controller is easy.

If geometry is sparse, unstable, or incomplete, recorded-path replay is the
correct V1 experience.

Preserve the architecture so a future viewer can support modes such as:

Overview
Recorded Path
First Person
Free Roam

without requiring changes to the authoritative world graph.

==================================================
D. REPRESENTATION / VIEWER CONTRACT
==================================================

World Builder should persist enough information for future iOS/desktop viewers
to support:

- orbit/pan/zoom overview
- trajectory visualization
- keyframe locations
- recorded-path first-person replay
- derived geometry
- confidence / unknown areas
- calibration / scale status

Do NOT make the Tower engine depend on a particular frontend renderer.

The authoritative world representation must remain separate from viewer state.

==================================================
E. STRETCH-GOAL GATE
==================================================

Do not start these additions prematurely.

First complete the core World Builder engine already in progress:

- frontend
- frame-quality analysis
- keyframe policy
- engine
- persistence
- inspection/debug output
- capture integration
- calibration
- tests
- adversarial review

Then evaluate the three additions above against the actual architecture.

Implement them during this run ONLY if:

1. the core World Builder definition of done is already satisfied or clearly
   protected,
2. the addition fits cleanly,
3. it does not violate blocked lifecycle/module architecture,
4. it can be meaningfully tested in the available environment,
5. it materially improves the Thursday MVP.

Otherwise:

document the exact follow-up implementation plan and STOP with the core engine
strong rather than weakening it to fit stretch goals.

==================================================
F. REQUIRED CHALLENGE
==================================================

Ask independent reviewers/subagents to challenge these additions.

Specifically ask:

- Are fiducials actually useful beyond evaluation?
- Can marker scale poison the map?
- Is face redaction best implemented inside World Builder or as shared
  infrastructure?
- Does face redaction interfere with feature tracking or geometry?
- Is recorded-path replay almost free given the existing graph?
- Does true free-roam provide real value with the geometry we can currently
  reconstruct?
- Is there a simpler way to achieve the same user experience?

Do not implement an idea merely because the user thought it sounded cool.

Make each feature earn its complexity.

==================================================
37. WORLD BUILDER V1 DEFINITION OF DONE
==================================================

As far as Tower can honestly establish:

1. World creation works.

2. Mapping session starts.

3. Frames enter World Builder.

4. Frames are evaluated.

5. Bad/useless frames can be rejected.

6. Meaningful keyframes are selected.

7. Persistent world/keyframe graph exists.

8. Spatial relationships are represented where supportable.

9. Scale/calibration state is explicit.

10. Derived inspectable geometry exists.

11. World updates incrementally.

12. Incremental updates are exposed.

13. Stop is clean.

14. World persists.

15. Process restart does not destroy world.

16. World reload works.

17. Saved world can be inspected.

18. Storage behavior is intentional/bounded.

19. Failures do not silently corrupt world.

20. Full Tower suite passes.

21. New World Builder tests pass.

22. Meaningful benchmarks are recorded.

23. Independent review has no unresolved critical correctness/data-loss issue.

24. Architecture is documented.

25. Physical-only claims are explicitly deferred.

26. Shared infrastructure remains cartridge-neutral.

27. Future cartridges have documented extension points.

If production cartridge registration is blocked by the lifecycle contract:

the ENGINE may still satisfy V1 for this run.

Document the integration boundary.

==================================================
38. FINAL ADVERSARIAL REVIEW
==================================================

Before declaring completion, dispatch independent reviewers.

At least one should attack correctness:

- geometry
- scale
- calibration
- graph
- persistence
- concurrency
- corruption
- recovery

At least one should attack complexity:

- what can be removed?
- what is redundant?
- what is premature?
- what dependency is unjustified?
- what ML is unnecessary?
- what classical stage is unnecessary?

At least one should attack architectural leakage:

- did World Builder contaminate generic camera behavior?
- did shared infrastructure become World Builder-specific?
- did we accidentally constrain future cartridges?

Fix justified findings.

==================================================
39. FINAL REPORT
==================================================

Report:

1. Starting state.
2. Branch.
3. Plan.
4. Subagents used.
5. Architecture implemented.
6. Deviations from readiness report.
7. Better ideas discovered.
8. SIMPLIFICATIONS DISCOVERED.
9. COMPLEXITY WE KEPT AND WHY.
10. No-LiDAR strategy.
11. Depth strategy.
12. Scale strategy.
13. Calibration strategy.
14. Linear-filtering/preprocessing findings.
15. Keyframe strategy.
16. Graph model.
17. Coordinate semantics.
18. Geometry representation.
19. ML components.
20. Classical CV components.
21. GPU changes.
22. Persistence architecture.
23. Retention.
24. Session lifecycle.
25. Incremental update contract.
26. Failure/recovery behavior.
27. Shared infrastructure created.
28. Why each shared abstraction is genuinely generic.
29. Future cartridge groundwork.
30. Multi-session readiness.
31. Object Memory future contract.
32. Files changed.
33. Tests added.
34. Full-suite result.
35. Benchmarks.
36. Review findings.
37. Fixes from review.
38. Known limitations.
39. Physical Ray-Ban validation still required.
40. Production cartridge integration status.
41. Blockers.
42. Commits.
43. Final Git state.
44. Exact first physical World Builder test procedure.
45. Recommended next step after physical validation.

==================================================
40. HARD STOP
==================================================

Once World Builder V1 reaches the definition above OR reaches a legitimate
architecture/product/hardware blocker:

STOP.

Do NOT proceed into:

- Object Memory integration
- Accessibility implementation
- Visual Q&A implementation
- Environmental Memory implementation
- multi-room mapping
- photorealistic reconstruction
- NeRF
- Gaussian splatting
- production iOS World Builder UI
- unrelated roadmap milestones

Leave us:

ONE strong World Builder

PLUS:

GOOD shared infrastructure

PLUS:

CLEAN groundwork for the remaining cartridges.

Do not leave us five half-built products.

BEGIN NOW:

1. verify master @ b591e30,
2. verify baseline,
3. read the completed readiness report,
4. read relevant project rules,
5. create the World Builder feature branch,
6. dispatch focused planning/challenge subagents,
7. produce and independently review the implementation plan,
8. then build autonomously.