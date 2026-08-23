"""Arming the dataset recorder in a real Tower process, and saying so.

Before this existed, `app.state.frame_observers` was populated only by
tests. Every physical-validation step the project has written down --
ChArUco calibration, the V0.9.3 acceptance-gate re-run, any World Builder
run on real footage -- begins "arm capture on the Tower", and that step
was not executable in a normal process. The gap was invisible because the
test suite armed the recorder by hand.

The privacy posture is unchanged and deliberately so: still off unless
explicitly configured, still armed only by `stream_start`, still bounded,
still stopped by any exit from the socket.
"""

import base64
import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tower.capture import CAPTURE_FILENAME, CaptureRecorder
from tower.config import get_settings
from tower.main import create_app

WIDTH, HEIGHT = 64, 48


@pytest.fixture
def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), (120, 90, 60)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _frame_message(jpeg: bytes, seq: int) -> dict:
    return {
        "type": "frame",
        "seq": seq,
        "source_seq": seq,
        "width": WIDTH,
        "height": HEIGHT,
        "format": "jpeg",
        "data": base64.b64encode(jpeg).decode("ascii"),
    }


@pytest.fixture(autouse=True)
def _clean_capture_env(monkeypatch):
    monkeypatch.delenv("TOWER_CAPTURE_ROOT", raising=False)


class TestSettings:
    def test_capture_root_is_unset_by_default(self):
        assert get_settings().capture_root is None

    def test_capture_root_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", "some/where")
        assert get_settings().capture_root == "some/where"

    def test_a_blank_capture_root_is_treated_as_unset(self, monkeypatch):
        """An empty env var is how a shell says "not set", not a path to "."."""
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", "   ")
        assert get_settings().capture_root is None


class TestArming:
    def test_no_observer_is_registered_without_configuration(self):
        app = create_app()
        assert not getattr(app.state, "frame_observers", None)

    def test_configuring_a_root_registers_exactly_one_recorder(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path))
        app = create_app()

        observers = app.state.frame_observers
        assert len(observers) == 1
        assert isinstance(observers[0], CaptureRecorder)

    def test_arming_does_not_start_recording(self, tmp_path, monkeypatch):
        """Configuration arms the recorder; only stream_start records.

        This is the whole privacy claim. If merely configuring a root
        began writing frames, capture would be incidental rather than an
        Explicit Dataset-Recording Session.
        """
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path))
        app = create_app()

        assert app.state.frame_observers[0].is_recording is False
        assert not list(tmp_path.rglob("*.jpg"))

    def test_a_frame_outside_stream_markers_is_not_recorded(
        self, tmp_path, monkeypatch, jpeg
    ):
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path))
        app = create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json(_frame_message(jpeg, 1))
            assert ws.receive_json()["type"] == "frame_result"

        assert not list(tmp_path.rglob("*.jpg"))

    def test_an_env_armed_recorder_captures_a_real_session(
        self, tmp_path, monkeypatch, jpeg
    ):
        """End to end: the documented physical procedure, minus the glasses."""
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path))
        app = create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "stream_start"})
            ws.send_json(_frame_message(jpeg, 1))
            ws.receive_json()
            ws.send_json(_frame_message(jpeg, 2))
            ws.receive_json()
            ws.send_json({"type": "stream_stop"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

        frames = sorted(tmp_path.rglob("*.jpg"))
        assert [path.name for path in frames] == ["00000001.jpg", "00000002.jpg"]
        assert frames[0].read_bytes() == jpeg

        manifests = list(tmp_path.rglob(CAPTURE_FILENAME))
        assert len(manifests) == 1


class TestHealthReportsCaptureState:
    """06-PRIVACY-DATA requires recording state to be clearly indicated.

    Until now it existed only in a server-side log line, which no client
    and no operator on another machine can see.
    """

    def test_capture_is_null_when_nothing_is_armed(self):
        with TestClient(create_app()) as client:
            body = client.get("/health").json()

        assert body["capture"] is None

    def test_armed_but_idle_reports_not_recording(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path))
        with TestClient(create_app()) as client:
            body = client.get("/health").json()

        assert body["capture"] == {
            "armed": True,
            "recording": False,
            "capture_id": None,
            "frames_written": 0,
            "bytes_written": 0,
        }

    def test_health_reports_recording_while_a_stream_is_open(
        self, tmp_path, monkeypatch, jpeg
    ):
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path))
        app = create_app()

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "stream_start"})
                ws.send_json(_frame_message(jpeg, 1))
                ws.receive_json()

                during = client.get("/health").json()["capture"]

                ws.send_json({"type": "stream_stop"})
                ws.send_json({"type": "ping"})
                ws.receive_json()

            after = client.get("/health").json()["capture"]

        assert during["recording"] is True
        assert during["capture_id"] is not None
        assert during["frames_written"] == 1
        assert during["bytes_written"] == len(jpeg)

        assert after["recording"] is False
        assert after["capture_id"] == during["capture_id"]
        assert after["frames_written"] == 1

    def test_health_survives_an_observer_that_cannot_report(self, monkeypatch):
        """A broken observer must not take /health down with it.

        /health is how an operator finds out the Tower is unwell. It is
        the one endpoint that must not depend on every subsystem being
        healthy.
        """

        class Hostile:
            @property
            def is_recording(self):
                raise RuntimeError("no")

        app = create_app()
        app.state.frame_observers = [Hostile()]

        with TestClient(app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["capture"] == {"armed": True, "error": "unavailable"}


class TestCaptureRootIsCreatedLazily:
    def test_configuring_a_missing_directory_does_not_create_it(
        self, tmp_path, monkeypatch
    ):
        """Arming must not leave a directory behind on a Tower that never records."""
        root = tmp_path / "not-yet"
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(root))
        create_app()

        assert not root.exists()

    def test_environment_root_may_be_relative(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TOWER_CAPTURE_ROOT", "data/capture")
        app = create_app()

        recorder = app.state.frame_observers[0]
        assert Path(os.fspath(recorder.capture_dir("x"))).is_absolute() is False
