"""A load that can be abandoned, and a model that cannot outlive it.

This exists for one ordering bug, and it is worth stating precisely
because no implementation of `release()` alone can fix it.

A module lifecycle bounds its load with `asyncio.wait_for`. For that
bound to mean anything against a blocking model load, the load has to run
on a worker thread (`run_abandonable` below -- not `asyncio.to_thread`,
whose executor `asyncio.run` joins on close, which would hand the bound
straight back). But a timeout does not stop the
thread -- nothing in Python can. It abandons it. The container then marks
the module FAILED, which calls `release()`, which sets `_model = None`
and empties the CUDA cache. Some seconds later the abandoned thread
finishes its download, reaches `self._model = model`, and installs a
fully loaded model into a module that is FAILED, will never be asked to
process a frame, and will never be released again. On CUDA that is
resident GPU memory with no owner.

Release running *first* is the whole problem, so the guard cannot live in
release. It lives here: a one-way latch that release closes and that the
loader must pass through before it is allowed to hand anything to `self`.

**One-way on purpose.** There is no `reset()`. A released instance never
loads again -- FAILED is terminal in this repo's lifecycle, and the
module drops its experiment on release and builds a fresh one from the
registry if it ever loads again. A reset would introduce exactly the
race it is meant to prevent: an abandoned thread from load #1 publishing
into load #2.

**Thread-safe because the race is real.** The check and the install are
one critical section, and so are the invalidation and the teardown --
otherwise a loader could pass the check, be pre-empted, and install into
a slot that release had just cleared. Passing teardown to `invalidate()`
rather than doing it afterwards is what makes that structural instead of
a comment somebody has to keep obeying.

Nothing here imports torch, or knows what a model is. It guards an
assignment.
"""

import asyncio
import contextvars
import threading
from typing import Any, Callable


async def run_abandonable(func: Callable[..., Any], /, *args: Any) -> Any:
    """Run a blocking callable off-thread on a thread nobody ever joins.

    This is `asyncio.to_thread` with one difference, and the difference
    is the entire point: `to_thread` uses the loop's **default**
    executor, and `asyncio.run` joins that executor on the way out
    (`Runner.close` -> `loop.shutdown_default_executor`, which waits up
    to `THREAD_JOIN_TIMEOUT = 300` seconds). So a caller that bounds this
    work with `asyncio.wait_for` gets its bound back from `wait_for` and
    then pays the full un-bounded cost anyway when the loop closes.
    Measured on a 3 s stall behind a 0.05 s bound: `load_and_start`
    returned in 0.063 s and `asyncio.run` took 3.006 s.

    **This thread is deliberately never joined**, which is unusual enough
    to justify. It is a `daemon` thread, so neither `asyncio.run` nor
    interpreter shutdown waits for it -- and both of those are the bug,
    not a safety net. The premise of the bound is that a load which
    overran it is *abandoned*: the caller has already marked the module
    FAILED and released it, and `LoadInvalidation` below guarantees that
    whatever the abandoned thread eventually produces is discarded and
    freed by the thread itself rather than installed. Joining it would
    only make startup wait for work whose result is already thrown away.

    A thread per call is affordable because this runs once per module
    load, not per frame.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    context = contextvars.copy_context()

    def _deliver(setter: Callable[[Any], None], value: Any) -> None:
        # The waiter may have been cancelled by its timeout while the
        # orphan was still running; setting either half of a done future
        # raises InvalidStateError, and setting an exception nobody will
        # retrieve logs a spurious "exception was never retrieved".
        if not future.done():
            setter(value)

    def _runner() -> None:
        try:
            result = context.run(func, *args)
        except BaseException as exc:  # relayed verbatim to the awaiter
            payload = (future.set_exception, exc)
        else:
            payload = (future.set_result, result)
        try:
            loop.call_soon_threadsafe(_deliver, *payload)
        except RuntimeError:
            # The loop that was waiting is already closed. That is the
            # abandoned case working as designed: there is nobody left to
            # tell, and the load's own invalidation token has already
            # made sure it built nothing that survives.
            pass

    threading.Thread(
        target=_runner, name="tower-abandonable-load", daemon=True
    ).start()
    return await future


class LoadInvalidation:
    """A one-way latch between a slow loader and the release that beat it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._invalidated = False

    @property
    def invalidated(self) -> bool:
        with self._lock:
            return self._invalidated

    def invalidate(self, teardown: Callable[[], None] | None = None) -> None:
        """Close the latch, and tear down what is already installed.

        Call this FIRST in `release()`, with the clearing as `teardown`.
        Both halves happen under the lock, so a loader can neither install
        into a slot mid-teardown nor slip an install in between.

        `teardown` runs under the lock and must not call back into this
        object -- the lock is not reentrant, and a teardown that so much
        as reads `.invalidated` deadlocks itself (reproduced).

        Idempotent, and idempotent in the strong sense: `release()` must
        be safe to call twice, and safe after a load that never
        completed. `teardown` runs at most ONCE per token. Re-running it
        would be harmless for both shipped teardowns, but it cannot be
        necessary either: the latch is one-way, so after the first
        invalidation nothing can ever be installed again and there is
        never anything new to tear down.
        """
        with self._lock:
            already_invalidated = self._invalidated
            self._invalidated = True
            if teardown is not None and not already_invalidated:
                teardown()

    def publish(self, install: Callable[[], None]) -> bool:
        """Install what the load built -- unless release got there first.

        Returns True if `install` ran. Returns False if the load was
        abandoned, in which case the CALLER still owns what it built and
        must free it: it holds the only reference left, and the release
        that would have freed it has already happened.

        `install` runs under the lock and must not call back into this
        object -- the lock is not reentrant.
        """
        with self._lock:
            if self._invalidated:
                return False
            install()
            return True
