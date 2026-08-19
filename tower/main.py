from fastapi import FastAPI

from tower.config import get_settings
from tower.logging_config import configure_logging
from tower.routes import health, ws
from tower.session import ConnectionTracker


def create_app() -> FastAPI:
    configure_logging(get_settings())

    app = FastAPI(title="Glasses Tower")
    app.state.session = ConnectionTracker()
    app.include_router(health.router)
    app.include_router(ws.router)
    return app


app = create_app()
