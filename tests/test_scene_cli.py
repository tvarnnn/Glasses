"""The driver, run as a user runs it.

There is deliberately **no `scene_query.py`**. The scene state is
ephemeral -- nothing is persisted -- so there would be nothing for a
separate query process to read. The questions are answered by the run
that observed the frames, which is the honest shape for a cartridge whose
whole claim is to describe *now*.

`--detector none` throughout, except where the real detector is the
point: these tests are about the driver, and a suite that downloaded
model weights would fail on a train.
"""

import json
import subprocess
import sys

import pytest

from tower.capture import CaptureRecorder


def _run(*args):
    return subprocess.run(
        [sys.executable, "scripts/scene_session.py", *args],
        capture_output=True,
        text=True,
    )


class TestArguments:
    def test_help_exits_zero(self):
        assert _run("--help").returncode == 0

    def test_it_requires_exactly_one_frame_source(self, tmp_path):
        assert _run().returncode != 0
        assert _run("--synthetic", "--frames", str(tmp_path)).returncode != 0

    def test_a_missing_capture_directory_exits_nonzero(self, tmp_path):
        assert _run("--follow-capture", str(tmp_path / "absent")).returncode != 0

    def test_an_empty_frame_directory_exits_nonzero(self, tmp_path):
        assert _run("--frames", str(tmp_path)).returncode != 0


class TestSyntheticRun:
    @pytest.fixture(scope="class")
    @staticmethod
    def report():
        result = _run(
            "--synthetic",
            "--synthetic-frames",
            "8",
            "--detector",
            "none",
            "--format",
            "json",
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def test_it_observes_every_frame(self, report):
        assert report["frames_observed"] == 8

    def test_it_persists_nothing(self, report):
        """The design's strongest privacy property, asserted rather than
        assumed."""
        assert report["persisted"] is False

    def test_orientation_is_off_by_default(self, report):
        assert report["orientation_enabled"] is False

    def test_the_facing_question_is_refused_rather_than_answered_zero(
        self, report
    ):
        answer = report["answers"]["facing_wearer"]

        assert answer["answered"] is False
        assert answer["value"] is None
        assert "never measured" in answer["reason"]

    def test_the_scene_declares_its_frame_of_reference(self, report):
        assert report["scene"]["frame_of_reference"] == "camera"

    def test_the_scene_lists_what_it_refuses_to_assert(self, report):
        """A refusal a consumer can see is worth more than a silent gap."""
        refused = set(report["scene"]["refused_relationships"])

        assert {"on", "inside", "near", "in_front_of", "behind"} <= refused


class TestTextOutputIsHonest:
    def test_it_says_nothing_is_persisted(self):
        result = _run("--synthetic", "--synthetic-frames", "4", "--detector", "none")

        assert "NOTHING PERSISTED" in result.stdout

    def test_it_says_positions_are_camera_relative(self):
        result = _run("--synthetic", "--synthetic-frames", "4", "--detector", "none")

        assert "CAMERA-RELATIVE" in result.stdout

    def test_it_labels_a_synthetic_run_as_synthetic(self):
        result = _run("--synthetic", "--synthetic-frames", "4", "--detector", "none")

        assert "SYNTHETIC, NOT PHYSICAL" in result.stdout

    def test_it_says_counts_come_from_tracks(self):
        result = _run("--synthetic", "--synthetic-frames", "4", "--detector", "none")

        assert "CONFIRMED TRACKS, not detections" in result.stdout


class TestFollowingACapture:
    """The live path, reusing the follower the World Builder closeout built."""

    @staticmethod
    def _write_capture(root, count=8):
        from tests import synthetic_scene as ss

        clock = [1000.0]

        def clock_fn():
            clock[0] += 0.3
            return clock[0]

        recorder = CaptureRecorder(root, clock=clock_fn)
        capture_id = recorder.start()
        scene = ss.furnished_room()
        poses = ss.strafe(count, step=0.05)
        images = ss.render_sequence(
            scene, poses, ss.camera_matrix(640, 360), 640, 360
        )
        for index, image in enumerate(images):
            recorder.write_frame(
                ss.encode_jpeg(image), source_seq=index, wire_seq=index
            )
        recorder.stop()
        return recorder.capture_dir(capture_id)

    def test_a_recorded_capture_is_observed_frame_by_frame(self, tmp_path):
        directory = self._write_capture(tmp_path / "capture", count=8)

        result = _run(
            "--follow-capture",
            str(directory),
            "--detector",
            "none",
            "--format",
            "json",
        )

        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["frame_source"] == "live-capture"
        assert report["frames_observed"] == 8

    def test_it_writes_nothing_into_the_capture_directory(self, tmp_path):
        """A live-state cartridge must not leave anything behind."""
        directory = self._write_capture(tmp_path / "capture", count=6)
        before = sorted(path.name for path in directory.rglob("*"))

        _run("--follow-capture", str(directory), "--detector", "none")

        assert sorted(path.name for path in directory.rglob("*")) == before


class TestWithTheRealDetector:
    """Opt-in: downloads COCO weights on first run."""

    pytestmark = pytest.mark.skipif(
        __import__("os").environ.get("TOWER_RUN_MODEL_TESTS") != "1",
        reason="opt-in: needs torchvision COCO weights; "
        "set TOWER_RUN_MODEL_TESTS=1",
    )

    def test_a_rendered_room_yields_no_detections_rather_than_hallucinations(
        self,
    ):
        """The synthetic room contains no COCO object.

        Detecting nothing is the correct answer, and the only one this
        host can check -- there is no imagery of people anywhere on it.
        """
        result = _run(
            "--synthetic", "--synthetic-frames", "6", "--format", "json"
        )

        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["detector"] == "ssdlite320"
        assert report["scene"]["counts"] == {}
