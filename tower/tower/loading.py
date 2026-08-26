"""A load that can be abandoned, and a model that cannot outlive it.

This exists for one ordering bug, and it is worth stating precisely
because no implementation of `release()` alone can fix it.

A module lifecycle bounds its load with `asyncio.wait_for`. For that
bound to mean anything against a blocking model load, the load has to run
on a worker thread (`asyncio.to_thread`). But a timeout does not stop the
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

import threading
from typing import Callable


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

        Idempotent: `release()` must be safe to call twice, and safe after
        a load that never completed.
        """
        with self._lock:
            self._invalidated = True
            if teardown is not None:
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
