# Platform Backend Completion Audit (Track A)

**Date:** 2026-08-20
**Baseline:** commit `a6030fc` (V0.9.1, depth CV baseline shipped; 98 tests passed / 3 skipped)
**Scope:** research/audit only — no application code touched.

## Question

Streaming and the V0.8 module container both work. Is the shared Tower backend
infrastructure complete enough for the module library to start multiplying
(World Builder, Object Memory, Environmental Memory, Document Memory, Visual
Q&A, Accessibility, Translator), or does more shared infrastructure need to be
built first?

## Method

Read the canonical docs (`00`–`07` under `guidelines/docs/`) and the entire
current Tower source tree (`tower/**/*.py`, 19 files) against them. Every
classification below is grounded in a specific line of code or doc text, not
assumption. File paths are absolute; line numbers refer to the state at
commit `a6030fc`.

---

## Classification Table

| # | Item | Classification |
|---|------|----------------|
| 1 | Module selection / active-module identity | already solved (for registry-of-one scope) |
| 2 | Module lifecycle | already solved |
| 3 | Module health | partially solved |
| 4 | Session lifecycle | already solved |
| 5 | Stream lifecycle | already solved (same mechanism as #4) |
| 6 | Module configuration / settings schema | needed before multiple production modules |
| 7 | Module output contracts (`frame_result`) | needed before multiple production modules |
| 8 | Error propagation to client | partially solved — recommend fixing now |
| 9 | Reconnect behavior (Tower-side) | unnecessary-overengineering-for-now |
| 10 | Tower availability signaling | already solved |
| 11 | Graceful degradation | unnecessary-overengineering-for-now |
| 12 | Phone/Tower capability negotiation | needed before multiple production modules |
| 13 | Protocol versioning | needed before multiple production modules |
| 14 | Module metadata (`ModuleDescriptor`) | partially solved |
| 15 | Latency telemetry (`StageTimer`) | partially solved |
| 16 | Frame identity/timestamps (`seq`) | needed specifically for World Builder (also required for memory modules) |
| 17 | Result identity | needed specifically for World Builder |
| 18a | Shared perception outputs / model cache | unnecessary-overengineering-for-now |
| 18b | Persistence / memory storage interface | needed specifically for memory modules (Document/Object/Environmental) |
| 19 | Future viewer subscriptions / live-world updates | future nice-to-have |
| 20 | Module isolation / switching / cleanup | needed before multiple production modules |
| 21 | Privacy/data behavior declarations (`ModuleDataBehavior`) | partially solved |

---

## 1. Module selection / active-module identity — already solved

`tower/config.py:19` reads `TOWER_CV_EXPERIMENT` once at process start;
`tower/main.py:15-20` (`_build_cv_module`) picks `DepthEstimationModule` vs.
`ExperimentalCVModule` from that single env var, and the container is
constructed once in `create_app()` (`tower/main.py:34`). There is no runtime
selection endpoint. Confirmed: both `ExperimentalCVModule` and
`DepthEstimationModule` hardcode the same `descriptor.id = "experimental-cv"`
(`tower/modules/experimental_cv.py:6`, `tower/modules/depth_cv.py:6`) — from
the platform's perspective, switching `TOWER_CV_EXPERIMENT` or
`TOWER_CV_DEVICE` never changes module identity, only which experiment
function backs the one slot. This is exactly the "registry of one" design
`03-ROADMAP.md` V0.8–V0.9 calls for — adequate as-is.

## 2. Module lifecycle — already solved

`tower/modules/base.py:63-150` implements `UNLOADED → LOADING → READY →
ACTIVE → STOPPING/FAILED` exactly as `04-MODULE-SYSTEM.md`'s Lifecycle
section and `03-ROADMAP.md` V0.8 specify, with strict state-guarded
transitions (`InvalidModuleStateError` on illegal calls) and a `FAILED`
short-circuit (`mark_failed()`, `base.py:114-122`) that runs `_do_release()`
synchronously. `tower/modules/container.py:40-79` wraps `load()`/`start()`/
`stop()`/`unload()` in `asyncio.wait_for(..., timeout=LIFECYCLE_TIMEOUT_S)`
(10s, `container.py:16`), matching `01-SYSTEM-ARCHITECTURE.md`'s "no
lifecycle operation may block indefinitely" reliability policy and
`02-DEVELOPMENT-RULES.md` Rule 15.

## 3. Module health — partially solved

`GET /health` (`tower/routes/health.py:9-18`) returns exactly `status`,
`service`, `version`, `module_state`, `module_id`. This is truthful (Rule 3)
but minimal: no FPS/frame-count/uptime, no connected-client state, no
resource (GPU/model) readiness detail, and no `data_behavior` (see #21).
Adequate for a single always-on module; will need a per-module health list
once more than one module can exist side by side.

## 4–5. Session lifecycle / Stream lifecycle — already solved (same mechanism)

`stream_start`/`stream_stop` control messages (`tower/routes/ws.py:130-149`)
open/close a `SessionMetrics` measurement window
(`tower/metrics.py:47-110`); a stray `stream_stop` with no open window logs a
warning rather than erroring (`ws.py:145-149`), and disconnect always
finalizes an open window (`ws.py:154-157`). `ConnectionTracker`
(`tower/session.py`) separately tracks only a boolean connected/disconnected
state plus lifetime counters — no session IDs. In the current codebase
"session" and "stream" are the same primitive; there is no separate concept
of a session outliving a stream or vice versa. This is sufficient for a
single iPhone client and matches `07-PLATFORM-CONSTRAINTS.md` Limitation 4's
"a new session is a new observation stream" rule (`SessionMetrics` is never
reused across reconnects, per its own docstring at `metrics.py:14-17`).

## 6. Module configuration / settings schema — needed before multiple production modules

Only two env vars exist (`TOWER_CV_EXPERIMENT`, `TOWER_CV_DEVICE`,
`tower/config.py:19-20`), read once at startup into a frozen `Settings`
dataclass. There is no `settingsSchema` field on `ModuleDescriptor`
(confirmed absent — see #14), no runtime reconfiguration endpoint, and no
per-module settings concept at all. This is fine while there is exactly one
module with two knobs. It becomes a real requirement once a module has
genuinely configurable, module-owned settings — e.g. `06-PRIVACY-DATA.md`'s
"Configurable Retention" requirement for Environmental/Object Memory
(a retention-window setting) or a future Translator's language pair. Not
worth building ahead of a concrete second module.

## 7. Module output contracts (`frame_result`) — needed before multiple production modules

The envelope sent over WS (`tower/routes/ws.py:82-91`) is `type`, `seq`,
`processing_ms`, `result_value`, `result_label`, `stage_ms`, plus an
*optional* `mean_intensity` bolted on only when non-`None`. Confirmed the
inner shape is ad hoc per experiment, not a uniform contract:
- `baseline.py:5-13`: `stage_ms={"total": ...}`, populates `mean_intensity`.
- `edge_detection.py:8-30`: `stage_ms={decode, blur, canny, summarize}`, no `mean_intensity`.
- `depth.py:88-117`: `stage_ms={decode, preprocess, inference, postprocess}`, no `mean_intensity`.

`mean_intensity` is the one field that leaks a specific experiment's output
into the otherwise generic envelope — it exists only because two of three
current experiments happen to produce it. This is acceptable for three
bounded CV Lab experiments sharing one slot (Rule 10 — no premature scope
expansion), but a real second module (e.g. Object Memory, which will not
have a "processing_ms + single scalar result_value" shape at all) cannot
reuse this envelope as-is. Needs a real generalization pass once a
non-CV-experiment module exists, not before.

## 8. Error propagation to client — partially solved, recommend fixing now

`FrameProcessingError` → `FrameSkippedError` → `ModuleUnavailableError` are
implemented exactly as documented in `base.py:23-43` and wired through
`container.py:80-104`. But tracing what `ws.py` does with them
(`ws.py:46-63`): on `FrameSkippedError` it logs, increments a metric
(`metrics.record_frame_processing_error()`), and **returns — no message is
sent to the WebSocket client.** On the generic `ModuleUnavailableError`
(module now `FAILED`) it logs and **also returns with no client-facing
message.** From the iOS client's point of view, a skipped frame and a fully
failed module are both indistinguishable from an ordinary dropped frame —
there is no `frame_error`/`module_failed` message type on the wire at all.
This is a real, already-latent gap (not a future-module concern): it
undercuts Rule 3's truthful-state requirement, since `GET /health` would
show `module_state: "failed"` but nothing pushes that fact to the connected
client — it has to separately poll `/health` to discover why frames stopped
arriving. Cheap to fix (one new WS message type) and valuable regardless of
which module ships next; recommended as a near-term fix rather than deferred.

## 9. Reconnect behavior (Tower-side) — unnecessary-overengineering-for-now

Confirmed via `grep` for `reconnect|backoff` across `tower/`: the only hit is
`metrics.py`'s docstring describing a *future* protocol concept, not
executable logic. `ws.py`'s loop simply runs until `WebSocketDisconnect`,
then calls `session.client_disconnected()` (`ws.py:152-157`) — no retry, no
backoff, nothing to reconnect *to* from the server side. This matches
`01-SYSTEM-ARCHITECTURE.md`'s Reliability Policies, which frame
reconnection as a property of the connecting side (glasses session / iOS
`TowerClient`), not the Tower (a passive WS acceptor). Building
Tower-initiated reconnect logic would be solving a problem that doesn't
exist in this architecture.

## 10. Tower availability signaling — already solved

The Tower's only job here is to be truthfully reachable-or-not at the
network/HTTP level and to report real `module_state` when reached
(`health.py`). Interpreting "Tower: Unavailable" is explicitly the iOS
`TowerClient`'s responsibility per `01-SYSTEM-ARCHITECTURE.md` — "Tower
Failure" section. No further Tower-side work is implied by what's read here.

## 11. Graceful degradation — unnecessary-overengineering-for-now

`_resolve_device()` in `depth_cv.py:56-67` does device-level fallback
(`"auto"` → CUDA if available else CPU) but there is no feature-level
degradation (e.g., "GPU absent → serve a lighter capability"). This exact
scope decision is already made explicitly in
`01-SYSTEM-ARCHITECTURE.md` — Heterogeneous Compute & Graceful Degradation:
"This is a future direction, not a current requirement... sufficient until
a real second compute target or a real Tower-optional use case exists."
Confirmed nothing beyond device selection exists; correctly so per the doc's
own instruction.

## 12. Phone/Tower capability negotiation — needed before multiple production modules

Confirmed absent at the protocol level (no `capabilities` field anywhere in
`tower/`). This is exactly what `03-ROADMAP.md` V1.0 ("Generalize Module
Registry") describes as gated on a second production module creating real
requirements — "descriptor/sensor-profile negotiation generalized from
actual usage rather than speculative design." Correctly not built yet;
becomes necessary the moment a second module needs a different sensor
profile than the CV Lab's fixed camera-frame assumption.

## 13. Protocol versioning — needed before multiple production modules

Confirmed zero version field in the WS JSON protocol: `frame`, `frame_result`,
`ping`/`pong`, `stream_start`/`stream_stop` messages (`ws.py`, `frames.py`)
carry no `version`/`protocol_version` key. `health.py:4` has a
service-level `API_VERSION = "0.1.0"` constant, but it is never embedded in
any WS message. Harmless today because there is exactly one message shape
consumed by exactly one iOS build. Becomes valuable once module-specific
message shapes diverge (e.g. a future Translator's streaming audio chunks
vs. CV Lab's `frame_result`) and old/new iOS builds must coexist against a
changing Tower.

## 14. Module metadata (`ModuleDescriptor`) — partially solved

`tower/modules/base.py:55-60` defines `ModuleDescriptor` with exactly `id`,
`name`, `version`, `data_behavior`. Compared against `04-MODULE-SYSTEM.md`'s
target descriptor (`id, name, description, version, capabilities,
sensorProfile, dataBehavior, settingsSchema, uiExtension`): `description`,
`capabilities`, `sensorProfile`, `settingsSchema`, `uiExtension` are all
absent (confirmed via grep — no occurrences anywhere in `tower/`). This
matches `04-MODULE-SYSTEM.md`'s own framing — "exact programming-language
types are intentionally deferred" and "should evolve incrementally... not be
replaced up front with a fully general plugin system." The fields that
*are* present (`id`/`name`/`version`/`data_behavior`) are exactly the ones a
single-module system with no negotiation needs today. The missing fields
(`capabilities`, `sensorProfile`, `settingsSchema`) are the same fields
identified as needed once negotiation (#12) and settings (#6) become real
requirements — i.e., this descriptor should grow in lockstep with those,
not ahead of them.

## 15. Latency telemetry (`StageTimer`) — partially solved

`tower/instrumentation.py:5-24` (`StageTimer`) is a thin, general-purpose
named-stage timer with no fixed stage vocabulary. Actual stage coverage
today, confirmed per experiment:
- `depth.py`: `decode → preprocess → inference → postprocess` (matches the
  ML-model shape `01-SYSTEM-ARCHITECTURE.md`'s Latency Instrumentation
  section anticipates).
- `edge_detection.py`: `decode → blur → canny → summarize` (classical-CV
  shape, different vocabulary).
- `baseline.py`: single `"total"` bucket (doesn't use `StageTimer` at all —
  reuses `frame_processing.py`'s `processing_ms`).

Two coarse end-to-end figures also exist:
`cv_processing_ms`/`processing_ms` (module-side) and `receive_to_result_ms`
(`ws.py:72`, computed from `receive_start = time.perf_counter()` at
`ws.py:18`) — this exactly matches what `01-SYSTEM-ARCHITECTURE.md` says is
the current, expected state ("V0.7 already reports two coarse figures... as
a starting point; per-stage breakdown is future work"). No `capture` or
`transport` stage timing reaches the Tower at all (nothing in the wire
protocol carries a capture timestamp — see #16), so the earliest stages of
the documented `capture → transport → decode → ...` pipeline are structurally
unmeasurable from the Tower alone today. This is the documented, accepted
state, not a regression — flagged as "partially solved" because it is
correctly incomplete per the architecture doc's own instruction, not because
it needs immediate work.

## 16. Frame identity/timestamps (`seq`) — needed specifically for World Builder (also required for memory modules)

`tower/frames.py:8` — `REQUIRED_FIELDS = ("seq", "width", "height", "format",
"data")` — confirms the wire protocol still carries exactly one `seq` int
and nothing else identity/time-related; unchanged since V0.7.
`metrics.py:19-33`'s docstring is explicit that this single field cannot
distinguish sender-side sampling from genuine transit loss, and that
`07-PLATFORM-CONSTRAINTS.md` Limitation 9's `source_seq`/`tx_seq` split
remains unimplemented. No capture timestamp and no Tower-receive timestamp
are transmitted on the wire at all (`ws.py`'s `receive_start` is local,
never sent back to the client). This is inert for the current CV Lab
experiments (each frame is processed independently, "latest wins," no
history). It becomes a real requirement for World Builder (needs true
capture-time ordering for SfM/SLAM per Limitation 1/9) and equally for
Object/Environmental Memory (needs last-seen semantics distinct from
arrival time per Limitation 7). Correctly deferred until now; should be
designed once, not per-module, before the first history-keeping module
starts.

## 17. Result identity — needed specifically for World Builder

No result carries any ID beyond the echoed `seq` (`ws.py:84`). Fine for the
current synchronous 1-frame-in → 1-`frame_result`-out model, where `seq`
alone is sufficient correlation. Becomes insufficient once processing is
decoupled from arrival — World Builder's documented async
keyframe-selection → SfM/SLAM → reconstruction pipeline
(`07-PLATFORM-CONSTRAINTS.md` Limitation 14) means a "result" may arrive
long after and out of order from the frame that triggered it, at which
point a request/result correlation ID (not just a source frame `seq`)
becomes necessary. Not required by any module that exists today.

## 18a. Shared perception outputs / model cache — unnecessary-overengineering-for-now

Confirmed nothing exists: no shared model cache, no perception-output bus.
`04-MODULE-SYSTEM.md`'s own Model Resources section states this "may be
introduced later if measurements show repeated model loads are costly and
multiple modules genuinely share the same model" — there is exactly one
module today, so there is nothing to measure yet. Building this now would
be speculative ahead of any real sharing requirement.

## 18b. Persistence / memory storage interface — needed specifically for memory modules

No persistence layer of any kind exists in `tower/` — confirmed by both the
file inventory (no storage/db module) and by both real modules declaring
`persists_data=False` (`experimental_cv.py:9`, `depth_cv.py:10`). This is
correctly absent today (neither shipped module persists anything), but it is
a hard prerequisite — not a nice-to-have — for Object/Document/Environmental
Memory, which cannot exist without some storage namespace and a working
purge mechanism. `06-PRIVACY-DATA.md` is explicit and unusually strict here:
"Modules with long-lived history (Environmental Memory in particular) must
implement working retention/deletion behavior **before** they are used to
collect real data — documenting the principle here is not a substitute for
implementing it." This is a blocking prerequisite specifically for the
memory-module family, not a general platform gap.

## 19. Future viewer subscriptions / live-world updates — future nice-to-have

Confirmed absent: `/ws` is a single endpoint handling exactly one connected
client at a time (`ConnectionTracker` tracks one boolean, not a set of
subscribers). `03-ROADMAP.md`'s own "Future Research" section lists "live
world-state visualization for World Build" as explicitly outside V1. No
work implied now.

## 20. Module isolation / switching / cleanup — needed before multiple production modules

This is the sharpest finding in the audit: **there is no runtime "switch
module" code path at all.** `ModuleContainer` (`tower/modules/container.py`)
exposes exactly two lifecycle-driving methods: `load_and_start()` — called
once, at process startup (`main.py:39`) — and `shutdown()` — called once, at
process shutdown via the FastAPI `lifespan` context manager (`main.py:24-26`,
`23-26`). There is no `switch_to(new_module)` method, no code path that ever
calls `stop()`/`unload()` on a live module and `load()`/`start()` on a
different one while the process keeps running. The only way to run a
different module today is to set a different env var and restart the
process. This is exactly consistent with `03-ROADMAP.md` V0.8's own scope
("no dynamic discovery, no descriptor negotiation protocol, no module
registry yet") and V1.0/V1.1's explicit gating ("triggered only once a
second production module... creates real, concrete requirements" /
"exercised across real module switches"). The one piece of real
resource-ownership logic that *does* exist and *is* exercised is
`_do_release()` on the `FAILED` path (`base.py:114-122`,
`depth_cv.py:52-53`, confirmed it frees CUDA memory in `depth.py:70-86`) —
but that is failure cleanup, not module switching. This is squarely the
work item V1.0/V1.1 name: it should be built when the second module is
built, not before, and not separately from it.

## 21. Privacy/data behavior declarations (`ModuleDataBehavior`) — partially solved

`tower/modules/base.py:46-52` defines exactly the fields
`04-MODULE-SYSTEM.md`'s Data Behavior section calls for: `persists_data`,
`retains_raw_imagery`, `retention`, `supports_purge`, `transmits_externally`.
Both real modules populate it with honest, accurate values — `persists_data:
False, retains_raw_imagery: False, retention: "none", supports_purge:
False, transmits_externally: False` (`experimental_cv.py:8-14`,
`depth_cv.py:9-15`) — which is truthful for modules that hold no state
between frames and write nothing to disk. However, confirmed via grep that
**nothing anywhere in the codebase reads, validates, or enforces this
dataclass.** `GET /health` doesn't even expose it (`health.py:12-18` returns
only `module_state`/`module_id`, not `data_behavior`). It is attached to
`ModuleDescriptor` and reachable via `container.descriptor.data_behavior`,
but no code path consumes it. Currently decorative but *correctly* populated
— the schema is right, the values are right, only the plumbing to actually
act on it (surface it, gate behavior on `supports_purge`, etc.) is missing.
This becomes load-bearing, not decorative, the moment a module sets
`persists_data=True` — at that point `06-PRIVACY-DATA.md`'s purge
requirement stops being a documentation exercise and needs a real, working
`purge()` path, which is the same forcing function as #18b.

---

## Recommendation

**Build the next production module — do not run a standalone infrastructure-hardening milestone first.** The project's own stated philosophy
(`02-DEVELOPMENT-RULES.md` Rule 10, `03-ROADMAP.md`'s "generalize only when
justified" sequencing) is correct and this audit found no evidence it should
be overridden: most of the "gaps" above (settings schema, capability
negotiation, protocol versioning, uniform output contract, module switching,
shared model cache) are gaps *only* relative to a multi-module future that
doesn't exist yet, and every one of them is explicitly named in
`03-ROADMAP.md` V1.0/V1.1 as work to do *once* a second production module
creates real requirements. Building them now would be speculative — exactly
what Rule 10 prohibits. The roadmap already names the right next module:
Object Memory, "a strong bounded candidate for an early production module"
(`03-ROADMAP.md` Phase 3), and building it is what will generate the real
requirements needed to generalize the registry (V1.0) and harden switching
(V1.1) correctly rather than speculatively.

That said, four items are genuine exceptions — each is either a present-day
rule violation-in-waiting or a blocking prerequisite the *next* module
literally cannot function without, not a speculative generalization. Fix
these as part of (or immediately before) starting Object Memory / World
Builder V1 work:

1. **Error propagation to the WS client (#8).** A `FAILED` module or a
   skipped frame is currently invisible to the connected client — it looks
   identical to ordinary packet loss. This already undercuts Rule 3's
   truthful-state requirement for the module that exists *today*, is cheap
   to fix (one new WS message type), and will only get more important as
   more can go wrong with more modules.

2. **Persistence + a real, working purge path (#18b / #21).**
   `06-PRIVACY-DATA.md` explicitly forbids collecting real data with Object
   Memory or Environmental Memory before working retention/deletion exists
   — this is a hard blocker stated in the privacy doc itself, not an
   audit opinion. `ModuleDataBehavior`'s schema is already correct; it just
   needs a real implementation and enforcement path the moment the first
   persisting module ships.

3. **`seq` → `source_seq`/`tx_seq` split, or equivalent capture/receive
   timestamps (#16).** Required before any module reasons about temporal
   gaps or ordering (Object/Environmental Memory's last-seen semantics,
   World Builder's SfM/SLAM ordering) — `07-PLATFORM-CONSTRAINTS.md`
   Limitation 9 already flags this as insufficient. Cheap to fix while the
   wire protocol is being touched anyway for the next module; expensive to
   retrofit into accumulated history data later.

4. **Module switching / registry generalization (#20, i.e. V1.0/V1.1).**
   Not a "fix before" item — this *is* the shape of the next milestone.
   Flagged here only to confirm precisely what the audit found: today there
   is no code path to swap modules at runtime at all, only env-var + restart.
   Build this together with the second module, using its real requirements,
   exactly as `03-ROADMAP.md` V1.0/V1.1 already specify.

Everything else in the classification table — settings schema, output
contract generalization, capability negotiation, protocol versioning, viewer
subscriptions, shared model cache, graceful degradation, Tower-side
reconnect — is correctly deferred and should stay deferred until a concrete
module creates the requirement, per the project's own rules.
