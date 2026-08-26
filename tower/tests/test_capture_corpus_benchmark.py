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
