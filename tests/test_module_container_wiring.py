from fastapi.testclient import TestClient

from tower.main import create_app
from tower.modules.base import ModuleState


def test_module_container_is_active_immediately_after_create_app():
    app = create_app()

    assert app.state.module_container.state == ModuleState.ACTIVE


def test_lifespan_shutdown_returns_module_to_unloaded():
    app = create_app()
    assert app.state.module_container.state == ModuleState.ACTIVE

    with TestClient(app) as client:
        # Entering the `with` block runs ASGI startup (a harmless no-op --
        # the module is already ACTIVE); ping confirms the app still serves
        # requests normally with the wiring in place.
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}

    # Exiting the `with TestClient(app) as client:` block runs ASGI
    # shutdown, which must have driven the module back to UNLOADED.
    assert app.state.module_container.state == ModuleState.UNLOADED
