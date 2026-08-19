from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ModuleState(Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    ACTIVE = "active"
    STOPPING = "stopping"
    FAILED = "failed"


class InvalidModuleStateError(Exception):
    """Raised when a lifecycle/process call happens from an illegal state."""


class ModuleUnavailableError(Exception):
    """Raised by ModuleContainer.process() when the module cannot accept observations."""


@dataclass(frozen=True)
class ModuleDataBehavior:
    persists_data: bool
    retains_raw_imagery: bool
    retention: str
    supports_purge: bool
    transmits_externally: bool


@dataclass(frozen=True)
class ModuleDescriptor:
    id: str
    name: str
    version: str
    data_behavior: ModuleDataBehavior


class Module(ABC):
    descriptor: ModuleDescriptor

    def __init__(self) -> None:
        self._state = ModuleState.UNLOADED

    @property
    def state(self) -> ModuleState:
        return self._state

    async def load(self) -> None:
        if self._state != ModuleState.UNLOADED:
            raise InvalidModuleStateError(
                f"load() requires UNLOADED, got {self._state}"
            )
        self._state = ModuleState.LOADING
        await self._do_load()
        self._state = ModuleState.READY

    async def start(self) -> None:
        if self._state != ModuleState.READY:
            raise InvalidModuleStateError(
                f"start() requires READY, got {self._state}"
            )
        await self._do_start()
        self._state = ModuleState.ACTIVE

    def process(self, observation: Any) -> Any:
        if self._state != ModuleState.ACTIVE:
            raise InvalidModuleStateError(
                f"process() requires ACTIVE, got {self._state}"
            )
        return self._do_process(observation)

    async def stop(self) -> None:
        if self._state != ModuleState.ACTIVE:
            raise InvalidModuleStateError(
                f"stop() requires ACTIVE, got {self._state}"
            )
        self._state = ModuleState.STOPPING
        await self._do_stop()
        self._state = ModuleState.READY

    async def unload(self) -> None:
        if self._state != ModuleState.READY:
            raise InvalidModuleStateError(
                f"unload() requires READY, got {self._state}"
            )
        await self._do_unload()
        self._state = ModuleState.UNLOADED

    def mark_failed(self) -> None:
        self._state = ModuleState.FAILED

    @abstractmethod
    async def _do_load(self) -> None: ...

    @abstractmethod
    async def _do_start(self) -> None: ...

    @abstractmethod
    def _do_process(self, observation: Any) -> Any: ...

    @abstractmethod
    async def _do_stop(self) -> None: ...

    @abstractmethod
    async def _do_unload(self) -> None: ...
