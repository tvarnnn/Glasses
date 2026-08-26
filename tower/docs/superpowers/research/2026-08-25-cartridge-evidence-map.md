# Cartridge evidence map and high-level roadmap

**Date:** 2026-08-25
**Method:** three parallel archaeology agents over `tower/`, `ios/` and the
docs tree, plus direct measurement of on-disk artifacts. Every status below is
read off code, tests or data — not off a design document.

---

> ## Superseded in six places — updated 2026-08-26
>
> This remains the orientation document, but four of its findings have since
> been acted on or falsified. Read this block before trusting the tables.
>
> **1. §3.1's headline is fixed. The ML stack is installed.**
> `torch 2.13.0+cu132` and `torchvision 0.28.0+cu132` are in the venv with
> **CUDA working on Blackwell** — `sm_120` in the arch list, capability
> `(12, 0)`, a real kernel executed. `easyocr 1.7.2` is installed and pinned.
> The Blackwell question turned out to be settled by this repo's own history,
> not by research. Detail:
> `2026-08-26-ml-dependency-feasibility.md`.
>
> **2. §6's cheapest evidence has been collected.** The 9,199 real frames have
> now been through a detector. Three cartridge premises moved as a result —
> most importantly, the `person` detections are the **wearer's own torso**
> (median box bottom edge 0.981, 59% touching the frame edge), so this corpus
> is not a validation set for bystander perception and never was. Detail:
> `2026-08-26-real-corpus-first-measurement.md`.
>
> **3. Document Memory's premise did not survive.** It is still IMPLEMENTED,
> but detection fires **6 times in 9,199 frames and all six are false
> positives**. Detection, not recognition, is the binding constraint — the
> inverse of what its own module doc claimed. Its resolution table was also
> measured in **landscape geometries DAT cannot produce**. Detail:
> `2026-08-26-document-memory-reality-check.md`.
>
> **3b. The gate has since been re-derived, and false positives are now
> 0 of 9,199** (`MIN_ROW_TRANSITIONS` 8 -> 31, derived in code from the
> corpus ceiling and the readable-page floor). The deeper finding is that
> `row_transitions` measures crop size, not glyphiness: real on-screen
> text scores *below* real negatives, so the ordering is inverted and no
> threshold on that statistic separates them. A threshold survives only
> because the overlapping content is unreadable anyway — EasyOCR finds
> **zero** text regions in those frames. Detail:
> `2026-08-26-document-gate-rederivation.md`.
>
> **4. Object Memory is no longer blocked, and §3.2's ruling is not what
> gated it.** The Task 4 decision gates registering as a live in-process
> `Module`; every other cartridge produces out of process by tailing a
> capture journal. Object Memory now does the same and has written its first
> **55 real observations**. The `person` ruling is still unresolved and is
> now *sidestepped* rather than pre-empted: a closed whitelist persists only
> `laptop` and `cell phone`, so no bystander record can be written until a
> human decides.
>
> **4b. Object Memory now has a wire path**, its first:
> `tower/routes/observations.py`, registered as a fifth router, read-only
> by construction (`purge`/`prune_expired` unreachable, AST-enforced) and
> unable to widen retention over HTTP. The payload states its own limits
> as fields — `claim: category-was-visible-once`, `identity:
> category-not-instance`, `spatial_ref: null` — because this cartridge
> does not know where anything is.
>
> **5. Scene Understanding's constants were re-derived.** Its tuning
> assumed **~3.3 fps**; the corpus measures **11.97**. `max_misses = 5`
> was documented as 1.5 s of absence and was really **0.42 s**, so a
> person occluded for half a second was recounted as a new person. Now
> `frames_in(MAX_ABSENCE_S)`. Counting at 60% detector dropout went
> **0.252 -> 0.783**. Detail: `2026-08-26-tracker-retune.md`.
>
> **6. This document is no longer the roadmap.** Its title says "and
> high-level roadmap"; that half now lives in
> `docs/agent-handoffs/CARTRIDGE-ROADMAP.md`, which covers all nine
> cartridges, the five blockers, and the dependency order. **This file
> remains the archaeology — what exists.** Two blockers named there are
> not in the tables below: **camera resolution** (360x640 gives ~2 px
> glyphs) and the fact that the lifecycle ruling of §3.2 now gates Scene
> Understanding's wire path too, because that cartridge has no store by
> design and so cannot use the journal-follower escape that freed Object
> Memory.
>
> **What did not change:** there is still no audio path of any kind, so
> Translator, and the voice halves of Visual Q&A and Accessibility, remain
> blocked exactly as described below.

This exists because the same archaeology keeps being redone. It records what is
*built*, what is *designed*, and what has *met hardware* — three different
things that the docs routinely conflate.

---

## 1. The rule this map applies

| Class | Means |
|---|---|
| IMPLEMENTED | code exists and is tested |
| PARTIAL | some layers exist, a named layer does not |
| PLANNED-WITH-DESIGN | a real design doc exists; no code |
| PLANNED-DOC-ONLY | a module doc exists; no design, no code |
| Physically validated | ran against real Ray-Ban glasses, with a report |

Test coverage is not physical validation. Several cartridges are heavily tested
and have never seen a real frame.

---

## 2. Status

| Cartridge | Status | Tests | Physically validated |
|---|---|---|---|
| **World Builder** | PARTIAL → transport now complete | ~310 + 20 iOS | **Partly.** Capture/reconnect on 2026-08-24; first posed reconstruction 2026-08-25. Geometry has never reached a phone |
| **Experimental CV Lab** | IMPLEMENTED | 86 | **Partly.** The `baseline` experiment only, 2026-08-21 |
| **Document Memory** | IMPLEMENTED engine + CLI; no wire contract | 145 | **No.** Synthetic pages only. `data/document_memory/` has never existed |
| **Scene Understanding** | IMPLEMENTED, persists nothing by design | 98 | **No.** There is no imagery of people on this host |
| **Object Memory** | PARTIAL — data layer only, 328 lines, no producer | 33 | **Never run at all** |
| **Environmental Memory** | PLANNED-WITH-DESIGN; the design says *do not begin* | 0 | N/A |
| **Translator** | PLANNED-WITH-DESIGN; two plans, both stamped DO NOT IMPLEMENT | 0 | N/A |
| **Visual Q&A** | PLANNED-DOC-ONLY | 0 | N/A |
| **Accessibility** | PLANNED-DOC-ONLY, additionally hard-blocked | 0 | N/A |

There is no `tower/tower/cartridges/` directory. Cartridges are sibling packages
under `tower/tower/`. "Cartridge" is a docs word; the code says "module" only
for the lifecycle contract.

---

## 3. The four blockers that actually gate the program

Ordered by how much they unblock per unit of work.

### 3.1 ~~The ML stack is not installed — everything model-backed is inert~~

> **FIXED 2026-08-26 — this section is history, not status.** `torch
> 2.13.0+cu132` and `torchvision 0.28.0+cu132` are installed with CUDA
> **executing** on Blackwell `sm_120`, alongside `easyocr 1.7.2`,
> `scipy 1.18.1` and `cv2 5.0.0`. Only `timm` is still missing, which
> gates depth alone. Everything below describes the state that has since
> been resolved; it is kept because the *trap* it documents is still
> live — a bare `pip install .[ml]` resolves **CPU-only** torch from
> PyPI on Windows, and it imports and runs, silently turning every GPU
> figure into a CPU figure.

`torch`, `torchvision`, `timm` and `easyocr` are **absent from the venv**.
Verified independently twice. Only `cv2` 5.0.0 and `numpy` 2.5.2 are present.

So object detection (SSDLite320/COCO), depth (MiDaS), scene detection,
orientation (KeypointRCNN) and OCR (EasyOCR) **cannot run at all right now**,
and every "measured on this host" figure across the docs is currently
unreproducible. No document says so.

The only vendored model is
`tower/models/face_detection_yunet_2023mar.onnx` (232 KB), which works because
`cv2.FaceDetectorYN` is compiled into opencv-headless.

**This is the cheapest high-value item on the board.** Restoring CUDA torch in
the correct install order (`README.md:70-95` documents the hazard) reanimates
three cartridges' worth of measurement.

### 3.2 An unrecorded ruling gates the module lifecycle

`docs/superpowers/plans/2026-08-20-object-memory-first-slice.md:826-896` is a
decision gate that has never been answered. In short: `_do_load()` must load a
detector synchronously, `asyncio.wait_for` cannot interrupt sync CPU work on the
loop thread, so the 10 s `LIFECYCLE_TIMEOUT_S` is fiction; enforcing it makes a
cold-cache first run fail deterministically, and `to_thread` + `mark_failed()`
leaks a loaded model through an ordering bug no `release()` can fix.

Five options are costed. It gates Object Memory tasks 4-8, a **second module
slot** (the V1.0 trigger), and transitively Accessibility and Visual Q&A.

**This one needs a human ruling.** It is an execution-model decision, not a bug.

### 3.3 The `person` ruling

COCO includes `person`. Object Memory's Task 6 as written would persist a record
per bystander. Escalated, unresolved, and it must be decided **before** any code
writes such a record.

### 3.4 No audio path exists anywhere

`tower/frames.py` accepts JPEG only; `Module.process()` takes `bytes` meaning one
still image. *"The only sensor observation this platform has a word for is a
still image."* Every audio library is absent and there is no capture endpoint
attached.

Blocks Translator, and the voice half of Visual Q&A and Accessibility.

Three hardware facts reshape it: Ray-Ban HFP is documented 8 kHz mono (every
ASR candidate expects 16 kHz), A2DP and HFP are mutually exclusive (the wearer
cannot hear high-quality audio while the mic captures), and the mic is reachable
through ordinary `AVAudioSession`, **not** a DAT call.

---

## 4. Shared infrastructure — what exists

| Concern | Where | Note |
|---|---|---|
| Module contract | `tower/modules/base.py` | 6 states; `mark_failed()` is terminal |
| Container | `tower/modules/container.py` | **"Registry of one."** Holds exactly one Module |
| Capability registry | `tower/results/registry.py` | Static, compiled in. Not dynamic discovery |
| Result channel | `tower/results/`, `tower/routes/results_ws.py` | Read-only over state other processes persisted. One slot per subscription, newest wins |
| Geometry transport | `tower/results/world_builder_geometry.py`, `tower/routes/geometry.py` | **New.** HTTP, off the frame socket |
| Capture recorder | `tower/capture.py` | Shared, off by default, bounded, purgeable |
| Capture workers | `tower/capture_workers.py` | One child process per capture lineage, from an argv — cartridge-blind |
| Boundary enforcement | `tests/test_architecture_boundaries.py` | AST-based; includes an AST-level ban on gaze/identity vocabulary |

**What does not exist:** multi-consumer frame distribution, frame metadata into
modules, any asynchronous execution path (no worker, queue or executor anywhere
in `tower/`), cartridge-declared sensor requirements.

### The frame fan-out, precisely

One decode-and-dispatch feeding **one** module. Every other cartridge runs
**out of process**, tailing the capture journal via `CaptureFollower`. Only
World Builder is auto-attached, because `main.py` hardcodes one `WorkerSpec`.

There is **no shared inference**: three separate sites load the same SSDLite320
COCO weights independently, and sharing is explicitly refused for now on the
grounds that the consumers want different things from the same weights.

---

## 5. Dependency graph

```
  ML stack restored (§3.1)  ── unblocks measurement for ──┐
                                                          │
  Lifecycle ruling (§3.2) ──┬─ Object Memory 4-8          │
                            ├─ second module slot          │
                            └─ Accessibility, Visual Q&A   │
                                                          │
  `person` ruling (§3.3) ──── Object Memory persistence    │
                                                          │
  Audio path (§3.4) ────────┬─ Translator                  │
                            └─ voice half of VQA / A11y    │
                                                          │
  World Builder geometry ───┬─ Object Memory spatial ◄─────┘
   (transport done;          ├─ Scene Understanding spatial
    registration NOT)        └─ Environmental Memory "where"
```

**World Builder's registration gap propagates.** Three cartridges want "where",
and no cartridge can answer it while segments share no coordinate frame. The
Environmental Memory study put it bluntly: of *"what was in this room earlier?"*,
the word **"room" is not weakly supported — it is not supported at all.**

---

## 6. The cheapest evidence available, unclaimed

`data/captures/` holds **18 captures, 9,199 real Ray-Ban frames** at 360×640
portrait. **No detector or OCR has ever been run on any of them.**

Document Memory's OCR benchmark used **landscape** frame sizes while every real
frame is **portrait** — so the delivered case may be worse than the worst row in
its table, and nobody has checked. Word recall was already 0.43–0.81 at 640×360
against 0.96–1.00 at 1280×720.

Running the existing detectors over that corpus is roughly ten seconds of CPU
and can falsify several cartridge premises. It is blocked only by §3.1.

---

## 7. Recommended order

1. **Physically validate the geometry transport.** Handoff written. Cheap, and
   it closes World Builder's product path.
2. **Restore the ML stack** (§3.1). Cheapest unblock on the board.
3. **Run the 9,199 frames through what exists** (§6). Highest evidence per
   minute; may falsify premises before they cost implementation.
4. **Get the two rulings** (§3.2, §3.3). Human decisions; nothing routes around
   them.
5. **Then World Builder registration** — covisibility before bundle adjustment,
   because BA measured 0.00% drift improvement on a chain graph with median
   covisibility span 1. Three cartridges are waiting on this.
6. **Then capture resolution.** DAT offers 720×1280; the app streams 360×640;
   frames are ~20.8 KB JPEG at ~2 Mbps, so there is headroom. This is a
   correctness lever on tracking, not a cosmetic one — and it may move Document
   Memory's OCR recall from 0.43 to near 1.0 at the same time.

Note that 1080p is **not** available. `07-PLATFORM-CONSTRAINTS.md:79` lists
`high` 720×1280, `medium` 504×896, `low` 360×640, all 9:16. There is no
landscape mode, so the ~45° horizontal field is fixed by the SDK at every
resolution.

---

## 8. Stale documentation found

| Claim | Reality |
|---|---|
| `EXPERIMENTAL-CV.md:275-279`: face detection BLOCKED, "no ONNX file exists anywhere on disk" | False. YuNet is vendored and in production use |
| `SCENE-UNDERSTANDING.md:357`: "torch is CPU-only on this host" | torch is not installed at all |
| `03-ROADMAP.md:112` cites `tower/modules/depth_cv.py` | Deleted at V0.9.5 — the same doc says so 40 lines later |
| `04-MODULE-SYSTEM.md:198`: recorder writes under `data/world_builder/captures/` | Actual path is `data/captures/`, and putting the shared recorder under a cartridge prefix is what `capture.py` argues against |
| `IOS-to-Tower.md:62`: capability declaration "MISSING — TOWER NEEDED" | Implemented since 2026-08-23 |
| Every doc treating calibration as the standing blocker | A `self_calibrated` record for 360×640 has existed since 2026-08-25 |
| `2026-08-25-FINAL-HANDOFF.md:91-97`: the iOS client "is in no branch of this repository" | It was on `origin/ios/world-builder-integration` the whole time; that handoff searched only the `ios-origin` remote |
