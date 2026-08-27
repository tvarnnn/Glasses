import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


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


class FrameProcessingError(Exception):
    """Raised by a module's _do_process() to signal a recoverable,
    frame-scoped failure OR refusal (e.g. an undecodable frame, or a
    module that is deliberately not processing right now). ModuleContainer
    treats this as "drop this one frame" -- it must NOT take the whole
    module down. Any other exception from _do_process() is still a
    genuine module failure and still marks the module FAILED.

    `reason` is an optional machine-readable code that reaches the client
    as `frame_error.reason` in place of the generic `frame_skipped`.
    Optional because the transport must keep working for a module that
    names nothing, and useful because "that frame was undecodable" and
    "this module is paused" are different facts a person acts on
    differently. It is a CODE, not prose -- the prose is the exception
    message, which travels beside it.
    """

    def __init__(self, *args, reason: str | None = None) -> None:
        super().__init__(*args)
        self.reason = reason


class FrameSkippedError(ModuleUnavailableError):
    """A ModuleUnavailableError specifically because one frame failed a
    recoverable, frame-scoped check -- the module itself is still ACTIVE
    and will accept the next frame. Callers that only care "was this
    frame dropped" can keep catching ModuleUnavailableError unchanged;
    callers that want to distinguish "one bad frame" from "module died"
    (e.g. metrics) can catch this subtype specifically.

    Carries the `reason` of the FrameProcessingError it was raised from,
    when there was one. The container is the only thing that translates
    between the two, so the code the module chose survives the hop
    without the transport having to know which module chose it.
    """

    def __init__(self, *args, reason: str | None = None) -> None:
        super().__init__(*args)
        self.reason = reason


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
        try:
            self._do_release()
        except Exception:
            logger.exception(
                "module %s: _do_release() raised during FAILED transition",
                self.descriptor.id,
            )

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

    def _do_release(self) -> None:
        """Best-effort synchronous resource release on a FAILED transition.

        Default no-op. Override for a module holding a resource (e.g. a
        loaded model) that must not survive FAILED, regardless of which
        lifecycle stage caused it. Must not raise. Must be safe to call
        even if _do_load() only partially completed. Deliberately
        synchronous, not async: mark_failed() can be reached from
        ModuleContainer.process(), a synchronous hot-path method with no
        running event loop to await against.
        """
        return None
