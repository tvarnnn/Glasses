#!/usr/bin/env bash
# Timeboxed attempt to build DPVO's CUDA extensions for real, in WSL2.
#
# Why WSL and not Windows: on the Windows host the build is blocked twice over.
# (1) The only CUDA toolkit present is 11.8, torch is 2.13.0+cu132, and
#     torch.utils.cpp_extension._check_cuda_version raises before nvcc is even
#     invoked; nvcc 11.8 also tops out at sm_90 and cannot emit sm_120 at all.
# (2) There is no MSVC on the host -- no cl.exe, no Visual Studio install --
#     so CUDAExtension has no host compiler.
#
# WSL2 Ubuntu 24.04 here has working GPU passthrough (nvidia-smi sees the
# RTX 5070), gcc 13.3, g++ and make. It does NOT have passwordless sudo, so
# apt-installing the CUDA toolkit is not available to an unattended agent.
# The workaround is that NVIDIA ships nvcc on PyPI: `nvidia-cuda-nvcc` 13.2.86
# matches torch's cu132 exactly. This script assembles a CUDA_HOME out of pip
# wheels and builds against it.
#
# Everything lands in ~/dpvo_build inside WSL. Nothing touches the repo.
set -u
LOG() { echo "=== $* ==="; }
ROOT=$HOME/dpvo_build
mkdir -p "$ROOT" && cd "$ROOT" || exit 1

LOG "step 1: venv"
# Ubuntu 24.04 here ships no python3-venv/python3-pip and there is no
# passwordless sudo, so ensurepip fails. Bootstrap pip by hand instead.
if [ ! -d venv ]; then python3 -m venv --without-pip venv || exit 1; fi
. venv/bin/activate
python -m pip --version >/dev/null 2>&1 || {
  curl -sS -o /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py || exit 1
  python /tmp/get-pip.py -q || exit 1
}
python -m pip install -q --upgrade pip setuptools wheel || exit 1

LOG "step 2: torch cu132"
python -c "import torch" 2>/dev/null || \
  pip install -q torch --index-url https://download.pytorch.org/whl/cu132 || exit 1
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda,
      "avail", torch.cuda.is_available())
print("arch list", torch.cuda.get_arch_list())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0),
          torch.cuda.get_device_capability(0))
PY

LOG "step 3: CUDA toolkit from pip wheels"
pip install -q "nvidia-cuda-nvcc==13.2.*" "nvidia-cuda-runtime-cu13" \
  "nvidia-cuda-cccl-cu13" "nvidia-cuda-crt" "nvidia-cuda-nvrtc-cu13" \
  2>&1 | tail -3
SP=$(python -c "import site;print(site.getsitepackages()[0])")
echo "site-packages: $SP"
find "$SP/nvidia" -maxdepth 3 -name nvcc -type f 2>/dev/null
find "$SP/nvidia" -maxdepth 4 -name "cuda_runtime.h" 2>/dev/null | head -3

NVCC=$(find "$SP/nvidia" -maxdepth 4 -name nvcc -type f 2>/dev/null | head -1)
if [ -z "$NVCC" ]; then LOG "FAIL: pip wheels shipped no nvcc"; exit 2; fi
CUDA_HOME="$ROOT/cuda_home"
rm -rf "$CUDA_HOME"; mkdir -p "$CUDA_HOME/bin" "$CUDA_HOME/include" "$CUDA_HOME/lib64" "$CUDA_HOME/nvvm"
ln -sf "$NVCC" "$CUDA_HOME/bin/nvcc"
NVCCDIR=$(dirname "$(dirname "$NVCC")")
for d in "$NVCCDIR"/nvvm/*; do ln -sf "$d" "$CUDA_HOME/nvvm/" 2>/dev/null; done
for d in "$NVCCDIR"/bin/*; do ln -sf "$d" "$CUDA_HOME/bin/" 2>/dev/null; done
# merge every wheel's include/ and lib/ into one tree
for inc in "$SP"/nvidia/*/include "$SP"/nvidia/*/*/include; do
  [ -d "$inc" ] || continue
  for f in "$inc"/*; do ln -sfn "$f" "$CUDA_HOME/include/" 2>/dev/null; done
done
for lib in "$SP"/nvidia/*/lib "$SP"/nvidia/*/*/lib; do
  [ -d "$lib" ] || continue
  for f in "$lib"/*; do ln -sfn "$f" "$CUDA_HOME/lib64/" 2>/dev/null; done
done
export CUDA_HOME PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
export TORCH_CUDA_ARCH_LIST="12.0"
nvcc --version 2>&1 | tail -3
echo "sm_120 supported by this nvcc:"; nvcc --list-gpu-code 2>&1 | grep -c sm_120

LOG "step 4: torch-scatter (DPVO imports torch_scatter in net.py)"
pip install torch-scatter --no-build-isolation 2>&1 | tail -8

LOG "step 5: DPVO"
if [ ! -d DPVO ]; then git clone -q --depth 1 https://github.com/princeton-vl/DPVO.git; fi
cd DPVO || exit 1
if [ ! -d thirdparty/eigen-3.4.0 ]; then
  mkdir -p thirdparty
  curl -sL -o /tmp/eigen.zip https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.zip
  python -c "import zipfile;zipfile.ZipFile('/tmp/eigen.zip').extractall('thirdparty')"
fi
pip install -q numba einops yacs plyfile opencv-python-headless 2>&1 | tail -3
pip install . --no-build-isolation 2>&1 | tail -30

LOG "step 6: import check"
cd "$ROOT"
python - <<'PY'
try:
    import torch, cuda_corr, cuda_ba, lietorch_backends
    print("ALL THREE CUDA EXTENSIONS IMPORT OK")
except Exception as e:
    print("IMPORT FAILED:", type(e).__name__, e)
try:
    from dpvo.dpvo import DPVO
    print("dpvo.dpvo imports OK")
except Exception as e:
    print("dpvo.dpvo import FAILED:", type(e).__name__, e)
PY
LOG "done"
