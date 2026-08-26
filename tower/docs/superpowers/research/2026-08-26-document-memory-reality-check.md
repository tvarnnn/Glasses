# Document Memory — Reality Check on Real Ray-Ban Footage

Status: **THE PREMISE DOES NOT SURVIVE CONTACT WITH REAL DATA.** Branch
`integration/world-builder-lifecycle-v1`.

Document Memory shipped 7 modules, ~1,843 lines and 145 tests without
ever seeing a real frame. `data/document_memory/` has never existed on
this machine. Every figure in the 2026-08-22 V1 report came from
synthetic rendered pages.

This is the first run against `data/captures/` — **9,199 real Ray-Ban
frames, all 360×640 portrait, across 18 captures.** Nothing was written:
the sweeps read the corpus and print, and no `data/document_memory/`
directory was created.

Two questions were open. Both are now answered, and the answer to the
first makes the second almost beside the point.

---

## 0. What was installed, and what it did not break

`easyocr==1.7.2`, into the existing `[ocr]` extra. The 2026-08-26
dependency study exonerated it and the install confirms that exoneration:

| Check | After install |
|---|---|
| `pip check` | **No broken requirements found** |
| cv2 distributions present | **one** — `opencv-python-headless 5.0.0.93` |
| `cv2.__version__` | **5.0.0** (unchanged) |
| `numpy` | **2.5.2** (unchanged) |
| `torch` | **2.13.0+cu132**, `cuda.is_available() == True` (unchanged) |

A `--dry-run` before installing showed the transitive set — `scipy`,
`scikit-image`, `imageio`, `tifffile`, `lazy-loader`, `ninja`,
`pyclipper`, `python-bidi`, `shapely` — and **no `opencv-python`**. The
`rapidocr_onnxruntime` breakage the V1 report recorded did not recur.

It is now **pinned**, for the reason the `ml` extra pins torch: the
version is load-bearing on a measurement (§3 reproduces two published
rows against exactly this version).

**A side effect worth recording.** `scikit-image` arriving as an easyocr
dependency un-gated 12 previously-skipped tests —
`tests/test_world_builder_redaction.py` and one pose-accuracy test, both
of which `importorskip("skimage.data")` for sample faces. All 12 pass.
The suite went 1307 passed / 32 skipped → **1319 passed / 30 skipped / 0
failed**.

The opt-in real-model suite was also run for the first time with real
weights: `TOWER_RUN_MODEL_TESTS=1 pytest
tests/test_document_ocr_integration.py` → **14 passed**. The recogniser
seam works. That is not the problem.

---

## 1. The finding: the detector fires on 6 frames in 9,199, and all six are wrong

```
frames walked                     9,199
frames where detect_page() fired      6
detection rate                   0.065%
```

Six. And OCR was then run on all six warped crops:

```
regions returned    0   0   0   0   0   0
characters          0   0   0   0   0   0
```

**Every one of the six is a false positive.** Rendered with their
detected quad outlined, they are:

| Capture | Frames | What it actually is |
|---|---|---|
| `22e9d428…` seq 569 | 1 | a **venetian blind** over a kitchen window |
| `b5a0d654…` seq 1109–1117 | 5 | a **backlit laptop keyboard** |

This directly contradicts the V1 report's headline defence of the glyph
gate. That table — reproduced from the module docstring in
`tower/document_memory/detect.py` — claims:

```
    rendered text   43 - 86
    blinds           0
    bricks           0
    floor tiles      0
    striped shirt    0
    keyboard         0
```

Measured on **real** frames, the same statistic reads:

| Surface | Published (synthetic) | Measured (real) |
|---|---|---|
| venetian blind | 0 | **8.0** — exactly at `MIN_ROW_TRANSITIONS = 8` |
| laptop keyboard | 0 | **19 – 23** |

The "order of magnitude below the text floor and well above every
structure measured" margin is an artefact of the renderer. A real slat
has a rail, a bracket, a gap and a highlight; a real backlit keyboard is
literally a grid of small light patches separated by dark gaps — which is
a tolerable description of a line of glyphs. The gate was tuned against
structures that were too clean to be structures.

### Where the 9,199 frames actually die

Every gate in `detect_page`, instrumented without modifying it:

| Stage | Frames reaching it | Quad candidates |
|---|---|---|
| any contour | 9,112 | 1,429,163 |
| area ≥ 6% of frame | 3,848 | 5,608 |
| 4-point **and convex** | 485 | 1,434 |
| solidity ≥ 0.85 | 455 | 1,399 |
| aspect in [0.25, 4.0] | 453 | 1,395 |
| `text_row_fraction` ≥ 0.08 | 341 | 977 |
| `ink_fraction` in [0.004, 0.60] | 339 | 357 |
| `row_transitions` ≥ 8 | **6** | **8** |

The first cliff is at `4-point and convex`: **1.43 M contours collapse to
1,434 quads, and 9,199 frames collapse to 485.** Only 4.9% of real frames
contain anything the detector will even consider page-shaped.

Signal distribution over the 1,395 surviving quads:

| Statistic | min | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| `text_row_fraction` | 0.000 | 0.233 | 0.303 | 0.311 | 0.467 |
| `ink_fraction` | 0.014 | 0.722 | 0.753 | 0.868 | 0.983 |
| **`row_transitions`** | **0.0** | **0.0** | **2.0** | **5.0** | **26.0** |
| `area_fraction` | 0.060 | 0.083 | 0.114 | 0.178 | 0.261 |

`row_transitions` — the glyph gate, the module's whole thesis — has a
**median of zero** across every page-shaped region in the corpus. Not a
low value. Zero.

### One hypothesis tested and rejected

The corpus is full of screens, and `measure_text_likeness` thresholds
`THRESH_BINARY_INV`, so on a dark-mode terminal the "ink" it counts is
the *background* — which fits the observed `ink_fraction` median of
0.722, above the 0.60 cap. The obvious story is "the detector has the
wrong polarity for the documents that are actually there."

**That story is wrong, and it was worth checking rather than asserting.**
Re-running the three text gates on the inverted probe:

```
quad candidates                              1,395
pass the text gates as written                   8
pass the text gates at inverted polarity         8
fail ONLY the ink cap                            0
```

Inverting polarity changes nothing. The 620 candidates the ink cap
rejects would all have died at the glyph gate anyway, so the cap is not
load-bearing either. The detector is not mis-polarised. It simply is not
being shown pages.

### The cheap path is cheap, and that is the one thing that held

`detect_page` on real 360×640 frames: **median 0.771 ms, p95 1.92 ms.**
The V1 report predicted 2.62 ms at 640×360 with a page in view. Real
frames are faster because almost nothing survives as far as the warp. The
architecture's 400× cost ratio is sound. The expensive stage really is
rare — it is just rare because it never fires, not because it fires
selectively.

---

## 2. What OCR returns on real frames — and this is NOT a recall measurement

There are no ground-truth transcripts for this corpus. Nothing in this
section is compared against a known string, and **no recall number is
reported for real footage.** What follows is what can be observed
honestly without ground truth.

Because the detected path returned six empty results, an **independent
witness** was needed: without one, "the detector never fires" is
indistinguishable from "the corpus contains no documents." Every 10th
frame was therefore OCR'd whole and unwarped, bypassing detection
entirely.

| | detected path | full-frame control |
|---|---|---|
| frames OCR'd | 6 | 919 |
| frames returning **any** text region | **0** (0.0%) | **35** (3.81%) |
| median regions when text | — | 1 |
| median characters when text | — | 8 |
| mean of per-frame mean confidence | — | **0.175** |
| median of per-frame mean confidence | — | **0.056** |
| tokens returned across the sample | 0 | 85 |
| of those, alphabetic and ≥3 letters | 0 | 12 |
| of those, **actual dictionary words** | 0 | **0** |

Zero recognisable English words in 919 sampled real frames.

Verbatim, the highest-character-count outputs — these are the *best* the
corpus produced:

```
'lESN W A R E'      conf 0.116
'E N W A R E'       conf 0.220
'1enINIA R E'       conf 0.004
'3EnWNA R E'        conf 0.006
'SENNA R E'         conf 0.056
'00 00 000'         conf 0.722
```

The recurring string is a disintegrating read of **ALIENWARE**, the brand
logo silk-screened on a monitor bezel in one capture. That logo is the
single most legible piece of text in 9,199 frames of first-person
footage. The `'00 00 000'` is a ChArUco calibration board.

### What is in the corpus, and why that matters

A visual review of 51 frames sampled across all 18 captures (quartile
positions within each) shows the corpus is: **laptop screens** (dark-mode
terminals and chat), **phone screens** held in hand, **ChArUco
calibration boards**, and **walls, doors, ceilings and carpet**.

**There is not a single sheet of paper in any sampled frame.**

This is a genuine confound and it must be stated plainly: a 0.065%
detection rate on a corpus containing no paper documents is not by itself
proof that the detector fails on documents. It proves two other things
instead, and both are damaging:

1. **The corpus that exists cannot validate this cartridge.** Document
   Memory's acceptance gate — "nothing counts as validation for the
   platform's own camera until it runs on real DAT footage" — cannot be
   met with the footage that exists. These captures were recorded for
   World Builder, and they show a wearer looking at screens and walls.
2. **On 9,199 frames of ordinary indoor life, the detector's precision is
   0/6.** Every time it spoke, it was wrong. That number does not depend
   on the corpus containing documents; it is a false-positive rate
   measured against the real world, and it is 100%.

And the full-frame control settles the harder question. The corpus *does*
contain enormous quantities of text — every one of those laptop and phone
screens is dense with it — and at 360×640, **EasyOCR cannot read any of
it.** 3.81% of frames yield a region, at median confidence 0.056, and not
one dictionary word. The text is there. The pixels are not.

---

## 3. Portrait versus landscape — the question this exercise existed to settle

The published ladder used **landscape** frame sizes. Every real frame is
**360×640 portrait**. The 2026-08-25 plan flagged that "the real
delivered case may be **worse than the worst row in the table**, and
nobody has checked."

Checked. Using the same renderer (`tests/document_fixtures.py`), the same
metric (`word_recall` from `scripts/document_memory_benchmark.py`), the
same three documents and the same three tilts — so this **is** a recall
measurement, with ground truth, directly comparable to the published
rows.

Two portrait placements are reported, because the harness's default
corners stretch the page to fill the frame:

- **fill** — the harness default, the same treatment the published rows
  got, so the comparison is like-for-like.
- **aspect-fit** — the page placed at its own 800×1040 aspect inside the
  frame, which is what a real page in a portrait view looks like.

| Geometry | Warped page | Word recall | Mean |
|---|---|---|---|
| 1280×720 landscape *(published 0.957–1.000)* | 796–1026 × 636 | **0.957 – 1.000** | 0.986 |
| 640×480 landscape *(published 0.905–1.000)* | 399–514 × 424 | **0.905 – 1.000** | 0.947 |
| **640×360 landscape** *(published 0.429–0.810)* | 399–514 × 318 | **0.400 – 0.762** | 0.572 |
| **360×640 portrait — what the glasses deliver** | 226–290 × 564 | **0.343 – 1.000** | **0.703** |
| 360×640 portrait, aspect-fit | 261–318 × 414 | 0.629 – 0.952 | 0.820 |
| 504×896 portrait — DAT's middle rung | 316–404 × 790 | **0.886 – 1.000** | 0.952 |
| 504×896 portrait, aspect-fit | 365–446 × 578 | 0.957 – 1.000 | 0.991 |
| 720×1280 portrait — DAT's top rung | 450–578 × 1128 | **0.943 – 1.000** | 0.989 |
| 720×1280 portrait, aspect-fit | 522–636 × 826 | 0.979 – 1.000 | 0.995 |

**The two published rows that were re-measured reproduce.** 640×480 comes
back 0.905–1.000 and 1280×720 comes back 0.957–1.000, both identical to
the report. The 640×360 row lands at 0.400–0.762 against a published
0.429–0.810 — a small shift consistent with running EasyOCR on GPU rather
than CPU. It is the same axis.

### The answer, and it is not the simple one

**Yes — portrait's worst case falls below the worst published row.**
0.343 against 0.429. The prior study's suspicion is confirmed at the
tail.

**But portrait's mean is better than landscape's, not worse.** 0.703
against 0.572, and square-on portrait is dramatically better:

| Document, tilt 0 | 640×360 landscape | 360×640 portrait |
|---|---|---|
| paper | 0.468 | **0.915** |
| notes | 0.457 | **0.971** |
| receipt | 0.762 | **1.000** |

The two geometries carry the same pixel count and fail differently.
Landscape squashes a portrait page to 514×318 — every line of body text
crushed to about 10 px tall, uniformly bad at every tilt. Portrait keeps
the height (564 px) and starves the width, so a square-on page reads
almost perfectly and a *tilted* one collapses, because the harness's tilt
shears width away: 290 px at tilt 0, **226 px at tilt 1.0**, where recall
drops to 0.343.

So the honest one-line summary is: **portrait beats the published worst
row when the wearer faces the page, and falls below it when the wearer
does not.** Since a wearer reading a document usually does face it, the
aspect-fit portrait row — **0.629–0.952** — is the fairest single
estimate of the delivered geometry, and it sits above the published worst
row throughout.

**And none of it matters,** because §1 is upstream of all of it. This
entire table describes what would happen *if a page were detected*. Six
times in 9,199 frames one was, and all six were blinds and keyboards.

---

## 4. Verdict

**Not viable as-is. Viable with a capture change, and the capture change
is smaller than it looks.**

Ranked by what actually blocks:

**(1) Detection, not recognition, is the binding constraint — and this
inverts the V1 report's conclusion.** That report says *"Page detection
still works at 640×360. Only recognition is starved, which narrows the
requirement usefully."* Measured on real frames, the opposite holds.
Detection fires 6 times in 9,199 frames and is wrong all 6 times.
Recognition never got the chance to be starved. The requirement is not
narrow; it is the entire cheap path.

**(2) The glyph gate's margin does not exist outside the renderer.**
Blinds measured 8.0 and keyboards 19–23 against a documented 0 for both,
with a threshold of 8. Any real deployment ships those false positives.
`MIN_ROW_TRANSITIONS` was chosen from a distribution real surfaces do not
obey, and re-deriving it needs real negatives — which now exist: 9,199 of
them, containing at least one blind and several keyboards that must land
below whatever threshold replaces it.

**(3) 360×640 cannot read the text that is genuinely in frame.** Not a
synthetic claim — 919 real frames, dense with screen text, produced zero
dictionary words at median confidence 0.056.

**(4) Every published resolution row describes a geometry the hardware
cannot deliver.** `docs/agent-handoffs/WORLD-BUILDER-STATUS.md` §2.4:
*"DAT offers 720×1280 / 504×896 / 360×640, all 9:16. No landscape mode at
any resolution."* 1280×720, 896×504 and 640×480 are **not options**.
Three of the four rows in the V1 report's headline table are unreachable,
and that ladder should be replaced by the portrait one in §3.

### What would have to change

**Do not raise the stream resolution.** That is the cross-cartridge
tension, and it is already measured against us.
`WORLD-BUILDER-STATUS.md` §2.4 records: *"Would 720p help tracking? **No
— it would hurt.** Halving resolution improved survival 0.874→0.930 … at
720p **73.3%** of frames fall below `min_sharpness = 25.0` and are
rejected as blurred."* Raising the stream to fix Document Memory would
break World Builder's tracking, which is the cartridge that currently
works.

**The tension dissolves, because Document Memory does not need the
stream.** Its own architecture says so: the pipeline exists to make the
expensive stage rare, and a test pins *at most two* OCR calls per dwell.
It needs **one or two high-resolution stills**, not a high-resolution
video stream. That is precisely the "bursty / stability-gated capture"
idea already sketched in the 2026-08-25 plan, and §3 now prices it:

- a **504×896** still — DAT's *middle* rung, not the top one — buys
  **0.886–1.000** recall (0.957–1.000 aspect-fit), against 0.343–1.000 at
  the delivered rung.
- 504×896 has **never been measured against World Builder.** The 720p
  finding is about 720×1280 specifically. If bursty stills prove
  impossible and a stream change is forced, the middle rung is the
  unmeasured option and the experiment worth running.
- 720×1280 buys 0.943–1.000, but only as a still. As a stream it is ruled
  out.

**Then re-derive the glyph gate against real negatives, and re-run this
sweep on a corpus that contains paper.** Both are prerequisites, and the
second is not optional: no capture in `data/captures/` shows the wearer
looking at a document, so even a perfect detector could not be validated
against it. Someone has to wear the glasses and read a page.

Until such a capture exists, **Document Memory's premise is untested
rather than disproved** — but its detector's behaviour in ordinary indoor
life is now measured, and it is six firings, all false.

---

## 5. Provenance

Every number above is a measurement taken on this host on 2026-08-26. The
sweeps reuse `scripts/capture_corpus_benchmark.py`'s `iter_capture_frames`
and `scripts/document_memory_benchmark.py`'s `word_recall` rather than
introducing a fourth harness. No file under `tower/document_memory/`, no
World Builder code, no wire contract and no iOS file was modified; the
only source change accompanying this report is the `easyocr` pin in
`pyproject.toml`. Nothing was persisted to `data/`.

| Measurement | How |
|---|---|
| detection rate, gate attrition, signal distributions | `detect_page` over all 9,199 frames, plus a non-mutating mirror of its gate chain |
| false-positive identification | detected quad drawn on the source frame and inspected |
| real-frame OCR | `EasyOcrRecogniser(gpu=True)` on the 6 warped crops and on every 10th raw frame (919) |
| polarity hypothesis | the three text gates re-run on `255 - page` for all 1,395 quad candidates |
| portrait recall | `tests/document_fixtures.py` renderer, `word_recall`, 3 documents × 3 tilts × 9 geometries |

Suite at time of commit: **1319 passed, 30 skipped, 0 failed** (274 s),
plus **14 passed** in the opt-in `TOWER_RUN_MODEL_TESTS=1` real-model
suite.
