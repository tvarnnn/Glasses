# Adversarial review of the load-invalidation guarantee

**Date:** 2026-08-26
**Reviewed:** commit `767a633` — the E+A lifecycle ruling
**Reviewer:** an agent that did not write the code
**Verdict:** the core guarantee **holds**. Everything around it does not.
**Status:** findings recorded; fixes tracked in §3.

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

The right shape for C6 is to stop comparing values and ask the real
question — *did the caller specify a bound?* — with a `None` sentinel:
an explicit `9.999` stays `9.999`, an explicit `300` stays `300`, and an
unspecified bound gets `LOAD_TIMEOUT_S`. No cliff, no inversion.

C1 is the one that needs a decision rather than a patch: bounding
`load_and_start` is pointless while `asyncio.run` joins the executor
afterwards. Either startup stops using `asyncio.run` for this, or the
bound must be honest about covering only the awaited portion.

C4 and C5 are test defects, and they are why C2 and C3 survived review:
the suite cannot currently distinguish a working token from a gutted one.
