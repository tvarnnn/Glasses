"""CLI-contract tests for the World Builder Experiment 1/2 analysis scripts.

These cover argument handling and the pure-numeric helpers only -- they do
not run MiDaS or decode a real video, so they stay in the default (fast,
no-model) suite. The experiments' actual measured results live in
guidelines/docs/reports/V0.9.3-world-builder-experiments-1-2-report.md.
"""
import subprocess
import sys

import numpy as np

from scripts.depth_temporal_consistency import (
    _ema,
    _flicker_metrics,
    _lag_penalty,
    _normalize,
    _resize_to_platform_budget,
    _temporal_median,
)
from scripts.feature_trackability import _summarize


def test_depth_temporal_consistency_requires_video_argument():
    result = subprocess.run(
        [sys.executable, "scripts/depth_temporal_consistency.py"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--video" in result.stderr


def test_feature_trackability_requires_video_argument():
    result = subprocess.run(
        [sys.executable, "scripts/feature_trackability.py"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--video" in result.stderr


def test_normalize_maps_to_unit_range():
    depth = np.array([[1.0, 2.0], [3.0, 5.0]], dtype=np.float32)

    normalized = _normalize(depth)

    assert normalized.min() == 0.0
    assert normalized.max() == 1.0


def test_normalize_handles_flat_map_without_dividing_by_zero():
    flat = np.full((4, 4), 7.0, dtype=np.float32)

    normalized = _normalize(flat)

    assert np.all(normalized == 0.0)


def test_resize_preserves_orientation_at_platform_budget():
    landscape = np.zeros((1080, 1920, 3), dtype=np.uint8)
    portrait = np.zeros((1920, 1080, 3), dtype=np.uint8)

    assert _resize_to_platform_budget(landscape).shape[:2] == (504, 896)
    assert _resize_to_platform_budget(portrait).shape[:2] == (896, 504)


def test_flicker_metrics_are_zero_for_a_perfectly_static_sequence():
    static = [np.full((8, 8), 0.5, dtype=np.float32) for _ in range(5)]

    metrics = _flicker_metrics(static)

    assert metrics["mad_mean"] == 0.0
    assert metrics["temporal_std_mean"] == 0.0


def test_ema_reduces_flicker_of_an_alternating_sequence():
    alternating = [
        np.full((8, 8), 1.0 if index % 2 else 0.0, dtype=np.float32)
        for index in range(10)
    ]

    raw = _flicker_metrics(alternating)["mad_mean"]
    smoothed = _flicker_metrics(_ema(alternating, 0.3))["mad_mean"]

    assert smoothed < raw


def test_temporal_median_window_of_one_is_a_passthrough():
    sequence = [np.random.rand(4, 4).astype(np.float32) for _ in range(5)]

    smoothed = _temporal_median(sequence, window=1)

    for original, result in zip(sequence, smoothed):
        assert np.allclose(original, result)


def test_lag_penalty_is_zero_when_smoothed_equals_raw():
    sequence = [np.random.rand(4, 4).astype(np.float32) for _ in range(4)]

    assert _lag_penalty(sequence, sequence) == 0.0


def test_summarize_reports_expected_statistics():
    summary = _summarize([1.0, 2.0, 3.0, 10.0])

    assert summary == {"mean": 4.0, "median": 2.5, "min": 1.0, "max": 10.0}
