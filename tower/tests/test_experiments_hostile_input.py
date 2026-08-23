"""Frames that are valid, useless, and used to kill the module.

Every case here came out of adversarial review, and every one of them was
reachable from the wire.

The severity is what makes this file worth its length. `ModuleContainer`
treats any exception that is not a `FrameProcessingError` as a MODULE
failure; `mark_failed()` is terminal, because FAILED can never transition
back to UNLOADED; and the container is built once at process start with
no swap path. So one bad frame does not drop one frame -- it ends CV
processing for every subsequent frame of every subsequent session, for
the life of the server process.

Two of these are reachable through the live WebSocket path, which is what
makes them worth this much test. `tower/frames.py` validates a frame with
`Image.open(...).size`, which parses the JPEG **header**:

- a 1x64 JPEG is not malformed at all, merely useless, and passes every
  check the transport makes. It then kills ORB;
- a real JPEG truncated to 800 bytes passes PIL and still decodes to
  `None` in OpenCV. Measured: at 400 bytes PIL rejects it too, at 800 it
  does not.

The rest -- empty payloads, garbage -- are not reachable from the wire
today, but any other caller of `Experiment.run()` (a script, a future
direct integration) gets no such gate, and the contract each experiment's
code visibly relies on should be self-sufficient rather than borrowed.
"""

import base64
import io

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tower.experiments import EXPERIMENTS, ExperimentSettings
from tower.main import create_app
from tower.modules.base import FrameProcessingError, ModuleState

CHEAP = (
    "baseline",
    "edge_detection",
    "frame_quality",
    "feature_detection",
    "redaction_impact",
    "optical_flow",
)


def _jpeg(width: int, height: int) -> bytes:
    rng = np.random.default_rng(1)
    array = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    ok, buffer = cv2.imencode(".jpg", array)
    assert ok
    return buffer.tobytes()


def _truncated_jpeg() -> bytes:
    """A real JPEG cut short: PIL opens it, OpenCV cannot decode it.

    800 bytes is chosen from measurement, not taste -- at 400 PIL rejects
    it too, so a shorter cut would test the transport rather than the
    experiment.
    """
    return _jpeg(160, 120)[:800]


HOSTILE = {
    "empty": b"",
    "garbage": b"not a jpeg at all",
    "truncated": _truncated_jpeg(),
    "1x1": _jpeg(1, 1),
    "1x64": _jpeg(1, 64),
    "64x1": _jpeg(64, 1),
    "1x1000": _jpeg(1, 1000),
    "1000x1": _jpeg(1000, 1),
    "2x2": _jpeg(2, 2),
    "3x600": _jpeg(3, 600),
}


class TestNoInputTakesTheModuleDown:
    @pytest.mark.parametrize("name", CHEAP)
    @pytest.mark.parametrize("label", sorted(HOSTILE))
    def test_a_hostile_frame_is_a_frame_level_failure_or_a_result(
        self, name, label
    ):
        """Either it works or it raises FrameProcessingError. Nothing else.

        Anything else marks the module FAILED permanently.
        """
        experiment = EXPERIMENTS[name]()
        experiment.load(ExperimentSettings())

        try:
            result = experiment.run(HOSTILE[label])
        except FrameProcessingError:
            return
        assert result.result_label

    @pytest.mark.parametrize("label", sorted(HOSTILE))
    def test_a_hostile_frame_never_leaves_a_non_finite_number(self, label):
        """A NaN or Infinity reaches the client as invalid JSON.

        `json.dumps` writes bare `NaN`, which a strict parser rejects --
        so a divide-by-zero deep in a metric becomes a broken client.
        """
        import math

        for name in CHEAP:
            experiment = EXPERIMENTS[name]()
            experiment.load(ExperimentSettings())
            try:
                result = experiment.run(HOSTILE[label])
            except FrameProcessingError:
                continue
            values = dict(result.metrics)
            values["result_value"] = result.result_value
            bad = {k: v for k, v in values.items() if not math.isfinite(v)}
            assert not bad, f"{name}/{label}: {bad}"


class TestTheModuleSurvivesOverTheWire:
    """The end-to-end version, because that is where it actually bit."""

    @staticmethod
    def _message(payload: bytes, seq: int, width: int, height: int) -> dict:
        return {
            "type": "frame",
            "seq": seq,
            "width": width,
            "height": height,
            "format": "jpeg",
            "data": base64.b64encode(payload).decode("ascii"),
        }

    def test_a_one_pixel_frame_does_not_end_the_session(self, monkeypatch):
        monkeypatch.setenv("TOWER_CV_EXPERIMENT", "feature_detection")
        app = create_app()
        good = _jpeg(64, 64)

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json(self._message(good, 1, 64, 64))
            assert ws.receive_json()["type"] == "frame_result"

            ws.send_json(self._message(_jpeg(1, 64), 2, 1, 64))
            hostile = ws.receive_json()

            ws.send_json(self._message(good, 3, 64, 64))
            after = ws.receive_json()

            # Checked INSIDE the `with`: leaving it runs ASGI shutdown,
            # which unloads the module, so the same assertion placed after
            # would read UNLOADED and fail for entirely the wrong reason.
            assert app.state.module_container.state == ModuleState.ACTIVE

        assert hostile["type"] == "frame_error"
        assert hostile["reason"] == "frame_skipped", (
            "a degenerate frame must be a SKIPPED FRAME, not a dead module"
        )
        assert after["type"] == "frame_result", (
            "the module must still be ACTIVE after a hostile frame"
        )

    def test_a_thin_frame_does_not_end_the_session_for_redaction_impact(
        self, monkeypatch
    ):
        monkeypatch.setenv("TOWER_CV_EXPERIMENT", "redaction_impact")
        app = create_app()
        good = _jpeg(64, 64)

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json(self._message(_jpeg(1000, 1), 1, 1000, 1))
            ws.receive_json()
            ws.send_json(self._message(good, 2, 64, 64))
            after = ws.receive_json()
            assert app.state.module_container.state == ModuleState.ACTIVE

        assert after["type"] == "frame_result"


class TestOpticalFlowRefusesAStaleReference:
    """A frame from minutes ago is not a reference to anything.

    The module is process-scoped, so without this the first frame of a new
    wearer session is diffed against the last frame of the previous one
    and reported with `has_reference: 1.0`.
    """

    @staticmethod
    def _experiment(clock):
        experiment = EXPERIMENTS["optical_flow"]()
        experiment._clock = clock
        experiment.load(ExperimentSettings())
        return experiment

    def test_a_gap_beyond_the_window_drops_the_reference(self):
        now = [100.0]
        experiment = self._experiment(lambda: now[0])
        frame = _jpeg(160, 120)

        experiment.run(frame)
        now[0] += 60.0
        after_gap = experiment.run(frame)

        assert after_gap.metrics["reference_stale"] == 1.0
        assert after_gap.metrics["has_reference"] == 0.0
        assert after_gap.result_value == 0.0
        assert after_gap.metrics["seconds_since_reference"] == 60.0

    def test_a_normal_frame_interval_keeps_the_reference(self):
        """300 ms is the delivered interval. It must not trip the guard."""
        now = [100.0]
        experiment = self._experiment(lambda: now[0])
        frame = _jpeg(160, 120)

        experiment.run(frame)
        now[0] += 0.3
        after = experiment.run(frame)

        assert after.metrics["reference_stale"] == 0.0
        assert after.metrics["has_reference"] == 1.0

    def test_the_first_frame_reports_an_unknown_age_not_a_zero_one(self):
        """Zero seconds since a reference that does not exist would be a lie."""
        experiment = self._experiment(lambda: 5.0)

        first = experiment.run(_jpeg(160, 120))

        assert first.metrics["has_reference"] == 0.0
        assert first.metrics["seconds_since_reference"] == -1.0

    def test_recovery_is_immediate_after_a_stale_gap(self):
        now = [0.0]
        experiment = self._experiment(lambda: now[0])
        frame = _jpeg(160, 120)

        experiment.run(frame)
        now[0] += 30.0
        experiment.run(frame)
        now[0] += 0.2
        recovered = experiment.run(frame)

        assert recovered.metrics["has_reference"] == 1.0
        assert recovered.metrics["reference_stale"] == 0.0


class TestForwardBackwardErrorIsInformative:
    def test_it_is_measured_over_attempted_tracks_not_survivors(self):
        """Measured over survivors it can never exceed its own filter.

        `kept = ok & (fb_error <= 1.0)`, so a median over `kept` is
        bounded by 1.0 by construction and would read "excellent" on every
        frame however badly the tracking went. The honest denominator is
        every track LK claimed to have followed.
        """
        from tests import synthetic_scene as ss
        from tower.experiments.optical_flow import MAX_FORWARD_BACKWARD_PX

        scene = ss.furnished_room()
        # A deliberately violent 1.2 m step. Tracking largely fails, which
        # is the whole point: a quality metric that cannot report failure
        # is not a quality metric.
        poses = ss.strafe(2, step=1.2)
        assert ss.poses_outside_room(poses) == []
        images = ss.render_sequence(scene, poses, ss.camera_matrix(320, 240), 320, 240)
        frames = [ss.encode_jpeg(image) for image in images]

        experiment = EXPERIMENTS["optical_flow"]()
        experiment.load(ExperimentSettings())
        experiment.run(frames[0])
        metrics = experiment.run(frames[1]).metrics

        assert metrics["rejected_by_forward_backward"] > 0, (
            "this pair must actually defeat the tracker"
        )
        # The point of the fix: the reported value is free to exceed the
        # filter. Measured here at ~70 px against a 1.0 px filter. Under
        # the old computation -- a median over the survivors of that same
        # filter -- it was bounded by 1.0 and read 'excellent'.
        assert metrics["median_forward_backward_px"] > MAX_FORWARD_BACKWARD_PX, (
            "measured over survivors this is bounded by the filter itself; "
            "it must be measured over attempted tracks"
        )

    def test_a_clean_pair_still_reports_a_small_error(self):
        """The metric must stay informative in the good case too."""
        from tests import synthetic_scene as ss

        scene = ss.furnished_room()
        poses = ss.strafe(2, step=0.12)
        images = ss.render_sequence(scene, poses, ss.camera_matrix(320, 240), 320, 240)
        frames = [ss.encode_jpeg(image) for image in images]

        experiment = EXPERIMENTS["optical_flow"]()
        experiment.load(ExperimentSettings())
        experiment.run(frames[0])
        metrics = experiment.run(frames[1]).metrics

        assert metrics["median_forward_backward_px"] < 1.0
        assert metrics["tracked_fraction"] > 0.5


class TestPillowAcceptsWhatOpenCvRejects:
    def test_the_transport_gate_is_not_a_substitute_for_the_guard(self):
        """Why every experiment must guard even though frames.py validates.

        PIL parses the JPEG header; OpenCV decodes the whole file. A real
        JPEG truncated to 800 bytes passes the first and fails the second,
        so the transport's check does not make undecodable input
        unreachable -- it only narrows which undecodable input arrives.
        """
        truncated = _truncated_jpeg()

        opened = Image.open(io.BytesIO(truncated))
        assert opened.size == (160, 120), "PIL must accept it"

        array = np.frombuffer(truncated, dtype=np.uint8)
        assert cv2.imdecode(array, cv2.IMREAD_COLOR) is None, (
            "OpenCV must reject it -- if this ever changes, the guard is "
            "no longer load-bearing and this test should say so"
        )

    def test_a_shorter_truncation_is_caught_by_the_transport_instead(self):
        """The boundary, so the 800 in _truncated_jpeg is not a magic number."""
        with pytest.raises(OSError):
            Image.open(io.BytesIO(_jpeg(160, 120)[:400]))
