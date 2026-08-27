# Adversarial review: the native-migration refusal and the three changes

**Reviewer stance:** assume the conclusion is wrong and the changes are
unjustified. Everything below labelled MEASURED was run by this reviewer
in this session; QUOTED means taken from the lane's own artifacts.

---

## VERDICT

**The refusal of C++ is SOUND.** I attacked all four supporting legs and
could not break any of them. Two survived with corrected numbers, and one
of the corrections makes the refusal *stronger*, not weaker.

**All three changes are SAFE. None should be reverted.** Two need wording
corrections, and one needs a one-line guard or a narrowed docstring:

| change | verdict |
|---|---|
| `_Pack` / `_residuals_packed` (committed) | **SAFE WITH CORRECTIONS** — tighten the parity tolerance; stop claiming "identical" |
| `storage.py` dumps-then-write | **SAFE** — one comment sentence is wrong |
| `frontend.measure_sharpness` CV_16S | **SAFE WITH CORRECTIONS** — the exactness argument is an *unenforced precondition* |

**Quiet-machine GIL number: 82.7%, and the conclusion survives.**

---

## Environment

Asserted every run. `tower.world_builder.backends.classical` resolved to
`C:\Users\tvllo\Projects\Glasses-world-builder\tower\tower\world_builder\backends\classical.py`
with `EXTEND_REFERENCE_DEPTH` present; cwd pinned to `<worktree>/tower`
so `redaction.DEFAULT_MODEL_PATH` resolves and face redaction is ON.
Scratch was an absolute path under `%TEMP%\wb-adv-gil`; nothing was
written into the main repo's corpus. OpenCV 5.0.0, numpy 2.5.2, Python
3.12.5.

**The review target moved mid-review.** HEAD advanced from `f00e3bc` to
`e5c8716` — six commits from another lane working the same branch — and
the three "uncommitted" changes were committed underneath me. I verified
my temporary reverts restored byte-exactly (`git diff` clean against
HEAD) and that the committed content is what I measured.

**Two comparison targets in the brief are confounded.**
`baseline_HEAD_d3d24b5.json` (1,712 kf / 591 solved / 75,369 points) is
the **DEPTH=1** control per its own README, while
`EXTEND_REFERENCE_DEPTH = 3` today. A current-HEAD corpus replay compared
against it would show a large divergence that has nothing to do with
sharpness. I therefore ran a **clean A/B toggling only
`measure_sharpness`**, which removes the confound entirely.

---

## Findings that change a priority

### 1. `measure_sharpness` rests on an unenforced precondition, and violating it fails three different ways

The docstring asserts "The input is 8-bit" as a fact. Nothing enforces
it. MEASURED, old vs new on the same array:

| input | old | new | divergence |
|---|---|---|---|
| 3-channel colour 32×32 | 109635.12 | 110448.25 | **7.4e-3 relative** |
| int16 | 6,889,649,961 | 905,545,047 | **8.7e-1 relative** |
| uint16 | 7,527,392,126 | **raises `cv2.error`** | behaviour change |
| float64 | 1.73e12 | **raises `cv2.error`** | behaviour change |

The colour case is the quiet one: `meanStdDev` returns **per-channel**
deviations and `[0, 0]` silently takes channel 0, where `.var()` pooled
all three. That is twelve orders of magnitude worse than the claimed
4.1e-16 bound, and it returns a plausible number rather than raising.

**The product path is safe.** `decode_gray` uses `IMREAD_GRAYSCALE`, so
input is always uint8 and 2-D, and
`test_the_decoder_still_produces_the_uint8_this_relies_on` pins exactly
that premise — genuinely good defensive testing. But `measure_sharpness`
is a module-level public function annotated only `np.ndarray`.

**Recommendation:** keep the change; either add a one-line
`assert gray.dtype == np.uint8 and gray.ndim == 2`, or reword the
docstring from "the input is 8-bit" to "this REQUIRES 8-bit
single-channel input, and silently returns a channel-0 answer otherwise".

### 2. The residual parity test is ~4× from failing, not orders of magnitude

MEASURED over 400 realistic working sets (5 cameras × 44 points,
observations generated from a known Sim(3)):

- the two paths are **bit-identical 0 / 400 times**
- max **absolute** divergence **1.374e-07 px**
- max divergence relative to residual magnitude **1.589e-13**

`np.allclose(rtol=1e-9, atol=1e-9)` at pixel-scale residuals (|b| up to
~500 px) permits ~5e-7 px. Measured worst case is 1.37e-7 px — a **3.6×
margin**, resting on one fixed seed. A different seed, more points, or
larger residuals could flake it.

`@` on (3,3)@(3,K) goes through BLAS; `einsum("nij,nj->ni", ...)` does
not. They are not required to agree bitwise and they don't.

**Recommendation:** assert the scale-invariant property instead —
`max|a-b| <= 1e-12 * max|a|` — which is ~10⁵ tighter than the current
test *and* stable across seeds.

### 3. "Registration output was identical" is true of one world, not of the change

The brief asked whether a 1e-9 tolerance is safe inside
`if probe_cost < cost`. MEASURED by running the **whole** `_refine` both
ways (shipped packed path vs a byte-for-byte copy using the reference
residual) over 80 problems generated from a known Sim(3):

- **0 / 80 converged bit-identically**
- max `|param|` divergence **1.405e-09**
- max relative cost drift **1.299e-11**
- max scale drift **0.0006 ppm**

So the step-acceptance branch *does* diverge, and the converged Sim(3)
moves. The magnitude is ~1e-9 on metre-scale translations — nanometres —
against admission gates at 4 px and whole degrees, so no gate can
plausibly flip. **Determinism is preserved** (same code, same answer
every time); only the value shifted, once, at the change.

**Recommendation:** wording only. Say "agrees to ~1e-9 and re-derived
the same admissions on the tested worlds", not "output identical".

---

## Findings that change wording

### 4. "Native OpenCV totals 25.29 s = 79.1%" is not what was measured

`profile_split.py` classifies NATIVE as `filename == "~"`, which its own
docstring describes as "every `cv2.*`, **every numpy ufunc and linalg
entry point, every builtin**". Two consequences:

- The table's own native rows sum to **22.911 s** (MEASURED by addition),
  not 25.29 s. 2.38 s of the headline is in rows that are not shown, so
  the figure cannot be reconstructed from the evidence given.
- Counting numpy as un-migratable is the one tendentious step, and the
  lane's own sharpness win refutes it: eliminating numpy `_var` (1.302 s)
  is precisely a "native" cost being removed by better dispatch.

The share is real and the conclusion is unaffected. The **label** is
wrong: it is "time in compiled code", not "native OpenCV".

### 5. The cProfile direction claim SURVIVES, and it is worth more than claimed

The brief asked me to verify that cProfile's inflation makes the native
share an UNDER-estimate. MEASURED on a workload with a known split
(pure-Python loop + `GaussianBlur`), true wall-clock split vs cProfile
split classified exactly as `profile_split.py` does:

| mix | true native | cProfile native | direction |
|---|---|---|---|
| very python-heavy | 5.2% | 4.5% | UNDER |
| python-heavy | 18.7% | 17.4% | UNDER |
| balanced | 47.1% | 45.1% | UNDER |
| native-heavy | 82.8% | 78.6% | UNDER |

Under-estimates in **all four**. At the native-heavy end the gap is ~4
points, so the product path's true native share is plausibly ~83% rather
than 79.1%. **This strengthens the refusal.**

### 6. The 1.74× ceiling is arithmetically right; 94% is the flattering framing

MEASURED by recomputation: 6.409 / (6.409 − 2.724) = **1.7392** ≈ 1.74×.
Amdahl applied correctly to cumtime, which is the right column.

But "1.64× is 94% of 1.74×" is a **ratio of speedups**. By time actually
removed: 6.409 / 1.64 = 3.908 s, so 2.501 s of the 2.724 s removable was
removed = **91.8%**. Both are defensible; 94% is the higher of the two.
Either is far above the noise floor and neither changes the verdict.

### 7. Internal inconsistency in the redaction share

§1 says face redaction "is 22.8% of the runtime"; §2.1 and §5 say
**33.6%**. One of them is stale.

### 8. The orjson rejection gives a reason that is partly wrong

`storage.py` says orjson "would silently defeat the `allow_nan=False`
guard callers rely on". MEASURED by grep: exactly **one** caller has that
guard — `world_builder/store.py:463`, placements — and it is a
**separate `json.dumps(payload, allow_nan=False)` executed before**
`write_json_atomic`. Changing the encoder *inside* `write_json_atomic`
would not defeat it. Every other caller has no such guard to defeat.

The conclusion (don't adopt orjson — the bytes differ) is correct. The
stated reason is not.

### 9. A quoted precision figure is slightly understated

"max 4.1e-16 relative" was measured on 120 frames. MEASURED over all
**9,372** corpus frames: max relative **6.22e-16**, max absolute
6.82e-13. Immaterial, but it is the number that should be quoted.

---

## What survived, and what I did to try to break it

### The GIL conclusion — 82.7% on a re-run, and it is robust

The machine could **not** be made quiet: other agents were running
throughout (measured 55–75% total CPU, many live `claude`/`python`
processes). Rather than report a number I could not defend, I made the
measurement **self-calibrating** by adding a positive control — a second
pure-Python CPU hog in the same process, which provably holds the GIL and
therefore establishes what "collapsed" looks like *on this machine under
this load*. Three interleaved rounds
(`scripts/research/native_adversarial/gil_contention_controlled.py`):

| | rate | retained |
|---|---|---|
| NEGATIVE CONTROL — spinner alone | 46,025,802 /s | 100.0% |
| **SUBJECT — spinner during replay** | **38,080,395 /s** | **82.7%** |
| POSITIVE CONTROL — spinner + GIL holder | 21,412,064 /s | 46.5% |

Per-round retention: 68.4% / 91.9% / 82.7% (median 82.7%). The positive
control lands at 46.5%, almost exactly the 50% two-pure-Python-threads
prediction, which is what a real GIL bottleneck measures here.

**82.7% against a 46.5% floor is clean separation.** The quoted 86.9%
was ~4 points optimistic, and the spread across rounds is wide because
the machine is noisy — but every single round sits far above the
collapse floor. **The GIL conclusion holds.**

Caveat worth recording: replay wall time was 311–443 s (median 359 s)
against the 32 s quoted for this capture — an ~11× inflation from ambient
load plus the competing spinner. **The absolute time from this run is
unusable; only the ratio is.** That is precisely why the positive control
was added.

### The sharpness change is safe — and on the absolute floor, provably so

I tried hard to construct the decision flip the brief asked for. It
cannot exist at product resolution, and here is why.

**The lattice argument.** The CV_16S Laplacian is an *integer* array, so
the variance of N values is exactly
`(N·Σx² − (Σx)²) / N²` — an integer over N². Every achievable sharpness
therefore lies on a lattice of spacing 1/N². MEASURED:

| resolution | N | lattice spacing | spacing / eps(25.0) |
|---|---|---|---|
| **product 360×640** | 230,400 | **1.884e-11** | **5,302×** |
| 1080p | 2,073,600 | 2.326e-13 | 65× |
| hypothetical 30 MP | 30,250,000 | 1.093e-15 | 0.31× |

At product resolution the lattice is **5,300× coarser than one float64
ULP at 25.0**. An achievable sharpness is either ≥ 25 by at least
1.9e-11 or < 25 by at least that much, so a ~1e-15 implementation
discrepancy **cannot** move a value across the bar. The only flippable
case is a value landing *exactly* on 25.0 — and I constructed arrays with
variance exactly 25.0 and both reductions agreed. Note the guarantee is
resolution-dependent: it weakens at 1080p and **fails above ~30 MP**.

**The empirical margin, on the whole corpus.** All 8 pinned captures,
**9,372 real frames**, replaying the exact
`KeyframeGate._is_sharp_enough` logic under both implementations
(`scripts/research/native_adversarial/sharpness_margins.py`):

| | |
|---|---|
| frames examined | **9,372** |
| **gate decisions that flipped** | **0** |
| sharp-enough count old / new | **7,070 / 7,070** |
| max abs / rel discrepancy | 6.82e-13 / 6.22e-16 |
| **min safety factor, absolute floor** | **4.881e+12×** |
| **min safety factor, rolling ratio** | **3.037e+11×** |

The closest any real frame came to the floor was `b35d8ab8/00002784.jpg`
at 24.96532 — a margin of 3.5e-2 against a 7.1e-15 discrepancy. The
closest ratio was `22e9d428/00003292.jpg` at 0.549966 — margin 3.4e-5
against a 1.1e-16 discrepancy. Frames *do* approach the ratio bar; they
approach it eleven orders of magnitude further away than the change can
reach.

This is a stronger result than the lane's own: it replaces "the counts
matched" with "here is how much room there was", corpus-wide.

Also checked and identical: uniform images, 1×N, N×1, 1×1, 2×2,
non-contiguous stride-2 views, transposed views. Empty arrays raise
identically in both. One incidental note: numpy's `.var()` was **exact**
on the test array while `meanStdDev`-then-square was 1 ULP off, so the
new form is marginally *less* accurate — irrelevant at these margins.

### The JSON change survives byte-identity outright

MEASURED — `json.dump(obj, f)` vs `f.write(json.dumps(obj))`, byte-compared:

unicode + astral + control characters, 400-deep nesting, floats needing
repr round-trip (`5e-324`, `1e-300`, `-0.0`, `2**-53`, DBL_MAX), ints
beyond 2^53 up to `10**40`, `None`/bools/empty containers, **NaN and
±Infinity**, coerced dict keys, a 2 MB string. **IDENTICAL in every
case.** A 100,000-deep payload raises `RecursionError` from *both*. They
share the same encoder and the same defaults, so this is what should
happen — but it is now checked rather than assumed.

**Blast radius is narrower than the brief feared.** MEASURED by grep:
`object_memory` and `document_memory` do **not** use `write_json_atomic`
(object_memory has its own `json.dump` at `store.py:283`; document_memory
imports only `new_id`/`append_jsonl`/`read_raw_jsonl`). Real callers are
`capture.py` (small bounded manifests), `intrinsics_store` (one dict),
and `world_builder/store.py`.

**Nothing can observe a partial write.** Both forms write to `path.tmp`
and `os.replace` only after `flush` + `fsync`, so the change moves bytes
around strictly inside the temp file's lifetime.

**The materialisation cost is real but mis-stated in the comment.**
MEASURED peak traced memory:

| payload | dump | dumps |
|---|---|---|
| 6.42 MB doc (75k points) | 9.42 MB | 16.04 MB |
| 66.77 MB doc (750k points) | 71.49 MB | **166.92 MB** |

The extra peak is ~1.0–1.4× the document size, not the ~1× the comment
implies. At the measured 1.71 MB maximum this is ~2 MB and genuinely
negligible — the comment's own "a future caller writing something an
order of magnitude larger should revisit it" is exactly right, and the
750k row is the number that justifies it.

### The pack does not alias, and the reference is not dead

- MEASURED with `np.shares_memory`: `_pack` copies **all four** inputs
  (`object_points`, `image_points`, `r_target`, `t_target`), single- and
  multi-observation. No aliasing.
  *Gap:* the shipped `test_the_pack_does_not_alias_its_inputs` checks
  **only `object_points`**. It passes for the right reason, but it would
  not catch aliasing in the other three.
- *Gap:* `test_the_inputs_are_not_mutated` calls only `wreg._residuals`
  — the **reference** — while its docstring describes the 38,483-call
  packed hot path. It does not exercise `_pack`/`_residuals_packed`.
- `params` is never mutated in place (`probe = params.copy()`;
  `params, cost = probe, probe_cost`). The pack is never written to.
- `_residuals` is **live**, called at `scripts/world_registration.py:819`
  for the quality report. Not dead code.

### Removability — the tests pin requirements, not implementations

- **Sharpness:** I reverted `measure_sharpness` to
  `cv2.Laplacian(gray, CV_64F).var()` and ran the new tests. **11 passed,
  0 failed.** They assert *equivalence to the reference*, so they pin a
  requirement and would survive a revert. This is the correct answer to
  the brief's question.
- **JSON:** reverted `storage.py` to `json.dump(payload, handle)` —
  `tests/test_world_builder_store.py` **27 passed**.
- **Registration:** the parity tests name `_residuals_packed` directly,
  so removing it breaks them by symbol, not by encoding a performance
  requirement. That is appropriate for a reference/optimised pair.
- Full affected suite at HEAD: **88 passed** across
  `test_world_builder_frontend.py`,
  `test_world_registration_residual_parity.py`,
  `test_world_builder_store.py`.

Both temporary reverts were restored and verified with `git diff`
(clean against HEAD). Nothing under `tower/tower/` was left modified;
`ios/` was not touched.

---

## Verification code

All new code is under
`tower/scripts/research/native_adversarial/`:

| file | what it attacks |
|---|---|
| `gil_contention_controlled.py` | GIL, with a positive control so ambient load cannot fake it |
| `sharpness_torture.py` | dtype/channel/degenerate-shape preconditions |
| `sharpness_lattice.py` | the absolute floor is unflippable — lattice argument |
| `sharpness_margins.py` | corpus-wide flip search and safety factors, 9,372 frames |
| `json_torture.py` | byte-identity on hostile payloads; materialisation cost |
| `registration_numerics.py` | true divergence, aliasing across all four fields |
| `registration_numerics2.py` | divergence in pixels; full-refine Sim(3) stability |
| `cprofile_direction.py` | does cProfile under-estimate the native share |

---

## Bottom line

I could not break the refusal. The one leg I could have broken — the GIL
claim, which was taken on a saturated machine — re-measures at **82.7%
against a 46.5% positive control**, and holds. The cProfile direction
claim not only survives but was under-sold. The ceiling arithmetic is
correct.

The riskiest change, sharpness, turns out to be the best-defended one:
safe by a **4.9e12×** margin on the floor and **3.0e11×** on the ratio
across every frame in the corpus, and *provably* unflippable on the floor
at this resolution. Its real weakness is not numerical at all — it is
that the exactness argument is a precondition nobody enforces, and the
colour-image path returns a wrong number instead of raising.

Nothing here should be reverted.
