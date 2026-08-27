"""Is there a CHEAPER, BEHAVIOUR-PRESERVING configuration of FaceDetectorYN?

`FaceDetectorYN.detect` is the single largest cost in replay+build (22.8%).
It is already native, so the only lever is configuration. Redaction is a
privacy feature: any change that alters WHICH faces are found is out of
scope regardless of how fast it is. So each candidate below is scored on
detection equality FIRST and speed second.

Run from tower/:
  <venv-python> scripts/research/native_eval/bench_yunet.py
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

MODEL = Path("models") / "face_detection_yunet_2023mar.onnx"
SHIPPED_CONFIDENCE, NMS_THRESHOLD, TOP_K = 0.30, 0.30, 5000
UPSCALE = 2

# No real captured frames are stored in this repo (data/world_builder/worlds/*
# holds world.json only, no imagery), and synthetic content scores below
# 0.30 everywhere -- which would make "detections identical" vacuously
# true at the shipped threshold. So the EQUALITY test runs at a very low
# confidence, where the detector emits many candidate boxes: that is a
# fingerprint of the network's raw arithmetic, and it is a STRICTER test
# than comparing the handful of boxes that survive 0.30. Timings use the
# shipped configuration.
CONFIDENCE = 0.01


def frame(h=360, w=640, seed=0):
    """A synthetic first-person-ish frame. Content only has to be stable."""
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    img = cv2.GaussianBlur(img, (9, 9), 0)
    # a few face-ish ellipses so the network has something to score
    for cx, cy, r in [(160, 140, 26), (430, 180, 34), (300, 260, 18)]:
        cv2.ellipse(img, (cx, cy), (r, int(r * 1.3)), 0, 0, 360, (200, 178, 160), -1)
        cv2.circle(img, (cx - r // 3, cy - r // 4), max(2, r // 8), (40, 40, 40), -1)
        cv2.circle(img, (cx + r // 3, cy - r // 4), max(2, r // 8), (40, 40, 40), -1)
    return img


def bench(fn, n=30):
    fn()
    best = float("inf")
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best * 1000


def make(size, backend=0, target=0):
    return cv2.FaceDetectorYN.create(
        str(MODEL), "", size, CONFIDENCE, NMS_THRESHOLD, TOP_K, backend, target
    )


def detections(det, img):
    _, faces = det.detect(img)
    return np.zeros((0, 15)) if faces is None else np.asarray(faces)


def main():
    if not MODEL.exists():
        print("model missing at", MODEL.resolve())
        return
    print("cv2", cv2.__version__, "| cuda devices:", cv2.cuda.getCudaEnabledDeviceCount())
    print("cv2.ocl available:", cv2.ocl.haveOpenCL(), "| threads:", cv2.getNumThreads())
    print()

    img = frame()
    h, w = img.shape[:2]
    up = cv2.resize(img, (w * UPSCALE, h * UPSCALE), interpolation=cv2.INTER_CUBIC)
    size_up = (up.shape[1], up.shape[0])
    size_native = (w, h)

    print("=== cost split of the SHIPPED path (640x360 frame) ===")
    t_resize = bench(lambda: cv2.resize(img, (w * UPSCALE, h * UPSCALE), interpolation=cv2.INTER_CUBIC))
    det_up = make(size_up)
    t_detect = bench(lambda: det_up.detect(up))
    print(f"  INTER_CUBIC 2x upscale : {t_resize:7.2f} ms")
    print(f"  detect @ {size_up[0]}x{size_up[1]}     : {t_detect:7.2f} ms")
    print(f"  shipped total          : {t_resize + t_detect:7.2f} ms")
    ref = detections(det_up, up)
    print(f"  reference detections   : {len(ref)}")
    print()

    print("=== candidate configurations ===")
    rows = []

    # 1. No upscale. Explicitly a REDACTION WEAKENING - listed to price it.
    det_n = make(size_native)
    t = bench(lambda: det_n.detect(img))
    got = detections(det_n, img)
    rows.append(("no upscale (detect @640x360)", t, len(got), "WEAKENS: loses small faces"))

    # 2. INTER_LINEAR instead of INTER_CUBIC.
    lin = cv2.resize(img, size_up, interpolation=cv2.INTER_LINEAR)
    t_lin = bench(lambda: cv2.resize(img, size_up, interpolation=cv2.INTER_LINEAR))
    got = detections(det_up, lin)
    same = got.shape == ref.shape and np.allclose(got, ref, atol=1e-3)
    rows.append((
        "INTER_LINEAR upscale + same detect",
        t_lin + t_detect, len(got),
        "identical" if same else "CHANGES detections (different pixels in)",
    ))

    # 3. OpenCL target.
    try:
        det_ocl = make(size_up, cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_OPENCL)
        t_ocl = bench(lambda: det_ocl.detect(up))
        got = detections(det_ocl, up)
        same = got.shape == ref.shape and np.allclose(got, ref, atol=1e-3)
        rows.append((
            "DNN_TARGET_OPENCL", t_resize + t_ocl, len(got),
            "identical" if same else "CHANGES detections (fp arithmetic differs)",
        ))
    except Exception as exc:
        rows.append(("DNN_TARGET_OPENCL", float("nan"), -1, f"unavailable: {type(exc).__name__}"))

    # 4. OpenCL FP16 target.
    try:
        det_f16 = make(size_up, cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_OPENCL_FP16)
        t_f16 = bench(lambda: det_f16.detect(up))
        got = detections(det_f16, up)
        same = got.shape == ref.shape and np.allclose(got, ref, atol=1e-3)
        rows.append((
            "DNN_TARGET_OPENCL_FP16", t_resize + t_f16, len(got),
            "identical" if same else "CHANGES detections (fp16)",
        ))
    except Exception as exc:
        rows.append(("DNN_TARGET_OPENCL_FP16", float("nan"), -1, f"unavailable: {type(exc).__name__}"))

    # 5. CUDA target (needs a CUDA-enabled cv2 build).
    try:
        det_cuda = make(size_up, cv2.dnn.DNN_BACKEND_CUDA, cv2.dnn.DNN_TARGET_CUDA)
        t_cuda = bench(lambda: det_cuda.detect(up))
        got = detections(det_cuda, up)
        same = got.shape == ref.shape and np.allclose(got, ref, atol=1e-3)
        rows.append((
            "DNN_BACKEND_CUDA", t_resize + t_cuda, len(got),
            "identical" if same else "CHANGES detections",
        ))
    except Exception as exc:
        rows.append(("DNN_BACKEND_CUDA", float("nan"), -1, f"unavailable: {str(exc)[:70]}"))

    # 6. TOP_K. Purely a cap on candidates before NMS; 5000 is far above
    #    what a 1280x720 frame produces, so lowering it is only safe if
    #    the detections are unchanged.
    det_topk = cv2.FaceDetectorYN.create(
        str(MODEL), "", size_up, CONFIDENCE, NMS_THRESHOLD, 50
    )
    t_topk = bench(lambda: det_topk.detect(up))
    got = detections(det_topk, up)
    same = got.shape == ref.shape and np.allclose(got, ref, atol=1e-3)
    rows.append((
        "TOP_K 5000 -> 50", t_resize + t_topk, len(got),
        "identical here" if same else "CHANGES detections",
    ))

    # 7. Thread count (cv2 default vs explicit).
    for nthreads in (1, 4, 0):
        cv2.setNumThreads(nthreads)
        d = make(size_up)
        t = bench(lambda: d.detect(up))
        got = detections(d, up)
        same = got.shape == ref.shape and np.allclose(got, ref, atol=1e-3)
        rows.append((
            f"cv2.setNumThreads({nthreads})", t_resize + t, len(got),
            "identical" if same else "CHANGES detections",
        ))
    cv2.setNumThreads(-1)

    base = t_resize + t_detect
    print(f"{'configuration':<38} {'ms':>8} {'speedup':>8} {'faces':>6}  behaviour")
    print(f"{'SHIPPED (INTER_CUBIC 2x + CPU)':<38} {base:8.2f} {1.0:8.2f}x {len(ref):6d}  reference")
    for name, t, n, note in rows:
        sp = base / t if t == t and t > 0 else float("nan")
        print(f"{name:<38} {t:8.2f} {sp:8.2f}x {n:6d}  {note}")


if __name__ == "__main__":
    main()
