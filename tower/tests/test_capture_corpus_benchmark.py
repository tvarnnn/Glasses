"""Benchmarking against the frames the glasses actually produced.

Every CV figure in this repository was measured on synthetic renders or a
handful of hand-made images, while 9,199 real Ray-Ban frames sat unread in
`data/captures/`. Synthetic frames have no motion blur, no rolling shutter,
no auto-exposure hunting and no JPEG artefacts at the quality the phone
actually sends -- so a number measured on them is a number about the
renderer.

These tests pin the harness that closes that gap.
"""

import io
import json

import numpy as np
import pytest
from PIL import Image

from scripts.capture_corpus_benchmark import (
    CorpusReport,
    benchmark_corpus,
    iter_capture_frames,
)
from tower.experiments import UnclassifiedMetricError, frame_quality


def _jpeg(width: int = 32, height: int = 24, value: int = 128) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(
        np.full((height, width, 3), value, dtype=np.uint8)
    ).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def corpus(tmp_path):
    """Two captures with frames, one with none.

    The empty capture is not padding: `capture.py` creates the directory
    when recording starts, so a capture that was started and immediately
    stopped leaves exactly this shape on disk.
    """
    root = tmp_path / "captures"
    for capture_id, frame_count in (("aaa", 3), ("bbb", 2), ("empty", 0)):
        frames = root / capture_id / "frames"
        frames.mkdir(parents=True)
        lines = []
        for seq in range(1, frame_count + 1):
            name = f"{seq:08d}.jpg"
            (frames / name).write_bytes(_jpeg(value=40 * seq))
            lines.append(json.dumps({"source_seq": seq, "relpath": f"frames/{name}"}))
        (root / capture_id / "frames.jsonl").write_text("\n".join(lines))
    return root


class TestIteration:
    def test_it_walks_every_capture_that_has_frames(self, corpus):
        found = list(iter_capture_frames(corpus))
        assert len(found) == 5
        assert {capture_id for capture_id, _, _ in found} == {"aaa", "bbb"}

    def test_an_empty_capture_is_skipped_not_an_error(self, corpus):
        """A started-then-stopped capture is a real shape on disk."""
        assert all(capture_id != "empty" for capture_id, _, _ in
                   iter_capture_frames(corpus))

    def test_frames_arrive_in_source_order(self, corpus):
        seqs = [seq for capture_id, seq, _ in iter_capture_frames(corpus)
                if capture_id == "aaa"]
        assert seqs == sorted(seqs)

    def test_a_limit_bounds_each_capture_not_the_whole_corpus(self, corpus):
        """Otherwise one long capture would starve every later one."""
        found = list(iter_capture_frames(corpus, per_capture_limit=1))
        assert len(found) == 2
        assert {capture_id for capture_id, _, _ in found} == {"aaa", "bbb"}

    def test_a_missing_root_yields_nothing_rather_than_raising(self, tmp_path):
        assert list(iter_capture_frames(tmp_path / "nope")) == []


class TestBenchmark:
    def test_it_reports_per_capture_and_overall(self, corpus):
        report = benchmark_corpus(corpus, "baseline")

        assert isinstance(report, CorpusReport)
        assert report.frames == 5
        assert set(report.per_capture) == {"aaa", "bbb"}
        assert report.per_capture["aaa"].frames == 3

    def test_it_records_the_experiment_and_frame_count_it_actually_ran(self, corpus):
        report = benchmark_corpus(corpus, "baseline", per_capture_limit=2)
        assert report.experiment == "baseline"
        assert report.frames == 4

    def test_timings_are_summarised_not_averaged_away(self, corpus):
        """A mean hides the tail, and the tail is what drops frames."""
        report = benchmark_corpus(corpus, "baseline")
        assert report.median_ms > 0
        assert report.p95_ms >= report.median_ms

    def test_counts_are_summed_and_rates_are_not(self, corpus):
        """Summing a mean intensity across frames would be meaningless.

        `baseline` reports mean_intensity, which is a RATE: averaging is
        right and summing is nonsense. A detection count is the opposite.
        The harness must not treat them alike.
        """
        report = benchmark_corpus(corpus, "baseline")
        assert 0 < report.mean_intensity <= 255

    def test_an_empty_corpus_reports_zero_rather_than_dividing_by_it(self, tmp_path):
        report = benchmark_corpus(tmp_path / "nope", "baseline")
        assert report.frames == 0
        assert report.median_ms == 0.0
        assert report.per_capture == {}

    def test_an_unknown_experiment_is_refused_by_name(self, corpus):
        with pytest.raises(KeyError):
            benchmark_corpus(corpus, "no_such_experiment")

    def test_a_frame_that_will_not_decode_is_counted_not_fatal(self, corpus):
        """One truncated JPEG must not lose the other 9,198 frames."""
        (corpus / "aaa" / "frames" / "00000002.jpg").write_bytes(b"not a jpeg")

        report = benchmark_corpus(corpus, "baseline")

        assert report.failed == 1
        assert report.frames == 4
        assert report.per_capture["aaa"].failed == 1

    def test_the_report_serialises_to_json(self, corpus):
        report = benchmark_corpus(corpus, "baseline")
        payload = json.loads(json.dumps(report.to_json_dict()))
        assert payload["frames"] == 5
        assert payload["experiment"] == "baseline"


def _textured_jpeg(width: int = 96, height: int = 72, shift: int = 0) -> bytes:
    """Blocky noise a corner tracker can actually follow.

    Flat frames yield no corners, so an optical-flow run over them never
    reaches the branch that reports `tracked_fraction` -- which is the
    metric this harness was summing to ~768 over the real corpus.
    """
    rng = np.random.default_rng(11)
    small = rng.integers(0, 255, (height // 8, width // 8, 3), dtype=np.uint8)
    array = np.asarray(
        Image.fromarray(small).resize((width, height), Image.NEAREST)
    )
    if shift:
        array = np.roll(array, shift, axis=1)
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@pytest.fixture
def textured_corpus(tmp_path):
    """One capture whose frames move, so flow has something to measure."""
    frames = tmp_path / "captures" / "moving" / "frames"
    frames.mkdir(parents=True)
    for seq in range(1, 6):
        (frames / f"{seq:08d}.jpg").write_bytes(_textured_jpeg(shift=2 * seq))
    return tmp_path / "captures"


class TestMetricsAggregateTheWayTheExperimentSaysTheyDo:
    """The harness used to guess from the metric's NAME, via an allowlist
    that had been checked against the producers exactly once."""

    def test_a_rate_is_averaged_and_never_summed(self, corpus):
        report = benchmark_corpus(corpus, "frame_quality")

        assert "sharpness_laplacian_var" in report.averaged_metrics
        assert "sharpness_laplacian_var" not in report.summed_metrics
        # A fraction that has been summed over five frames is not a
        # fraction any more. This is the whole defect, in one bound.
        assert 0.0 <= report.averaged_metrics["overexposed_fraction"] <= 1.0
        assert 0.0 <= report.averaged_metrics["underexposed_fraction"] <= 1.0

    def test_a_count_is_summed_and_a_configured_value_is_neither(self, corpus):
        report = benchmark_corpus(corpus, "feature_detection")

        assert "keypoint_count" in report.summed_metrics
        assert "mean_response" in report.averaged_metrics
        assert "requested_features" in report.constant_metrics
        assert "requested_features" not in report.summed_metrics
        assert "requested_features" not in report.averaged_metrics

    def test_a_constant_is_reported_once_with_the_frames_that_carried_it(
        self, corpus
    ):
        """Summing a 32-pixel width over five frames gives 160, which is
        not a width. Averaging gives 32, which pretends the corpus was
        uniform. Neither is a report; the value and its frame count is."""
        report = benchmark_corpus(corpus, "frame_quality")

        assert report.constant_metrics["width"] == {32.0: 5}
        assert report.constant_metrics["height"] == {24.0: 5}
        assert "width" not in report.summed_metrics
        assert "width" not in report.averaged_metrics

    def test_a_constant_that_differs_between_captures_reports_both_values(
        self, tmp_path
    ):
        """The corpus really does hold more than one resolution, so a
        single number here would be a lie rather than a simplification."""
        root = tmp_path / "captures"
        for capture_id, (width, height), count in (
            ("small", (32, 24), 2), ("large", (64, 48), 3)
        ):
            frames = root / capture_id / "frames"
            frames.mkdir(parents=True)
            for seq in range(1, count + 1):
                (frames / f"{seq:08d}.jpg").write_bytes(_jpeg(width, height))

        report = benchmark_corpus(root, "frame_quality")

        assert report.constant_metrics["width"] == {32.0: 2, 64.0: 3}

    def test_a_metric_with_no_meaningful_aggregate_is_counted_not_combined(
        self, textured_corpus
    ):
        """A mean of 179 and -179 degrees is 0 -- a direction neither
        frame was moving."""
        report = benchmark_corpus(textured_corpus, "optical_flow")

        assert report.unaggregated_metrics["dominant_direction_deg"] > 0
        assert "dominant_direction_deg" not in report.summed_metrics
        assert "dominant_direction_deg" not in report.averaged_metrics

    def test_tracked_fraction_stays_a_fraction(self, textured_corpus):
        """The reported symptom: ~768 over 9,199 real frames, for a
        quantity that cannot exceed 1."""
        report = benchmark_corpus(textured_corpus, "optical_flow")

        assert "tracked_fraction" in report.averaged_metrics
        assert 0.0 <= report.averaged_metrics["tracked_fraction"] <= 1.0
        assert report.summed_metrics["seeded_count"] >= 1.0

    def test_an_unclassified_metric_stops_the_run_instead_of_being_summed(
        self, corpus, monkeypatch
    ):
        """Remove one classification and the harness must refuse, not
        guess. This is the assertion the previous design could not make:
        a miss there was indistinguishable from a count."""
        monkeypatch.delitem(frame_quality.METRIC_KINDS, "overexposed_fraction")

        with pytest.raises(UnclassifiedMetricError) as excinfo:
            benchmark_corpus(corpus, "frame_quality")

        assert "overexposed_fraction" in str(excinfo.value)

    def test_the_three_shapes_survive_the_json_round_trip(self, corpus):
        report = benchmark_corpus(corpus, "frame_quality")
        payload = json.loads(json.dumps(report.to_json_dict()))

        assert payload["averaged_metrics"]["overexposed_fraction"] <= 1.0
        assert payload["constant_metrics"]["width"] == [
            {"value": 32.0, "frames": 5}
        ]
        assert "width" not in payload["summed_metrics"]
