from fastapi.testclient import TestClient

from tower.main import create_app


def test_ws_ping_returns_pong():
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "ping"})
        response = websocket.receive_json()

    assert response == {"type": "pong"}


def test_session_tracks_connection_and_disconnection():
    app = create_app()
    client = TestClient(app)

    assert app.state.session.is_client_connected() is False

    with client.websocket_connect("/ws"):
        assert app.state.session.is_client_connected() is True

    assert app.state.session.is_client_connected() is False


def test_session_counts_total_connections_and_disconnects_across_reconnects():
    app = create_app()
    client = TestClient(app)

    with client.websocket_connect("/ws"):
        pass
    with client.websocket_connect("/ws"):
        pass

    assert app.state.session.total_connections == 2
    assert app.state.session.total_disconnects == 2
