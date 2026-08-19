import asyncio
import logging

import pytest

from tower.modules.base import (
    Module,
    ModuleDataBehavior,
    ModuleDescriptor,
    ModuleState,
    ModuleUnavailableError,
)
from tower.modules.container import ModuleContainer


def _descriptor(module_id: str) -> ModuleDescriptor:
    return ModuleDescriptor(
        id=module_id,
        name=module_id,
        version="0.0.1",
        data_behavior=ModuleDataBehavior(
            persists_data=False,
            retains_raw_imagery=False,
            retention="none",
            supports_purge=False,
            transmits_externally=False,
        ),
    )


class _HappyModule(Module):
    descriptor = _descriptor("happy")

    async def _do_load(self) -> None:
        pass

    async def _do_start(self) -> None:
        pass

    def _do_process(self, observation):
        return f"processed:{observation}"

    async def _do_stop(self) -> None:
        pass

    async def _do_unload(self) -> None:
        pass


class _HangingLoadModule(Module):
    descriptor = _descriptor("hanging-load")

    async def _do_load(self) -> None:
        await asyncio.sleep(999)

    async def _do_start(self) -> None:
        pass

    def _do_process(self, observation):
        return observation

    async def _do_stop(self) -> None:
        pass

    async def _do_unload(self) -> None:
        pass


class _BrokenProcessModule(Module):
    descriptor = _descriptor("broken-process")

    async def _do_load(self) -> None:
        pass

    async def _do_start(self) -> None:
        pass

    def _do_process(self, observation):
        raise RuntimeError("processing exploded")

    async def _do_stop(self) -> None:
        pass

    async def _do_unload(self) -> None:
        pass


class _HangingStopModule(Module):
    descriptor = _descriptor("hanging-stop")

    async def _do_load(self) -> None:
        pass

    async def _do_start(self) -> None:
        pass

    def _do_process(self, observation):
        return observation

    async def _do_stop(self) -> None:
        await asyncio.sleep(999)

    async def _do_unload(self) -> None:
        pass


class _HangingUnloadModule(Module):
    descriptor = _descriptor("hanging-unload")

    async def _do_load(self) -> None:
        pass

    async def _do_start(self) -> None:
        pass

    def _do_process(self, observation):
        return observation

    async def _do_stop(self) -> None:
        pass

    async def _do_unload(self) -> None:
        await asyncio.sleep(999)


def test_load_and_start_reaches_active_and_process_delegates_to_module():
    container = ModuleContainer(_HappyModule())

    asyncio.run(container.load_and_start())

    assert container.state == ModuleState.ACTIVE
    assert container.process("frame") == "processed:frame"


def test_shutdown_from_active_returns_to_unloaded():
    container = ModuleContainer(_HappyModule())
    asyncio.run(container.load_and_start())

    asyncio.run(container.shutdown())

    assert container.state == ModuleState.UNLOADED


def test_load_timeout_marks_failed_and_does_not_raise(caplog):
    caplog.set_level(logging.ERROR, logger="tower.modules.container")
    container = ModuleContainer(_HangingLoadModule(), lifecycle_timeout_s=0.05)

    asyncio.run(container.load_and_start())  # must not raise

    assert container.state == ModuleState.FAILED


def test_process_raises_unavailable_when_not_active():
    container = ModuleContainer(_HappyModule())  # never loaded

    with pytest.raises(ModuleUnavailableError):
        container.process("frame")


def test_process_exception_marks_failed_and_stops_further_processing():
    container = ModuleContainer(_BrokenProcessModule())
    asyncio.run(container.load_and_start())

    with pytest.raises(ModuleUnavailableError):
        container.process("frame")

    assert container.state == ModuleState.FAILED

    # A second call must not attempt to call the broken module again --
    # it should short-circuit on the FAILED state check alone.
    with pytest.raises(ModuleUnavailableError):
        container.process("frame")


def test_shutdown_stop_timeout_marks_failed_and_does_not_raise():
    container = ModuleContainer(_HangingStopModule(), lifecycle_timeout_s=0.05)
    asyncio.run(container.load_and_start())
    assert container.state == ModuleState.ACTIVE

    asyncio.run(container.shutdown())  # must not raise

    assert container.state == ModuleState.FAILED


def test_shutdown_unload_timeout_marks_failed_and_does_not_raise():
    container = ModuleContainer(_HangingUnloadModule(), lifecycle_timeout_s=0.05)
    asyncio.run(container.load_and_start())
    assert container.state == ModuleState.ACTIVE

    asyncio.run(container.shutdown())  # must not raise

    assert container.state == ModuleState.FAILED
