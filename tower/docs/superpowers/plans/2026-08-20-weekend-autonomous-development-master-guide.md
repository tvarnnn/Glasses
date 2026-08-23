# Weekend Autonomous Development Master Guide

**Status: PLANNING DOCUMENT ONLY. Not authorization to execute. A human must
give an explicit greenlight after reviewing this guide before any milestone
below is started.**

Date written: 2026-08-20. Written by a planning-only Claude Code session per
the user's explicit instruction to research, audit, and document — not to
implement. If you are a future Claude session reading this after context
loss: **stop and confirm with the user that greenlight was actually given**
before treating anything below as authorized. This document being findable
in the repository is not itself authorization; it exists so that once
authorization *is* given verbally or in a follow-up message, you have
everything you need without re-deriving it.

---

## 1. Project Vision (verified against `guidelines/docs/00-PROJECT-VISION.md`)

The Glasses platform is a modular wearable AI platform: Ray-Ban Meta glasses
are a first-person sensor/output endpoint, a custom Swift iPhone app is the
control plane and network bridge, and a persistent Windows Tower runtime
performs compute-intensive CV/AI work. The goal is not one glasses app — it's
a reusable host/runtime capable of hosting a growing library of interchangeable
wearable applications ("modules" / "cartridges"). Only one major module is
active at a time in V1. See `guidelines/docs/00-PROJECT-VISION.md` for the
full statement; this section is a compressed pointer, not a replacement.

Canonical doc set (read these directly, don't rely on this guide's summaries
for architectural rules):
- `guidelines/docs/00-PROJECT-VISION.md`
- `guidelines/docs/01-SYSTEM-ARCHITECTURE.md`
- `guidelines/docs/02-DEVELOPMENT-RULES.md` — **read this in full before any
  implementation work; Rule 17 in particular governs how much deference these
  docs are owed.**
- `guidelines/docs/03-ROADMAP.md`
- `guidelines/docs/04-MODULE-SYSTEM.md`
- `guidelines/docs/05-DAT-INTEGRATION.md`
- `guidelines/docs/06-PRIVACY-DATA.md`
- `guidelines/docs/07-PLATFORM-CONSTRAINTS.md`
- `guidelines/docs/modules/*.md` (per-module design seeds)
- `guidelines/docs/prompts/*.md` (task-entry prompts — `START-HERE.md` is the
  canonical "how to begin a session" prompt; this guide supplements it for
  the specific weekend-autonomous-run context, it does not replace it)

## 2. Verified Starting State (as of this planning session, 2026-08-20)

Verified directly against the repository, not assumed from the user's prompt:

- **Repo:** `C:\Users\tvllo\Projects\GlassesTower`, branch `master`, HEAD at
  commit `a6030fc` ("fix: address final whole-branch review findings for
  V0.9.1 depth CV baseline") at the start of this session. This is the Tower
  runtime repo only — **no iOS/Swift code exists in this repository.** The
  iPhone app lives in a separate repo/environment not present here (see
  §4 and §24).
- **Tests:** `98 passed, 3 skipped, 1 warning` (`pytest`, ~1.2s). The 3 skips
  are all in `tests/test_depth_experiment_integration.py`, gated behind
  `TOWER_RUN_MODEL_TESTS=1` because they need a real torch install and a
  first-run MiDaS weight download — a deliberate, correctly-implemented
  opt-in gate, not a neglected test (see
  `docs/superpowers/research/2026-08-20-testing-reliability-techdebt-audit.md`
  §1). The 1 warning is a cosmetic `StarletteDeprecationWarning`
  (httpx vs. httpx2), not investigated further.
- **Milestones complete:** V0.7 (sustained streaming instrumentation — a real
  mock-device-kit/iPhone-driven measurement run is complete and filled in,
  ~14.3 minutes, 695 frames; the roadmap's 20-30 min duration target was not
  literally reached and **physical-glasses validation is still deferred**
  — see `guidelines/docs/reports/V0.7-sustained-streaming-report.md`), V0.8
  (module container / "registry of one"), V0.9
  (Experimental CV Lab: `baseline`, `edge_detection` experiments), V0.9.1
  (stateful MiDaS-small monocular depth experiment, CPU+CUDA both measured
  and working — see `guidelines/docs/reports/V0.9.1-depth-cv-baseline-report.md`).
- **GPU:** RTX 5070 confirmed present (`nvidia-smi`: driver 596.21, CUDA
  13.2). **`torch` is currently NOT installed in the active `.venv`** — it is
  an optional `ml` extra (`pip install -e ".[dev,ml]"`, with a specific
  CUDA-index install-order caveat documented in `README.md`). Any session
  that wants to run or extend the `depth` experiment, or any new model-backed
  experiment, needs to reinstall it first — this is expected, not a
  regression (see `guidelines/docs/01-SYSTEM-ARCHITECTURE.md`, GPU/Acceleration Strategy: PyTorch is optional core-wide).
- **DAT/Meta Wearables MCP:** **not configured in this Windows Claude Code
  environment** — no `search_dat_docs` or equivalent tool is available here.
  Any task requiring current DAT documentation (`02-DEVELOPMENT-RULES.md`
  Rule 4) cannot be completed from this machine/session; it needs a Mac-side
  session where that MCP is configured (see §24).
- **Untracked file found at session start:**
  `docs/superpowers/plans/2026-08-19-v0.7-sustained-streaming-instrumentation.md`
  — this is the (already-executed) V0.7 implementation plan, never committed.
  Verified its content matches what's actually in the codebase (`tower/metrics.py`,
  `tests/test_ws_sustained.py`, `scripts/soak_test_stream.py` all exist and
  match the plan). Recommend committing it as-is (historical record of
  completed work) as part of this session's documentation commit — it is not
  a decision requiring the weekend run's judgment, just a housekeeping gap.
- **Stale git worktree found:** `.claude/worktrees/v0.8-module-container` —
  checked via `git -C <path> status`/`log`: it is on branch `master`, has the
  same single untracked file as the main tree, and no unique commits or
  uncommitted work. Almost certainly a harmless leftover from the V0.8
  implementation session. **Do not delete it autonomously** — flag it to the
  user; removing a worktree is a `git worktree remove`-class operation this
  guide's stop conditions treat as needing confirmation (see §23), even
  though the evidence strongly suggests it's inert.
- **Research produced this session** (seven documents from six research
  tracks — one track produced two companion documents — all under
  `docs/superpowers/research/`, all read in full and synthesized into this
  guide — do not re-read them in full again unless you need a specific
  detail this guide didn't carry forward):
  1. `2026-08-20-platform-backend-audit.md`
  2. `2026-08-20-testing-reliability-techdebt-audit.md`
  3. `2026-08-20-world-builder-foundations.md`
  4. `2026-08-20-canonical-memory-architecture.md`
  5. `2026-08-20-document-memory-design.md`
  6. `2026-08-20-hermes-agent-evaluation.md`
  7. `2026-08-20-gpu-nvidia-roadmap.md`

## 3. Current Runtime Architecture (verified against code, not just docs)

```text
Ray-Ban Meta Glasses -> Meta DAT -> Swift iPhone app (separate repo)
        -> WebSocket -> Tower (this repo, Python/FastAPI)
        -> ModuleContainer (registry of one) -> active Module
        -> frame_result -> iPhone -> Glasses/user
```

Tower source layout (`tower/`, 19 files) — see `README.md`'s "Project
Structure" section for the authoritative, current listing; it is kept
up to date and this guide does not duplicate it. Key facts verified in this
session (grounded in `docs/superpowers/research/2026-08-20-platform-backend-audit.md`):

- **Module lifecycle** (`tower/modules/base.py`, `container.py`):
  `UNLOADED -> LOADING -> READY -> ACTIVE -> STOPPING/FAILED`, matches
  `04-MODULE-SYSTEM.md` exactly, bounded 10s timeouts on every lifecycle call
  via `asyncio.wait_for`, `FAILED` short-circuit calls `_do_release()`
  best-effort. **Known real gap:** this timeout mechanism cannot bound a
  *synchronous* blocking call inside `_do_load()` — and `DepthEstimationModule`
  does exactly that (`torch.hub.load(...)`, a synchronous, network-touching
  call). It currently only bites at process startup (no live-serving window
  exposed), so urgency is low, but it is a real, verified gap between what
  `LIFECYCLE_TIMEOUT_S` appears to guarantee and what it does. See §9 and the
  techdebt audit §3a.
- **Module switching at runtime does not exist.** `ModuleContainer` has
  exactly `load_and_start()` (called once at process startup) and
  `shutdown()` (called once at process shutdown). There is no
  `switch_to(new_module)` path. The only way to run a different experiment
  today is `TOWER_CV_EXPERIMENT=<x>` + process restart. This is intentional
  "registry of one" scope per `03-ROADMAP.md` V0.8, not a bug — but it means
  V1.0/V1.1 (registry generalization, lifecycle hardening across real
  switches) is **not yet started at all**, not partially built.
- **Error propagation to the WS client is incomplete.** A `FrameSkippedError`
  or a fully `FAILED` module both currently just... stop sending
  `frame_result` messages, with nothing pushed to the client explaining why.
  `GET /health` would show the truth, but the client has to poll it
  separately. This already undercuts Rule 3 (truthful state) for the module
  that exists *today*. See §9, MUST item 1.
- **No persistence layer exists anywhere in `tower/`.** Both real modules
  declare `persists_data=False` and mean it. This is fine today and a hard
  blocking prerequisite for any memory module (Object/Document/Environmental
  Memory) — see §7 and §11.
- **No auth/encryption; `TOWER_HOST` defaults to `0.0.0.0`.** Confirmed
  still-accurate per `07-PLATFORM-CONSTRAINTS.md` Limitation 11; explicitly
  planned for Phase 1.5 (Tailscale/WireGuard), not this weekend's scope.

## 4. Development vs. Runtime Topology

**This is a critical distinction the original planning prompt specifically
asked to be made explicit, and the codebase itself already enforces it
structurally: this repository contains zero iOS/Swift code.** The runtime
topology is:

```text
RUNTIME:      Glasses -> iPhone (control plane + transport bridge) -> Tower (compute)
DEVELOPMENT:  Windows machine (this repo, this Claude session) = Tower dev environment
              Mac (separate repo/session, not visible here) = iPhone dev environment
```

The Mac/iPhone is **not** a required runtime hop for anything Tower-side —
it's the control plane and transport bridge at runtime, and a separate
*development machine* for iOS work. Windows Claude (this session and its
successors) must never conflate "I can't test the iOS side from here" with
"the iOS side isn't part of the runtime" — it is, it's just developed
elsewhere.

**Implication for the weekend run:** Windows Claude Code running in this repo
can verify, test, and modify Tower-side code end-to-end, including protocol
message *shapes* the Tower emits, but cannot build/run/test the iOS side, and
does not have DAT documentation access (§2). Any task that would require
changing the iPhone app, changing Swift code, or looking up current DAT API
behavior must produce a **Mac-side handoff document** instead of attempting
the change directly — see §24 for the required handoff format.

## 5. Existing Modules

Exactly one real module family exists: **Experimental CV Lab**
(`tower/modules/experimental_cv.py`, `tower/modules/depth_cv.py`), selectable
via `TOWER_CV_EXPERIMENT`, with three experiments: `baseline` (grayscale +
mean intensity), `edge_detection` (Canny), `depth` (MiDaS-small monocular
relative depth, CPU/CUDA both measured). All three share `descriptor.id =
"experimental-cv"` — from the platform's perspective this is one module with
three interchangeable inner behaviors, not three modules.

No other module (World Builder, Object Memory, Environmental Memory,
Document Memory, Visual Q&A, Accessibility, Translator) has any
implementation. All exist only as design-seed specs under
`guidelines/docs/modules/`, except Document Memory, which had no spec at all
until this session produced a research-seed proposal (§11).

## 6. Planned Modules — Current Design-Seed State

| Module | Spec exists? | Roadmap positioning | This session added |
|---|---|---|---|
| World Builder | Yes (`WORLD-BUILD.md`) | Phase 3, no early-starter claim | Bounded next-experiment sequence (§10) |
| Object Memory | Yes (`OBJECT-MEMORY.md`) | Phase 3, "strong bounded candidate for an early production module" | Confirmed by backend audit as the recommended next production module (§9) |
| Environmental Memory | Yes (`ENVIRONMENTAL-MEMORY.md`) | Phase 3, highest privacy exposure, gated on real retention/deletion being *implemented* first | — |
| Document Memory | **No — did not exist before this session** | Not on `03-ROADMAP.md` at all yet | Full research-seed spec produced (§11) |
| Visual Q&A | Yes (`VISUAL-QA.md`) | Phase 3, "comparatively heavy," not an early starter | — |
| Accessibility | Yes (`ACCESSIBILITY.md`) | Phase 3, experimental-assistive framing only | — |
| Translator | Yes (`TRANSLATOR.md`) | Explicitly "not scheduled," future concept only | — |

## 7. Shared Platform Services — What Exists, What's Missing

Full item-by-item audit:
`docs/superpowers/research/2026-08-20-platform-backend-audit.md`. Headline
conclusion (do not re-derive this — it's already the audit's direct answer to
"should we build more shared infrastructure before adding modules"):

> **Build the next production module — do not run a standalone
> infrastructure-hardening milestone first.** Most named "gaps" (settings
> schema, capability negotiation, protocol versioning, uniform output
> contract, module switching, shared model cache) are gaps only relative to a
> multi-module future that doesn't exist yet, and `03-ROADMAP.md` already
> names them as V1.0/V1.1 work triggered by a second production module's
> real requirements. Building them now would be exactly the speculative
> generalization Rule 10 prohibits.

Four exceptions the audit found genuinely load-bearing *now*, not
speculative — see §9 for how these map to weekend milestones:

1. WS error propagation to the client (cheap, fixes a present-day Rule 3 gap).
2. Persistence + a real working purge path (`06-PRIVACY-DATA.md` explicitly
   forbids real data collection by Object/Environmental Memory before this
   exists — hard blocker, not a preference).
3. `seq` -> `source_seq`/`tx_seq` split or equivalent capture/receive
   timestamps (needed before any history-keeping module can reason about
   temporal gaps; cheap now, expensive to retrofit into accumulated data
   later). **Note:** this touches the wire protocol shape — Tower-side
   changes can be additive/backward-compatible, but full utility requires an
   iPhone-side sender change. Treat as Tower-side prep + a Mac-side handoff,
   not a unilateral protocol change (§4, §24).
4. Module switching / registry generalization (V1.0/V1.1) — not a "fix
   before" item, this *is* the shape of the milestone that follows the next
   production module.

## 8. Research Conclusions — Index

Each research document is authoritative for its topic; this guide summarizes
conclusions and gives them a place in the sequence, but defers to the
document itself for reasoning/evidence/sources. Read the linked document
before making a decision that depends on its findings — do not act on this
guide's one-paragraph summary alone for anything consequential.

## 9. Platform Backend Completion Audit — Summary

See §3 and §7 above, and the full document:
`docs/superpowers/research/2026-08-20-platform-backend-audit.md`.

**Combined with the testing/reliability audit**
(`docs/superpowers/research/2026-08-20-testing-reliability-techdebt-audit.md`),
the following near-term, non-speculative fixes are identified — these are
the MUST-track candidates in §17:

| Fix | Source | Risk/cost | Autonomous-safe? |
|---|---|---|---|
| WS `frame_error`/`module_failed` client-facing message | backend audit #8 | Low — one new message type, additive | Yes |
| `ws.py` main loop has no catch-all for malformed non-dict/non-JSON messages | techdebt audit §5 | Low — small, local, reversible | Yes |
| Cosmetic `StarletteDeprecationWarning` (httpx→httpx2) | techdebt audit §1 | Trivial dependency swap | Yes |
| Lifecycle timeout can't bound synchronous blocking `_do_load()` (real for `torch.hub.load()`) | techdebt audit §3a | Needs a real design decision (e.g. `asyncio.to_thread`) — changes the lifecycle contract's execution model | **No — needs user judgment**, not a silent autonomous patch (see §22) |
| No auth/encryption; `0.0.0.0` bind default | techdebt audit §4 | Explicitly planned for Phase 1.5 | **No — needs user judgment / already scheduled elsewhere** |
| `backpressure_drops` always 0 / no stale-frame dropping | techdebt audit §3d | Correctly deferred per V0.9.1's own recorded decision rule | No action — not a finding, a confirmed non-issue |

## 10. CV / World Builder Foundations — Summary

Full document: `docs/superpowers/research/2026-08-20-world-builder-foundations.md`.

**Do not jump to any SLAM/VO library.** Four bounded, ordered Experimental CV
Lab experiments, each following `EXPERIMENTAL-CV.md`'s Success Criteria
pattern (hypothesis/dataset/metric/baseline/result):

1. **`depth_temporal_consistency`** (Low risk) — does naive per-frame
   MiDaS-small output flicker on real continuous motion, and does cheap
   post-hoc smoothing fix it? Reuses the shipped `DepthEstimationModule`
   unmodified; needs a bounded, opt-in capture of full per-frame depth
   arrays for a short real clip.
2. **`feature_trackability`** (Low risk) — does ordinary, undirected glasses
   motion produce frame pairs with enough shared trackable structure (ORB +
   RANSAC-verified matches) to make any multi-view geometry worth
   attempting at all? This is the load-bearing open question — egocentric
   wearable video is a real, currently-untested question for this platform:
   standard VO/SLAM benchmark datasets are generally captured with more
   deliberate, steady, or robot-mounted motion than casual wearable use, and
   nothing in the existing literature or this platform's own data confirms
   that assumption transfers.
3. **`monocular_pose_feasibility`** (Medium-High risk — the single biggest
   unknown in the whole sequence) — can a real-time-viable monocular VO
   approach (classical `recoverPose` first; DPVO/DPV-SLAM or NVIDIA cuVSLAM
   as escalation candidates, each with real integration risk) produce a
   qualitatively plausible trajectory on this hardware. **Hard prerequisite:
   camera intrinsics for the DAT stream do not exist anywhere in this repo**
   — this blocks the experiment and requires either `search_dat_docs` (Mac
   session, §4/§24) or empirical calibration.
4. **`depth_scale_fusion`** (Medium risk) — combine stabilized depth (from
   Experiment 1) with a scale signal (ground-plane heuristic, a metric-depth
   model swap, or Experiment 3's pose) and measure error against physically
   taped real-world reference distances.

**Explicitly not yet:** full SLAM (ORB-SLAM3/DROID-SLAM), loop closure,
persistent map storage, TSDF/point-cloud fusion, Gaussian Splatting (actively
judged "currently impractical," not merely "later" — see the document's
§1.6), live viewer. All correctly deferred per existing docs; this research
reinforces rather than challenges that.

**Data availability constraint for the weekend run:** Experiments 1, 2, and 3
all need real motion footage (mock-device-with-motion, webcam, or
phone-camera clip) — synthetic single-frame JPEGs (as used in
`scripts/depth_benchmark.py`) cannot exercise any of them. **Confirm a usable
real-motion clip is actually obtainable in this environment before starting
Experiment 1 or 2** — if not, these drop from MUST/SHOULD to STRETCH or are
blocked entirely pending a Mac-side/physical-device session (§24).

## 11. Document Memory — Design Summary

Full documents:
`docs/superpowers/research/2026-08-20-document-memory-design.md` (the module
spec) and `docs/superpowers/research/2026-08-20-canonical-memory-architecture.md`
(the cross-cutting memory question it depends on).

Document Memory is a **research-seed proposal, not yet promoted into
`guidelines/docs/modules/`.** It should be reviewed and, if approved,
formally promoted (moved/adapted into `guidelines/docs/modules/DOCUMENT-MEMORY.md`
and added to `03-ROADMAP.md`) as an explicit user decision — not silently
adopted by a future autonomous session just because a well-written doc exists
in `docs/superpowers/research/`.

Key design points: passive capture (dwell/stability/completeness heuristics
decide when a reading event is confident enough to persist — never a
per-document "remember this" command requirement, matching World Build's
Passive Operation Requirement), OCR approach undecided pending measurement
(Tesseract/PaddleOCR classical family vs. a local VLM — PaddleOCR-VL named as
a promising newer option blurring the line), strict anti-hallucination
requirement (never answer beyond what was actually OCR'd; explicit "insufficient
evidence" is a first-class required response), and default-conservative
retention (derived text/embeddings persisted, raw imagery discarded after the
in-memory dwell window unless a specific future feature justifies otherwise).

## 12. Canonical Memory Architecture — Summary

Full document: `docs/superpowers/research/2026-08-20-canonical-memory-architecture.md`.

**Do not build a shared memory service, database, or retrieval API now** —
zero memory modules are implemented, so there is no real evidence to
generalize from (mirrors the platform's own V1.0 registry-generalization
trigger). **Do adopt a shared conceptual "observation record" shape**
(provenance, timestamps split by observation-vs-record-created, confidence
including explicit UNKNOWN, source type, module ownership, reserved-but-unused
`external_refs`/`spatial_ref` fields, privacy tags, retention tag, real
tombstone-deletion) inside each module's own storage — zero coordination
cost, directly operationalizes `07-PLATFORM-CONSTRAINTS.md` Limitation 15,
and avoids an archaeology-style migration later if a real cross-module need
appears. **Promotion trigger:** two memory modules actually implemented,
showing a concrete repeated need for something on the deferred list (a real
cross-namespace join, a real shared embedding, a real agent-access
requirement with its own privacy review already done) — not anticipated in
advance.

Storage-technology recommendation for whichever module implements
persistence first: start with the simplest thing that works for V1 scale
(plain files/NumPy for a single module's small store), move to SQLite +
`sqlite-vec` only once actually measured necessary, treat this as each
module's own implementation decision per `04-MODULE-SYSTEM.md` ("storage
technology may differ by module"), not a platform-wide choice to lock in now.

## 13. Hermes Agent Evaluation — Summary

Full document: `docs/superpowers/research/2026-08-20-hermes-agent-evaluation.md`.

**Recommendation: do not adopt Hermes Agent now; do not plan around it as
the platform's future agent/orchestration layer.** This is a reasoned
rejection, not a "revisit later" hedge:

1. Hermes Agent's core identity (self-curated, always-on, cross-session
   memory as its headline differentiator) is structurally incompatible with
   the platform's explicit requirement that Glasses, not the agent
   framework, own canonical memory — and this cannot be configured away, only
   fought release-to-release.
2. One concrete, load-bearing latency data point (8-15s per tool call on a
   common local Ollama configuration) directly threatens the first realistic
   use case (`VISUAL-QA.md`'s low end-to-end latency requirement).
3. Pre-1.0 (`v0.20.4`), very fast release cadence, large open-issue backlog
   — a risky foundation for a platform-critical layer.
4. The bulk of its actual feature surface (16 messaging gateways,
   self-evolution/skills subsystem) is irrelevant carried weight — exactly
   the unjustified complexity Rule 17 asks to be challenged.
5. **Preferred alternative:** a small custom tool-calling layer built
   directly on a model provider's native tool-use/MCP support achieves the
   platform's actual target shape (`Glasses Memory/Services <-> defined
   tools/MCP <-> reasoning model`) more directly, with less code than it
   would take to safely neutralize Hermes's memory system.

**This is not scoped for the weekend run at all** — no module in §17's
MUST/SHOULD/STRETCH requires an agent layer. Flagged here only so a future
session doesn't independently reach for Hermes without checking this
evaluation first. See the document's §11-12 for concrete adoption/rejection
criteria if this is ever revisited.

## 14. NVIDIA / GPU Roadmap — Summary

Full document: `docs/superpowers/research/2026-08-20-gpu-nvidia-roadmap.md`.

**No further NVIDIA-specific tooling is justified right now.** V0.9.1's one
data point (MiDaS-small, inference-dominated, CUDA already ~32% faster on
the bottleneck stage, absolute inference cost already only ~15ms) doesn't
show a problem any of these candidates would fix:

| Candidate | Classification |
|---|---|
| TensorRT (Torch-TensorRT) | Useful after specific trigger — a future model's `inference` stage both dominates *and* is large enough to violate a defined latency budget CUDA alone can't meet |
| CV-CUDA | Probably unnecessary — preprocess/decode aren't the bottleneck, **and it has no native Windows support today** (Linux/WSL2 only — new finding this session) |
| DeepStream | Probably unnecessary — **confirmed zero Windows support at any point**, not merely a poor architectural fit (new, stronger finding this session) |
| FP16/quantization | Useful after specific trigger — cheaper first step than TensorRT once inference dominance is re-confirmed on a heavier model |
| `torch.compile`/CUDA graphs | Research only — **blocked on Windows today**, Triton has no official Windows support (new finding this session) |
| ONNX Runtime EPs | Probably unnecessary — redundant with Torch-TensorRT for a PyTorch-based Tower |

**Smallest next measurement that would move this decision:** run the same
`depth_benchmark.py`-style CPU-vs-CUDA harness with per-stage instrumentation
against one heavier/structurally-different model — an object detector is the
natural next candidate already listed in `EXPERIMENTAL-CV.md`. Not scoped for
this weekend unless Object Memory work (§17) reaches the point of needing a
real detector, at which point this benchmark is a natural side-artifact of
that work, not a separate milestone.

## 15. Module Dependency Graph

```text
                    Experimental CV Lab (exists)
                    baseline / edge_detection / depth
                            |
              +-------------+--------------+
              |                            |
   World Builder bounded experiments   Object Memory
   (Exp. 1-4, §10 — still inside       (needs: persistence + purge [§7 item 2],
    Experimental CV Lab, no new         needs: an object detector — itself a
    module, no registry change)         candidate for the next GPU benchmark
              |                         data point [§14])
              |                                |
   [camera intrinsics — blocked on     [V1.0 registry generalization +
    Mac-side DAT docs or empirical      V1.1 lifecycle hardening across
    calibration, §10/§24]               real switches — triggered BY
              |                         building this module, not before]
   World Builder itself                        |
   (Phase 3, not started,               Environmental Memory
    depends on Exp. 1-4 outcomes)       (Phase 3, gated on real
                                         retention/deletion actually
                                         implemented first, per
                                         06-PRIVACY-DATA.md)
                                                |
                                         Document Memory
                                         (research-seed only, §11 —
                                         needs the same persistence+purge
                                         prerequisite; NOT yet on
                                         03-ROADMAP.md; needs explicit
                                         user promotion decision first)

   Visual Q&A / Accessibility / Translator — Phase 3, no early-starter
   claim in any research this session; Visual Q&A specifically flagged as
   latency-sensitive in a way that rules out Hermes Agent (§13) and would
   need its own local-model/latency research before scoping.

   Hermes Agent — REJECTED for now (§13). Not a dependency of anything above.
```

**Reading this graph:** the two real "next module" candidates are Object
Memory (roadmap-endorsed, backend-audit-endorsed, and the mechanism that
would naturally trigger V1.0/V1.1) and the World Builder bounded-experiment
sequence (research-endorsed, stays inside the existing Experimental CV Lab,
no registry/module-switching work required). These are **not mutually
exclusive** and can proceed on independent tracks, but per §17/§25, only one
should be the weekend's MUST-track focus — pick based on data availability
(§10's real-motion-footage constraint) more than abstract preference.

## 16. Recommended Milestone Sequence

Following `03-ROADMAP.md`'s existing numbering — this guide does **not**
renumber or reinterpret V1.0/V1.1/V1.2. It proposes what would fill the gap
between the current state (V0.9.1) and those already-named milestones.

- **V0.9.2 — Backend Truthfulness & Reliability Hardening** (new, small,
  proposed — not yet in `03-ROADMAP.md`; promoting it there is a documentation
  decision the weekend run may make per §22's autonomous-decision authority,
  since it's recording completed work, not proposing new scope): the three
  MUST-track fixes in §9's table that are autonomous-safe (WS error
  propagation, malformed-message handling, cosmetic dependency fix) plus
  regression tests. Explicitly excludes the two "needs user judgment" items
  (synchronous lifecycle timeout gap, auth/encryption) — those stay
  documented findings, not silent patches.
- **V0.9.3 — World Builder Foundations, Experiment 1-2** (new, small,
  proposed): `depth_temporal_consistency` and `feature_trackability` from
  §10, if real-motion footage is actually available (§10's stated
  constraint) — these are independent of each other and can run in either
  order.
- **V1.2 — First Promoted Production Module** (already named in
  `03-ROADMAP.md`): Object Memory, per the roadmap's own framing ("a strong
  bounded candidate for an early production module") and the backend audit's
  independent confirmation. This is realistically **not** a single-weekend
  deliverable in full (see §17) — the weekend's job is to make credible,
  cleanly-tested progress toward it, not necessarily finish it.
- **V1.0/V1.1** (already named, unchanged): triggered by V1.2's real
  requirements, built together with it per the roadmap's existing sequencing
  — not attempted speculatively ahead of V1.2.

**World Builder Experiment 3 (`monocular_pose_feasibility`) is explicitly
NOT scheduled for this weekend** — it's blocked on camera intrinsics (§10),
which is a Mac-side/DAT-docs or empirical-calibration prerequisite this
Windows session cannot resolve alone (§4).

## 17. MUST / SHOULD / STRETCH — Weekend Scope

Per the user's explicit instruction: **quality over module count.** One
milestone finished cleanly beats four half-built systems.

### MUST (should realistically complete)

1. V0.9.2's autonomous-safe fixes (§9 table, 3 items) with regression tests,
   each as its own small commit.
2. Confirm (do not assume) whether real-motion footage is actually obtainable
   in this environment for World Builder Experiment 1/2 — this is itself a
   MUST-track task, because it gates everything else in §10/§16, and it's
   cheap to determine early.
3. If real-motion footage is confirmed available: `depth_temporal_consistency`
   (Experiment 1, §10) — lowest risk, reuses the shipped module unmodified,
   produces a measured report per `EXPERIMENTAL-CV.md`'s pattern.

### SHOULD (if MUST completes cleanly and time/budget remain)

4. `feature_trackability` (Experiment 2, §10) — if Experiment 1 went
   cleanly and footage supports it.
5. Object Memory: **design/spec review only** — read `OBJECT-MEMORY.md`
   against the current module contract (`tower/modules/base.py`), identify
   the concrete first-slice scope (the audit and roadmap both say "bounded
   V1," not full spatial/re-ID), and write an implementation plan (per the
   `superpowers:writing-plans` skill) for review. **Do not start writing the
   module's actual `_do_process()`/detector/persistence code without a
   completed, reviewed plan** — this is exactly the kind of module-shaped
   work that benefits from the plan-then-implement discipline this project's
   own `guidelines/docs/prompts/NEW-MODULE.md` already asks for.

### STRETCH (only if MUST+SHOULD complete with real time/budget left)

6. Begin Object Memory implementation from the SHOULD-track plan — module
   descriptor, lifecycle wiring, a minimal persistence namespace with a real
   working purge path (§7 item 2), using subagent-driven-development per
   §21. **Watch for the known lifecycle-timeout bug pattern (§9's table,
   techdebt audit §3a):** if this module's `_do_load()` performs any
   synchronous, network- or disk-touching work (loading a detector model,
   opening a persistence store), it can silently reproduce the same
   unbounded-blocking gap `DepthEstimationModule` already has — do not
   repeat that pattern unreviewed; if it comes up, treat it as a "needs user
   judgment" item per §22, not a silent copy of the existing gap. This is
   explicitly a "start, don't necessarily finish" item —
   stopping partway through a well-planned, well-tested increment is fine;
   starting a *second* unplanned module in the remaining time is not (see
   §22's stop conditions around scope).
7. The `seq` -> `source_seq`/`tx_seq` wire-protocol prep (§7 item 3) —
   Tower-side additive change only, plus the Mac-side handoff document
   (§24) an iOS session would need to actually consume the new field. Do
   not attempt to make the iPhone side consume it from this session.

### Explicitly out of scope this weekend (do not attempt)

- World Builder Experiment 3/4 (blocked on intrinsics, §10/§16).
- Document Memory implementation of any kind — it isn't even promoted to
  `guidelines/docs/modules/` yet (§11); that promotion itself is a user
  decision, not an autonomous one.
- Anything touching Environmental Memory (gated on retention/deletion
  actually being implemented first — that's an Object Memory-adjacent or
  later concern, not this weekend's).
- Any Hermes Agent work of any kind (§13 — rejected).
- Any TensorRT/CV-CUDA/DeepStream integration (§14 — not justified by
  current evidence).
- Any iOS/Swift/DAT code change (§4 — produce a handoff document instead,
  §24).
- The synchronous-lifecycle-timeout fix and the auth/encryption gap (§9
  table — both explicitly flagged "needs user judgment," not autonomous).

## 18. Testing Requirements

- Every MUST/SHOULD/STRETCH code change follows
  `superpowers:test-driven-development`: failing test first, then the
  implementation, then confirm green.
- Full suite (`pytest`) must stay green after every task — this repo's own
  convention (`docs/superpowers/plans/*.md` files already follow this
  pattern; see e.g. the V0.7 plan's Task 4 Step 4 "run the pre-existing
  suite unmodified" regression check).
- New experiments (World Builder Experiments 1/2) follow
  `EXPERIMENTAL-CV.md`'s Success Criteria discipline: hypothesis, dataset,
  metric, baseline, result — written up as a report under
  `guidelines/docs/reports/`, matching the existing V0.7/V0.9.1 report
  format and filename convention (`guidelines/docs/reports/V0.9.3-...md` or
  similar, following whatever milestone number is actually used — see §16
  for how to decide that).
- Do not claim a target "achieved" without a measured number, per
  `02-DEVELOPMENT-RULES.md` Rule 3 and every existing report's own
  discipline.

## 19. Benchmark Requirements

- Any new model-backed experiment (a detector for Object Memory, a
  metric-depth model swap, a VO library) gets the same CPU-vs-CUDA
  measurement treatment `scripts/depth_benchmark.py` already established for
  `depth` — reuse that script's pattern rather than inventing a new one.
- Per-stage timing (`StageTimer`, `tower/instrumentation.py`) is required for
  any new experiment with more than one processing stage — this is already
  the established convention (`depth.py`, `edge_detection.py` both do this;
  `baseline.py` doesn't because it's genuinely single-stage).
- Do not adopt any acceleration technology (§14) without a fresh measured
  data point specific to the new workload — V0.9.1's numbers do not transfer
  to a structurally different model.

## 20. Git / Worktree Strategy

- Use `superpowers:using-git-worktrees` for any implementation task that
  benefits from isolation (Object Memory implementation, §17 item 6, is the
  clearest candidate this weekend).
- **Do not touch or remove** `.claude/worktrees/v0.8-module-container` (§2)
  without asking the user first — it appears inert but removing a worktree
  is exactly the class of action this guide's stop conditions (§23) treat as
  needing confirmation.
- Commit small and often, one logical change per commit, matching this
  repo's existing commit history style (`git log --oneline` shows small,
  well-scoped commits like "feat: add TOWER_CV_DEVICE setting" — follow that
  granularity, not large multi-concern commits).
- Follow the global git safety rules already in force for this session
  (never `--force` push, never skip hooks, always `git status` before
  anything destructive, new commits over amends) — these apply to the
  weekend run exactly as they applied to this planning session.
- Do not push to any remote unless the user explicitly asks (no evidence a
  remote is even configured for this repo as of this session — verify before
  assuming one exists).

## 21. Subagent Strategy

- Use `superpowers:subagent-driven-development` for any MUST/SHOULD/STRETCH
  item that decomposes into independent tasks (Object Memory implementation,
  §17 item 6, is the natural candidate).
- Use `superpowers:dispatching-parallel-agents` only for genuinely
  independent problem domains — per this guide's own research phase, that
  was CV-research vs. memory-design vs. Hermes-eval vs. GPU-eval vs.
  code-audits: six clearly separable questions. The weekend's implementation
  work is much more likely to be sequential (one module, built incrementally)
  than parallel — **do not force parallelism where a single coherent
  implementation thread is more appropriate.**
- Token/compute discipline (per the user's explicit instruction): do not
  spawn a subagent for a trivial one-line fix, a tiny doc update, or
  redundant overlapping research. Do parallelize independent research
  question. Do not parallelize implementation against the same files without
  a strong, stated reason.
- Every implementation task gets `superpowers:requesting-code-review` before
  being considered done; every review's findings get verified
  (`superpowers:receiving-code-review` — do not blindly implement
  suggestions that don't hold up) before being applied.
- Before merging/finishing any implementation branch, use
  `superpowers:finishing-a-development-branch`.

## 22. Autonomous Decision Authority

The weekend run **may** decide, without stopping for the user, when the
decision is local, reversible, evidence-backed, tested, and
architecture-consistent. Concretely, in this repo's context:

- Fixing a genuine bug found during implementation (with a regression test).
- Correcting a broken/flaky test.
- Adding a missing regression test for behavior that already exists but
  isn't covered.
- Improving error handling that doesn't change an established contract
  (e.g., §9's WS error-propagation fix — additive, doesn't remove or change
  any existing message shape).
- Correcting a stale doc/comment that's factually wrong against the current
  code (not a design decision — a factual correction).
- Choosing between equivalent internal implementations (e.g., which classical
  detector to try first in an experiment already scoped to "try classical
  first" — §10 already made that call; picking ORB vs. a specific parameter
  set within that is implementation detail).
- Pinning a dependency version for reproducibility (the project already has
  a direct precedent: the V0.9.1 MiDaS `torch.hub` ref pin).
- Rejecting a planned-but-unjustified complexity addition, with the reasoning
  recorded (Rule 17 explicitly asks for this) — e.g., declining to add
  TensorRT without a fresh measured trigger (§14).
- Small observability additions required by the active milestone's own
  success criteria (e.g., the opt-in per-frame depth-array capture
  Experiment 1 needs).

**For anything bigger than the above, record: issue, evidence, ruling,
alternatives considered, and cost if wrong** — even when the decision is
within the run's authority to make, per the user's explicit instruction.
This record belongs in the milestone's own report/plan doc, not buried in a
commit message alone.

**What is NOT autonomous** (needs the user, even if it looks small): anything
in §9's "needs user judgment" row, anything in §17's "explicitly out of
scope" list, promoting Document Memory from research-seed to an approved
`guidelines/docs/modules/` spec (§11), and — per §16 above — the
architectural framing of a new roadmap milestone number (V0.9.2/V0.9.3 above
are this guide's *proposal*, not a pre-approved roadmap edit; recording
completed work under a sensible number is fine, inventing new scope under a
new number is not).

## 23. Stop Conditions

Stop and wait for the user if any of the following occurs — this list is the
user's own, reproduced here as the canonical reference, plus repo-specific
concretization where useful:

- Fundamental architecture redesign appears required (e.g., an experiment
  result suggests the whole module-container design needs to change — highly
  unlikely given §9's audit, but the trigger is "evidence suggests it," not
  "someone is annoyed by it").
- Risk to the working streaming foundation (V0.5-V0.7) — do not let any
  weekend work regress `tests/test_ws*.py` or the sustained-streaming path.
- Major iOS/DAT change appears required without the appropriate environment
  — produce a Mac-side handoff (§24) instead of attempting it.
- Any destructive storage migration (not applicable yet — no storage exists,
  but the first module to add persistence should treat its own *initial*
  schema choice as low-stakes, and any *later* schema change to already-
  populated storage as requiring this stop condition).
- A privacy/product decision with major implications (e.g., "should Document
  Memory retain page images by default" — §11 already recommends no, but
  overriding that recommendation is a stop-and-ask, not an autonomous call).
- An unexpected dependency/platform migration need surfaces (e.g., discovering
  mid-experiment that a VO library genuinely requires Linux/WSL2 — flag and
  stop, don't silently start a WSL2 migration).
- Unresolved CUDA/framework incompatibility beyond what's already documented
  in `README.md`'s install-order caveats.
- Evidence surfaces that the *approved* weekend milestone itself was the
  wrong choice (e.g., Experiment 2 shows passive glasses motion has no
  trackable structure at all — this is a valid, useful negative result per
  §10's own framing, and should be written up as such, but if it changes
  what the *next* milestone should be, that's a stop-and-report, not a
  silent pivot to a different unapproved milestone).
- Git state that risks losing work (per the global git safety rules already
  in force).
- An ambiguous decision with large rework cost if guessed wrong.
- A major protocol change between phone and Tower beyond the additive,
  Tower-side-only prep described in §7 item 3/§17 item 7.
- A security issue requiring user judgment (the known `0.0.0.0`/no-auth gap
  is already flagged, not a new discovery requiring a fresh stop — but a
  *new* security finding would be).

**When stopped:** preserve work (commit what's safely committable — small,
clean, passing-tests commits per §20's granularity, not a giant WIP dump),
write a decision report (issue, evidence, options, recommendation — same
shape as §22's "record" requirement), and wait. Do not guess and proceed.

## 24. Mac-Side / iOS Handoff Procedure

Any task this weekend run identifies as requiring iOS/Swift/DAT work
produces a handoff document instead of an attempted implementation. Required
format (create under `docs/superpowers/handoffs/` — new directory, create it
if this triggers):

```markdown
# Mac Handoff — <short title>

## Objective
<what needs to happen, in product/behavior terms>

## Relevant protocol
<exact current wire message shapes involved, cited from tower/frames.py /
tower/routes/ws.py, plus exactly what would change and why>

## Tower-side state
<what, if anything, was already done Tower-side to prepare for this
(e.g., an additive new field already added to frame_result) — cite the
commit>

## Tower expectations
<what the Tower will send/expect once the iOS side is updated>

## Files/components likely involved (Swift side)
<best-effort guess based on guidelines/docs/05-DAT-INTEGRATION.md's
documented architecture — GlassesConnection, StreamManager, TowerClient,
etc. — clearly labeled as a guess from documentation, not verified against
actual Swift source, since this session cannot read that repo>

## DAT documentation needed
<explicitly flag if this requires search_dat_docs — this Windows session
could not verify current DAT behavior; the Mac session must do so before
implementing, per 02-DEVELOPMENT-RULES.md Rule 4>

## Acceptance criteria
<concrete, testable>

## Tests / manual validation required
<what should be run/verified on the Mac side, and what the Tower side
already verified (e.g., "Tower-side tests pass for the new optional field;
Mac session must verify the iPhone sends/handles it correctly")>
```

Known candidates already identified this session that would need this
treatment if scoped: the `source_seq`/`tx_seq` wire-protocol split (§7 item
3), and — for World Builder Experiment 3 — obtaining camera intrinsics via
`search_dat_docs` (§10).

## 25. Documentation Requirements

- Update `guidelines/docs/03-ROADMAP.md` and `README.md`'s "Current
  milestone" line only when a milestone genuinely completes — matching this
  repo's existing, consistent pattern (every prior milestone's final commit
  in this session's `git log` review did exactly this).
- Every new experiment gets a report under `guidelines/docs/reports/`,
  matching the V0.7/V0.9.1 filename and section-structure convention.
- Do not edit `guidelines/docs/modules/*.md` specs to reflect a new
  implementation's design choices *while* the design is still under
  planning-only review (i.e., don't promote Document Memory's research-seed
  doc into `guidelines/docs/modules/` without the user's explicit decision,
  §11/§22).
- New planning/spec/research artifacts follow this repo's existing
  `docs/superpowers/{plans,specs,research}/YYYY-MM-DD-<slug>.md` naming
  convention — already established by this session's own output and by the
  pre-existing V0.7/V0.8/V0.9/V0.9.1 plan/spec files.

## 26. Final Verification Procedure (before considering any weekend milestone done)

1. `pytest` — full suite green, no unexplained skips beyond the existing 3
   opt-in model-integration tests.
2. Re-read the specific `guidelines/docs/` sections relevant to what was
   built, confirm the implementation actually matches (or explicitly and
   correctly diverges from, with reasoning recorded per §22) the documented
   contract.
3. For any new experiment: confirm its report exists under
   `guidelines/docs/reports/` with real measured numbers, not placeholders.
4. Confirm `README.md`'s "Project Structure" and "Current milestone" lines
   are still accurate (this repo's own convention keeps them tightly in
   sync with reality — don't let them drift).
5. `git status` clean (or only expected/explained untracked files remain),
   git log shows small coherent commits matching §20.
6. Run `superpowers:verification-before-completion` discipline generally:
   evidence before assertions, always — do not report a milestone "done"
   without having just run the commands that prove it.

## 27. Final Weekend Report Template

Produce this at the end of the run (or at a stop condition, adapted) as a
new file under `guidelines/docs/reports/` or `docs/superpowers/plans/` as
appropriate to what was actually produced:

```markdown
# Weekend Autonomous Run — Report — <date>

## What was completed (MUST/SHOULD/STRETCH, from the Master Guide)
<explicit list against §17's plan, with checkmarks/status>

## Measured results
<every experiment/benchmark's actual numbers, per §18/§19>

## Autonomous decisions made
<per §22's "record" requirement — issue, evidence, ruling, alternatives,
cost-if-wrong, for each>

## Stop conditions triggered (if any)
<per §23 — what happened, current state, options for the user>

## Mac-side handoffs produced (if any)
<links to docs/superpowers/handoffs/*.md>

## Test/build state
<full suite result, any new skips and why>

## What's next
<the next natural milestone per §16's sequence, given what was actually
learned this weekend — not necessarily identical to the pre-weekend plan
if evidence changed the picture>

## Anything the user should specifically review before the next session
```

## 28. Recommended First Action After Future Greenlight

1. Re-read this guide's §17 (MUST/SHOULD/STRETCH) and §2 (verified starting
   state) — confirm nothing has changed since this guide was written (a
   fresh `git log`/`pytest` check costs almost nothing and catches drift if
   time has passed between this planning session and the greenlit run).
2. Resolve §17 MUST item 2 first (confirm real-motion footage availability)
   — it gates the World Builder track and should be resolved before any
   other work starts, since it determines whether §17's SHOULD/STRETCH
   sequencing is even reachable this weekend.
3. Start with §17 MUST item 1 (the three autonomous-safe backend fixes) in
   parallel with resolving item 2 — they're independent, low-risk, and
   establish the small-commit rhythm (§20) the rest of the run should
   follow.
4. Do not start Object Memory work (§17 items 5/6) until items 1-4 are
   genuinely done and verified (§26) — resist the temptation to parallelize
   the module-design-review task against the backend fixes just because both
   are "available"; per §21, sequential focus beats forced parallelism here.
