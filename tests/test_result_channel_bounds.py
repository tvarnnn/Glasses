"""Resources, slow consumers, cleanup, and failure containment.

The properties that decide whether this channel is safe to leave running,
as opposed to whether it produces the right JSON.
"""

import asyncio

import pytest

from tests.result_channel_fixtures import (  # noqa: F401
    _close_result_channel_clients,
    build_world,
    drain,
    make_client,
    pump,
    subscribe,
)
from tower.results.publisher import (
    MAX_SUBSCRIPTIONS_PER_CONNECTION,
    ConnectionChannel,
    ResultHub,
    Subscription,
)
from tower.results.envelope import Snapshot


@pytest.fixture(scope="module")
def world_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("worlds")
    build_world(root, frames=10)
    return root


def _snapshot(revision: str) -> Snapshot:
    return Snapshot(payload={"revision_marker": revision}, revision=revision)


def _subscription() -> Subscription:
    return Subscription(
        subscription_id="sub-1",
        cartridge="world_builder",
        result_type="status",
        contract="c",
        world_id=None,
        session_id=None,
        cursor_status=None,
    )


# -- bounded memory -----------------------------------------------------


def test_a_subscription_holds_exactly_one_snapshot_however_many_arrive():
    """There is no queue, and this is what that means concretely.

    A hundred snapshots offered to a subscriber that never reads leave ONE
    in memory. A bounded queue of N would have held N -- and, worse, would
    have had to choose between dropping the newest (discarding the only
    snapshot that matters) and dropping the oldest (a slower coalesce at
    N times the memory).
    """
    subscription = _subscription()
    for index in range(100):
        subscription.offer(_snapshot(f"rev-{index}"))

    assert subscription._pending.revision == "rev-99"
    assert subscription.coalesced == 99

    taken = subscription.take()
    assert taken.revision == "rev-99"
    assert subscription._pending is None
    assert subscription.has_pending is False


def test_an_identical_snapshot_is_not_counted_as_a_supersession():
    """`coalesced` must mean "you missed intermediate states".

    Re-offering the same revision is not an intermediate state, and
    counting it would report drops that never happened.
    """
    subscription = _subscription()
    subscription.offer(_snapshot("same"))
    subscription.offer(_snapshot("same"))
    subscription.offer(_snapshot("same"))

    assert subscription.coalesced == 0


def test_coalescing_is_reported_to_the_client(world_root, monkeypatch):
    """A slow consumer learns it was slow, without a gap in the sequence.

    Every poll pass runs before the sender task gets a turn, because they
    are driven inside one portal call. So the client sees one message
    carrying the newest state plus the count it skipped.
    """
    client = make_client(monkeypatch, world_root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        first = drain(ws, expect="cartridge_result")
        assert first["coalesced"] == 0

        channel = client.app.state.result_hub

        async def _flood():
            hub = channel
            for index in range(20):
                for connection in list(hub._channels):
                    for subscription in connection._subscriptions.values():
                        subscription.offer(_snapshot(f"flood-{index}"))
                    connection._wakeup.set()

        client.portal.call(_flood)
        latest = drain(ws, expect="cartridge_result")

    assert latest["revision"] == "flood-19"
    assert latest["coalesced"] == 19
    assert latest["seq"] == 2, "the sequence stays dense; coalescing is not a gap"


def test_a_connection_cannot_open_unbounded_subscriptions(world_root, monkeypatch):
    """A remote party must not be able to grow a server-side dict at will."""
    client = make_client(monkeypatch, world_root)
    request = {
        "type": "result_subscribe",
        "cartridge": "world_builder",
        "result_type": "status",
    }
    with client.websocket_connect("/ws") as ws:
        for _ in range(MAX_SUBSCRIPTIONS_PER_CONNECTION):
            ws.send_json(request)
        ws.send_json(request)

        # Each accepted subscribe produces an acknowledgement AND a
        # snapshot, and the refusal is one more message; read them all
        # and classify, rather than assuming an interleaving that nothing
        # guarantees.
        seen = [
            ws.receive_json()
            for _ in range(2 * MAX_SUBSCRIPTIONS_PER_CONNECTION + 1)
        ]

    accepted = [m for m in seen if m["type"] == "result_subscribed"]
    refused = [m for m in seen if m["type"] == "result_error"]

    assert len(accepted) == MAX_SUBSCRIPTIONS_PER_CONNECTION
    assert len(refused) == 1
    assert refused[0]["reason"] == "too_many_subscriptions"


# -- slow consumers -----------------------------------------------------


def test_a_consumer_that_never_reads_is_dropped_not_waited_on():
    """The bound that protects the FRAME path.

    One socket is one TCP stream, so a client that stops reading blocks
    everything on it. A result send that waited indefinitely would be the
    thing holding the frame path up.
    """
    hub = ResultHub(lambda *args: _snapshot("x"), clock=lambda: 0.0)
    started = asyncio.Event()

    async def _never_returns(_payload):
        started.set()
        await asyncio.Event().wait()

    async def _run():
        import tower.results.publisher as publisher

        original = publisher.SEND_TIMEOUT_S
        publisher.SEND_TIMEOUT_S = 0.05
        try:
            channel = ConnectionChannel(hub, _never_returns, lambda: 0.0)
            subscription = _subscription()
            await channel.add(subscription)
            subscription.offer(_snapshot("first"))
            channel._wakeup.set()
            await asyncio.wait_for(started.wait(), timeout=2.0)
            # Long enough for the 50 ms send timeout to fire and the
            # subscription to be closed.
            for _ in range(60):
                await asyncio.sleep(0.01)
                if channel.subscription_count == 0:
                    break
            return channel.subscription_count
        finally:
            publisher.SEND_TIMEOUT_S = original
            await channel.close()

    assert asyncio.run(_run()) == 0


# -- cleanup ------------------------------------------------------------


def test_disconnect_removes_every_subscription_and_stops_the_reader(
    world_root, monkeypatch
):
    """A subscription that outlived its socket would keep polling disk forever."""
    client = make_client(monkeypatch, world_root)
    hub = client.app.state.result_hub

    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        drain(ws, expect="cartridge_result")
        assert client.portal.call(_channel_count(hub)) == 1

    assert client.portal.call(_channel_count(hub)) == 0
    assert client.portal.call(_task_alive(hub)) is False


def test_unsubscribing_the_last_subscription_stops_the_reader(
    world_root, monkeypatch
):
    """A Tower nobody is watching must do no disk IO on anyone's behalf."""
    client = make_client(monkeypatch, world_root)
    hub = client.app.state.result_hub

    with client.websocket_connect("/ws") as ws:
        reply = subscribe(ws)
        drain(ws, expect="cartridge_result")
        assert client.portal.call(_task_alive(hub)) is True

        ws.send_json(
            {
                "type": "result_unsubscribe",
                "subscription_id": reply["subscription_id"],
            }
        )
        drain(ws, expect="result_unsubscribed")

        assert client.portal.call(_channel_count(hub)) == 0
        assert client.portal.call(_task_alive(hub)) is False


def _channel_count(hub):
    async def _call():
        return len(hub._channels)

    return _call


def _task_alive(hub):
    async def _call():
        return hub._task is not None and not hub._task.done()

    return _call


# -- failure containment ------------------------------------------------


def test_a_reader_failure_reaches_the_client_instead_of_going_quiet():
    """The worst outcome is silence, so it is the one that is ruled out.

    A dead reader that still looks alive leaves a client waiting forever
    for a channel that is never coming back. The failure travels as a
    VALUE in the subscription slot, so no swallow clause anywhere can eat
    it on the way out.
    """
    def _explode(*args):
        raise RuntimeError("the disk fell over")

    hub = ResultHub(_explode, clock=lambda: 0.0, poll_seconds=0.001)
    sent = []

    async def _capture(payload):
        sent.append(payload)

    async def _run():
        channel = ConnectionChannel(hub, _capture, lambda: 0.0)
        await channel.add(_subscription())
        # poll_once swallows a per-target failure; the loop-level failure
        # is what fail_all responds to, so drive that directly.
        try:
            raise RuntimeError("the disk fell over")
        except RuntimeError as exc:
            channel.fail_all(f"reader stopped with {type(exc).__name__}")
        for _ in range(50):
            await asyncio.sleep(0.01)
            if sent:
                break
        await channel.close()
        return sent

    messages = asyncio.run(_run())
    assert messages, "the client was never told the channel had died"
    assert messages[0]["reason"] == "channel_failed"
    assert "RuntimeError" in messages[0]["message"]


def test_one_unreadable_target_does_not_stop_the_others():
    """A poll pass must not be all-or-nothing across subscribers."""
    calls = []

    def _snapshot_for(cartridge, result_type, world_id, session_id):
        calls.append(world_id)
        if world_id == "broken":
            raise ValueError("unreadable")
        return _snapshot("fine")

    hub = ResultHub(_snapshot_for, clock=lambda: 0.0)
    delivered = []

    async def _capture(payload):
        delivered.append(payload)

    async def _run():
        channel = ConnectionChannel(hub, _capture, lambda: 0.0)
        for index, world in enumerate(("broken", "healthy")):
            subscription = Subscription(
                subscription_id=f"sub-{index}",
                cartridge="world_builder",
                result_type="status",
                contract="c",
                world_id=world,
                session_id=None,
                cursor_status=None,
            )
            await channel.add(subscription)
        await hub.poll_once()
        for _ in range(50):
            await asyncio.sleep(0.01)
            if delivered:
                break
        await channel.close()
        return delivered

    messages = asyncio.run(_run())
    assert "broken" in calls and "healthy" in calls
    assert [m["payload"]["revision_marker"] for m in messages] == ["fine"]


def test_hub_shutdown_survives_a_reader_that_already_died():
    """Shutdown must not re-raise a dead task's exception.

    That would turn a dead push channel into a failed application
    shutdown -- a small problem escalating into a visible one.
    """
    def _explode(*args):
        raise RuntimeError("boom")

    hub = ResultHub(_explode, clock=lambda: 0.0, poll_seconds=0.001)

    async def _run():
        channel = ConnectionChannel(hub, _noop_send, lambda: 0.0)
        await channel.add(_subscription())
        for _ in range(50):
            await asyncio.sleep(0.01)
            if hub._task is not None and hub._task.done():
                break
        await hub.shutdown()
        await channel.close()

    asyncio.run(_run())


async def _noop_send(_payload):
    return None
