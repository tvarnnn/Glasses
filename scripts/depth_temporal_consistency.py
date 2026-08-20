#!/usr/bin/env python3
"""World Builder Experiment 1 -- depth_temporal_consistency (offline analysis).

Measures how much the shipped MiDaS-small `depth` experiment's output
flickers frame-to-frame on real continuous motion, and how much a cheap
post-hoc smoothing filter (EMA / temporal median) reduces that flicker.

This is an OFFLINE dataset analysis, not a live Tower/WS run: the wire
protocol only carries the scalar mean_relative_depth, but this experiment
needs the full per-frame depth array. It drives `DepthEstimation` directly
with its opt-in `capture_depth_array` hook, reusing the shipped inference
path unmodified (see docs/superpowers/research/
2026-08-20-world-builder-foundations.md, Experiment A).

IMPORTANT -- what the numbers this prints do and do not mean:
results from a public dataset clip are *feasibility evidence*, NOT
physical-glasses/DAT validation. See docs/superpowers/research/
2026-08-20-world-builder-dataset-selection.md for the dataset ruling, its
limitations, and the acceptance gate requiring a re-run on real DAT footage.

Usage:
    .venv\\Scripts\\python.exe scripts/depth_temporal_consistency.py \\
        --video path/to/clip.MP4 --frames 150 --target-fps 15

Requires the `ml` extra: pip install -e ".[dev,ml]"
"""
import argparse
import json
import time

import cv2
import numpy as np

from tower.experiments.depth import DepthEstimation

# The platform's target stream geometry (03-ROADMAP.md V0.7). Source
# footage is resampled toward this so the measurement reflects roughly the
# pixel budget the Tower would really see, rather than the dataset's native
# resolution. Aspect ratio is preserved (no distortion), so a landscape
# source becomes landscape at an equivalent pixel count.
TARGET_LONG_EDGE = 896
TARGET_SHORT_EDGE = 504


def _resize_to_platform_budget(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if width >= height:
        target = (TARGET_LONG_EDGE, TARGET_SHORT_EDGE)
    else:
        target = (TARGET_SHORT_EDGE, TARGET_LONG_EDGE)
    return cv2.resize(frame, target, interpolation=cv2.INTER_AREA)


def _normalize(depth: np.ndarray) -> np.ndarray:
    """Min-max normalize one relative-depth map to [0, 1].

    MiDaS output is relative inverse depth with an arbitrary per-frame
    scale/offset -- comparing two raw frames directly would measure that
    arbitrary drift rather than structural flicker. Normalizing per frame
    is the standard way to make consecutive relative-depth maps
    comparable, and is itself a source of some measured instability
    (a scale shift shows up as a global change), which the report notes.
    """
    lo = float(depth.min())
    hi = float(depth.max())
    if hi - lo < 1e-9:
        return np.zeros_like(depth, dtype=np.float32)
    return ((depth - lo) / (hi - lo)).astype(np.float32)


def _flicker_metrics(sequence: list[np.ndarray]) -> dict:
    """Frame-to-frame instability of a sequence of normalized depth maps.

    - mad: mean absolute difference between consecutive frames, in
      normalized depth units (0-1 scale). Lower = more temporally stable.
    - p95: 95th-percentile absolute per-pixel change, i.e. how bad the
      worst-flickering regions are, not just the average.
    - temporal_std: per-pixel standard deviation over time, averaged over
      pixels -- overall jitter of the whole map across the window.
    """
    consecutive_mad = []
    consecutive_p95 = []
    for previous, current in zip(sequence, sequence[1:]):
        delta = np.abs(current - previous)
        consecutive_mad.append(float(delta.mean()))
        consecutive_p95.append(float(np.percentile(delta, 95)))
    stacked = np.stack(sequence, axis=0)
    return {
        "mad_mean": round(float(np.mean(consecutive_mad)), 5),
        "mad_max": round(float(np.max(consecutive_mad)), 5),
        "p95_mean": round(float(np.mean(consecutive_p95)), 5),
        "temporal_std_mean": round(float(stacked.std(axis=0).mean()), 5),
    }


def _ema(sequence: list[np.ndarray], alpha: float) -> list[np.ndarray]:
    """Causal exponential moving average -- usable in a live stream."""
    smoothed = [sequence[0]]
    for frame in sequence[1:]:
        smoothed.append(alpha * frame + (1.0 - alpha) * smoothed[-1])
    return smoothed


def _temporal_median(sequence: list[np.ndarray], window: int) -> list[np.ndarray]:
    """Causal trailing-window median -- also usable in a live stream."""
    smoothed = []
    for index in range(len(sequence)):
        start = max(0, index - window + 1)
        smoothed.append(np.median(np.stack(sequence[start : index + 1]), axis=0))
    return smoothed


def _lag_penalty(raw: list[np.ndarray], smoothed: list[np.ndarray]) -> float:
    """How far smoothing pulls the output away from the true current frame.

    Smoothing always trades responsiveness for stability; this quantifies
    the cost side of that trade so the report is not just "flicker went
    down". Mean absolute deviation of the smoothed output from the raw
    output for the same frame, in normalized depth units.
    """
    return round(
        float(np.mean([np.abs(s - r).mean() for r, s in zip(raw, smoothed)])), 5
    )


def run(video_path: str, frame_count: int, target_fps: float, device: str) -> dict:
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise RuntimeError(f"could not open video: {video_path}")
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    # Subsample toward the platform's ~15 FPS target so inter-frame motion
    # magnitude resembles what the Tower would actually receive. Sampling a
    # 50 FPS clip at every frame would understate flicker by making
    # consecutive frames unrealistically similar.
    stride = max(1, int(round(source_fps / target_fps))) if source_fps > 0 else 1

    experiment = DepthEstimation(capture_depth_array=True)
    experiment.load(device)

    raw_depths: list[np.ndarray] = []
    inference_ms: list[float] = []
    source_index = 0
    try:
        while len(raw_depths) < frame_count:
            ok, frame = capture.read()
            if not ok:
                break
            if source_index % stride != 0:
                source_index += 1
                continue
            source_index += 1

            resized = _resize_to_platform_budget(frame)
            ok_encode, encoded = cv2.imencode(".jpg", resized)
            if not ok_encode:
                raise RuntimeError("failed to JPEG-encode a frame")

            started = time.perf_counter()
            result = experiment.run(encoded.tobytes())
            inference_ms.append((time.perf_counter() - started) * 1000)
            raw_depths.append(_normalize(experiment.last_depth_array))
            del result
    finally:
        capture.release()
        experiment.release()

    if len(raw_depths) < 3:
        raise RuntimeError(f"only decoded {len(raw_depths)} frames; need at least 3")

    baseline = _flicker_metrics(raw_depths)
    variants = {"raw_baseline": {"flicker": baseline, "lag_from_raw": 0.0}}
    for alpha in (0.5, 0.3):
        smoothed = _ema(raw_depths, alpha)
        variants[f"ema_alpha_{alpha}"] = {
            "flicker": _flicker_metrics(smoothed),
            "lag_from_raw": _lag_penalty(raw_depths, smoothed),
        }
    for window in (3, 5):
        smoothed = _temporal_median(raw_depths, window)
        variants[f"median_window_{window}"] = {
            "flicker": _flicker_metrics(smoothed),
            "lag_from_raw": _lag_penalty(raw_depths, smoothed),
        }

    for name, data in variants.items():
        if name == "raw_baseline":
            data["mad_reduction_vs_raw_pct"] = 0.0
            continue
        data["mad_reduction_vs_raw_pct"] = round(
            100.0 * (baseline["mad_mean"] - data["flicker"]["mad_mean"]) / baseline["mad_mean"],
            2,
        )

    steady_state = inference_ms[1:] if len(inference_ms) > 1 else inference_ms
    return {
        "video": video_path,
        "device": device,
        "source_fps": round(source_fps, 2),
        "sample_stride": stride,
        "effective_sampled_fps": round(source_fps / stride, 2) if source_fps else None,
        "frames_analyzed": len(raw_depths),
        "depth_map_shape": list(raw_depths[0].shape),
        "per_frame_experiment_ms_avg": round(sum(steady_state) / len(steady_state), 2),
        "variants": variants,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="path to a real-motion video clip")
    parser.add_argument("--frames", type=int, default=150)
    parser.add_argument("--target-fps", type=float, default=15.0)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    args = parser.parse_args()

    report = run(args.video, args.frames, args.target_fps, args.device)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
