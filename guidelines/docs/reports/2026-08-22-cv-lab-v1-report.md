# Experimental CV Lab V1 — Implementation Report

Status: **IMPLEMENTED, MEASURED ON SYNTHETIC IMAGERY.** Branch
`cartridge/experimental-cv-lab-v1`, off `world-builder/v1`.

Every number below is a real measurement of this code on this machine.
The imagery driving it is **rendered**, so a *cost* here is meaningful
guidance and a *content* measurement is not a statement about any real
room. The standing acceptance gate is unchanged: nothing counts as
validation for the platform's own camera until it runs on real DAT
footage.

---

## 1. What the Lab could not do, and now can

The Lab shipped at V0.9 and has been the only cartridge on the live frame
path ever since. It had two structural problems that its own module doc
made visible:

**Every experiment had to reduce itself to one number.** `ExperimentResult`
was five scalars, one of which was the answer. Frame quality has six
things to say; optical flow four; detection a count, a class breakdown
and a score distribution. The doc's own rule — *every experiment must
expose useful measurements* — was not satisfiable.

`CARTRIDGE-GROUNDWORK.md` listed "a non-scalar result channel" as missing
infrastructure that four other cartridges were waiting on. It is the
Lab's own type. This is the cartridge that owns the file, so fixing it
here is not scope creep.

**A stateful experiment cost a whole `Module` subclass.** There were two
of them — `ExperimentalCVModule` and `DepthEstimationModule` — sharing a
single descriptor id, because the depth experiment holds a model across
frames. V1 adds two more stateful experiments; on the old design that
would have meant four near-identical classes.

---

## 2. The two changes that made the rest possible

### 2.1 `metrics`, a measurement channel

```python
ExperimentResult(
    result_value: float,      # the HEADLINE, mandatory
    result_label: str,
    processing_ms: float,
    stage_ms: dict[str, float],
    mean_intensity: float | None = None,
    metrics: dict[str, float] = {},
)
```

The headline stays mandatory on purpose. It is a discipline rather than a
limitation: an experiment that cannot name its single most important
number has not decided what it is measuring. A test asserts that every
experiment's headline also appears in its own `metrics`, so a client may
read either and they can never disagree.

On the wire, `frame_result` gains `metrics` **only when non-empty**. A
client that has never heard of the field is unaffected, which is the rule
`docs/agent-handoffs/TOWER-TO-IOS.md` §7 states for any change while the
result type is still scalar-shaped. `baseline` predates the channel and
does not grow an empty object.

**Deliberately `name -> number` and nothing richer.** This is a
measurement channel. A structured result — a detection list, a geometry
delta, a world update — needs the module-contract work that is blocked at
V1.0/V1.1, and widening this type would have been a quiet way of
pretending otherwise.

### 2.2 One protocol, one module

An experiment is now anything with `name`, `load(settings)`, `run(bytes)`
and `release()`. The registry maps a name to a **factory**, not an
instance: a registry of instances would load model weights in any process
that so much as imported the module.

`tower/modules/depth_cv.py` was **deleted**. The refactor removes a class
rather than adding one, which is the test any abstraction of this kind
should have to pass.

`StatelessExperiment` adapts a plain function, so a stateless experiment
still costs exactly one function to write.

**What this deliberately did NOT resolve:** `_do_load()` is still
synchronous. The unbounded-blocking lifecycle gap is a standing decision
gate that also blocks Object Memory Tasks 4–8, and a refactor is not the
place to quietly pick an option in it.

---

## 3. The experiment set, and why each one is there

| Experiment | Headline | 640×360 | State | Why it exists |
|---|---|---|---|---|
| `baseline` | `mean_intensity` | 1.0 ms | — | The V0.7 wire-compatibility reference |
| `edge_detection` | `edge_density` | 1.5 ms | — | The V0.9 first experiment |
| `frame_quality` | `sharpness_laplacian_var` | 5.6 ms | — | Cheap early rejection, the question every cartridge has |
| `feature_detection` | `keypoint_count` | 4.2 ms | — | Does a real indoor scene give us anything to track |
| `optical_flow` | `median_flow_px` | 4.6 ms | previous frame | Apparent motion, measured independently of any cartridge's tracker |
| `redaction_impact` | `region_keypoint_retention` | 4.9 ms | — | What privacy filtering costs the geometry after it |
| `object_detection` | `detections` | 35.3 ms | model | Scene Understanding must choose a detector; the promotion path says measure here first |
| `depth` | `mean_relative_depth` | 26.0 ms | model | The V0.9.1 baseline, moved onto the protocol |

### Why `feature_detection` reports coverage as well as a count

A count alone is misleading. A thousand keypoints piled into one corner
is a worse frame for geometry than three hundred spread evenly, because a
solver needs constraints from across the view. `spatial_coverage` — the
fraction of an 8×8 grid holding at least one keypoint — makes that
distinguishable. Measured on a deliberately clumped frame: **0.09
coverage against 0.59** for a spread one, with both carrying real texture.

### Why sparse optical flow, with the rejected alternative kept

| Resolution | sparse LK | dense Farneback | multiple |
|---|---|---|---|
| 640×360 | 3.45 ms | 25.82 ms | **7.5×** |
| 896×504 | 6.67 ms | 51.91 ms | **7.8×** |
| 1280×720 | 12.91 ms | 115.11 ms | **8.9×** |

Same headline question, one answer good enough. Dense flow stays in the
benchmark rather than becoming a comment saying "dense was slower" — a
rejected option is only a decision for as long as its evidence survives.

### Why `object_detection` is here and not in Scene Understanding

The module doc's promotion path is *experiment → measured success →
dedicated module*. Scene Understanding has to choose a detector, and this
is where that choice gets its numbers. `ssdlite320_mobilenet_v3_large`
with COCO weights costs **no new dependency** — torchvision was already
in the `ml` extra — and 13.4 MB of weights.

The most useful measured result for the next cartridge:

| Resolution | total | inference | decode |
|---|---|---|---|
| 640×360 | 35.30 ms | 30.28 ms | 0.61 ms |
| 896×504 | 35.54 ms | 31.75 ms | 1.53 ms |
| 1280×720 | 37.26 ms | 30.86 ms | 2.92 ms |

**Detection cost is essentially independent of input resolution**, because
the model resizes to 320 internally. Sending a higher-resolution frame to
this detector buys nothing and costs only decode. That is a real
constraint on any Scene Understanding design and it was not obvious in
advance.

### Why there is no face detection

Not a judgement call — a verified absence. This OpenCV 5 build has **no
`CascadeClassifier`**. `FaceDetectorYN` exists as an API but ships **no
model**, and a search of the installed `cv2` package finds zero `.onnx`,
`.xml`, `.caffemodel` or `.pb` files. There is also no face imagery
anywhere to validate against.

`redaction_impact` measures the *consequence* of redaction honestly
instead: it blurs a fixed central rectangle roughly the size and position
of a face at conversational distance, and reports what the downstream
detector loses. Its `boundary_fraction` is the number that matters most —
survivors sitting on the blur boundary look trackable and describe an
artefact rather than the scene.

### What was rejected for V1

| Rejected | Why |
|---|---|
| Face detection | Verified unavailable, above |
| Dense optical flow as an experiment | 7.5–8.9× the cost for the same headline. It is a benchmark comparison, which is where a rejected alternative belongs |
| Semantic/instance segmentation, tracking-by-detection, image retrieval, novelty detection | All in the module doc's candidate list. None answers a question another cartridge has **today**, and adding them is exactly the "random collection of models" the brief forbids |
| A GPU variant of anything | torch is CPU-only on this host and there is no C++/CUDA compiler. A GPU number we cannot produce would be a fabrication |
| A new dataset-recording mechanism | `tower/capture.py` already is one — shared, bounded, privacy-reviewed. The Lab points at it |
| A general structured result type | Needs the blocked module contract. Widening `metrics` beyond numbers would have been a quiet way of pretending otherwise |

---

## 4. Measured costs

Full sweep, `scripts/cv_lab_benchmark.py`, 20 repetitions after an untimed
warm-up, synthetic imagery:

| Experiment | 640×360 | 896×504 | 1280×720 |
|---|---|---|---|
| `baseline` | 1.00 ms | 1.61 ms | 3.40 ms |
| `edge_detection` | 1.51 ms | 2.34 ms | 4.38 ms |
| `feature_detection` | 4.21 ms | 5.76 ms | 9.31 ms |
| `redaction_impact` | 4.90 ms | 6.44 ms | 9.91 ms |
| `optical_flow` | 4.62 ms | 8.43 ms | 16.37 ms |
| `frame_quality` | 5.61 ms | 10.09 ms | 19.66 ms |
| `depth` | 26.01 ms | 28.83 ms | 34.51 ms |
| `object_detection` | 35.30 ms | 35.54 ms | 37.26 ms |

For context: the glasses currently deliver ~3.3 fps, a ~300 ms interval.
Every classical experiment runs at under 2% duty cycle at the delivered
resolution and neither model-backed one exceeds 12%. **Nothing in the Lab
is compute-bound today**, and no effort was spent optimising any of it.

---

## 5. Evaluation, not just instrumentation

The module doc requires hypothesis / dataset / metric / baseline / result.
The World Builder review's test-quality finding applies with full force
here: **every assertion compares against something known independently of
the code under test.**

| Claim | Independent truth it is checked against |
|---|---|
| Sharpness measures sharpness | A deliberately Gaussian-blurred copy of the same frame must score under half |
| Entropy measures information | A flat frame must score under 2 bits; a textured one at least 3 bits more |
| Exposure metrics measure exposure | An all-white frame must report >90% overexposed; a mid-grey one under 1% |
| Keypoints measure texture | A blank frame must yield fewer than 5; a textured one more than 100 |
| Coverage measures spread | A clumped frame must score under 0.2 and a spread one over 0.4, with both carrying real features |
| Flow measures camera motion | A **rendered sideways walk** must produce flow within 25° of horizontal, with coherence above 0.8 |
| Flow scales with motion | A 0.20 m step must produce more than twice the flow of a 0.05 m step |
| Redaction removes what we redacted | The rectangle's coordinates are ours; the pixels that actually changed must lie inside it |
| Detection does not hallucinate | Blank, noise and non-object shape frames must yield **zero** confident COCO detections |
| Cost grows with resolution | More pixels cannot be cheaper |

---

## 6. Isolation

Three boundary tests, AST-level:

- No file under `tower/experiments/` and not
  `tower/modules/experimental_cv.py` may import `tower.world_builder` or
  `tower.object_memory`. The Lab's job is to **measure** properties World
  Builder holds private opinions about; importing that opinion would
  restate a cartridge's answer instead of measuring the property, and a
  threshold change on the cartridge side would silently move a
  measurement. It would also put a sandbox that may be thrown away
  upstream of a persistent world.
- No experiment may call a write primitive. The descriptor declares
  `persists_data=False` and that declaration is what
  `06-PRIVACY-DATA.md` is enforced against.
- Shared transport (`routes/`, `frames.py`, `metrics.py`) may not import
  an experiment implementation. The transport may know the *shape* of a
  result; a transport that special-cased `depth` would make the next
  experiment a transport change.

---

## 7. Privacy posture

Unchanged and still true: `persists_data=False`,
`retains_raw_imagery=False`, `transmits_externally=False`, enforced by
test rather than by intention.

Two things worth naming:

- `optical_flow` holds one grayscale frame of wearer imagery in memory
  between calls. `release()` drops it, and a test asserts that — a stopped
  experiment must not keep imagery alive.
- The experiment outlives the WebSocket session, because the module is
  process-scoped. A second wearer session inherits the first session's
  last frame as its flow reference. That is real, and a test records it
  as current behaviour rather than asserting a reset that does not
  happen. For a measurement tool a surprising carry-over would silently
  corrupt a measurement, so it is documented rather than hidden.

`object_detection` produces **no identity**. It reports counts by COCO
class and score statistics, nothing more, and persists nothing.

---

## 8. Limitations

- **Everything is synthetic.** The rendered room contains no COCO object,
  which is why `object_detection` reports zero detections in the
  benchmark — correct, and useless as evidence about a real room.
- **`redaction_impact` blurs a fixed rectangle, not a face.** It measures
  what redaction costs; it does not measure what redacting a *face*
  costs, because nothing here can find one.
- **No GPU numbers.** torch is CPU-only on this host.
- **The metrics channel is numbers only.** By design, but it means an
  experiment that genuinely needs to return a list still cannot.
- **`spatial_coverage` uses a fixed 8×8 grid.** Coverage is therefore
  comparable across frames of the same aspect ratio and not obviously
  across very different ones.


---

## 9. Adversarial review — findings and fixes

Two independent reviewers were dispatched: one told to break the Lab, one
told to ask only *what can we delete?*. Both found real defects. The
correctness reviewer's headline finding was independently reproduced by a
probe run here before its report arrived, which is the only reason it
appears twice in the evidence below.

### 9.1 BLOCKER — a 1-pixel-thin frame permanently killed CV processing

`cv2.ORB_create().detect()` builds an image pyramid whose internal
`cv2.resize` asserts on a non-positive scale when **either dimension is
exactly 1**. Measured across every `(h, w)` from 1 to 32: ORB fails if and
only if a dimension is 1, and succeeds at 2×1000 and 1000×2. So the floor
is **2**, chosen from the measurement.

The severity is not the crash. It is what the crash means:

- `ModuleContainer.process` treats any exception that is not a
  `FrameProcessingError` as a **module** failure;
- `mark_failed()` is terminal — FAILED can never transition back to
  UNLOADED;
- the container is built **once** at process start, with no swap path.

So one such frame did not drop one frame. It ended CV processing for
every subsequent frame of every subsequent session, for the life of the
server process. Reproduced end to end over a real WebSocket:

```
frame 1 (64x64) -> frame_result
frame 2 (1x64)  -> cv2.error, module marked FAILED
frame 3 (64x64) -> frame_error: module_unavailable
```

**And it was reachable.** A 1×64 JPEG is not malformed — merely useless.
`tower/frames.py` validates a frame with `Image.open(...).size`, which
parses the JPEG header, and a 1-pixel-tall image passes every check the
transport makes.

**Fixed:** one shared `_decode` helper enforces a minimum dimension and
raises `FrameProcessingError`. `feature_detection` and `redaction_impact`
pass `ORB_MIN_DIMENSION`.

### 9.2 MAJOR — three decode failure modes, only one of them guarded

The `if image is None` check every experiment carried covers exactly one
of three ways decoding fails:

| Input | What actually happens |
|---|---|
| Truncated file | `imdecode` returns `None` — the guard works |
| **Empty buffer** | `imdecode` **raises** `!buf.empty()`; the guard never runs |
| **Valid but 1px** | Decodes cleanly, then kills ORB |

**Reachability, measured rather than assumed.** A real 160×120 JPEG cut
to **800 bytes** is opened by PIL (`.size` returns `(160, 120)`) and
decoded by OpenCV to `None`. Cut to 400 bytes, PIL rejects it too. So the
truncated case genuinely arrives at the module; the empty and garbage
cases do not, today, because PIL catches them first — but any other
caller of `Experiment.run()` has no such gate, and a contract that is
true only because of a check in a different package is not a contract.

**Fixed:** `_decode` handles all three, and `frame_processing.py` (which
`baseline` goes through) carries the same guard inline — inline rather
than by importing the helper, because it is shared infrastructure and
must not import a cartridge.

### 9.3 MAJOR — `depth` crashed the same way on an extreme aspect ratio

MiDaS's transform resizes, and its internal `cv2.resize` asserts on
1×1000 and 1000×1. 1×1 and 16×16 are fine, so this is about the **ratio**,
not the size. Same terminal consequence as 9.1. Fixed with a
`cv2.error → FrameProcessingError` translation at the preprocess stage.
`object_detection` was tested against the same inputs and does not need
one — torchvision's transform is defensive.

### 9.4 MAJOR — optical flow diffed across session boundaries

The module is process-scoped, so `OpticalFlowExperiment._previous` is a
single process-global slot. Verified: session A sends a frame and
disconnects; session B connects and its **first** frame is silently
diffed against A's last one, reported as `has_reference: 1.0` with
nothing to indicate the reference is foreign. It also held a decoded
frame of wearer imagery indefinitely, which is the wrong posture for a
module declaring `retains_raw_imagery=False`.

**Fixed by a staleness window**, not by a lifecycle change. A reference
older than **2.0 s** is treated as no reference: at the delivered 3.3 fps
the interval is ~300 ms and at 12 fps ~83 ms, so the window is ~7× the
slowest expected spacing — loose enough never to fire during normal
streaming, tight enough that a reconnect, a walk out of range, or a new
session cannot silently become a measurement. Uses a **monotonic** clock,
so an NTP correction cannot make a live reference look stale.
`seconds_since_reference` and `reference_stale` are reported, and the
first frame reports `-1.0` rather than `0.0` — zero seconds since a
reference that does not exist would be a lie.

**The residual case, named rather than papered over:** a new session
starting *inside* the 2 s window still inherits the previous session's
frame. Closing that needs a session-boundary hook on the module contract,
which is the blocked V1.0/V1.1 work.

This one also produced a test-quality finding worth carrying forward. The
original test asserted `has_reference == 1.0` across two connections and
was commented as "documents current behaviour rather than asserting a
reset that does not happen". That is a test that pins broken behaviour
and would keep passing however the leak was fixed. Documented is not the
same as safe.

### 9.5 MAJOR — `redaction_impact` did not measure what it claimed

The experiment's own docstring called `boundary_fraction` "the number
that matters most", and it was computed over **every survivor in the
frame** rather than over survivors near the redaction. The denominator
was dominated by ordinary never-blurred texture that happens to lie near
the box edge, diluting the signal roughly 2.5×. No test exercised it.

Its headline was also nearly a constant: the region covers ~6% of the
frame, so frame-wide retention sits near 0.99 whether the redaction was
clean or leaky, and nobody would gate a decision on 0.96 versus 0.97.

**Fixed:** the headline is now `region_keypoint_retention` (in-region),
and `boundary_fraction`'s denominator is survivors inside or within the
boundary band. On a rendered room the numbers are now decision-relevant
and reproduce the World Builder review's informal finding:

| | before the fix | after |
|---|---|---|
| headline | 0.99 (frame retention) | **0.12** (region retention) |
| boundary fraction | 0.33 | **0.96** |

**96% of the keypoints surviving near a blurred region sit on its
boundary.** They look trackable and describe the blur's own edge rather
than the scene. That is the measurement this experiment exists to
produce, and until this fix it did not produce it.

### 9.6 MINOR — a metric that could not report bad news

`median_forward_backward_px` was a median over `fb_error[kept]`, where
`kept` is exactly the set that already passed `fb_error <= 1.0`. It was
therefore bounded by 1.0 **by construction** and read "excellent" on
every frame however badly tracking went. Now measured over every track
LK claimed to have followed, with `rejected_by_forward_backward`
alongside. On a deliberately violent 1.2 m step it reports **70 px**
against the 1.0 px filter — exactly the information the old computation
destroyed.

### 9.7 Deletion candidates — examined, and two kept

The simplicity reviewer proved `baseline` byte-identical to
`frame_quality`'s `mean_intensity` (max absolute difference **0.0** over
52 synthetic inputs) and `edge_detection` correlated **r = 0.93** with
`frame_quality`'s `edge_density`. Both were recommended for deletion.

**Both are kept, and the reason is not measurement.** `baseline` is the
**default** experiment and the V0.7/V0.8 wire-compatibility reference: a
connected iOS client expects `result_label == "mean_intensity"`, and
`frame_quality`'s headline is `sharpness_laplacian_var`. Deleting
`baseline` would change the wire contract for a live client on another
machine — a cross-machine breakage that no measurement here justifies.
`edge_detection` is V0.9's original experiment and blurs before Canny,
which `frame_quality` does not; at r = 0.93 it is under the 0.95
same-metric-twice bar the reviewer itself proposed.

The reviewer's evidence is right and its conclusion does not follow: both
are redundant *as measurements* and neither is there to measure.

**`gradient_energy` examined and kept.** It costs 1.66 ms of
`frame_quality`'s 5.6 ms (~30%) and correlates r = 0.916 with the
headline sharpness. Kept because the Lab exists to make candidate quality
signals **comparable** — you cannot choose between two gates you never
computed together. Recorded here so that whoever promotes `frame_quality`
into a production cartridge knows this is the first stage to drop.

### 9.8 Attacks that were cleared

Reported so the absence of a finding is evidence rather than silence.
Verified with runnable probes, not by reading:

- **NaN / Infinity on the wire.** Hunted hard across every experiment and
  every degenerate input — 1×1, 2×2, 16×16, 1×1000, 1000×1, grayscale
  JPEG, CMYK JPEG, 2000×2000, flat colour. Every empty-array and
  divide-by-zero path is explicitly guarded, and
  `json.dumps(..., allow_nan=False)` succeeded on every case. A test now
  pins it, because `json.dumps` writes bare `NaN`, which is invalid JSON
  and would break a strict client parser.
- **`mark_failed()`'s "must not raise" contract** holds even when
  `experiment.release()` itself raises. The experiment is swapped out
  *before* `release()` is called, so there is no double-release and no
  dangling reference.
- **Numerical correctness.** `entropy_bits` returns exactly 8.0 for a
  uniform 256-level histogram. The exposure boundary levels are exact and
  non-overlapping. `spatial_coverage`'s grid clamps correctly at the
  right and bottom edges. The circular mean in `direction_coherence`
  handles the 179°/−179° wraparound. `region_area_fraction` uses
  `gray.size`, which for a 2-D `uint8` array is pixel count, not bytes.
  `object_detection`'s category indices were checked against the real
  loaded weights: `categories[1] == "person"`.
- **Contract drift.** No experiment writes to disk or touches the network
  inside `run()`; only `load()` does. The pre-existing scalar wire fields
  are byte-for-byte unchanged for `baseline`.
- **Test quality.** No self-referential test found in the new material
  apart from the optical-flow one named in 9.4. Every assertion in
  `test_experiments_measure_truth.py` is against an independently derived
  value.

**The gap that let 9.1 through:** nothing in the suite exercised a
legitimately-decodable-but-degenerate image *shape*. The existing hostile
-input tests only used garbage bytes.
`tests/test_experiments_hostile_input.py` now sweeps ten shapes across
every cheap experiment, plus the end-to-end WebSocket case.
