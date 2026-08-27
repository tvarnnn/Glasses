#!/usr/bin/env bash
# Part 2 of the WSL build: CUDA_HOME is the pip-installed nvidia/cu13 tree
# (nvcc 13.2.86, which matches torch 2.13.0+cu132 exactly and does emit
# sm_120). No sudo was needed anywhere.
set -u
LOG() { echo "=== $* ==="; }
ROOT=$HOME/dpvo_build
cd "$ROOT" || exit 1
. venv/bin/activate
SP=$(python -c "import site;print(site.getsitepackages()[0])")
export CUDA_HOME="$SP/nvidia/cu13"
[ -e "$CUDA_HOME/lib64" ] || ln -s "$CUDA_HOME/lib" "$CUDA_HOME/lib64"
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib:${LD_LIBRARY_PATH:-}"
export TORCH_CUDA_ARCH_LIST="12.0"
export MAX_JOBS=8
nvcc --version | tail -1

LOG "numpy + deps"
pip install -q "numpy<3" einops yacs plyfile opencv-python-headless numba \
  2>&1 | tail -3

LOG "torch-scatter"
pip install torch-scatter --no-build-isolation 2>&1 | tail -12
python -c "import torch_scatter; print('torch_scatter OK', torch_scatter.__version__)" \
  2>&1 | tail -3

LOG "DPVO"
if [ ! -d DPVO ]; then git clone -q --depth 1 https://github.com/princeton-vl/DPVO.git; fi
cd DPVO || exit 1
if [ ! -d thirdparty/eigen-3.4.0 ]; then
  mkdir -p thirdparty
  curl -sL -o /tmp/eigen.zip https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.zip
  python -c "import zipfile;zipfile.ZipFile('/tmp/eigen.zip').extractall('thirdparty')"
fi
pip install . --no-build-isolation 2>&1 | tail -40

LOG "import check"
cd "$ROOT"
python - <<'PY'
import traceback
for mod in ("cuda_corr", "cuda_ba", "lietorch_backends"):
    try:
        __import__(mod)
        print(f"  {mod}: OK")
    except Exception as e:
        print(f"  {mod}: FAILED {type(e).__name__}: {e}")
try:
    from dpvo.dpvo import DPVO
    print("dpvo.dpvo imports OK")
except Exception as e:
    print("dpvo.dpvo import FAILED:", type(e).__name__, e)
    traceback.print_exc()
PY
LOG "done"
