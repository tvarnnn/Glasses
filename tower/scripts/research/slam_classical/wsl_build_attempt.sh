#!/usr/bin/env bash
# Timeboxed ORB-SLAM3 build attempt inside WSL2 (Ubuntu 24.04).
#
# The point of this script is NOT to succeed. It is to record EXACTLY which
# dependency wall is hit first, so the report can price "get ORB-SLAM3
# running" instead of hand-waving it. Every step prints a PROBE line so the
# transcript is the evidence.
#
# Run:  wsl -d ITSC-3146 -- bash /mnt/c/.../wsl_build_attempt.sh
set -u
say() { echo "PROBE[$1] $2"; }

say sudo "checking for passwordless sudo (apt is the normal install path)"
if sudo -n true 2>/dev/null; then say sudo "PASSWORDLESS SUDO AVAILABLE"; SUDO=1; else
  say sudo "BLOCKED - sudo requires a password, apt-get install is unavailable non-interactively"; SUDO=0; fi

say deps "checking each ORB-SLAM3 build dependency"
for h in /usr/include/eigen3/Eigen/Core /usr/include/GL/gl.h \
         /usr/include/boost/serialization/serialization.hpp \
         /usr/include/opencv4/opencv2/core.hpp /usr/include/X11/Xlib.h \
         /usr/include/GL/glew.h /usr/include/python3.12/Python.h; do
  if [ -f "$h" ]; then say deps "PRESENT  $h"; else say deps "MISSING  $h"; fi
done

say cmake "cmake is not in PATH; trying the userspace pip route"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v cmake >/dev/null 2>&1; then
  pip3 install --user --quiet cmake ninja 2>&1 | tail -2 || say cmake "pip install cmake FAILED"
fi
command -v cmake >/dev/null 2>&1 && say cmake "OK $(cmake --version | head -1)" || say cmake "STILL MISSING"

SRC=/mnt/c/Users/tvllo/AppData/Local/Temp/claude/C--Users-tvllo-Projects-Glasses/9b0536e8-15bd-4b4c-a285-b06758d320a4/scratchpad/thirdparty/ORB_SLAM3
say src "ORB_SLAM3 source at $SRC"
[ -d "$SRC" ] && say src "present" || { say src "ABSENT - abort"; exit 1; }

say cmakelists "declared find_package requirements:"
grep -nE "find_package|REQUIRED|Pangolin|Boost|Eigen|OpenCV" "$SRC/CMakeLists.txt" | head -30

# Configure in a scratch dir on the Linux filesystem (not /mnt/c, which is slow).
B=$HOME/orb3build
mkdir -p "$B" && cd "$B" || exit 1
say configure "attempting cmake configure of Thirdparty/DBoW2 (smallest unit: needs only OpenCV)"
cmake -S "$SRC/Thirdparty/DBoW2" -B "$B/dbow2" 2>&1 | tail -20
say configure "exit=$?"

say configure "attempting cmake configure of the ORB_SLAM3 core"
cmake -S "$SRC" -B "$B/core" 2>&1 | tail -30
say configure "exit=$?"
say done "walls hit are printed above"
