import asyncio

from tower.modules.base import ModuleState
from tower.modules.depth_cv import DepthEstimationModule


class _FakeDepthExperiment:
    def __init__(self) -> None:
        self.loaded_with_device = None
        self.release_calls = 0
        self.run_calls = 0

    def load(self, device: str) -> None:
        self.loaded_with_device = device

    def run(self, raw_bytes: bytes):
        self.run_calls += 1
        return f"depth-result:{raw_bytes!r}"

    def release(self) -> None:
        self.release_calls += 1


def test_full_lifecycle_with_cpu_device_delegates_to_experiment():
    fake = _FakeDepthExperiment()
    module = DepthEstimationModule(device="cpu", experiment=fake)

    asyncio.run(module.load())
    assert module.state == ModuleState.READY
    assert fake.loaded_with_device == "cpu"

    asyncio.run(module.start())
    assert module.state == ModuleState.ACTIVE

    result = module.process(b"frame-bytes")
    assert result == "depth-result:b'frame-bytes'"
    assert fake.run_calls == 1

    asyncio.run(module.stop())
    asyncio.run(module.unload())
    assert module.state == ModuleState.UNLOADED
    assert fake.release_calls == 1


def test_mark_failed_releases_the_experiment():
    fake = _FakeDepthExperiment()
    module = DepthEstimationModule(device="cpu", experiment=fake)
    asyncio.run(module.load())
    asyncio.run(module.start())

    module.mark_failed()

    assert module.state == ModuleState.FAILED
    assert fake.release_calls == 1


def test_descriptor_matches_experimental_cv_lab_id():
    module = DepthEstimationModule(device="cpu", experiment=_FakeDepthExperiment())

    assert module.descriptor.id == "experimental-cv"
    assert module.descriptor.name == "Experimental CV Lab"
