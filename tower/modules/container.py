import asyncio
import logging
from typing import Any

from tower.modules.base import (
    FrameProcessingError,
    FrameSkippedError,
    Module,
    ModuleDescriptor,
    ModuleState,
    ModuleUnavailableError,
)

logger = logging.getLogger(__name__)

LIFECYCLE_TIMEOUT_S = 10.0


class ModuleContainer:
    """Drives the single hardcoded V0.8 module through its full lifecycle.

    Registry of one: this container holds exactly one Module instance,
    constructed by the caller. No discovery, no swapping.
    """

    def __init__(
        self, module: Module, lifecycle_timeout_s: float = LIFECYCLE_TIMEOUT_S
    ) -> None:
        self._module = module
        self._lifecycle_timeout_s = lifecycle_timeout_s

    @property
    def state(self) -> ModuleState:
        return self._module.state

    @property
    def descriptor(self) -> "ModuleDescriptor":
        return self._module.descriptor

    async def load_and_start(self) -> None:
        try:
            await asyncio.wait_for(
                self._module.load(), timeout=self._lifecycle_timeout_s
            )
            await asyncio.wait_for(
                self._module.start(), timeout=self._lifecycle_timeout_s
            )
        except Exception:
            logger.exception(
                "module %s failed to load/start; marking FAILED",
                self._module.descriptor.id,
            )
            self._module.mark_failed()

    async def shutdown(self) -> None:
        if self._module.state == ModuleState.ACTIVE:
            try:
                await asyncio.wait_for(
                    self._module.stop(), timeout=self._lifecycle_timeout_s
                )
            except Exception:
                logger.exception(
                    "module %s failed to stop; marking FAILED",
                    self._module.descriptor.id,
                )
                self._module.mark_failed()
                return
        if self._module.state == ModuleState.READY:
            try:
                await asyncio.wait_for(
                    self._module.unload(), timeout=self._lifecycle_timeout_s
                )
            except Exception:
                logger.exception(
                    "module %s failed to unload; marking FAILED",
                    self._module.descriptor.id,
                )
                self._module.mark_failed()

    def process(self, raw_bytes: bytes) -> Any:
        if self._module.state != ModuleState.ACTIVE:
            # state.value, not the enum: this string reaches the WS client
            # in a frame_error message, so it should carry the protocol's
            # own vocabulary ("failed") rather than a Python repr
            # ("ModuleState.FAILED").
            raise ModuleUnavailableError(
                f"module {self._module.descriptor.id} is "
                f"{self._module.state.value}, not ACTIVE"
            )
        try:
            return self._module.process(raw_bytes)
        except FrameProcessingError as exc:
            logger.warning(
                "module %s: frame-level failure, module stays ACTIVE: %s",
                self._module.descriptor.id,
                exc,
            )
            raise FrameSkippedError(
                f"module {self._module.descriptor.id} could not process this frame"
            ) from exc
        except Exception as exc:
            logger.exception(
                "module %s raised during process(); marking FAILED",
                self._module.descriptor.id,
            )
            self._module.mark_failed()
            raise ModuleUnavailableError(
                f"module {self._module.descriptor.id} failed while processing"
            ) from exc
