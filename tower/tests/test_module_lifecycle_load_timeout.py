"""The load timeout, made real -- and the leak that making it real exposes.

Three claims are under test here, and every one of them was false before
the change these tests were written against:

1. **A synchronous blocking load is actually interrupted.**
   `ModuleContainer` has always wrapped `load()` in `asyncio.wait_for`,
   but `wait_for` can only cancel at an await point. A `_do_load` that
   calls a blocking C/IO function (`torch.hub.load`, a weight download)
   never yields one, so the bound was decoration. It is enforced now
   because the blocking call runs on a worker thread.

2. **A load that finishes AFTER the timeout leaves nothing behind.**
   This is an ordering bug, not a partial-state bug. On timeout the
   container marks the module FAILED, which releases the experiment --
   and only afterwards does the orphaned loader thread reach the line
   that installs the model. Release has already run and will never run
   again, so the FAILED module ends up holding a live model, and on CUDA
   that is GPU memory nothing will ever free. The test below opens the
   gate on the orphan *after* asserting the module is already FAILED, so
   the losing interleaving is guaranteed rather than hoped for.

3. **A slow-but-legitimate load still succeeds.** Enforcing a 10 s bound
   on a cold first run turns "hangs once, then works forever" into
   "fails every first run", which is a worse bug than the one being
   fixed. Load therefore has its OWN, generous bound, distinct from the
   tight one that still governs start/stop/unload.
"""

import asyncio
import threading
import time

import pytest

from tower.experiments import ExperimentSettings
from tower.loading import LoadInvalidation
from tower.modules.base import ModuleState
from tower.modules.container import (
    LIFECYCLE_TIMEOUT_S,
    LOAD_TIMEOUT_S,
    ModuleContainer,
)
from tower.modules.experimental_cv import ExperimentalCVModule

# Long enough that a test asserting "the container gave up early" cannot
# pass by accident, short enough that the orphaned worker is joined
# without making the suite wait.
BLOCKING_LOAD_S = 2.0


class _SyncBlockingExperiment:
    """Loads by BLOCKING the calling thread. No await point, ever.

    This is the shape of every real model load in this repo: a torch
    import, a weight download, a `.to(device)`. None of them yield to the
    event loop, which is precisely why the old timeout could not touch
    them.
    """

    name = "sync-blocking"

    def __init__(self, gate: threading.Event, hold_s: float) -> None:
        self._gate = gate
        self._hold_s = hold_s
        self.loaded = False
        self.release_calls = 0

    def load(self, settings=None) -> None:
        self._gate.wait(timeout=self._hold_s)
        self.loaded = True

    def run(self, raw_bytes: bytes):
        return "sync-blocking-result"

    def release(self) -> None:
        self.release_calls += 1


class _LateInstallingExperiment:
    """Builds its model off-thread, then installs it -- possibly too late.

    Mirrors the real experiments' structure deliberately: the expensive
    object is built into a local, and only handed to `self` through the
    production invalidation token. A test double that implemented its own
    guard would prove nothing about the code that ships, so this one uses
    `LoadInvalidation` itself.
    """

    name = "late-installing"

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self._invalidation = LoadInvalidation()
        self.model = None
        self.discarded = False
        self.released = False
        self.finished = threading.Event()

    def load(self, settings=None) -> None:
        try:
            self._gate.wait(timeout=BLOCKING_LOAD_S)
            model = object()
            if not self._invalidation.publish(lambda: self._install(model)):
                # Invalidated mid-load: this thread owns the model and
                # nothing else will ever come back for it.
                self.discarded = True
                return
        finally:
            self.finished.set()

    def _install(self, model) -> None:
        self.model = model

    def run(self, raw_bytes: bytes):
        return "late-installing-result"

    def release(self) -> None:
        self.released = True
        self._invalidation.invalidate(self._clear)

    def _clear(self) -> None:
        self.model = None


def _container(experiment, **timeouts) -> ModuleContainer:
    module = ExperimentalCVModule(
        experiment.name, ExperimentSettings(device="cpu"), experiment=experiment
    )
    return ModuleContainer(module, **timeouts)


def test_a_synchronous_blocking_load_is_actually_interrupted():
    """The timeout fires; before the fix it could not.

    The assertion that matters is the elapsed time. A container that
    "reached FAILED" after sitting through the whole blocking load would
    not have enforced anything.
    """
    gate = threading.Event()
    experiment = _SyncBlockingExperiment(gate, hold_s=BLOCKING_LOAD_S)
    container = _container(experiment, lifecycle_timeout_s=10.0, load_timeout_s=0.05)

    async def scenario() -> float:
        started = time.perf_counter()
        await container.load_and_start()
        elapsed = time.perf_counter() - started
        # Let the orphan out before asyncio.run() joins the executor.
        gate.set()
        return elapsed

    elapsed = asyncio.run(scenario())

    assert container.state == ModuleState.FAILED
    assert elapsed < BLOCKING_LOAD_S / 2, (
        f"load_and_start took {elapsed:.2f}s: the 0.05s bound did not "
        "interrupt the blocking load, it merely outlived it"
    )


def test_a_load_that_lands_after_the_timeout_leaves_no_model_behind():
    """The ordering bug, exercised deterministically rather than hopefully.

    The gate is opened only after the module is observed FAILED and the
    experiment observed released -- so the orphan's install attempt
    ALWAYS happens after release, which is the interleaving that leaks.
    """
    gate = threading.Event()
    experiment = _LateInstallingExperiment(gate)
    container = _container(experiment, lifecycle_timeout_s=10.0, load_timeout_s=0.05)

    observed = {}

    async def scenario() -> None:
        await container.load_and_start()
        observed["state"] = container.state
        observed["released"] = experiment.released
        gate.set()

    asyncio.run(scenario())

    assert observed["state"] == ModuleState.FAILED
    assert observed["released"] is True, (
        "the ordering this test exercises requires release() to have "
        "already run when the loader installs its model"
    )
    assert experiment.finished.wait(BLOCKING_LOAD_S * 2), (
        "the orphaned loader never completed; the race was not exercised"
    )
    assert experiment.model is None, (
        "a FAILED module is holding a fully loaded model that nothing "
        "will ever release"
    )
    assert experiment.discarded is True, (
        "the orphaned loader must notice it was invalidated and free what "
        "it built, not merely decline to publish it"
    )


def test_a_slow_but_legitimate_load_still_succeeds():
    """E did its job: a cold load is slow, not doomed.

    The general lifecycle bound here is 50 ms and the load takes 300 ms.
    Under a single shared bound -- which is what `to_thread` alone would
    have given us -- this module would fail every time. It reaches ACTIVE
    because load is bounded separately and generously.
    """
    gate = threading.Event()  # never set: the load takes its full 0.3s
    experiment = _SyncBlockingExperiment(gate, hold_s=0.3)
    container = _container(experiment, lifecycle_timeout_s=0.05, load_timeout_s=5.0)

    asyncio.run(container.load_and_start())

    assert container.state == ModuleState.ACTIVE
    assert experiment.loaded is True


def test_load_is_bounded_generously_by_default_and_the_rest_stays_tight():
    """A cold first run downloads weights; a stop does not.

    119 MB of MiDaS weights inside 10 s needs ~95 Mbit/s sustained from
    the first byte. Inside the load bound it needs ~8 Mbit/s. That gap is
    the whole reason the two numbers are different.
    """
    experiment = _SyncBlockingExperiment(threading.Event(), hold_s=0.0)
    container = _container(experiment)

    assert LOAD_TIMEOUT_S >= 60.0
    assert container._load_timeout_s == LOAD_TIMEOUT_S
    assert container._lifecycle_timeout_s == LIFECYCLE_TIMEOUT_S


def test_narrowing_the_general_bound_narrows_load_with_it():
    """A caller asking for a 50 ms container is not asking for 50 ms
    everywhere except load, which may take two minutes."""
    experiment = _SyncBlockingExperiment(threading.Event(), hold_s=0.0)

    container = _container(experiment, lifecycle_timeout_s=0.05)

    assert container._load_timeout_s == 0.05


def test_the_depth_experiment_discards_a_model_that_arrives_after_release(
    monkeypatch,
):
    """The same race, against the real production loader.

    Opt-in only in the sense that it needs torch importable; `torch.hub`
    is monkeypatched, so nothing is downloaded and no weights are read.
    What runs is `DepthEstimation.load` exactly as it ships.
    """
    torch = pytest.importorskip("torch")

    from tower.experiments.depth import DepthEstimation

    gate = threading.Event()
    finished = threading.Event()
    built = []

    class _FakeModel:
        def __init__(self) -> None:
            self.moved_to = None

        def to(self, device):
            self.moved_to = device
            return self

        def eval(self):
            return self

    class _FakeTransforms:
        small_transform = object()

    def _fake_hub_load(repo, target, **kwargs):
        if target == "transforms":
            return _FakeTransforms()
        gate.wait(timeout=BLOCKING_LOAD_S)
        model = _FakeModel()
        built.append(model)
        return model

    monkeypatch.setattr(torch.hub, "load", _fake_hub_load)

    class _SignallingDepth(DepthEstimation):
        """Real load(), plus a way to know the orphan has finished it."""

        def load(self, settings=None) -> None:
            try:
                super().load(settings)
            finally:
                finished.set()

    experiment = _SignallingDepth()
    module = ExperimentalCVModule(
        "depth", ExperimentSettings(device="cpu"), experiment=experiment
    )
    container = ModuleContainer(module, load_timeout_s=0.05)

    observed = {}

    async def scenario() -> None:
        await container.load_and_start()
        observed["state"] = container.state
        gate.set()

    asyncio.run(scenario())

    assert observed["state"] == ModuleState.FAILED
    assert finished.wait(BLOCKING_LOAD_S * 2)
    assert built, "the orphaned loader never built a model; no race happened"
    assert experiment._model is None
    assert experiment._transform is None
    assert experiment._device is None
