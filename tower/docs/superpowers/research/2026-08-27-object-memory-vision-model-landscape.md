# Object Memory — the vision-model landscape, priced against this host

**Date:** 2026-08-27
**Status:** RESEARCH ONLY. Nothing was installed, no code was written, no
dependency was added. Every claim below is either a web citation or a
pointer into this repo's own prior measurements.
**Scope:** the five model families named in the brief, plus prior art on
episodic object memory, evidence on instance re-identification failure, and
evidence on which objects people actually lose.

> **Read §12 (Provenance and confidence) before quoting any number.** Parts
> of this report were verified first-hand; parts were delegated and not
> re-checked; one delegated section was substantially retracted. §12 says
> which is which.

---

## TL;DR

1. **The binding constraint is upstream of every model here.** The shipped
   detector has **0.000 recall below 1% of frame area**, and the objects
   worth remembering — keys, wallet, glasses, medication — live in that
   band. Semantics added downstream of a blind stage-one produce a
   well-characterised memory of laptops. Fix the size floor first (§0.2,
   §10.1).
2. **Instance identity is not a solved problem, and the contract's existing
   prohibition on it is vindicated by the evidence**, not merely cautious.
   Best-in-class embeddings get **26.4% Recall@1** on small mass-produced
   objects; IDF1 collapses ~100% → ~40% from identical distractors alone;
   zero-shot egocentric object re-ID tops out at **45.3% mAP**; humans hit
   0.90 where networks hit 0.40 (§7).
3. **Do not ask a small VLM "are these the same object?"** Every candidate
   is at or below chance on the 561k-query Twin benchmark (§4.7).
4. **Picks:** `llmdet_tiny` (Apache-2.0) for async open-vocab detection —
   best accuracy-per-byte *and* the best measured motion-blur robustness;
   `dinov2-base/large` (Apache-2.0) **patch-pooled, not CLS**, for
   embeddings; `trackers` (Apache-2.0) with C-BIoU + CMC and **no re-ID**;
   `MiniCPM-V-4.6` or `Florence-2-base` for optional async captioning
   (§10.2).
5. **License traps that will catch people:** the YOLO family is GPL/AGPL
   *twice over*; MobileCLIP2 and AIMv2 are **research-only**; Qwen2.5-VL-**3B**
   is non-commercial while the 7B is Apache; BLIP-2-OPT forbids surveillance
   use outright; **SAM 3 is no longer Apache-2.0**; Grounding DINO 1.5+ and
   DINO-X are API-only (§11).
6. **The reframing worth arguing for:** three independent sources say the
   hard part is **capturing the stow event**, not recognising the object
   later — objects are stowed in enclosed spaces and then don't move. A
   stow-event log needs **no instance identity**, so it stays inside the
   existing contract (§8.8, §10.4).

---

## 0. The four constraints that decide most of this

Before any model comparison, four facts narrow the field more than any
benchmark does. Two come from this repo's own measurements; two I verified
on the web today.

### 0.1 CPU is the default device, and that is not a detail

`2026-08-26-detector-oracle-and-the-size-floor.md` measured, on this host:

| detector | CUDA warm median | CPU |
|---|---|---|
| `ssdlite320_mobilenet_v3_large` (shipped) | 42.2 ms | 44.1 ms |
| `fasterrcnn_resnet50_fpn_v2` (oracle) | 46.8 ms | **1,352.1 ms** |

and concluded: *"CPU is the default device"*, which is why the oracle — only
11% dearer on CUDA — was rejected as **16.2x the 83.5 ms delivered frame
interval** off the GPU. That ruling governs this report too. **Any
recommendation that only works on CUDA is a recommendation that breaks the
default configuration.** The live path must stay CPU-viable; the expensive
stage may be CUDA-only *if and only if* it is genuinely asynchronous and its
absence degrades the product rather than breaking it.

### 0.2 The shipped detector cannot see the objects this cartridge is for

Same report, recall against oracle boxes bucketed by box area as a fraction
of frame (n = 7,964):

| oracle box area | shipped recall |
|---|---|
| < 0.5% | **0.000** |
| 0.5–1% | **0.000** |
| 1–2% | 0.009 |
| 2–5% | 0.080 |
| 5–10% | 0.229 |
| > 25% | 0.523 |

This is the most important number in this document, and §8 below is what
makes it fatal rather than merely unfortunate. The assistive-memory
literature's "frequently lost" objects — keys, wallet, phone, glasses,
remote, medication — are small. A key fob at conversational distance on a
VGA-to-HD frame is well under 2% of frame area. **The current detector is
blind to precisely the object class this cartridge exists to remember.** No
choice of embedding model, VLM, or tracker downstream repairs a stage-one
recall of 0.000.

### 0.3 The contract currently forbids what most of this research is about

`docs/contracts/OBJECT-MEMORY.md` §1 is explicit:

> A record is about a category, not an instance. `laptop` means *a* laptop
> was in view. It is not "your laptop", and two records of `laptop` are not
> evidence about the same object. [...] **Persistent identity is forbidden
> outright by the cartridge brief** (`07-PLATFORM-CONSTRAINTS.md` Core
> Principle 3); nothing here re-identifies an object across sightings.

Every record carries `identity: "category-not-instance"`,
`claim: "category-was-visible-once"`, and `spatial_ref: null`. In code,
`tower/object_memory/relevance.py` sets `PERSISTED_CLASSES = ("laptop",
"cell phone")` with `min_score = 0.5`, `resample_seconds = 30.0`, and the
`RelevanceFilter` is keyed *by class, not by instance* — with a comment
saying so.

I want to be direct about what the evidence in §2 and §7 does to that
prohibition: **it supports it.** This report is not a case for lifting the
ban. It is a case that the ban is currently the technically correct
position, plus a description of what would have to become true to revisit
it.

### 0.4 The Windows/Blackwell toolchain forecloses several standard escapes

Verified today:

- **`torch.compile` on CUDA does not work on Windows.** The current PyTorch
  tutorial is titled *"How to use torch.compile on Windows CPU/XPU"* and
  covers only CPU and Intel XPU — there is no CUDA path
  ([docs](https://docs.pytorch.org/tutorials/unstable/inductor_windows.html)).
  The tracking issue [pytorch/pytorch#122094](https://github.com/pytorch/pytorch/issues/122094),
  opened 2024-03-18, is **still open**, with the description
  *"torch.compile is not supported on Windows. torch.compile has dependency
  triton."* An unofficial [`triton-windows`](https://github.com/woct0rdho/triton-windows)
  fork exists and tracks recent torch releases, but it is a third-party
  fork and still needs MSVC for the CPU inductor path.
- **`flash-attn` has no official Windows wheels.** Community prebuilds exist
  (`mjun0812/flash-attention-prebuild-wheels`, `lldacing`, `ussoewwin`),
  including builds against torch 2.12.0+cu132 with consumer-Blackwell
  kernels — but they are explicitly *"unofficial fork builds ... use at your
  own risk"*. Any model whose code path hard-requires
  `attn_implementation="flash_attention_2"` is a deployment risk here.
- **ONNX Runtime is not a safe escape hatch either.** ORT ≥1.27 builds
  against CUDA 13.0 by default, but sm_120 support is live-issue territory:
  [microsoft/onnxruntime#26177](https://github.com/microsoft/onnxruntime/issues/26177)
  (sm_120 build) and [#27875](https://github.com/microsoft/onnxruntime/issues/27875)
  ("does Windows onnxruntime-gpu support RTX 50 series sm_120?") are open.

**Consequence:** every published latency figure that assumes TensorRT or
`torch.compile` should be treated as *not transferable to this host*. That
disqualifies most of the impressive FPS numbers in the open-vocabulary
detector literature (§1) and all of the Jetson figures.

One more practical trap, recorded in `2026-08-26-ml-dependency-feasibility.md`:
installing any package that lists `torch` as a dependency from plain PyPI
will pull **CPU-only torch** and clobber the cu132 install. `transformers`
is **not currently installed** and nothing in the repo imports it, so
adopting anything in §1–§4 is a new dependency with that install-order
hazard attached. The venv is also on **OpenCV 5.0.0**, not 4.x, which
matters for any camera-motion-compensation code that assumes cv2 4.x APIs.

---

## 1. Open-vocabulary / zero-shot detectors

### 1.1 What is actually reachable without a compiler

`transformers` supports exactly five zero-shot detection architectures,
all via `AutoModelForZeroShotObjectDetection` /
`pipeline(task="zero-shot-object-detection")`
([docs](https://huggingface.co/docs/transformers/en/tasks/zero_shot_object_detection)),
plus SAM 3 as a sixth route (§1.5).

| Model | `transformers` class | Min ver | fp32 weights | ~Params | License |
|---|---|---|---|---|---|
| OWL-ViT B/32 | `OwlViTForObjectDetection` | ≤4.21 | 613 MB | ~153 M | Apache-2.0 |
| OWLv2 B/16 | `Owlv2ForObjectDetection` | 4.35.0 | 620 MB | ~155 M | Apache-2.0 |
| OWLv2 L/14 | `Owlv2ForObjectDetection` | 4.35.0 | 1.75 GB | ~437 M | Apache-2.0 |
| Grounding DINO Swin-T | `GroundingDinoForObjectDetection` | 4.40.0 | 689 MB | ~172 M | Apache-2.0 |
| Grounding DINO Swin-B | `GroundingDinoForObjectDetection` | 4.40.0 | 933 MB | ~233 M | Apache-2.0 |
| OmDet-Turbo Swin-T | `OmDetTurboForObjectDetection` | 4.46.0 | **462 MB** | ~115 M | Apache-2.0 |
| MM-Grounding-DINO L | `MMGroundingDinoForObjectDetection` | 4.55.0 | 1.38 GB | ~345 M | Apache-2.0 |
| **LLMDet-tiny** | `MMGroundingDinoForObjectDetection` | **4.55.0** | 692 MB | ~173 M | **Apache-2.0** |
| LLMDet-large | same | 4.55.0 | ~1.4 GB | ~330 M | Apache-2.0 |

Param counts are derived from fp32 file size ÷ 4 and are ±few %. Pinning
`transformers >= 4.55` gets all five architectures.

A version caveat that matters in practice: **the current release is
transformers 5.16.1**, requiring Python 3.10+ and PyTorch 2.5+ (verified
from the PyPI JSON API today). Our Python 3.12.5 / torch 2.13 satisfy that
comfortably, and every `>=4.x` floor in the table above is met by 5.x. But
v5 is a **major** release: most tutorials, blog posts and Stack Overflow
answers for these models were written against 4.x, and the `4.55` figures
above are *introduction* versions, not the version you would install. Budget
for API drift when following any third-party example.

### 1.2 Accuracy — LLMDet is the surprise

LVIS numbers. **Split matters enormously**: *minival* runs ~8–10 AP above
*val1.0*, and the OWL family reports both standard and "fixed" AP. Do not
cross-compare rows from different protocols.

| Model | LVIS minival AP | minival AP_r | val1.0 AP | val1.0 AP_r | COCO ZS |
|---|---|---|---|---|---|
| OWL-ViT L/14 | — | — | 34.6 (std) | 31.2 | — |
| OWLv2 L/14 (OWL-ST+FT) | — | — | 49.4 (std) | 44.6 | 56.0 |
| OWLv2 L/14 fixed-AP | — | — | 51.1 | 47.4 | — |
| Grounding DINO Swin-T | ~28.8 | ~21.6 | — | — | 52.5 (Swin-L) |
| MM-GDINO Swin-T | 41.4 | 34.2 | 31.9 | 23.6 | 50.6 |
| **LLMDet-tiny** | **50.7** | **44.7** | 44.3 | 34.9 | — |
| LLMDet-base | 54.3 | 48.3 | 47.8 | 38.5 | — |
| LLMDet-large | 56.6 | 51.1 | 50.2 | 42.0 | — |
| YOLO-World-L | 35.4 | 27.6 | — | — | — |
| YOLOE-v8-L | 35.9 | 33.2 | — | — | — |
| **SAM 3** | **52.4 box / 48.5 mask** | — | — | — | — |

Sources: [OWL-ViT](https://arxiv.org/pdf/2205.06230),
[OWLv2](https://arxiv.org/html/2306.09683v3),
[Grounding DINO](https://arxiv.org/abs/2303.05499),
[MM-GDINO configs](https://github.com/open-mmlab/mmdetection/tree/main/configs/mm_grounding_dino),
[LLMDet](https://github.com/iSEE-Laboratory/LLMDet),
[YOLO-World](https://arxiv.org/html/2401.17270v3),
[YOLOE](https://github.com/THU-MIG/yoloe),
[SAM 3](https://arxiv.org/html/2511.16719v1).

**`llmdet_tiny` at ~173 M params beats OWLv2-L/14 (~437 M) on LVIS AP_rare**
(44.7 vs 44.6 on different splits — close, and at 40% the size), and it is
Apache-2.0 and pure PyTorch. That is the headline result of the detector
survey.

### 1.3 The blur finding, which reorders everything

[*Open-Vocabulary Object Detectors: Robustness Challenges under
Distribution Shifts*](https://arxiv.org/html/2405.14874v3) benchmarks
OWL-ViT, YOLO-World and Grounding DINO on COCO-C:

| Model | motion blur sev.1 → sev.5 | COCO-O overall |
|---|---|---|
| OWL-ViT | 31.8 → **9.2** mAP (−71%) | 26.4 → 15.97 (−39%) |
| YOLO-World | 37.3 → **4.4** mAP (**−88%**) | 39.3 → 23.42 (−40%) |
| **Grounding DINO** | 30.1 → **18.2** mAP (**−40%**) | 48.4 → 41.52 (**−14%**) |

For hand-held/head-mounted Ray-Ban stills with motion blur, this is
decision-relevant and it points away from the OWL family and toward the
Grounding-DINO lineage — i.e. toward LLMDet, which inherits that backbone.
Caveats: OWLv2 was **not** tested; COCO-C synthetic motion blur is not real
rolling-shutter/handheld blur; JPEG compression is not disaggregated.

### 1.4 Licensing — the YOLO trap is real and has two jaws

**Clean Apache-2.0 with weights:** OWL-ViT, OWLv2, Grounding DINO
(IDEA-Research HF repos), MM-Grounding-DINO, LLMDet, OmDet-Turbo.

**Copyleft:**
- **YOLO-World** has *two different copyleft licenses depending on which
  repo you load it from.* The [AILab-CVC/YOLO-World LICENSE](https://github.com/AILab-CVC/YOLO-World/blob/master/LICENSE)
  is **GPL-3.0**, and it builds on `mmyolo`, which is
  [GPL-3.0 precisely because YOLOv5-derived algorithms are GPL](https://github.com/open-mmlab/mmyolo/discussions/868).
  Loading the same model through Ultralytics' `YOLOWorld` class instead puts
  you under **AGPL-3.0**, and [Ultralytics is explicit](https://www.ultralytics.com/license)
  that this requires open-sourcing your entire project or buying an
  Enterprise License — [issue #19390](https://github.com/ultralytics/ultralytics/issues/19390)
  confirms that extends to on-device, non-network products and internal R&D.
- **YOLOE** is [AGPL-3.0 by LICENSE file](https://github.com/THU-MIG/yoloe/blob/main/LICENSE)
  and ships a custom Ultralytics fork installed with `pip install -e .`, so
  the obligation is unavoidable. Strictly worse than YOLO-World.

**API-only — no weights at any price:** Grounding DINO 1.5 Pro/Edge, 1.6,
DINO-X ([API repo](https://github.com/IDEA-Research/DINO-X-API), quota via
WeChat Pay), T-Rex2 (under a bespoke "IDEA License 1.0"). Each of these
repos is Apache-2.0 **for the client code only** — a search will tell you
"Grounding DINO 1.5 is Apache-2.0", and that is wrong about the weights.
For a wearable product, API-only also means every frame leaves the device,
which is a non-starter on privacy grounds independent of licensing.

### 1.5 SAM 3 — strongest, newest, and a fresh license trap

SAM 3 ([`facebook/sam3`](https://huggingface.co/facebook/sam3),
[paper](https://arxiv.org/html/2511.16719v1)) is 0.9 B params, native in
`transformers` (`Sam3Model`/`Sam3Processor`, plus video and tracker
variants), and does promptable concept segmentation from **either a noun
phrase or an image exemplar**. Zero-shot LVIS **mask AP 48.5 / box AP
52.4**; on the SA-Co/Gold open-vocabulary benchmark it scores cgF1 **54.1**
against **OWLv2's 17.3** and Gemini 2.5's 13.0. Reported latency: *"On an
H200 GPU, SAM 3 runs in 30 ms for a single image with 100+ detected
objects."*

Two cautions. First, that H200 figure tells you nothing about a shared RTX
5070 — and per §0.4 you cannot reach for TensorRT to close the gap.
Second, and less obvious: **SAM 2 was Apache-2.0; SAM 3 is not.** It ships
the custom [SAM License](https://github.com/facebookresearch/sam3/blob/main/LICENSE)
(last updated 2025-11-19) — commercial use is permitted, royalty-free, but
with acceptable-use restrictions (no military/nuclear/espionage/ITAR), a
no-reverse-engineering clause, publication-attribution obligations, trade
controls compliance, and Meta-side termination on breach. Not OSI.
Anyone who assumes "SAM is Apache" from prior experience will be wrong.

### 1.6 Dependency hazards — verified, and better than feared

**The HF ports do not need a compiler.** I had this checked against the
actual source. `transformers`' `MultiScaleDeformableAttention` is
pure-PyTorch built on `nn.functional.grid_sample()`; there is no
`load_cuda_kernels`, no JIT `cpp_extension.load`, and no bundled
`vision.cpp` on `main`. The old JIT path was removed after
[transformers#30765](https://github.com/huggingface/transformers/issues/30765).
The `@use_kernel_forward_from_hub` decorator only *marks* the layer as
swappable via the optional `kernels` package — and HF's own
[kernels docs](https://huggingface.co/docs/kernels/index) point Windows
users at WSL2 because so few kernels support Windows, so on native Windows
nothing is substituted and you land on the pure-PyTorch path by default.
There is also an explicit `disable_custom_kernels=True` config flag on
`GroundingDinoConfig`, `MMGroundingDinoConfig` and `OmDetTurboConfig`.

**By contrast, the original repos are exactly the trap you feared.**
`pip install`ing IDEA-Research/GroundingDINO on Windows fails at the `_C`
extension — [#303](https://github.com/IDEA-Research/GroundingDINO/issues/303)
(`NameError: name '_C' is not defined`),
[#405](https://github.com/IDEA-Research/GroundingDINO/issues/405) (nvcc
failure on `ms_deform_attn_cuda.cu`),
[#210](https://github.com/IDEA-Research/GroundingDINO/issues/210) (wheel
build failure), and — worst —
[#246](https://github.com/IDEA-Research/GroundingDINO/issues/246), where it
*silently* degrades: `UserWarning: Failed to load custom C++ ops. Running on
CPU mode Only!`. [ComfyUI-RMBG#177](https://github.com/1038lab/ComfyUI-RMBG/issues/177)
reproduces this on **Windows + Python 3.12 specifically**. LLMDet's original
repo pins `mmcv==2.2.0`/`mmengine==0.10.5` (compiled CUDA ops, no wheels for
torch 2.13/cu13); YOLO-World's original pins **`torch==1.11.0`**, which is
flatly incompatible with sm_120.

**The load-bearing insight: `transformers ≥ 4.55` gives you LLMDet's and
MM-Grounding-DINO's weights with none of the MMCV/mmengine chain.** The HF
port reimplements the architecture natively — same weights, same
Apache-2.0, no compiler.

*Unmeasured:* the speed penalty of the `grid_sample` fallback versus the
CUDA kernel is not published anywhere I could find. Also unpublished:
inference VRAM and desktop-GPU latency for **any** of OWLv2, HF Grounding
DINO, MM-GDINO or LLMDet. Nobody has benchmarked these on a 40-/50-series
card publicly. You will have to measure.

### 1.7 Running a detector on a crop rather than a frame

No direct benchmark exists for OWLv2/Grounding-DINO/LLMDet used as crop
classifiers. The indirect evidence is consistent and points in one useful
direction and two cautionary ones.

- **Cropping loses context and adds blur.** [CORA](https://openaccess.thecvf.com/content/CVPR2023/papers/Wu_CORA_Adapting_CLIP_for_Open-Vocabulary_Detection_With_Region_Prompting_and_CVPR_2023_paper.pdf)
  and [ViLD](https://arxiv.org/pdf/2104.13921) report that classifying a
  region as a whole image is significantly worse than using regional
  features, and that a small crop upscaled to the model's fixed input is
  blurred by the resize. **This compounds badly with already-blurry
  VGA-to-HD input.** Standard practice in that literature is to crop at a
  **1.2× enlarged box**, not a tight one.
- **But localization-insensitivity, normally a defect, is a feature here.**
  [RO-ViT](https://research.google/blog/ro-vit-region-aware-pre-training-for-open-vocabulary-object-detection-with-vision-transformers/)
  notes loosely and tightly localized boxes produce similar features —
  *"good for classification, problematic for detection"*. Our second stage
  is handed boxes and only needs to name them. That is the regime where
  crop scoring works best.
- **A concrete configuration hazard:** `Owlv2ImageProcessor` defaults to
  `size={'height': 960, 'width': 960}` with `do_pad=True`. Hand it a wide
  200×80 crop and most of that 960×960 canvas is gray padding while you pay
  the full 3,600-token cost. Pad crops to square with **real surrounding
  image** before handing them over.
- **Fine-grained discrimination fails across the board.** [*The devil is in
  the fine-grained details*](https://arxiv.org/html/2311.17518v2) evaluates
  ViLD, Detic, CORA, OWL B/16 & L/14, OWLv2 B/16 & L/14 and Grounding DINO
  with per-object hard-negative vocabularies: **11–26 mAP on Hard negatives
  vs 35–70 on Trivial**, with Detic best on Trivial (69.7) and *worst* on
  Hard (11.5). Color is the strongest attribute (12–53 mAP); transparency
  and pattern are much weaker. Design the candidate label set to be coarse
  and mutually distinct. Do not expect "ceramic mug" vs "glass tumbler".

### 1.8 One-shot image-conditioned detection — tempting, and partly a trap

OWL-ViT supports detection conditioned on a **query image** rather than
text, which maps suggestively onto "find my specific keys again". The
paper's numbers are genuinely strong: **41.8 AP50 with a single query
image, 46.8 AP50 with k=10 queries**, on *unseen* COCO categories, up from
prior SOTA (AIT) at 24.3 ([OWL-ViT](https://ar5iv.labs.arxiv.org/html/2205.06230)).
SAM 3 also accepts image exemplars.

Two caveats before designing around it. First, this is one-shot **category**
transfer — "find more things like this kind of thing" — not instance
identity; §2 and §7 are about why those are different problems. Second, the
`transformers` port of this mode is under active complaint:
[#30131](https://github.com/huggingface/transformers/issues/30131) and
[#26920](https://github.com/huggingface/transformers/issues/26920) report
*"Owlv2 seems to have really poor performance in image-guided detection"*.
Verify it works on your data before it becomes load-bearing.

---

## 2. Image embeddings and instance re-identification

### 2.1 Licenses first, because they eliminate the obvious picks

| Family | Weights license | Commercial? |
|---|---|---|
| **DINOv2** (all sizes) | **Apache-2.0**, ungated | Yes, clean |
| **DINOv3** (all) | custom [DINOv3 License](https://ai.meta.com/resources/models-and-libraries/dinov3-license/), **gated** | Yes, with conditions |
| OpenAI CLIP | no license tag; card says *"Any deployed use case ... whether commercial or not — is currently out of scope"* | Legally murky |
| OpenCLIP / LAION | MIT | Yes |
| **SigLIP / SigLIP 2** | **Apache-2.0** | Yes, clean |
| EVA-CLIP / EVA-02 | MIT (timm/open_clip) | Yes |
| **MobileCLIP / MobileCLIP2** | **`apple-amlr`** | **NO — research only** |
| **AIMv2** | **`apple-amlr`** | **NO — research only** |

**The MobileCLIP finding is the one that stings.** MobileCLIP2-S2 is
99.1 M params, 77.2% ImageNet zero-shot, and **6.9 ms on an iPhone 12 Pro
Max** — it looks purpose-built for this system. But the LICENSE file (I
read it directly, on both
[MobileCLIP2-S2](https://huggingface.co/apple/MobileCLIP2-S2) and
[MobileCLIP-S2](https://huggingface.co/apple/MobileCLIP-S2)) is the **Apple
Machine Learning Research Model License Agreement**, granting rights
*"exclusively for Research Purposes"* and defining that term to exclude
*"any commercial exploitation, product development or use in any commercial
product or service."* Apple may terminate at will. Note the split that
causes the confusion: the *code* repo `apple/ml-mobileclip` is MIT, with
separate `LICENSE_MODELS` for the weights. **MIT code, research-only
weights.** The same applies to every AIMv2 checkpoint.

**DINOv3's license is more permissive than its reputation but is not free.**
It does grant commercial rights — *"non-exclusive, worldwide,
non-transferable and royalty-free"*, no MAU threshold, no revenue cap — but
it requires prominently displaying **"Built with DINOv3"** on a website, UI,
blog post, about page or product documentation; forbids
military/nuclear/espionage/ITAR use; forbids reverse engineering; terminates
on breach or on suing Meta; and gates the HF download behind contact-info
disclosure. There is an open request to relicense to Apache-2.0
([dinov3#31](https://github.com/facebookresearch/dinov3/issues/31)).
The attribution badge is a **product requirement, not a footnote**.
DINOv2, by contrast, is Apache-2.0 with zero strings.

### 2.2 The instance-retrieval evidence, and where it disagrees with itself

**The DINOv2 paper's own numbers** (Table 9, k-NN on frozen features,
[ar5iv](https://ar5iv.labs.arxiv.org/html/2304.07193)):

| Model | ROxford-H | Met | AmsterTime |
|---|---|---|---|
| OpenCLIP ViT-G/14 (1.8 B) | 19.7 | **6.5** | 23.9 |
| DINOv2 ViT-S/14 (21 M) | 43.2 | **29.4** | 54.3 |
| DINOv2 ViT-B/14 (86 M) | 49.5 | 36.7 | 63.5 |
| DINOv2 ViT-L/14 (300 M) | **54.0** | **40.0** | 68.9 |

The Met column is the one that matters: it is artwork *instance* retrieval.
OpenCLIP's largest model scores 6.5 where DINOv2's **smallest** scores 29.4
— a 4.5× gap at 1/85th the parameters. **CLIP-family global features are
catastrophically bad at instance identity outside the landmark domain.**
Caveat: these are the DINOv2 authors evaluating their own model on a
protocol they chose.

**The independent replication complicates it.** [ILIAS
(CVPR 2025)](https://arxiv.org/abs/2502.11748) is a purpose-built
instance-level benchmark — 1,000 instances, 1,232 queries, against **100 M
YFCC100M distractors**, with objects deliberately post-2014 so distractors
are guaranteed true negatives. mAP@1k, no adaptation, on full ILIAS:

| Model | mAP@1k |
|---|---|
| **DINOv3-L** | **26.5** |
| SigLIP2-L@512 | 20.8 |
| DINOv3-B | 22.0 |
| **DINOv2-L** | **15.3** |
| DINOv2-L-reg | 12.7 |
| EVA-CLIP-L | 10.9 |
| OpenCLIP ViT-L | 9.4 |

Three things here matter. (a) **At true scale, SigLIP2 beats DINOv2** —
which contradicts the naive "DINO for instance, CLIP for semantics"
heuristic. The ILIAS authors note DINOv2 wins on *architecture and
sculpture* but loses overall; domain dominates. (b) **DINOv3-L is the top
no-adaptation model**, winning on both axes. (c) **Registers hurt instance
retrieval** — DINOv2-L-reg (12.7) < DINOv2-L (15.3), and the same inversion
appears at B. DINOv2's own card shows S/14-reg *losing* 3.7 mAP on
ROxford-H versus plain S/14. Do not assume the registers variant is a free
upgrade for this task.

And the number that should govern the design: **even the best frozen
foundation model gets ~26 mAP@1k on clean, well-lit web photos of
deliberately distinctive objects.** Our inputs are worse in every dimension.

### 2.3 Patch tokens beat the CLS token by more than the backbone choice does

[Patch-wise Retrieval](https://arxiv.org/html/2512.12610):

| Backbone | Benchmark | Global (CLS) | **Local (patch)** | Δ |
|---|---|---|---|---|
| DINOv2 | INSTRE | 57.70 | **72.54** | +14.84 |
| CLIP | INSTRE | 73.84 | **87.57** | +13.73 |
| DINOv2 | ILIAS | 40.56 | **57.52** | +16.96 |
| CLIP | ILIAS | 31.60 | **53.35** | +21.75 |

**+14 to +22 mAP from aggregating patch tokens instead of reading the CLS
token** — a larger effect than any backbone swap in §2.2. For small, blurry
crops this should matter *more*, since a CLS token on a 40×40 crop is
dominated by whatever texture survived the resize. Corroborating on the
correspondence side, [A Tale of Two Features](https://arxiv.org/abs/2305.15347)
characterizes DINOv2 patch features as giving *"sparse but accurate
matches"* — high-precision, low-recall, which is the right operating point
for a system that must prefer ambiguity.

*Flags:* this paper is recent (arXiv 2512.x), peer-review status
unconfirmed, and its absolute scale disagrees with the ILIAS leaderboard
(its CLIP-global INSTRE number also inverts the DINOv2 paper's ordering).
Treat the **direction** as well-supported and the absolute values as
unverified.

### 2.4 Practical specs

| Model | HF id | Params | Embed dim | Notes |
|---|---|---|---|---|
| DINOv2 S/14 | `facebook/dinov2-small` | 21 M | 384 | Apache-2.0, ungated |
| DINOv2 B/14 | `facebook/dinov2-base` | 86.6 M | 768 | Apache-2.0, ungated |
| DINOv2 L/14 | `facebook/dinov2-large` | 300 M | 1024 | Apache-2.0, ungated |
| DINOv3 S/16 | `facebook/dinov3-vits16-pretrain-lvd1689m` | 21.6 M | 384 | gated, custom license |
| DINOv3 L/16 | `facebook/dinov3-vitl16-pretrain-lvd1689m` | 300 M | 1024 | gated, custom license |
| SigLIP2 base | `google/siglip2-base-patch16-224` | 0.4 B (both towers) | 768 | Apache-2.0 |
| SigLIP2 SO400m | `google/siglip2-so400m-patch14-384` | ~400 M vision | 1152 | Apache-2.0 |

Measured cost — the only real datapoint I found, from
[Swiss DINO](https://arxiv.org/html/2407.07541v1): DINOv2 ViT-S **7.3 ms /
152 MB VRAM**, ViT-B **7.3 ms / 444 MB**, ViT-L **14.6 ms / 1250 MB** on
GPU. All three fit the 3–4 GB budget comfortably; ViT-B is under half a
gigabyte.

Dependency-wise all of these are clean: DINOv2's xFormers path is
**optional** (`MemEffAttention` falls back when absent; xFormers is listed
only for training/eval reproduction, and the HF port has no xFormers
dependency at all). DINOv3 loads via `DINOv3ViTModel` with
`attn_implementation="sdpa"`, no custom kernels, no flash-attn, no
`trust_remote_code`. SigLIP2 accepts `eager`/`sdpa`/`flash_attention_2` with
eager as the default — flash-attn optional. AIMv2 needs
`trust_remote_code=True`, which combined with its license is two strikes.

---

## 3. Zero-shot CLIP-style classification over crops

This is the family where the brief's own hypothesis — "softmax over a prompt
set is NOT a probability" — needed sourcing. It is correct, but the
literature is messier than a single citation suggests, and the mess is
worth knowing.

### 3.1 Prompt ensembling: real, modest, cheap

The CLIP paper reports that ensembling **80 context prompts** on ImageNet
improves accuracy by **+3.5%** over the single default prompt, and that
prompt engineering plus ensembling together are worth **~+5%**
([CLIP](https://arxiv.org/pdf/2103.00020)). Practice is to average the
*text embeddings* across templates (not the logits), then compute one cosine
similarity. Beyond uniform averaging, bias-corrected prompt weighting has
been reported to lift ImageNet top-1 from 77.0% (equal-weight 80 prompts)
to 77.4% — a real but small further gain. The cost is zero at inference:
the ensemble collapses into one text vector per class, computed once.

### 3.2 Calibration: the literature genuinely disagrees, and that itself is the finding

- **Minderer et al., "Revisiting the Calibration of Modern Neural
  Networks"** (NeurIPS 2021) found that zero-shot CLIP is *"well-calibrated
  given its accuracy"* ([arXiv 2106.07998](https://arxiv.org/pdf/2106.07998)).
- **LeVine et al., "Enabling Calibration In The Zero-Shot Inference of Large
  Vision-Language Models"** (ICLR 2023 workshop) measured calibration across
  prompt, dataset and architecture and concluded the opposite — that
  zero-shot CLIP **is** miscalibrated — and proposed a modified temperature
  scaling, finding that **a single learned temperature generalizes for each
  (pretraining set, architecture) pair across inference dataset and prompt
  choice** ([arXiv 2303.12748](https://arxiv.org/abs/2303.12748)).

What both agree on, and what should be carried into design: **the raw
softmax over a prompt set is not a calibrated probability without a fitted
temperature**, and neither paper validates it as an *open-set* probability
at all. The good news from LeVine is that one temperature per model is
enough — you do not need to re-fit per prompt set.

There is a further wrinkle specific to SigLIP: its sigmoid loss does not
enforce cross-class competition, so its scores reflect pairwise affinity
rather than a class posterior, making it comparatively **more** miscalibrated
than softmax CLIP. *(Search-surfaced; I did not verify this against a
primary source — flagged.)*

### 3.3 The closed-set assumption is the deeper problem

Calibration is a second-order concern next to this: CLIP zero-shot
classification takes the candidate label list as *the* vocabulary and
*"inherently assumes all test samples belong to one of the known classes"*
([Grounding Descriptions in Images](https://arxiv.org/pdf/2412.04429)).
There is no "none of the above" mass. Softmax renormalizes over whatever
list you hand it, so an unfamiliar object is not scored as unfamiliar — it
is confidently assigned to the nearest label you happened to supply.
Purpose-built open-set variants such as ZO-CLIP have to *synthesize
candidate unknown class names* to recover a usable confidence
([arXiv 2109.02748](https://arxiv.org/abs/2109.02748)).

Compounding it, the **modality gap** means absolute cosine values are not
comparable across images — image and text embeddings occupy distinct
submanifolds, and only *ranks within one image* are meaningful
([Mitigate the Gap](https://arxiv.org/html/2406.17639),
[Jina](https://jina.ai/news/the-what-and-why-of-text-image-modality-gap-in-clip-models/)).
So a global similarity threshold — the obvious way to implement "reject if
unsure" — is not well-founded either.

**Design consequence:** if a CLIP-style stage is used, it must (a) include
explicit distractor/background prompts so the softmax has somewhere to put
mass, (b) use a temperature fitted once per model, and (c) express
uncertainty via *margin between top-1 and top-2* rather than absolute
similarity or absolute softmax.

### 3.4 Failure modes that bite specifically here

- **Corruption.** Zero-shot CLIP ViT-B/16 on ImageNet-C at severity 5 scores
  **24.51% mean accuracy**, with the worst corruptions at impulse 12.04,
  gaussian 11.18, glass blur 15.18, zoom blur 22.58
  ([BATCLIP](https://arxiv.org/html/2412.02837v3), verified from the HTML).
  *A widely-quoted "motion blur 19.13% vs 66.97% clean" figure I could not
  verify in the source and am not relying on.*
- **The closest published proxy for our actual imagery.** [*Explaining
  CLIP's performance disparities on data from blind/low vision
  users*](https://arxiv.org/abs/2311.17315) (CVPR 2024) tested **25 CLIP
  variants** and found accuracy **15 percentage points lower** on images
  captured by BLV users than on web-crawled images, attributing it to image
  content, **image quality (underexposure, blur, camera viewpoint,
  framing)**, and text content. Hand-held/head-mounted glasses stills sit
  squarely in that distribution. Encouragingly, few-shot adaptation with as
  few as **5 images** partially mitigated it.
- **Small objects need *more* context, not tighter crops.** [Guided
  Cropping](https://arxiv.org/pdf/2309.06581) finds the accuracy gap between
  plain CLIP and guided-cropped CLIP *grows* as maximum object size
  decreases; and, counter-intuitively, while tighter boxes help large
  objects, **small objects are classified better with more surrounding
  background**. This aligns with the 1.2× box expansion practice in §1.7.
- **Compositional blindness.** CLIP behaves like a bag-of-words
  cross-modally; attribute binding, spatial relations, counting and negation
  all fail (ARO, SugarCrepe, VL-Checklist, MMVP, WhatsUp)
  ([CLIP Behaves like a Bag-of-Words](https://arxiv.org/pdf/2502.03566)).
  Typographic attacks work. Any prompt of the form "the *red* mug *next to*
  the laptop" is asking for a capability CLIP does not have.

---

---

## 4. Small VLMs for judging a crop

> **Provenance warning specific to this section.** The delegated research
> pass on VLMs produced a large benchmark table set and then **retracted
> most of it**, on the grounds that the figures had not actually been read
> from sources. I have kept only (a) claims the researcher re-affirmed as
> personally fetched, and (b) claims I verified myself. Everything dropped
> is listed in §4.9 so that nobody re-derives it from a stale draft. Read
> §12 before treating any number in this report as settled.

### 4.1 The premise that turned out to be wrong

I briefed this research assuming flash-attn would be the gating constraint.
It largely is not: **Florence-2, MiniCPM-V 4.6, InternVL (`*-hf`), SmolVLM
and Qwen3-VL are now native architectures in `transformers` core** — no
`trust_remote_code`, no remote `.py` in the repo, and therefore no stray
`flash_attn` import to trip over. (`openbmb/MiniCPM-V-4.6` was confirmed to
contain **zero `.py` files**.) The famous Florence-2 `get_imports`
monkey-patch is obsolete and should not be shipped.

The constraint is still real for *this specific host*, for a non-obvious
reason. `transformers` supports
`attn_implementation="kernels-community/flash-attn2"`, which downloads a
precompiled kernel and skips the local build — but that repo's
[build directory](https://huggingface.co/api/models/kernels-community/flash-attn2/tree/main/build)
contains **exactly two Windows variants, both torch 2.10 (cu128 and
cu130)**; every `cu132` build is Linux. So there is no Hub kernel for
Windows + cu132 + torch 2.13, and community wheels are ABI-pinned to a torch
minor that does not match ours.

**Keep the no-flash-attn constraint.** It costs little: FA2 wins on long
sequences, and a small crop produces only 64–512 visual tokens. SDPA is the
officially documented path — current `transformers` defaults any omitted
backbone to SDPA, and the canonical `from_pretrained` examples in the
Qwen2.5-VL, Qwen3-VL and PaliGemma docs all use
`attn_implementation="sdpa"`; flash-attn appears only on vendor model cards.

⚠️ **Windows-specific trap:** there are reports of Windows machines where
`is_flash_attn_2_available()` returns `True` while flash-attn does not
actually work. **Set `attn_implementation` explicitly rather than trusting
autodetection.**

### 4.2 A correction to my own §0.4: bitsandbytes is fine

The [bitsandbytes installation guide](https://huggingface.co/docs/bitsandbytes/main/en/installation)
publishes this build matrix:

| OS | CUDA Toolkit | Targets |
|---|---|---|
| Windows x86-64 | 12.8 | sm70…sm90, **sm100, sm120** |
| **Windows x86-64** | **13.0 – 13.2** | sm75…sm90, **sm100, sm120** |

`pip install bitsandbytes` — no compilation, no CUDA Toolkit. This
contradicts a GitHub issue claiming sm_120 Windows was unsupported and a
stale line in the `transformers` bnb doc; the build matrix is the source of
truth. **4-bit NF4 quantization is available on this host**, which materially
widens the options. AWQ/GPTQ custom kernels on sm_120 remain **unverified**.

### 4.3 The candidates (licenses and sizes — the verified set)

| Model | Repo | License | Params | Disk | Native? |
|---|---|---|---|---|---|
| **Florence-2 base** | `florence-community/Florence-2-base` | **MIT** | 0.23 B | — | Yes, `Florence2ForConditionalGeneration` |
| **MiniCPM-V 4.6** | `openbmb/MiniCPM-V-4.6` | **Apache-2.0**, ungated | **1.30 B** | — | Yes, zero `.py` in repo |
| **InternVL3.5-1B** | `OpenGVLab/InternVL3_5-1B-HF` | **Apache-2.0** | 1.06 B | **2.12 GB** | Yes |
| InternVL3.5 2B/4B/8B | `OpenGVLab/InternVL3_5-*-HF` | Apache-2.0 | — | — | Yes |
| **SmolVLM / SmolVLM2** | `HuggingFaceTB/SmolVLM*` | Apache-2.0 | 256 M–2.2 B | — | Yes |
| **Qwen3-VL-2B** | `Qwen/Qwen3-VL-2B-Instruct` | **Apache-2.0**, ungated | **2.128 B** | **4.255 GB** | Yes |
| Qwen3-VL-4B | `Qwen/Qwen3-VL-4B-Instruct` | Apache-2.0 | — | 8.88 GB | Yes |
| Qwen2-VL-2B | `Qwen/Qwen2-VL-2B-Instruct` | Apache-2.0 | 2 B | — | Yes |
| Qwen2.5-VL-7B | `Qwen/Qwen2.5-VL-7B-Instruct` | Apache-2.0 | 7 B | — | Yes |
| **Moondream 2** | `vikhyatk/moondream2` | **Apache-2.0**, ungated | 2 B | — | No — `trust_remote_code` |
| PaliGemma 2 | `google/paligemma2-*` | **`gemma`, gated, non-OSI** | 3–10 B | — | Yes |

Two naming traps, both verified: the `transformers` MiniCPM-V doc page
references `openbmb/MiniCPM-V-4_6` (underscore) — **that repo does not
exist**; the real one uses a **dot**. And Florence-2 must be loaded from
`florence-community/*`, not `microsoft/*` — Microsoft never converted their
checkpoints when the architecture went native, and HF created a dedicated
org for the converted ones.

Also verified: `Qwen/Qwen3-VL-*-FP8` exists but its own model card states
**Transformers cannot load these weights directly** — FP8 is vLLM/SGLang
only.

### 4.4 License landmines

| Model | Declared | Actual |
|---|---|---|
| **`Qwen/Qwen2.5-VL-3B-Instruct`** | `qwen-research` | **NON-COMMERCIAL** — LICENSE §2(a): *"FOR NON-COMMERCIAL PURPOSES ONLY"*. The `-AWQ` variant inherits it. **The 7B genuinely is Apache-2.0** — it is the *small* one that is restricted, which is the opposite of most people's assumption, and exactly the size a memory cartridge would reach for. |
| **`google/paligemma2-*`** | `gemma` | Not OSI, and **gated** — browser acceptance plus `HF_TOKEN`, which breaks cold-start CI. |
| **Moondream 3-preview** | `other` | **BSL 1.1** with an Additional Use Grant (M87 Labs); converts to Apache-2.0 two years post-release; prohibits hosting to compete with M87's paid version. |
| **Moondream 3.1** | `moondream-model-license-1.0` | Perpetual, no conversion date. Commercial products/SaaS/self-hosting permitted; prohibits offering a general-purpose hosted Moondream inference API. **Source-available, not OSI.** |
| `LiquidAI/LFM2-VL-*` | `LFM Open License v1.0` | Commercial **only below $10 M annual revenue**. Not OSI. |
| **InternVL3.5 (all sizes)** | Apache-2.0 | **Clean.** |
| **Moondream 2** | Apache-2.0 | **Clean.** A rumour that its license changed is a conflation with Moondream 3. |

### 4.5 Moondream 3 is disqualified twice over

Verified from its [model card](https://huggingface.co/moondream/moondream3-preview):
**9 B total parameters, 2 B active** (24 layers; first four dense, the rest
MoE FFNs with 64 experts, 8 activated per token). Active-parameter counts do
not reduce residency — all experts must be in memory. The model requires
`trust_remote_code=True`, uses **FlexAttention for inference**, and the card
states that **calling `.compile()` is "critical for fast decoding."**

That second point is a direct collision with §0.4: `flex_attention` +
`.compile()` lowers through Triton, and **`torch.compile` on CUDA does not
work on Windows**. A model whose speed story depends on `torch.compile` has
no speed story on this host. Combined with a 9 B resident footprint on a
shared 12 GB card and a non-OSI license, it is out on three independent
grounds.

**Moondream 2 is the clean alternative**: Apache-2.0, 2 B, ungated,
`trust_remote_code=True`, and it exposes four task APIs — **caption, query,
detect, point**. Its 2025-06-21 release notes report ChartQA 74.8 → **77.5**
(82.2 with program-of-thought), ScreenSpot 60.3 → **80.4** F1@0.5,
CountBenchQA 80 → **86.4**, DocVQA 76.5 → **79.3**, TextVQA 74.6 → **76.3**,
and COCO detection 30.5 → **51.2** (verified from the model card; these are
vendor-reported).

### 4.6 Small crops: the evidence is strong, and it says pad and upscale

**Accuracy collapses with subject size, and cropping recovers most of it.**
[arXiv 2310.16033](https://ar5iv.labs.arxiv.org/html/2310.16033) partitions
TextVQA by subject-area fraction: BLIP-2 FlanT5XL falls from 36.81% on large
subjects to **19.91%** on small ones (<0.5% of image) — a **−45.9% relative**
drop.

[*MLLMs Know Where to Look*](https://arxiv.org/html/2502.17422v1) extends it
across models:

| Model | TextVQA large → small |
|---|---|
| BLIP-2 | 36.32% → 12.13% (**−24 pts**) |
| InstructBLIP | 45.30% → 21.79% (−23) |
| LLaVA-1.5 | 50.65% → 39.38% (−11) |
| Qwen-VL | 68.60% → 56.42% (−12) |
| GPT-4o | −7 pts (small vs medium) |

Ground-truth cropping on small objects gains **LLaVA-1.5 +30.6 points** and
**InstructBLIP +23.7 points**.

**The paper's headline finding is what validates the architecture in the
brief:** *"MLLMs consistently know where to look, even when they fail to
answer the question correctly"* — attention over the ground-truth region
exceeds baseline across most layers. **The bottleneck is resolution
allocation, not localization.** A detector-driven crop pipeline *is* a
resolution-allocation mechanism, and this is the strongest published support
for the crop-then-judge hypothesis.

**But over-cropping is a real failure mode too.**
[TDBench](https://arxiv.org/html/2504.03748v2), sweeping digital
magnification across 60 VLMs, finds **GPT-4o peaks at ~0.8% object
occupancy; open-source models need 2–4%; beyond ~6% all models decline**
from resolution loss and reduced context. Combined with §3.4 (small objects
need *more* background) and §1.7 (the 1.2× expansion convention), the design
rule is: **pad the crop to land in a 2–4% occupancy band; never crop
tight.**

**A counterintuitive datum worth knowing:** degrading images (blur,
downscale, compression) **sometimes improves** VLM accuracy across
LLaVA/Qwen-VL/DeepSeek-VL/PaliGemma/Phi-3-Vision on several benchmarks
([arXiv 2506.15645](https://arxiv.org/pdf/2506.15645)). Low-resolution crops
are not uniformly fatal. But VLMs cannot reason *about* degradation:
**GPT-4o misclassified 77% of low-resolution samples as blur**, and LLaVA
mode-collapses to a single label ([arXiv 2602.04565](https://arxiv.org/html/2602.04565)).
Do not ask the VLM to tell you whether its own input was too blurry to
judge.

**Hallucination is systematic, not random.** DASH
([ICCV 2025](https://arxiv.org/abs/2503.23573)) found **>19,000 clusters
spanning 950,000 images** where PaliGemma and two LLaVA-NeXT models
systematically hallucinate objects across 380 classes. These will be
reproducible failure modes in our pipeline, not noise that averages away.

⚠️ **And treat POPE deltas with suspicion.**
[RePOPE](https://arxiv.org/html/2504.15707v1) re-annotated the benchmark and
found **9.3% incorrect "Yes" labels** versus 1.7% incorrect "No"; correction
**nearly doubles false positives** on POPE-random and materially reshuffles
model rankings. **Published POPE F1 differences under ~2 points are not
meaningful.**

### 4.7 "Are these two crops the same object?" — do not ask a small VLM

This is the most important negative result in the report.

**[Twin / "Same or Not?"](https://arxiv.org/html/2512.23592v2)** — 561,000
image-pair queries over 1,836 object instances and 22,157 images, asking
*exactly* our question: whether two images depict the same object instance,
*"requiring attention beyond category-level semantics."*

| Model | Mean accuracy |
|---|---|
| GPT-4o | 81.7% |
| Gemini 2.5 Flash | 81.2% |
| Gemma3 4B | 69.4% |
| InternVL3.5 1B | 59.2% |
| **Qwen2.5-VL 3B** | **54.4%** |
| **SmolVLM2 2.2B** | **49.4%** (chance) |
| PerceptionLM 3B | 39.1% (**below** chance) |

**Every small open-source VLM in the candidate set is at or near a coin flip
on pairwise object identity, zero-shot.** Fine-tuning on Twin lifts
Qwen2.5-VL to 73.7% (+19.3) but InternVL3.5 by only +0.8.

[VLM²-Bench](https://arxiv.org/html/2502.12084v3) confirms this is a general
capability gap rather than a benchmark artifact. On object-centric
comparison (OC-Cpr): **humans 96.02**, GPT-4o 74.17, Qwen2.5-VL-7B 71.39,
InternVL2.5-8B 53.33. GPT-4o sits **34.80 points below human** on the
overall average, and the paper notes many open-source models are
*"comparable to the chance-level baseline or only slightly outperform it."*

And the re-ID literature does not use VLMs this way either.
[LVLM-ReID](https://arxiv.org/abs/2411.18111) uses the LVLM as a **semantic
feature generator** — instructing it to emit *"one semantic token that
encapsulates key appearance semantics"* — and does the actual matching with
a metric embedding, naming the reason: *"LVLMs operate via generative
prediction, while person re-identification requires extracting discriminative
features."*

**Architectural conclusion, and I would weight this heavily: the VLM must
not be the matcher.** Use an embedding (§2) for similarity; use the VLM to
write a human-readable attribute string stored alongside and compared as a
secondary, textual signal.

### 4.8 Runtime escape hatches on Windows

`llama.cpp` (`llama-server` / `llama-mtmd-cli`) is the best fallback: no
torch, no Triton, no sm_120 dependency. It supports SmolVLM/SmolVLM2,
Qwen2-VL/2.5-VL/3-VL, InternVL 2.5/3, MiniCPM-V and Moondream2; the vision
encoder loads as a separate `mmproj` file. It also provides a hard
`--n-gpu-layers` VRAM cap and **process isolation from the SLAM stack** —
a genuine architectural win when four processes share 12 GB.

Verified sizes: `Qwen/Qwen3-VL-2B-Instruct-GGUF` Q4_K_M = **1.11 GB** plus a
Q8_0 mmproj of **0.45 GB** → **~1.55 GB total**.

**Recommend against vLLM**: no official Windows support, community native
builds pin torch 2.11 (which would fight our stack), and its
`gpu_memory_utilization` preallocation is actively hostile to sharing a card
with three live processes. ONNX exists for several of these models but the
VLM ONNX repos have tiny download counts — essentially untested.

For sm_120 on Windows generally, expect environment friction:
[vllm#41614](https://github.com/vllm-project/vllm/issues/41614) documents
needing `TORCH_CUDA_ARCH_LIST=12.0`, `CUDA_MODULE_LOADING=LAZY`, and
CUDA-Toolkit-versus-torch path deconfliction.

### 4.9 What was retracted and must not be reused

The following were in an earlier draft of this section and were **withdrawn
by the researcher as unverified**. They are listed so nobody resurrects them
from a stale copy: all benchmark figures for MiniCPM-V 4.0/4.5, SmolVLM OCR
and throughput numbers, InternVL per-size POPE/HallusionBench values;
Florence-2's CIDEr/NoCaps figures, its `processing_florence2.py` prompt-
expansion strings and `<loc_N>` quantization details; the claim that
`Phi3VPreTrainedModel._supports_sdpa = False`; Moondream's `region.py` /
`encode_spatial_refs` box-input API; InternVL's `try/except` flash-attn
fallback behaviour; the Qwen per-generation coordinate-convention history;
and a number of cited GitHub issue/PR numbers. Some are probably correct.
None were checked.

**Consequence for the recommendation:** the region-captioning comparison
(box-in, description-out) is **not established** by this research. That is
unfortunate but not fatal, because §4.6's conclusion points away from
box-in-prompt anyway: we already have crops from a detector, so sending a
**padded crop** is simpler, avoids all coordinate-convention risk, and keeps
the judge model-agnostic.

## 5. Lightweight multi-object trackers on an egocentric, moving, low-rate camera

### 5.1 Library licenses — one hard disqualification

| Package | License (verified from LICENSE file) |
|---|---|
| **`boxmot`** (mikel-brostrom) | **AGPL-3.0** |
| `supervision` (Roboflow) | MIT |
| **`trackers`** (Roboflow) | **Apache-2.0** |
| `norfair` (Tryolabs) | BSD 3-Clause |
| `motpy` | MIT |

**`boxmot` is disqualified.** It is AGPL-3.0 by its
[LICENSE](https://raw.githubusercontent.com/mikel-brostrom/boxmot/master/LICENSE)
and its pyproject classifier, with no advertised commercial option — and it
hard-depends on `torch>=2.2.1`, `torchvision`, `timm`, `pandas`,
`scikit-learn`, dragging a second torch pin into a venv already pinned to
2.13.0+cu132 (see the §0.4 install trap).

Two further practical notes: `supervision`'s built-in `ByteTrack` is
**deprecated since 0.28.0 and removed at 0.30.0**, redirecting to the
separate `trackers` package; and `motpy` is effectively abandoned (last
release **0.0.10, 2021-09-22**) and is plain IoU+Kalman with no camera-motion
handling — i.e. precisely the model that breaks here.

**The two clean options are `trackers` (Apache-2.0) and `norfair`
(BSD-3).** Both are Windows-clean, torch-free and VRAM-free. `trackers`
ships SORT, ByteTrack, OC-SORT, BoT-SORT (with CMC) and C-BIoU as
clean-room re-implementations, with runtime deps of only numpy / supervision
/ scipy / opencv / rich / requests — assignment via
`scipy.optimize.linear_sum_assignment`. `norfair` ships a
`camera_motion.MotionEstimator` built on `goodFeaturesToTrack` then
`calcOpticalFlowPyrLK` then `findHomography`, with masking so detected
(moving) objects are excluded from corner sampling.

### 5.2 The compiled-dependency trap, confirmed

`ByteTrack/yolox/tracker/matching.py` imports **`cython_bbox`, `lap` and
`scipy`**. `cython_bbox` has **no Windows wheels**, needs MSVC Build Tools,
and historically ships a `/Wno-cpp` flag MSVC rejects with `error D8021`
([Towards-Realtime-MOT#165](https://github.com/Zhongdao/Towards-Realtime-MOT/issues/165),
[roboflow/notebooks#104](https://github.com/roboflow/notebooks/discussions/104)).
`lap` has the same source-build problem; **`lapx` is the fix** — same import
name, prebuilt Windows wheels for CPython 3.7–3.14, and its docs warn never
to install both.

So: **vendoring the official ByteTrack/OC-SORT/BoT-SORT code onto Windows
means MSVC. Using `trackers` or `norfair` means scipy and nothing else.**
At our object counts (tens), `lap`'s speed advantage over
`linear_sum_assignment` is irrelevant — microseconds either way.

Algorithm-level licenses also matter: **SORT, DeepSORT and StrongSORT are
all GPL-3.0**; ByteTrack, OC-SORT and BoT-SORT are MIT. (Deep OC-SORT and
Hybrid-SORT carry MIT *badges* but Deep OC-SORT has no LICENSE file at repo
root — unverified.) The re-ID nets are license-clean — OSNet/torchreid MIT,
FastReID Apache-2.0 — but see §5.4 for why they should not be used anyway.

### 5.3 Accuracy and cost

Independent re-evaluation from Roboflow `trackers` (same detector, tuned
params — the honest apples-to-apples set, and note it compresses the spread
that author-reported numbers imply):

| Tracker | MOT17 HOTA / MOTA / IDF1 | DanceTrack HOTA |
|---|---|---|
| SORT | 60.4 / 75.8 / 72.5 | 54.3 |
| ByteTrack | 60.5 / 76.1 / 72.7 | 55.3 |
| OC-SORT | 62.0 / 77.3 / 76.5 | 54.1 |
| **BoT-SORT** | **63.8 / 79.4 / 78.7** | 57.8 |
| C-BIoU | 63.0 / 77.4 / **79.1** | 57.7 |

Author-reported speeds for context: ByteTrack 30 FPS on a V100 *including*
the detector; OC-SORT **~700–793 FPS association-only on an i9 CPU**;
UCMCTrack ">1000 FPS on a single CPU" given detections. **Association is
free at our scale.** The only tracker component that would actually contend
for the 12 GB and the 38.6 ms is a re-ID CNN.

### 5.4 Camera-motion compensation is worth ~20x more than appearance re-ID

The BoT-SORT ablation on MOT17-val is the cleanest available answer:

| Config | MOTA | IDF1 | HOTA |
|---|---|---|---|
| Baseline (their ByteTrack re-impl) | 77.66 | 79.77 | 67.88 |
| + Kalman retune | 77.67 | 79.89 | 68.12 |
| **+ CMC** | **78.31** | **81.51** | **69.06** |
| + all three (BoT-SORT) | 78.39 | 81.53 | 69.11 |
| BoT-SORT-**ReID** | 78.46 | 82.07 | 69.17 |

**CMC alone: +1.18 HOTA. Adding a full appearance re-ID network on top of
CMC: +0.06 HOTA.** Deep OC-SORT's ablation supplies the control experiment:
CMC helps MOT17 and DanceTrack and gives **no gain on MOT20 — because MOT20
is static-camera**. So the benefit is specifically camera motion, not
generic regularization. CAMOT reports CMC alone worth **+4.5 MOTA** from a
weaker baseline; treat 1–4.5 MOTA as the plausible band. MOT17 is only
~4-of-7 moving-camera scenes, so the per-moving-sequence gain is larger than
the diluted aggregate suggests.

Cost: no paper reports GMC in ms/frame (**unverified**), but the
implementation bounds it — Ultralytics' `GMC` defaults to `downscale=2` and
recommends `sparseOptFlow` for heavy camera motion, and boxmot's guidance is
that disabling it on static cameras "saves a few milliseconds per frame".
**Single-digit CPU ms, no VRAM.** Against a 38.6 ms CUDA / 68 ms end-to-end
budget that is affordable.

**But CMC has a specific failure mode here.** Lucas-Kanade sparse flow
assumes small inter-frame displacement and adequate texture. Under low,
irregular frame rate with motion blur and large head rotations, LK
correspondence degrades *exactly when the warp is most needed*, and RANSAC
will confidently return a wrong affine. Norfair's design acknowledges this
with a `proportion_points_used_threshold=0.9` reset. **Any CMC shipped here
needs a "motion estimate untrustworthy" path, not just a warp.**

### 5.5 Egocentric benchmarks: the baselines are genuinely bad

- **EgoTracks** (Meta, from Ego4D): trackers strong on LaSOT *"drop
  sharply."* STARK scores **AO ~ 35.99%**. Fine-tuning (EgoSTARK) lifts
  F-score 30.48 to 38.2, about **+15%** relative. Stated causes are our exact
  conditions: rapid appearance change from viewpoint/scale/state, **"large,
  discontinuous motion"** from head turns *"unlike the smooth motion assumed
  in traditional trackers"*, frequent occlusion and out-of-frame, and a
  re-detection requirement ([arXiv 2301.03213](https://arxiv.org/abs/2301.03213)).
- **TREK-150** (EPIC-KITCHENS, IJCV 2023), 42 algorithms on 150 densely
  annotated first-person sequences: top generic trackers land at **success
  ~ 0.47–0.49** versus ~0.65–0.70 on OTB/LaSOT. Hardest attributes: **full
  occlusion, out-of-view, low resolution**
  ([arXiv 2209.13502](https://arxiv.org/abs/2209.13502)). Nuance worth
  keeping: per-attribute analysis found trackers relatively *robust* to the
  head-motion attribute in isolation — the damage comes from the occlusion,
  out-of-view and small-object conditions that head motion *causes*.
- **VISTA** (ICCV 2025) is the adversarial check on the above: 544
  synchronized first-/third-person pairs of the *same scene*, isolating
  viewpoint from domain. FPV vs TPV AUC: OSTrack 43.7 vs 49.2; SAM2-M 45.7
  vs 58.8; STARK 35.5 vs 42.8. Conclusion: FPV *is* harder, but **much of
  the previously-reported gap is the human-object-activity domain, not the
  first-person viewpoint per se** — and an FPV-trained STARK scores 49.8 in
  FPV vs 38.4 in TPV, flipping the ordering
  ([arXiv 2507.16015](https://arxiv.org/html/2507.16015)). Cite this against
  anyone claiming egocentric tracking is hopeless: it is a domain-shift
  problem as much as a geometry problem.

### 5.6 Low and irregular frame rate — a second, independent degradation

[FraMOT](https://ar5iv.labs.arxiv.org/html/2209.11404) subsamples MOT17 to
eight frame rates from 25 fps down to 0.5 fps. Averaged over all rates,
**ByteTrack scores mHOTA 52.5 against its 63.1 at full rate — roughly 10
HOTA points evaporate purely from frame-rate variation** — with a
"Vulnerable Ratio" of **38.3**, meaning ~38% of its associations are
frame-rate-fragile. MOT20 is worse (mHOTA 43.5, VR 58.1).

[StableTrack](https://arxiv.org/html/2511.20418v1) (Nov 2025) states the
mechanism plainly: *"in the case of low-frequency detections, increased time
intervals between detection frames promote motion uncertainty, leading to
inaccurate KF predictions. Consequently, reliance on motion cues becomes
less effective, increasing the importance of visual appearance similarity"*
— and that the Mahalanobis distance *"becomes an unstable similarity
measure."* It reports **+11.6 HOTA at 1 Hz** on MOT17-val over SOTA. For
scale: StrongSORT++ falls from 64.4 HOTA at full rate to 47.4 at 11 Hz.

[UCMCTrack](https://ar5iv.labs.arxiv.org/html/2312.08952) names both of our
failure conditions in one sentence: *"in cases of camera jitter or low
sampling rates, the two boxes may not intersect, rendering IoU
ineffective."*

**C-BIoU is the cheapest known mitigation and it costs nothing.** It adds a
**buffer expanding both detection and track boxes** so identical-but-
non-overlapping boxes in adjacent frames still match, with cascaded matching
(small buffer first, large buffer for leftovers) to avoid over-expansion
([WACV 2023](https://arxiv.org/abs/2211.14317)). In Roboflow's independent
eval it is **top IDF1 on MOT17 (79.1, beating BoT-SORT's 78.7)** with no
CMC, no re-ID and no extra compute. For an irregular-rate egocentric
pipeline this is an exceptional cost/benefit ratio — a few lines of box
arithmetic aimed directly at the "boxes no longer overlap" failure.

**Configuration trap:** ByteTrack-family `lost_track_buffer` is counted in
**frames** and scaled by a declared `frame_rate`, which defaults to 30. At an
actual 2–5 fps, leaving the default turns a 1-second track timeout into
6–15 seconds of wall-clock, and stale tracks will silently hijack new
detections.

### 5.7 Does the SLAM cartridge solve this? The evidence says largely yes

[**IT3DEgo**](https://arxiv.org/html/2312.04117v2) is the directly relevant
study: HoloLens 2, 50 sequences averaging >10,000 frames across 10 indoor
environments, **with per-frame camera pose and depth** — structurally the
same sensor situation as glasses plus a SLAM cartridge. Its conclusion is
explicit: *"tracking in 3D is much easier than in 2D by leveraging camera
pose and depth sensors"*, because stationary objects keep constant 3D world
coordinates however violently the head moves in 2D.

Numbers (precision @0.25 m / L2 error): best 2D single-object tracker
**21.5% / 1.55 m**; SAM+DINOv2 lifted directly to 3D **23.3% / 1.35 m**;
**multi-view pre-enrollment 56.0% / 0.67 m**. The lift comes from lifting
detections by pose x depth x inverse-intrinsics and associating in the world
frame.

Supporting evidence: UCMCTrack demonstrates the same principle *without*
depth — Kalman on a ground plane via homography, beating image-plane CMC
methods at >1000 CPU FPS; and the entire autonomous-driving 3D-MOT
literature (AB3DMOT, MUTR3D) tracks in the global frame using ego-pose.
Object-SLAM systems associate by reprojecting 3D object landmarks into the
image with known pose ([DSP-SLAM](https://arxiv.org/pdf/2108.09481),
[CubeSLAM](https://arxiv.org/pdf/1806.00557)).

Separately, [**EMAP**](https://arxiv.org/abs/2404.03110) reformulates the
Kalman filter to decouple camera rotational/translational velocity and depth
from object trajectories. On KITTI MOT: **OC-SORT ID switches −73%, HOTA
+5%+; Deep OC-SORT IDSW −21%, HOTA +5%+.** A **73% ID-switch reduction from
ego-motion awareness alone** is the strongest single argument in this
report for fixing the motion model rather than the appearance model.

**Four caveats before betting on it.** (1) IT3DEgo's absolute precision is
still 21–56% — 3D association is *easier*, not *solved*. (2) It presumes
**stationary objects**; a moved object breaks the constant-world-coordinate
assumption, and "the object moved" is the whole point of an object memory.
(3) It needs **depth as well as pose**; pose-only degenerates to a
ground-plane assumption. (4) It **couples tracking correctness to SLAM pose
quality** — pose loss or drift becomes a tracking failure, so it needs the
same "estimate untrustworthy" fallback that CMC does.

### 5.8 What not to reach for

- **CoTracker is CC-BY-NC** — verified from the
  [LICENSE.md](https://raw.githubusercontent.com/facebookresearch/co-tracker/main/LICENSE.md),
  header *"Attribution-NonCommercial 4.0 International"*. A relicensing PR
  ([#70](https://github.com/facebookresearch/co-tracker/pull/70)) exists but
  the file still says NC. **Do not ship it commercially.**
- **SAM 2 is Apache-2.0** and is the strongest tracker on VISTA-FPV (45.7
  AUC) — but it is a video-memory transformer contending for VRAM already
  committed to SLAM + depth + detector. Not viable in the live path.
- **Point tracking is not a shortcut.** [EgoPoints](https://arxiv.org/html/2412.04592)
  measures delta_avg going from TAP-Vid-DAVIS to egocentric video: CoTracker
  **74.7 to 38.5**, PIPs++ 64.0 to 36.9, BootsTAPIR 65.2 to 39.6, LocoTrack
  75.3 to 59.4. Re-identification delta_avg after a point returns to view is
  **catastrophic: CoTracker 4.8%, LocoTrack 0.1%, BootsTAPIR 0.0%** — because
  EgoPoints has 9x more out-of-view points and **59x more points requiring
  re-ID**. Point trackers fail on the *same* out-of-view/re-detection axis as
  box trackers, at higher compute cost and (for CoTracker) an NC license.
- **Re-ID trackers generally.** Per §5.4 they buy +0.06 HOTA over CMC, they
  are the only component that costs VRAM, and the available nets
  (FastReID SBS50, OSNet) are **pedestrian** models, badly domain-mismatched
  to household objects seen from a head-mounted camera.

---

## 6. Prior art: is "where did I leave my keys" a solved problem?

No. And the numbers are worth stating precisely, because they set the bar
for what this cartridge should promise.

### 6.1 Ego4D Episodic Memory — the benchmark built for exactly this question

**VQ2D (visual queries, 2D)** — given an image of an object, find the most
recent time it appeared in a long egocentric video. Baseline spatio-temporal
AP at IoU 0.25 (stAP₂₅):

| Method | stAP₂₅ val | stAP₂₅ test |
|---|---|---|
| SiamRCNN (official baseline) | 0.15 | 0.13 |
| NFM | 0.19 | 0.17 |
| CocoFormer | 0.19 | 0.18 |
| VQLoC (challenge winner) | 0.22 | 0.24 |

**Roughly 0.13–0.24.** Training-free methods have since improved
substantially — Relocate reports **+49% stAP₂₅** over prior SOTA and EAGLE a
further **+14.3%** — but note what that implies: **detect-then-track is a
weak baseline on egocentric video, and the headroom is in association and
re-detection, not in detection.**

**VQ3D (visual queries, 3D)** — the actual "where is it" question: return the
object's 3D position relative to the wearer. This is the number that should
govern expectations
([arXiv 2211.10284](https://arxiv.org/html/2211.10284), verified by me):

| | overall success | QwP (queries with pose) | L2 error |
|---|---|---|---|
| Ego4D baseline | **8.7%** | 15.15% | — |
| Their improved method | **25.76%** | 66.29% | **8.97 m** |

Two things to take from this. First, **the state of the art localizes a
queried object in 3D about a quarter of the time, with a mean L2 error of
nearly nine metres** — which in a domestic interior is "somewhere in the
house". Second, the authors identify the bottleneck precisely: *"the ratio
of queries we have poses QwP is the upper bound of the most important
metric, the overall success rate."* **The binding constraint was camera
pose, not recognition.** That is a direct argument for the SLAM cartridge
being the enabling dependency for any spatial answer this cartridge might
ever give — and equally, an argument that without reliable pose the ceiling
is ~15%.

**EgoTracks** (Meta, from Ego4D): STARK scores **AO ≈ 35.99%**; egocentric
fine-tuning (EgoSTARK) lifts F-score from 30.48 to 38.2. See §5.5.

### 6.2 The one system with a genuinely good number — and why

[**D3A, "Where were my keys?"**](https://arxiv.org/abs/2110.13061) reports
**81.98% mean accuracy in 11.7 ms** over 150 queries, while storing **only
0.17% of total sensory data** — 47× faster and 33% more accurate than its
baseline. It works by online incremental hierarchical association to pick
**keyframes that best represent the unique objects in the environment**,
stored in a key-value database supporting queries by object attribute,
**spatial relationship between objects**, and time.

The contrast with Ego4D's 8.7–25.8% is not a contradiction; it is a lesson
about problem framing. D3A operates on a robot with reliable pose in a
bounded environment, answers queries against a curated keyframe index rather
than re-scanning video, and leans on **spatial-temporal structure rather
than appearance re-identification**. **The system that works is the one that
does not try to re-identify instances from appearance.**

### 6.3 3D object mapping with pose: easier, still not solved

[IT3DEgo](https://arxiv.org/html/2312.04117v2) (§5.7) is the cleanest
evidence that pose helps: HoloLens 2, 50 sequences, 10 indoor environments,
per-frame pose and depth. Precision @0.25 m / L2 error — best 2D tracker
**21.5% / 1.55 m**; SAM+DINOv2 lifted to 3D **23.3% / 1.35 m**; multi-view
pre-enrollment **56.0% / 0.67 m**. Its stated conclusion: *"tracking in 3D is
much easier than in 2D by leveraging camera pose and depth sensors."*

Note the ceiling even so: **56% at best, with multi-view enrollment** —
i.e. having previously walked around the object deliberately.

### 6.4 Object-SLAM and open-vocabulary scene graphs: the failure modes are the point

The relevant literature is candid about data association being the weak
link, and about failing in *both* directions:

- [**Fusion++**](https://arxiv.org/pdf/1808.08378) associates via IoU between
  the instance mask and the TSDF-projected mask, and states that *"data
  associations can become ambiguous when odometry drifts or objects are
  occluded."*
- **QuadricSLAM** is described in follow-up work as having *"overlooked the
  data association problem"* / requiring manual association.
- **Bowman et al. 2017** open on the premise: *"In a map with several objects
  of the same class, however, a crucial data association problem exists."*
  Their answer is the probabilistic/EM formulation in §7.6.
- [**OpenLex3D**](https://openlex3d.github.io/) reports that methods merging
  2D segments — **ConceptGraphs and HOV-SG explicitly named** — *"tend to
  merge small segments together, leading to misclassifications."* That is
  over-merging, our exact concern.
- [**OSMa-Bench**](https://arxiv.org/pdf/2503.10331) documents ConceptGraphs'
  **"semantic overfragmentation"** — one physical staircase becoming N
  identically-labelled instance nodes. **The opposite error, in the same
  system.**

**Both error directions are documented in the same pipeline, which is the
tell: over-merge and over-split are two faces of one badly-chosen similarity
threshold.** A system required to prefer ambiguity should not be tuning that
threshold at all; it should be keeping the hypothesis set (§7.6).

**Clio** ([arXiv 2404.13696](https://arxiv.org/abs/2404.13696), MIT SPARK
lab) is the paper that names this problem most directly, and its framing is
worth importing wholesale. Verbatim from the abstract:

> *"What is the right granularity for the objects ... the robot has to
> include in its map representation? While related work implicitly chooses a
> level of granularity by tuning thresholds for object detection, we argue
> that such a choice is intrinsically **task-dependent**."*

Clio formulates that choice using the **Information Bottleneck**, clustering
3D primitives into task-relevant objects via an Agglomerative IB approach
driven by a natural-language task list, and reports that restricting the map
to relevant semantic concepts *"improves the accuracy of task execution"*.

The transferable idea for this cartridge is not the 3D scene graph — it is
that **"is this one object or two?" has no task-independent answer**, so the
right response to an ambiguous merge is to ask what the memory is *for*
(§8.7's priority tiers), not to retune a similarity threshold.

*Not retrieved: Clio's hardware, real-time rates, and its quantitative
object-reduction figures are not in the abstract and I did not obtain the
full text. Likewise the per-scene compute costs for ConceptGraphs,
OpenMask3D and HOV-SG that the brief asked for — these were delegated and
not returned. Treat "these pipelines are expensive" as an unquantified
expectation here, not a measured claim.*

Perceptual aliasing in indoor spaces compounds it: *"structural repetition in
buildings, such as hallways and rooms"* produces false loop closures, and
adversarially replicated high-texture patches *"bypass geometric checks in
state-of-the-art ORB-SLAM, resulting in false loop closures and hence
corrupting the map"* ([ROVER](https://arxiv.org/html/2508.13488v1)).

### 6.5 The benchmark that fits this cartridge best, and is license-clean

[**EgoObjects**](https://github.com/facebookresearch/EgoObjects) (ICCV 2023,
**MIT licensed**): 114 K annotated frames from 9 K+ videos by 250
participants, **14.4 K unique object instances** across 368 categories, at
**44.8 images per instance**, ~40 GB. Critically: *"The dataset supports both
the conventional category-level as well as the novel instance-level object
detection task."*

**This is the closest public benchmark to what Object Memory would need to
prove, and it is MIT-licensed.** No baseline numbers are published on the
repo page, and I found no published zero-shot open-vocabulary evaluation on
it for any of the §1 candidates. If this cartridge ever needs to justify an
instance-identity claim with evidence, EgoObjects is where that evidence
would come from — and producing it would be a genuine contribution rather
than a re-run.

---

## 7. How badly do embeddings over-merge identical objects?

The brief asked for quantitative evidence that appearance embeddings
over-merge visually identical mass-produced objects, because the system must
prefer ambiguity over false merging. The evidence is strong, consistent, and
worse than I expected. **I fetched and read the three primary sources in this
section myself.**

### 7.1 REMIND: a 60-point collapse from identical distractors alone

[REMIND](https://arxiv.org/html/2607.09267) does long-term multi-object
re-identification of *generic indoor objects* from monocular RGB across
temporal gaps, viewpoint change and illumination change, using **a frozen
DINOv3 ViT-S/16** — essentially this cartridge's problem statement.

IDF1 as a function of same-class distractor count (read from Figure 4, so
these are **approximate figure-reads, not table values**):

| same-class distractors present | REMIND | DAM4SAM | MASA |
|---|---|---|---|
| 0 | ~100% | ~95% | ~62% |
| 1–4 | ~90% | ~80% | ~55% |
| 5–8 | ~75% | ~65% | ~48% |
| 9–16 | ~60% | ~50% | ~42% |
| **17+** | **~40%** | ~35% | ~39% |

**A ~60-point collapse purely from adding visually identical same-class
objects.** Nothing else changes — same scene, same backbone, same method.

The ablation (these *are* table values) says where the recoverable signal
actually lives:

| Variant | Custom video IDF1 / IDSW | ScanNet++ IDF1 / IDSW |
|---|---|---|
| Full REMIND | 90.35% / 5.74% | 62.47% / 19.17% |
| **− background descriptor** | **55.56% / 19.87%** | **37.53% / 51.73%** |
| − neighbour context | 69.73% / 11.58% | 60.39% / 20.26% |

**Removing the *background* descriptor — not the object's own features —
costs 34.8 and 24.9 IDF1 points and nearly triples the ID-switch rate on
ScanNet++ (19.17% → 51.73%).** The thing that disambiguates two identical
mugs is not the mug. It is where the mug is and what is around it.

⚠️ **REMIND is a good architecture template and a bad policy template.** The
paper is explicit that it *"admits more recoveries at a higher ID-switch
rate"* — it deliberately prefers a plausible re-identification over a
conservative new-track decision. **Our requirement is the exact inverse.**

### 7.2 Mass-produced objects: the best model is wrong three times in four

A [visual product search benchmark](https://arxiv.org/html/2603.17186)
evaluates instance-level image→image retrieval against industrial product
catalogs — literally "which exact mass-produced SKU is this". Recall@1
(Table 3, no re-ranking, isolating the embedding):

| Model | Clips-and-Connectors v1 | DIY v1 | Furniture v1 |
|---|---|---|---|
| DINOv2-L | 13.7% | 18.2% | 40.2% |
| **DINOv3 ViT-L/16** | **26.4%** | 24.5% | 48.5% |
| SigLIP2-SO400M | 10.6% | 23.9% | **57.4%** |

The domain most like "two identical black laptops, two identical white
mugs" — small, repetitive, low-texture manufactured objects — is
Clips-and-Connectors, where **the best model reaches 26.4% Recall@1**.
Roughly three times in four, the top-1 nearest neighbour is the **wrong
physical instance**. Large, varied, textured objects (Furniture) reach
48–57%. Our domestic-crop distribution sits closer to the bad end.

The authors attribute the weakness to *"structured mechanical components and
repetitive visual patterns"*, and state that **"some large-scale pretrained
models fail entirely in specific domains"**, citing SigLIP2-SO400M at
**0.0 R@1 on DIY v1**.

⚠️ **Discrepancy I must flag:** that 0.0 figure appears in the paper's prose
while **Table 3 shows 23.9% for SigLIP2-SO400M on DIY v1**. I could not
reconcile them — possibly different splits or configurations. Do not quote
0.0 as settled. The *direction* — that a top-tier model can collapse on an
entire domain — is stated by the authors and is the part worth carrying.

### 7.3 Egocentric video makes it worse, and it is not close to solved

[Zero-shot object re-ID in egocentric kitchen videos](https://arxiv.org/abs/2605.26383)
evaluates five state-of-the-art extractors — **CLIP, DINOv2, DreamSim,
I-JEPA and SAM3** — on EPIC-Kitchens instance matching. The abstract is
blunt: *"we show that zero-shot methods fail, with the best baseline
achieving only **45.3% mAP**."* Their four-stage pipeline reaches **52.8%
mAP**.

Note *how* they got the +7.5: SAM3 background suppression, a fused
SAM3+DINOv2+CLIP descriptor, **mask-shape IoU for geometric consistency**,
and k-reciprocal re-ranking. Again — the gains come from geometry and
context, not from a better appearance embedding.

### 7.4 Humans are much better at this than models, which bounds the excuse

The CUTE benchmark ([*Are These the Same Apple?*](https://arxiv.org/abs/2311.00750),
NeurIPS 2023) contains 18,000 images of **180 distinct object instances
across 50 categories**, where objects within a category differ only in shape
or texture. Best in-the-wild results: **DINOv2 + crop 79.1 mAP / 69.0 top-1**;
CLIPScore + crop 69.3 / 59.5; LPIPS and SSIM around 40 mAP, i.e. near
random. Background removal lifts DINOv2's in-the-wild mAP from **70.9 → 79.1**
— the same "context/foreground separation matters" result as §7.1, from the
opposite direction.

And the number that should end the argument: on familiar high-similarity
pairs, **human observers reach ~0.90 accuracy where networks reach ~0.40.**
This is not a benchmark artifact; it is a real capability gap.

### 7.5 Small VLMs cannot rescue it

Per §4.7: on the Twin benchmark's 561,000 same-or-not queries, **Qwen2.5-VL
3B scores 54.4%, SmolVLM2 2.2B scores 49.4% (chance), and PerceptionLM 3B
scores 39.1% — below chance.** Adding a VLM as an arbiter does not repair an
ambiguous embedding match; it adds a second coin flip.

### 7.6 The information-theoretic floor, and what the literature does instead

If two objects are *genuinely* visually identical, no appearance embedding
can separate them — the information is not in the pixels. The cognitive
literature reports the same limit in humans: people track visually distinct
objects far better than visually identical ones. Every source in this
section that measured a fix found the fix was **context**: background
(REMIND, re-OBJ, CUTE), mask geometry (§7.3), spatial co-occurrence
(REMIND), or 3D position (§5.7).

The principled formulation already exists. **Bowman et al., ICRA 2017,
"Probabilistic Data Association for Semantic SLAM"** treats association as a
latent variable and uses EM with *expected* assignments, so an ambiguous
observation contributes weighted evidence to *multiple* hypotheses instead
of being forcibly bound to one. **Doherty et al., ICRA 2020**
([arXiv 1909.11213](https://arxiv.org/abs/1909.11213)) max-marginalizes the
discrete association variables into a max-mixture model and — critically —
**includes an explicit "null" hypothesis** that no valid association exists,
letting the system *reject* a detection rather than force a merge.

**That null hypothesis is precisely the "prefer ambiguity" primitive this
cartridge needs, and it has a published formalism behind it.** The design
rule that follows: do not threshold a scalar cosine similarity. Keep a
weighted candidate set per observation, always including "new object / none
of the above", and collapse only when evidence accumulates across
observations.

---

## 8. Which objects actually get lost — and why every published list is weak

The brief asked for sources rather than intuition. The honest headline is
that **the intuition is better sourced than the literature is**: every ranked
list of "what people lose" that exists is a marketing survey, and the
academic memory literature has never published an object ranking at all.

### 8.1 The strong negative result

Four rigorous diary/questionnaire studies were checked, and **all categorize
memory failures by *type*, never by object**:

| Study | N | Method | Finding |
|---|---|---|---|
| [Niedźwieńska et al. 2020, *PLoS One*](https://europepmc.org/article/MED/32976533) | 152 | 7-day diary | **Prospective** failures most common and most serious |
| [Niedźwieńska & Kvavilashvili 2019](https://europepmc.org/article/MED/31177225) | 32 aMCI + 38 control | 7-day diary | aMCI show more retrospective failures |
| [McAlister & Schmitter-Edgecombe 2016](https://europepmc.org/article/MED/26810777) | 138 + 138 | daily diary | Older adults forget names/words more |
| [Ossher, Flegal & Lustig 2013](https://europepmc.org/article/MED/22694275) | 105 | EMQ | Tip-of-the-tongue most reported |

The standard instruments (CFQ, EMQ, PRMQ) ask generically *whether* you
forget where you put things. **They are not object inventories.** State this
plainly in any design doc that cites "keys, wallet, phone".

### 8.2 The consumer surveys, and a citation-laundering chain

- **Pixie** (n > 1,700, fielded via SSI, **commissioned by a tracker
  vendor**) is the origin of the widely-repeated "TV remote is the most-lost
  item" claim. Its two vendor-controlled sources **disagree on the fielding
  date** (Oct 2016 vs commissioned Apr 2017), the full report URL is **dead**,
  and archives were unreachable. **The instrument is unrecoverable.**
- **The "Tile/Life360 survey" does not exist.** [Life360's post](https://www.life360.com/blog/most-commonly-lost-items)
  re-charts a survey by **Shane Co., a jewelry retailer** (Aug 2024, ~2,000
  US adults, methodology unpublished): **cell phones #1, keys 41%, wallets
  40%**; ~5 items lost per month, ~16 minutes per search.
- **The TV remote's #1 rank is single-source and does not replicate.**
  Shane Co./Life360 give phone #1, keys #2; [Chipolo's UK list](https://chipolo.net/en-us/blogs/lost-and-missing-items-what-we-lose-the-most-and-where-we-lose-it)
  gives keys #1 with remote at #5.
- **Structural flaw common to all of them:** these are **closed-item response
  lists**. An object cannot rank unless the vendor put it on the menu, and
  unlisted objects score zero by construction. **That is why medication never
  appears** despite being the single most-cited pain point in the blind and
  low-vision literature.

**The most trustworthy list in the corpus is behavioural, not self-report** —
Uber's lost-and-found top 10: **phone, camera, wallet, keys, purse/backpack,
clothing, glasses, headphones, vape, ID/licence.** Remotes are absent,
because remotes never leave the house.

**Most-valued ≠ most-lost.** The only "most prized possession" survey found
(OnePoll, n = 2,000, Jul 2020, commissioner undisclosed) ranks family photos
→ wedding ring → jewelry → engagement ring → heirloom → laptop → car.
**The two lists intersect only at phone and laptop, and nobody has published
a survey crossing frequency × distress** — which is exactly the cross this
product needs.

### 8.3 Clinical evidence

[McGarrigle, Howlett, Wong, Stanley & Rockwood 2019](https://pubmed.ncbi.nlm.nih.gov/30698122/),
*International Psychogeriatrics* 31(11):1635–1641 (n = 2,775; 787 / 28%
tracked misplacing): **lost-and-found 96%, hidden away 89%, found in odd
places 56%**, the last rising with severity. From the same cohort,
[Reeve et al. 2017](https://europepmc.org/article/MED/28274302) (n = 1,707)
found verbal repetition most strongly associated with misplacing/losing
objects, **OR 3.25**.

⚠️ Citation hazard worth recording: this paper is frequently cited as
2024/2025 because Elsevier re-hosts Cambridge's back catalogue and the DOI
now redirects to a 2024-style PII. **It is a 2019 paper.**

### 8.4 The closest thing to an empirical list

[MemPal](https://arxiv.org/html/2502.01801v1) (MIT Media Lab, N = 15, ages
62–96) chose its 20 test objects "based on survey results of recruited
participants and user research":

> folder, cup, phone, bottle, **medication**, **glasses**, headphones, book,
> charger, **remote**, ID card, ring, **wallet**, watch, magnifying glass,
> tape, scissors, ruler, mouse, **keys**

**And it reports the finding that should reshape the architecture: objects
are frequently left in *enclosed* areas — drawers, closets, cabinets.**
Visible to a head-worn camera at *stow* time; invisible at *retrieval* time.

### 8.5 Blind/low-vision is a different product — do not conflate

[Turkstra et al. 2023](https://arxiv.org/html/2305.03019v2) (N = 16, ages
25–79) find locating misplaced objects affects *"nearly every domestic
task"*, with **dropped medications** the archetypal case (*"If I drop my
medicine, it's like it's gone into a black hole on the white tile floor"*).
Two structural differences matter: the object is often **never seen at
all**, and **third parties displacing objects is a primary cause**, not the
user's own memory.

[VizWiz](https://arxiv.org/abs/1802.08218) has > 31,000 real questions from
blind users with **7,371 distinct answers** (vs 3,129 for VQA-v2 — a far
longer tail) and **~27% unanswerable**. The dominant need is
**identification and text-reading on an object already in hand**, not
spatial relocation.

### 8.6 Dataset statistics, read as warnings

- **Ego4D VQ has no dominant object category, and that is the finding.**
  ~22k queries over ~3,000 classes ≈ **7 queries per class** — an extreme
  long tail. ["Where is my Wallet?"](https://arxiv.org/html/2211.10528v2)
  reports *"grave implicit biases in current query-conditioned model design
  and visual query datasets."* **The per-category query distribution appears
  to be genuinely unpublished — and it is computable in an afternoon by
  histogramming `object_title` in `vq_train.json`.** That is the single
  highest-value missing number for prioritizing this cartridge.
- **EPIC-KITCHENS-100's** top nouns (tap, spoon, plate, cupboard, knife, pan,
  lid, bowl, drawer, sponge, glass, hand, fridge, cup, fork, bottle…) overlap
  the misplaced-object lists at only `bag`, `bottle`, `cloth`, `glass` — and
  that `glass` is a drinking glass. **Frequency-in-egocentric-video is not
  frequency-of-being-lost.**
- **IT3DEgo** names exactly one object from our priority list: **`keys` — as
  an example of a *deformable* instance**, because a keyring changes shape
  between views. The top-priority object is also a known re-identification
  hard case.
- **[Housekeep](https://arxiv.org/abs/2205.10712)** (1,799 objects, 268
  categories, 585 placements, 105 rooms) is the only dataset encoding
  **where a household object *belongs*** — the prior an "it's in an odd
  place" detector would need.

### 8.7 A defensible priority list

- **Tier A** — replicated across ≥2 independent sources *and* corroborated by
  behavioural (lost-and-found) data: **phone** (largely self-solving —
  deprioritize), **keys** (flagged as a deformable/hard re-ID case),
  **wallet/purse**, **glasses/sunglasses**.
- **Tier B** — attested with caveats: **TV remote** (unreplicated #1, low
  stakes, usually re-found in-room — the *weakest* priority despite the
  headline), headphones/earbuds, **medication** (zero survey support purely
  as a menu artifact; the only object independently named as critical in the
  blind/LV literature — high consequence), watch/ring, chargers.
- **Tier C** — rare, catastrophic, value-weighted; justifies a *different*
  interaction (proactive stow-confirmation rather than search): wedding and
  engagement rings, heirlooms, passport, ID/licence, bank cards.
- **Explicitly unsupported despite dominating egocentric datasets:**
  cookware, produce, utensils.

**Recommendation: derive the object priority from Tier A ∩ (leaves-the-house)
∪ Tier C (high-consequence) ∪ user-nominated valuables — not from any
published ranking, because none is trustworthy.**

### 8.8 The finding that should change the architecture

Three independent sources converge on the same point:

1. The Alzheimer's Association's discriminating criterion for concerning
   misplacement is **retrace ability**, not loss frequency.
2. **MemPal** found objects end up in **enclosed areas** — visible at stow
   time, invisible at retrieval time.
3. **IT3DEgo/ADT** found that objects overwhelmingly **do not move** — so the
   last stationary observation carries nearly all the signal.

**The hard problem is capturing the stow event, not recognizing the object
later.** A system that reliably logs "you put something down here, at this
time, and here is the frame" is more useful — and far more achievable on
this hardware — than one that tries to re-identify a specific mug across
sessions.

And it sidesteps §7 entirely: **a stow log does not need instance identity.**
It needs a timestamped, spatially-anchored observation with a picture
attached, which is very close to what `ObjectObservation` already is.

---

## 9. The comparison table

Columns as briefed. **"Compiles?"** means "does this need a custom CUDA op,
deformable-attention kernel, MMDetection/MMCV, flash-attn, or any C++ build
on Windows". **"Runs on 2.13+cu13?"** means "loads and runs with nothing
compiled locally".

### Open-vocabulary detectors

| Model | Repo | Weights | Params | License | Accuracy | Published latency (hw) | VRAM | Compiles? | 2.13+cu13? |
|---|---|---|---|---|---|---|---|---|---|
| **LLMDet-tiny** | `iSEE-Laboratory/llmdet_tiny` | 692 MB | ~173 M | **Apache-2.0** | LVIS minival 50.7 AP / **44.7 APr** | **none published** | unpublished | **No** (HF port) | **Yes** |
| LLMDet-large | `iSEE-Laboratory/llmdet_large` | ~1.4 GB | ~330 M | Apache-2.0 | minival 56.6 / **51.1 APr** | none published | unpublished | No | Yes |
| MM-GDINO Swin-T | `openmmlab-community/*` | — | — | Apache-2.0 | minival 41.4 / 34.2 APr | none published | unpublished | No (HF port) | Yes |
| Grounding DINO Swin-T | `IDEA-Research/grounding-dino-tiny` | 689 MB | ~172 M | Apache-2.0 | COCO ZS 52.5 (Swin-L) | 1.5 FPS (V100, PyTorch) | unpublished | **No via HF; YES via original repo** | Yes (HF only) |
| OWLv2 B/16 | `google/owlv2-base-patch16-ensemble` | 620 MB | ~155 M | Apache-2.0 | see §1.2 | none published | unpublished | **No** | **Yes** |
| OWLv2 L/14 | `google/owlv2-large-patch14-ensemble` | 1.75 GB | ~437 M | Apache-2.0 | LVIS 49.4 AP / 44.6 APr | none published | unpublished | No | Yes |
| OWL-ViT B/32 | `google/owlvit-base-patch32` | 613 MB | ~153 M | Apache-2.0 | LVIS 19.3 / 16.9 APr | 95 FPS (Jetson AGX Orin, **TensorRT**) | unpublished | No | Yes |
| OmDet-Turbo-T | `omlab/omdet-turbo-swin-tiny-hf` | **462 MB** | ~115 M | Apache-2.0 | COCO ZS 42.5, LVIS 30.3 | 21.5 FPS PyTorch / 140 FPS **TensorRT** | unpublished | No | Yes |
| **SAM 3** | `facebook/sam3` | — | 0.9 B | **custom SAM License** (not OSI) | **LVIS box 52.4 / mask 48.5**; SA-Co cgF1 54.1 | **30 ms (H200)**, 100+ objects | unpublished | No | Yes |
| YOLO-World-L | `AILab-CVC/YOLO-World` | — | 48 M det | **GPL-3.0** (+AGPL via Ultralytics) | LVIS 35.4 / 27.6 APr | 52 FPS (V100) | — | mmyolo, **torch==1.11 pin** | **No** |
| YOLOE-v8-L | `THU-MIG/yoloe` | — | 45 M | **AGPL-3.0** | LVIS 35.9 / 33.2 APr | — | — | Ultralytics fork | Probably |
| GDINO 1.5/1.6, DINO-X, T-Rex2 | — | **API only** | — | client code only | best-in-class | — | — | n/a | **n/a** |

### Embeddings / re-ID

| Model | Repo | Params | Dim | License | Instance retrieval | Latency / VRAM | Compiles? | 2.13+cu13? |
|---|---|---|---|---|---|---|---|---|
| **DINOv2 B/14** | `facebook/dinov2-base` | 86.6 M | 768 | **Apache-2.0**, ungated | ROxford-H 49.5; Met 36.7 | **7.3 ms / 444 MB** | No | **Yes** |
| **DINOv2 L/14** | `facebook/dinov2-large` | 300 M | 1024 | Apache-2.0 | ROxford-H **54.0**; Met **40.0**; ILIAS 15.3 | **14.6 ms / 1250 MB** | No | Yes |
| **DINOv3 L/16** | `facebook/dinov3-vitl16-*` | 300 M | 1024 | **custom, gated**, attribution required | **ILIAS 26.5** (best no-adapt); product R@1 26.4% | unpublished | No | Yes |
| SigLIP2 base | `google/siglip2-base-patch16-224` | 0.4 B | 768 | **Apache-2.0** | — | unpublished | No (sdpa ok) | Yes |
| SigLIP2 SO400m | `google/siglip2-so400m-patch14-384` | ~400 M vis | 1152 | Apache-2.0 | ILIAS 20.8; Furniture R@1 57.4% | unpublished | No | Yes |
| OpenCLIP ViT-L | `laion/CLIP-ViT-L-14-*` | 300 M | 768 | MIT | ILIAS 9.4; **Met 6.5** (ViT-G) | — | No | Yes |
| OpenAI CLIP | `openai/clip-vit-large-patch14` | 300 M | 768 | **no license tag**; card disclaims deployed use | — | — | No | Yes |
| **MobileCLIP2-S2** | `apple/MobileCLIP2-S2` | 99.1 M | — | **apple-amlr — RESEARCH ONLY** | IN-1k 77.2% | 6.9 ms (iPhone 12 Pro Max) | No | Yes |
| AIMv2-L | `apple/aimv2-large-patch14-224` | 300 M | — | **apple-amlr — RESEARCH ONLY** | IN-1k 86.6% | — | `trust_remote_code` | Yes |

### Small VLMs

| Model | Repo | Params | Disk | License | Notable | VRAM | flash-attn? | 2.13+cu13? |
|---|---|---|---|---|---|---|---|---|
| **Florence-2 base** | `florence-community/Florence-2-base` | 0.23 B | — | **MIT** | region/OCR/caption task tokens | tiny | No — native | **Yes** |
| **MiniCPM-V 4.6** | `openbmb/MiniCPM-V-4.6` | **1.30 B** | — | **Apache-2.0** | native, **zero `.py` in repo** | — | No | **Yes** |
| **InternVL3.5-1B** | `OpenGVLab/InternVL3_5-1B-HF` | 1.06 B | **2.12 GB** | **Apache-2.0** | native | — | No | Yes |
| **Qwen3-VL-2B** | `Qwen/Qwen3-VL-2B-Instruct` | 2.128 B | **4.255 GB** | **Apache-2.0** | GGUF 1.55 GB total | — | No | Yes |
| SmolVLM2-500M | `HuggingFaceTB/SmolVLM2-500M-*` | 507 M | — | Apache-2.0 | ⚠️ stored **fp32** | — | No | Yes |
| **Moondream 2** | `vikhyatk/moondream2` | 2 B | — | **Apache-2.0** | caption/query/detect/point | — | No (calls SDPA directly) | Yes (`trust_remote_code`) |
| Qwen2.5-VL-3B | `Qwen/Qwen2.5-VL-3B-Instruct` | 3 B | — | **`qwen-research` — NON-COMMERCIAL** | — | — | No | Yes |
| PaliGemma 2 3B | `google/paligemma2-3b-mix-224` | 3.03 B | — | **`gemma`, gated, non-OSI** | — | — | No | Yes |
| **Moondream 3** | `moondream/moondream3-preview` | **9 B** (2 B active) | — | **BSL 1.1** | needs `.compile()` | **≥24 GB official** | FlexAttention→Triton | **NO on Windows** |

### Trackers

| Tracker | Via | License | re-ID? | Compiled deps | MOT17 HOTA (indep.) | CPU-only? |
|---|---|---|---|---|---|---|
| **C-BIoU** | `trackers` (Apache-2.0) | Apache-2.0 re-impl | No | **none** | 63.0 (IDF1 **79.1**) | Yes |
| **BoT-SORT + CMC** | `trackers` | MIT algo / Apache re-impl | optional | **none** | **63.8** | Yes |
| ByteTrack | `trackers` | MIT | No | none via `trackers`; **`cython_bbox`+`lap` via original** | 60.5 | Yes |
| OC-SORT | `trackers` | MIT | No | same | 62.0 | Yes (~700 FPS) |
| SORT | `trackers` | **GPL-3.0** (original) | No | — | 60.4 | Yes |
| DeepSORT / StrongSORT | — | **GPL-3.0** | Yes | — | — | No (CNN) |
| anything via `boxmot` | `boxmot` | **AGPL-3.0** | — | torch pin conflict | — | — |
| norfair (+CMC) | `norfair` | **BSD-3** | optional | none | — | Yes |

---

## 10. What I would actually pick, and why

### 10.1 The uncomfortable first conclusion

**The highest-value change to this cartridge is not on this list.** Per
§0.2, `ssdlite320_mobilenet_v3_large` has **0.000 recall below 1% of frame
area and 0.009 in the 1–2% band**, and per §8 the objects worth remembering
— keys, wallet, glasses, medication — live in exactly that band. Every model
in this report is downstream of a stage that cannot see the subject.

So the ordering is: **fix the size floor first, then add semantics.** Adding
a DINOv2 embedding stage to a detector that never fires on keys produces a
very well-characterized memory of laptops.

Two candidate fixes, and the report favours the second:
1. **Tiling / SAHI on the live path.** [SAHI](https://arxiv.org/pdf/2202.06934)
   reports **+6.8, +5.1, +5.3 AP** across three detectors from slicing, with
   large small-object gains. But it multiplies detector cost by the tile
   count, and §0.1 says CPU is the default device. Probably unaffordable
   live; plausible on the async path over selected frames.
2. **An open-vocabulary detector on the async path only.** Run the cheap
   detector live for tracking continuity, and run **LLMDet-tiny** over
   selected full frames asynchronously with a small, curated prompt list
   ("keys", "wallet", "eyeglasses", "pill bottle", "remote control"). This
   directly targets the classes the COCO detector lacks *and* the small
   objects it misses, and it pays the cost off the live path where §0.1
   permits it.

### 10.2 The stack

**Open-vocab detector (async): `iSEE-Laboratory/llmdet_tiny` via
`MMGroundingDinoForObjectDetection`.** Apache-2.0, 692 MB, ~173 M params,
LVIS minival **44.7 AP_rare** — beating OWLv2-L/14 at 40% of the size. It is
in the Grounding-DINO lineage, which has by far the best measured motion-blur
robustness (**−40%** at severity 5, versus OWL-ViT's −71% and YOLO-World's
−88%) — decisive for hand-held glasses stills. Pure PyTorch through the HF
port; no MMCV, no compiler. Fallback if too slow: `omdet-turbo-swin-tiny-hf`
(462 MB). Control/simplest-possible option: `owlv2-base-patch16-ensemble`
(no deformable attention at all).

**Embedding: `facebook/dinov2-base` or `dinov2-large`, Apache-2.0,
patch-token pooled — not the CLS token.** Measured **7.3 ms / 444 MB** (B)
and **14.6 ms / 1250 MB** (L), both comfortably inside the 3–4 GB budget.
Patch pooling is worth **+14 to +22 mAP** over CLS (§2.3) — a larger effect
than any backbone swap available. **Skip the registers variants**: they are
neutral-to-harmful for instance retrieval at every size measured.

DINOv3-L is genuinely stronger (ILIAS 26.5 vs 15.3; product-catalogue R@1
26.4% vs 13.7%) and is *commercially usable*, but it is gated and obliges a
visible **"Built with DINOv3"** attribution — a product decision, not an
engineering one. Take it only if someone signs off on the badge. SigLIP2 is
a legitimate Apache-2.0 third option and a good *ensemble partner* because it
fails differently from DINO.

**Tracker: `trackers` (Apache-2.0), C-BIoU plus BoT-SORT-style CMC, no
re-ID.** Both are free at our object counts, both are CPU-only, and neither
touches VRAM. The evidence is unusually clean: **CMC is worth +1.18 HOTA
while a full appearance re-ID network on top of it is worth +0.06** (§5.4).
C-BIoU's buffered boxes attack the specific failure that ego-motion *and*
low frame rate both produce — boxes that no longer overlap — and it tops
IDF1 on MOT17 in independent evaluation at zero cost. **Set `frame_rate` to
the real delivered rate**, not the default 30, or track timeouts become
6–15 wall-clock seconds.

**VLM (async, optional): `openbmb/MiniCPM-V-4.6`** (Apache-2.0, 1.30 B,
native in `transformers`, zero remote code) or **`florence-community/Florence-2-base`**
(MIT, 0.23 B) for cheap captions and OCR of brand text. Load with
`attn_implementation="sdpa"`, explicitly. **Send padded crops, not
box-in-prompt coordinates** — it avoids the Qwen-style coordinate-convention
churn entirely and keeps the judge model-agnostic. Pad to a **2–4% occupancy
band**; never crop tight (§4.6, §3.4).

**And the rule that matters most: the VLM is not the matcher.** On the Twin
benchmark every candidate small VLM is at or below chance on "same object or
not" (§4.7). Use the embedding for similarity and the VLM only to write a
human-readable attribute string.

### 10.3 The policy, which is the actual deliverable

The contract's existing prohibition on persistent identity (§0.3) is
**vindicated by the evidence**, and this report should be read as support for
keeping it rather than as a plan to lift it:

- The best frozen embedding gets **26.4% Recall@1** on small repetitive
  manufactured objects (§7.2).
- IDF1 collapses from ~100% to ~40% purely from identical same-class
  distractors (§7.1).
- Zero-shot egocentric object re-ID tops out at **45.3% mAP** for the best
  baseline, 52.8% for a purpose-built four-stage pipeline (§7.3).
- Humans hit ~0.90 where networks hit ~0.40 on high-similarity instance
  pairs (§7.4).
- Ego4D VQ3D localizes a queried object about **a quarter** of the time with
  ~9 m error (§6.1).

If instance identity is ever revisited, the shape is already determined by
the literature, and it is **not a cosine threshold**:

1. **Keep a weighted candidate set**, never a hard assignment — Bowman et
   al.'s EM formulation over latent associations.
2. **Always include an explicit "new object / none of the above"
   hypothesis** — Doherty et al.'s null hypothesis. This *is* the "prefer
   ambiguity" primitive, and it has a published formalism.
3. **Treat spatial and co-occurrence context as a first-class cue, not a
   tiebreaker.** In REMIND's ablation the background descriptor was worth
   more than the object's own appearance features.
4. **Collapse only on accumulated evidence across observations**, not on a
   single frame.

### 10.4 The reframing I would actually argue for

§8.8 is the finding I would put in front of a product decision. Three
independent sources converge: the clinically discriminating criterion is
**retrace ability**; objects are typically stowed in **enclosed spaces**
(visible when put away, invisible afterwards); and objects **overwhelmingly
do not move** once placed.

**That points at a stow-event log rather than an object localizer.** A record
saying "at 14:32 you set something down here, and here is the frame" is more
useful, more honest, and far more achievable on this hardware than "your keys
are at (x, y, z)". Critically, **it needs no instance identity at all** — so
it sidesteps §7 entirely and stays inside the existing contract. It is close
to what `ObjectObservation` already is; what it lacks is the *event*
(placement) rather than the *presence*, and a spatial anchor from the SLAM
cartridge.

### 10.5 What to measure locally, because nobody has published it

1. **Desktop-GPU latency and VRAM for every §1 candidate.** No published
   figures exist for OWLv2, HF Grounding DINO, MM-GDINO or LLMDet on any
   40-/50-series card, in any stack.
2. **Caption/attribute quality on tiny crops as a function of `min_pixels`.**
   No paper measures it. A 50-crop golden set from our own corpus, swept, is
   the highest-value experiment available.
3. **The pure-PyTorch `grid_sample` MSDA penalty** versus the CUDA kernel.
4. **Ego4D VQ's per-category query distribution** — histogram `object_title`
   in `vq_train.json`. Appears genuinely unpublished and is directly
   decision-relevant for §8.7.
5. **Our own duplicate-object test set.** Published rankings do not survive a
   VGA/motion-blur/small-crop distribution — one study found DINO v1 beating
   DINOv2 on transformation-robust instance matching.

---

## 11. Fashionable but wrong here

| Model / tool | Why it looks right | Why it is wrong **for this system** |
|---|---|---|
| **YOLO-World / YOLOE** | Fast, famous, "open-vocabulary YOLO", great LVIS-per-FLOP | **License, twice over.** YOLO-World is GPL-3.0 in its own repo and **AGPL-3.0** through Ultralytics — same model, two copyleft licenses depending on the import. YOLOE is AGPL and ships an Ultralytics fork. Ultralytics states this reaches on-device products and internal R&D. Also: original YOLO-World pins **`torch==1.11.0`**, impossible on sm_120 — and YOLO-World had the **worst motion-blur collapse measured (−88%)**, which is disqualifying for glasses imagery. |
| **Grounding DINO 1.5/1.6, DINO-X, T-Rex2** | Best-in-class LVIS numbers; repos say Apache-2.0 | **API-only.** The Apache-2.0 covers the *client code*, not the weights. Every frame would leave the device to a remote endpoint — unacceptable for a wearable camera on latency and privacy grounds alike. |
| **The original `IDEA-Research/GroundingDINO` repo** | It's the canonical implementation | The `_C` / MultiScaleDeformableAttention extension **fails to build on Windows + Python 3.12**, and its failure mode is a *silent* fallback to `Running on CPU mode Only!`. Use the `transformers` port: same weights, same license, no compiler. |
| **MobileCLIP / MobileCLIP2** | 99 M params, 77.2% ImageNet zero-shot, 6.9 ms on a *phone* — seemingly purpose-built for wearables | **`apple-amlr` is research-only.** The LICENSE grants use *"exclusively for Research Purposes"* and excludes *"any commercial exploitation, product development or use in any commercial product or service."* The MIT badge on `apple/ml-mobileclip` covers the **code**, not the weights. Same for **AIMv2**. |
| **Moondream 3** | 9 B quality at 2 B active cost; strong benchmarks | **Three independent disqualifiers.** ≥24 GB official VRAM (all experts resident) on a shared 12 GB card; `flex_attention` + a model card saying `.compile()` is *"critical for fast decoding"* — and **`torch.compile` on CUDA does not work on Windows**; and BSL 1.1, not OSI. Moondream **2** is Apache-2.0 and fine. |
| **Qwen2.5-VL-3B** | The obvious "small Qwen" pick | **`qwen-research`: "FOR NON-COMMERCIAL PURPOSES ONLY."** The 7B *is* Apache-2.0 — the restriction lands on precisely the size a memory cartridge would reach for. Use **Qwen3-VL-2B** (Apache-2.0) instead. |
| **BLIP-2 (OPT variants)** | Classic captioner, HF tag says MIT | Embeds frozen `facebook/opt-2.7b`, whose licence is non-commercial **and explicitly prohibits** *"purposes of surveillance"* and *"biometric processing"*. **For a camera-glasses product that is a double disqualifier.** The Flan-T5 variant is clean. |
| **PaliGemma 2** | Google, strong, well-documented | Non-OSI and **gated** (breaks cold-start CI); the Terms never use the word "commercial" — permission comes from a blog post — and they incorporate a Prohibited Use Policy **by reference** that Google reserves the right to update, so restrictions on weights you already hold can expand. |
| **DINOv3** *(qualified — not disqualified)* | Best no-adaptation instance retrieval measured (ILIAS 26.5) | Commercial use **is** granted, but it is gated, non-OSI, and obliges a visible **"Built with DINOv3"** attribution. That is a product/legal decision. DINOv2 is Apache-2.0, ungated, and only modestly worse. |
| **SAM 3** *(qualified)* | Genuinely SOTA — LVIS box 52.4, SA-Co cgF1 54.1 vs OWLv2's 17.3; text *and* exemplar prompts | **SAM 2 was Apache-2.0; SAM 3 is not** — it ships a custom "SAM License". Its 30 ms figure is on an **H200**, and §0.4 forecloses TensorRT/`torch.compile` here, so that number does not transfer. 0.9 B on a shared card. Worth measuring, not worth assuming. |
| **`boxmot`** | The obvious one-stop tracker library | **AGPL-3.0**, and it drags a conflicting `torch>=2.2.1` pin into a venv pinned to 2.13.0+cu132. Use `trackers` (Apache-2.0) or `norfair` (BSD-3). |
| **DeepSORT / StrongSORT / any re-ID tracker** | "Appearance features fix ID switches" | **GPL-3.0** (both), they are the only tracker component that costs VRAM, and BoT-SORT's own ablation says appearance re-ID adds **+0.06 HOTA** on top of CMC's +1.18. The available nets are *pedestrian* models, badly mismatched to household objects. |
| **CoTracker / point tracking** | Dense correspondence would surely help ego-motion | **CC-BY-NC — verified from the LICENSE file.** And it does not work anyway: on EgoPoints, CoTracker drops 74.7 → 38.5, with **4.8% re-identification accuracy** after a point leaves and re-enters view. It fails on the same axis as box tracking, at higher cost. |
| **Asking a small VLM "are these the same object?"** | The most natural prompt in the world | Twin benchmark: Qwen2.5-VL-3B **54.4%**, SmolVLM2-2.2B **49.4%** (chance), PerceptionLM-3B **39.1%** (below chance). The re-ID literature uses VLMs as *feature generators*, never as pairwise judges. |
| **A cosine-similarity threshold for identity** | Simple, tunable, one number | The modality gap makes absolute CLIP similarities incomparable across images; and the object-mapping literature shows the same threshold producing **over-merging** (ConceptGraphs/HOV-SG merging distinct segments) *and* **over-fragmentation** (one staircase → N nodes) in the same system. Keep a hypothesis set with an explicit null, not a threshold. |
| **`torch.compile` / TensorRT to close a latency gap** | Standard practice; most published FPS numbers assume it | **`torch.compile` on CUDA is unsupported on Windows** (tracking issue open since 2024), and ONNX Runtime's sm_120 Windows support is still live-issue territory. Treat every TensorRT/compiled benchmark in the literature as not transferable to this host. |
| **vLLM** | The default high-throughput serving choice | No official Windows support; community native builds pin torch 2.11; and `gpu_memory_utilization` preallocates a VRAM pool, which is actively hostile to sharing 12 GB with SLAM, depth and a detector. Use `llama.cpp`/`llama-server` if you need process isolation and a hard VRAM cap. |

---

## 12. Provenance and confidence

This report was assembled from parallel delegated research plus my own
verification, and the two did not prove equally reliable. Reading it
correctly requires knowing which is which.

**Verified by me, first-hand, this session** — treat as solid: the Windows /
Blackwell toolchain findings (§0.4); DINOv2, DINOv3, SAM 3, SigLIP2,
MobileCLIP/MobileCLIP2, Moondream 2 and Moondream 3 licences and specs;
SAM 3's benchmark and latency claims; OWL-ViT's one-shot numbers;
`transformers` zero-shot-detection support and current version; the REMIND
distractor collapse and ablation (§7.1); the product-search Recall@1 table
(§7.2); the egocentric-kitchen 45.3%/52.8% mAP result (§7.3); the CUTE
numbers (§7.4); Ego4D VQ3D (§6.1); D3A (§6.2); EgoObjects (§6.5); and the
whole of §3 (CLIP calibration, closed-set behaviour, corruption, BLV
disparity, prompt ensembling).

**Delegated and not independently re-checked** — treat as good leads
requiring confirmation before they become load-bearing: the detector
accuracy and latency tables (§1.2, §1.3), the `transformers` source-level
claims about deformable attention (§1.6), the ILIAS leaderboard digits
(§2.2), the patch-vs-CLS table (§2.3), the tracker tables and ablations
(§5.3–§5.6), and the survey/clinical citations in §8.

**Explicitly retracted and excluded**: the delegated VLM research produced a
large benchmark table set and then withdrew most of it as unverified. §4.9
lists exactly what was dropped so it cannot be resurrected from a stale
draft. The structural conclusions in §4 rest on sources the researcher
re-affirmed as personally read, or that I read myself.

**Known discrepancies I could not resolve**, flagged in place rather than
smoothed over: the SigLIP2 "0.0 R@1 on DIY v1" prose statement versus 23.9%
in the same paper's table (§7.2); REMIND's figure-read distractor buckets
differing in detail between my read and the delegated one (§7.1 uses mine);
and the two calibration papers reaching opposite conclusions about zero-shot
CLIP (§3.2 — the disagreement is itself the finding).

**Systematically unavailable, for anyone**: desktop-GPU latency and inference
VRAM for essentially every open-vocabulary detector and VLM here; the
pure-PyTorch deformable-attention penalty; open-vocab detector performance on
egocentric indoor imagery; and caption quality as a function of crop
resolution. §10.5 lists these as local experiments because the literature
will not supply them.
