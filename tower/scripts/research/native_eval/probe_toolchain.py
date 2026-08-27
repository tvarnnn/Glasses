"""Does this host have a C++ toolchain that could build a CPython extension?

Empirical, not inferred: writes a trivial C extension and asks setuptools
to compile it. Whatever happens IS the answer.

Run:
  <venv-python> scripts/research/native_eval/probe_toolchain.py
"""

from __future__ import annotations

import os
import shutil
import sys
import sysconfig

BUILD_DIR = os.path.join(
    os.environ.get("TEMP", "."), "native_eval_build"
)

TRIVIAL_C = """
#define PY_SSIZE_T_CLEAN
#include <Python.h>
static PyObject *ping(PyObject *self, PyObject *args){ return PyLong_FromLong(42); }
static PyMethodDef M[] = {{"ping", ping, METH_NOARGS, "ping"},{NULL,NULL,0,NULL}};
static struct PyModuleDef mod = {PyModuleDef_HEAD_INIT, "trivial", NULL, -1, M};
PyMODINIT_FUNC PyInit_trivial(void){ return PyModule_Create(&mod); }
"""


def main() -> None:
    os.makedirs(BUILD_DIR, exist_ok=True)
    os.chdir(BUILD_DIR)
    with open("trivial.c", "w", encoding="utf-8") as handle:
        handle.write(TRIVIAL_C)

    print("python:", sys.version.split()[0], sys.executable)
    print("platform:", sysconfig.get_platform())
    print()

    print("=== PROBE 1: python build headers/libs ===")
    inc = sysconfig.get_paths()["include"]
    print("  include dir :", inc, "->", os.path.isdir(inc))
    print("  Python.h    :", os.path.isfile(os.path.join(inc, "Python.h")))
    libs = os.path.join(sys.base_prefix, "libs")
    print("  libs dir    :", libs, "->", os.path.isdir(libs))
    print()

    print("=== PROBE 2: compilers on PATH ===")
    for exe in ("cl", "cl.exe", "gcc", "g++", "clang", "clang-cl", "cc", "link", "nvcc", "cmake", "ninja"):
        print(f"  {exe:<10}", shutil.which(exe) or "NOT FOUND")
    print()

    print("=== PROBE 3: MSVC discovery via setuptools ===")
    try:
        from setuptools._distutils import _msvccompiler as mv
        print("  _msvccompiler imported")
        try:
            env = mv._get_vc_env("x64")
            keys = sorted(env)[:8]
            print("  _get_vc_env('x64') OK, keys:", keys)
        except Exception as exc:
            print("  _get_vc_env('x64') FAILED:", type(exc).__name__, str(exc)[:300])
    except Exception as exc:
        print("  _msvccompiler unavailable:", type(exc).__name__, exc)
    print()

    print("=== PROBE 4: actually compile trivial.c ===")
    try:
        from setuptools._distutils.ccompiler import new_compiler
        from setuptools._distutils import sysconfig as ds

        compiler = new_compiler()
        print("  compiler class:", type(compiler).__name__)
        ds.customize_compiler(compiler)
        objects = compiler.compile(["trivial.c"], include_dirs=[inc])
        print("  COMPILE OK ->", objects)
        compiler.link_shared_object(objects, "trivial.pyd", libraries=[])
        print("  LINK OK -> trivial.pyd")
        sys.path.insert(0, BUILD_DIR)
        import trivial  # noqa
        print("  IMPORT OK, ping() ->", trivial.ping())
        print("\n  VERDICT: a C extension CAN be built on this host.")
    except Exception as exc:
        print("  COMPILE/LINK FAILED:", type(exc).__name__)
        print(" ", str(exc)[:600])
        print("\n  VERDICT: a C extension CANNOT be built on this host as configured.")


if __name__ == "__main__":
    main()
