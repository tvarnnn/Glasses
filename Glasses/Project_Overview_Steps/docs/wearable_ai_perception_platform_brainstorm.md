# Wearable AI Perception Platform

## Brainstorm README

### Core Idea

Build a modular wearable AI platform using Ray-Ban Meta Gen 2 glasses as
the **sensor/input layer**, an iPhone/Swift app as the **communication
bridge**, and a tower PC as the **compute layer**.

The glasses should do as little heavy computation as possible. The tower
handles computer vision, AI inference, storage, spatial reasoning, and
future applications.

``` text
Ray-Ban Meta Gen 2
        |
   camera / mic
        |
       DAT
        |
        v
Custom Swift iOS App
        |
   Wi-Fi / 5G
        |
        v
Tower PC / GPU Server
        |
  CV / AI / Memory
        |
        v
Custom Application
        |
     response
        |
        v
Swift App -> Glasses -> User
```

## Design Philosophy

Treat the glasses as a wearable sensor endpoint rather than the computer
doing the intelligence.

The architecture should separate:

1.  **Sensor Layer** --- Ray-Ban camera, microphones, speakers, and any
    other sensors DAT eventually exposes.
2.  **Transport Layer** --- Swift application receives data through Meta
    DAT and forwards it to the tower.
3.  **Compute Layer** --- Tower performs expensive inference and
    processing.
4.  **Perception Layer** --- Shared CV/audio/spatial capabilities.
5.  **Application Layer** --- Swappable projects built on the common
    platform.

The long-term goal is to make applications interchangeable without
rebuilding the glasses integration.

## Proposed Architecture

``` text
wearable-platform/
|
|-- ios-bridge/
|   |-- DAT integration
|   |-- glasses connection
|   |-- stream controls
|   |-- tower networking
|   |-- telemetry
|
|-- server/
|   |-- transport/
|   |-- perception/
|   |   |-- object_detection/
|   |   |-- tracking/
|   |   |-- ocr/
|   |   |-- depth/
|   |   |-- audio/
|   |   `-- spatial/
|   |
|   |-- relevance/
|   |-- world_model/
|   |-- memory/
|   |-- models/
|   `-- applications/
|       |-- object_memory/
|       |-- world_mapper/
|       |-- accessibility/
|       |-- visual_qa/
|       `-- experiments/
|
`-- docs/
```

## Swift App

The custom Swift app acts as the control plane and communication
gateway.

Potential interface:

``` text
GLASSES LAB

Glasses:        Connected
Tower:          Online
Active Module:  Object Memory
Stream:         504x896 @ 15 FPS
Latency:        -- ms
Frames Sent:    --
Relevant:       --
Dropped:        --
Battery:        --

[ START SESSION ]
```

Responsibilities:

-   Connect to the glasses through Meta DAT.
-   Start/stop sensor sessions.
-   Receive camera/audio data.
-   Forward sensor data to the tower over local Wi-Fi or cellular data.
-   Receive results from the tower.
-   Return audio/feedback to the glasses.
-   Select which tower-side application is active.
-   Display latency, FPS, connection status, dropped frames, battery
    information, and other telemetry when available.

The phone should perform minimal inference. It is primarily a bridge.

## Tower

The tower is the brain.

Potential workloads:

-   OpenCV
-   Object detection
-   Object tracking
-   OCR
-   Segmentation
-   Monocular depth estimation
-   Visual odometry
-   SLAM / Structure from Motion
-   Speech-to-text
-   Local multimodal models
-   Local LLM/agent
-   Persistent memory
-   World modeling
-   Relevance classification
-   GPU inference

The architecture should allow these capabilities to be shared across
applications.

## Relevance Classifier

Continuous first-person video produces enormous amounts of redundant
information.

Instead of processing and storing everything equally:

``` text
Sensor Data
    |
    v
Lightweight Relevance Layer
    |
    +------ Low relevance -> discard / sample / summarize
    |
    `------ High relevance -> expensive inference / memory / mapping
```

Possible inputs:

-   Visual change
-   Detected objects
-   OCR text
-   Motion
-   Speech transcript
-   Current application
-   Novelty compared with previous observations
-   Current spatial location
-   Object movement

Possible outputs:

-   Ignore
-   Process cheaply
-   Run full perception stack
-   Save observation
-   Add to world model
-   Upload high-quality keyframe

This could eventually become a learned relevance model trained from
collected sessions.

## Potential Applications

### 1. Object Memory

Continuously observe objects and maintain a temporal history.

Example:

``` text
16:02  Wallet -> desk
16:18  Keys -> kitchen counter
16:46  Backpack -> car
17:13  Charger -> classroom
```

User:

> Where did I last see my charger?

System queries the observation history and responds through the glasses.

This may be a strong first CV project because it requires detection,
tracking, temporal reasoning, relevance filtering, and persistent memory
without requiring the full long-term platform.

### 2. World Mapper

Collect first-person visual observations while walking and reconstruct
portions of the environment.

Potential technologies:

-   Feature detection/matching
-   Optical flow
-   Visual odometry
-   Visual SLAM
-   Structure from Motion
-   Monocular depth
-   Point clouds
-   Gaussian splatting / other reconstruction techniques

Multiple walks could progressively improve a persistent spatial
representation.

### 3. Accessibility

Build assistive perception for users with visual impairments.

Potential capabilities:

-   Detect obstacles.
-   Identify doors/stairs/chairs.
-   Read signs and labels.
-   Describe scenes.
-   Locate requested objects.
-   Provide spatial descriptions through audio.
-   Combine current perception with previously mapped environments.

Any safety-related functionality must be treated as experimental
assistive information rather than a primary safety system unless
appropriately validated.

### 4. Visual Q&A / Reading

User looks at something and asks a question.

``` text
Camera
  |
OCR / CV
  |
Local multimodal model
  |
Answer
  |
Glasses audio
```

Possible legitimate uses include reading signs, documents, menus,
labels, instructional material, and accessibility assistance.

### 5. Environmental / Physical-World Search

Long-term idea:

> Search for things that happened in the physical world.

Examples:

-   Where did I leave my keys?
-   What was written on the sign I passed earlier?
-   Have I seen my backpack today?
-   What objects changed position in this room?
-   What building was I looking at?

## Remote Compute

The tower does not need to be physically near the glasses.

``` text
Glasses
   |
  DAT
   |
iPhone
   |
 5G/LTE
   |
Internet
   |
Home Tower
   |
GPU inference
   |
Internet
   |
iPhone
   |
Glasses
```

This makes the tower a privately hosted remote inference server.

Important engineering problems:

-   Cellular bandwidth
-   Latency
-   Connection loss
-   Authentication/encryption
-   Battery consumption
-   Frame compression
-   Adaptive frame rates
-   Backpressure
-   Dropped frames
-   Privacy

## Streaming Target

Initial experiment:

``` text
Resolution:       504 x 896
Target FPS:       15
Target Duration:  20-30 minutes
Transport:        DAT -> iPhone -> tower
```

Benchmark:

-   Requested FPS
-   Actual FPS
-   Total frames
-   Dropped frames
-   Disconnects
-   End-to-end latency
-   Upload bandwidth
-   Data transferred
-   Glasses battery consumption
-   Phone battery consumption
-   Thermal behavior
-   Tower GPU utilization

At 15 FPS, a 30-minute session generates approximately **27,000
frames**.

## Adaptive Streaming

Continuous 30 FPS may be unnecessary.

Potential operating modes:

``` text
IDLE
2 FPS
  |
interesting event
  v
TRACKING
15 FPS
  |
active high-detail task
  v
HIGH RATE
24-30 FPS
  |
task complete
  v
IDLE
```

This could reduce bandwidth, storage, compute, and battery usage.

## Meta's Role

### V1: DAT

Meta remains responsible for the underlying glasses platform:

-   Stock firmware
-   Hardware drivers
-   Device provisioning/pairing
-   DAT access
-   Supported hardware interfaces

Our system owns:

-   Networking from the custom app to the tower
-   Computer vision
-   AI inference
-   Local models
-   Storage
-   Memory
-   World model
-   Applications
-   Server infrastructure
-   Application-level behavior

Meta AI does **not** need to be the reasoning engine for the custom
applications.

### Future Research: Remove Meta Dependency

Possible later research track:

``` text
V1: Glasses -> DAT -> Swift -> Tower
V2: Glasses -> Custom Desktop/Network Client -> Tower
V3: Glasses -> Custom Firmware -> Tower
```

The main platform should abstract its sensor source so replacing DAT
later does not require rebuilding perception/application logic.

Example conceptual interface:

``` text
SensorSource
    |
    +-- DATBridge
    +-- DirectRayBanClient
    `-- CustomFirmwareStream
```

Custom firmware/rooting is **not required for V1** and carries
significantly greater warranty and bricking risk.

## Reversibility

The initial project should remain non-destructive.

DAT/Developer Mode does not require replacing the glasses firmware. The
daily-driver glasses should remain stock.

Rule:

> Do not modify/flash the production glasses firmware unless a reliable
> recovery path has first been independently established.

Offline firmware research can remain a separate future project.

## CV Course: Two-Month Scope

The computer vision course is the reason to start building the platform.

Do **not** attempt the entire vision during the course.

Recommended objective:

### Wearable Platform V0.1 + One CV Application

Milestone 1:

> Receive one camera frame from the glasses in the custom Swift app.

Milestone 2:

> Forward one frame from Swift to the tower and process it with OpenCV.

Milestone 3:

> Establish a stable continuous stream.

Milestone 4:

> Benchmark approximately 15 FPS for 20-30 minutes.

Milestone 5:

> Implement the selected CV application.

Strong candidate:

**First-Person Object Memory**

``` text
Ray-Bans
   |
Swift / DAT
   |
Tower
   |
Object Detection
   |
Tracking
   |
Relevance Filtering
   |
Temporal Memory
```

Course concepts can be incorporated as they are learned rather than
forcing every possible CV technique into V1.

## Immediate Next Steps

1.  Set up Meta Wearables developer access and Developer Mode.
2.  Install/explore the official DAT iOS SDK and examples.
3.  Create a minimal Swift project.
4.  Connect to the Gen 2 glasses.
5.  Display one live camera frame.
6.  Build a minimal tower receiver.
7.  Send one frame from the phone to the tower.
8.  Process the frame with OpenCV.
9.  Establish continuous streaming.
10. Benchmark the pipeline before choosing more ambitious features.

## Guiding Principle

**Get the pipe working first.**

The first major success criterion is not an LLM, SLAM, or accessibility
system.

It is:

``` text
Ray-Ban Camera
      ->
Custom Swift App
      ->
Network
      ->
Tower PC
      ->
OpenCV
```

Once that works reliably, everything else becomes a module built on top
of the same foundation.

## Long-Term Vision

Build a modular wearable perception platform where consumer smart
glasses act as a first-person multimodal sensor endpoint, a mobile
application provides connectivity, and privately hosted GPU
infrastructure transforms continuous sensory observations into useful
representations of the physical world.

The end goal is not one smart-glasses application.

The goal is a **general platform for experimenting with wearable
computer vision, multimodal AI, spatial computing, accessibility,
environmental memory, and physical-world agents.**
