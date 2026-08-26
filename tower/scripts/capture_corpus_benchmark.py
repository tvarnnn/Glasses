"""Run a CV Lab experiment over the frames the glasses actually produced.

`cv_lab_benchmark.py` measures against synthetic renders, which is right
for comparing experiments to each other and wrong for predicting anything.
Synthetic frames carry no motion blur, no rolling shutter, no auto-exposure
hunting, and no JPEG artefacts at the quality the phone actually sends. A
number measured on them describes the renderer.

This walks `data/captures/` instead -- 18 captures and ~9,199 real
Ray-Ban frames at 360x640 that, until now, no detector or OCR had ever
been run against.

    python scripts/capture_corpus_benchmark.py object_detection
    python scripts/capture_corpus_benchmark.py depth --per-capture-limit 50
    python scripts/capture_corpus_benchmark.py baseline --format json

It reads. It never writes to the corpus, and it persists nothing: the
Experimental CV Lab declares `persists_data=False` and a boundary test
enforces it, so a benchmark that wrote results would break the cartridge's
own guarantee.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

# `scripts/` is a package inside the tower project; running this file
# directly still needs the project root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.experiments import EXPERIMENTS, ExperimentSettings  # noqa: E402

# Metric names whose values are RATES or SCORES, which must be averaged.
# Everything else -- detection counts, per-class counts -- is a COUNT and
# must be summed. Getting this backwards produces a number that looks
# plausible and means nothing: a summed "mean score" of 47.3 across 91
# frames, or a detection count averaged down to 0.4.
_RATE_METRICS = frozenset({
    "score_threshold",
    "mean_score",
    "max_score",
    "mean_depth",
    "depth_p50",
    "depth_p95",
    "sharpness",
    "blur_ratio",
    "inlier_ratio",
    "survival_ratio",
    "overlap_ratio",
})


@dataclass
class CaptureReport:
    """One capture's contribution."""

    capture_id: str
    frames: int = 0
    failed: int = 0
    timings_ms: list[float] = field(default_factory=list)

    @property
    def median_ms(self) -> float:
        return statistics.median(self.timings_ms) if self.timings_ms else 0.0

    def to_json_dict(self) -> dict:
        return {
            "capture_id": self.capture_id,
            "frames": self.frames,
            "failed": self.failed,
            "median_ms": round(self.median_ms, 3),
        }


@dataclass
class CorpusReport:
    """What the whole corpus said.

    `failed` is carried separately from `frames` rather than folded into
    it, because "9,198 frames at 40 ms" and "9,198 frames at 40 ms plus one
    that would not decode" are different claims, and the second one is the
    true one.
    """

    experiment: str
    device: str
    frames: int = 0
    failed: int = 0
    captures: int = 0
    timings_ms: list[float] = field(default_factory=list)
    per_capture: dict[str, CaptureReport] = field(default_factory=dict)
    summed_metrics: dict[str, float] = field(default_factory=dict)
    averaged_metrics: dict[str, float] = field(default_factory=dict)
    mean_intensity: float = 0.0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.timings_ms) if self.timings_ms else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.timings_ms:
            return 0.0
        ordered = sorted(self.timings_ms)
        return ordered[max(0, int(len(ordered) * 0.95) - 1)]

    def to_json_dict(self) -> dict:
        return {
            "experiment": self.experiment,
            "device": self.device,
            "captures": self.captures,
            "frames": self.frames,
            "failed": self.failed,
            "median_ms": round(self.median_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "fps_at_median": round(1000.0 / self.median_ms, 2) if self.median_ms else 0.0,
            "mean_intensity": round(self.mean_intensity, 3),
            "summed_metrics": {k: round(v, 3) for k, v in sorted(self.summed_metrics.items())},
            "averaged_metrics": {
                k: round(v, 4) for k, v in sorted(self.averaged_metrics.items())
            },
            "per_capture": [
                r.to_json_dict() for r in sorted(
                    self.per_capture.values(), key=lambda r: r.capture_id
                )
            ],
        }


def iter_capture_frames(
    root: Path | str, *, per_capture_limit: int | None = None
) -> Iterator[tuple[str, int, bytes]]:
    """Yield `(capture_id, source_seq, jpeg_bytes)` across every capture.

    The limit is PER CAPTURE, not per corpus: a corpus-wide cap would spend
    its whole budget inside the first long capture and never reach the
    others, which is the opposite of what a corpus benchmark is for.

    A capture directory with no frames is skipped rather than reported as
    an error -- `capture.py` creates the directory when recording starts,
    so a start-then-stop leaves exactly that shape behind.
    """
    root = Path(root)
    if not root.is_dir():
        return

    for capture_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        frames_dir = capture_dir / "frames"
        if not frames_dir.is_dir():
            continue

        paths = sorted(frames_dir.glob("*.jpg"))
        if per_capture_limit is not None:
            paths = paths[:per_capture_limit]

        for path in paths:
            try:
                seq = int(path.stem)
            except ValueError:
                # Not one of ours; the recorder writes zero-padded seqs.
                continue
            yield capture_dir.name, seq, path.read_bytes()


def benchmark_corpus(
    root: Path | str,
    experiment_name: str,
    *,
    per_capture_limit: int | None = None,
    device: str = "auto",
) -> CorpusReport:
    """Run one experiment over the corpus and summarise honestly."""
    factory = EXPERIMENTS[experiment_name]  # KeyError names the bad choice
    report = CorpusReport(experiment=experiment_name, device=device)

    experiment = factory()
    experiment.load(ExperimentSettings(device=device))

    summed: dict[str, float] = {}
    averaged: dict[str, list[float]] = {}
    intensities: list[float] = []

    try:
        for capture_id, _seq, raw in iter_capture_frames(
            root, per_capture_limit=per_capture_limit
        ):
            per = report.per_capture.setdefault(capture_id, CaptureReport(capture_id))

            started = time.perf_counter()
            try:
                result = experiment.run(raw)
            except Exception:
                # One truncated JPEG must not cost the other 9,198 frames.
                # Counted, never silently dropped.
                per.failed += 1
                report.failed += 1
                continue
            elapsed_ms = (time.perf_counter() - started) * 1000.0

            per.frames += 1
            per.timings_ms.append(elapsed_ms)
            report.frames += 1
            report.timings_ms.append(elapsed_ms)

            if result.mean_intensity is not None:
                intensities.append(result.mean_intensity)

            for name, value in result.metrics.items():
                if name in _RATE_METRICS:
                    averaged.setdefault(name, []).append(value)
                else:
                    summed[name] = summed.get(name, 0.0) + value
    finally:
        experiment.release()

    report.captures = len(report.per_capture)
    report.summed_metrics = summed
    report.averaged_metrics = {k: statistics.fmean(v) for k, v in averaged.items()}
    report.mean_intensity = statistics.fmean(intensities) if intensities else 0.0
    return report


def _render_text(report: CorpusReport) -> str:
    lines = [
        f"experiment   {report.experiment}  (device={report.device})",
        f"captures     {report.captures}",
        f"frames       {report.frames}"
        + (f"   FAILED {report.failed}" if report.failed else ""),
    ]
    if report.frames:
        lines += [
            f"median       {report.median_ms:.1f} ms"
            f"   ({1000.0 / report.median_ms:.1f} fps)",
            f"p95          {report.p95_ms:.1f} ms",
        ]
        if report.mean_intensity:
            lines.append(f"mean_intensity {report.mean_intensity:.2f}")
        if report.summed_metrics:
            lines.append("summed:")
            for name, value in sorted(report.summed_metrics.items()):
                lines.append(f"  {name:<28} {value:g}")
        if report.averaged_metrics:
            lines.append("averaged:")
            for name, value in sorted(report.averaged_metrics.items()):
                lines.append(f"  {name:<28} {value:.4f}")
    else:
        lines.append("no frames found -- is TOWER_CAPTURE_ROOT right?")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a CV Lab experiment over real captured frames."
    )
    parser.add_argument("experiment", choices=sorted(EXPERIMENTS))
    parser.add_argument(
        "--root",
        default="data/captures",
        help="capture root (default: data/captures)",
    )
    parser.add_argument(
        "--per-capture-limit",
        type=int,
        default=None,
        help="cap frames taken from EACH capture, so one long capture "
        "cannot starve the rest",
    )
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--format", default="text", choices=["text", "json"])
    args = parser.parse_args(argv)

    report = benchmark_corpus(
        args.root,
        args.experiment,
        per_capture_limit=args.per_capture_limit,
        device=args.device,
    )

    if args.format == "json":
        print(json.dumps(report.to_json_dict(), indent=2))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
