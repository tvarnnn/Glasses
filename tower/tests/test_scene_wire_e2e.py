"""The Scene Understanding wire path, driven end to end through the real app.

This file exists because of one specific failure mode, and it is the one
an adversarial reviewer of a cartridge should look for first:

    `/cartridges` says the contract is offered, and the production path
    that would serve it does not connect.

Every hop here is production code. The app is `create_app()`. The frames
arrive as base64 JPEG over the real `/ws`, through the real frame handler,
after a real `frame_result`. The session is the one
`tower/cartridge_runtime.py` built. The payload is assembled by the real
adapter and delivered by the real hub through the real subscription.

**The one thing that is stubbed is the detector**, and only the detector:
`_scene_session` is replaced with one whose engine factory returns a stub.
Loading `ssdlite320` would download 13.4 MB of weights on a first run and
add 30 ms per frame to a suite that runs on every commit, and it would
test torchvision rather than this wire. What is under test is that a frame
entering `/ws` comes back out as counts on a subscription -- and every
line responsible for that is real.

`tests/test_object_detection_integration.py` is where the real weights are
exercised, opt-in behind `TOWER_RUN_MODEL_TESTS`.
"""

import base64
import io
import threading

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.result_channel_fixtures import pump
from tower.scene.records import BoundingBox, Detection

CONTRACT = "scene_understanding.live/2026-08-27"

_OPEN: list = []


class StubSceneEngine:
    """A SceneEngine that always sees the same room, without torch.

    Returns real `SceneState` objects built by the real `SceneEngine`
    machinery -- tracker, counts, relations -- because the payload's
    shape depends on those and a hand-built state would not exercise
    them.
    """

    def __init__(self, detections):
        from tower.scene.detect import FixedDetector
        from tower.scene.engine import SceneEngine
        from tower.scene.tracking import TrackerPolicy

        self._engine = SceneEngine(
            FixedDetector([detections] * 10_000),
            TrackerPolicy(min_iou=0.25, min_hits=1, max_misses=5),
        )
        self._detector = type("D", (), {"name": "stub-detector"})()

    def load(self):
        self._engine.load()

    def release(self):
        self._engine.release()

    def observe(self, frame, *, received_at=None):
        return self._engine.observe(frame, received_at=received_at)


TWO_PEOPLE_A_CHAIR_AND_A_LAPTOP = [
    Detection("person", 0.9, BoundingBox(20, 80, 120, 300)),
    Detection("person", 0.9, BoundingBox(150, 90, 250, 305)),
    Detection("chair", 0.8, BoundingBox(480, 200, 600, 330)),
    Detection("laptop", 0.8, BoundingBox(40, 200, 140, 260)),
]


@pytest.fixture(autouse=True)
def _close_clients():
    yield
    while _OPEN:
        _OPEN.pop().__exit__(None, None, None)


@pytest.fixture
def client(monkeypatch, tmp_path):
    """The real app, scene enabled, detector stubbed.

    `_scene_session` is patched rather than the settings, so
    `build_live_cartridges` still runs -- including the branch that
    decides whether to construct anything at all, which is itself part of
    what "the production path connects" means.
    """
    from tower import cartridge_runtime
    from tower.main import create_app
    from tower.scene.live import SceneLive

    monkeypatch.setenv("TOWER_SCENE_UNDERSTANDING", "true")
    monkeypatch.delenv("TOWER_WORLD_ROOT", raising=False)
    monkeypatch.delenv("TOWER_CAPTURE_ROOT", raising=False)
    monkeypatch.setattr(
        cartridge_runtime,
        "_scene_session",
        lambda settings: SceneLive(
            lambda: StubSceneEngine(TWO_PEOPLE_A_CHAIR_AND_A_LAPTOP)
        ),
    )
    made = TestClient(create_app())
    made.__enter__()
    _OPEN.append(made)
    made.app.state.result_hub._poll_seconds = 3600.0
    return made


def _jpeg(width=640, height=360) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 90)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _send_frames(ws, count: int, *, width=640, height=360) -> None:
    payload = _jpeg(width, height)
    for seq in range(count):
        ws.send_json(
            {
                "type": "frame",
                "seq": seq,
                "width": width,
                "height": height,
                "format": "jpeg",
                "data": payload,
            }
        )
        assert ws.receive_json()["type"] == "frame_result"


def _await_scene(client, timeout_polls: int = 200):
    """Poll the HTTP view until the worker has produced a scene.

    The worker is a real thread and the test is not synchronised with it,
    so something has to wait. Polling the public route rather than
    sleeping a fixed interval keeps the test honest on a slow machine and
    fast on a quick one.
    """
    for _ in range(timeout_polls):
        payload = client.get("/scene").json()
        if payload["scene_available"]:
            return payload
    raise AssertionError("the session never produced a scene")


class TestTheDeclarationMatchesWhatCanBeServed:
    def test_the_offer_is_available_when_the_cartridge_is_enabled(self, client):
        declaration = client.get("/cartridges").json()
        offer = next(
            entry
            for entry in declaration["cartridges"]
            if entry["cartridge"] == "scene_understanding"
        )

        assert offer["available"] is True
        assert offer["unavailable_reason"] is None
        assert offer["contract"] == CONTRACT
        assert offer["result_type"] == "live"
        assert offer["snapshot_only"] is True

    def test_what_is_offered_can_actually_be_subscribed_to(self, client):
        """The assertion this whole file exists for.

        An offer that cannot be subscribed to is worse than no offer: it
        tells a person to connect to something that is not there.
        """
        with client.websocket_connect("/ws") as ws:
            ws.send_json(
                {
                    "type": "result_subscribe",
                    "cartridge": "scene_understanding",
                    "result_type": "live",
                    "contract": CONTRACT,
                }
            )
            reply = ws.receive_json()
            assert reply["type"] == "result_subscribed"
            first = ws.receive_json()

        assert first["type"] == "cartridge_result"
        assert first["contract"] == CONTRACT
        assert first["seq"] == 1

    def test_a_contract_mismatch_is_refused_rather_than_downgraded(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json(
                {
                    "type": "result_subscribe",
                    "cartridge": "scene_understanding",
                    "result_type": "live",
                    "contract": "scene_understanding.live/1999-01-01",
                }
            )
            error = ws.receive_json()

        assert error["reason"] == "contract_mismatch"
        assert error["offered_contract"] == CONTRACT


class TestAFrameOnTheSocketBecomesCountsOnTheSubscription:
    def test_the_whole_path_connects(self, client):
        """Frame in over /ws, counts out over the subscription.

        Deliberately one test rather than three: the value is in the hops
        being joined, and three tests that each stubbed one hop would all
        pass on a path that does not connect.
        """
        client.post("/scene/start")
        with client.websocket_connect("/ws") as ws:
            _send_frames(ws, 4)
            scene = _await_scene(client)

            ws.send_json(
                {
                    "type": "result_subscribe",
                    "cartridge": "scene_understanding",
                    "result_type": "live",
                }
            )
            assert ws.receive_json()["type"] == "result_subscribed"
            first = ws.receive_json()

        payload = first["payload"]
        assert payload["scene_available"] is True
        assert payload["counts"]["person"] == 2
        assert payload["counts"]["chair"] == 1
        assert payload["counts"]["laptop"] == 1
        # And the HTTP view agrees with the socket, because both call the
        # same function.
        assert scene["counts"] == payload["counts"]

    def test_frames_arriving_before_start_are_counted_and_dropped(self, client):
        with client.websocket_connect("/ws") as ws:
            _send_frames(ws, 3)

        status = client.get("/scene").json()
        assert status["lifecycle"]["state"] == "stopped"
        assert status["frames_dropped_not_running"] == 3
        assert status["frames_observed"] == 0
        assert status["scene_available"] is False

    def test_stopping_discards_the_scene_on_every_surface(self, client):
        """Stop must be stop on the socket as well as on the route.

        A stale scene reaching a client through a channel the stop route
        did not think about is exactly how this cartridge would end up
        making a claim about a room the wearer has left.
        """
        client.post("/scene/start")
        with client.websocket_connect("/ws") as ws:
            _send_frames(ws, 4)
            _await_scene(client)

            ws.send_json(
                {
                    "type": "result_subscribe",
                    "cartridge": "scene_understanding",
                    "result_type": "live",
                }
            )
            assert ws.receive_json()["type"] == "result_subscribed"
            assert ws.receive_json()["payload"]["scene_available"] is True

            stopped = client.post("/scene/stop").json()
            pump(client)
            after = ws.receive_json()

        assert stopped["scene_available"] is False
        assert stopped["counts"] is None
        assert after["payload"]["scene_available"] is False
        assert after["payload"]["counts"] is None
        assert after["payload"]["lifecycle"]["state"] == "stopped"
        assert "discarded" in after["payload"]["scene_unavailable_reason"]

    def test_a_paused_session_keeps_its_counts_and_says_they_are_not_current(
        self, client
    ):
        client.post("/scene/start")
        with client.websocket_connect("/ws") as ws:
            _send_frames(ws, 4)
            _await_scene(client)

        paused = client.post("/scene/pause").json()

        assert paused["lifecycle"]["state"] == "paused"
        assert paused["lifecycle"]["scene_is_current"] is False
        assert paused["scene_available"] is True
        assert paused["counts"]["person"] == 2


class TestThePayloadSaysWhatItMayNotSay:
    @pytest.fixture
    def payload(self, client):
        client.post("/scene/start")
        with client.websocket_connect("/ws") as ws:
            _send_frames(ws, 4)
            _await_scene(client)
        return client.get("/scene").json()

    @pytest.mark.parametrize(
        "forbidden",
        ("track_id", "visible_eyes", "visible_ears", "x0", "\"box\"", "normalised_x",
         "view_offset", "in_front_of\":"),
    )
    def test_no_identifying_or_joinable_field_reaches_the_wire(
        self, payload, forbidden
    ):
        """Serialised and searched, not inspected key by key.

        A key-by-key check tests the keys somebody remembered. Searching
        the encoded payload catches one nested three levels down in a
        block added later, which is how this would actually go wrong.
        """
        import json

        encoded = json.dumps(payload)
        assert forbidden not in encoded, f"the payload leaked {forbidden!r}"

    def test_relations_are_unexpressible_not_merely_empty(self, payload):
        assert payload["relations"] is None
        assert payload["relations_absent_reason"]
        refused = {entry["relation"] for entry in payload["refused_relations"]}
        assert "in_front_of" in refused
        assert "behind" in refused

    def test_people_are_a_count_and_an_aggregate_never_a_list(self, payload):
        people = payload["people"]

        assert people["count"] == 2
        assert people["may_include_wearer"] is True
        assert people["validated"] is False
        # Never 0. Orientation was never measured, and zero is an answer.
        assert people["facing_wearer"] is None
        assert people["facing_answered"] is False
        assert "observation gap" in people["facing_unavailable_reason"]

    def test_position_is_reported_for_objects_and_refused_for_people(self, payload):
        assert "person" not in payload["where"]
        assert payload["where_excludes"] == ["person"]
        # Two objects placed on opposite sides of the frame by the
        # fixture, so the side counts are known independently of the code.
        assert payload["where"]["chair"]["right"] == 1
        assert payload["where"]["laptop"]["left"] == 1

    def test_every_count_declares_itself_a_lower_bound(self, payload):
        assert payload["count_is_lower_bound"] is True
        limitations = {entry["limitation"] for entry in payload["count_limitations"]}
        assert "size-floor" in limitations
        assert "recall" in limitations

    def test_every_reported_class_is_present_even_at_zero(self, payload):
        assert set(payload["counts"]) == set(payload["reported_classes"])
        assert payload["counts"]["bottle"] == 0

    def test_every_boolean_is_a_real_bool_not_an_int(self, payload):
        """`bool` subclasses `int`, and a 1 fails every Swift `as? Bool`."""
        for key in ("count_is_lower_bound", "scene_available"):
            assert type(payload[key]) is bool
        for key in ("may_include_wearer", "validated", "facing_answered"):
            assert type(payload["people"][key]) is bool
        for key in ("scene_is_current", "load_overdue"):
            assert type(payload["lifecycle"][key]) is bool

    def test_the_payload_stays_small_with_every_class_saturated(self, client):
        """Fixed arity is what keeps this bounded, so prove the arity.

        A scene with one of everything is the largest `counts` and
        `where` this contract can produce, because both are keyed on a
        fixed class list rather than on what is in the room.
        """
        import json

        from tower.results.scene_understanding import REPORTED_CLASSES

        detections = [
            Detection(label, 0.9, BoundingBox(10 + i * 3, 10, 60 + i * 3, 90))
            for i, label in enumerate(REPORTED_CLASSES)
        ]
        import numpy as np

        from tower.scene.live import SceneLive

        # Decode stubbed here and only here: this test drives the session
        # directly rather than through `/ws`, because what it measures is
        # the payload's ARITY, and pushing 13 classes through the socket
        # would test the socket again for no extra information.
        frame = np.zeros((360, 640, 3), np.uint8)
        session = SceneLive(
            lambda: StubSceneEngine(detections), decode=lambda raw: frame
        )
        client.app.state.live_cartridges.frame_consumers[0].stop()
        client.app.state.live_cartridges = type(
            client.app.state.live_cartridges
        )(frame_consumers=[session], scene=session, document=None)
        try:
            session.start()
            # `start()` returns while the worker is still STARTING, and a
            # frame offered then is correctly dropped. So this waits on
            # the observable state rather than assuming the thread has
            # got there -- the same reason `_await_scene` polls.
            deadline = threading.Event()
            timer = threading.Timer(10.0, deadline.set)
            timer.start()
            try:
                while not deadline.is_set() and session.latest()[0] is None:
                    session.offer_frame(b"x", received_at=1.0)
                    deadline.wait(0.005)
            finally:
                timer.cancel()
            assert session.latest()[0] is not None, "the session never observed"
            payload = client.get("/scene").json()
            encoded = json.dumps(payload)
            assert payload["counts"]["dining table"] == 1
            assert len(encoded) < 8000, f"the payload grew to {len(encoded)} bytes"
        finally:
            session.stop()


class TestTheSessionIsNotRunningUnlessSomebodySaidSo:
    def test_a_fresh_tower_observes_nothing(self, client):
        status = client.get("/scene").json()

        assert status["lifecycle"]["state"] == "stopped"
        assert status["frames_observed"] == 0
        assert status["scene_available"] is False
        assert "stopped" in status["scene_unavailable_reason"]

    def test_the_routes_are_absent_when_the_cartridge_is_off(
        self, monkeypatch, tmp_path
    ):
        """Off must mean 404 on the control surface, not a silent no-op.

        A POST that returns 200 and does nothing is how an operator ends
        up believing a physical test is running when it is not.
        """
        from tower.main import create_app

        monkeypatch.delenv("TOWER_SCENE_UNDERSTANDING", raising=False)
        monkeypatch.delenv("TOWER_WORLD_ROOT", raising=False)
        off = TestClient(create_app())
        off.__enter__()
        _OPEN.append(off)

        assert off.get("/scene").status_code == 404
        assert off.post("/scene/start").status_code == 404

        offer = next(
            entry
            for entry in off.get("/cartridges").json()["cartridges"]
            if entry["cartridge"] == "scene_understanding"
        )
        assert offer["available"] is False
        assert "TOWER_SCENE_UNDERSTANDING" in offer["unavailable_reason"]
