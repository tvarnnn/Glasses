#!/usr/bin/env python
"""Read-only World Builder readiness diagnostic for this Tower.

Reports, in one place, every environment capability a monocular World
Builder pipeline would depend on: GPU visibility, whether torch can
actually reach that GPU, which OpenCV geometry/calibration/feature
primitives this build ships, and which optional acceleration libraries
are present.

Why this exists separately from ``scripts/verify_cuda.py``: that script
answers one question (can torch see CUDA) and raises SystemExit when the
answer is no. This one answers "what can this machine actually do for
World Builder", installs nothing, writes nothing, and by default exits 0
even when the answer is "not much" -- a diagnostic is only useful if it
still runs on the broken machine it is diagnosing.

Not part of the pytest suite's real work: the suite may not assume a GPU,
a driver, or a particular torch build. ``tests/test_world_builder_env_check_cli.py``
pins only the CLI contract.

    .venv\\Scripts\\python.exe scripts/world_builder_env_check.py
    .venv\\Scripts\\python.exe scripts/world_builder_env_check.py --format json
    .venv\\Scripts\\python.exe scripts/world_builder_env_check.py --strict
"""

import argparse
import importlib
import json
import platform
import shutil
import subprocess
import sys

# OpenCV symbols a monocular pipeline actually calls, grouped by role so a
# partial build reports which capability its absence costs us, rather than
# just a bare symbol name.
OPENCV_REQUIREMENTS = {
    "features": (
        "ORB_create",
        "SIFT_create",
    ),
    "matching": (
        "BFMatcher",
        "FlannBasedMatcher",
    ),
    "flow": (
        "calcOpticalFlowPyrLK",
        "calcOpticalFlowFarneback",
        "DISOpticalFlow_create",
    ),
    "geometry": (
        "findEssentialMat",
        "findFundamentalMat",
        "findHomography",
        "recoverPose",
        "decomposeEssentialMat",
        "triangulatePoints",
        "solvePnPRansac",
        "correctMatches",
    ),
    "calibration": (
        "calibrateCamera",
        "findChessboardCornersSB",
        "initCameraMatrix2D",
        "undistort",
    ),
}

# Optional libraries. Present/absent is informative either way -- absence
# is not a failure here, it is a cost estimate for a future decision.
OPTIONAL_LIBRARIES = (
    "torch",
    "torchvision",
    "timm",
    "scipy",
    "kornia",
    "open3d",
    "onnxruntime",
    "tensorrt",
    "numba",
    "cupy",
    "transformers",
)


def _module_version(name):
    """Import ``name`` and return its version string, or None if absent."""
    try:
        module = importlib.import_module(name)
    except Exception:
        return None
    return str(getattr(module, "__version__", "(no __version__)"))


def collect_host():
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def collect_nvidia_smi():
    """Query the driver directly.

    Deliberately independent of any Python build: the GPU can be perfectly
    healthy while torch cannot reach it, and distinguishing those two
    cases is the main thing this diagnostic exists to do.
    """
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return {"available": False, "reason": "nvidia-smi not on PATH"}

    query = "name,driver_version,memory.total,memory.free,compute_cap"
    try:
        completed = subprocess.run(
            [exe, "--query-gpu=" + query, "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    if completed.returncode != 0:
        return {
            "available": False,
            "reason": f"nvidia-smi exit {completed.returncode}",
        }

    gpus = []
    for line in completed.stdout.strip().splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        gpus.append(
            {
                "name": fields[0],
                "driver_version": fields[1],
                "memory_total": fields[2],
                "memory_free": fields[3],
                "compute_capability": fields[4],
            }
        )
    return {"available": bool(gpus), "gpus": gpus}


def collect_torch():
    try:
        import torch
    except Exception as exc:
        return {"installed": False, "reason": f"{type(exc).__name__}: {exc}"}

    info = {
        "installed": True,
        "version": torch.__version__,
        "cuda_build": torch.version.cuda,
        "cuda_available": bool(torch.cuda.is_available()),
        "device_count": 0,
        "arch_list": [],
        "device_name": None,
        "device_capability": None,
    }

    # A CPU-only wheel can raise from get_arch_list() rather than returning
    # an empty list, so this is guarded rather than assumed.
    try:
        info["arch_list"] = list(torch.cuda.get_arch_list())
    except Exception:
        info["arch_list"] = []

    if info["cuda_available"]:
        info["device_count"] = torch.cuda.device_count()
        try:
            info["device_name"] = torch.cuda.get_device_name(0)
            info["device_capability"] = list(torch.cuda.get_device_capability(0))
        except Exception as exc:
            info["device_query_error"] = f"{type(exc).__name__}: {exc}"

    return info


def collect_opencv():
    try:
        import cv2
    except Exception as exc:
        return {"installed": False, "reason": f"{type(exc).__name__}: {exc}"}

    info = {"installed": True, "version": cv2.__version__, "capabilities": {}}

    for capability, symbols in OPENCV_REQUIREMENTS.items():
        present = [name for name in symbols if hasattr(cv2, name)]
        missing = [name for name in symbols if not hasattr(cv2, name)]
        info["capabilities"][capability] = {
            "complete": not missing,
            "present": present,
            "missing": missing,
        }

    # ChArUco is the self-calibration path that needs no new dependency, so
    # it is reported explicitly rather than left implicit inside `aruco`.
    aruco = getattr(cv2, "aruco", None)
    info["charuco"] = {
        "aruco_module": aruco is not None,
        "CharucoBoard": hasattr(aruco, "CharucoBoard") if aruco else False,
        "CharucoDetector": hasattr(aruco, "CharucoDetector") if aruco else False,
    }

    try:
        info["cuda_device_count"] = cv2.cuda.getCudaEnabledDeviceCount()
    except Exception:
        info["cuda_device_count"] = 0

    return info


def collect_libraries():
    return {name: _module_version(name) for name in OPTIONAL_LIBRARIES}


def build_verdicts(report):
    """Turn raw facts into the few go/no-go statements an implementer needs.

    Returns a list of ``(key, ok, detail)`` tuples.
    """
    verdicts = []

    nvidia = report["nvidia_smi"]
    verdicts.append(
        (
            "gpu_visible",
            bool(nvidia.get("available")),
            (
                nvidia["gpus"][0]["name"]
                if nvidia.get("gpus")
                else nvidia.get("reason", "no GPU reported by driver")
            ),
        )
    )

    torch_info = report["torch"]
    torch_cuda_ok = bool(torch_info.get("cuda_available"))
    if not torch_info.get("installed"):
        torch_detail = "torch not installed"
    elif torch_cuda_ok:
        capability = torch_info.get("device_capability") or []
        torch_detail = (
            f"torch {torch_info['version']} -> {torch_info.get('device_name')} "
            f"sm_{''.join(str(value) for value in capability)}"
        )
    else:
        torch_detail = (
            f"torch {torch_info['version']} cannot reach CUDA "
            f"(cuda_build={torch_info.get('cuda_build')})"
        )
    verdicts.append(("torch_cuda_usable", torch_cuda_ok, torch_detail))

    # The interesting failure is specifically "GPU present, torch blind to
    # it": that is a fixable packaging problem rather than missing
    # hardware, and the two are indistinguishable if you only check torch.
    verdicts.append(
        (
            "gpu_reachable_from_python",
            bool(nvidia.get("available")) and torch_cuda_ok,
            (
                "GPU present but torch cannot use it"
                if nvidia.get("available") and not torch_cuda_ok
                else ("ok" if torch_cuda_ok else "no GPU reachable")
            ),
        )
    )

    cv_info = report["opencv"]
    if not cv_info.get("installed"):
        verdicts.append(("opencv_geometry", False, "opencv not installed"))
        verdicts.append(("opencv_self_calibration", False, "opencv not installed"))
        return verdicts

    capabilities = cv_info["capabilities"]
    incomplete = sorted(
        name for name, data in capabilities.items() if not data["complete"]
    )
    verdicts.append(
        (
            "opencv_geometry",
            not incomplete,
            (
                f"opencv {cv_info['version']}: all {len(capabilities)} "
                "capability groups complete"
                if not incomplete
                else f"incomplete groups: {', '.join(incomplete)}"
            ),
        )
    )

    charuco = cv_info["charuco"]
    charuco_ok = (
        charuco["CharucoBoard"]
        and charuco["CharucoDetector"]
        and capabilities["calibration"]["complete"]
    )
    verdicts.append(
        (
            "opencv_self_calibration",
            charuco_ok,
            (
                "ChArUco board + detector + calibrateCamera available"
                if charuco_ok
                else "ChArUco/calibration primitives incomplete"
            ),
        )
    )

    return verdicts


def render_text(report, verdicts):
    lines = []

    host = report["host"]
    lines.append("=== Host ===")
    lines.append(f"python           {host['python']}")
    lines.append(f"platform         {host['platform']}")

    lines.append("")
    lines.append("=== GPU (driver) ===")
    nvidia = report["nvidia_smi"]
    if nvidia.get("available"):
        for index, gpu in enumerate(nvidia["gpus"]):
            lines.append(
                f"[{index}] {gpu['name']}  driver {gpu['driver_version']}  "
                f"compute {gpu['compute_capability']}  "
                f"{gpu['memory_free']} free / {gpu['memory_total']}"
            )
    else:
        lines.append(f"unavailable: {nvidia.get('reason')}")

    lines.append("")
    lines.append("=== torch ===")
    torch_info = report["torch"]
    if torch_info.get("installed"):
        lines.append(f"version          {torch_info['version']}")
        lines.append(f"cuda build       {torch_info['cuda_build']}")
        lines.append(f"cuda available   {torch_info['cuda_available']}")
        lines.append(f"arch list        {torch_info['arch_list']}")
        if torch_info.get("device_name"):
            lines.append(f"device           {torch_info['device_name']}")
            lines.append(f"capability       {torch_info['device_capability']}")
    else:
        lines.append(f"not installed: {torch_info.get('reason')}")

    lines.append("")
    lines.append("=== OpenCV ===")
    cv_info = report["opencv"]
    if cv_info.get("installed"):
        lines.append(f"version          {cv_info['version']}")
        lines.append(f"cuda devices     {cv_info['cuda_device_count']}")
        for capability, data in cv_info["capabilities"].items():
            status = "complete" if data["complete"] else "INCOMPLETE"
            lines.append(f"{capability:16s} {status}")
            if data["missing"]:
                lines.append(f"                 missing: {', '.join(data['missing'])}")
        charuco = cv_info["charuco"]
        lines.append(
            f"charuco          board={charuco['CharucoBoard']} "
            f"detector={charuco['CharucoDetector']}"
        )
    else:
        lines.append(f"not installed: {cv_info.get('reason')}")

    lines.append("")
    lines.append("=== Optional libraries ===")
    for name, version in report["libraries"].items():
        lines.append(f"{name:16s} {version if version else '-- absent --'}")

    lines.append("")
    lines.append("=== Verdicts ===")
    for key, ok, detail in verdicts:
        lines.append(f"[{'OK ' if ok else 'NO '}] {key:28s} {detail}")

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Read-only World Builder environment readiness diagnostic. "
            "Installs nothing and writes nothing."
        )
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero if any verdict fails. Off by default so the "
            "diagnostic still runs cleanly on the machine it is diagnosing."
        ),
    )
    args = parser.parse_args(argv)

    report = {
        "host": collect_host(),
        "nvidia_smi": collect_nvidia_smi(),
        "torch": collect_torch(),
        "opencv": collect_opencv(),
        "libraries": collect_libraries(),
    }
    verdicts = build_verdicts(report)
    report["verdicts"] = [
        {"check": key, "ok": ok, "detail": detail} for key, ok, detail in verdicts
    ]

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report, verdicts))

    if args.strict and any(not ok for _, ok, _ in verdicts):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
