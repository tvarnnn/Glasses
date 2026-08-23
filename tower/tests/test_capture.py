"""Dataset-recording capture, and its integration with the live WS path."""

import json

import pytest
from starlette.testclient import TestClient

from tests import synthetic_scene as ss
from tower.main import create_app
from tower.capture import (
    END_REASON_BOUNDED_LIMIT,
    END_REASON_STOP,
    CaptureLimits,
    CaptureRecorder,
)

WIDTH, HEIGHT = 160, 120


@pytest.fixture
def jpeg():
    scene = ss.furnished_room()
    camera_matrix = ss.camera_matrix(WIDTH, HEIGHT)
    image = ss.render(scene, ss.strafe(1)[0], camera_matrix, WIDTH, HEIGHT)[0]
    return ss.encode_jpeg(image)


class TestCaptureRecorder:
    def test_nothing_is_written_before_start(self, tmp_path, jpeg):
        recorder = CaptureRecorder(tmp_path)

        assert not recorder.is_recording
        assert recorder.write_frame(jpeg, source_seq=1) is False
        assert not (tmp_path / "captures").exists()

    def test_frames_and_journal_are_written(self, tmp_path, jpeg):
        recorder = CaptureRecorder(tmp_path)
        capture_id = recorder.start()

        for seq in range(3):
            assert recorder.write_frame(jpeg, source_seq=seq, wire_seq=seq)
        status = recorder.stop()

        assert status.frames_written == 3
        assert status.end_reason == END_REASON_STOP
        records = recorder.read_frames(capture_id)
        assert [record["source_seq"] for record in records] == [0, 1, 2]
        for record in records:
            assert (recorder.capture_dir(capture_id) / record["relpath"]).exists()

    def test_time_basis_is_recorded_on_every_frame(self, tmp_path, jpeg):
        """There is no capture timestamp on the wire; say so per record."""
        recorder = CaptureRecorder(tmp_path)
        capture_id = recorder.start()
        recorder.write_frame(jpeg, source_seq=0)
        recorder.stop()

        record = recorder.read_frames(capture_id)[0]

        assert record["time_basis"] == "tower-receipt"

    def test_recording_stops_itself_at_the_byte_bound(self, tmp_path, jpeg):
        """Rule 15: no unbounded operation on the live path."""
        recorder = CaptureRecorder(
            tmp_path, limits=CaptureLimits(max_bytes=len(jpeg) * 2 + 1)
        )
        recorder.start()

        written = [recorder.write_frame(jpeg, source_seq=i) for i in range(5)]

        assert written[:2] == [True, True]
        assert written[2] is False
        assert not recorder.is_recording
        assert recorder.status.end_reason == END_REASON_BOUNDED_LIMIT

    def test_recording_stops_itself_at_the_time_bound(self, tmp_path, jpeg):
        # start() consumes one tick, then one per write_frame, then one
        # more inside the self-stop the bound triggers.
        ticks = iter([0.0, 0.0, 99.0, 99.0, 99.0])
        recorder = CaptureRecorder(
            tmp_path,
            limits=CaptureLimits(max_seconds=10.0),
            clock=lambda: next(ticks),
        )
        recorder.start()

        assert recorder.write_frame(jpeg, source_seq=0) is True
        assert recorder.write_frame(jpeg, source_seq=1) is False
        assert recorder.status.end_reason == END_REASON_BOUNDED_LIMIT

    def test_the_manifest_declares_the_privacy_posture(self, tmp_path, jpeg):
        recorder = CaptureRecorder(tmp_path)
        capture_id = recorder.start()
        recorder.write_frame(jpeg, source_seq=0)
        recorder.stop()

        manifest = json.loads(
            (recorder.capture_dir(capture_id) / "capture.json").read_text(
                encoding="utf-8"
            )
        )

        assert manifest["retains_raw_imagery"] is True
        assert manifest["redaction"] == "none"
        assert "dataset-recording" in manifest["privacy_tags"]

    def test_purge_removes_frames_journal_and_manifest(self, tmp_path, jpeg):
        recorder = CaptureRecorder(tmp_path)
        capture_id = recorder.start()
        recorder.write_frame(jpeg, source_seq=0)
        recorder.stop()

        removed, retained = recorder.purge(capture_id)

        assert removed > 0
        assert retained == 0
        assert not recorder.capture_dir(capture_id).exists()

    def test_purging_a_missing_capture_is_a_noop(self, tmp_path):
        assert CaptureRecorder(tmp_path).purge("nope") == (0, 0)

    def test_a_torn_journal_line_is_tolerated(self, tmp_path, jpeg):
        recorder = CaptureRecorder(tmp_path)
        capture_id = recorder.start()
        recorder.write_frame(jpeg, source_seq=0)
        recorder.stop()
        journal = recorder.capture_dir(capture_id) / "frames.jsonl"
        with journal.open("a", encoding="utf-8") as handle:
            handle.write('{"source_seq": 1, "trunc')

        assert len(recorder.read_frames(capture_id)) == 1


class TestWebSocketIntegration:
    """The hook must be invisible unless an operator switched it on."""

    def _frame_message(self, jpeg, seq):
        import base64

        return {
            "type": "frame",
            "seq": seq,
            "source_seq": seq,
            "width": WIDTH,
            "height": HEIGHT,
            "format": "jpeg",
            "data": base64.b64encode(jpeg).decode("ascii"),
        }

    def test_capture_is_off_by_default(self, jpeg):
        """The normal frame path must be unchanged when nothing is armed."""
        app = create_app()
        assert not getattr(app.state, "frame_observers", None)

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json(self._frame_message(jpeg, 1))
            reply = ws.receive_json()

        assert reply["type"] == "frame_result"

    def test_an_armed_recorder_captures_frames_between_stream_markers(
        self, tmp_path, jpeg
    ):
        app = create_app()
        recorder = CaptureRecorder(tmp_path)
        app.state.frame_observers = [recorder]

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "stream_start"})
            ws.send_json(self._frame_message(jpeg, 1))
            ws.receive_json()
            ws.send_json(self._frame_message(jpeg, 2))
            ws.receive_json()
            ws.send_json({"type": "stream_stop"})
            ws.send_json({"type": "ping"})
            ws.receive_json()

        status = recorder.status
        assert status is not None
        assert status.frames_written == 2
        assert not recorder.is_recording

    def test_frames_outside_a_stream_window_are_not_captured(
        self, tmp_path, jpeg
    ):
        app = create_app()
        recorder = CaptureRecorder(tmp_path)
        app.state.frame_observers = [recorder]

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json(self._frame_message(jpeg, 1))
            ws.receive_json()

        assert recorder.status is None

    def test_recording_stops_when_the_client_disconnects_abruptly(
        self, tmp_path, jpeg
    ):
        """A wearable disconnects abruptly as the NORMAL case.

        Without a stop in the endpoint's finally block, a recorder armed
        by one connection stays armed, and because the frame path gates
        only on is_recording, the NEXT connection's frames land in the
        previous connection's capture -- with no stream_start and no
        consent. That is incidental capture of someone else's imagery.
        """
        app = create_app()
        recorder = CaptureRecorder(tmp_path)
        app.state.frame_observers = [recorder]

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "stream_start"})
                ws.send_json(self._frame_message(jpeg, 1))
                ws.receive_json()
                # Leave without stream_stop, as a crash or drop would.

            assert not recorder.is_recording
            first_capture = recorder.status.capture_id
            frames_after_first = recorder.status.frames_written

            # A fresh connection sending frames without stream_start must
            # not be recorded at all.
            with client.websocket_connect("/ws") as ws:
                ws.send_json(self._frame_message(jpeg, 2))
                ws.receive_json()

        assert recorder.status.capture_id == first_capture
        assert recorder.status.frames_written == frames_after_first

    def test_a_failing_recorder_never_costs_the_client_its_result(
        self, tmp_path, jpeg
    ):
        """Recording is a side errand.

        A full disk or a permission error must not take a frame_result
        away from the client, and must not end the session.
        """

        class ExplodingRecorder(CaptureRecorder):
            @property
            def is_recording(self):
                return True

            def write_frame(self, *args, **kwargs):
                raise OSError("disk on fire")

        app = create_app()
        app.state.frame_observers = [ExplodingRecorder(tmp_path)]

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json(self._frame_message(jpeg, 1))
            reply = ws.receive_json()

        assert reply["type"] == "frame_result"
