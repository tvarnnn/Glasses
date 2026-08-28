# `pyceres` wheel linkage, and the Sim(3) pose-graph solver decision

**Date:** 2026-08-27
**Closes:** F16 (open question) in `2026-08-26-world-builder-slam-adversarial-review.md:393-402`
**Scope:** blocking licensing gate for the Stage 4 / Step 6 pose-graph-optimisation work.

---

## VERDICT

> **NO — `pyceres` is NOT safe for a commercial closed-source product, on this platform or any other.**
> The published `pyceres` wheels bundle a Ceres built `WITH_SUITESPARSE=ON` and ship the
> **GPL-2.0-or-later** SuiteSparse modules — **SPQR in full**, and **CHOLMOD's Supernodal and
> MatrixOps** — as loaded, hard-linked dependencies. This is not a build-flag risk to be
> assessed; it is a measured fact about the exact artefact the deliverable recommended.
>
> **Recommended solver: `scipy.optimize.least_squares` (BSD-3, scipy 1.18.1 already in the
> venv), poses in a 7-vector Sim(3) exp-chart, with `jac_sparsity` + `tr_solver='lsmr'`** —
> falling back to a hand-rolled Levenberg–Marquardt on `numpy` + `scipy.sparse.linalg` if
> determinism or speed demands it. Ranked table in §5.

The question is **determined**, not undetermined. Four independent lines of evidence agree
and none dissent.

---

## 1. Does a `cp312` / `win_amd64` wheel exist?

**MEASURED-by-me.** Yes. Queried the PyPI JSON API directly (not memory):

```
python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('https://pypi.org/pypi/pyceres/json')); ..."
```

| field | value |
|---|---|
| latest version | **2.6** (uploaded 2025-11-05) |
| filename | **`pyceres-2.6-cp312-cp312-win_amd64.whl`** |
| size | **8,457,845 bytes** |
| sha256 | `c7e24463365778f423c34cd0e06ce57634a2e26da16935eec094c72263520493` |
| declared licence | `Apache-2.0` (METADATA + classifier) |
| URL | `https://files.pythonhosted.org/packages/4c/4c/2291a63a81ddfa306ee18d57156a458758953933212f224ea3a7bb6b036c/pyceres-2.6-cp312-cp312-win_amd64.whl` |

Every 3.9–3.14 CPython has a `win_amd64` wheel back to 2.0; `cp312` first appears at 2.2.

**MEASURED-by-me.** Downloaded to `%TEMP%\pyceres_probe\` with `urllib.request.urlretrieve`
and re-hashed locally — SHA-256 matches PyPI's digest byte for byte. **Nothing was installed
into `tower/.venv`; the venv was never written to.** (Note: the venv actually lives at
`C:\Users\tvllo\Projects\Glasses\tower\.venv`, not inside this worktree; it was only ever
read from, via `python -c "import ..."`.)

---

## 2. What does that wheel link against? (the crux)

### 2.1 The wheel's own contents

**MEASURED-by-me**, `zipfile.ZipFile(...).infolist()`:

```
    973312  pyceres.cp312-win_amd64.pyd
   3115008  pyceres-2.6.data/platlib/ceres-decfaa0fda11c960cbb7283aa8ca0e93.dll
   2052096  pyceres-2.6.data/platlib/cholmod-2fcda09a063ab81f566d163bc500d711.dll   <-- GPL modules inside
    351232  pyceres-2.6.data/platlib/spqr-6893aef7f150343c5a9dc2ec79dad2a8.dll      <-- GPL-2.0-or-later, entire module
     14336  pyceres-2.6.data/platlib/suitesparseconfig-*.dll
     35840  .../amd-*.dll      38912 .../camd-*.dll
     46080  .../ccolamd-*.dll  31744 .../colamd-*.dll
   8453369  .../liblapack-*.dll     1761280 .../openblas-*.dll
   3717841  .../libgfortran-5-*.dll  ... plus glog, gflags, msvcp140, libwinpthread
```

`delvewheel` 1.11.2 vendored these; the `DELVEWHEEL` metadata file records
`--add-path D:\a\pyceres\pyceres/vcpkg/installed/x64-windows/bin`, i.e. a **vcpkg** build.

`cholmod.dll` and `spqr.dll` in the wheel settle the headline. The remaining sections
establish that the **GPL** modules specifically are present and reachable.

### 2.2 PE import table — Ceres genuinely links SuiteSparse

**MEASURED-by-me.** No MSVC on this host, so I wrote a pure-Python PE parser
(`%TEMP%\pyceres_probe\pe.py`, ~60 lines, stdlib `struct` only — no `pefile`, no install)
that walks the COFF header, section table, and data directories 0 (export) and 1 (import).

`ceres-*.dll` **IMPORT DLLS** include, verbatim:

```
cholmod-2fcda09a063ab81f566d163bc500d711.dll
spqr-6893aef7f150343c5a9dc2ec79dad2a8.dll
```

Imported by name from `cholmod.dll` (17 symbols):

```
cholmod_amd  cholmod_analyze  cholmod_analyze_p  cholmod_camd  cholmod_factorize
cholmod_finish  cholmod_free_dense  cholmod_free_factor  cholmod_free_sparse
cholmod_l_finish  cholmod_l_free_sparse  cholmod_l_start  cholmod_nested_dissection
cholmod_print_common  cholmod_solve  cholmod_start  cholmod_triplet_to_sparse
```

Imported from `spqr.dll` (mangled MSVC symbol, demangled):

```
??$SuiteSparseQR@N_J@@YA_JHN_JPEAUcholmod_sparse_struct@@PEAPEAU0@PEAPEA_JPEAUcholmod_common_struct@@@Z
   ==  int64_t SuiteSparseQR<double, int64_t>(int, double, int64_t,
                                              cholmod_sparse*, cholmod_sparse**,
                                              int64_t**, cholmod_common*)
```

These are **hard, non-delay-loaded PE imports**. `spqr.dll` and `cholmod.dll` are resolved by
the Windows loader when `ceres.dll` loads, which happens on `import pyceres` (the `.pyd`
itself hard-imports `ceres-*.dll`). The GPL code is mapped into the process on import, in
every configuration, with no flag to avoid it.

### 2.3 Which SuiteSparse modules — the distinction that decides the case

SuiteSparse is licensed per module; only some modules are GPL. **MEASURED-by-me** by
enumerating `cholmod.dll`'s 918 exported names and grouping by module:

| SuiteSparse module | licence | present in shipped `cholmod.dll`? | evidence |
|---|---|---|---|
| **Supernodal** | **GPL-2.0-or-later** | **YES — 10 exports** | `cholmod_super_numeric`, `cholmod_super_symbolic`, `cholmod_super_symbolic2`, `cholmod_super_lsolve`, `cholmod_super_ltsolve` (+ 5 `cholmod_l_*` int64 twins) |
| **MatrixOps** | **GPL-2.0-or-later** | **YES — 8/8 probed** | `cholmod_ssmult`, `cholmod_horzcat`, `cholmod_vertcat`, `cholmod_norm_sparse`, `cholmod_scale`, `cholmod_sdmult`, `cholmod_submatrix`, `cholmod_symmetry` |
| **SPQR** (separate DLL) | **GPL-2.0-or-later** | **YES — 372 exports** | `spqr-*.dll`, incl. multiple `SuiteSparseQR<...>` template instantiations |
| Modify | GPL-2.0-or-later | no (0/3 probed) | `cholmod_updown`/`rowadd`/`rowdel` absent |
| Partition | LGPL-2.1+ | yes | `cholmod_nested_dissection`, `cholmod_metis`, `cholmod_bisect` (+614 `metis*` exports) |
| Cholesky / Check / Utility | LGPL-2.1+ / Apache | yes | `cholmod_analyze`, `cholmod_factorize`, `cholmod_solve`, `cholmod_rowfac` |

**Corroborating measurement:** `cholmod.dll` imports 20 BLAS Level-2/3 kernels from
`openblas-*.dll` — `dgemm_`, `dsyrk_`, `dtrsm_`, `dtrsv_`, `dgemv_` and their `s`/`c`/`z`
variants. **Dense BLAS is used by CHOLMOD's Supernodal module and essentially nowhere else**;
the simplicial (LGPL) path is scalar. The BLAS dependency is independent confirmation that
`CHOLMOD_SUPERNODAL` was compiled in, not merely that the symbols survived.

So this is **not** the benign case. It is not a CXSparse-only or AMD/COLAMD-only build. The
two modules the deliverable named as the disqualifying ones — **CHOLMOD Supernodal and
SPQR** — are both present, and MatrixOps (also GPL) is present as a third.

### 2.4 The upstream build config — QUOTED, with URL

`https://github.com/cvg/pyceres/blob/main/ci/vcpkg-dependencies.txt`, complete file:

```
ceres[lapack,schur,suitesparse]
gflags
glog
```

`https://github.com/cvg/pyceres/blob/main/pyproject.toml` — a single `vcpkg-dependencies.txt`
feeds `before-all` on **linux, macos and windows** alike, pinned to
`VCPKG_COMMIT_ID = 36fb57eb3878cc3422351a91d3e87c328388dabd`.

At that vcpkg commit, `ports/ceres/vcpkg.json` defines the requested feature as:

```json
"suitesparse": {
  "description": "SuiteSparse support for Ceres",
  "dependencies": [
    { "name": "ceres", "features": ["lapack"] },
    { "name": "suitesparse-cholmod", "default-features": false, "features": ["matrixops"] },
    "suitesparse-config",
    "suitesparse-spqr"
  ]
}
```

and `ports/suitesparse-spqr/vcpkg.json` declares, verbatim:

```json
"name": "suitesparse-spqr",
"license": "GPL-2.0-or-later",
"dependencies": [ "lapack",
  { "name": "suitesparse-cholmod", "features": ["supernodal"] }, ... ]
```

and `ports/suitesparse-cholmod/vcpkg.json` marks the exact features in play:

```json
"matrixops":  { "license": "GPL-2.0-or-later AND LGPL-2.1-or-later AND Apache-2.0" },
"supernodal": { "license": "GPL-2.0-or-later AND LGPL-2.1-or-later AND Apache-2.0",
                "dependencies": ["lapack"] }
```

and `ports/suitesparse-cholmod/portfile.cmake` flips the upstream GPL switch:

```cmake
set(GPL_ENABLED OFF)
if(CHOLMOD_MATRIXOPS OR CHOLMOD_MODIFY OR CHOLMOD_SUPERNODAL OR CUDA_ENABLED)
    set(GPL_ENABLED ON)
endif()
...
    -DCHOLMOD_GPL=${GPL_ENABLED}
```

vcpkg's own top-level `ports/suitesparse/vcpkg.json` places `supernodal`,
`matrixops`, `modify` and `suitesparse-spqr` under a feature literally named **`gpl`**:
*"Enable GPL-licensed packages"*.

So the build system that produced this wheel **classifies its own output as
GPL-2.0-or-later**, and compiles CHOLMOD with `CHOLMOD_GPL=ON`. The binary measurement in
§2.3 and the build manifest agree exactly.

### 2.5 What Ceres upstream says about precisely this configuration

**QUOTED**, `https://github.com/ceres-solver/ceres-solver/blob/master/docs/source/installation.rst`
(fetched raw; exact text):

> `WITH_SUITESPARSE [Default: OFF]`: SuiteSparse support is opt-in. Turn this `ON` to link
> Ceres against `SuiteSparse`, provided it and all of its dependencies are present.
>
> **WARNING:** SuiteSparse is licensed under a mixture of GPL/LGPL/Commercial terms. Ceres
> requires the CHOLMOD supernodal factorization and SPQR components, which are only available
> under GPL/Commercial terms. Consequently, unless you hold a commercial SuiteSparse license,
> **a Ceres build with `WITH_SUITESPARSE=ON` is GPL licensed.** This is why SuiteSparse
> support is opt-in rather than enabled by default. Obtaining a commercial SuiteSparse license
> removes this restriction.

The deliverable's risk model was right about the mechanism. It simply had not been checked
against the artefact — and the artefact is on the wrong side of it.

### 2.6 The wheel ships no GPL licence text — an independent compliance defect

**MEASURED-by-me.** The wheel's *only* licence file is
`pyceres-2.6.dist-info/licenses/LICENSE`, 11,580 bytes, which is the **Apache License 2.0 and
nothing else**. `grep -in "gpl\|suitesparse\|cholmod\|spqr\|lesser"` over it returns **zero
matches**. There is no SuiteSparse `License.txt`, no GPL-2 text, no LGPL text, and no written
offer of source.

That matters on its own terms. Even setting aside any argument about derivative works,
GPL-2 §3 conditions *redistribution of the GPL binary itself* on accompanying source or a
written offer. Consuming this wheel means redistributing `spqr.dll` and a `CHOLMOD_GPL=ON`
`cholmod.dll` inside a commercial product, with no GPL notice and no source offer. That is
already non-conforming before the linking question is even reached.

### 2.7 There is no platform escape

**MEASURED-by-me.** Every `cp312`/`win_amd64` wheel published, not just 2.6:

| wheel | SuiteSparse DLLs bundled |
|---|---|
| `pyceres-2.2-cp312-cp312-win_amd64.whl` | `libcholmod-*.dll`, `libspqr-*.dll`, libamd, libcamd, libcolamd, libccolamd |
| `pyceres-2.4-cp312-cp312-win_amd64.whl` | `libcholmod-*.dll`, `libspqr-*.dll`, + same |
| `pyceres-2.5-cp312-cp312-win_amd64.whl` | `cholmod-*.dll`, `spqr-*.dll`, + suitesparseconfig |
| `pyceres-2.6-cp312-cp312-win_amd64.whl` | `cholmod-*.dll`, `spqr-*.dll`, + suitesparseconfig |

Downgrading does not help. And the Linux wheel is **worse**, not better: the manylinux
`cp312` wheel vendors only `libgfortran` and `libquadmath` in `pyceres.libs/`, because
SuiteSparse is **statically linked into `pyceres.cpython-312-x86_64-linux-gnu.so`**. Scanning
that 10.1 MB `.so` for symbol strings — **MEASURED-by-me** — finds `SuiteSparseQR` ×58,
`cholmod_super_numeric` ×3, `CHOLMOD` ×83, `SPQR` ×7. Static linkage of GPL code into a
single binary is the least defensible form of coupling there is.

---

## 3. Could `pyceres` be made safe?

Three theoretical routes, honestly priced:

1. **Buy a commercial SuiteSparse licence** from the author (Tim Davis / TAMU). This is a
   real, intended route — Ceres's own warning names it. It removes the GPL condition
   entirely. Cost unknown to me (**not investigated — requires contacting the licensor**).
   Only worth pricing if Ceres's specific capabilities become load-bearing, which for this
   project they are not (§5).
2. **Rebuild `pyceres` from source** with `ci/vcpkg-dependencies.txt` patched to
   `ceres[lapack,schur]`. Licence-clean and only a one-line patch — but see §4.3 for why it
   is not cheap on this host, and it puts the team on the hook for maintaining a private
   wheel build.
3. **Use the wheel and hope.** Not an option for a commercial closed-source product. The
   dynamic-linking-as-derivative-work theory is genuinely contested in law — but that debate
   is irrelevant here, because §2.6's redistribution obligation attaches to the GPL binaries
   themselves regardless, and no closed-source product should rest on a contested theory when
   a BSD-3 path exists at comparable cost.

---

## 4. The alternatives, concretely

### 4.1 `scipy.optimize` — BSD-3

**MEASURED-by-me** against `C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe`
(read-only `import`, nothing written):

- **`scipy 1.18.1` is already installed.** No new dependency, no new wheel, no licence review.
- `scipy.libs/` contains exactly one vendored binary: `libscipy_openblas-*.dll`. **No
  CHOLMOD, no SPQR, no SuiteSparse of any kind.** scipy is BSD-3; OpenBLAS is BSD-3.
- `scipy.optimize.least_squares` supports `jac_sparsity=` and `tr_solver='lsmr'` — verified
  present in the installed build's signature/docstring. That is exactly the combination a
  pose graph needs: the Jacobian is block-sparse, and `lsmr` on a sparse Jacobian avoids ever
  forming the dense normal equations.
- `scipy.sparse.linalg.splu` (SuperLU, **BSD-3**) and `spsolve` are available for a
  hand-built normal-equations solve.

The one design note: `least_squares` optimises a flat vector and knows nothing about
manifolds. For Sim(3) this is a non-problem if each pose is parameterised as an **absolute
7-vector chart `[ω(3), t(3), log s(1)]` with `exp` applied inside the residual** rather than
as a constrained quaternion + scale. There is no constraint to violate, so no retraction
machinery is needed and no re-parameterisation between iterations.

Prior in-repo research (`2026-08-26-slam-lane-classical-map-architecture.md:1103-1105`)
already concluded numpy + cv2 suffice for the Sim(3) estimation itself (Horn 1987 / Umeyama
1991, ~30 LOC, patent-free, and already proven end-to-end by the prior lane). This finding is
consistent with that: the solver is the only piece that was ever in question, and scipy
covers it.

### 4.2 Hand-rolled Gauss–Newton / Levenberg–Marquardt on numpy

~200–300 LOC for a Sim(3) pose graph: analytic Jacobians of the relative-pose residual,
sparse normal equations assembled into `scipy.sparse.csr_matrix`, LM damping, and
`splu`/`spsolve` (SuperLU, BSD-3) or `cholesky` via `scipy.linalg` on the dense reduced
system if the graph is small.

This is what g2o and Ceres do internally, minus the templating. It is the *most* deterministic
option — every step is inspectable, the damping schedule is explicit, and there is no
black-box trust-region policy that might change across a scipy release. Against it: it is
code the team must test and own, and getting the Sim(3) Jacobians right is where the bugs
live.

Given the loop-closure gate ladder already documented (`:625-628`: ≥15 RANSAC inliers, ≥20
`OptimizeSim3` inliers, ≥80 refined projection matches) and the essential-graph
`minFeat=100` threshold (`:593`), the graphs here are small — tens to low hundreds of
keyframes per session. At that scale a hand-rolled LM is not a performance compromise; the
dense-vs-sparse and supernodal-vs-simplicial distinctions that motivate Ceres+SuiteSparse in
the first place simply do not bind.

### 4.3 Build Ceres from source with `WITH_SUITESPARSE=OFF`

Licence-wise this is clean: Ceres core is BSD-3 and `WITH_SUITESPARSE` is `OFF` by default,
so a stock build needs no flag change at all — only *not* opting in.

Feasibility on this host is the problem. **MEASURED-by-me:**

```
ls "/c/Program Files/Microsoft Visual Studio"       -> No such file or directory
ls "/c/Program Files (x86)/Microsoft Visual Studio" -> No such file or directory
where cl / cmake / ninja / gcc  -> "INFO: Could not find files for the given pattern(s)."
```

**There is no C/C++ toolchain of any kind on this machine** — no MSVC, no CMake, no Ninja, no
MinGW. Building Ceres from source means first provisioning VS Build Tools (multi-GB), CMake,
Ninja, then Eigen + glog + gflags, then Ceres, then `pyceres` itself against it, then
`delvewheel`-repairing the result — and then owning that private wheel forever, including for
CI and for every other developer machine. **ESTIMATED** at 1–3 days of setup plus an ongoing
maintenance tax, to obtain a solver whose distinguishing capability (supernodal sparse
Cholesky) is precisely the GPL part we are excluding and is not needed at this graph size.

Not recommended, but it is the correct fallback if Ceres ever becomes genuinely necessary.

---

## 5. Ranked recommendation

Ranked by (licence safety, implementation cost, determinism, maintainability, Windows
compatibility):

| # | Option | Licence | Impl. cost | Determinism | Maintainability | Windows |
|---|---|---|---|---|---|---|
| **1** | **`scipy.optimize.least_squares`, Sim(3) as 7-vector exp-chart, `jac_sparsity` + `tr_solver='lsmr'`** | **BSD-3 (+OpenBLAS BSD-3)** — clean | **lowest**: already installed, no new dep | good; TR policy is a scipy-version dependency, so pin scipy | excellent — someone else's tested solver | **already working in this venv** |
| **2** | **Hand-rolled LM/GN on numpy + `scipy.sparse.linalg.splu`** | **BSD-3** — clean | ~200–300 LOC + tests | **best** — every step explicit and pinned | medium — team owns the Jacobians | trivially portable |
| **3** | Ceres from source, `WITH_SUITESPARSE=OFF`, `pyceres` rebuilt against it | BSD-3 (Ceres core) + Apache-2.0 binding — clean | **1–3 days setup, no toolchain on host [ESTIMATED]** | very good | poor — private wheel, forever | needs a full MSVC provisioning |
| — | Commercial SuiteSparse licence + stock wheel | clean, but **paid**; price not investigated | zero code | very good | fine | fine |
| **✗** | **`pyceres` PyPI wheel as-is** | **GPL-2.0-or-later — DISQUALIFYING** | zero | — | — | — |

**Recommendation: start at #1, keep #2 in reserve.** Write the residual and its analytic
Jacobian by hand either way — that is the part that carries the project's actual risk, and it
is identical between #1 and #2. Which optimiser consumes it is then a swap of about twenty
lines, which makes the #1 → #2 fallback nearly free. Do not spend the Stage 4 budget on #3
unless #1 and #2 both demonstrably fail at the real graph size, which on the evidence of
`:593` and `:625-628` they will not.

**Action for the deliverable:** F16's open question is now **closed as NO**. The two
conflicting licences the review flagged (BSD-3 vs Apache-2.0 for the binding) are both moot —
the binding's licence was never the exposure. Strike `pyceres` from the Stage 4
recommendation at `:1103` and substitute the scipy path.

---

## Appendix — reproduction

All work in `%TEMP%\pyceres_probe\` (outside the repo). Nothing installed into any venv;
`tower/.venv` was read-only-imported and never written.

```
python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('https://pypi.org/pypi/pyceres/json')); ..."   # §1 file listing
python -c "import urllib.request; urllib.request.urlretrieve(URL,'pyceres-2.6-cp312-cp312-win_amd64.whl')"               # download
python -c "import hashlib; print(hashlib.sha256(open(WHL,'rb').read()).hexdigest())"                                     # digest check
python -c "import zipfile; [print(i.file_size,i.filename) for i in zipfile.ZipFile(WHL).infolist()]"                      # §2.1
python pe.py x/pyceres.cp312-win_amd64.pyd x/.../ceres-*.dll x/.../cholmod-*.dll x/.../spqr-*.dll                          # §2.2 PE imports
python syms.py                                                                                                            # §2.3 module-by-module exports
python more.py                                                                                                            # §2.7 older wheels + manylinux .so scan
```

`pe.py` is a ~60-line stdlib-only PE parser (COFF header -> section table -> data directories
0 and 1). It was written because `dumpbin` is unavailable and `pefile` would have required an
install. Its output was cross-checked against the vcpkg manifests in §2.4, which agree
independently.

**Labelling key:** every table row and quotation above is marked MEASURED-by-me (command
given), QUOTED-with-URL (source given), or ESTIMATED. The only ESTIMATED figure in the
verdict path is the §4.3 build-from-source effort, which does not affect the NO.
