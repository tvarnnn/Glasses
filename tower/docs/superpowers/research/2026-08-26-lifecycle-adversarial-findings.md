# Adversarial review of the load-invalidation guarantee

**Date:** 2026-08-26
**Reviewed:** commit `767a633` — the E+A lifecycle ruling
**Reviewer:** an agent that did not write the code
**Verdict:** the core guarantee **holds**. Everything around it does not.
**Status:** all findings reproduced and fixed; see §3.

---

## 1. What held, and it is worth stating first

The thing the change set out to prove is true. **No interleaving installs
a surviving model.** `publish()` and `invalidate()` share one lock, so a
publish either precedes invalidation — and `_clear` then removes the
model — or it is refused outright.

Verified by the reviewer, not asserted:

- **The orphan path genuinely frees.** Weakref probes placed *inside*
  `empty_cache()` show the model dead for both experiments. `del model`
  is the last reference; the publish lambda is already gone. No reference
  cycle in SSDLite — refcounting alone frees it, `gc.collect()` is
  unnecessary.
- **Reload after FAILED is blocked** at `base.py:74`, so the one-way
  latch cannot brick a reachable module. `unload` → reload builds a fresh
  experiment with a fresh token.
- **Double release, and install-raises-inside-publish, are both safe.**

## 2. What did not hold — six confirmed findings

### C1 — The bound is fiction at the only production call site

`main.py:212` runs `asyncio.run(container.load_and_start())` inside
`create_app()`. `asyncio.run` → `Runner.close` →
`shutdown_default_executor(THREAD_JOIN_TIMEOUT=300)`, **which joins the
orphaned loader thread.**

Measured: `load_and_start` returned in **0.063 s** while `asyncio.run`
took **3.006 s** for a 3 s stall. Worst case is the 120 s bound **plus a
300 s join**.

This is the finding that matters most: the entire purpose of the change
was to bound startup, and at the one place it runs in production, it does
not. Confirmed independently by the lead.

**Test 1 conceals it.** Its line 149 opens the gate *before* returning,
with the comment "Let the orphan out before `asyncio.run()` joins the
executor" — the test works around the exact defect it should expose.

### C2 — TOCTOU on an unlocked `is_cuda` read

`depth.py:143` reads `self._device` outside the lock and `:155` acts on
it. If the loader publishes between those lines, `publish` returns True
(so the loader skips its own `del` / `empty_cache`), `_clear` drops the
CUDA model, and `if is_cuda` is False — so **`empty_cache()` never runs
anywhere.** Same shape at `object_detection.py:127/132`.

### C3 — Raise-after-build is unguarded, and the leak tests miss it

`depth.py:90-91` builds the model and moves it to CUDA; `:93` then makes
a **second** `torch.hub.load` call that can raise. The token guards only
the *publish*, so nothing covers this window. `release()` sees
`_device is None` and skips `empty_cache`; a weakref shows the model
**still alive during `release()`**, held by the traceback.

### C4 — Atomicity is untested

A deliberately non-atomic `publish`/`invalidate` — check, drop the lock,
sleep 20 ms, install — **passes 16/16**. The lock is correct and nothing
would notice if it were removed.

### C5 — A `release()` that frees nothing passes the suite

Gutting `invalidate()`'s teardown leaves the full suite at **exit 0**.
The only assertions that release actually frees a model live in
`test_object_detection_integration.py:117` and
`test_depth_experiment_integration.py` — both inside the baseline's **30
skips**, gated on `TOWER_RUN_MODEL_TESTS=1`.

This is the same failure shape this run has hit twice before: the
protection exists, and the thing that would notice its removal does not
run.

### C6 — The conditional bound is discontinuous, and inverts

`container.py:64-71`. Exercised directly:

```
lifecycle=  9.999  ->  load=  9.999
lifecycle=   10.0  ->  load=  120.0     <- 12,000x swing from 1 ms
lifecycle=   50.0  ->  load=  120.0
lifecycle=  300.0  ->  load=  120.0     <- widened, and load got TIGHTER
```

The intent — "a caller who narrows the container is not asking for 50 ms
everywhere except load" — is right. Comparing the *value* against the
default is the wrong way to express it, because it cannot tell a caller
who passed `10.0` deliberately from one who passed nothing.

**The lead reviewed this code before the adversarial pass and called it
"sound and well-argued", having read the comment's reasoning without
exercising the boundary. That was wrong, and the correction is the point
of an adversarial reviewer that did not write the code.**

### S1 — suspected

`invalidate()`'s teardown deadlocks if it touches the token (reproduced),
and its docstring lacks the non-reentrancy warning `publish()` carries.
Both shipped teardowns are safe today. Teardown also re-runs on every
`release()`.

## 3. Fixes

**Status: all six fixed, plus S1. 2026-08-26.** Every finding above was
reproduced first, by an agent that wrote none of the code under repair.
None failed to reproduce.

### C1 — startup no longer waits for the orphan

Reproduced exactly: `load_and_start` returned in 0.055 s while
`asyncio.run` took **3.006 s** for a 3 s stall behind a 0.05 s bound.

`ExperimentalCVModule._do_load` now calls
`tower.loading.run_abandonable` instead of `asyncio.to_thread`. It is the
same `await`, with the same result and exception relay, but the blocking
call runs on a **`daemon` thread that nothing ever joins** — not
`asyncio.run`'s `shutdown_default_executor`, not interpreter shutdown.
Same scenario after the change: **0.056 s** end to end.

Deliberately not joining a thread is unusual, so it is justified in
`run_abandonable`'s docstring and it is the premise of the bound itself:
a load that overran its bound is *abandoned*, the module is already
FAILED and released, and the invalidation token guarantees the orphan
frees whatever it built rather than installing it. Joining it would make
startup wait for work whose result is thrown away.

Rejected alternatives, and why — recorded in full in §4a of
`2026-08-26-lifecycle-load-timeout.md`:

* **A dedicated `ThreadPoolExecutor`.** Dodges the `asyncio.run` join,
  but `concurrent.futures.thread` registers an atexit hook that joins its
  non-daemon threads at interpreter shutdown. A stuck download would
  become a shutdown hang instead of a startup hang — the bug moved, not
  removed.
* **Stop using `asyncio.run` in `create_app()`.** The comment at
  `main.py:208` is load-bearing: every pre-existing test builds
  `TestClient(create_app())` without `with client:`, which never runs
  ASGI lifespan, so a module loaded there stays UNLOADED forever. That is
  a change to app wiring, not to this bound.
* **Keep the behaviour and document the bound honestly.** The purpose of
  the change was to bound startup. Accurate prose about not doing that is
  not a fix.

**Test 1's evasion is gone.** It no longer opens its gate from inside the
coroutine, and it is now timed around the *whole* `asyncio.run` rather
than the await inside it. A new
`test_startup_does_not_wait_for_the_orphan_it_just_abandoned` never opens
the gate at all. Reverting to `asyncio.to_thread` turns them red at
2.01 s and 4.01 s respectively.

### C2 — the device is read under the lock

Both `depth.release()` and `ObjectDetectionExperiment.release()` now read
`self._device` *inside* the teardown callback, so one lock covers the
question and the answer. `empty_cache()` still runs outside the lock,
where nothing depends on holding it.

Covered by `test_release_frees_cuda_even_if_the_model_lands_mid_release`
(parametrised over both experiments). Rather than hoping to hit a
few-bytecode window, it wraps the token's `invalidate` and publishes a
CUDA model at exactly the contested moment — deterministic, no sleeps.
Reverting either `release()` to the unlocked read turns it red.

### C3 — the raise-after-build window is guarded

Confirmed, and confirmed in the shape that matters: the container calls
`mark_failed()` → `release()` from *inside* its `except` block, where the
live traceback still pins the loader frame and its `model` local. A
weakref showed the model alive during `release()`.

`depth.load()` now wraps `model.to(...)` / `model.eval()` / the second
`torch.hub.load` in `try/except BaseException`, freeing the model (and
`empty_cache()` on CUDA) before re-raising. `object_detection.load()`
gets the same guard, and additionally builds `weights.transforms()` and
the category list *before* the publish rather than inside the install
lambda, where a raise would happen under the token's lock.

Covered by `test_depth_frees_the_model_when_the_second_hub_load_raises`,
which probes the weakref from inside `release()`.

### C4 and C5 — the token is now protected by tests that run

New file: `tests/test_load_invalidation_atomicity.py`. Fakes only — no
model download, no GPU, no `TOWER_RUN_MODEL_TESTS` gate. The token-level
tests need no torch at all.

Measured against deliberately broken production code:

| Mutation | Tests that go red |
|---|---|
| `publish()` checks under the lock and installs outside it | 2 |
| `invalidate()` sets the flag and skips the teardown | 9 |
| `release()` reads the device outside the lock (depth) | 1 |
| `release()` reads the device outside the lock (object detection) | 1 |
| the C3 `except` guard removed | 1 |
| `asyncio.to_thread` restored | 2 |
| the C6 value comparison restored | 1 |

The atomicity tests are deterministic rather than stress-based: a
publisher parks *inside* its install callback while an invalidator runs,
which is exactly the interleaving a non-atomic implementation gets wrong.

### C6 — a `None` sentinel, not a value comparison

`ModuleContainer.__init__` now takes `lifecycle_timeout_s: float | None`
and asks *did the caller specify a bound?*. Explicit `9.999` stays
`9.999`, explicit `10.0` stays `10.0`, explicit `300` stays `300`, and
only an unspecified bound gets `LOAD_TIMEOUT_S`. Verified continuous and
monotonic across `0.05 … 300`. No caller passed either bound
positionally, so the signature change is safe.

### S1 — confirmed, then split

Both halves reproduced.

* **The reentrancy deadlock is real and is kept.** A teardown that reads
  `.invalidated` hangs. Making the lock reentrant would let a teardown
  observe the latch mid-teardown, which is the atomicity C4 exists to
  protect — so this is documented in `invalidate()`'s docstring (matching
  the warning `publish()` already carried) and pinned by
  `test_a_teardown_that_touches_the_token_deadlocks_as_documented`, whose
  failure message points anyone who "fixes" it at the tests to re-examine.
* **The re-running teardown is fixed.** `invalidate()` now runs its
  teardown at most once per token. It cannot ever be needed twice: the
  latch is one-way, so after the first invalidation nothing can be
  installed again and there is never anything new to tear down.
