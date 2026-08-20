import logging

from fastapi.testclient import TestClient

from tower.main import create_app


def test_malformed_non_json_text_does_not_close_connection(caplog):
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_text("not valid json{{{")
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    messages = [record.getMessage() for record in caplog.records]
    assert any("malformed" in m.lower() for m in messages), messages


def test_non_dict_json_does_not_close_connection(caplog):
    caplog.set_level(logging.WARNING, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(["not", "a", "dict"])
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    messages = [record.getMessage() for record in caplog.records]
    assert any("malformed" in m.lower() for m in messages), messages


def test_client_disconnect_during_receive_still_propagates(caplog):
    caplog.set_level(logging.INFO, logger="tower.routes.ws")
    client = TestClient(create_app())

    with client.websocket_connect("/ws"):
        pass

    messages = [record.getMessage() for record in caplog.records]
    assert any("disconnected" in m.lower() for m in messages), messages
