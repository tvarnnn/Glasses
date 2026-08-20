# Research — NVIDIA GPU Acceleration Roadmap: Is Further Tooling Justified Yet?

Date: 2026-08-20
Author: research agent (no code changed; this document is the only output)
Status: RESEARCH ONLY — informs but does not amend `01-SYSTEM-ARCHITECTURE.md`'s
GPU / Acceleration Strategy section. Any actual roadmap change is a separate,
explicit decision per `02-DEVELOPMENT-RULES.md` Rule 17.

## Why this document exists

`docs/reports/V0.9.1-depth-cv-baseline-report.md` is the platform's first real
GPU-vs-CPU measurement: MiDaS-small monocular depth, single stream, RTX 5070.
CUDA beat CPU on every steady-state metric, but the margin was modest (~18-32%,
headline client round-trip 20.18ms CUDA vs 29.35ms CPU) because the workload
itself is light — CPU inference was already ~23-29ms. Per-stage breakdown:

| Stage | CPU avg | CUDA avg | Change |
|---|---|---|---|
| decode | 1.27ms | 1.776ms | flat (noise-level) |
| preprocess | 5.029ms | 6.356ms | flat (noise-level) |
| **inference** | **22.722ms** | **15.363ms** | **~32% lower — the entire win lives here** |
| postprocess | 0.081ms | 0.171ms | flat (noise-level) |

This is one data point: one lightweight model, one resolution, one single-stream
session, on a Windows desktop Tower. This document asks, per
`01-SYSTEM-ARCHITECTURE.md`'s "correctness → instrument → profile → identify
bottlenecks → accelerate only where measurements justify it" philosophy and
`docs/modules/EXPERIMENTAL-CV.md`'s Success Criteria discipline, whether that
one data point currently justifies adopting any NVIDIA-specific tooling beyond
plain PyTorch CUDA execution — and if not, what evidence would.

The existing architecture doc already reasons about these candidates in the
abstract and already flags DeepStream as the weakest fit. This document's job
is to (a) verify that reasoning against current (2026) real-world tool status,
and (b) tie the recommendation to the actual V0.9.1 numbers rather than
restating the abstract case.

---

## 1. TensorRT — inference-graph compilation/optimization

### Current status (verified 2026)

- **Torch-TensorRT** (the PyTorch-native path) is an actively maintained
  project, current with PyTorch 2.13 and CUDA 13.2 — the same versions this
  Tower runs. Windows is supported via a community-maintained CMake build path
  (`docs.pytorch.org/TensorRT/getting_started/getting_started_with_windows.html`),
  not a first-class one-command install.
- NVIDIA also ships **Torch-TensorRT for RTX**
  (`docs.pytorch.org/TensorRT/getting_started/tensorrt_rtx.html`), a newer
  variant specifically aimed at consumer/workstation RTX GPUs (Turing or
  newer — the RTX 5070 qualifies) that JIT-compiles an optimized engine on the
  end user's own machine in under ~30 seconds, avoiding the traditional
  "build a device-specific engine ahead of time" workflow. The documentation
  explicitly labels this integration **experimental**: "Torch-TensorRT only
  supports TensorRT-RTX for experimental purposes; Torch-TensorRT by default
  uses standard TensorRT during the build and run."
- Plain **TensorRT** itself now has a real `pip install` path on Windows
  (`tensorrt-cu13`-style wheels default to CUDA 13.x), which is easier than
  the historical zip-file/manual-PATH install — but the pip wheels omit
  `trtexec` and C++ headers, and the full zip install still requires manual
  PATH configuration for the runtime DLLs and CUDA libraries. This is a real
  but non-trivial improvement over the old "Windows TensorRT is painful"
  reputation — not a solved, invisible dependency.
- Regardless of install path, the TensorRT workflow still means: export or
  trace the PyTorch model → build/compile an engine (device- and
  precision-specific) → validate numerical parity → maintain a second
  inference code path alongside the plain PyTorch one. That is real ongoing
  integration and maintenance cost, independent of how easy the initial
  `pip install` is.

### Does the V0.9.1 data justify it?

No. TensorRT is architecture-doc-justified only "once a specific PyTorch model
is profiled as the bottleneck and its inference time... dominates." V0.9.1
shows inference *is* the dominant stage (correct precondition) but at an
absolute magnitude — 15.4ms CUDA, already ~2x faster than CPU — that is not a
demonstrated problem. Nothing in the report shows this ~15ms figure is
insufficient for any concrete requirement (no target frame budget has been
missed; `effective_fps` was 40 against a 60-frame burst, well within a
reasonable real-time budget). Compiling a second, harder-to-maintain inference
path to shave milliseconds off an already-fast, already-not-bottlenecking
15ms stage does not currently pay for its integration/maintenance cost per
Rule 17's "challenge a technology choice that does not justify its
dependency/complexity cost" standard.

### Classification: **useful after specific trigger**

**Trigger:** a future model's measured `inference` stage (via the same
per-stage `stage_ms_avg` instrumentation used in V0.9.1) both (a) dominates
total `cv_processing_ms` the way MiDaS-small's did, and (b) is large enough in
absolute terms to matter against a concrete latency budget the platform has
actually defined (e.g., a real-time frame-rate target that CUDA-only execution
measurably cannot hit). A heavier future model — an object detector, a
World-Builder-related reconstruction model, or a larger depth backbone — is
the natural candidate to produce that second data point. Until then, plain
PyTorch CUDA execution (already the lowest-integration-cost candidate per the
architecture doc, and already validated in V0.9.1) remains sufficient.

---

## 2. CV-CUDA — GPU-accelerated classical CV/preprocessing

### Current status (verified 2026)

- CV-CUDA (`github.com/CVCUDA/CV-CUDA`) is at v0.17.0, actively released
  (repository activity as recent as January 2026), with real production
  adopters (NVIDIA's own materials name Microsoft, Tencent, and Baidu as
  CV-CUDA users for cloud-scale computer vision). It is a real, maturing,
  reasonably credible library — not vaporware.
- **Critical platform-fit finding: CV-CUDA does not support native Windows.**
  Its own documentation states support is Linux (x86_64/aarch64) only, with
  Windows usable solely through **WSL2**. The Tower is a native Windows
  Python/FastAPI process. Adopting CV-CUDA today would mean either (a)
  running the Tower's CV path inside WSL2 — a nontrivial architecture change
  with its own GPU-passthrough, IPC, and packaging complexity, not a drop-in
  library swap — or (b) waiting on NVIDIA to ship native Windows support,
  which has no committed date in current documentation.
- Its core value proposition is GPU-resident classical CV/preprocessing
  (resize, format conversion, decode/encode via nvImageCodec, augmentation)
  to avoid CPU↔GPU round trips and CPU-bound OpenCV preprocessing becoming a
  pipeline bottleneck.

### Does the V0.9.1 data change the recommendation?

It reinforces the existing "not currently justified" position, and for two
independent reasons rather than one:

1. **The workload reason (matches the existing doc's stated trigger):**
   V0.9.1's own per-stage breakdown is the direct evidence the architecture
   doc asked for. `preprocess` (5.0ms CPU / 6.4ms CUDA) and `decode`
   (1.3ms / 1.8ms) are small and *not* the bottleneck — `inference` is, by a
   wide margin (22.7ms / 15.4ms). CV-CUDA's justification condition in
   `01-SYSTEM-ARCHITECTURE.md` ("justified only if profiling shows CPU-side
   OpenCV preprocessing, not model inference, is the bottleneck") is
   explicitly *not* met by this data. Accelerating a 5ms stage that is
   already ~17-25% of total processing time, when it isn't the constraint,
   would not move the metric that matters (total latency), since
   preprocess/decode barely moved between the CPU and CUDA runs in the first
   place (i.e., they weren't meaningfully CPU-bound to begin with in this
   workload).
2. **A new, independent platform-fit reason the existing doc did not have
   evidence for:** even if a future workload did show CPU-side preprocessing
   as the bottleneck, CV-CUDA's lack of native Windows support means it would
   not be a drop-in fix on this Tower today — it would require a WSL2 (or
   future native-Windows) migration decision on its own merits, separate
   from the acceleration question itself.

### Classification: **probably unnecessary** (for now), verging on
**useful after specific trigger** only once the Windows gap closes

Reasoning: even under the specific trigger the architecture doc already
names (CPU-side preprocessing becomes the measured bottleneck), CV-CUDA is
not currently adoptable on this Windows Tower without a separate,
significant WSL2 architecture decision that has not been evaluated and is
out of scope of a pure acceleration choice. Until (a) a future profiling run
shows preprocess/decode dominating over inference the way inference
dominated here, **and** (b) CV-CUDA ships native Windows support (or the
Tower's WSL2-vs-native tradeoff is separately evaluated), CV-CUDA is not
actionable. If OpenCV-based preprocessing ever does become the bottleneck
before Windows support lands, the more practical near-term answer is
GPU-resident preprocessing via plain PyTorch/CUDA tensor ops (already
available, zero new dependency) rather than adding CV-CUDA specifically.

---

## 3. DeepStream — multi-stream video-analytics framework

### Current status (verified 2026)

- DeepStream is now at SDK 9.x (release notes reference DeepStream 9.0/9.1),
  actively maintained, and its supported-GPU list has grown to include
  current architectures (Turing, Ampere, Hopper, Ada, **Blackwell** — the
  RTX 5070's generation) plus newer devices (Jetson AGX Thor, DGX Spark).
  It remains fundamentally what the architecture doc already describes: a
  GStreamer-based, plugin-driven pipeline for **multi-stream, multi-model,
  multi-sensor** video analytics, targeted at NVR/edge-analytics-style
  deployments.
- **Platform-fit finding that goes beyond the existing doc's reasoning:
  DeepStream has no Windows support at all**, in 2026 or at any point in its
  history. NVIDIA's own installation documentation covers exclusively Linux
  targets: Ubuntu 24.04 x86_64 dGPU, Jetson (L4T Ubuntu/JetPack), and
  aarch64/DGX Spark via Docker. There is no Windows installation path,
  documented or implied, anywhere in current NVIDIA DeepStream documentation.
- This means DeepStream is not merely a poor architectural fit for a
  single-stream, single-desktop Tower (the existing doc's framing) — it is
  **not installable on the Tower's actual operating system at all**, full
  stop, independent of the single-stream-vs-multi-stream argument.

### Does anything in 2026 change the existing skepticism?

No — if anything it strengthens it. The existing doc calls DeepStream "the
weakest candidate on this list" because the platform is single-stream and
single-desktop. That reasoning still holds (DeepStream's entire value
proposition — GStreamer pipeline orchestration and hardware-accelerated
multi-camera batching across concurrent feeds — has no target in a one-glasses-
stream, one-active-module architecture per `01-SYSTEM-ARCHITECTURE.md`'s
Module Switching section). The newly confirmed Windows-only-unsupported fact
adds a second, independent, and more absolute disqualifier: this is not "low
priority," it is "does not run on this platform's OS today."

### Classification: **probably unnecessary** — direct statement: this does
not fit and current 2026 research gives no reason to revisit that

DeepStream should not be adopted on the current Windows Tower under any
foreseeable single-stream requirement, and would remain a poor fit even in a
hypothetical future multi-stream scenario given it has no Windows support.
If the platform ever needed genuine multi-camera/multi-sensor pipeline
orchestration (not currently on the roadmap — see `01-SYSTEM-ARCHITECTURE.md`,
Module Switching: V1 permits exactly one active module), that would first
require either porting the Tower to Linux or running DeepStream in a
container/WSL2/separate Linux host — a platform decision, not an acceleration
decision — before DeepStream's own multi-stream merits would even become
relevant to evaluate.

---

## 4. Other CUDA-specific optimizations worth naming

Evaluated against the same discipline: don't recommend something because it
exists.

### ONNX Runtime with CUDA / TensorRT execution providers
Real and current: ONNX Runtime's CUDA EP wraps cuDNN and is aimed at fast
setup; its TensorRT EP does full-graph optimization at the cost of longer
engine-build time, and NVIDIA's own materials describe using it as an
"end-to-end AI for NVIDIA-based PCs" path. This is functionally a competing
route to the *same* place TensorRT already goes (graph-level inference
optimization), with the added cost of introducing a second inference runtime
(ONNX Runtime) alongside PyTorch rather than staying in PyTorch's own
compilation path. It doesn't offer a capability the platform lacks a
lower-cost route to (Torch-TensorRT already covers this ground for a
PyTorch-based Tower) and carries the same "not currently justified by
inference time" problem as TensorRT itself, per V0.9.1. **Not currently
worth separate evaluation from TensorRT** — if a future model's `inference`
stage does justify graph compilation (see item 1's trigger), Torch-TensorRT
is the lower-friction choice for a PyTorch-based Tower before ONNX Runtime EPs
would be considered.

### torch.compile / CUDA graphs
**torch.compile is not officially supported on Windows as of 2026.** Its
default Inductor backend depends on Triton, which still lacks official
Windows support; only early, backend-specific experimental work exists (e.g.,
Intel XPU nightly builds), nothing applicable to this Tower's PyTorch
CUDA/NVIDIA setup. This is a concrete, verified reason `torch.compile` is not
presently usable here at all, regardless of whether a future model's
profiling would otherwise justify it — worth naming explicitly so a future
agent doesn't assume it's a quick win. CUDA graphs (used for reducing
per-launch CPU dispatch overhead) can, in principle, be used directly via
`torch.cuda.graphs` without full `torch.compile`, but that's only worth
profiling if the *decode/host-dispatch overhead* — not inference compute
itself — is shown to be the bottleneck, which V0.9.1 does not show (its
`cv_processing_ms` and `receive_to_result_ms` gaps track inference time
closely, not per-call dispatch overhead).

### FP16 / quantization
A genuinely low-cost, high-leverage lever once a model's `inference` stage is
the measured bottleneck: MiDaS models (and most modern vision backbones)
support FP16 execution on CUDA with a one-line `.half()`-style change and
without TensorRT's separate compilation/maintenance burden. This is worth
naming as a **cheaper first step than TensorRT** if a future profiling run
does show inference dominating — try FP16 under plain PyTorch CUDA before
reaching for a graph-compiler, since it's nearly free to test and to revert.
Not yet justified against V0.9.1's numbers for the same reason TensorRT
isn't (inference is already fast in absolute terms), but it's the natural
next experiment to run first, before TensorRT, once/if a heavier model does
show inference-bound latency.

### ONNX export in general
Neutral utility, not an accelerator by itself — exporting to ONNX is a
prerequisite for the ONNX Runtime EP path above, and is only worth doing if
that specific path is chosen for a specific measured reason. Not needed on
its own.

### ROCm / other-vendor concerns
Confirmed not relevant — the Tower's GPU is an NVIDIA RTX 5070; ROCm (AMD) or
other non-NVIDIA acceleration stacks have no bearing here and do not need
further investigation.

### Classification (for this section as a whole): FP16/quantization is
**useful after specific trigger** (same inference-dominance trigger as
TensorRT, but cheaper to test first); ONNX Runtime EPs are **probably
unnecessary** (redundant with Torch-TensorRT for a PyTorch-based Tower);
torch.compile/CUDA graphs are **research only** (blocked by lack of Windows
support today — worth re-checking if PyTorch/Triton ship official Windows
support, but not actionable now); ROCm is **out of scope, confirmed
irrelevant**.

---

## Is a second profiling data point needed?

**Yes — clearly.** V0.9.1 is a single, light, inference-dominated workload.
Every recommendation above already depends on comparing a *future* model's
profile against this one, which means the honest answer to "should we adopt
TensorRT/CV-CUDA/etc. now" cannot be fully settled by one data point no
matter how carefully it's read. Per `docs/modules/EXPERIMENTAL-CV.md`'s
Success Criteria discipline, a second, materially different experiment is
the correct next step before any of these technologies could be responsibly
adopted platform-wide.

### What the second experiment needs to measure

A second benchmark run, structured like V0.9.1 (same `depth_benchmark.py`-
style CPU-vs-CUDA harness, same per-stage instrumentation), but on a
**heavier and/or structurally different** workload — the natural roadmap
candidate is an object detector (already in `docs/modules/EXPERIMENTAL-CV.md`'s
Candidate Experiments list) or a future World-Builder-related reconstruction
model. It should measure, at minimum:

1. **Per-stage breakdown** (`decode`/`preprocess`/`inference`/`postprocess`)
   on both CPU and CUDA, exactly as V0.9.1 did — to see whether inference
   still dominates, or whether a heavier model's preprocessing (e.g.,
   multi-scale resizing, NMS-heavy postprocessing) shifts the bottleneck
   away from inference. **This single measurement determines whether
   TensorRT/FP16 (inference-focused) or CV-CUDA (preprocessing-focused) is
   even the right category of tool to consider next** — right now neither
   the existing doc's CV-CUDA trigger nor its TensorRT trigger is met, and
   only new data can change that.
2. **Absolute inference latency in real terms**, not just relative CPU-vs-CUDA
   percentage — V0.9.1's finding that "CUDA is 32% faster" mattered less than
   the fact that 15ms was already fast enough not to be a problem. A second
   model needs an actual latency budget to compare against (e.g., a
   real-time frame-rate target once one is defined) to determine whether its
   absolute inference cost is a real bottleneck worth solving, not just
   whether CUDA beats CPU again.
3. **Sustained/streaming behavior**, not just a 60-frame burst — V0.9.1
   explicitly scoped itself as a bounded comparison, not a soak test (see its
   Conclusion's "Next steps"). A heavier model run under sustained streaming
   conditions (closer to `V0.7-sustained-streaming-report.md`'s shape) would
   also surface whether backpressure/frame-dropping becomes relevant at
   higher per-frame cost — a separate but related question the current data
   explicitly could not answer.
4. Ideally, **real camera/glasses frame content** rather than synthetic JPEGs,
   per V0.9.1's own recorded caveat, since real content may have different
   decode/preprocess characteristics than synthetic frames.

---

## Overall recommendation

**Further NVIDIA-specific tooling adoption (TensorRT, CV-CUDA, DeepStream, or
ONNX Runtime EPs) is not justified right now.** This confirms rather than
overturns the existing architecture doc's philosophy — the one real
measurement available (V0.9.1) shows a modest, inference-dominated win from
plain PyTorch CUDA execution alone, with no stage currently large enough or
badly enough matched by CUDA to justify a second inference runtime or a new
preprocessing dependency. Two of the four candidates (CV-CUDA, DeepStream)
also carry a **Windows platform-support disqualifier** independent of the
performance question — CV-CUDA is Linux/WSL2-only, DeepStream is Linux-only —
that this research surfaced and the existing doc did not previously have
explicit evidence for. torch.compile, sometimes assumed to be a "free"
PyTorch-native win, is similarly blocked on Windows today by Triton's lack of
Windows support.

**Classification summary:**
| Candidate | Classification |
|---|---|
| TensorRT | useful after specific trigger — future model's `inference` stage both dominates total processing time (as MiDaS-small's did) and is large enough in absolute terms to violate a defined latency/frame-rate budget CUDA alone cannot meet |
| CV-CUDA | probably unnecessary — V0.9.1 shows preprocess/decode are not the bottleneck (the doc's own trigger is unmet), and it has no native Windows support today regardless |
| DeepStream | probably unnecessary — confirmed still a poor single-stream fit, and confirmed to have zero Windows support at any point, a stronger disqualifier than the existing doc's framing captured |
| ONNX Runtime EPs / torch.compile / FP16 / ONNX export / ROCm | mixed — FP16 is useful after specific trigger (cheaper first step than TensorRT); ONNX Runtime EPs probably unnecessary (redundant with Torch-TensorRT); torch.compile is research only (Windows-blocked); ROCm confirmed out of scope |

**Smallest next measurement that would actually move this decision forward:**
run the same `depth_benchmark.py`-style CPU-vs-CUDA harness, with the same
per-stage instrumentation, against one heavier/structurally-different model
(the roadmap's own next candidate — an object detector is the most natural
choice already listed in `docs/modules/EXPERIMENTAL-CV.md`). The single most
decision-relevant number from that run is which stage dominates
`cv_processing_ms` — if it's still `inference`, and it's now large enough to
violate a real latency budget, that is the evidence needed to promote
TensorRT/FP16 from "useful after specific trigger" to "useful now"; if it's
`preprocess`, that reopens CV-CUDA's evaluation (Windows-support gap
notwithstanding). Until that second data point exists, adding any of these
technologies would be adopting a solution before a problem exists — exactly
what `01-SYSTEM-ARCHITECTURE.md`'s GPU strategy and Rule 17 both warn
against.

---

## Sources consulted

- [Torch-TensorRT for RTX — Torch-TensorRT](https://docs.pytorch.org/TensorRT/getting_started/tensorrt_rtx.html)
- [Building Torch-TensorRT on Windows — Torch-TensorRT](https://docs.pytorch.org/TensorRT/getting_started/getting_started_with_windows.html)
- [RN-08516-001_v26.06 | July 2026 PyTorch Release Notes (NVIDIA)](https://docs.nvidia.com/deeplearning/frameworks/pdf/PyTorch-Release-Notes.pdf)
- [Releases · pytorch/TensorRT](https://github.com/pytorch/tensorrt/releases)
- [Installing TensorRT — NVIDIA TensorRT](https://docs.nvidia.com/deeplearning/tensorrt/latest/installing-tensorrt/installing.html)
- [Method 5: Zip File Installation (Windows) — NVIDIA TensorRT](https://docs.nvidia.com/deeplearning/tensorrt/latest/installing-tensorrt/install-zip.html)
- [CV-CUDA Open Source Library | NVIDIA Developer](https://developer.nvidia.com/cv-cuda)
- [GitHub - CVCUDA/CV-CUDA](https://github.com/CVCUDA/CV-CUDA)
- [CV-CUDA — CV-CUDA Beta documentation / installation](https://cvcuda.github.io/CV-CUDA/installation.html)
- [DeepStream SDK 9.1 Release Notes — NVIDIA](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Release_notes.html)
- [DeepStream Installation — NVIDIA](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Installation.html)
- [GitHub - NVIDIA/DeepStream](https://github.com/NVIDIA/DeepStream)
- [End-to-End AI for NVIDIA-Based PCs: CUDA and TensorRT Execution Providers in ONNX Runtime | NVIDIA Technical Blog](https://developer.nvidia.com/blog/end-to-end-ai-for-nvidia-based-pcs-cuda-and-tensorrt-execution-providers-in-onnx-runtime/)
- [CUDA Execution Provider — ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [NVIDIA TensorRT RTX Execution Provider — ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/TensorRTRTX-ExecutionProvider.html)
- [Investigate torch.compile Windows support · Issue #122094 · pytorch/pytorch](https://github.com/pytorch/pytorch/issues/122094)
- [Windows support timeline for torch.compile — PyTorch Forums](https://discuss.pytorch.org/t/windows-support-timeline-for-torch-compile/182268)
- [[Windows] Experimental torch.compile support for Windows on XPU · Issue #144373 · pytorch/pytorch](https://github.com/pytorch/pytorch/issues/144373)

Internal documents grounding this research:
- `guidelines/docs/01-SYSTEM-ARCHITECTURE.md` (GPU / Acceleration Strategy)
- `guidelines/docs/02-DEVELOPMENT-RULES.md` (Rule 17)
- `guidelines/docs/modules/EXPERIMENTAL-CV.md` (GPU / Acceleration Benchmarking)
- `guidelines/docs/reports/V0.9.1-depth-cv-baseline-report.md` (the measured data this analysis is grounded in)
