"""Tearing the Lab down without leaving anything behind.

An experiment may be mid-load in a background task when the Tower stops.
`release()` cannot wait for it -- it is reachable from `mark_failed()`,
which the frame path can reach, with no loop to await against -- so it
cancels and moves on. Cancellation is delivered at the next await point,
and if the loop closes first the task never reaches the clause that frees
what it built.

That is what `CVLab.shutdown()` is for, and this file is why to believe
it works.
"""

import asyncio
import threading

from tests.cv_lab_fixtures import (  # noqa: F401
    _close_cv_lab_clients,
    armed_lab,
    jpeg_bytes,
    make_client,
)
from tower.cv_lab.contracts import STATE_UNAVAILABLE
from tower.experiments import EXPERIMENTS


class _Blocking:
    """A load that will not finish until it is told to."""

    name = "blocking"
    loading = threading.Event()
    proceed = threading.Event()
    released = 0

    @classmethod
    def reset(cls):
        cls.loading = threading.Event()
        cls.proceed = threading.Event()
        cls.released = 0

    def load(self, settings):
        type(self).loading.set()
        type(self).proceed.wait(5)

    def run(self, raw_bytes):
        raise AssertionError("a shut-down Lab must never process a frame")

    def release(self):
        type(self).released += 1


def test_shutdown_waits_for_an_arm_that_is_still_loading():
    _Blocking.reset()

    async def scenario():
        lab = await armed_lab("baseline")
        original = EXPERIMENTS["edge_detection"]
        EXPERIMENTS["edge_detection"] = _Blocking
        try:
            lab.start("edge_detection")
            await asyncio.get_running_loop().run_in_executor(
                None, _Blocking.loading.wait, 5
            )
            task = lab._arm_task
            _Blocking.proceed.set()
            await lab.shutdown()
        finally:
            EXPERIMENTS["edge_detection"] = original
        return lab, task

    lab, task = asyncio.run(scenario())

    # The task is finished, not merely asked to finish. A pending task at
    # loop close is where "Task was destroyed but it is pending" comes
    # from, and where an unreleased model would hide.
    assert task.done()
    assert lab.status()["lifecycle"]["state"] == STATE_UNAVAILABLE
    # Whatever the abandoned load built was released by the thread that
    # built it, rather than left to a garbage collector that may never
    # come.
    assert _Blocking.released >= 1


def test_shutdown_is_safe_with_no_arm_in_flight():
    async def scenario():
        lab = await armed_lab("baseline")
        await lab.shutdown()
        await lab.shutdown()
        return lab

    lab = asyncio.run(scenario())
    assert lab.status()["lifecycle"]["state"] == STATE_UNAVAILABLE
    assert lab._experiment is None


def test_the_app_lifespan_shuts_the_lab_down(monkeypatch):
    """The whole point of `shutdown()` is that `lifespan` calls it."""
    client = make_client(monkeypatch, "baseline")
    lab = client.app.state.cv_lab
    assert lab.status()["lifecycle"]["state"] == "running"

    client.__exit__(None, None, None)

    assert lab.status()["lifecycle"]["state"] == STATE_UNAVAILABLE
    available, reason = lab.availability()
    assert available is False
    assert reason


def test_the_module_still_reaches_unloaded_after_a_lab_shutdown(monkeypatch):
    """Shutting the Lab down first must not stop the container from
    completing its own teardown -- the module lifecycle is the shared
    contract and this change must not bend it."""
    client = make_client(monkeypatch, "baseline")
    container = client.app.state.module_container
    assert container.state.value == "active"

    client.__exit__(None, None, None)

    assert container.state.value == "unloaded"
