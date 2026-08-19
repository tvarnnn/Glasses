import asyncio
import io

from PIL import Image

from tower.frame_processing import process_frame
from tower.modules.base import ModuleState
from tower.modules.baseline_cv import BaselineCVModule


def _jpeg_bytes(width: int, height: int, color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_descriptor_declares_no_persistence_or_transmission():
    module = BaselineCVModule()

    behavior = module.descriptor.data_behavior
    assert behavior.persists_data is False
    assert behavior.retains_raw_imagery is False
    assert behavior.supports_purge is False
    assert behavior.transmits_externally is False


def test_process_after_load_and_start_matches_process_frame_directly():
    module = BaselineCVModule()
    asyncio.run(module.load())
    asyncio.run(module.start())

    raw_bytes = _jpeg_bytes(32, 32, (255, 255, 255))

    result = module.process(raw_bytes)
    direct = process_frame(raw_bytes)

    assert result.mean_intensity == direct.mean_intensity
    assert result.processing_ms >= 0


def test_full_lifecycle_reaches_unloaded():
    module = BaselineCVModule()
    asyncio.run(module.load())
    asyncio.run(module.start())
    asyncio.run(module.stop())
    asyncio.run(module.unload())

    assert module.state == ModuleState.UNLOADED
