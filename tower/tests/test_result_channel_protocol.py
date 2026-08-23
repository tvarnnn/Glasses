"""The wire contract: discovery, subscription, ordering, cursors, errors.

Everything a fresh iOS client would have to get right, pinned so that
changing it is a deliberate act rather than a side effect.
"""

import json

import pytest

from tests.result_channel_fixtures import (
    build_world,
    drain,
    make_client,
    pump,
    subscribe,
)
from tower.results import registry
from tower.results.contracts import (
    ENVELOPE_CONTRACT,
    WORLD_BUILDER_STATUS_CONTRACT,
)


@pytest.fixture
def built(tmp_path):
    root = tmp_path / "worlds"
    world_id, session_id = build_world(root)
    return root, world_id, session_id


# -- discovery ----------------------------------------------------------


def test_http_and_websocket_declare_byte_identical_capabilities(monkeypatch, built):
    """Two surfaces onto one function, not two functions that agree today.

    iOS caches the declaration and compares contract identifiers for
    equality. If the socket and the route could drift, a client that
    cached one and validated against the other would decide the Tower had
    changed contract when nothing had.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    over_http = client.get("/cartridges").json()
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "cartridges"})
        over_ws = drain(ws, expect="cartridges")

    assert json.dumps(over_http, sort_keys=True) == json.dumps(
        over_ws, sort_keys=True
    )


def test_an_unconfigured_tower_still_offers_the_contract(monkeypatch):
    """IOS-to-Tower.md 0.1's third state, which must not collapse into the first.

    "the Tower offers a contract this build implements, but is
     unreachable -> connect"

    is a different instruction to a person than "not built yet". A Tower
    with no world root still knows how to speak the contract.
    """
    client = make_client(monkeypatch, None)
    declaration = client.get("/cartridges").json()
    offer = declaration["cartridges"][0]

    assert offer["contract"] == WORLD_BUILDER_STATUS_CONTRACT
    assert offer["available"] is False
    assert "world root" in offer["unavailable_reason"]


def test_cartridges_without_a_contract_are_not_offered(monkeypatch, built):
    """Presence in `not_offered` must never read as an offer."""
    root, _, _ = built
    client = make_client(monkeypatch, root)
    declaration = client.get("/cartridges").json()

    offered = {entry["cartridge"] for entry in declaration["cartridges"]}
    silent = {entry["cartridge"] for entry in declaration["not_offered"]}

    assert offered == {"world_builder"}
    assert silent == {"experimental_cv", "document_memory", "scene_understanding"}
    assert offered.isdisjoint(silent)
    for entry in declaration["not_offered"]:
        assert "contract" not in entry


def test_the_declaration_says_results_are_snapshots(monkeypatch, built):
    """IOS-to-Tower.md 1.3: a UI that assumes deltas draws a partial world
    as a complete one. So the mode is declared, not implied."""
    root, _, _ = built
    client = make_client(monkeypatch, root)
    offer = client.get("/cartridges").json()["cartridges"][0]
    assert offer["snapshot_only"] is True


# -- subscription and envelope -----------------------------------------


def test_a_subscription_begins_with_a_complete_snapshot(monkeypatch, built):
    root, world_id, session_id = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        reply = subscribe(ws)
        assert reply["type"] == "result_subscribed"
        assert reply["contract"] == WORLD_BUILDER_STATUS_CONTRACT

        envelope = drain(ws, expect="cartridge_result")

    assert envelope["seq"] == 1
    assert envelope["snapshot"] is True
    assert envelope["envelope_contract"] == ENVELOPE_CONTRACT
    assert envelope["time_basis"] == "tower-receipt"
    assert envelope["payload"]["world"]["world_id"] == world_id
    assert envelope["payload"]["session"]["session_id"] == session_id


def test_the_envelope_is_json_serialisable_and_bounded(monkeypatch, built):
    """A payload of fixed arity, so coalescing bounds bytes and not just count.

    The channel holds one snapshot per subscription. That is only a memory
    bound if a snapshot cannot itself be huge -- and this payload carries
    counts and states, never arrays of events, poses or points.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        envelope = drain(ws, expect="cartridge_result")

    encoded = json.dumps(envelope)
    assert json.loads(encoded) == envelope
    assert len(encoded) < 8000, f"snapshot grew to {len(encoded)} bytes"

    def _no_unbounded_lists(node, path="payload"):
        if isinstance(node, list):
            assert len(node) <= 16, f"{path} is an unbounded list"
            for item in node:
                _no_unbounded_lists(item, path)
        elif isinstance(node, dict):
            for key, value in node.items():
                _no_unbounded_lists(value, f"{path}.{key}")

    _no_unbounded_lists(envelope["payload"])


def test_seq_is_dense_per_subscription(monkeypatch, built):
    """Ordering is a dense per-subscription counter assigned at send time.

    Dense, not gapped: because every result is a complete snapshot, a
    client never needs a gap to tell it something was dropped. `coalesced`
    carries that instead, so a gap would only ever mean corruption.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        seqs = [drain(ws, expect="cartridge_result")["seq"]]
        for _ in range(3):
            pump(client)
            seqs.append(drain(ws, expect="cartridge_result")["seq"])

    assert seqs == [1, 2, 3, 4]


def test_revision_is_stable_while_nothing_changes(monkeypatch, built):
    """IOS-to-Tower.md 1.2: distinguish new data from repeated data.

    A finished world does not change, so its revision must not either --
    even though elapsed-time figures are re-sent by the heartbeat.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        first = drain(ws, expect="cartridge_result")
        pump(client)
        second = drain(ws, expect="cartridge_result")

    assert second["revision"] == first["revision"]
    assert second["revision_changed"] is False


def test_revision_changes_when_the_world_does(monkeypatch, tmp_path):
    root = tmp_path / "worlds"
    world_id, session_id = build_world(root, frames=8)
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        first = drain(ws, expect="cartridge_result")

        # A genuinely new session in the same world.
        build_world(root, frames=8, name="Second")
        pump(client)
        later = drain(ws, expect="cartridge_result")

    assert later["revision"] != first["revision"]
    assert later["revision_changed"] is True


def test_a_heartbeat_is_marked_as_not_a_change(monkeypatch, built):
    """Elapsed time advances without anything having happened.

    `mapping_seconds` is excluded from the revision so a live figure does
    not make every poll look like news, and the heartbeat that refreshes
    it says `revision_changed: false` so a client can skip the redraw.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        drain(ws, expect="cartridge_result")
        pump(client)
        beat = drain(ws, expect="cartridge_result")

    assert beat["revision_changed"] is False
    assert beat["payload"]["progress"]["mapping_seconds"] is not None


def test_an_unchanged_world_publishes_nothing_before_the_heartbeat(
    monkeypatch, built
):
    """The bandwidth half of the same rule.

    With no change and no heartbeat due, a poll pass must produce NO
    message at all. IOS-to-Tower.md 4.8 asks the Tower to coalesce before
    publishing; republishing an identical snapshot at poll rate is the
    thing that asks for.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        drain(ws, expect="cartridge_result")

        pump(client, times=5, heartbeat=3600.0)

        # Nothing was published, so a ping is answered immediately and
        # arrives before any result would have.
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


# -- reconnect and cursors ---------------------------------------------


def test_reconnect_always_yields_a_full_snapshot(monkeypatch, built):
    """The reconnect contract, and the reason a cursor cannot lose data.

    There is no delta stream to resume into, so there is no gap for a
    cursor to mis-handle. Every subscription starts complete, whatever
    the client claims to remember.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        first = drain(ws, expect="cartridge_result")

    with client.websocket_connect("/ws") as ws:
        reply = subscribe(ws, since_revision=first["revision"])
        again = drain(ws, expect="cartridge_result")

    assert reply["cursor_status"] == "matched"
    assert again["seq"] == 1
    assert again["payload"] == first["payload"]


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        (None, "absent"),
        ("deadbeefdeadbeef", "stale"),
        ("", "unrecognised"),
        (17, "unrecognised"),
    ],
)
def test_cursor_classification(monkeypatch, built, cursor, expected):
    """A stale or nonsense cursor is REPORTED, never an error.

    The reply is a complete snapshot either way, so refusing would deny a
    client correct data over a field that cannot affect correctness. What
    the status buys is the difference between "nothing changed while I was
    away" and "my cached revision is worthless".
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        overrides = {} if cursor is None else {"since_revision": cursor}
        reply = subscribe(ws, **overrides)
        envelope = drain(ws, expect="cartridge_result")

    assert reply["cursor_status"] == expected
    assert envelope["payload"]["world"] is not None


def test_a_duplicate_subscription_is_independent(monkeypatch, built):
    """Two subscriptions to the same target get their own ids and sequences.

    They must not share a slot: one client draining slowly cannot be
    allowed to consume another's snapshot.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        first = subscribe(ws)
        second = subscribe(ws)
        assert first["subscription_id"] != second["subscription_id"]

        seen = {}
        for _ in range(2):
            envelope = drain(ws, expect="cartridge_result")
            seen[envelope["subscription_id"]] = envelope["seq"]

    assert seen == {
        first["subscription_id"]: 1,
        second["subscription_id"]: 1,
    }


# -- errors -------------------------------------------------------------


def test_unknown_cartridge_is_refused_with_what_is_offered(monkeypatch, built):
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "result_subscribe",
                "cartridge": "scene_understanding",
                "result_type": "status",
            }
        )
        error = drain(ws, expect="result_error")

    assert error["reason"] == "unknown_cartridge"
    assert error["offered"] == ["world_builder"]


def test_unknown_result_type_is_distinct_from_unknown_cartridge(monkeypatch, built):
    """Two different problems, two different reasons.

    "this Tower has no such cartridge" and "that cartridge does not
    publish that" call for different client responses.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "result_subscribe",
                "cartridge": "world_builder",
                "result_type": "trajectory_stream",
            }
        )
        error = drain(ws, expect="result_error")

    assert error["reason"] == "unknown_result_type"


def test_a_contract_mismatch_is_refused_not_served(monkeypatch, built):
    """Equality, and nothing else.

    A mismatch is not "older" or "newer" -- identifiers are opaque. It
    means the two sides are not talking about the same agreement, and
    serving a payload the client would decode under different rules is
    the one outcome worse than refusing.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "result_subscribe",
                "cartridge": "world_builder",
                "result_type": "status",
                "contract": "world_builder.status/1999-01-01",
            }
        )
        error = drain(ws, expect="result_error")

    assert error["reason"] == "contract_mismatch"
    assert error["offered_contract"] == WORLD_BUILDER_STATUS_CONTRACT


def test_subscribing_to_an_unavailable_cartridge_is_refused(monkeypatch):
    client = make_client(monkeypatch, None)
    with client.websocket_connect("/ws") as ws:
        subscribe(ws)
        error = drain(ws, expect="result_error")

    assert error["reason"] == "cartridge_unavailable"


@pytest.mark.parametrize(
    "request_body",
    [
        {"type": "result_subscribe"},
        {"type": "result_subscribe", "cartridge": "world_builder"},
        {"type": "result_subscribe", "cartridge": 5, "result_type": "status"},
        {
            "type": "result_subscribe",
            "cartridge": "world_builder",
            "result_type": "status",
            "world_id": 42,
        },
        {
            "type": "result_subscribe",
            "cartridge": "world_builder",
            "result_type": "status",
            "session_id": ["a"],
        },
        {"type": "result_unsubscribe"},
        {"type": "result_unsubscribe", "subscription_id": 3},
    ],
)
def test_malformed_requests_are_refused_and_the_socket_survives(
    monkeypatch, built, request_body
):
    """A hostile or confused request must not end a connection.

    The same socket carries frames. A subscribe with a list where a string
    belongs cannot be allowed to take the frame path down with it.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        ws.send_json(request_body)
        error = drain(ws, expect="result_error")
        assert error["reason"] in ("malformed_request", "unknown_subscription")

        ws.send_json({"type": "ping"})
        assert drain(ws, expect="pong")["type"] == "pong"


def test_an_unknown_message_type_is_answered_not_ignored(monkeypatch, built):
    """IOS-to-Tower.md 2.2: iOS never lets a request silently no-op.

    Before this channel, an unrecognised message produced a server-side
    log line no client could see, so "not implemented" and "lost in
    flight" were indistinguishable from the phone.
    """
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "please_do_something_new"})
        error = drain(ws, expect="protocol_error")

    assert error["reason"] == "unknown_message_type"
    assert error["message_type"] == "please_do_something_new"


def test_unsubscribing_twice_reports_the_second_as_unknown(monkeypatch, built):
    root, _, _ = built
    client = make_client(monkeypatch, root)
    with client.websocket_connect("/ws") as ws:
        reply = subscribe(ws)
        drain(ws, expect="cartridge_result")
        sub_id = reply["subscription_id"]

        ws.send_json({"type": "result_unsubscribe", "subscription_id": sub_id})
        assert drain(ws, expect="result_unsubscribed")["subscription_id"] == sub_id

        ws.send_json({"type": "result_unsubscribe", "subscription_id": sub_id})
        assert drain(ws, expect="result_error")["reason"] == "unknown_subscription"


def test_the_registry_refuses_every_unoffered_pair(monkeypatch, built):
    """Guards the lookup itself, not just its use over the wire."""
    root, _, _ = built
    assert registry.find_offer(root, "world_builder", "status") is not None
    assert registry.find_offer(root, "world_builder", "geometry") is None
    assert registry.find_offer(root, "document_memory", "status") is None
    assert registry.find_offer(None, "world_builder", "status")["available"] is False
