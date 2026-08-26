# Re-deriving Document Memory's Glyph Gate Against Real Negatives

Status: **RE-DERIVED, AND THE METRIC IS WORSE THAN THE OLD NUMBER WAS.**
Branch `integration/world-builder-lifecycle-v1`, from `baec44a`.

`2026-08-26-document-memory-reality-check.md` is the authority for why
this was needed and every figure in §1 below reproduces it exactly. Its
closing instruction was: *"re-deriving it needs real negatives — which
now exist: 9,199 of them, containing at least one blind and several
keyboards that must land below whatever threshold replaces it."*

Done. The threshold moved from **8 to 31**, both edges of the derivation
are now measured and written into `detect.py`, and the corpus false
positive count went **6 → 0**.

**But the headline is not the number.** Re-deriving the gate turned up
something the old derivation had no way to see: on real frames,
`row_transitions` **does not separate text from structure.** It separates
large crops from small ones. Every genuine line of text in 9,199 frames
scores **below** the corpus's hardest negative. The threshold is
derivable only because a second, unrelated fact happens to coincide at
360×640, and §4 is about how narrow that coincidence is.

---

## 1. What the real negatives measure

`detect_page`'s gate chain, mirrored without modifying it, over all
**9,199 frames / 18 captures / 360×640**. Nothing was written; `data/`
was read only.

| Stage | Frames | Quad candidates |
|---|---|---|
| reach the text-likeness probe | 453 | **1,395** |
| pass `text_row_fraction` ≥ 0.08 and the ink band | — | 357 |
| pass `row_transitions` ≥ 8 *(old gate)* | **6** | **8** |

`row_transitions` over the 1,395, in full — this is the complete real
negative distribution, not a summary:

| value | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 8 | 13 | 19 | 21 | 23 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| count | 723 | 100 | 549 | 5 | 4 | 3 | 2 | 1 | 1 | 2 | 1 | 2 | 1 | 1 |

min 0 · p50 **0** · p90 2 · p95 2 · p99 **5** · max **26**

### Where each surface actually lands

Every candidate above 2 was rendered with its quad outlined and
identified by eye. The 0–2 bulk was sampled the same way.

| Surface | `row_transitions` | Where |
|---|---|---|
| blank wall, door, ceiling, carpet | **0** | everywhere |
| ChArUco marker cells, blank desk | **0 – 2** | `e1c52b…`, the calibration captures |
| **a laptop screen full of text** | **0.0** | `b901bc…/3055` — see §2 |
| venetian blind, oblique | 3 – 6 | `22e9d4…/549-573` |
| **venetian blind, square on** | **8.0** | `22e9d4…/569` — *exactly the old threshold* |
| **backlit laptop keyboard** | **19 – 26** | `b5a0d654…/1109-1117` |

Both published rows from the reality check reproduce: blind 8.0,
keyboard 19–23 (the full run reaches 26). The old comment claimed 0 for
both.

The keyboard is not a freak. A backlit keyboard is a grid of ~15 px light
patches separated by dark gaps, and "many short runs per row with gaps
between them" is the definition the gate was built on. It is a correct
reading of a keyboard by a metric that thinks keycaps are glyphs.

---

## 2. The real positives, and the finding

The corpus contains **no paper** — the reality check established that
with a visual review of 51 frames across all 18 captures, and nothing
here contradicts it. So positives come from two places, and every
conclusion below says which.

### (a) Real screens — 13 crops, 10 frames, 8 captures

The corpus is dense with laptop and phone displays showing real text.
Twelve crops were read off a coordinate grid by hand and verified by
looking at the warped result; the thirteenth is `b901bc…/3055`, where
**`detect_page`'s own contour stage proposed the quad** — it found the
screen unaided. There is no transcript for any of them, so nothing here
is a recall measurement; the ground truth is only "a human confirms this
crop is text."

Both ink polarities are reported, because `measure_text_likeness`
thresholds `THRESH_BINARY_INV` and counts *dark* pixels as ink. Paper is
dark-on-light and matches. Every screen in this corpus is dark-mode.

| Frame | What | as written | inverted |
|---|---|---|---|
| `64f481…/723` | laptop screen | 0.0 | 6.0 |
| `69030f…/803` | laptop screen | 0.0 | 3.0 |
| `2e6cff…/733` | laptop screen | 0.0 | 6.0 |
| `2e6cff…/1212` | laptop screen | 0.0 | 4.0 |
| `b35d8a…/1` | laptop screen | 0.0 | 6.0 |
| `b35d8a…/1` | phone screen | 0.0 | 5.0 |
| `341b0f…/251` | laptop screen | 2.0 | 1.0 |
| `341b0f…/251` | phone screen | 0.0 | 7.0 |
| `68a7c7…/1` | laptop screen | 0.0 | **8.0** |
| `68a7c7…/1` | phone screen | 0.0 | 4.0 |
| `0f0c55…/1821` | phone screen | 0.0 | 3.0 |
| `b1ab1d…/869` | laptop screen | 0.0 | 4.0 |
| `b901bc…/3055` *(machine-proposed)* | laptop screen | 0.0 | — |

**as written: 0 – 2, median 0. Inverted: 1 – 8, median 5.**

**This is the finding.** The real positives sit *below* the real
negatives. A backlit keyboard scores 26; the best of these thirteen real
screens scores 8, and that only after flipping the polarity. The
distributions do not merely overlap — the order is inverted, and no
threshold anywhere on this statistic reverses it. Thirteen crops is a
small positive set, and it is every one that could be built from a
corpus with no paper in it; the claim it supports is about the order of
the two populations, not about a percentile.

Polarity is not the explanation. At 360×640 a laptop screen occupies
about 200×140 px and its glyphs are roughly two pixels tall. After the
480×360 probe resize and Otsu the crop binarises into blocks, not
glyphs. The detail is gone before polarity gets a say.

### (b) The renderer, at the geometry the glasses deliver

`tests/document_fixtures.py`, three documents, 360×640 portrait, JPEG
q70, page centred at its own aspect. `row_transitions` measured at the
ground-truth corners so a detection miss cannot hide the signal:

| page in frame | area | paper | notes | receipt |
|---|---|---|---|---|
| 324×421 | 59.2% | 73 | 71 | 40 |
| 260×338 | 38.1% | 63 | 65 | 36 |
| 200×260 | 22.6% | 52 | 53 | 34 |
| 160×208 | 14.4% | 41 | 42 | **24** |
| 120×156 | 8.1% | 32 | 34 | 18 |
| 90×117 | 4.6% | 18 | 18 | 12 |

**The same rendered page, unchanged in content, spans 40 → 24 → 12 as it
shrinks — straight through the keyboard's 19–26.** The gate is measuring
how many pixels the crop has. That is why the old derivation looked so
clean: the renderer only ever showed it pages filling the frame.

Blur says the same thing from a different direction. One full-frame page,
Gaussian kernel 0 → 15: **74, 56, 41, 24, 18, 14.** A blurred page lands
in the keyboard's band too.

---

## 3. The derivation

The overlap in §2 is real and is not being papered over. What makes a
threshold derivable anyway is that at 360×640 the pages inside the
overlap are pages **OCR cannot read**. Ground truth is available here —
the renderer chose the string — so this is a recall measurement:

| page in frame | area | `row_transitions` | `word_recall` |
|---|---|---|---|
| paper 324×421 | 59.2% | 73 | 0.894 |
| notes 324×421 | 59.2% | 71 | 0.886 |
| receipt 324×421 | 59.2% | 40 | 1.000 |
| paper 260×338 | 38.1% | 63 | 0.511 |
| notes 260×338 | 38.1% | 65 | 0.400 |
| **receipt 260×338** | 38.1% | **36** | **0.714** |
| paper 200×260 | 22.6% | 52 | 0.043 |
| notes 200×260 | 22.6% | 53 | 0.000 |
| receipt 200×260 | 22.6% | 34 | 0.000 |
| everything smaller | ≤14.4% | 12 – 42 | **0.000** |

Blur agrees independently: recall 0.915 → 0.723 → 0.213 → 0.106 → 0.000
at kernel 0/3/5/7/9, crossing zero exactly where `row_transitions`
crosses out of the thirties.

So the two edges, both measured:

```python
CORPUS_STRUCTURE_CEILING = 26.0   # worst real non-page in 9,199 frames
READABLE_PAGE_FLOOR      = 36.0   # lowest score that still read (0.714)
MIN_ROW_TRANSITIONS = round((CORPUS_STRUCTURE_CEILING + READABLE_PAGE_FLOOR) / 2)
```

**31.** Halfway, because neither edge is soft: at the ceiling there is no
margin against the next keyboard, at the floor none against the last page
that still reads. Five transitions of headroom each way — a **10-wide
window**, not the order of magnitude the old comment claimed.

The derivation lives in `detect.py`, not here, for the reason
`max_misses` became `frames_in(MAX_ABSENCE_S)`: a bare number that
happens to work is what produced this bug.

### What it costs

Nothing that was working. Everything the new threshold rejects and the
old one admitted returned `word_recall` ≤ 0.106. The cut falls between a
page at 22.6% of frame (recall 0.043) and one at 38.1% (recall 0.714),
and between blur kernel 5 (0.213) and 7 (0.106).

### What it is pinned to

**360×640, and only that.** Both edges are functions of crop pixel count.
The reality check's recommendation — bursty 504×896 stills rather than a
higher stream — moves the readable floor *down* and the structure ceiling
*up*, and the window could close entirely. Re-derive against
`tests/test_document_detect_corpus.py`; do not scale.

---

## 4. What this does and does not buy

**It does not make Document Memory work.** No page has ever been
photographed by these glasses. A gate that is now correct on 9,199 real
negatives is still a gate that has never once been shown a positive it
was built for. The acceptance requirement is unchanged and unmet:
someone has to wear the glasses and read a page.

**What it does buy, precisely:**

| | before | after |
|---|---|---|
| frames detected as documents, 9,199 real frames | 6 | **0** |
| of those, false positives | 6 (100%) | — |
| venetian blind, square on | admitted at exactly 8.0 | rejected |
| backlit keyboard | admitted at 19–26 | rejected |

**And it buys one thing more valuable than the number:** the gate's own
docstring no longer asserts a margin that does not exist. Anyone reading
`detect.py` now sees that `row_transitions` cannot tell text from
structure at this resolution, that the threshold rests on a 10-wide
window, and what invalidates it.

**The honest limit on the ceiling.** 26 is one keyboard, in one capture,
in one apartment. p99 over 1,395 real quads is 5, so the tail is thin —
but a differently-lit keyboard, a radiator grille, a bookshelf edge-on or
a perforated ceiling tile could all exceed it, and none of those is in
this corpus. The regression test is what makes the next such surface
visible rather than silent.

---

## 5. The guard

`tests/test_document_detect_corpus.py`, **24 tests, ~11 s**, marked
PHYSICAL, NOT SYNTHETIC.

The specific hole it closes: `test_document_detect.py` and
`test_document_memory_hostile.py` draw their negatives from **the same
renderer as their positives**, so a threshold tuned on that renderer
passed both, and no possible addition to those files could have caught
this. Every negative in the new file is a frame the glasses recorded.

1. **The six firings, by name.** Each of the eight offending quads is
   pinned with the corners `detect_page` itself produced and the value it
   measured (blind 8.0, keyboard 19/25/26/19/21), asserted below the gate
   and the frame asserted undetected.
2. **The whole corpus.** All 9,199 frames through `detect_page`; the only
   correct count is zero. Not sampled — at stride 20 the *old* detector
   fired on nothing, because six in 9,199 is not something a sample
   finds.
3. **The overlap itself**, so the next person to touch the threshold sees
   it instead of rediscovering it: every real screen scores ≤ 2 as
   written and ≤ 8 inverted, and one assertion pins that the hardest real
   negative still out-scores every real line of text. If that order ever
   flips, the derivation is standing on evidence that changed.

Corners are hard-coded rather than re-detected, so the measurement
survives a gate change that stops the detector proposing them. The corpus
is machine-local (`data/` is gitignored), so these skip where it is
absent — a real limit, and the reason the numbers are also written down
here.

### Two existing tests were written to the margin that never existed

Both were changed, not deleted, and both say why in their docstring:

- `test_real_text_still_clears_the_glyph_gate_by_a_wide_margin` asserted
  `row_transitions > MIN_ROW_TRANSITIONS * 3`. A full-frame rendered page
  measures **72**, so the threefold margin was already false at 8×3=24
  and merely survived by luck. Now
  `test_real_text_still_clears_the_readable_floor`, asserting against the
  edge the threshold was actually derived from.
- `test_sharpness_collapses_on_a_blurred_frame` blurred at kernel 15,
  which now scores 14 and is correctly refused (recall 0.000). Moved to
  kernel 5, inside the detectable band, so it measures sharpness rather
  than the glyph gate.

---

## 6. Provenance

Every number measured on this host on 2026-08-26 against
`data/captures/`. Nothing persisted to `data/`; no frame copied into the
repo. The sweeps reuse `scripts/capture_corpus_benchmark.py`'s
`iter_capture_frames` and `scripts/document_memory_benchmark.py`'s
`word_recall`. No new dependency. Nothing touched outside
`tower/document_memory/detect.py` and three test files — not the OCR
seam, the store, retention, `tower/results/`, `tower/routes/`,
`tower/detection.py`, World Builder, Object Memory, Scene Understanding
or any iOS file.

| Measurement | How |
|---|---|
| real negative distribution | non-mutating mirror of `detect_page`'s gate chain, all 1,395 quads in 9,199 frames |
| surface identification | detected quad outlined on the source frame and on its warp, inspected |
| real screen positives | 12 quads read off a coordinate grid and eye-verified, plus 1 the detector proposed itself; both polarities |
| size ladder | renderer at six placements in 360×640, JPEG q70, measured at ground-truth corners |
| recall ladder | `EasyOcrRecogniser(gpu=True)` + `word_recall` on the same crops |
| blur ladder | Gaussian kernel 0–15 on one full-frame page, same two metrics |
| false positives after the change | full-corpus sweep, asserted in the suite |

Full suite on the tree this is committed to: **1468 passed, 30 skipped,
0 failed** (242 s), up from 1444/30/0 — the 24 new tests are the corpus
guard.
