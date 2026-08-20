import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tower.config import Settings, get_settings
from tower.logging_config import configure_logging
from tower.modules.base import Module
from tower.modules.container import ModuleContainer
from tower.modules.experimental_cv import ExperimentalCVModule
from tower.routes import health, ws
from tower.session import ConnectionTracker


def _build_cv_module(settings: Settings) -> Module:
    if settings.cv_experiment == "depth":
        from tower.modules.depth_cv import DepthEstimationModule

        return DepthEstimationModule(settings.cv_device)
    return ExperimentalCVModule(settings.cv_experiment)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await app.state.module_container.shutdown()


def create_app() -> FastAPI:
    configure_logging(get_settings())

    app = FastAPI(title="Glasses Tower", lifespan=lifespan)
    app.state.session = ConnectionTracker()
    app.state.module_container = ModuleContainer(_build_cv_module(get_settings()))
    # Started here, not in `lifespan` above: TestClient(create_app()) used
    # without `with client:` (every pre-existing test in this repo) never
    # runs ASGI lifespan events, leaving the module UNLOADED forever. See
    # docs/superpowers/specs/2026-08-19-v0.8-module-container-design.md, "Wiring" Amendment.
    asyncio.run(app.state.module_container.load_and_start())
    app.include_router(health.router)
    app.include_router(ws.router)
    return app


app = create_app()
