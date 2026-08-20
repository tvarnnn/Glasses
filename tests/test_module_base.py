import asyncio
import logging

import pytest

from tower.modules.base import (
    InvalidModuleStateError,
    Module,
    ModuleDataBehavior,
    ModuleDescriptor,
    ModuleState,
)


class _RecordingModule(Module):
    descriptor = ModuleDescriptor(
        id="test-module",
        name="Test Module",
        version="0.0.1",
        data_behavior=ModuleDataBehavior(
            persists_data=False,
            retains_raw_imagery=False,
            retention="none",
            supports_purge=False,
            transmits_externally=False,
        ),
    )

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def _do_load(self) -> None:
        self.calls.append("load")

    async def _do_start(self) -> None:
        self.calls.append("start")

    def _do_process(self, observation):
        self.calls.append(f"process:{observation}")
        return f"result:{observation}"

    async def _do_stop(self) -> None:
        self.calls.append("stop")

    async def _do_unload(self) -> None:
        self.calls.append("unload")


def test_module_starts_unloaded():
    module = _RecordingModule()
    assert module.state == ModuleState.UNLOADED


def test_full_lifecycle_happy_path_transitions_and_calls_hooks_in_order():
    module = _RecordingModule()

    asyncio.run(module.load())
    assert module.state == ModuleState.READY

    asyncio.run(module.start())
    assert module.state == ModuleState.ACTIVE

    result = module.process("frame-bytes")
    assert result == "result:frame-bytes"
    assert module.state == ModuleState.ACTIVE

    asyncio.run(module.stop())
    assert module.state == ModuleState.READY

    asyncio.run(module.unload())
    assert module.state == ModuleState.UNLOADED

    assert module.calls == [
        "load",
        "start",
        "process:frame-bytes",
        "stop",
        "unload",
    ]


def test_start_before_load_raises_invalid_state():
    module = _RecordingModule()

    with pytest.raises(InvalidModuleStateError):
        asyncio.run(module.start())


def test_process_before_active_raises_invalid_state():
    module = _RecordingModule()

    with pytest.raises(InvalidModuleStateError):
        module.process("frame-bytes")


def test_load_twice_raises_invalid_state():
    module = _RecordingModule()
    asyncio.run(module.load())

    with pytest.raises(InvalidModuleStateError):
        asyncio.run(module.load())


def test_mark_failed_forces_failed_state_from_any_state():
    module = _RecordingModule()
    asyncio.run(module.load())
    asyncio.run(module.start())

    module.mark_failed()

    assert module.state == ModuleState.FAILED

    with pytest.raises(InvalidModuleStateError):
        module.process("frame-bytes")


class _ReleaseTrackingModule(Module):
    descriptor = ModuleDescriptor(
        id="release-tracking",
        name="Release Tracking",
        version="0.0.1",
        data_behavior=ModuleDataBehavior(
            persists_data=False,
            retains_raw_imagery=False,
            retention="none",
            supports_purge=False,
            transmits_externally=False,
        ),
    )

    def __init__(self) -> None:
        super().__init__()
        self.release_calls = 0

    async def _do_load(self) -> None:
        pass

    async def _do_start(self) -> None:
        pass

    def _do_process(self, observation):
        return observation

    async def _do_stop(self) -> None:
        pass

    async def _do_unload(self) -> None:
        pass

    def _do_release(self) -> None:
        self.release_calls += 1


class _RaisingReleaseModule(Module):
    descriptor = ModuleDescriptor(
        id="raising-release",
        name="Raising Release",
        version="0.0.1",
        data_behavior=ModuleDataBehavior(
            persists_data=False,
            retains_raw_imagery=False,
            retention="none",
            supports_purge=False,
            transmits_externally=False,
        ),
    )

    async def _do_load(self) -> None:
        pass

    async def _do_start(self) -> None:
        pass

    def _do_process(self, observation):
        return observation

    async def _do_stop(self) -> None:
        pass

    async def _do_unload(self) -> None:
        pass

    def _do_release(self) -> None:
        raise RuntimeError("release exploded")


def test_default_do_release_is_a_safe_no_op():
    module = _RecordingModule()

    module.mark_failed()  # must not raise even though _do_release is unimplemented

    assert module.state == ModuleState.FAILED


def test_mark_failed_calls_do_release():
    module = _ReleaseTrackingModule()
    asyncio.run(module.load())
    asyncio.run(module.start())

    module.mark_failed()

    assert module.state == ModuleState.FAILED
    assert module.release_calls == 1


def test_mark_failed_swallows_do_release_exception(caplog):
    caplog.set_level(logging.ERROR, logger="tower.modules.base")
    module = _RaisingReleaseModule()

    module.mark_failed()  # must not raise

    assert module.state == ModuleState.FAILED
