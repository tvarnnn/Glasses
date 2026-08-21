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
    assert "client disconnected" in messages


def test_state_runtimeerror_propagates_instead_of_spinning(monkeypatch):
    """A RuntimeError from receive_json must END the connection, not loop.

    Starlette raises RuntimeError synchronously (no await point) when the
    socket is in an invalid state -- 'not connected', or 'receive() after
    disconnect'. Swallowing that and `continue`-ing would spin the loop at
    full CPU with no opportunity for the event loop to cancel it, hanging
    the worker rather than just the connection (Rule 15: no tight retry
    loops). This test pins that only payload errors are swallowed.
    """
    from starlette.websockets import WebSocket

    calls = {"count": 0}
    real_receive_json = WebSocket.receive_json

    async def fake_receive_json(self, mode="text"):
        calls["count"] += 1
        if calls["count"] > 50:
            raise AssertionError("busy loop: receive_json retried after RuntimeError")
        raise RuntimeError('Cannot call "receive" once a disconnect message has been received.')

    monkeypatch.setattr(WebSocket, "receive_json", fake_receive_json)
    client = TestClient(create_app())

    try:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "ping"})
            websocket.receive_json()
    except Exception:
        pass  # the endpoint is expected to terminate, one way or another
    finally:
        monkeypatch.setattr(WebSocket, "receive_json", real_receive_json)

    assert calls["count"] == 1, f"expected exactly one attempt, got {calls['count']}"
