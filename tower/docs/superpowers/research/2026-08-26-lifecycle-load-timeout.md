# The lifecycle load timeout, made real

**Date:** 2026-08-26
**Lane:** Tower
**Subject:** `ModuleContainer`'s load bound, why it was fiction, what it
cost to make it true, and what is deliberately left for V1.1.

---

## 1. The defect

`ModuleContainer` has always wrapped every lifecycle call in
`asyncio.wait_for(..., self._lifecycle_timeout_s)`, with
`LIFECYCLE_TIMEOUT_S = 10.0`. Read as English, that says "no module gets
more than ten seconds to load". It did not say that. It could not.

`asyncio.wait_for` cancels the awaited coroutine, and a coroutine can
only be cancelled **at an await point**. A `_do_load` that calls a
synchronous blocking function never reaches one. The call runs to
completion on the event loop thread, the timer cannot fire because the
loop is not running, and `wait_for` gets its chance only after the thing
it was supposed to interrupt has already finished.

Every model-backed load in this repo is exactly that shape:

* `DepthEstimation.load` → `torch.hub.load(...)` — clones a GitHub
  repository and downloads weights, synchronously.
* `ObjectDetectionExperiment.load` →
  `ssdlite320_mobilenet_v3_large(weights=...)` — downloads COCO weights,
  synchronously.

So the failure mode the timeout existed to prevent — a stalled download
hanging the Tower — was fully live. Worse than merely unbounded: because
the block sits on the event loop thread, a stalled load froze *every*
websocket, every route, and the health endpoint that would have reported
it, for as long as the network took to give up.

This was known. The 2026-08-20 techdebt audit named it (§3a), the
Master Guide classified it as "needs user judgment", and the Object
Memory plan turned it into a costed decision gate rather than copying the
gap into a second module.

## 2. The ruling, and that it was made autonomously

The gate offered five options (A–E) and recommended **E + A**. On
**2026-08-26** the Tower lane ruled **E + A**, under an explicit autonomy
grant, and recorded that in the plan file itself
(`docs/superpowers/plans/2026-08-20-object-memory-first-slice.md`,
Task 4). It is worth being blunt about this in both places: the gate's
own text says the call belongs to the user, so a later reader must not
mistake this for a preference the user expressed. It was delegated, and
it is reversible — E is one constant, A is one line, and the token is
additive.

## 3. Option E: a separate, generous load bound

`ModuleContainer.__init__` already accepted `lifecycle_timeout_s` and
`main.py` never passed it, so every deployment ran on 10 s for
everything. Load now has its own bound:

```python
LOAD_TIMEOUT_S = 120.0
```

**The evidence for 120, measured on this host rather than chosen for
roundness** (`~/.cache/torch/hub/checkpoints`):

| What a cold load must fetch | Bytes |
|---|---|
| `midas_v21_small_256.pt` (depth) | 85.8 MB |
| `tf_efficientnet_lite3` backbone (depth) | 33.2 MB |
| **depth total** | **119.0 MB** + two torch.hub repo clones |
| `ssdlite320_mobilenet_v3_large_coco` | 14.1 MB |

119 MB inside 10 s requires ~95 Mbit/s **sustained from the first byte**,
including TLS handshakes and GitHub redirects. No ordinary link
guarantees that, which is the trap the plan called consequence 1:
enforcing the old bound would have converted "hangs once, then works
forever" into "**fails every first run**". 119 MB inside 120 s requires
~8 Mbit/s, which is an ordinary link.

**It is still a bound.** Warm loads measured on this host:

| Load | Warm cost |
|---|---|
| depth (MiDaS-small), CUDA, cached | 1.80 s |
| SSDLite320, CPU, cached | 0.16 s |
| `import torch` + `torchvision.models.detection` | 2.23 s |

So 120 s is roughly 65x the real warm cost. A stalled download or an
unreachable host is still caught, in bounded time, and the Tower reports
FAILED instead of hanging. start/stop/unload keep the tight 10 s: none of
them touch the network.

**Narrowing still narrows everything.** `load_timeout_s` defaults to
`None`, which resolves to `LOAD_TIMEOUT_S` only while the general bound
is at its default; a caller that asks for a 50 ms container gets 50 ms
for load too. A test asking for a tightly bounded container is not asking
for "50 ms everywhere except load, which may take two minutes".

## 4. Option A: make the load genuinely awaitable

```python
experiment = self._experiment
await asyncio.to_thread(experiment.load, self._settings)
```

One line, in `ExperimentalCVModule._do_load` — the only `Module` subclass
in the repo, and the one whose experiments block. The blocking work now
runs on a worker thread, so the event loop stays live, the timer fires,
and `wait_for` can actually cancel.

**Not in `Module`/`ModuleContainer`.** That is option B. It changes the
execution model of the contract every module depends on, and V1.1 owns
lifecycle hardening. See §6.

## 5. The ordering bug, and the token that fixes it

Making the timeout real exposes a bug that the fiction was hiding, and it
is the part most likely to be got wrong, because **no implementation of
`release()` alone can fix it**.

A timeout does not stop the worker thread. Nothing in Python can. It
**abandons** it. So:

```
t=0.00  load starts on a worker thread; the download begins
t=120   wait_for times out; load_and_start marks the module FAILED
t=120   mark_failed -> _do_release -> experiment.release(): _model = None,
        torch.cuda.empty_cache()
t=135   the abandoned thread finishes its download and runs
        self._model = model; model.to(cuda)
```

The FAILED module now holds a fully loaded model — on CUDA, resident GPU
memory — that nothing will ever release, because release already ran and
will never run again. Release running *first* is the whole problem, which
is why the guard cannot live in release.

**The mitigation, as the plan specified it:** a load-invalidation token.
`tower/loading.py` holds `LoadInvalidation`, which is:

* **A one-way latch.** `release()` calls `invalidate()`; there is no
  `reset()`. A reset would reintroduce exactly the race it prevents — an
  abandoned thread from load #1 publishing into load #2. Safe here
  because FAILED is terminal and the module drops its experiment on
  release, building a fresh one from the registry if it ever loads again.
* **Thread-safe, because the race is real.** The check and the install
  are one critical section (`publish(install)`), and so are the
  invalidation and the teardown (`invalidate(teardown)`). Passing the
  teardown *into* `invalidate` is what makes the ordering structural
  instead of a comment somebody has to keep obeying: clearing first and
  invalidating afterwards would leave open the very window being closed.
* **Explicit about ownership.** `publish` returning `False` means the
  caller still holds the only reference to what it built and must free it
  — which both experiments now do, including `torch.cuda.empty_cache()`
  on the device they actually built on.

Both model-holding experiments were restructured to build into **locals**
and hand over only through `publish()`:
`tower/experiments/depth.py`, `tower/experiments/object_detection.py`.
Nothing about their loaded behaviour changed; what changed is that there
is no longer a window in which `self._model` can be assigned by a thread
nobody is waiting for.

## 6. What B would still change at V1.1

This ruling settles how *one* module loads. It does not settle the
contract, and these remain open:

1. **`Module.load()` / `ModuleContainer` running `_do_load` off-thread
   for every module.** Today a second `Module` subclass that blocks would
   silently reinherit the original gap; only `ExperimentalCVModule` is
   protected, by its own code. B makes the guarantee structural.
2. **A contract statement about what `_do_load` may do.** Right now
   "must not block" is true of one implementation and written in one
   comment. Under B it becomes a property of the base class.
3. **The invalidation token as part of the contract**, rather than
   something each model-holder remembers to use. B would give the base
   class a place to own it, so a new module cannot forget.
4. **`SSDLite320Detector` in `tower/detection.py`.** Untouched here, on
   purpose: Object Memory and Scene Understanding run **out of process**
   by tailing a capture journal, so that detector never meets a module
   lifecycle or this timeout, and it has no leak to fix today. The moment
   any of them is hosted by a `Module`, it needs the same token — that is
   B's migration, alongside depth.
5. **A pre-warm story.** 120 s makes a cold first run survivable; it does
   not make it fast. Option C's insight (pre-provision the weights) stays
   the right operational advice for a demo, and V1.1 could make it a
   startup step instead of folklore.

## 7. Tests

`tests/test_module_lifecycle_load_timeout.py`. Each was proven to fail
against deliberately broken production code before being trusted:

| Test | Proves | Goes red when |
|---|---|---|
| `test_a_synchronous_blocking_load_is_actually_interrupted` | the bound now fires on blocking work, and fires *early* (elapsed assertion, not just state) | `to_thread` removed |
| `test_a_load_that_lands_after_the_timeout_leaves_no_model_behind` | no leak; the abandoned loader discards what it built | the token's `publish` stops honouring invalidation |
| `test_the_depth_experiment_discards_a_model_that_arrives_after_release` | the same, against real `DepthEstimation.load` with `torch.hub` monkeypatched — no download, no weights read | either of the above |
| `test_a_slow_but_legitimate_load_still_succeeds` | E did its job: a 300 ms load survives a 50 ms *general* bound | load falls back to the general bound |
| `test_load_is_bounded_generously_by_default_and_the_rest_stays_tight` | the two numbers are actually different | E reverted |
| `test_narrowing_the_general_bound_narrows_load_with_it` | a tightly bounded container stays tightly bounded | the resolution rule changes |

**The leak test is deterministic, not timing-dependent.** The fake
loader blocks on an event; the test opens that event only *after*
observing that the module is FAILED and the experiment released. The
losing interleaving is therefore guaranteed on every run rather than
hoped for — and the orphan's completion is awaited through a second
event, so the assertions cannot run before the race has happened.
