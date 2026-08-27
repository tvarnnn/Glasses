"""Shared setup for the CV Lab tests.

A module rather than a `conftest.py` for the same reason
`result_channel_fixtures.py` is one: these are helpers, not fixtures, and
the two files that want them import them by name. `tests/__init__.py`
already makes `tests` a package.

Nothing here sleeps. A start hands its load to a background task, so the
tests await that task through `CVLab.wait_until_armed()` -- which is what
it exists for. A test that slept would be a test that passes on a fast
machine.
"""

import asyncio
import base64
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tower.cv_lab import CVLab
from tower.main import create_app

_CLIENTS: list[TestClient] = []


@pytest.fixture(autouse=True)
def _close_cv_lab_clients():
    """Exit every TestClient this module opened, in reverse order.

    Must be imported by name into each consuming test module for it to
    run. A TestClient left open holds the app's portal thread and, with
    it, whatever background task an unfinished arm is sitting in.
    """
    yield
    while _CLIENTS:
        client = _CLIENTS.pop()
        try:
            client.__exit__(None, None, None)
        except Exception:
            pass


def jpeg_bytes(width: int = 64, height: int = 64, *, textured: bool = False) -> bytes:
    """A decodable frame. Textured when an experiment needs something to find."""
    if textured:
        rng = np.random.default_rng(7)
        array = rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)
        image = Image.fromarray(array)
    else:
        image = Image.new("RGB", (width, height), color=(90, 90, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def jpeg_message(seq: int, width: int = 64, height: int = 64, **kwargs) -> dict:
    return {
        "type": "frame",
        "seq": seq,
        "width": width,
        "height": height,
        "format": "jpeg",
        "data": base64.b64encode(jpeg_bytes(width, height, **kwargs)).decode("ascii"),
    }


def make_lab(experiment_id: str = "baseline", **kwargs) -> CVLab:
    return CVLab(experiment_id, **kwargs)


async def armed_lab(experiment_id: str = "baseline", **kwargs) -> CVLab:
    lab = make_lab(experiment_id, **kwargs)
    await lab.load_initial()
    return lab


async def start_and_wait(lab: CVLab, experiment_id: str):
    """Start an experiment and await the arm. Returns the command outcome."""
    outcome = lab.start(experiment_id)
    await lab.wait_until_armed()
    return outcome


def make_client(monkeypatch, experiment: str = "baseline") -> TestClient:
    """A Tower with a CV Lab, its lifespan running and its hub timer off.

    `TOWER_CV_EXPERIMENT` is set BEFORE `create_app()`, because the Lab's
    startup default is read there. The hub's poll interval is pushed to an
    hour so that nothing polls on wall-clock: every test that needs a
    snapshot drives `poll_once` explicitly through `pump`.
    """
    monkeypatch.setenv("TOWER_CV_EXPERIMENT", experiment)
    client = TestClient(create_app())
    client.__enter__()
    _CLIENTS.append(client)
    client.app.state.result_hub._poll_seconds = 3600.0
    return client


def pump(client: TestClient, times: int = 1, heartbeat: float = 0.0) -> None:
    """Run N complete hub poll passes on the app's own event loop."""
    hub = client.app.state.result_hub
    hub._heartbeat_seconds = heartbeat

    async def _run():
        for _ in range(times):
            await hub.poll_once()

    client.portal.call(_run)


def drain(ws, expect: str, limit: int = 16) -> dict:
    """The next message of a given type, skipping others.

    Blocks deliberately rather than timing out: a test that gave up after
    a while would be a test that flakes on a busy machine, and this
    repository already has a machine busy enough to prove it.
    """
    for _ in range(limit):
        message = ws.receive_json()
        if message.get("type") == expect:
            return message
    raise AssertionError(f"never saw a {expect!r} in {limit} messages")


def command(ws, message: dict, expect: str = "cv_lab_status") -> dict:
    ws.send_json(message)
    return drain(ws, expect)


def frame(ws, seq: int, **kwargs) -> dict:
    ws.send_json(jpeg_message(seq, **kwargs))
    return ws.receive_json()


def run_async(coroutine):
    return asyncio.run(coroutine)
