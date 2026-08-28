# Research — ML Dependency Feasibility for the Tower venv

Date: 2026-08-26
Author: research agent
Status: RESEARCH ONLY — **nothing was installed, `pyproject.toml` was not
modified.** Every `pip` invocation below was run with `--dry-run --report`,
which resolves and reports but does not write to the venv.

---

## Headline

**The Blackwell question is already settled on this exact host, by this
repo's own evidence.** `guidelines/docs/reports/V0.9.1-depth-cv-baseline-report.md`
lines 43–44 record a working run with:

> Hardware: RTX 5070 (Blackwell, `torch.cuda.get_device_capability(0) ==
> (12, 0)`), driver-reported CUDA 13.2, torch 2.13.0+cu132.

and line 91 records a live CUDA model load: `"depth model loaded on cuda in
1617.8ms (torch 2.13.0+cu132, cuda runtime 13.2, 82.7MB allocated)"`.

So sm_120 is not a research risk here. It is a *reproduction* task. The venv
lost its CUDA torch (the 2026-08-20 weekend report, item 5, notes the venv
was left holding `2.13.0+cpu`); the machine never lost the capability.

Everything below confirms that path is still available today and prices it.

---

## Environment, as measured

| Fact | Value | How verified |
|---|---|---|
| OS / arch | Windows 11, AMD64 | given |
| Python | 3.12.5 (MSC v.1940, 64-bit) in `tower/.venv` | `python -c "import sys"` |
| numpy | **2.5.2** | `pip list` |
| OpenCV | **opencv-python-headless 5.0.0.93** (`cv2.__version__ == 5.0.0`) | `pip list` |
| Pillow | 12.3.0 | `pip list` |
| pip | 26.2.1 | dry-run report |
| GPU | RTX 5070, 12227 MiB, ~1108 MiB in use | given |
| Driver | 596.21 | given |
| Free disk on C: | 752 GB | `df -h` |
| Frames waiting | **9,199 `.jpg`** (9,234 files) in `tower/data/captures/`, 199 MB | `find | wc -l` |

Note the OpenCV major version: this venv is on **OpenCV 5**, not 4. That is a
real variable for Stage C and is called out there.

---

## 1. Which PyTorch build supports sm_120 on Windows + Python 3.12?

**Answer: `torch 2.13.0+cu132` / `torchvision 0.28.0+cu132` from
`https://download.pytorch.org/whl/cu132`. Windows cp312 wheels exist on that
index and were confirmed by resolver, not by memory.**

Evidence, in order of strength:

1. **The index itself.** `https://download.pytorch.org/whl/cu132/torch/`
   lists exactly three cp312 win_amd64 wheels:
   `torch-2.12.0+cu132`, `torch-2.12.1+cu132`, `torch-2.13.0+cu132`.
   `.../cu132/torchvision/` lists `0.27.0+cu132`, `0.27.1+cu132`,
   `0.28.0+cu132` for cp312 win_amd64. So **Windows is supported on cu132**,
   and the minimum torch on that index is 2.12.0.

2. **A live resolve against this venv** (dry-run, nothing installed):

   ```
   pip install --dry-run torch torchvision \
       --index-url https://download.pytorch.org/whl/cu132
   → Would install ... torch-2.13.0+cu132 torchvision-0.28.0+cu132
   ```

   It resolved cleanly against Python 3.12.5 / Windows / numpy 2.5.2.

3. **The architecture list.** The PyTorch release/packaging announcement
   *"Introducing CUDA 13.2 and Deprecating CUDA 12.8 (Release 2.12)"*
   states the cu132 build covers "Turing (7.5), Ampere (8.0, 8.6), Hopper
   (9.0), **Blackwell (10.0, 12.0)**". `12.0` is sm_120 — the RTX 5070.

4. **NVIDIA's own CUDA 13.2 release notes** discuss sm_120/sm_121 GPUs
   explicitly (cuBLAS known-issues section), confirming the toolkit targets
   the architecture.

5. **This host already did it** — the V0.9.1 report quoted above.

### Which indexes are and are not options

- `cu128` — **gone.** The PyTorch 2.13 release blog's non-feature notes say
  "the CUDA 12.8/12.9 builds were removed". The dev-discuss thread confirms
  12.8 was pulled from the binary build matrix around April 2026. Any guide
  telling you to use `cu128` for Blackwell is from 2025 and is stale.
- `cu126` — legacy, predates the sm_120 kernels being routine; no reason to
  use it.
- `cu130` — the **default** build (this is what plain PyPI ships on Linux).
  A viable fallback; CUDA 13.0 also covers Blackwell 12.0. Not recommended
  here only because cu132 is the version this host has already proven.
- `cu132` — **recommended.** Matches the driver-reported CUDA 13.2 and
  matches `tower/README.md` lines 99–111, which already documents cu132 as
  "the verified working install command" on this machine.

### A note on a bad search result

A general web search for "PyTorch sm_120 Windows" still surfaces 2025-era
GitHub issues (#159207, #164342) and forum threads whose summaries claim
*"stable PyTorch supports only up to sm_90, use nightly cu128, or use WSL2."*
**That is stale and was contradicted by every primary source checked above.**
It is exactly the failure mode the task warned about. Do not act on it.

---

## 2. Does driver 596.21 support the required CUDA runtime?

**Yes, with enormous margin.**

- CUDA 13.x minor-version compatibility requires driver **>= 580** (NVIDIA
  CUDA Toolkit 13.2 release notes, "Minimum Required Driver Version for CUDA
  Minor Version Compatibility"). 596.21 clears that by 16 major points.
- The GA table lists "N/A" for a bundled Windows driver, because **from CUDA
  13.1 onward the Windows display driver is no longer bundled with the
  toolkit** — you supply your own. You already have one.
- You do **not** need to install the CUDA Toolkit at all. The PyTorch Windows
  CUDA wheel bundles its own CUDA runtime DLLs; only the display driver has
  to be new enough. (On Linux torch declares `cuda-toolkit==13.0.3` etc. as
  pip deps — note the `platform_system == "Linux"` markers in torch 2.13.0's
  metadata. On Windows those deps do not apply, which is why the Windows
  install is a single fat wheel.)

Minimum driver for the recommendation: **>= 580**. Actual: **596.21**. Pass.

---

## 3. numpy 2.x compatibility

**No conflict. numpy 2.5.2 satisfies every candidate, and nothing wants
numpy 1.x.** Checked against real wheel metadata from the dry-run reports:

| Package | numpy requirement | 2.5.2 OK? |
|---|---|---|
| `torch 2.13.0` | *does not depend on numpy at all* | n/a |
| `torchvision 0.28.0` | `numpy` (unconstrained) + `torch==2.13.0` (exact pin) | yes |
| `timm 1.0.28` | via torch/torchvision only | yes |
| `scipy 1.18.1` | `numpy>=2.0.0,<2.8` | yes |
| `scikit-image 0.26.0` | `numpy>=1.24`, built against `numpy>=2.0` | yes |
| `shapely 2.1.2` | `numpy>=1.21` | yes |
| `easyocr 1.7.2` | `numpy` (unconstrained) | yes |

Two things worth stating precisely, because "torch built against numpy 1.x
breaks on import" is a real historical failure:

- That failure was **torch 2.4 and earlier** (pytorch/pytorch #131668 —
  "Release 2.4 windows wheels are not compatible with numpy 2.0"; #135013).
  NumPy 2 support landed in **torch 2.3.0** and the wheels have been built
  against the NumPy 2 headers since (pytorch/pytorch #107302). A module
  compiled against NumPy 2 is compatible with both 1.x and 2.x; the reverse
  is not true. torch 2.13.0 is nine minor releases past the fix.
- NumPy 2.x is **ABI-stable within the 2 series**, so a wheel built against
  numpy 2.0 headers runs on 2.5.2. The upper bound to watch is scipy's
  `<2.8`, which is a forward guard, not a problem today.

Note the *pinning direction*: `torchvision 0.28.0` requires `torch==2.13.0`
exactly. Install them together, from the same index, or you get a resolver
fight. Also note that a `+cu132` local-version torch **does** satisfy
`torch==2.13.0`, which is what makes the staged install below work.

---

## 4. Second-`cv2` hazard

**Verdict: none of the candidates pull `opencv-python`. The `easyocr`
suspicion is unfounded — it is the one that gets this right.**

`easyocr 1.7.2`'s declared requirements, read straight from the wheel
metadata in the dry-run report:

```
torch, torchvision>=0.5, opencv-python-headless, scipy, numpy, Pillow,
scikit-image, python-bidi, PyYAML, Shapely, pyclipper, ninja
```

It asks for **`opencv-python-headless`** by name — the same distribution this
project already has (`opencv-python-headless 5.0.0.93`) — so pip marks it
already-satisfied and installs no second cv2. The full resolve confirms it:

```
Would install ImageIO-2.37.4 Jinja2 MarkupSafe easyocr-1.7.2 filelock fsspec
lazy-loader mpmath networkx ninja-1.13.0 pyclipper-1.4.0 python-bidi-0.6.11
scikit-image-0.26.0 scipy-1.18.1 setuptools shapely-2.1.2 sympy
tifffile-2026.8.23 torch-2.13.0 torchvision-0.28.0
```

No `opencv-python`. This matches `pyproject.toml`'s `ocr` extra comment
exactly: the package that *did* drag in a second cv2 was
**`rapidocr_onnxruntime`**, which was rejected for that reason. The repo
history is right; easyocr is clean.

Per-candidate chains:

| Package | Pulls opencv? | Notes |
|---|---|---|
| `easyocr` | **no** — requires `opencv-python-headless` | clean, verified by resolve |
| `timm` | no | pulls `huggingface_hub 1.28.0`, `httpx 0.28.1`, `safetensors`, `hf-xet`, `tqdm`, `certifi` |
| `torch` / `torchvision` | no | |
| `scipy` | no | arrives transitively via easyocr/scikit-image |
| `scikit-learn` | no | **not needed — nothing in `tower/` imports sklearn** |
| `onnxruntime` | no | **not needed — nothing imports it** |
| `transformers` | no | **not needed — nothing imports it** |

That last block is a finding in its own right. A grep for
`import (torch|torchvision|timm|easyocr|scipy|sklearn|onnxruntime|transformers)`
across all non-venv `.py` files returns hits for only **torch, torchvision,
timm (indirectly, via MiDaS's hubconf), and easyocr**:

- `tower/experiments/depth.py` — torch (MiDaS via `torch.hub`, needs timm)
- `tower/experiments/object_detection.py` — torchvision `ssdlite320_mobilenet_v3_large`
- `tower/scene/detect.py` — torchvision `ssdlite320_mobilenet_v3_large`
- `tower/scene/orientation.py` — torchvision `keypointrcnn_resnet50_fpn`
- `tower/document_memory/ocr.py` — easyocr
- `scripts/verify_cuda.py`, `scripts/world_builder_env_check.py`, `tests/test_depth_experiment_integration.py` — torch

**`scipy`, `sklearn`, `onnxruntime` and `transformers` are not direct
dependencies of anything in this repo.** scipy arrives as a transitive of
easyocr; the other three should not be installed at all. That shrinks the
problem considerably: the entire ML stack this repo actually needs is
`torch + torchvision + timm + easyocr`.

The one genuine cv2-adjacent risk is not a *second* cv2 — it is the *major
version* of the one you have. See Stage C risks.

---

## 5. Install order — does the README hazard still apply?

**Yes, unchanged, and it is currently the single most likely way to waste an
afternoon.** `tower/README.md` lines 70–94 warn that `pyproject.toml`'s `ml`
extra declares bare `"torch"`/`"torchvision"` with no index pin, so
`pip install -e ".[dev,ml]"` resolves them from plain PyPI, and once a
CPU-only wheel satisfies that unconstrained requirement, a later CUDA-indexed
install can report "already satisfied" without replacing it.

Confirmed empirically today. Resolving `easyocr` (or `timm`) against plain
PyPI gives:

```
torch-2.13.0-cp312-cp312-win_amd64.whl        122.1 MB
torchvision-0.28.0-cp312-cp312-win_amd64.whl    4.1 MB
```

A **122 MB** torch wheel is unambiguously the **CPU-only** build — the
cu132 Windows wheel is **1,917,946,849 bytes (1.92 GB)**. torch 2.13.0's
metadata also confirms it: every CUDA dependency it declares is gated on
`platform_system == "Linux"`, so the PyPI Windows wheel carries no CUDA at
all. This is exactly how the venv ended up on `2.13.0+cpu` per the
2026-08-20 weekend report.

**Therefore: the CUDA-indexed install must be the first ML install in the
venv.** Anything that lists `torch` as a dependency — `timm`, `easyocr`, the
`ml` extra, the `ocr` extra — must come after.

Two supporting hazards from the same README section that still stand:

- **MAX_PATH (README lines 113–128).** A 1.92 GB torch wheel with a deep
  bundled license tree, unpacked into a path under
  `C:\Users\tvllo\Projects\Glasses\tower\.venv\...`, can trip
  `OSError: [WinError 206]`. The README's documented workaround is manual
  wheel extraction with the `\\?\` extended-length prefix — **not** enabling
  the global `LongPathsEnabled` registry policy. Installing into the main
  tree (as here) rather than a nested `.claude/worktrees/...` path gives the
  most headroom. Have the workaround ready; do not improvise a registry edit.
- **`httpx` vs `httpx2`.** `timm` pulls `huggingface_hub`, which pulls
  `httpx 0.28.1`. That is expected and correct — `pyproject.toml`'s `dev`
  extra comment says the two coexist deliberately and that uninstalling
  `httpx` breaks MiDaS weight downloads. Do not "clean it up".

---

## Staged recommendation

Disk is not a constraint (752 GB free). Bandwidth is the only real cost, and
it is front-loaded entirely into Stage A.

### Stage A — run the existing detectors over the 9,199 frames

**Packages:** `torch`, `torchvision`. That is the whole list.

```powershell
.venv\Scripts\python.exe -m pip install "torch==2.13.0+cu132" "torchvision==0.28.0+cu132" --index-url https://download.pytorch.org/whl/cu132
```

Then verify before anything else touches the venv:

```powershell
.venv\Scripts\python.exe scripts\verify_cuda.py
.venv\Scripts\python.exe -m pip check
```

`verify_cuda.py` prints `torch.cuda.get_device_capability(0)` and runs a real
CUDA matmul; it exits non-zero if CUDA is not actually available. The number
to see is `(12, 0)` — the same figure the V0.9.1 report recorded.
`scripts/world_builder_env_check.py` additionally dumps
`torch.cuda.get_arch_list()`, which is the direct read on whether sm_120
kernels are compiled in; expect `sm_120` to appear in that list.

**Download:** ~1.94 GB (torch 1.92 GB + torchvision 9.1 MB + ~10.6 MB of
pure-Python deps: sympy, networkx, setuptools, jinja2, filelock, fsspec,
mpmath, MarkupSafe). Installed footprint roughly 4–5 GB.
Plus **14.07 MB** of `ssdlite320_mobilenet_v3_large_coco-a79551df.pth` COCO
weights on first detector load (size confirmed by HTTP range request).

**Expected VRAM:** small. SSDLite320-MobileNetV3 is a mobile-class detector;
budget under 1 GB including the CUDA context. For scale, the MiDaS-small
model on this host measured **82.7 MB allocated**. ~11.1 GB is free. No risk.

**What this unblocks:**
- `tower/experiments/object_detection.py` (the `object_detection` experiment)
- `tower/scene/detect.py` `TorchvisionDetector` — Scene Understanding's
  detection stage
- `tower/scene/orientation.py` `keypointrcnn` — **no additional package**;
  orientation is torchvision-only (see Stage B note)
- `scripts/scene_benchmark.py` with real models instead of `--no-models`
- every "measured on this host" figure in the detection cartridges

**What could go wrong:**
1. **MAX_PATH on unpack** — see above; workaround documented in README.
2. **A partial/interrupted 1.92 GB download** leaving a broken install. If
   the install aborts, `pip uninstall torch torchvision` before retrying
   rather than re-running the install over the wreckage.
3. **`pip check` noise** from the httpx/httpx2 pair — expected, benign,
   documented in `pyproject.toml`.
4. **The one thing Stage A does *not* give you: a harness.** No script in
   `scripts/` currently walks `data/captures/`. `scene_benchmark.py`,
   `cv_lab_benchmark.py` and `world_builder_benchmark.py` all use rendered
   synthetic imagery (`scene_benchmark.py`'s docstring says so in capitals:
   "SYNTHETIC, NOT PHYSICAL"); `feature_trackability.py` and
   `depth_temporal_consistency.py` take `--video`, not a frame directory.
   Running the detectors over the 9,199 real frames needs a small
   directory-walking harness written. Budget that as part of the same task —
   it is maybe an hour, and it is the actual deliverable, not the install.

### Stage B — Scene Understanding / Object Memory extras

**Packages:** `timm`. One package. Everything else is already there.

```powershell
.venv\Scripts\python.exe -m pip install "timm==1.0.28"
```

**Important correction to the brief's framing:** orientation via
`keypointrcnn_resnet50_fpn` needs **no new package** — `tower/scene/orientation.py`
imports it from `torchvision.models.detection`, which Stage A already
installed. Orientation is unblocked by Stage A; only its **236.99 MB** of
`keypointrcnn_resnet50_fpn_coco-fc266e95.pth` weights download on first use.

`timm` exists solely because MiDaS's `hubconf.py` (from `intel-isl/MiDaS`,
loaded via `torch.hub` in `tower/experiments/depth.py`) unconditionally
imports a DPT/BEiT backbone chain, even to load `MiDaS_small`. Without it,
`DepthEstimation.load()` raises `ModuleNotFoundError: No module named 'timm'`.

**Download:** timm plus its transitive set — `huggingface_hub 1.28.0`,
`httpx 0.28.1`, `httpcore`, `certifi`, `safetensors 0.8.0`, `hf-xet 1.6.0`,
`tqdm` — roughly **30–40 MB**. torch/torchvision show as already satisfied,
so nothing large re-downloads.
Model weights on first use: **85.76 MB** (`midas_v21_small_256.pt`) +
**236.99 MB** (KeypointRCNN COCO) if orientation is enabled.

**Expected VRAM:** MiDaS-small measured at **82.7 MB allocated** on this host.
KeypointRCNN-ResNet50-FPN is much heavier — 237 MB of parameters plus FPN
activations at its default 800px min-size; budget **1.5–2.5 GB peak**.
Still comfortable in ~11.1 GB, but this is the first thing here that would
notice a second concurrent CUDA process.

**What could go wrong:**
1. **`timm` installed before Stage A** would pull CPU-only torch from PyPI.
   Order matters. Verify with `pip list | findstr torch` — you want
   `2.13.0+cu132`, not `2.13.0`.
2. **MiDaS weight download failure.** `torch.hub` fetches from GitHub
   releases at first load. Behind a proxy or offline this fails at runtime,
   not install time. README has a section on this (lines 130+).
3. **timm/MiDaS hubconf drift.** `timm 1.0.x` reorganised several backbone
   import paths relative to `timm 0.6.x`, which the MiDaS hubconf chain was
   originally written against. If `DepthEstimation.load()` raises an
   `ImportError` from inside timm rather than a `ModuleNotFoundError`, that
   is the cause, and the fix is pinning an older timm — not reinstalling
   torch. Worth knowing before you start debugging in the wrong place.
4. **Orientation cost.** `scene_benchmark.py` exists specifically to measure
   "the gap between them... the whole reason orientation is off by default".
   Expect it to be expensive; that is a known design fact, not a regression.

### Stage C — OCR for Document Memory

**Package:** `easyocr`.

```powershell
.venv\Scripts\python.exe -m pip install "easyocr==1.7.2"
```

**Download:** ~**54 MB** of genuinely new packages, given Stages A and B —
`scipy 1.18.1` (36.7 MB), `scikit-image 0.26.0` (11.9 MB), `easyocr` (2.9 MB),
`shapely 2.1.2` (1.7 MB), `ninja` (0.3 MB), `imageio` (0.3 MB),
`tifffile` (0.3 MB), `python-bidi` (0.2 MB), `pyclipper` (0.1 MB),
`lazy-loader`. (The resolver's raw total is 190.7 MB, but 126 MB of that is
torch+torchvision, already installed by Stage A.)
EasyOCR then downloads its CRAFT detector and English recogniser weights
(~100 MB combined) on first `easyocr.Reader(...)` construction.

**Expected VRAM:** `tower/document_memory/ocr.py` constructs the reader with
`gpu=False` by default, so **zero VRAM** as currently wired. The docstring
records the CPU cost as measured: reader construction 5.1 s once, then 1.19 s
per page, 0.987 sequence similarity on a rendered 800x1040 page. If flipped
to `gpu=True`, budget well under 1 GB.

**What could go wrong — this is the riskiest stage, but not for the expected
reason:**
1. **OpenCV 5, not OpenCV 4.** This venv has `opencv-python-headless
   5.0.0.93`. `easyocr 1.7.2` predates OpenCV 5 and requests
   `opencv-python-headless` unconstrained, so pip will happily accept cv2 5.
   OpenCV 5 removed and renamed a number of legacy APIs. If easyocr fails, it
   will fail at *runtime* inside `readtext()` with an `AttributeError` or a
   signature error from cv2 — not at install time. **This, not a second cv2,
   is the real Stage C hazard.** Mitigation: run
   `scripts/document_memory_benchmark.py` immediately after install; if it
   breaks in cv2, the fix is a compatibility shim in
   `tower/document_memory/ocr.py`, or `opencv-python-headless<5` — and that
   second option is a whole-project decision, not an OCR decision, so raise
   it rather than doing it.
2. **scipy's `numpy<2.8` ceiling.** Fine at 2.5.2. It becomes a blocker only
   if numpy is later upgraded past 2.7.
3. **`ninja` on PATH.** easyocr declares it; the wheel ships the binary. Only
   an issue in constrained PATH environments.
4. **Not a risk: a second cv2.** Verified above. The `ocr` extra's existing
   comment already got this right.

---

## Is a CPU-only Stage A viable, and is it the smarter first move?

**Viable: yes, comfortably. Smarter: no — and here it is actively harmful.**

**Viability.** `pip install torch torchvision` from plain PyPI yields
CPU-only wheels totalling **126 MB** (vs 1.94 GB), needs no driver, no CUDA,
no Blackwell reasoning at all, and would run every Stage A detector. On
throughput: the V0.9.1 report measured MiDaS-small CPU inference at
**22.7 ms/frame** on this host. SSDLite320-MobileNetV3 is a lighter model, so
call it 25–60 ms/frame; 9,199 frames is then roughly **4–9 minutes** of
wall-clock for a full offline pass. That is nothing. For a first
*measurement* pass over a fixed frame corpus — offline, batch, no latency
requirement — CPU is entirely adequate.

**Why it is nonetheless the wrong first move here, on three grounds:**

1. **It buys risk reduction you have already paid for.** The whole appeal of
   CPU-only is sidestepping the Blackwell question. But the Blackwell
   question is answered — by primary sources *and* by this host's own logged
   run at `torch 2.13.0+cu132`, capability `(12, 0)`. There is no uncertainty
   left to sidestep. You would be buying insurance against a settled fact.

2. **It walks straight into the documented trap.** Installing CPU-only torch
   is *precisely* the `README.md` lines 70–94 hazard: the unconstrained
   `torch` requirement is then satisfied, and the later cu132 install can
   report "already satisfied" without replacing anything. The observable
   symptom is nasty — `TOWER_CV_DEVICE=cuda` raises from `resolve_device()`,
   and `TOWER_CV_DEVICE=auto` **silently falls back to CPU with no error at
   all**. This repo has already been through that once; the weekend report's
   item 5 is the record of it. Doing it deliberately a second time, on
   purpose, to save 1.8 GB of download, is a bad trade.

3. **It doesn't reduce the work; it duplicates it.** The real remaining work
   in Stage A is the missing harness that walks `data/captures/` — that code
   is identical either way. And any CPU-measured figure would have to be
   re-measured on GPU before it could be cited as a Tower baseline, since
   every existing report on this host is GPU-referenced.

**Recommendation: go straight to cu132, and treat CPU-only as a fallback
that gets used only if the cu132 install genuinely fails** (MAX_PATH that
resists the `\\?\` workaround, or a download that cannot complete). If you do
end up on CPU-only for any reason, uninstall it explicitly —
`pip uninstall -y torch torchvision` — before installing from the cu132
index. Never install over it.

---

## Recommended sequence, end to end

```powershell
# 0. Confirm the venv is still clean of torch (should print nothing)
.venv\Scripts\python.exe -m pip list | findstr /I "torch timm easyocr"

# 1. Stage A -- CUDA torch FIRST, before any extra that names torch
.venv\Scripts\python.exe -m pip install "torch==2.13.0+cu132" "torchvision==0.28.0+cu132" --index-url https://download.pytorch.org/whl/cu132

# 2. Prove it before building on it
.venv\Scripts\python.exe scripts\verify_cuda.py               # expect capability (12, 0)
.venv\Scripts\python.exe scripts\world_builder_env_check.py   # expect sm_120 in arch_list
.venv\Scripts\python.exe -m pip check

# 3. Stage B -- depth backbone (orientation already works after step 1)
.venv\Scripts\python.exe -m pip install "timm==1.0.28"

# 4. Stage C -- OCR
.venv\Scripts\python.exe -m pip install "easyocr==1.7.2"
.venv\Scripts\python.exe scripts\document_memory_benchmark.py   # smoke-test cv2 5 compatibility
```

Before each stage, `--dry-run --report <file>` reproduces exactly what this
document checked, without touching the venv. It costs seconds and it is how
every claim above was verified.

**Note on `pyproject.toml`:** the staged commands above deliberately do *not*
run `pip install -e ".[dev,ml,ocr]"`. Running it after Stage A would be
harmless (torch/torchvision already satisfy the unconstrained requirements,
and it would only add `timm`) — but running it *before* Stage A is the trap.
Whether to tighten the `ml` extra with an index pin is a separate decision
and was not made here, per the instruction not to modify `pyproject.toml`.

---

## Sources

Primary, checked 2026-08-26:

- [PyTorch cu132 wheel index — torch](https://download.pytorch.org/whl/cu132/torch/) — cp312 win_amd64 wheels for 2.12.0, 2.12.1, 2.13.0
- [PyTorch cu132 wheel index — torchvision](https://download.pytorch.org/whl/cu132/torchvision/) — cp312 win_amd64 wheels for 0.27.0, 0.27.1, 0.28.0
- [Introducing CUDA 13.2 and Deprecating CUDA 12.8 (Release 2.12) — PyTorch dev-discuss](https://dev-discuss.pytorch.org/t/introducing-cuda-13-2-and-deprecating-cuda-12-8-release-2-12/3337) — cu132 arch list includes Blackwell 12.0; CUDA 12.8 removed from the build matrix
- [PyTorch 2.13 Release Blog](https://pytorch.org/blog/pytorch-2-13-release-blog/) — "CUDA 13.0 remains the default build... the CUDA 12.8/12.9 builds were removed"
- [CUDA Toolkit 13.2 Release Notes — NVIDIA](https://docs.nvidia.com/cuda/archive/13.2.0/cuda-toolkit-release-notes/index.html) — driver >= 580 for CUDA 13.x minor-version compatibility; Windows driver no longer bundled from 13.1; sm_120/sm_121 referenced
- [Compatible NVIDIA GPU drivers on Windows for CUDA Toolkit 13.0+ — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/compatible-nvidia-gpu-drivers-on-windows-for-cuda-toolkit-13-0/371618)
- [NumPy 2.0 Support — pytorch/pytorch #107302](https://github.com/pytorch/pytorch/issues/107302) — NumPy 2 support landed in torch 2.3.0
- [Release 2.4 windows wheels are not compatible with numpy 2.0 — pytorch/pytorch #131668](https://github.com/pytorch/pytorch/issues/131668) — the historical failure, fixed long before 2.13
- [Support NumPy 2.0 — pytorch/vision #8460](https://github.com/pytorch/vision/issues/8460)

Local, in-repo:

- `tower/README.md` lines 62–128 — install-order hazard, cu132 command, MAX_PATH
- `tower/pyproject.toml` — `ml` / `ocr` extras and their rationale comments
- `guidelines/docs/reports/V0.9.1-depth-cv-baseline-report.md` lines 43–44, 67, 91 — the sm_120 proof on this host
- `guidelines/docs/reports/2026-08-20-weekend-autonomous-run-report.md` item 5 — how the venv reached `2.13.0+cpu`
- `tower/scene/detect.py`, `tower/scene/orientation.py`, `tower/experiments/object_detection.py`, `tower/experiments/depth.py`, `tower/document_memory/ocr.py` — the actual import surface

Stale sources encountered and rejected: 2025-era GitHub issues #159207 and
#164342, and the associated forum/Medium posts recommending nightly `cu128`
or WSL2 for Blackwell. Do not act on them.
