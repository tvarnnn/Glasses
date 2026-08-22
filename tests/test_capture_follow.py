"""Reading a capture journal while it is still being written.

The recorder already fsyncs each image BEFORE appending its journal line,
so a journal line always points at a complete file. That ordering is what
makes tailing safe, and it is what this follower depends on -- without it
a reader could hand a consumer a half-written JPEG.

Shared infrastructure, not World Builder's. Any cartridge that wants to
process a dataset session as it is recorded reads it the same way.
"""

import io

import pytest
from PIL import Image

from tower.capture import CaptureFollower, CaptureRecorder

WIDTH, HEIGHT = 48, 32


def _jpeg(shade: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), (shade, shade, shade)).save(
        buffer, format="JPEG"
    )
    return buffer.getvalue()


@pytest.fixture
def recorder(tmp_path) -> CaptureRecorder:
    return CaptureRecorder(tmp_path)


def _write(recorder: CaptureRecorder, seq: int) -> bytes:
    payload = _jpeg(30 + seq)
    recorder.write_frame(
        payload,
        source_seq=seq,
        wire_seq=seq,
        tx_seq=seq,
        width=WIDTH,
        height=HEIGHT,
    )
    return payload


class TestFollowingAFinishedCapture:
    def test_every_frame_is_yielded_in_order(self, recorder):
        capture_id = recorder.start()
        payloads = [_write(recorder, seq) for seq in range(3)]
        recorder.stop()

        follower = CaptureFollower(recorder.capture_dir(capture_id))
        frames = list(follower.follow())

        assert [frame.source_seq for frame in frames] == [0, 1, 2]
        assert [frame.raw_bytes for frame in frames] == payloads

    def test_frame_metadata_survives_the_journal(self, recorder):
        capture_id = recorder.start()
        _write(recorder, 7)
        recorder.stop()

        frame = next(iter(CaptureFollower(recorder.capture_dir(capture_id)).follow()))

        assert frame.source_seq == 7
        assert frame.wire_seq == 7
        assert frame.tx_seq == 7
        assert frame.width == WIDTH
        assert frame.height == HEIGHT
        assert isinstance(frame.received_at, float)

    def test_a_closed_capture_terminates_rather_than_polling_forever(self, recorder):
        capture_id = recorder.start()
        _write(recorder, 0)
        recorder.stop()

        polls = []

        def sleep(seconds):
            polls.append(seconds)

        list(
            CaptureFollower(
                recorder.capture_dir(capture_id), sleep=sleep
            ).follow()
        )

        assert polls == [], "a finished capture must need no sleep at all"


class TestFollowingALiveCapture:
    def test_frames_written_during_the_follow_are_picked_up(self, recorder):
        """The live case, made deterministic by writing from the sleep hook."""
        capture_id = recorder.start()
        _write(recorder, 0)

        remaining = [1, 2]

        def sleep(_seconds):
            if remaining:
                _write(recorder, remaining.pop(0))
            else:
                recorder.stop()

        frames = list(
            CaptureFollower(recorder.capture_dir(capture_id), sleep=sleep).follow()
        )

        assert [frame.source_seq for frame in frames] == [0, 1, 2]

    def test_a_frame_appended_after_the_stop_manifest_is_still_yielded(
        self, recorder
    ):
        """The one real race, closed by a final re-read.

        The recorder appends the journal line and only later rewrites the
        manifest. A follower that stopped the instant it saw `ended_at`
        would drop whatever landed in between.
        """
        capture_id = recorder.start()
        _write(recorder, 0)

        state = {"stopped": False}

        def sleep(_seconds):
            if not state["stopped"]:
                _write(recorder, 1)
                recorder.stop()
                state["stopped"] = True

        frames = list(
            CaptureFollower(recorder.capture_dir(capture_id), sleep=sleep).follow()
        )

        assert [frame.source_seq for frame in frames] == [0, 1]

    def test_max_polls_bounds_a_capture_that_never_closes(self, recorder):
        """Rule 15: no unbounded wait. A crashed recorder must not hang a reader."""
        capture_id = recorder.start()
        _write(recorder, 0)

        slept = []
        frames = list(
            CaptureFollower(
                recorder.capture_dir(capture_id), sleep=slept.append
            ).follow(max_idle_polls=3)
        )

        assert [frame.source_seq for frame in frames] == [0]
        assert len(slept) == 3

    def test_a_new_frame_resets_the_idle_budget(self, recorder):
        capture_id = recorder.start()
        _write(recorder, 0)
        produced = [1, 2, 3, 4]

        def sleep(_seconds):
            if produced:
                _write(recorder, produced.pop(0))

        frames = list(
            CaptureFollower(recorder.capture_dir(capture_id), sleep=sleep).follow(
                max_idle_polls=2
            )
        )

        assert [frame.source_seq for frame in frames] == [0, 1, 2, 3, 4]


class TestRobustness:
    def test_a_journal_line_whose_image_is_missing_is_skipped(self, recorder):
        """An orphan journal line must not take the whole follow down.

        This should be impossible given the write ordering, but a reader
        that trusts the invariant absolutely turns a deleted file into a
        crash mid-session.
        """
        capture_id = recorder.start()
        _write(recorder, 0)
        _write(recorder, 1)
        recorder.stop()

        directory = recorder.capture_dir(capture_id)
        (directory / "frames" / "00000000.jpg").unlink()

        frames = list(CaptureFollower(directory).follow())

        assert [frame.source_seq for frame in frames] == [1]

    def test_a_missing_capture_directory_yields_nothing(self, tmp_path):
        assert list(CaptureFollower(tmp_path / "absent").follow(max_idle_polls=1)) == []
