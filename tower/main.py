import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tower.config import get_settings
from tower.logging_config import configure_logging
from tower.modules.baseline_cv import BaselineCVModule
from tower.modules.container import ModuleContainer
from tower.routes import health, ws
from tower.session import ConnectionTracker


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await app.state.module_container.shutdown()


def create_app() -> FastAPI:
    configure_logging(get_settings())

    app = FastAPI(title="Glasses Tower", lifespan=lifespan)
    app.state.session = ConnectionTracker()
    app.state.module_container = ModuleContainer(BaselineCVModule())
    # Loaded/started here, synchronously, rather than in `lifespan` above:
    # TestClient(create_app()) used without `with client:` (how every
    # pre-existing test in this repo uses it) never runs ASGI lifespan
    # events, which would leave the module UNLOADED forever in tests.
    # Full rationale: docs/superpowers/specs/2026-08-19-v0.8-module-container-design.md,
    # "Wiring" section, Amendment.
    asyncio.run(app.state.module_container.load_and_start())
    app.include_router(health.router)
    app.include_router(ws.router)
    return app


app = create_app()
