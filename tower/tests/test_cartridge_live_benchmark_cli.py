"""The live-cost benchmark, driven as a person would drive it.

A benchmark that only ever runs by hand rots quietly: its argument names
drift, its report keys move, and the next person to need a number finds a
traceback instead. These tests keep it callable.

No model is loaded here. The two heavy paths -- `--cartridge scene` with
real weights and `--document-recogniser easyocr` -- are what the script
exists for and what nobody should pay for on every commit. What is under
test is the harness around them: argument parsing, the report shape, the
refusal when there are no frames, and the driving loop's accounting.
"""

import json

import pytest

from scripts import cartridge_live_benchmark as bench


class FakeSession:
    """A session that takes a fixed time per frame, without a thread.

    Deliberately synchronous: `_drive`'s accounting is what is under
    test, and a real worker would make the assertions depend on
    scheduling.
    """

    def __init__(self, *, cost_frames: int = 0):
        self.offered = 0
        self.observed = 0
        self.skipped = 0
        self._cost = cost_frames

    def offer_frame(self, payload, *, received_at=None, source_seq=None):
        self.offered += 1
        if self._cost and self.offered % self._cost == 0:
            self.skipped += 1
        else:
            self.observed += 1

    def status(self):
        return {
            "frames_offered": self.offered,
            "frames_observed": self.observed,
            "frames_skipped": self.skipped,
            "frames_dropped_not_running": 0,
        }


def _frames(count: int):
    return [(index, b"frame") for index in range(count)]


class TestTheHarnessAccountsForEveryFrame:
    def test_every_offered_frame_is_observed_or_skipped(self):
        """The accounting identity the whole report rests on.

        A frame that is neither observed nor skipped nor dropped has gone
        missing, and every rate below it would be quietly wrong.
        """
        session = FakeSession(cost_frames=4)

        run = bench._drive(session, _frames(20), paced=False, settle_s=0.1)

        assert (
            run["frames_observed"]
            + run["frames_skipped"]
            + run["frames_dropped_not_running"]
            == run["frames_offered"]
        )
        assert run["frames_offered"] == 20

    def test_the_skip_fraction_is_reported_and_is_not_hidden(self):
        session = FakeSession(cost_frames=4)

        run = bench._drive(session, _frames(20), paced=False, settle_s=0.1)

        assert run["frames_skipped"] == 5
        assert run["skip_fraction"] == pytest.approx(0.25)

    def test_pacing_feeds_at_the_delivered_interval_not_faster(self):
        """Feeding faster measures the harness, not the cartridge."""
        session = FakeSession()

        run = bench._drive(session, _frames(6), paced=True, settle_s=0.1)

        assert run["paced"] is True
        # Six frames at 83.5 ms cannot complete in less than five gaps.
        assert run["wall_seconds"] >= 5 * bench.DELIVERED_INTERVAL_S

    def test_the_event_loop_cost_is_measured_separately(self):
        """`offer_frame` runs on the loop and its cost is everyone's."""
        session = FakeSession()

        run = bench._drive(session, _frames(10), paced=False, settle_s=0.1)

        cost = run["offer_frame_cost"]
        assert cost["count"] == 10
        assert cost["median_ms"] >= 0.0
        assert cost["p95_ms"] >= cost["median_ms"]

    def test_a_session_that_observed_nothing_reports_nulls_not_zeros(self):
        """A rate with no denominator is not zero; it is unknown."""

        class Silent(FakeSession):
            def offer_frame(self, payload, *, received_at=None, source_seq=None):
                self.offered += 1
                self.skipped += 1

        run = bench._drive(Silent(), _frames(4), paced=False, settle_s=0.1)

        assert run["frames_observed"] == 0
        assert run["worker_service_ms_mean"] is None


class TestTheScriptRefusesToInventData:
    def test_an_empty_corpus_is_an_error_with_a_reason(self, tmp_path, capsys):
        """No frames must not become a synthetic run.

        A synthetic frame contains no COCO object and no page, so every
        figure produced from one would describe the empty path while
        looking like a measurement.
        """
        code = bench.main(["--captures", str(tmp_path), "--cartridge", "scene"])

        payload = json.loads(capsys.readouterr().out)
        assert code == 1
        assert payload["error"] == "no frames"
        assert "invent" in payload["note"]

    def test_the_document_run_is_skipped_without_a_root(self, tmp_path, capsys):
        """It writes real records. It must not choose a directory itself."""
        frames_dir = tmp_path / "cap" / "frames"
        frames_dir.mkdir(parents=True)
        (frames_dir / "000001.jpg").write_bytes(b"not-a-jpeg")

        bench.main(
            [
                "--captures",
                str(tmp_path),
                "--cartridge",
                "document",
                "--frames",
                "1",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert "no --document-root" in payload["runs"]["document"]["skipped"]


def test_the_delivered_interval_matches_the_tracker_s_own_constant():
    """One number, two places, and they must not drift.

    `tower/scene/tracking.py` derives `max_misses` from this interval. A
    benchmark that paced at a different rate would be measuring a
    cartridge tuned for something else.
    """
    from tower.scene.tracking import DELIVERED_FRAME_INTERVAL_S

    assert bench.DELIVERED_INTERVAL_S == pytest.approx(DELIVERED_FRAME_INTERVAL_S)
