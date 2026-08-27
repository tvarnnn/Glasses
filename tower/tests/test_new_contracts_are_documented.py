"""Every key these two cartridges put on a wire must be written down.

`test_every_payload_key_is_documented` already holds this for World
Builder, and its docstring gives the reason: "a key on the wire that the
document never names is a key a consumer has to guess at."

That test walks one envelope, from one subscription, on one cartridge. It
could not see the other two, so extending the property to them is a
separate file rather than a parameter -- these payloads need their own
fixtures (a live session, a written store) and folding them into the
existing test would have made a small deterministic test depend on a
worker thread.

The bar is deliberately mechanical: every dict key, at every depth, in
every state the payload has. It catches the case that actually happens --
a block added later, three levels down, that nobody remembered to write
up -- rather than the case a human reviewer would catch anyway.

`docs/contracts/CARTRIDGE-RESULTS.md` is read by the relative path the
existing drift test uses, so pytest's rootdir must be `tower/`. It
already is; `pyproject.toml` sets it.
"""

import base64
import io
import json
import pathlib
import threading

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests import document_fixtures as fx
from tests.test_documents_wire_e2e import _write_one_document
from tests.test_scene_wire_e2e import (
    TWO_PEOPLE_A_CHAIR_AND_A_LAPTOP,
    StubSceneEngine,
)

DOCUMENT = pathlib.Path("docs/contracts/CARTRIDGE-RESULTS.md")

_OPEN: list = []


@pytest.fixture(autouse=True)
def _close_clients():
    yield
    while _OPEN:
        _OPEN.pop().__exit__(None, None, None)


def _undocumented(payload, document: str) -> list:
    missing = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in document:
                    missing.append(f"{path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(payload)
    return missing


@pytest.fixture
def contract_document() -> str:
    return DOCUMENT.read_text(encoding="utf-8")


class TestTheSceneContractIsWrittenDown:
    @pytest.fixture
    def client(self, monkeypatch):
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

    def test_the_stopped_payload_is_fully_documented(
        self, client, contract_document
    ):
        payload = client.get("/scene").json()
        assert _undocumented(payload, contract_document) == []

    def test_the_running_payload_is_fully_documented(
        self, client, contract_document
    ):
        """The state with the most keys, so the one most likely to drift."""
        client.post("/scene/start")
        buffer = io.BytesIO()
        Image.new("RGB", (640, 360), (30, 60, 90)).save(buffer, format="JPEG")
        data = base64.b64encode(buffer.getvalue()).decode("ascii")
        with client.websocket_connect("/ws") as ws:
            for seq in range(4):
                ws.send_json(
                    {
                        "type": "frame",
                        "seq": seq,
                        "width": 640,
                        "height": 360,
                        "format": "jpeg",
                        "data": data,
                    }
                )
                assert ws.receive_json()["type"] == "frame_result"
            for _ in range(400):
                payload = client.get("/scene").json()
                if payload["scene_available"]:
                    break

        assert payload["scene_available"] is True
        assert _undocumented(payload, contract_document) == []

    def test_the_contract_identifier_and_the_vocabulary_are_documented(
        self, client, contract_document
    ):
        payload = client.get("/scene").json()

        assert payload["contract"] in contract_document
        for state in payload["lifecycle"]["states"]:
            assert state in contract_document
        for label in payload["reported_classes"]:
            # A class a consumer could see in `counts` and could not look
            # up is a label it has to guess the meaning of.
            assert label in contract_document, label


class TestTheDocumentContractsAreWrittenDown:
    def _client(self, monkeypatch, root, *, capture=False):
        from tower import cartridge_runtime
        from tower.document_memory.live import DocumentLive
        from tower.main import create_app

        monkeypatch.delenv("TOWER_WORLD_ROOT", raising=False)
        monkeypatch.delenv("TOWER_CAPTURE_ROOT", raising=False)
        monkeypatch.delenv("TOWER_SCENE_UNDERSTANDING", raising=False)
        monkeypatch.setenv("TOWER_DOCUMENT_ROOT", str(root))
        monkeypatch.setenv("TOWER_DOCUMENT_CAPTURE", "true" if capture else "false")
        if capture:
            from tower.document_memory.ocr import FixedTextRecogniser
            from tower.document_memory.dwell import DwellPolicy

            monkeypatch.setattr(
                cartridge_runtime,
                "_document_session",
                lambda settings: DocumentLive(
                    settings.document_root,
                    policy=DwellPolicy(min_frames=3, min_seconds=0.6),
                    recogniser_factory=lambda: FixedTextRecogniser(
                        pages=[fx.page_regions(fx.TRANSFORMER_PAPER)]
                    ),
                ),
            )
        made = TestClient(create_app())
        made.__enter__()
        _OPEN.append(made)
        made.app.state.result_hub._poll_seconds = 3600.0
        return made

    def test_the_listing_is_fully_documented(
        self, monkeypatch, tmp_path, contract_document
    ):
        _write_one_document(tmp_path)
        client = self._client(monkeypatch, tmp_path)

        assert _undocumented(client.get("/documents").json(), contract_document) == []

    def test_one_document_is_fully_documented(
        self, monkeypatch, tmp_path, contract_document
    ):
        """The largest payload this cartridge produces, and the only one
        carrying text."""
        _write_one_document(tmp_path)
        client = self._client(monkeypatch, tmp_path)
        document_id = client.get("/documents").json()["documents"][0]["document_id"]

        payload = client.get(f"/documents/{document_id}").json()

        assert _undocumented(payload, contract_document) == []

    def test_a_search_result_is_fully_documented(
        self, monkeypatch, tmp_path, contract_document
    ):
        _write_one_document(tmp_path)
        client = self._client(monkeypatch, tmp_path)

        payload = client.get("/documents/search", params={"text": "the"}).json()

        assert _undocumented(payload, contract_document) == []

    def test_the_session_status_on_the_channel_is_fully_documented(
        self, monkeypatch, tmp_path, contract_document
    ):
        client = self._client(monkeypatch, tmp_path, capture=True)
        client.post("/documents-session/start")
        deadline = threading.Event()
        timer = threading.Timer(15.0, deadline.set)
        timer.start()
        try:
            while not deadline.is_set():
                if client.get("/documents-session").json()["session"]["state"] == "running":
                    break
                deadline.wait(0.005)
        finally:
            timer.cancel()

        with client.websocket_connect("/ws") as ws:
            ws.send_json(
                {
                    "type": "result_subscribe",
                    "cartridge": "document_memory",
                    "result_type": "status",
                }
            )
            assert ws.receive_json()["type"] == "result_subscribed"
            envelope = ws.receive_json()

        assert _undocumented(envelope, contract_document) == []

    def test_the_answer_vocabulary_is_documented(
        self, monkeypatch, tmp_path, contract_document
    ):
        client = self._client(monkeypatch, tmp_path)
        payload = client.get("/documents").json()

        assert payload["contract"] in contract_document
        for answer in payload["answers"]:
            assert answer in contract_document, answer
        for kind in payload["retrieval_kinds"]:
            assert kind in contract_document, kind


def test_nothing_on_these_wires_is_a_bare_int_pretending_to_be_a_bool(
    monkeypatch, tmp_path
):
    """`bool` subclasses `int`, and a `1` fails every Swift `as? Bool`.

    Checked by walking the real serialised payloads rather than by
    inspecting the fields somebody remembered, because the failure mode
    is a comparison or a `len()` landing in a field that reads as a flag.
    """
    _write_one_document(tmp_path)
    from tower.main import create_app

    monkeypatch.delenv("TOWER_WORLD_ROOT", raising=False)
    monkeypatch.setenv("TOWER_DOCUMENT_ROOT", str(tmp_path))
    client = TestClient(create_app())
    client.__enter__()
    _OPEN.append(client)

    payload = client.get("/documents").json()
    encoded = json.dumps(payload)

    # Round-tripping through JSON is what a client sees; a numpy bool or a
    # bare int would survive as a number and this finds it.
    suspicious = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, int) and not isinstance(node, bool):
            name = path.rsplit(".", 1)[-1]
            if name.startswith(("is_", "has_", "can_")) or name.endswith(
                ("_available", "_validated", "_derived", "_is_model_output")
            ):
                suspicious.append(f"{path} = {node!r}")

    walk(payload)
    assert suspicious == [], f"integers in boolean-shaped fields: {suspicious}"
    assert '"true"' not in encoded and '"false"' not in encoded
