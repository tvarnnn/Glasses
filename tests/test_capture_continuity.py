"""A WiFi hiccup mid-walk must produce ONE continuous world.

`handoff.md` 9.3 states the shape plainly, and states it as the EXPECTED
case rather than an edge case:

    stream_start -> frames -> socket dies -> new socket -> ping/pong ->
    stream_start AGAIN -> frames CONTINUING FROM THE PREVIOUS seq

with no `stream_stop` in between, because a dropped socket produces none.

Before this work the consequence was measured and severe: the follower saw
its capture close, ended the mapping session, and the rest of the walk sat
in a second directory that nothing read. The world ended at the hiccup.

Two sessions would not have been an acceptable fix either. `build()` is
per session, and the result channel reports the newest session's keyframe
count -- so on the phone, which replaces `WorldSnapshot` wholesale and has
no merge layer, the count would visibly reset to zero at the moment of the
hiccup.
"""

import base64
import json

import numpy as np
import pytest

from tower.capture import (
    CAPTURE_FILENAME,
    END_REASON_DISCONNECT,
    END_REASON_STOP,
    CaptureFollower,
    CaptureRecorder,
)


def _jpeg(value: int = 128) -> bytes:
    import cv2

    ok, buffer = cv2.imencode(".jpg", np.full((64, 64, 3), value, dtype=np.uint8))
    assert ok
    return buffer.tobytes()


def _frame_payload() -> str:
    return base64.b64encode(_jpeg()).decode("ascii")


def _frame(seq: int, data: str) -> dict:
    return {
        "type": "frame",
        "seq": seq,
        "width": 64,
        "height": 64,
        "format": "jpeg",
        "data": data,
    }


def _manifest_of(recorder, capture_id) -> dict:
    path = recorder.capture_dir(capture_id) / CAPTURE_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


# -- the recorder side --------------------------------------------------


def test_a_disconnect_leaves_a_capture_that_a_successor_can_continue(tmp_path):
    recorder = CaptureRecorder(tmp_path)
    first = recorder.start(owner=object())
    recorder.write_frame(_jpeg(), source_seq=1)
    recorder.stop(END_REASON_DISCONNECT)

    assert recorder.resumable_capture() == first

    second = recorder.start(owner=object(), continues=recorder.resumable_capture())
    assert _manifest_of(recorder, second)["continues_capture"] == first


def test_a_polite_stop_is_not_resumable(tmp_path):
    """A stream_stop ends the walk deliberately. Only a drop leaves one open."""
    recorder = CaptureRecorder(tmp_path)
    recorder.start(owner=object())
    recorder.stop(END_REASON_STOP)
    assert recorder.resumable_capture() is None


def test_a_reconnect_after_the_grace_window_is_a_new_walk(tmp_path):
    """Past the point where iOS has stopped retrying, it is a different walk.

    handoff.md 6.4: iOS gives up after five attempts, roughly 45 s.
    """
    now = [1000.0]
    recorder = CaptureRecorder(tmp_path, clock=lambda: now[0])
    recorder.start(owner=object())
    recorder.stop(END_REASON_DISCONNECT)

    now[0] += 89.0
    assert recorder.resumable_capture() is not None
    now[0] += 2.0
    assert recorder.resumable_capture() is None


def test_a_new_recording_clears_the_resumable_capture(tmp_path):
    """A successor must not itself be offered as a predecessor twice."""
    recorder = CaptureRecorder(tmp_path)
    first = recorder.start(owner=object())
    recorder.stop(END_REASON_DISCONNECT)
    recorder.start(owner=object(), continues=first)
    assert recorder.resumable_capture() is None


# -- the follower side --------------------------------------------------


def test_the_follower_continues_into_a_successor(tmp_path):
    recorder = CaptureRecorder(tmp_path)
    first = recorder.start(owner=object())
    recorder.write_frame(_jpeg(10), source_seq=1)
    recorder.write_frame(_jpeg(20), source_seq=2)
    recorder.stop(END_REASON_DISCONNECT)

    second = recorder.start(owner=object(), continues=first)
    recorder.write_frame(_jpeg(30), source_seq=3)
    recorder.write_frame(_jpeg(40), source_seq=4)
    recorder.stop(END_REASON_STOP)

    follower = CaptureFollower(
        recorder.capture_dir(first), poll_seconds=0.001, sleep=lambda _s: None
    )
    seqs = [frame.source_seq for frame in follower.follow(max_idle_polls=3)]

    assert seqs == [1, 2, 3, 4], "the walk was cut at the reconnect"
    assert follower.directory.name == second


def test_the_follower_does_not_wait_after_a_polite_stop(tmp_path):
    """Waiting on every ordinary session would add a fixed delay for nothing."""
    slept = []
    recorder = CaptureRecorder(tmp_path)
    first = recorder.start(owner=object())
    recorder.write_frame(_jpeg(), source_seq=1)
    recorder.stop(END_REASON_STOP)

    follower = CaptureFollower(
        recorder.capture_dir(first),
        poll_seconds=0.001,
        sleep=lambda s: slept.append(s),
    )
    seqs = [frame.source_seq for frame in follower.follow(max_idle_polls=2)]

    assert seqs == [1]
    assert slept == [], "a cleanly stopped capture must end immediately"


def test_the_follower_gives_up_when_no_successor_arrives(tmp_path):
    """A phone that never comes back must not hang the follower forever."""
    recorder = CaptureRecorder(tmp_path)
    first = recorder.start(owner=object())
    recorder.write_frame(_jpeg(), source_seq=1)
    recorder.stop(END_REASON_DISCONNECT)

    follower = CaptureFollower(
        recorder.capture_dir(first),
        poll_seconds=0.001,
        sleep=lambda _s: None,
        resume_grace_seconds=0.01,
    )
    seqs = [frame.source_seq for frame in follower.follow(max_idle_polls=3)]
    assert seqs == [1]


def test_the_follower_ignores_an_unrelated_capture(tmp_path):
    """Only a capture that NAMES this one continues it."""
    recorder = CaptureRecorder(tmp_path)
    first = recorder.start(owner=object())
    recorder.write_frame(_jpeg(), source_seq=1)
    recorder.stop(END_REASON_DISCONNECT)

    # A different walk entirely, linking nothing.
    recorder.start(owner=object())
    recorder.write_frame(_jpeg(), source_seq=99)
    recorder.stop(END_REASON_STOP)

    follower = CaptureFollower(
        recorder.capture_dir(first),
        poll_seconds=0.001,
        sleep=lambda _s: None,
        resume_grace_seconds=0.01,
    )
    seqs = [frame.source_seq for frame in follower.follow(max_idle_polls=3)]
    assert seqs == [1], "an unrelated capture was mistaken for a continuation"


def test_following_reconnects_can_be_switched_off(tmp_path):
    recorder = CaptureRecorder(tmp_path)
    first = recorder.start(owner=object())
    recorder.write_frame(_jpeg(), source_seq=1)
    recorder.stop(END_REASON_DISCONNECT)
    recorder.start(owner=object(), continues=first)
    recorder.write_frame(_jpeg(), source_seq=2)
    recorder.stop(END_REASON_STOP)

    follower = CaptureFollower(
        recorder.capture_dir(first),
        poll_seconds=0.001,
        sleep=lambda _s: None,
        follow_reconnects=False,
    )
    seqs = [frame.source_seq for frame in follower.follow(max_idle_polls=3)]
    assert seqs == [1]


# -- over the real wire -------------------------------------------------


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from tower.main import create_app

    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(tmp_path / "capture"))
    return TestClient(create_app())


def test_a_reconnect_over_the_wire_produces_one_continuous_frame_stream(client):
    """The whole hiccup, driven through the real app.

    Note what iOS does NOT do here: it sends no stream_stop (the socket
    died), and seq CONTINUES rather than restarting -- handoff.md 9.3.
    """
    data = _frame_payload()
    recorder = client.app.state.frame_observers[0]

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "stream_start"})
        for seq in (1, 3, 5):
            ws.send_json(_frame(seq, data))
            ws.receive_json()
        first = recorder.status.capture_id

    # The socket dropped. No stream_stop was sent.
    assert recorder.status.end_reason == END_REASON_DISCONNECT

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "stream_start"})
        for seq in (7, 9, 11):
            ws.send_json(_frame(seq, data))
            ws.receive_json()
        second = recorder.status.capture_id
        ws.send_json({"type": "stream_stop"})

    assert second != first
    assert _manifest_of(recorder, second)["continues_capture"] == first

    follower = CaptureFollower(
        recorder.capture_dir(first), poll_seconds=0.001, sleep=lambda _s: None
    )
    seqs = [frame.wire_seq for frame in follower.follow(max_idle_polls=3)]
    assert seqs == [1, 3, 5, 7, 9, 11], (
        "the walk was not continuous across the reconnect"
    )
