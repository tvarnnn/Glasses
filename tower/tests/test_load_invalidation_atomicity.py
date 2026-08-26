"""The protections around the load handover, tested so that removing one fails.

An adversarial review found that the lock in `LoadInvalidation` and the
teardown in `invalidate()` were both *correct* and both *unprotected*: a
deliberately non-atomic publish/invalidate passed 16/16, and gutting the
teardown left the whole suite at exit 0. The only assertions that would
have noticed lived in the model-download tests, which are skipped unless
`TOWER_RUN_MODEL_TESTS=1`.

Nothing here downloads a model or needs a GPU. The token-level tests need
no torch at all, so the core guarantee stays covered in any environment.

Each test below names the mutation it is here to catch:

* remove the lock from `publish()` or `invalidate()`  -> the atomicity tests fail
* make `invalidate()` set the flag without tearing down -> the teardown tests fail
* read the device outside the lock in `release()`      -> the TOCTOU tests fail
* drop the `except` around the model build in `load()` -> the leak test fails
"""

import gc
import threading
import time
import weakref

import pytest

from tower.loading import LoadInvalidation

# Long enough that a thread which was supposed to block has visibly
# blocked, short enough that the suite does not notice.
INTERLEAVE_S = 0.05
JOIN_S = 5.0


class _FakeModel:
    """Stands in for a torch module. Cheap, and weakref-able."""

    def to(self, device):
        self.moved_to = device
        return self

    def eval(self):
        return self


# ---------------------------------------------------------------------------
# Atomicity: the lock is load-bearing, and its removal must be noticed.
# ---------------------------------------------------------------------------


def test_a_publish_racing_an_invalidate_never_survives_it():
    """The guarantee in one line: once `invalidate()` returns, the slot is empty.

    Deterministic, not hopeful. The publisher is parked *inside* its
    install callback while the invalidator runs, which is the exact
    interleaving a non-atomic implementation gets wrong: check, lose the
    lock, let release clear the slot, then install into it anyway.

    Fails if the lock is removed from either `publish()` or
    `invalidate()`.
    """
    token = LoadInvalidation()
    slot = {"model": None}
    install_entered = threading.Event()
    let_install_finish = threading.Event()

    def install() -> None:
        install_entered.set()
        let_install_finish.wait(JOIN_S)
        slot["model"] = "MODEL"

    def teardown() -> None:
        slot["model"] = None

    published: list[bool] = []
    publisher = threading.Thread(target=lambda: published.append(token.publish(install)))
    publisher.start()
    assert install_entered.wait(JOIN_S), "the publisher never reached its install"

    invalidator = threading.Thread(target=lambda: token.invalidate(teardown))
    invalidator.start()
    # Let the invalidator reach the lock and, if there is no lock, run
    # its teardown to completion before the install lands.
    time.sleep(INTERLEAVE_S)
    let_install_finish.set()

    publisher.join(JOIN_S)
    invalidator.join(JOIN_S)
    assert not publisher.is_alive() and not invalidator.is_alive()

    assert slot["model"] is None, (
        "a model installed by a racing publish outlived the invalidation "
        "that was supposed to tear it down -- publish and invalidate are "
        "not one critical section"
    )


def test_install_and_teardown_never_run_at_the_same_time():
    """Mutual exclusion, observed directly rather than inferred.

    The publisher parks inside `install` and watches for the teardown to
    start. Under one shared lock it can never see it. If either half runs
    unlocked, it sees it immediately.
    """
    token = LoadInvalidation()
    teardown_started = threading.Event()
    install_entered = threading.Event()
    observed = {}

    def install() -> None:
        install_entered.set()
        # Returns True only if a teardown started while we were inside
        # the install -- i.e. only if the lock is not doing its job.
        observed["overlap"] = teardown_started.wait(INTERLEAVE_S * 4)

    def teardown() -> None:
        teardown_started.set()

    publisher = threading.Thread(target=lambda: token.publish(install))
    publisher.start()
    assert install_entered.wait(JOIN_S)

    invalidator = threading.Thread(target=lambda: token.invalidate(teardown))
    invalidator.start()

    publisher.join(JOIN_S)
    invalidator.join(JOIN_S)
    assert not publisher.is_alive() and not invalidator.is_alive()

    assert observed["overlap"] is False, (
        "a teardown ran while an install was still in flight: the check "
        "and the install are not in the same critical section"
    )


def test_an_invalidate_in_flight_blocks_a_publish_rather_than_racing_it():
    """The mirror image: teardown parks, and no publish may slip past it.

    Without the lock on `invalidate()`, the publisher sees a latch that
    has not been closed yet, installs, and the half-finished teardown
    never clears what it installed.
    """
    token = LoadInvalidation()
    slot = {"model": None}
    teardown_entered = threading.Event()
    let_teardown_finish = threading.Event()

    def teardown() -> None:
        teardown_entered.set()
        let_teardown_finish.wait(JOIN_S)
        slot["model"] = None

    invalidator = threading.Thread(target=lambda: token.invalidate(teardown))
    invalidator.start()
    assert teardown_entered.wait(JOIN_S), "the invalidator never reached its teardown"

    published: list[bool] = []

    def publish() -> None:
        published.append(token.publish(lambda: slot.__setitem__("model", "MODEL")))

    publisher = threading.Thread(target=publish)
    publisher.start()
    time.sleep(INTERLEAVE_S)
    let_teardown_finish.set()

    invalidator.join(JOIN_S)
    publisher.join(JOIN_S)
    assert not publisher.is_alive() and not invalidator.is_alive()

    assert published == [False], (
        "a publish slipped past an invalidation that was already under way"
    )
    assert slot["model"] is None


# ---------------------------------------------------------------------------
# Teardown: `invalidate()` frees, and a `release()` that frees nothing fails.
# ---------------------------------------------------------------------------


def test_invalidate_actually_runs_the_teardown_it_was_handed():
    """Gutting the teardown used to leave the suite at exit 0."""
    token = LoadInvalidation()
    slot = {"model": _FakeModel()}
    probe = weakref.ref(slot["model"])

    token.invalidate(lambda: slot.__setitem__("model", None))

    assert token.invalidated is True
    assert slot["model"] is None, "invalidate() closed the latch but freed nothing"
    gc.collect()
    assert probe() is None, "the model survived a teardown that claimed to drop it"


def test_the_teardown_runs_once_no_matter_how_often_release_is_called():
    """S1: the latch is one-way, so a second teardown can never be needed.

    Re-running it is not merely wasteful -- it re-does device queries and
    a cache flush for a slot that provably cannot have refilled, because
    nothing can be installed after the first invalidation.
    """
    token = LoadInvalidation()
    calls: list[int] = []

    token.invalidate(lambda: calls.append(1))
    token.invalidate(lambda: calls.append(2))
    token.invalidate(lambda: calls.append(3))

    assert calls == [1]
    assert token.invalidated is True


def test_a_teardown_that_touches_the_token_deadlocks_as_documented():
    """The non-reentrancy warning in the docstring is a real constraint.

    Pinned so that anyone who makes the lock reentrant to "fix" this has
    to come here and think about it: reentrancy would let a teardown
    observe the latch mid-teardown, and the atomicity above is the whole
    point of holding it.
    """
    token = LoadInvalidation()
    returned = threading.Event()

    def reentrant_teardown() -> None:
        _ = token.invalidated  # takes the same non-reentrant lock

    threading.Thread(
        target=lambda: (token.invalidate(reentrant_teardown), returned.set()),
        daemon=True,
    ).start()

    assert not returned.wait(1.0), (
        "invalidate() no longer deadlocks on a reentrant teardown. If the "
        "lock became reentrant, the mutual exclusion tests above are the "
        "thing to re-examine, not this one."
    )


# ---------------------------------------------------------------------------
# The real experiments, with fakes: no download, no GPU, no skip marker.
# ---------------------------------------------------------------------------


def _fake_cuda(monkeypatch, torch):
    """Make the CUDA branch of `release()` observable on any host."""
    empties: list[int] = []
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: empties.append(1))
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 0)
    return empties


def test_depth_release_frees_the_model_and_empties_the_cuda_cache(monkeypatch):
    """C5 at the experiment level: a `release()` that frees nothing must fail.

    The only assertions that a release actually frees a model used to
    live in the model-download tests, which do not run by default.
    """
    torch = pytest.importorskip("torch")

    from tower.experiments.depth import DepthEstimation

    empties = _fake_cuda(monkeypatch, torch)
    experiment = DepthEstimation()
    model = _FakeModel()
    probe = weakref.ref(model)
    experiment._install(model, object(), torch.device("cuda"))
    del model

    experiment.release()

    assert experiment._model is None
    assert experiment._transform is None
    assert experiment._device is None
    assert empties == [1], "released a CUDA model without emptying the cache"
    gc.collect()
    assert probe() is None, "the released model is still alive"


def test_object_detection_release_frees_the_model_and_empties_the_cuda_cache(
    monkeypatch,
):
    torch = pytest.importorskip("torch")

    from tower.experiments.object_detection import ObjectDetectionExperiment

    empties = _fake_cuda(monkeypatch, torch)
    experiment = ObjectDetectionExperiment()
    model = _FakeModel()
    probe = weakref.ref(model)
    experiment._install(model, object(), ["person"], torch.device("cuda"))
    del model

    experiment.release()

    assert experiment._model is None
    assert experiment._categories is None
    assert experiment._device is None
    assert empties == [1], "released a CUDA model without emptying the cache"
    gc.collect()
    assert probe() is None


@pytest.mark.parametrize("experiment_name", ["depth", "object_detection"])
def test_release_frees_cuda_even_if_the_model_lands_mid_release(
    monkeypatch, experiment_name
):
    """C2: the TOCTOU, constructed deterministically instead of raced.

    `release()` used to read `self._device` outside the lock and act on
    it several lines later. An abandoned loader that publishes in that
    window makes `publish()` return True -- so the loader skips its own
    `del` and `empty_cache()` -- while `_clear` drops the CUDA model and
    the stale `is_cuda` is still False. `empty_cache()` then runs
    NOWHERE, and the freed blocks stay in torch's caching allocator.

    Rather than hoping to hit a few-bytecode window, the publish is
    injected at exactly that point: wrapped around the token's
    `invalidate`, so it lands after `release()` has had its chance to
    look at `_device` and before the teardown runs. A `release()` that
    reads the device under the lock sees the model; one that read it
    earlier does not.
    """
    torch = pytest.importorskip("torch")

    if experiment_name == "depth":
        from tower.experiments.depth import DepthEstimation as Experiment

        def install(experiment, model, device):
            experiment._install(model, object(), device)
    else:
        from tower.experiments.object_detection import (
            ObjectDetectionExperiment as Experiment,
        )

        def install(experiment, model, device):
            experiment._install(model, object(), ["person"], device)

    empties = _fake_cuda(monkeypatch, torch)
    experiment = Experiment()
    cuda = torch.device("cuda")
    # Held in a list, and popped out of it at publish time, so that after
    # the publish the experiment holds the ONLY reference -- which is
    # what makes the weakref assertion below mean something.
    holder = [_FakeModel()]
    probe = weakref.ref(holder[0])

    token = experiment._invalidation
    real_invalidate = token.invalidate

    def racing_invalidate(teardown=None):
        # The abandoned loader wins by a hair: it publishes here, after
        # release() could have looked at _device and before anything is
        # torn down. publish() returns True, so the loader does NOT free
        # the model itself -- this release is now the only thing that can.
        assert token.publish(lambda: install(experiment, holder.pop(), cuda)) is True
        return real_invalidate(teardown)

    monkeypatch.setattr(token, "invalidate", racing_invalidate)

    experiment.release()

    assert experiment._model is None
    assert empties == [1], (
        "a CUDA model was published between release()'s device check and "
        "its teardown, and empty_cache() ran nowhere: the loader skipped "
        "it because publish() succeeded, and release() skipped it because "
        "it had read a stale device"
    )
    gc.collect()
    assert probe() is None


def test_depth_frees_the_model_when_the_second_hub_load_raises():
    """C3: the window the invalidation token does not cover.

    `load()` builds the model and moves it to the device, and only then
    makes a SECOND `torch.hub.load` call for the transforms. That call
    can raise. The token guards the publish, so nothing guarded this --
    and the leak is not theoretical: the container catches the exception
    and calls `release()` from inside its `except` block, where the live
    traceback still pins this frame and its `model` local. `_device` is
    None by then, so `release()` skips `empty_cache()` too.

    The probe runs INSIDE `release()`, which is the only place the
    difference is visible.
    """
    torch = pytest.importorskip("torch")

    from tower.experiments.depth import DepthEstimation

    probes: list[weakref.ref] = []

    def fake_hub_load(repo, target, **kwargs):
        if target == "transforms":
            raise RuntimeError("hub cache is corrupt")
        model = _FakeModel()
        probes.append(weakref.ref(model))
        return model

    observed = {}

    class _ProbingDepth(DepthEstimation):
        def release(self) -> None:
            gc.collect()
            observed["alive_during_release"] = probes[0]() is not None
            super().release()

    experiment = _ProbingDepth()
    original_load = torch.hub.load
    torch.hub.load = fake_hub_load
    try:
        try:
            experiment.load()
        except RuntimeError:
            # Exactly how the container reaches release(): from inside
            # the `except` block, with the traceback still live.
            experiment.release()
        else:
            pytest.fail("the fake transforms load was supposed to raise")
    finally:
        torch.hub.load = original_load

    assert probes, "no model was ever built; the window was not exercised"
    assert observed["alive_during_release"] is False, (
        "a model built before the raise was still alive during release(), "
        "pinned by the traceback -- on CUDA that is resident GPU memory "
        "that release() also declines to free, because _device is None"
    )
