# Testing / Reliability / Technical Debt Audit — 2026-08-20

Research/audit only. No code, tests, or other docs were changed as part of
this pass. Scope: `tower/` and `tests/` trees, grounded against
`01-SYSTEM-ARCHITECTURE.md` (Reliability Policies), `02-DEVELOPMENT-RULES.md`
Rule 15, `07-PLATFORM-CONSTRAINTS.md` Limitation 11, and
`docs/reports/V0.9.1-depth-cv-baseline-report.md`.

Purpose: feed the persistent "Weekend Autonomous Development Master Guide"
so a future, context-free session can tell what it may fix on its own
authority vs. what needs a specific milestone/trigger vs. what needs the
user.

---

## 1. Test suite result

```
.venv\Scripts\python.exe -m pytest -v
```

**98 passed, 3 skipped, 1 warning, in 1.21s.** No failures.

The 1 warning is `StarletteDeprecationWarning` (httpx vs. httpx2 under
`starlette.testclient`) — cosmetic, not investigated further, low priority.

### The 3 skips

All three live in `tests/test_depth_experiment_integration.py` and share one
module-level `pytestmark`:

```python
pytestmark = pytest.mark.skipif(
    os.environ.get("TOWER_RUN_MODEL_TESTS") != "1",
    reason="opt-in: requires a real torch install and a MiDaS weight "
    "download on first run; set TOWER_RUN_MODEL_TESTS=1 to run",
)
```

- `test_run_on_real_image_produces_expected_result_shape` — loads the real
  MiDaS-small model on CPU and runs inference on a real JPEG.
- `test_resolve_device_auto_prefers_cuda_when_available` — checks
  `_resolve_device("auto")` against the real `torch.cuda.is_available()`.
- `test_resolve_device_cuda_raises_when_unavailable` — checks that
  requesting `cuda` explicitly without a CUDA device raises; this one
  additionally self-skips with "only meaningful on a machine without CUDA"
  if CUDA *is* available, so on this GPU-equipped Tower it would skip twice
  over even with the env var set.

**Read:** this is a deliberate, correctly-implemented opt-in gate, not a
broken or neglected test. It exists because these tests require a real
torch install plus a first-run network download of MiDaS weights — properly
excluded from the default fast/offline suite. Not a finding requiring
action.

---

## 2. TODO/FIXME/deferred-marker sweep

Grep across `tower/` and `tests/` for
`TODO|FIXME|XXX|not yet|not implemented|deferred|future milestone`
(case-insensitive) returned **4 hits, all in `tower/`, none in `tests/`**:

1. **`tower/metrics.py:33`** (inside `SessionMetrics`'s class docstring) —
   documents that `seq_gap_total` cannot distinguish intentional
   sender-side sampling from genuine network/transit loss under the
   current single-field wire protocol, and that the `source_seq`/`tx_seq`
   split needed to distinguish them is "not implemented as of V0.7." Read:
   an accurate, already-cross-referenced statement of a known protocol
   limitation (mirrors `07-PLATFORM-CONSTRAINTS.md` Limitation 9), not an
   oversight.

2. **`tower/metrics.py:41`** (same docstring) — states `backpressure_drops`
   "will always read 0 until a future milestone adds a real drop
   mechanism," because the `receive -> process -> ack` loop in
   `tower/routes/ws.py` is "intentionally left unchanged this milestone."
   Read: this is the same fact the caller already found and recorded from
   the V0.9.1 report — confirmed here directly in the source comment, not
   just the report. Deliberate, not an oversight.

3. **`tower/experiments/depth.py:98`** — `import torch  # deferred: only
   the stages below need it, so an undecodable frame never requires torch
   to be installed at all.` Read: this is a *design* use of "deferred"
   (deferred import for optional-dependency isolation), not a piece of
   unfinished work. No action implied.

4. **`tower/modules/experimental_cv.py:22`** — docstring: "Stateless by
   design: no experiment allocates a persistent resource in `_do_load()`,
   which keeps V0.8's deferred resource-leak-on-partial-failure finding
   inert for this milestone." Read: this references a real, still-open
   design finding from V0.8 (see Section 3 below) that was deliberately
   left unaddressed while no module needed it — but a module that *does*
   need it (holds a resource in `_do_load()`) now exists
   (`DepthEstimationModule`, added in V0.9). See Section 3 for whether
   that trigger condition has actually been hit and how it was handled.

**Total: 4 markers, all already-documented deliberate deferrals, zero
undocumented/silent TODOs.** This codebase does not have a backlog of
silent debt markers — everything found is already narrated in its own
docstring with a stated trigger condition.

---

## 3. Reliability Policy compliance — `tower/routes/ws.py` and `tower/session.py`

Also read `tower/modules/container.py`, `tower/modules/base.py`,
`tower/modules/depth_cv.py`, `tower/experiments/depth.py`, and the relevant
tests (`tests/test_module_container.py`) to ground this section in actual
behavior, not just the two named files.

### 3a. Bounded lifecycle timeouts + defined FAILED transition

**Partially implements it — and the gap is concrete, not theoretical.**

`tower/modules/container.py` (`ModuleContainer`) wraps every lifecycle
call — `load()`, `start()`, `stop()`, `unload()` — individually in
`asyncio.wait_for(..., timeout=self._lifecycle_timeout_s)` with
`LIFECYCLE_TIMEOUT_S = 10.0` as the default (`container.py:16`). This *is*
the only bounded-timeout mechanism in the codebase — confirmed by grep,
nothing else times out lifecycle operations. On any exception (including
`asyncio.TimeoutError`), the module is moved to `FAILED` via
`module.mark_failed()` (`container.py:48-53`, `61-67`, `73-78`), and
`Module.mark_failed()` (`base.py:114-122`) forces the state to `FAILED` and
best-effort calls `_do_release()`, swallowing any exception it raises. This
part matches the policy well: bounded timeout, defined FAILED transition,
`ModuleContainer.load_and_start()` never lets an exception propagate out
(`container.py:48` catches bare `Exception`), so a module failure cannot
crash the persistent Tower process. `tests/test_module_container.py` has
direct coverage for all four timeout paths
(`test_load_timeout_marks_failed_and_does_not_raise`,
`test_shutdown_stop_timeout_marks_failed_and_does_not_raise`,
`test_shutdown_unload_timeout_marks_failed_and_does_not_raise`).

**The gap:** every one of those tests simulates a "hang" with
`await asyncio.sleep(999)` inside `_do_load`/`_do_stop`/`_do_unload`
(`tests/test_module_container.py:56,134,156`) — a *cooperative* async
hang. `asyncio.wait_for()` can only preempt a coroutine at an `await`
point; it cannot interrupt a synchronous call that never yields back to
the event loop. The currently-selectable `DepthEstimationModule`
(`tower/modules/depth_cv.py`) does exactly that:

```python
# tower/modules/depth_cv.py
async def _do_load(self) -> None:
    self._experiment.load(_resolve_device(self._requested_device))
```

`DepthEstimation.load()` (`tower/experiments/depth.py:33-68`) is a fully
**synchronous** method with no `await` inside it, and it performs
`torch.hub.load(midas_ref, "MiDaS_small", trust_repo=True)` — a call that
can involve network I/O (fetching/verifying the pinned MiDaS ref) and is
not bounded by anything in this codebase. If that call hangs (DNS timeout,
slow/stalled network, a git-clone-style hang under `torch.hub`), the
`await asyncio.wait_for(self._module.load(), timeout=10.0)` wrapper around
it in `container.py` **cannot fire** — the synchronous call blocks the
single event loop thread entirely, so the `wait_for` timeout callback never
gets a chance to run until the blocking call itself returns (at which point
the "timeout" is moot).

In practice this fires only at Tower process startup:
`tower/main.py:39` calls `asyncio.run(app.state.module_container.load_and_start())`
directly inside `create_app()`, at import time, before `app = create_app()`
even returns and before uvicorn starts serving — so a hang here blocks the
whole process before it's listening for anything (no partial
availability window to lose), but it does mean `LIFECYCLE_TIMEOUT_S`
provides **no actual protection** against the one realistic hang scenario
(a stalled model download) for the one module that currently needs it.
This is untested — no test in the suite exercises a *synchronous* blocking
`_do_load()`, only cooperative-async ones.

**Read:** the bounded-timeout mechanism is real and well-tested for
async-cooperative hangs, but structurally cannot bound synchronous/blocking
work, and the one module in the codebase that does synchronous,
network-touching work in `_do_load()` is exactly the case it can't cover.
This is a genuine reliability gap, not a documentation gap — the code
looks protected (a timeout constant exists, tests pass) but isn't, for this
specific and currently-real code path.

### 3b. Resource leak on load-succeeds-start-fails (V0.8 deferred finding, re-checked)

The V0.8 design doc explicitly deferred this finding, on the condition that
it be revisited "the moment a stateful (model-loading) experiment is
added." `DepthEstimationModule` is exactly that trigger — it holds a
loaded model across frames (`tower/modules/depth_cv.py`'s class docstring
says so directly: "the first Module in the Lab that actually exercises
`Module._do_release()`"). Checked whether the trigger was actually
followed up: **yes** — `DepthEstimationModule` overrides `_do_release()`
(`depth_cv.py:52-53`) to call `self._experiment.release()`, so a
`load()`-succeeds/`start()`-fails-or-any-later-failure path does get the
model released via `mark_failed()` → `_do_release()`. For this module the
originally-deferred concern appears to have been addressed as part of
building it, not left open. Confirms Section 3a is the more relevant
lifecycle risk today, not the resource-leak-on-partial-failure concern.

### 3c. Bounded/exponential-backoff reconnection

**Not implemented — and largely not this repo's responsibility as
currently scoped.** Grepped `tower/` and `scripts/` for
`backoff|retry|reconnect`: the only hit is a docstring comment in
`metrics.py` about *sessions* being distinct on reconnect, not an actual
reconnect/backoff mechanism. The Tower is a passive WebSocket server
(`tower/routes/ws.py`'s `@router.websocket("/ws")` — accepts inbound
connections; never initiates outbound ones), so "reconnection" per
`01-SYSTEM-ARCHITECTURE.md`'s Reliability Policies is a client-side
concern (the iOS `TowerClient` / glasses session), which lives outside
this repo. `07-PLATFORM-CONSTRAINTS.md` Limitation 10 already documents
this precisely: `TowerClient` "currently does a single bounded-timeout
connection attempt, not automatic reconnection" — not yet implemented on
the client side either. **Read:** consistent with existing docs; no new
finding here, just confirmation. Not something the Tower repo alone can
fix — needs the iOS side, which is out of this audit's tree.

### 3d. Bounded frame queue / stale-frame dropping

**Partially implements it, matching the V0.9.1 report's own conclusion.**
`tower/routes/ws.py`'s `websocket_endpoint()` is a single strictly
sequential loop:

```python
while True:
    message = await websocket.receive_json()
    ...
    elif message_type == "frame":
        await _handle_frame_message(websocket, message, active_measurement)
```

There is no application-level queue/buffer anywhere in this path — each
frame is fully decoded, processed by the module, and its result sent back
(`await websocket.send_json(payload)`) before the loop calls
`receive_json()` again. This means the code cannot accumulate an
**unbounded application-level queue** — that half of the policy is
satisfied by construction, not by an explicit bound-check. What it does
*not* do is the other half of the policy: actively **drop stale frames**
when processing falls behind. If the module is slow, backlog simply
accumulates wherever the ASGI/transport layer buffers un-read incoming
messages (outside this application's control), and every frame that does
get read is processed in order — nothing is ever proactively discarded.
`backpressure_drops` in `tower/metrics.py` exists as a counter for exactly
this but has no code path that increments it (confirmed: grepped for
`backpressure_drops` outside `metrics.py`/tests — no writer). This matches
`docs/reports/V0.9.1-depth-cv-baseline-report.md`'s own documented
decision rule: no action was taken because a 60-frame bounded benchmark
showed flat latency, and the report explicitly says to revisit only "if a
real sustained session shows `receive_to_result_ms` drifting upward."
**Read:** correctly deferred per that report's own criteria — not an
oversight, and the audit found nothing to suggest that decision needs
revisiting yet.

---

## 4. Auth/encryption state (Limitation 11 re-check)

Read `tower/main.py` and everything under `tower/routes/`. Confirmed:

- No authentication middleware, API key check, token validation, or
  session-credential check anywhere in `create_app()`
  (`tower/main.py:29-42`) or either router (`health.py`, `ws.py`).
- `@router.websocket("/ws")` calls `await websocket.accept()`
  unconditionally (`ws.py:117`) — any client that can reach the port is
  accepted.
- No TLS/HTTPS setup in this repo (uvicorn is presumably invoked
  plaintext; nothing in `tower/` wraps it).
- `tower/config.py`'s `get_settings()` defaults `TOWER_HOST` to
  `"0.0.0.0"` (binds all interfaces, not just localhost) unless overridden
  — compounds the no-auth situation by defaulting to a
  broader-than-localhost bind rather than a narrower one.

**Confirmed: Limitation 11's claim is still fully accurate.** Nothing in
the current codebase adds auth or encryption; the `0.0.0.0` default bind is
worth noting as a small compounding factor (not previously called out in
Limitation 11's text) but doesn't change the underlying conclusion.

---

## 5. Other correctness/robustness notes (kept in scope — module-system hardening, second-module, World Builder/memory adjacency)

- **`tower/routes/ws.py`'s main loop has no generic exception handler.**
  `await websocket.receive_json()` will raise if the client sends
  non-JSON or a JSON value that isn't a dict (`message.get("type")` would
  then raise `AttributeError`). Only `WebSocketDisconnect` is caught
  (`ws.py:152`); any other exception propagates out of the endpoint
  coroutine. This does not crash the Tower process (Starlette handles
  per-connection exceptions without taking down the ASGI app), but it does
  mean a malformed non-frame message from a buggy or malicious client ends
  that connection abruptly without a clean warning log, unlike every other
  validation path in this file (`frames.py`'s `parse_and_decode_frame`
  already validates frame-shaped messages carefully — this gap is only for
  messages that aren't even a well-formed dict). Small, local, easy to
  reproduce with a unit test.
- **`torch.hub.load`'s network dependency is unpinned in scope, not just
  in ref.** The MiDaS ref itself is pinned (`tower/experiments/depth.py:42`,
  per the V0.9.1 spec amendment), but the call still reaches out to
  GitHub at runtime on every fresh model load (no local cache
  pre-provisioning documented) — ties directly into the Section 3a timeout
  gap: this is the actual operation that could hang.
- **`TOWER_HOST` defaulting to `0.0.0.0`** (Section 4) is a minor
  compounding factor worth flagging together with Limitation 11 rather
  than fixing unilaterally, since changing a bind-address default is a
  small architecture/security decision, not a pure bugfix.

Nothing else surfaced in this pass that's plausibly relevant to the named
near-term milestones; did not go further into iOS-side code, DAT
integration, or unrelated experiment/edge-detection code paths, per scope.

---

## Classification summary

| # | Finding | Classification |
|---|---|---|
| 2 | 4 TODO/deferred markers — all already-documented, deliberate, no silent debt | No action needed — informational only |
| 3a | `asyncio.wait_for` lifecycle timeout cannot bound synchronous/blocking `_do_load()` work (real for `DepthEstimationModule`'s `torch.hub.load()`) | **Needs user judgment** — touches how model loading is structured (e.g., moving the blocking call to a thread executor via `asyncio.to_thread`/`loop.run_in_executor` is the standard fix, but changes the lifecycle contract's execution model and deserves a deliberate design decision, not a silent autonomous patch, especially since it only manifests at startup today) |
| 3b | V0.8 resource-leak-on-partial-failure finding | No action needed — trigger condition (`DepthEstimationModule`) already exists and `_do_release()` already handles it |
| 3c | No reconnection/backoff in this repo | No action needed here — correctly out of this repo's scope; tracked accurately in `07-PLATFORM-CONSTRAINTS.md` Limitation 10 for the iOS side |
| 3d | No stale-frame-dropping / `backpressure_drops` always 0 | **Needs a specific future milestone** — the V0.9.1 report's own recorded decision rule: revisit only if a real sustained session shows `receive_to_result_ms` drifting upward |
| 4 | No auth/encryption on WS/HTTP transport; `TOWER_HOST` defaults to `0.0.0.0` | **Needs user judgment** — security/architecture decision, explicitly planned for a later phase (Tailscale/WireGuard, Phase 1.5) per existing docs |
| 5 | `ws.py` main loop has no catch-all for malformed non-dict/non-JSON messages | **Fix now is safe/autonomous-appropriate** — small, local, reversible; add a narrow `except` (or upfront `isinstance(message, dict)` check) around the per-message dispatch with a clean warning log, plus a regression test, mirroring the existing `FrameError` handling pattern already used one level down in `frames.py` |
| 5 | Cosmetic `StarletteDeprecationWarning` (httpx vs httpx2) | **Fix now is safe/autonomous-appropriate** — trivial dependency swap if/when convenient; not urgent |

---

## Bottom line for the Master Guide

The codebase is small, disciplined, and its documentation is unusually
honest about its own gaps — every deferred item found already carries a
stated trigger condition in its own docstring. The one genuinely new
finding from this pass (not already recorded anywhere) is **3a**: the
lifecycle-timeout mechanism that the architecture doc and Rule 15 require
is implemented and tested only against cooperative-async hangs, and
structurally cannot protect against the synchronous, network-touching
`torch.hub.load()` call that `DepthEstimationModule` (the currently
depth-selectable module) actually performs in `_do_load()`. It currently
only bites at process startup (no live-serving window is exposed), which
lowers urgency, but it is a real, verifiable gap between what
`LIFECYCLE_TIMEOUT_S = 10.0` appears to guarantee and what it actually
guarantees.
