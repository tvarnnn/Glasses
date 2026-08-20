from tower.experiments import ExperimentResult
from tower.experiments.depth import DepthEstimation
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


class DepthEstimationModule(Module):
    """Runs the MiDaS-small depth experiment. Same descriptor id/name as
    ExperimentalCVModule -- from the platform's perspective this is
    still the one Experimental CV Lab slot, just a different backing
    implementation selected by TOWER_CV_EXPERIMENT=depth, same as
    switching between baseline/edge_detection doesn't change module_id.

    Stateful by design: this is the first Module in the Lab that
    actually exercises Module._do_release().
    """

    descriptor = DESCRIPTOR

    def __init__(self, device: str, experiment: DepthEstimation | None = None) -> None:
        super().__init__()
        self._requested_device = device
        self._experiment = experiment if experiment is not None else DepthEstimation()

    async def _do_load(self) -> None:
        self._experiment.load(_resolve_device(self._requested_device))

    async def _do_start(self) -> None:
        return None

    def _do_process(self, observation: bytes) -> ExperimentResult:
        return self._experiment.run(observation)

    async def _do_stop(self) -> None:
        return None

    async def _do_unload(self) -> None:
        self._experiment.release()

    def _do_release(self) -> None:
        self._experiment.release()


def _resolve_device(requested: str) -> str:
    if requested == "cpu":
        return "cpu"
    import torch

    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(
                "TOWER_CV_DEVICE=cuda requested but no CUDA device is available"
            )
        return "cuda"
    return "cuda" if torch.cuda.is_available() else "cpu"  # "auto"
