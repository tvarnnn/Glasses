import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tower.capture import CaptureRecorder
from tower.config import Settings, get_settings
from tower.experiments import ExperimentSettings
from tower.logging_config import configure_logging
from tower.modules.base import Module
from tower.modules.container import ModuleContainer
from tower.modules.experimental_cv import ExperimentalCVModule
from tower.results import build_hub
from tower.routes import cartridges, health, ws
from tower.session import ConnectionTracker


def _build_cv_module(settings: Settings) -> Module:
    """The one module slot.

    There used to be a branch here selecting a different Module subclass
    for the depth experiment, because that experiment holds a model.
    Experiment state now lives behind the Experiment protocol, so the
    module is the same one whichever experiment is selected -- which is
    what the module doc always said: one Lab slot, many experiments.
    """
    return ExperimentalCVModule(
        settings.cv_experiment,
        ExperimentSettings(device=settings.cv_device),
    )


def _build_frame_observers(settings: Settings) -> list:
    """Register the dataset recorder, or nothing at all.

    A LIST because ws.py reads a list -- more than one consumer may
    eventually want raw frames, and a singleton would force the second
    one to displace the first.

    Arming is not recording. A configured root creates no directory and
    writes no byte until a `stream_start` arrives, so this stays an
    Explicit Dataset-Recording Session under 06-PRIVACY-DATA.md rather
    than becoming incidental capture. Unset by default, which is why
    every Tower that has ever run recorded nothing.
    """
    if settings.capture_root is None:
        return []
    return [CaptureRecorder(settings.capture_root)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # The result hub first: it holds a polling task, and stopping it
    # before the module container means no snapshot can be built against
    # an app that is half torn down. Guarded with getattr because most of
    # this repo's tests construct the app without running lifespan at all
    # (see the comment in create_app).
    hub = getattr(app.state, "result_hub", None)
    if hub is not None:
        await hub.shutdown()
    await app.state.module_container.shutdown()


def create_app() -> FastAPI:
    configure_logging(get_settings())

    app = FastAPI(title="Glasses Tower", lifespan=lifespan)
    app.state.session = ConnectionTracker()
    settings = get_settings()
    app.state.module_container = ModuleContainer(_build_cv_module(settings))
    app.state.frame_observers = _build_frame_observers(settings)
    # Read-only, and read by the result channel alone. The web process
    # never builds a world; world_build_session.py does, in its own
    # process, and this is only where to look for what it wrote.
    app.state.world_root = settings.world_root
    # One shared reader for the whole app. It starts no task until a
    # client subscribes and stops again when the last one goes, so a Tower
    # nobody is watching does no polling and no disk IO on its behalf.
    app.state.result_hub = build_hub(settings.world_root)
    # Started here, not in `lifespan` above: TestClient(create_app()) used
    # without `with client:` (every pre-existing test in this repo) never
    # runs ASGI lifespan events, leaving the module UNLOADED forever. See
    # docs/superpowers/specs/2026-08-19-v0.8-module-container-design.md, "Wiring" Amendment.
    asyncio.run(app.state.module_container.load_and_start())
    app.include_router(health.router)
    app.include_router(cartridges.router)
    app.include_router(ws.router)
    return app


app = create_app()
