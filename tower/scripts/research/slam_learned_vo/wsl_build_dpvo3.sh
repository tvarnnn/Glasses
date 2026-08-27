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
# Python.h comes from debs unpacked into ~/pydev/root (no sudo, no apt install)
export CPATH="$HOME/pydev/root/usr/include:$HOME/pydev/root/usr/include/python3.12:$HOME/pydev/root/usr/include/x86_64-linux-gnu/python3.12:${CPATH:-}"
export LIBRARY_PATH="$HOME/pydev/root/usr/lib/x86_64-linux-gnu:${LIBRARY_PATH:-}"
echo "CPATH=$CPATH"
pip install -q ninja
LOG "torch-scatter"
pip install torch-scatter --no-build-isolation 2>&1 | tail -14
python -c "import torch_scatter;print('torch_scatter OK')" 2>&1 | tail -2
LOG "DPVO"
cd DPVO && pip install . --no-build-isolation 2>&1 | tail -30
LOG "import check"
cd "$ROOT"
python - <<'PY'
for mod in ("cuda_corr", "cuda_ba", "lietorch_backends"):
    try:
        __import__(mod); print(f"  {mod}: OK")
    except Exception as e:
        print(f"  {mod}: FAILED {type(e).__name__}: {e}")
try:
    from dpvo.dpvo import DPVO
    print("dpvo.dpvo imports OK")
except Exception as e:
    print("dpvo.dpvo import FAILED:", type(e).__name__, e)
PY
LOG done
