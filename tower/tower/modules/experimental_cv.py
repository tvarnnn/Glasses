from tower.experiments import EXPERIMENTS, ExperimentResult, ExperimentSettings
from tower.loading import run_abandonable
from tower.modules.base import Module, ModuleDataBehavior, ModuleDescriptor

DESCRIPTOR = ModuleDescriptor(
    id="experimental-cv",
    name="Experimental CV Lab",
    version="0.2.0",
    data_behavior=ModuleDataBehavior(
        persists_data=False,
        retains_raw_imagery=False,
        retention="none",
        supports_purge=False,
        transmits_externally=False,
    ),
)


class ExperimentalCVModule(Module):
    """Hosts exactly one selected experiment, stateful or not.

    There used to be a second Module subclass with this same descriptor id,
    existing only because the depth experiment holds a model across frames.
    The Lab's V1 adds two more stateful experiments, so that pattern would
    have meant four more near-identical classes. The state now lives behind
    the `Experiment` protocol and this class stopped caring.

    `data_behavior` still declares no persistence and no retained imagery,
    and that must stay true: an experiment that wanted to persist would
    make this descriptor a lie, and the descriptor is what the privacy
    policy is enforced against.
    """

    descriptor = DESCRIPTOR

    def __init__(
        self,
        experiment_name: str,
        settings: ExperimentSettings | None = None,
        experiment=None,
    ) -> None:
        super().__init__()
        self._experiment_name = experiment_name
        self._settings = settings or ExperimentSettings()
        # Injected instance wins, for tests and for a caller that has
        # already built one. Otherwise the registry factory runs in
        # _do_load, never at construction: building a detector here would
        # load model weights merely because someone constructed a module.
        self._experiment = experiment

    async def _do_load(self) -> None:
        if self._experiment is None:
            factory = EXPERIMENTS.get(self._experiment_name)
            if factory is None:
                raise ValueError(
                    f"unknown experiment {self._experiment_name!r}; "
                    f"available: {sorted(EXPERIMENTS)}"
                )
            self._experiment = factory()
        # On a thread, not inline, and this is the only reason the
        # container's load timeout means anything. `asyncio.wait_for` can
        # cancel only at an await point; `experiment.load()` for a
        # model-backed experiment is a torch import, a weight download and
        # a `.to(device)`, none of which yield one. Called inline, a
        # stalled download hangs the event loop -- the whole Tower, every
        # websocket -- for as long as it takes, with a 120 s timer
        # watching and unable to act.
        #
        # `run_abandonable`, not `asyncio.to_thread`: `to_thread` runs on
        # the loop's DEFAULT executor, and `create_app()` drives this
        # through `asyncio.run`, which joins that executor on close. The
        # bound would be handed straight back at the one place it runs in
        # production. See tower/loading.py for the measurement.
        #
        # Deliberately in this module rather than in `Module.load()`:
        # moving every module's `_do_load` off-thread changes the
        # execution model of the shared lifecycle contract, and V1.1 owns
        # lifecycle hardening. See the 2026-08-26 ruling in
        # docs/superpowers/plans/2026-08-20-object-memory-first-slice.md.
        #
        # Read into a local first: a timeout marks the module FAILED and
        # clears `self._experiment` while this call is still in flight.
        experiment = self._experiment
        await run_abandonable(experiment.load, self._settings)

    async def _do_start(self) -> None:
        return None

    def _do_process(self, observation: bytes) -> ExperimentResult:
        return self._experiment.run(observation)

    async def _do_stop(self) -> None:
        return None

    async def _do_unload(self) -> None:
        self._release()

    def _do_release(self) -> None:
        self._release()

    def _release(self) -> None:
        """Free whatever the experiment holds, and forget it.

        Must be safe after a partial load and safe to call twice --
        `mark_failed()` can be reached from anywhere, including from
        inside `_do_load` itself.
        """
        experiment, self._experiment = self._experiment, None
        if experiment is not None:
            experiment.release()
