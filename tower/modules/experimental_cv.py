from tower.experiments import EXPERIMENTS, ExperimentResult
from tower.modules.base import Module, ModuleDataBehavior, ModuleDescriptor

DESCRIPTOR = ModuleDescriptor(
    id="experimental-cv",
    name="Experimental CV Lab",
    version="0.1.0",
    data_behavior=ModuleDataBehavior(
        persists_data=False,
        retains_raw_imagery=False,
        retention="none",
        supports_purge=False,
        transmits_externally=False,
    ),
)


class ExperimentalCVModule(Module):
    """Runs exactly one configured, stateless experiment function per frame.

    Stateless by design: no experiment allocates a persistent resource in
    _do_load(), which keeps V0.8's deferred resource-leak-on-partial-
    failure finding inert for this milestone.
    """

    descriptor = DESCRIPTOR

    def __init__(self, experiment_name: str) -> None:
        super().__init__()
        self._experiment_name = experiment_name
        self._experiment_fn = None

    async def _do_load(self) -> None:
        fn = EXPERIMENTS.get(self._experiment_name)
        if fn is None:
            raise ValueError(
                f"unknown experiment {self._experiment_name!r}; "
                f"available: {sorted(EXPERIMENTS)}"
            )
        self._experiment_fn = fn

    async def _do_start(self) -> None:
        return None

    def _do_process(self, observation: bytes) -> ExperimentResult:
        return self._experiment_fn(observation)

    async def _do_stop(self) -> None:
        return None

    async def _do_unload(self) -> None:
        self._experiment_fn = None
