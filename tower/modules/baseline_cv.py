from tower.frame_processing import FrameProcessingResult, process_frame
from tower.modules.base import Module, ModuleDataBehavior, ModuleDescriptor

DESCRIPTOR = ModuleDescriptor(
    id="baseline-cv",
    name="Baseline CV (V0.7 passthrough)",
    version="0.1.0",
    data_behavior=ModuleDataBehavior(
        persists_data=False,
        retains_raw_imagery=False,
        retention="none",
        supports_purge=False,
        transmits_externally=False,
    ),
)


class BaselineCVModule(Module):
    """The one hardcoded V0.8 module: wraps the existing V0.7 frame-processing
    pipeline (grayscale + mean intensity) behind the module lifecycle
    contract, without changing its behavior. V0.9 replaces this module in
    the same container slot with the real Experimental CV Lab module.
    """

    descriptor = DESCRIPTOR

    async def _do_load(self) -> None:
        return None

    async def _do_start(self) -> None:
        return None

    def _do_process(self, observation: bytes) -> FrameProcessingResult:
        return process_frame(observation)

    async def _do_stop(self) -> None:
        return None

    async def _do_unload(self) -> None:
        return None
